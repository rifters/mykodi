# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file debrid.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
import time

import traceback
import requests

import xbmc
from . import control
from . import log_utils
from . import source_utils
from .crewruntime import c


# Constants for pack resolution
DEBRID_API_TIMEOUT = 10  # seconds
PACK_PROCESS_DELAY = 2   # seconds - wait for torrent processing
STATUS_CHECK_DELAY = 1   # seconds - wait before status check

# Module-level RD rate-limit backoff state
# When RD returns 429, we back off for RD_RATE_LIMIT_BACKOFF seconds before retrying
_rd_rate_limited_until = 0.0   # time.time() value; 0 = no active backoff
RD_RATE_LIMIT_BACKOFF = 3      # seconds to wait after confirmed 429 (measured: RD recovers in ~2.2s)
RD_RATE_LIMIT_RETRY_SLEEP = 3  # seconds to sleep before first retry on 429 (avoids second 429)

# Set to True the first time RD returns 451 (DMCA block) in this session.
# Used by errorForSources() to show a more informative failure message.
_rd_451_hit = False


def rd_451_was_hit():
    """Return True if Real-Debrid blocked at least one source (451) this session."""
    return _rd_451_hit

try:
    import resolveurl
    debrid_resolvers = [resolver() for resolver in resolveurl.relevant_resolvers(order_matters=True) if resolver.isUniversal()]
except:
    debrid_resolvers = []


# Global lock to prevent multiple pack resolutions from running simultaneously
_pack_resolution_active = {}  # Dictionary to track active resolutions by hash

# Global progress dialog for resolution attempts (shared across sources)
_resolution_progress_dialog = {'dialog': None}


def create_shared_resolution_dialog(message='Resolving sources...'):
    """Create the shared resolution progress dialog."""
    if _resolution_progress_dialog['dialog'] is None:
        try:
            c.log('[Debrid] Creating shared resolution progress dialog')
            _resolution_progress_dialog['dialog'] = control.progressDialog if control.setting('progress.dialog') == '0' else control.progressDialogBG
            _resolution_progress_dialog['dialog'].create(control.addonInfo('name'), message)
            _resolution_progress_dialog['dialog'].update(0)
        except Exception as e:
            c.log(f'[Debrid] Error creating shared dialog: {e}', 1)
    return _resolution_progress_dialog['dialog']


def update_shared_resolution_dialog(message, percent=0):
    """Update the shared resolution progress dialog if it exists."""
    if _resolution_progress_dialog['dialog'] is not None:
        try:
            _resolution_progress_dialog['dialog'].update(percent, message)
        except Exception as e:
            c.log(f'[Debrid] Error updating shared dialog: {e}', 1)


def close_shared_resolution_dialog():
    """Close the shared resolution progress dialog if it exists."""
    if _resolution_progress_dialog['dialog'] is not None:
        try:
            c.log('[Debrid] Closing shared resolution progress dialog')
            _resolution_progress_dialog['dialog'].close()
        except Exception as e:
            c.log(f'[Debrid] Error closing shared dialog: {e}', 1)
        finally:
            _resolution_progress_dialog['dialog'] = None


def status(torrent=False):
    debrid_check = debrid_resolvers != []
    if debrid_check is True:
        if torrent:
            enabled = control.setting('torrent.enabled')
            if enabled == '' or enabled.lower() == 'true':
                return True
            else:
                return False
    return debrid_check


def _notify_debrid_unreachable(service_name: str) -> None:
    """Show a once-per-session toast when a debrid service can't be reached."""
    prop = 'thecrew.debrid_unreachable_notified'
    if not control.window.getProperty(prop):
        control.window.setProperty(prop, 'true')
        c.log(f'[Debrid] {service_name} unreachable — notifying user', 1)
        c.infoDialog(f'{service_name} could not be reached. Check your internet connection.')
    else:
        c.log(f'[Debrid] {service_name} unreachable (notification already shown)', 1)


def get_debrid_token(service_name, thecrew_setting_name):
    """Get debrid token from resolveurl first, then fall back to The Crew settings."""
    token = None
    source = None

    # Try resolveurl first
    try:
        resolveurl_addon = control.addon('script.module.resolveurl')
        token = resolveurl_addon.getSetting(service_name)
        if token:
            source = 'resolveurl'
            c.log(f'[Debrid Token] Got {service_name} token from resolveurl')
    except Exception as e:
        c.log(f'[Debrid Token] Could not get {service_name} token from resolveurl: {e}')

    # Fall back to The Crew settings
    if not token:
        token = control.setting(thecrew_setting_name)
        if token:
            source = 'thecrew'
            c.log(f'[Debrid Token] Got {service_name} token from The Crew settings')

    return token, source


def resolver(url, debrid, season=None, episode=None):
    # Import at function level to avoid namespace issues


    try:
        c.log('[Debrid] ========== RESOLVER CALLED ==========')
        c.log(f'[Debrid] resolver() called: url={url[:60] if url else None}..., debrid={debrid}, season={season}, episode={episode}')

        # Check if this is a magnet link with season/episode (pack source)
        if url.startswith('magnet:') and season is not None and episode is not None:
            c.log('[Debrid] Pack source detected: magnet link with S{season:02d}E{episode:02d}')
            c.log('[Debrid] Starting pack resolution')

            # Check if there's an active persistent overlay (TV Evening/Up Next)
            try:
                from .sources import get_active_overlay
                active_overlay = get_active_overlay()
                c.log(f'[Debrid] Overlay check: active_overlay={active_overlay}, type={type(active_overlay)}')

                if active_overlay and hasattr(active_overlay, 'transition_to_state'):
                    # Use existing overlay - just update message
                    c.log('[Debrid] Using active overlay for resolution progress')
                    active_overlay.transition_to_state('resolving', 'Generating playable link...')
                    progressDialog = active_overlay
                    close_dialog_after = False  # Don't close - it's managed elsewhere
                else:
                    # Check if we already have a global resolution dialog active
                    if _resolution_progress_dialog['dialog'] is not None:
                        c.log('[Debrid] Reusing existing resolution progress dialog')
                        progressDialog = _resolution_progress_dialog['dialog']
                        close_dialog_after = False  # Don't close shared dialog
                        # Update the dialog message for this attempt
                        try:
                            progressDialog.update(0, f'Trying {debrid} for S{season:02d}E{episode:02d}...')
                        except Exception:
                            pass
                    else:
                        # No overlay and no shared dialog - create one
                        if active_overlay:
                            c.log('[Debrid] Overlay exists but missing transition_to_state method')
                        else:
                            c.log('[Debrid] No active overlay detected')
                        c.log('[Debrid] Creating shared progress dialog')
                        progressDialog = control.progressDialog if control.setting('progress.dialog') == '0' else control.progressDialogBG
                        progressDialog.create(control.addonInfo('name'), 'Resolving...')
                        progressDialog.update(0, f'Trying {debrid} for S{season:02d}E{episode:02d}...')
                        _resolution_progress_dialog['dialog'] = progressDialog
                        close_dialog_after = False  # Don't close - let sourcesDirect manage it
            except Exception as e:
                c.log(f'[Debrid] Error checking for active overlay: {e}', 1)
                c.log(f'[Debrid] Traceback: {traceback.format_exc()}')
                # Fallback to creating a dialog
                if _resolution_progress_dialog['dialog'] is not None:
                    progressDialog = _resolution_progress_dialog['dialog']
                    close_dialog_after = False
                else:
                    progressDialog = control.progressDialog if control.setting('progress.dialog') == '0' else control.progressDialogBG
                    progressDialog.create(control.addonInfo('name'), f'Resolving pack for S{season:02d}E{episode:02d}...')
                    progressDialog.update(0)
                    _resolution_progress_dialog['dialog'] = progressDialog
                    close_dialog_after = False

            # Try direct pack resolution for supported debrid services
            # Normalize debrid service name (case-insensitive matching)
            debrid_normalized = debrid.lower().replace(' ', '-')
            if debrid_normalized in ('real-debrid', 'alldebrid', 'premiumize.me'):
                # Map to canonical name for resolve_pack
                canonical_name_map = {
                    'real-debrid': 'Real-Debrid',
                    'alldebrid': 'AllDebrid',
                    'premiumize.me': 'Premiumize.me'
                }
                canonical_name = canonical_name_map.get(debrid_normalized, debrid)
                c.log(f'[Debrid] Normalized "{debrid}" -> "{canonical_name}" for pack resolution')
                pack_url = resolve_pack(url, canonical_name, season, episode, progressDialog)

                # Close dialog only if we created it (not if using overlay)
                if close_dialog_after:
                    try:
                        if progressDialog:
                            progressDialog.close()
                    except Exception:
                        pass

                if pack_url:
                    c.log('[Debrid] Pack resolution successful: Selected correct episode file')
                    c.log('[Debrid] ========== RESOLVER RETURNING (PACK SUCCESS) ==========')
                    return pack_url
                else:
                    # Pack resolution failed — do NOT fall back to resolveurl for season/episode
                    # requests. resolveurl has no episode awareness and will play whatever file
                    # RD last had selected for this torrent (likely the wrong episode).
                    # Returning None lets the sources loop move on to the next source.
                    c.log('[Debrid] Pack resolution failed — skipping resolveurl fallback to avoid wrong episode', 1)
                    c.log('[Debrid] ========== RESOLVER RETURNING (PACK FAILED — NO FALLBACK) ==========')
                    return None

        c.log(f'[Debrid] Calling resolveurl standard resolver for {debrid}')
        debrid_resolver = [resolver for resolver in debrid_resolvers if resolver.name == debrid][0]

        debrid_resolver.login()
        _host, _media_id = debrid_resolver.get_host_and_id(url)

        # Log season/episode info for debugging pack file selection
        if season is not None and episode is not None:
            c.log(f'[Debrid] Resolving with season={season}, episode={episode} for pack file selection')

        # Try to pass season/episode to get_media_url if it supports it
        try:
            # Some resolvers support season/episode parameters for pack file selection
            stream_url = debrid_resolver.get_media_url(_host, _media_id, season=season, episode=episode)
        except TypeError:
            # Fallback if resolver doesn't support season/episode parameters
            stream_url = debrid_resolver.get_media_url(_host, _media_id)
            if season is not None and episode is not None:
                c.log('[Debrid] Note: Resolver does not support season/episode parameters')

        c.log('[Debrid] ========== RESOLVER RETURNING (RESOLVEURL SUCCESS) ==========')
        return stream_url
    except Exception as e:
        if isinstance(e, requests.RequestException):
            _notify_debrid_unreachable(debrid)
        c.log(f'{debrid} Resolve Failure: {e}', 1)
        c.log('[Debrid] ========== RESOLVER RETURNING (EXCEPTION) ==========')
        return None


def resolve_pack(magnet_url, debrid_service, season, episode, progressDialog=None):
    """
    Resolve pack torrent by selecting correct episode file from magnet link.

    Args:
        magnet_url: Magnet link
        debrid_service: Debrid service name ('Real-Debrid', 'AllDebrid', 'Premiumize.me')
        season: Season number
        episode: Episode number
        progressDialog: Optional progress dialog to update during resolution

    Returns:
        str: Direct download URL for correct episode file, or None if failed
    """
    # Extract hash from magnet to use as lock key
    hash_match = re.search(r'btih:([a-fA-F0-9]+)', magnet_url)
    if hash_match:
        torrent_hash = hash_match.group(1).lower()

        # Check if this torrent is already being resolved
        if torrent_hash in _pack_resolution_active:
            c.log('[Pack] Another resolution is already in progress for this torrent, skipping')
            return None

        # Mark this torrent as being resolved
        _pack_resolution_active[torrent_hash] = True

    try:
        c.log(f'[Pack] Resolving with {debrid_service} for S{season:02d}E{episode:02d}')

        result = None
        if debrid_service == 'Real-Debrid':
            c.log('[Pack] Dispatching to resolve_pack_realdebrid()')
            result = resolve_pack_realdebrid(magnet_url, season, episode, progressDialog)
        elif debrid_service == 'AllDebrid':
            c.log('[Pack] Dispatching to resolve_pack_alldebrid()')
            result = resolve_pack_alldebrid(magnet_url, season, episode, progressDialog)
            c.log(f'[Pack] resolve_pack_alldebrid() returned: {result}')
        elif debrid_service == 'Premiumize.me':
            c.log('[Pack] Dispatching to resolve_pack_premiumize()')
            result = resolve_pack_premiumize(magnet_url, season, episode, progressDialog)
        else:
            c.log(f'[Pack] Resolution not implemented for {debrid_service}')

        return result
    except Exception as e:
        c.log(f'[Pack] Resolution error: {e}', 1)
        c.log(f'[Pack] Traceback: {traceback.format_exc()}', 1)
        return None
    finally:
        # Always clear the lock when done
        if hash_match and torrent_hash in _pack_resolution_active:
            del _pack_resolution_active[torrent_hash]
            c.log('[Pack] Released resolution lock')


def _rd_check_429(response, label):
    """Return True if response is a 429 rate-limit. Logs a clear message so it's easy to spot in logs."""
    if response is not None and response.status_code == 429:
        c.log(f'[RD] Rate limited (429) on {label} — backing off, no retry', 1)
        return True
    return False


def _rd_refresh_access_token():
    """
    Refresh the Real-Debrid access token using the stored refresh token and client credentials.
    Writes the new access token back into resolveurl settings so future calls are also fixed.
    Returns new access token string on success, None on failure.
    """
    try:
        resolveurl_addon = control.addon('script.module.resolveurl')
        refresh_token = resolveurl_addon.getSetting('RealDebridResolver_refresh')
        client_id = resolveurl_addon.getSetting('RealDebridResolver_client_id')
        client_secret = resolveurl_addon.getSetting('RealDebridResolver_client_secret')

        if not refresh_token:
            c.log('[RD Token Refresh] No refresh token found in resolveurl — cannot refresh')
            return None

        c.log('[RD Token Refresh] Attempting to refresh access token...')
        token_url = 'https://api.real-debrid.com/oauth/v2/token'
        data = {
            'client_id': client_id or 'X245A4XAIBGVM',
            'client_secret': client_secret or '',
            'code': refresh_token,
            'grant_type': 'http://oauth.net/grant_type/device/1.0',
        }
        response = requests.post(token_url, data=data, timeout=15)
        if response.status_code == 200:
            token_data = response.json()
            new_token = token_data.get('access_token')
            if new_token:
                # Persist back so resolveurl and future calls all use the fresh token
                try:
                    resolveurl_addon.setSetting('RealDebridResolver_token', new_token)
                    c.log('[RD Token Refresh] New access token stored in resolveurl settings')
                except Exception as _se:
                    c.log(f'[RD Token Refresh] Could not persist token to resolveurl: {_se}')
                c.log('[RD Token Refresh] Access token refreshed successfully')
                return new_token
            c.log('[RD Token Refresh] No access_token field in response')
        else:
            c.log(f'[RD Token Refresh] Refresh request failed: {response.status_code}')
    except Exception as _e:
        c.log(f'[RD Token Refresh] Exception: {_e}')
    return None


def resolve_pack_realdebrid(magnet_url, season, episode, progressDialog=None):
    """Resolve pack with Real-Debrid API."""
    c.log(f'[RD Pack] Starting resolution for S{season:02d}E{episode:02d}')
    try:
        # Get RD API token from resolveurl or settings
        if progressDialog:
            try:
                progressDialog.update(10, 'Getting Real-Debrid token...')
            except Exception:
                pass
        rd_token, token_source = get_debrid_token('RealDebridResolver_token', 'realdebridtoken')
        if not rd_token:
            c.log('[RD Pack] No Real-Debrid token found in resolveurl or The Crew settings', 1)
            return None
        c.log(f'[RD Pack] Token found from {token_source}')

        base_url = 'https://api.real-debrid.com/rest/1.0'
        headers = {'Authorization': f'Bearer {rd_token}'}

        # Note: RD's instantAvailability endpoint no longer reliably returns cached status,
        # so we skip the pre-check entirely and go straight to adding the magnet.

        # Add magnet to RD
        c.log('[RD Pack] Adding magnet to Real-Debrid')
        add_url = f'{base_url}/torrents/addMagnet'
        add_data = {'magnet': magnet_url}

        # Honour any active rate-limit backoff from a previous 429
        global _rd_rate_limited_until
        if time.time() < _rd_rate_limited_until:
            remaining = _rd_rate_limited_until - time.time()
            c.log(f'[RD Pack] Rate-limit backoff active — waiting {remaining:.1f}s before retrying', 1)
            time.sleep(remaining)

        add_response = requests.post(add_url, data=add_data, headers=headers, timeout=DEBRID_API_TIMEOUT)

        if add_response.status_code == 451:
            # DMCA-blocked hash — RD returns 451 and then aggressively rate-limits the next call.
            # Brief sleep gives RD's limiter time to reset before we move to the next source.
            c.log('[RD Pack] Hash blocked (451 — DMCA/legal) — sleeping 1s to avoid triggering 429 on next source', 1)
            global _rd_451_hit
            _rd_451_hit = True
            time.sleep(1)
            return None
        if add_response.status_code == 429:
            c.log(f'[RD Pack] 429 headers: {dict(add_response.headers)}', 1)
            retry_after = add_response.headers.get('Retry-After') or add_response.headers.get('X-RateLimit-Reset') or add_response.headers.get('X-Rate-Limit-Reset')
            c.log(f'[RD Pack] Retry-After/X-RateLimit-Reset value: {retry_after}', 1)
            c.log(f'[RD Pack] Rate limited by Real-Debrid (429) — sleeping {RD_RATE_LIMIT_RETRY_SLEEP}s then retrying once', 1)
            time.sleep(RD_RATE_LIMIT_RETRY_SLEEP)
            add_response = requests.post(add_url, data=add_data, headers=headers, timeout=DEBRID_API_TIMEOUT)
            if add_response.status_code == 429:
                c.log(f'[RD Pack] Second 429 headers: {dict(add_response.headers)}', 1)
                _rd_rate_limited_until = time.time() + RD_RATE_LIMIT_BACKOFF
                c.log(f'[RD Pack] Still rate limited after retry — backing off for {RD_RATE_LIMIT_BACKOFF}s', 1)
                return None
        if add_response.status_code == 401:
            c.log('[RD Pack] Add magnet returned 401 (token expired) — attempting token refresh and retry')
            new_token = _rd_refresh_access_token()
            if new_token:
                rd_token = new_token
                headers = {'Authorization': f'Bearer {rd_token}'}
                add_response = requests.post(add_url, data=add_data, headers=headers, timeout=DEBRID_API_TIMEOUT)
                c.log(f'[RD Pack] Retry after token refresh: {add_response.status_code}')
            else:
                c.log('[RD Pack] Token refresh failed — cannot add magnet', 1)
                return None
        if add_response.status_code not in (201, 202):
            c.log(f'[RD Pack] Failed to add magnet: {add_response.status_code}', 1)
            return None
        if add_response.status_code == 202:
            c.log('[RD Pack] Torrent already exists in Real-Debrid account (202)')

        torrent_id = add_response.json().get('id')
        if not torrent_id:
            c.log('[RD Pack] No torrent ID returned', 1)
            return None

        # Wait for torrent to be processed
        if progressDialog:
            try:
                progressDialog.update(40, 'Processing torrent...')
            except Exception:
                pass
        time.sleep(PACK_PROCESS_DELAY)

        # Get torrent info
        if progressDialog:
            try:
                progressDialog.update(60, 'Finding episode file...')
            except Exception:
                pass
        info_url = f'{base_url}/torrents/info/{torrent_id}'
        info_response = requests.get(info_url, headers=headers, timeout=DEBRID_API_TIMEOUT)

        if _rd_check_429(info_response, 'torrents/info'):
            return None
        if info_response.status_code != 200:
            c.log(f'[RD Pack] Failed to get torrent info: {info_response.status_code}', 1)
            return None

        torrent_info = info_response.json()
        files = torrent_info.get('files', [])

        if not files:
            c.log('[RD Pack] No files in torrent', 1)
            return None

        # Filter video files
        video_extensions = source_utils.supported_video_extensions()
        video_files = [f for f in files if any(f['path'].lower().endswith(ext) for ext in video_extensions)]

        if not video_files:
            c.log('[RD Pack] No video files in torrent', 1)
            return None

        c.log(f'[RD Pack] Found {len(video_files)} video files, searching for S{season:02d}E{episode:02d}')

        # Find ALL matching files using seas_ep_filter
        matched_files = []
        for file in video_files:
            if source_utils.seas_ep_filter(season, episode, file['path']):
                matched_files.append(file)
                c.log(f'[RD Pack] Potential match: {file["path"]} ({file.get("bytes", 0) / 1024 / 1024:.1f} MB)')

        if not matched_files:
            c.log('[RD Pack] No matching episode file found', 1)
            return None

        # Filter out samples and proofs
        non_sample_files = [f for f in matched_files if not any(x in f['path'].lower() for x in ['sample', 'proof', '-trailer'])]
        if non_sample_files:
            matched_files = non_sample_files
        else:
            c.log('[RD Pack] Warning: All matches look like samples!')

        # Choose the largest file (most likely to be the full episode)
        matched_file = max(matched_files, key=lambda f: f.get('bytes', 0))
        c.log(f'[RD Pack] Selected best match: {matched_file["path"]} ({matched_file.get("bytes", 0) / 1024 / 1024:.1f} MB)')
        if progressDialog:
            try:
                progressDialog.update(80, 'Generating playable link...')
            except Exception:
                pass

        # Final validation that we have a matched file
        if not matched_file:
            c.log(f'[RD Pack] No file matched S{season:02d}E{episode:02d} pattern', 1)
            return None

        # Select the file (retry up to 3 times — transient RD API timeouts are common)
        file_id = str(matched_file['id'])
        select_url = f'{base_url}/torrents/selectFiles/{torrent_id}'
        select_data = {'files': file_id}
        select_response = None
        for _attempt in range(3):
            try:
                select_response = requests.post(select_url, data=select_data, headers=headers, timeout=DEBRID_API_TIMEOUT)
                if _rd_check_429(select_response, 'selectFiles'):
                    return None
                break
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as _exc:
                if _attempt < 2:
                    c.log(f'[RD Pack] selectFiles timeout (attempt {_attempt + 1}/3), retrying...')
                    time.sleep(2)
                else:
                    c.log(f'[RD Pack] selectFiles failed after 3 attempts: {_exc}', 1)
                    raise

        if select_response is None or select_response.status_code not in (202, 204):
            status_code = select_response.status_code if select_response is not None else 'N/A'
            c.log(f'[RD Pack] Failed to select file: {status_code}', 1)
            return None
        if select_response.status_code == 202:
            c.log('[RD Pack] selectFiles returned 202 - files already selected, continuing')

        # Check if torrent is already cached (downloaded) or needs downloading
        c.log('[RD Pack] Checking torrent status...')
        time.sleep(STATUS_CHECK_DELAY)

        info_response = requests.get(info_url, headers=headers, timeout=DEBRID_API_TIMEOUT)
        if _rd_check_429(info_response, 'torrents/info (status check)'):
            return None
        torrent_info = info_response.json()
        status = torrent_info.get('status')
        progress = torrent_info.get('progress', 0)

        c.log(f'[RD Pack] Status: {status}, progress: {progress}%')

        # If torrent is not cached, return None to let sources loop try next source
        # DO NOT fall back to resolveurl here - that would add the magnet again!
        # The sources loop will automatically try the next available source.
        if status in ('downloading', 'queued', 'magnet_conversion', 'waiting_files_selection'):
            c.log(f'WARNING: Pack not cached (status: {status}) - skipping to try next source')
            c.log(f'WARNING: Note: Torrent is queued but will take time. Trying alternative sources.')
            c.log('[Pack] Released resolution lock')
            return None

        if status == 'error':
            c.log('[RD Pack] Real-Debrid reported an error status', 1)
            return None

        # Torrent is cached (downloaded), get links
        c.log(f'[RD Pack] Torrent is cached (status: {status}), getting links...')

        links = torrent_info.get('links', [])
        if not links:
            c.log('[RD Pack] No download links available', 1)
            return None

        # Map our matched file to the correct link index.
        # RD's links[] corresponds 1:1 with the SELECTED files in the order
        # they appear in the files array. For fully-cached packs all episodes
        # may be selected, so links[0] is NOT necessarily our episode — find
        # the position of our specific file among the selected files.
        updated_files = torrent_info.get('files', [])
        selected_files_ordered = [f for f in updated_files if f.get('selected') == 1]
        link_index = 0  # safe default
        for i, f in enumerate(selected_files_ordered):
            if f['id'] == matched_file['id']:
                link_index = i
                c.log(f'[RD Pack] S{season:02d}E{episode:02d} is at link index {i} of {len(links)} links '
                      f'({len(selected_files_ordered)} selected files)')
                break
        else:
            c.log(f'[RD Pack] WARNING: matched file id={matched_file["id"]} not found in selected list — using index 0')

        if link_index >= len(links):
            c.log(f'[RD Pack] Link index {link_index} out of range ({len(links)} links)', 1)
            return None

        unrestrict_url = f'{base_url}/unrestrict/link'
        unrestrict_response = requests.post(unrestrict_url, data={'link': links[link_index]},
                                            headers=headers, timeout=DEBRID_API_TIMEOUT)

        if _rd_check_429(unrestrict_response, 'unrestrict/link'):
            return None
        if unrestrict_response.status_code != 200:
            c.log(f'[RD Pack] Failed to unrestrict link: {unrestrict_response.status_code}', 1)
            return None

        unrestrict_info = unrestrict_response.json()
        download_url = unrestrict_info.get('download')
        resolved_filename = unrestrict_info.get('filename', '')
        if download_url:
            # Final sanity check: confirm the resolved file actually matches our episode
            if resolved_filename and not source_utils.seas_ep_filter(season, episode, resolved_filename):
                c.log(f'[RD Pack] MISMATCH: resolved file "{resolved_filename}" does not match '
                      f'S{season:02d}E{episode:02d} — aborting to avoid wrong episode', 1)
                return None
            c.log(f'[RD Pack] Successfully resolved: {resolved_filename}')
            return download_url

        return None

    except requests.RequestException as e:
        c.log(f'[RD Pack] Network error: {e}', 1)
        _notify_debrid_unreachable('Real-Debrid')
        return None
    except Exception as e:
        c.log(f'[RD Pack] Exception: {e}', 1)
        c.log(f'[RD Pack] Traceback: {traceback.format_exc()}', 1)
        return None


def resolve_pack_alldebrid(magnet_url, season, episode, progressDialog=None):
    """Resolve pack with AllDebrid API (v4.1)."""
    c.log(f'[AD Pack] Function called for S{season:02d}E{episode:02d}')
    try:
        if progressDialog:
            try:
                progressDialog.update(10, 'Getting AllDebrid token...')
            except Exception:
                pass
        ad_token, token_source = get_debrid_token('AllDebridResolver_token', 'alldebridtoken')
        if not ad_token:
            c.log('[AD Pack] No AllDebrid token found in resolveurl or The Crew settings', 1)
            return None

        headers = {'Authorization': f'Bearer {ad_token}'}
        base_v4 = 'https://api.alldebrid.com/v4'
        base_v41 = 'https://api.alldebrid.com/v4.1'

        # Pre-check: instant availability (GET /v4/magnet/instant)
        btih_match = re.search(r'btih:([0-9a-fA-F]{32,40})', magnet_url, re.IGNORECASE)
        if btih_match:
            btih_hash = btih_match.group(1).lower()
            if progressDialog:
                try:
                    progressDialog.update(15, 'Checking AllDebrid instant availability...')
                except Exception:
                    pass
            try:
                instant_response = requests.get(
                    f'{base_v4}/magnet/instant',
                    headers=headers,
                    params={'magnets[]': btih_hash},
                    timeout=DEBRID_API_TIMEOUT
                )
                if instant_response.status_code == 200:
                    instant_data = instant_response.json()
                    c.log(f'[AD Pack] Instant check response: {instant_data}')
                    if instant_data.get('status') == 'success':
                        magnets_instant = instant_data.get('data', {}).get('magnets', [])
                        if magnets_instant:
                            mag = magnets_instant[0]
                            if not mag.get('instant', False):
                                c.log('[AD Pack] Not in AllDebrid cache — skipping upload')
                                return None
                            c.log('[AD Pack] Confirmed instant/cached — proceeding with upload')
                        else:
                            c.log('[AD Pack] Instant check returned no magnets data — proceeding anyway')
                    else:
                        c.log(f'[AD Pack] Instant check non-success — proceeding anyway: {instant_data}')
                else:
                    c.log(f'[AD Pack] Instant check HTTP {instant_response.status_code} — proceeding anyway')
            except Exception as instant_ex:
                c.log(f'[AD Pack] Instant check exception — proceeding anyway: {instant_ex}')
        else:
            c.log('[AD Pack] Could not extract hash for instant check — proceeding with upload')

        # Step 1: Upload magnet
        c.log(f'[AD Pack] Adding magnet to AllDebrid (token from {token_source})')
        if progressDialog:
            try:
                progressDialog.update(20, 'Adding magnet to AllDebrid...')
            except Exception:
                pass
        add_response = requests.post(
            f'{base_v4}/magnet/upload',
            headers=headers,
            data={'magnets[]': magnet_url},
            timeout=DEBRID_API_TIMEOUT
        )

        if add_response.status_code != 200:
            c.log(f'[AD Pack] Failed to add magnet: {add_response.status_code}', 1)
            return None

        add_data = add_response.json()
        if add_data.get('status') != 'success':
            c.log(f'[AD Pack] Upload failed: {add_data}', 1)
            return None

        magnet_obj = add_data['data']['magnets'][0]
        if 'error' in magnet_obj:
            c.log(f'[AD Pack] Magnet upload error: {magnet_obj["error"]}', 1)
            return None
        magnet_id = magnet_obj['id']

        # Step 2: Check status via v4.1 endpoint (POST)
        c.log('[AD Pack] Checking magnet status...')
        if progressDialog:
            try:
                progressDialog.update(40, 'Checking if cached...')
            except Exception:
                pass
        time.sleep(STATUS_CHECK_DELAY)

        status_response = requests.post(
            f'{base_v41}/magnet/status',
            headers=headers,
            data={'id': magnet_id},
            timeout=DEBRID_API_TIMEOUT
        )

        if status_response.status_code != 200:
            c.log(f'[AD Pack] Failed to get status: {status_response.status_code}', 1)
            return None

        status_data = status_response.json()
        if status_data.get('status') != 'success':
            c.log(f'[AD Pack] Status check failed: {status_data}', 1)
            return None

        magnets = status_data.get('data', {}).get('magnets', [])
        if not magnets:
            c.log('[AD Pack] No magnets in status', 1)
            return None

        # v4.1 returns magnets as a dict keyed by magnet ID, not a list
        if isinstance(magnets, dict):
            magnet_info = magnets.get(str(magnet_id)) or next(iter(magnets.values()), None)
        else:
            magnet_info = magnets[0] if magnets else None

        if not magnet_info:
            c.log('[AD Pack] Could not extract magnet info from status response', 1)
            return None
        magnet_status = magnet_info.get('status')
        c.log(f'[AD Pack] Magnet status: {magnet_status}')

        if magnet_status != 'Ready':
            c.log(f'WARNING: Pack not ready (status: {magnet_status}) - skipping to try next source')
            return None

        # Step 3: Get file list via dedicated /magnet/files endpoint (v4.1 status no longer returns links)
        c.log(f'[AD Pack] Torrent is cached, fetching file list...')
        if progressDialog:
            try:
                progressDialog.update(55, 'Getting file list...')
            except Exception:
                pass

        files_response = requests.post(
            f'{base_v4}/magnet/files',
            headers=headers,
            data={'id[]': magnet_id},
            timeout=DEBRID_API_TIMEOUT
        )

        if files_response.status_code != 200:
            c.log(f'[AD Pack] Failed to get files: {files_response.status_code}', 1)
            return None

        files_data = files_response.json()
        if files_data.get('status') != 'success':
            c.log(f'[AD Pack] Files fetch failed: {files_data}', 1)
            return None

        files_tree = files_data.get('data', {}).get('magnets', [{}])[0].get('files', [])

        # Flatten the nested folder tree into a flat list of file dicts
        def _flatten(nodes):
            result = []
            for node in nodes:
                if 'e' in node:
                    result.extend(_flatten(node['e']))
                elif 'l' in node:
                    result.append({'filename': node['n'], 'link': node['l'], 'size': node.get('s', 0)})
            return result

        all_files = _flatten(files_tree)

        # Filter video files
        video_extensions = source_utils.supported_video_extensions()
        video_files = [f for f in all_files if any(f['filename'].lower().endswith(ext) for ext in video_extensions)]

        if not video_files:
            c.log('[AD Pack] No video files found', 1)
            return None

        c.log(f'[AD Pack] Found {len(video_files)} video files, searching for S{season:02d}E{episode:02d}')
        if progressDialog:
            try:
                progressDialog.update(60, 'Finding episode file...')
            except Exception:
                pass

        matched_files = []
        for file in video_files:
            if source_utils.seas_ep_filter(season, episode, file['filename']):
                matched_files.append(file)
                c.log(f'[AD Pack] Potential match: {file["filename"]} ({file.get("size", 0) / 1024 / 1024:.1f} MB)')

        if not matched_files:
            c.log('[AD Pack] No matching episode file found', 1)
            return None

        non_sample_files = [f for f in matched_files if not any(x in f['filename'].lower() for x in ['sample', 'proof', '-trailer'])]
        if non_sample_files:
            matched_files = non_sample_files
        else:
            c.log('[AD Pack] Warning: All matches look like samples!')

        matched_file = max(matched_files, key=lambda f: f.get('size', 0))
        c.log(f'[AD Pack] Selected best match: {matched_file["filename"]} ({matched_file.get("size", 0) / 1024 / 1024:.1f} MB)')
        if progressDialog:
            try:
                progressDialog.update(80, 'Generating playable link...')
            except Exception:
                pass

        # Step 4: Unrestrict the file link
        unrestrict_response = requests.post(
            f'{base_v4}/link/unlock',
            headers=headers,
            data={'link': matched_file['link']},
            timeout=DEBRID_API_TIMEOUT
        )

        if unrestrict_response.status_code != 200:
            c.log(f'[AD Pack] Failed to unrestrict: {unrestrict_response.status_code}', 1)
            return None

        unrestrict_data = unrestrict_response.json()
        if unrestrict_data.get('status') != 'success':
            c.log(f'[AD Pack] Unrestrict failed: {unrestrict_data}', 1)
            return None

        download_url = unrestrict_data['data']['link']
        if download_url:
            c.log('[AD Pack] Successfully resolved pack file')
            return download_url

        return None

    except requests.RequestException as e:
        c.log(f'[AD Pack] Network error: {e}', 1)
        _notify_debrid_unreachable('AllDebrid')
        return None
    except Exception as e:
        c.log(f'[AD Pack] Exception: {e}', 1)
        c.log(f'[AD Pack] Traceback: {traceback.format_exc()}', 1)
        return None


def resolve_pack_premiumize(magnet_url, season, episode, progressDialog=None):
    """Resolve pack with Premiumize API."""
    c.log(f'[PM Pack] Function called for S{season:02d}E{episode:02d}')
    try:
        if progressDialog:
            try:
                progressDialog.update(10, 'Checking Premiumize cache...')
            except Exception:
                pass
        pm_token, token_source = get_debrid_token('PremiumizeMeResolver_token', 'premiumizetoken')
        if not pm_token:
            c.log('[PM Pack] No Premiumize token found in resolveurl or The Crew settings', 1)
            return None

        base_url = 'https://www.premiumize.me/api'
        headers = {'Authorization': f'Bearer {pm_token}'}

        # Step 1: Use cache/check (lightweight, not rate-limited like transfer/create)
        # Extract btih hash from magnet URL
        import re as _re
        btih_match = _re.search(r'btih:([0-9a-fA-F]{32,40})', magnet_url, _re.IGNORECASE)
        if not btih_match:
            c.log('[PM Pack] Could not extract btih hash from magnet URL — skipping', 1)
            return None
        btih_hash = btih_match.group(1).lower()

        c.log(f'[PM Pack] Checking cache via cache/check for hash {btih_hash} (token from {token_source})')
        cache_response = requests.get(
            f'{base_url}/cache/check',
            params={'items[]': btih_hash},
            headers=headers,
            timeout=DEBRID_API_TIMEOUT
        )

        if cache_response.status_code != 200:
            c.log(f'[PM Pack] cache/check failed: {cache_response.status_code} — skipping', 1)
            return None

        cache_data = cache_response.json()
        if cache_data.get('status') != 'success':
            c.log(f'[PM Pack] cache/check error: {cache_data}', 1)
            return None

        is_cached = cache_data.get('response', [False])[0]
        if not is_cached:
            c.log(f'[PM Pack] Not cached (cache/check returned false) — skipping')
            return None

        # Step 2: Cached — call transfer/create once to get folder_id
        c.log(f'[PM Pack] Cache hit! Calling transfer/create to get folder_id...')
        add_response = requests.post(
            f'{base_url}/transfer/create',
            data={'src': magnet_url},
            headers=headers,
            timeout=DEBRID_API_TIMEOUT
        )

        if add_response.status_code == 429:
            c.log(f'[PM Pack] Rate limited by Premiumize (429) — sleeping {RD_RATE_LIMIT_RETRY_SLEEP}s then retrying once', 1)
            time.sleep(RD_RATE_LIMIT_RETRY_SLEEP)
            add_response = requests.post(f'{base_url}/transfer/create', data={'src': magnet_url}, headers=headers, timeout=DEBRID_API_TIMEOUT)
        if add_response.status_code != 200:
            c.log(f'[PM Pack] Failed to create transfer: {add_response.status_code}', 1)
            return None

        add_result = add_response.json()
        if add_result.get('status') != 'success':
            c.log(f'[PM Pack] Create transfer failed: {add_result}', 1)
            return None

        folder_id = add_result.get('folder_id')
        if not folder_id:
            c.log(f'[PM Pack] Cache hit but no folder_id in transfer/create response — skipping', 1)
            return None

        # Content is confirmed cached — now fetch files
        c.log(f'[PM Pack] Got folder_id={folder_id}, fetching files...')
        if progressDialog:
            try:
                progressDialog.update(40, 'Adding magnet to Premiumize...')
            except Exception:
                pass

        list_response = requests.get(
            f'{base_url}/folder/list',
            params={'id': folder_id},
            headers=headers,
            timeout=DEBRID_API_TIMEOUT
        )

        if list_response.status_code != 200:
            c.log(f'[PM Pack] Failed to list folder: {list_response.status_code}', 1)
            return None

        list_data = list_response.json()
        if list_data.get('status') != 'success':
            c.log(f'[PM Pack] List folder failed: {list_data}', 1)
            return None

        content = list_data.get('content', [])

        # Filter video files
        video_extensions = source_utils.supported_video_extensions()
        video_files = [item for item in content if item.get('type') == 'file' and any(item['name'].lower().endswith(ext) for ext in video_extensions)]

        if not video_files:
            c.log('[PM Pack] No video files found', 1)
            return None

        c.log(f'[PM Pack] Found {len(video_files)} video files, searching for S{season:02d}E{episode:02d}')
        if progressDialog:
            try:
                progressDialog.update(60, 'Finding episode file...')
            except Exception:
                pass

        matched_files = []
        for file in video_files:
            if source_utils.seas_ep_filter(season, episode, file['name']):
                matched_files.append(file)
                c.log(f'[PM Pack] Potential match: {file["name"]} ({file.get("size", 0) / 1024 / 1024:.1f} MB)')

        if not matched_files:
            c.log('[PM Pack] No matching episode file found', 1)
            return None

        non_sample_files = [f for f in matched_files if not any(x in f['name'].lower() for x in ['sample', 'proof', '-trailer'])]
        if non_sample_files:
            matched_files = non_sample_files
        else:
            c.log('[PM Pack] Warning: All matches look like samples!')

        matched_file = max(matched_files, key=lambda f: f.get('size', 0))
        c.log(f'[PM Pack] Selected best match: {matched_file["name"]} ({matched_file.get("size", 0) / 1024 / 1024:.1f} MB)')
        if progressDialog:
            try:
                progressDialog.update(80, 'Generating playable link...')
            except Exception:
                pass

        download_url = matched_file.get('link')
        if download_url:
            c.log('[PM Pack] Successfully resolved pack file')
            return download_url

        return None

    except requests.RequestException as e:
        c.log(f'[PM Pack] Network error: {e}', 1)
        _notify_debrid_unreachable('Premiumize')
        return None
    except Exception as e:
        c.log(f'[PM Pack] Exception: {e}', 1)
        c.log(f'[PM Pack] Traceback: {traceback.format_exc()}', 1)
        return None
