# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file torrentgalaxy.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
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
            name='torrentgalaxy',
            base_link='https://tgx.rs',
            domains=['torrentgalaxy.to']
        )
        self.search_link = '/torrents.php?search=%s'

    def _scrape_torrents(self, data, hostDict):
        title = data.get('tvshowtitle', data.get('title'))
        hdlr = self._build_hdlr(data)
        query = self._build_query(data)
        query = re.sub(r'(\\\|/| -|:|;|\*|\?|"|\'|<|>|\|)', ' ', query)

        url = self.search_link % quote_plus(query)
        url = urljoin(self.base_link, url)

        try:
            r = client.request(url)
            posts = client.parseDom(r, 'div', attrs={'class': 'tgxtable'})

            for post in posts:
                links = re.findall('a href="(magnet:.+?)"', post, re.DOTALL)

                # Parse size
                try:
                    size_str = re.findall(r'((?:\d+\,\d+\.\d+|\d+\.\d+|\d+\,\d+|\d+)\s*(?:GiB|MiB|GB|MB))', post)[0]
                    dsize, isize = self._parse_size(size_str)
                except:
                    dsize, isize = 0.0, ''

                for url in links:
                    if hdlr not in url:
                        continue

                    # Filter non-English
                    if any(x in url for x in ['FRENCH', 'Ita', 'italian', 'TRUEFRENCH', '-lat-', 'Dublado']):
                        continue

                    url = url.split('&dn=', 1)[0]
                    info_hash = url.split('btih:')[1].split('&')[0] if 'btih:' in url else None

                    source_dict = self._build_torrent_source(url, url, 0, dsize, info_hash)
                    source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
                    self._sources_list.append(source_dict)

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
                    url = self.search_link % quote_plus(query)
                    url = urljoin(self.base_link, url)
                    r = client.request(url)

                    posts = client.parseDom(r, 'div', attrs={'class': 'tgxtable'})

                    for post in posts:
                        try:
                            links = re.findall('a href="(magnet:.+?)"', post, re.DOTALL)
                            if not links:
                                continue

                            url_magnet = links[0]

                            if search_series:
                                valid, last_season = source_utils.filter_show_pack(
                                    tvshowtitle, aliases, imdb, year, season,
                                    source_utils.release_title_format(url_magnet), total_seasons
                                )
                                if not valid:
                                    continue
                                package_meta = {'package': 'show', 'last_season': last_season}
                            else:
                                valid, episode_start, episode_end = source_utils.filter_season_pack(
                                    tvshowtitle, aliases, year, season,
                                    source_utils.release_title_format(url_magnet)
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

                            url_clean = url_magnet.split('&dn=', 1)[0]
                            info_hash = url_clean.split('btih:')[1].split('&')[0] if 'btih:' in url_clean else None

                            source_dict = self._build_torrent_source(url_magnet, url_clean, 0, dsize, info_hash)
                            source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
                            source_dict.update(package_meta)
                            sources.append(source_dict)

                        except:
                            continue

                except:
                    continue

            return sources
        except:
            return sources
