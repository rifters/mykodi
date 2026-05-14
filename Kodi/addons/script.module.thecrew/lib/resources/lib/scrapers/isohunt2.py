# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file isohunt2.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urljoin, quote_plus, unquote

from ..modules import cleantitle, client
from .torrent_base import TorrentBaseScraper


class source(TorrentBaseScraper):
    def __init__(self):
        super().__init__(
            name='isohunt2',
            base_link='https://isohunt.nz',
            domains=['isohunt2.net']
        )
        self.search_link = '/torrent/?ihq=%s&fiht=2&age=0&Torrent_sort=seeders'

    def _scrape_torrents(self, data, hostDict):
        title = data.get('tvshowtitle', data.get('title'))
        hdlr = self._build_hdlr(data)
        query = self._build_query(data)
        query = re.sub(r'(\\\|/| -|:|;|\*|\?|"|\'|<|>|\|)', ' ', query)

        url = self.search_link % quote_plus(query)
        url = urljoin(self.base_link, url)

        try:
            r = client.request(url)
            posts = client.parseDom(r, 'tbody')[0]
            posts = client.parseDom(posts, 'tr')

            for post in posts:
                try:
                    links = re.compile('<a href="(/torrent_details/.+?)">\n<span>(.+?)</span>').findall(post)
                    for link, name in links:
                        if hdlr not in name:
                            continue

                        # Filter non-English
                        if any(x in link for x in ['FRENCH', 'Ita', 'ITA', 'italian', 'Tamil', 'TRUEFRENCH', '-lat-', 'Dublado', 'Dub', 'Rus', 'Hindi']):
                            continue

                        link_url = urljoin(self.base_link, link)
                        detail = client.request(link_url)

                        try:
                            size_str = re.findall('Size&nbsp;(.+?)&nbsp', detail, re.DOTALL)[0]
                            dsize, isize = self._parse_size(size_str)
                        except:
                            dsize, isize = 0.0, ''

                        # Extract magnet from detail page
                        url_magnet = unquote(detail)
                        url_magnet = url_magnet.split('url=')[1].split('&tr=')[0].replace('%28', '(').replace('%29', ')')
                        info_hash = url_magnet.split('btih:')[1].split('&')[0] if 'btih:' in url_magnet else None

                        source_dict = self._build_torrent_source(name, url_magnet, 0, dsize, info_hash)
                        source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
                        self._sources_list.append(source_dict)

                except:
                    continue

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
                    url = self.search_link % quote_plus(query)
                    url = urljoin(self.base_link, url)
                    r = client.request(url)
                    posts = client.parseDom(r, 'tr', attrs={'class': 't-row'})

                    for post in posts:
                        try:
                            data_elem = client.parseDom(post, 'td', attrs={'class': 'title-row'})[0]
                            link = client.parseDom(data_elem, 'a', ret='href')[0]
                            name = client.parseDom(data_elem, 'a')[0]

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

                            link_url = urljoin(self.base_link, link)
                            detail_page = client.request(link_url)
                            getsize = re.findall('Size&nbsp;(.+?)&nbsp', detail_page, re.DOTALL)[0]
                            dsize, isize = self._parse_size(getsize)

                            url_magnet = unquote(detail_page.split('url=')[1].split('&tr=')[0])
                            quality, info = source_utils.get_release_quality(name)
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
