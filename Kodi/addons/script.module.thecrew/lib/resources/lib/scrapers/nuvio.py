# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file nuvio.py (refactored with BaseScraper)
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
* Free API scraper for nuvio streaming sources
********************************************************cm*
'''

import json
from urllib.parse import urljoin

from .base import BaseScraper
from ..modules import client
from ..modules import source_utils
from ..modules.crewruntime import c


class source(BaseScraper):
    """
    Nuvio API scraper - refactored to use BaseScraper

    API-based scraper that queries nuviostreams.hayd.uk for direct sources.
    Works for both movies and TV episodes.
    """

    def __init__(self):
        super().__init__(
            name='nuvio',
            base_link='https://nuviostreams.hayd.uk',
            search_link='',  # API-based, no search page
            domains=['nuviostreams.hayd.uk']
        )
        self.movieSearch_link = '/stream/movie/%s.json'
        self.tvSearch_link = '/stream/series/%s:%s:%s.json'

    def _scrape_sources(self, url, hostDict):
        """API-based scraping logic for nuvio streams"""
        sources = []

        try:
            # Parse URL data
            data = self._parse_data(url)
            if not data:
                return sources

            title = data.get('tvshowtitle') or data.get('title')
            year = data.get('year')
            imdb = data.get('imdb')

            # Build API URL
            if 'tvshowtitle' in data:
                season = data.get('season')
                episode = data.get('episode')
                api_url = urljoin(self.base_link, self.tvSearch_link % (imdb, season, episode))
            else:
                api_url = urljoin(self.base_link, self.movieSearch_link % imdb)

            c.log(f'[nuvio] Requesting API: {api_url}')

            # Request API
            response = self._request(api_url, timeout=40)
            if not response:
                c.log('[nuvio] Empty API response')
                return sources

            # Parse JSON response
            try:
                json_data = json.loads(response)
                files = json_data.get('streams', [])
            except Exception as e:
                c.log(f'[nuvio] JSON parse error: {e}')
                return sources

            if not files:
                c.log('[nuvio] No streams found in API response')
                return sources

            c.log(f'[nuvio] Found {len(files)} streams')

            # Process each stream
            for file in files:
                try:
                    name = file.get('title', '')
                    stream_url = file.get('url', '')

                    if not stream_url:
                        continue

                    # Extract size information
                    try:
                        dsize = file.get('behaviorHints', {}).get('videoSize', 0)
                        isize = source_utils.convert_size(dsize) if dsize else ''
                    except Exception:
                        try:
                            import re
                            size_info = file.get('size', '')
                            rsize = re.search(r'([\d.]+)\s*(KB|MB|GB|TB)', size_info, re.IGNORECASE)
                            if rsize:
                                value = float(rsize.group(1))
                                unit = rsize.group(2).upper()
                                multipliers = {
                                    'KB': 1024,
                                    'MB': 1024 ** 2,
                                    'GB': 1024 ** 3,
                                    'TB': 1024 ** 4,
                                }
                                size_bytes = int(value * multipliers[unit])
                                isize = source_utils.convert_size(size_bytes)
                            else:
                                isize = ''
                        except Exception:
                            isize = ''

                    # Get quality from filename
                    quality, info = source_utils.get_release_quality(name)
                    if isize:
                        info.insert(0, isize)
                    info_str = ' | '.join(info) if info else ''

                    sources.append({
                        'provider': 'nuvio',
                        'source': 'direct',
                        'quality': quality,
                        'language': 'en',
                        'url': stream_url,
                        'info': info_str,
                        'direct': True,
                        'debridonly': False,
                    })

                except Exception as e:
                    c.log(f'[nuvio] Error processing stream: {e}')
                    continue

            c.log(f'[nuvio] Returning {len(sources)} sources')
            return sources

        except Exception as e:
            c.scraper_error(e, exc_info=e)
            return sources
