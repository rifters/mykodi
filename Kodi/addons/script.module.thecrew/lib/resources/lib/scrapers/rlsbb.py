# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file rlsbb.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urljoin

from ..modules import cleantitle, client, debrid, source_utils

try:
    from ..modules import cfscrape
except ImportError:
    cfscrape = None
from .base import BaseScraper
from ..modules.crewruntime import c


class source(BaseScraper):
    def __init__(self):
        super().__init__(name='rlsbb', language=['en'])
        self.domains = ['rlsbb.in', 'old3.rlsbb.in']
        self.base_link = 'https://rlsbb.in/'
        self.old_base_link = 'http://old3.rlsbb.in/'

    def sources(self, url, hostDict, hostprDict=None):
        sources = []
        try:
            if not url or debrid.status() is False:
                return sources

            hostDict = (hostprDict or []) + hostDict
            data = self._parse_data(url)

            title = data.get('tvshowtitle', data.get('title'))
            year = str(data.get('year', ''))
            season = data.get('season')
            episode = data.get('episode')

            # Select base link based on year
            if year and int(year) >= 2021:
                base_url = self.base_link
            else:
                base_url = self.old_base_link

            # Build query
            query = cleantitle.geturl(title)

            # Sanitize query
            query = re.sub(r'[\\\\]', '', query)
            query = re.sub(r'[&#,+]', '-', query)
            query = re.sub(r'--+', '-', query).strip('-')

            # Build URL based on content type
            if season and episode:
                # Format season and episode with zero-padding (S01E01 format)
                query_url = urljoin(base_url, '%s-%s-s%02de%02d/' % (query, year, int(season), int(episode)))
            else:
                query_url = urljoin(base_url, '%s-%s/' % (query, year))

            # Use cfscrape
            try:
                scraper = cfscrape.create_scraper()
                r = scraper.get(query_url)

                if r.status_code in [503, 403]:
                    return sources

                r = r.content.decode('utf-8')
            except:
                return sources

            # Check for Cloudflare protection
            if any(x in r for x in ['Just a moment', 'cloudflare', 'Enable JavaScript']):
                return sources

            # Parse posts
            posts = client.parseDOM(r, 'div', attrs={'class': 'content'})
            if not posts:
                return sources

            seen_urls = set()

            for post in posts:
                try:
                    # Extract links
                    links = client.parseDOM(post, 'a', ret='href')

                    for link in links:
                        # Skip duplicates
                        if link in seen_urls:
                            continue

                        # Skip unwanted file types
                        if any(x in link.lower() for x in ['.rar', '.zip', '.iso', '.idx', '.sub', '.srt']):
                            continue

                        valid, host = source_utils.is_host_valid(link, hostDict)
                        if not valid:
                            continue

                        seen_urls.add(link)

                        # Extract quality and info
                        quality, info = source_utils.get_release_quality(post, link)

                        # Try to extract size from post
                        try:
                            size_match = re.search(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|MB|MiB))', post, re.I)
                            if size_match:
                                size_str = size_match.group(1)
                                dsize, isize = self._parse_size(size_str)
                                info.insert(0, isize)
                        except:
                            pass

                        sources.append({
                            'source': host,
                            'quality': quality,
                            'language': 'en',
                            'url': link,
                            'info': ' | '.join(info),
                            'direct': False,
                            'debridonly': False
                        })

                except:
                    continue

            return sources
        except:
            return sources
