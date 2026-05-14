# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file homepornking.py
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


class HomePornKing(CrewAdult):
    def __init__(self):
        super().__init__(
            name='homepornking',
            title='Homemade Porn LQ - [COLOR orchid]HPK[/COLOR]'
        )

    def get_videos(self, url=None, page=1):
        """Get homemade videos"""
        c.log(f'[HomePornKing] Fetching videos')

        # Prepare URLs for multiple pages
        urls = []
        base_url = 'https://www.homepornking.com/new/'
        for i in range(1, 5):
            urls.append(base_url + str(i) + '/')

        # Use concurrent fetching
        page_fetcher = PageFetcher()
        html = page_fetcher.run(urls)

        if not html:
            return []

        # Extract videos
        pattern = r'(?s)pics_h(?:[^=]*)=\'([^\']*)\'><img src=\'([^\']*)\' alt=\'([^\']*)'
        matches = re.findall(pattern, html)

        results = []
        for path,thumb, title in matches:
            video_url = 'https://www.homepornking.com' + path
            title = self._cleanup_title(title)
            results.append((video_url, title, thumb))

        c.log(f'[HomePornKing] Found {len(results)} videos')
        return results

    def resolve(self, url):
        """Resolve video page using resolveurl"""
        c.log(f'[HomePornKing] Resolving: {url}')

        # Handle go.php redirect with base64 encoded URL
        if '/go.php?u=' in url:
            import base64
            from urllib.parse import urlparse, parse_qs
            try:
                parsed = urlparse(url)
                encoded = parse_qs(parsed.query).get('u', [''])[0]
                if encoded:
                    decoded = base64.b64decode(encoded).decode('utf-8')
                    c.log(f'[HomePornKing] Decoded go.php URL: {decoded}')
                    url = decoded
            except Exception as e:
                c.log(f'[HomePornKing] Failed to decode go.php URL: {e}')

        # Try resolveurl framework
        resolved = self._try_resolveurl(url)
        if resolved:
            return resolved

        # Fallback: fetch page and extract video URL
        c.log(f'[HomePornKing] Resolveurl failed, trying manual extraction')
        try:
            html = client.request(url, timeout=10)
            if html:
                # Try common video URL patterns
                video_url = self._extract_video_url(html)
                if video_url:
                    return video_url
        except Exception as e:
            c.log(f'[HomePornKing] Manual extraction failed: {e}')

        # Last resort
        c.log(f'[HomePornKing] All methods failed, returning None')
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
            html = client.request(url)
            if html:
                self.results.append((idx, html))
        except:
            pass


# Register the site
site = HomePornKing()
