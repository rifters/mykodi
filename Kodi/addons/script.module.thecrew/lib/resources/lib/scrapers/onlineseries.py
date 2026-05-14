# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file onlineseries.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
import time
from urllib.parse import urljoin

from ..modules import cleantitle, client, debrid, dom_parser, source_utils, workers
from .base import BaseScraper


class source(BaseScraper):
    def __init__(self):
        super().__init__(name='onlineseries', language=['en'])
        self.domains = ['onlineseries.ucoz.com']
        self.base_link = 'https://onlineseries.ucoz.com'
        self.search_link = 'search/?q=%s'

    def sources(self, url, hostDict, hostprDict=None):
        try:
            self._sources = []

            if not url or debrid.status() is False:
                return self._sources

            self.hostDict = (hostprDict or []) + hostDict
            data = self._parse_data(url)

            title = data.get('tvshowtitle', data.get('title'))
            hdlr = 'S%02dE%02d' % (int(data['season']), int(data['episode'])) if data.get('tvshowtitle') else data['year']

            # Build search query
            if data.get('tvshowtitle'):
                query = '%s S%02dE%02d' % (data['tvshowtitle'], int(data['season']), int(data['episode']))
            else:
                query = '%s %s' % (data['title'], data['year'])

            query = re.sub(r'[\\\/\-:\;\*\?"\'\<\>\|]', ' ', query)
            query_url = urljoin(self.base_link, self.search_link % cleantitle.geturl(query))

            # Search
            r = self._request(query_url)
            if not r:
                return self._sources

            # Parse results
            posts = dom_parser.parse_dom(r, 'div', {'class': 'eTitle'})
            posts = [dom_parser.parse_dom(i.content, 'a', req='href') for i in posts if i]
            posts = [(i[0].attrs['href'], re.sub(r'<.+?>', '', i[0].content)) for i in posts if i]

            # Filter by title and hdlr
            posts = [(i[0], i[1]) for i in posts if (
                cleantitle.get_simple(i[1].split(hdlr)[0]) == cleantitle.get(title) and
                hdlr.lower() in i[1].lower()
            )]

            # Threaded source extraction
            threads = [workers.Thread(self._get_sources, post) for post in posts]
            [i.start() for i in threads]
            [i.join() for i in threads]

            # Wait for all threads
            alive = [x for x in threads if x.is_alive()]
            while alive:
                alive = [x for x in threads if x.is_alive()]
                time.sleep(0.1)

            return self._sources
        except:
            return []

    def _get_sources(self, url_tuple):
        """Extract sources from detail page"""
        try:
            detail = self._request(url_tuple[0])
            if not detail:
                return

            title = url_tuple[1]

            # Extract links
            links_dom = dom_parser.parse_dom(detail, 'a', req='href')
            links = [i.attrs['href'] for i in links_dom]

            # Extract size info
            info = []
            try:
                size_match = re.findall(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GiB|MiB|GB|MB))', detail)
                if size_match:
                    size_str = size_match[0]
                    div = 1 if size_str.endswith(('GB', 'GiB')) else 1024
                    size_val = float(re.sub(r'[^0-9\.\,]', '', size_str.replace(',', '.'))) / div
                    info.append('%.2f GB' % size_val)
            except:
                pass

            info_str = ' | '.join(info)

            # Process links
            for link in links:
                try:
                    if 'youtube' in link:
                        continue

                    # Skip unwanted file types
                    if any(x in link.lower() for x in ['.rar.', '.zip.', '.iso.']):
                        continue
                    if any(link.lower().endswith(x) for x in ['.rar', '.zip', '.iso']):
                        continue

                    # Skip samples, trailers, youtube
                    if any(x in link.lower() for x in ['sample', 'trailer', 'youtube']):
                        continue

                    valid, host = source_utils.is_host_valid(link, self.hostDict)
                    if not valid:
                        continue

                    # Avoid duplicates
                    if link in str(self._sources):
                        continue

                    quality, info2 = source_utils.get_release_quality(title, link)

                    self._sources.append({
                        'source': host,
                        'quality': quality,
                        'language': 'en',
                        'url': link,
                        'info': info_str,
                        'direct': False,
                        'debridonly': True
                    })

                except:
                    continue

        except:
            pass
