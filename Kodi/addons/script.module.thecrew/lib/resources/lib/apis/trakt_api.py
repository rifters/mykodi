# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file trakt_api.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 * Modern Trakt.tv API wrapper with OAuth 2.0 device flow
 * Clean separation of concerns, extensive logging, automatic token refresh
 *
 ********************************************************cm*
'''

import time
import json
from datetime import datetime
from typing import Optional, Dict, List, Any, Union
from urllib.parse import urljoin

from ..modules.crewruntime import c
from ..modules import http_client
from ..modules import keys


class TraktAuthError(Exception):
    """Raised when authentication fails or token is invalid"""
    pass


class TraktRateLimitError(Exception):
    """Raised when Trakt API rate limit is exceeded"""
    pass


class TraktAPIError(Exception):
    """Generic Trakt API error"""
    pass


class TraktAPI:
    """
    Modern Trakt.tv API wrapper for The Crew addon

    Features:
    - OAuth 2.0 device flow authentication with QR code support
    - Automatic token refresh
    - Comprehensive devmode logging
    - Clean error handling with custom exceptions
    - Session management with connection pooling
    - Account Manager integration

    API Documentation: https://trakt.docs.apiary.io/
    """

    def __init__(self):
        """Initialize Trakt API client"""
        self.name = 'Trakt'
        self.base_url = 'https://api.trakt.tv'
        self.client_id = keys.trakt_id
        self.client_secret = keys.trakt_secret
        self.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
        self.api_version = '2'

        # Use shared HTTP session with connection pooling
        self.session = http_client.get_trakt_session()

        # Load current credentials from settings
        self._load_credentials()

        if c.devmode:
            c.log('[Trakt API] Initialized', 1)
            c.log(f'[Trakt API] Authenticated: {self.is_authenticated()}', 1)

    # ========================================================================================
    # AUTHENTICATION & CREDENTIALS
    # ========================================================================================

    def _load_credentials(self):
        """Load authentication credentials from Kodi settings"""
        try:
            self.username = c.get_setting('trakt.user').strip()
            self.token = c.get_setting('trakt.token').strip()
            self.refresh = c.get_setting('trakt.refresh').strip()

            # Get token expiration (Unix timestamp)
            # Use canonical key trakt.expires_at (trakt.expires is the legacy key)
            expires_str = c.get_setting('trakt.expires_at') or c.get_setting('trakt.expires')
            try:
                self.token_expires = float(expires_str) if expires_str else 0
            except (ValueError, TypeError):
                self.token_expires = 0

            if c.devmode and self.token:
                time_left = int(self.token_expires - time.time())
                c.log(f'[Trakt API] Token expires in {time_left} seconds', 1)

        except Exception as e:
            if c.devmode:
                c.log(f'[Trakt API] Error loading credentials: {e}', 1)
            self.username = ''
            self.token = ''
            self.refresh = ''
            self.token_expires = 0

    def _save_credentials(self, username: str = '', token: str = '', refresh: str = '', expires_in: int = 0):
        """
        Save authentication credentials to Kodi settings

        Args:
            username: Trakt username
            token: Access token
            refresh: Refresh token
            expires_in: Token lifetime in seconds (default: 7776000 = 90 days)
        """
        try:
            # Calculate expiration timestamp
            if expires_in > 0:
                self.token_expires = time.time() + expires_in
            else:
                # Default to 90 days (Trakt's actual access_token lifetime is 7776000 seconds)
                self.token_expires = time.time() + 7776000

            # Save to settings — use canonical key trakt.expires_at
            c.set_setting('trakt.user', username)
            c.set_setting('trakt.token', token)
            c.set_setting('trakt.refresh', refresh)
            c.set_setting('trakt.expires_at', str(self.token_expires))
            c.set_setting('trakt.expires', '')  # clear legacy key

            # Update instance variables
            self.username = username
            self.token = token
            self.refresh = refresh

            if c.devmode:
                c.log(f'[Trakt API] Credentials saved for user: {username}', 1)
                c.log(f'[Trakt API] Token expires: {datetime.fromtimestamp(self.token_expires)}', 1)

        except Exception as e:
            if c.devmode:
                c.log(f'[Trakt API] Error saving credentials: {e}', 1)
            raise TraktAuthError(f'Failed to save credentials: {e}')

    def is_authenticated(self) -> bool:
        """
        Check if user is authenticated with valid token

        Returns:
            bool: True if authenticated, False otherwise
        """
        return bool(self.token and self.username)

    def _ensure_auth(self):
        """
        Ensure we have valid authentication before making API calls.
        Always re-reads credentials from settings (never uses stale cached values).
        Token refresh is delegated to trakt.py which holds the shared lock.

        Raises:
            TraktAuthError: If not authenticated
        """
        # Always reload fresh credentials — cached self.refresh may be stale if
        # trakt.py already did a reactive refresh (refresh token rotation means
        # the old token is consumed; using it again causes a 401 → revoke cascade).
        self._load_credentials()

        if not self.is_authenticated():
            raise TraktAuthError('Not authenticated - please authorize Trakt first')

    def authorize(self) -> bool:
        """
        Initiate OAuth 2.0 device flow authorization
        Shows QR code and user code for easy pairing

        Returns:
            bool: True if authorization successful, False otherwise
        """
        try:
            if c.devmode:
                c.log('[Trakt API] Starting device authorization flow...', 1)

            # Check if already authorized
            if self.is_authenticated():
                if c.yesnoDialog('Trakt account already authorized.\n\nRe-authorize?', 'Trakt'):
                    self.revoke()
                else:
                    return True

            # Step 1: Get device code
            device_data = self._get_device_code()
            if not device_data:
                c.infoDialog('Failed to connect to Trakt', sound=True)
                return False

            verification_url = device_data.get('verification_url', 'https://trakt.tv/activate')
            user_code = device_data.get('user_code', '')
            device_code = device_data.get('device_code', '')
            expires_in = int(device_data.get('expires_in', 600))
            interval = int(device_data.get('interval', 5))

            if c.devmode:
                c.log(f'[Trakt API] Device code: {device_code[:20]}...', 1)
                c.log(f'[Trakt API] User code: {user_code}', 1)
                c.log(f'[Trakt API] Verification URL: {verification_url}', 1)

            # Generate QR code for easy mobile scanning
            qr_path = self._generate_qr_code(verification_url)

            # Step 2: Show QR code dialog and poll for authorization
            success = self._poll_for_token(
                verification_url=verification_url,
                user_code=user_code,
                device_code=device_code,
                interval=interval,
                expires_in=expires_in,
                qr_path=qr_path
            )

            if success:
                c.infoDialog('Trakt account authorized successfully!', sound=False)
                if c.devmode:
                    c.log(f'[Trakt API] Authorization successful for user: {self.username}', 1)
                return True
            else:
                c.infoDialog('Trakt authorization failed or timed out', sound=True)
                return False

        except Exception as e:
            if c.devmode:
                c.log(f'[Trakt API] Authorization error: {e}', 1)
            c.infoDialog(f'Trakt authorization failed: {str(e)}', sound=True)
            return False

    def _get_device_code(self) -> Optional[Dict]:
        """
        Get device code for OAuth device flow

        Returns:
            dict: Device code data with verification_url, user_code, device_code, interval, expires_in
            None: If request fails
        """
        try:
            url = urljoin(self.base_url, '/oauth/device/code')
            data = {'client_id': self.client_id}

            if c.devmode:
                c.log(f'[Trakt API] POST {url}', 1)

            response = self.session.post(url, json=data, timeout=30)

            if response.status_code == 200:
                result = response.json()
                if c.devmode:
                    c.log(f'[Trakt API] Device code obtained successfully', 1)
                return result
            else:
                if c.devmode:
                    c.log(f'[Trakt API] Device code request failed: {response.status_code}', 1)
                return None

        except Exception as e:
            if c.devmode:
                c.log(f'[Trakt API] Error getting device code: {e}', 1)
            return None

    def _poll_for_token(self, verification_url: str, user_code: str, device_code: str,
                       interval: int, expires_in: int, qr_path: str = None) -> bool:
        """
        Poll Trakt API for authorization token
        Shows dialog with QR code and user code while polling

        Args:
            verification_url: URL for user to visit
            user_code: Code for user to enter
            device_code: Device code for polling
            interval: Polling interval in seconds
            expires_in: Token expiration time in seconds
            qr_path: Path to QR code image (optional)

        Returns:
            bool: True if token obtained, False if failed or timed out
        """
        try:
            # Import here to avoid circular dependency
            from ..modules import trakt as trakt_module

            # Use existing QR dialog from trakt module
            return trakt_module.show_trakt_qr_dialog(
                verification_url=verification_url,
                user_code=user_code,
                qr_path=qr_path,
                device_code=device_code,
                interval=interval,
                expires_in=expires_in
            )

        except Exception as e:
            if c.devmode:
                c.log(f'[Trakt API] Error polling for token: {e}', 1)
            return False

    def _generate_qr_code(self, url: str) -> Optional[str]:
        """
        Generate QR code for verification URL

        Args:
            url: URL to encode in QR code

        Returns:
            str: Path to QR code image file
            None: If QR code generation fails
        """
        try:
            from ..modules import utils
            return utils.make_qrcode(url, 'trakt_auth.png')
        except Exception as e:
            if c.devmode:
                c.log(f'[Trakt API] QR code generation failed: {e}', 1)
            return None

    def refresh_token(self) -> bool:
        """
        Refresh access token using refresh token.
        Delegates to trakt.py's token_refresh() which holds the shared threading lock,
        preventing races between this class and trakt.py's reactive refresh path.

        Returns:
            bool: True if refresh successful, False otherwise
        """
        try:
            # Import here to avoid circular imports at module load time
            from ..modules import trakt as trakt_module

            if c.devmode:
                c.log('[Trakt API] Delegating token refresh to trakt.py (shared lock)...', 1)

            # Build minimal headers dict that token_refresh() expects so it can
            # update the Authorization header in place after a successful refresh.
            headers = {
                'Authorization': f'Bearer {self.token}',
            }

            result = trakt_module.token_refresh(headers, '', None)

            if result is True:
                # Reload credentials from settings so self.token is current
                self._load_credentials()
                if c.devmode:
                    c.log('[Trakt API] Token refreshed successfully via trakt.py', 1)
                return True
            else:
                if c.devmode:
                    c.log(f'[Trakt API] Token refresh via trakt.py failed (result={result})', 1)
                # Do NOT call self.revoke() here — trakt.py already cleared tokens
                # and set the auth_failed flag if appropriate.
                return False

        except Exception as e:
            if c.devmode:
                c.log(f'[Trakt API] Error in refresh_token: {e}', 1)
            return False

    def revoke(self):
        """
        Revoke authorization and clear all stored credentials
        """
        try:
            if c.devmode:
                c.log('[Trakt API] Revoking authorization...', 1)

            # Optionally call Trakt revoke endpoint
            if self.token:
                try:
                    url = urljoin(self.base_url, '/oauth/revoke')
                    data = {
                        'token': self.token,
                        'client_id': self.client_id,
                        'client_secret': self.client_secret
                    }
                    self.session.post(url, json=data, timeout=10)
                except:
                    pass  # Ignore errors, we're clearing locally anyway

            # Clear credentials from settings
            self._save_credentials('', '', '', 0)

            if c.devmode:
                c.log('[Trakt API] Authorization revoked', 1)

        except Exception as e:
            if c.devmode:
                c.log(f'[Trakt API] Error revoking authorization: {e}', 1)

    # ========================================================================================
    # ACCOUNT INFORMATION (for Account Manager)
    # ========================================================================================

    def account_info(self) -> Optional[Dict]:
        """
        Get comprehensive account information for Account Manager

        Returns:
            dict: Account details with username, VIP status, stats, etc.
            None: If not authenticated or request fails
        """
        try:
            if not self.is_authenticated():
                if c.devmode:
                    c.log('[Trakt API] Cannot get account info - not authenticated', 1)
                return None

            if c.devmode:
                c.log('[Trakt API] Getting account info...', 1)

            # Get user profile
            user = self._get('/users/me')
            if not user:
                return None

            # Get user settings
            settings = self._get('/users/settings')

            # Get user stats
            stats = self._get('/users/me/stats')

            # Build account info dict
            account = {
                'active': True,
                'username': user.get('username', 'N/A'),
                'name': user.get('name', 'N/A'),
                'vip': user.get('vip', False),
                'vip_ep': user.get('vip_ep', False),
                'vip_og': user.get('vip_og', False),
                'private': user.get('private', False),
                'joined': user.get('joined_at', 'N/A'),
                'location': user.get('location', 'N/A'),
                'about': user.get('about', 'N/A')
            }

            # Add stats if available
            if stats:
                movies_stats = stats.get('movies', {})
                shows_stats = stats.get('shows', {})
                episodes_stats = stats.get('episodes', {})

                account.update({
                    'movies_collected': movies_stats.get('collected', 0),
                    'movies_watched': movies_stats.get('watched', 0),
                    'shows_collected': shows_stats.get('collected', 0),
                    'shows_watched': shows_stats.get('watched', 0),
                    'episodes_collected': episodes_stats.get('collected', 0),
                    'episodes_watched': episodes_stats.get('watched', 0),
                    'total_minutes': movies_stats.get('minutes', 0) + episodes_stats.get('minutes', 0)
                })

            # Add settings if available
            if settings:
                account.update({
                    'timezone': settings.get('user', {}).get('timezone', 'N/A'),
                    'cover_image': settings.get('user', {}).get('images', {}).get('avatar', {}).get('full', '')
                })

            if c.devmode:
                c.log(f'[Trakt API] Account info retrieved for: {account["username"]}', 1)

            return account

        except Exception as e:
            if c.devmode:
                c.log(f'[Trakt API] Error getting account info: {e}', 1)
            return None

    # ========================================================================================
    # HTTP REQUEST METHODS
    # ========================================================================================

    def _get(self, endpoint: str, params: Dict = None, auth_required: bool = True) -> Optional[Any]:
        """
        Make authenticated GET request to Trakt API

        Args:
            endpoint: API endpoint (e.g., '/users/me')
            params: Query parameters (optional)
            auth_required: Whether authentication is required (default: True)

        Returns:
            Parsed JSON response or None if request fails

        Raises:
            TraktAuthError: If auth required but not authenticated
            TraktRateLimitError: If rate limit exceeded
            TraktAPIError: For other API errors
        """
        try:
            if auth_required:
                self._ensure_auth()

            url = urljoin(self.base_url, endpoint)

            headers = {
                'Content-Type': 'application/json',
                'trakt-api-version': self.api_version,
                'trakt-api-key': self.client_id
            }

            # Add auth header if authenticated
            if self.token:
                headers['Authorization'] = f'Bearer {self.token}'

            if c.devmode:
                c.log(f'[Trakt API] GET {endpoint}', 1)
                if params:
                    c.log(f'[Trakt API] Params: {params}', 1)

            response = self.session.get(url, headers=headers, params=params, timeout=30)

            # Handle response codes
            if response.status_code == 200:
                result = response.json() if response.content else None
                if c.devmode:
                    c.log(f'[Trakt API] GET {endpoint} - Success', 1)
                return result

            elif response.status_code == 204:
                # No content (success)
                if c.devmode:
                    c.log(f'[Trakt API] GET {endpoint} - No content (204)', 1)
                return None

            elif response.status_code == 401:
                # Unauthorized - try to refresh token
                if c.devmode:
                    c.log(f'[Trakt API] GET {endpoint} - Unauthorized (401)', 1)
                if self.refresh:
                    self.refresh_token()
                    # Retry request with new token
                    return self._get(endpoint, params, auth_required)
                else:
                    raise TraktAuthError('Unauthorized - please re-authorize Trakt')

            elif response.status_code == 429:
                # Rate limit exceeded
                if c.devmode:
                    c.log(f'[Trakt API] GET {endpoint} - Rate limit exceeded (429)', 1)
                raise TraktRateLimitError('Trakt API rate limit exceeded')

            else:
                # Other error
                if c.devmode:
                    c.log(f'[Trakt API] GET {endpoint} - Error {response.status_code}', 1)
                    c.log(f'[Trakt API] Response: {response.text}', 1)
                raise TraktAPIError(f'API request failed: {response.status_code}')

        except (TraktAuthError, TraktRateLimitError, TraktAPIError):
            raise
        except Exception as e:
            if c.devmode:
                c.log(f'[Trakt API] GET {endpoint} - Exception: {e}', 1)
            return None

    def _post(self, endpoint: str, data: Dict = None, auth_required: bool = True) -> Optional[Any]:
        """
        Make authenticated POST request to Trakt API

        Args:
            endpoint: API endpoint (e.g., '/sync/history')
            data: JSON data to send
            auth_required: Whether authentication is required (default: True)

        Returns:
            Parsed JSON response or None if request fails

        Raises:
            TraktAuthError: If auth required but not authenticated
            TraktRateLimitError: If rate limit exceeded
            TraktAPIError: For other API errors
        """
        try:
            if auth_required:
                self._ensure_auth()

            url = urljoin(self.base_url, endpoint)

            headers = {
                'Content-Type': 'application/json',
                'trakt-api-version': self.api_version,
                'trakt-api-key': self.client_id
            }

            # Add auth header if authenticated
            if self.token:
                headers['Authorization'] = f'Bearer {self.token}'

            if c.devmode:
                c.log(f'[Trakt API] POST {endpoint}', 1)
                if data:
                    c.log(f'[Trakt API] Data: {json.dumps(data)[:200]}...', 1)

            response = self.session.post(url, headers=headers, json=data, timeout=30)

            # Handle response codes
            if response.status_code in [200, 201]:
                result = response.json() if response.content else None
                if c.devmode:
                    c.log(f'[Trakt API] POST {endpoint} - Success ({response.status_code})', 1)
                return result

            elif response.status_code == 204:
                # No content (success)
                if c.devmode:
                    c.log(f'[Trakt API] POST {endpoint} - No content (204)', 1)
                return {'status': 'success'}

            elif response.status_code == 401:
                # Unauthorized - try to refresh token
                if c.devmode:
                    c.log(f'[Trakt API] POST {endpoint} - Unauthorized (401)', 1)
                if self.refresh:
                    self.refresh_token()
                    # Retry request with new token
                    return self._post(endpoint, data, auth_required)
                else:
                    raise TraktAuthError('Unauthorized - please re-authorize Trakt')

            elif response.status_code == 429:
                # Rate limit exceeded
                if c.devmode:
                    c.log(f'[Trakt API] POST {endpoint} - Rate limit exceeded (429)', 1)
                raise TraktRateLimitError('Trakt API rate limit exceeded')

            else:
                # Other error
                if c.devmode:
                    c.log(f'[Trakt API] POST {endpoint} - Error {response.status_code}', 1)
                    c.log(f'[Trakt API] Response: {response.text}', 1)
                raise TraktAPIError(f'API request failed: {response.status_code}')

        except (TraktAuthError, TraktRateLimitError, TraktAPIError):
            raise
        except Exception as e:
            if c.devmode:
                c.log(f'[Trakt API] POST {endpoint} - Exception: {e}', 1)
            return None

    def _delete(self, endpoint: str, data: Dict = None, auth_required: bool = True) -> bool:
        """
        Make authenticated DELETE request to Trakt API

        Args:
            endpoint: API endpoint (e.g., '/sync/playback/123')
            data: JSON data to send (optional)
            auth_required: Whether authentication is required (default: True)

        Returns:
            bool: True if successful, False otherwise

        Raises:
            TraktAuthError: If auth required but not authenticated
            TraktRateLimitError: If rate limit exceeded
            TraktAPIError: For other API errors
        """
        try:
            if auth_required:
                self._ensure_auth()

            url = urljoin(self.base_url, endpoint)

            headers = {
                'Content-Type': 'application/json',
                'trakt-api-version': self.api_version,
                'trakt-api-key': self.client_id
            }

            # Add auth header if authenticated
            if self.token:
                headers['Authorization'] = f'Bearer {self.token}'

            if c.devmode:
                c.log(f'[Trakt API] DELETE {endpoint}', 1)

            response = self.session.delete(url, headers=headers, json=data, timeout=30)

            # Handle response codes
            if response.status_code in [200, 204]:
                if c.devmode:
                    c.log(f'[Trakt API] DELETE {endpoint} - Success ({response.status_code})', 1)
                return True

            elif response.status_code == 401:
                # Unauthorized - try to refresh token
                if c.devmode:
                    c.log(f'[Trakt API] DELETE {endpoint} - Unauthorized (401)', 1)
                if self.refresh:
                    self.refresh_token()
                    # Retry request with new token
                    return self._delete(endpoint, data, auth_required)
                else:
                    raise TraktAuthError('Unauthorized - please re-authorize Trakt')

            elif response.status_code == 429:
                # Rate limit exceeded
                if c.devmode:
                    c.log(f'[Trakt API] DELETE {endpoint} - Rate limit exceeded (429)', 1)
                raise TraktRateLimitError('Trakt API rate limit exceeded')

            else:
                # Other error
                if c.devmode:
                    c.log(f'[Trakt API] DELETE {endpoint} - Error {response.status_code}', 1)
                    c.log(f'[Trakt API] Response: {response.text}', 1)
                return False

        except (TraktAuthError, TraktRateLimitError, TraktAPIError):
            raise
        except Exception as e:
            if c.devmode:
                c.log(f'[Trakt API] DELETE {endpoint} - Exception: {e}', 1)
            return False

    # ========================================================================================
    # WATCH HISTORY & PLAYBACK
    # ========================================================================================

    def get_watched_movies(self, extended: str = 'full') -> Optional[List[Dict]]:
        """
        Get all watched movies

        Args:
            extended: Extended info level ('min', 'full', 'metadata')

        Returns:
            list: List of watched movies with metadata
        """
        endpoint = f'/users/me/watched/movies?extended={extended}'
        return self._get(endpoint)

    def get_watched_shows(self, extended: str = 'full') -> Optional[List[Dict]]:
        """
        Get all watched shows with episode details

        Args:
            extended: Extended info level ('min', 'full', 'metadata')

        Returns:
            list: List of watched shows with seasons/episodes
        """
        endpoint = f'/users/me/watched/shows?extended={extended}'
        return self._get(endpoint)

    def mark_watched(self, media_type: str, ids: Dict, watched_at: str = None,
                    season: int = None, episode: int = None) -> Optional[Dict]:
        """
        Mark item as watched

        Args:
            media_type: 'movie', 'show', 'season', or 'episode'
            ids: Dictionary of IDs (trakt, imdb, tmdb, etc.)
            watched_at: ISO 8601 timestamp (optional, defaults to now)
            season: Season number (for episode)
            episode: Episode number (for episode)

        Returns:
            dict: Response with added/existing/not_found counts
        """
        endpoint = '/sync/history'

        # Build request data
        item = {'ids': ids}

        if watched_at:
            item['watched_at'] = watched_at

        # Handle episodes
        if media_type == 'episode' and season is not None and episode is not None:
            data = {
                'shows': [{
                    'ids': ids,
                    'seasons': [{
                        'number': season,
                        'episodes': [{'number': episode}]
                    }]
                }]
            }
        elif media_type == 'season' and season is not None:
            data = {
                'shows': [{
                    'ids': ids,
                    'seasons': [{'number': season}]
                }]
            }
        else:
            data = {f'{media_type}s': [item]}

        return self._post(endpoint, data)

    def mark_unwatched(self, media_type: str, ids: Dict, season: int = None,
                      episode: int = None) -> Optional[Dict]:
        """
        Remove item from watch history

        Args:
            media_type: 'movie', 'show', 'season', or 'episode'
            ids: Dictionary of IDs (trakt, imdb, tmdb, etc.)
            season: Season number (for episode)
            episode: Episode number (for episode)

        Returns:
            dict: Response with deleted/not_found counts
        """
        endpoint = '/sync/history/remove'

        item = {'ids': ids}

        # Handle episodes
        if media_type == 'episode' and season is not None and episode is not None:
            data = {
                'shows': [{
                    'ids': ids,
                    'seasons': [{
                        'number': season,
                        'episodes': [{'number': episode}]
                    }]
                }]
            }
        elif media_type == 'season' and season is not None:
            data = {
                'shows': [{
                    'ids': ids,
                    'seasons': [{'number': season}]
                }]
            }
        else:
            data = {f'{media_type}s': [item]}

        return self._post(endpoint, data)

    def get_playback_progress(self, media_type: str = None, limit: int = 50) -> Optional[List[Dict]]:
        """
        Get playback progress for unwatched items

        Args:
            media_type: Filter by 'movies', 'episodes', or None for all
            limit: Maximum items to return (default: 50)

        Returns:
            list: Playback progress items with progress percentage and timestamps
        """
        endpoint = f'/sync/playback/{media_type}' if media_type else '/sync/playback'
        endpoint += f'?limit={limit}'
        return self._get(endpoint)

    def delete_playback_progress(self, playback_id: int) -> bool:
        """
        Delete a playback progress item

        Args:
            playback_id: Trakt playback ID

        Returns:
            bool: True if deleted successfully
        """
        endpoint = f'/sync/playback/{playback_id}'
        return self._delete(endpoint)

    # ========================================================================================
    # COLLECTION & LISTS
    # ========================================================================================

    def get_collection(self, media_type: str, extended: str = 'full') -> Optional[List[Dict]]:
        """
        Get user's collection

        Args:
            media_type: 'movies' or 'shows'
            extended: Extended info level ('min', 'full', 'metadata')

        Returns:
            list: Collection items
        """
        endpoint = f'/users/me/collection/{media_type}?extended={extended}'
        return self._get(endpoint)

    def get_watchlist(self, media_type: str = None, extended: str = 'full') -> Optional[List[Dict]]:
        """
        Get user's watchlist

        Args:
            media_type: Filter by 'movies', 'shows', 'seasons', 'episodes', or None for all
            extended: Extended info level ('min', 'full', 'metadata')

        Returns:
            list: Watchlist items
        """
        endpoint = f'/users/me/watchlist/{media_type}' if media_type else '/users/me/watchlist'
        endpoint += f'?extended={extended}'
        return self._get(endpoint)

    def get_list(self, username: str, list_slug: str) -> Optional[Dict]:
        """
        Get a specific user list

        Args:
            username: Trakt username
            list_slug: List slug/ID

        Returns:
            dict: List metadata
        """
        endpoint = f'/users/{username}/lists/{list_slug}'
        return self._get(endpoint, auth_required=False)

    def get_list_items(self, username: str, list_slug: str, extended: str = 'full') -> Optional[List[Dict]]:
        """
        Get items in a user list

        Args:
            username: Trakt username
            list_slug: List slug/ID
            extended: Extended info level

        Returns:
            list: List items
        """
        endpoint = f'/users/{username}/lists/{list_slug}/items?extended={extended}'
        return self._get(endpoint, auth_required=False)

    # ========================================================================================
    # RATINGS
    # ========================================================================================

    def add_rating(self, media_type: str, ids: Dict, rating: int,
                  rated_at: str = None, season: int = None, episode: int = None) -> Optional[Dict]:
        """
        Add or update rating for an item

        Args:
            media_type: 'movie', 'show', 'season', or 'episode'
            ids: Dictionary of IDs
            rating: Rating value (1-10)
            rated_at: ISO 8601 timestamp (optional)
            season: Season number (for episode/season)
            episode: Episode number (for episode)

        Returns:
            dict: Response with added/existing/not_found counts
        """
        endpoint = '/sync/ratings'

        item = {'ids': ids, 'rating': rating}
        if rated_at:
            item['rated_at'] = rated_at

        # Handle episodes/seasons
        if media_type == 'episode' and season is not None and episode is not None:
            data = {
                'shows': [{
                    'ids': ids,
                    'seasons': [{
                        'number': season,
                        'episodes': [{'number': episode, 'rating': rating}]
                    }]
                }]
            }
        elif media_type == 'season' and season is not None:
            data = {
                'shows': [{
                    'ids': ids,
                    'seasons': [{'number': season, 'rating': rating}]
                }]
            }
        else:
            data = {f'{media_type}s': [item]}

        return self._post(endpoint, data)

    def remove_rating(self, media_type: str, ids: Dict, season: int = None,
                     episode: int = None) -> Optional[Dict]:
        """
        Remove rating for an item

        Args:
            media_type: 'movie', 'show', 'season', or 'episode'
            ids: Dictionary of IDs
            season: Season number (for episode/season)
            episode: Episode number (for episode)

        Returns:
            dict: Response with deleted/not_found counts
        """
        endpoint = '/sync/ratings/remove'

        item = {'ids': ids}

        # Handle episodes/seasons
        if media_type == 'episode' and season is not None and episode is not None:
            data = {
                'shows': [{
                    'ids': ids,
                    'seasons': [{
                        'number': season,
                        'episodes': [{'number': episode}]
                    }]
                }]
            }
        elif media_type == 'season' and season is not None:
            data = {
                'shows': [{
                    'ids': ids,
                    'seasons': [{'number': season}]
                }]
            }
        else:
            data = {f'{media_type}s': [item]}

        return self._post(endpoint, data)

    def get_ratings(self, media_type: str = None, rating: int = None) -> Optional[List[Dict]]:
        """
        Get user's ratings

        Args:
            media_type: Filter by 'movies', 'shows', 'seasons', 'episodes', or None for all
            rating: Filter by specific rating (1-10)

        Returns:
            list: Rated items
        """
        endpoint = f'/users/me/ratings/{media_type}' if media_type else '/users/me/ratings'
        if rating:
            endpoint += f'/{rating}'
        return self._get(endpoint)

    # ========================================================================================
    # SYNC & ACTIVITIES
    # ========================================================================================

    def get_last_activities(self) -> Optional[Dict]:
        """
        Get last activity timestamps for syncing

        Returns:
            dict: Activity timestamps grouped by category
                 (all, movies, episodes, shows, seasons, comments, lists)
        """
        endpoint = '/sync/last_activities'
        return self._get(endpoint)

    def get_sync_history(self, media_type: str, limit: int = 100, page: int = 1,
                        start_at: str = None, end_at: str = None) -> Optional[List[Dict]]:
        """
        Get watch history

        Args:
            media_type: 'movies', 'shows', or 'episodes'
            limit: Items per page (default: 100)
            page: Page number (default: 1)
            start_at: ISO 8601 start date (optional)
            end_at: ISO 8601 end date (optional)

        Returns:
            list: History items
        """
        endpoint = f'/sync/history/{media_type}?limit={limit}&page={page}'
        if start_at:
            endpoint += f'&start_at={start_at}'
        if end_at:
            endpoint += f'&end_at={end_at}'
        return self._get(endpoint)

    # ========================================================================================
    # UTILITY METHODS
    # ========================================================================================

    def open_settings(self):
        """Open addon settings dialog"""
        try:
            import xbmcaddon
            xbmcaddon.Addon().openSettings()
        except Exception as e:
            if c.devmode:
                c.log(f'[Trakt API] Error opening settings: {e}', 1)
