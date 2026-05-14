# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file cache.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

import hashlib
import re
import time
import os
import json
import traceback
from contextlib import contextmanager

from sqlite3 import dbapi2 as db, OperationalError


import requests

import xbmcvfs

from . import keys
import random
from resources.lib.modules import control
from resources.lib.modules import utils
from resources.lib.modules.crewruntime import c

cache_table = 'cache'
ALLOWED_TABLES = {'cache', 'backdrop_cache', 'episode_cache', 'meta_cache', 'fanart_cache'}
if cache_table not in ALLOWED_TABLES:
    raise ValueError(f'[Cache] Invalid table name: {cache_table!r}')
CACHE_VERSION = 2  # Increment when cache schema changes


def get_dynamic_ttl(metadata=None):
    """
    Calculate dynamic TTL based on content status.

    Args:
        metadata: Dict with show/movie metadata (status, air_date, etc.)

    Returns:
        int: TTL in hours (6 for airing shows, 720 for ended)
    """
    if not metadata:
        return 24  # Default 24 hours

    try:
        status = metadata.get('status', '').lower()

        # Currently airing shows get shorter cache (6 hours)
        if status in ['returning series', 'in production', 'continuing']:
            return 6

        # Ended shows get longer cache (30 days)
        elif status in ['ended', 'canceled', 'cancelled']:
            return 720

        # Check if movie is recently released (within last year)
        if 'premiered' in metadata or 'release_date' in metadata:
            try:
                date_str = metadata.get('premiered') or metadata.get('release_date')
                if date_str:
                    import datetime
                    release_date = datetime.datetime.strptime(date_str[:10], '%Y-%m-%d')
                    days_old = (datetime.datetime.now() - release_date).days

                    # Recent releases: 6 hour cache
                    if days_old < 365:
                        return 6
                    # Older content: 30 day cache
                    else:
                        return 720
            except (ValueError, TypeError, AttributeError):
                pass  # Date parsing failed

        # Default to 24 hours if status unknown
        return 24
    except (Exception):
        return 24  # Safe fallback for any error


def get_image(tmdb_id, image_type='backdrop', rotate=True):
    """
    Get cached backdrop/poster images from TMDB with rotation support.

    Args:
        tmdb_id: TMDB ID for the show/movie
        image_type: 'backdrop' or 'poster'
        rotate: If True, return different image each time (rotation)

    Returns:
        Local file path to downloaded image, or None if failed
    """


    try:
        c.log(f"[Cache] get_image() called with tmdb_id={tmdb_id}, image_type={image_type}, rotate={rotate}")

        if not tmdb_id or tmdb_id in ('None', '0', None, 0):
            c.log(f"[Cache]REJECT: Skipping image fetch for invalid tmdb_id: {repr(tmdb_id)}")
            return None

        # Use fanart-style caching table
        cursor = _get_connection_cursor()

        # Create backdrop_cache table if needed
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backdrop_cache (
                tmdb_id TEXT,
                image_type TEXT,
                images TEXT,
                last_used INTEGER,
                added INTEGER,
                PRIMARY KEY (tmdb_id, image_type)
            )
        """)
        cursor.connection.commit()

        # MIGRATION: Add missing columns if table was created with old schema
        try:
            # Check if images column exists
            cursor.execute("SELECT images FROM backdrop_cache LIMIT 1")
        except Exception as e:
            if 'no such column' in str(e):
                c.log("[Cache] Migrating backdrop_cache table - dropping and recreating with new schema")
                cursor.execute("DROP TABLE IF EXISTS backdrop_cache")
                cursor.execute("""
                    CREATE TABLE backdrop_cache (
                        tmdb_id TEXT,
                        image_type TEXT,
                        images TEXT,
                        last_used INTEGER,
                        added INTEGER,
                        PRIMARY KEY (tmdb_id, image_type)
                    )
                """)
                cursor.connection.commit()
                c.log("[Cache] backdrop_cache table recreated successfully")

        # MIGRATION: Update old image.themoviedb.org URLs to image.tmdb.org
        try:
            cursor.execute("SELECT tmdb_id, image_type, images FROM backdrop_cache")
            for row in cursor.fetchall():
                row_tmdb_id, row_image_type, images_json = row
                if images_json and 'image.themoviedb.org' in images_json:
                    # Replace old domain with new domain
                    updated_json = images_json.replace('image.themoviedb.org', 'image.tmdb.org')
                    cursor.execute(
                        "UPDATE backdrop_cache SET images=? WHERE tmdb_id=? AND image_type=?",
                        (updated_json, row_tmdb_id, row_image_type)
                    )
                    c.log(f"[Cache] Updated URLs for TMDB {row_tmdb_id} from themoviedb.org to tmdb.org")
            cursor.connection.commit()
        except Exception as e:
            c.log(f"[Cache] URL migration failed (non-critical): {e}")

        # Check cache (2 weeks expiry like fanart)
        TWOWEEKS = 1209600
        now = int(time.time())

        cursor.execute(
            "SELECT images, last_used FROM backdrop_cache WHERE tmdb_id=? AND image_type=? AND added > ?",
            (str(tmdb_id), image_type, now - TWOWEEKS)
        )
        row = cursor.fetchone()

        if row:
            # Have cached image list (row is dict from _dict_factory)
            images = json.loads(row['images']) if isinstance(row['images'], str) else row['images']
            last_used = row.get('last_used', 0) or 0
            c.log(f"[Cache] Found cached images: {len(images)} images, last_used={last_used}")
        else:
            # Fetch from TMDB
            c.log(f"[Cache] No cache found, fetching from TMDB API...")
            tmdb_api_key = keys.tmdb_key
            url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/images?api_key={tmdb_api_key}"
            c.log(f"[Cache] TMDB URL: {url[:100]}...")

            response = requests.get(url, timeout=5)
            c.log(f"[Cache] TMDB response status: {response.status_code}")

            if response.status_code != 200:
                c.log(f"[Cache] TMDB request failed: status {response.status_code}", 1)
                return None

            data = response.json()
            image_key = 'backdrops' if image_type == 'backdrop' else 'posters'
            image_list = data.get(image_key, [])
            c.log(f"[Cache] TMDB returned {len(image_list)} {image_key}")

            if not image_list:
                c.log("[Cache] No images available from TMDB")
                return None

            # Extract URLs (using image.tmdb.org, not themoviedb.org)
            images = [f"https://image.tmdb.org/t/p/original{img['file_path']}"
                for img in image_list[:10]]  # Limit to 10 to save space
            c.log(f"[Cache] Prepared {len(images)} image URLs for caching")

            # Cache the list
            cursor.execute("""
                INSERT OR REPLACE INTO backdrop_cache
                (tmdb_id, image_type, images, last_used, added)
                VALUES (?, ?, ?, ?, ?)
            """, (str(tmdb_id), image_type, json.dumps(images), 0, now))
            cursor.connection.commit()
            last_used = 0
            c.log("[Cache] Cached image list to database")

        if not images:
            c.log("[Cache] No images available after cache check")
            return None

        # Select image (rotate if enabled)
        if rotate and len(images) > 1:
            # Use round-robin rotation
            idx = (last_used + 1) % len(images)
            c.log(f"[Cache] Rotation enabled: selected index {idx} (last was {last_used})")
        else:
            # Always use first image
            idx = 0
            c.log(f"[Cache] Rotation disabled or single image: using index {idx}")

        image_url = images[idx]
        c.log(f"[Cache] Selected image URL: {image_url[:80]}...")

        # Update last_used index
        cursor.execute(
            "UPDATE backdrop_cache SET last_used=? WHERE tmdb_id=? AND image_type=?",
            (idx, str(tmdb_id), image_type)
        )
        cursor.connection.commit()

        # Download to temp folder
        c.log(f"[Cache] Downloading image from {image_url[:50]}...")
        img_response = requests.get(image_url, timeout=10)
        c.log(f"[Cache] Download response status: {img_response.status_code}")

        if img_response.status_code != 200:
            c.log(f"[Cache] Image download failed: status {img_response.status_code}", 1)
            return None

        temp_dir = control.transPath('special://temp/')
        xbmcvfs.mkdirs(temp_dir)
        c.log(f"[Cache] Temp directory: {temp_dir}")

        # Use tmdb_id in filename for caching
        filename = f'tmdb_{tmdb_id}_{image_type}_{idx}.jpg'
        local_path = os.path.join(temp_dir, filename)
        c.log(f"[Cache] Local path will be: {local_path}")

        # Check if already downloaded
        if xbmcvfs.exists(local_path):
            c.log(f"[Cache] Image already exists locally, returning: {local_path}")
            return local_path

        # Write image
        c.log(f"[Cache] Writing {len(img_response.content)} bytes to file...")
        with control.openFile(local_path, 'wb') as f:
            f.write(img_response.content)

        c.log(f"[Cache] SUCCESS: Image saved to {local_path}")
        return local_path

    except Exception as e:
        c.log(f'[Cache] EXCEPTION in get_image for TMDB {tmdb_id}: {e}', 1)
        import traceback
        c.log(f'[Cache] Traceback: {traceback.format_exc()}', 1)
        return None


def get(function_, timeout, *args):
    """
    Execute a function with caching support.

    Args:
        function_: Function to execute
        timeout: Cache timeout in hours. None = bypass cache (always fresh). 0 = indefinite. n > 0 = expire after n hours.
        *args: Arguments to pass to the function

    Returns:
        The function result (from cache or fresh execution)
    """
    try:
        # Generate cache key
        key = _hash_function(function_, *args)

        # If timeout is None, bypass cache entirely (always fetch fresh)
        if timeout is None:
            if callable(function_):
                return function_(*args)
            return function_

        # Try to get from cache
        cached = cache_get(key, timeout)

        if cached is not None:
            try:
                # Return cached value (handle JSON deserialization if needed)
                value = cached.get('value')
                if isinstance(value, str):
                    try:
                        return json.loads(value)
                    except Exception:
                        return value
                return value
            except Exception:
                pass  # If parsing fails, fetch fresh

        # Cache miss or expired - execute function
        if not callable(function_):
            return function_

        result = function_(*args)

        # Cache the result if it's not None
        if result is not None:
            try:
                serialized = json.dumps(result)
                cache_insert(key, serialized)
            except Exception:
                pass  # If caching fails, still return result

        return result

    except Exception as e:
        c.log(f"[Cache.get] Error: {e}")
        # If everything fails, try to execute function directly
        try:
            if callable(function_):
                return function_(*args)
            return function_
        except Exception:
            return None


def timeout(function_, *args):
    try:
        key = _hash_function(function_, *args)
        result = cache_get(key)
        return int(result['date']) if result else 0
    except Exception:
        return 0


def cache_delete(key, table=None):
    """Delete a cache key from the unified cache table."""
    try:
        with _get_connection_cursor() as cursor:
            if table:
                cursor.execute(f"DELETE FROM {cache_table} WHERE key = ? AND namespace = ?", (key, table))
            else:
                cursor.execute(f"DELETE FROM {cache_table} WHERE key = ?", (key,))
    except Exception as e:
        pass


def cache_delete_by_prefix(prefix, table=None):
    """
    Delete all cache keys starting with a given prefix.

    Args:
        prefix: String prefix to match (e.g., 'trakt_next_episodes')
        table: Optional namespace/table to filter by

    Returns:
        int: Number of deleted entries
    """
    try:
        with _get_connection_cursor() as cursor:
            if table:
                cursor.execute(f"DELETE FROM {cache_table} WHERE key LIKE ? AND namespace = ?",
                             (f"{prefix}%", table))
            else:
                cursor.execute(f"DELETE FROM {cache_table} WHERE key LIKE ?", (f"{prefix}%",))
            return cursor.rowcount
    except Exception as e:
        c.log(f'[Cache] Failed to delete by prefix={prefix}: {e}')
        return 0




def cache_get(key, timeout=None, table=None):
    # Returns dict row if present and not expired, else None
    try:
        with _get_connection_cursor() as cursor:
            # Ensure schema is up-to-date (adds 'namespace', 'etag', 'last_modified')
            _ensure_cache_table_schema(cursor)

            sql = f"SELECT * FROM {cache_table} WHERE key = ?"
            params = [key]
            if table:
                sql += " AND namespace = ?"
                params.append(table)

            cursor.execute(sql, params)
            row = cursor.fetchone()
            if not row:
                return None

            # None or 0 = indefinite cache, skip expiry check
            if timeout is None or timeout == 0:
                return row

            # timeout is in hours
            now = int(time.time())
            if (now - int(row.get('date', 0))) >= int(timeout) * 3600:
                return None

            return row
    except OperationalError:
        return None
    except Exception as e:
        return None


def cache_get_many(keys, timeout=None, table=None):
    """
    Batch fetch multiple cache entries in ONE query.
    Returns dict: {key: row_dict} for all found keys.
    Missing/expired keys are not included in result.

    Args:
        keys: List of cache keys to fetch
        timeout: Cache timeout in hours (None = ignore expiration)
        table: Optional namespace filter

    Returns:
        dict: {key: cached_row_dict} for valid entries only
    """
    if not keys:
        return {}

    try:
        with _get_connection_cursor() as cursor:
            _ensure_cache_table_schema(cursor)

            # Build WHERE IN query with parameterized placeholders
            placeholders = ','.join('?' * len(keys))
            sql = f"SELECT * FROM {cache_table} WHERE key IN ({placeholders})"
            params = list(keys)

            if table:
                sql += " AND namespace = ?"
                params.append(table)

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            # Build result dict, filtering expired entries if timeout specified
            # None or 0 = indefinite (skip expiry check)
            result = {}
            now = int(time.time()) if (timeout is not None and timeout != 0) else None

            for row in rows:
                key = row.get('key')
                if not key:
                    continue

                # Check expiration only for finite timeouts
                if now is not None:
                    row_date = int(row.get('date', 0))
                    if (now - row_date) >= int(timeout) * 3600:
                        continue  # Expired, skip

                result[key] = row

            return result

    except Exception as e:
        c.log(f"[Cache] cache_get_many error: {e}")
        return {}


def get_with_etag(key, fetcher, ttl_seconds=60, namespace=None):
    """
    Conditional fetch using ETag/Last-Modified.

    - fetcher(conditional_headers) should return (body_text, response_headers, status_code)
    - ttl_seconds: how fresh cached data can be before conditional revalidation
    """
    try:
        row = cache_get(key, table=namespace)

        now = int(time.time())
        # If we have a fresh cached row within ttl, return it immediately
        if row and (now - int(row.get('date', 0))) <= int(ttl_seconds):
            try:
                return json.loads(row['value']) if isinstance(row['value'], str) else row['value']
            except Exception:
                return row['value']

        # Prepare conditional headers if we have etag/last_modified
        conditional = {}
        if row and row.get('etag'):
            conditional['If-None-Match'] = row.get('etag')
        if row and row.get('last_modified'):
            conditional['If-Modified-Since'] = row.get('last_modified')

        # Perform the conditional fetch
        result = fetcher(conditional) if conditional else fetcher(None)
        if not result:
            # No response; fallback to cached value if available
            if row:
                try:
                    return json.loads(row['value']) if isinstance(row['value'], str) else row['value']
                except Exception:
                    return row['value']
            return None

        # Normalize result to (body, headers, status)
        body, headers, status = (result[0], result[1], result[2]) if len(result) >= 3 else (result[0], result[1], 200)

        if status == 304:
            # Not modified - do NOT update the cached timestamp to allow
            # subsequent calls to revalidate in case server content changes shortly after.
            try:
                return json.loads(row['value']) if isinstance(row['value'], str) else row['value']
            except Exception:
                return row['value']

        if status and (200 <= int(status) < 300):
            # New content - store and return
            parsed = json.loads(body) if isinstance(body, str) else body
            etag = headers.get('ETag') or headers.get('Etag')
            last_mod = headers.get('Last-Modified') or headers.get('last-modified')
            cache_insert(key, json.dumps(parsed), table=namespace, etag=etag, last_modified=last_mod)
            return parsed

        # Other status - fallback to cached if available
        if row:
            try:
                return json.loads(row['value']) if isinstance(row['value'], str) else row['value']
            except Exception:
                return row['value']

        return None
    except Exception as e:
        return None

def _ensure_cache_table_schema(cursor):
    """Ensure the unified cache table exists and has the expected columns."""
    try:
        # Create base table if missing
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {cache_table} (key TEXT PRIMARY KEY, value TEXT, date INTEGER, namespace TEXT)")
        cursor.connection.commit()

        # Ensure 'table' column exists (for older DBs)
        pragma = cursor.execute(f"PRAGMA table_info({cache_table})").fetchall()
        cols = [row['name'] if isinstance(row, dict) else row[1] for row in pragma]
        if 'namespace' not in cols:
            try:
                cursor.execute(f"ALTER TABLE {cache_table} ADD COLUMN namespace TEXT")
                cursor.connection.commit()

                # If older DB used 'table' column, copy values across
                if 'table' in cols:
                    try:
                        # Copy values from 'table' into new 'namespace' column
                        cursor.execute(f"UPDATE {cache_table} SET namespace = table")
                        cursor.connection.commit()
                    except Exception as e:
                        pass

            except Exception as e:
                pass

        # Ensure etag and last_modified columns exist for conditional requests
        if 'etag' not in cols:
            try:
                cursor.execute(f"ALTER TABLE {cache_table} ADD COLUMN etag TEXT")
                cursor.connection.commit()
            except Exception as e:
                pass

        if 'last_modified' not in cols:
            try:
                cursor.execute(f"ALTER TABLE {cache_table} ADD COLUMN last_modified TEXT")
                cursor.connection.commit()
            except Exception as e:
                pass

        # Record migration as applied (idempotent)
        try:
            cursor.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at INTEGER)")
            # Check whether migration already recorded to avoid noisy duplicate logs
            cursor.execute("SELECT 1 FROM schema_migrations WHERE name = ? LIMIT 1", ('cache_v2',))
            exists = cursor.fetchone()
            if not exists:
                # Use INSERT OR IGNORE to avoid race-condition errors if another process inserts simultaneously
                cursor.execute("INSERT OR IGNORE INTO schema_migrations (name, applied_at) VALUES (?,?)", ('cache_v2', int(time.time())))
                cursor.connection.commit()
                # Verify insertion actually took place before logging
                cursor.execute("SELECT 1 FROM schema_migrations WHERE name = ? LIMIT 1", ('cache_v2',))
                now_exists = cursor.fetchone()
                if now_exists:
                    pass
            # If exists already, silently continue to avoid repetitive log entries
        except Exception as e:
            pass
    except Exception as e:
        pass


def cache_insert(key, value, table=None, etag=None, last_modified=None):
    # Insert or update a key in the unified cache table. 'table' is optional metadata.
    with _get_connection_cursor() as cursor:
        # Ensure schema is ready
        _ensure_cache_table_schema(cursor)

        now = int(time.time())

        # Upsert using parameterized queries
        namespace_val = table if table is not None else None
        update_result = cursor.execute(f"UPDATE {cache_table} SET value=?,date=?,namespace=?,etag=?,last_modified=? WHERE key= ?", (value, now, namespace_val, etag, last_modified, key))

        if update_result.rowcount == 0:
            cursor.execute(f"INSERT INTO {cache_table} (key, value, date, namespace, etag, last_modified) VALUES (?, ?, ?, ?, ?, ?)", (key, value, now, namespace_val, etag, last_modified))



def clear_caches(cache_types=None):
    """
    General function to clear specified cache types.
    - cache_types: List of strings (e.g., ['main', 'meta', 'providers', 'debrid', 'search']) or None for all.
    - Maintains ability to call individual functions separately.
    - Uses improved exception handling for robustness.
    """
    if cache_types is None:
        cache_types = ['main', 'meta', 'providers', 'debrid', 'search']

    cache_functions = {
        'main': _clear_main_cache,
        'meta': _clear_meta_cache,
        'providers': _clear_providers_cache,
        'debrid': _clear_debrid_cache,
        'search': _clear_search_cache
    }

    for cache_type in cache_types:
        if cache_type in cache_functions:
            try:
                cache_functions[cache_type]()
            except Exception as e:
                pass
        else:
            pass

def _clear_main_cache():
    """Clear main cache tables (main cache table + artwork/image caches)."""
    try:
        with _get_connection_cursor() as cursor:
            tables_to_clear = [
                cache_table,       # Main unified cache (table named 'cache')
                'backdrop_cache',  # TMDB backdrop images
                'episode_cache',   # Episode metadata from TMDB
                'season_cache',    # Season posters from TMDB
                'show_cache',      # Show backdrops from TMDB
                'fanart_cache'     # Fanart cache
            ]
            for t in tables_to_clear:
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS {t}")
                    cursor.execute("VACUUM")
                    cursor.connection.commit()
                except OperationalError as e:
                    pass
                except Exception as e:
                    pass
    except Exception as e:
        pass

def _clear_meta_cache():
    """Clear meta cache tables (meta)."""
    try:
        with _get_connection_cursor_meta() as cursor:
            for t in ['meta']:
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS {t}")
                    cursor.execute("VACUUM")
                    cursor.connection.commit()
                except OperationalError as e:
                    pass
                except Exception as e:
                    pass
    except Exception as e:
        pass

def _clear_providers_cache():
    """Clear providers cache tables (rel_src, rel_url)."""
    try:
        with _get_connection_cursor_providers() as cursor:
            for t in ['rel_src', 'rel_url']:
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS {t}")
                    cursor.execute("VACUUM")
                    cursor.connection.commit()
                except OperationalError as e:
                    pass
                except Exception as e:
                    pass
    except Exception as e:
        pass

def _clear_debrid_cache():
    """Clear debrid cache tables (debrid_data)."""
    try:
        with _get_connection_cursor_debrid() as cursor:
            for t in ['debrid_data']:
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS {t}")
                    cursor.execute("VACUUM")
                    cursor.connection.commit()
                except OperationalError as e:
                    pass
                except Exception as e:
                    pass
    except Exception as e:
        pass

def _clear_search_cache():
    """Clear search cache tables (tvshow, movies)."""
    try:
        with _get_connection_cursor_search() as cursor:
            for t in ['tvshow', 'movies']:
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS {t}")
                    cursor.execute("VACUUM")
                    cursor.connection.commit()
                except OperationalError as e:
                    pass
                except Exception as e:
                    pass
    except Exception as e:
        pass

# Keep individual functions for backward compatibility and separate calls
def cache_clear():
    _clear_main_cache()

def cache_clear_meta():
    _clear_meta_cache()

def cache_clear_providers():
    _clear_providers_cache()

def cache_clear_debrid():
    _clear_debrid_cache()

def cache_clear_search():
    _clear_search_cache()

# Update cache_clear_all to use the new general function
def cache_clear_all():
    clear_caches()  # Clears all by default

def cache_clear_all_old():
    cache_clear()
    cache_clear_meta()
    cache_clear_providers()
    cache_clear_debrid()

def _dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


@contextmanager
def _db_cursor(db_path):
    """Open a DB connection, yield a cursor, auto-commit on success and always close.

    WAL journal mode: readers never block writers and writers never block readers —
    only writer-vs-writer contention exists, and each write completes in ~1-2ms.
    timeout=5: safety net for pathological cases (disk pressure, AV lock on Windows);
    in practice no thread comes close to it because each write hold is microseconds.
    """
    control.makeFile(control.dataPath)
    conn = db.connect(db_path, timeout=5)
    conn.row_factory = _dict_factory
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _get_connection_cursor():
    return _db_cursor(control.cacheFile)

def _get_connection_cursor_meta():
    return _db_cursor(control.metacacheFile)

def _get_connection_cursor_providers():
    return _db_cursor(control.providercacheFile)

def _get_connection_cursor_debrid():
    return _db_cursor(control.dbFile)

def _get_connection_cursor_search():
    return _db_cursor(control.searchFile)


def _hash_function(function_instance, *args):
    return _get_function_name(function_instance) + _generate_md5(args)


def get_poster_from_tmdb(tmdb_id):
    """
    Fetch poster URL from TMDB for a show.

    This uses the same TMDB images API that returns backdrops, posters, and logos.
    Returns the first English poster, or first poster if no English one found.

    Args:
        tmdb_id: TMDB ID of the show

    Returns:
        str: Full poster URL, or '0' if not found
    """
    try:
        if not tmdb_id or tmdb_id in ('None', '0'):
            c.log(f"[Cache] Skipping poster fetch for invalid tmdb_id: {tmdb_id}")
            return '0'

        import requests
        from . import keys

        tmdb_api_key = keys.tmdb_key
        url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/images?api_key={tmdb_api_key}"

        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            return '0'

        result = response.json()
        posters = result.get('posters', [])

        if not posters:
            return '0'

        # Prefer English posters, fallback to any poster
        en_posters = [p for p in posters if p.get('iso_639_1') == 'en']
        selected_poster = en_posters[0] if en_posters else posters[0]

        poster_path = selected_poster.get('file_path')
        if not poster_path:
            return '0'

        # Build full URL (original size for best quality)
        poster_url = f"https://image.tmdb.org/t/p/original{poster_path}"

        return poster_url

    except Exception as e:
        c.log(f"[Cache] Error fetching poster from TMDB: {e}")
        c.log(f"[Cache] Traceback: {traceback.format_exc()}")
        return '0'



def get_episode_details(show_tmdb, season, episode):
    """
    Get cached episode details (title, plot, runtime, air_date) from TMDB.
    Cache expires after 7 days (episodes rarely change once aired).

    Args:
        show_tmdb: TMDB ID for the show
        season: Season number
        episode: Episode number

    Returns:
        Dict with keys: title, plot, duration, air_date (or None if failed)
    """
    import time
    import json
    from . import keys, client

    # Validate show_tmdb before making API call
    if not show_tmdb or show_tmdb in ('None', '0'):
        c.log(f"[Cache] Skipping episode details fetch for invalid show_tmdb: {show_tmdb}")
        return None

    try:
        cursor = _get_connection_cursor()

        # Create episode_cache table if needed
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS episode_cache (
                show_tmdb TEXT,
                season INTEGER,
                episode INTEGER,
                details TEXT,
                added INTEGER,
                PRIMARY KEY (show_tmdb, season, episode)
            )
        """)
        cursor.connection.commit()

        # Check cache (7 days expiry - episodes don't change after airing)
        SEVENDAYS = 604800
        now = int(time.time())

        cursor.execute(
            "SELECT details FROM episode_cache WHERE show_tmdb=? AND season=? AND episode=? AND added > ?",
            (str(show_tmdb), season, episode, now - SEVENDAYS)
        )
        row = cursor.fetchone()

        if row:
            details = json.loads(row['details']) if isinstance(row['details'], str) else row['details']
            return details

        # Fetch from TMDB
        tmdb_key = keys.tmdb_key
        url = f'https://api.themoviedb.org/3/tv/{show_tmdb}/season/{season}/episode/{episode}?api_key={tmdb_key}&append_to_response=credits'

        episode_data = client.request(url, timeout='10')
        if not episode_data:
            return None

        episode_json = json.loads(episode_data)

        # Extract relevant fields
        details = {
            'title': episode_json.get('name', ''),
            'plot': episode_json.get('overview', ''),
            'duration': episode_json.get('runtime'),
            'air_date': episode_json.get('air_date', '')
        }

        # Extract cast info
        credits = episode_json.get('credits', {})
        cast_list = credits.get('cast', [])

        # Sort by order (0 = lead, higher = supporting/guest)
        cast_list_sorted = sorted(cast_list, key=lambda x: x.get('order', 999))

        # Get top 3 leads (order 0-2)
        leads = []
        for actor in cast_list_sorted[:10]:  # Check first 10
            if actor.get('order', 999) <= 2:
                leads.append({
                    'name': actor.get('name', ''),
                    'character': actor.get('character', ''),
                    'thumb': f"https://image.tmdb.org/t/p/w185{actor['profile_path']}" if actor.get('profile_path') else '',
                    'order': actor.get('order', 999)
                })
            if len(leads) >= 3:
                break

        # Get guest stars (order > 10, limit to 2)
        guests = []
        for actor in cast_list_sorted:
            if actor.get('order', 999) > 10:
                guests.append({
                    'name': actor.get('name', ''),
                    'character': actor.get('character', ''),
                    'thumb': f"https://image.tmdb.org/t/p/w185{actor['profile_path']}" if actor.get('profile_path') else '',
                    'order': actor.get('order', 999)
                })
            if len(guests) >= 2:
                break

        details['cast_leads'] = leads
        details['cast_guests'] = guests

        # Cache the details
        cursor.execute("""
            INSERT OR REPLACE INTO episode_cache
            (show_tmdb, season, episode, details, added)
            VALUES (?, ?, ?, ?, ?)
        """, (str(show_tmdb), season, episode, json.dumps(details), now))
        cursor.connection.commit()

        return details

    except Exception as e:
        c.log(f"[Cache] Error getting episode details: {e}")
        return None


def get_season_artwork(show_tmdb, season):
    """
    Get cached season poster URL from TMDB.
    Cache expires after 30 days (seasons rarely get new posters).

    Args:
        show_tmdb: TMDB ID for the show
        season: Season number

    Returns:
        Full poster URL (or None if failed)
    """
    import time
    import json
    from . import keys, client

    # Validate show_tmdb before making API call
    if not show_tmdb or show_tmdb in ('None', '0'):
        c.log(f"[Cache] Skipping season artwork fetch for invalid show_tmdb: {show_tmdb}")
        return None

    try:
        cursor = _get_connection_cursor()

        # Create season_cache table if needed
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS season_cache (
                show_tmdb TEXT,
                season INTEGER,
                poster_url TEXT,
                added INTEGER,
                PRIMARY KEY (show_tmdb, season)
            )
        """)
        cursor.connection.commit()

        # Check cache (30 days expiry - season posters rarely change)
        THIRTYDAYS = 2592000
        now = int(time.time())

        cursor.execute(
            "SELECT poster_url FROM season_cache WHERE show_tmdb=? AND season=? AND added > ?",
            (str(show_tmdb), season, now - THIRTYDAYS)
        )
        row = cursor.fetchone()

        if row and row['poster_url']:
            return row['poster_url']

        # Fetch from TMDB
        tmdb_key = keys.tmdb_key
        url = f'https://api.themoviedb.org/3/tv/{show_tmdb}/season/{season}?api_key={tmdb_key}'

        season_data = client.request(url, timeout='10')
        if not season_data:
            return None

        season_json = json.loads(season_data)
        poster_path = season_json.get('poster_path', '')

        if not poster_path:
            return None

        poster_url = f'https://image.tmdb.org/t/p/w500{poster_path}'

        # Cache the URL
        cursor.execute("""
            INSERT OR REPLACE INTO season_cache
            (show_tmdb, season, poster_url, added)
            VALUES (?, ?, ?, ?)
        """, (str(show_tmdb), season, poster_url, now))
        cursor.connection.commit()

        return poster_url

    except Exception as e:
        c.log(f"[Cache] Error getting season artwork: {e}")
        return None


def get_show_artwork(show_tmdb):
    """
    Get cached show backdrop URL from TMDB.
    Cache expires after 30 days (show backdrops rarely change).    Args:
        show_tmdb: TMDB ID for the show

    Returns:
        Full backdrop URL (or None if failed)
    """
    import time
    import json
    from . import keys, client

    # Validate show_tmdb before making API call
    if not show_tmdb or show_tmdb in ('None', '0'):
        c.log(f"[Cache] Skipping show artwork fetch for invalid show_tmdb: {show_tmdb}")
        return None

    try:
        cursor = _get_connection_cursor()

        # Create show_cache table if needed
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS show_cache (
                show_tmdb TEXT PRIMARY KEY,
                backdrop_url TEXT,
                added INTEGER
            )
        """)
        cursor.connection.commit()

        # Check cache (30 days expiry - show backdrops rarely change)
        THIRTYDAYS = 2592000
        now = int(time.time())

        cursor.execute(
            "SELECT backdrop_url FROM show_cache WHERE show_tmdb=? AND added > ?",
            (str(show_tmdb), now - THIRTYDAYS)
        )
        row = cursor.fetchone()

        if row and row['backdrop_url']:
            return row['backdrop_url']

        # Fetch from TMDB
        tmdb_key = keys.tmdb_key
        url = f'https://api.themoviedb.org/3/tv/{show_tmdb}?api_key={tmdb_key}'

        show_data = client.request(url, timeout='10')
        if not show_data:
            return None

        show_json = json.loads(show_data)
        backdrop_path = show_json.get('backdrop_path', '')

        if not backdrop_path:
            return None

        backdrop_url = f'https://image.tmdb.org/t/p/original{backdrop_path}'

        # Cache the URL
        cursor.execute("""
            INSERT OR REPLACE INTO show_cache
            (show_tmdb, backdrop_url, added)
            VALUES (?, ?, ?)
        """, (str(show_tmdb), backdrop_url, now))
        cursor.connection.commit()

        return backdrop_url

    except Exception as e:
        c.log(f"[Cache] Error getting show artwork: {e}")
        return None

def get_diverse_backdrop_pool(limit=20):
    """
    Extract backdrop URLs from multiple shows in the cache for variety.
    Returns a list of dicts with tmdb_id and fanart URL from user's recently cached shows.

    This provides beautiful variety by using shows the user actually watches,
    instead of just using the current episode's show.

    Args:
        limit: Maximum number of different shows to return (default 20)

    Returns:
        List of dicts: [{'tmdb': '12345', 'fanart': 'https://...'}, ...]
    """
    try:
        cursor = _get_connection_cursor()

        # Query cache for recent show entries with fanart
        # Look for cached episode/show data that has fanart URLs
        cursor.execute("""
            SELECT DISTINCT value
            FROM cache
            WHERE value LIKE '%fanart%'
            AND value LIKE '%tmdb%'
            ORDER BY date DESC
            LIMIT 100
        """)

        rows = cursor.fetchall()

        # Extract unique show TMDB IDs and fanart URLs
        shows = {}  # Use dict to dedupe by tmdb_id
        for row in rows:
            try:
                # Parse the cached JSON value
                value = row['value'] if isinstance(row, dict) else row[0]

                # Handle JSON string or pickled data
                if isinstance(value, str) and value.startswith('['):
                    items = json.loads(value)
                    if not isinstance(items, list):
                        items = [items]

                    for item in items:
                        if not isinstance(item, dict):
                            continue

                        # Extract tmdb and fanart
                        tmdb_id = item.get('tmdb', '0')
                        fanart_url = item.get('fanart', '0')

                        # Only add if both are valid and not already in dict
                        if (tmdb_id != '0' and fanart_url != '0' and
                            'http' in fanart_url and tmdb_id not in shows):
                            shows[tmdb_id] = {
                                'tmdb': tmdb_id,
                                'fanart': fanart_url
                            }

                            # Stop if we have enough
                            if len(shows) >= limit:
                                break

            except Exception as e:
                # Skip malformed entries
                continue

            if len(shows) >= limit:
                break

        result = list(shows.values())
        return result

    except Exception as e:
        c.log(f"[Cache] Error getting diverse backdrop pool: {e}")
        return []


def _get_function_name(function_instance):
    return re.sub(r'.+\smethod\s|.+function\s|\sat\s.+|\sof\s.+', '', repr(function_instance))


def _generate_md5(*args):
    md5_hash = hashlib.md5()
    args = utils.traverse(args)
    for arg in args:
        if isinstance(arg, str):
            md5_hash.update(arg.encode('utf-8', errors='replace'))
        elif isinstance(arg, bytes):
            md5_hash.update(arg)
        else:
            md5_hash.update(str(arg).encode('utf-8', errors='replace'))
    return str(md5_hash.hexdigest())


def _is_cache_valid(cached_time, cache_timeout):
    now = int(time.time())
    diff = now - cached_time
    return (cache_timeout * 3600) > diff


def cache_version_check():
    if _find_cache_version():
        control.infoDialog(control.lang(32057), sound=True, icon='INFO') # Keep calm and expect us!


def _find_cache_version():
    version_file = os.path.join(control.dataPath, 'cache.v')
    try:
        with open(version_file, 'r', encoding="utf8") as fh:
            old_version = fh.read()
    except (IOError, OSError, Exception):
        old_version = '0'  # File read failed

    try:
        cur_version = control.addon('script.module.thecrew').getAddonInfo('version')
        if old_version != cur_version:
            with open(version_file, 'w', encoding="utf8") as fh:
                fh.write(cur_version)
            return True
        return False
    except (IOError, OSError, Exception):
        return False  # Version check/write failed