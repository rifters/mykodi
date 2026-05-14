# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file x1337.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import quote, urljoin

from ..modules import cache, cleantitle, client, dom_parser as dom, workers
from .torrent_base import TorrentBaseScraper
from ..modules.crewruntime import c

# Module-level logging to verify import
c.log('========== [1337x] MODULE LOADED - scrapers/x1337.py imported ==========', __name__)


class source(TorrentBaseScraper):
    def __init__(self):
        super().__init__(
            name='1337x',
            domains=['1337x.tw', '1337x.pro', 'www.1377x.is', '1337x.to', '1337x.st', '1337x.se', '1337x.eu', '1337x.ws', '1337x.gd']
        )
        c.log('========== [1337x] __init__() CALLED - source class instantiated ==========')
        self.tvsearch = '/sort-category-search/%s/TV/seeders/desc/1/'
        self.moviesearch = '/sort-category-search/%s/Movies/size/desc/1/'
        self._cached_base = None

    @property
    def base_link(self):
        if not self._cached_base:
            self._cached_base = cache.get(self._get_base_url, 120, f'https://{self.domains[0]}')
        return self._cached_base

    def _scrape_torrents(self, data, hostDict):
        c.log(f'[1337x] _scrape_torrents STARTED')
        c.log(f'[1337x] Data: {data}')

        # Build search URLs
        self.tvsearch = f'{self.base_link}/sort-category-search/%s/TV/seeders/desc/1/'
        self.moviesearch = f'{self.base_link}/sort-category-search/%s/Movies/size/desc/1/'

        query = self._build_query(data)
        query = re.sub(r'(\\\|/| -|:|;|\*|\?|"|\'|<|>|\|)', ' ', query)

        c.log(f'[1337x] Query: {query}')

        urls = []
        if data.get('tvshowtitle'):
            base = self.tvsearch % quote(query)
            urls = [base, base.replace('/1/', '/2/'), base.replace('/1/', '/3/')]
        else:
            base = self.moviesearch % quote(query)
            urls = [base, base.replace('/1/', '/2/'), base.replace('/1/', '/3/')]

        c.log(f'[1337x] Search URLs: {urls}')

        # Fetch items concurrently
        items = []
        threads = [workers.Thread(self._get_items, url, data, items) for url in urls]
        [t.start() for t in threads]
        [t.join() for t in threads]

        c.log(f'[1337x] Found {len(items)} items')

        # Get sources from items
        threads = [workers.Thread(self._get_sources, item) for item in items]
        [t.start() for t in threads]
        [t.join() for t in threads]

        c.log(f'[1337x] Returning {len(self._sources_list)} sources')
        return self._sources_list

    def _get_items(self, url, data, items):
        try:
            title = data.get('tvshowtitle', data.get('title'))
            title = cleantitle.get_query(title)
            hdlr = self._build_hdlr(data)

            r = self._safe_request(url, timeout=10, retries=2)
            if not r:
                return
            r = c.to_str(r, errors='replace')

            posts = client.parseDom(r, 'tbody')
            if not posts:
                return
            posts = client.parseDom(posts[0], 'tr')

            for post in posts:
                a_tags = client.parseDom(post, 'a')
                a_hrefs = client.parseDom(post, 'a', ret='href')
                if len(a_tags) < 2 or len(a_hrefs) < 2:
                    continue

                link = urljoin(self.base_link, a_hrefs[1])
                name = a_tags[1]

                # Match title
                t = name.split(hdlr)[0]
                if cleantitle.get(re.sub('(|)', '', t)) != cleantitle.get(title):
                    continue

                # Match handler
                if not self._matches_release(name, title, hdlr):
                    continue

                # Parse size
                try:
                    size_str = re.findall(r'((?:\d+\,\d+\.\d+|\d+\.\d+|\d+\,\d+|\d+)\s*(?:GiB|MiB|GB|MB))', post)[0]
                    dsize, isize = self._parse_size(size_str)
                except:
                    dsize, isize = 0.0, ''

                items.append((name, link, isize, dsize))
        except Exception as e:
            c.log(f'1337x_get_items: {e}', 1)

    def _get_sources(self, item):
        try:
            name, link, isize, dsize = item

            # Get detail page
            data = self._safe_request(link, timeout=10, retries=2)
            if not data:
                return
            data = c.to_str(data, errors='replace')

            # Extract magnet
            data = client.parseDom(data, 'a', ret='href')
            mags = [i for i in data if 'magnet:' in i]
            if not mags:
                return

            url = mags[0].split('&tr')[0]
            info_hash = url.split('btih:')[1].split('&')[0] if 'btih:' in url else None

            source_dict = self._build_torrent_source(name, url, 0, dsize, info_hash)
            source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
            self._sources_list.append(source_dict)
        except Exception as e:
            c.log(f'1337x_get_sources: {e}', 1)

    def _safe_request(self, url, timeout=10, retries=2):
        for _ in range(retries):
            try:
                r = client.request(url, timeout=timeout)
                if r:
                    return r
            except:
                continue
        return None

    def sources_packs(self, data, hostDict, search_series=False, total_seasons=0, bypass_filter=0):
        from ..modules import source_utils
        sources = []
        try:
            tvshowtitle = data.get('tvshowtitle')
            year = data.get('year')
            season = int(data.get('season', 0))
            imdb = data.get('imdb')
            aliases = data.get('aliases', [])

            if not tvshowtitle:
                return sources

            title_query = cleantitle.get_query(tvshowtitle)
            queries = []

            if search_series:
                queries.extend([
                    f'{title_query} Complete Series',
                    f'{title_query} All Seasons',
                ])
            else:
                queries.extend([
                    f'{title_query} S{season:02d}',
                    f'{title_query} Season {season}',
                ])

            for query in queries:
                try:
                    search_url = self.tvsearch % quote(query)
                    r = client.request(search_url)
                    r = c.to_str(r, errors='replace')

                    posts = client.parseDom(r, 'tbody')[0]
                    posts = client.parseDom(posts, 'tr')

                    for post in posts:
                        try:
                            a_hrefs = client.parseDom(post, 'a', ret='href')
                            a_tags = client.parseDom(post, 'a')
                            if len(a_hrefs) < 2 or len(a_tags) < 2:
                                continue
                            link = urljoin(self.base_link, a_hrefs[1])
                            name = a_tags[1]

                            if search_series:
                                valid, last_season = source_utils.filter_show_pack(
                                    tvshowtitle, aliases, imdb, year, season,
                                    source_utils.release_title_format(name), total_seasons
                                )
                                if not valid:
                                    continue
                                package_meta = {'package': 'show', 'last_season': last_season}
                            else:
                                valid, episode_start, episode_end = source_utils.filter_season_pack(
                                    tvshowtitle, aliases, year, season,
                                    source_utils.release_title_format(name)
                                )
                                if not valid:
                                    continue
                                package_meta = {
                                    'package': 'season',
                                    'episode_start': episode_start,
                                    'episode_end': episode_end
                                }

                            try:
                                size_str = re.findall(r'((?:\d+\,\d+\.\d+|\d+\.\d+|\d+\,\d+|\d+)\s*(?:GiB|MiB|GB|MB))', post)[0]
                                dsize, isize = self._parse_size(size_str)
                            except:
                                dsize, isize = 0.0, ''

                            # Get magnet
                            detail_page = client.request(link)
                            detail_page = c.to_str(detail_page, errors='replace')
                            detail_data = client.parseDom(detail_page, 'a', ret='href')
                            url = [i for i in detail_data if 'magnet:' in i][0]
                            url = url.split('&tr')[0]
                            info_hash = url.split('btih:')[1].split('&')[0] if 'btih:' in url else None

                            source_dict = self._build_torrent_source(name, url, 0, dsize, info_hash)
                            source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
                            source_dict.update(package_meta)
                            sources.append(source_dict)

                        except Exception as e:
                            c.log(f'1337x Pack - Error processing: {e}', 1)
                            continue

                except Exception as e:
                    c.log(f'1337x Pack - Error searching: {e}', 1)
                    continue

            return sources
        except Exception as e:
            c.log(f'1337x Pack - Exception: {e}', 1)
            return sources

    def _get_base_url(self, fallback):
        for domain in self.domains:
            try:
                url = f'https://{domain}'
                result = self._safe_request(url, timeout=7, retries=1)
                if not result:
                    continue
                result = c.to_str(result, errors='ignore')
                m = re.findall('<title>(.+?)</title>', result, re.DOTALL)
                if m and '1337x' in m[0].lower():
                    return url
            except:
                continue
        return fallback
