# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 * @file debridcheck.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

import os
import sys
import time
import datetime
import json
import sqlite3 as database
import traceback
from typing import List, Tuple, Dict, Any, Optional, Callable
from threading import Thread

import requests

from . import control
from . import utils
from .crewruntime import c


__r_url__ = control.addon('script.module.resolveurl')
rd_enabled = (__r_url__.getSetting('RealDebridResolver_enabled') == 'true' and
              __r_url__.getSetting('RealDebridResolver_token') != '')
ad_enabled = (__r_url__.getSetting('AllDebridResolver_enabled') == 'true' and
              __r_url__.getSetting('AllDebridResolver_token') != '')
pm_enabled = (__r_url__.getSetting('PremiumizeMeResolver_enabled') == 'true' and
              __r_url__.getSetting('PremiumizeMeResolver_token') != '')
progressDialog = control.progressDialogBG


class RDapi:
    def __init__(self):
        self.token = __r_url__.getSetting('RealDebridResolver_token')
        self.client_id = __r_url__.getSetting('RealDebridResolver_client_id')
        self.client_secret = __r_url__.getSetting('RealDebridResolver_client_secret')
        self.refresh = __r_url__.getSetting('RealDebridResolver_refresh')
        self.rest_base_url = 'https://api.real-debrid.com/rest/1.0/'
        self.oauth_url = 'https://api.real-debrid.com/oauth/v2/'

    def _get(self, url):
        original_url = url
        url = self.rest_base_url + url
        if '?' not in url:
            url += "?auth_token=%s" % self.token
        else:
            url += "&auth_token=%s" % self.token
        response = requests.get(url, timeout=15).text
        if 'bad_token' in response or 'Bad Request' in response:
            self.refreshToken()
            response = self._get(original_url)
        try:
            resp = utils.json_loads_as_str(response)
        except Exception as e:
            c.log(traceback.format_exc())
            resp = utils.byteify(response)
        #from resources.lib.modules import log_utils
        #log_utils.log('RDapi-' + str(resp))
        return resp

    def refreshToken(self) -> None:
        """Refresh Real-Debrid OAuth token."""
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': self.refresh,
            'grant_type': 'http://oauth.net/grant_type/device/1.0'
        }
        url = f"{self.oauth_url}token"

        try:
            response = requests.post(url, data=data, timeout=30)
            response_data = response.json()

            if 'access_token' in response_data:
                self.token = response_data['access_token']
                __r_url__.setSetting('RealDebridResolver_token', self.token)

            if 'refresh_token' in response_data:
                self.refresh = response_data['refresh_token']
                __r_url__.setSetting('RealDebridResolver_refresh', self.refresh)

            c.log("[debridcheck] RD token refreshed successfully")

        except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
            c.log(f"[debridcheck] RD token refresh failed: {e}")
            c.log(traceback.format_exc())

    def check_cache(self, hashes: List[str]) -> Optional[Dict[str, Any]]:
        """Check if torrents are cached on Real-Debrid.

        Args:
            hashes: List of torrent info hashes to check

        Returns:
            Dictionary mapping hashes to cache status
        """
        hash_string = '/'.join(hashes)
        url = f"torrents/instantAvailability/{hash_string}"
        return self._get(url)

class ADapi:
    """AllDebrid API client for cache checking."""

    def __init__(self):
        self.base_url = 'https://api.alldebrid.com/v4/'
        self.token = __r_url__.getSetting('AllDebridResolver_token')
        self.user_agent = 'ResolveURL for Kodi'

    def check_cache(self, hashes: List[str]) -> Optional[Dict[str, Any]]:
        """Check if torrents are cached on AllDebrid.

        Args:
            hashes: List of torrent info hashes to check

        Returns:
            API response or None on failure
        """
        data = {'magnets[]': hashes}
        return self._post('magnet/instant', data)

    def _post(self, url: str, data: Dict[str, Any] = {}) -> Optional[Dict[str, Any]]:
        """Execute POST request to AllDebrid API.

        Args:
            url: API endpoint path
            data: POST data dictionary

        Returns:
            Parsed JSON response or None on failure
        """
        if not self.token:
            c.log("[debridcheck] AD: No token configured")
            return None

        if data is None:
            data = {}

        full_url = f"{self.base_url}{url}?agent={self.user_agent}&apikey={self.token}"

        try:
            response = requests.post(full_url, data=data, timeout=30)
            resp = response.json()

            if resp.get('status') == 'success' and 'data' in resp:
                return resp['data'].get('magnets')

            return resp

        except (requests.RequestException, json.JSONDecodeError) as e:
            c.log(f"[debridcheck] AD API request failed: {e}")
            c.log(traceback.format_exc())
            return None

class PMapi:
    """Premiumize.me API client for cache checking."""

    def __init__(self):
        self.base_url = 'https://www.premiumize.me/api/'
        self.token = __r_url__.getSetting('PremiumizeMeResolver_token')

    def check_cache(self, hashes: List[str]) -> Optional[Dict[str, Any]]:
        """Check if torrents are cached on Premiumize.

        Args:
            hashes: List of torrent info hashes to check

        Returns:
            API response or None on failure
        """
        url = "cache/check"
        data = {'items[]': hashes}
        return self._post(url, data)

    def _post(self, url: str, data: Dict[str, Any] = {}) -> Optional[Dict[str, Any]]:
        """Execute POST request to Premiumize API.

        Args:
            url: API endpoint path
            data: POST data dictionary

        Returns:
            Parsed JSON response or None on failure
        """
        if not self.token and 'token' not in url:
            c.log("[debridcheck] PM: No token configured")
            return None

        if data is None:
            data = {}

        headers = {'Authorization': f"Bearer {self.token}"}

        if 'token' not in url:
            url = self.base_url + url

        try:
            response = requests.post(url, data=data, headers=headers, timeout=30)
            return utils.json_loads_as_str(response.text)

        except (requests.RequestException, json.JSONDecodeError) as e:
            c.log(f"[debridcheck] PM API request failed: {e}")
            c.log(traceback.format_exc())
            try:
                return utils.byteify(response.text)
            except:
                return None


class DebridCheck:
    """Main coordinator for checking torrent cache across multiple debrid services."""

    def __init__(self):
        self.db_cache = DebridCache()
        self.db_cache.check_database()

        # Cache storage
        self.cached_hashes: List[Tuple[str, str, bool]] = []

        # Thread management
        self.main_threads: List[Thread] = []

        # Real-Debrid
        self.rd_cached_hashes: List[str] = []
        self.rd_hashes_unchecked: List[str] = []
        self.rd_query_threads: List[Thread] = []
        self.rd_process_results: List[Tuple[str, bool]] = []

        # AllDebrid
        self.ad_cached_hashes: List[str] = []
        self.ad_hashes_unchecked: List[str] = []
        self.ad_query_threads: List[Thread] = []
        self.ad_process_results: List[Tuple[str, bool]] = []

        # Premiumize
        self.pm_cached_hashes: List[str] = []
        self.pm_hashes_unchecked: List[str] = []
        self.pm_process_results: List[Tuple[str, bool]] = []

        # Progress tracking
        self.starting_debrids: List[Tuple[str, Callable]] = []
        self.starting_debrids_display: List[Tuple[str, str]] = []

    def run(self, hash_list: List[str]) -> Tuple[List[str], List[str], List[str]]:
        """Check cache status for list of torrent hashes across all enabled debrid services.

        Args:
            hash_list: List of torrent info hashes to check

        Returns:
            Tuple of (rd_cached, ad_cached, pm_cached) hash lists
        """
        control.sleep(500)
        self.hash_list = hash_list

        # Query local cache first
        self._query_local_cache(self.hash_list)

        # Prepare Real-Debrid checks
        if rd_enabled:
            self._prepare_rd_check()

        # Prepare AllDebrid checks
        if ad_enabled:
            self._prepare_ad_check()

        # Prepare Premiumize checks
        if pm_enabled:
            self._prepare_pm_check()

        # Execute all checks in parallel
        if self.starting_debrids:
            self._execute_checks()

        control.sleep(500)
        return self.rd_cached_hashes, self.ad_cached_hashes, self.pm_cached_hashes

    def _prepare_rd_check(self) -> None:
        """Prepare Real-Debrid cache check."""
        # Get already cached hashes from local DB
        self.rd_cached_hashes = [
            str(hash_info[0])
            for hash_info in self.cached_hashes
            if hash_info[1] == 'rd' and hash_info[2]  # hash_info[2] is boolean cached status
        ]

        # Find hashes not in local cache
        cached_hash_set = {h[0] for h in self.cached_hashes if h[1] == 'rd'}
        self.rd_hashes_unchecked = [
            h for h in self.hash_list
            if h not in cached_hash_set
        ]

        if self.rd_hashes_unchecked:
            self.starting_debrids.append(('Real-Debrid', self.RD_cache_checker))

    def _prepare_ad_check(self) -> None:
        """Prepare AllDebrid cache check."""
        # Get already cached hashes from local DB
        self.ad_cached_hashes = [
            str(hash_info[0])
            for hash_info in self.cached_hashes
            if hash_info[1] == 'ad' and hash_info[2]
        ]

        # Find hashes not in local cache
        cached_hash_set = {h[0] for h in self.cached_hashes if h[1] == 'ad'}
        self.ad_hashes_unchecked = [
            h for h in self.hash_list
            if h not in cached_hash_set
        ]

        if self.ad_hashes_unchecked:
            self.starting_debrids.append(('AllDebrid', self.AD_cache_checker))

    def _prepare_pm_check(self) -> None:
        """Prepare Premiumize cache check."""
        # Get already cached hashes from local DB
        self.pm_cached_hashes = [
            str(hash_info[0])
            for hash_info in self.cached_hashes
            if hash_info[1] == 'pm' and hash_info[2]
        ]

        # Find hashes not in local cache
        cached_hash_set = {h[0] for h in self.cached_hashes if h[1] == 'pm'}
        self.pm_hashes_unchecked = [
            h for h in self.hash_list
            if h not in cached_hash_set
        ]

        if self.pm_hashes_unchecked:
            self.starting_debrids.append(('Premiumize.me', self.PM_cache_checker))

    def _execute_checks(self) -> None:
        """Execute all prepared debrid checks in parallel threads."""
        # Create threads for each debrid service
        for i, (service_name, checker_func) in enumerate(self.starting_debrids):
            thread = Thread(target=checker_func)
            self.main_threads.append(thread)
            self.starting_debrids_display.append((thread.getName(), service_name))

        # Start all threads
        for thread in self.main_threads:
            thread.start()

        # Show progress dialog
        self.debrid_check_dialog()

        # Wait for all threads to complete
        for thread in self.main_threads:
            thread.join()

    def debrid_check_dialog(self) -> None:
        """Display progress dialog while checking debrid caches."""
        timeout = 20
        progressDialog.create('Checking debrid cache, please wait..')
        start_time = time.time()
        end_time = start_time + timeout

        while not progressDialog.isFinished():
            try:
                # Check for abort request
                if control.monitor.abortRequested():
                    return sys.exit()

                # Get currently running checks
                alive_threads = [x.getName() for x in self.main_threads if x.is_alive()]
                remaining_debrids = [
                    x[1] for x in self.starting_debrids_display
                    if x[0] in alive_threads
                ]

                # Calculate progress
                current_time = time.time()
                current_progress = current_time - start_time

                try:
                    percent = int((current_progress / timeout) * 100)
                    msg = f"Remaining Debrid Checks: {', '.join(remaining_debrids).upper()}"
                    progressDialog.update(percent, message=msg)
                except (ZeroDivisionError, ValueError) as e:
                    c.log(f"[debridcheck] Progress update error: {e}")

                time.sleep(0.1)

                # Exit conditions
                if not alive_threads or current_time > end_time:
                    break

            except Exception as e:
                c.log(f"[debridcheck] Dialog loop error: {e}")
                c.log(traceback.format_exc())
                break

        try:
            progressDialog.close()
        except Exception as e:
            c.log(f"[debridcheck] Dialog close error: {e}")

        control.sleep(200)

    def RD_cache_checker(self) -> None:
        """Check Real-Debrid cache in parallel chunks."""
        hash_chunk_list = list(utils.chunk_list(self.rd_hashes_unchecked, 100))

        for chunk in hash_chunk_list:
            thread = Thread(target=self._rd_lookup, args=(chunk,))
            self.rd_query_threads.append(thread)

        # Start all threads
        for thread in self.rd_query_threads:
            thread.start()

        # Wait for completion
        for thread in self.rd_query_threads:
            thread.join()

        # Save results to local cache
        self._add_to_local_cache(self.rd_process_results, 'rd')

    def AD_cache_checker(self) -> None:
        """Check AllDebrid cache in parallel chunks."""
        hash_chunk_list = list(utils.chunk_list(self.ad_hashes_unchecked, 100))

        for chunk in hash_chunk_list:
            thread = Thread(target=self._ad_lookup, args=(chunk,))
            self.ad_query_threads.append(thread)

        # Start all threads
        for thread in self.ad_query_threads:
            thread.start()

        # Wait for completion
        for thread in self.ad_query_threads:
            thread.join()

        # Save results to local cache
        self._add_to_local_cache(self.ad_process_results, 'ad')

    def PM_cache_checker(self) -> None:
        """Check Premiumize cache."""
        self._pm_lookup(self.pm_hashes_unchecked)
        self._add_to_local_cache(self.pm_process_results, 'pm')

    def _rd_lookup(self, chunk: List[str]) -> None:
        """Query Real-Debrid API for cache status of hash chunk.

        Args:
            chunk: List of hashes to check (max 100)
        """
        try:
            rd_cache_get = RDapi().check_cache(chunk)

            if not rd_cache_get:
                # API failed, mark all as uncached
                for h in chunk:
                    self.rd_process_results.append((h, False))
                return

            for h in chunk:
                is_cached = False

                if h in rd_cache_get:
                    info = rd_cache_get[h]
                    # Check if has valid RD cached files
                    if isinstance(info, dict) and info.get('rd') and len(info['rd']) > 0:
                        self.rd_cached_hashes.append(h)
                        is_cached = True

                self.rd_process_results.append((h, is_cached))

        except Exception as e:
            c.log(f"[debridcheck] RD lookup error: {e}")
            c.log(traceback.format_exc())
            # Mark all in chunk as uncached on error
            for h in chunk:
                self.rd_process_results.append((h, False))

    def _ad_lookup(self, hash_list: List[str]) -> None:
        """Query AllDebrid API for cache status.

        Args:
            hash_list: List of hashes to check
        """
        try:
            ad_cache = ADapi().check_cache(hash_list)

            if isinstance(ad_cache, list):
                for item in ad_cache:
                    # Handle both dict and string responses
                    if isinstance(item, dict):
                        is_cached = item.get('instant', False) is True
                        hash_val = item.get('hash', '')
                    else:
                        # API may return hash strings directly if all cached
                        hash_val = str(item) if item else ''
                        is_cached = True if hash_val else False

                    if is_cached and hash_val:
                        self.ad_cached_hashes.append(hash_val)

                    if hash_val:
                        self.ad_process_results.append((hash_val, is_cached))
            else:
                # API returned non-list (error), mark all uncached
                for h in hash_list:
                    self.ad_process_results.append((h, False))

        except Exception as e:
            c.log(f"[debridcheck] AD lookup error: {e}")
            c.log(traceback.format_exc())
            # Mark all as uncached on error
            for h in hash_list:
                self.ad_process_results.append((h, False))

    def _pm_lookup(self, hash_list: List[str]) -> None:
        """Query Premiumize API for cache status.

        Args:
            hash_list: List of hashes to check
        """
        try:
            pm_cache_response = PMapi().check_cache(hash_list)

            if not pm_cache_response or 'response' not in pm_cache_response:
                # API failed, mark all as uncached
                for h in hash_list:
                    self.pm_process_results.append((h, False))
                return

            pm_cache = pm_cache_response['response']

            for idx, h in enumerate(hash_list):
                is_cached = False

                # PM returns array of booleans matching input hash order
                if idx < len(pm_cache) and pm_cache[idx] is True:
                    self.pm_cached_hashes.append(h)
                    is_cached = True

                self.pm_process_results.append((h, is_cached))

        except Exception as e:
            c.log(f"[debridcheck] PM lookup error: {e}")
            c.log(traceback.format_exc())
            # Mark all as uncached on error
            for h in hash_list:
                self.pm_process_results.append((h, False))

    def _query_local_cache(self, hash_list: List[str]) -> None:
        """Query local database cache for hash status.

        Args:
            hash_list: List of hashes to check in cache
        """
        cached = self.db_cache.get_all(hash_list)
        if cached:
            self.cached_hashes = cached

    def _add_to_local_cache(self, results: List[Tuple[str, bool]], debrid: str) -> None:
        """Add lookup results to local database cache.

        Args:
            results: List of (hash, is_cached) tuples
            debrid: Debrid service identifier ('rd', 'ad', 'pm')
        """
        if results:
            self.db_cache.set_many(results, debrid)


class DebridCache:
    """Local SQLite cache for debrid torrent cache status."""

    def __init__(self):
        self.dbfile = control.dbFile

    def get_all(self, hash_list: List[str]) -> List[Tuple[str, str, bool]]:
        """Retrieve cache status for list of hashes.

        Args:
            hash_list: List of torrent hashes to check

        Returns:
            List of tuples: (hash, debrid_service, is_cached_bool)
        """
        if not hash_list:
            return []

        result = []
        try:
            current_time = self._get_timestamp(datetime.datetime.now())

            with database.connect(self.dbfile, timeout=40.0) as dbcon:
                dbcur = dbcon.cursor()

                # Safe parameterized query
                placeholders = ', '.join('?' * len(hash_list))
                query = f"SELECT * FROM debrid_data WHERE hash IN ({placeholders})"
                dbcur.execute(query, hash_list)
                cache_data = dbcur.fetchall()

                if cache_data:
                    # Filter expired entries
                    valid_data = []
                    expired_data = []

                    for row in cache_data:
                        hash_val, debrid, cached_str, expires = row

                        if expires > current_time:
                            # Convert string 'True'/'False' to boolean
                            is_cached = cached_str == 'True' if isinstance(cached_str, str) else bool(cached_str)
                            valid_data.append((hash_val, debrid, is_cached))
                        else:
                            expired_data.append(row)

                    # Remove expired entries
                    if expired_data:
                        self.remove_many(expired_data)

                    result = valid_data

        except database.Error as e:
            c.log(f"[debridcheck] Database get_all error: {e}")
            c.log(traceback.format_exc())
        except Exception as e:
            c.log(f"[debridcheck] Unexpected get_all error: {e}")
            c.log(traceback.format_exc())

        return result

    def remove_many(self, old_cached_data: List[Tuple]) -> None:
        """Remove expired cache entries.

        Args:
            old_cached_data: List of database row tuples to remove
        """
        try:
            hash_list = [(str(row[0]),) for row in old_cached_data]

            with database.connect(self.dbfile, timeout=40.0) as dbcon:
                dbcur = dbcon.cursor()
                dbcur.executemany("DELETE FROM debrid_data WHERE hash=?", hash_list)
                dbcon.commit()

        except database.Error as e:
            c.log(f"[debridcheck] Database remove_many error: {e}")
            c.log(traceback.format_exc())
        except Exception as e:
            c.log(f"[debridcheck] Unexpected remove_many error: {e}")
            c.log(traceback.format_exc())

    def set_many(self, hash_list: List[Tuple[str, bool]], debrid: str,
                 expiration: datetime.timedelta = datetime.timedelta(hours=1)) -> None:
        """Store cache check results in database.

        Args:
            hash_list: List of (hash, is_cached_bool) tuples
            debrid: Debrid service identifier ('rd', 'ad', 'pm')
            expiration: How long to cache results (default 1 hour)
        """
        if not hash_list:
            return

        try:
            expires = self._get_timestamp(datetime.datetime.now() + expiration)

            # Convert booleans to strings for database storage
            # Format: (hash, debrid, cached_str, expires)
            insert_list = [
                (hash_val, debrid, 'True' if is_cached else 'False', expires)
                for hash_val, is_cached in hash_list
            ]

            with database.connect(self.dbfile, timeout=40.0) as dbcon:
                dbcur = dbcon.cursor()

                # Use INSERT OR REPLACE to handle duplicates
                dbcur.executemany(
                    "INSERT OR REPLACE INTO debrid_data VALUES (?, ?, ?, ?)",
                    insert_list
                )
                dbcon.commit()

        except database.Error as e:
            c.log(f"[debridcheck] Database set_many error: {e}")
            c.log(traceback.format_exc())
        except Exception as e:
            c.log(f"[debridcheck] Unexpected set_many error: {e}")
            c.log(traceback.format_exc())

    def check_database(self) -> None:
        """Create database and table if they don't exist."""
        try:
            if not os.path.exists(control.dataPath):
                control.makeFile(control.dataPath)

            with database.connect(self.dbfile) as dbcon:
                dbcur = dbcon.cursor()
                dbcur.execute("""
                    CREATE TABLE IF NOT EXISTS debrid_data (
                        hash TEXT NOT NULL,
                        debrid TEXT NOT NULL,
                        cached TEXT,
                        expires INTEGER,
                        UNIQUE (hash, debrid)
                    )
                """)
                dbcon.commit()

        except database.Error as e:
            c.log(f"[debridcheck] Database check_database error: {e}")
            c.log(traceback.format_exc())
        except Exception as e:
            c.log(f"[debridcheck] Unexpected check_database error: {e}")
            c.log(traceback.format_exc())

    def _get_timestamp(self, date_time: datetime.datetime) -> int:
        """Convert datetime to Unix timestamp.

        Args:
            date_time: Datetime to convert

        Returns:
            Unix timestamp integer
        """
        return int(time.mktime(date_time.timetuple()))