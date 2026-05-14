# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file maxrls.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urljoin, quote_plus

from ..modules import client, debrid, source_utils
from .base import BaseScraper


class source(BaseScraper):
    def __init__(self):
        super().__init__(name='maxrls', language=['en'])
        self.domains = ['max-rls.com']
        self.base_link = 'http://max-rls.com'
        self.search_link = '/?s=%s&submit=Find'

    def sources(self, url, hostDict, hostprDict=None):
        sources = []
        try:
            if not url or debrid.status() is False:
                return sources

            hostDict = (hostprDict or []) + hostDict
            data = self._parse_data(url)

            title = data.get('tvshowtitle', data.get('title'))
            hdlr = 'S%02dE%02d' % (int(data['season']), int(data['episode'])) if data.get('tvshowtitle') else data['year']

            # Build search query
            if data.get('tvshowtitle'):
                query = '%s S%02dE%02d' % (data['tvshowtitle'], int(data['season']), int(data['episode']))
            else:
                query = '%s %s' % (data['title'], data['year'])

            query_url = urljoin(self.base_link, self.search_link % quote_plus(query))
            query_url = query_url.replace('%3A+', '+')

            # Search (try multiple times)
            r = self._request(query_url)

            items = []
            for loop_count in range(2):
                if loop_count == 1 or (r is None and data.get('tvshowtitle')):
                    r = self._request(query_url)

                if r:
                    posts = client.parseDom(r, 'h2', attrs={'class': 'postTitle'})

                    for post in posts:
                        try:
                            post_urls = client.parseDom(post, 'a', ret='href')
                            items.extend(post_urls)
                        except:
                            continue

                if items:
                    break

            # Extract sources from detail pages
            for item_url in items:
                try:
                    detail = self._request(item_url)
                    if not detail:
                        continue

                    content = client.parseDom(detail, 'div', attrs={'class': 'postContent'})

                    for content_block in content:
                        links = client.parseDom(content_block, 'a', ret='href')

                        for link in links:
                            quality, info = source_utils.get_release_quality(link)

                            # Skip SD quality
                            if 'SD' in quality:
                                continue

                            valid, host = source_utils.is_host_valid(link, hostDict)
                            if not valid:
                                continue

                            sources.append({
                                'source': host,
                                'quality': quality,
                                'language': 'en',
                                'url': link,
                                'info': ' | '.join(info),
                                'direct': False,
                                'debridonly': True
                            })

                except:
                    continue

            return sources
        except:
            return sources
