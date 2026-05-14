# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file tordl.py
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
from ..modules.crewruntime import c


class source(TorrentBaseScraper):
    def __init__(self):
        super().__init__(
            name='tordl',
            base_link='https://www.torrentdownload.info',
            domains=['btdig.com']
        )
        self.search_link = '/search?q=%s'

    def _scrape_torrents(self, data, hostDict):
        query = self._build_query(data).lower()
        query = re.sub(r'(\\\|/| -|:|;|\*|\?|"|\'|<|>|\|)', ' ', query)

        url = urljoin(self.base_link, self.search_link % quote_plus(query))

        try:
            r = client.request(url)
            r = c.to_str(r, errors='replace').strip()

            posts = client.parseDom(r, 'table', attrs={'class': 'table2', 'cellspacing': '0'})
            posts = client.parseDom(posts, 'tr')[1:]

            for post in posts:
                try:
                    if 'php' in post or '/feed' in post:
                        continue

                    links = client.parseDom(post, 'a', ret='href')[0]
                    links = client.replaceHTMLCodes(links).lstrip('/')

                    parts = links.split('/')
                    if len(parts) < 2:
                        continue

                    hash_val = parts[0]
                    name = parts[1]

                    if len(hash_val) != 40:
                        continue

                    if query not in str(cleantitle.get_title(name)):
                        continue

                    url_magnet = self._build_magnet(hash_val, name)

                    try:
                        size_td = client.parseDom(post, 'td', attrs={'class': 'tdnormal'})[1]
                        dsize, isize = self._parse_size(size_td)
                    except:
                        dsize, isize = 0.0, ''

                    source_dict = self._build_torrent_source(name, url_magnet, 0, dsize, hash_val)
                    source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
                    source_dict['name'] = name
                    self._sources_list.append(source_dict)

                except Exception as e:
                    c.scraper_error(f'Scrape error: {e}', exc_info=e)
                    continue

        except Exception as e:
            c.scraper_error(e, exc_info=e)

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
                    r = c.to_str(r, errors='replace')

                    posts = client.parseDom(r, 'div', attrs={'class': 'grey_bar3'})

                    for post in posts:
                        try:
                            data_elem = client.parseDom(post, 'p', attrs={'class': 'tt-name'})[0]
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

                            url_link = client.parseDom(data_elem, 'a', ret='href')[0]
                            url_link = urljoin(self.base_link, url_link)
                            r2 = client.request(url_link)
                            r2 = c.to_str(r2, errors='replace')
                            url_magnet = re.findall('href=["\']?(magnet:.+?)["\']?>', r2)[0]
                            url_magnet = url_magnet.split('&tr=')[0]

                            quality, info = source_utils.get_release_quality(name, name)
                            try:
                                size_str = re.findall(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|MB|MiB))', post)[0]
                                dsize, isize = self._parse_size(size_str)
                                info.insert(0, isize) if isize else None
                            except:
                                dsize = 0.0
                            info = ' | '.join(info)

                            source_dict = {'source': 'Torrent', 'quality': quality, 'language': 'en',
                                         'url': url_magnet, 'info': info, 'direct': False, 'debridonly': True,
                                         'size': dsize, 'name': name}
                            source_dict.update(package_meta)
                            sources.append(source_dict)
                        except:
                            continue
                except:
                    continue
            return sources
        except:
            return sources
