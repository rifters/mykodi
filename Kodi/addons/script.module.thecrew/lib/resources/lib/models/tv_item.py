# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file tv_item.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
import json
import time
from urllib.parse import quote

from ..modules import control
from ..modules import client
from ..modules import cache
from ..modules import cleantitle
from ..modules import fanart as fanart_tv
from ..modules import http_client
from ..modules import keys
from ..modules.crewruntime import c


class TVItem:
    """
    Base class for TV show items (both shows and episodes).
    Contains shared functionality for metadata, artwork, and ID resolution.
    """

    # Class-level TMDB configuration
    tmdb_link = 'https://api.themoviedb.org/3/'
    tmdb_img_link = 'https://image.tmdb.org/t/p/%s%s'

    def __init__(self, data=None):
        """
        Initialize TV item with optional data dictionary.

        Args:
            data (dict, optional): Dictionary containing item metadata
        """
        self.session = http_client.get_tmdb_session()
        self.tmdb_user = c.get_setting('tm.personal_user') or c.get_setting('tm.user') or keys.tmdb_key
        self.lang = control.apiLanguage()['tmdb']
        self.show_fanart = c.get_setting('fanart') == 'true'

        # Core identifiers
        self.imdb = '0'
        self.tmdb = '0'
        self.tvdb = '0'
        self.trakt = '0'

        # Basic metadata
        self.title = ''
        self.originaltitle = ''
        self.year = '0'
        self.plot = ''
        self.tagline = ''
        self.genre = ''
        self.rating = '0'
        self.votes = '0'
        self.duration = '0'
        self.premiered = ''
        self.status = ''

        # Network/Studio
        self.studio = ''
        self.network = ''
        self.country = ''

        # Content rating
        self.mpaa = ''

        # Cast and crew
        self.director = '0'
        self.writer = '0'
        self.cast = []
        self.castwiththumb = '0'

        # Artwork URLs
        self.poster = '0'
        self.fanart = '0'
        self.banner = '0'
        self.clearlogo = '0'
        self.clearart = '0'
        self.landscape = '0'
        self.thumb = '0'

        # Additional metadata
        self.trailer = ''
        self.mediatype = 'tvshow'  # Override in subclasses

        # Load data if provided
        if data:
            self.load_from_dict(data)

    def load_from_dict(self, data):
        """
        Load item properties from dictionary.

        Args:
            data (dict): Dictionary containing item metadata
        """
        # IDs
        self.imdb = str(data.get('imdb', '0'))
        self.tmdb = str(data.get('tmdb', '0'))
        self.tvdb = str(data.get('tvdb', '0'))
        self.trakt = str(data.get('trakt', '0'))

        # Metadata
        self.title = data.get('title', '')
        self.originaltitle = data.get('originaltitle', self.title)
        self.year = str(data.get('year', '0'))
        self.plot = data.get('plot', '')
        self.tagline = data.get('tagline', '')
        self.genre = data.get('genre', '')
        self.rating = str(data.get('rating', '0'))
        self.votes = str(data.get('votes', '0'))
        self.duration = str(data.get('duration', '0'))
        self.premiered = data.get('premiered', '')
        self.status = data.get('status', '')

        # Network/Studio
        self.studio = data.get('studio', '')
        self.network = data.get('network', '')
        self.country = data.get('country', '')

        # Rating
        self.mpaa = data.get('mpaa', '')

        # Cast and crew
        self.director = data.get('director', '0')
        self.writer = data.get('writer', '0')
        self.cast = data.get('cast', [])
        self.castwiththumb = data.get('castwiththumb', '0')

        # Artwork
        self.poster = data.get('poster', '0')
        self.fanart = data.get('fanart', '0')
        self.banner = data.get('banner', '0')
        self.clearlogo = data.get('clearlogo', '0')
        self.clearart = data.get('clearart', '0')
        self.landscape = data.get('landscape', '0')
        self.thumb = data.get('thumb', '0')

        # Additional
        self.trailer = data.get('trailer', '')

    def to_dict(self):
        """
        Convert item to dictionary for Kodi ListItem.

        Returns:
            dict: Dictionary representation of item
        """
        return {
            'imdb': self.imdb,
            'tmdb': self.tmdb,
            'tvdb': self.tvdb,
            'trakt': self.trakt,
            'originaltitle': self.originaltitle,
            'title': self.title,
            'year': self.year,
            'plot': self.plot,
            'tagline': self.tagline,
            'genre': self.genre,
            'rating': self.rating,
            'votes': self.votes,
            'duration': self.duration,
            'premiered': self.premiered,
            'status': self.status,
            'studio': self.studio,
            'network': self.network,
            'country': self.country,
            'mpaa': self.mpaa,
            'director': self.director,
            'writer': self.writer,
            'cast': self.cast,
            'castwiththumb': self.castwiththumb,
            'poster': self.poster,
            'fanart': self.fanart,
            'banner': self.banner,
            'clearlogo': self.clearlogo,
            'clearart': self.clearart,
            'landscape': self.landscape,
            'thumb': self.thumb,
            'trailer': self.trailer,
            'mediatype': self.mediatype,
        }

    def resolve_tmdb_id(self, tvshowtitle=None):
        """
        Resolve TMDB ID from existing IDs or by searching title.

        Args:
            tvshowtitle (str, optional): Show title for search fallback

        Returns:
            str: TMDB ID or '0' if not found
        """
        # Already have valid TMDB
        if self.tmdb and self.tmdb != '0':
            return self.tmdb

        # Try resolve from IMDB
        if self.imdb and self.imdb != '0':
            try:
                url = f"{self.tmdb_link}find/{self.imdb}?api_key={self.tmdb_user}&external_source=imdb_id"
                result = http_client.tmdb_get_json(url, timeout=16)
                if tv_results := (result or {}).get('tv_results') or []:
                    if tmdb_id := tv_results[0].get('id'):
                        self.tmdb = str(tmdb_id)
                        return self.tmdb
            except Exception as e:
                c.log(f"[TVItem] TMDB lookup by IMDB failed: {e}")

        # Fallback: search by title
        search_title = tvshowtitle or self.title
        if search_title:
            try:
                self.tmdb = self._search_tmdb_by_title(search_title, self.year)
                return self.tmdb
            except Exception as e:
                c.log(f"[TVItem] TMDB search failed: {e}")

        return '0'

    def _search_tmdb_by_title(self, title, year=None):
        """
        Search TMDB by title and optional year.

        Args:
            title (str): Show title to search
            year (str, optional): Year to filter results

        Returns:
            str: TMDB ID or '0' if not found
        """
        try:
            qtitle = quote(title)
            url = f"{self.tmdb_link}search/tv?api_key={self.tmdb_user}&language=en-US&query={qtitle}&page=1"
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
                    c.log(f"[TVItem] TMDB search attempt {attempt} failed: {e}")
                    if attempt < 3:
                        control.sleep(1000 * (2 ** (attempt - 1)))

            if not result:
                return '0'

            results = result.get('results') or []
            if not results:
                return '0'

            # Try exact cleantitle match first
            match = next((r for r in results if cleantitle.get(r.get('name')) == cleantitle.get(title)), None)
            if match is None:
                # Try case-insensitive match
                match = next((r for r in results if (r.get('name') or '').lower() == title.lower()), None)
            if match is None:
                # Use first result
                match = results[0]

            tmdb_id = match.get('id')
            return str(tmdb_id) if tmdb_id else '0'

        except Exception as e:
            c.log(f"[TVItem] TMDB search error: {e}")
            return '0'

    def fetch_tmdb_metadata(self):
        """
        Fetch metadata from TMDB for this item.
        Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement fetch_tmdb_metadata()")

    def fetch_fanart_tv_art(self):
        """
        Fetch extended artwork from fanart.tv.
        Requires valid TVDB ID.

        Returns:
            dict: Artwork dictionary or empty dict if failed
        """
        if not self.show_fanart or not self.tvdb or self.tvdb in ('0', None, ''):
            return {}

        try:
            # Verbose fanart fetching logged per show commented out for performance (50-100+ logs)
            # c.log(f'[TVItem] Fetching fanart.tv art for tvdb={self.tvdb}')
            tv_fanart = cache.get(fanart_tv.get_fanart_tv_art, 72, self.tvdb)

            if tv_fanart:
                # Update artwork with fanart.tv data (only if valid, don't override TMDB with '0')
                if tv_fanart.get('poster') and tv_fanart.get('poster') not in ['0', '', None]:
                    self.poster = tv_fanart['poster']
                if tv_fanart.get('fanart') and tv_fanart.get('fanart') not in ['0', '', None]:
                    self.fanart = tv_fanart['fanart']

                self.banner = tv_fanart.get('banner', self.banner) if tv_fanart.get('banner', '0') != '0' else self.banner
                self.clearlogo = tv_fanart.get('clearlogo', self.clearlogo) if tv_fanart.get('clearlogo', '0') != '0' else self.clearlogo
                self.clearart = tv_fanart.get('clearart', self.clearart) if tv_fanart.get('clearart', '0') != '0' else self.clearart
                self.landscape = tv_fanart.get('landscape', self.landscape) if tv_fanart.get('landscape', '0') != '0' else self.landscape
                return tv_fanart
            else:
                c.log('[TVItem] No fanart.tv data')
                return {}

        except Exception as e:
            c.log(f'[TVItem] Exception fetching fanart.tv art: {str(e)}')
            return {}

    @staticmethod
    def clean_plot(plot):
        """
        Clean HTML tags and entities from plot text.

        Args:
            plot (str): Raw plot text

        Returns:
            str: Cleaned plot text
        """
        if not plot:
            return '0'
        plot = re.sub('<.+?>|</.+?>|\n', '', plot)
        plot = client.replaceHTMLCodes(plot)
        return plot if plot else '0'

    @staticmethod
    def format_tmdb_image(size, path):
        """
        Format TMDB image URL.

        Args:
            size (str): Image size (e.g., 'w500', 'original')
            path (str): Image path from TMDB API

        Returns:
            str: Full image URL or '0' if no path
        """
        if not path:
            return '0'
        if not size:
            size = 'original'
        return f"https://image.tmdb.org/t/p/{size}{path}"
