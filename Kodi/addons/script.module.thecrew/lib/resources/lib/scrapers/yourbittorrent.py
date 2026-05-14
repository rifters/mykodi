# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file yourbittorrent.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urljoin, quote_plus

from ..modules import cache, cleantitle, client, workers
from .torrent_base import TorrentBaseScraper
from ..modules.crewruntime import c


class source(TorrentBaseScraper):
    def __init__(self):
        super().__init__(
            name='yourbittorrent',
            domains=['yourbittorrent.com', 'yourbittorrent2.com']
        )
        self.search_link = '?q=%s'
        self._cached_base = None

    @property
    def base_link(self):
        if not self._cached_base:
            self._cached_base = cache.get(self._get_base_url, 0, f'https://{self.domains[0]}')
        return self._cached_base

    def _scrape_torrents(self, data, hostDict):
        title = data.get('tvshowtitle', data.get('title'))
        title = title.replace('&', 'and').replace('Special Victims Unit', 'SVU')
        hdlr = self._build_hdlr(data)
        year = data.get('year')

        query = f'{title} {hdlr}'
        query = re.sub(r'[^A-Za-z0-9\s\.-]+', '', query)

        url = self.search_link % quote_plus(query)
        url = urljoin(self.base_link, url).replace('+', '-')

        try:
            result = client.request(url)
            if not result:
                return self._sources_list

            result = c.to_str(result, errors='replace')
            links = re.findall('<a href="(/torrent/.+?)"', result, re.DOTALL)

            threads = [workers.Thread(self._get_sources, link, title, hdlr, year) for link in links]
            [t.start() for t in threads]
            [t.join() for t in threads]

        except Exception as e:
            c.log(f'YourBT_scrape_error: {e}', 1)

        return self._sources_list

    def _get_sources(self, link, title, hdlr, year):
        try:
            url = urljoin(self.base_link, link)
            result = client.request(url)

            if not result:
                return

            result = c.to_str(result, errors='replace')

            # Extract info hash
            info_hash_match = re.findall(r'<kbd>(.+?)<', result, re.DOTALL)
            if not info_hash_match:
                return
            info_hash = info_hash_match[0]

            # Extract name
            name_match = re.findall(r'<h3 class="card-title">(.+?)<', result, re.DOTALL)
            if not name_match:
                return
            name = name_match[0]

            # Build magnet
            url_magnet = self._build_magnet(info_hash, name)

            # Check against already found sources
            if url_magnet in str(self._sources_list):
                return

            # Filter non-English
            if any(x in url_magnet.lower() for x in ['french', 'italian', 'spanish', 'truefrench', 'dublado', 'dubbed']):
                return

            # Match title
            title_check = name.split(hdlr)[0].replace(str(year), '').replace('(', '').replace(')', '').replace('&', 'and').replace('+', ' ')
            if cleantitle.get(title_check) not in cleantitle.get(title):
                return

            # Match handler
            if hdlr not in name:
                return

            # Extract size
            size_match = re.findall(r'<div class="col-3">File size:</div><div class="col">(.+?)<', result, re.DOTALL)
            if not size_match:
                return
            size_str = size_match[0]

            try:
                size_parsed = re.findall(r'((?:\d+\,\d+\.\d+|\d+\.\d+|\d+\,\d+|\d+)\s*(?:GiB|MiB|GB|MB))', size_str)
                if size_parsed:
                    dsize, isize = self._parse_size(size_parsed[0])
                else:
                    dsize, isize = 0.0, ''
            except:
                dsize, isize = 0.0, ''

            source_dict = self._build_torrent_source(name, url_magnet, 0, dsize, info_hash)
            source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
            source_dict['source'] = 'torrent'  # lowercase
            self._sources_list.append(source_dict)

        except Exception as e:
            c.log(f'YourBT_get_sources_error: {e}', 1)

    def _get_base_url(self, fallback):
        for domain in self.domains:
            try:
                url = f'https://{domain}'
                result = client.request(url, timeout=7)
                result = c.to_str(result, errors='ignore')
                search_n = re.findall('<title>(.+?)</title>', result, re.DOTALL)[0]
                if result and '1337x' in search_n:
                    return url
            except:
                continue
        return fallback

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

                    posts = client.parseDom(r, 'div', attrs={'class': 'row'})

                    for post in posts:
                        try:
                            name_div = client.parseDom(post, 'div', attrs={'class': 'title'})[0]
                            name = client.parseDom(name_div, 'a')[0]

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

                            url_link_div = client.parseDom(post, 'div', attrs={'class': 'title'})[0]
                            url_link = client.parseDom(url_link_div, 'a', ret='href')[0]
                            url_link = urljoin(self.base_link, url_link)
                            r2 = client.request(url_link)
                            r2 = c.to_str(r2, errors='replace')
                            url_magnet = client.parseDom(r2, 'a', ret='href', attrs={'class': 'btn-magnet'})[0]
                            url_magnet = url_magnet.split('&tr=')[0]

                            quality, info = source_utils.get_release_quality(name, name)
                            try:
                                size_str = re.findall(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|MB|MiB))', post)[0]
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
