# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file magnetdl.py
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
    def __init__(self):
        super().__init__(
            name='magnetdl',
            base_link='https://www.magnetdl.hair',
            domains=['magnetdl.hair']
        )
        self.search_link = '/{0}/{1}'

    def _scrape_torrents(self, data, hostDict):
        title = data.get('tvshowtitle', data.get('title'))
        hdlr = self._build_hdlr(data)

        query = f'{title} {hdlr.lower()}'
        query = re.sub(r'(\\\|/| -|:|;|\*|\?|"|\'|<|>|\|)', ' ', query)

        url = urljoin(self.base_link, self.search_link.format(query[0].lower(), cleantitle.geturl(query)))

        try:
            r = client.request(url)
            r = client.parseDom(r, 'tbody')[0]
            posts = client.parseDom(r, 'tr')
            posts = [i for i in posts if 'magnet:' in i]

            for post in posts:
                try:
                    post = post.replace('&nbsp;', ' ')
                    name = client.parseDom(post, 'a', ret='title')[1]

                    t = name.split(hdlr)[0]
                    if cleantitle.get(re.sub('(|)', '', t)) != cleantitle.get(title):
                        continue

                    if not self._matches_release(name, title, hdlr):
                        continue

                    links = client.parseDom(post, 'a', ret='href')
                    magnet = [i.replace('&amp;', '&') for i in links if 'magnet:' in i][0]
                    url_clean = magnet.split('&tr')[0]
                    info_hash = url_clean.split('btih:')[1].split('&')[0] if 'btih:' in url_clean else None

                    try:
                        size_str = re.findall(r'((?:\d+\,\d+\.\d+|\d+\.\d+|\d+\,\d+|\d+)\s*(?:GiB|MiB|GB|MB))', post)[0]
                        dsize, isize = self._parse_size(size_str)
                    except:
                        dsize, isize = 0.0, ''

                    source_dict = self._build_torrent_source(name, url_clean, 0, dsize, info_hash)
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

            queries = []

            if search_series:
                queries.append(f'{tvshowtitle} Complete Series')
            else:
                queries.append(f'{tvshowtitle} S{season:02d}')

            for query in queries:
                try:
                    url = urljoin(self.base_link, self.search_link.format(query[0].lower(), cleantitle.geturl(query)))
                    r = client.request(url)
                    r = client.parseDom(r, 'tbody')[0]
                    posts = client.parseDom(r, 'tr')
                    posts = [i for i in posts if 'magnet:' in i]

                    for post in posts:
                        try:
                            post = post.replace('&nbsp;', ' ')
                            name = client.parseDom(post, 'a', ret='title')[1]

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

                            links = client.parseDom(post, 'a', ret='href')
                            magnet = [i.replace('&amp;', '&') for i in links if 'magnet:' in i][0]
                            url_magnet = magnet.split('&tr')[0]

                            quality, info = source_utils.get_release_quality(name, name)
                            try:
                                size_str = re.findall(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|MB|MiB))', name)[-1]
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
