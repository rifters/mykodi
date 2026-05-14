# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file tmdb_api.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import requests
from typing import Optional, Dict, List, Any
from datetime import datetime

from ..modules import keys
from ..modules import control
from ..modules import http_client
from ..modules.crewruntime import c


class TMDbAPI:
    """
    Modern TMDb API client with structured methods and proper error handling.

    Features:
    - Centralized API key management via keys.py
    - Session-based HTTP with connection pooling
    - DevMode logging support
    - Consistent error handling
    - Type hints for better IDE support

    Usage:
        api = TMDbAPI()
        movie = api.get_movie(tmdb_id='550')
        shows = api.discover_tv(with_networks='213', sort_by='popularity.desc')
    """

    BASE_URL = 'https://api.themoviedb.org/3'
    IMAGE_BASE_URL = 'https://image.tmdb.org/t/p'

    def __init__(self, api_key: Optional[str] = None, language: Optional[str] = None):
        """
        Initialize TMDb API client.

        Args:
            api_key: Optional custom API key. Falls back to settings then keys.py
            language: Optional language code. Falls back to addon settings
        """
        # API Key priority: custom > user setting > protected default
        self.api_key = (
            api_key or
            control.setting('tm.personal_user') or
            control.setting('tm.user') or
            keys.tmdb_key
        )

        # Language setup
        self.language = language or control.apiLanguage().get('tmdb', 'en-US')

        # HTTP session with connection pooling
        self.session = http_client.HTTPClient.get_session('tmdb')

        # Today's date for date-based queries
        self.today = datetime.now().strftime('%Y-%m-%d')

        c.log(f"[TMDbAPI] Initialized with language={self.language}")


    # ============================================================================
    # Core Request Methods
    # ============================================================================

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
        """
        Make GET request to TMDb API.

        Args:
            endpoint: API endpoint (e.g., '/movie/550')
            params: Query parameters

        Returns:
            JSON response or None on error
        """
        url = f"{self.BASE_URL}{endpoint}"

        # Merge API key with other params
        request_params = {'api_key': self.api_key}
        if params:
            request_params.update(params)

        try:
            response = self.session.get(url, params=request_params, timeout=10)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                c.log(f"[TMDbAPI] Authentication failed - invalid API key", 1)
                return None
            elif response.status_code == 404:
                if c.devmode:
                    c.log(f"[TMDbAPI] Resource not found: {endpoint}", 1)
                return None
            else:
                c.log(f"[TMDbAPI] Request failed: {response.status_code} - {url}", 1)
                return None

        except requests.exceptions.Timeout:
            c.log(f"[TMDbAPI] Request timeout: {url}", 1)
            return None
        except Exception as e:
            c.log(f"[TMDbAPI] Request error: {str(e)}", 1)
            return None


    # ============================================================================
    # Movie Methods
    # ============================================================================

    def get_movie(self, tmdb_id: str, append_to_response: Optional[str] = None) -> Optional[Dict]:
        """
        Get detailed movie information.

        Args:
            tmdb_id: TMDb movie ID
            append_to_response: Comma-separated list of additional data (credits, videos, etc.)

        Returns:
            Movie details dictionary or None
        """
        params = {'language': self.language}
        if append_to_response:
            params['append_to_response'] = append_to_response

        return self._get(f'/movie/{tmdb_id}', params)


    def search_movie(self, query: str, page: int = 1, include_adult: bool = False) -> Optional[Dict]:
        """
        Search for movies by title.

        Args:
            query: Search query
            page: Page number
            include_adult: Include adult content

        Returns:
            Search results dictionary or None
        """
        params = {
            'query': query,
            'page': page,
            'include_adult': include_adult,
            'language': self.language
        }
        return self._get('/search/movie', params)


    def discover_movies(self, **filters) -> Optional[Dict]:
        """
        Discover movies with filters.

        Supports all TMDb discover filters:
            with_genres, with_original_language, with_origin_country,
            sort_by, year, primary_release_year, vote_average.gte,
            vote_count.gte, release_date.gte, release_date.lte, etc.

        Args:
            **filters: TMDb discover filter parameters

        Returns:
            Discovery results dictionary or None
        """
        params = {'language': self.language}
        params.update(filters)
        return self._get('/discover/movie', params)


    def get_popular_movies(self, page: int = 1) -> Optional[Dict]:
        """Get currently popular movies."""
        return self._get('/movie/popular', {'language': self.language, 'page': page})


    def get_top_rated_movies(self, page: int = 1) -> Optional[Dict]:
        """Get top rated movies."""
        return self._get('/movie/top_rated', {'language': self.language, 'page': page})


    def get_now_playing_movies(self, page: int = 1, region: str = 'US') -> Optional[Dict]:
        """Get movies currently in theaters."""
        return self._get('/movie/now_playing', {'language': self.language, 'page': page, 'region': region})


    def get_upcoming_movies(self, page: int = 1, region: str = 'US') -> Optional[Dict]:
        """Get upcoming movies."""
        return self._get('/movie/upcoming', {'language': self.language, 'page': page, 'region': region})


    def get_trending_movies(self, time_window: str = 'week') -> Optional[Dict]:
        """
        Get trending movies.

        Args:
            time_window: 'day' or 'week'
        """
        return self._get(f'/trending/movie/{time_window}', {'api_key': self.api_key})


    def get_movie_similar(self, tmdb_id: str, page: int = 1) -> Optional[Dict]:
        """Get similar movies."""
        return self._get(f'/movie/{tmdb_id}/similar', {'page': page})


    def get_movie_recommendations(self, tmdb_id: str, page: int = 1) -> Optional[Dict]:
        """Get recommended movies based on a movie."""
        return self._get(f'/movie/{tmdb_id}/recommendations', {'language': self.language, 'page': page})


    # ============================================================================
    # TV Show Methods
    # ============================================================================

    def get_tv(self, tmdb_id: str, append_to_response: Optional[str] = None) -> Optional[Dict]:
        """
        Get detailed TV show information.

        Args:
            tmdb_id: TMDb TV show ID
            append_to_response: Comma-separated list (aggregate_credits, content_ratings, external_ids, etc.)

        Returns:
            TV show details dictionary or None
        """
        params = {'language': self.language}
        if append_to_response:
            params['append_to_response'] = append_to_response

        return self._get(f'/tv/{tmdb_id}', params)


    def get_tv_season(self, tmdb_id: str, season_number: int) -> Optional[Dict]:
        """Get TV season details including episodes."""
        return self._get(f'/tv/{tmdb_id}/season/{season_number}', {'language': self.language})


    def get_tv_episode(self, tmdb_id: str, season: int, episode: int) -> Optional[Dict]:
        """Get specific TV episode details."""
        return self._get(f'/tv/{tmdb_id}/season/{season}/episode/{episode}', {'language': self.language})


    def search_tv(self, query: str, page: int = 1, include_adult: bool = False) -> Optional[Dict]:
        """
        Search for TV shows by title.

        Args:
            query: Search query
            page: Page number
            include_adult: Include adult content

        Returns:
            Search results dictionary or None
        """
        params = {
            'query': query,
            'page': page,
            'include_adult': include_adult,
            'language': self.language
        }
        return self._get('/search/tv', params)


    def discover_tv(self, **filters) -> Optional[Dict]:
        """
        Discover TV shows with filters.

        Supports all TMDb discover filters:
            with_genres, with_networks, with_origin_country, with_original_language,
            sort_by, first_air_date_year, first_air_date.gte, first_air_date.lte,
            vote_average.gte, vote_count.gte, with_status, etc.

        Args:
            **filters: TMDb discover filter parameters

        Returns:
            Discovery results dictionary or None
        """
        params = {'language': self.language}
        params.update(filters)
        return self._get('/discover/tv', params)


    def get_popular_tv(self, page: int = 1) -> Optional[Dict]:
        """Get currently popular TV shows."""
        return self._get('/tv/popular', {'language': self.language, 'page': page})


    def get_top_rated_tv(self, page: int = 1) -> Optional[Dict]:
        """Get top rated TV shows."""
        return self._get('/tv/top_rated', {'language': self.language, 'page': page})


    def get_on_the_air_tv(self, page: int = 1) -> Optional[Dict]:
        """Get TV shows currently airing."""
        return self._get('/tv/on_the_air', {'language': self.language, 'page': page})


    def get_airing_today_tv(self, page: int = 1) -> Optional[Dict]:
        """Get TV shows airing today."""
        return self._get('/tv/airing_today', {'language': self.language, 'page': page})


    def get_trending_tv(self, time_window: str = 'week') -> Optional[Dict]:
        """
        Get trending TV shows.

        Args:
            time_window: 'day' or 'week'
        """
        return self._get(f'/trending/tv/{time_window}', {'api_key': self.api_key})


    def get_tv_similar(self, tmdb_id: str, page: int = 1) -> Optional[Dict]:
        """Get similar TV shows."""
        return self._get(f'/tv/{tmdb_id}/similar', {'page': page})


    def get_tv_recommendations(self, tmdb_id: str, page: int = 1) -> Optional[Dict]:
        """Get recommended TV shows based on a show."""
        return self._get(f'/tv/{tmdb_id}/recommendations', {'language': self.language, 'page': page})


    # ============================================================================
    # Search & Lookup Methods
    # ============================================================================

    def find_by_external_id(self, external_id: str, external_source: str = 'imdb_id') -> Optional[Dict]:
        """
        Find media by external ID (IMDb, TVDB, etc.).

        Args:
            external_id: External ID (e.g., 'tt0111161')
            external_source: Source type (imdb_id, tvdb_id, freebase_mid, etc.)

        Returns:
            Results dictionary with movie_results, tv_results, etc.
        """
        return self._get(f'/find/{external_id}', {'external_source': external_source})


    def search_person(self, query: str, page: int = 1) -> Optional[Dict]:
        """Search for people (actors, directors, etc.)."""
        params = {
            'query': query,
            'page': page,
            'include_adult': False,
            'language': self.language
        }
        return self._get('/search/person', params)


    def get_person(self, person_id: str) -> Optional[Dict]:
        """Get person details."""
        return self._get(f'/person/{person_id}', {'language': self.language})


    def get_person_tv_credits(self, person_id: str) -> Optional[Dict]:
        """Get person's TV credits."""
        return self._get(f'/person/{person_id}/tv_credits', {'language': self.language})


    def get_person_movie_credits(self, person_id: str) -> Optional[Dict]:
        """Get person's movie credits."""
        return self._get(f'/person/{person_id}/movie_credits', {'language': self.language})


    def get_trending_people(self, time_window: str = 'day') -> Optional[Dict]:
        """
        Get trending people.

        Args:
            time_window: 'day' or 'week'
        """
        return self._get(f'/trending/person/{time_window}', {'language': self.language})


    # ============================================================================
    # Helper Methods
    # ============================================================================

    def get_image_url(self, path: str, size: str = 'original') -> str:
        """
        Build full image URL from TMDb path.

        Args:
            path: Image path from TMDb (e.g., '/abc123.jpg')
            size: Image size (w92, w154, w185, w342, w500, w780, original, etc.)

        Returns:
            Full image URL
        """
        if not path:
            return ''
        return f"{self.IMAGE_BASE_URL}/{size}{path}"


    def get_configuration(self) -> Optional[Dict]:
        """Get TMDb API configuration (image sizes, base URLs, etc.)."""
        return self._get('/configuration', {})


# Convenience function for quick access
def get_tmdb_api() -> TMDbAPI:
    """Get a TMDbAPI instance with default settings."""
    return TMDbAPI()
