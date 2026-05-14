# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file pornrewind.py
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


class Pornrewind(CrewAdult):
    def __init__(self):
        super().__init__(
            name='pornrewind',
            title='Pornrewind: [COLOR gold][B]HD[/B][/COLOR]'
        )

    def get_videos(self, url=None, page=1):
        """Get HD videos"""
        c.log(f'[Pornrewind] Fetching videos')

        # Prepare URLs for multiple pages
        urls = []
        base_url = 'https://www.pornrewind.com/categories/hd/'
        for i in range(1, 10):
            urls.append(base_url + str(i) + '/')

        # Use concurrent fetching
        page_fetcher = PageFetcher()
        html = page_fetcher.run(urls)

        if not html:
            return []

        # Extract videos
        pattern = r'(?s)data-item-id="(?:[^=]*)=(?:[^=]*)="([^"]*)(?:[^=]*)="([^"]*)(?:[^=]*)=(?:[^=]*)=(?:[^=]*)="([^"]*)'
        matches = re.findall(pattern, html)

        results = []
        for video_url, title, thumb in matches:
            title = self._cleanup_title(title)
            results.append((video_url, title, thumb))

        c.log(f'[Pornrewind] Found {len(results)} videos')
        return results

    def resolve(self, url):
        """Resolve video page using resolveurl"""
        c.log(f'[Pornrewind] Resolving: {url}')

        # Try resolveurl framework
        resolved = self._try_resolveurl(url)
        if resolved:
            return resolved

        # Fallback: fetch page and extract video URL
        c.log(f'[Pornrewind] Resolveurl failed, trying manual extraction')
        try:
            html = client.request(url, timeout=10)
            if html:
                # Try common video URL patterns
                video_url = self._extract_video_url(html)
                if video_url:
                    return video_url
        except Exception as e:
            c.log(f'[Pornrewind] Manual extraction failed: {e}')

        # Last resort
        c.log(f'[Pornrewind] All methods failed, returning None')
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
site = Pornrewind()
