# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file tvdb_api.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import requests
from typing import Optional, Dict, Any

from ..modules import keys
from ..modules import control
from ..modules import http_client
from ..modules.crewruntime import c


class TVDbAPI:
    """
    Modern TVDb API client with structured methods and proper error handling.

    Features:
    - Centralized API key management via keys.py
    - Session-based HTTP with connection pooling
    - DevMode logging support
    - Consistent error handling
    - Type hints for better IDE support

    Usage:
        api = TVDbAPI()
        series = api.get_series(tvdb_id='121361')
        episodes = api.get_series_episodes(tvdb_id='121361')
    """

    # Use v3 API - v4 requires different API keys
    BASE_URL = 'https://api.thetvdb.com'

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize TVDb API client.

        Args:
            api_key: Optional custom API key. Falls back to settings then keys.py
        """
        # API Key priority: custom > user setting > protected default
        self.api_key = (
            api_key or
            control.setting('tvdb.user') or
            keys.tvdb_key
        )

        # HTTP session with connection pooling
        self.session = http_client.HTTPClient.get_session('tvdb')

        # Authentication token (TVDb v4 requires login)
        self.token = None
        self._authenticate()

        c.log(f"[TVDbAPI] Initialized")


    # ============================================================================
    # Authentication
    # ============================================================================

    def _authenticate(self) -> bool:
        """
        Authenticate with TVDb API to get bearer token.

        Returns:
            True if successful, False otherwise
        """
        url = f"{self.BASE_URL}/login"

        try:
            response = self.session.post(
                url,
                json={'apikey': self.api_key},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                # v3 returns token directly, not nested in 'data'
                self.token = data.get('token')
                if self.token:
                    if c.devmode:
                        c.log("[TVDbAPI] Authentication successful (v3)", 1)
                    return True

            c.log(f"[TVDbAPI] Authentication failed: {response.status_code}", 1)
            # Log response body for debugging
            try:
                error_body = response.json()
                c.log(f"[TVDbAPI] Auth error response: {error_body}", 1)
            except:
                c.log(f"[TVDbAPI] Auth error response (text): {response.text[:200]}", 1)
            return False

        except Exception as e:
            c.log(f"[TVDbAPI] Authentication error: {str(e)}", 1)
            return False


    # ============================================================================
    # Core Request Methods
    # ============================================================================

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
        """
        Make GET request to TVDb API.

        Args:
            endpoint: API endpoint (e.g., '/series/121361')
            params: Query parameters

        Returns:
            JSON response data or None on error
        """
        if not self.token:
            c.log("[TVDbAPI] Not authenticated", 1)
            return None

        url = f"{self.BASE_URL}{endpoint}"
        headers = {'Authorization': f'Bearer {self.token}'}

        try:
            response = self.session.get(url, params=params, headers=headers, timeout=10)

            if response.status_code == 200:
                return response.json().get('data')
            elif response.status_code == 401:
                if c.devmode:
                    c.log("[TVDbAPI] Token expired, re-authenticating...", 1)
                if self._authenticate():
                    # Retry with new token
                    headers = {'Authorization': f'Bearer {self.token}'}
                    response = self.session.get(url, params=params, headers=headers, timeout=10)
                    if response.status_code == 200:
                        return response.json().get('data')
                return None
            elif response.status_code == 404:
                if c.devmode:
                    c.log(f"[TVDbAPI] Resource not found: {endpoint}", 1)
                return None
            else:
                c.log(f"[TVDbAPI] Request failed: {response.status_code} - {url}", 1)
                return None

        except requests.exceptions.Timeout:
            c.log(f"[TVDbAPI] Request timeout: {url}", 1)
            return None
        except Exception as e:
            c.log(f"[TVDbAPI] Request error: {str(e)}", 1)
            return None


    # ============================================================================
    # Series Methods
    # ============================================================================

    def get_series(self, tvdb_id: str) -> Optional[Dict]:
        """
        Get series details.

        Args:
            tvdb_id: TVDb series ID

        Returns:
            Series details dictionary or None
        """
        return self._get(f'/series/{tvdb_id}')


    def get_series_episodes(self, tvdb_id: str, season: Optional[int] = None, page: int = 1) -> Optional[Dict]:
        """
        Get episodes for a series.

        Args:
            tvdb_id: TVDb series ID
            season: Optional season number filter
            page: Page number for pagination (v3 uses 1-based)

        Returns:
            Episodes dictionary or None
        """
        # v3 uses query endpoint for episodes
        params = {}
        if season is not None:
            params['airedSeason'] = season

        endpoint = f'/series/{tvdb_id}/episodes/query'
        if params:
            return self._get(endpoint, params)
        else:
            return self._get(f'/series/{tvdb_id}/episodes')


    def get_episode(self, episode_id: str) -> Optional[Dict]:
        """
        Get specific episode details.

        Args:
            episode_id: TVDb episode ID

        Returns:
            Episode details dictionary or None
        """
        return self._get(f'/episodes/{episode_id}')


    def search_series(self, query: str) -> Optional[Dict]:
        """
        Search for series by name.

        Args:
            query: Search query

        Returns:
            Search results or None
        """
        return self._get('/search/series', {'name': query})


    def get_series_artworks(self, tvdb_id: str) -> Optional[Dict]:
        """
        Get artwork for a series (posters, banners, backgrounds, etc.).

        Args:
            tvdb_id: TVDb series ID

        Returns:
            Artwork dictionary or None
        """
        # v3 uses 'images' endpoint, not 'artworks'
        return self._get(f'/series/{tvdb_id}/images')


    # ============================================================================
    # Season Methods
    # ============================================================================

    def get_season(self, season_id: str) -> Optional[Dict]:
        """
        Get season details.

        Args:
            season_id: TVDb season ID

        Returns:
            Season details dictionary or None
        """
        # v3 doesn't have dedicated season endpoint
        # Use episodes query with season filter instead
        return None


    # ============================================================================
    # Helper Methods
    # ============================================================================

    def get_image_url(self, image_path: str) -> str:
        """
        Build full image URL from TVDb path.

        Args:
            image_path: Image path from TVDb

        Returns:
            Full image URL
        """
        if not image_path:
            return ''

        # TVDb returns full URLs
        if image_path.startswith('http'):
            return image_path

        # Legacy paths need base URL (v3 uses banners subdomain)
        return f"https://www.thetvdb.com/banners/{image_path}"


# Convenience function for quick access
def get_tvdb_api() -> TVDbAPI:
    """Get a TVDbAPI instance with default settings."""
    return TVDbAPI()
