# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file glodls.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urljoin, quote_plus

from ..modules import cleantitle, client
from .torrent_base import TorrentBaseScraper


class source(TorrentBaseScraper):
    def __init__(self):
        super().__init__(
            name='glodls',
            base_link='https://glodls.to/',
            domains=['glodls.to']
        )
        self.tvsearch = 'search_results.php?search={0}&cat=41&incldead=0&inclexternal=0&lang=1&sort=seeders&order=desc'
        self.moviesearch = 'search_results.php?search={0}&cat=1&incldead=0&inclexternal=0&lang=1&sort=size&order=desc'

    def _scrape_torrents(self, data, hostDict):
        title = data.get('tvshowtitle', data.get('title'))
        hdlr = self._build_hdlr(data)
        query = self._build_query(data)
        query = re.sub('(\\\|/| -|:|;|\*|\?|"|\'|<|>|\|)', ' ', query)

        if data.get('tvshowtitle'):
            url = self.tvsearch.format(quote_plus(query))
        else:
            url = self.moviesearch.format(quote_plus(query))

        url = urljoin(self.base_link, url)

        try:
            headers = {'User-Agent': client.agent()}
            r = client.request(url, headers=headers)
            posts = client.parseDom(r, 'tr', attrs={'class': 't-row'})
            posts = [i for i in posts if 'racker:' not in i]

            for post in posts:
                try:
                    data_links = client.parseDom(post, 'a', ret='href')
                    url_magnet = [i for i in data_links if 'magnet:' in i][0]
                    name = client.parseDom(post, 'a', ret='title')[0]

                    t = name.split(hdlr)[0]
                    if cleantitle.get(re.sub('(|)', '', t)) != cleantitle.get(title):
                        continue

                    if not self._matches_release(name, title, hdlr):
                        continue

                    try:
                        size_str = re.findall(r'((?:\d+\,\d+\.\d+|\d+\.\d+|\d+\,\d+|\d+)\s*(?:GiB|MiB|GB|MB))', post)[0]
                        dsize, isize = self._parse_size(size_str)
                    except:
                        dsize, isize = 0.0, ''

                    url_clean = url_magnet.split('&tr')[0]
                    info_hash = url_clean.split('btih:')[1].split('&')[0] if 'btih:' in url_clean else None

                    source_dict = self._build_torrent_source(name, url_clean, 0, dsize, info_hash)
                    source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
                    self._sources_list.append(source_dict)

                except:
                    pass

        except:
            pass

        return self._sources_list

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
                    url = self.tvsearch.format(quote_plus(query))
                    url = urljoin(self.base_link, url)
                    r = client.request(url)
                    posts = client.parseDom(r, 'tr', attrs={'class': 't-row'})

                    for post in posts:
                        try:
                            name = client.parseDom(post, 'a', attrs={'class': 'pn'})[0]

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

                            url_magnet = client.parseDom(post, 'a', ret='href', attrs={'class': 'ttth'})[0]
                            if not url_magnet.startswith('magnet'):
                                url_magnet = urljoin(self.base_link, url_magnet)
                                r2 = client.request(url_magnet)
                                url_magnet = re.findall('href="(magnet:.+?)"', r2, re.DOTALL)[0]
                            url_magnet = url_magnet.split('&tr=')[0]

                            quality, info = source_utils.get_release_quality(name, name)
                            try:
                                size_str = re.findall(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|MB|MiB))', post)[0]
                                dsize, isize = self._parse_size(size_str)
                            except:
                                dsize, isize = 0.0, ''
                            info.insert(0, isize) if isize else None
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
