# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file allmoviesforyou.py (refactored with BaseScraper)
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
    AllMoviesForYou scraper - refactored to use BaseScraper

    Before: 126 lines
    After: ~60 lines (52% reduction)
    """

    def __init__(self):
        super().__init__(
            name='allmoviesforyou',
            base_link='https://allmovies.gg',
            search_link='/?s=%s',
            domains=['allmoviesforyou.co'],
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:88.0) Gecko/20100101 Firefox/88.0',
                'Referer': 'https://allmovies.gg'
            }
        )
        self.search_link2 = '/embed/tmdb/tv?id=%s&s=%s&e=%s'

    def _scrape_sources(self, url, hostDict):
        """Site-specific scraping logic"""
        sources = []

        # Parse URL data
        data = self._parse_data(url)
        if not data:
            return sources

        # Build search URL
        search_url = self.search_link % quote_plus(data['title'])
        search_url = urljoin(self.base_link, search_url)

        # Request search page
        r = self._request(search_url)
        if not r:
            return sources

        # Parse search results
        try:
            r = client.parseDom(r, 'article', attrs={'class': 'TPost B'})
            items = []
            for i in r:
                try:
                    found = re.findall(
                        r'<a href="(.+?)">.+?<span class="Qlty">(.+?)</span>.+?<span class="Qlty Yr">(.+?)</span>.+?<h2 class="Title">(.+?)</h2>',
                        i, re.DOTALL
                    )
                    if found:
                        items.append(found[0])
                except re.error as rex:
                    c.log(f'[allmoviesforyou] Regex error: {rex}')
                    continue
        except Exception as e:
            c.log(f'[allmoviesforyou] Error parsing search results: {e}')
            return sources

        # Process matching items
        for item in items:
            try:
                # item = (url, quality, year, title)
                if data['title'] not in item[3] or data['year'] not in item[2]:
                    continue

                # Get item page
                page = self._request(item[0])
                if not page:
                    continue

                # Find iframe
                frames = re.findall(r'<iframe src="(.+?)"', page)
                if not frames:
                    c.log(f'[allmoviesforyou] No iframe on {item[0]}')
                    continue

                iframe = frames[0].replace('#038;', '')

                # Get iframe page
                iframe_page = self._request(iframe, headers={
                    'User-Agent': self.headers.get('User-Agent'),
                    'Referer': item[0]
                })
                if not iframe_page:
                    continue

                # Extract source URLs
                urls_found = re.findall(r'src="(.+?)"', iframe_page)
                for u in urls_found:
                    valid, host = source_utils.is_host_valid(u, hostDict)
                    if valid:
                        sources.append({
                            'source': host,
                            'quality': item[1],
                            'language': 'en',
                            'url': u,
                            'direct': False,
                            'debridonly': False
                        })
            except Exception as e:
                c.log(f'[allmoviesforyou] Error processing item: {e}')
                continue

        return sources
