# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file torrentquest.py
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
            name='torrentquest',
            base_link='https://torrentquest.com',
            domains=['torrentquest.com']
        )
        self.search_link = '/%s/%s'

    def _scrape_torrents(self, data, hostDict):
        title = data.get('tvshowtitle', data.get('title'))
        stype = 'TV' if data.get('tvshowtitle') else 'Movie'
        hdlr = self._build_hdlr(data)
        query = self._build_query(data)
        query = re.sub(r'(\\\|/| -|:|;|\*|\?|"|<|>|\|)', ' ', query)

        url = urljoin(self.base_link, self.search_link % (query[0].lower(), cleantitle.geturl(query)))
        html = client.request(url)

        if not html:
            return self._sources_list

        html = html.replace('&nbsp;', ' ')

        try:
            results = client.parseDom(html, 'tbody')[0]
        except:
            return self._sources_list

        rows = re.findall('<tr>(.+?)</tr>', results, re.DOTALL)
        if not rows:
            return self._sources_list

        for entry in rows:
            try:
                # Verify type
                try:
                    if stype == 'TV':
                        verify = re.findall('<td class="t5">(.+?)</td>', entry, re.DOTALL)[0]
                    else:
                        verify = re.findall('<td class="t2">(.+?)</td>', entry, re.DOTALL)[0]
                except:
                    continue

                # Get name
                try:
                    name = re.findall('<td class="n">(.+?)</td>', entry, re.DOTALL)[0]
                    name = re.findall('title="(.+?)"', name, re.DOTALL)[0]
                    name = client.replaceHTMLCodes(name)

                    if cleantitle.get(title) not in cleantitle.get(name):
                        continue
                except:
                    continue

                if not self._matches_release(name, title, hdlr):
                    continue

                # Get seeders
                try:
                    seeders = int(re.findall('<td class="s">(.+?)</td>', entry, re.DOTALL)[0])
                except:
                    continue

                if not self._check_seeders(seeders, self.min_seeders):
                    continue

                # Get magnet link
                try:
                    link = 'magnet:%s' % re.findall('href="magnet:(.+?)"', entry, re.DOTALL)[0]
                    link = str(client.replaceHTMLCodes(link).split('&tr')[0])
                except:
                    continue

                # Parse size
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
                    url = self.search_link % (query[0].lower(), cleantitle.geturl(query))
                    url = urljoin(self.base_link, url)
                    r = client.request(url)

                    posts = client.parseDom(r, 'div', attrs={'class': 'one_result'})

                    for post in posts:
                        try:
                            name = client.parseDom(post, 'a')[0]

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

                            try:
                                seeders = int(re.findall('<span class="seeds">(.+?)</span>', post)[0])
                            except:
                                continue
                            if not self._check_seeders(seeders, self.min_seeders):
                                continue

                            link_url = client.parseDom(post, 'a', ret='href')[0]
                            link_url = urljoin(self.base_link, link_url)
                            r2 = client.request(link_url)
                            link = re.findall('"(magnet:.+?)"', r2)[0]
                            link = link.split('&tr=')[0]

                            quality, info = source_utils.get_release_quality(name, name)
                            try:
                                size_str = re.findall(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|MB|MiB))', post)[0]
                                dsize, isize = self._parse_size(size_str)
                                info.insert(0, isize) if isize else None
                            except:
                                pass
                            info = ' | '.join(info)

                            source_dict = {'source': 'Torrent', 'quality': quality, 'language': 'en',
                                         'url': link, 'info': info, 'direct': False, 'debridonly': True}
                            source_dict.update(package_meta)
                            sources.append(source_dict)
                        except:
                            continue
                except:
                    continue

            return sources
        except:
            return sources
