# -*- coding: utf-8 -*-
'''
 ***********************************************************
 * The Crew Add-on - Episode Model
 *
 * @package script.module.thecrew
 *
 * @copyright (c) 2025, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ***********************************************************
'''

import json
from .tv_item import TVItem
from ..modules import cache
from ..modules import http_client
from ..modules.crewruntime import c


class Episode(TVItem):
    """
    Represents a TV episode.
    Used for episode-level listings like "Next Episodes" or "In Progress Episodes".
    """

    def __init__(self, data=None):
        """
        Initialize episode instance.

        Args:
            data (dict, optional): Dictionary containing episode metadata
        """
        super().__init__(data)

        self.mediatype = 'episode'

        # Episode identifiers
        self.season = 0
        self.episode = 0

        # Parent show info
        self.tvshowtitle = ''
        self.showimdb = '0'
        self.showtmdb = '0'
        self.showtvdb = '0'
        self.showtrakt = '0'

        # Episode-specific metadata
        self.first_aired = ''
        self.unaired = False

        # Episode artwork (in addition to show artwork)
        self.season_poster = '0'  # Season-specific poster
        # self.thumb inherited from TVItem (episode still)

        # Progress tracking
        self.resume_point = 0  # Resume time in seconds
        self.last_watched_at = None  # Timestamp

        # Cast and crew
        self.castwiththumb = []  # List of dicts: [{name, role, thumbnail}]
        self.director = ''  # String of director names
        self.writer = ''  # String of writer names

        if data:
            self.load_from_dict(data)

    def load_from_dict(self, data):
        """
        Load episode properties from dictionary.

        Args:
            data (dict): Dictionary containing episode metadata
        """
        # Load base properties
        super().load_from_dict(data)

        # Episode identifiers
        self.season = int(data.get('season', 0))
        self.episode = int(data.get('episode', 0))

        # Parent show info
        self.tvshowtitle = data.get('tvshowtitle', '')
        self.showimdb = str(data.get('showimdb', '0'))
        self.showtmdb = str(data.get('showtmdb', '0'))
        self.showtvdb = str(data.get('showtvdb', '0'))
        self.showtrakt = str(data.get('showtrakt', '0'))

        # Episode-specific
        self.first_aired = data.get('first_aired', data.get('premiered', ''))
        self.premiered = self.first_aired  # Alias
        self.unaired = data.get('unaired', False)

        # Episode artwork
        self.season_poster = data.get('season_poster', '0')

        # Progress
        self.resume_point = float(data.get('resume_point', 0))
        self.last_watched_at = data.get('last_watched_at') or data.get('_last_watched')

        # Cast and crew
        self.castwiththumb = data.get('castwiththumb', [])
        self.director = data.get('director', '')
        self.writer = data.get('writer', '')

    def to_dict(self):
        """
        Convert episode to dictionary for Kodi ListItem.

        Returns:
            dict: Dictionary representation of episode
        """
        d = super().to_dict()
        d.update({
            'season': self.season,
            'episode': self.episode,
            'tvshowtitle': self.tvshowtitle,
            'showimdb': self.showimdb,
            'showtmdb': self.showtmdb,
            'showtvdb': self.showtvdb,
            'showtrakt': self.showtrakt,
            'first_aired': self.first_aired,
            'unaired': self.unaired,
            'season_poster': self.season_poster,
            'resume_point': self.resume_point,
            'last_watched_at': self.last_watched_at,
            'castwiththumb': self.castwiththumb,
            'director': self.director,
            'writer': self.writer,
        })
        return d

    def fetch_tmdb_metadata(self, episode_cache_dict=None, metadata_cache_dict=None):
        """
        Fetch episode metadata from TMDB.
        Requires show TMDB ID, season, and episode number.

        Uses smart caching to avoid repeated API calls for non-existent episodes.
        Cache is invalidated when user watches episodes or after 7 days.

        Args:
            episode_cache_dict: Optional pre-loaded cache dict for batch performance
            metadata_cache_dict: Optional pre-loaded metadata cache from cache_get_many()

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Need show TMDB ID
            if self.showtmdb == '0':
                c.log(f"[Episode] Cannot fetch metadata - no show TMDB ID")
                return False

            if self.season == 0 or self.episode == 0:
                c.log(f"[Episode] Cannot fetch metadata - invalid season/episode")
                return False

            # Check smart cache first (validates against Trakt activity timestamps)
            from resources.lib.modules import trakt
            cache_result = trakt.check_next_episode_cache(int(self.showtmdb), self.season, self.episode, cache_dict=episode_cache_dict)

            if cache_result is not None:
                # Cache hit - use cached result
                if cache_result is False:
                    # Episode confirmed not to exist on TMDB (cached 404)
                    c.log(f"[Episode] Using cached 404 for show {self.showtmdb} S{self.season:02d}E{self.episode:02d}")
                    return False
                # If cache_result is True, continue to fetch (we need the full metadata)
                # c.log(f"[Episode] Cache indicates episode exists, fetching metadata...")

            # Build URL for cache key
            url = f"{self.tmdb_link}tv/{self.showtmdb}/season/{self.season}/episode/{self.episode}?api_key={self.tmdb_user}&language={self.lang}&append_to_response=credits,images"

            # Check if metadata was pre-loaded via batch
            response = None
            if metadata_cache_dict:
                cache_key = Episode.get_metadata_cache_key(self.showtmdb, self.season, self.episode, self.lang)
                cached_row = metadata_cache_dict.get(cache_key)
                if cached_row:
                    # Parse cached value
                    value = cached_row.get('value')
                    if isinstance(value, str):
                        try:
                            response = json.loads(value)
                        except Exception:
                            response = value
                    else:
                        response = value

            # If not in batch cache, fetch individually
            if not response:
                response = cache.get(http_client.tmdb_get_json, 24, url, 16)

            if not response:
                c.log(f"[Episode] Failed to fetch TMDB data for S{self.season:02d}E{self.episode:02d}")
                # Cache this negative result to avoid repeated API calls
                trakt.update_next_episode_cache(int(self.showtmdb), self.season, self.episode, False)
                return False

            # Parse response
            self._parse_tmdb_response(response)

            # Cache this positive result
            trakt.update_next_episode_cache(int(self.showtmdb), self.season, self.episode, True)

            return True

        except Exception as e:
            c.log(f"[Episode] Error fetching TMDB metadata: {e}")
            return False

    @staticmethod
    def get_metadata_cache_key(showtmdb, season, episode, lang):
        """
        Generate cache key for episode metadata (for batch pre-loading).

        Args:
            showtmdb: TMDB show ID
            season: Season number
            episode: Episode number
            lang: Language code

        Returns:
            str: Cache key matching what cache.get() would generate
        """
        from ..modules import keys
        tmdb_link = 'https://api.themoviedb.org/3/'
        url = f"{tmdb_link}tv/{showtmdb}/season/{season}/episode/{episode}?api_key={keys.tmdb_key}&language={lang}&append_to_response=credits,images"

        # Match cache._hash_function(http_client.tmdb_get_json, url, 16)
        return cache._hash_function(http_client.tmdb_get_json, url, 16)

    @staticmethod
    def get_metadata_cache_key_minimal(showtmdb, season, episode, lang):
        """
        Generate cache key for MINIMAL episode metadata (widget-optimized).
        No append_to_response = much smaller payload.

        Args:
            showtmdb: TMDB show ID
            season: Season number
            episode: Episode number
            lang: Language code

        Returns:
            str: Cache key for minimal metadata
        """
        from ..modules import keys
        tmdb_link = 'https://api.themoviedb.org/3/'
        url = f"{tmdb_link}tv/{showtmdb}/season/{season}/episode/{episode}?api_key={keys.tmdb_key}&language={lang}"

        # Match cache._hash_function(http_client.tmdb_get_json, url, 16)
        return cache._hash_function(http_client.tmdb_get_json, url, 16)

    def fetch_tmdb_metadata_minimal(self, episode_cache_dict=None, metadata_cache_dict=None):
        """
        Fetch MINIMAL episode metadata from TMDB (widget-optimized).

        Skips append_to_response (no credits, no images) for ~75% bandwidth savings.
        Only fetches: name, overview, air_date, still_path
        Perfect for widgets where cast/crew info isn't displayed.

        Args:
            episode_cache_dict: Optional pre-loaded cache dict for batch performance
            metadata_cache_dict: Optional pre-loaded metadata cache from cache_get_many()

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Need show TMDB ID
            if self.showtmdb == '0':
                return False

            if self.season == 0 or self.episode == 0:
                return False

            # Check smart cache first (validates against Trakt activity timestamps)
            from resources.lib.modules import trakt
            cache_result = trakt.check_next_episode_cache(int(self.showtmdb), self.season, self.episode, cache_dict=episode_cache_dict)

            if cache_result is not None:
                # Cache hit
                if cache_result is False:
                    # Episode confirmed not to exist on TMDB (cached 404)
                    return False

            # Build URL WITHOUT append_to_response (minimal payload)
            url = f"{self.tmdb_link}tv/{self.showtmdb}/season/{self.season}/episode/{self.episode}?api_key={self.tmdb_user}&language={self.lang}"

            # Check if metadata was pre-loaded via batch
            response = None
            if metadata_cache_dict:
                cache_key = Episode.get_metadata_cache_key_minimal(self.showtmdb, self.season, self.episode, self.lang)
                cached_row = metadata_cache_dict.get(cache_key)
                if cached_row:
                    # Parse cached value
                    value = cached_row.get('value')
                    if isinstance(value, str):
                        try:
                            response = json.loads(value)
                        except Exception:
                            response = value
                    else:
                        response = value

            # If not in batch cache, fetch individually
            if not response:
                response = cache.get(http_client.tmdb_get_json, 24, url, 16)

            if not response:
                # Cache this negative result to avoid repeated API calls
                trakt.update_next_episode_cache(int(self.showtmdb), self.season, self.episode, False)
                return False

            # Parse response (minimal - no credits/images)
            self._parse_tmdb_response_minimal(response)

            # Cache this positive result
            trakt.update_next_episode_cache(int(self.showtmdb), self.season, self.episode, True)

            return True

        except Exception as e:
            c.log(f"[Episode] Error fetching minimal TMDB metadata: {e}")
            return False

    def _parse_tmdb_response_minimal(self, data):
        """
        Parse MINIMAL TMDB API response (widget-optimized).
        Only extracts basic episode info - no cast/crew.

        Args:
            data (dict): TMDB API response data (without append_to_response)
        """
        try:
            # Episode info only
            self.title = data.get('name', self.title)
            self.plot = self.clean_plot(data.get('overview', ''))
            self.first_aired = data.get('air_date', '')
            self.premiered = self.first_aired

            # Ratings (optional, included in minimal response)
            self.rating = str(data.get('vote_average', 0))
            self.votes = str(data.get('vote_count', 0))

            # Runtime (optional)
            if runtime := data.get('runtime'):
                self.duration = str(runtime)

            # Episode still (thumbnail) - single image, minimal overhead
            if still_path := data.get('still_path'):
                self.thumb = self.format_tmdb_image(c.tmdb_stillsize, still_path)

            # NO cast/crew processing (not in minimal response)
            # Saves ~20-30KB per episode

        except Exception as e:
            c.log(f"[Episode] Error parsing minimal TMDB response: {e}")

    def _parse_tmdb_response(self, data):
        """
        Parse TMDB API response and populate episode properties.

        Args:
            data (dict): TMDB API response data
        """
        try:
            # Episode info
            self.title = data.get('name', self.title)
            self.plot = self.clean_plot(data.get('overview', ''))
            self.first_aired = data.get('air_date', '')
            self.premiered = self.first_aired

            # Ratings
            self.rating = str(data.get('vote_average', 0))
            self.votes = str(data.get('vote_count', 0))

            # Runtime
            if runtime := data.get('runtime'):
                self.duration = str(runtime)

            # Episode still (thumbnail)
            if still_path := data.get('still_path'):
                self.thumb = self.format_tmdb_image(c.tmdb_stillsize, still_path)

            # Cast and crew from credits
            credits = data.get('credits', {})

            # Guest stars (cast)
            guest_stars = credits.get('guest_stars', [])[:30]
            self.castwiththumb = []
            for person in guest_stars:
                profile_path = person.get('profile_path')
                thumbnail = self.format_tmdb_image(c.tmdb_profilesize, profile_path) if profile_path else ''

                # Get character name from roles array
                character = ''
                if roles := person.get('roles'):
                    character = roles[0].get('character', '')
                elif 'character' in person:
                    character = person['character']

                self.castwiththumb.append({
                    'name': person.get('name', ''),
                    'role': character,
                    'thumbnail': thumbnail
                })

            # Crew (writers and directors)
            crew_list = credits.get('crew', [])
            writers = [x['name'] for x in crew_list if 'Writer' in x.get('jobs', []) or x.get('job') == 'Writer']
            directors = [x['name'] for x in crew_list if 'Director' in x.get('jobs', []) or x.get('job') == 'Director']

            self.writer = ' / '.join(writers) if writers else ''
            self.director = ' / '.join(directors) if directors else ''

        except Exception as e:
            c.log(f"[Episode] Error parsing TMDB response: {e}")

    def fetch_show_artwork(self, artwork_cache=None):
        """
        Fetch parent show artwork (poster, fanart, etc.) from TMDB and fanart.tv.
        Also fetches episode still and season poster.
        Updates poster, fanart, banner, clearlogo, etc.

        Args:
            artwork_cache (dict, optional): Shared cache {show_tmdb_id: artwork_dict}

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Need show TMDB ID
            if self.showtmdb == '0':
                c.log(f"[Episode] Cannot fetch show artwork - no show TMDB ID")
                return False

            # Check cache first for show-level artwork
            cache_hit = False
            if artwork_cache is not None and self.showtmdb in artwork_cache:
                cached = artwork_cache[self.showtmdb]
                self.poster = cached.get('poster', self.poster)
                self.fanart = cached.get('fanart', self.fanart)
                self.banner = cached.get('banner', '0')
                self.clearlogo = cached.get('clearlogo', '0')
                self.clearart = cached.get('clearart', '0')
                self.landscape = cached.get('landscape', '0')
                if self.showtvdb == '0':
                    self.showtvdb = cached.get('showtvdb', '0')
                if self.showimdb == '0':
                    self.showimdb = cached.get('showimdb', '0')
                cache_hit = True

            # Fetch episode still (thumbnail) from TMDB - ALWAYS (episode-specific)
            if self.season and self.episode:
                try:
                    episode_url = f"{self.tmdb_link}tv/{self.showtmdb}/season/{self.season}/episode/{self.episode}?api_key={self.tmdb_user}&language={self.lang}"
                    episode_response = cache.get(http_client.tmdb_get_json, 24, episode_url, 16)
                    if episode_response and (still_path := episode_response.get('still_path')):
                        self.thumb = self.format_tmdb_image(c.tmdb_stillsize, still_path)
                except Exception as e:
                    c.log(f"[Episode] Error fetching episode still: {e}")

            # Fetch season poster from TMDB - ALWAYS (season-specific)
            if self.season:
                try:
                    season_url = f"{self.tmdb_link}tv/{self.showtmdb}/season/{self.season}?api_key={self.tmdb_user}&language={self.lang}"
                    season_response = cache.get(http_client.tmdb_get_json, 24, season_url, 16)
                    if season_response and (season_poster_path := season_response.get('poster_path')):
                        self.poster = self.format_tmdb_image(c.tmdb_postersize, season_poster_path)
                except Exception as e:
                    c.log(f"[Episode] Error fetching season poster: {e}")

            # Only fetch show-level artwork if not cached
            if not cache_hit:
                # Fetch show metadata from TMDB (fallback for poster/fanart)
                url = f"{self.tmdb_link}tv/{self.showtmdb}?api_key={self.tmdb_user}&language={self.lang}&append_to_response=external_ids"
                response = cache.get(http_client.tmdb_get_json, 24, url, 16)

                if response:
                    # Get show poster (fallback if no season poster)
                    if self.poster in ['0', '', None]:
                        if poster_path := response.get('poster_path'):
                            self.poster = self.format_tmdb_image(c.tmdb_postersize, poster_path)

                    # Get fanart
                    if backdrop_path := response.get('backdrop_path'):
                        self.fanart = self.format_tmdb_image(c.tmdb_fanartsize, backdrop_path)

                    # Get external IDs if we don't have them
                    external_ids = response.get('external_ids', {})
                    if self.showtvdb == '0' and (tvdb_id := external_ids.get('tvdb_id')):
                        self.showtvdb = str(tvdb_id)
                    if self.showimdb == '0' and (imdb_id := external_ids.get('imdb_id')):
                        self.showimdb = str(imdb_id)

                    # Log IDs for debugging
                    c.log(f"[Episode] After TMDB fetch - Show IDs: imdb={self.showimdb}, tmdb={self.showtmdb}, tvdb={self.showtvdb}")

                # Fetch fanart.tv artwork if enabled and we have TVDB ID
                if self.show_fanart and self.showtvdb and self.showtvdb != '0':
                    try:
                        from ..modules import fanart as fanart_tv
                        tv_fanart = cache.get(fanart_tv.get_fanart_tv_art, 72, self.showtvdb)
                        if tv_fanart:
                            # Only use fanart.tv values if valid (not '0', '', or None)
                            if tv_fanart.get('poster') and tv_fanart.get('poster') not in ['0', '', None]:
                                self.poster = tv_fanart['poster']
                            if tv_fanart.get('fanart') and tv_fanart.get('fanart') not in ['0', '', None]:
                                self.fanart = tv_fanart['fanart']
                            if tv_fanart.get('banner') and tv_fanart.get('banner') not in ['0', '', None]:
                                self.banner = tv_fanart['banner']
                            if tv_fanart.get('clearlogo') and tv_fanart.get('clearlogo') not in ['0', '', None]:
                                self.clearlogo = tv_fanart['clearlogo']
                            if tv_fanart.get('clearart') and tv_fanart.get('clearart') not in ['0', '', None]:
                                self.clearart = tv_fanart['clearart']
                            if tv_fanart.get('landscape') and tv_fanart.get('landscape') not in ['0', '', None]:
                                self.landscape = tv_fanart['landscape']
                    except Exception as e:
                        c.log(f"[Episode] Error fetching fanart.tv art: {e}")

                # Populate cache for future episodes from same show
                if artwork_cache is not None:
                    artwork_cache[self.showtmdb] = {
                        'poster': self.poster,
                        'fanart': self.fanart,
                        'banner': self.banner,
                        'clearlogo': self.clearlogo,
                        'clearart': self.clearart,
                        'landscape': self.landscape,
                        'showtvdb': self.showtvdb,
                        'showimdb': self.showimdb
                    }

            return True

        except Exception as e:
            c.log(f"[Episode] Error fetching show artwork: {e}")
            return False

    @classmethod
    def from_trakt_progress(cls, show_data, season_num, episode_num, episode_data=None):
        """
        Create Episode instance from Trakt progress data.

        Args:
            show_data (dict): Trakt show data
            season_num (int): Season number
            episode_num (int): Episode number
            episode_data (dict, optional): Trakt episode data if available

        Returns:
            Episode: New Episode instance
        """
        try:
            episode = cls()

            # Episode identifiers
            episode.season = season_num
            episode.episode = episode_num

            # Show info
            episode.tvshowtitle = show_data.get('title', '')
            episode.year = str(show_data.get('year', ''))
            episode.status = show_data.get('status', '')

            # Show IDs
            ids = show_data.get('ids', {})
            episode.showimdb = str(ids.get('imdb', '0'))
            episode.showtmdb = str(ids.get('tmdb', '0'))
            episode.showtvdb = str(ids.get('tvdb', '0'))
            episode.showtrakt = str(ids.get('trakt', '0'))

            # Episode data if provided
            if episode_data:
                episode.title = episode_data.get('title', f"Episode {episode_num}")
                episode.plot = episode_data.get('overview', '')  # Trakt provides overview
                episode.last_watched_at = episode_data.get('last_watched_at')

                # Episode IDs
                ep_ids = episode_data.get('ids', {})
                episode.imdb = str(ep_ids.get('imdb', '0'))
                episode.tmdb = str(ep_ids.get('tmdb', '0'))
                episode.tvdb = str(ep_ids.get('tvdb', '0'))
                episode.trakt = str(ep_ids.get('trakt', '0'))

            return episode

        except Exception as e:
            c.log(f"[Episode] Error creating episode from Trakt data: {e}")
            return None

    def get_action_url(self, action='play'):
        """
        Get plugin URL for this episode.

        Args:
            action (str): Action to perform (e.g., 'play', 'playFromBeginning')

        Returns:
            str: Plugin URL
        """
        params = {
            'action': action,
            'tvshowtitle': self.tvshowtitle,
            'year': self.year,
            'imdb': self.showimdb,
            'tmdb': self.showtmdb,
            'tvdb': self.showtvdb,
            'season': self.season,
            'episode': self.episode,
        }
        from urllib.parse import urlencode
        return f"plugin://plugin.video.thecrew/?{urlencode(params)}"

    def __str__(self):
        """String representation for debugging."""
        return f"{self.tvshowtitle} S{self.season:02d}E{self.episode:02d} - {self.title}"
