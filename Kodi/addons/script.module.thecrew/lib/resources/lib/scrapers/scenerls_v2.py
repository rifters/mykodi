# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file scenerls_v2.py (V2 version - different from root scenerls.py)
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urljoin, quote_plus, urlparse

from ..modules import cleantitle, client, debrid, source_utils
from .base import BaseScraper


class source(BaseScraper):
    def __init__(self):
        super().__init__(name='scenerls_v2', language=['en'])
        self.domains = ['scene-rls.com', 'scene-rls.net']
        self.base_link = 'http://scene-rls.net'
        self.search_link = '/?s=%s&submit=Find'

    def sources(self, url, hostDict, hostprDict=None):
        sources = []
        try:
            if not url or debrid.status() is False:
                return sources

            hostDict = (hostprDict or []) + hostDict
            data = self._parse_data(url)

            title = data.get('tvshowtitle', data.get('title'))
            title_query = cleantitle.get_query(title)
            hdlr = 's%02de%02d' % (int(data['season']), int(data['episode'])) if data.get('tvshowtitle') else data['year']

            # Build search query
            if data.get('tvshowtitle'):
                query = '%s s%02de%02d' % (title_query, int(data['season']), int(data['episode']))
            else:
                query = '%s %s' % (title_query, data['year'])

            query = re.sub(r'[\\\/\-:\;\*\?"\'\<\>\|]', ' ', query)
            query_url = urljoin(self.base_link, self.search_link % quote_plus(query))

            # Search
            r = self._request(query_url)
            if not r:
                return sources

            # Parse posts
            posts = client.parseDom(r, 'div', attrs={'class': 'post'})

            items = []
            for post in posts:
                try:
                    content = client.parseDom(post, 'div', attrs={'class': 'postContent'})
                    if not content:
                        continue

                    # Extract size
                    size_match = re.findall(r'((?:\d+\,\d+\.\d+|\d+\.\d+|\d+\,\d+|\d+)\s*(?:GiB|MiB|GB|MB))',
                                          content[0], re.I)
                    size = size_match[0] if size_match else ''

                    # Extract URLs from h2
                    h2 = client.parseDom(content, 'h2')
                    urls = client.parseDom(h2, 'a', ret='href')

                    # Parse URL to get name
                    for u in urls:
                        name = u.strip('/').split('/')[-1]
                        items.append((name, u, size))

                except:
                    continue

            # Process items
            for item in items:
                try:
                    name = client.replaceHTMLCodes(item[0])

                    # Filter by title
                    t = re.sub(r'(\.|{|\[|\s)(\d{4}|S\d*E\d*|S\d*|3D)(\.|)|\]|\s|)(.+|)', '', name)
                    if cleantitle.get(t) != cleantitle.get(title):
                        continue

                    quality, info = source_utils.get_release_quality(name, item[1])

                    # Add size info
                    try:
                        dsize, isize = self._parse_size(item[2])
                        info.insert(0, isize)
                    except:
                        dsize = 0.0

                    # Process URL
                    url = item[1]

                    # Skip unwanted file types
                    if any(x in url for x in ['.rar', '.zip', '.iso']):
                        continue

                    # Extract host from URL
                    try:
                        parsed = urlparse(url.strip().lower())
                        host_match = re.findall(r'([\w]+[.][\w]+)$', parsed.netloc)
                        if not host_match:
                            continue
                        host = host_match[0]
                    except:
                        continue

                    # Validate host
                    if host not in hostDict:
                        continue

                    sources.append({
                        'source': host,
                        'quality': quality,
                        'language': 'en',
                        'url': url,
                        'info': ' | '.join(info),
                        'direct': False,
                        'debridonly': True,
                        'size': dsize,
                        'name': name
                    })

                except:
                    continue

            return sources
        except:
            return sources
