# -*- coding: utf-8 -*-
'''
 ***********************************************************
 * The Crew Add-on
 *
 * @package script.module.thecrew
 *
 * @copyright (c) 2025, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ***********************************************************
'''

# CM - 01/09/2023
import os
import sys
import re
import time
import datetime
import json


import concurrent.futures
from contextlib import suppress
import traceback

from urllib.parse import quote, quote_plus, unquote_plus, parse_qsl, urlsplit, urlencode, urlparse
import requests

from ..modules import trakt
from ..modules import keys
from ..modules import bookmarks
from ..modules import cleantitle
from ..modules import cleangenre
from ..modules import control
from ..modules import metacache
from ..modules import client
from ..modules import cache
from ..modules import playcount
from ..modules import workers
from ..modules import views
from ..modules import utils
from ..modules import crew_errors
from ..modules import fanart as fanart_tv
from ..modules import http_client

from ..modules.listitem import ListItemInfoTag
from ..modules.crewruntime import c, COLOR_STRING_IDS


IS_ORION_INSTALLED = getattr(c, 'is_orion_installed', lambda: False)()

# Attempt a safe dynamic import of the optional 'orion' module to avoid
# unresolved import errors and the use of wildcard imports.
ORION = None
try:
    if IS_ORION_INSTALLED:
        import importlib
        ORION = importlib.import_module('orion')
except Exception:
    ORION = None


params = dict(parse_qsl(sys.argv[2].replace('?', ''))) if len(sys.argv) > 2 else {}
action = params.get('action')


class TMDBMixin:
    """Shared TMDB configuration and helper methods for Seasons and Episodes classes."""

    def _init_tmdb_config(self):
        """Initialize shared TMDB configuration, session, and API endpoints."""
        # Use shared HTTP client with connection pooling and retry logic
        self.session = http_client.get_tmdb_session()

        # Cache for show data to avoid redundant API calls
        self._show_data_cache = {}

        # API credentials and settings
        self.tmdb_user = c.get_setting('tm.personal_user') or c.get_setting('tm.user') or keys.tmdb_key
        self.user = self.tmdb_user
        self.lang = control.apiLanguage()['tmdb']
        self.showunaired = c.get_setting('showunaired') or 'true'
        self.specials = c.get_setting('tv.specials') or 'true'
        self.show_fanart = c.get_setting('fanart') == 'true'

        # Date handling
        self.today_date = datetime.date.today().strftime("%Y-%m-%d")

        # TMDB base URLs
        self.tmdb_link = 'https://api.themoviedb.org/3/'
        self.tmdb_img_link = 'https://image.tmdb.org/t/p/%s%s'

        # TMDB API endpoints (common to both Seasons and Episodes)
        self.tmdb_show_link = f'{self.tmdb_link}tv/%s?api_key={self.tmdb_user}&language=%s&append_to_response=external_ids,aggregate_credits,content_ratings'
        self.tmdb_show_lite_link = f'{self.tmdb_link}tv/%s?api_key={self.tmdb_user}&language=en&append_to_response=external_ids'
        self.tmdb_by_imdb = f"{self.tmdb_link}find/%s?api_key={self.tmdb_user}&external_source=imdb_id"
        self.tmdb_show_with_external_ids = f'{self.tmdb_link}tv/%s?api_key={self.tmdb_user}&language={self.lang}&append_to_response=external_ids,aggregate_credits,content_ratings'
        self.tmdb_episode_link = f'{self.tmdb_link}tv/%s/season/%s/episode/%s?api_key={self.tmdb_user}&language={self.lang}&append_to_response=credits,images'
        self.tmdb_api_link = f'{self.tmdb_link}tv/%s?api_key={self.tmdb_user}&language={self.lang}&append_to_response=external_ids,aggregate_credits,content_ratings,external_ids'
        self.tmdb_external_ids_by_tmdb = f'{self.tmdb_link}tv/%s/external_ids?api_key={self.tmdb_user}&language=en-US'
        self.tmdb_networks_link = f'{self.tmdb_link}discover/tv?api_key={self.tmdb_user}&sort_by=popularity.desc&with_networks=%s&append_to_response=external_ids&page=1'
        self.tmdb_search_tvshow_link = f'{self.tmdb_link}search/tv?api_key={self.tmdb_user}&language=en-US&append_to_response=external_ids&query=%s&page=1'
        self.tmdb_info_tvshow_link = f'{self.tmdb_link}tv/%s?api_key={self.tmdb_user}&language=en-US&append_to_response=external_ids,images'

    def get_cast(self, item):
        """Extract cast information from TMDB aggregate_credits."""
        cast_list = item.get('aggregate_credits', {}).get('cast', [])[:30]
        cast_info = []
        for person in cast_list:
            icon = self.tmdb_img_link % (
                c.tmdb_profilesize, person['profile_path']
            ) if person['profile_path'] else ''
            cast_info.append({
                'name': person['name'],
                'role': person['roles'][0]['character'],
                'thumbnail': icon
            })

        crew_list = item.get('aggregate_credits', {}).get('crew', [])
        writers = [x['name'] for x in crew_list if 'Writer' in x.get('jobs', [])]
        directors = [x['name'] for x in crew_list if 'Director' in x.get('jobs', [])]

        writer = ' / '.join(writers) if writers else '0'
        director = ' / '.join(directors) if directors else '0'

        return cast_info, writer, director

    def get_plot_fallback_item(self, translations) -> str:
        """Get English plot as fallback if native language plot is unavailable."""
        fallback_items = [x['data'] for x in translations if x.get('iso_639_1') == 'en']
        if fallback_items:
            fallback_item = fallback_items[0]
            show_plot = fallback_item['overview'] or c.lang(32623)
            show_plot = client.replaceHTMLCodes(str(show_plot))
        else:
            show_plot = c.lang(32623)

        return show_plot

    def get_tmdb_art(self, tmdb):
        """Get TMDB artwork for a given TMDB ID using bandwidth-friendly image sizes (cached)."""
        try:
            # Cache artwork URLs for 30 days (2592000 seconds) - artwork rarely changes
            return cache.get(self._fetch_tmdb_art, 2592000, tmdb)
        except Exception:
            return '0', '0'

    def _fetch_tmdb_art(self, tmdb):
        """Internal method to fetch TMDB artwork (used by cache.get())."""
        try:
            url = self.tmdb_show_link % (tmdb, self.lang)
            result = self.session.get(url, timeout=10).json()

            poster = self.tmdb_img_link % (c.tmdb_postersize, result['poster_path']) if 'poster_path' in result else '0'
            fanart = self.tmdb_img_link % (c.tmdb_fanartsize, result['backdrop_path']) if 'backdrop_path' in result else '0'

            return poster, fanart
        except Exception:
            # Ensure we always return a tuple so callers can safely unpack
            return '0', '0'


class Seasons(TMDBMixin):
    def __init__(self):
        self.list = []
        self.speedtest = {'start': time.perf_counter()}
        self.meta = []

        # Initialize shared TMDB configuration from mixin
        self._init_tmdb_config()

    def __del__(self):
        with suppress(Exception):
            self.session.close()



    def get(self, tvshowtitle, year, imdb, tmdb, meta=None, idx=True, create_directory=True):
        try:
            if idx is True:
                #self.list = cache.get(self.tmdb_list, 24, tvshowtitle, year, imdb, tmdb, meta)
                self.list = self.tmdb_list(tvshowtitle, year, imdb, tmdb, meta)
                if create_directory is True:
                    self.season_directory(self.list)
                return self.list
            else:
                self.list = self.tmdb_list(tvshowtitle, year, imdb, tmdb, meta)
            return self.list
        except Exception as e:
            failure = traceback.format_exc()



    def tmdb_list(self, tvshowtitle, year, imdb_id, tmdb_id, meta=None, lite=False):
        """
        Get a list of TV show seasons from TMDB.

        Cleaner logic, narrower exception handling and improved logging.
        Returns: self.list (list of season dicts)
        """

        # reset list for repeated calls
        self.list = []

        # Validate TMDB id early
        if tmdb_id in ('0', None, ''):
            raise ValueError('No valid TMDB id provided')

        # Build request URL
        try:
            if lite:
                url = self.tmdb_show_lite_link % tmdb_id
            else:
                lang = 'en' if self.lang == 'en' else self.lang
                url = self.tmdb_show_link % (tmdb_id, lang)
                if not lite and self.lang != 'en':
                    url = f'{url},translations'
        except Exception as e:
            raise

        # Fetch show data from TMDB using centralized helper
        item = http_client.tmdb_get_json(url, timeout=16)
        if not item:
            raise ValueError('Empty or failed TMDB response')

        # Safe extraction helpers
        def _int_from(item, key, default=0):
            try:
                return int(item.get(key) or default)
            except Exception:
                return default

        def _first_in_list(val, default=45):
            try:
                if isinstance(val, list):
                    return val[0] if val else default
                return val or default
            except Exception:
                return default

        number_of_episodes = _int_from(item, 'number_of_episodes', 0)
        number_of_seasons = _int_from(item, 'number_of_seasons', 0)

        tvshowtitle = item.get('name') or tvshowtitle or '0'
        tagline = item.get('tagline') or '0'
        ext_ids = item.get('external_ids') or {}
        tvdb_id = ext_ids.get('tvdb') or '0'
        imdb_id = ext_ids.get('imdb_id') or imdb_id or '0'

        seasons_list = item.get('seasons') or []
        if self.specials == 'false':
            seasons_list = [s for s in seasons_list if s.get('season_number') != 0]

        # network/studio
        studio = '0'
        try:
            networks = item.get('networks') or []
            if networks:
                studio = networks[0].get('name') or '0'
        except Exception as e:
            pass

        # genres
        try:
            genres = item.get('genres') or []
            genre = ' / '.join([g.get('name', '') for g in genres]) if genres else '0'
        except Exception:
            genre = '0'

        # duration
        duration_val = _first_in_list(item.get('episode_run_time', 45), 45)
        try:
            duration = str(int(duration_val))
        except Exception:
            duration = '45'

        # MPAA / content ratings (try US first)
        mpaa = '0'
        try:
            c_ratings = (item.get('content_ratings') or {}).get('results') or []
            if c_ratings:
                us = [r.get('rating') for r in c_ratings if r.get('iso_3166_1') == 'US' and r.get('rating')]
                if us:
                    mpaa = us[0] or '0'
        except Exception:
            mpaa = '0'

        status = item.get('status') or '0'
        rating = str(item.get('vote_average') or 0)
        votes = str(item.get('vote_count') or 0)

        # cast extraction (non-fatal)
        cast = '0'
        writer = '0'
        director = '0'
        try:
            cast_info, writer, director = self.get_cast(item)
            cast = cast_info or '0'
        except Exception as e:
            pass

        # overview / plot (with fallback translations if available)
        try:
            show_plot = item.get('overview') or c.lang(32623) or '0'
            show_plot = client.replaceHTMLCodes(c.to_str(show_plot, errors='replace'))
        except Exception:
            show_plot = c.lang(32623) or '0'

        if self.lang != 'en' and (not show_plot or show_plot == '0'):
            try:
                translations = (item.get('translations') or {}).get('translations', []) or []
                if translations:
                    show_plot = self.get_plot_fallback_item(translations)
            except Exception as e:
                pass

        # artwork defaults
        banner = clearlogo = clearart = landscape = '0'
        try:
            if meta:
                _meta = json.loads(unquote_plus(meta))
                show_poster = _meta.get('poster', '0')
                fanart = _meta.get('fanart', '0')
                banner = _meta.get('banner', '0')
                clearlogo = _meta.get('clearlogo', '0')
                clearart = _meta.get('clearart', '0')
                landscape = _meta.get('landscape', '0')
            else:
                poster_path = item.get('poster_path') or ''
                show_poster = self.tmdb_img_link % (c.tmdb_postersize, poster_path) if poster_path else '0'

                fanart_path = item.get('backdrop_path') or ''
                fanart = self.tmdb_img_link % (c.tmdb_fanartsize, fanart_path) if fanart_path else '0'

                # fanart.tv fallback if tvdb available
            try:
                if self.show_fanart and tvdb_id not in ('0', None, ''):
                    tv_fanart = cache.get(fanart_tv.get_fanart_tv_art, 72, tvdb_id)
                    if tv_fanart:
                        show_poster = tv_fanart.get('poster', show_poster)
                        fanart = tv_fanart.get('fanart') or fanart or '0'
                        banner = tv_fanart.get('banner', banner)
                        clearlogo = tv_fanart.get('clearlogo', clearlogo)
                        clearart = tv_fanart.get('clearart', clearart)
                        landscape = tv_fanart.get('landscape', landscape)
            except Exception as e:
                pass
        except Exception as e:
            show_poster = '0'
            fanart = '0'

        # helper: date numeric comparator (YYYYMMDD as int)
        def _date_num(date_str):
            try:
                return int(re.sub('[^0-9]', '', str(date_str)))
            except Exception:
                return 0

        today_num = _date_num(self.today_date)

        # iterate seasons and build result entries
        for s in seasons_list:
            try:
                season_num_raw = s.get('season_number', 0)
                season = str(int(season_num_raw))
                premiered = s.get('air_date') or '0'

                # skip if not premiered and show not ended
                if status != 'Ended' and (not premiered or premiered == '0'):
                    continue

                unaired = 'false'
                if status != 'Ended' and premiered and premiered != '0':
                    premiered_num = _date_num(premiered)
                    if premiered_num > today_num:
                        unaired = 'true'
                        if self.showunaired != 'true':
                            continue

                plot = s.get('overview') or c.lang(32623) or '0'
                plot = client.replaceHTMLCodes(c.to_str(plot, errors='replace'))

                poster_path = s.get('poster_path') or ''
                poster = self.tmdb_img_link % (c.tmdb_postersize, poster_path) if poster_path else show_poster
                thumb = poster

                self.list.append({
                    'season': season,
                    'tvshowtitle': tvshowtitle,
                    'tagline': tagline,
                    'year': year,
                    'premiered': premiered,
                    'status': status,
                    'studio': studio,
                    'genre': genre,
                    'duration': duration,
                    'mpaa': mpaa,
                    'castwiththumb': cast,
                    'writer': writer,
                    'director': director,
                    'plot': plot,
                    'imdb': imdb_id,
                    'tmdb': str(tmdb_id),
                    'tvdb': tvdb_id,
                    'poster': thumb,
                    'fanart': fanart,
                    'banner': banner,
                    'clearlogo': clearlogo,
                    'thumb': thumb,
                    'clearart': clearart,
                    'landscape': landscape,
                    'seasons': number_of_seasons,
                    'episodes': number_of_episodes,
                    'rating': rating,
                    'votes': votes,
                    'unaired': unaired,
                })
            except Exception as e:
                failure = traceback.format_exc()
                continue

        return self.list

    def no_info(self, item):
        '''cm - placeholder for now '''
        return item

    def super_info(self, i):
        """
        Populate an entry in self.list (index i) with enriched TMDB/episode metadata.
        Simplified by delegating to helper functions for clarity and speed.
        """
        try:
            item = self.list[i]
            is_episode = 'showimdb' in item

            # Step 1: Resolve and validate IDs
            ids = self._resolve_ids(item, is_episode)
            if not ids:
                return  # Skip if IDs can't be resolved

            show_imdb, show_tmdb, show_tvdb, show_trakt = ids

            # Step 2: Fetch TMDB data
            show_item, episode_item = self._fetch_tmdb_data(show_tmdb, item['season'], item['episode'])
            if not episode_item:
                return  # Skip if episode data unavailable

            # Step 3: Extract metadata
            metadata = self._extract_metadata(show_item, episode_item, item, show_imdb, show_tmdb, show_tvdb, show_trakt, is_episode)

            # Step 4: Handle artwork
            artwork = self._handle_artwork(show_tvdb, show_tmdb)
            metadata.update(artwork)

            # Step 5: Build and update the item
            enriched_item = self._build_enriched_item(metadata, item)
            self._update_list_entry(i, enriched_item)

            # Step 6: Append to meta cache
            self._append_meta(enriched_item, show_imdb, show_tmdb, show_tvdb, item.get('resume_point', '0.0'))

        except Exception as e:
            failure = traceback.format_exc()

    def _resolve_ids(self, item, is_episode):
        """Resolve and validate IMDB/TMDB/TVDB/TRAKT IDs, fetching missing ones from TMDB."""
        try:
            if is_episode:
                show_imdb = item.get('showimdb', '0')
                show_tmdb = item.get('showtmdb', '0')
                show_tvdb = item.get('showtvdb', '0')
                show_trakt = item.get('showtrakt', '0')
            else:
                show_imdb = item.get('imdb', '0')
                show_tmdb = item.get('tmdb', '0')
                show_tvdb = item.get('tvdb', '0')
                show_trakt = item.get('trakt', '0')

            # Resolve missing TMDB from IMDB
            if show_tmdb == '0' and show_imdb != '0':
                try:
                    result = self.session.get(self.tmdb_by_imdb % show_imdb, timeout=15).json()
                    show_tmdb = str(result['tv_results'][0]['id']) if result.get('tv_results') else '0'
                except Exception:
                    pass

            # Resolve missing IMDB from TMDB
            if show_imdb == '0' and show_tmdb != '0':
                try:
                    result = self.session.get(self.tmdb_external_ids_by_tmdb % show_tmdb, timeout=15).json()
                    show_imdb = result.get('imdb_id', '0')
                except Exception:
                    pass

            # Resolve missing TVDB from TMDB
            if show_tvdb == '0' and show_tmdb != '0':
                try:
                    result = self.session.get(self.tmdb_external_ids_by_tmdb % show_tmdb, timeout=15).json()
                    show_tvdb = result.get('tvdb_id', '0')
                except Exception:
                    pass

            # Fail if no valid ID
            if show_tmdb in ('0', None) and show_imdb in ('0', None):
                return None

            return show_imdb, show_tmdb, show_tvdb, show_trakt
        except Exception as e:
            return None

    def _fetch_tmdb_data(self, show_tmdb, season, episode):
        """Fetch show and episode data from TMDB."""
        try:
            # Check cache for show data first (avoid redundant API calls for same show)
            if show_tmdb in self._show_data_cache:
                show_item = self._show_data_cache[show_tmdb]
            else:
                _id = show_tmdb
                en_url = self.tmdb_api_link % _id
                trans_url = f'{en_url},translations'
                url = en_url if self.lang == 'en' else trans_url
                show_item = self.session.get(url, timeout=15).json()
                # Cache show data for reuse across episodes
                self._show_data_cache[show_tmdb] = show_item

            # Always fetch episode data (unique per episode)
            episode_url = self.tmdb_episode_link % (show_tmdb, season, episode)
            episode_item = self.session.get(episode_url, timeout=15).json()

            return show_item, episode_item
        except Exception as e:
            return {}, {}

    def _extract_metadata(self, show_item, episode_item, item, show_imdb, show_tmdb, show_tvdb, show_trakt, is_episode):
        """Extract core metadata from TMDB responses."""
        try:
            show_title = item.get('tvshowtitle', '')
            title = item.get('title', '') or episode_item.get('name', '')
            season = item.get('season', '0')
            episode = item.get('episode', '0')
            year = item.get('year', '0')
            resume_point = item.get('resume_point', '0.0') or item.get('_resume_point', '0.0')

            # Normalize season/episode
            season = f"{int(season):01d}" if season and season != '0' else '0'
            episode = f"{int(episode):01d}" if episode and episode != '0' else '0'

            label = f"{show_title} : (S{season.zfill(2)}E{episode.zfill(2)})" if is_episode else show_title

            # Duration, status, premiered
            duration = episode_item.get('runtime') or episode_item.get('episode_run_time') or '45'
            status = show_item.get('status') or show_item.get('in_production', '0') or 'Ended'
            premiered = episode_item.get('air_date', '0')
            premiered = re.search(r'(\d{4}-\d{2}-\d{2})', premiered)
            premiered = premiered[1] if premiered else '0'

            # Genre, MPAA, rating, etc.
            genre = ' / '.join([d['name'] for d in show_item.get('genres', [])]) if show_item.get('genres') else '0'
            mpaa = show_item.get('mpaa', 'Not Rated')
            rating = str(show_item.get('vote_average', '0'))
            votes = str(show_item.get('vote_count', '0'))
            studio = next((c['name'] for c in show_item.get('production_companies', []) if c), '0')
            # Kodi v21+ requires countries as a list, not a string
            countries = [c['name'] for c in show_item.get('production_countries', [])] if show_item.get('production_countries') else []
            tagline = show_item.get('tagline', '0')

            # Trailer
            trailer = item.get('trailer', '')
            if not trailer:
                if vids := episode_item.get('videos', {}).get('results', []):
                    trailer = vids[0].get('key', '')
                elif show_vids := show_item.get('videos', {}).get('results', []):
                    trailer = show_vids[0].get('key', '')

            # In widget
            in_widget = bool(c.is_widget_listing())

            # Plot
            plot = episode_item.get('overview') or show_item.get('overview', '0')
            plot = client.replaceHTMLCodes(plot) if plot else '0'

            # Crew
            crew = episode_item.get('credits', {}).get('crew', []) or show_item.get('crew', [])
            crew = [c for c in crew if c.get('job') in ('Director', 'Writer')]
            director = '/'.join([d['name'] for d in crew if d['job'] == 'Director']) or '0'
            writer = '/'.join([w['name'] for w in crew if w['job'] == 'Writer']) or '0'

            # Cast
            castwiththumb = []
            with suppress(Exception):
                creds = episode_item.get('credits', {})
                cast = creds.get('cast', [])[:30] + creds.get('guest_stars', [])[:30]
                for person in cast:
                    profile_path = person.get('profile_path', '')
                    icon = self.tmdb_img_link % (c.tmdb_profilesize, profile_path) if profile_path else ''
                    castwiththumb.append({
                        'name': person.get('name', ''),
                        'role': person.get('character', ''),
                        'thumbnail': icon
                    })
            # Unaired check
            unaired = ''
            if premiered != '0':
                premiered_num = int(re.sub('[^0-9]', '', premiered))
                today_num = int(re.sub('[^0-9]', '', str(self.today_date)))
                if premiered_num > today_num:
                    unaired = 'true'
                    if self.showunaired != 'true':
                        return {}


            return {
                'title': title, 'season': season, 'episode': episode, 'year': year,
                'imdb': show_imdb, 'tmdb': show_tmdb, 'tvdb': show_tvdb, 'trakt': show_trakt,
                'status': status, 'studio': studio, 'premiered': premiered, 'genre': genre,
                'duration': duration, 'rating': rating, 'votes': votes, 'mpaa': mpaa,
                'director': director, 'writer': writer, 'castwiththumb': castwiththumb,
                'plot': plot, 'tagline': tagline, 'countries': countries, 'trailer': trailer,
                'label': label, 'resume_point': resume_point, 'tvshowtitle': show_title,
                'unaired': unaired, 'in_widget': in_widget
            }
        except Exception as e:
            return {}

    def _handle_artwork(self, show_tvdb, show_tmdb):
        """Fetch artwork from fanart.tv and TMDB fallbacks."""
        try:
            poster = fanart = banner = landscape = clearlogo = clearart = '0'

            # Fanart.tv
            if show_tvdb and show_tvdb != '0':
                try:
                    tempart = fanart_tv.get_fanart_tv_art(tvdb=show_tvdb)
                    poster = tempart.get('poster', poster)
                    fanart = tempart.get('fanart', fanart)
                    banner = tempart.get('banner', banner)
                    landscape = tempart.get('landscape', landscape)
                    clearlogo = tempart.get('clearlogo', clearlogo)
                    clearart = tempart.get('clearart', clearart)
                except Exception:
                    pass

            # TMDB fallback
            if poster == '0':
                try:
                    p, f = self.get_tmdb_art(show_tmdb)
                    poster = p or poster
                    fanart = f or fanart
                except Exception:
                    pass

            # Default fallbacks
            if poster == '0':
                poster = c.addon_poster()
            if fanart == '0':
                fanart = c.addon_fanart()

            return {
                'poster': poster, 'fanart': fanart, 'banner': banner, 'landscape': landscape,
                'clearlogo': clearlogo, 'clearart': clearart, 'thumb': landscape or fanart
            }
        except Exception as e:
            return {'poster': '0', 'fanart': '0', 'banner': '0', 'landscape': '0', 'clearlogo': '0', 'clearart': '0', 'thumb': '0'}

    def _build_enriched_item(self, metadata, original_item):
        """Build the final enriched item dict."""
        try:
            return {
                'title': metadata['title'], 'originaltitle': metadata['title'], 'year': metadata['year'],
                'imdb': metadata['imdb'], 'tvdb': metadata['tvdb'], 'tmdb': metadata['tmdb'],
                'status': metadata['status'], 'studio': metadata['studio'], 'poster': metadata['poster'],
                'banner': metadata['banner'], 'fanart': metadata['fanart'], 'fanart2': metadata['fanart'],
                'landscape': metadata['landscape'], 'discart': metadata['clearart'], 'clearlogo': metadata['clearlogo'],
                'clearart': metadata['clearart'], 'premiered': metadata['premiered'], 'genre': metadata['genre'],
                'thumb': metadata['thumb'], 'in_widget': metadata['in_widget'], 'duration': metadata['duration'],
                'rating': metadata['rating'], 'votes': metadata['votes'], 'mpaa': metadata['mpaa'],
                'director': metadata['director'], 'writer': metadata['writer'], 'castwiththumb': metadata['castwiththumb'],
                'plot': metadata['plot'], 'tagline': metadata['tagline'], 'countries': metadata['countries'],
                'trailer': metadata['trailer'], 'label': metadata['label'], 'resume_point': metadata['resume_point'],
                'trakt': metadata['trakt'], '_last_watched': original_item.get('_last_watched', '0'),
                'tvshowtitle': metadata['tvshowtitle'], 'season': metadata['season'], 'episode': metadata['episode'],
                'action': original_item.get('action'), 'unaired': metadata['unaired'],
                '_sort_key': max(original_item.get('_last_watched', '0'), metadata['premiered'])
            }
        except Exception as e:
            return {}

    def _update_list_entry(self, i, enriched_item):
        """Safely update self.list[i] with the enriched item."""
        try:
            if self.list and i < len(self.list):
                if self.list[i] is None or not isinstance(self.list[i], dict):
                    self.list[i] = enriched_item
                else:
                    self.list[i].update(enriched_item)
        except Exception as e:
            pass

    def _append_meta(self, enriched_item, show_imdb, show_tmdb, show_tvdb, resume_point):
        """Append to self.meta for caching."""
        try:
            meta_entry = {
                'imdb': show_imdb, 'tmdb': show_tmdb, 'tvdb': show_tvdb, 'lang': self.lang,
                'user': self.user, 'resume_point': resume_point, 'item': enriched_item
            }
            self.meta.append(meta_entry)
        except Exception as e:
            pass

    def worker(self, level = 0):
        """
        Worker for episodes. This function is used in multiple places in the CM codebase.
        It takes a list of episodes and fetches the metadata for each episode in parallel.
        The function can be used to fetch the metadata for a list of episodes with or without info.
        If level is 0, the function fetches all the metadata for each episode.
        If level is 1, the function only fetches the title, year, season, episode and tvshowtitle.
        The function returns a list of metadata for each episode.
        """
        try:
            total = len(self.list)

            if total == 0:
                control.infoDialog('List returned no relevant results [worker episodes]', icon='INFO', sound=False)
                return

            for i in range(total):
                # ensure the entry is a dict before updating to avoid "None is not subscriptable"
                try:
                    if isinstance(self.list[i], dict):
                        self.list[i].update({'metacache': False})
                    else:
                        # replace None or non-dict entries with a minimal dict expected downstream
                        self.list[i] = {'metacache': False}
                except Exception:
                    # defensive fallback: ensure valid dict in list slot
                    self.list[i] = {'metacache': False}

            self.list = metacache.fetch(self.list, self.lang, self.user)

            try:
                result = []
                #cm - changed worker 21-04-2025
                #cm - changed worker 27-04-2025 - added max threads/fixed steps
                with concurrent.futures.ThreadPoolExecutor(max_workers=c.get_max_threads(total, 50)) as executor:
                    if level == 1:
                        futures = {executor.submit(self.no_info, i): i for i in range(total)}
                    else:
                        futures = {executor.submit(self.super_info, i): i for i in range(total)}

                    for future in concurrent.futures.as_completed(futures):
                        i = futures[future]
                        try:
                            result.append(future.result())
                            #if(len(result) == total):
                                #c.log(f"[CM Debug @ 1291 in episodes.py] completed all {len(result)} futures in worker for super_info")
                        except Exception as e:
                            pass

                if self.meta:
                    metacache.insert(self.meta)

            except Exception as e:
                failure = traceback.format_exc()

        except Exception as e:
            failure = traceback.format_exc()

    def season_directory(self, items):
        try:
            if not items:
                control.idle()

            sysaddon = sys.argv[0]
            syshandle = int(sys.argv[1])

            trakt_credentials = trakt.get_trakt_credentials_info()

            # non-fatal indicators fetch; if it fails we leave indicators as None
            indicators = None
            with suppress(Exception):
                indicators = playcount.getSeasonIndicators(items[0].get('imdb'))  # ['1']

            watched_menu = control.lang(32068) if trakt.getTraktIndicatorsInfo() is True else control.lang(32066)
            unwatched_menu = control.lang(32069) if trakt.getTraktIndicatorsInfo() is True else control.lang(32067)
            queue_menu = control.lang(32065)
            trakt_manager_menu = control.lang(32515)
            label_menu = control.lang(32055)
            play_random = control.lang(32535)
            add_to_library = control.lang(32551)

            # cm
            color_list = [
                32589, 32590, 32591, 32592, 32593,
                32594, 32595, 32596, 32597, 32598
            ]
            color_nr = color_list[int(c.get_setting('unaired.identify'))]
            unaired_color = re.sub(r"\][\w\s]*\[", "][I]%s[/I][", control.lang(int(color_nr)))

            if unaired_color == '':
                unaired_color = '[COLOR red][I]%s[/I][/COLOR]'


            for i in items:
                try:
                    label = f"{label_menu} {i.get('season')}"

                    if i.get('unaired') == 'true':
                        label = unaired_color % label

                    systitle = sysname = quote_plus(i.get('tvshowtitle', ''))

                    # NOTE: str() made fanart a tuple in some cases; keep defensive handling
                    poster = str(i.get('poster')) if i.get('poster') and i.get('poster') != '0' else c.addon_poster()

                    fanart = '0'
                    if isinstance(i.get('fanart'), tuple):
                        fanart = i.get('fanart')[0]
                    if fanart == '0':
                        fanart = str(i.get('fanart')) if i.get('fanart') and i.get('fanart') != '0' else c.addon_fanart()

                    banner = str(i.get('banner')) if i.get('banner') and i.get('banner') != '0' else c.addon_banner()

                    # fix typo: check 'landscape' key correctly
                    landscape = (
                        str(i.get('landscape')) if i.get('landscape') and i.get('landscape') != '0'
                        else fanart
                    )

                    clearlogo = (
                        str(i.get('clearlogo')) if i.get('clearlogo') and i.get('clearlogo') != '0'
                        else c.addon_clearlogo()
                    )
                    clearart = (
                        str(i.get('clearart')) if i.get('clearart') and i.get('clearart') != '0'
                        else c.addon_clearart()
                    )
                    discart = (
                        str(i.get('discart')) if i.get('discart') and i.get('discart') != '0'
                        else c.addon_discart()
                    )
                    duration = i.get('duration') if i.get('duration') and i.get('duration') != '0' else '45'
                    status = i.get('status') if 'status' in i else '0'

                    episode_meta = {
                        'poster': poster,
                        'fanart': fanart,
                        'banner': banner,
                        'clearlogo': clearlogo,
                        'clearart': clearart,
                        'discart': discart,
                        'landscape': landscape,
                        'duration': duration,
                        'status': status
                    }

                    sysmeta = quote_plus(json.dumps(episode_meta))

                    imdb = i.get('imdb')
                    tvdb = i.get('tvdb')
                    tmdb = i.get('tmdb')
                    year = i.get('year')
                    season = i.get('season')

                    meta = {k: v for k, v in i.items() if v != '0'}
                    meta['code'] = imdb
                    meta['imdbnumber'] = imdb
                    meta['imdb_id'] = imdb
                    meta['tvdb_id'] = tvdb
                    meta['mediatype'] = 'season'
                    meta['season'] = int(season)
                    meta['tvshowtitle'] = i.get('tvshowtitle', '')
                    meta['title'] = f"{i.get('tvshowtitle', '')} - Season {season}"
                    meta['trailer'] = f'{sysaddon}?action=trailer&name={sysname}&imdb={imdb}&tmdb={tmdb}&mediatype=season&meta={sysmeta}'

                    if 'duration' not in i or i.get('duration') == '0':
                        meta['duration'] = '45'

                    if meta.get('duration') != '0':
                        meta['duration'] = str(int(meta['duration']))

                    meta['duration'] = str(int(meta['duration']) * 60)

                    meta['genre'] = cleangenre.lang(meta.get('genre', ''), self.lang)

                    # silenced extraction for season year (non-fatal)
                    with suppress(Exception):
                        season_year = i.get('premiered') if i.get('premiered') and i.get('premiered') != '0' else i.get('year')
                        season_year = re.findall(r'(\d{4})', season_year)[0]
                        meta['year'] = str(season_year)

                    # silenced overlay calculation; merge dict updates using |=
                    with suppress(Exception):
                        # Don't show watched indicator for unaired seasons
                        # Bug fix: Unaired seasons were showing watched at season level
                        # even though episodes inside correctly showed as unwatched
                        from ..modules import cleandate
                        season_aired = cleandate.has_aired(i.get('premiered', '0'))

                        overlay = int(playcount.getSeasonOverlay(indicators, season))
                        if overlay == 7 and season_aired:
                            # Only mark as watched if season has aired
                            meta.update({'playcount': 1, 'overlay': 7})
                        else:
                            # Unwatched or unaired - show as unwatched
                            meta.update({'playcount': 0, 'overlay': 6})

                    base_random = (
                        f'{sysaddon}?action=random&rtype=episode'
                        f'&tvshowtitle={systitle}&year={year}&imdb={imdb}'
                        f'&tmdb={tmdb}&season={season}'
                    )
                    cm = [
                        (play_random, f'RunPlugin({base_random})'),
                        (queue_menu, f'RunPlugin({sysaddon}?action=queueItem)'),
                    ]
                    base_watched = (
                        f'{sysaddon}?action=seasonPlaycount&name={systitle}&imdb={imdb}'
                        f'&tmdb={tmdb}&season={season}&query=7'
                    )
                    cm.append((watched_menu, f'RunPlugin({base_watched})'))

                    base_unwatched = (
                        f'{sysaddon}?action=seasonPlaycount&name={systitle}&imdb={imdb}'
                        f'&tmdb={tmdb}&season={season}&query=6'
                    )
                    cm.append((unwatched_menu, f'RunPlugin({base_unwatched})'))

                    if trakt_credentials:
                        trakt_mgr_cmd = (
                            f'RunPlugin({sysaddon}?action=traktManager&name={sysname}'
                            f'&tmdb={tmdb}&content=tvshow)'
                        )
                        cm.append((trakt_manager_menu, trakt_mgr_cmd))

                    library_cmd = (
                        f'RunPlugin({sysaddon}?action=tvshowToLibrary&tvshowtitle={systitle}'
                        f'&year={year}&imdb={imdb}&tmdb={tmdb})'
                    )
                    cm.append((add_to_library, library_cmd))

                    try:
                        item = control.item(label=label, offscreen=True)
                    except Exception:
                        item = control.item(label=label)

                    art = {}
                    # Use season poster for thumb (not fanart) - fixes season poster display issue
                    thumb = poster
                    art.update({
                        'icon': poster,
                        'banner': banner,
                        'poster': poster,
                        'tvshow.poster': poster,
                        'season.poster': poster,
                        'landscape': landscape,
                        'clearlogo': clearlogo,
                        'thumb': thumb,
                        'clearart': clearart,
                        'discart': discart
                    })
                    item.setArt(art)

                    cast_with_thumb = i.get('castwiththumb')
                    if cast_with_thumb and cast_with_thumb != '0':
                        meta['cast'] = cast_with_thumb

                    meta['art'] = art
                    meta['studio'] = c.string_split_to_list(meta.get('studio')) if 'studio' in meta else []
                    meta['genre'] = c.string_split_to_list(meta.get('genre')) if 'genre' in meta else []
                    meta['director'] = c.string_split_to_list(meta.get('director')) if 'director' in meta else []
                    meta['writer'] = c.string_split_to_list(meta.get('writer')) if 'writer' in meta else []

                    # Pass listitem to the infotagger module and specify tag type
                    info_tag = ListItemInfoTag(item, 'video')
                    infolabels = control.tagdataClean(meta)

                    info_tag.set_info(infolabels)
                    unique_ids = {'imdb': imdb, 'tmdb': str(tmdb)}
                    info_tag.set_unique_ids(unique_ids)
                    info_tag.set_info(infolabels)

                    if 'cast' in meta:
                        info_tag.set_cast(meta.get('cast'))
                    elif 'castwiththumb' in meta:
                        info_tag.set_cast(meta.get('castwiththumb'))
                    else:
                        info_tag.set_cast([])

                    stream_info = {'codec': 'h264'}
                    info_tag.add_stream_info('video', stream_info)  # (stream_details)
                    item.addContextMenuItems(cm, replaceItems=True)

                    url = (
                        f'{sysaddon}?action=episodes&tvshowtitle={systitle}&year={year}'
                        f'&imdb={imdb}&tmdb={tmdb}&meta={sysmeta}&season={season}'
                    )

                    control.addItem(handle=syshandle, url=url, listitem=item, isFolder=True)
                except Exception as e:
                    failure = traceback.format_exc()


            # setting property is non-fatal; suppress related exceptions
            with suppress(Exception):
                control.property(syshandle, 'showplot', items[0]['plot'])

            control.content(syshandle, 'seasons')
            control.directory(syshandle, cacheToDisc=True)
            views.set_view('seasons', {'skin.estuary': 55, 'skin.confluence': 500})
        except Exception as e:
            failure = traceback.format_exc()



class Episodes(TMDBMixin):
    def __init__(self):
        self.list = []
        self.blist = []
        self.meta = []

        # Initialize shared TMDB configuration from mixin
        self._init_tmdb_config()

        # Episodes-specific caches (extends mixin's _show_data_cache)
        self._artwork_cache = {}  # key: (show_tvdb, show_tmdb), value: artwork dict

        # Episodes-specific attributes
        self.speedtest_start = time.perf_counter()

        # Override session with requests.Session (Episodes uses requests.Session instead of http_client)
        self.session = requests.Session()

        # Additional datetime handling
        self.datetime = datetime.datetime.now(datetime.timezone.utc)
        self.systime = self.datetime.strftime('%Y%m%d%H%M%S%f')

        # Additional user settings
        self.trakt_link = 'https://api.trakt.tv'
        self.tvmaze_link = 'https://api.tvmaze.com'
        self.trakt_user = c.get_setting('trakt.user').strip()
        self.hq_artwork = c.get_setting('hq.artwork') or 'false'
        self.fanart_tv_user = c.get_setting('fanart.tv.user')

        # Episodes-specific TMDB endpoints (extend or override mixin's base endpoints)
        self.tmdb_show_link = f'{self.tmdb_link}tv/%s?api_key={self.tmdb_user}'
        self.tmdb_season_link = f'{self.tmdb_link}tv/%s/season/%s?api_key={self.tmdb_user}&language=%s&append_to_response=aggregate_credits'
        self.tmdb_season_lite_link = f'{self.tmdb_link}tv/%s/season/%s?api_key={self.tmdb_user}&language={self.lang}'
        self.search_link = f'{self.tmdb_link}search/tv?api_key={self.tmdb_user}&language=en-US&query=%s&page=1'
        self.tmdb_api_link = f'{self.tmdb_link}tv/%s?api_key={self.tmdb_user}&language={self.lang}&append_to_response=credits,images,ratings,external_ids,videos,translations'




        # self.added_link = 'https://api.tvmaze.com/schedule'
        self.added_link = f'{self.trakt_link}/calendars/my/shows/date[5]/6/'
        self.calendar_link = 'https://api.tvmaze.com/schedule?date=%s&country=US'
        # https://api.trakt.tv/calendars/all/shows/date[30]/31 #use this for new episodes?
        # self.mycalendar_link = f'{self.trakt_link}/calendars/my/shows/date[29]/60/'
        # Changed from date[30]/31 to date[7]/7 (2026-02-24) - reduces talk show spam from 61 days to 14 days total
        self.mycalendar_link = f'{self.trakt_link}/calendars/my/shows/date[7]/7/'
        # New calendar endpoints (added 2026-03-10) - "What's airing tonight?" feature
        # NOTE: Using date[0] instead of "today" keyword to avoid Trakt UTC timezone issues
        self.calendar_today_link = f'{self.trakt_link}/calendars/my/shows/date[0]/1'  # Airing today (explicit date)
        self.calendar_thisweek_link = f'{self.trakt_link}/calendars/my/shows/date[0]/7'  # Airing this week (next 7 days)
        self.calendar_nextweek_link = f'{self.trakt_link}/calendars/my/shows/date[0]/14'  # Fetch 2 weeks, filter to days 7-14 in code
        self.trakthistory_link = f'{self.trakt_link}/users/me/history/shows?limit=40'
        self.progress_link = f'{self.trakt_link}/users/me/watched/shows'
        #self.progress_link = 'https://trakt.tv/users/me/progress/watched/activity?hide_completed=true'
        self.hiddenprogress_link = f'{self.trakt_link}/users/hidden/progress_watched?limit=1000&type=show'
        self.ondeck_link = f'{self.trakt_link}/sync/playback/episodes?limit=40'
        self.traktlists_link = f'{self.trakt_link}/users/me/lists'
        self.traktlikedlists_link = f'{self.trakt_link}/users/likes/lists?limit=1000000'
        self.traktlist_link = f'{self.trakt_link}/users/%s/lists/%s/items'
        self.show_watched_link = f'{self.trakt_link}/shows/%s/progress/collection?hidden=%s&specials=%s&count_specials=%s'

    def __del__(self):
        self.session.close()

    def get(self,tvshowtitle,year,imdb_id,tmdb_id,meta,season=None,episode=None,include_episodes=True,create_directory=True):
        """
        Get episodes for a TV show.

        Args:
            tvshowtitle (str): The title of the TV show.
            year (int): The year the TV show was released.
            imdb_id (str): The IMDB ID of the TV show.
            tmdb_id (str): The TMDB ID of the TV show.
            meta (dict): The metadata of the TV show.
            season (int or None): The season to retrieve. If None, all seasons are retrieved.
            episode (int or None): The episode to retrieve. If None, all episodes are retrieved.
            include_episodes (bool): If True, include episodes in the results.
            create_directory (bool): If True, create a directory for the episodes.

        Returns:
            list: A list of episodes.
        """

        url = (
            f"tvshowtitle={tvshowtitle}"
            f"&year={year}"
            f"&imdb_id={imdb_id}"
            f"&tmdb_id={tmdb_id}"
            f"&season={season}"
            f"&episode={episode}"
        )

        if include_episodes:
            # self.list = self.tmdb_list(tvshowtitle, year, imdb_id, tmdb_id, season, meta)
            # self.list = cache.get(self.tmdb_list, 1, tvshowtitle, year, imdb_id, tmdb_id, season, meta)
            self.list = cache.get(self.tmdb_list, 0, tvshowtitle, year, imdb_id, tmdb_id, season, meta)


            if season is not None and episode is not None:
                try:
                    c.log(
                        "[CM Debug @ 853 in episodes.py] title = "
                        f"{tvshowtitle}, year = {year}, imdb_id = {imdb_id}, "
                        f"tmdb_id = {tmdb_id}, season = {season}, episode = {episode}"
                    )

                    idxs= [
                        x
                        for x, y in enumerate(self.list)
                        if (
                            y.get('season') == str(season)
                            and y.get('episode') == str(episode)
                        )
                    ]

                    if idxs:
                        idx = idxs[-1]
                        self.list = [y for x, y in enumerate(self.list) if x >= idx]
                        self.list = sorted(
                            self.list,
                            key=lambda k: (int(k['season']), int(k['episode']))
                        )
                except Exception as e:
                    failure = traceback.format_exc()


            if create_directory:
                self.episodeDirectory(self.list)
        else:
            self.list = self.tmdb_list(tvshowtitle, year, imdb_id, tmdb_id, season, lite=True)

        return self.list

    def calendar(self, url, idx = True):
        try:
            return self._get_calendar(url, idx)
        except (AttributeError, ValueError, RuntimeError, requests.RequestException, crew_errors.TraktResourceError) as e:
            failure = traceback.format_exc()
            return []

    def worker(self, level = 0):
        """
        Worker for episodes. This function is used in multiple places in the CM codebase.
        It takes a list of episodes and fetches the metadata for each episode in parallel.
        The function can be used to fetch the metadata for a list of episodes with or without info.
        If level is 0, the function fetches all the metadata for each episode.
        If level is 1, the function only fetches the title, year, season, episode and tvshowtitle.
        The function returns a list of metadata for each episode.
        """
        try:
            total = len(self.list)

            if total == 0:
                control.infoDialog('List returned no relevant results [worker episodes]', icon='INFO', sound=False)
                return

            for i in range(total):
                if self.list[i] is not None and isinstance(self.list[i], dict):
                    self.list[i].update({'metacache': False})

            self.list = metacache.fetch(self.list, self.lang, self.user)

            try:
                result = []
                #cm - changed worker 21-04-2025
                #cm - changed worker 27-04-2025 - added max threads/fixed steps
                with concurrent.futures.ThreadPoolExecutor(max_workers=c.get_max_threads(total, 50)) as executor:
                    if level == 1:
                        futures = {executor.submit(self.no_info, i): i for i in range(total)}
                    else:
                        futures = {executor.submit(self.super_info, i): i for i in range(total)}
                    for future in concurrent.futures.as_completed(futures):
                        i = futures[future]
                        try:
                            result.append(future.result())
                            #if(len(result) == total):
                                #c.log(f"[CM Debug @ 1291 in episodes.py] completed all {len(result)} futures in worker for super_info")
                        except Exception as e:
                            pass

                if self.meta:
                    metacache.insert(self.meta)

            except Exception as e:
                pass

                failure = traceback.format_exc()
                pass
        except Exception as e:
            pass

            failure = traceback.format_exc()
            pass

    def no_info(self, item):
        '''cm - placeholder for now '''
        return item

    def super_info(self, i):
        """
        Populate an entry in self.list (index i) with enriched TMDB/episode metadata.
        Simplified by delegating to helper functions for clarity and speed.
        """
        try:
            item = self.list[i]

            # Skip None or invalid items
            if item is None or not isinstance(item, dict):
                return

            is_episode = 'showimdb' in item

            # Step 1: Resolve and validate IDs
            ids = self._resolve_ids(item, is_episode)
            if not ids:
                return  # Skip if IDs can't be resolved

            show_imdb, show_tmdb, show_tvdb, show_trakt = ids

            # Step 2: Fetch TMDB data
            show_item, episode_item = self._fetch_tmdb_data(show_tmdb, item['season'], item['episode'])
            if not episode_item:
                return  # Skip if episode data unavailable

            # Step 3: Extract metadata
            metadata = self._extract_metadata(show_item, episode_item, item, show_imdb, show_tmdb, show_tvdb, show_trakt, is_episode)

            # Step 4: Handle artwork
            artwork = self._handle_artwork(show_tvdb, show_tmdb)
            metadata.update(artwork)

            # Step 5: Build and update the item
            enriched_item = self._build_enriched_item(metadata, item)
            self._update_list_entry(i, enriched_item)

            # Step 6: Append to meta cache
            self._append_meta(enriched_item, show_imdb, show_tmdb, show_tvdb, item.get('resume_point', '0.0'))

        except Exception as e:
            failure = traceback.format_exc()

    def _resolve_ids(self, item, is_episode):
        """Resolve and validate IMDB/TMDB/TVDB/TRAKT IDs, fetching missing ones from TMDB."""
        try:
            if is_episode:
                show_imdb = item.get('showimdb', '0')
                show_tmdb = item.get('showtmdb', '0')
                show_tvdb = item.get('showtvdb', '0')
                show_trakt = item.get('showtrakt', '0')
            else:
                show_imdb = item.get('imdb', '0')
                show_tmdb = item.get('tmdb', '0')
                show_tvdb = item.get('tvdb', '0')
                show_trakt = item.get('trakt', '0')

            # Resolve missing TMDB from IMDB
            if show_tmdb == '0' and show_imdb != '0':
                try:
                    result = self.session.get(self.tmdb_by_imdb % show_imdb, timeout=15).json()
                    show_tmdb = str(result['tv_results'][0]['id']) if result.get('tv_results') else '0'
                except Exception:
                    pass

            # Resolve missing IMDB from TMDB
            if show_imdb == '0' and show_tmdb != '0':
                try:
                    result = self.session.get(self.tmdb_external_ids_by_tmdb % show_tmdb, timeout=15).json()
                    show_imdb = result.get('imdb_id', '0')
                except Exception:
                    pass

            # Resolve missing TVDB from TMDB
            if show_tvdb == '0' and show_tmdb != '0':
                try:
                    result = self.session.get(self.tmdb_external_ids_by_tmdb % show_tmdb, timeout=15).json()
                    show_tvdb = result.get('tvdb_id', '0')
                except Exception:
                    pass

            # Fail if no valid ID
            if show_tmdb in ('0', None) and show_imdb in ('0', None):
                return None

            return show_imdb, show_tmdb, show_tvdb, show_trakt
        except Exception as e:
            return None

    def _fetch_tmdb_data(self, show_tmdb, season, episode):
        """Fetch show and episode data from TMDB with show-level caching."""
        try:
            # Check cache for show data first (avoid redundant API calls for same show)
            if show_tmdb in self._show_data_cache:
                show_item = self._show_data_cache[show_tmdb]
            else:
                _id = show_tmdb
                en_url = self.tmdb_api_link % _id
                trans_url = f'{en_url},translations'
                url = en_url if self.lang == 'en' else trans_url
                show_item = self.session.get(url, timeout=15).json()
                # Cache show data for reuse across episodes
                self._show_data_cache[show_tmdb] = show_item

            # Always fetch episode data (unique per episode)
            episode_url = self.tmdb_episode_link % (show_tmdb, season, episode)
            episode_item = self.session.get(episode_url, timeout=15).json()

            return show_item, episode_item
        except Exception as e:
            return {}, {}

    def _extract_metadata(self, show_item, episode_item, item, show_imdb, show_tmdb, show_tvdb, show_trakt, is_episode):
        """Extract core metadata from TMDB responses."""
        try:
            show_title = item.get('tvshowtitle', '')
            title = item.get('title', '') or episode_item.get('name', '')
            season = item.get('season', '0')
            episode = item.get('episode', '0')
            year = item.get('year', '0')
            resume_point = item.get('resume_point', '0.0') or item.get('_resume_point', '0.0')

            # Normalize season/episode
            season = f"{int(season):01d}" if season and season != '0' else '0'
            episode = f"{int(episode):01d}" if episode and episode != '0' else '0'

            # For Continue Watching, label should be just the episode title - the worker will format it properly
            label = title if is_episode else show_title

            # Duration, status, premiered
            duration = episode_item.get('runtime') or episode_item.get('episode_run_time') or '45'
            status = show_item.get('status') or show_item.get('in_production', '0') or 'Ended'
            premiered = episode_item.get('air_date', '0')
            premiered_match = re.search(r'(\d{4}-\d{2}-\d{2})', premiered)
            premiered = premiered_match.group(1) if premiered_match else '0'

            # Genre, MPAA, rating, etc.
            genre = ' / '.join([d['name'] for d in show_item.get('genres', [])]) if show_item.get('genres') else '0'
            mpaa = show_item.get('mpaa', 'Not Rated')
            rating = str(show_item.get('vote_average', '0'))
            votes = str(show_item.get('vote_count', '0'))
            studio = next((c['name'] for c in show_item.get('production_companies', []) if c), '0')
            # Kodi v21+ requires countries as a list, not a string
            countries = [c['name'] for c in show_item.get('production_countries', [])] if show_item.get('production_countries') else []
            tagline = show_item.get('tagline', '0')

            # Trailer
            trailer = item.get('trailer', '')
            if not trailer:
                vids = episode_item.get('videos', {}).get('results', [])
                if vids:
                    trailer = vids[0].get('key', '')
                else:
                    show_vids = show_item.get('videos', {}).get('results', [])
                    if show_vids:
                        trailer = show_vids[0].get('key', '')

            # Plot
            in_widget = bool(c.is_widget_listing())
            plot = episode_item.get('overview') or show_item.get('overview', '0')
            plot = client.replaceHTMLCodes(plot) if plot else '0'

            # Crew
            crew = episode_item.get('credits', {}).get('crew', []) or show_item.get('crew', [])
            crew = [c for c in crew if c.get('job') in ('Director', 'Writer')]
            director = '/'.join([d['name'] for d in crew if d.get('job') == 'Director']) or '0'
            writer = '/'.join([w['name'] for w in crew if w.get('job') == 'Writer']) or '0'

            # Cast
            castwiththumb = []
            try:
                creds = episode_item.get('credits', {})
                cast = creds.get('cast', [])[:30] + creds.get('guest_stars', [])[:30]
                for person in cast:
                    profile_path = person.get('profile_path', '')
                    icon = self.tmdb_img_link % (c.tmdb_profilesize, profile_path) if profile_path else ''
                    castwiththumb.append({
                        'name': person.get('name', ''),
                        'role': person.get('character', ''),
                        'thumbnail': icon
                    })
            except Exception:
                pass

            # Unaired check
            unaired = ''
            if premiered != '0':
                premiered_num = int(re.sub('[^0-9]', '', premiered))
                today_num = int(re.sub('[^0-9]', '', str(self.today_date)))
                if premiered_num > today_num:
                    unaired = 'true'
                    if self.showunaired != 'true':
                        raise Exception('Unaired episode hidden')

            return {
                'title': title, 'season': season, 'episode': episode, 'year': year,
                'imdb': show_imdb, 'tmdb': show_tmdb, 'tvdb': show_tvdb, 'trakt': show_trakt,
                'status': status, 'studio': studio, 'premiered': premiered, 'genre': genre,
                'duration': duration, 'rating': rating, 'votes': votes, 'mpaa': mpaa,
                'director': director, 'writer': writer, 'castwiththumb': castwiththumb,
                'plot': plot, 'tagline': tagline, 'countries': countries, 'trailer': trailer,
                'label': label, 'resume_point': resume_point, 'tvshowtitle': show_title,
                'unaired': unaired, 'in_widget': in_widget
            }
        except Exception as e:
            return {}

    def _handle_artwork(self, show_tvdb, show_tmdb):
        """Fetch artwork from fanart.tv and TMDB fallbacks with show-level caching."""
        try:
            # Check cache first (artwork is show-level, not episode-level)
            cache_key = (show_tvdb, show_tmdb)
            if cache_key in self._artwork_cache:
                return self._artwork_cache[cache_key]

            poster = fanart = banner = landscape = clearlogo = clearart = '0'

            # Fanart.tv
            if show_tvdb and show_tvdb != '0':
                try:
                    tempart = fanart_tv.get_fanart_tv_art(tvdb=show_tvdb)
                    poster = tempart.get('poster', poster)
                    fanart = tempart.get('fanart', fanart)
                    banner = tempart.get('banner', banner)
                    landscape = tempart.get('landscape', landscape)
                    clearlogo = tempart.get('clearlogo', clearlogo)
                    clearart = tempart.get('clearart', clearart)
                except Exception:
                    pass

            # TMDB fallback
            if poster == '0':
                try:
                    p, f = self.get_tmdb_art(show_tmdb)
                    poster = p or poster
                    fanart = f or fanart
                except Exception:
                    pass

            # Default fallbacks
            if poster == '0':
                poster = c.addon_poster()
            if fanart == '0':
                fanart = c.addon_fanart()

            artwork = {
                'poster': poster, 'fanart': fanart, 'banner': banner, 'landscape': landscape,
                'clearlogo': clearlogo, 'clearart': clearart, 'thumb': landscape or fanart
            }
            # Cache for reuse across episodes of same show
            self._artwork_cache[cache_key] = artwork
            return artwork
        except Exception as e:
            return {'poster': '0', 'fanart': '0', 'banner': '0', 'landscape': '0', 'clearlogo': '0', 'clearart': '0', 'thumb': '0'}

    def _build_enriched_item(self, metadata, original_item):
        """Build the final enriched item dict."""
        try:
            return {
                'title': metadata['title'], 'originaltitle': metadata['title'], 'year': metadata['year'],
                'imdb': metadata['imdb'], 'tvdb': metadata['tvdb'], 'tmdb': metadata['tmdb'],
                'status': metadata['status'], 'studio': metadata['studio'], 'poster': metadata['poster'],
                'banner': metadata['banner'], 'fanart': metadata['fanart'], 'fanart2': metadata['fanart'],
                'landscape': metadata['landscape'], 'discart': metadata['clearart'], 'clearlogo': metadata['clearlogo'],
                'clearart': metadata['clearart'], 'premiered': metadata['premiered'], 'genre': metadata['genre'],
                'thumb': metadata['thumb'], 'in_widget': metadata['in_widget'], 'duration': metadata['duration'],
                'rating': metadata['rating'], 'votes': metadata['votes'], 'mpaa': metadata['mpaa'],
                'director': metadata['director'], 'writer': metadata['writer'], 'castwiththumb': metadata['castwiththumb'],
                'plot': metadata['plot'], 'tagline': metadata['tagline'], 'countries': metadata['countries'],
                'trailer': metadata['trailer'], 'label': metadata['label'], 'resume_point': metadata['resume_point'],
                'trakt': metadata['trakt'], '_last_watched': original_item.get('_last_watched', '0'),
                'tvshowtitle': metadata['tvshowtitle'], 'season': metadata['season'], 'episode': metadata['episode'],
                'action': original_item.get('action'), 'unaired': metadata['unaired'],
                '_sort_key': max(original_item.get('_last_watched', '0'), metadata['premiered'])
            }
        except Exception as e:
            return {}

    def _update_list_entry(self, i, enriched_item):
        """Safely update self.list[i] with the enriched item."""
        try:
            if self.list and i < len(self.list):
                if self.list[i] is None or not isinstance(self.list[i], dict):
                    self.list[i] = enriched_item
                else:
                    self.list[i].update(enriched_item)
        except Exception as e:
            pass

    def _append_meta(self, enriched_item, show_imdb, show_tmdb, show_tvdb, resume_point):
        """Append to self.meta for caching."""
        try:
            meta_entry = {
                'imdb': show_imdb, 'tmdb': show_tmdb, 'tvdb': show_tvdb, 'lang': self.lang,
                'user': self.user, 'resume_point': resume_point, 'item': enriched_item
            }
            self.meta.append(meta_entry)
        except Exception as e:
            pass

    def _get_calendar(self, url, idx):
        sortorder = c.get_setting('prgr.sortorder')

        # Handle progress modes embedded in URL
        progress_mode = None
        if url == 'progress_lastwatched':
            url = 'progress'
            progress_mode = 0
        elif url == 'progress_unwatched':
            url = 'progress'
            progress_mode = 1

        # Define constants for magic strings
        url_elements = ['tvProgress', 'tvmaze']

        for element in url_elements:
            if element in url:
                break
        else:
            # Handle new calendar shortcuts (calendar_today, calendar_thisweek, etc.)
            if url in ['calendar_today', 'calendar_thisweek', 'calendar_nextweek']:
                url = getattr(self, f'{url}_link')
            elif not hasattr(self, f'{url}_link'):
                # Handle attribute error
                raise AttributeError(f"Attribute '{url}_link' does not exist")
            else:
                url = getattr(self, f'{url}_link')

        # Save original URL before date transformation for comparison purposes
        url_original = url

        ####cm#
        # Making it possible to use date[xx] in url's where xx is a str(int)
        for i in re.findall(r'date\[(\d+)\]', url):
            url = url.replace(
                f'date[{i}]',
                (self.datetime - datetime.timedelta(days=int(i))).strftime('%Y-%m-%d')
                )


        if url == 'tvProgress':
            #self.list = cache.get(self.episodes_progress_list, 0)
            self.list = self.episodes_progress_list()
        if url == self.progress_link:
            # self.blist = cache.get(self.trakt_progress_list, 720, url)
            # self.list = cache.get(self.trakt_progress_list, 0, url)
            self.list = self.trakt_progress_list(url, progress_mode)

        elif url == self.ondeck_link:
            self.blist = cache.get(self.trakt_episodes_list, 720, url, self.trakt_user, self.lang)
            self.list = cache.get(self.trakt_episodes_list, 0, url, self.trakt_user, self.lang)
            # Ensure self.list is a valid list before sorting
            if isinstance(self.list, list) and self.list:
                self.list = sorted(self.list, key=lambda k: k.get('premiered', ''), reverse=True)
            else:
                self.list = []

        elif url_original == self.mycalendar_link:
            self._load_trakt_episodes_with_cache(url)
            # Sort by premiered ascending (oldest first) for calendar views
            if isinstance(self.list, list) and self.list:
                self.list = sorted(self.list, key=lambda k: k.get('premiered', ''), reverse=False)
        elif url_original == self.added_link:
            self._load_trakt_episodes_with_cache(url)
            # Sort by premiered ascending (oldest first) for calendar views
            if isinstance(self.list, list) and self.list:
                self.list = sorted(self.list, key=lambda k: k.get('premiered', ''), reverse=False)
        # New calendar endpoints (added 2026-03-10)
        # NOTE: Trakt calendar API has timezone issues - it filters by UTC air timestamp, not premiered date
        # So we filter client-side by 'premiered' field to show correct local dates
        elif url_original == self.calendar_today_link:
            self._load_trakt_episodes_with_cache(url)
            # Filter to only show episodes that premiered today (ignore timezone artifacts)
            if self.list:
                pass
            try:
                today = datetime.datetime.now(datetime.timezone.utc).date()

                filtered_list = []
                for item in self.list:
                    premiered = item.get('premiered', '')
                    if premiered:
                        try:
                            air_date = datetime.datetime.strptime(premiered, '%Y-%m-%d').date()
                            # Keep only episodes that premiered exactly today
                            if air_date == today:
                                filtered_list.append(item)
                        except (ValueError, TypeError):
                            pass  # Skip items with invalid dates

                # Sort by premiered date (earliest first)
                self.list = sorted(filtered_list, key=lambda x: x.get('premiered', ''), reverse=False)
                if self.list:
                    pass
            except Exception as e:
                pass
        elif url_original == self.calendar_thisweek_link:
            self._load_trakt_episodes_with_cache(url)
            # Filter to only show episodes in the next 7 days (today through day 6)
            try:
                today = datetime.datetime.now(datetime.timezone.utc).date()
                day_6 = today + datetime.timedelta(days=6)

                filtered_list = []
                for item in self.list:
                    premiered = item.get('premiered', '')
                    if premiered:
                        try:
                            air_date = datetime.datetime.strptime(premiered, '%Y-%m-%d').date()
                            # Keep episodes airing from today through 6 days from now (7 days total)
                            if today <= air_date <= day_6:
                                filtered_list.append(item)
                        except (ValueError, TypeError):
                            pass  # Skip items with invalid dates

                # Sort by premiered date (earliest first)
                self.list = sorted(filtered_list, key=lambda x: x.get('premiered', ''), reverse=False)
            except Exception as e:
                pass
        elif url_original == self.calendar_nextweek_link:
            self._load_trakt_episodes_with_cache(url)
            # Filter to only show episodes 7-14 days from now
            # (We fetch 14 days but only want the second week)
            try:
                today = datetime.datetime.now(datetime.timezone.utc).date()
                day_7 = today + datetime.timedelta(days=7)
                day_14 = today + datetime.timedelta(days=14)

                filtered_list = []
                for item in self.list:
                    premiered = item.get('premiered', '')
                    if premiered:
                        try:
                            air_date = datetime.datetime.strptime(premiered, '%Y-%m-%d').date()
                            # Keep episodes that air between 7 and 14 days from now (exclusive of day 7, inclusive of day 14)
                            if day_7 < air_date <= day_14:
                                filtered_list.append(item)
                        except (ValueError, TypeError):
                            pass  # Skip items with invalid dates

                # Sort by premiered date (earliest first)
                self.list = sorted(filtered_list, key=lambda x: x.get('premiered', ''), reverse=False)
            except Exception as e:
                pass
        elif url == self.trakthistory_link:
            self.list = cache.get(self.trakt_episodes_list, 1, url, self.trakt_user, self.lang)
            self.list = sorted(self.list, key=lambda k: int(k['watched_at']), reverse=True)

        elif self.trakt_link in url and '/users/' in url:
            #self.list = cache.get(self.trakt_list, 0, url, self.trakt_user)
            self.list = self.trakt_list(url, self.trakt_user)
            self.list = self.list[::-1]

        elif self.trakt_link in url:
            self.list = cache.get(self.trakt_list, 1, url, self.trakt_user)

        elif self.tvmaze_link in url:
            self.list = cache.get(self.tvmaze_list, 1, url, False)



        # For calendar views: preserve fresh metadata from Trakt/TMDB, but still use worker for cached artwork
        # Include ALL calendar views: today/thisweek/nextweek/mycalendar/added
        is_calendar_view = url_original in [
            self.calendar_today_link,
            self.calendar_thisweek_link,
            self.calendar_nextweek_link,
            self.mycalendar_link,
            self.added_link
        ]

        if idx:
            if is_calendar_view:
                # Save original metadata from Trakt/TMDB (fresh data, not stale cache)
                # Preserve: premiered dates, episode titles, plots, ratings, etc.
                # Use composite key: (imdb or tvdb, season, episode) to uniquely identify each episode
                preserved_metadata = {}
                for item in self.list:
                    if item:
                        key_id = item.get('imdb') or item.get('tvdb') or item.get('tmdb')
                        season = item.get('season', '')
                        episode = item.get('episode', '')
                        if key_id:
                            # Preserve critical metadata fields that should come from fresh API data
                            preserved_metadata[(key_id, season, episode)] = {
                                'premiered': item.get('premiered', ''),
                                'title': item.get('title', ''),  # Episode title (e.g., "His name was Martin")
                                'plot': item.get('plot', ''),
                                'rating': item.get('rating', '0'),
                                'votes': item.get('votes', '0'),
                                'unaired': item.get('unaired', '')  # Preserve unaired flag for correct coloring
                            }

                # Call worker for metadata enrichment (gets cached artwork: posters, fanart, etc.)
                self.worker(0)

                # Restore original metadata (prevent metacache from overlaying stale/missing data)
                for item in self.list:
                    if item:
                        key_id = item.get('imdb') or item.get('tvdb') or item.get('tmdb')
                        season = item.get('season', '')
                        episode = item.get('episode', '')
                        if key_id and (key_id, season, episode) in preserved_metadata:
                            # Restore fresh metadata fields
                            for field, value in preserved_metadata[(key_id, season, episode)].items():
                                # Special case: 'unaired' can be '' (falsy) which is valid (means aired)
                                if field == 'unaired':
                                    item[field] = value
                                elif value and value != '0':  # Only restore other fields if we have valid data
                                    item[field] = value
                            # Remove 'label' so episodeDirectory recreates it from the correct episode title
                            # (worker sets label=show_title for non-showimdb items, causing duplicate show names)
                            if 'label' in item:
                                del item['label']
            else:
                self.worker(0)

        # Skip sortorder sorting for calendar views (they have custom ascending sort)
        if not is_calendar_view:
            if sortorder == '0':
                if self.list and isinstance(self.list, list):
                    # Filter out None items before sorting
                    self.list = [item for item in self.list if item is not None and isinstance(item, dict)]
                    self.list = sorted(self.list, key=lambda k: k.get('premiered', ''), reverse=True)
                else:
                    self.list = []
            elif self.list and isinstance(self.list, list):
                for i in self.list:
                    # c.log(f"[CM Debug @ 970 in episodes.py] all keys in i = {repr(list(i.keys()))}")
                    # c.log(f"[CM Debug @ 937 in episodes.py] _sort_key = {i['_sort_key']}")
                    self.list = sorted(self.list, key=lambda k: k.get('_sort_key', ''), reverse=True)
            else:
                # Only show dialog in dev mode to avoid spamming users when Trakt not authenticated
                if c.devmode:
                    c.infoDialog(f'self.list is empty, url = {url}', 'Error', icon='main_classy.png', time=5000, sound=False)

        self.episodeDirectory(self.list)
        return self.list

    def _load_trakt_episodes_with_cache(self, url):
        """
        Populate self.blist from a long‑TTL cache and self.list as the fresh result.
        This avoids doubling external requests and lets trakt_episodes_list reuse cached entries.
        """
        # long‑lived cached backup (used for reusing artwork/metadata if available)
        try:
            self.blist = cache.get(self.trakt_episodes_list, 720, url, self.trakt_user, self.lang) or []
        except Exception as e:
            self.blist = []

        # fresh list (short/no cache) for current UI
        try:
            self.list = cache.get(self.trakt_episodes_list, 0, url, self.trakt_user, self.lang) or []
        except Exception as e:
            self.list = []

        # normalize/safe sort
        try:
            if isinstance(self.list, list) and self.list:
                self.list = sorted(self.list, key=lambda k: k.get('premiered', ''), reverse=True)
            else:
                self.list = []
        except Exception as e:
            self.list = []



    def _fetch_trakt_episode_lists_deleted(self, url):
        #self.blist = cache.get(self.trakt_episodes_list, 720, url, self.trakt_user, self.lang)
        self.blist = self.trakt_episodes_list(url, self.trakt_user, self.lang)
        #self.list = cache.get(self.trakt_episodes_list, 0, url, self.trakt_user, self.lang)
        self.list = self.trakt_episodes_list(url, self.trakt_user, self.lang)
        self.list = sorted(self.list, key=lambda k: k['premiered'], reverse=True)
        #except Exception as e:
    def widget(self):
        pass

        if trakt.getTraktIndicatorsInfo() is True:
            setting = c.get_setting('tv.widget.alt')
        else:
            setting = c.get_setting('tv.widget')

        if setting == '2':
            self.calendar(self.progress_link)
        elif setting == '3':
            self.calendar(self.mycalendar_link)
        else:
            self.calendar(self.added_link)

    def calendars(self, idx=True):
        months_list = control.lang(32060).split('|')
        days_list = control.lang(32061).split('|')

        for i in range(7): # cm - Changed from 30 to 7 days (2026-02-24) - reduces menu clutter and talk show spam
            try:
                _date = (self.datetime - datetime.timedelta(days=i))
                year_int = _date.strftime('%Y')
                month_day_int = _date.strftime('%d') #cm - day of month zero padded
                name_month_int = int(_date.strftime('%m')) #cm - month as padded with 0 string starting with 01 = january
                name_day_int = _date.isoweekday() #cm - weekday as decimal int starting where 1 = monday

                part_a = days_list[name_day_int-1]
                part_b = f"{month_day_int} {months_list[name_month_int-1]} {year_int}"
                name = (control.lang(32062) % (part_a, part_b))
                url = self.calendar_link % (self.datetime - datetime.timedelta(days=i)).strftime('%Y-%m-%d')
                # self.list.append({'name': name, 'url': url, 'image': 'calendar.png', 'action': 'calendar'})

                if self.list is not None:
                    self.list.append({'name': name, 'url': url, 'image': 'calendar.png', 'action': 'calendar'})
                else:
                    self.list = [{'name': name, 'url': url, 'image': 'calendar.png', 'action': 'calendar'}]
            except Exception as e:
                pass

        if idx is True:
            self.addDirectory(self.list)
        return self.list

    def userlists(self):
        userlists = []

        # ensure trakt credentials and get activity; return empty list early if no credentials
        if not trakt.get_trakt_credentials_info():
            return []

        try:
            activity = trakt.getActivity_from_db()
        except Exception as e:
            activity = 0

        def fetch_lists(link):
            try:
                # choose cache timeout based on activity freshness
                if activity <= cache.timeout(self.trakt_user_list, link, self.trakt_user):
                    return cache.get(self.trakt_user_list, 720, link, self.trakt_user) or []
                return cache.get(self.trakt_user_list, 0, link, self.trakt_user) or []
            except Exception as e:
                return []

        # fetch both user lists and liked lists
        userlists.extend(fetch_lists(self.traktlists_link))
        userlists.extend(fetch_lists(self.traktlikedlists_link))

        # normalize and annotate each entry in-place
        self.list = []
        for idx, itm in enumerate(userlists):
            try:
                itm_dict = dict(itm)
            except Exception:
                # fallback: wrap scalar values
                itm_dict = {'name': itm} if isinstance(itm, str) else {}
            itm_dict['image'] = 'userlists.png'
            itm_dict['action'] = 'calendar'
            self.list.append(itm_dict)

        self.addDirectory(self.list, queue=True)
        return self.list

    def get_media_info(self, result, key, return_type='', default_value='0'):
        """
        Returns a value from a dictionary based on the key.
        If the value is a list or dictionary, it can be converted to a string or integer.
        If the value is a string and the return type is int, it will be converted to an integer.
        :param result: The dictionary to retrieve the value from.
        :param key: The key to retrieve the value for.
        :param return_type: The type to return the value as. Options are str, int, list, dict.
        :param default_value: The value to return if the key is not found.
        :return: The value from the dictionary.
        """

        def convert_to(return_type, value):
            if return_type == 'str':
                return ' / '.join(map(str, value))
            if return_type == 'int':
                return sum(1 for _ in value)
            if return_type == 'list':
                return list(value.items())
            return dict(enumerate(value)) if return_type == 'dict' else value

        if key == '':
            # return all keys as values
            return [convert_to(return_type, result[k]) for k in result.keys()]
        value = result.get(key, default_value)
        return convert_to(return_type, value)

    def get_media_info_old(self, result, key, return_type='', default_value='0'):
        pass

        def check_numeric(value):
            return int(value) if value.isnumeric() else len(value)

        def get_list_from_dict(d):
            # d is expected to be a dict or iterable; return list of (key, value) pairs
            if isinstance(d, dict) and len(d.keys()) > 0:
                return list(d.items())
            # treat as iterable/list and convert to (keyN, value) pairs
            list_from_dict = []
            for x, item in enumerate(d):
                k = f'key{x}'
                list_from_dict.append((k, item))
            return list_from_dict


        def get_dict_from_list(l):
            # if it's already a dict-like with keys return its items, otherwise enumerate the list into a dict
            if isinstance(l, dict) and len(l.keys()) > 0:
                return list(l.items())
            return dict(enumerate(l))


        def get_key_info(result, key):
            if key not in result or result[key] is None:
                result[key] = default_value

            val = result[key]

            if isinstance(val, list) and return_type == 'dict':
                return get_dict_from_list(val)
            if isinstance(val, dict) and return_type == 'list':
                # check if key exists in dict
                return get_list_from_dict(val)
            if isinstance(val, str):
                return check_numeric(val) if return_type == 'int' else val
            return val

        if key == '':
            #return all keys as values
            r = []
            for k in result.keys():
                r.append(get_key_info(result, k))
            return r
        return get_key_info(result, key)

    def trakt_list(self, url, user, return_art=True):
        # sourcery skip: use-contextlib-suppress
        # sourcery skip: use-contextlib-suppress
        """
        Fetch a trakt list and parse items into a simplified itemlist.
        Refactored to reduce nesting and number of locals; narrower exception handling.
        """
        # replace date[n] placeholders with actual dates (one-per-match)
        for i in re.findall(r'date\[(\d+)\]', url):
            repl_date = (self.datetime - datetime.timedelta(days=int(i))).strftime('%Y-%m-%d')
            url = url.replace(f'date[{i}]', repl_date)

        q = dict(parse_qsl(urlsplit(url).query))
        q['extended'] = 'full'
        q = urlencode(q).replace('%2C', ',')
        u = url.replace(f'?{urlparse(url).query}', '') + '?' + q

        try:
            items = trakt.getTraktAsJson(u)
        except (ValueError, requests.RequestException, crew_errors.TraktResourceError) as e:
            return []

        if not items:
            return []

        itemlist = []

        def _parse_item(item):
            """Parse a single trakt item into the expected dict or return None on parse errors."""
            try:
                # c.log(
                #     "[CM Debug @ 1052 in episodes.py] item is of "
                #     f"type {type(item)}\n\nitem = {item}"
                # )

                # defaults
                poster = fanart = banner = landscape = clearlogo = clearart = '0'
                resume_point = item.get('progress', 0.0)

                # last_watched extraction
                last_watched = '0'
                ep_info = item.get('episode') or {}
                show_info = item.get('show') or {}
                if isinstance(ep_info, dict) and 'updated_at' in ep_info:
                    last_watched = ep_info.get('updated_at', '0')
                elif isinstance(show_info, dict) and 'updated_at' in show_info:
                    last_watched = show_info.get('updated_at', '0')

                # use `or` instead of conditional expression
                tvshowtitle = show_info.get('title') or '0'

                title = ep_info.get('title') if isinstance(ep_info, dict) else None
                if not title:
                    raise ValueError("Missing episode title")
                title = client.replaceHTMLCodes(title)

                # normalize season/episode numbers
                season_raw = ep_info.get('season')
                season = f'{int(season_raw):01d}' if season_raw is not None else '0'
                if season == '0' and self.specials != 'true':
                    raise ValueError("Specials disabled")

                episode_raw = ep_info.get('number')
                episode = f'{int(episode_raw):01d}' if episode_raw is not None else '0'
                if episode == '0':
                    raise ValueError("Invalid episode number")

                # ids
                ids = show_info.get('ids') or {}
                imdb = ids.get('imdb') or '0'
                if imdb != '0':
                    imdb = 'tt' + re.sub('[^0-9]', '', str(imdb))

                tvdb = ids.get('tvdb', '0') or '0'
                if tvdb != '0':
                    tvdb = re.sub('[^0-9]', '', str(tvdb))

                tmdb = ids.get('tmdb', '0')
                if tmdb == '0' or not tmdb:
                    raise ValueError("Missing TMDB id")
                tmdb = str(tmdb)

                year = re.sub('[^0-9]', '', str(show_info.get('year', '0')))

                premiered = ep_info.get('first_aired', None)
                # guard against None when using regex
                try:
                    m = re.search(r'(\d{4}-\d{2}-\d{2})', premiered or '')
                    premiered = m[1] if m else '0'
                except (TypeError, AttributeError):
                    premiered = '0'

                studio = show_info.get('network') or '0'

                genre_list = show_info.get('genres') or '0'
                if genre_list != '0':
                    genre_list = [g.title() for g in genre_list]
                    genre = ' / '.join(genre_list)
                else:
                    genre = '0'

                duration = str(show_info.get('runtime') or '0')
                rating = str(ep_info.get('rating') or '0')
                votes = str(ep_info.get('votes') or '0')
                if votes != '0':
                    try:
                        votes = str(format(int(votes), ',d'))
                    except (ValueError, TypeError):
                        pass

                mpaa = show_info.get('certification') or '0'

                plot = ep_info.get('overview') or show_info.get('overview') or '0'
                if plot != '0':
                    plot = client.replaceHTMLCodes(plot)

                paused_at = item.get('paused_at', '0') or '0'
                if paused_at != '0':
                    paused_at = re.sub('[^0-9]+', '', paused_at)

                watched_at = item.get('watched_at', '0') or '0'
                if watched_at != '0':
                    watched_at = re.sub('[^0-9]+', '', watched_at)

                # localized title/plot
                if self.lang != 'en' and imdb != '0':
                    try:
                        trans = trakt.getTVShowTranslation(
                            imdb, lang=self.lang, season=season, episode=episode, full=True
                        )
                        if trans:
                            title = trans.get('title') or title
                            plot = trans.get('overview') or plot
                    except (crew_errors.TraktResourceError, ValueError, TypeError, requests.RequestException) as _e:
                        pass

                # collect artwork if fanart is enabled
                if c.get_setting('fanart') == 'true' and return_art:
                    if tvdb != '0':
                        try:
                            tempart = fanart_tv.get_fanart_tv_art(tvdb=tvdb)

                            if tempart:
                                poster = tempart.get('poster', poster)
                                fanart = tempart.get('fanart', fanart)
                                banner = tempart.get('banner', banner)
                                landscape = tempart.get('landscape', landscape)
                                clearlogo = tempart.get('clearlogo', clearlogo)
                                clearart = tempart.get('clearart', clearart)
                        except (requests.RequestException, KeyError, TypeError) as _e:
                            pass

                    if poster == '0':
                        p, f = self.get_tmdb_art(tmdb)
                        poster = p or poster
                        if f and f != '0':
                            fanart = f
                            landscape = f

                return {
                    'title': title,
                    'season': season,
                    'episode': episode,
                    'tvshowtitle': tvshowtitle,
                    'year': year,
                    'premiered': premiered,
                    'status': 'Continuing',
                    'studio': studio,
                    'genre': genre,
                    'duration': duration,
                    'rating': rating,
                    'votes': votes,
                    'mpaa': mpaa,
                    'plot': plot,
                    'imdb': imdb,
                    'tvdb': tvdb,
                    'tmdb': tmdb,
                    'poster': poster,
                    'thumb': landscape,
                    'fanart': fanart,
                    'banner': banner,
                    'landscape': landscape,
                    'clearlogo': clearlogo,
                    'clearart': clearart,
                    'paused_at': paused_at,
                    'watched_at': watched_at,
                    '_last_watched': last_watched,
                    'resume_point': resume_point,
                }
            except (KeyError, TypeError, ValueError) as e:
                return None
            except Exception as e:
                return None

        for itm in items:
            parsed = _parse_item(itm)
            if parsed:
                itemlist.append(parsed)

        itemlist = itemlist[::-1]
        return itemlist

    def get_show_watched_progress(self, trakt_id, hidden=False, specials=False, count_specials=False):
        url = self.show_watched_link % (trakt_id, hidden, specials, count_specials)
        return trakt.getTraktAsJson(url)

    def episodes_progress_list(self):
        try:
            progress = trakt.get_trakt_progress('episode') # type: ignore

            def add_episode_with_metadata(item):
                try:
                    tmdb = str(item['tmdb'])
                    tvdb = str(item['tvdb'])
                    imdb = item['imdb']
                    trakt_id = str(item['trakt'])

                    showtmdb = str(item['showtmdb'])
                    showtvdb = str(item['showtvdb'])
                    showimdb = item['showimdb']
                    showtrakt = str(item['showtrakt'])

                    tvshowtitle = item['tvshowtitle']
                    last_played = item['last_played']

                    title = item['title']
                    season = str(item['season'])
                    episode = str(item['episode'])
                    resume_point = item['resume_point']
                    year = item['year']
                    mediatype = item['media_type']
                    action = 'episode'

                    # Fetch full show metadata from Trakt API
                    try:
                        show_url = f"{self.trakt_link}/shows/{showtrakt}?extended=full"
                        show_data = trakt.getTraktAsJson(show_url) or {}
                        if not isinstance(show_data, dict):  # Type safety for linter
                            show_data = {}

                        duration = show_data.get('runtime', 45)
                        if duration == 1:  # Trakt sometimes returns 1
                            duration = 45

                        plot = show_data.get('overview', c.lang(32012))
                        plot = client.replaceHTMLCodes(plot)

                        studio = show_data.get('network', '0')
                        network = show_data.get('network', '0')
                        mpaa = show_data.get('certification', '0')
                        status = show_data.get('status', '0')
                        country = (show_data.get('country') or '0').upper()
                        tagline = show_data.get('tagline', '0')
                        if tagline != '0':
                            tagline = client.replaceHTMLCodes(tagline)

                        genre = show_data.get('genres', [])
                        if genre:
                            genre = '/'.join(genre)
                        else:
                            genre = '0'

                        trailer = str(show_data.get('trailer') or '0')
                        first_aired = show_data.get('first_aired', '0')
                        aired_episodes = int(show_data.get('aired_episodes', 0))

                    except Exception as meta_error:
                        # Fallback to minimal metadata
                        duration = 45
                        plot = c.lang(32012)
                        studio = network = mpaa = status = country = tagline = genre = trailer = first_aired = '0'
                        aired_episodes = 0

                    # Initialize artwork defaults
                    thumb = c.addon_thumb()  # Episode still default
                    season_poster = poster = fanart = '0'
                    banner = clearlogo = clearart = landscape = '0'

                    c.log(f'[CM ART] Fetching artwork for {tvshowtitle} S{season}E{episode}')

                    # Fetch episode thumbnail (still) from TMDB
                    try:
                        if showtmdb and showtmdb != '0':
                            episode_url = self.tmdb_episode_link % (showtmdb, season, episode)
                            response_text = cache.get(client.request, 24, episode_url)

                            if response_text:
                                episode_data = json.loads(response_text)
                                still_path = episode_data.get('still_path') if isinstance(episode_data, dict) else None
                                if still_path:
                                    thumb = self.tmdb_img_link % (c.tmdb_stillsize, still_path)
                                    c.log(f'[CM ART]   (OK) Episode still: {thumb[:80]}...')
                                else:
                                    c.log(f'[CM ART]   (X) No episode still_path from TMDB')

                    except Exception as thumb_error:
                        c.log(f'[CM ART]   (X)(X) Exception fetching episode still: {str(thumb_error)}')

                    # Fetch season poster from TMDB
                    try:
                        if showtmdb and showtmdb != '0':
                            season_url = self.tmdb_season_link % (showtmdb, season, self.lang)
                            c.log(f'[CM ART]   Fetching season poster: {season_url[:100]}...')
                            season_response = cache.get(client.request, 24, season_url)

                            if season_response:
                                season_data = json.loads(season_response)
                                c.log(f'[CM ART]   Season data is dict: {isinstance(season_data, dict)}')
                                poster_path = season_data.get('poster_path') if isinstance(season_data, dict) else None
                                c.log(f'[CM ART]   Season poster_path: {poster_path}')
                                if poster_path:
                                    season_poster = self.tmdb_img_link % (c.tmdb_postersize, poster_path)
                                    poster = season_poster  # Use season poster as primary poster
                                    c.log(f'[CM ART]   (OK) Season poster: {season_poster[:80]}...')
                                else:
                                    c.log(f'[CM ART]   (X) No season poster_path')
                            else:
                                c.log(f'[CM ART]   (X) No season response from TMDB')

                    except Exception as season_error:
                        c.log(f'[CM ART]   (X)(X) Exception fetching season poster: {str(season_error)}')

                        c.log(f'[CM ART]   Traceback: {traceback.format_exc()}')

                    # Fetch show-level poster and fanart from TMDB if not yet set
                    try:
                        if showtmdb and showtmdb != '0' and poster == '0':
                            show_url = f"{self.tmdb_link}tv/{showtmdb}?api_key={self.tmdb_user}&language={self.lang}"
                            c.log(f'[CM ART]   Fetching show art (no season poster): {show_url[:100]}...')
                            show_response = cache.get(client.request, 24, show_url)

                            if show_response:
                                show_data = json.loads(show_response)
                                if isinstance(show_data, dict):
                                    show_poster_path = show_data.get('poster_path')
                                    if show_poster_path and poster == '0':
                                        poster = self.tmdb_img_link % (c.tmdb_postersize, show_poster_path)
                                        c.log(f'[CM ART]   (OK) Show poster (fallback): {poster[:80]}...')

                                    show_fanart_path = show_data.get('backdrop_path')
                                    if show_fanart_path:
                                        fanart = self.tmdb_img_link % (c.tmdb_fanartsize, show_fanart_path)
                                        c.log(f'[CM ART]   (OK) Show fanart: {fanart[:80]}...')
                        elif poster != '0':
                            c.log(f'[CM ART]   Skipping show art fetch - already have season poster')
                            # Still fetch fanart
                            if showtmdb and showtmdb != '0':
                                show_url = f"{self.tmdb_link}tv/{showtmdb}?api_key={self.tmdb_user}&language={self.lang}"
                                show_response = cache.get(client.request, 24, show_url)
                                if show_response:
                                    show_data = json.loads(show_response)
                                    if isinstance(show_data, dict):
                                        show_fanart_path = show_data.get('backdrop_path')
                                        if show_fanart_path:
                                            fanart = self.tmdb_img_link % (c.tmdb_fanartsize, show_fanart_path)
                                            c.log(f'[CM ART]   (OK) Show fanart: {fanart[:80]}...')

                    except Exception as show_error:
                        c.log(f'[CM ART]   (X)(X) Exception fetching show art: {str(show_error)}')

                    # Fetch extended artwork from fanart.tv
                    try:
                        if self.show_fanart and showtvdb and showtvdb not in ('0', None, ''):
                            # Verbose fanart fetching logged per show commented out for performance
                            # c.log(f'[CM ART]   Fetching fanart.tv art for tvdb={showtvdb}')
                            tv_fanart = cache.get(fanart_tv.get_fanart_tv_art, 72, showtvdb)
                            if tv_fanart:
                                # c.log(f'[CM ART]   fanart.tv returned keys: {list(tv_fanart.keys())}')
                                # Use fanart.tv artwork, fallback to TMDB if not available
                                poster = tv_fanart.get('poster', poster)
                                fanart = tv_fanart.get('fanart', fanart) or fanart
                                banner = tv_fanart.get('banner', '0')
                                clearlogo = tv_fanart.get('clearlogo', '0')
                                clearart = tv_fanart.get('clearart', '0')
                                landscape = tv_fanart.get('landscape', '0')
                                c.log(f'[CM ART]   (OK) fanart.tv art applied')
                            else:
                                c.log(f'[CM ART]   (X) No fanart.tv data')
                        else:
                            c.log(f'[CM ART]   Skipping fanart.tv (show_fanart={self.show_fanart}, tvdb={showtvdb})')

                    except Exception as fanart_error:
                        c.log(f'[CM ART]   (X)(X) Exception fetching fanart.tv art: {str(fanart_error)}')

                    c.log(f'[CM ART] Final artwork - poster: {poster[:50] if poster != "0" else "0"}... | fanart: {fanart[:50] if fanart != "0" else "0"}...')

                    return {
                        'title': title, 'imdb': imdb, 'tmdb': tmdb, 'tvdb': tvdb,
                        'trakt': trakt_id, 'showimdb': showimdb, 'showtmdb': showtmdb,
                        'showtvdb': showtvdb, 'showtrakt': showtrakt,
                        'season': season, 'episode': episode, 'tvshowtitle': tvshowtitle,
                        'resume_point': resume_point, 'year': year, '_last_watched': last_played,
                        'mediatype': mediatype, 'action': action,
                        'duration': duration, 'plot': plot, 'studio': studio, 'network': network,
                        'mpaa': mpaa, 'status': status, 'country': country, 'tagline': tagline,
                        'genre': genre, 'trailer': trailer, 'first_aired': first_aired,
                        'aired_episodes': aired_episodes,
                        'thumb': thumb,  # Episode still
                        'season_poster': season_poster,  # Season-specific poster
                        'poster': poster,  # Show/season poster
                        'fanart': fanart,  # Show backdrop
                        'banner': banner,  # Show banner
                        'clearlogo': clearlogo,  # Show clear logo
                        'clearart': clearart,  # Show clear art
                        'landscape': landscape,  # Show landscape
                    }
                except Exception as e:
                    return None

            # Process episodes with threading for faster metadata fetch
            max_threads = c.get_max_threads(len(progress))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
                futures = {executor.submit(add_episode_with_metadata, item): item for item in progress}

                for future in concurrent.futures.as_completed(futures):
                    try:
                        result = future.result()
                        if result:
                            self.list.append(result)
                    except Exception as exc:
                        pass

            return self.list

        except Exception as e:
            failure = traceback.format_exc()
            pass

    def trakt_progress_list(self, url, progress_mode=None):
        try:
            url += '?extended=full'
            result = trakt.getTraktAsJson(url)
            # c.log(f"[CM Debug @ 1432 in episodes.py] result = {result}")
            items = []
        except Exception as e:
            c.log(f"Exception 1 in trakt_progress_list: {e}")
            return
        sortorder = c.get_setting('prgr.sortorder')


        if not result:
            return self.list


        def add_item(item):
            try:
                # c.log(f"[CM Debug @ 1447 in episodes.py] inside add_item: item = {item.get('show').get('title')}")
                # c.log(f"[CM Debug @ 1758 in episodes.py] item = {item}")
                add = True
                num_1, num_2 = 0, 0
                seasons = item.get('seasons') or []

                # support both list and dict shapes
                if isinstance(seasons, dict):
                    seasons = list(seasons.values())

                for s in seasons:
                    try:
                        if int(s.get('number', 0)) > 0:
                            eps = s.get('episodes') or []
                            num_1 += len(eps)
                    except Exception:
                        # defensive: skip malformed season entries
                        continue

                num_2 = aired_episodes = int(item.get('show', {}).get('aired_episodes', 0))


                if num_1 >= num_2:
                    # c.log(f"[CM Debug @ 1466 in episodes.py] INFO: {item['show']['title']}: All episodes watched")
                    #! All episodes watched, progress_list returns unwatched only so we skip
                    add = False

                # Progress Mode: 0 = Last Watched Episode, 1 = Next Unwatched Episode
                # Use parameter if provided, else default to 1 (Next Unwatched)
                used_mode = int(progress_mode) if progress_mode is not None else 1
                season = None
                episode = None


                try:
                    seasons = item.get('seasons') or []

                    # Support both list and dict shapes
                    if isinstance(seasons, dict):
                        seasons = list(seasons.values())

                    # Sort seasons by number ascending
                    sorted_seasons = sorted(
                        [s for s in seasons if s.get('number', 0) > 0],
                        key=lambda s: s.get('number', 0)
                    )

                    if used_mode == 0:
                        # IN PROGRESS SHOWS MODE: Show last WATCHED episode
                        # User will manually choose: continue from here, watch first ep of new season, etc.
                        last_watched_season = None
                        last_watched_episode = None
                        last_watched_timestamp = None

                        for s in sorted_seasons:
                            season_num = s.get('number')
                            eps = s.get('episodes') or []

                            for e in eps:
                                if e.get('last_watched_at'):
                                    # Check if this is more recent than what we found
                                    if last_watched_timestamp is None or e.get('last_watched_at') > last_watched_timestamp:
                                        last_watched_season = season_num
                                        last_watched_episode = e.get('number')
                                        last_watched_timestamp = e.get('last_watched_at')

                        if last_watched_season is not None and last_watched_episode is not None:
                            season = last_watched_season
                            episode = last_watched_episode
                        else:
                            # No watched episodes, default to S01E01
                            season = 1
                            episode = 1

                    else:
                        # IN PROGRESS EPISODES MODE: Find first UNWATCHED episode (default)
                        # This is the "smart" mode that auto-advances to next episode
                        for s in sorted_seasons:
                            season_num = s.get('number')
                            eps = s.get('episodes') or []

                            # Sort episodes by number ascending
                            sorted_eps = sorted(
                                [e for e in eps if e.get('number', 0) > 0],
                                key=lambda e: e.get('number', 0)
                            )

                            # Find first episode without last_watched_at
                            for e in sorted_eps:
                                if not e.get('last_watched_at'):
                                    season = season_num
                                    episode = e.get('number')
                                    break

                            # If we found an unwatched episode, stop searching
                            if season is not None and episode is not None:
                                break

                        # If no unwatched episode found, default to latest season/episode (all watched)
                        if season is None or episode is None:
                            if sorted_seasons:
                                last_season = sorted_seasons[-1]
                                season = last_season.get('number', 1)
                                last_eps = last_season.get('episodes') or []
                                if last_eps:
                                    episode = max(e.get('number', 1) for e in last_eps if e.get('number'))
                                else:
                                    episode = 1
                            else:
                                season = 1
                                episode = 1

                except Exception as exc:
                    season = 1
                    episode = 1

                # Count watched episodes for progress stats
                try:
                    watched_episodes = 0
                    seasons = item.get('seasons') or []
                    if isinstance(seasons, dict):
                        seasons = list(seasons.values())
                    for s in seasons:
                        eps = s.get('episodes') or []
                        for e in eps:
                            if e.get('last_watched_at'):
                                watched_episodes += 1
                except Exception as exc:
                    watched_episodes = 0

                # c.log(f"[CM Debug @ 1806 in episodes.py] watched_episodes = {watched_episodes}")

                tvshowtitle = item['show']['title']  # item.get('show').get('title')
                year = item['show']['year']  # year returns int
                imdb = item['show']['ids']['imdb'] or '0'  # returns str
                tvdb = str(item['show']['ids']['tvdb']) or '0' # returns int
                tmdb = str(item['show']['ids']['tmdb']) or '0' # returns int
                slug = item['show']['ids']['slug']
                trakt_id = item['show']['ids']['trakt']

                first_aired = item['show']['first_aired']

                if not tvshowtitle:
                    raise ValueError('No Title')
                else:
                    tvshowtitle = client.replaceHTMLCodes(tvshowtitle)

                trailer = str(item.get('show').get('trailer')) or '0'

                if int(year) > int(self.datetime.strftime('%Y')):
                    #!year is bigger than current year, future show and we're in progress so continue
                    # add = False
                    pass  # Future show logic disabled

                studio = str(item['show']['network']) or '0'
                duration = item['show']['runtime'] or 45
                if duration == 1: #trakt return 1 in some cases ??
                    duration = 60

                plot = item['show']['overview'] or c.lang(32012)
                plot = client.replaceHTMLCodes(plot)
                tagline = item['show']['tagline'] or '0'
                tagline = client.replaceHTMLCodes(tagline)
                country = item['show']['country'].upper() or '0'
                network = item['show']['network'] or '0'
                mpaa = item['show']['certification'] or '0'
                status = item['show']['status'] or '0'
                genre = item['show']['genres'] or '0'
                if genre != '0':
                    genre = '/'.join(genre)

                last_watched = item['last_watched_at'] or '0'


                if add:
                    return{
                            'imdb': imdb, 'tvdb': tvdb, 'tmdb': tmdb, 'trakt_id': trakt_id,
                            'tvshowtitle': tvshowtitle, 'year': year, 'studio': studio, 'duration': duration,
                            'first_aired': first_aired, 'mpaa': mpaa, 'status': status, 'genre': genre,
                            'snum': season, 'enum': episode, 'trailer': trailer, 'season': season,
                            'episode': episode, 'sortorder': sortorder, 'action': 'episodes',
                            '_last_watched': last_watched, 'slug': slug, 'country': country,
                            'network': network, 'tagline': tagline, 'plot': plot,
                            '_sort_key': first_aired or '0', 'aired_episodes': aired_episodes,
                            'watched_episodes': watched_episodes,
                        }
                return None
            except Exception as e:
                pass



        try:
            # result = []


            # if items:
            max_threads = c.get_max_threads(len(result))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
                #futures = {executor.submit(self.super_info, i): item for item in items}
                futures = {executor.submit(add_item, item): item for item in result}

                # c.log(f"[CM Debug @ 1929 in episodes.py] futures = {futures}")

                for future in concurrent.futures.as_completed(futures):
                    i = futures[future]
                    try:
                        result = future.result()
                        # c.log(f"\n\n\n[CM Debug @ 1850 in episodes.py]added item = {result}\n\n\n")
                        items.append(result)

                    except Exception as exc:
                        failure = traceback.format_exc()
                        c.log(f"Error processing item {i}: {exc}")
                    # c.log(f"[CM Debug @ 1560 in episodes.py] result = {result}")
        except Exception as e:
            pass


        try:
            # Fetch hidden progress from Trakt (may be list or single dict)
            hidden_result = trakt.getTraktAsJson(self.hiddenprogress_link) or []

            # Normalize to list
            if isinstance(hidden_result, dict):
                # Detect Trakt error payload
                if 'status_code' in hidden_result and str(hidden_result.get('status_code', ['']))[0] == '34':
                    raise crew_errors.TraktResourceError(
                        f'Resource status_code == 34 with url == {self.hiddenprogress_link}'
                    )
                hidden_result = [hidden_result]
            elif not isinstance(hidden_result, list):
                hidden_result = list(hidden_result) if hidden_result else []

            # Collect tmdb ids defensively and dedupe while preserving order
            hidden_tmdb_ids = []
            for entry in hidden_result:
                try:
                    tmdb_id = entry.get('show', {}).get('ids', {}).get('tmdb')
                    if tmdb_id is not None:
                        hidden_tmdb_ids.append(str(tmdb_id))
                except Exception as exc:
                    continue
            hidden_tmdb_ids = list(dict.fromkeys(hidden_tmdb_ids))

            # c.log(f"[CM Debug @ 2431 in episodes.py] hidden tmdb ids = {hidden_tmdb_ids}")

            # Ensure items is a list and remove None / non-dict entries before filtering
            if not isinstance(items, list):
                items = list(items) if items else []

            orig_count = len(items)
            items = [it for it in items if isinstance(it, dict)]
            removed = orig_count - len(items)
            if removed and c.devmode:
                pass

            # Filter out items whose tmdb appears in hidden progress
            filtered_items = [it for it in items if str(it.get('tmdb', '0')) not in hidden_tmdb_ids]

            # c.log(f"[CM Debug @ 2441 in episodes.py] filtered items count = {len(filtered_items)}")
            items = filtered_items


            # c.log(f"[CM Debug @ 2445 in episodes.py] items after hidden filter = {items}")

        except crew_errors.TraktResourceError as e:
            pass
        except Exception as e:
            failure = traceback.format_exc()


        self.list = items
        # c.log(f"[CM Debug @ 1601 in episodes.py] self.list = {items}")
        return items

    def _is_cached_current(self, cached, source_item, max_age_days: int = 7, rating_tolerance: float = 0.5, require_poster: bool = True) -> bool:
        """
        Decide if a cached entry is still suitable to reuse.
        Parameters:
            - cached: cached dict (may include optional 'fetched_at' epoch seconds)
            - source_item: source/trakt item used as reference
            - max_age_days: max age (days) of cached entry before considered stale (if 'fetched_at' present)
            - rating_tolerance: absolute difference in rating allowed (0 disables rating check)
            - require_poster: if True, cached entry must have a poster to be reused
        Returns True to reuse cached entry, False to refetch.
        """
        try:
            if not cached or not isinstance(cached, dict):
                return False

            # poster required?
            if require_poster and cached.get('poster', '0') in (None, '0', ''):
                return False

            # premiered mismatch -> stale
            if cached.get('premiered', '0') != (source_item.get('premiered') or '0'):
                return False

            # age check if fetched_at present (expect epoch seconds)
            try:
                fetched = cached.get('fetched_at') or cached.get('_fetched_at')
                if fetched:
                    now = time.time()
                    fetched_ts = float(fetched)
                    age_days = (now - fetched_ts) / 86400.0
                    if age_days > float(max_age_days):
                        return False
            except Exception:
                # if parsing fails, ignore age check (don't break reuse)
                pass

            # rating tolerance check (optional)
            if rating_tolerance and rating_tolerance > 0:
                try:
                    cached_rating = float(cached.get('rating', 0) or 0)
                    src_rating = float(source_item.get('rating', cached_rating) or cached_rating)
                    if abs(cached_rating - src_rating) > float(rating_tolerance):
                        return False
                except Exception:
                    # ignore rating parse errors
                    pass

            # watched timestamp differences: accept cached for UI but dynamic fields should be updated
            cached_watched = str(cached.get('watched_at', cached.get('_last_watched', '0') or '0'))
            src_watched = str(source_item.get('watched_at', source_item.get('_last_watched', '0') or '0'))
            return cached_watched != src_watched

        except Exception:
            return False


    def trakt_episodes_list(self, url, user, lang):
        pass

        # ensure self.list is always a list to avoid NoneType errors when appending
        self.list = []

        items = self.trakt_list(url, user, return_art=True)


        def items_list(i):
            tmdb, imdb, tvdb = i['tmdb'], i['imdb'], i['tvdb']

            # try to resolve tmdb via imdb if missing
            if (not tmdb or tmdb == '0') and imdb != '0':
                try:
                    url = self.tmdb_by_imdb % imdb
                    result = self.session.get(url, timeout=16).json()
                    tv_results = result.get('tv_results', [])
                    if tv_results:
                        tmdb = str(tv_results[0].get('id') or '0')
                except Exception:
                    tmdb = '0'

            # try reuse cached blist item if present and still current
            try:
                cached_item = next(
                    (x for x in (self.blist or []) if x.get('tmdb') == tmdb and x.get('season') == i.get('season') and x.get('episode') == i.get('episode')),
                    None
                )
                if cached_item and self._is_cached_current(cached_item, i):
                    # reuse cached metadata/artwork but ensure dynamic fields from source i are copied
                    entry = dict(cached_item)  # shallow copy
                    # update dynamic runtime fields from the trakt/source item
                    for k in ('paused_at', 'watched_at', 'resume_point', '_last_watched'):
                        if k in i:
                            entry[k] = i[k]
                    # ensure self.list is initialised before appending
                    if not isinstance(self.list, list):
                        self.list = []
                    self.list.append(entry)
                    return
            except Exception:
                # any failure here should fall through to fetching fresh data
                pass

            # fall back to fetching episode info from TMDB
            try:
                if tmdb == '0':
                    raise Exception()

                url = self.tmdb_episode_link % (tmdb, i['season'], i['episode'])
                item = self.session.get(url, timeout=10).json()

                title = item.get('name') or '0'
                if title != '0':
                    title = client.replaceHTMLCodes(str(title))

                season = f"{int(item.get('season_number', 0)):01d}"
                if int(season) == 0 and self.specials != 'true':
                    raise Exception()

                episode = f"{int(item.get('episode_number', 0)):01d}"

                tvshowtitle = i.get('tvshowtitle')
                premiered = i.get('premiered')

                unaired = ''
                if premiered and premiered != '0' and int(re.sub('[^0-9]', '', premiered)) > int(re.sub('[^0-9]', '', self.today_date)):
                    unaired = 'true'
                    if self.showunaired != 'true':
                        raise Exception('hide unaired episode')

                status = i.get('status', '0')
                duration = i.get('duration', '0')
                mpaa = i.get('mpaa', '0')
                studio = i.get('studio', '0')
                genre = i.get('genre', '0')
                year = i.get('year', '0')
                rating = str(item.get('vote_average') or i.get('rating', '0'))
                votes = str(item.get('vote_count') or i.get('votes', '0'))

                thumb = self.tmdb_img_link % (c.tmdb_stillsize, item.get('still_path')) if item.get('still_path') else '0'
                plot = item.get('overview') or (i.get('plot') or 'The Crew - No plot Available')
                plot = client.replaceHTMLCodes(c.to_str(plot, errors='replace'))

                # crew/cast extraction (non fatal)
                director = writer = '0'
                try:
                    r_crew = item.get('crew', [])
                    director_list = [d['name'] for d in r_crew if d.get('job') == 'Director']
                    writer_list = [w['name'] for w in r_crew if w.get('job') == 'Writer']
                    director = '/'.join(director_list) if director_list else '0'
                    writer = '/'.join(writer_list) if writer_list else '0'
                except Exception:
                    pass

                castwiththumb = []
                try:
                    credits = item.get('credits', {}) or {}
                    for person in credits.get('cast', [])[:30]:
                        _icon = person.get('profile_path')
                        icon = self.tmdb_img_link % (c.tmdb_profilesize, _icon) if _icon else ''
                        castwiththumb.append({'name': person.get('name'), 'role': person.get('character'), 'thumbnail': icon})
                    if not castwiththumb:
                        castwiththumb = '0'
                except Exception:
                    castwiththumb = '0'

                # artwork via fanart/tmdb
                poster = fanart = banner = landscape = clear_logo = clear_art = '0'
                if tvdb and tvdb != '0':
                    try:
                        artwork = fanart_tv.get_fanart_tv_art(tvdb=tvdb)
                        poster = artwork.get('poster', poster)
                        fanart = artwork.get('fanart', fanart)
                        banner = artwork.get('banner', banner)
                        landscape = artwork.get('landscape', landscape)
                        clear_logo = artwork.get('clearlogo', clear_logo)
                        clear_art = artwork.get('clearart', clear_art)
                    except Exception:
                        pass

                if poster == '0':
                    p, f = self.get_tmdb_art(tmdb)
                    poster = p or poster
                    if f and f != '0':
                        fanart = f

                if fanart == '0':
                    fanart = '0'

                landscape = fanart if thumb == '0' else thumb

                return {
                    'title': title, 'season': season, 'episode': episode,
                    'tvshowtitle': tvshowtitle, 'year': year, 'premiered': premiered,
                    'status': status, 'studio': studio, 'genre': genre, 'duration': duration,
                    'rating': rating, 'votes': votes, 'mpaa': mpaa, 'director': director,
                    'writer': writer, 'castwiththumb': castwiththumb, 'plot': plot,
                    'imdb': imdb, 'tvdb': tvdb, 'tmdb': tmdb, 'poster': poster,
                    'banner': banner, 'fanart': fanart, 'thumb': thumb,
                    'clearlogo': clear_logo, 'clearart': clear_art,
                    'landscape': landscape, 'paused_at': i.get('paused_at', '0'),
                    'unaired': unaired, 'watched_at': i.get('watched_at', '0'), '_last_watched': i.get('watched_at', '0')
                }
            except Exception as e:
                return None




        # items = items[:100]
        try:
            result = []
            # Guard against empty items list to prevent max_workers=0 crash
            if not items:
                return self.list

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(items)) as executor:
                pass

                futures = {executor.submit(items_list, i): i for i in items}

                for future in concurrent.futures.as_completed(futures):
                    i = futures[future]
                    try:
                        result = future.result()
                        self.list.append(result)

                    except Exception as exc:
                        c.log(f"Error processing item {i}: {exc}")
                    # c.log(f"[CM Debug @ 1846 in episodes.py] result = {result}")
        except Exception as e:
            failure = traceback.format_exc()

        return self.list

    def trakt_user_list(self, url, user):
        pass

        items = trakt.getTraktAsJson(url)

        if not items:
            return


        for item in items:
            try:
                try:
                    name = item['list']['name']
                except Exception:
                    name = item['name']
                name = client.replaceHTMLCodes(name)

                try:
                    url = (trakt.slug(item['list']['user']['username']), item['list']['ids']['slug'])
                except Exception:
                    url = ('me', item['ids']['slug'])
                url = self.traktlist_link % url

                self.list.append({'name': name, 'url': url, 'context': url})
            except Exception:
                pass

        self.list = sorted(self.list, key=lambda k: utils.title_key(k['name']))
        return self.list

    def tvmaze_list(self, url, limit):
        try:
            itemlist = []
            items = self.session.get(url, timeout=10).json()
        except Exception:
            return

        for item in items:
            try:
                if 'english' not in item['show']['language'].lower():
                    raise ValueError()


                if (
                    limit is True
                    and 'scripted' not in item['show']['type'].lower()
                ):
                    raise ValueError()
                tvshowtitle = item['_links']['show']['name']
                if not tvshowtitle:
                    tvshowtitle = ''
                else:
                    tvshowtitle = client.replaceHTMLCodes(tvshowtitle)

                title = item['name']
                if not title:
                    raise ValueError('no title')
                title = client.replaceHTMLCodes(title)

                season = item['season']
                season = re.sub('[^0-9]', '', '%02d' % int(season))
                if not season:
                    raise ValueError('no season')

                episode = item['number']
                episode = re.sub('[^0-9]', '', '%02d' % int(episode))
                if episode == '0':
                    raise ValueError('episode = 0')

                tvshowtitle = item['show']['name']
                if not tvshowtitle:
                    raise ValueError('no tvshowtitle')
                tvshowtitle = client.replaceHTMLCodes(tvshowtitle)

                year = item['show']['premiered']
                year = re.findall(r'(\d{4})', year)[0]

                imdb = item['show']['externals']['imdb']
                if not imdb:
                    imdb = '0'
                else:
                    imdb = 'tt' + re.sub('[^0-9]', '', str(imdb))

                tvdb = item['show']['externals']['thetvdb']
                if not tvdb:
                    raise ValueError('no tvdb')
                tvdb = re.sub('[^0-9]', '', str(tvdb))

                poster_medium = item['show']['image']['medium'] if 'medium' in item['show']['image'] else '0'

                poster1 = '0'
                try:
                    poster1 = item['show']['image']['original']
                except Exception:
                    poster1 = '0'
                if not poster1:
                    poster1 = '0'

                try:
                    thumb1 = item['show']['image']['original']
                except Exception:
                    thumb1 = '0'

                try:
                    thumb2 = item['image']['original']
                except Exception:
                    thumb2 = '0'

                if not thumb2:
                    thumb = thumb1
                else:
                    thumb = thumb2
                if not thumb:
                    thumb = '0'

                premiered = item['airdate']
                try:
                    premiered = re.findall(r'(\d{4}-\d{2}-\d{2})', premiered)[0]
                except Exception:
                    premiered = '0'

                try:
                    studio = item['show']['network']['name']
                except Exception:
                    studio = '0'
                if studio is None:
                    studio = '0'

                try:
                    genre = item['show']['genres']
                except Exception:
                    genre = '0'
                genre = [i.title() for i in genre]
                if genre == []:
                    genre = '0'
                genre = ' / '.join(genre)

                try:
                    duration = item['show']['runtime']
                except Exception:
                    duration = '0'
                if duration is None:
                    duration = '0'
                duration = str(duration)

                try:
                    rating = item['show']['rating']['average']
                except Exception:
                    rating = '0'
                if rating is None or rating == '0.0':
                    rating = '0'
                rating = str(rating)
                rating = c.to_str(rating)

                votes = '0'

                try:
                    plot = item['show']['summary']
                except Exception:
                    plot = '0'
                if not plot:
                    plot = '0'
                plot = re.sub('<.+?>|</.+?>|\n', '', plot)
                plot = client.replaceHTMLCodes(plot)

                poster2 = fanart = banner = landscape = clearlogo = clearart = '0'

                if not tvdb == '0':
                    tempart =fanart_tv.get_fanart_tv_art(tvdb=tvdb)
                    poster2 = tempart.get('poster', '0')
                    fanart = tempart.get('fanart', '0')
                    banner = tempart.get('banner', '0')
                    landscape = tempart.get('landscape', '0')
                    clearlogo = tempart.get('clearlogo', '0')
                    clearart = tempart.get('clearart', '0')

                #poster = poster2 if not poster2 == '0' else poster1 if not poster1 == '0' else poster_medium
                poster = poster2 if poster2 != '0' else poster_medium if poster1 == '0' else poster1

                itemlist.append({'title': title, 'season': season, 'episode': episode,
                                'tvshowtitle': tvshowtitle, 'year': year, 'premiered': premiered,
                                    'status': 'Continuing', 'studio': studio, 'genre': genre,
                                    'duration': duration, 'rating': rating, 'votes': votes,
                                    'plot': plot, 'imdb': imdb, 'tvdb': tvdb, 'tmdb': '0',
                                    'thumb': thumb, 'poster': poster, 'banner': banner,
                                    'fanart': fanart, 'clearlogo': clearlogo, 'clearart': clearart,
                                    'landscape': landscape})
            except Exception:
                pass

        return itemlist[::-1]

    def _resolve_tmdb(self, tmdb, imdb, tvshowtitle, year) -> tuple:
        """
        Resolve a TMDB id from provided tmdb or imdb, otherwise search by title.
        """
        try:
            # already have a valid tmdb
            if tmdb and tmdb != '0':
                url = self.tmdb_show_link % tmdb
                resp_json = http_client.tmdb_get_json(url, timeout=16)
                if resp_json is not None:
                    return str(tmdb), resp_json
                return str(tmdb), None

            # try resolve from imdb
            if imdb and imdb != '0':
                try:
                    url = self.tmdb_by_imdb % imdb
                    result = http_client.tmdb_get_json(url, timeout=16)
                    if tv_results := (result or {}).get('tv_results') or []:
                        if _id := tv_results[0].get('id'):
                            return str(_id), None
                except requests.RequestException as e:
                    pass

            # fallback: search TMDB by title
            if not tvshowtitle:
                return '0', None
            try:
                return self._find_tmdb_id_by_title(tvshowtitle, year)
            except requests.RequestException as e:
                return '0', None
            except Exception as e:
                return '0', None
        except Exception as e:
            return '0', None

    def _find_tmdb_id_by_title(self, tvshowtitle, year):
        """Search TMDB by title (optionally filtered by year) and return (tmdb_id_or_'0', search_result_or_None)."""
        qtitle = quote(tvshowtitle)
        url = self.search_link % qtitle
        if year:
            url = f'{url}&first_air_date_year={str(year)}'

        result = None
        for attempt in range(1, 4):
            try:
                resp = self.session.get(url, timeout=16)
                resp.raise_for_status()
                result = resp.json()
                break
            except Exception as e:
                if attempt < 3:
                    control.sleep(1000 * (2 ** (attempt - 1)))
                    continue

        if not result:
            return '0', None

        results = result.get('results') or []
        if not results:
            return '0', result

        preferred = (
            self.list[0].get('title', '') or ''
            if isinstance(self.list, list)
            and len(self.list) > 0
            and isinstance(self.list[0], dict)
            else ''
        )
        preferred = preferred or tvshowtitle

        # try cleantitle exact match, then case-insensitive name match, then first result
        match = next((r for r in results if cleantitle.get(r.get('name')) == cleantitle.get(preferred)), None)
        if match is None:
            match = next((r for r in results if (r.get('name') or '').lower() == (tvshowtitle or '').lower()), None)
        if match is None:
            match = results[0]

        tmdb_id = match.get('id')
        return (str(tmdb_id), result) if tmdb_id else ('0', result)

    def tmdb_list(self, tvshowtitle, year, imdb, tmdb, season, meta=None, lite=False):
        """Gets a list of episodes for a given tvshow. The list is in descending order."""

        # resolve TMDB id and capture optional search result to reuse later if needed
        tmdb, tmdb_search_result = self._resolve_tmdb(tmdb, imdb, tvshowtitle, year)

        result = tmdb_search_result or []

        if tmdb == '0':
            return self.list


        try:
            episodes_url = self.tmdb_season_link % (tmdb, season, self.lang)
            episodes_lite_url = self.tmdb_season_lite_link % (tmdb, season)

            url = episodes_url if lite is False else episodes_lite_url
            result = self.session.get(url, timeout=10).json()

            episode_list = result['episodes']

            if self.specials == 'false':
                episode_list = [e for e in episode_list if e['season_number'] != 0]
            if not episode_list:
                raise Exception()

            r_cast = result.get('aggregate_credits', {}).get('cast', [])

            poster_path = result.get('poster_path')
            if poster_path:
                poster = self.tmdb_img_link % (c.tmdb_postersize, poster_path)
            else:
                poster = '0'


            fanart = banner = clearlogo = clearart = landscape = duration = status = '0'
            studio = genre = mpaa = '0'
            if meta:
                _meta = json.loads(unquote_plus(meta))
                poster = _meta['poster'] if poster == '0' else poster
                fanart = _meta['fanart'] if fanart == '0' else fanart
                thumb = _meta['thumb'] if 'thumb' in _meta else '0'
                banner = _meta['banner']
                clearlogo = _meta['clearlogo']
                clearart = _meta['clearart']
                landscape = _meta['landscape'] or thumb
                duration = _meta['duration']
                status = _meta['status']
                studio = _meta.get('studio', '0')
                genre = _meta.get('genre', '0')
                mpaa = _meta.get('mpaa', '0')

            def add_item(item):
                # for item in episode_list:
                try:
                    season = str(item['season_number'])
                    episode = str(item['episode_number'])

                    title = item.get('name') or f'Episode {episode}'
                    label = title

                    premiered = item.get('air_date') or '0'

                    unaired = ''
                    if not premiered or premiered == '0':
                        pass
                    elif int(re.sub('[^0-9]', '', premiered)) > int(re.sub('[^0-9]', '', self.today_date)):
                        unaired = 'true'
                        if self.showunaired != 'true':
                            raise ValueError('hide unaired episode')

                    still_path = item.get('still_path') if 'still_path' in item else None
                    if still_path:
                        thumb = self.tmdb_img_link % (c.tmdb_stillsize, still_path)
                    else:
                        thumb = landscape or fanart or '0'



                    rating = str(item['vote_average']) or '0'
                    votes = str(item['vote_count']) or '0'
                    episodeplot = item['overview'] or '0'

                    try:
                        r_crew = item['crew']

                        director = [d for d in r_crew if d['job'] == 'Director']
                        director = '/'.join([d['name'] for d in director])

                        writer = [w for w in r_crew if w['job'] == 'Writer']
                        writer = '/'.join([w['name'] for w in writer])

                    except Exception:
                        director = writer = ''
                    if not director:
                        director = '0'
                    if not writer:
                        writer = '0'

                    castwiththumb = []
                    try:
                        # Try episode-specific guest_stars first, fallback to show cast
                        episode_cast = item.get('guest_stars', [])
                        if episode_cast:
                            for person in episode_cast[:30]:
                                _icon = person.get('profile_path')
                                icon = self.tmdb_img_link % (c.tmdb_profilesize, _icon) if _icon else ''
                                castwiththumb.append({
                                    'name': person['name'],
                                    'role': person.get('character', ''),
                                    'thumbnail': icon
                                })
                        else:
                            # Fallback to show-level cast
                            for person in r_cast[:30]:
                                _icon = person['profile_path']
                                icon = self.tmdb_img_link % (c.tmdb_profilesize, _icon) if _icon else ''
                                castwiththumb.append({
                                    'name': person['name'],
                                    'role': person['character'],
                                    'thumbnail': icon
                                })
                    except Exception:
                        pass
                    if not castwiththumb:
                        castwiththumb = '0'

                    return{
                        'title': title, 'imdb': imdb, 'tmdb': tmdb, 'tvdb': '0',
                        'season': season, 'episode': episode, 'tvshowtitle': tvshowtitle,
                        'year': year, 'premiered': premiered, 'status': status,
                        'studio': studio, 'genre': genre, 'duration': duration,
                        'rating': rating, 'votes': votes, 'mpaa': mpaa,
                        'plot': episodeplot, 'director': director, 'writer': writer,
                        'castwiththumb': castwiththumb, 'unaired': unaired,
                        'poster': poster, 'fanart': fanart, 'banner': banner,
                        'thumb': thumb, 'clearlogo': clearlogo, 'clearart': clearart,
                        'landscape': landscape
                        }

                    # c.log(f"[CM Debug @ 1430 in episodes.py] tempdict = {tempdict}")
                    # return tempdict

                except (Exception, ValueError) as e:
                    failure = traceback.format_exc()
                failure = traceback.format_exc()

        except Exception as e:
            failure = traceback.format_exc()


        try:
            collected = []
            num_workers = max(1, len(episode_list))

            with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = {executor.submit(add_item, item): item for item in episode_list}

                for future in concurrent.futures.as_completed(futures):
                    i = futures[future]
                    resp = None
                    try:
                        resp = future.result()
                        if resp:
                            self.list.append(resp) # type: ignore
                            collected.append(resp)

                    except Exception as exc:
                        c.log(f"Error processing item {i}: {exc}")
                    # c.log(f"[CM Debug @ 3049 in episodes.py] resp = {resp}")
        except Exception as e:
            failure = traceback.format_exc()


        # Sort episodes by season and episode number to ensure proper order
        # (ThreadPoolExecutor.as_completed returns in random completion order)
        if self.list:
            self.list = sorted(self.list, key=lambda k: (int(k.get('season', 0)), int(k.get('episode', 0))))

        return self.list

    def episodeDirectory(self, items):
        if items is None or len(items) == 0:
            return

        # cm setting up
        sysaddon = sys.argv[0]
        syshandle = int(sys.argv[1])

        addon_poster, addon_banner = c.addon_poster(), c.addon_banner()
        addon_fanart, setting_fanart = c.addon_fanart(), c.get_setting('fanart')
        addon_clearlogo, addon_clearart = c.addon_clearlogo(), c.addon_clearart()
        addon_discart = c.addon_discart()

        trakt_credentials = trakt.get_trakt_credentials_info()
        is_playable = 'plugin' not in control.infoLabel('Container.PluginName')
        indicators = playcount.get_tvshow_indicators(refresh=True)

        try:
            multi = [i['tvshowtitle'] for i in items]
        except Exception:
            multi = []
        multi = len([x for y, x in enumerate(multi) if x not in multi[:y]])
        multi = multi > 1

        try:
            sysaction = items[0]['action']
        except Exception:
            sysaction = ''

        isFolder = sysaction == 'episodes'

        playback_menu = control.lang(32063) if control.setting('hosts.mode') == '2' else control.lang(32064)
        watched_menu = control.lang(32068) if trakt_credentials else control.lang(32066)
        unwatched_menu = control.lang(32069) if trakt_credentials else control.lang(32067)
        queue_menu = control.lang(32065)
        trakt_manager_menu = control.lang(32515)
        add_to_library = control.lang(32551)
        clear_resume_menu = control.lang(90237)

        clear_providers = control.lang(32098)
        tvshow_browser_menu = control.lang(32071)

        # Get current container URL for redirect after clearing resume point
        current_container = sysaddon + sys.argv[2]

        # Get color for unaired episodes from centralized constants
        colornr = COLOR_STRING_IDS[int(control.setting('unaired.identify'))]
        unairedcolor = re.sub(r"\][\w\s]*\[", "][I]%s[/I][", control.lang(int(colornr)))
        unairedcolor = re.sub(r"\][\w\s]*\[", "][I]%s[/I][", control.lang(int(colornr)))

        # fixed by cm -  28-4-2021
        if unairedcolor == '':
            unairedcolor = '[COLOR red][I]%s[/I][/COLOR]'

        x=0

        for i in items:
            if x == 0:
                x+=1

            try:
                # Build episode label from available data
                # Priority: episode title > generic "Episode XX" > fallback "0"
                if 'label' not in i:
                    if 'title' in i and i['title'] != '0':
                        i['label'] = i['title']
                    else:
                        # Don't fallback to tvshowtitle - that creates duplicate show names
                        i['label'] = '0'


                season = str(i['season']).zfill(2)
                episode = str(i['episode']).zfill(2)

                if i['label'] == '0':
                    # Standard format with parentheses: (S01E01) : Episode 01
                    label = f'(S{season}E{episode}) : Episode {episode}'
                else:
                    # With episode title: (S01E01) : Episode Title
                    label = f'(S{season}E{episode}) : {i["label"]}'

                title = i['title'] if 'title' in i and i['title'] != '0' else label


                if multi:
                    # When viewing episodes from multiple shows, prepend show title
                    label = f'{i["tvshowtitle"]} {label}'

                with suppress(Exception):
                    if i['unaired'] == 'true':
                        label = unairedcolor % label

                imdb, tvdb, tmdb, year, season, episode = i['imdb'], i['tvdb'], i['tmdb'], i['year'], i['season'], i['episode']

                poster = i['poster'] if 'poster' in i and i['poster'] != '0' else addon_poster
                fanart = i['fanart'] if 'fanart' in i and i['fanart'] != '0' else addon_fanart
                banner = i['banner'] if 'banner' in i and i['banner'] != '0' else addon_banner
                landscape = i['landscape'] if 'landscape' in i and i['landscape'] != '0' else fanart
                clearlogo = i['clearlogo'] if 'clearlogo' in i and i['clearlogo'] != '0' else addon_clearlogo
                clearart = i['clearart'] if 'clearart' in i and i['clearart'] != '0' else addon_clearart
                discart = i['discart'] if 'discart' in i and i['discart'] != '0' else addon_discart

                duration = i['duration'] if 'duration' in i and i['duration'] != '0' else '45'
                status = i['status'] if 'status' in i else '0'
                studio = i.get('studio', '0')
                genre = i.get('genre', '0')
                mpaa = i.get('mpaa', '0')

                s_meta = {
                    'poster': poster, 'fanart': fanart, 'banner': banner, 'clearlogo': clearlogo,
                    'clearart': clearart, 'discart': discart, 'landscape': landscape,
                    'duration': duration, 'status': status, 'studio': studio, 'genre': genre, 'mpaa': mpaa
                    }

                # Create show-level metadata for browser menu
                show_meta = {
                    'title': i.get('tvshowtitle', ''),
                    'tvshowtitle': i.get('tvshowtitle', ''),
                    'year': year,
                    'imdb': imdb,
                    'tmdb': tmdb,
                    'tvdb': tvdb,
                    'poster': poster,
                    'fanart': fanart,
                    'banner': banner,
                    'clearlogo': clearlogo,
                    'clearart': clearart,
                    'discart': discart,
                    'landscape': landscape,
                    'duration': duration,
                    'status': status,
                    'studio': i.get('studio', ''),
                    'genre': i.get('genre', ''),
                    'mpaa': i.get('mpaa', ''),
                    'plot': i.get('plot', ''),
                    'mediatype': 'tvshow'
                }
                show_meta = {k: v for k, v in show_meta.items() if v not in ['', '0', None]}

                seasons_meta = quote_plus(json.dumps(s_meta))
                show_sysmeta = quote_plus(json.dumps(show_meta))

                systitle = quote_plus(title)
                systvshowtitle = quote_plus(i['tvshowtitle'])

                premiered = i['premiered'] if 'premiered' in i and i['premiered'] != '0' else i['first_aired'] if 'first_aired' in i and i['first_aired'] != '0' else '0'
                syspremiered = quote_plus(premiered)
                systrailer = quote_plus(i['trailer']) if 'trailer' in i else '0'

                # sysyear = re.findall('(\d{4})', i['premiered'])[0]
                # meta = dict((k, v) for k, v in list(i.items()) if not v == '0')
                meta = {k: v for k, v in i.items() if v != '0'}

                if i.get('season') == '0':
                    meta['season'] = '0'
                meta.update({'mediatype': 'episode'})
                meta.update({'code': tmdb})
                meta.update({'imdb_id': imdb})
                meta.update({'tmdb_id': tmdb})
                if systrailer == '0':
                    meta['trailer'] = (
                        f'{sysaddon}?action=trailer&name={systvshowtitle}&imdb={imdb}&tmdb={tmdb}&mediatype=episode&season={season}&episode={episode}'
                    )
                else:
                    meta.update({'trailer': f'{sysaddon}?action=trailer&name={systvshowtitle}&url={systrailer}&imdb={imdb}&tmdb={tmdb}&mediatype=episode&season={season}&episode={episode}'})


                with suppress(Exception):
                    # duration -> seconds
                    if duration:
                        meta['duration'] = str(int(duration) * 60)

                    # normalized genre
                    meta['genre'] = cleangenre.lang(meta.get('genre', ''), self.lang)

                    # extract year from premiered if possible
                    if (m := re.search(r'(\d{4})', str(i.get('premiered', '')))):
                        meta['year'] = m[1]

                    # prefer explicit label/title if present
                    if i.get('label'):
                        meta['title'] = i['label']

                    # tvshow year if present
                    if i.get('year'):
                        meta['tvshowyear'] = i.get('year')

                meta.update({
                    'poster': poster, 'fanart': fanart, 'banner': banner, 'landscape': landscape,
                    'clearlogo': clearlogo, 'clearart': clearart, 'discart': discart
                    })
                sysmeta = quote_plus(json.dumps(meta))


                url = '%s?action=play&title=%s&year=%s&imdb=%s&tmdb=%s&season=%s&episode=%s&tvshowtitle=%s&premiered=%s&meta=%s&t=%s' % (sysaddon, systitle, year, imdb, tmdb, season, episode, systvshowtitle, syspremiered, sysmeta, self.systime)
                sysurl = quote_plus(url)

                if isFolder:
                    # url = '%s?action=episodes&tvshowtitle=%s&year=%s&imdb=%s&tmdb=%s&meta=%s&season=%s&episode=%s' % (sysaddon, systvshowtitle, year, imdb, tmdb, seasons_meta, season, episode)
                    url = '%s?action=episodes&tvshowtitle=%s&year=%s&imdb=%s&tmdb=%s&meta=%s&season=%s&episode=%s' % (sysaddon, systvshowtitle, year, imdb, tmdb, seasons_meta, season, episode)
                    url = f'{sysaddon}?action=play&title={systitle}&year={year}&imdb={imdb}&tmdb={tmdb}&season={season}&episode={episode}&tvshowtitle={systvshowtitle}&premiered={syspremiered}&meta={sysmeta}&t={self.systime}'

                # Get resume point early so we can use it in context menu
                _imdb_key = imdb if imdb and str(imdb) not in ('None', 'null', '') else ''
                offset = bookmarks.get('episode', imdb=_imdb_key, tmdb=int(tmdb) if tmdb and str(tmdb) not in ('None', '', '0') else 0, season=int(season or 0), episode=int(episode or 0))

                # Build context menu in logical order
                cm = []
                cm.append(
                    (queue_menu, 'RunPlugin(%s?action=queueItem)' % sysaddon))

                if multi:
                    cm.append((tvshow_browser_menu, 'ActivateWindow(Videos,%s?action=episodes&tvshowtitle=%s&year=%s&imdb=%s&tmdb=%s&meta=%s&season=%s,return)' % (sysaddon, systvshowtitle, year, imdb, tmdb, show_sysmeta, season)))

                # Note: "Play next" (Queue) removed - not compatible with source scraping architecture

                # Watch status (watched/unwatched)
                try:
                    overlay = int(playcount.get_episode_overlay(indicators, imdb, tmdb, season, episode))
                    if overlay == 7:
                        cm.append((unwatched_menu, 'RunPlugin(%s?action=episodePlaycount&imdb=%s&tmdb=%s&season=%s&episode=%s&query=6)' % (sysaddon, imdb, tmdb, season, episode)))
                        meta.update({'playcount': 1, 'overlay': 7})
                    else:
                        cm.append((watched_menu, 'RunPlugin(%s?action=episodePlaycount&imdb=%s&tmdb=%s&season=%s&episode=%s&query=7)' % (sysaddon, imdb, tmdb, season, episode)))
                        meta.update({'playcount': 0, 'overlay': 6})
                except Exception:
                    pass

                # Add clear resume point menu if there's a resume point
                if offset > 0:
                    cm.append((clear_resume_menu, 'RunPlugin(%s?action=episodeClearBookmark&imdb=%s&tmdb=%s&season=%s&episode=%s&redirect=%s)' % (sysaddon, imdb, tmdb, season, episode, quote_plus(current_container))))

                if trakt_credentials:
                    cm.append((trakt_manager_menu, 'RunPlugin(%s?action=traktManager&name=%s&tmdb=%s&content=tvshow)' % (sysaddon, systvshowtitle, tmdb)))

                if not isFolder:
                    cm.append((playback_menu, 'RunPlugin(%s?action=alterSources&url=%s&meta=%s)' % (sysaddon, sysurl, sysmeta)))

                cm.append((add_to_library, 'RunPlugin(%s?action=tvshowToLibrary&tvshowtitle=%s&year=%s&imdb=%s&tmdb=%s)' % (sysaddon, systvshowtitle, year, imdb, tmdb)))

                cm.append(
                    (clear_providers, 'RunPlugin(%s?action=clearSources)' % sysaddon))


                try:
                    item = control.item(label=label, offscreen=True)
                except Exception:
                    item = control.item(label=label)

                art = {}

                thumb = meta.get('thumb', '') or fanart

                art.update({
                    'icon': thumb, 'thumb': thumb, 'banner': banner, 'poster': thumb,
                    'tvshow.poster': poster, 'season.poster': poster, 'landscape': landscape,
                    'clearlogo': clearlogo, 'clearart': clearart, 'discart': discart})

                if setting_fanart == 'true':
                    art.update({'fanart': fanart})

                castwiththumb = i.get('castwiththumb')
                if castwiththumb and castwiththumb != '0':
                    item.setCast(castwiththumb)
                    # meta.update({'cast': castwiththumb})

                item.setArt(art)
                item.addContextMenuItems(cm, replaceItems=True)
                if is_playable:
                    item.setProperty('IsPlayable', 'true')

                item.setProperty('imdb_id', imdb)
                item.setProperty('tmdb_id', tmdb)
                item.setProperty('tvdb_id', tvdb)

                # Prepare lists for infotag (Kodi v21+ requirement)
                meta['studio'] = c.string_split_to_list(meta.get('studio', '')) if 'studio' in meta else []
                meta['genre'] = c.string_split_to_list(meta.get('genre', '')) if 'genre' in meta else []
                meta['director'] = c.string_split_to_list(meta.get('director', '')) if 'director' in meta else []
                meta['writer'] = c.string_split_to_list(meta.get('writer', '')) if 'writer' in meta else []

                # Pass listitem to the infotagger module and specify tag type
                info_tag = ListItemInfoTag(item, 'video')
                infolabels = control.tagdataClean(meta)

                info_tag.set_info(infolabels)

                # Set resume point using InfoTagVideo (Kodi v19+ method) if there is one
                if float(offset) > 60:
                    try:
                        info_tag.set_resume_point({'ResumeTime': float(offset), 'TotalTime': float(meta['duration'])})
                    except Exception as e:
                        c.log(f"[Episodes] Error setting resume point: {e}")
                unique_ids = {'imdb': imdb, 'tmdb': tmdb, 'tvdb': tvdb}
                info_tag.set_unique_ids(unique_ids)

                # Set trailer explicitly on InfoTag for information dialog
                trailer_val = meta.get('trailer', 'NOT_IN_META')
                # c.log(f"[CM Debug @ episodes.py] Episode trailer check - trailer in meta: {trailer_val}")
                if 'trailer' in meta and meta['trailer'] not in ('0', '', None):
                    # c.log(f"[CM Debug @ episodes.py] Setting trailer on InfoTag: {meta['trailer']}")
                    info_tag._info_tag.setTrailer(meta['trailer'])
                else:
                    # c.log(f"[CM Debug @ episodes.py] Trailer NOT set - value was: {meta.get('trailer', 'KEY_MISSING')}")
                    pass

                # Set cast if available
                castwiththumb = i.get('castwiththumb')
                if castwiththumb and castwiththumb != '0':
                    info_tag.set_cast(castwiththumb)

                # Set resume point if offset exists
                if float(offset) > 60:
                    try:
                        resume_seconds = float(offset)
                        duration = float(meta['duration']) if 'duration' in meta and meta['duration'] != '0' else 0

                        # Apply same corruption detection as label
                        if 0.01 <= resume_seconds < 1.0:
                            if duration > 0:
                                resume_seconds = duration * resume_seconds
                        elif 1.0 <= resume_seconds <= 100.0:
                            if duration > 0 and resume_seconds < 92:
                                resume_seconds = duration * (resume_seconds / 100.0)

                        # Use info_tag to set resume point (Kodi v21+ method)
                        meta['offset'] = resume_seconds
                        info_tag.set_resume_point(meta, 'offset', 'duration', False)
                    except Exception:
                        pass

                # Add stream info
                stream_info = {'codec': 'h264'}
                info_tag.add_stream_info('video', stream_info)

                # Context menu must be added after infotag setup
                item.addContextMenuItems(cm, replaceItems=True)

                control.addItem(handle=syshandle, url=url, listitem=item, isFolder=isFolder)
            except Exception as e:
                pass



        control.content(syshandle, 'episodes')
        control.directory(syshandle, cacheToDisc=False)  # Don't cache - watched status changes dynamically

    def addDirectory(self, items, queue=False):
        if items is None or len(items) == 0:
            control.idle()
            return []

        sysaddon = sys.argv[0]
        syshandle = int(sys.argv[1])
        addonFanart, addonThumb, artPath = control.addonFanart(), control.addonThumb(), control.artPath()
        queueMenu = control.lang(32065)

        for i in items:
            try:
                name = i['name']

                if i['image'].startswith('http'):
                    thumb = i['image']
                elif artPath is not None:
                    thumb = os.path.join(artPath, i['image'])
                else:
                    thumb = addonThumb

                url = f"{sysaddon}?action={i['action']}"
                try:
                    url += f"&url={quote_plus(i['url'])}"
                except Exception:
                    pass

                cm = []


                if queue is True:
                    cm.append(
                        (queueMenu, 'RunPlugin(%s?action=queueItem)' % sysaddon))

                try:
                    item = control.item(label=name, offscreen=True)
                except Exception:
                    item = control.item(label=name)

                item.setArt({'icon': thumb, 'thumb': thumb, 'fanart': addonFanart})

                item.addContextMenuItems(cm, replaceItems=True)

                control.addItem(handle=syshandle, url=url,listitem=item, isFolder=True)
            except Exception:
                pass

        control.content(syshandle, 'addons')
        control.directory(syshandle, cacheToDisc=True)
