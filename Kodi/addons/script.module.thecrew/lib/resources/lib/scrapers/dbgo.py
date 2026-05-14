# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file dbgo.py (refactored with BaseScraper)
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
import base64

from .base import BaseScraper
from ..modules import client
from ..modules.crewruntime import c

from urllib.parse import quote_plus, urljoin


class source(BaseScraper):
    """
    DBGO scraper - refactored to use BaseScraper.

    Before: 51 lines
    After: ~30 lines (41% reduction)

    Only implements site-specific scraping logic in _scrape_sources().
    All common code (movie/tvshow/episode/error handling) inherited from base.
    """

    def __init__(self):
        super().__init__(
            name='dbgo',
            base_link='https://dbgo.fun',
            search_link='/video.php?id=%s',
            domains=['dbgo.fun'],
            headers={'Referer': 'https://cdn.dbgo.fun'}
        )

    def _scrape_sources(self, url, hostDict):
        """Site-specific scraping logic for DBGO"""
        sources = []

        # Parse URL data
        data = self._parse_data(url)
        if not data:
            return sources

        imdb = data.get('imdb')
        if not imdb:
            return sources

        # Build search URL
        search_url = self.search_link % quote_plus(imdb)
        search_url = urljoin(self.base_link, search_url)

        # Request page
        response = self._request(search_url)
        if not response:
            return sources

        # Extract and decode video URL
        try:
            encoded = re.findall('file:"#2(.*?)"', response)[0]
            encoded = encoded.replace('//eS95L3kv', '').replace('//ei96L3ov', '').replace('//eC94L3gv', '')
            decoded = base64.b64decode(encoded).decode('utf-8')
            video_url = decoded + '|Referer=https://cdn.dbgo.fun/'

            sources.append({
                'source': 'CDN',
                'quality': '720p',
                'language': 'en',
                'url': video_url,
                'direct': False,
                'debridonly': False
            })
        except Exception as e:
            c.log(f'[dbgo] Error extracting video URL: {e}')

        return sources
