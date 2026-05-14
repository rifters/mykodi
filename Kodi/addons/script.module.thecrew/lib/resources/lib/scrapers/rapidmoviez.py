# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file rapidmoviez.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urljoin, quote_plus

from ..modules import cleantitle, client, debrid, source_utils, workers

try:
    from ..modules import cfscrape
except ImportError:
    cfscrape = None
from .base import BaseScraper
from ..modules.crewruntime import c


class source(BaseScraper):
    def __init__(self):
        super().__init__(name='rapidmoviez', language=['en'])
        self.domains = ['rapidmoviez.com']
        self.base_link = 'https://www.rapidmoviez.com/'
        self.search_link = 'search/%s'

    def sources(self, url, hostDict, hostprDict=None):
        sources = []
        try:
            if not url or debrid.status() is False:
                return sources

            hostDict = (hostprDict or []) + hostDict
            data = self._parse_data(url)

            title = data.get('tvshowtitle', data.get('title'))
            year = data.get('year', '')
            season = data.get('season', '')
            episode = data.get('episode', '')

            # Build search query
            query = '%s %s' % (title, year)
            query = re.sub(r'[^A-Za-z0-9\s\.]', '', query)
            query_url = urljoin(self.base_link, self.search_link % quote_plus(query))

            # Use cfscrape for Cloudflare protection
            try:
                scraper = cfscrape.create_scraper()
                r = scraper.get(query_url).content.decode('utf-8')
            except:
                return sources

            # Parse search results
            r = client.parseDOM(r, 'div', attrs={'class': 'list_items'})
            if not r:
                return sources

            r = client.parseDOM(r, 'li')
            items = []

            for entry in r:
                try:
                    entry_title = client.parseDOM(entry, 'a', attrs={'class': 'title'}, ret='title')[0]
                    if not cleantitle.get(title) in cleantitle.get(entry_title):
                        continue
                    if year and not year in entry_title:
                        continue

                    entry_url = client.parseDOM(entry, 'a', attrs={'class': 'title'}, ret='href')[0]
                    items.append(entry_url)
                except:
                    continue

            # Threaded source extraction
            threads = []
            for item_url in items:
                threads.append(workers.Thread(self._get_sources, item_url, hostDict, title,
                                             year, season, episode, sources))
            [i.start() for i in threads]
            [i.join() for i in threads]

            return sources
        except:
            return sources

    def _get_sources(self, url, hostDict, title, year, season, episode, sources):
        try:
            scraper = cfscrape.create_scraper()
            r = scraper.get(url).content.decode('utf-8')

            # Extract quality from title
            quality, info = source_utils.get_release_quality(r, url)

            # Parse links
            r_links = client.parseDOM(r, 'pre', attrs={'class': 'links'})
            if not r_links:
                return

            for link_block in r_links:
                # Extract URLs
                urls = re.findall(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)', link_block)

                for link in urls:
                    # Skip unwanted file types
                    if any(x in link.lower() for x in ['.rar', '.zip', '.iso', '.idx', '.sub', '.srt']):
                        continue

                    valid, host = source_utils.is_host_valid(link, hostDict)
                    if not valid:
                        continue

                    sources.append({
                        'source': host,
                        'quality': quality,
                        'language': 'en',
                        'url': link,
                        'info': ' | '.join(info),
                        'direct': False,
                        'debridonly': False
                    })
        except:
            pass
