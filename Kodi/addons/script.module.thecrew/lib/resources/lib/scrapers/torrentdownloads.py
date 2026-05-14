# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file torrentdownloads.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urljoin, quote, quote_plus

from ..modules import cleantitle, client, workers
from .torrent_base import TorrentBaseScraper
from ..modules.crewruntime import c


class source(TorrentBaseScraper):
    def __init__(self):
        super().__init__(
            name='torrentdownloads',
            base_link='https://www.torrentdownloads.me',
            domains=['torrentdownloads.me']
        )
        self.search = '/rss.xml?new=1&type=search&cid={0}&search={1}'

    def _scrape_torrents(self, data, hostDict):
        title = data.get('tvshowtitle', data.get('title'))
        hdlr = self._build_hdlr(data)
        query = self._build_query(data)
        query = re.sub(r'(\\\|/| -|:|;|\*|\?|"|\'|<|>|\|)', ' ', query)

        if data.get('tvshowtitle'):
            url = self.search.format('8', quote(query))
        else:
            url = self.search.format('4', quote(query))

        url = urljoin(self.base_link, url)

        try:
            headers = {'User-Agent': client.agent()}
            _html = client.request(url, headers=headers)

            if not _html:
                c.log(f"[TorrentDownloads] Empty RSS response for {url}")
                return self._sources_list

            threads = [
                workers.Thread(self._get_items, i, title, hdlr)
                for i in re.findall(r'<item>(.+?)</item>', _html, re.DOTALL)
            ]
            [t.start() for t in threads]
            [t.join() for t in threads]

        except:
            pass

        return self._sources_list

    def _get_items(self, r, title, hdlr):
        try:
            size = re.search(r'<size>([\d]+)</size>', r).group(1)
            seeders = re.search(r'<seeders>([\d]+)</seeders>', r).group(1)
            _hash = re.search(r'<info_hash>([a-zA-Z0-9]+)</info_hash>', r).group(1)
            name = re.search(r'<title>(.+?)</title>', r).group(1)

            if seeders == '0':
                return

            t = name.split(hdlr)[0]

            try:
                y = re.findall(r'[\.|\(|\[|\s|\_|\-](S\d+E\d+|S\d+)[\.|\)|\]|\s|\_|\-]', name, re.I)[-1].upper()
            except:
                y = re.findall(r'[\.|\(|\[|\s\_|\-](\d{4})[\.|\)|\]|\s\_|\-]', name, re.I)[-1].upper()

            if cleantitle.get(re.sub('(|)', '', t)) != cleantitle.get(title) or y != hdlr:
                return

            url = self._build_magnet(_hash.upper(), name)
            dsize, isize = self._parse_size_bytes(int(size))

            source_dict = self._build_torrent_source(name, url, int(seeders), dsize, _hash)
            source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
            source_dict['source'] = 'torrent'  # lowercase
            self._sources_list.append(source_dict)

        except:
            pass

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
                    url = self.search.format('8', quote_plus(query))
                    url = urljoin(self.base_link, url)
                    r = client.request(url)

                    items = client.parseDom(r, 'item')

                    for item in items:
                        try:
                            name = client.parseDom(item, 'title')[0]

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

                            seeders = re.findall(r'<torrent:seeds>(\d+)</torrent:seeds>', item)
                            seeders = seeders[0] if seeders else '0'
                            if seeders == '0':
                                continue

                            url_magnet = re.findall('<link>(.+?)</link>', item)[0]
                            url_magnet = client.request(url_magnet, output='geturl')
                            if 'magnet:' not in url_magnet:
                                continue
                            url_magnet = url_magnet.split('&tr=')[0]

                            quality, info = source_utils.get_release_quality(name, name)
                            try:
                                size_str = re.findall(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|MB|MiB))', name)[0]
                                dsize, isize = self._parse_size(size_str)
                                info.insert(0, isize) if isize else None
                            except:
                                pass
                            info = ' | '.join(info)

                            source_dict = {'source': 'torrent', 'quality': quality, 'language': 'en',
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
