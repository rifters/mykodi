# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file whoreshub.py
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


class WhoresHub(CrewAdult):
    def __init__(self):
        super().__init__(
            name='whoreshub',
            title='HD & UHD Videos - [COLOR orchid]WH[/COLOR]'
        )
        self.base_url = 'https://www.whoreshub.com/'

    def get_categories(self):
        """Get video sections and categories"""
        c.log('[WhoresHub] Fetching categories')

        results = []

        # Add main sections at the top (not alphabetically sorted)
        results.append(('https://www.whoreshub.com/latest-updates/', '[COLOR orchid]Latest Updates[/COLOR]', self.icon))
        results.append(('https://www.whoreshub.com/most-popular/', 'Most Viewed', self.icon))
        results.append(('https://www.whoreshub.com/top-rated/', 'Top Rated', self.icon))

        # Fetch categories from all pages (categories are paginated)
        try:
            all_categories = {}  # Use dict to avoid duplicates: {url: (name, thumb, count)}

            # Categories page has 4 pages
            for page_num in range(1, 5):
                if page_num == 1:
                    page_url = 'https://www.whoreshub.com/categories/'
                else:
                    page_url = f'https://www.whoreshub.com/categories/{page_num}/'

                c.log(f'[WhoresHub] Fetching category page {page_num}')
                html = client.request(page_url, timeout=15)

                if not html:
                    continue

                # Get all category URLs from this page
                cat_urls = re.findall(r'href="(https://www\.whoreshub\.com/categories/[^"]+)"', html)

                # Filter out pagination links
                cat_urls = [u for u in cat_urls if not re.search(r'/categories/\d+/$|/categories/$', u)]

                # For each URL, extract title, thumbnail, and video count
                for url in cat_urls:
                    if url in all_categories:
                        continue  # Already processed

                    cat_name = None
                    thumb_url = self.icon
                    count = None

                    # Try pattern 1: with description span (has both thumb and title)
                    match1 = re.search(rf'href="{re.escape(url)}".*?data-src="([^"]+)".*?<span class="description">([^<]+)</span>.*?<span class="text">(\d+)</span>', html, re.DOTALL)
                    if match1:
                        thumb_url = 'https:' + match1.group(1) if not match1.group(1).startswith('http') else match1.group(1)
                        cat_name = self._cleanup_title(match1.group(2))
                        count = match1.group(3)
                    else:
                        # Try pattern 2: from alt attribute (also has thumb)
                        match2 = re.search(rf'href="{re.escape(url)}"[^>]*>.*?data-src="([^"]+)"[^>]*alt="([^"]+)".*?<span class="text">(\d+)</span>', html, re.DOTALL)
                        if match2:
                            thumb_url = 'https:' + match2.group(1) if not match2.group(1).startswith('http') else match2.group(1)
                            cat_name = self._cleanup_title(match2.group(2))
                            count = match2.group(3)

                    # Fallback: extract name from URL
                    if not cat_name:
                        cat_name = url.rstrip('/').split('/')[-1].replace('-', ' ').title()

                    # Add video count to name if available
                    if count:
                        display_name = f'{cat_name} [{count}]'
                    else:
                        display_name = cat_name

                    all_categories[url] = (display_name, thumb_url, cat_name)  # Store original name for sorting

            # Add all categories to results, sorted alphabetically by original name
            for url, (display_name, thumb, _) in sorted(all_categories.items(), key=lambda x: x[1][2]):
                results.append((url, display_name, thumb))

            c.log(f'[WhoresHub] Found {len(all_categories)} total categories')
        except Exception as e:
            c.log(f'[WhoresHub] Failed to fetch categories: {e}')

        c.log(f'[WhoresHub] Total sections: {len(results)}')
        return results

    def get_videos(self, url, page=1):
        """Get videos from a section or category"""
        c.log(f'[WhoresHub] Fetching videos from: {url}, page: {page}')

        # Build single page URL
        page_num = int(page)
        if page_num == 1:
            page_url = url
        else:
            # Ensure proper URL structure for pagination
            if url.endswith('/'):
                page_url = f'{url}{page_num}/'
            else:
                page_url = f'{url}/{page_num}/'

        c.log(f'[WhoresHub] Page URL: {page_url}')

        try:
            html = client.request(page_url, timeout=15)
            if not html:
                return []
        except Exception as e:
            c.log(f'[WhoresHub] Failed to fetch page: {e}')
            return []

        # Extract videos
        pattern = r'"item" href="([^"]*)" title="([^"]*).+?data-src="([^"]*)'
        matches = re.findall(pattern, html, re.DOTALL)

        results = []
        for video_url, title, thumb in matches:
            if title and video_url:
                title = self._cleanup_title(title)
                thumbnail = 'https:' + thumb if thumb and not thumb.startswith('http') else thumb
                results.append((video_url, title, thumbnail))

        c.log(f'[WhoresHub] Found {len(results)} videos')

        # Add next page if we have results
        if results:
            results.append(('NEXT_PAGE', f'[COLOR orchid]Next Page ({page_num + 1})[/COLOR]', ''))

        return results

    def resolve(self, url):
        """Resolve video page to playable URL"""
        c.log(f'[WhoresHub] Resolving: {url}')

        try:
            html = client.request(url, timeout=10)
            if not html:
                return None

            # Extract video URLs with quality labels
            pattern = r'_url(?:[^\']*)\'(h[^\']*).+?text\: \'([^\']*)'
            matches = re.findall(pattern, html, re.DOTALL)

            # Filter for MP4 URLs
            mp4_urls = []
            quality_labels = []

            for video_url, quality_label in matches:
                if 'mp4' in video_url:
                    # Add headers for access
                    url_with_headers = video_url + '|User-Agent=Mozilla/5.0&Referer=' + url
                    mp4_urls.append(url_with_headers)
                    quality_labels.append(quality_label)

            if not mp4_urls:
                return None

            # If multiple qualities, select first (usually highest)
            # Could add quality selection dialog here if needed
            selected_url = mp4_urls[0]

            c.log(f'[WhoresHub] Resolved to: {quality_labels[0] if quality_labels else "unknown quality"}')
            return selected_url

        except Exception as e:
            c.log(f'[WhoresHub] Resolution failed: {e}')
            return None


# Register the site
site = WhoresHub()
