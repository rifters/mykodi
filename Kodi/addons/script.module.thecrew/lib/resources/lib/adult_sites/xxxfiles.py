# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file xxxfiles.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from .base import CrewAdult
from ..modules import client
from ..modules.crewruntime import c
from ..modules.http_client import HTTPClient


class XXXFiles(CrewAdult):
    def __init__(self):
        super().__init__(
            name='xxxfiles',
            title='New Videos - [COLOR orchid] XXF[/COLOR]'
        )

    def get_videos(self, url=None, page=1):
        """Get latest videos"""
        c.log(f'[XXXFiles] Fetching videos, page: {page}')

        # Build page URL
        page_url = f'https://www.xxxfiles.com/latest-updates/{page}/'

        try:
            session = HTTPClient.get_session('adult')
            response = session.get(page_url, timeout=10)
            response.raise_for_status()
            html = response.text
            if not html:
                return []
        except Exception as e:
            c.log(f'[XXXFiles] Fetch failed: {e}')
            return []

        # Extract video links and titles
        pattern = r'(?s)thumb item(?:[^=]*)="([^"]*)(?:[^=]*)=(?:[^=]*)=(?:[^=]*)=(?:[^=]*)="([^"]*)" alt="([^"]*)">(?:[^>]*)>([^<]*)'
        matches = re.findall(pattern, html)

        results = []
        for match in matches:
            video_url = match[0]
            thumb = match[1] if len(match) > 1 else ''
            title = self._cleanup_title(match[2])
            if video_url and title:
                results.append((video_url, title, thumb))

        c.log(f'[XXXFiles] Found {len(results)} videos on page {page}')

        # Add next page indicator if we got results
        if results:
            results.append(('NEXT_PAGE', f'Next Page ({page + 1})...', ''))

        return results

    def resolve(self, url):
        """Resolve video page to playable URL"""
        c.log(f'[XXXFiles] Resolving: {url}')

        try:
            session = HTTPClient.get_session('adult')
            response = session.get(url, timeout=10)
            response.raise_for_status()
            html = response.text
            if not html:
                return None

            # Extract source URLs
            sources = re.findall(r'(?s)source src=\'([^\']*)(?:[^=]*)=(?:[^=]*)="([^"]*)', html)

            if not sources:
                return None

            # Return first/best quality
            video_url = sources[0][0]
            c.log('[XXXFiles] Resolved successfully')
            return video_url

        except Exception as e:
            c.log(f'[XXXFiles] Resolution failed: {e}')
            return None

# Register the site
site = XXXFiles()
