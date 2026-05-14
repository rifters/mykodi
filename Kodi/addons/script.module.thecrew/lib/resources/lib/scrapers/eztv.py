# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file eztv.py
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
    # Disabled for 2.3.0-beta - slow (20-30s) with low success rate
    disabled = True

    def __init__(self):
        super().__init__(
            name='eztv',
            base_link='https://eztv.ag',
            domains=['eztv.io']
        )
        self.search_link = '/search/%s'

    def _scrape_torrents(self, data, hostDict):
        title = data.get('tvshowtitle')
        hdlr = self._build_hdlr(data)
        query = self._build_query(data)
        query = re.sub('(\\\|/| -|:|;|\*|\?|"|<|>|\|)', ' ', query)

        url = self.search_link % quote_plus(query).replace('+', '-')
        url = urljoin(self.base_link, url)
        html = client.request(url)

        try:
            results = client.parseDom(html, 'table', attrs={'class': 'forum_header_border'})
            table_html = None
            for result in results:
                if 'magnet:' in result:
                    table_html = result
                    break

            # If no table with magnets found, return empty
            if not table_html or not isinstance(table_html, str):
                return self._sources_list
        except:
            return self._sources_list

        rows = re.findall('<tr name="hover" class="forum_header_border">(.+?)</tr>', table_html, re.DOTALL)
        if not rows:
            return self._sources_list

        for entry in rows:
            try:
                columns = re.findall('<td\s.+?>(.+?)</td>', entry, re.DOTALL)
                derka = re.findall('href="magnet:(.+?)" class="magnet" title="(.+?)"', columns[2], re.DOTALL)[0]
                name = derka[1]

                # Match title
                t = name.split(hdlr)[0]
                if cleantitle.get(re.sub('(|)', '', t)) != cleantitle.get(title):
                    continue

                # Match handler
                if not self._matches_release(name, title, hdlr):
                    continue

                # Check seeders
                try:
                    seeders = int(re.findall('<font color=".+?">(.+?)</font>', columns[5], re.DOTALL)[0])
                except:
                    continue
                if not self._check_seeders(seeders, self.min_seeders):
                    continue

                # Build magnet
                url = 'magnet:%s' % str(client.replaceHTMLCodes(derka[0]).split('&tr')[0])
                info_hash = url.split('btih:')[1].split('&')[0] if 'btih:' in url else None

                # Parse size from name
                try:
                    size_str = re.findall(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|MB|MiB))', name)[-1]
                    dsize, isize = self._parse_size(size_str)
                except:
                    dsize, isize = 0.0, ''

                source_dict = self._build_torrent_source(name, url, seeders, dsize, info_hash)
                source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
                self._sources_list.append(source_dict)

            except:
                continue

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
                    search_query = query.replace(' ', '-')
                    url = self.search_link % quote_plus(search_query).replace('+', '-')
                    url = urljoin(self.base_link, url)
                    html = client.request(url)

                    results = client.parseDom(html, 'table', attrs={'class': 'forum_header_border'})
                    table_html = None
                    for result in results:
                        if 'magnet:' in result:
                            table_html = result
                            break

                    # If no table with magnets found, skip this query
                    if not table_html or not isinstance(table_html, str):
                        continue

                    rows = re.findall('<tr name="hover" class="forum_header_border">(.+?)</tr>', table_html, re.DOTALL)
                    if not rows:
                        continue

                    for entry in rows:
                        try:
                            columns = re.findall('<td\s.+?>(.+?)</td>', entry, re.DOTALL)
                            derka = re.findall('href="magnet:(.+?)" class="magnet" title="(.+?)"', columns[2], re.DOTALL)[0]
                            name = derka[1]

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
                                seeders = int(re.findall('<font color=".+?">(.+?)</font>', columns[5], re.DOTALL)[0])
                            except:
                                continue
                            if not self._check_seeders(seeders, self.min_seeders):
                                continue

                            url = 'magnet:%s' % str(client.replaceHTMLCodes(derka[0]).split('&tr')[0])
                            info_hash = url.split('btih:')[1].split('&')[0] if 'btih:' in url else None

                            try:
                                size_str = re.findall(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|MB|MiB))', name)[-1]
                                dsize, isize = self._parse_size(size_str)
                            except:
                                dsize, isize = 0.0, ''

                            source_dict = self._build_torrent_source(name, url, seeders, dsize, info_hash)
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
