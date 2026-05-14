# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file trakt.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
import os
import time
import json
import threading
from datetime import datetime, timedelta
from typing import Dict, Any
from functools import wraps
import traceback

from urllib.parse import urljoin, quote_plus
import sqlite3 as database
from sqlite3 import OperationalError


import requests

from requests.adapters import HTTPAdapter
# from requests.structures import CaseInsensitiveDict
from urllib3.util.retry import Retry

from . import cache
from . import cleandate
from . import client
from . import control
from . import keys
from . import utils
from . import crew_errors
from . import http_client
from .crewruntime import c

trakt_endpoints = {
    'settings': {

    },
    'shows': {

    },
    'movies': {
    }

}

trakt_response_codes = {
    '200': 'Success',
    '201': 'Success - new resource created (POST)',
    '204': 'Success - no content to return (DELETE)',
    '400': 'Bad Request - request couldn\'t be parsed',
    '401': 'Unauthorized - OAuth must be provided',
    '403': 'Forbidden - invalid API key or unapproved app',
    '404': 'Not Found - method exists but no record found',
    '405': 'Method Not Found - method doesn\'t exist',
    '409': 'Conflict - resource already created',
    '412': 'Precondition Failed - use application/json content type',
    '420': 'Account Limit Exceeded - list count, item count, etc',
    '422': 'Unprocessable Entity - validation errors',
    '423': 'Locked User Account - have the user contact support',
    '426': 'VIP Only - user must upgrade to VIP',
    '429': 'Rate Limit Exceeded',
    '500': 'Server Error - please open a support ticket',
    '502': 'Service Unavailable - server overloaded (try again in 30s)',
    '503': 'Service Unavailable - server overloaded (try again in 30s)',
    '504': 'Service Unavailable - server overloaded (try again in 30s)',
    '520': 'Service Unavailable - Cloudflare error',
    '521': 'Service Unavailable - Cloudflare error',
    '522': 'Service Unavailable - Cloudflare error'
}

BASE_URL = 'https://api.trakt.tv/'
CLIENT_ID = keys.trakt_id
CLIENT_SECRET = keys.trakt_secret
REDIRECT_URI = 'urn:ietf:wg:oauth:2.0:oob'
TRAKTUSER = c.get_setting('trakt.user').strip()
# Adopt a helpful User-Agent for Trakt API requests (recommended by docs)
try:
    USER_AGENT = f"{control.addonInfo('id')}/{control.addonInfo('version')}"
except Exception:
    USER_AGENT = 'script.module.thecrew/unknown'

# Use shared HTTP client with connection pooling and retry logic
session = http_client.get_trakt_session()

# Global variable to store last pagination info from Trakt API responses
# Format: {'page': 4, 'limit': 40, 'page_count': 259, 'item_count': 10360}
_last_pagination_info = {}

# Module-level lock: ensures only one thread can execute token_refresh at a time.
# Replaces the window-property spin-wait which had a TOCTOU race — two threads
# could both read 'refreshing_token' as empty before either set it to 'true'.
_trakt_refresh_lock = threading.Lock()


def with_db_connection(return_on_error=None, return_as_dict=True):
    """Decorator to handle database connections automatically (auto-injects dbcon/dbcur and auto-closes)."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            dbcon, dbcur = None, None
            try:
                dbcon = get_connection(control.traktsyncFile, return_as_dict)
                if not dbcon:
                    return return_on_error

                dbcur = get_connection_cursor(dbcon)
                if not dbcur:
                    return return_on_error

                # Inject dbcon and dbcur as first two arguments
                return func(dbcon, dbcur, *args, **kwargs)

            except database.Error as e:
                c.log(f"[Trakt DB] Error in {func.__name__}: {e}")
                return return_on_error
            finally:
                # Always close connections
                if dbcur:
                    try:
                        dbcur.close()
                    except Exception:
                        pass  # Safe to ignore DB cursor close errors
                if dbcon:
                    try:
                        dbcon.close()
                    except Exception:
                        pass  # Safe to ignore DB connection close errors

        return wrapper
    return decorator


def get_trakt(url, post=None, conditional_headers=None):
    """Make a request to the Trakt API with automatic token refresh."""
    try:
        # Check if token needs refresh before making request
        check_and_refresh_token()
        return _handle_the_request(url, post, conditional_headers)
    except requests.RequestException as e:
        c.log(f'get_trakt network error: {e}')
        # Notify user once per session, not during playback
        if not control.window.getProperty('thecrew.trakt_network_notified'):
            try:
                import xbmc as _xbmc
                if not _xbmc.Player().isPlaying():
                    control.window.setProperty('thecrew.trakt_network_notified', 'true')
                    c.infoDialog('Trakt could not be reached. Check your internet connection.', sound=True)
            except Exception:
                pass


def check_and_refresh_token():
    """
    Check if access token is expired or about to expire.

    NOTE: We do NOT proactively refresh tokens anymore (switched to reactive-only approach).
    This function now only validates token expiration for logging purposes.
    Actual refresh happens reactively when Trakt returns 401 in msg_handler().

    This is more robust because:
    - Tokens last their full lifetime (~90 days)
    - Refresh tokens are only used when actually needed (on 401)
    - Reduces risk of burning refresh tokens due to crashes/race conditions
    """
    try:
        # Check if authentication completely failed (tokens were cleared by another thread)
        if control.window.getProperty('thecrew.trakt_auth_failed') == 'true':
            return  # Auth is broken, don't check anything

        if not get_trakt_credentials_info():
            return  # No token configured

        expires_at_str = c.get_setting('trakt.expires_at')
        if not expires_at_str:
            # Fall back to legacy key written by trakt_api.py
            expires_at_str = c.get_setting('trakt.expires')
            if expires_at_str:
                # Migrate to canonical key
                c.set_setting('trakt.expires_at', expires_at_str)
                c.set_setting('trakt.expires', '')
            else:
                # No expiration data - log it but don't refresh proactively
                c.log('[Trakt] No token expiry stored - will use reactive refresh on first 401', 1)
                return

        try:
            expires_at = int(expires_at_str)
            current_time = int(time.time())
            time_remaining = expires_at - current_time

            # Just log the status - NO proactive refresh
            if time_remaining < 0:
                # Token expired - will be refreshed reactively on next API call (401)
                c.log(f'[Trakt] Access token expired {abs(time_remaining)}s ago - will refresh on next API call', 1)
            else:
                hours_remaining = time_remaining / 3600
                days_remaining = hours_remaining / 24
                # Only log once per session
                if not control.window.getProperty('thecrew.trakt_token_logged'):
                    control.window.setProperty('thecrew.trakt_token_logged', 'true')
                    c.log(f'[Trakt] Access token valid for {hours_remaining:.1f}h ({days_remaining:.1f} days)', 1)

        except (ValueError, TypeError) as e:
            c.log(f'[Trakt] Could not parse token expiration: {e}', 1)

    except Exception as e:
        c.log(f'[Trakt] Exception in check_and_refresh_token: {e}')
        # Don't fail - reactive refresh will handle auth issues


def check_trakt_health() -> str:
    """Make a lightweight API probe to determine Trakt connectivity and auth status at startup.

    Sets the thecrew.trakt_status window property to one of:
      'ok'             — credentials valid and Trakt reachable
      'no_credentials' — user has not configured Trakt
      'no_network'     — network unreachable or timeout
      'locked'         — Trakt account is locked (423)
      'auth_dead'      — refresh token invalid / session expired

    Returns the status string.
    """
    if not get_trakt_credentials_info():
        status = 'no_credentials'
        control.window.setProperty('thecrew.trakt_status', status)
        c.log('[Trakt] Health check: no credentials configured')
        return status

    token = c.get_setting('trakt.token')
    headers = {
        'Content-Type': 'application/json',
        'trakt-api-key': CLIENT_ID,
        'trakt-api-version': '2',
        'User-Agent': USER_AGENT,
        'Authorization': f'Bearer {token}',
    }
    url = urljoin(BASE_URL, '/users/settings')

    try:
        response = requests.get(url, headers=headers, timeout=10)
        status_code = str(response.status_code)

        if status_code == '200':
            status = 'ok'
        elif status_code == '423':
            status = 'locked'
        elif status_code in ('401', '403'):
            # Try to refresh — 3-way result: True=ok, None=network, False=auth dead
            refresh_result = token_refresh(headers, url, None)
            if refresh_result is True:
                status = 'ok'
            elif refresh_result is None:
                status = 'no_network'
            else:
                status = 'auth_dead'
                control.window.setProperty('thecrew.trakt_auth_failed', 'true')
        else:
            c.log(f'[Trakt] Health check: unexpected status {status_code}, treating as ok', 1)
            status = 'ok'

    except requests.RequestException as e:
        c.log(f'[Trakt] Health check: network error: {e}', 1)
        status = 'no_network'

    control.window.setProperty('thecrew.trakt_status', status)
    c.log(f'[Trakt] Health check result: {status}')
    return status


def _handle_the_request(url, post, conditional_headers=None):
    """Perform a Trakt API request and handle retries on token refresh."""
    # Normalize URL - if not absolute, use BASE_URL
    if not url.startswith('http'):
        url = urljoin(BASE_URL, url)

    # Use json= where possible so requests sets content-type and encodes safely
    payload = post if post else None

    headers = {
        'Content-Type': 'application/json',
        'trakt-api-key': CLIENT_ID,
        'trakt-api-version': '2',
        'User-Agent': USER_AGENT,
    }

    # OAuth endpoints don't use Authorization header (they use client_id/secret in body)
    is_oauth_endpoint = '/oauth/' in url
    if not is_oauth_endpoint and get_trakt_credentials_info():
        headers['Authorization'] = f'Bearer {c.get_setting("trakt.token")}'

    # Debug logging for OAuth requests
    if is_oauth_endpoint:
        if payload:
            # Don't log secrets, just structure
            pass  # Debug logging removed

    # Add conditional request headers (If-Modified-Since, If-None-Match)
    if conditional_headers:
        headers.update(conditional_headers)

    # Try the request; if token refresh happens, retry once
    retried = False
    while True:
        try:
            if payload is not None:
                response = session.post(url, json=payload, headers=headers, timeout=30)
            else:
                response = session.get(url, headers=headers, timeout=30)
        except requests.RequestException as e:
            c.log(f"[Trakt] Network exception when requesting {url}: {e}")
            raise

        response.encoding = 'utf-8'
        status_code = response.status_code

        # Debug logging for OAuth responses
        if '/oauth/' in url:
            if response.text and len(response.text) < 500:
                pass  # Debug logging removed

        # If not 2xx, let the message handler decide whether a retry is appropriate
        if not status_code or not str(status_code).startswith('2'):
            should_retry = msg_handler(url, response, str(status_code), payload, headers)
            if should_retry and not retried:
                retried = True
                # Update Authorization header if token was rotated in msg_handler/token_refresh
                # But skip for OAuth endpoints
                if not is_oauth_endpoint and get_trakt_credentials_info():
                    headers['Authorization'] = f'Bearer {c.get_setting("trakt.token")}'
                # loop to retry once
                continue
        # Return raw text, headers and status for caller convenience
        return response.text, response.headers, status_code


def msg_handler(url, response, status_code, post, headers) -> bool:
    """Handle non-2xx responses. Return True when caller should retry the request once (e.g., after token refresh)."""
    # Default: do not retry
    if status_code in ['401', '403']:
        # Check if auth already failed (tokens cleared by another thread)
        if control.window.getProperty('thecrew.trakt_auth_failed') == 'true':
            return False  # Don't retry, auth is broken

        # Use a threading.Lock to serialize token refresh across threads.
        # Only one thread can hold the lock; all others block here until it's released.
        with _trakt_refresh_lock:
            # Re-check auth_failed: the thread that just held the lock may have
            # failed and cleared the tokens.
            if control.window.getProperty('thecrew.trakt_auth_failed') == 'true':
                return False

            # Check if the token was already rotated by the thread that just held
            # the lock. If our header is stale, update and retry without refreshing.
            current_token = c.get_setting('trakt.token')
            if current_token and f'Bearer {current_token}' != headers.get('Authorization', ''):
                headers['Authorization'] = f'Bearer {current_token}'
                return True

            # We are the first — do the refresh.
            control.window.setProperty('thecrew.trakt_refreshing_token', 'true')
            try:
                refresh_result = token_refresh(headers, url, post)
                if refresh_result is True:
                    return True
                import xbmc as _xbmc
                is_playing = _xbmc.Player().isPlaying()
                if refresh_result is None:
                    # Network error during token refresh — tokens may still be valid, don't clear them
                    c.log('[Trakt] Token refresh failed due to network error', 1)
                    if not control.window.getProperty('thecrew.trakt_network_notified'):
                        control.window.setProperty('thecrew.trakt_network_notified', 'true')
                        if not is_playing:
                            c.infoDialog('Trakt could not be reached. Check your internet connection.', sound=True)
                        else:
                            c.log('[Trakt] Suppressed network error dialog - playback is active', 1)
                else:
                    # Auth failure — refresh token invalid or expired
                    c.log('[Trakt] Token refresh failed - authentication required', 1)
                    control.window.setProperty('thecrew.trakt_auth_failed', 'true')
                    if not control.window.getProperty('thecrew.trakt_auth_notified'):
                        control.window.setProperty('thecrew.trakt_auth_notified', 'true')
                        if not is_playing:
                            control.okDialog(
                                'Trakt Authorization Required\n\n' +
                                'Your Trakt session has expired. Please re-authorize Trakt in The Crew settings to restore functionality.\n\n' +
                                'Go to: The Crew Add-on Settings > Accounts > Trakt',
                                'Trakt'
                            )
                        else:
                            c.log('[Trakt] Suppressed re-auth dialog - playback is active', 1)
                return False
            finally:
                control.window.clearProperty('thecrew.trakt_refreshing_token')
    elif status_code == '405':
        c.log(f'[Trakt] Method Not Allowed (405) for {url}', 1)
        return False
    elif not response:
        # Log server errors silently — startup health check handles user-facing messaging
        if status_code != '404':
            c.log(f'[Trakt] Server did not respond (status={status_code}): {trakt_response_codes.get(status_code, "No status")}', 1)
        return False
    elif status_code == '423':
        c.log(f'[Trakt] Account locked (423): {trakt_response_codes[status_code]}', 1)
        if control.window.getProperty('thecrew.trakt_status') != 'locked':
            control.window.setProperty('thecrew.trakt_status', 'locked')
            import xbmc as _xbmc
            if not _xbmc.Player().isPlaying():
                control.okDialog(
                    'Your Trakt account is locked.\n\n'
                    'Visit trakt.tv to unlock your account, then re-authorize Trakt in The Crew settings.\n\n'
                    'Go to: The Crew Add-on Settings > Accounts > Trakt',
                    'Trakt Account Locked'
                )
        return False
    elif status_code == '429':
        if 'Retry-After' in headers:
            retry_time = headers['Retry-After']
            c.log(f'[Trakt] Rate limit (429): waiting {retry_time}s before retry')
            control.sleep((int(retry_time) + 1) * 1000)
            return True
        else:
            c.log('[Trakt] Rate limit (429): no Retry-After header, skipping')
        return False
    elif status_code == '422':
        # Validation errors - log the response body for debugging
        try:
            error_details = response.text if response else 'No response body'
            c.log(f"[Trakt] 422 Validation Error - {trakt_response_codes[status_code]}")
            c.log(f"[Trakt] Error details: {error_details}")
            if c.devmode:
                c.infoDialog(f'Trakt validation error: {error_details[:100]}', sound=False, time=3000)
        except Exception:
            c.log(f"[Trakt] {trakt_response_codes[status_code]}")
        return False
    elif status_code in ['404']:
        # 404 is expected for unwatched episodes/movies - don't show notification
        c.log(f"trakt status = {trakt_response_codes[status_code]}")
        return False
    elif status_code:
        c.log(f"trakt status = {trakt_response_codes[status_code]}")
        return False
    else:
        return False



def token_refresh(headers, url, post) -> bool:
    """Refresh the Trakt OAuth access token using the refresh token."""
    try:
        oauth = urljoin(BASE_URL, '/oauth/token')

        refresh_token = c.get_setting('trakt.refresh')
        if not refresh_token:
            c.log('[Trakt] No refresh token available', 1)
            return False

        c.log(f'[Trakt] Starting token refresh... (refresh_token length: {len(refresh_token)})', 1)

        opost = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'redirect_uri': REDIRECT_URI,
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token
        }

        # Use fresh headers for token refresh (don't include Authorization)
        refresh_headers = {
            'Content-Type': 'application/json',
            'trakt-api-key': CLIENT_ID,
            'trakt-api-version': '2',
            'User-Agent': USER_AGENT,
        }

        # Use json= for safer encoding
        raw_response = session.post(oauth, json=opost, headers=refresh_headers, timeout=30)

        # Check HTTP status first
        if raw_response.status_code == 401:
            c.log('[Trakt] Refresh token expired or invalid - user must re-authenticate', 1)
            # Clear invalid tokens
            c.set_setting('trakt.token', '')
            c.set_setting('trakt.refresh', '')
            c.set_setting('trakt.expires_at', '')
            # Mark auth as failed so other waiting threads abort immediately
            control.window.setProperty('thecrew.trakt_auth_failed', 'true')
            return False

        if raw_response.status_code == 400:
            c.log('[Trakt] Invalid refresh token (HTTP 400) - clearing tokens, user must re-authenticate', 1)
            # HTTP 400 typically means malformed/invalid refresh token
            c.set_setting('trakt.token', '')
            c.set_setting('trakt.refresh', '')
            c.set_setting('trakt.expires_at', '')
            # Mark auth as failed so other waiting threads abort immediately
            control.window.setProperty('thecrew.trakt_auth_failed', 'true')
            return False

        if raw_response.status_code != 200:
            c.log(f'[Trakt] Token refresh failed with status {raw_response.status_code}', 1)
            return False

        response = raw_response.json()

        # Check for error in response body
        if response and isinstance(response, dict) and 'error' in response:
            error_msg = response.get('error_description', response['error'])
            c.log(f'[Trakt] Token refresh error: {error_msg}', 1)
            return False

        # Validate required fields
        if not all(k in response for k in ['access_token', 'refresh_token', 'expires_in']):
            c.log('[Trakt] Token refresh response missing required fields', 1)
            return False

        # Save new tokens with expiration timestamp
        token = response['access_token']
        refresh = response['refresh_token']
        expires_in = int(response['expires_in'])  # Trakt now uses 86400 (1 day)

        # Calculate expiration timestamp (current time + expires_in)
        expiration_timestamp = int(time.time()) + expires_in

        # Log the actual expires_in value we got from Trakt
        expires_hours = expires_in / 3600
        expires_days = expires_hours / 24
        c.log(f'[Trakt] Token refresh successful! expires_in={expires_in}s ({expires_hours:.1f}h / {expires_days:.1f}days)', 1)
        c.log(f'[Trakt] New refresh_token length: {len(refresh)}', 1)

        c.set_setting('trakt.token', token)
        c.set_setting('trakt.refresh', refresh)
        c.set_setting('trakt.expires_at', str(expiration_timestamp))

        # Clear any previous auth failed flag since refresh succeeded
        control.window.clearProperty('thecrew.trakt_auth_failed')

        # Update Authorization header for retry if provided
        try:
            headers['Authorization'] = f'Bearer {token}'
        except Exception:
            pass

        return True

    except requests.RequestException as e:
        c.log(f'[Trakt] Network error during token refresh: {e}', 1)
        return None  # Distinct sentinel: network error (token may still be valid)
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        c.log(f'[Trakt] Exception in token_refresh: {e}', 1)
        return False

def getTraktAsJson(url, post=None):
    """Make a request to the Trakt API and return the response as a JSON object/list."""
    try:
        if isinstance(url, str):
            result = get_trakt(url, post) if post else get_trakt(url)
        else:
            return None

        if result:
            # _sort_list_by_header expects (body, headers) - support (body, headers, status) too
            if isinstance(result, tuple) and len(result) >= 2:
                return _sort_list_by_header(result[:2])
            return _sort_list_by_header(result)
        # Handle the case where get_trakt returns None
        c.log('getTraktAsJson Error: get_trakt returned None')
        return None
    except (TypeError, AttributeError, IndexError) as e:
        failure = traceback.format_exc()
        c.log(f'Traceback:: {failure}')
        c.log(f'getTraktAsJson exception: {e}')

def deleteTraktPlayback(playback_id):
    """Delete a playback progress item from Trakt."""
    try:
        if not playback_id:
            c.log('[Trakt] deleteTraktPlayback: No playback_id provided')
            return False

        if not get_trakt_credentials_info():
            c.log('[Trakt] deleteTraktPlayback: Not authenticated')
            return False

        check_and_refresh_token()

        url = urljoin(BASE_URL, f'/sync/playback/{playback_id}')

        headers = {
            'Content-Type': 'application/json',
            'trakt-api-key': CLIENT_ID,
            'trakt-api-version': '2',
            'User-Agent': USER_AGENT,
            'Authorization': f'Bearer {c.get_setting("trakt.token")}'
        }

        response = session.delete(url, headers=headers, timeout=30)
        status_code = response.status_code


        # 204 = Success - no content to return (standard for DELETE)
        # 404 = Item not found (already deleted or never existed)
        if status_code in [204, 404]:
            return True
        else:
            c.log(f'[Trakt] Failed to delete playback {playback_id}: {status_code}')
            if response.text:
                pass  # Could log response text for debugging
            return False

    except requests.RequestException as e:
        c.log(f'[Trakt] Exception in deleteTraktPlayback: {e}')
        c.log(f'[Trakt] Traceback: {traceback.format_exc()}')
        return False


def get_resume_id_from_trakt_api(imdb: str, media_type: str = 'movie') -> int:
    """Fetch playback progress from the Trakt API and return the resume_id (playback id)
    for the entry matching the given IMDB ID.  Returns 0 if not found or not authenticated."""
    try:
        if not get_trakt_credentials_info():
            return 0

        check_and_refresh_token()

        trakt_media = 'movies' if media_type == 'movie' else 'episodes'
        endpoint = f'sync/playback/{trakt_media}?extended=full'
        result = getTraktAsJson(endpoint)

        if not result:
            return 0

        for item in result:
            item_type = item.get('type')
            if not item_type:
                continue
            ids = item.get(item_type, {}).get('ids', {})
            if ids.get('imdb') == imdb:
                resume_id = item.get('id', 0)
                c.log(f'[Trakt] get_resume_id_from_trakt_api: found resume_id={resume_id} for imdb={imdb}')
                return resume_id

        c.log(f'[Trakt] get_resume_id_from_trakt_api: no match found for imdb={imdb}')
        return 0

    except Exception as e:
        c.log(f'[Trakt] Exception in get_resume_id_from_trakt_api: {e}')
        return 0


def _sort_list_by_header(result):
    global _last_pagination_info
    resp, res_headers = result
    # Support empty or invalid responses gracefully
    try:
        # If response is a string, strip whitespace and abort early on empty body
        if isinstance(resp, str):
            s = resp.strip()
            if not s:
                return None
            resp = json.loads(s)
    except json.JSONDecodeError as e:
        c.log(f"[Trakt] Failed to decode JSON from Trakt response: {e}")
        return []  # Return empty list instead of None for consistent handling
    except (TypeError, AttributeError) as e:
        c.log(f"[Trakt] Unexpected error parsing Trakt response: {e}")
        return []  # Return empty list instead of None for consistent handling

    # Extract pagination info from headers (if present)
    if res_headers and isinstance(res_headers, dict):
        try:
            pagination_info = {}
            if 'X-Pagination-Page' in res_headers:
                pagination_info['page'] = int(res_headers['X-Pagination-Page'])
            if 'X-Pagination-Limit' in res_headers:
                pagination_info['limit'] = int(res_headers['X-Pagination-Limit'])
            if 'X-Pagination-Page-Count' in res_headers:
                pagination_info['page_count'] = int(res_headers['X-Pagination-Page-Count'])
            if 'X-Pagination-Item-Count' in res_headers:
                pagination_info['item_count'] = int(res_headers['X-Pagination-Item-Count'])

            # Store pagination info globally if any pagination headers were found
            if pagination_info:
                _last_pagination_info = pagination_info
        except (KeyError, ValueError, TypeError) as e:
            c.log(f"[Trakt] Error extracting pagination headers: {e}")

        # Apply sorting if sort headers present
        if 'X-Sort-By' in res_headers and 'X-Sort-How' in res_headers:
            resp = sort_list(res_headers['X-Sort-By'], res_headers['X-Sort-How'], resp)

    return resp
    #except Exception as e:
        #c.log('getTraktAsJson Error: ' + str(e))
        #pass


def get_pagination_info():
    """Get pagination info from the last Trakt API response."""
    return _last_pagination_info.copy()



def generate_qr_code_local(data, size=280):
    """Generate QR code locally using segno library"""
    try:
        import os
        import tempfile
        from .segno import make as make_qr

        # Create temp directory if it doesn't exist
        temp_dir = os.path.join(tempfile.gettempdir(), 'thecrew_qr')
        os.makedirs(temp_dir, exist_ok=True)

        # Generate unique filename
        qr_filename = os.path.join(temp_dir, 'trakt_auth_qr.png')

        # Generate QR code
        qr = make_qr(data, error='H')  # High error correction

        # Calculate scale to get approximately desired size
        # QR codes are typically 21-177 modules depending on version
        # We want final size to be around 'size' pixels
        scale = max(1, size // 50)  # Reasonable scale factor

        # Save as PNG
        qr.save(qr_filename, scale=scale, border=2, dark='#000000', light='#FFFFFF')

        return qr_filename
    except Exception as e:
        import traceback
        # Fallback to external API
        from urllib.parse import quote
        return f'https://api.qrserver.com/v1/create-qr-code/?data={quote(data)}&size={size}x{size}'


def show_trakt_qr_dialog(verification_url, user_code, qr_path, device_code, interval, expires_in):
    """Show QR code dialog for Trakt authentication with polling"""
    try:
        import xbmcgui
        import threading
        import time


        class TraktQRViewer(xbmcgui.WindowXMLDialog):
            def __init__(self, *args, **kwargs):
                self.header = kwargs.get('header', 'Trakt Authentication')
                self.message = kwargs.get('message', '')
                self.qr_path = kwargs.get('qr_path', '')
                self.device_code = kwargs.get('device_code', '')
                self.interval = kwargs.get('interval', 1)
                self.expires_in = kwargs.get('expires_in', 600)
                self.authenticated = False
                self.access_token = None
                self.polling = True
                self.poll_thread = None

            def onInit(self):
                try:
                    # Control IDs from LogViewer_QR.xml
                    HEADERLABEL = 101
                    TEXT = 502
                    QR_IMAGE = 501
                    CLOSEBUTTON = 503

                    self.getControl(HEADERLABEL).setLabel(self.header)

                    self.getControl(TEXT).setText(self.message)

                    self.getControl(QR_IMAGE).setImage(self.qr_path)

                    # Set focus to close button
                    self.setFocusId(CLOSEBUTTON)


                    # Start polling thread
                    self.poll_thread = threading.Thread(target=self._poll_for_token)
                    self.poll_thread.daemon = True
                    self.poll_thread.start()
                except Exception as e:
                    import traceback

            def _poll_for_token(self):
                """Poll for token in background thread"""
                try:
                    start_time = time.time()
                    while self.polling and (time.time() - start_time) < self.expires_in:
                        time.sleep(self.interval)

                        try:
                            r = getTraktAsJson(
                                '/oauth/device/token',
                                {
                                    'client_id': CLIENT_ID,
                                    'client_secret': CLIENT_SECRET,
                                    'code': self.device_code
                                })

                            if r and isinstance(r, dict) and 'access_token' in r:
                                self.authenticated = True
                                self.access_token = r
                                self.close()
                                return
                        except Exception as e:
                            # Expected during polling (400 error = pending)
                            pass

                    if self.polling:
                        self.close()
                except Exception as e:
                    c.log(f'[Trakt QR] Polling error: {e}')

            def onAction(self, action):
                # Close on back/esc
                if action.getId() in [10, 92]:  # ACTION_NAV_BACK, ACTION_PREVIOUS_MENU
                    self.polling = False
                    self.close()

            def onClick(self, controlId):
                if controlId == 503:  # Close button
                    self.polling = False
                    self.close()

        # Show dialog
        xml_file = 'LogViewer_QR.xml'
        addon_path = c.get_artwork_path()
        skin = c.appearance() or 'thecrew'

        message = (
            f'Scan QR code with your mobile device\n\n'
            f'OR manually visit:\n{verification_url}\n\n'
            f'And enter code: {user_code}\n\n'
            f'Waiting for authentication...'
        )

        dialog = TraktQRViewer(
            xml_file,
            addon_path,
            skin,
            '1080i',
            header='Trakt Authentication',
            message=message,
            qr_path=qr_path,
            device_code=device_code,
            interval=interval,
            expires_in=expires_in
        )
        dialog.doModal()

        # Return result
        authenticated = dialog.authenticated
        access_token = dialog.access_token
        dialog.polling = False
        del dialog

        return authenticated, access_token
    except Exception as e:
        import traceback
        return False, None


def auth_trakt():
    try:
        if get_trakt_credentials_info() is True:
            if c.yesnoDialog(
                f'{c.lang(32511)}[CR]{c.lang(32512)}',
                'Trakt',
            ):
                set_trakt_credentials('', '', '')
            return  # Changed from raise Exception()

        result = getTraktAsJson('/oauth/device/code', {'client_id': CLIENT_ID})
        if not result or not isinstance(result, dict) or 'device_code' not in result:
            c.log(f'[Trakt] Failed to get device code: {result}')
            c.infoDialog('Failed to connect to Trakt', sound=True)
            return

        verification_url = result.get('verification_url', 'https://trakt.tv/activate')
        user_code = result.get('user_code', '')
        expires_in = int(result.get('expires_in', 0))
        device_code = result.get('device_code', '')
        interval = result.get('interval', 1)

        # Generate QR code locally using segno
        activation_url = f'{verification_url}/{user_code}'

        qr_filepath = generate_qr_code_local(activation_url, size=280)

        # Show QR dialog with polling (replaces progress dialog)
        authenticated, r = show_trakt_qr_dialog(
            verification_url,
            user_code,
            qr_filepath,
            device_code,
            interval,
            expires_in
        )

        if not authenticated or not r or not isinstance(r, dict) or 'access_token' not in r:
            c.log('[Trakt] Failed to get access token')
            c.infoDialog('Trakt authorization failed or timed out', sound=True)
            return

        token = r['access_token']
        refresh = r['refresh_token']
        expires_in = int(r.get('expires_in', 86400))  # Default to 1 day if missing

        # Log actual expires_in from Trakt for debugging
        expires_hours = expires_in / 3600
        expires_days = expires_hours / 24
        c.log(f'[Trakt Auth] Got tokens from Trakt: expires_in={expires_in}s ({expires_hours:.1f}h / {expires_days:.1f}days)', 1)
        c.log(f'[Trakt Auth] access_token length: {len(token)}, refresh_token length: {len(refresh)}', 1)

        # Calculate expiration timestamp
        expiration_timestamp = int(time.time()) + expires_in

        headers = {
                    'Content-Type': 'application/json',
                    'trakt-api-key': CLIENT_ID,
                    'trakt-api-version': 2,
                    'Authorization': f'Bearer {token}'
                }

        # Initialize user to empty string in case /users/me fails
        user = ''
        authed = ''

        # Save tokens FIRST so getTraktAsJson can use them
        set_trakt_credentials('', token, refresh, expiration_timestamp)

        # Now get username with the new token
        try:
            result = getTraktAsJson('/users/me')
            if result and isinstance(result, dict) and 'username' in result:
                user = result.get('username')
                authed = '' if user == '' else 'yes'
                # Update username
                c.set_setting('trakt.user', user)
        except Exception as e:
            c.log(f'[Trakt] Failed to get username: {e}')
            # Continue anyway with empty username

        c.infoDialog(f'Trakt authorized{": " + user if user else ""}', sound=True)
    except Exception as e:
        c.log(f'[Trakt] Authorization error: {e}')
        c.log(traceback.format_exc())
        control.openSettings('3.1')



def set_trakt_credentials(value, arg1, arg2, expires_at=None):
    c.set_setting('trakt.user', value)
    c.set_setting('trakt.token', arg1)
    c.set_setting('trakt.refresh', arg2)
    if expires_at:
        c.set_setting('trakt.expires_at', str(expires_at))

def get_trakt_credentials_info() -> bool:
    """Checks if Trakt credentials are set in the crew settings."""
    user = c.get_setting('trakt.user').strip()
    token = c.get_setting('trakt.token')
    refresh = c.get_setting('trakt.refresh')
    return user != '' and token != '' and refresh != ''

#cm - indicators
def getTraktIndicatorsInfo() -> bool:
    """Check if Trakt indicators are enabled in crew settings."""
    indicator_setting = c.get_setting('indicators')
    alternative_indicator_setting = c.get_setting('indicators.alt')
    indicators = alternative_indicator_setting if get_trakt_credentials_info() else indicator_setting
    return indicators == '1'

def use_trakt_bookmarks() -> bool:
    if getTraktIndicatorsInfo():
        setting = c.get_setting('indicators.alt')
        return setting != '32314'
    return False

def get_trakt_addon_movie_info():
    """Check if Trakt is enabled and authorized in the Trakt addon."""
    if not c.addon_exists('script.trakt'):
        return False

    try:
        scrobble = control.addon('script.trakt').getSetting('scrobble_movie') or ''
        exclude_http = control.addon('script.trakt').getSetting('ExcludeHTTP') or ''
        authorization = control.addon('script.trakt').getSetting('authorization') or ''

    except Exception as e:
        c.log(f"Exception in get_trakt_addon_movie_info: {e}")
        return False


    return scrobble == 'true' and exclude_http == 'false' and authorization

def getTraktAddonEpisodeInfo():
    """Check if Trakt is enabled and authorized in the Trakt addon for episodes."""
    try:
        scrobble = control.addon('script.trakt').getSetting('scrobble_episode') == 'true'
        exclude_http = control.addon('script.trakt').getSetting('ExcludeHTTP') == 'false'
        authorization = control.addon('script.trakt').getSetting('authorization') != ''
    except LookupError:
        return False
    return scrobble and exclude_http and authorization

def manager(name: str, imdb: str, tmdb: str, content: str) -> None:
    """Opens a dialog to select a Trakt action to perform."""
    try:
        post = {"movies": [{"ids": {"imdb": imdb}}]} if content == "movie" else {"shows": [{"ids": {"tmdb": tmdb}}]}

        actions = [
            (c.lang(90261), "rate"),  # Rate this
            (c.lang(90262), "remove_rating"),  # Remove Rating
            (c.lang(32516), "/sync/collection"),
            (c.lang(32517), "/sync/collection/remove"),
            (c.lang(32518), "/sync/watchlist"),
            (c.lang(32519), "/sync/watchlist/remove"),
            (c.lang(32520), "/users/me/lists/%s/items"),
        ]

        result = getTraktAsJson("/users/me/lists")
        if not result:
            return
        lists = [(i["name"], i["ids"]["slug"]) for i in result]
        lists = [lists[i // 2] for i in range(len(lists) * 2)]

        for i in range(0, len(lists), 2):
            lists[i] = ((c.lang(32521) % lists[i][0]), f"/users/me/lists/{lists[i][1]}/items")
        for i in range(1, len(lists), 2):
            lists[i] = ((c.lang(32522) % lists[i][0]), f"/users/me/lists/{lists[i][1]}/items/remove")
        actions += lists

        select = control.selectDialog([i[0] for i in actions], c.lang(32515))

        if select == -1:
            return

        # Handle rating actions
        if select == 0:  # Rate this
            # Show rating selector (1-10)
            rating_labels = [f"{i} - {['Terrible', 'Bad', 'Poor', 'Meh', 'Fair', 'Decent', 'Good', 'Great', 'Excellent', 'Masterpiece'][i-1]}" for i in range(1, 11)]
            rating_select = control.selectDialog(rating_labels, c.lang(90264))
            if rating_select == -1:
                return
            rating = rating_select + 1  # Convert index to rating (1-10)

            # Submit rating
            if content == "movie":
                rate_media('movie', imdb, rating, id_type='imdb')
            else:
                rate_media('show', tmdb, rating, id_type='tmdb')
            return

        elif select == 1:  # Remove Rating
            # Remove rating
            if content == "movie":
                remove_rating('movie', imdb, id_type='imdb')
            else:
                remove_rating('show', tmdb, id_type='tmdb')
            return

        # Handle list creation and management (existing code)
        if select == 6:  # Adjusted index (was 4, now 6 due to 2 new items at start)
            t = c.lang(32520)
            k = control.keyboard("", t)
            k.doModal()

            new = k.getText() if k.isConfirmed() else None
            if new is None or new == "":
                return

            result = get_trakt("/users/me/lists", post={"name": new, "privacy": "private"})
            if result and isinstance(result, (list, tuple)):
                result = result[0]

            try:
                data = utils.json_loads_as_str(result)
                if isinstance(data, list) and data:
                    slug = data[0].get("ids", {}).get("slug")
                else:
                    slug = data.get("ids", {}).get("slug")
            except (json.JSONDecodeError, KeyError, AttributeError, TypeError, IndexError):
                c.infoDialog(c.lang(32515), heading=name, sound=True, icon="ERROR")
                return

            result_data = get_trakt(actions[select][1] % slug, post=post)
            if not result_data:
                c.infoDialog(c.lang(32515), heading=name, sound=True, icon="ERROR")
                return
            result = result_data[0]
        else:
            result_data = get_trakt(actions[select][1], post=post)
            if not result_data:
                c.infoDialog(c.lang(32515), heading=name, sound=True, icon="ERROR")
                return
            result = result_data[0]

        icon = control.infoLabel("ListItem.Icon") if result is not None else "ERROR"
        c.infoDialog(c.lang(32515), heading=name, sound=True, icon=icon)
    except Exception as e:
        c.log(f"Exception in trakt manager: {e}")


def my_ratings_menu() -> None:
    """Display a menu to view user's ratings by type."""
    try:
        if not get_trakt_credentials_info():
            c.infoDialog("Trakt account required", sound=True, icon="ERROR")
            return

        menu_items = [
            (c.lang(32001), 'movies'),  # Movies
            (c.lang(32002), 'shows'),   # TV Shows
            (c.lang(32326), 'episodes') # Episodes
        ]

        labels = [item[0] for item in menu_items]
        select = control.selectDialog(labels, c.lang(90263))  # "My Ratings"

        if select == -1:
            return

        media_type = menu_items[select][1]
        display_ratings(media_type)

    except Exception as e:
        c.log(f"Exception in my_ratings_menu: {e}")


def display_ratings(media_type: str) -> None:
    """Display user's ratings for a specific media type."""
    try:
        ratings = get_my_ratings(media_type)

        if not ratings:
            c.infoDialog(f"No {media_type} rated yet", sound=True, icon="INFO")
            return

        # Create display list
        items = []
        for item in ratings:
            rating = item.get('rating', 0)
            rated_at = item.get('rated_at', '')

            if media_type == 'movies':
                movie = item.get('movie', {})
                title = movie.get('title', 'Unknown')
                year = movie.get('year', '')
                label = f"[STAR] {rating}/10 - {title} ({year})"
            elif media_type == 'shows':
                show = item.get('show', {})
                title = show.get('title', 'Unknown')
                year = show.get('year', '')
                label = f"[STAR] {rating}/10 - {title} ({year})"
            elif media_type == 'episodes':
                episode = item.get('episode', {})
                show = item.get('show', {})
                title = show.get('title', 'Unknown')
                season = episode.get('season', 0)
                ep_num = episode.get('number', 0)
                ep_title = episode.get('title', '')
                label = f"[STAR] {rating}/10 - {title} S{season:02d}E{ep_num:02d} - {ep_title}"
            else:
                label = f"[STAR] {rating}/10"

            items.append(label)

        # Show ratings list
        select = control.selectDialog(items, f"{c.lang(90263)} - {media_type.title()}")

        # Could add option to modify rating if user selects an item

    except Exception as e:
        c.log(f"Exception in display_ratings: {e}")
        c.infoDialog("Error loading ratings", sound=True, icon="ERROR")








def slug(title):
    """
    Convert a given title to a slug string.
    """
    if not isinstance(title, str):
        return ''
    title = title.strip().lower()
    title = re.sub('[^a-z0-9_]', '-', title)
    title = re.sub('-{2,}', '-', title)
    return title.rstrip('-')

def sort_list(sort_key, sort_direction, list_data) -> list:
    """
    Sort a list of trakt items based on the given key and direction.
    """
    reverse = sort_direction != 'asc'
    if sort_key == 'rank':
        return sorted(list_data, key=lambda x: x['rank'], reverse=reverse)
    elif sort_key == 'added':
        return sorted(list_data, key=lambda x: x['listed_at'], reverse=reverse)
    elif sort_key == 'title':
        return sorted(list_data, key=lambda x: utils.title_key(x[x['type']].get('title')), reverse=reverse)
    elif sort_key == 'released':
        return sorted(list_data, key=lambda x: released_key(x[x['type']]), reverse=reverse)
    elif sort_key == 'runtime':
        return sorted(list_data, key=lambda x: x[x['type']].get('runtime', 0), reverse=reverse)
    elif sort_key == 'popularity':
        return sorted(list_data, key=lambda x: x[x['type']].get('votes', 0), reverse=reverse)
    elif sort_key == 'percentage':
        return sorted(list_data, key=lambda x: x[x['type']].get('rating', 0), reverse=reverse)
    elif sort_key == 'votes':
        return sorted(list_data, key=lambda x: x[x['type']].get('votes', 0), reverse=reverse)
    else:
        return list_data

def released_key(item):
    """ Return the released or first_aired timestamp from a trakt item. """
    if 'released' in item:
        return item['released'] or '0'
    elif 'first_aired' in item:
        return item['first_aired'] or '0'
    else:
        return '0'

def _convert_and_get_latest_iso(values):
    """Convert a list of ISO timestamp-like values to integers (UTC) and return the latest value."""
    converted = []
    for v in values:
        try:
            if v is None:
                converted.append(0)
            else:
                converted.append(int(cleandate.new_iso_to_utc(v)))
        except ValueError:
            converted.append(0)
    return sorted(converted)[-1] if converted else 0


def getActivity() -> int:
    """Get latest activity timestamp from Trakt API (makes API call)."""
    try:
        i = getTraktAsJson('/sync/last_activities')

        if i and isinstance(i, dict):
            movies = i.get('movies', {})
            episodes = i.get('episodes', {})
            shows = i.get('shows', {})
            seasons = i.get('seasons', {})
            lists = i.get('lists', {})

            activity_values = [
                movies.get('collected_at', 0),
                movies.get('watchlisted_at', 0),
                shows.get('watchlisted_at', 0),
                episodes.get('collected_at', 0),
                episodes.get('watchlisted_at', 0),
                seasons.get('watchlisted_at', 0),
                lists.get('updated_at', 0),
                lists.get('liked_at', 0),
            ]
            activity = _convert_and_get_latest_iso(activity_values)
        else:
            activity = 0

        c.log(f"trakt activity = {activity}")

        return activity
    except ValueError:
        return 0


def getActivity_from_db(activity_type=None) -> int:
    """Get latest activity timestamp from database (server-friendly, no API call)."""
    try:
        activity_values = []

        if activity_type == 'watched':
            # Only watched activities
            activity_values = [
                get_trakt_table_value('movies', 'watched_at') or 0,
                get_trakt_table_value('episodes', 'watched_at') or 0,
            ]

        elif activity_type == 'episodes':
            # Episode-specific activities (watched, paused, collected, watchlisted)
            activity_values = [
                get_trakt_table_value('episodes', 'watched_at') or 0,
                get_trakt_table_value('episodes', 'paused_at') or 0,
                get_trakt_table_value('episodes', 'collected_at') or 0,
                get_trakt_table_value('episodes', 'watchlisted_at') or 0,
            ]

        elif activity_type == 'movies':
            # Movie-specific activities
            activity_values = [
                get_trakt_table_value('movies', 'watched_at') or 0,
                get_trakt_table_value('movies', 'collected_at') or 0,
                get_trakt_table_value('movies', 'watchlisted_at') or 0,
            ]

        elif activity_type == 'collection':
            # Collection-related (what's in user's library)
            activity_values = [
                get_trakt_table_value('movies', 'collected_at') or 0,
                get_trakt_table_value('episodes', 'collected_at') or 0,
            ]

        elif activity_type == 'watchlist':
            # Watchlist-related (what user wants to watch)
            activity_values = [
                get_trakt_table_value('movies', 'watchlisted_at') or 0,
                get_trakt_table_value('shows', 'watchlisted_at') or 0,
                get_trakt_table_value('episodes', 'watchlisted_at') or 0,
                get_trakt_table_value('seasons', 'watchlisted_at') or 0,
            ]

        else:
            # 'all' or None - All activities (backward compatible, excludes lists.liked_at to avoid comment/like spam)
            activity_values = [
                get_trakt_table_value('movies', 'collected_at') or 0,
                get_trakt_table_value('movies', 'watchlisted_at') or 0,
                get_trakt_table_value('movies', 'watched_at') or 0,
                get_trakt_table_value('shows', 'watchlisted_at') or 0,
                get_trakt_table_value('episodes', 'collected_at') or 0,
                get_trakt_table_value('episodes', 'watchlisted_at') or 0,
                get_trakt_table_value('episodes', 'watched_at') or 0,
                get_trakt_table_value('episodes', 'paused_at') or 0,
                get_trakt_table_value('seasons', 'watchlisted_at') or 0,
                get_trakt_table_value('lists', 'updated_at') or 0,
                # NOTE: Intentionally excluding lists.liked_at to avoid invalidation on comment likes
            ]

        activity = _convert_and_get_latest_iso(activity_values)
        return activity
    except (database.Error, KeyError, ValueError, TypeError) as e:
        c.log(f"[Trakt] Error reading {activity_type or 'all'} activity from DB: {e}")
        return 0

# def getWatchedActivity():
#     try:
#         i = getTraktAsJson('/sync/last_activities')
def getWatchedActivity():
    """Return timestamp (ISO) of most recent watched activity from Trakt API (uses conditional ETag fetch, cached 60s)."""
    try:
        # fetcher that performs conditional requests via get_trakt and returns (body, headers, status)
        def fetcher(conditional_headers=None):
            res = get_trakt('/sync/last_activities', conditional_headers=conditional_headers)
            if not res:
                return None
            # get_trakt returns (text, headers, status)
            return res

        i = cache.get_with_etag('trakt.last_activities', fetcher, ttl_seconds=60, namespace='trakt')

        c.log(f"getWatchedActivity returned: {i}")

        if not i or not isinstance(i, dict):
            return 0

        activity_values = [
            i.get('movies', {}).get('watched_at'),
            i.get('episodes', {}).get('watched_at'),
        ]
        activity = _convert_and_get_latest_iso(activity_values)

        return activity

    except (KeyError, TypeError, AttributeError) as e:
        failure = traceback.format_exc()
        c.log(f'Traceback:: {failure}')
        c.log(f'Exception raised in trakt handler: {e}')
        return 0


def getWatchedActivity_from_db():
    """Return timestamp (ISO) of most recent watched activity from database (server-friendly, no API call)."""
    # Simple wrapper - calls getActivity_from_db with 'watched' type
    return getActivity_from_db(activity_type='watched')


def get_last_activity():
    """Return full activity data from Trakt /sync/last_activities endpoint (uses conditional ETag fetch, cached 60s)."""
    try:
        # fetcher that performs conditional requests via get_trakt and returns (body, headers, status)
        def fetcher(conditional_headers=None):
            res = get_trakt('/sync/last_activities', conditional_headers=conditional_headers)
            if not res:
                return None
            # get_trakt returns (text, headers, status)
            return res

        i = cache.get_with_etag('trakt.last_activities', fetcher, ttl_seconds=60, namespace='trakt')

        if c.devmode:
            c.log(f"[get_last_activity] Fetched activity data: {i}")

        if not i or not isinstance(i, dict):
            return None

        return i

    except (KeyError, TypeError, AttributeError) as e:
        failure = traceback.format_exc()
        c.log(f'[get_last_activity] Traceback:: {failure}')
        c.log(f'[get_last_activity] Exception raised: {e}')
        return None
@with_db_connection(return_on_error=[])
def get_queued_indicators_movies(dbcon, dbcur):
    """Get movie indicators from scrobble queue for items marked as watched (>92%)."""
    try:
        if not table_exists('scrobble_queue'):
            return []

        dbcur.execute("SELECT DISTINCT imdb FROM scrobble_queue WHERE media_type='movie' AND progress >= 92 AND action='stop'")
        results = dbcur.fetchall()

        return [row[0] for row in results] if results else []
    except database.Error as e:
        c.log(f"[Trakt] Error fetching queued movie indicators: {e}")
        return []


@with_db_connection(return_on_error={})
def get_queued_indicators_episodes(dbcon, dbcur):
    """Get episode indicators from scrobble queue for items marked as watched (>92%)."""
    try:
        if not table_exists('scrobble_queue'):
            return {}

        dbcur.execute("SELECT imdb, season, episode FROM scrobble_queue WHERE media_type='episode' AND progress >= 92 AND action='stop'")
        results = dbcur.fetchall()

        # Group by show IMDB
        episodes_by_show = {}
        if results:
            for imdb, season, episode in results:
                if imdb not in episodes_by_show:
                    episodes_by_show[imdb] = []
                try:
                    episodes_by_show[imdb].append((int(season), int(episode)))
                except (ValueError, TypeError):
                    continue

        return episodes_by_show
    except database.Error as e:
        c.log(f"[Trakt] Error fetching queued episode indicators: {e}")
        return {}


@with_db_connection(return_on_error=None)
def get_queued_progress(dbcon, dbcur, media_type, imdb, season='', episode=''):
    """Get progress for a specific item from the scrobble queue."""
    if not table_exists('scrobble_queue'):
        return None

    if media_type == 'movie':
        dbcur.execute("SELECT progress FROM scrobble_queue WHERE media_type='movie' AND imdb=?", (imdb,))
    else:  # episode
        dbcur.execute("SELECT progress FROM scrobble_queue WHERE media_type='episode' AND imdb=? AND season=? AND episode=?",
                    (imdb, str(season), str(episode)))

    result = dbcur.fetchone()
    return result[0] if result else None


def cachesyncMovies(timeout=None):
    return cache.get(syncMovies, timeout, TRAKTUSER)

def timeoutsyncMovies():
    timeout = cache.timeout(syncMovies, TRAKTUSER)
    return timeout

def syncMovies(user):
    try:
        if get_trakt_credentials_info() is False:
            c.log('getTraktCredentialsInfo is false')
            return

        # Get watched movies from Trakt
        trakt_watched = []
        if indicators := getTraktAsJson('/users/me/watched/movies'):
            if indicators := [i['movie']['ids'] for i in indicators]:
                trakt_watched = [str(i['imdb']) for i in indicators if 'imdb' in i]

        # Merge with queued indicators (movies marked as watched locally but not yet synced)
        queued_watched = get_queued_indicators_movies()

        # Combine both lists (use set to avoid duplicates)
        if trakt_watched or queued_watched:
            combined = list(set(trakt_watched + queued_watched))
            c.log(f"[Trakt] Movie indicators: {len(trakt_watched)} from Trakt + {len(queued_watched)} queued = {len(combined)} total")
            return combined

        return []
    except (KeyError, TypeError, AttributeError) as e:
        c.log(f'Exception raised in trakt operation: {e}')


def cachesyncTVShows(timeout=None):
    return syncTVShows(0)


def timeoutsyncTVShows():
    timeout = cache.timeout(syncTVShows, TRAKTUSER) or 0
    return timeout

def syncTVShows(user):
    try:
        if not get_trakt_credentials_info():
            c.log('getTraktCredentialsInfo is false')
            return

        # Get watched shows from Trakt
        watched_shows = getTraktAsJson('/users/me/watched/shows?extended=full')
        if not watched_shows:
            c.log('[Trakt] No watched shows returned from API')
            return

        indicators = [(show['show']['ids']['tmdb'], show['show']['aired_episodes'], [(s['number'], e['number']) for s in show['seasons'] for e in s['episodes']]) for show in watched_shows]
        indicators = [(str(tmdb_id), aired_episodes, watched_episodes) for tmdb_id, aired_episodes, watched_episodes in indicators]

        # Merge with queued episode indicators
        queued_episodes = get_queued_indicators_episodes()

        if queued_episodes:
            # Convert indicators to dict for easier merging
            indicators_dict = {tmdb_id: (aired_episodes, set(watched_episodes)) for tmdb_id, aired_episodes, watched_episodes in indicators}

            # For queued episodes, we need to look up TMDB ID from IMDB (requires additional data)
            # For now, add queued episodes to existing shows in indicators
            # Note: This is a simplified approach - full implementation would need IMDB->TMDB mapping
            for imdb, episodes in queued_episodes.items():
                # Find matching show in indicators (would need proper IMDB->TMDB lookup)
                # For now, log that we have queued episodes
                c.log(f"[Trakt] Found {len(episodes)} queued episodes for show {imdb}")

            # Convert back to list format
            indicators = [(tmdb_id, aired, list(watched)) for tmdb_id, (aired, watched) in indicators_dict.items()]

        return indicators
    except (KeyError, TypeError, AttributeError) as e:
        c.log(f"Exception raised: {e}")





def syncSeason(imdb):
    try:
        if get_trakt_credentials_info() is False:
            return
        indicators = getTraktAsJson(f'/shows/{imdb}/progress/watched?specials=false&hidden=false')
        indicators = indicators['seasons']
        indicators = [(i['number'], [x['completed'] for x in i['episodes']]) for i in indicators]
        #indicators = ['%01d' % int(i[0]) for i in indicators if False not in i[1]]
        indicators = [f"{int(i[0]):01d}" for i in indicators if False not in i[1]]
        return indicators
    except (KeyError, TypeError, IndexError, Exception):
        pass  # API failure or data parsing error


def syncTraktStatus(silent=False):
    try:
        cachesyncMovies()
        cachesyncTVShows()
        if not silent:
            c.infoDialog(c.lang(32092))
    except Exception as e:
        c.log(f'[Trakt] Sync failed: {e}')
        c.infoDialog('Trakt sync failed')

##########################################
# Movies
##########################################
def markMovieAsWatched(key, media_id):
    try:
        if key == 'imdb' and not media_id.startswith('tt'):
            media_id = f'tt{media_id}'
        result = get_trakt('/sync/history', {"movies": [{"ids": {key: media_id}}]})
        if result:
            delete_progress_from_database(key, media_id)

        return result[0] if result else None
    except (requests.RequestException, KeyError, TypeError):
        return None

def markMovieAsNotWatched(key, media_id):
    try:
        if key == 'imdb' and not media_id.startswith('tt'):
            media_id = f'tt{media_id}'
        result = get_trakt('/sync/history/remove', {"movies": [{"ids": {key: media_id}}]})
        return result[0] if result else None
    except (requests.RequestException, KeyError, TypeError):
        return None



###########################################
# TV Shows
###########################################
def markTVShowAsNotWatched(key, media_id):
    try:
        result = get_trakt('/sync/history/remove', {"shows": [{"ids": {key: media_id}}]})
        return result[0] if result else None
    except (requests.RequestException, KeyError, TypeError):
        return None

def markTVShowAsWatched(key, media_id):
    try:
        result = get_trakt('/sync/history/', {"shows": [{"ids": {key: media_id}}]})
        return result[0] if result else None
    except (requests.RequestException, KeyError, TypeError):
        return None


#############################################
# Seasons
#############################################
def markSeasonAsWatched(key, media_id, season):
    """Mark all episodes in a season as watched using a single batch API call."""
    c.log(f"[Trakt] Marking season {season} as watched for {key}={media_id}")
    try:
        # Get TMDB ID if we only have IMDB
        tmdb_id = media_id if key == 'tmdb' else None
        if key == 'imdb':
            # Look up TMDB ID from IMDB
            from ..indexers import episodes
            try:
                # Use TMDB's find endpoint to get TMDB ID from IMDB
                import requests
                tmdb_user = c.get_setting('tm.personal_user') or c.get_setting('tm.user') or keys.tmdb_key
                url = f'https://api.themoviedb.org/3/find/{media_id}?api_key={tmdb_user}&external_source=imdb_id'
                r = requests.get(url, timeout=10)
                result = r.json()
                tv_results = result.get('tv_results', [])
                if tv_results:
                    tmdb_id = str(tv_results[0]['id'])
                    c.log(f"[Trakt] Converted IMDB {media_id} to TMDB {tmdb_id}")
            except Exception as e:
                c.log(f"[Trakt] Failed to convert IMDB to TMDB: {e}")

        if not tmdb_id:
            c.log(f"[Trakt] No TMDB ID available, falling back to season-only sync")
            result = getTraktAsJson('/sync/history', {"shows": [{"seasons": [{"number": int(season)}], "ids": {key: media_id}}]})
            return result

        # Get all episodes in this season from TMDB
        tmdb_user = c.get_setting('tm.personal_user') or c.get_setting('tm.user') or keys.tmdb_key
        season_url = f'https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}?api_key={tmdb_user}'

        import requests
        r = requests.get(season_url, timeout=10)
        season_data = r.json()

        episodes_list = season_data.get('episodes', [])
        if not episodes_list:
            c.log(f"[Trakt] No episodes found for season {season}")
            return None

        # Build episodes array for batch sync (all episodes in one call)
        episode_numbers = [{"number": ep['episode_number']} for ep in episodes_list]

        c.log(f"[Trakt] Marking {len(episode_numbers)} episodes in season {season} as watched")

        # Single API call for entire season
        payload = {
            "shows": [{
                "seasons": [{
                    "number": int(season),
                    "episodes": episode_numbers
                }],
                "ids": {key: media_id}
            }]
        }

        result = getTraktAsJson('/sync/history', payload)
        c.log(f"[Trakt] Season {season} marked as watched successfully")
        return result

    except (requests.RequestException, json.JSONDecodeError, KeyError, TypeError) as e:
        c.log(f"[Trakt] Exception in markSeasonAsWatched: {e}")
        c.log(f"[Trakt] Traceback: {traceback.format_exc()}")
        return None

def markSeasonAsNotWatched(key, media_id, season):
    """Mark all episodes in a season as unwatched using a single batch API call."""
    c.log(f"[Trakt] Marking season {season} as unwatched for {key}={media_id}")
    try:
        # Get TMDB ID if we only have IMDB
        tmdb_id = media_id if key == 'tmdb' else None
        if key == 'imdb':
            # Look up TMDB ID from IMDB
            try:
                import requests
                tmdb_user = c.get_setting('tm.personal_user') or c.get_setting('tm.user') or keys.tmdb_key
                url = f'https://api.themoviedb.org/3/find/{media_id}?api_key={tmdb_user}&external_source=imdb_id'
                r = requests.get(url, timeout=10)
                result = r.json()
                tv_results = result.get('tv_results', [])
                if tv_results:
                    tmdb_id = str(tv_results[0]['id'])
                    c.log(f"[Trakt] Converted IMDB {media_id} to TMDB {tmdb_id}")
            except Exception as e:
                c.log(f"[Trakt] Failed to convert IMDB to TMDB: {e}")

        if not tmdb_id:
            c.log(f"[Trakt] No TMDB ID available, falling back to season-only sync")
            result = getTraktAsJson('/sync/history/remove', {"shows": [{"seasons": [{"number": int(season)}], "ids": {key: media_id}}]})
            c.log(f"[Trakt] Season-only unwatched result: {result}")
            return result

        # Get all episodes in this season from TMDB
        tmdb_user = c.get_setting('tm.personal_user') or c.get_setting('tm.user') or keys.tmdb_key
        season_url = f'https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}?api_key={tmdb_user}'

        import requests
        r = requests.get(season_url, timeout=10)
        season_data = r.json()

        episodes_list = season_data.get('episodes', [])
        if not episodes_list:
            c.log(f"[Trakt] No episodes found for season {season}")
            return None

        # Build episodes array for batch sync
        episode_numbers = [{"number": ep['episode_number']} for ep in episodes_list]

        c.log(f"[Trakt] Marking {len(episode_numbers)} episodes in season {season} as unwatched")

        # Single API call for entire season
        payload = {
            "shows": [{
                "seasons": [{
                    "number": int(season),
                    "episodes": episode_numbers
                }],
                "ids": {key: media_id}
            }]
        }

        c.log(f"[Trakt] Unwatched payload: {payload}")
        result = getTraktAsJson('/sync/history/remove', payload)
        c.log(f"[Trakt] Season {season} unwatched result: {result}")
        c.log(f"[Trakt] Season {season} marked as unwatched successfully")
        return result

    except (requests.RequestException, json.JSONDecodeError, KeyError, TypeError) as e:
        c.log(f"[Trakt] Exception in markSeasonAsNotWatched: {e}")
        c.log(f"[Trakt] Traceback: {traceback.format_exc()}")
        return None

#############################################
# Episodes
#############################################
def markEpisodeAsWatched(key, media_id, season, episode):
    season, episode = int('%01d' % int(season)), int('%01d' % int(episode))
    #season, episode = int(f'{season:01d}'), int(f'{episode:01d}')
    result = get_trakt('/sync/history', {"shows": [{"seasons": [{"episodes": [{"number": episode}], "number": season}], "ids": {key: media_id}}]})

    # Clear progress caches to force immediate update in UI
    cache.cache_delete_by_prefix('trakt_next_episodes', table='trakt')
    cache.cache_delete('trakt.last_activities', table='trakt')

    try:
        return result[0] if result else None
    except IndexError:
        # Handle the case when get_trakt returns None
        # For example, you can return a default value or raise an exception
        return None

def markEpisodeAsNotWatched(key, media_id, season, episode):
    season, episode = int('%01d' % int(season)), int('%01d' % int(episode))
    season, episode = int(f'{season:01d}'), int(f'{episode:01d}')
    result = get_trakt('/sync/history/remove', {"shows": [{"seasons": [{"episodes": [{"number": episode}], "number": season}], "ids": {key: media_id}}]})

    # Clear progress caches to force immediate update in UI
    cache.cache_delete_by_prefix('trakt_next_episodes', table='trakt')
    cache.cache_delete('trakt.last_activities', table='trakt')

    try:
        return result[0] if result else None
    except IndexError:
        # Handle the case when get_trakt returns None
        # For example, you can return a default value or raise an exception
        return None






##############################################
# Scrobble
##############################################
@with_db_connection(return_on_error=False)
def queue_scrobble(dbcon, dbcur, media_type, imdb, watched_percent, action, season='', episode=''):
    """Queue a scrobble event instead of making immediate API call."""
    if not imdb.startswith('tt'):
        imdb = 'tt' + imdb

    timestamp = get_now_in_iso()

    # Ensure table exists
    if not table_exists('scrobble_queue'):
        dbcur.execute(sql_dict['sql_create_scrobble_queue'])
        dbcon.commit()

    # Queue the scrobble (replaces existing queue item for same content)
    sql = sql_dict['sql_insert_scrobble_queue']
    dbcur.execute(sql, (media_type, imdb, season, episode, watched_percent, action, timestamp))
    dbcon.commit()

    c.log(f"[Trakt] Queued scrobble: {media_type} {imdb} s{season}e{episode} - {watched_percent}% ({action})")
    return True


@with_db_connection(return_on_error=None)
def process_scrobble_queue(dbcon, dbcur, force=False):
    """Process queued scrobble events and send to Trakt."""
    if not table_exists('scrobble_queue'):
        return

    # Get all queued scrobbles
    dbcur.execute(sql_dict['sql_select_scrobble_queue'])
    queue_items = dbcur.fetchall()

    if not queue_items:
        return

    c.log(f"[Trakt] Processing {len(queue_items)} queued scrobble events")

    for item in queue_items:
        item_id, media_type, imdb, season, episode, progress, action = item

        try:
            # Round progress to 2 decimal places to avoid Trakt validation errors
            progress_rounded = round(float(progress), 2)

            # Make the actual API call
            if media_type == 'movie':
                r = get_trakt(f'/scrobble/{action}', {"movie": {"ids": {"imdb": imdb}}, "progress": progress_rounded})
            else:  # episode
                r = get_trakt(f'/scrobble/{action}', {
                    "show": {"ids": {"imdb": imdb}},
                    "episode": {"season": int(season), "number": int(episode)},
                    "progress": progress_rounded
                })

            # Remove from queue on success
            dbcur.execute(sql_dict['sql_delete_scrobble_item'], (item_id,))
            dbcon.commit()

            # Invalidate last activities cache so UI sees recent activity quickly
            try:
                cache.cache_delete('trakt.last_activities', table='trakt')
            except Exception:
                pass

            c.log(f"[Trakt] Processed scrobble: {media_type} {imdb} - {progress_rounded}% ({action})")

        except Exception as e:
            c.log(f'[Trakt] Failed to process scrobble {item_id}: {e}')
            # Keep in queue to retry later
            continue


def trakt_official_status(media_type):
    """Check whether the official script.trakt addon is installed, enabled, authorized and set to scrobble
    this media type. If it is, The Crew should skip its own scrobble call to avoid duplicate history entries.

    Returns True if The Crew should skip (script.trakt will handle it), False if The Crew should send its own call.
    """
    try:
        import xbmcaddon as _xbmcaddon
        import xbmc as _xbmc
        # Check installed and enabled
        if not _xbmc.getCondVisibility('System.HasAddon(script.trakt)'):
            return False
        trakt_addon = _xbmcaddon.Addon('script.trakt')
        # Check authorized (has a token stored)
        try:
            authorization = trakt_addon.getSetting('authorization')
        except Exception:
            authorization = ''
        if not authorization:
            return False
        # Check it's not set to exclude HTTP sources (which would mean it won't scrobble from us)
        try:
            exclude_http = trakt_addon.getSetting('ExcludeHTTP')
        except Exception:
            exclude_http = ''
        if exclude_http == 'true':
            return False
        # Check it's configured to scrobble this media type
        setting_key = 'scrobble_movie' if media_type in ('movie', 'movies') else 'scrobble_episode'
        try:
            scrobble_setting = trakt_addon.getSetting(setting_key)
        except Exception:
            scrobble_setting = ''
        if scrobble_setting == 'false':
            return False
        # All checks passed — script.trakt is active and will handle this scrobble
        c.log(f'[Trakt] trakt_official_status: script.trakt is active for {media_type}, skipping own scrobble')
        return True
    except Exception as e:
        c.log(f'[Trakt] trakt_official_status check failed: {e}')
        return False


def scrobbleMovie(imdb, watched_percent, action):
    """Scrobble a movie to Trakt. Always sends immediately (direct API call).
    Skips if the official script.trakt addon is active and will handle it instead.
    """
    try:
        if trakt_official_status('movie'):
            return True

        if not imdb.startswith('tt'):
            imdb = 'tt' + imdb

        watched_percent = round(float(watched_percent), 2)
        c.log(f'[Trakt] scrobbleMovie imdb={imdb} percent={watched_percent} action={action}')

        r = get_trakt(f'/scrobble/{action}', {"movie": {"ids": {"imdb": imdb}}, "progress": watched_percent})
        c.log(f'[Trakt] scrobbleMovie response: {r}')
        return r
    except (requests.RequestException, KeyError, ValueError, TypeError) as e:
        c.log(f'[Trakt] Exception in scrobbleMovie: {e}')


def scrobbleEpisode(imdb, season, episode, watched_percent, action):
    """Scrobble an episode to Trakt. Always sends immediately (direct API call).
    Skips if the official script.trakt addon is active and will handle it instead.
    """
    try:
        if trakt_official_status('episode'):
            return True

        if not imdb.startswith('tt'):
            imdb = f'tt{imdb}'

        season, episode = int(season), int(episode)
        watched_percent = round(float(watched_percent), 2)
        c.log(f'[Trakt] scrobbleEpisode imdb={imdb} S{season}E{episode} percent={watched_percent} action={action}')

        r = get_trakt(f'/scrobble/{action}', {"show": {"ids": {"imdb": imdb}}, "episode": {"season": season, "number": episode}, "progress": watched_percent})
        c.log(f'[Trakt] scrobbleEpisode response: {r}')
        return r
    except (requests.RequestException, KeyError, ValueError, TypeError) as e:
        c.log(f'[Trakt] Exception in scrobbleEpisode: {e}')


def get_watched_batch(media_type='shows', last_modified=None, etag=None):
    """Get watched status for all shows/movies in a single batch request using conditional requests."""
    try:
        url = f'/sync/watched/{media_type}'

        # Add conditional request headers if we have cached validators
        conditional_headers = {}
        if last_modified:
            conditional_headers['If-Modified-Since'] = last_modified
        if etag:
            conditional_headers['If-None-Match'] = etag

        # Make request with conditional headers
        if not url.startswith('http'):
            url = urljoin(BASE_URL, url)

        headers = {
            'Content-Type': 'application/json',
            'trakt-api-key': CLIENT_ID,
            'trakt-api-version': '2'
        }

        if get_trakt_credentials_info():
            headers['Authorization'] = f'Bearer {c.get_setting("trakt.token")}'

        if conditional_headers:
            headers.update(conditional_headers)

        response = session.get(url, headers=headers, timeout=30)

        # 304 Not Modified - data hasn't changed
        if response.status_code == 304:
            c.log(f'[Trakt Batch] {media_type} not modified (304), using cached data')
            # Return cached validators
            return None, last_modified, etag

        # Success - return data and new cache validators
        if response.status_code == 200:
            new_last_modified = response.headers.get('Last-Modified')
            new_etag = response.headers.get('ETag')
            data = response.json()
            c.log(f'[Trakt Batch] Fetched {len(data)} {media_type}, Last-Modified: {new_last_modified}, ETag: {new_etag}')
            return data, new_last_modified, new_etag

        # Handle other status codes
        c.log(f'[Trakt Batch] Unexpected status {response.status_code} for {media_type}')
        return None, None, None

    except (requests.RequestException, json.JSONDecodeError, KeyError, TypeError) as e:
        c.log(f'[Trakt Batch] Exception in get_watched_batch: {e}')
        return None, None, None


def sync_watched_batch():
    """Sync all watched content from Trakt using optimized batch operations with conditional requests."""
    try:
        # Get last sync validators from cache (Last-Modified timestamps and ETags)
        shows_last_modified = cache.get(lambda: c.get_setting('trakt.shows.last_modified'), 0)
        shows_etag = cache.get(lambda: c.get_setting('trakt.shows.etag'), 0)
        movies_last_modified = cache.get(lambda: c.get_setting('trakt.movies.last_modified'), 0)
        movies_etag = cache.get(lambda: c.get_setting('trakt.movies.etag'), 0)

        result = {}

        # Fetch shows with conditional request (using both Last-Modified and ETag)
        shows_data, shows_timestamp, shows_new_etag = get_watched_batch('shows', shows_last_modified, shows_etag)
        if shows_data is not None:
            result['shows'] = shows_data
            # Save new cache validators
            if shows_timestamp:
                c.set_setting('trakt.shows.last_modified', shows_timestamp)
            if shows_new_etag:
                c.set_setting('trakt.shows.etag', shows_new_etag)
        else:
            c.log('[Trakt Batch] Shows data unchanged (304), using cached version')

        # Fetch movies with conditional request (using both Last-Modified and ETag)
        movies_data, movies_timestamp, movies_new_etag = get_watched_batch('movies', movies_last_modified, movies_etag)
        if movies_data is not None:
            result['movies'] = movies_data
            # Save new cache validators
            if movies_timestamp:
                c.set_setting('trakt.movies.last_modified', movies_timestamp)
            if movies_new_etag:
                c.set_setting('trakt.movies.etag', movies_new_etag)
        else:
            c.log('[Trakt Batch] Movies data unchanged (304), using cached version')

        return result if result else None

    except (KeyError, TypeError, AttributeError) as e:
        c.log(f'[Trakt Batch] Exception in sync_watched_batch: {e}')
        return None


def get_progress_batch(show_ids):
    """Get watch progress for multiple shows in optimized batches."""
    try:
        if not show_ids:
            return {}

        # Trakt doesn't have a true batch progress endpoint, but we can optimize
        # by requesting only hidden shows to reduce payload
        url = '/users/hidden/progress_watched'
        params = '?type=show&limit=1000'

        response = get_trakt(url + params)

        if not response:
            return {}

        # Process response into dict for quick lookup
        progress_dict = {}
        for item in response:
            show_id = item.get('show', {}).get('ids', {}).get('trakt')
            if show_id:
                progress_dict[show_id] = item

        c.log(f'[Trakt Batch] Fetched progress for {len(progress_dict)} shows')
        return progress_dict

    except (requests.RequestException, json.JSONDecodeError, KeyError, TypeError) as e:
        c.log(f'[Trakt Batch] Exception in get_progress_batch: {e}')
        return {}

def getMovieTranslation(_id, lang, full=False):
    url = f'/movies/{_id}/translations/{lang}'
    try:
        item = getTraktAsJson(url)[0]
        return item if full else item.get('title')
    except (IndexError, KeyError, TypeError, Exception):
        pass  # API failure or parsing error


def getTVShowTranslation(_id, lang, season=None, episode=None, full=False):
    if season and episode:
        url = f'/shows/{_id}/seasons/{season}/episodes/{episode}/translations/{lang}'
    else:
        url = f'/shows/{_id}/translations/{lang}'

    try:
        item = getTraktAsJson(url)[0]
        return item if full else item.get('title')
    except (IndexError, KeyError, TypeError, Exception):
        pass  # API failure or parsing error


def getMovieAliases(_id):
    try:
        return getTraktAsJson(f'/movies/{_id}/aliases')
    except (Exception):
        return []  # API failure


def getTVShowAliases(_id):
    try:
        return getTraktAsJson(f'/shows/{_id}/aliases')
    except (Exception):
        return []  # API failure


def getMovieSummary(_id, full=True):
    try:
        url = f'/movies/{_id}'
        if full:
            url += '?extended=full'
        return getTraktAsJson(url)
    except (Exception):
        return  # API failure


def getTVShowSummary(_id, full=True):
    try:
        url = f'/shows/{_id}'
        if full:
            url += '?extended=full'
        return getTraktAsJson(url)
    except (Exception):
        return  # API failure


def getPeople(_id, content_type, full=True):
    try:
        url = f'/{content_type}/{_id}/people'
        if full:
            url += '?extended=full'
        return getTraktAsJson(url)
    except (Exception):
        return  # API failure


def get_boxoffice():
    """Get weekend box office top 10 movies (updates Monday)"""
    try:
        if not get_trakt_credentials_info():
            return []
        return getTraktAsJson('/movies/boxoffice')
    except (Exception):
        return []  # API failure


def get_recommendations_movies(page=1, limit=20):
    """Get personalized movie recommendations based on watch history"""
    try:
        if not get_trakt_credentials_info():
            return []
        return getTraktAsJson(f'/recommendations/movies?page={page}&limit={limit}')
    except (Exception):
        return []  # API failure


def get_recommendations_shows(page=1, limit=20):
    """Get personalized TV show recommendations"""
    try:
        if not get_trakt_credentials_info():
            return []
        return getTraktAsJson(f'/recommendations/shows?page={page}&limit={limit}')
    except (Exception):
        return []  # API failure


def get_movies_popular(page=1, limit=40):
    """Get popular movies"""
    try:
        return getTraktAsJson(f'/movies/popular?page={page}&limit={limit}')
    except (Exception):
        return []  # API failure


def get_movies_anticipated(page=1, limit=40):
    """Get most anticipated upcoming movies"""
    try:
        return getTraktAsJson(f'/movies/anticipated?page={page}&limit={limit}')
    except (Exception):
        return []  # API failure


def get_movies_played(page=1, limit=40):
    """Get most played movies (by watch count)"""
    try:
        return getTraktAsJson(f'/movies/played?page={page}&limit={limit}')
    except (Exception):
        return []  # API failure


def get_movies_watched(page=1, limit=40):
    """Get most watched movies (by unique users)"""
    try:
        return getTraktAsJson(f'/movies/watched?page={page}&limit={limit}')
    except (Exception):
        return []  # API failure


def get_movies_collected(page=1, limit=40):
    """Get most collected movies (in user libraries)"""
    try:
        return getTraktAsJson(f'/movies/collected?page={page}&limit={limit}')
    except (Exception):
        return []  # API failure


def get_shows_popular(page=1, limit=40):
    """Get popular TV shows"""
    try:
        return getTraktAsJson(f'/shows/popular?page={page}&limit={limit}')
    except (Exception):
        return []  # API failure


def get_shows_anticipated(page=1, limit=40):
    """Get most anticipated upcoming TV shows"""
    try:
        return getTraktAsJson(f'/shows/anticipated?page={page}&limit={limit}')
    except (Exception):
        return []  # API failure


def get_shows_played(page=1, limit=40):
    """Get most played TV shows (by watch count)"""
    try:
        return getTraktAsJson(f'/shows/played?page={page}&limit={limit}')
    except (Exception):
        return []  # API failure


def get_shows_watched(page=1, limit=40):
    """Get most watched TV shows (by unique users)"""
    try:
        return getTraktAsJson(f'/shows/watched?page={page}&limit={limit}')
    except (Exception):
        return []  # API failure


def get_shows_collected(page=1, limit=40):
    """Get most collected TV shows (in user libraries)"""
    try:
        return getTraktAsJson(f'/shows/collected?page={page}&limit={limit}')
    except (Exception):
        return []  # API failure


def get_related_movies(movie_id, limit=10):
    """Get related movies based on Trakt's algorithm (uses Trakt ID, slug, or IMDB ID)."""
    try:
        return getTraktAsJson(f'/movies/{movie_id}/related?limit={limit}')
    except (Exception):
        return []  # API failure


def get_related_shows(show_id, limit=10):
    """Get related TV shows based on Trakt's algorithm (uses Trakt ID, slug, or IMDB ID)."""
    try:
        return getTraktAsJson(f'/shows/{show_id}/related?limit={limit}')
    except (Exception):
        return []  # API failure


def get_calendar_shows(days=7, start_date=None):
    """Get calendar of TV show episodes airing for the authenticated user."""
    try:
        if start_date is None:
            from datetime import datetime
            start_date = datetime.now().strftime('%Y-%m-%d')

        return getTraktAsJson(f'/calendars/my/shows/{start_date}/{days}')
    except (Exception):
        return []  # API failure


def get_calendar_movies(days=30, start_date=None):
    """Get calendar of movie releases for the authenticated user."""
    try:
        if start_date is None:
            from datetime import datetime
            start_date = datetime.now().strftime('%Y-%m-%d')

        return getTraktAsJson(f'/calendars/my/movies/{start_date}/{days}')
    except (Exception):
        return []  # API failure


def SearchAll(title, year, full=True):
    try:
        movies = SearchMovie(title, year, full) or []
        shows = SearchTVShow(title, year, full) or []

        # Ensure both are lists before concatenation
        if not isinstance(movies, list):
            movies = [movies]
        if not isinstance(shows, list):
            shows = [shows]

        return movies + shows
    except (Exception):
        return []  # Search failure


def SearchMovie(title, year, full=True):
    try:
        title = quote_plus(title)
        url = f'/search/movie?query={title}'

        if year:
            url += f'&year={year}'
        if full:
            url += '&extended=full'
        return getTraktAsJson(url)
    except Exception:
        return


def SearchTVShow(title, year, full=True):
    try:
        title = quote_plus(title)
        url = f'/search/show?query={title}'

        if year:
            url += f'&year={year}'
        if full:
            url += '&extended=full'
        return getTraktAsJson(url)
    except Exception:
        return

def IdLookup(content, _type, type_id):
    try:
        r = getTraktAsJson(f'/search/{_type}/{type_id}?type={content}')
        return r[0].get(content, {}).get('ids', []) if r is not None else {}
    except Exception:
        return {}

def getGenre(content, _type, type_id):
    try:
        r = f'/search/{_type}/{type_id}?type={content}&extended=full'
        c.log(f"trakt operation response: {r}")
        r = getTraktAsJson(r)
        return r[0].get(content, {}).get('genres', []) if r is not None else []
    except Exception:
        return []

def getEpisodeRating(imdb, season, episode):
    """Get the rating and votes for a given episode."""

    try:
        if not imdb.startswith('tt'):
            imdb = f'tt{imdb}'
        url = f'/shows/{imdb}/seasons/{season}/episodes/{episode}/ratings'
        r = getTraktAsJson(url)
        if r is None:
            return '0', '0'

        if isinstance(r, dict):
            r1 = r.get('rating', '0')
            r2 = r.get('votes', '0')
        return str(r1), str(r2)
    except crew_errors.GeneralError as e:
        c.log(f'Trakt getEpisodeRating Error: {e}')
        return '0', '0'


####################################################################################################
# Ratings - User ratings and community ratings (added 2026-03-10)
####################################################################################################

def get_my_ratings(media_type='all'):
    """Get user's personal ratings from Trakt."""
    try:
        if not get_trakt_credentials_info():
            c.log('[Trakt] Cannot get ratings - not authenticated')
            return []

        if media_type == 'all':
            url = '/sync/ratings'
        else:
            url = f'/sync/ratings/{media_type}'

        c.log(f'[Trakt] Fetching user ratings: {url}')
        return getTraktAsJson(url) or []
    except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
        c.log(f'[Trakt] Error fetching ratings: {e}')
        return []


def rate_media(media_type, media_id, rating, id_type='tmdb', season=None, episode=None):
    """Submit a rating for a movie, show, season, or episode."""
    try:
        if not get_trakt_credentials_info():
            c.log('[Trakt] Cannot rate - not authenticated')
            c.infoDialog('Please authenticate with Trakt to rate', 'Trakt Not Connected', sound=False)
            return None

        # Validate rating (1-10)
        rating = int(rating)
        if rating < 1 or rating > 10:
            c.log(f'[Trakt] Invalid rating: {rating} (must be 1-10)')
            return None

        # Ensure IMDB IDs have 'tt' prefix
        if id_type == 'imdb' and not media_id.startswith('tt'):
            media_id = f'tt{media_id}'

        # Build payload based on media type
        if media_type == 'movie':
            payload = {
                'movies': [{
                    'ids': {id_type: media_id},
                    'rated_at': datetime.utcnow().isoformat() + 'Z',
                    'rating': rating
                }]
            }
        elif media_type == 'show':
            payload = {
                'shows': [{
                    'ids': {id_type: media_id},
                    'rated_at': datetime.utcnow().isoformat() + 'Z',
                    'rating': rating
                }]
            }
        elif media_type == 'season' and season is not None:
            payload = {
                'shows': [{
                    'ids': {id_type: media_id},
                    'seasons': [{
                        'number': int(season),
                        'rated_at': datetime.utcnow().isoformat() + 'Z',
                        'rating': rating
                    }]
                }]
            }
        elif media_type == 'episode' and season is not None and episode is not None:
            payload = {
                'shows': [{
                    'ids': {id_type: media_id},
                    'seasons': [{
                        'number': int(season),
                        'episodes': [{
                            'number': int(episode),
                            'rated_at': datetime.utcnow().isoformat() + 'Z',
                            'rating': rating
                        }]
                    }]
                }]
            }
        else:
            c.log(f'[Trakt] Invalid media_type or missing season/episode: {media_type}')
            return None

        c.log(f'[Trakt] Rating {media_type} {media_id} as {rating}/10')
        result = get_trakt('/sync/ratings', post=payload)

        if result:
            c.log(f'[Trakt] Rating submitted successfully: {result}')
            c.infoDialog(f'Rated {rating}/10', 'Trakt Rating Submitted', sound=False)
            return result
        else:
            c.log('[Trakt] Rating submission failed')
            return None
    except (requests.RequestException, json.JSONDecodeError, KeyError, ValueError) as e:
        c.log(f'[Trakt] Error submitting rating: {e}')
        return None


def remove_rating(media_type, media_id, id_type='tmdb', season=None, episode=None):
    """Remove a rating for a movie, show, season, or episode."""
    try:
        if not get_trakt_credentials_info():
            c.log('[Trakt] Cannot remove rating - not authenticated')
            return None

        # Ensure IMDB IDs have 'tt' prefix
        if id_type == 'imdb' and not media_id.startswith('tt'):
            media_id = f'tt{media_id}'

        # Build payload (same structure as rate_media, but without rating/rated_at)
        if media_type == 'movie':
            payload = {'movies': [{'ids': {id_type: media_id}}]}
        elif media_type == 'show':
            payload = {'shows': [{'ids': {id_type: media_id}}]}
        elif media_type == 'season' and season is not None:
            payload = {
                'shows': [{
                    'ids': {id_type: media_id},
                    'seasons': [{'number': int(season)}]
                }]
            }
        elif media_type == 'episode' and season is not None and episode is not None:
            payload = {
                'shows': [{
                    'ids': {id_type: media_id},
                    'seasons': [{
                        'number': int(season),
                        'episodes': [{'number': int(episode)}]
                    }]
                }]
            }
        else:
            c.log(f'[Trakt] Invalid media_type or missing season/episode: {media_type}')
            return None

        c.log(f'[Trakt] Removing rating for {media_type} {media_id}')
        result = get_trakt('/sync/ratings/remove', post=payload)

        if result:
            c.log(f'[Trakt] Rating removed successfully: {result}')
            c.infoDialog('Rating removed', 'Trakt Rating', sound=False)
            return result
        else:
            c.log('[Trakt] Rating removal failed')
            return None
    except (requests.RequestException, json.JSONDecodeError, KeyError, ValueError) as e:
        c.log(f'[Trakt] Error removing rating: {e}')
        return None


def get_community_rating_movie(movie_id, id_type='imdb'):
    """Get community rating and votes for a movie."""
    try:
        # Use movie ID directly in URL path
        url = f'/movies/{movie_id}/ratings'
        c.log(f'[Trakt] Fetching movie community rating: {url}')

        result = getTraktAsJson(url)
        if result and isinstance(result, dict):
            rating = str(result.get('rating', '0'))
            votes = str(result.get('votes', '0'))
            c.log(f'[Trakt] Movie community rating: {rating}/10 ({votes} votes)')
            return rating, votes
        return '0', '0'
    except (requests.RequestException, json.JSONDecodeError, KeyError, TypeError) as e:
        c.log(f'[Trakt] Error fetching movie community rating: {e}')
        return '0', '0'


def get_community_rating_show(show_id, id_type='imdb'):
    """Get community rating and votes for a TV show."""
    try:
        # Use show ID directly in URL path
        url = f'/shows/{show_id}/ratings'
        c.log(f'[Trakt] Fetching show community rating: {url}')

        result = getTraktAsJson(url)
        if result and isinstance(result, dict):
            rating = str(result.get('rating', '0'))
            votes = str(result.get('votes', '0'))
            c.log(f'[Trakt] Show community rating: {rating}/10 ({votes} votes)')
            return rating, votes
        return '0', '0'
    except (requests.RequestException, json.JSONDecodeError, KeyError, TypeError) as e:
        c.log(f'[Trakt] Error fetching show community rating: {e}')
        return '0', '0'


def get_user_stats():
    """Get user's watch statistics from Trakt."""
    try:
        if not get_trakt_credentials_info():
            c.log('[Trakt] Cannot get stats - not authenticated')
            return None

        c.log('[Trakt] Fetching user statistics')
        result = getTraktAsJson('/users/me/stats')

        if result and isinstance(result, dict):
            c.log(  f'[Trakt] Stats retrieved - Movies: {result.get("movies", {}).get("watched", 0)}, '
                        f'Shows: {result.get("shows", {}).get("watched", 0)}, '
                        f'Episodes: {result.get("episodes", {}).get("watched", 0)}')
            return result

        c.log('[Trakt] No stats data returned')
        return None
    except Exception as e:
        c.log(f'[Trakt] Error fetching user stats: {e}')
        return None


def show_stats_dialog():
    """Show the Trakt statistics dialog."""
    try:
        import xbmcaddon
        from ..windows.trakt_stats_dialog import TraktStatsDialog

        c.log("[Trakt Stats] Fetching user statistics...")

        # Check if user is authenticated
        if not get_trakt_credentials_info():
            c.okDialog('Please authorize Trakt first./n/nGo to Tools > Trakt > Authorize',
                       'Trakt Statistics'
                       )
            return

        # Get username
        username = control.setting('trakt.user') or 'User'

        # Fetch stats
        stats = get_user_stats()

        if not stats:
            c.okDialog('Unable to fetch statistics.\n\nPlease try again later.',
                       'Trakt Statistics'
                       )
            return

        # Show dialog
        c.log("[Trakt Stats] Showing dialog")

        # Get addon path
        addon = xbmcaddon.Addon('script.thecrew.artwork')

        dialog = TraktStatsDialog(
            'TraktStats.xml',
            addon.getAddonInfo('path'),
            'thecrew',
            '1080i',
            stats=stats,
            username=username
        )
        dialog.doModal()
        del dialog

        c.log("[Trakt Stats] Dialog closed")

    except Exception as e:
        c.log(f"[Trakt Stats] Error showing dialog: {e}", 1)
        control.dialog.ok('Error', f'Unable to show statistics: {str(e)}')



####################################################################################################
# Database - 25-11-2024
#
# cm new from here to add functions for syncing with trakt
#
####################################################################################################
sql_dict = {
    'sql_create_movies_collection' :
        'CREATE TABLE IF NOT EXISTS movies_collection (last_collected_at TEXT, last_updated_at TEXT, Title TEXT, Year INT, trakt INT, slug TEXT, imdb TEXT, tmdb INT, UNIQUE(trakt, imdb, tmdb));',
    'sql_create_shows_collection' :
        'CREATE TABLE IF NOT EXISTS shows_collection (last_collected_at TEXT, last_updated_at TEXT, Title TEXT, Year INT, trakt INT, slug TEXT, tvdb INT, imdb TEXT, tmdb INT, tvrage TEXT, UNIQUE(trakt, tvdb, imdb, tmdb));',
    'sql_create_seasons_collection' :
        'CREATE TABLE IF NOT EXISTS seasons_collection (trakt INT, tvdb INT, imdb TEXT, tmdb INT, season INT, episode INT, collected_at TEXT, UNIQUE (trakt, tvdb, imdb, tmdb, season, episode));',
    'sql_create_trakt_progress' :
        'CREATE TABLE progress (media_type text not null, trakt integer primary key, imdb text, tmdb integer, tvdb integer, showtrakt integer, showimdb text, showtmdb integer, showtvdb integer, season integer, episode integer, resume_point real, curr_time text, last_played text, resume_id integer, tvshowtitle text, title text, year integer)',
    'sql_insert_trakt_progress' :
        'INSERT OR REPLACE INTO progress (media_type, trakt, imdb, tmdb, tvdb, showtrakt, showimdb, showtmdb, showtvdb, season, episode, resume_point, curr_time, last_played, resume_id, tvshowtitle, title, year) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,?, ?, ?, ?) ',
    'sql_create_service' :
        'CREATE TABLE IF NOT EXISTS service(setting TEXT, value TEXT, UNIQUE(setting));',
    'sql_update_service' :
        'UPDATE service SET value = ? where setting = ?',

    'sql_create_sync_data' :
        'CREATE TABLE sync_data (media_type TEXT NOT NULL, name TEXT NOT NULL, date TEXT);',
    'sql_insert_sync_data' :
        'INSERT OR REPLACE INTO sync_data (media_type, name, date) VALUES (?,?,?)',
    'sql_select_sync_data' :
        'SELECT date FROM sync_data WHERE media_type = ? AND name = ?',
    'sql_delete_sync_data' :
        'DELETE FROM sync_data WHERE media_type = ? AND name = ?',
    'sql_create_trakt_watched' :
        'CREATE TABLE IF NOT EXISTS watched (media_type text not null, trakt integer, tvdb integer, imdb TEXT, tmdb integer, season integer, episode integer, last_played text, title text, unique(media_type, trakt, season, episode))',
    'sql_insert_trakt_watched' :
        'INSERT OR REPLACE INTO watched (media_type, trakt, tvdb, imdb, tmdb, season, episode, last_played, title) VALUES (?,?,?,?,?,?,?,?,?)',
    'sql_create_trakt_history' :
        'CREATE TABLE IF NOT EXISTS trakt_history (history_id INTEGER PRIMARY KEY, watched_at TEXT NOT NULL, action TEXT, media_type TEXT NOT NULL, trakt_id INTEGER, imdb_id TEXT, tmdb_id INTEGER, tvdb_id INTEGER, title TEXT, year INTEGER, season INTEGER, episode INTEGER, show_trakt_id INTEGER, show_title TEXT)',
    'sql_insert_trakt_history' :
        'INSERT OR REPLACE INTO trakt_history (history_id, watched_at, action, media_type, trakt_id, imdb_id, tmdb_id, tvdb_id, title, year, season, episode, show_trakt_id, show_title) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
    'sql_create_scrobble_queue' :
        'CREATE TABLE IF NOT EXISTS scrobble_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, media_type TEXT, imdb TEXT, season TEXT, episode TEXT, progress REAL, action TEXT, timestamp TEXT, UNIQUE(media_type, imdb, season, episode))',
    'sql_insert_scrobble_queue' :
        'INSERT OR REPLACE INTO scrobble_queue (media_type, imdb, season, episode, progress, action, timestamp) VALUES (?,?,?,?,?,?,?)',
    'sql_select_scrobble_queue' :
        'SELECT id, media_type, imdb, season, episode, progress, action FROM scrobble_queue ORDER BY timestamp ASC',
    'sql_delete_scrobble_item' :
        'DELETE FROM scrobble_queue WHERE id = ?',
    'sql_clear_scrobble_queue' :
        'DELETE FROM scrobble_queue',
    'sql_create_next_episode_cache' :
        'CREATE TABLE IF NOT EXISTS next_episode_cache (show_tmdb INTEGER, season INTEGER, episode INTEGER, episode_exists BOOLEAN, last_checked TEXT, trakt_watched_at TEXT, trakt_paused_at TEXT, PRIMARY KEY (show_tmdb, season, episode))',
    'sql_insert_next_episode_cache' :
        'INSERT OR REPLACE INTO next_episode_cache (show_tmdb, season, episode, episode_exists, last_checked, trakt_watched_at, trakt_paused_at) VALUES (?,?,?,?,?,?,?)',
    'sql_select_next_episode_cache' :
        'SELECT episode_exists, last_checked, trakt_watched_at, trakt_paused_at FROM next_episode_cache WHERE show_tmdb = ? AND season = ? AND episode = ?',
    'sql_delete_old_cache_entries' :
        'DELETE FROM next_episode_cache WHERE last_checked < ?',
}

@with_db_connection(return_on_error=None, return_as_dict=True)
def check_next_episode_cache(dbcon, dbcur, show_tmdb, season, episode, cache_dict=None):
    """Check if an episode existence validation is cached and still valid.

    Args:
        cache_dict: Optional pre-loaded cache dict from batch_load_episode_cache_for_shows()
                   Format: {(show_tmdb, season, episode): cache_entry_dict}
    """
    try:
        from datetime import datetime, timedelta

        # Check pre-loaded cache first (10-50x faster than DB query)
        if cache_dict is not None:
            cache_key = (show_tmdb, season, episode)
            if cache_key in cache_dict:
                cached_entry = cache_dict[cache_key]
                episode_exists = cached_entry['episode_exists']
                last_checked = cached_entry['last_checked']
                cached_watched_at = cached_entry['cached_watched_at']
                cached_paused_at = cached_entry['cached_paused_at']

                # Validate the cached entry (same logic as DB path)
                try:
                    last_checked_dt = datetime.strptime(last_checked, "%Y-%m-%dT%H:%M:%S.%fZ")
                except ValueError:
                    return None

                # Check if cache is too old (>7 days)
                if datetime.utcnow() - last_checked_dt > timedelta(days=7):
                    return None

                # Get current Trakt activity timestamps
                current_watched, current_paused = get_trakt_activity_from_db()

                # Invalidate if activity changed
                if current_watched != cached_watched_at or current_paused != cached_paused_at:
                    return None

                # Cache is valid
                return bool(episode_exists)
            # Key not in cache, fall through to None

        # Fallback to DB query if cache_dict not provided or key not found
        sql = sql_dict['sql_select_next_episode_cache']
        dbcur.execute(sql, (show_tmdb, season, episode))
        result = dbcur.fetchone()

        if not result:
            return None

        episode_exists, last_checked, cached_watched_at, cached_paused_at = result

        # Parse last_checked timestamp
        try:
            last_checked_dt = datetime.strptime(last_checked, "%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            # Invalid timestamp, invalidate cache
            return None

        # Check if cache is too old (>7 days) - new episodes might have aired
        if datetime.utcnow() - last_checked_dt > timedelta(days=7):
            c.log(f"[NextEpisodeCache] Cache expired for show {show_tmdb} S{season:02d}E{episode:02d} (>7 days old)")
            return None

        # Get current Trakt activity timestamps from database (not API!)
        current_watched, current_paused = get_trakt_activity_from_db()

        # Invalidate if user watched or paused episodes since cache was created
        if current_watched != cached_watched_at or current_paused != cached_paused_at:
            c.log(f"[NextEpisodeCache] Trakt activity changed for show {show_tmdb} S{season:02d}E{episode:02d}")
            return None

        # Cache is valid
        # Verbose log commented out for performance (reduces log spam)
        # c.log(f"[NextEpisodeCache] Using cached result for show {show_tmdb} S{season:02d}E{episode:02d}: exists={episode_exists}")
        return bool(episode_exists)

    except Exception as e:
        c.log(f"[NextEpisodeCache] Error checking cache: {e}")
        return None

def get_trakt_activity_from_db():
    """Get Trakt activity timestamps from the database (already cached by syncTrakt)."""
    try:
        watched_at = get_trakt_table_value('episodes', 'watched_at') or ''
        paused_at = get_trakt_table_value('episodes', 'paused_at') or ''
        return (watched_at, paused_at)
    except Exception as e:
        c.log(f"[NextEpisodeCache] Error reading Trakt activity from DB: {e}")
        return ('', '')


@with_db_connection(return_on_error=None, return_as_dict=True)
def update_next_episode_cache(dbcon, dbcur, show_tmdb, season, episode, exists):
    """Update the cache with an episode existence validation result."""
    try:
        from datetime import datetime

        # Ensure table exists
        if not table_exists('next_episode_cache'):
            create_table('next_episode_cache')

        # Get current Trakt activity timestamps from database (not API!)
        watched_at, paused_at = get_trakt_activity_from_db()

        # Store result with current timestamp and Trakt activity
        last_checked = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        sql = sql_dict['sql_insert_next_episode_cache']
        dbcur.execute(sql, (show_tmdb, season, episode, int(exists), last_checked, watched_at, paused_at))

        dbcon.commit()

        c.log(f"[NextEpisodeCache] Cached result for show {show_tmdb} S{season:02d}E{episode:02d}: exists={exists}")

    except Exception as e:
        c.log(f"[NextEpisodeCache] Error updating cache: {e}")
        if dbcon:
            dbcon.close()

@with_db_connection(return_on_error=None)
def init_next_episode_cache(dbcon, dbcur):
    """Initialize the next_episode_cache table and clean up old entries."""
    from datetime import datetime, timedelta

    # Create table if it doesn't exist
    if not table_exists('next_episode_cache'):
        c.log("[NextEpisodeCache] Creating next_episode_cache table")
        create_table('next_episode_cache')

    # Clean up old entries (>30 days)
    cutoff_date = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    sql = sql_dict['sql_delete_old_cache_entries']
    dbcur.execute(sql, (cutoff_date,))
    deleted_count = dbcur.rowcount

    if deleted_count > 0:
        c.log(f"[NextEpisodeCache] Cleaned up {deleted_count} old cache entries")

    dbcon.commit()

@with_db_connection(return_on_error=None, return_as_dict=True)
def batch_load_episode_cache_for_shows(dbcon, dbcur, show_ids):
    """Batch load all episode cache entries for multiple shows (10-50x faster than individual queries).

    Args:
        show_ids: List of show TMDB IDs

    Returns:
        dict: {(show_tmdb, season, episode): cache_entry_dict} for quick lookups
    """
    try:
        from datetime import datetime, timedelta

        if not show_ids:
            return {}

        # Ensure table exists
        if not table_exists('next_episode_cache'):
            return {}

        # Build SQL with IN clause for batch query
        placeholders = ','.join('?' * len(show_ids))
        sql = f"SELECT show_tmdb, season, episode, episode_exists, last_checked, trakt_watched_at, trakt_paused_at FROM next_episode_cache WHERE show_tmdb IN ({placeholders})"

        dbcur.execute(sql, show_ids)
        results = dbcur.fetchall()

        # Build lookup dict
        cache_dict = {}
        for row in results:
            show_tmdb, season, episode, episode_exists, last_checked, cached_watched, cached_paused = row
            cache_dict[(show_tmdb, season, episode)] = {
                'episode_exists': episode_exists,
                'last_checked': last_checked,
                'cached_watched_at': cached_watched,
                'cached_paused_at': cached_paused
            }

        c.log(f"[NextEpisodeCache] Batch loaded {len(cache_dict)} cache entries for {len(show_ids)} shows")
        return cache_dict

    except Exception as e:
        c.log(f"[NextEpisodeCache] Error batch loading cache: {e}")
        return {}

def syncTrakt() -> None:
    """
    Syncs Kodi status with Trakt.tv
    """
    if not control.player.isPlayingVideo() and c.devmode:
        c.infoDialog('Syncing with Trakt', 'Please wait', icon='main_classy.png', sound=False)
    else:
        c.log('(def syncTrakt) Syncing with Trakt', 1)

    try:
        # Initialize next episode cache on startup (creates table, cleans old entries)
        init_next_episode_cache()

        # MUST run first: stores fresh Trakt timestamps into the local DB so that
        # fill_history() and fill_trakt_watched() can use them for change detection.
        # Running this last (as before) caused fill_history() to compare stale timestamps
        # and skip incremental fetches even when new activity existed on Trakt.
        sync_last_activities()

        fill_progress_table()
        fill_trakt_watched()

        # Sync collection in background (movies + shows)
        get_trakt_collection('all')

        # Sync watch history (incremental - only fetches new events)
        fill_history()

        if not control.player.isPlayingVideo():
            return c.infoDialog('Syncing with Trakt Finished', 'Please wait', icon='main_classy.png', sound=False)
        else:
            c.log('Syncing with Trakt Finished', 1)

    except (Exception, OperationalError) as e:
        pass

        failure = traceback.format_exc()
        c.log(f'Traceback:: {failure}')
        c.log(f'Exception raised in trakt flow: {e}')



def get_show_extended_info(trakt_id):
    endpoint = f'/shows/{trakt_id}?extended=full'
    return getTraktAsJson(endpoint)

def fill_progress_table() -> None:
    """Fetches progress from trakt and inserts/updates it in the database (trakt_progress)."""
    start, end = get_start_end(diff=365)

    # Fetch BOTH movies and episodes from Trakt playback progress
    for media in ['movies', 'episodes']:
        endpoint = f'sync/playback/{media}?extended=full&start_at={start}&end_at={end}'
        c.log(f"[Trakt] fill_progress_table: Fetching {media} from {endpoint}")

        if result := getTraktAsJson(endpoint):
            if not table_exists('trakt_progress'):
                create_table('trakt_progress')

            c.log(f"[Trakt] fill_progress_table: Processing {len(result)} {media}")

            for item in result:
                media_type = item.get('type')
                progress = item.get('progress')
                ids = item.get(media_type).get('ids')
                trakt_id = ids.get('trakt')
                tvdb_id = ids.get('tvdb')
                tmdb_id = ids.get('tmdb')
                imdb_id = ids.get('imdb')
                year = item.get(media_type).get('year')
                title = item.get(media_type).get('title')
                season = item.get(media_type).get('season') if media_type == 'episode' else 0
                episode = item.get(media_type).get('number') if media_type == 'episode' else 0
                current_time = get_now_in_iso()
                last_played = item.get('paused_at')
                resume_id = item.get('id')

                # Convert Trakt's progress percentage to seconds using runtime.
                # resume_point must be stored in seconds so the player can seek correctly.
                runtime_minutes = item.get(media_type, {}).get('runtime', 0) or 0
                if runtime_minutes > 0 and progress is not None:
                    resume_seconds = int((float(progress) / 100.0) * runtime_minutes * 60)
                else:
                    resume_seconds = 0
                c.log(f"[Trakt] fill_progress_table: {media_type} progress={progress}% runtime={runtime_minutes}min -> resume_seconds={resume_seconds}s")

                if 'show' in item:
                    tvshowtitle = item.get('show').get('title')
                    show_trakt_id = item.get('show').get('ids').get('trakt')
                    show_imdb_id = item.get('show').get('ids').get('imdb')
                    show_tmdb_id = item.get('show').get('ids').get('tmdb')
                    show_tvdb_id = item.get('show').get('ids').get('tvdb')
                else:
                    tvshowtitle = ''
                    show_trakt_id = 0
                    show_imdb_id = 0
                    show_tmdb_id = 0
                    show_tvdb_id = 0

                insert_trakt_progress(
                    media_type,
                    trakt_id,
                    imdb_id,
                    tmdb_id,
                    tvdb_id,
                    show_trakt_id,
                    show_imdb_id,
                    show_tmdb_id,
                    show_tvdb_id,
                    season,
                    episode,
                    resume_seconds,
                    current_time,
                    last_played,
                    resume_id,
                    tvshowtitle,
                    title,
                    year,
                )

def update_progress_in_database(imdb_id: str = '', trakt_id: int = 0, tmdb_id: int = 0, season: int = 0, episode: int = 0, progress: int = 0, resume_point: float = None) -> None:
    """Update progress in the trakt sync database using UPSERT logic."""
    try:
        # If resume_point not provided, use progress percentage as 0-1 fraction
        # Otherwise use the provided value (should be in seconds from bookmarks.reset)
        if resume_point is None:
            resume_point = progress / 100.0        # Determine media type
        media_type = 'episode' if season and episode else 'movie'

        c.log(f"[Trakt] update_progress_in_database: {media_type} imdb={imdb_id} progress={progress}% resume_point={resume_point}")

        connection = get_connection(control.traktsyncFile, return_as_dict=True)
        if connection:
            cursor = connection.cursor()
        else:
            raise OperationalError("Could not establish database connection.")

        # Use INSERT OR REPLACE with minimal fields
        # For movies: trakt is primary key, so we use a dummy value if not provided
        # For episodes: we need show info which we might not have, so try UPDATE first

        if media_type == 'movie':
            # Try UPDATE first
            conditions = []
            if imdb_id:
                conditions.append(f"imdb = '{imdb_id}'")
            if trakt_id:
                conditions.append(f"trakt = {trakt_id}")
            if tmdb_id:
                conditions.append(f"tmdb = {tmdb_id}")

            if conditions:
                sql = 'UPDATE progress SET resume_point = ? WHERE media_type = ? AND (' + ' OR '.join(conditions) + ')'
                c.log(f"[Trakt] Executing UPDATE: {sql} with resume_point={resume_point}")
                cursor.execute(sql, (resume_point, media_type))
                rows_updated = cursor.rowcount
                c.log(f"[Trakt] UPDATE affected {rows_updated} rows")

                if rows_updated == 0:
                    # Row doesn't exist, insert minimal record using imdb as the key
                    # Use a synthetic trakt ID based on imdb hash to satisfy primary key constraint
                    c.log(f"[Trakt] No existing row, inserting new record with imdb={imdb_id}")
                    synthetic_trakt_id = abs(hash(imdb_id)) % (10 ** 8) if imdb_id else (trakt_id if trakt_id else 0)
                    sql = 'INSERT OR REPLACE INTO progress (media_type, trakt, imdb, tmdb, tvdb, showtrakt, showimdb, showtmdb, showtvdb, season, episode, resume_point, curr_time, last_played, resume_id, tvshowtitle, title, year) VALUES (?, ?, ?, ?, 0, 0, NULL, 0, 0, 0, 0, ?, NULL, NULL, 0, NULL, NULL, 0)'
                    cursor.execute(sql, (media_type, synthetic_trakt_id, imdb_id, tmdb_id, resume_point))
                    c.log(f"[Trakt] INSERT completed with synthetic trakt_id={synthetic_trakt_id}")
        else:
            # Episode - try UPDATE using show identifiers (showimdb/showtmdb) + season/episode
            show_conditions = []
            if imdb_id:
                show_conditions.append(f"showimdb = '{imdb_id}'")
            if trakt_id:
                show_conditions.append(f"showtrakt = {trakt_id}")
            if tmdb_id:
                show_conditions.append(f"showtmdb = {tmdb_id}")

            if show_conditions:
                where_show = '(' + ' OR '.join(show_conditions) + ')'
                sql = f"UPDATE progress SET resume_point = ? WHERE media_type = 'episode' AND {where_show} AND season = {season} AND episode = {episode}"
                c.log(f"[Trakt] Executing UPDATE: {sql}")
                cursor.execute(sql, (resume_point,))
                rows_updated = cursor.rowcount
                c.log(f"[Trakt] UPDATE affected {rows_updated} rows")

                if rows_updated == 0:
                    # No existing row, insert a minimal record for the episode
                    c.log(f"[Trakt] No existing row, inserting new episode record imdb={imdb_id} tmdb={tmdb_id} S{season}E{episode}")
                    synthetic_trakt_id = abs(hash(f"{imdb_id or tmdb_id}S{season:02d}E{episode:02d}")) % (10 ** 8)
                    sql = ('INSERT OR REPLACE INTO progress '
                           '(media_type, trakt, imdb, tmdb, tvdb, showtrakt, showimdb, showtmdb, showtvdb, '
                           'season, episode, resume_point, curr_time, last_played, resume_id, tvshowtitle, title, year) '
                           'VALUES (?, ?, ?, ?, 0, ?, ?, ?, 0, ?, ?, ?, NULL, NULL, 0, NULL, NULL, 0)')
                    cursor.execute(sql, ('episode', synthetic_trakt_id, imdb_id, tmdb_id,
                                         trakt_id, imdb_id, tmdb_id,
                                         season, episode, resume_point))
                    c.log(f"[Trakt] INSERT completed with synthetic trakt_id={synthetic_trakt_id}")
            else:
                c.log("[Trakt] update_progress_in_database: no identifiers for episode, skipping")

        connection.commit()
        cursor.close()
        connection.close()
        c.log("[Trakt] update_progress_in_database completed successfully")
    except Exception as e:
        c.log(f"[Trakt] ERROR in update_progress_in_database: {e}")
        c.log(f"[Trakt] Traceback: {traceback.format_exc()}")


def delete_progress_from_database(key, media_id, season: int = 0, episode: int = 0) -> None:
    """Delete progress from the trakt sync database."""
    try:
        if key == 'imdb' and not media_id.startswith('tt'):
            media_id = f'tt{media_id}'
        connection = get_connection(control.traktsyncFile)
        if connection:
            cursor = connection.cursor()
        else:
            raise OperationalError("Could not establish database connection.")

        conditions = []
        if key == 'imdb' and media_id:
            # Episodes may store the show IMDB in showimdb (not imdb) — match both
            if season and episode:
                conditions.append(f"(imdb = '{media_id}' OR showimdb = '{media_id}')")
            else:
                conditions.append(f"imdb = '{media_id}'")
        if key == 'trakt' and media_id:
            conditions.append(f"trakt = {media_id}")
        if key == 'tmdb' and media_id:
            conditions.append(f"tmdb = {media_id}")
        if season:
            conditions.append(f"season = {season}")
        if episode:
            conditions.append(f"episode = {episode}")

        if conditions:
            sql = 'DELETE FROM progress WHERE ' + ' AND '.join(conditions)
            c.log(f"[Trakt] Executing DELETE: {sql}")
            cursor.execute(sql)
            c.log(f"[Trakt] DELETE affected {cursor.rowcount} rows")

        connection.commit()
        cursor.close()
        connection.close()
        c.log("[Trakt] delete_progress_from_database completed successfully")
    except Exception as e:
        c.log(f"[Trakt] ERROR in delete_progress_from_database: {e}")
        c.log(f"[Trakt] Traceback: {traceback.format_exc()}")


@with_db_connection(return_on_error=None, return_as_dict=True)
def fill_trakt_watched(dbcon, dbcur) -> None:
    """Fetch watched data from Trakt and update database using optimized batch sync."""
    # Use optimized batch sync with conditional requests
    batch_result = sync_watched_batch()

    if not batch_result:
        c.log('[Trakt] No watched data to sync (unchanged or error)')
        return

    if not table_exists('trakt_watched'):
        create_table('trakt_watched')

    # Process shows from batch result
    if 'shows' in batch_result:
        for item in batch_result['shows']:
            media_type = 'show'
            show = item['show']
            trakt_id = show['ids']['trakt']
            tvdb_id = show['ids'].get('tvdb', 0)
            imdb_id = show['ids'].get('imdb')
            tmdb_id = show['ids'].get('tmdb')
            title = show['title']

            for season in item['seasons']:
                season_nr = season['number']
                for episodes in season['episodes']:
                    episode_nr = episodes['number']
                    last_watched_at = episodes['last_watched_at']
                    dbcur.execute(sql_dict['sql_insert_trakt_watched'],
                                (media_type, trakt_id, tvdb_id, imdb_id, tmdb_id,
                                season_nr, episode_nr, last_watched_at, title))

    # Process movies from batch result
    if 'movies' in batch_result:
        media_type = 'movie'
        for item in batch_result['movies']:
            movie = item['movie']
            trakt_id = movie['ids']['trakt']
            tvdb_id = movie['ids'].get('tvdb', 0)
            imdb_id = movie['ids'].get('imdb')
            tmdb_id = movie['ids'].get('tmdb')
            title = movie['title']
            last_watched_at = item['last_watched_at']

            dbcur.execute(sql_dict['sql_insert_trakt_watched'],
                        (media_type, trakt_id, tvdb_id, imdb_id, tmdb_id,
                        0, 0, last_watched_at, title))

    dbcon.commit()
    c.log('[Trakt] Batch sync completed successfully')



@with_db_connection(return_on_error=None, return_as_dict=True)
def fill_trakt_watched_orig(dbcon, dbcur) -> None:
    """Fetch watched data from trakt and insert/update it in the database (original implementation)."""
    try:
        pass

        _types = ['movies', 'shows']
        #_types = ['shows']

        for _type in _types:
            c.log(f"type = {_type} (type={type(_type)})")
            endpoint = f'sync/watched/{_type}'
            if result := getTraktAsJson(endpoint):
                if _type == 'movies':
                    indicators = [i['movie']['ids']['tmdb'] for i in result]
                    c.log(f"indicators = {indicators}")
                if not table_exists('trakt_watched'):
                    create_table('trakt_watched')

                for item in result:
                    media_type = _type
                    trakt_id = item.get(_type).get('ids').get('trakt')
                    tvdb_id = item.get(_type).get('ids').get('tvdb') or 0
                    imdb_id = item.get(_type).get('ids').get('imdb')
                    tmdb_id = item.get(_type).get('ids').get('tmdb')
                    title = item.get(_type).get('title')


                    if _type == 'movies':
                        seasons = 0
                        episode = 0
                        last_watched_at = item.get('last_watched_at')
                        dbcur.execute(sql_dict['sql_insert_trakt_watched'], (media_type, trakt_id, tvdb_id, imdb_id, tmdb_id, seasons, episode, last_watched_at, title))
                    else:
                        seasons = item.get('seasons')
                        c.log(f"seasons = {seasons}")
                        for season in seasons:
                            season_nr = season.get('number')
                            c.log(f"season = {season_nr}")
                            for episodes in season:
                                episode_nr = episodes.get('number')
                                c.log(f"episode_nr = {episode_nr}")
                                for item in episodes.get('episodes'):
                                    c.log(f"item = {item}")
                                    last_watched_at = item.get('last_watched_at')
                                    c.log(f"last_watched = {last_watched_at}")
                                    dbcur.execute(sql_dict['sql_insert_trakt_watched'], (media_type, trakt_id, tvdb_id, imdb_id, tmdb_id, season_nr, episode_nr, last_watched_at, title))
                dbcon.commit()

    except Exception as e:
        failure = traceback.format_exc()
        c.log(f'Traceback:: {failure}')
        c.log(f'Exception raised: {e}')


@with_db_connection(return_on_error=None, return_as_dict=True)
def fill_history(dbcon, dbcur, force_full_sync=False) -> None:
    """Fetch watch history from Trakt and store it in the database (uses incremental sync)."""
    try:
        # Ensure table exists
        if not table_exists('trakt_history'):
            create_table('trakt_history')
            # First time - do full sync
            force_full_sync = True

        # Check if watched activity has changed (movies.watched_at or episodes.watched_at)
        latest_watched = max(
            get_trakt_table_value('movies', 'watched_at') or '',
            get_trakt_table_value('episodes', 'watched_at') or ''
        )

        last_history_sync = get_trakt_sync_value('last_history_sync') or ''

        # Skip sync if nothing changed
        if not force_full_sync and latest_watched and latest_watched == last_history_sync:
            if c.devmode:
                c.log(f"[Trakt] No new watch history detected (last={last_history_sync}), skipping")
            return

        # Determine sync range
        if force_full_sync or not last_history_sync:
            # Full sync from 2016
            start_date = '2016-06-01T00:00:00.000Z'
            c.log("[Trakt] Performing FULL history sync from 2016")
        else:
            # Incremental sync - fetch only new events since last sync
            start_date = last_history_sync
            c.log(f"[Trakt] Performing INCREMENTAL history sync from {start_date}")

        from resources.lib.modules import cleandate
        end_date = cleandate.now_to_iso()

        _types = ['movies', 'episodes']
        total_new_events = 0

        for _type in _types:
            endpoint = f'/sync/history/{_type}?start_at={start_date}&end_at={end_date}'

            result = getTraktAsJson(endpoint)
            if not result:
                c.log(f"[Trakt] No history data returned for {_type}")
                continue

            c.log(f"[Trakt] Processing {len(result)} history entries for {_type}")
            total_new_events += len(result)

            for item in result:
                try:
                    # Common fields
                    history_id = item.get('id')
                    watched_at = item.get('watched_at')
                    action = item.get('action', 'watch')
                    media_type = item.get('type')

                    if _type == 'movies':
                        # Movie data
                        movie = item.get('movie', {})
                        trakt_id = movie.get('ids', {}).get('trakt')
                        imdb_id = movie.get('ids', {}).get('imdb')
                        tmdb_id = movie.get('ids', {}).get('tmdb')
                        tvdb_id = None
                        title = movie.get('title')
                        year = movie.get('year')
                        season = None
                        episode = None
                        show_trakt_id = None
                        show_title = None

                    else:  # episodes
                        # Episode data
                        episode_data = item.get('episode', {})
                        trakt_id = episode_data.get('ids', {}).get('trakt')
                        imdb_id = episode_data.get('ids', {}).get('imdb')
                        tmdb_id = episode_data.get('ids', {}).get('tmdb')
                        tvdb_id = episode_data.get('ids', {}).get('tvdb')
                        title = episode_data.get('title')
                        year = None
                        season = episode_data.get('season')
                        episode = episode_data.get('number')

                        # Show data
                        show = item.get('show', {})
                        show_trakt_id = show.get('ids', {}).get('trakt')
                        show_title = show.get('title')

                    # Insert into database (INSERT OR REPLACE handles duplicates)
                    dbcur.execute(sql_dict['sql_insert_trakt_history'],
                                (history_id, watched_at, action, media_type,
                                 trakt_id, imdb_id, tmdb_id, tvdb_id,
                                 title, year, season, episode,
                                 show_trakt_id, show_title))

                except Exception as e:
                    c.log(f"[Trakt] Error processing history item: {e}")
                    continue

            dbcon.commit()

        # Update last sync timestamp (use latest watched activity)
        if latest_watched:
            if not table_exists('service'):
                create_table('service')
            dbcur.execute(sql_dict['sql_update_service'], (latest_watched, 'last_history_sync'))
            dbcon.commit()
            c.log(f"[Trakt] History sync completed - {total_new_events} events processed, last_sync={latest_watched}")
        else:
            c.log(f"[Trakt] History sync completed - {total_new_events} events processed")

    except Exception as e:
        failure = traceback.format_exc()
        c.log(f'[Trakt] fill_history error - Traceback: {failure}')
        c.log(f'[Trakt] fill_history error - Exception: {e}')


def sync_last_activities():
    """Sync last activities from Trakt (uses 'all' timestamp as quick check, stores detailed activity timestamps if changed)."""
    try:
        # Fetch full activity data from Trakt
        i = getTraktAsJson('/sync/last_activities')
        if not i:
            c.log("[Trakt] sync_last_activities: No data returned from Trakt")
            return

        # Get the 'all' timestamp (latest across all activities)
        _all = i.get('all')
        if not _all:
            c.log("[Trakt] sync_last_activities: No 'all' timestamp in response")
            return

        # Check if anything changed by comparing 'all' timestamp
        stored_all = get_trakt_sync_value('all') or ''

        if _all == stored_all:
            # Nothing changed - skip updating
            if c.devmode:
                c.log(f"[Trakt] No activity changes detected (all={_all}), skipping sync")
            return

        # Something changed - store ALL the detailed activity timestamps
        if c.devmode:
            c.log(f"[Trakt] Activity changed ({stored_all} -> {_all}), storing all timestamps")

        create_trakt_tables(i)

        # Update crew_last_sync timestamp
        _crew = cleandate.now_to_iso()
        update_service(_all, _crew)

    except Exception as e:
        c.log(f"[Trakt] Error in sync_last_activities: {e}")
        import traceback
        c.log(f"[Trakt] Traceback: {traceback.format_exc()}")



@with_db_connection(return_on_error=None, return_as_dict=True)
def update_service(dbcon, dbcur, _all, _crew):
    try:
        d = {'all':_all, 'crew_last_sync': _crew}

        if not table_exists('service'):
            create_table('service')

        for k,v in d.items():
            sql = sql_dict['sql_update_service']
            dbcur.execute(sql, (v, k))
        dbcon.commit()
    except Exception as e:
        c.log(f"Exception raised: {e}")


@with_db_connection(return_on_error=None, return_as_dict=True)
def insert_trakt_progress(dbcon, dbcur, media_type, trakt, imdb, tmdb, tvdb, showtrakt, showimdb, showtmdb, showtvdb, season, episode, resume_point, curr_time, last_played, resume_id, tvshowtitle, title, year):
    "Insert progress data into trakt_progress table."
    sql = sql_dict['sql_insert_trakt_progress']
    dbcur.execute(sql, (media_type, trakt, imdb, tmdb, tvdb, showtrakt, showimdb, showtmdb, showtvdb, season, episode, resume_point, curr_time, last_played, resume_id, tvshowtitle, title, year))
    dbcon.commit()



def get_start_end(diff):
    """Returns a tuple of ISO 8601 formatted dates (start, end) for current date and given number of days ago."""
    start = datetime.now() - timedelta(days=diff)
    start = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return quote_plus(start), quote_plus(end)

def get_now_in_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")

def get_connection(file, return_as_dict=False):
    """Establishes a connection to a SQLite database file."""
    try:
        pass

        if not os.path.isfile(control.dataPath):
            control.makeFile(control.dataPath)

        dbcon = database.connect(file)
        dbcon.execute('PRAGMA page_size = 32768')
        dbcon.execute('PRAGMA cache_size = 10000000')
        dbcon.execute('PRAGMA mmap_size = 30000000000')
        #dbcon.execute('PRAGMA journal_mode = OFF')
        dbcon.execute('PRAGMA journal_mode = MEMORY')
        dbcon.execute('PRAGMA temp_store = MEMORY')
        dbcon.execute('PRAGMA synchronous = OFF')

        if return_as_dict:
            dbcon.row_factory = _dict_factory
        return dbcon
    except Exception as e:
        c.log(f"Error getting database connection: {e}")
        return None

def get_connection_cursor(db_connection):
    """Returns a database cursor object from a connection."""
    if db_connection is None:
        c.log("Database connection is None")
        return None

    try:
        return db_connection.cursor()
    except Exception as e:
        c.log(f"Error getting database cursor: {e}")
        return None


def open_connection(file = control.traktsyncFile):
    """Opens a connection to a SQLite database file."""
    conn = get_connection(file)
    cursor = get_connection_cursor(conn)
    return None if conn is None or cursor is None else (conn, cursor)

def commit(db_connection) -> None:
    _commit(db_connection)

def close_connection(db_connection):
    """Closes a database connection."""
    if db_connection is not None:
        db_connection.close()
    else:
        c.log("Database connection is None")


def _commit(db_connection):
    """Commits the current transaction to the database."""
    if db_connection is None:
        c.log("Database connection is None")
        return
    else:
        c.log("Database connection is not None")
    try:
        if db_connection is not None:
            c.log(f"Database connection is of type(): {type(db_connection)}")
            db_connection.commit()
            c.log("Database connection is initialized")
        else:
            c.log("Database connection is not initialized")
    except AttributeError:
        c.log("Database connection does not have a connection attribute")
    except Exception as e:
        c.log(f"Error committing to the database: {e}")



def _dict_factory(cursor, row):
    """Construct a dictionary from a SQLite query result."""
    if cursor is None or row is None:
        raise ValueError("cursor and row must not be None")

    row_dict = {}
    for index, column in enumerate(cursor.description):
        try:
            row_dict[column[0]] = row[index]
        except Exception as e:
            c.log(f"Error constructing dictionary from SQLite query result: {e}")
    return row_dict

####
# end of core database functions


def get_db_connection(file=control.traktsyncFile, return_as_dict=True):
    """Return a database connection and cursor for the specified SQLite file."""
    try:
        dbcon = get_connection(file, return_as_dict)
        dbcur = get_connection_cursor(dbcon)

        # check if we have a valid connection and cursor
        if dbcur and dbcon:
            return dbcon, dbcur
        c.log("Error: dbcur or dbcon is None, cannot create connection")
        return None, None

    except (database.Error, database.OperationalError) as e:
        c.log(f"Error getting database connection: {e}")
        return None, None

####
# start of trakt functions

def check_sync_tables():
    """Check if the trakt sync tables exist and create them if not."""
    try:
        #fetch activities
        last_activities = getTraktAsJson('/sync/last_activities')
        c.log(f"last_activities type = {type(last_activities)}")

        if last_activities:
            create_trakt_tables(last_activities)
        else:
            c.log("Error: last_activities is None")
    except Exception as e:
        c.log(f"Error checking sync tables: {e}")

@with_db_connection(return_on_error=None, return_as_dict=True)
def fetch_last_service(dbcon, dbcur, fetch_all=False):
    """Retrieve the last sync timestamp from the trakt sync database."""
    try:
        sql = 'SELECT value FROM service where setting = "crew_last_sync"'
        if fetch_all:
            dbcur.execute(sql)
            return dbcur.fetchall()
        else:
            dbcur.execute(sql)
            return dbcur.fetchone()
    except (database.Error, database.OperationalError) as e:
        c.log(f"Error fetching last sync timestamp: {e}")
        return None

@with_db_connection(return_on_error=None, return_as_dict=True)
def fetch_last_activity(dbcon, dbcur, fetch_all=True, activity_type='all'):
    try:
        if fetch_all:
            sql = 'SELECT value FROM service where setting = "all"'
            dbcur.execute(sql)
            return dbcur.fetchall()
        else:
            sql = f'SELECT value FROM service where setting = "{activity_type}"'
            dbcur.execute(sql)
            return dbcur.fetchone()
    except (database.Error, database.OperationalError) as e:
        c.log(f"Error fetching last activity: {e}")
        return None

@with_db_connection(return_on_error=None, return_as_dict=True)
def create_trakt_tables(dbcon, dbcur, last_activities):
    """Create the tables in the trakt sync database if they don't exist."""
    try:
        for key, val in last_activities.items():
            if isinstance(val, str):
                if not table_exists('service'):
                    sql = "CREATE TABLE IF NOT EXISTS service(setting TEXT, value TEXT, UNIQUE(setting));"
                    dbcur.execute(sql)

                sql = f"INSERT OR REPLACE INTO service Values ('{key}', '{val}')"
                dbcur.execute(sql)

            elif isinstance(val, dict):
                if not table_exists(key):
                    sql = f"CREATE TABLE IF NOT EXISTS {key} (setting TEXT, value TEXT, UNIQUE(setting));"
                    dbcur.execute(sql)

                for k, v in val.items():
                    sql = f"INSERT OR REPLACE INTO {key} Values ('{k}', '{v}')"
                    dbcur.execute(sql)

                timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
                sql = f"INSERT OR REPLACE INTO service Values ('crew_last_sync', '{timestamp}')"
                dbcur.execute(sql)

        dbcon.commit()

    except Exception as e:
        c.log(f'Exception in create_trakt_tables(last_activities): Error = {e}')

@with_db_connection(return_on_error=None, return_as_dict=True)
def create_table(dbcon, dbcur, name='', query=''):
    """Create a table in the trakt sync database."""
    try:
        if not name and not query:
            c.log(f"Trying to create table in trakt::create_table without name or query. name = {name}, query = {query}, returning")
            return

        if table_exists(name):
            c.log(f"Table {name} already exists")
        elif f'sql_create_{name}' in sql_dict:
            sql = sql_dict[f'sql_create_{name}']
            # Ensure idempotent CREATE TABLE statements include IF NOT EXISTS to avoid race errors
            if isinstance(sql, str) and sql.lower().startswith('create table') and 'if not exists' not in sql.lower():
                sql = sql.replace('CREATE TABLE', 'CREATE TABLE IF NOT EXISTS', 1)
            dbcur.execute(sql)
            c.log(f"sql = {sql}")
        elif query:
            if query.lower().startswith('create table'):
                # Add IF NOT EXISTS to prevent OperationalError when table exists
                safe_query = query
                if 'if not exists' not in query.lower():
                    safe_query = query.replace('CREATE TABLE', 'CREATE TABLE IF NOT EXISTS', 1)
                dbcur.execute(safe_query)
            else:
                c.log(f"Trying to use invalid query in trakt::create_table, query = {query}, returning")
        #no return here, gracefully close the connection

        dbcon.commit()

    except OperationalError as e:
        # Some OperationalErrors are benign (e.g., 'table x already exists') when multiple
        # callers attempt to create the same table concurrently. Handle that case quietly.
        msg = str(e).lower()
        if 'already exists' in msg:
            c.log(f"Table {name} already exists, skipping")
        else:
            failure = traceback.format_exc()
            c.log(f'Traceback:: {failure}')

    except Exception as e:
        failure = traceback.format_exc()

@with_db_connection(return_on_error=None, return_as_dict=True)
def get_trakt_collection(dbcon, dbcur, media_type="all") -> None:
    try:
        do_commit = False

        if media_type in ['movies', 'all']:
            if not table_exists('movies_collection'):
                sql = sql_dict['sql_create_movies_collection']
                dbcur.execute(sql)
                do_commit = True
            movie_collection = getTraktAsJson('/sync/collection/movies')
            insert_collection(movie_collection, 'movies')

        if media_type in ['shows', 'all']:
            if not table_exists('shows_collection'):
                sql = sql_dict['sql_create_shows_collection']
                dbcur.execute(sql)
                do_commit= True

            if not table_exists('seasons_collection'):
                sql = sql_dict['sql_create_seasons_collection']
                dbcur.execute(sql)
                do_commit = True

            show_collection = getTraktAsJson('/sync/collection/shows')
            insert_collection(show_collection, 'shows')

        if do_commit:
            dbcon.commit()
            if not control.player.isPlayingVideo():
                c.infoDialog('trakt collection updated', icon="main_orangehat.png", time=2000)

    except Exception as e:
        failure = traceback.format_exc()

@with_db_connection(return_on_error=None, return_as_dict=True)
def get_collection(dbcon, dbcur, media_type, trakt_id=0, imdb_id='', tmdb_id=0):
    """Retrieves collection entries from the trakt sync database for the specified media type and identifiers."""
    try:
        pass

        if media_type not in ['movies', 'shows']:
            return
        if not table_exists(f"{media_type}_collection"):
            create_table(f"{media_type}_collection", sql_dict[f"sql_create_{media_type}_collection"])
        query = []
        media_type = media_type.lower()


        if trakt_id == 0 and imdb_id == '' and tmdb_id == 0:
            sql = f"SELECT * FROM {media_type}_collection"
        else:
            if trakt_id != 0:
                query.append(f"trakt = {trakt_id}")
            if imdb_id != '':
                query.append(f"imdb = '{imdb_id}'")
            if tmdb_id != 0:
                query.append(f"tmdb = {tmdb_id}")
            sql = f"SELECT * FROM {media_type}_collection WHERE {' AND '.join(query)}"

        dbcur.execute(sql)
        rows = dbcur.fetchall()

        dbcon.commit()

        if len(rows) > 0:
            return rows
        else:
            return

    except OperationalError as e:
        c.log(f'Exception raised in get_collection. Error = {e}')
    except Exception as e:
        c.log(f'Exception raised in get_collection. Error = {e}')





@with_db_connection(return_on_error=None, return_as_dict=True)
def get_collection_orig(dbcon, dbcur, media_type, trakt=0, imdb='', tmdb=0):
    """Retrieves collection entries from the trakt sync database for the specified media type and identifiers."""
    try:
        sql = ''
        if media_type == 'movies':
            if trakt == 0 and imdb == '' and tmdb == 0:
                sql = "SELECT * FROM movies_collection"
            elif imdb == '' and tmdb == 0:
                sql = f"SELECT * FROM movies_collection WHERE trakt = {trakt}"
            elif trakt == 0 and tmdb == 0:
                sql = f"SELECT * FROM movies_collection WHERE imdb = '{imdb}'"
            elif trakt == 0 and imdb == '':
                sql = f"SELECT * FROM movies_collection WHERE tmdb = {tmdb}"
            elif trakt == 0:
                sql = f"SELECT * FROM movies_collection WHERE imdb = '{imdb}' AND tmdb = {tmdb}"
            elif imdb == '':
                sql = f"SELECT * FROM movies_collection WHERE trakt = {trakt} AND tmdb = {tmdb}"
            else:
                sql = f"SELECT * FROM movies_collection WHERE trakt = {trakt} OR imdb = '{imdb}' OR tmdb = {tmdb}"
        elif media_type == 'shows':
            sql = f"SELECT * FROM shows_collection WHERE trakt = '{trakt}' AND imdb = '{imdb}' AND tmdb = '{tmdb}'"

        dbcur.execute(sql)
        return dbcur.fetchall()
    except Exception as e:
        c.log(f'Exception raised in get_collection. Error = {e}')







def table_exists(table_name) -> bool:
    """Checks if a table exists in the trakt sync database."""
    try:
        dbcon = get_connection(control.traktsyncFile, return_as_dict=True)
        dbcur = get_connection_cursor(dbcon)

        sql = f"SELECT count(*) as aantal FROM sqlite_master WHERE type='table' AND name='{table_name}'"
        dbcur.execute(sql)
        row = dbcur.fetchone()
        result = row['aantal'] != 0

        dbcon.close()
        return result

    except Exception as e:
        c.log(f'Exception raised in tables_exists. Error = {e}')
        return False


@with_db_connection(return_on_error=None, return_as_dict=True)
def insert_collection(dbcon, dbcur, collection, mediatype):
    try:
        table_name = ''

        if mediatype == 'movies':
            table_name = 'movies_collection'
        elif mediatype == 'shows':
            table_name = 'shows_collection'

        if not table_exists(table_name):
            sql = sql_dict[f'sql_create_{table_name}']
            dbcur.execute(sql)
            dbcon.commit()

        for item in collection:
            pass

            if mediatype == 'movies':
                last_collected_at = item['collected_at']
                last_updated_at = item['updated_at']
                title = item['movie']['title']
                year = item['movie']['year']
                trakt = item['movie']['ids']['trakt']
                slug = item['movie']['ids']['slug']
                imdb = item['movie']['ids']['imdb']
                tmdb = item['movie']['ids']['tmdb']
                sql = f"INSERT OR REPLACE INTO '{table_name}' Values ('{last_collected_at}', '{last_updated_at}', '{title}', {year}, {trakt}, '{slug}', '{imdb}', {tmdb})"
                dbcur.execute(sql)
                dbcon.commit()

            elif mediatype == 'shows':
                try:
                    last_collected_at = item['last_collected_at']
                    last_updated_at = item['last_updated_at']
                    seasons = item['seasons']
                    trakt = item['show']['ids']['trakt']
                    slug = item['show']['ids']['slug']
                    imdb = item['show']['ids']['imdb']
                    tmdb = item['show']['ids']['tmdb']
                    tvdb = item['show']['ids']['tvdb']
                    tvrage = item['show']['ids']['tvrage']
                    title = item['show']['title']
                    year = item['show']['year']
                    sql = f"INSERT OR REPLACE INTO '{table_name}' Values ('{last_collected_at}', '{last_updated_at}', '{title}', {year}, {trakt}, '{slug}', '{tvdb}', '{imdb}', {tmdb}, '{tvrage}')"

                    for season in seasons:
                        for episode in season['episodes']:
                            sql = f"INSERT OR REPLACE INTO seasons_collection Values ({trakt}, {tvdb}, '{imdb}', {tmdb}, {season['number']}, {episode['number']}, '{episode['collected_at']}')"

                    dbcur.execute(sql)
                    dbcon.commit()
                except Exception as e:
                    failure = traceback.format_exc()

    except Exception as e:
        failure = traceback.format_exc()
        pass


@with_db_connection(return_on_error=[], return_as_dict=True)
def get_trakt_progress(dbcon, dbcur, media_type: str, trakt_id: int = 0) -> list:
    """Retrieves progress entries from the trakt sync database for the specified media type and ID."""
    try:
        sql = f"SELECT * FROM progress WHERE media_type = '{media_type}'"
        if trakt_id:
            sql += f" AND trakt_id = {trakt_id}"


        dbcur.execute(sql)
        rows = dbcur.fetchall()
        dbcon.commit()

        return rows

    except Exception as e:
        failure = traceback.format_exc()
        return []


@with_db_connection(return_on_error=None, return_as_dict=True)
def get_episode_progress(dbcon, dbcur, imdb: str, season: int, episode: int):
    """Get the progress percentage for a specific episode from the progress table."""
    try:
        # Use showimdb column since imdb parameter is the show's IMDB ID
        sql = "SELECT resume_point FROM progress WHERE media_type = 'episode' AND showimdb = ? AND season = ? AND episode = ?"
        dbcur.execute(sql, (imdb, season, episode))
        row = dbcur.fetchone()

        if row and row['resume_point'] is not None:
            progress = float(row['resume_point'])
            return progress
        return None
    except Exception as e:
        c.log(f"[Trakt] Error getting episode progress for {imdb} S{season}E{episode}: {e}\n{traceback.format_exc()}")
        return None






@with_db_connection(return_on_error=None, return_as_dict=True)
def update_trakt_sync_table(dbcon, dbcur, key, value):
    """Updates the value in the trakt sync table."""
    try:
        sql = "INSERT OR REPLACE INTO service Values (?, ?)"
        dbcur.execute(sql, (key, value))
        _commit(dbcon)
    except Exception as e:
        c.log(f"[Trakt] Error updating sync table {key}={value}: {e}")

@with_db_connection(return_on_error=None, return_as_dict=True)
def get_trakt_sync_value(dbcon, dbcur, key):
    """Returns the value from the trakt sync SERVICE table for the given key."""
    try:
        sql = "SELECT value FROM service WHERE setting = ?"
        result = dbcur.execute(sql, (key,))
        row = result.fetchone()
        # When using dict mode (return_as_dict=True), access by column name not index
        return row['value'] if row else None
    except Exception as e:
        c.log(f"[Trakt] Error getting sync value {key}: {e}")
        return None


@with_db_connection(return_on_error=None, return_as_dict=True)
def get_trakt_table_value(dbcon, dbcur, table_name, key):
    """Returns the value from a specific trakt sync table (movies, episodes, shows, seasons, lists)."""
    try:
        sql = f"SELECT value FROM {table_name} WHERE setting = ?"
        result = dbcur.execute(sql, (key,))
        row = result.fetchone()
        return row['value'] if row else None
    except Exception as e:
        c.log(f"[Trakt] Error getting table value {table_name}.{key}: {e}")
        return None


@with_db_connection(return_on_error=[], return_as_dict=True)
def get_watch_history(dbcon, dbcur, media_type=None, trakt_id=None, limit=None, offset=0):
    """Retrieve watch history from local database (no API calls)."""
    try:
        if not table_exists('trakt_history'):
            return []

        sql = "SELECT * FROM trakt_history"
        conditions = []
        params = []

        if media_type:
            conditions.append("media_type = ?")
            params.append(media_type)

        if trakt_id:
            conditions.append("trakt_id = ?")
            params.append(trakt_id)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY watched_at DESC"

        if limit:
            sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"

        result = dbcur.execute(sql, params)
        rows = result.fetchall()

        return rows

    except Exception as e:
        c.log(f"[Trakt] Error getting watch history: {e}")
        return []


@with_db_connection(return_on_error=0, return_as_dict=True)
def get_rewatch_count(dbcon, dbcur, trakt_id, media_type='movie'):
    """Gets the number of times a user has watched a specific item."""
    try:
        if not table_exists('trakt_history'):
            return 0

        sql = "SELECT COUNT(*) as count FROM trakt_history WHERE trakt_id = ? AND media_type = ?"
        result = dbcur.execute(sql, (trakt_id, media_type))
        row = result.fetchone()

        return row['count'] if row else 0

    except Exception as e:
        c.log(f"[Trakt] Error getting rewatch count: {e}")
        return 0


@with_db_connection(return_on_error=[], return_as_dict=True)
def get_recently_watched(dbcon, dbcur, days=7, media_type=None, limit=50, offset=0):
    """Gets recently watched items from local history (no API calls)."""
    try:
        if not table_exists('trakt_history'):
            return []

        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        sql = "SELECT * FROM trakt_history WHERE watched_at >= ?"
        params = [cutoff]

        if media_type:
            sql += " AND media_type = ?"
            params.append(media_type)

        sql += " ORDER BY watched_at DESC LIMIT ? OFFSET ?"
        params.append(limit)
        params.append(offset)

        result = dbcur.execute(sql, params)
        rows = result.fetchall()

        return rows

    except Exception as e:
        c.log(f"[Trakt] Error getting recently watched: {e}")
        return []
