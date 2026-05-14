# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file fanart_api.py
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
from ..modules import cache
from ..modules.crewruntime import c


class FanartAPI:
    """
    Modern Fanart.tv API client with structured methods and proper error handling.

    Features:
    - Centralized API key management via keys.py
    - Session-based HTTP with connection pooling
    - Automatic caching of artwork
    - DevMode logging support
    - Consistent error handling
    - Type hints for better IDE support

    Usage:
        api = FanartAPI()
        artwork = api.get_tv_artwork(tvdb_id='121361')
        poster = artwork.get('tvposter', [{}])[0].get('url')
    """

    # Use HTTP instead of HTTPS to match working legacy code (modules/fanart.py)
    BASE_URL = 'http://webservice.fanart.tv/v3'
    TV_ENDPOINT = '/tv'
    MOVIE_ENDPOINT = '/movies'

    def __init__(self, api_key: Optional[str] = None, client_key: Optional[str] = None):
        """
        Initialize Fanart.tv API client.

        Args:
            api_key: Optional custom API key. Falls back to keys.py
            client_key: Optional personal client key for VIP access
        """
        # Always use protected API key from keys.py for project key
        self.api_key = api_key or keys.fanart_key

        # Client key from user settings for VIP features
        self.client_key = client_key or control.setting('fanart.tv.user') or ''

        # HTTP session with connection pooling
        self.session = http_client.HTTPClient.get_session('fanart')

        c.log(f"[FanartAPI] Initialized (VIP: {bool(self.client_key)})")


    # ============================================================================
    # Core Request Methods
    # ============================================================================

    def _get(self, endpoint: str) -> Optional[Any]:
        """
        Make GET request to Fanart.tv API.

        Args:
            endpoint: Full API endpoint URL

        Returns:
            JSON response or None on error
        """
        headers = {'api-key': self.api_key}
        if self.client_key:
            headers['client-key'] = self.client_key

        try:
            response = self.session.get(endpoint, headers=headers, timeout=10)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                c.log(f"[FanartAPI] Authentication failed - invalid API key", 1)
                return None
            elif response.status_code == 404:
                if c.devmode:
                    c.log(f"[FanartAPI] Resource not found: {endpoint}", 1)
                return None
            elif response.status_code == 429:
                c.log(f"[FanartAPI] Rate limit exceeded", 1)
                return None
            else:
                c.log(f"[FanartAPI] Request failed: {response.status_code} - {endpoint}", 1)
                # Log response body for debugging
                if c.devmode:
                    try:
                        c.log(f"[FanartAPI] Response: {response.text[:500]}", 1)
                    except:
                        pass
                return None

        except requests.exceptions.Timeout:
            c.log(f"[FanartAPI] Request timeout: {endpoint}", 1)
            return None
        except Exception as e:
            c.log(f"[FanartAPI] Request error: {str(e)}", 1)
            return None


    def _get_cached(self, cache_key: str, endpoint: str, cache_hours: int = 168) -> Optional[Any]:
        """
        Get artwork with caching.

        Args:
            cache_key: Unique cache key (not used - cache module auto-generates keys)
            endpoint: API endpoint
            cache_hours: Hours to cache (default: 7 days)

        Returns:
            Cached or fresh JSON response
        """
        # Cache module automatically generates key from function + args
        # Don't pass cache_key as an argument to _get()
        cached = cache.get(self._get, cache_hours, endpoint)
        return cached


    # ============================================================================
    # TV Show Artwork Methods
    # ============================================================================

    def get_tv_artwork(self, tvdb_id: str, language: str = 'en', use_cache: bool = True) -> Dict[str, Any]:
        """
        Get TV show artwork from Fanart.tv.

        Args:
            tvdb_id: TVDB ID
            language: Preferred language code
            use_cache: Whether to use caching

        Returns:
            Dictionary with artwork types:
            {
                'tvposter': [list of posters],
                'showbackground': [list of backgrounds],
                'tvbanner': [list of banners],
                'hdtvlogo': [list of HD logos],
                'clearlogo': [list of clear logos],
                'hdclearart': [list of HD clear art],
                'clearart': [list of clear art],
                'tvthumb': [list of thumbnails/landscapes]
            }
        """
        if not tvdb_id or tvdb_id == '0':
            return {}

        url = f"{self.BASE_URL}{self.TV_ENDPOINT}/{tvdb_id}"

        if use_cache:
            result = self._get_cached(f'fanart_tv_{tvdb_id}', url)
        else:
            result = self._get(url)

        if not result or isinstance(result, dict) and result.get('status') == 'error':
            return {}

        return result


    def get_tv_poster(self, tvdb_id: str, language: str = 'en') -> str:
        """
        Get best TV show poster URL.

        Args:
            tvdb_id: TVDB ID
            language: Preferred language code

        Returns:
            Poster URL or empty string
        """
        artwork = self.get_tv_artwork(tvdb_id, language)
        return self._extract_best_artwork(artwork, 'tvposter', language)


    def get_tv_background(self, tvdb_id: str, language: str = 'en') -> str:
        """Get best TV show background/fanart URL."""
        artwork = self.get_tv_artwork(tvdb_id, language)
        return self._extract_best_artwork(artwork, 'showbackground', language)


    def get_tv_banner(self, tvdb_id: str, language: str = 'en') -> str:
        """Get best TV show banner URL."""
        artwork = self.get_tv_artwork(tvdb_id, language)
        return self._extract_best_artwork(artwork, 'tvbanner', language)


    def get_tv_logo(self, tvdb_id: str, language: str = 'en') -> str:
        """Get best TV show logo URL (prefers HD)."""
        artwork = self.get_tv_artwork(tvdb_id, language)
        # Try HD first, fallback to regular
        url = self._extract_best_artwork(artwork, 'hdtvlogo', language)
        if not url:
            url = self._extract_best_artwork(artwork, 'clearlogo', language)
        return url


    def get_tv_clearart(self, tvdb_id: str, language: str = 'en') -> str:
        """Get best TV show clear art URL (prefers HD)."""
        artwork = self.get_tv_artwork(tvdb_id, language)
        # Try HD first, fallback to regular
        url = self._extract_best_artwork(artwork, 'hdclearart', language)
        if not url:
            url = self._extract_best_artwork(artwork, 'clearart', language)
        return url


    def get_tv_landscape(self, tvdb_id: str, language: str = 'en') -> str:
        """Get best TV show landscape/thumb URL."""
        artwork = self.get_tv_artwork(tvdb_id, language)
        # Try tvthumb first, fallback to showbackground
        url = self._extract_best_artwork(artwork, 'tvthumb', language)
        if not url:
            url = self._extract_best_artwork(artwork, 'showbackground', language)
        return url


    # ============================================================================
    # Movie Artwork Methods
    # ============================================================================

    def get_movie_artwork(self, imdb_id: str, language: str = 'en', use_cache: bool = True) -> Dict[str, Any]:
        """
        Get movie artwork from Fanart.tv.

        Args:
            imdb_id: IMDb ID (with or without 'tt' prefix)
            language: Preferred language code
            use_cache: Whether to use caching

        Returns:
            Dictionary with artwork types:
            {
                'movieposter': [list of posters],
                'moviebackground': [list of backgrounds],
                'moviebanner': [list of banners],
                'hdmovielogo': [list of HD logos],
                'movielogo': [list of logos],
                'hdmovieclearart': [list of HD clear art],
                'movieclearart': [list of clear art],
                'moviedisc': [list of disc art],
                'moviethumb': [list of thumbnails]
            }
        """
        if not imdb_id or imdb_id == '0':
            return {}

        # Ensure IMDb ID has 'tt' prefix
        if not imdb_id.startswith('tt'):
            imdb_id = f'tt{imdb_id}'

        url = f"{self.BASE_URL}{self.MOVIE_ENDPOINT}/{imdb_id}"

        if use_cache:
            result = self._get_cached(f'fanart_movie_{imdb_id}', url)
        else:
            result = self._get(url)

        if not result or isinstance(result, dict) and result.get('status') == 'error':
            return {}

        return result


    def get_movie_poster(self, imdb_id: str, language: str = 'en') -> str:
        """Get best movie poster URL."""
        artwork = self.get_movie_artwork(imdb_id, language)
        return self._extract_best_artwork(artwork, 'movieposter', language)


    def get_movie_background(self, imdb_id: str, language: str = 'en') -> str:
        """Get best movie background/fanart URL."""
        artwork = self.get_movie_artwork(imdb_id, language)
        return self._extract_best_artwork(artwork, 'moviebackground', language)


    def get_movie_logo(self, imdb_id: str, language: str = 'en') -> str:
        """Get best movie logo URL (prefers HD)."""
        artwork = self.get_movie_artwork(imdb_id, language)
        # Try HD first, fallback to regular
        url = self._extract_best_artwork(artwork, 'hdmovielogo', language)
        if not url:
            url = self._extract_best_artwork(artwork, 'movielogo', language)
        return url


    def get_movie_clearart(self, imdb_id: str, language: str = 'en') -> str:
        """Get best movie clear art URL (prefers HD)."""
        artwork = self.get_movie_artwork(imdb_id, language)
        # Try HD first, fallback to regular
        url = self._extract_best_artwork(artwork, 'hdmovieclearart', language)
        if not url:
            url = self._extract_best_artwork(artwork, 'movieclearart', language)
        return url


    def get_movie_disc(self, imdb_id: str, language: str = 'en') -> str:
        """Get best movie disc art URL."""
        artwork = self.get_movie_artwork(imdb_id, language)
        return self._extract_best_artwork(artwork, 'moviedisc', language)


    # ============================================================================
    # Helper Methods
    # ============================================================================

    def _extract_best_artwork(self, artwork_dict: Dict, key: str, language: str) -> str:
        """
        Extract best artwork URL from results.

        Prioritizes:
        1. User's language
        2. English (en)
        3. Language-neutral (00 or empty)
        4. Any available

        Args:
            artwork_dict: Full artwork dictionary
            key: Artwork type key
            language: Preferred language

        Returns:
            Best artwork URL or empty string
        """
        items = artwork_dict.get(key, [])
        if not items:
            return ''

        # Sort by language preference
        sorted_items = sorted(
            items,
            key=lambda x: (
                x.get('lang') != language,  # Preferred language first
                x.get('lang') != 'en',       # English second
                x.get('lang') not in ['00', ''],  # Neutral third
            )
        )

        # Get URL from best match
        if sorted_items:
            best = sorted_items[0]
            if isinstance(best, dict):
                return best.get('url', '')
            elif isinstance(best, str):
                return best

        return ''


    def get_all_tv_artwork_urls(self, tvdb_id: str, language: str = 'en') -> Dict[str, str]:
        """
        Get all TV artwork URLs in a simple dictionary.

        Returns:
            {
                'poster': 'url',
                'fanart': 'url',
                'banner': 'url',
                'clearlogo': 'url',
                'clearart': 'url',
                'landscape': 'url'
            }
        """
        return {
            'poster': self.get_tv_poster(tvdb_id, language),
            'fanart': self.get_tv_background(tvdb_id, language),
            'banner': self.get_tv_banner(tvdb_id, language),
            'clearlogo': self.get_tv_logo(tvdb_id, language),
            'clearart': self.get_tv_clearart(tvdb_id, language),
            'landscape': self.get_tv_landscape(tvdb_id, language)
        }


    def get_all_movie_artwork_urls(self, imdb_id: str, language: str = 'en') -> Dict[str, str]:
        """
        Get all movie artwork URLs in a simple dictionary.

        Returns:
            {
                'poster': 'url',
                'fanart': 'url',
                'clearlogo': 'url',
                'clearart': 'url',
                'disc': 'url'
            }
        """
        return {
            'poster': self.get_movie_poster(imdb_id, language),
            'fanart': self.get_movie_background(imdb_id, language),
            'clearlogo': self.get_movie_logo(imdb_id, language),
            'clearart': self.get_movie_clearart(imdb_id, language),
            'disc': self.get_movie_disc(imdb_id, language)
        }


# Convenience function for quick access
def get_fanart_api() -> FanartAPI:
    """Get a FanartAPI instance with default settings."""
    return FanartAPI()
