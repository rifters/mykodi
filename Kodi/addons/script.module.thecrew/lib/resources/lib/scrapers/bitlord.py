# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file bitlord.py
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
            name='bitlord',
            base_link='http://www.bitlordsearch.com',
            domains=['bitlordsearch.com']
        )
        self.search_link = '/search?q=%s'

    def _scrape_torrents(self, data, hostDict):
        title = data.get('tvshowtitle', data.get('title'))
        title = title.replace('&', 'and').replace('Special Victims Unit', 'SVU')
        hdlr = self._build_hdlr(data)

        query = f'{title} {hdlr}'
        query = re.sub('(\\\|/| -|:|;|\*|\?|"|\'|<|>|\|)', '', query)

        url = self.search_link % quote_plus(query)
        url = urljoin(self.base_link, url)

        try:
            r = client.request(url)
            links = zip(
                client.parseDom(r, 'a', attrs={'class': 'btn btn-default magnet-button stats-action banner-button'}, ret='href'),
                client.parseDom(r, 'td', attrs={'class': 'size'})
            )

            for magnet_link, size in links:
                try:
                    url_str = magnet_link.replace('&amp;', '&')
                    url_str = re.sub(r'(&tr=.+)&dn=', '&dn=', url_str)
                    url_str = url_str.split('&tr=')[0]

                    if 'magnet' not in url_str:
                        continue

                    # Filter non-English
                    if any(x in url_str.lower() for x in ['french', 'italian', 'spanish', 'truefrench', 'dublado', 'dubbed']):
                        continue

                    name = url_str.split('&dn=')[1] if '&dn=' in url_str else ''
                    if not name:
                        continue

                    t = name.split(hdlr)[0].replace(data.get('year', ''), '').replace('(', '').replace(')', '').replace('&', 'and')
                    if cleantitle.get(t) != cleantitle.get(title):
                        continue

                    # Parse size (size is in bytes)
                    size_bytes = int(size)
                    dsize, isize = self._parse_size_bytes(size_bytes)

                    # Size filter (< 5.12 GB seems too small)
                    if dsize < 5.12:
                        continue

                    info_hash = url_str.split('btih:')[1].split('&')[0] if 'btih:' in url_str else None
                    source_dict = self._build_torrent_source(name, url_str, 0, dsize, info_hash)
                    source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
                    source_dict['source'] = 'torrent'  # lowercase for consistency with original
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
                    posts = client.parseDom(r, 'div', attrs={'class': 'row'})

                    for post in posts:
                        try:
                            name = client.parseDom(post, 'a', ret='title')[0]

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

                            url_link = client.parseDom(post, 'a', ret='href')[0]
                            url_link = urljoin(self.base_link, url_link)
                            r2 = client.request(url_link)
                            u = client.parseDom(r2, 'a', ret='href')
                            url_magnet = [i for i in u if i.startswith('magnet:')][0]
                            url_magnet = url_magnet.split('&tr=')[0]

                            quality, info = source_utils.get_release_quality(name, name)
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
