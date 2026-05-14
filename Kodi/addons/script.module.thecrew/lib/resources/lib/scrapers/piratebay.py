# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file piratebay.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
import ast
import json
import traceback
from urllib.parse import urljoin, quote_plus

from ..modules import cache, cleantitle, client, control
from .torrent_base import TorrentBaseScraper
from ..modules.crewruntime import c


class source(TorrentBaseScraper):
    def __init__(self):
        super().__init__(
            name='piratebay',
            base_link='https://apibay.org',
            # Domain list: apibay.org FIRST (API, no validation needed)
            # Other domains tested sequentially when cache expires or fails
            # Different countries block different mirrors - keep multiple fallbacks
            domains=['apibay.org','tpbproxypirate.com', 'pirateproxy.live', 'thepiratebay.org', 'thepiratebay.fun',
                    'thepiratebay.asia', 'tpb.party', 'thepiratebay3.org', 'thepiratebayz.org',
                    'thehiddenbay.com', 'piratebay.live', 'thepiratebay.zone']
        )
        self.search_link = '/q.php?q=%s&cat=0'
        self._cached_base = None

    @property
    def base_url(self):
        """
        Get base URL with long-term caching (24 hours).

        Different countries block different TPB mirrors, so we:
        1. Cache the working domain for 24 hours (not 2 hours)
        2. Validate domains only when cache expires or request fails
        3. Use persistent cache.db so it survives Kodi restarts
        """
        if self._cached_base is None:
            # Get cached domain (24 hour cache = 1440 minutes)
            default_url = f"https://{self.domains[0]}"
            cached_url = cache.get(self._get_base_url, 1440, default_url)

            # Check if we got a cached value
            if cached_url == default_url:
                c.log(f'[TPB] No cached domain found, validating domains...')
            else:
                c.log(f'[TPB] Using cached domain: {cached_url} (valid for 24h)')

            self._cached_base = cached_url

        return self._cached_base

    def _invalidate_cache(self):
        """
        Invalidate cached domain (called when request fails).
        Forces re-validation on next scrape.
        """
        c.log('[TPB] Invalidating cached domain due to request failure')
        self._cached_base = None
        try:
            # Clear from persistent cache using correct API
            # Generate cache key same way cache.get() does
            cache_key = cache._hash_function(self._get_base_url)
            cache.cache_delete(cache_key)
            c.log('[TPB] Cache invalidated successfully')
        except Exception as e:
            c.log(f'[TPB] Could not clear cache: {e}')

    def _scrape_torrents(self, data, hostDict):
        title = data.get('tvshowtitle', data.get('title'))
        year = str(data.get('year', ''))
        aliases = data.get('aliases', [])
        hdlr = self._build_hdlr(data)
        is_movie = not data.get('tvshowtitle')  # True if movie, False if episode

        query = self._build_query(data)
        query = re.sub(r'(\\\|/| -|:|;|\*|\?|"|<|>|\|)', ' ', query)

        url = self.search_link % quote_plus(query)
        url = urljoin(self.base_url, url)
        c.log(f'[TPB] Query="{query}" Title="{title}" Year="{year}" Handler="{hdlr}" IsMovie={is_movie}')
        c.log(f'[TPB] URL: {url}')

        # Add explicit modern headers to avoid bot detection
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive'
        }

        html = client.request(url, timeout=10, error=True, headers=headers)

        # Check if we got an error object instead of content
        if hasattr(html, 'code') or hasattr(html, 'reason'):
            error_code = getattr(html, 'code', 'no code')
            error_reason = getattr(html, 'reason', 'no reason')
            c.log(f'[TPB] Request error: {error_code} - {error_reason}')
            c.log(f'[TPB] Error object type: {type(html)}')

            # Invalidate cache if domain is blocked (403) or unreachable (timeout, connection error)
            # This forces domain re-validation on next scrape
            if error_code in [403, 404, 503] or error_code == 'no code':
                c.log('[TPB] Domain appears blocked or unreachable, invalidating cache')
                self._invalidate_cache()

            return self._sources_list

        c.log(f'[TPB] Response: len={len(html) if html else 0}')

        if not html:
            c.log(f'[TPB] Empty response from API')
            # Don't invalidate cache for empty responses - might just be no results
            return self._sources_list

        try:
            entries = json.loads(html)
            c.log(f'[TPB] Parsed {len(entries)} entries from API')

            if not isinstance(entries, list):
                c.log(f'[TPB] Response is not a list: {type(entries)}')
                return self._sources_list

            processed = 0
            rejected_title = 0
            rejected_seeders = 0

            for entry in entries:
                if not isinstance(entry, dict):
                    continue

                try:
                    name = entry.get('name', '')
                    if not name:
                        continue

                    # Use sophisticated check_title from base scraper (checks aliases, year ranges, episode codes)
                    if not self.check_title(title, aliases, name, hdlr, year, is_movie):
                        rejected_title += 1
                        if processed < 3:  # Log first few rejections for debugging
                            c.log(f'[TPB] Reject (check_title): "{name}"')
                        continue

                    seeders = int(entry.get('seeders', 0))
                    if not self._check_seeders(seeders, self.min_seeders):
                        rejected_seeders += 1
                        continue

                    info_hash = entry.get('info_hash', '')
                    url = self._build_magnet(info_hash, name)

                    size_bytes = entry.get('size', 0)
                    dsize, isize = self._parse_size_bytes(size_bytes)

                    source_dict = self._build_torrent_source(name, url, seeders, dsize, info_hash)
                    source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
                    self._sources_list.append(source_dict)
                    processed += 1

                except Exception as e:
                    c.log(f'[TPB] Error processing entry: {e}')
                    continue

            c.log(f'[TPB] Results: {len(self._sources_list)} added | {rejected_title} title rejected | {rejected_seeders} seeders rejected')

        except Exception as e:
            c.log(f'[TPB] Error parsing results: {e}')
            c.log(f'[TPB] Traceback: {traceback.format_exc()}')

        return self._sources_list

    def sources_packs(self, data, hostDict, search_series=False, total_seasons=0, bypass_filter=0):
        from ..modules import source_utils
        sources = []
        try:
            tvshowtitle = data.get('tvshowtitle')
            year = data.get('year')
            season = int(data.get('season', 0))
            imdb = data.get('imdb')
            aliases = data.get('aliases', [])

            if not tvshowtitle:
                return sources

            title_query = cleantitle.get_query(tvshowtitle)
            queries = []

            if search_series:
                queries.extend([
                    f'{title_query} Complete Series',
                    f'{title_query} All Seasons',
                    f'{title_query} Season 1-{total_seasons}' if total_seasons > 0 else None
                ])
            else:
                queries.extend([
                    f'{title_query} S{season:02d}',
                    f'{title_query} Season {season}',
                    f'{title_query} Season.{season}',
                ])

            queries = [q for q in queries if q]

            for query in queries:
                try:
                    url = self.search_link % quote_plus(query)
                    url = urljoin(self.base_url, url)
                    html = client.request(url)

                    if not html or not html.startswith('['):
                        continue

                    entries = ast.literal_eval(html)
                    if not isinstance(entries, list):
                        continue

                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue

                        try:
                            name = entry.get('name', '')
                            if not name:
                                continue

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
                                package_meta = {
                                    'package': 'season',
                                    'episode_start': episode_start,
                                    'episode_end': episode_end
                                }

                            seeders = int(entry.get('seeders', 0))
                            if not self._check_seeders(seeders, self.min_seeders):
                                continue

                            info_hash = entry.get('info_hash', '')
                            url = self._build_magnet(info_hash, name)

                            size_bytes = entry.get('size', 0)
                            dsize, isize = self._parse_size_bytes(size_bytes)

                            source_dict = self._build_torrent_source(name, url, seeders, dsize, info_hash)
                            source_dict['info'] = isize + ' | ' + source_dict['info'] if isize else source_dict['info']
                            source_dict.update(package_meta)
                            sources.append(source_dict)

                        except Exception as e:
                            c.log(f'TPB Pack - Error processing entry: {e}')
                            continue

                except Exception as e:
                    c.log(f'TPB Pack - Error searching: {e}')
                    continue

            return sources

        except Exception as e:
            c.log(f'TPB Pack - Exception: {e}')
            return sources

    def _get_base_url(self, fallback):
        """
        Find working TPB domain by testing each sequentially.

        Country-specific blocking: Different countries block different mirrors.
        This validation only runs when cache expires (every 24 hours) or fails.

        OPTIMIZATION: Reduced timeout from 10s to 3s per domain (faster fallback).
        """
        import time
        start_time = time.time()
        c.log(f'[TPB] Starting domain validation (testing {len(self.domains)} domains)')

        for i, domain in enumerate(self.domains, 1):
            try:
                url = f'https://{domain}'

                # apibay.org is an API - skip HTML validation, just return it
                if domain == 'apibay.org':
                    c.log(f'[TPB] [{i}/{len(self.domains)}] Using apibay.org API (no validation needed)')
                    elapsed = time.time() - start_time
                    c.log(f'[TPB] Domain validation complete in {elapsed:.1f}s - using {url}')
                    return url

                # For other domains: test with shorter timeout (3s instead of 10s)
                c.log(f'[TPB] [{i}/{len(self.domains)}] Testing {domain}...')
                result = client.request(url, limit=1, timeout='3')
                result = re.findall('<input type="submit" title="(.+?)"', result, re.DOTALL)[0]
                if result and 'Pirate Search' in result:
                    elapsed = time.time() - start_time
                    c.log(f'[TPB] [{i}/{len(self.domains)}] ✓ Found working domain in {elapsed:.1f}s: {domain}')
                    return url
                else:
                    c.log(f'[TPB] [{i}/{len(self.domains)}] ✗ Invalid response from {domain}')
            except Exception as e:
                c.log(f'[TPB] [{i}/{len(self.domains)}] ✗ Failed: {domain} - {str(e)[:50]}')
                continue

        elapsed = time.time() - start_time
        c.log(f'[TPB] All {len(self.domains)} domains failed after {elapsed:.1f}s, using fallback: {fallback}')
        return fallback
