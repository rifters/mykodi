# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file torrent_base.py
* @package script.module.thecrew
*
* Base scraper class for torrent scrapers. Extends BaseScraper with
* torrent-specific functionality like magnet link handling, size parsing,
* seeders checking, and pack support.
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
import traceback
from urllib.parse import quote_plus

from .base import BaseScraper
from ..modules import cleantitle, debrid, source_utils, control
from ..modules.crewruntime import c


class TorrentBaseScraper(BaseScraper):
    """
    Base class for torrent scrapers. Provides common torrent functionality:
    - Pack capability support
    - Seeders checking
    - Magnet link building
    - Size parsing (GB/MB)
    - Quality detection
    - Debrid requirement checking

    Subclasses only need to implement _scrape_torrents() with site-specific logic.
    """

    pack_capable = True

    def __init__(self, name=None, base_link=None, search_link=None, **kwargs):
        """
        Initialize torrent scraper.

        Args:
            name: Scraper name (e.g., '1337x') - can be set later by subclass
            base_link: Base URL (e.g., 'https://1337x.to') - can be set later
            search_link: Search URL pattern - can be set later
            **kwargs: Optional settings:
                - min_seeders: Minimum seeders required (default: from settings or 0)
                - pack_capable: Whether scraper supports packs (default: True)
                - All BaseScraper kwargs
        """
        super().__init__(name, base_link, search_link, **kwargs)

        # Pack support
        self.pack_capable = kwargs.get('pack_capable', True)

        # Min seeders from settings or kwargs
        try:
            self.min_seeders = int(control.setting('torrent.min.seeders') or 0)
        except Exception:
            self.min_seeders = kwargs.get('min_seeders', 0)

    def _scrape_sources(self, data, hostDict):
        """
        Torrent-specific sources method.
        Calls _scrape_torrents() directly with data dict (no URL parsing overhead).

        Note: We don't check debrid status here - torrents are still returned
        and marked as debridonly. The debrid check happens at playtime.
        """
        try:
            c.log(f'[{self.name}] TorrentBaseScraper._scrape_sources() CALLED')
            c.log(f'[{self.name}] Data: title={data.get("title")}, year={data.get("year")}, imdb={data.get("imdb")}')

            # Call site-specific torrent scraping directly with data dict
            results = self._scrape_torrents(data, hostDict)
            c.log(f'[{self.name}] _scrape_torrents returned {len(results) if results else 0} sources')
            return results if results else []

        except Exception as e:
            c.scraper_error(e, scraper=self.name, exc_info=e)
            return []

    def _scrape_torrents(self, data, hostDict):
        """
        Site-specific torrent scraping - MUST be implemented by subclass.

        Args:
            data: Dictionary with title, year, season, episode, imdb, etc.
            hostDict: Host dictionary (usually ignored for torrents)

        Returns:
            List of torrent source dictionaries with keys:
                - source: 'torrent' or provider name
                - quality: Quality string
                - language: 'en'
                - url: Magnet link
                - info: Info string (size, codec, etc.)
                - direct: False
                - debridonly: True
                - hash: Info hash (optional)
                - seeders: Seeder count (optional)
                - size: Size in GB (optional)
        """
        raise NotImplementedError(f'{self.name} must implement _scrape_torrents()')

    def sources_packs(self, data, hostDict, search_series=False, total_seasons=0, bypass_filter=0):
        """
        Search for pack releases (season packs or complete series).
        Override this method if scraper has custom pack search logic.

        Args:
            data: TV show data dict
            hostDict: Host dictionary
            search_series: True for complete series, False for season pack
            total_seasons: Total number of seasons
            bypass_filter: Bypass filter flag

        Returns:
            List of pack sources
        """
        # Default implementation - subclasses should override
        return []

    # Helper methods for torrent scrapers

    def _build_magnet(self, info_hash, name=None):
        """
        Build magnet link from info hash.

        Args:
            info_hash: Torrent info hash
            name: Optional torrent name for &dn= parameter

        Returns:
            Magnet link string
        """
        try:
            magnet = f'magnet:?xt=urn:btih:{info_hash}'
            if name:
                magnet += f'&dn={quote_plus(name)}'
            return magnet
        except Exception as e:
            c.scraper_error(f'Error building magnet: {e}', scraper=self.name)
            return None

    def _parse_size(self, size_str):
        """
        Parse size string like '1.23 GB' or '700 MB' to float GB and formatted string.

        Args:
            size_str: Size string (e.g., '1.23 GB', '700 MB', '1.23 GiB')

        Returns:
            Tuple of (size_gb_float, formatted_string)
            Example: (1.23, '1.23 GB') or (0.68, '700.00 MB')
        """
        try:
            if not size_str:
                return 0.0, ''

            # Normalize: GiB->GB, MiB->MB
            s = size_str.upper().replace('GIB', 'GB').replace('MIB', 'MB')
            s = s.replace(',', '')  # Remove thousand separators

            # Match number and unit
            m = re.match(r'([0-9]+(?:\.[0-9]+)?)\s*(GB|MB)', s)
            if not m:
                return 0.0, ''

            val = float(m[1])
            unit = m[2]

            # Convert to GB
            size_gb = val if unit == 'GB' else val / 1024.0

            # Format display string
            if unit == 'GB':
                display = f'{val:.2f} GB'
            else:
                display = f'{val:.2f} MB'

            return size_gb, display

        except Exception as e:
            c.scraper_error(f'Error parsing size "{size_str}": {e}', scraper=self.name)
            return 0.0, ''

    def _parse_size_bytes(self, size_bytes):
        """
        Parse size in bytes to GB float and formatted string.

        Args:
            size_bytes: Size in bytes (int or string)

        Returns:
            Tuple of (size_gb_float, formatted_string)
        """
        try:
            size_bytes = int(size_bytes)
            if size_bytes == 0:
                return 0.0, '0.00 GB'

            size_gb = float(size_bytes) / 1024 / 1024 / 1024
            display = f'{size_gb:.2f} GB'
            return size_gb, display

        except Exception as e:
            c.log(f'[{self.name}] Error parsing size bytes "{size_bytes}": {e}')
            return 0.0, ''

    def _check_seeders(self, seeders, min_seeders=None):
        """
        Check if seeders meet minimum requirement.

        Args:
            seeders: Seeder count (int or string)
            min_seeders: Minimum required (uses self.min_seeders if None)

        Returns:
            True if seeders >= min_seeders, False otherwise
        """
        try:
            seeders = int(seeders)
            min_req = min_seeders if min_seeders is not None else self.min_seeders
            return seeders >= min_req
        except Exception:
            return False

    def _build_query(self, data):
        """
        Build search query from data dict.

        Args:
            data: Data dict with title, year, season, episode, tvshowtitle

        Returns:
            Cleaned query string ready for URL encoding
        """
        try:
            title = data.get('tvshowtitle') or data.get('title')
            title = cleantitle.get_query(title)

            # Build query based on content type
            if data.get('tvshowtitle'):
                # TV show: "Title S01E01"
                season = int(data.get('season', 0))
                episode = int(data.get('episode', 0))
                query = f'{title} S{season:02d}E{episode:02d}'
            else:
                # Movie: "Title 2020"
                year = data.get('year')
                query = f'{title} {year}'

            # Clean query
            query = re.sub(r'(\\\|/| -|:|;|\*|\?|"|\'|<|>|\|)', ' ', query)
            return query

        except Exception as e:
            c.log(f'[{self.name}] Error building query: {e}')
            return ''

    def _build_hdlr(self, data):
        """
        Build handler string for matching (e.g., 'S01E01' or '2020').

        Args:
            data: Data dict with year, season, episode, tvshowtitle

        Returns:
            Handler string
        """
        try:
            if data.get('tvshowtitle'):
                season = int(data.get('season', 0))
                episode = int(data.get('episode', 0))
                return f'S{season:02d}E{episode:02d}'
            else:
                return str(data.get('year'))
        except Exception:
            return ''

    def _matches_release(self, release_name, title, hdlr):
        """
        Check if release name matches title and handler.

        Args:
            release_name: Release name to check
            title: Expected title
            hdlr: Handler string (e.g., 'S01E01' or '2020')

        Returns:
            True if matches, False otherwise
        """
        try:
            # Clean names for comparison
            clean_release = cleantitle.get(release_name)
            clean_title = cleantitle.get(title)

            # Check title match
            if clean_title not in clean_release:
                return False

            # Check year/episode match
            y = re.findall(r'[\.|\(|\[|\s](\d{4}|S\d*E\d*|S\d*)[\.|\)|\]|\s]', release_name.upper())
            if y:
                y = y[-1].upper()
                if y != hdlr.upper():
                    return False

            return True

        except Exception as e:
            c.log(f'[{self.name}] Error matching release: {e}')
            return False

    def _build_torrent_source(self, name, url, seeders=0, size=None, info_hash=None, season=None, episode=None):
        """
        Build torrent source dictionary with standard fields.

        Args:
            name: Release name
            url: Magnet link or torrent URL
            seeders: Seeder count (default: 0)
            size: Size in GB or size string (optional)
            info_hash: Info hash (optional)
            season: Season number (for episodes, helps with pack file selection)
            episode: Episode number (for episodes, helps with pack file selection)

        Returns:
            Source dictionary
        """
        try:
            # Get quality and info from release name
            quality, info = source_utils.get_release_quality(name, url)

            # Add size to info if provided
            if size:
                if isinstance(size, str):
                    # Parse size string
                    _, size_str = self._parse_size(size)
                elif isinstance(size, (int, float)):
                    # Use numeric size
                    size_str = f'{float(size):.2f} GB'
                else:
                    size_str = str(size)

                if size_str:
                    info.insert(0, size_str)

            # Join info
            info_str = ' | '.join(info) if info else ''

            # Build source dict
            source = {
                'provider': self.name,
                'source': 'torrent',
                'quality': quality,
                'language': 'en',
                'url': url,
                'info': info_str,
                'direct': False,
                'debridonly': True,
                'name': name
            }

            # Add optional fields
            if seeders:
                source['seeders'] = int(seeders)
            if info_hash:
                source['hash'] = info_hash
            if size and isinstance(size, (int, float)):
                source['size'] = float(size)

            # Add season/episode for pack file selection
            if season is not None:
                source['season'] = season
            if episode is not None:
                source['episode'] = episode

            return source

        except Exception as e:
            c.log(f'[{self.name}] Error building source: {e}')
            return None
