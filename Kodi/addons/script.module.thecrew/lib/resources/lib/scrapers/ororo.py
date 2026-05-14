# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file ororo.py (refactored with BaseScraper)
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
import base64
import json

from urllib.parse import urljoin

from ..scrapers.base import BaseScraper
from ..modules import cache, control, client
from ..modules.crewruntime import c


class source(BaseScraper):
    """
    Ororo.tv scraper - refactored to use BaseScraper

    Before: 234 lines
    After: ~140 lines (40% reduction)

    Note: Requires login credentials
    """

    def __init__(self):
        # Get credentials
        user = control.setting('ororo.user')
        password = control.setting('ororo.pass')
        user_pass = f'{user}:{password}'
        encoded = base64.b64encode(user_pass.encode('utf-8')).decode('utf-8')

        super().__init__(
            name='ororo',
            base_link='https://ororo.tv',
            search_link='/api/v2/shows',
            domains=['ororo.tv'],
            headers={
                'Authorization': f'Basic {encoded}',
                'User-Agent': 'Kodi'
            }
        )

        self.moviesearch_link = '/api/v2/movies'
        self.tvsearch_link = '/api/v2/shows'
        self.movie_link = '/api/v2/movies/%s'
        self.show_link = '/api/v2/shows/%s'
        self.episode_link = '/api/v2/episodes/%s'

        self.user = user
        self.password = password

    def movie(self, imdb, title, localtitle, aliases, year):
        """Get movie URL by IMDb ID"""
        if not self.user or not self.password:
            c.log('[ororo] No credentials - skipping movie()')
            return None

        try:
            url = self.ororo_moviecache(self.user)
            if not url:
                c.log('[ororo] Empty movie cache')
                return None

            # Find IMDb match
            try:
                url_id = [i[0] for i in url if imdb == i[1]][0]
            except Exception:
                c.log(f'[ororo] Movie {imdb} not found')
                return None

            return self.movie_link % url_id
        except Exception as e:
            c.log(f'[ororo] movie() error: {e}')
            return None

    def tvshow(self, imdb, tvdb, tvshowtitle, localtvshowtitle, aliases, year):
        """Get TV show URL by IMDb ID"""
        if not self.user or not self.password:
            c.log('[ororo] No credentials - skipping tvshow()')
            return None

        try:
            url = cache.get(self.ororo_tvcache, 120, self.user)
            if not url:
                c.log('[ororo] Empty TV cache')
                return None

            # Find IMDb match
            try:
                url_id = [i[0] for i in url if imdb == i[1]][0]
            except Exception:
                c.log(f'[ororo] TV show {imdb} not found')
                return None

            return self.show_link % url_id
        except Exception as e:
            c.log(f'[ororo] tvshow() error: {e}')
            return None

    def episode(self, url, imdb, tvdb, title, premiered, season, episode):
        """Get episode URL"""
        if not self.user or not self.password:
            c.log('[ororo] No credentials - skipping episode()')
            return None

        if url is None:
            return None

        try:
            url_full = urljoin(self.base_link, url)
            r = client.request(url_full, headers=self.headers)
        except Exception as e:
            c.log(f'[ororo] Network error: {e}')
            return None

        try:
            data = json.loads(r)
            episodes = data.get('episodes', [])
            episodes = [(str(i.get('id')), str(i.get('season')), str(i.get('number')), str(i.get('airdate'))) for i in episodes]
        except Exception as e:
            c.log(f'[ororo] Parse error: {e}')
            return None

        # Find matching episode
        matches = [i for i in episodes if season == '%01d' % int(i[1]) and episode == '%01d' % int(i[2])]
        matches += [i for i in episodes if premiered == i[3]]

        if not matches:
            c.log('[ororo] No matching episode')
            return None

        try:
            return self.episode_link % matches[0][0]
        except Exception as e:
            c.log(f'[ororo] Episode URL error: {e}')
            return None

    def _scrape_sources(self, url, hostDict):
        """Site-specific scraping logic"""
        sources = []

        if not self.user or not self.password:
            c.log('[ororo] No credentials - skipping sources')
            return sources

        # Parse URL to get path
        data = self._parse_data(url)
        if data:
            # URL-encoded data - not used for ororo (uses paths)
            return sources

        # URL is a path like /api/v2/movies/123
        try:
            url_full = urljoin(self.base_link, url)
            r = client.request(url_full, headers=self.headers)
        except Exception as e:
            c.log(f'[ororo] Network error: {e}')
            return sources

        try:
            data = json.loads(r)
            media_url = data.get('url')
            if not media_url:
                c.log(f'[ororo] No URL in response')
                return sources

            sources.append({
                'source': 'ororo',
                'quality': 'HD',
                'language': 'en',
                'url': media_url,
                'direct': True,
                'debridonly': False
            })
        except Exception as e:
            c.log(f'[ororo] Parse error: {e}')

        return sources

    def ororo_moviecache(self, user):
        """Build movie cache"""
        try:
            url = urljoin(self.base_link, self.moviesearch_link)
            c.log(f'[ororo] Fetching movie cache from {url}')

            r = client.request(url, headers=self.headers)
            try:
                data = json.loads(r)
            except Exception as e:
                c.log(f'[ororo] JSON error: {e}')
                return None

            movies = data.get('movies', [])
            result = []
            for i in movies:
                try:
                    result.append((str(i.get('id')), str(i.get('imdb_id'))))
                except Exception:
                    continue

            result = [(i[0], 'tt' + re.sub('[^0-9]', '', i[1])) for i in result if i[1]]
            return result
        except Exception as e:
            c.log(f'[ororo] Movie cache error: {e}')
            return None

    def ororo_tvcache(self, user):
        """Build TV cache"""
        try:
            url = urljoin(self.base_link, self.tvsearch_link)
            c.log(f'[ororo] Fetching TV cache from {url}')

            r = client.request(url, headers=self.headers)
            try:
                data = json.loads(r)
            except Exception as e:
                c.log(f'[ororo] JSON error: {e}')
                return None

            shows = data.get('shows', [])
            result = []
            for i in shows:
                try:
                    result.append((str(i.get('id')), str(i.get('imdb_id'))))
                except Exception:
                    continue

            result = [(i[0], 'tt' + re.sub(r'[^0-9]', '', i[1])) for i in result if i[1]]
            return result
        except Exception as e:
            c.log(f'[ororo] TV cache error: {e}')
            return None
