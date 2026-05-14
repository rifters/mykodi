# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file anymovies.py (refactored with BaseScraper)
* @package script.module.thecrew
*
* Original author: Tempest
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import quote_plus, urljoin

from .base import BaseScraper
from ..modules import client
from ..modules import source_utils
from ..modules.crewruntime import c


class source(BaseScraper):
    """
    AnyMovies scraper - refactored to use BaseScraper

    Before: 115 lines
    After: ~50 lines (57% reduction)
    """

    def __init__(self):
        super().__init__(
            name='anymovies',
            base_link='https://www.downloads-anymovies.com',
            search_link='/search.php?zoom_query=%s',
            domains=['downloads-anymovies.com']
        )

    def _scrape_sources(self, url, hostDict):
        """Site-specific scraping logic"""
        sources = []

        # Parse URL data
        data = self._parse_data(url)
        if not data:
            return sources

        # Build search query
        hdlr = data['year']
        query = '%s %s' % (data['title'], data['year'])
        query = re.sub(r'(\\\|/| -|:|;|\*|\?|"|\'|<|>|\|)', ' ', query)

        # Build search URL
        search_url = self.search_link % quote_plus(query)
        search_url = urljoin(self.base_link, search_url).replace('++', '+')

        # Request search page
        post = self._request(search_url)
        if not post:
            c.log('[anymovies] Blocked or empty search result')
            return sources

        # Parse search results
        try:
            links = re.compile(r'class="result_title"><a href="(.+?)">(.+?)</a></div>').findall(post) or []
            c.log(f'[anymovies] Found {len(links)} search links')

            for _url, title in links:
                if hdlr not in title:
                    continue

                # Get result page
                page = self._request(_url)
                if not page:
                    continue

                # Find outgoing links
                found = re.findall(r'<span class="text"><a href="(.+?)" target="_blank">', page) or []
                c.log(f'[anymovies] Found {len(found)} links on {_url}')

                for link in found:
                    valid, host = source_utils.is_host_valid(link, hostDict)
                    c.log(f'[anymovies] is_host_valid({link}) -> {valid}, {host}')
                    if valid:
                        c.log(f'[anymovies] Adding source {host} {link}')
                        sources.append({
                            'source': host,
                            'quality': 'HD',
                            'language': 'en',
                            'url': link,
                            'direct': False,
                            'debridonly': False
                        })
        except Exception as e:
            c.log(f'[anymovies] Error processing results: {e}')

        return sources
