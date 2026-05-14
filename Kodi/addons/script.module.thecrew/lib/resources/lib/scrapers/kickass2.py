# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file kickass2.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urljoin, quote_plus, unquote

from ..modules import cache, cleantitle, client
from .torrent_base import TorrentBaseScraper


class source(TorrentBaseScraper):
    # Disabled for 2.3.0-beta - slow (20-30s) with low success rate
    disabled = True

    def __init__(self):
        super().__init__(
            name='kickass2',
            domains=['kickass.love', 'kkickass.com', 'kkat.net', 'kickass-kat.com', 'kickasst.net',
                    'kickasst.org', 'kickasstorrents.id', 'thekat.cc', 'thekat.ch']
        )
        self.search_link = '/usearch/%s'
        self._cached_base = None

    @property
    def base_link(self):
        if self._cached_base is None:
            self._cached_base = cache.get(self._get_base_url, 120, f'https://{self.domains[0]}')
        return self._cached_base

    def _scrape_torrents(self, data, hostDict):
        title = data.get('tvshowtitle', data.get('title'))
        hdlr = self._build_hdlr(data)
        query = self._build_query(data)
        query = re.sub('(\\\|/| -|:|;|\*|\?|"|<|>|\|)', ' ', query)

        url = self.search_link % quote_plus(query)
        url = urljoin(self.base_link, url)
        html = client.request(url)

        if not html:
            return self._sources_list

        html = html.replace('&nbsp;', ' ')

        try:
            rows = client.parseDom(html, 'tr', attrs={'id': 'torrent_latest_torrents'})
        except:
            return self._sources_list

        if not rows:
            return self._sources_list

        for entry in rows:
            try:
                name = re.findall('class="cellMainLink">(.+?)</a>', entry, re.DOTALL)[0]
                name = client.replaceHTMLCodes(name)

                if cleantitle.get(title) not in cleantitle.get(name):
                    continue

                if not self._matches_release(name, title, hdlr):
                    continue

                try:
                    seeders = int(re.findall('<td class="green center">(.+?)</td>', entry, re.DOTALL)[0])
                except:
                    seeders = 0

                if not self._check_seeders(seeders, self.min_seeders):
                    continue

                try:
                    link = 'magnet%s' % re.findall('url=magnet(.+?)"', entry, re.DOTALL)[0]
                    link = str(unquote(link).split('&tr')[0])
                except:
                    continue

                try:
                    size_str = re.findall(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|MB|MiB))', entry)[-1]
                    dsize, isize = self._parse_size(size_str)
                except:
                    dsize, isize = 0.0, ''

                info_hash = link.split('btih:')[1].split('&')[0] if 'btih:' in link else None
                source_dict = self._build_torrent_source(name, link, seeders, dsize, info_hash)
                source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
                self._sources_list.append(source_dict)

            except:
                continue

        return self._sources_list

    def _get_base_url(self, fallback):
        for domain in self.domains:
            try:
                url = f'https://{domain}'
                result = client.request(url, timeout='10')
                search_n = re.findall('<input type="txt" name="(.+?)"', result, re.DOTALL)[0]
                if search_n and 'q1' in search_n:
                    return url
            except:
                continue
        return fallback

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
                queries.append(f'{title_query} Complete Series')
            else:
                queries.append(f'{title_query} S{season:02d}')

            for query in queries:
                try:
                    url = self.search_link % quote_plus(query)
                    url = urljoin(self.base_link, url)
                    r = client.request(url)
                    posts = client.parseDom(r, 'tr')[2:]

                    for post in posts:
                        try:
                            data_link = client.parseDom(post, 'a', ret='href', attrs={'class': 'cellMainLink'})[0]
                            name = client.parseDom(post, 'a', attrs={'class': 'cellMainLink'})[0]

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
                                package_meta = {'package': 'season', 'episode_start': episode_start, 'episode_end': episode_end}

                            r2 = client.request(urljoin(self.base_link, data_link))
                            url_magnet = re.findall('\"(magnet:.+?)\"', r2, re.DOTALL)[0]
                            url_magnet = unquote(url_magnet).split('&tr=')[0]

                            quality, info = source_utils.get_release_quality(name, name)
                            try:
                                size_str = re.findall(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|MB|MiB))', post)[0]
                                dsize, isize = self._parse_size(size_str)
                                info.insert(0, isize) if isize else None
                            except:
                                pass
                            info = ' | '.join(info)

                            source_dict = {'source': 'Torrent', 'quality': quality, 'language': 'en',
                                         'url': url_magnet, 'info': info, 'direct': False, 'debridonly': True}
                            source_dict.update(package_meta)
                            sources.append(source_dict)
                        except:
                            continue
                except:
                    continue
            return sources
        except:
            return sources
