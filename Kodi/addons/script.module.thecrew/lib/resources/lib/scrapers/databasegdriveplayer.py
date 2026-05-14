# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file databasegdriveplayer.py (refactored with BaseScraper)
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re

from .base import BaseScraper
from ..modules import client
from ..modules import source_utils
from ..modules.crewruntime import c


class source(BaseScraper):
    """
    DatabaseGdrivePlayer scraper - refactored to use BaseScraper

    Before: 134 lines
    After: ~80 lines (40% reduction)
    """

    def __init__(self):
        super().__init__(
            name='databasegdriveplayer',
            base_link='https://databasegdriveplayer.co',
            search_link='/player.php',
            domains=['databasegdriveplayer.co', 'database.gdriveplayer.us', 'series.databasegdriveplayer.co']
        )

    def _scrape_sources(self, url, hostDict):
        """Site-specific scraping logic"""
        sources = []

        # Parse URL data
        data = self._parse_data(url)
        if not data:
            return sources

        imdb = data.get('imdb')
        if imdb == '0':
            return sources

        # Build URL based on content type
        if data.get('tvshowtitle'):
            # TV show episode
            season = data.get('season')
            episode = data.get('episode')
            player_url = self.base_link + f'/player.php?type=series&imdb={imdb}&season={season}&episode={episode}'
        else:
            # Movie
            player_url = self.base_link + f'/player.php?imdb={imdb}'

        # Request player page
        html = self._request(player_url)
        if not html:
            return sources

        # Parse servers
        links = self._parse_servers(html)
        if not links:
            c.log('[databasegdriveplayer] No servers found')
            return sources

        # Process links
        for link in links:
            if link.startswith('/player.php'):
                continue

            link = 'https:' + link if not link.startswith('http') else link
            link = link.replace('vidcloud.icu', 'vidembed.io').replace(
                'vidcloud9.com', 'vidembed.io').replace(
                'vidembed.cc', 'vidembed.io').replace(
                'vidnext.net', 'vidembed.me')

            # Get vidembed sources
            if 'vidembed' in link:
                for source in self._get_vidembed(link, hostDict):
                    sources.append(source)

            # Check if valid host
            valid, host = source_utils.is_host_valid(link, hostDict)
            if valid:
                link = link.split('&title=')[0]
                sources.append({
                    'source': host,
                    'quality': '720p',
                    'language': 'en',
                    'url': link,
                    'direct': False,
                    'debridonly': False
                })

        return sources

    def _parse_servers(self, html):
        """Extract server links from HTML"""
        try:
            servers = client.parseDom(html, 'ul', attrs={'class': 'list-server-items'})
            if not servers:
                return []
            return client.parseDom(servers[0], 'a', ret='href')
        except Exception:
            # Fallback: regex extraction
            try:
                return re.findall(r'href=["\'](.*?)["\']', html)
            except Exception as e:
                c.log(f'[databasegdriveplayer] Parse error: {e}')
                return []

    def _get_vidembed(self, link, hostDict):
        """Extract sources from vidembed page"""
        sources = []
        try:
            html = self._request(link)
            if not html:
                return sources

            urls = client.parseDom(html, 'li', ret='data-video')
            for url in urls:
                url = url.replace('vidcloud.icu', 'vidembed.io').replace(
                    'vidcloud9.com', 'vidembed.io').replace(
                    'vidembed.cc', 'vidembed.io').replace(
                    'vidnext.net', 'vidembed.me')

                valid, host = source_utils.is_host_valid(url, hostDict)
                if valid:
                    url = url.split('&title=')[0]
                    sources.append({
                        'source': host,
                        'quality': '720p',
                        'language': 'en',
                        'url': url,
                        'direct': False,
                        'debridonly': False
                    })
        except Exception:
            pass

        return sources
