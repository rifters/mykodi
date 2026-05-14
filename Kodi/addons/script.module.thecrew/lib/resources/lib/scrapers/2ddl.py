# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file 2ddl.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urljoin, quote_plus

from ..modules import cleantitle, client, debrid, dom_parser, source_utils
from .base import BaseScraper


class source(BaseScraper):
    def __init__(self):
        super().__init__(name='2ddl', language=['en'])
        self.domains = ['onceddl.net', '2ddl.ms']
        self.base_link = 'https://2ddl.ms'
        self.search_link = '/?q=%s'

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

            query = re.sub(r'[\\\/\-:\.\;\*\?"\'\<\>\|]', ' ', query)
            query_url = urljoin(self.base_link, self.search_link % quote_plus(query))
            query_url = query_url.replace('%3A+', '-').replace('+', '-').replace('--', '-').lower()

            # Search
            r = self._request(query_url)
            if not r:
                return sources

            # Parse results
            r_titles = client.parseDom(r, 'h2', attrs={'class': 'title'})
            results = []

            for item in r_titles:
                try:
                    matches = re.findall(r'<a class=""\s*href="([^"]*)"\s*title="([^"]*)', item, re.DOTALL)
                    if matches:
                        results.append(matches[0])
                except:
                    continue

            # Filter results by title and hdlr
            valid_items = []
            for item in results:
                try:
                    t = item[1]
                    t1 = re.sub(r'(\.|{|\[|\s)(\d{4}|S\d*E\d*|S\d+|3D)(\.|)|\]|\s|)(.+|)', '', t)

                    if cleantitle.get(t1) != cleantitle.get(title):
                        continue

                    y = re.findall(r'[\.|\(|\[|\s](\d{4}|S\d*E\d*|S\d*)[\.\)|\]|\s]', t)
                    if y and y[-1].upper() != hdlr:
                        continue

                    # Get detail page
                    detail = self._request(item[0])
                    if not detail:
                        continue

                    # Extract links
                    links = re.findall(r'<a href="([^"]*)', detail)
                    valid_items.extend([(t, link) for link in links])

                except:
                    continue

            # Process links
            for item in valid_items:
                try:
                    name = item[0]
                    url = item[1]

                    # Skip unwanted file types and sites
                    if any(x in url for x in ['.rar', '.zip', '.iso', 'www.share-online.biz',
                                              'https://ouo.io', 'http://guard.link']):
                        continue

                    valid, host = source_utils.is_host_valid(url, hostDict)
                    if not valid:
                        continue

                    quality, info = source_utils.get_release_quality(name, url)

                    sources.append({
                        'source': host,
                        'quality': quality,
                        'language': 'en',
                        'url': url,
                        'info': ' | '.join(info),
                        'direct': False,
                        'debridonly': True
                    })

                except:
                    continue

            return sources
        except:
            return sources
