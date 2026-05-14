# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file base.py
* @package script.module.thecrew
*
* Base scraper class providing common functionality for all scrapers.
* Individual scrapers inherit from BaseScraper and only need to implement
* site-specific scraping logic in _scrape_sources().
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urlencode, quote_plus, parse_qs, urljoin

from ..modules import client
from ..modules import source_utils
from ..modules.crewruntime import c


class BaseScraper:
    """
    Base class for all scrapers. Provides common functionality:
    - Standard initialization (priority, language, domains, headers)
    - Common methods (movie, tvshow, episode, resolve)
    - Error handling wrapper for sources()
    - Helper methods for HTTP requests

    Subclasses only need to implement _scrape_sources() with site-specific logic.
    """

    def __init__(self, name=None, base_link=None, search_link=None, **kwargs):
        """
        Initialize base scraper.

        Args:
            name: Scraper name (e.g., 'allmoviesforyou') - can be set later by subclass
            base_link: Base URL of the site (e.g., 'https://allmovies.gg') - can be set later
            search_link: Search URL pattern (e.g., '/?s=%s') - can be set later
            **kwargs: Optional settings:
                - priority: Scraper priority (default: 1)
                - language: Language list (default: ['en'])
                - domains: Domain list (default: [])
                - headers: HTTP headers dict (default: {'User-Agent': client.agent()})
                - defunct: Whether site is permanently closed (default: False)
        """
        # Allow subclasses to set these after calling super().__init__()
        if name is not None:
            self.name = name
        if base_link is not None:
            self.base_link = base_link
        if search_link is not None:
            self.search_link = search_link

        self.priority = kwargs.get('priority', 1)
        self.language = kwargs.get('language', ['en'])
        self.domains = kwargs.get('domains', [])

        # Default headers with User-Agent
        default_headers = {'User-Agent': client.agent()}
        self.headers = kwargs.get('headers', default_headers)

        # Defunct flag for permanently closed sites
        self.defunct = kwargs.get('defunct', False)

        # Sources list for scrapers to append to - renamed to avoid shadowing sources() method
        self._sources_list = []

    # movie()/tvshow()/episode() methods REMOVED for speed optimization
    # Scrapers now accept data dict directly in sources() - no URL encoding overhead

    def sources(self, data, hostDict=None, hostprDict=None):
        """
        Main sources method with standard error handling.
        Accepts data dict directly (no URL encoding overhead).
        Calls _scrape_sources() which must be implemented by subclass.

        Args:
            data: Dictionary with media info (imdb, title, year, season, episode, etc.)
            hostDict: Dictionary of valid hosts (optional - defaults to empty dict)
            hostprDict: Dictionary of prioritized hosts (optional)

        Returns:
            List of source dictionaries with keys:
                - source: Host name
                - quality: Quality (e.g., 'HD', '720p', '1080p')
                - language: Language code (e.g., 'en')
                - url: Source URL
                - direct: Whether this is a direct link (bool)
                - debridonly: Whether this requires debrid (bool)
        """
        try:
            c.log(f'[{self.name}] BaseScraper.sources() CALLED with data')

            if not data:
                c.log(f'[{self.name}] ERROR: data is None or empty')
                return []

            # Reset sources list for this search
            self._sources_list = []

            # Default to empty dict if not provided
            if hostDict is None:
                hostDict = {}
            if hostprDict is None:
                hostprDict = []

            # Merge prioritized hosts with regular hosts if provided
            if hostprDict:
                hostDict = dict(list(hostprDict.items()) + list(hostDict.items())) if isinstance(hostprDict, dict) else hostDict

            # Call site-specific scraping method
            c.log(f'[{self.name}] Calling _scrape_sources() with title={data.get("title", "unknown")}, year={data.get("year", "unknown")}')
            result = self._scrape_sources(data, hostDict)
            c.log(f'[{self.name}] _scrape_sources returned {len(result) if result else 0} sources')
            return result

        except Exception as e:
            c.scraper_error(e, scraper=self.name, exc_info=e)
            return []

    def check_title(self, title, aliases, release_name, hdlr, year, is_movie=True):
        """
        Sophisticated title/episode matching - checks aliases, year ranges, episode codes.
        Based on gears' source_utils.check_title() but adapted for crew scrapers.

        Args:
            title: Main title (string)
            aliases: List of alias titles (list of strings or None)
            release_name: The full release name from torrent/hoster (string)
            hdlr: Handler - year for movies, 'S01E02' format for episodes (string)
            year: Media year (string)
            is_movie: True for movies, False for episodes (boolean)

        Returns:
            True if release_name matches the title/episode criteria, False otherwise
        """
        try:
            from ..modules import cleantitle

            # For movies: check year +/- 1 to handle year confusion
            if is_movie:
                years = [str(int(year) - 1), str(year), str(int(year) + 1)]
                if not any(y in release_name for y in years):
                    return False
            # For episodes: check handler (S01E02 format) exists in release
            else:
                if not re.search(r'%s' % hdlr, release_name, re.I):
                    return False

            # Build list of valid titles (main + aliases)
            title_list = []
            if aliases:
                for alias in aliases:
                    try:
                        # Clean alias: remove ampersand, years
                        alias_clean = alias.replace('&', 'and').replace(year, '')
                        if is_movie:
                            for y in years:
                                alias_clean = alias_clean.replace(y, '')
                        if alias_clean and alias_clean not in title_list:
                            title_list.append(alias_clean)
                    except:
                        continue

            # Add main title if not already in list
            title_clean = title.replace('&', 'and').replace(year, '')
            if title_clean not in title_list:
                title_list.append(title_clean)

            # Extract the title portion from release_name (before quality indicators)
            # Remove parenthesis around years like (2024)
            release_title = re.sub(r'([(])(?=((19|20)[0-9]{2})).*?([)])', '\\2', release_name)

            # Split at handler to get title portion
            t = re.split(r'%s' % hdlr, release_title, 1, re.I)[0].replace(year, '').replace('&', 'and')

            # Remove years from title portion
            if is_movie:
                for y in years:
                    t = t.split(y)[0]

            # Split at quality indicators to isolate title
            t = re.split(r'2160p|216op|4k|1080p|1o8op|108op|1o80p|720p|72op|480p|48op', t, 1, re.I)[0]

            # Clean the extracted title
            cleantitle_release = cleantitle.get(t)

            # Check if any of our valid titles match the release title
            if not any(cleantitle.get(valid_title) == cleantitle_release for valid_title in title_list):
                return False

            # For episodes: reject episode ranges (S01E01-08, S01E01-E03, etc.)
            # These should be handled by pack scrapers, not single episode scrapers
            if not is_movie:
                range_patterns = [
                    r's\d{1,3}e\d{1,3}[-.]e\d{1,3}',  # S01E01-E03
                    r's\d{1,3}e\d{1,3}[-.]\d{1,3}(?!p|bit|gb)(?!\d{1,3})',  # S01E01-03
                    r's\d{1,3}[-.]e\d{1,3}[-.]e\d{1,3}',  # S01-E01-E03
                    r'season[.-]?\d{1,3}[.-]?ep[.-]?\d{1,3}[.-]ep[.-]?\d{1,3}',  # Season1Ep01Ep03
                    r'season[.-]?\d{1,3}[.-]?episode[.-]?\d{1,3}[-.]episode[.-]?\d{1,3}'  # Season1Episode01Episode03
                ]
                for pattern in range_patterns:
                    if re.search(pattern, release_name, re.I):
                        return False

            return True

        except Exception as e:
            c.scraper_error(f'check_title error: {e}', scraper='BaseScraper')
            return False

    def _scrape_sources(self, data, hostDict):
        """
        Site-specific scraping logic - MUST be implemented by subclass.

        This is the only method that contains unique scraping code for each site.
        All common error handling is in the base class.

        Args:
            data: Dictionary with media info (imdb, title, year, season, episode, etc.)
            hostDict: Dictionary of valid hosts

        Returns:
            List of source dictionaries

        Raises:
            NotImplementedError: If subclass doesn't implement this method
        """
        raise NotImplementedError(f'{self.name} must implement _scrape_sources()')

    def resolve(self, url):
        """
        Resolve a source URL to final playable URL.
        Override if site needs custom resolution logic.

        Args:
            url: Source URL

        Returns:
            Resolved URL (usually just returns the input URL)
        """
        return url

    # Helper methods

    def _request(self, url, **kwargs):
        """
        HTTP request wrapper with standard error handling.

        Args:
            url: URL to request
            **kwargs: Additional arguments for client.request()
                - headers: Custom headers (default: self.headers)
                - timeout: Request timeout
                - etc.

        Returns:
            Response text or None on error
        """
        try:
            # Use provided headers or fall back to instance headers
            headers = kwargs.pop('headers', self.headers)

            # Make request
            response = client.request(url, headers=headers, **kwargs)

            # Check for empty response
            if not response:
                c.log(f'[{self.name}] Empty response from {url}')
                return None

            # Check for common error patterns
            error_patterns = [
                '404 Not Found',
                'Just a moment',
                'Enable JavaScript and cookies',
                'Access denied',
                'Error 1020'
            ]

            if any(pattern in response for pattern in error_patterns):
                c.log(f'[{self.name}] Detected error page from {url}')
                return None

            return response

        except Exception as e:
            c.scraper_error(f'Request error for {url}: {e}', scraper=self.name)
            return None

    def _parse_data(self, url):
        """
        Parse URL-encoded data into dictionary.

        Args:
            url: URL-encoded string

        Returns:
            Dictionary with parsed data or None on error
        """
        try:
            data = parse_qs(url)
            data = dict([(i, data[i][0]) if data[i] else (i, '') for i in data])
            return data
        except Exception as e:
            c.scraper_error(f'Error parsing URL data: {e}', scraper=self.name)
            return None
