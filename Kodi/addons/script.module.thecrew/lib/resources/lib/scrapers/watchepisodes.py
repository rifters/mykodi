# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file watchepisodes.py (refactored with BaseScraper)
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re

from .base import BaseScraper
from ..modules import cleantitle, client, source_utils
from ..modules.crewruntime import c


class source(BaseScraper):
    """
    WatchEpisodes scraper - refactored to use BaseScraper

    Before: 74 lines
    After: ~45 lines (39% reduction)

    Note: TV shows only
    """

    def __init__(self):
        super().__init__(
            name='watchepisodes',
            base_link='https://www.watchepisodes4.com/',
            search_link='',  # Uses tvshow() to build URL
            domains=['watchepisodes4.com']
        )

    def tvshow(self, imdb, tvdb, tvshowtitle, localtvshowtitle, aliases, year):
        """Build TV show URL from title"""
        try:
            clean_title = cleantitle.geturl(tvshowtitle)
            url = self.base_link + clean_title
            return url
        except Exception:
            return None

    def episode(self, url, imdb, tvdb, title, premiered, season, episode):
        """Find episode URL from TV show page"""
        try:
            if not url:
                return None

            r = client.request(url)
            pattern = f'<a title=".+? Season {season} Episode {episode} .+?" href="(.+?)">'
            matches = re.compile(pattern).findall(r)

            for episode_url in matches:
                return episode_url
        except Exception:
            return None

    def _scrape_sources(self, url, hostDict):
        """Site-specific scraping logic"""
        sources = []

        # Parse URL - for watchepisodes, url is the episode page URL (not encoded data)
        data = self._parse_data(url)
        if data:
            # If it's encoded data, we can't use it (watchepisodes needs direct URL)
            return sources

        # URL is the direct episode page
        try:
            r = client.request(url)
            if not r:
                return sources

            # Extract source URLs
            matches = re.compile(r'class="watch-button" data-actuallink="(.+?)"').findall(r)

            for source_url in matches:
                if source_url in str(sources):
                    continue

                quality, info = source_utils.get_release_quality(source_url, source_url)
                valid, host = source_utils.is_host_valid(source_url, hostDict)

                if valid:
                    sources.append({
                        'source': host,
                        'quality': quality,
                        'language': 'en',
                        'url': source_url,
                        'direct': False,
                        'debridonly': False
                    })
        except Exception as e:
            c.scraper_error(e, exc_info=e)

        return sources
