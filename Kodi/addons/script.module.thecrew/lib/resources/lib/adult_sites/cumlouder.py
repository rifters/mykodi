# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file cumlouder.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from .base import CrewAdult
from ..modules import client, workers
from ..modules.crewruntime import c
from ..modules.http_client import HTTPClient


class CUMLOUDER(CrewAdult):
    def __init__(self):
        super().__init__(
            name='cumlouder',
            title='[B][COLOR orange]CUM[/COLOR]LOUDER[/B]'
        )
        self.base_url = 'https://www.cumlouder.com/'

    def get_categories(self):
        """Get series/categories"""
        c.log(f'[CUMLOUDER] Fetching categories')

        try:
            # Fetch from /series/ page instead of homepage
            series_url = self.base_url + 'series/'
            # Set cookies to bypass age verification (validated in test_cumlouder.ipynb)
            cookies = {
                'disclaimer-confirmed': '1',
                'parentDni': '0',
                'parentCountry': 'XX',
                'parentRegion': 'XX'
            }
            headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': self.base_url,
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            session = HTTPClient.get_session('adult')
            response = session.get(series_url, cookies=cookies, headers=headers, timeout=15)
            response.raise_for_status()
            html = response.text
            if not html:
                return []

            c.log(f'[CUMLOUDER] Fetched {len(html)} bytes from /series/')
        except Exception as e:
            c.log(f'[CUMLOUDER] Category fetch failed: {e}')
            return []

        # Extract series URLs (categories)
        pattern = r'(?s)href="(https://www\.cumlouder\.com/series/[^"]+)/"[^>]*>\s*<img[^>]+data-src="([^"]+)"[^>]*alt="([^"]+)"[^>]*>\s*<h2[^>]*>([^<]+)</h2>'
        matches = re.findall(pattern, html)

        results = []
        for cat_url, thumb_url, alt_text, title in matches:
            cat_name = self._cleanup_title(title.strip())
            results.append((cat_url, cat_name, thumb_url))

        c.log(f'[CUMLOUDER] Found {len(results)} categories')
        return results

    def get_videos(self, url, page=1):
        """Get videos from a series"""
        c.log(f'[CUMLOUDER] Fetching videos from: {url}, page: {page}')

        # Use base_url if no URL provided (when no categories found)
        if not url:
            url = self.base_url
            c.log(f'[CUMLOUDER] No URL provided, using base_url: {url}')

        # Build page URL
        base = url if url.endswith('/') else url + '/'
        page_url = base + str(page) + '/'

        try:
            # Set cookies to bypass age verification (validated in test_cumlouder.ipynb)
            cookies = {
                'disclaimer-confirmed': '1',
                'parentDni': '0',
                'parentCountry': 'XX',
                'parentRegion': 'XX'
            }
            headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': self.base_url,
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            session = HTTPClient.get_session('adult')
            response = session.get(page_url, cookies=cookies, headers=headers, timeout=15)
            response.raise_for_status()
            html = response.text
            if not html:
                return []
        except Exception as e:
            c.log(f'[CUMLOUDER] Page fetch failed: {e}')
            return []

        # Extract videos
        pattern = r'(?s)<a class="muestra-escena" href="([^"]*).*?data-src="([^"]*).*?alt="([^"]*)'
        matches = re.findall(pattern, html)

        results = []
        for video_path, thumb, title in matches:
            video_url = 'https://www.cumlouder.com' + video_path
            title = self._cleanup_title(title)
            results.append((video_url, title, thumb))

        c.log(f'[CUMLOUDER] Found {len(results)} videos on page {page}')

        # Add next page indicator if we got results (assume more pages exist)
        if results:
            results.append(('NEXT_PAGE', f'Next Page ({page + 1})...', ''))

        return results

    def resolve(self, url):
        """Resolve video page using resolveurl"""
        c.log(f'[CUMLOUDER] Resolving: {url}')

        # Try resolveurl framework
        resolved = self._try_resolveurl(url)
        if resolved:
            return resolved

        # Fallback: fetch page and extract video URL
        c.log(f'[CUMLOUDER] Resolveurl failed, trying manual extraction')
        try:
            # Set cookies to bypass age verification (validated in test_cumlouder.ipynb)
            cookies = {
                'disclaimer-confirmed': '1',
                'parentDni': '0',
                'parentCountry': 'XX',
                'parentRegion': 'XX'
            }
            headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Referer': self.base_url,
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            session = HTTPClient.get_session('adult')
            response = session.get(url, cookies=cookies, headers=headers, timeout=10)
            response.raise_for_status()
            html = response.text
            if html:
                # Try common video URL patterns
                video_url = self._extract_video_url(html)
                if video_url:
                    return video_url
        except Exception as e:
            c.log(f'[CUMLOUDER] Manual extraction failed: {e}')

        # Last resort
        c.log(f'[CUMLOUDER] All methods failed, returning None')
        return None


class PageFetcher:
    """Helper class for concurrent page fetching"""
    def __init__(self):
        self.results = []

    def run(self, urls):
        threads = []
        self.results = []
        indexed_urls = [(i+1, url) for i, url in enumerate(urls)]

        for idx, url in indexed_urls:
            thread = workers.Thread(self._fetch_page, (idx, url))
            threads.append(thread)

        [t.start() for t in threads]
        [t.join() for t in threads]

        # Sort by index and join results
        self.results.sort(key=lambda x: x[0])
        return ''.join([r[1] for r in self.results])

    def _fetch_page(self, data):
        idx, url = data
        try:
            # Set cookies to bypass age verification (validated in test_cumlouder.ipynb)
            cookies = {
                'disclaimer-confirmed': '1',
                'parentDni': '0',
                'parentCountry': 'XX',
                'parentRegion': 'XX'
            }
            headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Referer': 'https://www.cumlouder.com/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            session = HTTPClient.get_session('adult')
            response = session.get(url, cookies=cookies, headers=headers, timeout=15)
            response.raise_for_status()
            html = response.text
            if html:
                self.results.append((idx, html))
        except:
            pass


# Register the site
site = CUMLOUDER()
