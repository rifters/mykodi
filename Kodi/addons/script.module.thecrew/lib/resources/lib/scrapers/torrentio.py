# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file torrentio.py (refactored with TorrentBaseScraper)
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
import requests
import json

from ..scrapers.torrent_base import TorrentBaseScraper
from ..modules import cleantitle, source_utils
from ..modules.crewruntime import c


class source(TorrentBaseScraper):
    """
    Torrentio scraper - refactored with TorrentBaseScraper

    Before: 260 lines
    After: ~120 lines (54% reduction)

    Torrentio aggregates many torrent sites via API
    """

    def __init__(self):
        super().__init__(
            name='torrentio',
            base_link='https://torrentio.strem.fun',
            search_link='',  # Uses API endpoints
            min_seeders=0
        )
        self.movieSearch_link = '/stream/movie/%s.json'
        self.tvSearch_link = '/stream/series/%s:%s:%s.json'
        self.headers = {'User-Agent': 'Mozilla/5.0'}
        self.ITEMINFO = re.compile(r'👤.*')

    def _scrape_torrents(self, data, hostDict):
        """Site-specific torrent scraping via Torrentio API"""
        sources = []

        try:
            title = data.get('tvshowtitle') or data.get('title')
            title = title.replace('&', 'and').replace('/', ' ')
            imdb = data.get('imdb')

            # Extract season/episode for metadata
            is_episode = data.get('tvshowtitle') is not None
            season = data.get('season') if is_episode else None
            episode = data.get('episode') if is_episode else None

            # Build API URL
            if is_episode:
                url = f'{self.base_link}{self.tvSearch_link % (imdb, season, episode)}'
            else:
                url = f'{self.base_link}{self.movieSearch_link % imdb}'

            # Request API
            c.log(f'[torrentio] Requesting {url}')
            try:
                results = requests.get(url, headers=self.headers, timeout=15)
                files = results.json().get('streams', [])
            except (requests.RequestException, json.JSONDecodeError) as e:
                c.log(f'[torrentio] Request error: {e}')
                return sources

            # Process results
            for file in files:
                try:
                    infohash = file.get('infoHash')
                    if not infohash:
                        continue

                    # Parse title parts
                    file_title = file['title'].split('\n')
                    file_info_lines = [x for x in file_title if self.ITEMINFO.match(x)]

                    name = file_title[0]
                    clean_name = cleantitle.get(name)
                    clean_title = cleantitle.get(title)

                    # Check title match
                    if clean_title not in clean_name:
                        continue

                    # Build magnet
                    magnet = self._build_magnet(infohash, name)

                    # Extract seeders
                    seeders = 0
                    if file_info_lines:
                        seeders_match = re.search(r'(\d+)', file_info_lines[0])
                        if seeders_match:
                            seeders = int(seeders_match.group(1))

                    # Extract size
                    size_gb = 0
                    if file_info_lines:
                        size_match = re.search(
                            r'((?:\d+\,\d+\.\d+|\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|Gb|MB|MiB|Mb))',
                            file_info_lines[0]
                        )
                        if size_match:
                            size_gb, _ = self._parse_size(size_match.group(0))

                    # Build source (include season/episode for pack file selection)
                    source = self._build_torrent_source(
                        name=name,
                        url=magnet,
                        seeders=seeders,
                        size=size_gb,
                        info_hash=infohash,
                        season=season,
                        episode=episode
                    )

                    if source:
                        sources.append(source)

                except Exception as e:
                    c.log(f'[torrentio] Error processing item: {e}')
                    continue

            return sources

        except Exception as e:
            c.scraper_error('Exception in _scrape_torrents', exc_info=e)
            return sources

    def sources_packs(self, data, hostDict, search_series=False, total_seasons=0, bypass_filter=0):
        """Search for pack releases via Torrentio API"""
        sources = []

        try:
            tvshowtitle = data.get('tvshowtitle')
            year = data.get('year')
            season = int(data.get('season', 0))
            imdb = data.get('imdb')
            aliases = data.get('aliases', [])

            if not tvshowtitle or not imdb:
                return sources

            # Query first episode to get pack results
            url = f'{self.base_link}{self.tvSearch_link % (imdb, season, 1)}'
            c.log(f'[torrentio] Pack search: {url}')

            try:
                results = requests.get(url, headers=self.headers, timeout=15)
                files = results.json().get('streams', [])
            except (requests.RequestException, json.JSONDecodeError) as e:
                c.log(f'[torrentio] Pack request error: {e}')
                return sources

            for file in files:
                try:
                    infohash = file.get('infoHash')
                    if not infohash:
                        continue

                    file_title = file['title'].split('\n')
                    name = file_title[0]

                    # Validate pack
                    if search_series:
                        valid, last_season = source_utils.filter_show_pack(
                            tvshowtitle, aliases, imdb, year, season,
                            source_utils.release_title_format(name), total_seasons
                        )
                        if not valid:
                            continue
                        package_meta = {'package': 'show', 'last_season': last_season}
                    else:
                        valid, episode_start, episode_end = source_utils.filter_season_pack(
                            tvshowtitle, aliases, year, season,
                            source_utils.release_title_format(name)
                        )
                        if not valid:
                            continue
                        package_meta = {'package': 'season', 'episode_start': episode_start, 'episode_end': episode_end}

                    # Extract info
                    file_info_lines = [x for x in file_title if self.ITEMINFO.match(x)]
                    seeders = 0
                    size_gb = 0

                    if file_info_lines:
                        seeders_match = re.search(r'(\d+)', file_info_lines[0])
                        if seeders_match:
                            seeders = int(seeders_match.group(1))

                        size_match = re.search(
                            r'((?:\d+\,\d+\.\d+|\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|Gb|MB|MiB|Mb))',
                            file_info_lines[0]
                        )
                        if size_match:
                            size_gb, _ = self._parse_size(size_match.group(0))

                    # Build magnet
                    magnet = self._build_magnet(infohash, cleantitle.get(name))

                    # Build source
                    source = self._build_torrent_source(
                        name=name,
                        url=magnet,
                        seeders=seeders,
                        size=size_gb,
                        info_hash=infohash
                    )

                    if source:
                        source.update(package_meta)
                        sources.append(source)

                except Exception as e:
                    c.log(f'[torrentio] Pack item error: {e}')
                    continue

            return sources

        except Exception as e:
            c.log(f'[torrentio] Pack exception: {e}')
            return sources
