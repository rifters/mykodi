# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file limetorrents.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urljoin, quote

from ..modules import cleantitle, client
from .torrent_base import TorrentBaseScraper


class source(TorrentBaseScraper):
    # Disabled for 2.3.0-beta - slow (20-30s) with low success rate
    disabled = True

    def __init__(self):
        super().__init__(
            name='limetorrents',
            base_link='https://www.limetorrents.info',
            domains=['limetorrents.info']
        )
        self.tvsearch = 'https://www.limetorrents.info/search/tv/{0}/'
        self.moviesearch = 'https://www.limetorrents.info/search/movies/{0}/'

    def _scrape_torrents(self, data, hostDict):
        title = data.get('tvshowtitle', data.get('title'))
        hdlr = self._build_hdlr(data)
        query = self._build_query(data)
        query = re.sub(r'(\\\|/| -|:|;|\*|\?|"|\'|<|>|\|)', ' ', query)

        if data.get('tvshowtitle'):
            url = self.tvsearch.format(quote(query))
        else:
            url = self.moviesearch.format(quote(query))

        try:
            headers = {'User-Agent': client.agent()}
            r = client.request(url, headers=headers)
            posts = client.parseDom(r, 'table', attrs={'class': 'table2'})[0]
            posts = client.parseDom(posts, 'tr')

            for post in posts:
                try:
                    data_link = client.parseDom(post, 'a', ret='href')[1]
                    link = urljoin(self.base_link, data_link)
                    name = client.parseDom(post, 'a')[1]

                    t = name.split(hdlr)[0]
                    if cleantitle.get(re.sub(r'(\(|\))', '', t)) != cleantitle.get(title):
                        continue

                    if not self._matches_release(name, title, hdlr):
                        continue

                    try:
                        size_str = re.findall(r'((?:\d+\,\d+\.\d+|\d+\.\d+|\d+\,\d+|\d+)\s*(?:GiB|MiB|GB|MB))', post)[0]
                        dsize, isize = self._parse_size(size_str)
                    except:
                        dsize, isize = 0.0, ''

                    # Get magnet from detail page
                    detail_data = client.request(link)
                    m = re.search(r"href=[\"'](magnet:\?[^\"']+)", detail_data)
                    if not m:
                        continue
                    url_magnet = m.group(1)
                    info_hash = url_magnet.split('btih:')[1].split('&')[0] if 'btih:' in url_magnet else None

                    source_dict = self._build_torrent_source(name, url_magnet, 0, dsize, info_hash)
                    source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
                    source_dict['source'] = 'torrent'  # lowercase
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
                    search_url = self.tvsearch.format(quote(query))
                    headers = {'User-Agent': client.agent()}
                    r = client.request(search_url, headers=headers)
                    posts = client.parseDom(r, 'table', attrs={'class': 'table2'})[0]
                    posts = client.parseDom(posts, 'tr')

                    for post in posts:
                        try:
                            link = client.parseDom(post, 'a', ret='href')[1]
                            link = urljoin(self.base_link, link)
                            name = client.parseDom(post, 'a')[1]

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

                            detail_data = client.request(link)
                            url_magnet = re.search(r'''href=["'](magnet:\?[^"']+)''', detail_data).group(1)

                            quality, info = source_utils.get_release_quality(name, name)
                            info.insert(0, isize) if isize else None
                            info = ' | '.join(info)

                            source_dict = {
                                'source': 'torrent',
                                'quality': quality,
                                'language': 'en',
                                'url': url_magnet,
                                'info': info,
                                'direct': False,
                                'debridonly': True
                            }
                            source_dict.update(package_meta)
                            sources.append(source_dict)

                        except:
                            continue

                except:
                    continue

            return sources
        except:
            return sources
