# -*- coding: utf-8 -*-

'''
 *******************************************************cm**
 * The Crew Add-on - Progress Indexer
 *
 * @package script.module.thecrew
 *
 * Clean implementation of Trakt progress features using new model classes.
 * Provides three main features:
 *   1. In Progress Shows - TV shows you're watching (alphabetical, show posters)
 *   2. Next Episodes - Next unwatched episodes to watch (auto-advance)
 *   3. In Progress Episodes - Episodes with resume points (partially watched)
 *
 * @copyright (c) 2025-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 *******************************************************cm**
'''

import concurrent.futures
import threading
import traceback
from contextlib import suppress

from ..models.tvshow import TVShow
from ..models.episode import Episode
from ..modules import trakt
from ..modules import cache
from ..modules import control
from ..modules import workers
from ..modules import keys
from ..modules.crewruntime import c


class Progress:
    """
    Indexer for Trakt progress features.
    Uses clean model classes (TVShow, Episode) instead of monolithic approach.
    """

    def __init__(self):
        self.list = []
        self.trakt_user = c.get_setting('trakt.username').strip()
        self.lang = control.apiLanguage()['trakt']
        self.hidecinema = c.get_setting('hidecinema') == 'true'

        # Trakt API endpoints
        self.progress_link = 'https://api.trakt.tv/sync/watched/shows'
        self.trakthistory_link = 'https://api.trakt.tv/sync/history/episodes?limit=25'

    def get_in_progress_shows(self, page=None):
        """
        Get list of TV shows user is currently watching.
        Returns show-level objects (not episodes) sorted by most recently watched.

        Filters out:
        - Shows that are both ended AND fully watched
        - Shows hidden from calendar via Trakt

        When set to ICONS view, shows TV show posters (like Gears).
        User can select show to see seasons/episodes.

        Args:
            page: Page number (1-based). None/1 = first page.

        Returns:
            list: List of TVShow objects as dicts
        """
        PAGE_SIZE = 25
        try:
            page = max(1, int(page)) if page else 1
        except (ValueError, TypeError):
            page = 1
        try:
            c.log("[Progress] Fetching In Progress Shows")

            # Get hidden shows from Trakt (to filter them out)
            hidden_shows = set()
            try:
                hidden_url = "https://api.trakt.tv/users/hidden/calendar?type=show&limit=1000"
                hidden_result = trakt.getTraktAsJson(hidden_url)
                if hidden_result:
                    hidden_shows = {
                        str(item.get('show', {}).get('ids', {}).get('trakt'))
                        for item in hidden_result
                        if item.get('show', {}).get('ids', {}).get('trakt')
                    }
                    c.log(f"[Progress] Found {len(hidden_shows)} hidden shows")
            except Exception as e:
                c.log(f"[Progress] Could not fetch hidden shows: {e}")

            # Get progress from Trakt
            url = f"{self.progress_link}?extended=full"
            result = trakt.getTraktAsJson(url)

            if not result:
                c.log("[Progress] No Trakt progress data")
                self.list = []
                self.shows_directory(self.list)
                return self.list

            # --- Phase 0: Build TVShow objects from Trakt data only (no network) ---
            show_items = []  # [{'show': TVShow, 'last_watched_at': str}]
            filtered_count = 0
            for item in result:
                try:
                    show_data = item.get('show', {})
                    status = show_data.get('status', '').lower()
                    aired_episodes = int(show_data.get('aired_episodes', 0))
                    show_ids = show_data.get('ids', {})
                    trakt_id = str(show_ids.get('trakt', '0'))
                    showtmdb = str(show_ids.get('tmdb', '0'))

                    # Filter: hidden shows
                    if trakt_id in hidden_shows:
                        filtered_count += 1
                        continue

                    # Filter: ended/canceled AND fully watched
                    seasons = item.get('seasons', [])
                    if isinstance(seasons, dict):
                        seasons = list(seasons.values())
                    watched_count = sum(
                        len(s.get('episodes', []))
                        for s in seasons if s.get('number', 0) > 0
                    )
                    if status in ['ended', 'canceled'] and watched_count >= aired_episodes and aired_episodes > 0:
                        filtered_count += 1
                        continue

                    if not showtmdb or showtmdb in ('None', '0'):
                        continue

                    show = TVShow.from_trakt_progress(item)
                    if not show:
                        continue

                    # Find most recent watched timestamp
                    last_timestamp = None
                    for s in sorted((s for s in seasons if s.get('number', 0) > 0), key=lambda s: s.get('number', 0)):
                        for e in (s.get('episodes') or []):
                            ts = e.get('last_watched_at')
                            if ts and (last_timestamp is None or ts > last_timestamp):
                                last_timestamp = ts
                    show.last_watched_at = last_timestamp

                    show_items.append({'show': show, 'last_watched_at': last_timestamp})
                except Exception as e:
                    c.log(f"[Progress] Phase 0 show error: {e}")

            if filtered_count:
                c.log(f"[Progress] Filtered out {filtered_count} hidden/completed shows")
            c.log(f"[Progress] Phase 0: {len(show_items)} in-progress shows")

            # Sort by most recently watched
            show_items.sort(
                key=lambda si: si['last_watched_at'] or '1900-01-01T00:00:00.000Z',
                reverse=True
            )

            # Slice to current page
            start = (page - 1) * PAGE_SIZE
            end = start + PAGE_SIZE
            page_items = show_items[start:end]
            bg_items = show_items[end:]  # background warm only

            # Warm/cold split: check SQLite cache for each show's TMDB data
            from ..modules import http_client
            import json as _json
            import time as _time

            def _show_url(si):
                tmdb = si['show'].tmdb
                return (f"https://api.themoviedb.org/3/tv/{tmdb}"
                        f"?api_key={keys.tmdb_key}&language={self.lang}")

            def _show_cache_key(si):
                return cache._hash_function(http_client.tmdb_get_json, _show_url(si), 16)

            warm_items, cold_items = [], []
            for si in page_items:
                ck = _show_cache_key(si)
                cached = cache.cache_get(ck, timeout=None)  # any cached data → warm
                if cached:
                    warm_items.append((si, ck, cached))
                else:
                    cold_items.append((si, ck))
            c.log(f"[Progress] Page {page}: warm={len(warm_items)}, cold={len(cold_items)}, bg={len(bg_items)}")

            # Warm: apply from SQLite cache (no network)
            for si, ck, cached_entry in warm_items:
                try:
                    val = cached_entry.get('value')
                    resp = _json.loads(val) if isinstance(val, str) else val
                    if resp:
                        si['show']._parse_tmdb_response(resp)
                except Exception as e:
                    c.log(f"[Progress] Warm apply error: {e}")

            # Cold: parallel pure-HTTP fetch, then serial SQLite write
            def _show_fetch_raw(task):
                ck, url, si = task
                try:
                    resp = http_client.tmdb_get_json(url)
                    return ck, url, si, resp
                except Exception:
                    return ck, url, si, None

            if cold_items:
                cold_tasks = [(ck, _show_url(si), si) for si, ck in cold_items]
                n = min(len(cold_tasks), 25)
                c.log(f"[Progress] Show inline HTTP: {len(cold_tasks)} requests ({n} workers)")
                t0 = _time.time()
                cold_results = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
                    futs = [pool.submit(_show_fetch_raw, t) for t in cold_tasks]
                    for f in concurrent.futures.as_completed(futs):
                        with suppress(Exception):
                            cold_results.append(f.result())
                c.log(f"[Progress] Show inline HTTP done: {sum(1 for r in cold_results if r[3])}/{len(cold_tasks)} in {_time.time()-t0:.2f}s")
                for ck, url, si, resp in cold_results:
                    if resp:
                        with suppress(Exception):
                            cache.cache_insert(ck, _json.dumps(resp))
                        with suppress(Exception):
                            si['show']._parse_tmdb_response(resp)

            # Background warm: cache pages beyond current page for instant next-page loads
            if bg_items:
                def _show_bg_warm(items):
                    try:
                        bg_tasks = []
                        for si in items:
                            ck = _show_cache_key(si)
                            if not cache.cache_get(ck, timeout=24):  # skip if already fresh
                                bg_tasks.append((ck, _show_url(si), si))
                        if not bg_tasks:
                            c.log("[Progress] Show bg warm: all already cached")
                            return
                        n_bg = min(len(bg_tasks), 20)
                        bg_results = []
                        with concurrent.futures.ThreadPoolExecutor(max_workers=n_bg) as pool:
                            futs = [pool.submit(_show_fetch_raw, t) for t in bg_tasks]
                            for f in concurrent.futures.as_completed(futs):
                                with suppress(Exception):
                                    bg_results.append(f.result())
                        for ck, url, si, resp in bg_results:
                            if resp:
                                with suppress(Exception):
                                    cache.cache_insert(ck, _json.dumps(resp))
                        c.log(f"[Progress] Show bg warm done: {sum(1 for r in bg_results if r[3])}/{len(bg_tasks)} cached")
                    except Exception as ex:
                        c.log(f"[Progress] Show bg warm error: {ex}")

                threading.Thread(target=_show_bg_warm, args=(bg_items,), daemon=True, name="CrewShowWarm").start()

            # Build final list sliced to current page
            all_shows = [si['show'].to_dict() for si in show_items]
            all_shows.sort(
                key=lambda x: x.get('last_watched_at') or '1900-01-01T00:00:00.000Z',
                reverse=True
            )
            page_shows = all_shows[start:end]
            has_next = end < len(all_shows)

            import sys as _sys
            _base_url = (_sys.argv[0] + '?action=progress_shows') if _sys.argv else ''
            next_url = (f'{_base_url}&page={page + 1}') if has_next else None
            _total_pages = (len(all_shows) + PAGE_SIZE - 1) // PAGE_SIZE
            next_label = (f"{c.lang(30500) or 'Next Page'} (Page {page + 1} of {_total_pages})") if has_next else None

            self.list = page_shows
            c.log(f"[Progress] Rendering page {page}: items {start+1}-{min(end, len(all_shows))} of {len(all_shows)} ({len(warm_items)} warm, {len(cold_items)} cold)")
            self.shows_directory(self.list, next_url=next_url, next_label=next_label)
            return self.list

        except Exception as e:
            c.log(f"[Progress] Error in get_in_progress_shows: {e}")
            self.list = []
            self.shows_directory(self.list)
            return self.list

    def get_next_episodes(self, page=None):
        """
        Get next unwatched episodes user should watch.
        Auto-advances to first unwatched episode of each show.

        Args:
            page: Page number (1-based string or int). None/1 = first page.

        Returns:
            list: List of Episode objects as dicts
        """
        PAGE_SIZE = 25
        try:
            page = max(1, int(page)) if page else 1
        except (ValueError, TypeError):
            page = 1
        try:
            c.log("[Progress] Fetching Next Episodes")

            # Fetch Trakt progress (ETag-cached, 5 min TTL)
            url = f"{self.progress_link}?extended=full"

            def fetch_progress_data(conditional_headers=None):
                return trakt.get_trakt(url, conditional_headers=conditional_headers)

            cache_key = f"trakt_next_episodes_{hash(url)}"
            result = cache.get_with_etag(cache_key, fetch_progress_data, ttl_seconds=300, namespace='trakt')

            if not result:
                from resources.lib.modules import control
                auth_failed = control.window.getProperty('thecrew.trakt_auth_failed') == 'true'
                if not auth_failed:
                    # Transient failure (e.g. network not ready at boot) — retry once
                    c.log("[Progress] No Trakt progress data - retrying in 3s")
                    import time as _time
                    _time.sleep(3)
                    result = cache.get_with_etag(cache_key, fetch_progress_data, ttl_seconds=300, namespace='trakt')

            if not result:
                c.log("[Progress] No Trakt progress data - check Trakt authentication")
                from resources.lib.modules import control
                auth_failed = control.window.getProperty('thecrew.trakt_auth_failed') == 'true'
                already_notified = control.window.getProperty('thecrew.trakt_auth_notified') == 'true'
                if auth_failed and not already_notified:
                    control.window.setProperty('thecrew.trakt_auth_notified', 'true')
                    control.infoDialog("Please check Trakt authentication in The Crew settings", heading="Next Episodes Unavailable")
                self.list = []
                self.episodes_directory(self.list)
                return self.list

            # Widget context detection (preserved: after Container.Refresh PluginName changes)
            is_widget = c.is_widget_listing()
            import xbmcgui as _xbmcgui
            if not is_widget and _xbmcgui.Window(10000).getProperty('crew.widget.context') == '1':
                is_widget = True
            _xbmcgui.Window(10000).clearProperty('crew.widget.context')
            c.log(f"[Progress] NextEpisodes Widget Detection: is_widget={is_widget}")

            # --- Phase 0: Build list from Trakt data alone (~0ms, no network) ---
            # Pure math: find next unwatched episode for each show.
            next_items = []  # [{'show_data', 'season', 'episode', 'last_watched_at'}]
            for item in result:
                try:
                    show_data = item.get('show', {})
                    seasons = item.get('seasons', [])
                    if isinstance(seasons, dict):
                        seasons = list(seasons.values())

                    num_watched = sum(len(s.get('episodes', [])) for s in seasons if s.get('number', 0) > 0)
                    aired_episodes = int(show_data.get('aired_episodes', 0))
                    if num_watched >= aired_episodes and aired_episodes > 0:
                        continue  # fully watched

                    max_season = max_episode = 0
                    last_watched_at = None
                    for s in [s for s in seasons if s.get('number', 0) > 0]:
                        eps = s.get('episodes') or []
                        if eps:
                            max_ep = max(e.get('number', 0) for e in eps)
                            sn = s.get('number')
                            if sn > max_season or (sn == max_season and max_ep > max_episode):
                                max_season, max_episode = sn, max_ep
                                for e in eps:
                                    if e.get('number') == max_ep:
                                        last_watched_at = e.get('last_watched_at')
                                        break

                    next_season = 1 if max_season == 0 else max_season
                    next_episode = 1 if max_season == 0 else max_episode + 1
                    showtmdb = str(show_data.get('ids', {}).get('tmdb') or '0')
                    if not showtmdb or showtmdb in ('None', '0'):
                        continue

                    next_items.append({
                        'show_data': show_data,
                        'season': next_season,
                        'episode': next_episode,
                        'last_watched_at': last_watched_at,
                    })
                except Exception as e:
                    c.log(f"[Progress] Error scanning show: {e}")

            # Build Episode objects from Trakt data (no TMDB fetch)
            for ni in next_items:
                ep = Episode.from_trakt_progress(ni['show_data'], ni['season'], ni['episode'])
                if ep:
                    ep.last_watched_at = ni['last_watched_at']
                    ni['ep'] = ep
            next_items = [ni for ni in next_items if 'ep' in ni]
            next_items.sort(key=lambda ni: ni['last_watched_at'] or '1900-01-01T00:00:00.000Z', reverse=True)
            c.log(f"[Progress] Phase 0: {len(next_items)} shows with next episodes")

            # Slice to current page before any network/SQLite work
            start = (page - 1) * PAGE_SIZE
            end = start + PAGE_SIZE
            page_items = next_items[start:end]
            bg_items = next_items[end:]  # everything beyond this page — background warm only

            # Single SQL query: which page episodes are already in metadata cache?
            meta_keys = [
                Episode.get_metadata_cache_key_minimal(ni['ep'].showtmdb, ni['ep'].season, ni['ep'].episode, self.lang)
                for ni in page_items
            ]
            metadata_cache_dict = cache.cache_get_many(meta_keys, timeout=24) if meta_keys else {}

            warm_items, cold_items = [], []
            for ni in page_items:
                key = Episode.get_metadata_cache_key_minimal(ni['ep'].showtmdb, ni['ep'].season, ni['ep'].episode, self.lang)
                if key in metadata_cache_dict:
                    warm_items.append(ni)
                else:
                    cold_items.append(ni)
            c.log(f"[Progress] Page {page}: warm={len(warm_items)}, cold={len(cold_items)}, bg_warm={len(bg_items)}")

            # Enrich warm episodes inline from SQLite (no network, instant)
            from ..modules import http_client
            show_artwork = {}  # artwork dedup by showtmdb

            def _apply_artwork(ep):
                sid = ep.showtmdb
                if not sid or sid in ('0', 'None'):
                    return
                if sid not in show_artwork:
                    art_url = (f"https://api.themoviedb.org/3/tv/{sid}"
                               f"?api_key={keys.tmdb_key}&language={self.lang}&append_to_response=external_ids")
                    cached = cache.cache_get(cache._hash_function(http_client.tmdb_get_json, art_url, 16), timeout=None)
                    if cached:
                        import json as _json
                        try:
                            resp = _json.loads(cached['value']) if isinstance(cached['value'], str) else cached['value']
                        except Exception:
                            resp = {}
                        show_artwork[sid] = resp if (resp and isinstance(resp, dict)) else {}
                    else:
                        show_artwork[sid] = {}
                resp = show_artwork.get(sid, {})
                if resp.get('poster_path'):
                    ep.poster = f"https://image.tmdb.org/t/p/{c.tmdb_postersize}{resp['poster_path']}"
                if resp.get('backdrop_path'):
                    ep.fanart = f"https://image.tmdb.org/t/p/{c.tmdb_fanartsize}{resp['backdrop_path']}"
                    if not ep.thumb or ep.thumb == '0':
                        ep.thumb = ep.fanart

            for ni in warm_items:
                ni['ep'].fetch_tmdb_metadata_minimal(metadata_cache_dict=metadata_cache_dict)
                _apply_artwork(ni['ep'])

            import json as _json
            import time as _time

            def fetch_raw(task):
                ck, url, tag, ni = task
                try:
                    resp = http_client.tmdb_get_json(url)
                    return ck, url, tag, ni, resp
                except Exception:
                    return ck, url, tag, ni, None

            def build_http_tasks(items, seen_art_set):
                tasks = []
                for ni in items:
                    ep = ni['ep']
                    ep_url = (f"https://api.themoviedb.org/3/tv/{ep.showtmdb}"
                              f"/season/{ep.season}/episode/{ep.episode}"
                              f"?api_key={keys.tmdb_key}&language={self.lang}")
                    ep_key = cache._hash_function(http_client.tmdb_get_json, ep_url, 16)
                    tasks.append((ep_key, ep_url, 'ep', ni))
                    sid = ep.showtmdb
                    if sid and sid not in ('0', 'None') and sid not in seen_art_set and sid not in show_artwork:
                        seen_art_set.add(sid)
                        art_url = (f"https://api.themoviedb.org/3/tv/{sid}"
                                   f"?api_key={keys.tmdb_key}&language={self.lang}"
                                   f"&append_to_response=external_ids")
                        art_key = cache._hash_function(http_client.tmdb_get_json, art_url, 16)
                        tasks.append((art_key, art_url, 'art', ni))
                return tasks

            def apply_results(raw_results, target_items):
                """Apply HTTP results to Episode objects and write to SQLite. Returns list of 404 items."""
                ep_404s = []
                for ck, url, tag, ni, resp in raw_results:
                    if resp is None:
                        if tag == 'ep':
                            ep_404s.append(ni)
                        continue
                    with suppress(Exception):
                        cache.cache_insert(ck, _json.dumps(resp))
                    if tag == 'ep':
                        ep = ni['ep']
                        ep._parse_tmdb_response_minimal(resp)
                        with suppress(Exception):
                            trakt.update_next_episode_cache(int(ep.showtmdb), ep.season, ep.episode, True)
                    elif tag == 'art':
                        sid = ni['ep'].showtmdb
                        show_artwork[sid] = resp if isinstance(resp, dict) else {}
                # Fill missing artwork entries so _apply_artwork skips SQLite lookup
                for ni in target_items:
                    sid = ni['ep'].showtmdb
                    if sid and sid not in show_artwork:
                        show_artwork[sid] = {}
                return ep_404s

            def run_fallbacks(ep_404_items, fetch_fn):
                """Season-boundary fallbacks: episode 404 → try season+1 E01."""
                fallback_tasks = []
                for ni in ep_404_items:
                    ep = ni['ep']
                    if ep.episode > 1:
                        fb_url = (f"https://api.themoviedb.org/3/tv/{ep.showtmdb}"
                                  f"/season/{ep.season + 1}/episode/1"
                                  f"?api_key={keys.tmdb_key}&language={self.lang}")
                        fb_key = cache._hash_function(http_client.tmdb_get_json, fb_url, 16)
                        fallback_tasks.append((fb_key, fb_url, 'ep_fallback', ni))
                    else:
                        with suppress(Exception):
                            trakt.update_next_episode_cache(int(ep.showtmdb), ep.season, ep.episode, False)
                if not fallback_tasks:
                    return
                n_fb = min(len(fallback_tasks), 20)
                fb_results = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=n_fb) as pool:
                    futs = [pool.submit(fetch_fn, t) for t in fallback_tasks]
                    for f in concurrent.futures.as_completed(futs):
                        with suppress(Exception):
                            fb_results.append(f.result())
                for fb_key, fb_url, tag, ni, resp in fb_results:
                    ep = ni['ep']
                    if resp:
                        ep.season += 1
                        ep.episode = 1
                        ep._parse_tmdb_response_minimal(resp)
                        with suppress(Exception):
                            cache.cache_insert(fb_key, _json.dumps(resp))
                            trakt.update_next_episode_cache(int(ep.showtmdb), ep.season, ep.episode, True)
                    else:
                        with suppress(Exception):
                            trakt.update_next_episode_cache(int(ep.showtmdb), ep.season, ep.episode, False)

            # --- Inline enrichment: all cold items on this page ---
            if cold_items:
                seen_art_inline = set()
                inline_tasks = build_http_tasks(cold_items, seen_art_inline)
                n = min(len(inline_tasks), 25)
                c.log(f"[Progress] Inline HTTP: {len(inline_tasks)} requests ({n} workers)")
                t0 = _time.time()
                inline_results = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
                    futs = [pool.submit(fetch_raw, t) for t in inline_tasks]
                    for f in concurrent.futures.as_completed(futs):
                        with suppress(Exception):
                            inline_results.append(f.result())
                c.log(f"[Progress] Inline HTTP done: {sum(1 for r in inline_results if r[4])}/{len(inline_tasks)} in {_time.time()-t0:.2f}s")
                ep_404s = apply_results(inline_results, cold_items)
                run_fallbacks(ep_404s, fetch_raw)
                for ni in cold_items:
                    _apply_artwork(ni['ep'])

            # --- Background cache-warming: items beyond this page ---
            # Silently warms SQLite so next pages load instantly.
            if bg_items:
                def _bg_warm(items):
                    try:
                        seen_bg = set(show_artwork.keys())
                        bg_tasks = build_http_tasks(items, seen_bg)
                        n_bg = min(len(bg_tasks), 20)
                        bg_results = []
                        with concurrent.futures.ThreadPoolExecutor(max_workers=n_bg) as pool:
                            futs = [pool.submit(fetch_raw, t) for t in bg_tasks]
                            for f in concurrent.futures.as_completed(futs):
                                with suppress(Exception):
                                    bg_results.append(f.result())
                        bg_404s = apply_results(bg_results, items)
                        run_fallbacks(bg_404s, fetch_raw)
                        c.log(f"[Progress] Background warm done: {sum(1 for r in bg_results if r[4])}/{len(bg_tasks)} cached")
                    except Exception as ex:
                        c.log(f"[Progress] Background warm error: {ex}")

                threading.Thread(target=_bg_warm, args=(bg_items,), daemon=True, name="CrewWidgetWarm").start()

            # Build final sorted list, slice to current page
            all_episodes = [ni['ep'].to_dict() for ni in next_items if 'ep' in ni]
            all_episodes.sort(key=lambda x: x.get('last_watched_at') or '1900-01-01T00:00:00.000Z', reverse=True)
            page_episodes = all_episodes[start:end]
            has_next = end < len(all_episodes)

            import sys as _sys
            _base_url = (_sys.argv[0] + '?action=progress_next_episodes') if _sys.argv else ''
            next_url = (f'{_base_url}&page={page + 1}') if has_next else None
            _total_pages = (len(all_episodes) + PAGE_SIZE - 1) // PAGE_SIZE
            next_label = (f"{c.lang(30500) or 'Next Page'} (Page {page + 1} of {_total_pages})") if has_next else None

            self.list = page_episodes
            c.log(f"[Progress] Rendering page {page}: items {start+1}-{min(end, len(all_episodes))} of {len(all_episodes)} ({len(warm_items)} warm, {len(cold_items)} inline-cold, {len(bg_items)} bg)")
            self.episodes_directory(self.list, next_url=next_url, next_label=next_label)
            return self.list

        except Exception as e:
            c.log(f"[Progress] Error in get_next_episodes: {e}")
            self.list = []
            self.episodes_directory(self.list)
            return self.list

    def get_in_progress_episodes(self, page=None):
        """
        Get episodes with resume points (partially watched).
        Shows episodes user started but hasn't finished (0% < progress < 92%).

        Args:
            page: Page number (1-based). None/1 = first page.

        Returns:
            list: List of Episode objects as dicts
        """
        PAGE_SIZE = 25
        try:
            page = max(1, int(page)) if page else 1
        except (ValueError, TypeError):
            page = 1
        try:
            c.log("[Progress] Fetching In Progress Episodes")

            # Get playback progress from Trakt (ETag-cached, 5 min TTL)
            url = "https://api.trakt.tv/sync/playback/episodes?extended=full"

            def fetch_playback_data(conditional_headers=None):
                return trakt.get_trakt(url, conditional_headers=conditional_headers)

            cache_key = f"trakt_playback_episodes_{hash(url)}"
            result = cache.get_with_etag(cache_key, fetch_playback_data, ttl_seconds=300, namespace='trakt')

            if not result:
                c.log("[Progress] No Trakt playback progress data")
                self.list = []
                self.episodes_directory(self.list)
                return self.list

            # --- Phase 0: Build Episode objects from Trakt data only (no network) ---
            prog_items = []  # [{'ep': Episode, 'last_watched_at': str}]
            for item in result:
                try:
                    progress = float(item.get('progress', 0))
                    if progress <= 0 or progress >= 92:
                        continue

                    episode_data = item.get('episode', {})
                    show_data = item.get('show', {})
                    season_num = episode_data.get('season')
                    episode_num = episode_data.get('number')
                    if not season_num or not episode_num:
                        continue

                    showtmdb = str(show_data.get('ids', {}).get('tmdb', '0'))
                    if not showtmdb or showtmdb in ('None', '0'):
                        continue

                    ep = Episode.from_trakt_progress(show_data, season_num, episode_num, episode_data)
                    if not ep:
                        continue

                    ep.resume_point = progress
                    paused_at = item.get('paused_at', '')
                    ep.last_watched_at = paused_at

                    prog_items.append({'ep': ep, 'last_watched_at': paused_at})
                except Exception as e:
                    c.log(f"[Progress] Phase 0 episode error: {e}")

            c.log(f"[Progress] Phase 0: {len(prog_items)} in-progress episodes")

            # Sort by most recently paused
            prog_items.sort(
                key=lambda pi: pi['last_watched_at'] or '1900-01-01T00:00:00.000Z',
                reverse=True
            )

            # Slice to current page
            start = (page - 1) * PAGE_SIZE
            end = start + PAGE_SIZE
            page_items = prog_items[start:end]
            bg_items = prog_items[end:]  # background warm only

            # Single SQL query: which page episodes are already in metadata cache?
            meta_keys = [
                Episode.get_metadata_cache_key_minimal(pi['ep'].showtmdb, pi['ep'].season, pi['ep'].episode, self.lang)
                for pi in page_items
            ]
            metadata_cache_dict = cache.cache_get_many(meta_keys, timeout=24) if meta_keys else {}

            warm_items, cold_items = [], []
            for pi in page_items:
                key = Episode.get_metadata_cache_key_minimal(pi['ep'].showtmdb, pi['ep'].season, pi['ep'].episode, self.lang)
                if key in metadata_cache_dict:
                    warm_items.append(pi)
                else:
                    cold_items.append(pi)
            c.log(f"[Progress] Page {page}: warm={len(warm_items)}, cold={len(cold_items)}, bg_warm={len(bg_items)}")

            # Enrich warm episodes inline from SQLite (no network, instant)
            from ..modules import http_client
            show_artwork = {}  # artwork dedup by showtmdb

            def _apply_artwork(ep):
                sid = ep.showtmdb
                if not sid or sid in ('0', 'None'):
                    return
                if sid not in show_artwork:
                    art_url = (f"https://api.themoviedb.org/3/tv/{sid}"
                               f"?api_key={keys.tmdb_key}&language={self.lang}&append_to_response=external_ids")
                    cached = cache.cache_get(cache._hash_function(http_client.tmdb_get_json, art_url, 16), timeout=None)
                    if cached:
                        import json as _json2
                        try:
                            resp = _json2.loads(cached['value']) if isinstance(cached['value'], str) else cached['value']
                        except Exception:
                            resp = {}
                        show_artwork[sid] = resp if (resp and isinstance(resp, dict)) else {}
                    else:
                        show_artwork[sid] = {}
                resp = show_artwork.get(sid, {})
                if resp.get('poster_path'):
                    ep.poster = f"https://image.tmdb.org/t/p/{c.tmdb_postersize}{resp['poster_path']}"
                if resp.get('backdrop_path'):
                    ep.fanart = f"https://image.tmdb.org/t/p/{c.tmdb_fanartsize}{resp['backdrop_path']}"
                    if not ep.thumb or ep.thumb == '0':
                        ep.thumb = ep.fanart

            for pi in warm_items:
                pi['ep'].fetch_tmdb_metadata_minimal(metadata_cache_dict=metadata_cache_dict)
                _apply_artwork(pi['ep'])

            import json as _json
            import time as _time

            def fetch_raw(task):
                ck, url, tag, pi = task
                try:
                    resp = http_client.tmdb_get_json(url)
                    return ck, url, tag, pi, resp
                except Exception:
                    return ck, url, tag, pi, None

            def build_http_tasks(items, seen_art_set):
                tasks = []
                for pi in items:
                    ep = pi['ep']
                    ep_url = (f"https://api.themoviedb.org/3/tv/{ep.showtmdb}"
                              f"/season/{ep.season}/episode/{ep.episode}"
                              f"?api_key={keys.tmdb_key}&language={self.lang}")
                    ep_key = cache._hash_function(http_client.tmdb_get_json, ep_url, 16)
                    tasks.append((ep_key, ep_url, 'ep', pi))
                    sid = ep.showtmdb
                    if sid and sid not in ('0', 'None') and sid not in seen_art_set and sid not in show_artwork:
                        seen_art_set.add(sid)
                        art_url = (f"https://api.themoviedb.org/3/tv/{sid}"
                                   f"?api_key={keys.tmdb_key}&language={self.lang}"
                                   f"&append_to_response=external_ids")
                        art_key = cache._hash_function(http_client.tmdb_get_json, art_url, 16)
                        tasks.append((art_key, art_url, 'art', pi))
                return tasks

            def apply_results(raw_results, target_items):
                for ck, url, tag, pi, resp in raw_results:
                    if resp is None:
                        continue
                    with suppress(Exception):
                        cache.cache_insert(ck, _json.dumps(resp))
                    if tag == 'ep':
                        pi['ep']._parse_tmdb_response_minimal(resp)
                    elif tag == 'art':
                        sid = pi['ep'].showtmdb
                        show_artwork[sid] = resp if isinstance(resp, dict) else {}
                for pi in target_items:
                    sid = pi['ep'].showtmdb
                    if sid and sid not in show_artwork:
                        show_artwork[sid] = {}

            # Inline cold enrichment (≤25 workers)
            if cold_items:
                seen_art_inline = set()
                inline_tasks = build_http_tasks(cold_items, seen_art_inline)
                n = min(len(inline_tasks), 25)
                c.log(f"[Progress] InProgress inline HTTP: {len(inline_tasks)} requests ({n} workers)")
                t0 = _time.time()
                inline_results = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
                    futs = [pool.submit(fetch_raw, t) for t in inline_tasks]
                    for f in concurrent.futures.as_completed(futs):
                        with suppress(Exception):
                            inline_results.append(f.result())
                c.log(f"[Progress] InProgress inline HTTP done: {sum(1 for r in inline_results if r[4])}/{len(inline_tasks)} in {_time.time()-t0:.2f}s")
                apply_results(inline_results, cold_items)
                for pi in cold_items:
                    _apply_artwork(pi['ep'])

            # Background cache-warming: items beyond this page
            if bg_items:
                def _bg_warm(items):
                    try:
                        seen_bg = set(show_artwork.keys())
                        bg_tasks = build_http_tasks(items, seen_bg)
                        n_bg = min(len(bg_tasks), 20)
                        bg_results = []
                        with concurrent.futures.ThreadPoolExecutor(max_workers=n_bg) as pool:
                            futs = [pool.submit(fetch_raw, t) for t in bg_tasks]
                            for f in concurrent.futures.as_completed(futs):
                                with suppress(Exception):
                                    bg_results.append(f.result())
                        for ck, url, tag, pi, resp in bg_results:
                            if resp:
                                with suppress(Exception):
                                    cache.cache_insert(ck, _json.dumps(resp))
                        c.log(f"[Progress] InProgress bg warm done: {sum(1 for r in bg_results if r[4])}/{len(bg_tasks)} cached")
                    except Exception as ex:
                        c.log(f"[Progress] InProgress bg warm error: {ex}")

                threading.Thread(target=_bg_warm, args=(bg_items,), daemon=True, name="CrewInProgWarm").start()

            # Build final sorted list, slice to current page
            all_episodes = [pi['ep'].to_dict() for pi in prog_items]
            all_episodes.sort(
                key=lambda x: x.get('last_watched_at') or '1900-01-01T00:00:00.000Z',
                reverse=True
            )
            page_episodes = all_episodes[start:end]
            has_next = end < len(all_episodes)

            import sys as _sys
            _base_url = (_sys.argv[0] + '?action=progress_in_progress_episodes') if _sys.argv else ''
            next_url = (f'{_base_url}&page={page + 1}') if has_next else None
            _total_pages = (len(all_episodes) + PAGE_SIZE - 1) // PAGE_SIZE
            next_label = (f"{c.lang(30500) or 'Next Page'} (Page {page + 1} of {_total_pages})") if has_next else None

            self.list = page_episodes
            c.log(f"[Progress] Rendering page {page}: items {start+1}-{min(end, len(all_episodes))} of {len(all_episodes)} ({len(warm_items)} warm, {len(cold_items)} cold)")
            self.episodes_directory(self.list, next_url=next_url, next_label=next_label)
            return self.list

        except Exception as e:
            c.log(f"[Progress] Error in get_in_progress_episodes: {e}")
            self.list = []
            self.episodes_directory(self.list)
            return self.list

    def shows_directory(self, items, next_url=None, next_label=None):
        """
        Create Kodi directory listing for TV shows.
        Shows show posters in ICONS view.

        Args:
            items (list): List of show dictionaries
            next_url (str): Optional URL for the next-page item
        """
        if not items:
            control.idle()
            control.infoDialog(c.lang(32500), sound=False, icon='INFO')
            return

        from ..indexers import tvshows
        from ..modules import playcount
        from ..modules.listitem import ListItemInfoTag
        import sys
        import json
        from urllib.parse import quote_plus

        sysaddon = sys.argv[0]
        syshandle = int(sys.argv[1])

        trakt_credentials = trakt.get_trakt_credentials_info()
        indicators = playcount.get_tvshow_indicators()
        addon_poster = c.addon_poster()

        for i in items:
            try:
                label = i.get('tvshowtitle', i.get('title', ''))
                imdb = i.get('imdb', '')
                tmdb = i.get('tmdb', '')
                tvdb = i.get('tvdb', '')
                year = i.get('year', '')

                # Use addon poster/fanart as fallback for missing artwork ('0' means not found)
                poster = i.get('poster', addon_poster)
                if poster in ['0', '', None]:
                    poster = addon_poster

                fanart = i.get('fanart', c.addon_fanart())
                if fanart in ['0', '', None]:
                    fanart = c.addon_fanart()

                systitle = quote_plus(label)

                # URL to open seasons list
                url = f'{sysaddon}?action=seasons&tvshowtitle={systitle}&year={year}&imdb={imdb}&tmdb={tmdb}&tvdb={tvdb}'

                # Create listitem
                try:
                    listitem = control.item(label=label, offscreen=True)
                except Exception:
                    listitem = control.item(label=label)

                # Set artwork
                listitem.setArt({
                    'icon': poster,
                    'thumb': poster,
                    'poster': poster,
                    'tvshow.poster': poster,
                    'fanart': fanart
                })

                # Set info using InfoTag
                info_tag = ListItemInfoTag(listitem, 'video')

                infodata = {
                    'title': label,
                    'tvshowtitle': label,
                    'year': year,
                    'plot': i.get('plot', ''),
                    'mediatype': 'tvshow'
                }

                info_tag.set_info(control.tagdataClean(infodata))
                info_tag.set_unique_ids({'imdb': imdb, 'tmdb': tmdb, 'tvdb': tvdb})

                # Add to directory
                control.addItem(handle=syshandle, url=url, listitem=listitem, isFolder=True)

            except Exception as e:
                c.log(f"[Progress] Error adding show to directory: {e}")
                continue

        if next_url:
            import os as _os
            _art = c.get_art_path()
            _next_icon = _os.path.join(_art, 'next.png') if _art else c.addon_poster()
            next_item = control.item(label=next_label or c.lang(30500) or 'Next Page', offscreen=True)
            next_item.setArt({'icon': _next_icon, 'thumb': _next_icon, 'poster': _next_icon})
            control.addItem(handle=syshandle, url=next_url, listitem=next_item, isFolder=True)

        control.content(syshandle, 'tvshows')
        control.directory(syshandle, cacheToDisc=True)

    def episodes_directory(self, items, suppress_empty_dialog=False, next_url=None, next_label=None):
        """
        Create Kodi directory listing for episodes.
        Shows episode stills in ICONS view.

        Args:
            items (list): List of episode dictionaries
            suppress_empty_dialog (bool): When True and items is empty, end directory
                silently (no info dialog). Used when background loading will follow.
        """
        if not items:
            if suppress_empty_dialog:
                # Cold-cache first load: show a "Loading..." placeholder so the user
                # sees SOMETHING immediately instead of a blank widget.
                # Background thread will call Container.Refresh once real data is cached.
                import sys
                syshandle = int(sys.argv[1])
                try:
                    placeholder = control.item(label=c.lang(32099) or 'Loading…', offscreen=True)
                except Exception:
                    placeholder = control.item(label='Loading your shows…')
                placeholder.setArt({'icon': c.addon_poster(), 'thumb': c.addon_poster(), 'poster': c.addon_poster()})
                hint_url = sys.argv[0] + sys.argv[2]  # Same plugin URL → refresh re-runs us
                control.addItem(handle=syshandle, url=hint_url, listitem=placeholder, isFolder=False)
                control.content(syshandle, 'episodes')
                control.directory(syshandle, cacheToDisc=False)
                return
            control.idle()
            control.infoDialog(c.lang(32500), sound=False, icon='INFO')
            return

        from ..modules import playcount
        from ..modules import bookmarks
        from ..modules.listitem import ListItemInfoTag
        import sys
        import json
        from urllib.parse import quote_plus

        sysaddon = sys.argv[0]
        syshandle = int(sys.argv[1])

        indicators = playcount.get_tvshow_indicators()
        is_playable = 'plugin' not in control.infoLabel('Container.PluginName')

        # Check Trakt credentials
        trakt_credentials = trakt.get_trakt_credentials_info()

        # Context menu labels (language strings)
        playback_menu = control.lang(32063) if control.setting('hosts.mode') == '2' else control.lang(32064)
        watched_menu = control.lang(32068) if trakt_credentials else control.lang(32066)
        unwatched_menu = control.lang(32069) if trakt_credentials else control.lang(32067)
        queue_menu = control.lang(32065)
        trakt_manager_menu = control.lang(32515)
        add_to_library = control.lang(32551)
        clear_resume_menu = control.lang(90237)
        clear_providers = control.lang(32098)
        infoMenu = control.lang(32101)

        for i in items:
            try:
                label = i.get('title', i.get('label', ''))
                season = str(i.get('season', 0)).zfill(2)
                episode = str(i.get('episode', 0)).zfill(2)
                tvshowtitle = i.get('tvshowtitle', '')

                # Build episode label with TV show title (includes show name for multi-show views)
                ep_label = f'{tvshowtitle} (S{season}E{episode}) : {label}'

                # For episode playback, we need SHOW IDs (episodes don't have their own IMDB/TMDB IDs)
                # If episode-level IDs are missing/invalid, use show-level IDs
                imdb = i.get('imdb', '0')
                if imdb in ['0', '', None]:
                    imdb = i.get('showimdb', '0')

                # Ensure we never pass invalid imdb (use empty string for URL param consistency)
                if imdb in ['0', '', None]:
                    imdb = ''

                tmdb = i.get('tmdb', '0')
                if tmdb in ['0', '', None]:
                    tmdb = i.get('showtmdb', '0')

                # Ensure valid tmdb (should always be available from Trakt)
                if tmdb in ['0', '', None]:
                    tmdb = ''

                tvdb = i.get('tvdb', '0')
                if tvdb in ['0', '', None]:
                    tvdb = i.get('showtvdb', '0')

                year = i.get('year', '')
                duration = i.get('duration', 45) or 45  # minutes, handle empty string

                # Convert to int if string
                try:
                    duration = int(duration)
                except (ValueError, TypeError):
                    duration = 45

                # Get artwork (use addon defaults for missing artwork - '0' means not found)
                thumb = i.get('thumb', c.addon_thumb())
                if thumb in ['0', '', None]:
                    thumb = c.addon_thumb()

                poster = i.get('poster', c.addon_poster())
                if poster in ['0', '', None]:
                    poster = c.addon_poster()

                fanart = i.get('fanart', c.addon_fanart())
                if fanart in ['0', '', None]:
                    fanart = c.addon_fanart()

                # Build playback URL (match existing episodes.py format)
                systitle = quote_plus(label)
                systvshowtitle = quote_plus(tvshowtitle)

                premiered = i.get('premiered', i.get('first_aired', ''))
                syspremiered = quote_plus(premiered) if premiered else '0'

                # Build meta dict - keep required artwork fields even if '0' for old episodes.py compatibility
                required_fields = {'banner', 'clearlogo', 'clearart', 'landscape'}
                meta = {
                    k: v for k, v in i.items()
                    if v not in [None, ''] or k in required_fields
                }
                # Ensure required fields exist with '0' default
                for field in required_fields:
                    if field not in meta:
                        meta[field] = '0'

                sysmeta = quote_plus(json.dumps(meta))

                # Import time for unique cache-busting parameter
                import time
                systime = str(int(time.time()))

                url = (f'{sysaddon}?action=play&title={systitle}&year={year}&imdb={imdb}&tmdb={tmdb}'
                       f'&season={i.get("season")}&episode={i.get("episode")}'
                       f'&tvshowtitle={systvshowtitle}&premiered={syspremiered}&meta={sysmeta}&t={systime}')

                # Create listitem
                try:
                    listitem = control.item(label=ep_label, offscreen=True)
                except Exception:
                    listitem = control.item(label=ep_label)

                if is_playable:
                    listitem.setProperty('IsPlayable', 'true')

                # Set artwork
                listitem.setArt({
                    'icon': thumb,
                    'thumb': thumb,
                    'poster': poster,
                    'tvshow.poster': poster,
                    'season.poster': poster,
                    'fanart': fanart
                })

                # Get watch status
                try:
                    overlay = int(playcount.get_episode_overlay(indicators, imdb, tmdb, i.get('season'), i.get('episode')))
                except Exception:
                    overlay = 6

                # Prepare comprehensive metadata for InfoTag
                infodata = {
                    'title': label,
                    'tvshowtitle': tvshowtitle,
                    'season': i.get('season'),
                    'episode': i.get('episode'),
                    'year': year,
                    'plot': i.get('plot', ''),
                    'duration': str(int(duration) * 60),  # convert to seconds
                    'mediatype': 'episode',
                    'playcount': 1 if overlay == 7 else 0,
                    'overlay': overlay,
                    'rating': i.get('rating', '0'),
                    'votes': i.get('votes', '0'),
                    'premiered': i.get('premiered', ''),
                    'aired': i.get('first_aired', i.get('premiered', '')),
                    'mpaa': i.get('mpaa', ''),
                }

                # Add lists (genre, studio, director, writer)
                if genre := i.get('genre'):
                    infodata['genre'] = c.string_split_to_list(genre)
                if studio := i.get('studio'):
                    infodata['studio'] = c.string_split_to_list(studio)
                if director := i.get('director'):
                    infodata['director'] = c.string_split_to_list(director)
                if writer := i.get('writer'):
                    infodata['writer'] = c.string_split_to_list(writer)

                # Build trailer URL for episode (uses show's IDs)
                trailer = i.get('trailer', '')
                if not trailer or trailer in ('0', '', None):
                    # Build trailer plugin URL from show TMDB/IMDB with metadata for poster display
                    trailer = f'{sysaddon}?action=trailer&name={quote_plus(tvshowtitle)}&imdb={imdb}&tmdb={tmdb}&mediatype=episode&season={i.get("season")}&episode={i.get("episode")}&meta={sysmeta}'
                infodata['trailer'] = trailer

                info_tag = ListItemInfoTag(listitem, 'video')
                info_tag.set_info(control.tagdataClean(infodata))
                info_tag.set_unique_ids({'imdb': imdb, 'tmdb': tmdb, 'tvdb': tvdb})

                # Set trailer explicitly on InfoTag for information dialog
                if trailer and trailer not in ('0', '', None):
                    # c.log(f"[CM Debug @ progress.py] Setting trailer on InfoTag: {trailer}")
                    info_tag._info_tag.setTrailer(trailer)

                # Set cast separately (required format: list of dicts with name, role, thumbnail)
                if castwiththumb := i.get('castwiththumb'):
                    if castwiththumb and castwiththumb != '0':
                        info_tag.set_cast(castwiththumb)

                # Get resume point early (needed for context menu)
                resume_point = i.get('resume_point')
                has_resume = resume_point is not None and resume_point > 0

                # Build context menu in logical order (matching episodes.py)
                cm = []

                # 1. Queue
                cm.append((queue_menu, f'RunPlugin({sysaddon}?action=queueItem)'))

                # 2. Browse Series (all seasons)
                browse_series_label = control.lang(32071)
                browse_series_url = f'ActivateWindow(Videos,{sysaddon}?action=seasons&tvshowtitle={systvshowtitle}&year={year}&imdb={imdb}&tmdb={tmdb}&meta={sysmeta},return)'
                cm.append((browse_series_label, browse_series_url))

                # 3. Browse Season (all episodes in this season)
                browse_season_label = f'Browse Season {i.get("season")}'
                browse_season_url = f'ActivateWindow(Videos,{sysaddon}?action=episodes&tvshowtitle={systvshowtitle}&year={year}&imdb={imdb}&tmdb={tmdb}&meta={sysmeta}&season={i.get("season")},return)'
                cm.append((browse_season_label, browse_season_url))

                # 4. Information (replaces system "Information" menu)
                cm.append((infoMenu, 'Action(Info)'))

                # 5. Watch status (watched/unwatched) - use already calculated overlay
                if overlay == 7:
                    cm.append((unwatched_menu, f'RunPlugin({sysaddon}?action=episodePlaycount&imdb={imdb}&tmdb={tmdb}&season={i.get("season")}&episode={i.get("episode")}&query=6)'))
                else:
                    cm.append((watched_menu, f'RunPlugin({sysaddon}?action=episodePlaycount&imdb={imdb}&tmdb={tmdb}&season={i.get("season")}&episode={i.get("episode")}&query=7)'))

                # 6. Clear Resume Point (if there's a resume point)
                if has_resume:
                    # Pass current container URL so clear_resume_point can refresh the correct list
                    current_container = sysaddon + sys.argv[2]  # e.g., plugin://plugin.video.thecrew/?action=progress_in_progress_episodes
                    cm.append((clear_resume_menu, f'RunPlugin({sysaddon}?action=episodeClearBookmark&imdb={imdb}&tmdb={tmdb}&season={i.get("season")}&episode={i.get("episode")}&redirect={quote_plus(current_container)})'))

                # 7. Trakt Manager (if Trakt is enabled)
                if trakt_credentials:
                    cm.append((trakt_manager_menu, f'RunPlugin({sysaddon}?action=traktManager&name={systvshowtitle}&tmdb={tmdb}&content=tvshow)'))

                # 8. Playback Menu (Alter Sources)
                cm.append((playback_menu, f'RunPlugin({sysaddon}?action=alterSources&url={quote_plus(url)}&meta={sysmeta})'))

                # 9. Add to Library
                cm.append((add_to_library, f'RunPlugin({sysaddon}?action=tvshowToLibrary&tvshowtitle={systvshowtitle}&year={year}&imdb={imdb}&tmdb={tmdb})'))

                # 10. Clear Providers Cache
                cm.append((clear_providers, f'RunPlugin({sysaddon}?action=clearSources)'))

                # Note: System context menus cannot be removed (Kodi API limitation since v17/2016)
                listitem.addContextMenuItems(cm, replaceItems=True)

                # Handle resume point if present (for In Progress Episodes)
                if has_resume:
                    # resume_point is a percentage (0-100)
                    duration_seconds = int(duration) * 60

                    # Skip if duration is 0 or invalid (prevents division by zero)
                    if duration_seconds > 0:
                        # Convert percentage to seconds
                        resume_seconds = (duration_seconds * resume_point) / 100.0

                        # Calculate remaining time in minutes
                        remaining_seconds = duration_seconds - resume_seconds
                        remaining_minutes = int(remaining_seconds / 60)

                        # Add remaining time to label in gold
                        if remaining_minutes > 0:
                            ep_label = f'{ep_label} [COLOR gold]({remaining_minutes} mins left)[/COLOR]'
                            listitem.setLabel(ep_label)

                        # Set resume point using InfoTag (Kodi v19+ method)
                        # This automatically sets the overlay indicator (arrow vs checkmark)
                        try:
                            infodata['offset'] = resume_seconds
                            info_tag.set_resume_point(infodata, 'offset', 'duration', False)
                        except Exception as e:
                            c.log(f"[Progress] Error setting resume point: {e}")


                # Add to directory
                control.addItem(handle=syshandle, url=url, listitem=listitem, isFolder=False)

            except Exception as e:
                c.log(f"[Progress] Error adding episode to directory: {e}")

                c.log(f"[Progress] Traceback: {traceback.format_exc()}")
                continue

        if next_url:
            try:
                import os as _os
                _art = c.get_art_path()
                _next_icon = _os.path.join(_art, 'next.png') if _art else c.addon_poster()
                next_item = control.item(label=next_label or c.lang(30500) or 'Next Page', offscreen=True)
                next_item.setArt({'icon': _next_icon, 'thumb': _next_icon, 'poster': _next_icon})
                control.addItem(handle=syshandle, url=next_url, listitem=next_item, isFolder=True)
            except Exception as e:
                c.log(f"[Progress] Error adding next page item: {e}")

        control.content(syshandle, 'episodes')
        control.directory(syshandle, cacheToDisc=True)
