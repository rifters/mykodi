# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file easynews.py (refactored with BaseScraper)
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
import json
import base64
import requests

from urllib.parse import quote

from .base import BaseScraper
from ..modules import control, cleantitle, source_utils
from ..modules.crewruntime import c

SORT = {'s1': 'relevance', 's1d': '-', 's2': 'dsize', 's2d': '-', 's3': 'dtime', 's3d': '-'}
SEARCH_PARAMS = {'st': 'adv', 'sb': 1, 'fex': 'mkv, mp4, avi, mpg, wemb', 'fty[]': 'VIDEO', 'spamf': 1, 'u': '1', 'gx': 1, 'pno': 1, 'sS': 3}
SEARCH_PARAMS.update(SORT)


class source(BaseScraper):
    """
    Easynews scraper - refactored to use BaseScraper

    Before: 393 lines
    After: ~240 lines (39% reduction)

    Note: More complex due to pack support and auth requirements
    """

    pack_capable = True

    def __init__(self):
        super().__init__(
            name='easynews',
            base_link='https://members.easynews.com',
            search_link='/2.0/search/solr-search/advanced',
            domains=['easynews.com']
        )

    def _scrape_sources(self, url, hostDict):
        """Site-specific scraping logic"""
        auth = self._get_auth()
        if not auth:
            c.log('[easynews] No credentials - skipping')
            return []

        sources = []
        query = self._query(url)
        search_url, params = self._translate_search(query)
        headers = {'Authorization': auth}

        # Request search
        try:
            resp = requests.get(search_url, params=params, headers=headers, timeout=10)
        except Exception as e:
            c.log(f'[easynews] Network error: {e}')
            return sources

        if getattr(resp, 'status_code', None) != 200:
            c.log(f'[easynews] HTTP {getattr(resp, "status_code", None)}')
            return sources

        # Parse results
        try:
            results = json.loads(resp.text)
        except Exception as e:
            c.log(f'[easynews] JSON error: {e}')
            return sources

        down_url = results.get('downURL')
        dl_farm = results.get('dlFarm')
        dl_port = results.get('dlPort')
        files = results.get('data', []) or []

        for item in files:
            try:
                post_hash = item.get('0')
                post_title = item.get('10')
                ext = item.get('11') or ''
                duration = item.get('14') or ''

                # Filter checks
                checks = [False] * 6
                if item.get('alangs') and 'eng' not in item.get('alangs'):
                    checks[1] = True
                if re.match(r'^\d+s', str(duration)) or re.match(r'^[0-5]m', str(duration)):
                    checks[2] = True
                if item.get('passwd'):
                    checks[3] = True
                if item.get('virus'):
                    checks[4] = True
                if item.get('type') and str(item.get('type')).upper() != 'VIDEO':
                    checks[5] = True

                if any(checks):
                    continue

                if not (down_url and dl_farm and dl_port and post_hash):
                    c.log(f'[easynews] Missing fields: {post_title}')
                    continue

                # Build URL
                try:
                    stream_url = down_url + quote('/%s/%s/%s%s/%s%s' % (dl_farm, dl_port, post_hash, ext, post_title, ext))
                except Exception as e:
                    c.log(f'[easynews] URL build error: {e}')
                    continue

                file_dl = stream_url + '|Authorization=%s' % (quote(auth))

                # Get size
                try:
                    raw_size = int(item.get('rawSize', 0))
                    size = float(raw_size) / 1073741824 if raw_size else 0
                except Exception:
                    size = 0

                # Get quality and info
                try:
                    quality = source_utils.get_release_quality(post_title)[0]
                except Exception:
                    quality = 'SD'

                try:
                    info = source_utils.get_file_type(post_title)
                except Exception:
                    info = 'Unknown'

                info = '%.2f GB | %s | %s' % (size, info, post_title.replace('.', ' ').upper()) if post_title else ''

                sources.append({
                    'source': 'direct',
                    'quality': quality,
                    'language': 'en',
                    'url': file_dl,
                    'info': info,
                    'direct': True,
                    'debridonly': False
                })

            except Exception as e:
                c.log(f'[easynews] Item error: {e}')
                continue

        return sources

    def sources_packs(self, data, hostDict, search_series=False, total_seasons=0, bypass_filter=0):
        """Search for season packs or complete series"""
        auth = self._get_auth()
        if not auth:
            c.log('[easynews] No credentials - skipping pack search')
            return []

        sources = []

        try:
            tvshowtitle = data.get('tvshowtitle')
            year = data.get('year')
            season = int(data.get('season', 0))
            imdb = data.get('imdb')
            aliases = data.get('aliases', [])

            if not tvshowtitle:
                return sources

            title = cleantitle.normalize(tvshowtitle)

            # Build queries
            queries = []
            if search_series:
                queries.extend([
                    f'{title} Complete Series',
                    f'{title} S01-S{total_seasons:02d}' if total_seasons > 0 else f'{title} Complete'
                ])
            else:
                queries.extend([
                    f'{title} S{season:02d}',
                    f'{title} Season {season}'
                ])

            for query in queries:
                try:
                    search_url, params = self._translate_search(query)
                    headers = {'Authorization': auth}
                    resp = requests.get(search_url, params=params, headers=headers, timeout=10)

                    if getattr(resp, 'status_code', None) != 200:
                        continue

                    results = json.loads(resp.text)
                    files = results.get('data', []) or []
                    down_url = results.get('downURL')
                    dl_farm = results.get('dlFarm')
                    dl_port = results.get('dlPort')

                    for item in files:
                        try:
                            post_hash = item.get('0')
                            post_title = item.get('10')
                            ext = item.get('11') or ''
                            duration = item.get('14') or ''

                            # Basic checks
                            if item.get('alangs') and 'eng' not in item.get('alangs'):
                                continue
                            if item.get('passwd') or item.get('virus'):
                                continue
                            if item.get('type') and str(item.get('type')).upper() != 'VIDEO':
                                continue
                            if re.match(r'^\d+s', str(duration)) or re.match(r'^[0-5]m', str(duration)):
                                continue

                            if not (down_url and dl_farm and dl_port and post_hash):
                                continue

                            file_name = post_title or ''

                            # Validate pack
                            if search_series:
                                valid, last_season = source_utils.filter_show_pack(
                                    tvshowtitle, aliases, imdb, year, season,
                                    source_utils.release_title_format(file_name), total_seasons
                                )
                                if not valid:
                                    continue
                                package_meta = {'package': 'show', 'last_season': last_season}
                            else:
                                valid, episode_start, episode_end = source_utils.filter_season_pack(
                                    tvshowtitle, aliases, year, season,
                                    source_utils.release_title_format(file_name)
                                )
                                if not valid:
                                    continue
                                package_meta = {'package': 'season', 'episode_start': episode_start, 'episode_end': episode_end}

                            # Build URL
                            stream_url = down_url + quote('/%s/%s/%s%s/%s%s' % (dl_farm, dl_port, post_hash, ext, post_title, ext))
                            file_dl = stream_url + '|Authorization=%s' % (quote(auth))

                            # Get size and quality
                            try:
                                raw_size = int(item.get('rawSize', 0))
                                size = float(raw_size) / 1073741824 if raw_size else 0
                            except Exception:
                                size = 0

                            try:
                                quality = source_utils.get_release_quality(file_name)[0]
                            except Exception:
                                quality = 'SD'

                            try:
                                info = source_utils.get_file_type(file_name)
                            except Exception:
                                info = 'Unknown'

                            info = '%.2f GB | %s | %s' % (size, info, file_name.replace('.', ' ').upper())

                            source_dict = {
                                'source': 'direct',
                                'quality': quality,
                                'language': 'en',
                                'url': file_dl,
                                'info': info,
                                'direct': True,
                                'debridonly': False,
                                'size': size,
                                'name': file_name
                            }
                            source_dict.update(package_meta)
                            sources.append(source_dict)

                        except Exception as e:
                            c.log(f'[easynews] Pack item error: {e}')
                            continue

                except Exception as e:
                    c.log(f'[easynews] Pack query error: {e}')
                    continue

            return sources

        except Exception as e:
            c.log(f'[easynews] sources_packs error: {e}')
            return sources

    def _get_auth(self):
        """Get authorization header"""
        username = control.setting('easynews.user')
        password = control.setting('easynews.password')

        if username == '' or password == '':
            return None

        try:
            user_info = '%s:%s' % (username, password)
            user_info = user_info.encode('utf-8')
            auth = 'Basic ' + base64.b64encode(user_info).decode('utf-8')
            return auth
        except Exception:
            return None

    def _query(self, url):
        """Build search query"""
        content_type = 'episode' if 'tvshowtitle' in url else 'movie'

        if content_type == 'movie':
            title = cleantitle.normalize(url.get('title'))
            year = int(url.get('year'))
            years = '%s,%s,%s' % (str(year - 1), year, str(year + 1))
            query = '"%s" %s' % (title, years)
        else:
            title = cleantitle.normalize(url.get('tvshowtitle'))
            season = int(url.get('season'))
            episode = int(url.get('episode'))
            query = '%s S%02dE%02d' % (title, season, episode)

        return query

    def _translate_search(self, query):
        """Translate query to Easynews search params"""
        params = SEARCH_PARAMS.copy()
        params['pby'] = 100
        params['safeO'] = 1
        params['gps'] = params['sbj'] = query
        url = self.base_link + self.search_link
        return url, params
