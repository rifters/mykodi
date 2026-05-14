# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file scenerls.py
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
from ..modules.crewruntime import c


class source(BaseScraper):
    def __init__(self):
        super().__init__(name='scenerls', language=['en'])
        self.domains = ['scenerls.com']
        self.base_link = 'https://scenerls.com/'
        self.search_link = '/?s=%s&submit=Find'

    def sources(self, url, hostDict, hostprDict=None):
        sources = []
        try:
            if not url or debrid.status() is False:
                return sources

            hostDict = (hostprDict or []) + hostDict
            data = self._parse_data(url)

            title = data.get('tvshowtitle', data.get('title'))
            year = data.get('year', '')
            season = data.get('season')
            episode = data.get('episode')

            # Build search query
            if season and episode:
                # Format season and episode with zero-padding (S01E01 format)
                query = '%s s%02de%02d' % (title, int(season), int(episode))
            else:
                query = '%s %s' % (title, year)

            query_url = urljoin(self.base_link, self.search_link % quote_plus(query))
            r = self._request(query_url)

            if not r:
                return sources

            # Parse search results
            posts = client.parseDOM(r, 'div', attrs={'class': 'post'})

            for post in posts:
                try:
                    # Extract post title and content
                    post_title = client.parseDOM(post, 'h2')
                    if not post_title:
                        continue
                    post_title = post_title[0]

                    # Filter by title match
                    if not cleantitle.get(title) in cleantitle.get(post_title):
                        continue

                    # Extract content
                    post_content = client.parseDOM(post, 'div', attrs={'class': 'postContent'})
                    if not post_content:
                        continue
                    post_content = post_content[0]

                    # Extract quality and size info
                    quality, info = source_utils.get_release_quality(post_title, post_content)

                    try:
                        size_match = re.search(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|MB|MiB))', post_content, re.I)
                        if size_match:
                            size_str = size_match.group(1)
                            dsize, isize = self._parse_size(size_str)
                            info.insert(0, isize)
                    except:
                        pass

                    # Extract links
                    links = client.parseDOM(post_content, 'a', ret='href')

                    for link in links:
                        # Skip unwanted file types
                        if any(x in link.lower() for x in ['.rar', '.zip', '.iso']):
                            continue

                        # Parse host from URL
                        try:
                            parsed = urlparse(link.strip().lower())
                            netloc = parsed.netloc

                            # Extract domain
                            host_match = re.search(r'([\w]+[.][\w]+)$', netloc)
                            if not host_match:
                                continue

                            host = host_match.group(1)
                        except:
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
                            'debridonly': False
                        })

                except Exception as e:
                    c.scraper_error(self.name, e)
                    continue

            return sources
        except Exception as e:
            c.scraper_error(self.name, e)
            return sources
