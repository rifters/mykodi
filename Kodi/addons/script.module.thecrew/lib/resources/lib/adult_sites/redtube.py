# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file redtube.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import quote_plus
from .base import CrewAdult
from ..modules import client
from ..modules.crewruntime import c


class RedTube(CrewAdult):
    def __init__(self):
        super().__init__(
            name='redtube',
            title='Search [COLOR firebrick][B]RedTube[/B][/COLOR]'
        )

    def search(self, keyword):
        """Search RedTube for videos"""
        if not keyword:
            return []

        c.log(f'[RedTube] Searching for: {keyword}')

        url = f'https://www.redtube.com/?search={quote_plus(keyword)}&page=1&hd=1'

        try:
            html = client.request(url, timeout=10)
            if not html:
                return []
        except Exception as e:
            c.log(f'[RedTube] Search failed: {e}')
            return []

        # Extract video data
        video_links = re.findall(r'<a[^>]+href="(/\d+)"', html)
        titles = re.findall(r'<img[^>]+alt="([^"]+)"[^>]*class="[^"]*thumb', html)

        results = []
        for i in range(min(len(video_links), len(titles))):
            video_url = 'https://www.redtube.com' + video_links[i]
            title = self._cleanup_title(titles[i])
            results.append((video_url, title, ''))

        c.log(f'[RedTube] Found {len(results)} results')
        return results

    def resolve(self, url):
        """Resolve RedTube video page to playable URL"""
        c.log(f'[RedTube] Resolving: {url}')

        try:
            html = client.request(url, timeout=10)
            if not html:
                return None

            # Extract manifest URL
            match = re.search(r'"format":"mp4","videoUrl":"([^"]*)"', html)
            if not match:
                c.log(f'[RedTube] No manifest URL found')
                return None

            manifest_url = 'https://www.redtube.com' + match.group(1).replace('\\/', '/')

            # Fetch manifest to get quality URLs
            manifest = client.request(manifest_url, timeout=10)
            if not manifest:
                return None

            # Extract qualities
            qualities = re.findall(r'ty"\:"(\d+)(?:[^\:]*)\:"([^"]*)', manifest)
            if not qualities:
                return None

            # Sort by quality (highest first) and return best
            qualities.sort(reverse=True)
            video_url = qualities[0][1].replace('\\/', '/')

            c.log(f'[RedTube] Resolved to quality {qualities[0][0]}p')
            return video_url

        except Exception as e:
            c.log(f'[RedTube] Resolution failed: {e}')
            return None


# Register the site
site = RedTube()
