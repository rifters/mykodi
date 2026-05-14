# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file yify.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urljoin, quote

from ..modules import cache, cleantitle, client
from .torrent_base import TorrentBaseScraper
from ..modules.crewruntime import c


class source(TorrentBaseScraper):
    def __init__(self):
        super().__init__(
            name='yify',
            domains=['yts.am', 'yts.hn', 'yts.rs', 'yts-official.mx']
        )
        self.pack_capable = False  # Movies only
        self.search_link = '/browse-movies/%s'
        self._cached_base = None

    @property
    def base_link(self):
        if not self._cached_base:
            self._cached_base = cache.get(self._get_base_url, 0, f'https://{self.domains[0]}')
        return self._cached_base

    def _scrape_torrents(self, data, hostDict):
        # YIFY is movies only
        if data.get('tvshowtitle'):
            return self._sources_list

        query = f"{data.get('title')} {data.get('year')}"
        url = self.search_link % quote(query)
        url = urljoin(self.base_link, url)
        html = client.request(url)

        try:
            results = client.parseDom(html, 'div', attrs={'class': 'row'})[2]
        except:
            return self._sources_list

        items = re.findall(r'class="browse-movie-bottom">(.+?)</div>\s</div>', results, re.DOTALL)
        if not items:
            return self._sources_list

        for entry in items:
            try:
                link, name = re.findall('<a href="(.+?)" class="browse-movie-title">(.+?)</a>', entry, re.DOTALL)[0]
                name = client.replaceHTMLCodes(name)

                if cleantitle.get(name) != cleantitle.get(data.get('title')):
                    continue

                y = entry[-4:]
                if y != data.get('year'):
                    continue

                # Fetch detail page for torrents
                response = client.request(urljoin(self.base_link, link))
                entries = client.parseDom(response, 'div', attrs={'class': 'modal-torrent'})

                for torrent in entries:
                    try:
                        link_parts, torrent_name = re.findall(
                            'href="magnet:(.+?)" class="magnet-download download-torrent magnet" title="(.+?)"',
                            torrent, re.DOTALL
                        )[0]
                        url = f'magnet:{link_parts}'
                        url = str(client.replaceHTMLCodes(url).split('&tr')[0])
                        info_hash = url.split('btih:')[1].split('&')[0] if 'btih:' in url else None

                        try:
                            size_str = re.findall(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|MB|MiB))', torrent)[-1]
                            dsize, isize = self._parse_size(size_str)
                        except:
                            dsize, isize = 0.0, ''

                        source_dict = self._build_torrent_source(torrent_name, url, 0, dsize, info_hash)
                        source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
                        self._sources_list.append(source_dict)
                    except:
                        continue
            except:
                continue

        return self._sources_list

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
