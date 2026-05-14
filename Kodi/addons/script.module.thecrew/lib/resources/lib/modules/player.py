# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file player.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''


from argparse import Action
import base64
import codecs
import contextlib
import gzip
import json
import os
import queue as _stdlib_queue
import re
import sys
import traceback
import threading
import time
from io import BytesIO

import xbmc
import xbmcgui
import xbmcaddon

#from six.moves import xmlrpc_client

import xmlrpc.client



from urllib.parse import quote_plus, unquote_plus, parse_qs, urlparse


from . import bookmarks
from . import control
from . import cleantitle
from . import playcount
from . import trakt
from . import upnext
from . import subtitles
from . import episode_container
from . import tvevening_playlist_db
from . import tvevening_countdown
from . import tvevening_monitor
#
#from . import log_utils
from .crewruntime import c

# VERSION: 2025-02-28-v22.26 - CREWMONITOR ZERO-THREAD-GROWTH ARCHITECTURE
# - CrewMonitor service (service.py) has ONE persistent worker thread for entire Kodi session
# - Worker thread blocked on queue.get() when idle (zero CPU, ~50KB memory)
# - Replaces per-episode thread spawning (15->29 thread growth) with queue submission
# - Thread count: 16 threads (15 baseline + 1 CrewMonitor-Worker) across infinite episodes
# - CrewMonitor survives player.py module reloads (lives in service.py, never reloaded)
# - Zero point: 2.5s settling time for GPU/decoder resource release
# - Audio track selection independent of subtitle settings (v22.24)
# - Overlay='7' fix - UpNext works for previously watched episodes (v22.21)

# Module-level lock for player instance initialization (prevents race condition)
_player_init_lock = threading.Lock()

# v22.26: Reference to CrewMonitor from service.py (set on first access)
# CrewMonitor lives in service.py and survives player.py module reloads
_crew_monitor = None
_monitor_lock = threading.Lock()

def _get_crew_monitor():
    """
    Get reference to the active CrewMonitor from crewservice (in script.module.thecrew).
    Returns CrewMonitor instance or None if the service is not yet running.
    """
    global _crew_monitor
    if _crew_monitor is None:
        with _monitor_lock:
            if _crew_monitor is None:
                try:
                    from resources.lib.modules import crewservice
                    _crew_monitor = crewservice.get_crew_monitor()
                    if _crew_monitor is not None:
                        c.log("[Player] (OK) Connected to CrewMonitor via crewservice")
                    else:
                        c.log("[Player] (X) CrewMonitor service not yet initialized")
                except Exception as e:
                    c.log(f"[Player] (X) Could not get CrewMonitor reference: {e}")
    return _crew_monitor

# Module-level flag to signal that we're about to intentionally start new playback
# This resets onAVStarted debouncing so the next episode can start a monitoring loop
_expect_new_playback = False
_expect_lock = threading.Lock()

# Module-level storage for latest episode metadata (updated by player.run())
# This allows the global service player instance to sync with new playback
_latest_episode_metadata = {
    'title': None,
    'season': None,
    'episode': None,
    'imdb': None,
    'tmdb': None,
    'tvdb': None,
    'year': None,
    'content': None,
    'timestamp': 0  # When this was last updated (time.time())
}
_metadata_lock = threading.Lock()

# v22: Global player mode tracker - state machine for playback context
# Modes: None = normal playback, 'upnext' = UpNext auto-play, 'tvevening' = TV Evening playlist
_player_mode = None
_player_mode_lock = threading.Lock()

# v22: Global player instance registry (set by service.py, used by sources.py)
_global_player_instance = None
_global_player_lock = threading.Lock()

# Module-level monitoring state (shared across all player instances)
# SIMPLE: Just track which URL is being monitored. That's it.
import time as _time_module
_monitored_url = None  # URL currently being monitored (None if no active loop)
_monitoring_lock = threading.Lock()

# MODULE-LEVEL UpNext coordination (v21 fix for multiple instances)
_last_upnext_trigger_time = 0  # GLOBAL timestamp of last UpNext trigger
_upnext_lock = threading.Lock()  # Protects UpNext trigger timing


def set_player_mode(mode):
    """v22: Set the current player mode: None, 'upnext', or 'tvevening'"""
    global _player_mode, _player_mode_lock
    with _player_mode_lock:
        old_mode = _player_mode
        _player_mode = mode
        c.log(f"[Player] Mode changed: {old_mode} -> {mode}")


def get_player_mode():
    """v22: Get the current player mode"""
    global _player_mode, _player_mode_lock
    with _player_mode_lock:
        return _player_mode


def register_global_player(player_instance):
    """v22: Register the global player instance (called by service.py)"""
    global _global_player_instance, _global_player_lock
    with _global_player_lock:
        _global_player_instance = player_instance
        # Also store in stdlib queue module — shared across all Kodi Python contexts
        setattr(_stdlib_queue, '_thecrew_global_player', player_instance)
        c.log(f"[Player] Global player instance registered: {id(player_instance)}")


def get_global_player():
    """v22: Get the global player instance (called by sources.py)"""
    global _global_player_instance, _global_player_lock
    with _global_player_lock:
        if _global_player_instance is not None:
            return _global_player_instance
        # Cross-context fallback: service.py stored it in stdlib queue module
        cross_ctx = getattr(_stdlib_queue, '_thecrew_global_player', None)
        if cross_ctx is not None:
            _global_player_instance = cross_ctx  # Cache locally
            c.log(f"[Player] Global player retrieved via cross-context bridge: {id(cross_ctx)}")
        return cross_ctx


class player(xbmc.Player):
    def __init__ (self):
        # Skip reinitialization if already initialized
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        self.totalTime = 0
        self.currentTime = 0
        self.duration = 0
        self.content = ''
        self.name = ''
        self.title = ''
        self.year = ''
        self.season = None
        self.episode = None
        self.DBID = None
        self.imdb = None
        self.tmdb = None
        self.tvdb = None
        self.ids = {}
        self.offset = 0
        self.getbookmark = False
        self.resume_point = 0
        self.upnext_triggered = False  # Track if Up Next has been shown
        self.upnext_lock = threading.Lock()  # Prevent double-triggering from multiple monitors
        self.last_upnext_trigger_time = 0  # Track when Up Next was last triggered (safety check)
        self.playlist_position_on_start = -1  # Track position when playback starts
        self.last_playnext_time = 0  # Track when we last called playnext()

        # Track video start time for onAVStarted debouncing
        self.video_start_time = 0

        # Debounce onAVStarted to prevent Kodi's duplicate calls from creating multiple monitoring loops
        self.last_avstarted_time = 0
        self.last_avstarted_url = None
        self.monitoring_thread = None  # Background thread for TV Evening monitoring
        self.stop_monitoring = False  # Flag to stop monitoring thread
        self.current_episode_position = -1  # Position of currently playing episode (for monitoring)

        # v22: Instance ID for debugging
        self.instance_id = id(self)

        xbmc.Player.__init__(self)

        # Store instance reference in window property for keymap script
        control.window.setProperty('thecrew.player.instance', str(self.instance_id))
        c.log(f"[Player] Instance initialized: {self.instance_id}")

    def run(self, title, year, season, episode, imdb, tmdb, url, meta):#: -> Any
        try:
            control.sleep(200)
            c.log(f"[Player.run] Instance {self.instance_id} starting playback: {title} S{season}E{episode}")

            # v22.3: Verify TV Evening property is valid - clear if stale
            tv_prop = control.window.getProperty('thecrew.tvevening.monitor.active')
            if tv_prop == 'true':
                # Check if TV Evening playlist actually exists
                try:
                    db = tvevening_playlist_db.get_playlist_db()
                    playlist_size = db.get_playlist_size()
                    if playlist_size == 0:
                        c.log("[Player.run] [WARNING] STALE TV Evening property detected (no playlist) - CLEARING")
                        control.window.clearProperty('thecrew.tvevening.monitor.active')
                        tv_prop = 'false'
                except Exception as e:
                    c.log(f"[Player.run] Could not verify TV Evening playlist: {e}")
                    pass  # DB not initialized yet

            # v22: Detect and set player mode based on metadata
            is_upnext = meta.get('upnext', False)
            is_tvevening = tv_prop == 'true'

            if is_tvevening:
                set_player_mode('tvevening')
                c.log(f"[Player.run] TV Evening mode: playlist active")
            elif is_upnext:
                set_player_mode('upnext')
                c.log(f"[Player.run] UpNext mode: auto-play next episode")
            else:
                set_player_mode(None)  # Normal playback
                c.log(f"[Player.run] Normal playback mode")

            self.totalTime = 0
            self.currentTime = 0
            self.content = 'movie' if season is None or episode is None else 'episode'
            self.getbookmark = True

            self.title = title
            self.year = year
            # DBID is populated by getMeta() if item exists in Kodi library
            # Used by libForPlayback() to mark library items as watched
            # Remains None for non-library playback (majority of users)
            self.DBID = None

            if self.content == 'movie':
                self.name = quote_plus(title) + quote_plus(f' ({year})')
            else:
                self.name = quote_plus(title) + quote_plus(f' S{int(season):02d}E{int(episode):02d}')
            self.name = unquote_plus(self.name)

            self.season = f'{int(season):01d}' if self.content == 'episode' else None
            self.episode = f'{int(episode):01d}' if self.content == 'episode' else None
            c.log(f"[Player] run() setting metadata: S{self.season}E{self.episode}, imdb={imdb}, title={title}")

            # Normalize 'None' strings to Python None (common when passed via URL params)
            imdb = None if imdb is None or str(imdb) in ('None', '', 'null') else imdb
            tmdb = None if tmdb is None or str(tmdb) in ('None', '', 'null') else tmdb
            raw_imdb = meta.get('imdb_id', '') or ''
            raw_tmdb = meta.get('tmdb_id', '') or ''
            raw_tvdb = meta.get('tvdb_id', '') or ''
            self.imdb = imdb if imdb is not None else (None if str(raw_imdb) in ('None', '', 'null') else raw_imdb or None)
            self.tmdb = tmdb if tmdb is not None else (None if str(raw_tmdb) in ('None', '', 'null') else raw_tmdb or None)
            self.tvdb = None if str(raw_tvdb) in ('None', '', 'null') else raw_tvdb or None

            # Store metadata globally so service player instance can access it
            global _latest_episode_metadata, _metadata_lock
            with _metadata_lock:
                _latest_episode_metadata['title'] = title
                _latest_episode_metadata['season'] = self.season
                _latest_episode_metadata['episode'] = self.episode
                _latest_episode_metadata['imdb'] = self.imdb
                _latest_episode_metadata['tmdb'] = self.tmdb
                _latest_episode_metadata['tvdb'] = self.tvdb
                _latest_episode_metadata['year'] = year
                _latest_episode_metadata['content'] = self.content
                _latest_episode_metadata['is_upnext'] = meta.get('upnext', False)
                _latest_episode_metadata['timestamp'] = time.time()
                c.log(f"[Player] (OK) Stored metadata globally: S{self.season}E{self.episode}, imdb={self.imdb}, tmdb={self.tmdb}, upnext={meta.get('upnext', False)}")

            self.ids = {'imdb': self.imdb, 'tmdb': self.tmdb, 'tvdb': self.tvdb}
            self.ids = dict((k,v) for k, v in self.ids.items() if not v == '0')

            self.duration = int(meta.get('duration', 0))

            # Get resume position - can come from metadata or bookmarks
            # resume_point and offset should both be in SECONDS now
            # IMPORTANT: Skip ALL resume points for Up Next auto-play (always start from 00:00:00)
            # Reason: If E02 has resume point at 95%, honoring it would trigger Up Next instantly
            self.offset = 0.0
            self.resume_point = None

            is_upnext = meta.get('upnext', False)
            if is_upnext:
                c.log("[Player] Up Next auto-play detected - skipping all resume points (start from 00:00:00)")
            else:
                if 'resume_point' in meta and meta['resume_point']:
                    # Check if it's stored as percentage (< 1.0) or seconds (>= 1.0)
                    val = float(meta['resume_point'])
                    if val < 1.0:
                        # Old percentage format (0-1), convert to seconds
                        self.offset = val * float(self.duration)
                    else:
                        # New seconds format
                        self.offset = val
                elif 'offset' in meta and meta['offset']:
                    # offset should be in seconds
                    self.offset = float(meta['offset'])
                else:
                    # Get from bookmarks (returns seconds)
                    if self.content == 'episode':
                        self.offset = bookmarks.get(self.content, imdb=self.imdb, tmdb=self.tmdb, season=int(self.season), episode=int(self.episode))
                    else:
                        self.offset = bookmarks.get(self.content, imdb=self.imdb, tmdb=self.tmdb)

            # Try to get DBID from Kodi library (for watched status sync)
            # Only runs if library.playback_integration setting is enabled
            # getMeta() queries library and sets self.DBID if item found
            # Ignore returned metadata as it may be empty if item not in library
            if c.get_setting('library.playback_integration') == 'true':
                try:
                    _ = self.getMeta(meta)
                except Exception as e:
                    c.log(f"[Player.run] Library lookup failed: {e}")
                    pass  # Not in library or lookup failed, DBID stays None

            # Use supplied metadata for art and info labels
            poster, thumb, fanart, clearlogo, clearart, discart, meta = self.getMetaArt(meta)

            item = control.item(path=url)
            if self.content == 'movie':
                item.setArt({
                    'icon': thumb, 'thumb': thumb, 'poster': poster, 'fanart': fanart,
                    'clearlogo': clearlogo, 'clearart': clearart, 'discart': discart
                    })
            else:
                item.setArt({
                    'icon': thumb, 'thumb': thumb, 'tvshow.poster': poster,
                    'season.poster': poster, 'fanart': fanart, 'clearlogo': clearlogo,
                    'clearart': clearart
                    })

            item.setInfo(type='video', infoLabels = control.metadataClean(meta))

            # CONTAINER SYSTEM: Check if this is Up Next (use pre-fetched secondary) or new playback (initialize primary)
            is_upnext = meta.get('upnext', False)

            # CRITICAL: Clear resume point on ListItem for UpNext auto-play
            # This prevents Kodi's native resume dialog from appearing
            # Even though player skips resume in run(), Kodi's ListItem needs explicit clearing
            if is_upnext:
                try:
                    item.setProperty('ResumeTime', '0')
                    item.setProperty('TotalTime', str(self.duration))
                    c.log(f"[Player] Cleared resume point on ListItem for UpNext (duration={self.duration}s)")
                except Exception as e:
                    c.log(f"[Player] Failed to clear resume properties: {e}")

            if is_upnext and self.content == 'episode':
                # This is an Up Next auto-play - check if secondary container is ready
                secondary = episode_container.get_secondary()
                if secondary.is_ready() and secondary.sources:
                    c.log(f"[Container] Using pre-fetched secondary: {secondary.get_episode_string()}")
                    c.log(f"[Container] (OK) Using {len(secondary.sources)} pre-scraped sources (saved ~15s scraping time)")

                    # Swap containers atomically
                    primary = episode_container.swap_containers()

                    # Update player attributes from container
                    self.season = primary.season
                    self.episode = primary.episode
                    self.imdb = primary.imdb
                    self.tmdb = primary.tmdb

                    c.log(f"[Container] (OK) Container swap complete - now playing {primary.get_episode_string()}")
                    # Note: URL resolution still happens in normal flow, we just skip the scraping part
                else:
                    c.log(f"[Container] [WARNING] Secondary not ready or no sources (status: {secondary.status}), falling back to normal flow")
                    # IMPORTANT: Cancel and clear the stale secondary so that when the
                    # monitoring loop reaches 85%, start_prefetch() for the NEXT episode
                    # is not skipped due to secondary still appearing as 'ready' or 'prefetching'.
                    # Without this, stale ep data sits in secondary, blocks ep+1 prefetch, and
                    # the UpNext dialog shows the wrong (current) episode as "next".
                    try:
                        episode_container.cancel_upnext()
                        c.log("[Container] Cleared stale secondary so next prefetch can start at 85%")
                    except Exception as _ce:
                        c.log(f"[Container] Could not clear stale secondary (non-fatal): {_ce}")
                    # Initialize primary normally
                    episode_container.initialize_primary(
                        title, year, season, episode, imdb, tmdb, url, meta
                    )
            else:
                # First episode or manual play - initialize primary container
                if self.content == 'episode':
                    episode_container.initialize_primary(
                        title, year, season, episode, imdb, tmdb, url, meta
                    )
                    c.log(f"[Container] Initialized primary container for first episode")

            if 'plugin' in control.infoLabel('Container.PluginName'):
                control.player.play(url, item)

            # Only call setResolvedUrl if it wasn't already called early in Sources.play()
            # When playing from info dialog, Sources.play() resolves immediately to prevent Kodi timeout
            if not meta.get('_early_resolve_done', False):
                control.resolve(int(sys.argv[1]), True, item)
                c.log(f"[Player.run] Called setResolvedUrl (standard flow)")
            else:
                c.log(f"[Player.run] Skipping setResolvedUrl (already called in Sources.play())")

            control.window.setProperty('script.trakt.ids', json.dumps(self.ids))

            # Set video_start_time BEFORE keepPlaybackAlive() starts monitoring
            # Protects monitoring loop from stale timing during first few seconds
            self.video_start_time = time.time()
            c.log(f"[Player.run] Set video_start_time={self.video_start_time} (before monitoring)")

            # Set flag so onAVStarted() knows run() will handle monitoring
            self.run_will_monitor = True

            # v22.26: Window property-based signaling for persistent worker thread
            # CRITICAL: Only activate UpNext for episodes, not movies
            if self.content == 'episode':
                # Worker polls thecrew.upnext.active and monitors when 'true'
                # Window properties are global across all addons (unlike module attributes)
                # Replaces: threading.Thread(target=self.keepPlaybackAlive).start()
                control.window.setProperty('thecrew.upnext.active', 'true')
                control.window.setProperty('thecrew.upnext.title', title)
                control.window.setProperty('thecrew.upnext.year', str(year))
                control.window.setProperty('thecrew.upnext.season', str(season))
                control.window.setProperty('thecrew.upnext.episode', str(episode))
                control.window.setProperty('thecrew.upnext.imdb', str(self.imdb))
                control.window.setProperty('thecrew.upnext.tmdb', str(self.tmdb))
                control.window.setProperty('thecrew.upnext.content', 'episode')
                if c.devmode:
                    c.log(f"[Player.run] Set upnext: {title} S{self.season}E{self.episode}")
            else:
                # Movies: set window properties so CrewMonitor worker can save resume point
                control.window.setProperty('thecrew.upnext.active', 'true')
                control.window.setProperty('thecrew.upnext.title', title)
                control.window.setProperty('thecrew.upnext.year', str(year))
                control.window.setProperty('thecrew.upnext.season', '')
                control.window.setProperty('thecrew.upnext.episode', '')
                control.window.setProperty('thecrew.upnext.imdb', str(self.imdb))
                control.window.setProperty('thecrew.upnext.tmdb', str(self.tmdb))
                control.window.setProperty('thecrew.upnext.content', 'movie')
                if c.devmode:
                    c.log(f"[Player.run] Set movie playback tracking: {title}")

            # v22.26: Wait for playback to start, then select English audio track
            # Note: onAVStarted() also fires but skips audio selection when run_will_monitor=True (prevents duplicate)
            for _ in range(60):  # Wait up to 60 seconds for playback to start
                if self.isPlayingVideo():
                    control.sleep(1000)  # Give it 1 more second to stabilize
                    self.select_audio_track()
                    c.log("[Player.run] (OK) Audio track selection completed")
                    break
                control.sleep(1000)

            # Note: Don't clear run_will_monitor flag - it stays set to prevent onAVStarted() duplicates

            control.window.clearProperty('script.trakt.ids')
        except Exception as e:
            if c.devmode:
                failure = traceback.format_exc()
                c.log(f'[Player.run] Traceback: {failure}')
            c.log(f'[Player.run] Exception in run(): {e}')
            return

    def select_audio_track(self):
        """
        Automatically select preferred audio track (English preferred).

        This is independent of subtitle functionality and always runs.
        Extracted from subtitles.py to work even when subtitles are disabled.

        Returns:
            bool: True if audio track was selected
        """
        try:
            available_audio = self.getAvailableAudioStreams()
            if c.devmode:
                c.log(f"[Audio] Available: {available_audio}")

            if not available_audio:
                if c.devmode:
                    c.log("[Audio] No tracks available")
                return False

            # Get current audio stream to avoid unnecessary switches
            try:
                current_idx = self.getAudioStream()
            except Exception:
                current_idx = -1

            # Preferred audio languages in priority order
            preferred_langs = ['eng', 'en', 'english']

            # Try to find English audio track
            for idx, audio_lang in enumerate(available_audio):
                audio_lower = audio_lang.lower()
                for pref_lang in preferred_langs:
                    if pref_lang in audio_lower:
                        # Check if this track is already selected
                        if idx == current_idx:
                            if c.devmode:
                                c.log(f"[Audio] English track {idx} already active: '{audio_lang}' - no switch needed")
                            return True

                        if c.devmode:
                            c.log(f"[Audio] Switching to English track {idx}: '{audio_lang}' (current: {current_idx})")
                        self.setAudioStream(idx)
                        return True

            # If no English found
            if c.devmode:
                c.log(f"[Audio] No English found, using default (current: {current_idx})")
            return False

        except Exception as e:
            c.log(f"[Audio] [WARNING] Error: {e}")
            return False

    def getMetaArt(self, meta):
        pass

        try:
            poster = meta.get('poster')
            thumb = meta.get('thumb') or poster
            fanart = meta.get('fanart')
            clearlogo = meta.get('clearlogo', '')
            clearart = meta.get('clearart', '')
            discart = meta.get('discart', '')

            return poster, thumb, fanart, clearlogo, clearart, discart, meta
        except Exception:
            pass


    def getMeta(self, meta):
        # Early return if library integration is disabled
        if not c.get_setting('library.playback_integration') == 'true':
            return None

        try:
            poster = meta.get('poster')
            thumb = meta.get('thumb') or poster
            fanart = meta.get('fanart')
            clearlogo = meta.get('clearlogo', '')
            clearart = meta.get('clearart', '')
            discart = meta.get('discart', '')

            #return poster, thumb, fanart, clearlogo, clearart, discart, meta
        except Exception:
            pass

        try:
            if not self.content == 'movie':
                raise Exception()

            meta = control.jsonrpc(
                '{"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies", "params": {"filter":{"or": [{"field": "year", "operator": "is", "value": "%s"}, {"field": "year", "operator": "is", "value": "%s"}, {"field": "year", "operator": "is", "value": "%s"}]}, "properties" : ["title", "originaltitle", "year", "genre", "studio", "country", "runtime", "rating", "votes", "mpaa", "director", "writer", "plot", "plotoutline", "tagline", "thumbnail", "file"]}, "id": 1}' % (self.year, str(int(self.year)+1), str(int(self.year)-1))
                )
            meta = c.to_str(meta, errors='ignore')
            meta = json.loads(meta)['result']['movies']

            t = cleantitle.get(self.title)
            meta = [i for i in meta if self.year == str(i['year']) and (t == cleantitle.get(i['title']) or t == cleantitle.get(i['originaltitle']))][0]

            for k, v in meta.items():
                if isinstance(v, list):
                    try:
                        meta[k] = str(' / '.join([c.to_str(i) for i in v]))
                    except Exception:
                        meta[k] = ''
                else:
                    try:
                        meta[k] = str(c.to_str(v))
                    except Exception:
                        meta[k] = str(v)

            if 'plugin' not in control.infoLabel('Container.PluginName'):
                self.DBID = meta['movieid']

            poster = thumb = meta['thumbnail']

            return poster, thumb, '', '', '', '', meta
        except Exception as e:
            if c.devmode:
                failure = traceback.format_exc()
                c.log(f'[Player.getMeta] Traceback: {failure}')
            c.log(f'[Player.getMeta] Exception: {e}')
            pass


        try:
            if self.content != 'episode':
                raise Exception()

            meta = control.jsonrpc('{"jsonrpc": "2.0", "method": "VideoLibrary.GetTVShows", "params": {"filter":{"or": [{"field": "year", "operator": "is", "value": "%s"}, {"field": "year", "operator": "is", "value": "%s"}, {"field": "year", "operator": "is", "value": "%s"}]}, "properties" : ["title", "year", "thumbnail", "file"]}, "id": 1}' % (self.year, str(int(self.year)+1), str(int(self.year)-1)))
            meta = c.to_str(meta, errors='ignore')
            meta = json.loads(meta)['result']['tvshows']

            t = cleantitle.get(self.title)
            meta = [i for i in meta if self.year == str(i['year']) and t == cleantitle.get(i['title'])][0]

            tvshowid = meta['tvshowid']
            poster = meta['thumbnail']

            meta = control.jsonrpc('{ "jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes", "params":{ "tvshowid": %d, "filter":{"and": [{"field": "season", "operator": "is", "value": "%s"}, {"field": "episode", "operator": "is", "value": "%s"}]}, "properties": ["title", "season", "episode", "showtitle", "firstaired", "runtime", "rating", "director", "writer", "plot", "thumbnail", "file"]}, "id": 1}' % (tvshowid, self.season, self.episode))
            meta = c.to_str(meta, errors='ignore')
            meta = json.loads(meta)['result']['episodes'][0]

            for k, v in meta.items():
                if isinstance(v, list):
                    try:
                        meta[k] = str(' / '.join([c.to_str(i) for i in v]))
                    except Exception:
                        meta[k] = ''
                else:
                    try:
                        meta[k] = str(c.to_str(v))
                    except Exception:
                        meta[k] = str(v)

            if 'plugin' not in control.infoLabel('Container.PluginName'):
                self.DBID = meta['episodeid']

            thumb = meta['thumbnail']

            return poster, thumb, '', '', '', '', meta
        except Exception:
            pass

        poster, thumb, fanart, clearlogo, clearart, discart, meta = '', '', '', '', '', '', {'title': self.name}
        return poster, thumb, fanart, clearlogo, clearart, discart, meta



#TC 2/01/19 started
#cm 19-02-2025
#overlay isn't used anymore and is calculated by kodi based on percentage of video watched

    def _show_upnext_async(self, title, year, imdb, tmdb, season, episode, **kwargs):
        """Launch UpNext dialog in background thread (non-blocking).

        Args:
            title: TV show title
            year: Year
            imdb: IMDB ID
            tmdb: TMDB ID
            season: Season number
            episode: Episode number
            **kwargs: Additional parameters for upnext.show_upnext_dialog()
                     (from_playlist, from_database, playlist_position, etc.)
        """
        def show_upnext():
            try:
                upnext.show_upnext_dialog(title, year, imdb, tmdb, season, episode, **kwargs)
            except Exception as e:
                c.log(f"[UpNext] Error showing dialog: {e}")
        threading.Thread(target=show_upnext, daemon=True).start()

    def _check_and_trigger_upnext(self, pname, playlist, playlist_position, playlist_size):
        """Check if UpNext should trigger and show appropriate dialog.

        Handles prefetch at 85%, trigger logic, safety checks, and three modes:
        - TV Evening database playlist
        - Kodi playlist (parse next item)
        - Single episode mode

        Returns:
            bool: True if UpNext was triggered, False otherwise
        """
        # ═══ DEFENSIVE VALIDATION ═══
        if self.content != 'episode':
            c.log(f"[UpNext] CRITICAL: _check_and_trigger_upnext called but content={self.content} - ABORT")
            return False

        if not upnext.is_enabled():
            return False

        # v22.3: Validate TV Evening property before suppressing UpNext
        tv_evening_prop = control.window.getProperty('thecrew.tvevening.monitor.active')
        if tv_evening_prop == 'true':
            # Verify TV Evening playlist actually exists
            try:
                db = tvevening_playlist_db.get_playlist_db()
                if db.get_playlist_size() == 0:
                    c.log("[UpNext] [WARNING] STALE TV Evening property (no playlist) - CLEARING and allowing UpNext")
                    control.window.clearProperty('thecrew.tvevening.monitor.active')
                    tv_evening_prop = 'false'
            except Exception as e:
                c.log(f"[UpNext] Could not verify TV Evening playlist: {e}")
                pass

        tv_evening_active = tv_evening_prop == 'true'

        if tv_evening_active:
            # Skip UpNext when TV Evening Monitor is handling transitions
            c.log(f"[UpNext] Skipping UpNext - TV Evening Monitor is active (playlist exists)")
            return False

        # PREFETCH TRIGGER: Start fetching next episode at 85%
        prefetch_percent = 0.85
        if self.currentTime / self.totalTime >= prefetch_percent:
            secondary = episode_container.get_secondary()
            if secondary.is_empty() and self.season and self.episode:
                try:
                    next_episode = int(self.episode) + 1
                    c.log(f"[Container] Playback at {prefetch_percent*100:.0f}% - starting prefetch for S{self.season}E{next_episode:02d}")

                    episode_container.start_prefetch(
                        title=self.title,
                        year=self.year,
                        season=int(self.season),
                        episode=next_episode,
                        imdb=self.imdb,
                        tmdb=self.tmdb
                    )
                except Exception as e:
                    c.log(f"[Container] Error starting prefetch: {e}")

        # UPNEXT TRIGGER LOGIC
        trigger_percent = upnext.get_trigger_percent() / 100.0
        countdown_seconds = upnext.get_countdown_seconds()

        # Calculate trigger time accounting for countdown duration
        target_time_seconds = (self.totalTime * trigger_percent) - countdown_seconds

        if self.currentTime >= target_time_seconds:
            # Thread-safe check-and-set to prevent double-triggering
            with self.upnext_lock:
                if self.upnext_triggered:
                    return False  # Already triggered

                # SAFETY CHECK: Require at least 30 seconds of playback
                if self.currentTime < 30:
                    c.log(f"[UpNext] SAFETY: Ignoring trigger (only {self.currentTime:.1f}s played, minimum 30s)")
                    return False

                # STALE TIMING PROTECTION: Ignore triggers in first 10 seconds
                current_time = time.time()
                if hasattr(self, 'video_start_time'):
                    time_since_video_start = current_time - self.video_start_time
                    if time_since_video_start < 10.0:
                        c.log(f"[UpNext] STALE: Ignoring trigger (video started {time_since_video_start:.1f}s ago, waiting 10s)")
                        return False

            # v22.4: GLOBAL UpNext coordination (30s cooldown)
            global _last_upnext_trigger_time, _upnext_lock
            with _upnext_lock:
                current_time_global = time.time()
                time_since_last_global_trigger = current_time_global - _last_upnext_trigger_time
                if time_since_last_global_trigger < 30.0 and _last_upnext_trigger_time > 0:
                    c.log(f"[UpNext] [WARNING] GLOBAL REJECT: Only {time_since_last_global_trigger:.1f}s since last trigger (minimum 30s)")
                    return False

                # Claim the global trigger
                _last_upnext_trigger_time = current_time_global
                actual_percent = (self.currentTime / self.totalTime) * 100
                finish_percent = trigger_percent * 100
                c.log(f"[UpNext] (OK) GLOBAL CLAIM: Triggered at {actual_percent:.1f}% (countdown finishes at ~{finish_percent:.0f}% in {countdown_seconds}s)")
                c.log(f"[UpNext] Timing: played {self.currentTime:.1f}s of {self.totalTime:.1f}s")

            self.upnext_triggered = True
            self.last_upnext_trigger_time = current_time_global

            # Check if we have a TV Evening database playlist active
            db = tvevening_playlist_db.get_playlist_db()
            db_size = db.get_playlist_size()

            if db_size > 0:
                # TV Evening mode - use database playlist
                c.log(f"[UpNext] TV Evening mode detected - Database has {db_size} episodes")
                current_db_pos = playlist_position if playlist_position >= 0 else db.get_current_position()
                next_episode_db = db.get_next_episode(current_db_pos)

                if next_episode_db:
                    c.log(f"[UpNext] Found next episode in database at position {current_db_pos + 1}")
                    c.log(f"[UpNext] Next: {next_episode_db['tvshowtitle']} S{next_episode_db['season']:02d}E{next_episode_db['episode']:02d}")

                    db.mark_episode_watched(current_db_pos)

                    self._show_upnext_async(
                        next_episode_db['tvshowtitle'],
                        next_episode_db.get('year', ''),
                        next_episode_db.get('showimdb', ''),
                        next_episode_db.get('showtmdb', ''),
                        int(next_episode_db['season']),
                        int(next_episode_db['episode']),
                        from_playlist=True,
                        from_database=True,
                        playlist_position=playlist_position
                    )
                else:
                    c.log(f"[UpNext] No next episode in database (end of TV Evening playlist)")
                    db.mark_episode_watched(current_db_pos)

            else:
                # No TV Evening playlist - check Kodi playlist or single episode mode
                has_next_in_playlist = playlist_position < (playlist_size - 1)
                c.log(f"[UpNext] has_next_in_playlist={has_next_in_playlist} (pos={playlist_position}, size={playlist_size})")

                if has_next_in_playlist:
                    # Get next playlist item's metadata
                    c.log("[UpNext] Playlist mode - extracting next playlist item metadata")
                    try:
                        next_item = playlist[playlist_position + 1]
                        next_path = next_item.getPath()
                        c.log(f"[UpNext] Next playlist item path: {next_path}")

                        # Parse URL parameters
                        parsed = urlparse(next_path)
                        params = parse_qs(parsed.query)

                        next_title = params.get('tvshowtitle', [''])[0]
                        next_year = params.get('year', [''])[0]
                        next_imdb = params.get('imdb', [''])[0]
                        next_tmdb = params.get('tmdb', [''])[0]
                        next_season = params.get('season', ['0'])[0]
                        next_episode = params.get('episode', ['0'])[0]

                        c.log(f"[UpNext] Next playlist item: {next_title} S{next_season}E{next_episode}")

                        self._show_upnext_async(
                            next_title,
                            next_year,
                            next_imdb,
                            next_tmdb,
                            int(next_season),
                            int(next_episode),
                            from_playlist=True,
                            playlist_position=playlist_position
                        )
                    except Exception as e:
                        c.log(f"[UpNext] Error extracting playlist item: {e}")
                else:
                    # Single episode mode
                    c.log("[UpNext] Single episode mode - showing Up Next for next episode of same show")
                    self._show_upnext_async(
                        self.title,
                        self.year,
                        self.imdb,
                        self.tmdb,
                        int(self.season),
                        int(self.episode),
                        from_playlist=False
                    )

            return True

        return False

    def _monitor_episode_playback(self, pname, overlay):
        """Monitor episode playback with comprehensive safety checks.

        Includes:
        - File-based duplicate prevention (v22.8)
        - Monitoring lock (v22.4)
        - Prefetch and UpNext trigger
        - Watcher threshold (92%)
        """
        # ═══ DEFENSIVE VALIDATION ═══
        if self.content != 'episode':
            c.log(f"[Player._monitor_episode] CRITICAL: Called with content={self.content} - ABORT")
            return

        if not self.season or not self.episode:
            c.log(f"[Player._monitor_episode] CRITICAL: Missing metadata season={self.season}, episode={self.episode} - ABORT")
            return

        c.log("[Player._monitor_episode] Starting episode monitoring loop")

        # ═══ FILE-BASED DUPLICATE PREVENTION (v22.8) ═══
        try:
            current_file = self.getPlayingFile()
            last_processed = control.window.getProperty('thecrew.player.last_processed_file')

            if last_processed and last_processed == current_file:
                c.log(f"[Player._monitor_episode] [WARNING] File already processed: {current_file[:80]}... - EXITING")
                return

            if last_processed and last_processed != current_file:
                c.log(f"[Player._monitor_episode] 🔄 FILE TRANSITION (Episode):")
                c.log(f"[Player._monitor_episode]   Old: {last_processed[:80]}...")
                c.log(f"[Player._monitor_episode]   New: {current_file[:80]}...")

            control.window.setProperty('thecrew.player.last_processed_file', current_file)
            c.log(f"[Player._monitor_episode] (OK) File marked for processing: {current_file[:80]}...")
        except Exception as e:
            c.log(f"[Player._monitor_episode] [WARNING] Could not get playing file: {e}")

        # ═══ MONITORING LOCK (v22.4) ═══
        monitoring_lock_property = 'thecrew.player.monitoring.active'

        if control.window.getProperty(monitoring_lock_property):
            c.log(f"[Player._monitor_episode] [WARNING] Another instance already monitoring - EXITING")
            return

        control.window.setProperty(monitoring_lock_property, str(id(self)))
        c.log(f"[Player._monitor_episode] (OK) Claimed monitoring lock (instance {id(self)})")

        try:
            while self.isPlayingVideo():
                try:
                    self.totalTime = self.getTotalTime()
                    self.currentTime = self.getTime()

                    # v22.3: Guard against division by zero
                    if self.totalTime <= 0:
                        xbmc.sleep(2000)
                        continue

                    watcher = self.currentTime / self.totalTime >= .92
                    c.log(f"[CM Debug @ 929 in player.py] watcher={watcher}, currentTime={self.currentTime:.1f}, totalTime={self.totalTime:.1f}")
                    _property = control.window.getProperty(pname)

                    # Get playlist info for UpNext
                    playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                    playlist_size = playlist.size()
                    playlist_position = playlist.getposition()

                    # Check and trigger UpNext if conditions met
                    self._check_and_trigger_upnext(pname, playlist, playlist_position, playlist_size)

                    # Update watcher status
                    if watcher and _property != '7':
                        control.window.setProperty(pname, '7')
                        playcount.markEpisodeDuringPlayback(self.imdb, self.tmdb, self.season, self.episode, '7')
                    elif not watcher and _property != '6':
                        control.window.setProperty(pname, '6')
                        playcount.markEpisodeDuringPlayback(self.imdb, self.tmdb, self.season, self.episode, '6')

                except Exception as e:
                    c.log(f"[Player._monitor_episode] Monitoring loop error: {e}")
                finally:
                    xbmc.sleep(2000)

            # Clear monitored URL
            global _monitored_url, _monitoring_lock
            with _monitoring_lock:
                _monitored_url = None
            c.log("[Player._monitor_episode] (OK) Monitoring loop ended")

        finally:
            # ═══ ALWAYS RELEASE LOCK ═══
            current_lock = control.window.getProperty(monitoring_lock_property)
            if current_lock == str(id(self)):
                control.window.clearProperty(monitoring_lock_property)
                c.log(f"[Player._monitor_episode] (OK) Released monitoring lock (instance {id(self)})")
            else:
                c.log(f"[Player._monitor_episode] [WARNING] Lock taken by another instance (current={current_lock}, self={id(self)})")

    def _monitor_movie_playback(self, pname, overlay):
        """Monitor movie playback (simpler than episodes - no UpNext).

        Includes:
        - File-based duplicate prevention (v22.8)
        - Monitoring lock (v22.4)
        - Watcher threshold (92%)
        """
        # ═══ DEFENSIVE VALIDATION ═══
        if self.content != 'movie':
            c.log(f"[Player._monitor_movie] CRITICAL: Called with content={self.content} - ABORT")
            return

        c.log("[Player._monitor_movie] Starting movie monitoring loop")

        # ═══ FILE-BASED DUPLICATE PREVENTION (v22.8) ═══
        try:
            current_file = self.getPlayingFile()
            last_processed = control.window.getProperty('thecrew.player.last_processed_file')

            if last_processed and last_processed == current_file:
                c.log(f"[Player._monitor_movie] [WARNING] File already processed: {current_file[:80]}... - EXITING")
                return

            if last_processed and last_processed != current_file:
                c.log(f"[Player._monitor_movie] 🔄 FILE TRANSITION (Movie):")
                c.log(f"[Player._monitor_movie]   Old: {last_processed[:80]}...")
                c.log(f"[Player._monitor_movie]   New: {current_file[:80]}...")

            control.window.setProperty('thecrew.player.last_processed_file', current_file)
            c.log(f"[Player._monitor_movie] (OK) File marked for processing: {current_file[:80]}...")
        except Exception as e:
            c.log(f"[Player._monitor_movie] [WARNING] Could not get playing file: {e}")

        # ═══ MONITORING LOCK (v22.4) ═══
        monitoring_lock_property = 'thecrew.player.monitoring.active'

        if control.window.getProperty(monitoring_lock_property):
            c.log(f"[Player._monitor_movie] [WARNING] Another instance already monitoring - EXITING")
            return

        control.window.setProperty(monitoring_lock_property, str(id(self)))
        c.log(f"[Player._monitor_movie] (OK) Claimed monitoring lock for movie (instance {id(self)})")

        try:
            while self.isPlayingVideo():
                try:
                    self.totalTime = self.getTotalTime()
                    self.currentTime = self.getTime()

                    # v22.3: Guard against division by zero
                    if self.totalTime <= 0:
                        xbmc.sleep(2000)
                        continue

                    watcher = self.currentTime / self.totalTime >= .92
                    _property = control.window.getProperty(pname)

                    if watcher and _property != '7':
                        control.window.setProperty(pname, '7')
                        playcount.markMovieDuringPlayback(self.imdb, '7')
                    elif not watcher and _property != '6':
                        control.window.setProperty(pname, '6')
                        playcount.markMovieDuringPlayback(self.imdb, '6')

                except Exception as e:
                    c.log(f"[Player._monitor_movie] Movie monitoring error: {e}")
                    pass

                xbmc.sleep(2000)
        finally:
            # ═══ ALWAYS RELEASE LOCK ═══
            current_lock = control.window.getProperty(monitoring_lock_property)
            if current_lock == str(id(self)):
                control.window.clearProperty(monitoring_lock_property)
                c.log(f"[Player._monitor_movie] (OK) Released movie monitoring lock (instance {id(self)})")

    def keepPlaybackAlive(self):
        """Main coordinator for playback monitoring.

        Routes to appropriate monitoring method based on content type.
        Handles overlay calculation, playback wait, and playlist position capture.

        Refactored in v22.27 (2026-03-15) to improve maintainability while
        preserving ALL safety mechanisms (file guards, locks, coordination).
        """
        c.log(f"[Player.keepPlaybackAlive] ═══ ENTRY v22.27 ═══ content={getattr(self, 'content', 'UNDEFINED')} instance={id(self)}")

        pname = f"{control.addonInfo('id')}.player.overlay"
        control.window.clearProperty(pname)

        # ═══ CALCULATE OVERLAY BASED ON CONTENT TYPE ═══
        if self.content == 'movie':
            overlay = playcount.get_movie_overlay(playcount.get_movie_indicators(), self.imdb)
        elif self.content == 'episode':
            overlay = playcount.get_episode_overlay(playcount.get_tvshow_indicators(), self.imdb, self.tmdb, self.season, self.episode)
        else:
            overlay = '6'

        c.log(f"[Player.keepPlaybackAlive] Calculated overlay={overlay} for content={self.content}")

        # ═══ WAIT FOR PLAYBACK TO START (up to 240 seconds) ═══
        for __ in range(240):
            if self.isPlayingVideo():
                break
            xbmc.sleep(1000)

        # ═══ CAPTURE PLAYLIST POSITION ═══
        # Done AFTER playback starts to avoid race with previous episode's onPlayBackEnded
        try:
            playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
            if playlist.size() > 1:
                self.playlist_position_on_start = playlist.getposition()
                c.log(f"[Player.keepPlaybackAlive] Captured playlist position: {self.playlist_position_on_start} of {playlist.size()} items")
        except Exception as e:
            c.log(f"[Player.keepPlaybackAlive] Error capturing playlist position: {e}")

        # ═══ ROUTE TO APPROPRIATE MONITORING METHOD ═══
        # v22.27: Refactored to dedicated methods for maintainability
        # All safety mechanisms preserved (file guards, locks, coordination)

        if self.content == 'episode':
            self._monitor_episode_playback(pname, overlay)

        elif self.content == 'movie':
            self._monitor_movie_playback(pname, overlay)

        elif overlay == '7':
            # overlay='7' means already watched - simple monitoring loop for other content types
            while self.isPlayingVideo():
                try:
                    self.totalTime = self.getTotalTime()
                    self.currentTime = self.getTime()
                except Exception:
                    pass
                xbmc.sleep(2000)

        control.window.clearProperty(pname)
        c.log(f"[Player.keepPlaybackAlive] ═══ EXIT ═══")


    def do_rpc(self, method, params):
        """
        Construct a JSON-RPC request string.
        - method: String, e.g., "VideoLibrary.SetMovieDetails"
        - params: Dict, e.g., {"movieid": 123, "playcount": 1}
        Returns the formatted JSON string or None on error.
        """
        try:
            # Serialize params to JSON string
            params_json = json.dumps(params)
            return '{"jsonrpc": "2.0", "method": "%s", "params": %s, "id": 1}' % (
                method,
                params_json,
            )
        except Exception as e:
            if c.devmode:
                c.log(f"[Player.do_rpc] Failed to construct RPC: {e}")
            return None




    #! f-string on rpc impossible for now on py < 3.11 because of nesting-level
    def libForPlayback(self):
        """Update Kodi library playcount if item exists in library and integration is enabled."""
        with contextlib.suppress(Exception):
            if not self.DBID:
                return

            if self.content == 'movie':
                self.do_rpc('VideoLibrary.SetMovieDetails', {"movieid" : int(self.DBID), "playcount" : 1})
            elif self.content == 'episode':
                self.do_rpc('VideoLibrary.SetEpisodeDetails', {"episodeid" : int(self.DBID), "playcount" : 1})

    def idleForPlayback(self):
        for _ in range(400):
            if control.condVisibility('Window.IsActive(busydialog)') == 1 or\
                control.condVisibility('Window.IsActive(busydialognocancel)') == 1:
                control.idle()
            else:
                break
            control.sleep(100)

    def onAVStarted(self) -> None:
        try:
            control.execute('Dialog.Close(all,true)')

            # VERSION MARKER: v22 - SINGLE GLOBAL PLAYER with mode tracking
            c.log(f"[Player] ═══ onAVStarted() ENTRY - VERSION 2025-02-28-v22.26 - CREWMONITOR ZERO-GROWTH ═══")
            c.log(f"[Player] Instance: {self.instance_id} | Mode: {get_player_mode()}")

            # Debounce duplicate onAVStarted calls (Kodi fires this multiple times for same video)
            current_time = time.time()

            # Initialize debounce tracking if needed (for existing player instances)
            if not hasattr(self, 'last_avstarted_time'):
                self.last_avstarted_time = 0
                self.last_avstarted_url = None

            # Check if we're expecting new playback (from UpNext auto-play)
            # This flag acts as a one-time bypass token - only ONE call gets through
            global _expect_new_playback
            expecting = False
            with _expect_lock:
                if _expect_new_playback:
                    expecting = True
                    _expect_new_playback = False  # Clear immediately so only first call gets through
                    c.log("[Player] BYPASS: Expecting new playback - allowing this ONE call")

            # Check if Up Next dialog is currently showing - don't process onAVStarted during dialog
            try:
                from . import upnext as upnext_module
                if upnext_module._dialog_showing:
                    c.log("[Player] BLOCKED: Up Next dialog is showing, ignoring onAVStarted (prevents dialog interruption)")
                    return
            except Exception as e:
                c.log(f"[Player] Could not check dialog state: {e}")

            # If we're not expecting new playback, apply strict debounce
            if not expecting:
                # Hard debounce: Ignore ALL calls within 5 seconds (Kodi fires duplicates at 0s, 0.5s, 2s, etc)
                time_since_last = current_time - self.last_avstarted_time
                if time_since_last < 5.0:
                    c.log(f"[Player] BLOCKED: Ignoring duplicate onAVStarted (debounce: {time_since_last:.2f}s < 5s)")
                    return
                c.log(f"[Player] ACCEPTED: New video after {time_since_last:.2f}s")
            else:
                c.log("[Player] ACCEPTED: Via bypass flag")
                # CRITICAL: Clear offset immediately for Up Next auto-play
                # Service player retains offset from previous video, must clear BEFORE any seek operations
                self.offset = 0.0
                c.log("[Player] (OK) Cleared offset immediately (Up Next bypass active)")

            # Update debounce tracking IMMEDIATELY to protect against subsequent calls
            self.last_avstarted_time = current_time

            # Get current playback URL
            try:
                current_url = self.getPlayingFile()
            except (RuntimeError, Exception):
                current_url = None

            # URL-based duplicate detection: Block if same URL as last processed
            # This prevents multiple onAVStarted() calls from killing the monitoring loop
            if not expecting and current_url and current_url == self.last_avstarted_url:
                c.log(f"[Player] BLOCKED: Same URL as last onAVStarted (duplicate event for same video)")
                return

            # Update URL tracking
            self.last_avstarted_url = current_url
            c.log(f"[Player] Processing new playback (URL: {current_url[:60] if current_url else 'None'}...)")

            # Close persistent overlay when playback starts (unified UX)
            try:
                c.log('[Player] Attempting to close persistent overlay...')
                from . import sources
                c.log(f'[Player] Sources module imported, checking if overlay active...')
                if sources.is_overlay_active():
                    c.log('[Player] Overlay IS active, getting instance...')
                    overlay = sources.get_active_overlay()
                    if overlay:
                        c.log(f'[Player] Got overlay instance, calling force_close()...')
                        overlay.force_close()
                        c.log('[Player] (OK) Closed persistent overlay on playback start')
                    else:
                        c.log('[Player] [WARNING] Overlay reported active but get_active_overlay() returned None')
                else:
                    c.log('[Player] No overlay active (skipping close)')
            except Exception as e:
                c.log(f'[Player] (X) Error closing persistent overlay: {e}')
                import traceback
                c.log(f'[Player] Traceback: {traceback.format_exc()}')

            # Reset Up Next trigger for new video
            self.upnext_triggered = False
            if not hasattr(self, 'last_upnext_trigger_time'):
                self.last_upnext_trigger_time = 0  # Initialize if doesn't exist

            # Track when this video started playing (for stale timing protection)
            self.video_start_time = current_time
            c.log(f"[Player] Set video_start_time={current_time}")

            # Reset playback timing to prevent false triggers with stale data
            self.totalTime = 0
            self.currentTime = 0
            c.log("[Player] Reset playback timing for new video")

            # Sync with global metadata if this is the service player instance
            # When sources.py creates temporary player().run(), it stores metadata globally
            # The persistent service player needs to read that metadata to stay current
            try:
                global _latest_episode_metadata, _metadata_lock
                with _metadata_lock:
                    metadata_age = current_time - _latest_episode_metadata['timestamp']
                    # Only use if metadata was updated in last 10 seconds (fresh from player.run())
                    if metadata_age < 10.0 and _latest_episode_metadata['season']:
                        old_ep = f"S{self.season}E{self.episode}" if self.season and self.episode else "None"

                        self.title = _latest_episode_metadata['title']
                        self.season = _latest_episode_metadata['season']
                        self.episode = _latest_episode_metadata['episode']
                        self.imdb = _latest_episode_metadata['imdb']
                        self.tmdb = _latest_episode_metadata.get('tmdb')
                        self.tvdb = _latest_episode_metadata.get('tvdb')
                        self.year = _latest_episode_metadata['year']
                        self.content = _latest_episode_metadata['content']

                        # CRITICAL: Clear offset for Up Next auto-play to prevent seeking to old position
                        # Service player instance retains offset from previous video, must clear it
                        is_upnext = _latest_episode_metadata.get('is_upnext', False)
                        if is_upnext:
                            self.offset = 0.0
                            c.log("[Player] (OK) Cleared offset for Up Next auto-play (prevent stale seek)")

                        new_ep = f"S{self.season}E{self.episode}"
                        if old_ep != new_ep:
                            c.log(f"[Player] (OK) Synced with global metadata: {old_ep} -> {new_ep} (age: {metadata_age:.1f}s)")
                        else:
                            c.log(f"[Player] Global metadata unchanged: {new_ep}")
                    else:
                        c.log(f"[Player] No fresh global metadata (age: {metadata_age:.1f}s)")
            except Exception as e:
                c.log(f"[Player] Could not sync with global metadata: {e}")

            # v22.2: URL-based duplicate detection moved to _monitor_tv_evening_playback()
            # No need for duplicate checking here - monitoring thread handles it

            # Check if we're in a TV Evening playlist
            playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
            playlist_size = playlist.size()
            playlist_position = playlist.getposition()
            in_playlist = playlist_size > 1

            # Mark episode as started in TV Evening database
            try:
                db = tvevening_playlist_db.get_playlist_db()
                if db.get_playlist_size() > 0:
                    # TV Evening playlist is active

                    # Safeguard: Only process if we have a valid playlist position
                    if playlist_position < 0:
                        c.log(f"[Player] TV Evening active but playlist_position={playlist_position} (invalid), skipping database update")
                    else:
                        # Mark current episode as started
                        db.mark_episode_started(playlist_position)
                        c.log(f"[Player] Marked TV Evening episode {playlist_position} as started")

                        # Capture the starting position for monitoring thread
                        self.current_episode_position = playlist_position

                        # Stop any existing monitoring thread (playlist auto-advance doesn't call onPlayBackStopped)
                        if self.monitoring_thread and self.monitoring_thread.is_alive():
                            c.log(f"[Player] Stopping old monitoring thread before starting new one")
                            self.stop_monitoring = True
                            # Wait up to 1 second for old thread to fully exit
                            for i in range(10):
                                if not self.monitoring_thread.is_alive():
                                    break
                                xbmc.sleep(100)
                            if self.monitoring_thread.is_alive():
                                c.log(f"[Player] Warning: Old monitoring thread still alive after 1s, starting new one anyway")

                        # Check if new TVEveningMonitor is active (via window property)
                        tv_evening_active = control.window.getProperty('thecrew.tvevening.monitor.active') == 'true'
                        c.log(f"[Player] Checking TV Evening Monitor: tv_evening_active={tv_evening_active}")

                        if tv_evening_active:
                            c.log("[Player] TVEveningMonitor is active - skipping old monitoring thread")
                        else:
                            # v22.26: Submit TV Evening monitoring to CrewMonitor queue (legacy mode)
                            c.log("[Player] Starting legacy monitoring via CrewMonitor queue")
                            self.stop_monitoring = False

                            monitor = _get_crew_monitor()
                            if monitor and hasattr(monitor, 'episode_queue'):
                                episode_data = {
                                    'player_instance': self,
                                    'player_instance_id': self.instance_id,
                                    'playlist_position': playlist_position,
                                }
                                monitor.episode_queue.put(episode_data)
                                c.log(f"[Player] (OK) Submitted TV Evening episode to CrewMonitor queue for position {playlist_position}")
                            else:
                                # Fallback
                                c.log("[Player] [WARNING] CrewMonitor not available, spawning fallback thread")
                                self.monitoring_thread = threading.Thread(target=self._monitor_tv_evening_playback)
                                self.monitoring_thread.daemon = True
                                self.monitoring_thread.start()
                                c.log(f"[Player] Started fallback TV Evening monitoring thread for position {playlist_position}")
                else:
                    # For non-playlist episodes (regular UpNext auto-play via PlayMedia()):
                    # UpNext calls PlayMedia() which triggers onAVStarted() but NOT run()
                    # So we need to start keepPlaybackAlive monitoring here for episode 2, 3, 4...
                    # BUT: Only if run() is NOT already handling it (check flag to avoid duplicate monitoring)
                    if self.content == 'episode' and not getattr(self, 'run_will_monitor', False):
                        c.log("[Player.onAVStarted] Non-TV Evening episode - submitting to CrewMonitor queue for UpNext monitoring")

                        # v22.26: Submit to CrewMonitor queue (reuses persistent worker)
                        monitor = _get_crew_monitor()
                        if monitor and hasattr(monitor, 'episode_queue'):
                            episode_data = {
                                'player_instance': self,
                                'player_instance_id': self.instance_id,
                            }
                            monitor.episode_queue.put(episode_data)
                            c.log("[Player.onAVStarted] (OK) Submitted episode to CrewMonitor queue")
                        else:
                            # Fallback
                            c.log("[Player.onAVStarted] [WARNING] CrewMonitor not available, spawning fallback thread")
                            monitoring_thread = threading.Thread(target=self.keepPlaybackAlive)
                            monitoring_thread.daemon = True
                            monitoring_thread.start()
                            c.log("[Player.onAVStarted] Started fallback monitoring thread")
                    elif self.content == 'episode' and getattr(self, 'run_will_monitor', False):
                        c.log("[Player.onAVStarted] Skipping monitoring - run() will handle it (prevent duplicate)")

                # Only handle bookmarks if there's an offset to resume from
                if self.offset:
                    if control.setting('bookmarks.auto') == 'true':
                        self.seekTime(float(self.offset))
                    else:
                        self.pause()
                        minutes, seconds = divmod(float(self.offset), 60)
                        hours, minutes = divmod(minutes, 60)
                        label = f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
                        label = c.lang(32350) % label
                        if control.setting('bookmarks') == 'true' and trakt.get_trakt_credentials_info() is True:
                            yes = control.yesnoDialog(label + '[CR][I]Trakt sync is enabled [scrobble][/I] ', heading=c.lang(32344)) #RESUME
                        else:
                            yes = control.yesnoDialog(label, heading=c.lang(32344)) #RESUME
                        if yes:
                            self.seekTime(float(self.offset))
                        if not yes:
                            self.seekTime(0.0)
                        control.sleep(1000)
                        self.pause()

                # Select preferred audio track (English) - independent of subtitle settings
                # Only select here if run() won't handle it (prevents duplicate selection)
                if not getattr(self, 'run_will_monitor', False):
                    self.select_audio_track()
                else:
                    c.log("[Player.onAVStarted] Skipping audio selection - run() will handle it (prevent duplicate)")

                # Fetch subtitles if enabled (using modern Subtitles class)
                subtitles.Subtitles().fetch_and_load(self.name, self.imdb, self.season, self.episode)
                self.idleForPlayback()
            except Exception as e:
                # traceback already imported at module level
                failure = traceback.format_exc()
                c.log(f'[Player.onPlayBackStarted] Traceback: {failure}')
                c.log(f'[Player.onPlayBackStarted] Exception: {e}')
                pass
        except Exception as e:
            failure = traceback.format_exc()
            c.log(f'[Player.onPlayBackStarted] Traceback: {failure}')
            c.log(f'[Player.onPlayBackStarted] Exception: {e}')
            pass

    def _monitor_tv_evening_playback(self):
        """
        Background thread that monitors TV Evening playlist playback.
        Checks for Up Next trigger and handles database-backed next episode.

        NOTE: This is the OLD/LEGACY monitoring system.
        It is now DISABLED when the new TVEveningMonitor (tvevening_monitor.py) is active.
        """
        # v22: URL-based duplicate detection - only ONE monitoring loop per URL
        global _monitored_url, _monitoring_lock

        current_url = self.getPlayingFile() if self.isPlayingVideo() else None
        if not current_url:
            c.log("[Player Monitor] No URL to monitor, exiting")
            return

        # Atomic check-and-set
        with _monitoring_lock:
            if _monitored_url == current_url:
                c.log(f"[Player Monitor] [WARNING] REJECTED: Already monitoring this URL")
                return
            _monitored_url = current_url
            c.log(f"[Player Monitor] (OK) Starting monitoring loop for URL")

        # Check if new TVEveningMonitor system is active (via window property)
        tv_evening_active = control.window.getProperty('thecrew.tvevening.monitor.active') == 'true'

        if tv_evening_active:
            c.log("[Player Monitor] New TVEveningMonitor is active - EXITING old monitoring system immediately")
            # Clear monitored URL so another thread can try later
            with _monitoring_lock:
                _monitored_url = None
            return  # Exit immediately - new monitor handles everything

        # Capture the episode position at thread start to avoid race conditions
        episode_position = self.current_episode_position
        c.log(f"[Player Monitor] TV Evening monitoring thread started for position {episode_position} (LEGACY MODE)")
        import time

        try:
            while not self.stop_monitoring:
                # Continuous check: Exit if new TVEveningMonitor becomes active (via window property)
                tv_evening_active = control.window.getProperty('thecrew.tvevening.monitor.active') == 'true'
                if tv_evening_active:
                    c.log("[Player Monitor] New TVEveningMonitor detected - EXITING old monitoring loop")
                    break

                # Check if still playing
                if not self.isPlaying():
                    c.log("[Player Monitor] Playback stopped, exiting monitor")
                    break

                # Get database instance
                try:
                    db = tvevening_playlist_db.get_playlist_db()
                    db_size = db.get_playlist_size()

                    # Only monitor if TV Evening database is active
                    if db_size == 0:
                        c.log("[Player Monitor] No TV Evening playlist in database, exiting monitor")
                        break

                    # Check Up Next trigger
                    if upnext.is_enabled():
                        try:
                            currentTime = self.getTime()
                            totalTime = self.getTotalTime()

                            if totalTime > 0:
                                trigger_percent = upnext.get_trigger_percent() / 100.0
                                countdown_seconds = upnext.get_countdown_seconds()

                                # Calculate trigger time accounting for countdown duration
                                # Countdown should FINISH at trigger_percent, so start EARLIER
                                target_time_seconds = (totalTime * trigger_percent) - countdown_seconds

                                if currentTime >= target_time_seconds:
                                    # Thread-safe check-and-set to prevent double-triggering
                                    with self.upnext_lock:
                                        if self.upnext_triggered:
                                            continue  # Already triggered, skip

                                        # SAFETY CHECK: Don't trigger more than once per 60 seconds
                                        import time
                                        current_time = time.time()
                                        if not hasattr(self, 'last_upnext_trigger_time'):
                                            self.last_upnext_trigger_time = 0
                                        time_since_last_trigger = current_time - self.last_upnext_trigger_time

                                        # ADDITIONAL SAFETY: Require at least 30 seconds of playback
                                        if currentTime < 30:
                                            c.log(f"[Player Monitor] SAFETY: Ignoring trigger (only {currentTime:.1f}s played, minimum 30s)")
                                            continue

                                        if time_since_last_trigger < 60.0 and self.last_upnext_trigger_time > 0:
                                            c.log(f"[Player Monitor] SAFETY: Ignoring trigger (only {time_since_last_trigger:.1f}s since last, minimum 60s)")
                                            continue

                                        self.upnext_triggered = True
                                        self.last_upnext_trigger_time = current_time
                                        actual_percent = (currentTime / totalTime) * 100
                                        finish_percent = trigger_percent * 100
                                        c.log(f"[Player Monitor] Up Next triggered at {actual_percent:.1f}% (countdown will finish at ~{finish_percent:.0f}% in {countdown_seconds}s)")
                                        c.log(f"[Player Monitor] Timing: played {currentTime:.1f}s of {totalTime:.1f}s")

                                    # Use the captured episode position, not current playlist position
                                    # This avoids race condition where Kodi advances playlist during seek
                                    next_episode_db = db.get_next_episode(episode_position)

                                    if next_episode_db:
                                        c.log(f"[Player Monitor] Found next episode in database at position {episode_position + 1}: {next_episode_db['tvshowtitle']} S{next_episode_db['season']:02d}E{next_episode_db['episode']:02d}")

                                        # Mark current episode as watched
                                        db.mark_episode_watched(episode_position)
                                        c.log(f"[Player Monitor] Marked episode {episode_position} as watched")

                                        # Stop playback cleanly before showing countdown
                                        c.log("[Player Monitor] Stopping playback for countdown screen")
                                        self.stop()

                                        # Wait for playback to fully stop
                                        xbmc.sleep(500)

                                        # Show countdown dialog
                                        c.log("[Player Monitor] Showing countdown dialog")

                                        # Get addon path for dialog XML
                                        artwork_addon = xbmcaddon.Addon('script.thecrew.artwork')
                                        addon_path = artwork_addon.getAddonInfo('path')

                                        # Store addon path in window property for dialog
                                        xbmcgui.Window(10000).setProperty('script.thecrew.artwork.path', addon_path)

                                        # Create and show countdown dialog
                                        style = c.appearance()

                                        countdown_dialog = tvevening_countdown.TVEveningCountdown(
                                            'TVEveningCountdown.xml',
                                            addon_path,
                                            style=style,
                                            next_episode=next_episode_db,
                                            countdown=60
                                        )

                                        countdown_dialog.doModal()
                                        user_choice = countdown_dialog.get_user_choice()
                                        del countdown_dialog

                                        c.log(f"[Player Monitor] Countdown finished with choice: {user_choice}")

                                        if user_choice == 'play' or user_choice is None:
                                            # User clicked Play Now or countdown expired - play next episode
                                            c.log("[Player Monitor] Starting next episode")

                                            # Get episode URL from database
                                            next_url = next_episode_db.get('url')

                                            if next_url:
                                                # Play next episode
                                                xbmc.executebuiltin(f'PlayMedia({next_url})')
                                                c.log(f"[Player Monitor] Started playback: {next_episode_db['tvshowtitle']} S{next_episode_db['season']:02d}E{next_episode_db['episode']:02d}")
                                                # Wait for playback to actually start
                                                c.log("[Player Monitor] Waiting for new episode to start playing...")
                                                playback_started = False

                                                for i in range(50):  # Wait up to 5 seconds
                                                    xbmc.sleep(100)
                                                    if self.isPlaying():
                                                        playback_started = True
                                                        c.log("[Player Monitor] New episode is now playing")
                                                        break

                                                if not playback_started:
                                                    c.log("[Player Monitor] ERROR: New episode failed to start", trace=1)
                                                    self.stop_monitoring = True
                                                    continue

                                                # Reset trigger for next episode
                                                self.upnext_triggered = False
                                            else:
                                                c.log("[Player Monitor] Error: No URL found for next episode", trace=1)
                                                self.stop_monitoring = True

                                        elif user_choice == 'cancel':
                                            # User cancelled - stop TV Evening
                                            c.log("[Player Monitor] User cancelled TV Evening")
                                            self.stop_monitoring = True
                                        c.log(f"[Player Monitor] No next episode found after position {episode_position} (end of playlist)")

                        except Exception as e:
                            c.log(f"[Player Monitor] Error in Up Next check: {e}")
                            failure = traceback.format_exc()
                            c.log(f"[Player Monitor] Traceback: {failure}")

                except Exception as e:
                    c.log(f"[Player Monitor] Error accessing database: {e}")
                    failure = traceback.format_exc()
                    c.log(f"[Player Monitor] Traceback: {failure}")

                # Sleep briefly between checks
                time.sleep(1)

        except Exception as e:
            c.log(f"[Player Monitor] Fatal error in monitoring thread: {e}")
            failure = traceback.format_exc()
            c.log(f"[Player Monitor] Traceback: {failure}")

        finally:
            # v22: Clear monitored URL so next video can start monitoring
            # (already declared global at function start - don't redeclare)
            with _monitoring_lock:
                if _monitored_url == current_url:
                    _monitored_url = None
                    c.log(f"[Player Monitor] Cleared monitored URL (allowing next video)")
            c.log(f"[Player Monitor] TV Evening monitoring thread stopped for position {episode_position}")

    def update_time(self, state):
        """Update playback time and scrobble to Trakt.

        This function logs the playback action and sends scrobble data to Trakt
        when scrobbling is enabled. Shows notifications in dev mode.

        Args:
            state: 'start', 'pause', or 'stop' - the playback action to scrobble
        """
        try:
            c.log(f"[Player] update_time({state}) called - imdb={self.imdb}, tmdb={getattr(self, 'tmdb', None)}, S{self.season}E{self.episode}")

            # For 'stop': the player has already stopped so getTime() returns 0.
            # Use the last value polled by the monitoring loop (self.currentTime).
            # For 'start'/'pause': the player is still active, read live from Kodi.
            if state == 'stop':
                current_time = self.currentTime
                total_time = self.totalTime
            else:
                try:
                    current_time = self.getTime()
                    total_time = self.getTotalTime()
                except Exception:
                    current_time = self.currentTime
                    total_time = self.totalTime

            c.log(f"[Player] update_time times: current={current_time:.1f}s total={total_time:.1f}s")

            # Update cached values
            if total_time > 0:
                self.currentTime = current_time
                self.totalTime = total_time

            # Save local resume point on pause/stop (not on start - would overwrite before seek)
            # Use tmdb as fallback identifier when imdb is absent
            imdb_key = self.imdb or ''
            tmdb_key = getattr(self, 'tmdb', None) or 0
            if state in ('pause', 'stop') and total_time > 0 and (imdb_key or tmdb_key):
                try:
                    bookmarks.reset(
                        current_time, total_time, self.content,
                        imdb_key, self.season or '', self.episode or '',
                        tmdb=int(tmdb_key) if tmdb_key else 0
                    )
                    c.log(f"[Player] (OK) Local resume point saved: {current_time:.0f}s / {total_time:.0f}s ({current_time/total_time*100:.1f}%)")
                except Exception as e:
                    c.log(f"[Player] Error saving local resume point: {e}")

            # Scrobble to Trakt if credentials are configured and scrobbling is enabled
            if (trakt.get_trakt_credentials_info() is True and control.setting('trakt.scrobble') == 'true'):
                # Convert None to empty strings (movies have None for season/episode, imdb can be None)
                bookmarks.set_scrobble(
                    current_time, total_time, self.content,
                    imdb_key, self.season or '', self.episode or '', state
                )
        except Exception as e:
            c.log(f"[Player] Error in update_time({state}): {e}")

    def onPlayBackResumed(self):
        self.update_time('start')

    def onPlayBackPaused(self):
        self.update_time('pause')

    def onPlayBackStopped(self):
        # v22.6: Clear file-based tracking when playback stops
        control.window.clearProperty('thecrew.player.last_processed_file')
        c.log("[Player] (OK) Cleared file-based tracking (playback stopped)")

        # Refresh container if episodes were marked as watched during playback
        try:
            needs_refresh = control.window.getProperty('thecrew.container.needs_refresh') == 'true'
            if needs_refresh:
                c.log("[Player] Refreshing container to show updated watch status")
                control.refresh()
                control.window.clearProperty('thecrew.container.needs_refresh')
        except Exception as e:
            c.log(f"[Player] Error refreshing container: {e}")

        # Stop TV Evening Monitor if active (via window property)
        try:
            tv_evening_active = control.window.getProperty('thecrew.tvevening.monitor.active') == 'true'
            if tv_evening_active:
                c.log("[Player] onPlayBackStopped - TV Evening Monitor active, getting instance to stop it")
                active_monitor = tvevening_monitor.get_tv_evening_monitor()
                if active_monitor:
                    active_monitor.stop_session()
        except Exception as e:
            c.log(f"[Player] Error stopping TV Evening Monitor: {e}")

        self.stop_monitoring = True  # Stop legacy monitoring thread
        self.update_time('stop')

        # Flush any queued scrobbles immediately (don't wait for the 5-minute service cycle)
        try:
            from resources.lib.modules import trakt as _trakt
            _trakt.process_scrobble_queue()
            c.log("[Player] (OK) Scrobble queue flushed on playback stop")
        except Exception as e:
            c.log(f"[Player] Error flushing scrobble queue on stop: {e}")

    def onPlayBackEnded(self):
        # v22.6: Clear file-based tracking when playback ends (new episode can start)
        control.window.clearProperty('thecrew.player.last_processed_file')
        c.log("[Player] (OK) Cleared file-based tracking (playback ended)")

        # Check if TV Evening Monitor is handling playback (via window property)
        try:
            tv_evening_active = control.window.getProperty('thecrew.tvevening.monitor.active') == 'true'
            if tv_evening_active:
                c.log("[Player] onPlayBackEnded - TV Evening Monitor is active, letting it handle transitions")
                self.update_time('stop')
                return  # Exit early - let monitor handle everything
        except Exception as e:
            c.log(f"[Player] Error checking TV Evening Monitor: {e}")

        self.stop_monitoring = True  # Stop legacy monitoring thread

        # Check if we're in a playlist and need to manually advance
        try:
            import time
            current_time = time.time()
            time_since_last_playnext = current_time - self.last_playnext_time

            playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
            playlist_size = playlist.size()
            current_position = playlist.getposition()

            c.log(f"[Player] onPlayBackEnded - Playlist size: {playlist_size}, current position: {current_position}, position_on_start: {self.playlist_position_on_start}, time_since_last_playnext: {time_since_last_playnext:.2f}s")

            # Only advance if:
            # 1. We're in a playlist (size > 1)
            # 2. Position hasn't already changed (Kodi auto-advanced)
            # 3. We haven't called playnext() in the last 2 seconds (prevents race condition)
            # 4. We're not at the last item
            if playlist_size > 1:
                # Check if Kodi already auto-advanced to next episode
                if current_position != self.playlist_position_on_start:
                    c.log(f"[Player] Kodi auto-advanced from position {self.playlist_position_on_start} to {current_position}, skipping manual advance")
                elif time_since_last_playnext <= 2.0:
                    c.log(f"[Player] Skipping playnext() - called {time_since_last_playnext:.2f}s ago (too recent)")
                elif current_position < (playlist_size - 1):
                    next_position = current_position + 1
                    c.log(f"[Player] Manually advancing playlist from position {current_position} to {next_position}")

                    try:
                        # Use playlist.play() with position instead of playnext() for more reliable advancement
                        playlist.play(next_position)
                        self.last_playnext_time = time.time()
                        c.log(f"[Player] playlist.play({next_position}) called successfully, timestamp updated")
                    except Exception as e:
                        c.log(f"[Player] Error advancing playlist: {e}")
                else:
                    c.log(f"[Player] At end of playlist - no advance needed")
            else:
                # Not in a playlist - check if we should auto-play next episode (binge mode)
                c.log("[Player] Not in playlist - checking if Up Next should trigger")

                # Only auto-play next episode if:
                # 1. Up Next is enabled
                # 2. This is a TV episode (has season/episode)
                # 3. Up Next didn't already trigger during playback (user watched to end without using Up Next)
                if (self.content == 'episode' and
                    self.season and self.episode and
                    self.title and self.imdb):

                    try:
                        # Check if Up Next is enabled
                        if upnext.is_enabled():
                            c.log(f"[Player] Episode ended naturally: {self.title} S{self.season}E{self.episode}")
                            c.log("[Player] Auto-playing next episode (fallback for missed Up Next)")

                            # Get next episode info
                            next_episode = upnext.get_next_episode(
                                self.imdb,
                                self.tmdb,
                                int(self.season),
                                int(self.episode),
                                tvshowtitle=self.title,
                                year=self.year
                            )

                            if next_episode:
                                c.log(f"[Player] Next episode: S{next_episode['season']:02d}E{next_episode['episode']:02d}")

                                # Play next episode directly (no dialog since episode already ended)
                                upnext.play_next_episode(next_episode)
                            else:
                                c.log("[Player] No next episode found")
                    except Exception as e:
                        c.log(f"[Player] Error auto-playing next episode: {e}")
        except Exception as e:
            c.log(f"[Player] Error handling playlist in onPlayBackEnded: {e}")

        # Always update time/scrobble regardless of playlist status
        self.update_time('stop')

    def onPlayBackSeek(self, time, seekOffset):
        if c.devmode:
            secs_time = float(time/60)
            secs_seekOffset = float(seekOffset/60)
            c.log(f"[Player.onPlayBackSeek] time = {secs_time}s, seekOffset = {secs_seekOffset}s")


# Subtitles class moved to subtitles.py for better organization
# Import: from . import subtitles
# Usage: subtitles.Subtitles().fetch_and_load(name, imdb, season, episode)
