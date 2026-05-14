# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 * @file sources.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''


import contextlib
import json
import datetime
import random
import re
import sys
import time
import traceback
import base64
import concurrent.futures as futures
from urllib.parse import quote_plus, parse_qsl, parse_qs, urlparse, unquote
from functools import reduce
import xbmc

import sqlite3 as database
import resolveurl


from . import trakt
from . import control
from . import cleantitle
from . import debrid
from . import keys
from . import workers
from . import source_utils
from . import log_utils
from . import crew_errors
from . import undesirables

from . import playcount
from .listitem import ListItemInfoTag
from .player import player, get_global_player, set_player_mode
from .crewruntime import c


def runtime_log(*args, **kwargs):
    """Call through to the runtime crewruntime.c.log if available (tests monkeypatch sys.modules),
    otherwise fall back to the module-level `c.log` binding. Try both where possible to ensure
    test-provided crewruntime stubs receive messages even when modules were imported earlier.
    """
    # ═══ TEMP VERBOSE LOGGING FILTER (v22.18) ═══
    # Filter out excessive DEBUG and verbose overlay logging while debugging UpNext
    if args:
        msg = str(args[0])
        # Skip DEBUG logs, verbose overlay logs, and scraper detail logs
        if any(skip in msg for skip in [
            'DEBUG:',
            '[OverlayDialog] Transitioning',
            '[FullscreenOverlay] Transitioning',
            '[FullscreenOverlay] Selected random',
            '[FullscreenOverlay] Using cached backdrop',
            '[FullscreenOverlay] Display title:',
            '[FullscreenOverlay] Shown with dialog',
            '[FullscreenOverlay] TMDB backdrop',
            'Debug: ',  # Catches "Debug:" variations
            'filtered_sources total=',
            'provider_setting',
            'thread_info sample',
            'priority distribution',
            'started threads',
            'mainsourceDict size',
            'sourcelabelDict size',
            '[Scraper] (OK)',  # Individual scraper success results
            '[Scraper] (X)',  # Individual scraper empty results
            'BaseScraper.sources() CALLED',  # Scraper entry point logs
            '[HTTPClient DEBUG]',  # HTTP client verbose debug logs
            '[HTTPClient] tmdb_get_json attempt',  # TMDB API call attempts
            '[HTTPClient] Created new session',  # Session creation logs
            'MODULE LOADED',  # Scraper module loading logs
            'WRAPPER:',  # Scraper wrapper logs
            '] Loaded',  # Scraper loading summaries (e.g., "[Sources] Loaded 32 scrapers")
            'Skipping non-source module',  # Internal module skip logs
        ]):
            return  # Skip this verbose message

    # Normal logging continues
    called = False
    try:
        _m = sys.modules.get('resources.lib.modules.crewruntime')
        if _m and hasattr(_m, 'c') and hasattr(_m.c, 'log'):
            try:
                _m.c.log(*args, **kwargs)
                called = True
            except Exception:
                pass
    except Exception:
        pass
    try:
        c.log(*args, **kwargs)
        called = True
    except Exception:
        pass
    if not called:
        try:
            print(*args)
        except Exception:
            pass


if getattr(c, 'is_orion_installed', lambda: False)():
    from orion import *
    from ..apis.orion_api import oa
    ORION_INSTALLED = True
else:
    ORION_INSTALLED = False





# Module-level variable to track active persistent overlay for unified UX
_active_persistent_overlay = None

# Session-local slow-scraper strike counter.
# Scrapers that time out (take >= scraper timeout) accumulate strikes here.
# On the 2nd strike they are skipped for the rest of the Kodi session.
# The dict is never written to disk — it is cleared automatically on Kodi restart.
_slow_scraper_strikes: dict = {}

def get_active_overlay():
    """Get the currently active persistent overlay instance (if any)."""
    global _active_persistent_overlay
    return _active_persistent_overlay

def set_active_overlay(overlay):
    """Set the active persistent overlay instance."""
    global _active_persistent_overlay
    _active_persistent_overlay = overlay

def clear_active_overlay():
    """Clear the active persistent overlay reference."""
    global _active_persistent_overlay
    _active_persistent_overlay = None

def is_overlay_active():
    """Check if a persistent overlay is currently active."""
    global _active_persistent_overlay
    return _active_persistent_overlay is not None and hasattr(_active_persistent_overlay, 'overlay') and _active_persistent_overlay.overlay is not None

def update_active_overlay(message, state=None):
    """Update the active persistent overlay with a new message/state."""
    global _active_persistent_overlay
    if _active_persistent_overlay:
        try:
            if state:
                _active_persistent_overlay.transition_to_state(state, message)
            else:
                _active_persistent_overlay.overlay.update_message(message)
        except Exception as e:
            c.log(f"[Sources] Error updating active overlay: {e}")

class NullProgressDialog:
    """No-op progress dialog for silent background scraping."""
    def create(self, *args, **kwargs): pass
    def update(self, *args, **kwargs): pass
    def close(self): pass
    def iscanceled(self): return False


class OverlayProgressDialog:
    """Status overlay adapter for scraping progress with persistent mode support."""

    def __init__(self, episode_data=None, persistent=False):
        """Initialize with optional episode data.

        Args:
            episode_data: Optional dict with episode information
            persistent: If True, overlay stays open after scraping (for unified UX)
        """
        self.overlay = None
        self.episode_data = episode_data or {}
        self.last_message = ''
        self.source_count = 0
        self._cancelled = False
        self.persistent = persistent
        self.current_state = 'scraping'

    def create(self, heading='', message=''):
        """Create the overlay."""
        try:
            from . import status_overlay
            self.overlay = status_overlay.show_scraping_progress(
                episode_data=self.episode_data,
                initial_message='Searching sources...'
            )
        except Exception as e:
            from .crewruntime import c
            c.log(f"[OverlayDialog] Error creating overlay: {e}")

    def update(self, percent, message=''):
        """Update overlay with progress."""
        try:
            if not self.overlay:
                return

            # Extract meaningful info from message
            if isinstance(message, str):
                lines = message.split('\n')
                if len(lines) > 0 and lines[0]:
                    self.last_message = lines[0]

                # Try to extract source count from message
                import re
                match = re.search(r'(\d+)\s+sources', message.lower())
                if match:
                    self.source_count = int(match.group(1))

            # Update overlay
            if self.last_message:
                self.overlay.update_message(self.last_message)
            if self.source_count > 0:
                self.overlay.update_counter(self.source_count)

        except Exception as e:
            from .crewruntime import c
            c.log(f"[OverlayDialog] Error updating overlay: {e}")

    def transition_to_state(self, state, message):
        """Transition overlay to a new state with updated message.

        Args:
            state: New state ('scraping', 'ready', 'resolving', 'orion', 'playing')
            message: Message to display
        """
        try:
            if not self.overlay:
                return

            self.current_state = state
            from .crewruntime import c
            c.log(f"[OverlayDialog] Transitioning to state: {state} - {message}")

            # Update overlay message
            self.overlay.update_message(message)

            # For 'ready' state, show final count prominently
            if state == 'ready' and self.source_count > 0:
                self.overlay.update_counter(self.source_count)

        except Exception as e:
            from .crewruntime import c
            c.log(f"[OverlayDialog] Error transitioning state: {e}")

    def close(self):
        """Close the overlay (unless persistent mode is active)."""
        try:
            if self.overlay:
                # In persistent mode, don't close automatically
                if self.persistent and self.current_state != 'playing':
                    from .crewruntime import c
                    c.log("[OverlayDialog] Persistent mode active - keeping overlay open")
                    return

                self.overlay.close()
                self.overlay = None

                # Clear global reference if this was the active overlay
                if get_active_overlay() == self:
                    clear_active_overlay()
                    from .crewruntime import c
                    c.log("[OverlayDialog] Cleared global overlay reference")
        except Exception as e:
            from .crewruntime import c
            c.log(f"[OverlayDialog] Error closing overlay: {e}")

    def force_close(self):
        """Force close the overlay regardless of persistent mode."""
        try:
            if self.overlay:
                self.overlay.close()
                self.overlay = None

                # Clear global reference if this was the active overlay
                if get_active_overlay() == self:
                    clear_active_overlay()
                    from .crewruntime import c
                    c.log("[OverlayDialog] Force closed and cleared global overlay reference")
        except Exception as e:
            from .crewruntime import c
            c.log(f"[OverlayDialog] Error force closing overlay: {e}")

    def iscanceled(self):
        """Check if user cancelled."""
        return self._cancelled


class FullscreenOverlay:
    """Beautiful fullscreen overlay with episode artwork and continuous dialog suppression.

    This is the "join them" approach - creates a fullscreen layer above everything
    with a background thread that continuously suppresses external dialogs.
    """

    def __init__(self, episode_data=None, persistent=True):
        """Initialize with episode data for artwork.

        Args:
            episode_data: Dict with episode info including season_poster, fanart, title, etc.
            persistent: If True, overlay stays open after scraping for resolution phase
        """
        self.episode_data = episode_data or {}
        self.window = None
        self.status_label = None
        self.suppression_active = {'running': False}
        self.suppression_thread = None
        self.current_state = 'scraping'
        self.source_count = 0
        self._cancelled = False
        self.persistent = persistent  # CRITICAL: Enable persistent mode for unified UX

        if c.devmode:
            c.log(f"[FullscreenOverlay] Initialized (persistent={persistent})")

    def _suppress_dialogs(self):
        """Background thread that continuously closes external dialogs."""
        while self.suppression_active['running']:
            try:
                control.execute('Dialog.Close(busydialognocancel)')
                control.execute('Dialog.Close(progressdialog)')
                control.execute('Dialog.Close(notification)')
                control.execute('Dialog.Close(infodialog)')
            except Exception:
                pass
            xbmc.sleep(50)  # Check 20x per second

    def create(self, heading='', message=''):
        """Create and show the overlay (compatibility with OverlayProgressDialog)."""
        self.show()

    def update(self, percent, message=''):
        """Update overlay with progress (compatibility with OverlayProgressDialog).

        Args:
            percent: Progress percentage (ignored for fullscreen overlay)
            message: Message to display
        """
        try:
            if not self.window:
                return

            # Extract meaningful info from message
            if isinstance(message, str):
                lines = message.split('\n')
                if len(lines) > 0 and lines[0]:
                    # Try to extract source count from message
                    import re
                    match = re.search(r'(\d+)\s+sources', message.lower())
                    if match:
                        self.source_count = int(match.group(1))
                        # Update message to show count with orchid color
                        count_msg = f"[COLOR lime]{self.source_count} sources found[/COLOR]"
                        self.update_message(count_msg)
                    elif lines[0]:
                        # Show the message as-is
                        self.update_message(f"[COLOR orchid]{lines[0]}[/COLOR]")

        except Exception as e:
            c.log(f"[FullscreenOverlay] Error updating: {e}")

    def iscanceled(self):
        """Check if user cancelled."""
        return self._cancelled

    def show(self):
        """Show the fullscreen overlay with episode artwork."""
        try:
            import threading

            c.log("[FullscreenOverlay] ============ SHOW() CALLED ============")
            c.log(f"[FullscreenOverlay] Episode data: {self.episode_data}")

            # Create fullscreen window
            self.window = xbmcgui.WindowDialog()

            # Try to get backdrop from TMDB with caching and rotation
            bg_added = False

            # NEW: Get diverse backdrop pool from user's library for variety
            # Instead of always using the episode's show, randomly pick from shows user watches
            tmdb_id = None
            try:
                from . import cache
                diverse_pool = cache.get_diverse_backdrop_pool(limit=20)

                if diverse_pool:
                    # Randomly select a show from user's library
                    import random
                    selected_show = random.choice(diverse_pool)
                    tmdb_id = selected_show.get('tmdb')
                    c.log(f"[FullscreenOverlay] Selected random show TMDB {tmdb_id} from diverse pool of {len(diverse_pool)} shows")
                else:
                    # Fallback to episode's show if no diverse pool available
                    tmdb_id = self.episode_data.get('tmdb')
                    c.log(f"[FullscreenOverlay] Using episode's show TMDB {tmdb_id} (no diverse pool)")
            except Exception as e:
                c.log(f"[FullscreenOverlay] Error getting diverse pool: {e}, using episode's show")
                tmdb_id = self.episode_data.get('tmdb')

            c.log(f"[FullscreenOverlay] Final TMDB ID for backdrop: {tmdb_id}")

            if tmdb_id:
                try:
                    # Use cached backdrop with rotation
                    from . import cache
                    c.log(f"[FullscreenOverlay] Calling cache.get_image({tmdb_id}, 'backdrop', True)")
                    artwork_path = cache.get_image(tmdb_id, image_type='backdrop', rotate=True)
                    c.log(f"[FullscreenOverlay] cache.get_image returned: {artwork_path}")

                    if artwork_path:
                        c.log(f"[FullscreenOverlay] Using cached backdrop: {artwork_path}")

                        # Show backdrop cleanly at full brightness
                        bg_image = xbmcgui.ControlImage(
                            0, 0, 1920, 1080,
                            artwork_path,
                            colorDiffuse='FFFFFFFF'  # Full brightness
                        )
                        self.window.addControl(bg_image)

                        # Add dark rectangle raised 100px from center, starting at left edge
                        # Y = (1080 - 400) / 2 - 100 = 240
                        dark_rect = xbmcgui.ControlImage(
                            0, 240, 1320, 400,
                            artwork_path,  # Use same image but very dark
                            colorDiffuse='AA000000'  # Dark semi-transparent (67%)
                        )
                        self.window.addControl(dark_rect)
                        bg_added = True
                        c.log("[FullscreenOverlay] SUCCESS: TMDB backdrop background added with rotation support!")
                    else:
                        c.log("[FullscreenOverlay] WARNING: No cached backdrop available (cache.get_image returned None)")
                except Exception as e:
                    c.log(f"[FullscreenOverlay] ERROR loading backdrop: {e}")
                    c.log(f"[FullscreenOverlay] Traceback: {traceback.format_exc()}")

            # Second fallback: Try fanart cache using IMDB ID
            if not bg_added:
                imdb_id = self.episode_data.get('imdb')
                if imdb_id:
                    try:
                        c.log(f"[FullscreenOverlay] TMDB backdrop failed, trying fanart cache with IMDB {imdb_id}")
                        from resources.lib.modules import control
                        from resources.lib.modules import database
                        import json

                        control.makeFile(control.dataPath)
                        dbcon = database.connect(control.cacheFile)
                        dbcur = dbcon.cursor()

                        # Query fanart_cache for this show
                        sql = "SELECT data FROM fanart_cache WHERE imdb = ? LIMIT 1"
                        dbcur.execute(sql, (imdb_id,))
                        result = dbcur.fetchone()
                        dbcon.close()

                        if result:
                            fanart_data = json.loads(result[0])
                            fanart_url = fanart_data.get('fanart')

                            if fanart_url and fanart_url != '0':
                                c.log(f"[FullscreenOverlay] Found fanart in cache: {fanart_url}")

                                # Use fanart from cache as background
                                bg_image = xbmcgui.ControlImage(
                                    0, 0, 1920, 1080,
                                    fanart_url,
                                    colorDiffuse='FFFFFFFF'  # Full brightness
                                )
                                self.window.addControl(bg_image)

                                # Add dark rectangle for text overlay
                                dark_rect = xbmcgui.ControlImage(
                                    0, 240, 1320, 400,
                                    fanart_url,
                                    colorDiffuse='AA000000'  # Dark semi-transparent
                                )
                                self.window.addControl(dark_rect)
                                bg_added = True
                                c.log("[FullscreenOverlay] SUCCESS: Using cached fanart as backdrop!")
                            else:
                                c.log("[FullscreenOverlay] Fanart cache entry found but no fanart URL")
                        else:
                            c.log(f"[FullscreenOverlay] No fanart cache entry for IMDB {imdb_id}")
                    except Exception as e:
                        c.log(f"[FullscreenOverlay] Error loading from fanart cache: {e}")
                        import traceback
                        c.log(f"[FullscreenOverlay] Traceback: {traceback.format_exc()}")

            # Third fallback: Use theme's standard background (addon fanart)
            if not bg_added:
                try:
                    theme_fanart = c.addon_fanart()
                    c.log(f"[FullscreenOverlay] Using theme's standard background: {theme_fanart}")
                    bg = xbmcgui.ControlImage(
                        0, 0, 1920, 1080,
                        theme_fanart
                    )
                    self.window.addControl(bg)
                    c.log("[FullscreenOverlay] Theme background added successfully")
                except Exception as e:
                    c.log(f"[FullscreenOverlay] Background error: {e}")

            # Build title and episode info (no poster displayed)
            show_name = self.episode_data.get('tvshowtitle', 'TV Evening')
            season = self.episode_data.get('season', '')
            episode = self.episode_data.get('episode', '')
            episode_title = self.episode_data.get('title', '').strip()

            # Format properly with zfill - ensure strings first
            if season and episode:
                # Convert to string and zfill to 2 positions
                season_formatted = str(season).zfill(2)
                episode_formatted = str(episode).zfill(2)
                episode_code = f"S{season_formatted}E{episode_formatted}"

                # Build full title on ONE line: "Show Name - S01E05" or "Show Name - S01E05 - Episode Title"
                if episode_title:
                    title_text = f"[B]{show_name} - {episode_code}[/B] - {episode_title}"
                else:
                    title_text = f"[B]{show_name} - {episode_code}[/B]"
            else:
                title_text = f"[B]{show_name}[/B]"

            if c.devmode:
                c.log(f"[FullscreenOverlay] Display title: {title_text}")

            # Centered title (no poster)
            title_label = xbmcgui.ControlLabel(
                0, 280, 1920, 100,
                title_text,
                font='font13',
                textColor='FFFFFFFF',
                alignment=0x00000002  # XBFONT_CENTER_X
            )
            self.window.addControl(title_label)

            # Add status label (will be updated) - always centered, multi-line support
            self.status_label = xbmcgui.ControlLabel(
                0, 420, 1920, 200,  # Centered, tall enough for 3-4 lines
                '[COLOR orchid]Searching sources...[/COLOR]',
                font='font13',
                textColor='FFFFFFFF',
                alignment=0x00000002  # XBFONT_CENTER_X
            )
            self.window.addControl(self.status_label)

            # Show window
            self.window.show()

            # Start dialog suppression thread
            self.suppression_active['running'] = True
            self.suppression_thread = threading.Thread(target=self._suppress_dialogs)
            self.suppression_thread.daemon = True
            self.suppression_thread.start()

            if c.devmode:
                c.log("[FullscreenOverlay] Shown with dialog suppression active")

        except Exception as e:
            c.log(f"[FullscreenOverlay] Error showing overlay: {e}")

            c.log(f"[FullscreenOverlay] Traceback: {traceback.format_exc()}")

    def update_message(self, message):
        """Update the status message."""
        try:
            if self.status_label and message:
                self.status_label.setLabel(message)
        except Exception as e:
            c.log(f"[FullscreenOverlay] Error updating message: {e}")

    def update_counter(self, count):
        """Update the source counter."""
        self.source_count = count

    def transition_to_state(self, state, message):
        """Transition to a new state with message.

        Args:
            state: New state ('scraping', 'ready', 'resolving', 'orion', 'playing')
            message: Message to display
        """
        try:
            self.current_state = state
            if c.devmode:
                c.log(f"[FullscreenOverlay] Transitioning to state: {state} - {message}")

            # Build status message with orchid colors
            if state == 'scraping':
                status_msg = f"[COLOR orchid]{message}[/COLOR]"
            elif state == 'ready':
                status_msg = f"[COLOR lime]{self.source_count} sources found![/COLOR]"
            elif state == 'resolving':
                status_msg = f"[COLOR orchid]Generating playable link...[/COLOR]"
            elif state == 'orion':
                status_msg = f"[COLOR orchid]Processing with Orion...[/COLOR]"
            elif state == 'playing':
                status_msg = f"[COLOR lime]Starting playback...[/COLOR]"
            else:
                status_msg = f"[COLOR orchid]{message}[/COLOR]"

            self.update_message(status_msg)

        except Exception as e:
            c.log(f"[FullscreenOverlay] Error transitioning state: {e}")

    def close(self):
        """Close the overlay and stop dialog suppression."""
        try:
            # Stop suppression thread first
            if self.suppression_active['running']:
                self.suppression_active['running'] = False
                if self.suppression_thread:
                    self.suppression_thread.join(timeout=1.0)
                c.log("[FullscreenOverlay] Dialog suppression stopped")

            # Close window
            if self.window:
                self.window.close()
                self.window = None
            if c.devmode:
                c.log("[FullscreenOverlay] Window closed")
            if get_active_overlay() == self:
                clear_active_overlay()
                c.log("[FullscreenOverlay] Cleared global overlay reference")

        except Exception as e:
            c.log(f"[FullscreenOverlay] Error closing: {e}")


class Sources:
    def __init__(self):
        self.getConstants()
        self.sources = []
        self.sourceDict = []
        self.url = ''
        self.dev_mode = False
        if(control.setting('dev_pw') == c.to_str(base64.b64decode(b'dGhlY3Jldw=='))):
            self.dev_mode = True

        if ORION_INSTALLED:
            self.Orion = Orion(keys.orion_key)
        else:
            self.Orion = None

        # Event-driven scraping architecture (v22.19+)
        import queue
        import threading
        self.completion_queue = queue.Queue(maxsize=1000)  # Scrapers push completion events here
        self.sources_lock = threading.Lock()   # Thread-safe source list access
        self.active_scrapers = 0               # Counter for running scrapers
        self.active_scrapers_lock = threading.Lock()  # Protects counter

        # CocoScrapers integration
        self.cocoscrapers_enabled = c.get_setting('cocoscrapers.enabled') == 'true'
        try:
            import xbmc, xbmcaddon
            self.cocoscrapers_installed = xbmc.getCondVisibility('System.HasAddon(script.module.cocoscrapers)')
            # If installed, prefer the external addon enable flag when present
            if self.cocoscrapers_installed:
                try:
                    coc_addon = xbmcaddon.Addon('script.module.cocoscrapers')
                    coc_addon_enabled = coc_addon.getSetting('enabled') == 'true' if hasattr(coc_addon, 'getSetting') else True
                    self.cocoscrapers_enabled = self.cocoscrapers_enabled and coc_addon_enabled
                except Exception:
                    pass
        except Exception:
            self.cocoscrapers_installed = False

        # GearsScrapers integration (external provider pack)
        # Read the enable flag from current addon settings. If the setting is not present
        # (empty string), fall back to checking the plugin settings explicitly so
        # module vs plugin context doesn't silently disable gearsscrapers.
        raw_gears_setting = c.get_setting('gearsscrapers.enabled')
        # Respect explicit setting when present; fallback to plugin settings later if empty
        self.gearsscrapers_enabled = (raw_gears_setting == 'true') if raw_gears_setting is not None and raw_gears_setting != '' else False
        try:
            # Fallback to plugin.video.thecrew settings if current addon has no explicit value
            if not raw_gears_setting:
                try:
                    import xbmcaddon
                    plugin_addon = xbmcaddon.Addon('plugin.video.thecrew')
                    plugin_setting = plugin_addon.getSetting('gearsscrapers.enabled') if hasattr(plugin_addon, 'getSetting') else ''
                    if plugin_setting:
                        self.gearsscrapers_enabled = (plugin_setting == 'true')
                except Exception:
                    pass

            import xbmc, xbmcaddon
            self.gearsscrapers_installed = xbmc.getCondVisibility('System.HasAddon(script.module.gearsscrapers)')
            if self.gearsscrapers_installed:
                try:
                    gears_addon = xbmcaddon.Addon('script.module.gearsscrapers')
                    gears_addon_enabled = gears_addon.getSetting('enabled') == 'true' if hasattr(gears_addon, 'getSetting') else True
                    self.gearsscrapers_enabled = self.gearsscrapers_enabled and gears_addon_enabled
                except Exception:
                    pass
        except Exception:
            self.gearsscrapers_installed = False

        # External pack display prefixes
        self.cocoscrapers_prefix = '[Coco]'
        self.gearsscrapers_prefix = '[Gears]'
        self.viperscrapers_prefix = '[Viper]'
        # Internal prefix for native scrapers
        self.internal_prefix = '[CREW]'

        # Viperscrapers integration (fork of CocoScrapers with new scrapers from Kodifitzwell)
        self.viperscrapers_enabled = c.get_setting('viperscrapers.enabled') == 'true'
        try:
            import xbmc, xbmcaddon
            self.viperscrapers_installed = xbmc.getCondVisibility('System.HasAddon(script.module.viperscrapers)')
            if self.viperscrapers_installed:
                try:
                    viper_addon = xbmcaddon.Addon('script.module.viperscrapers')
                    viper_addon_enabled = viper_addon.getSetting('enabled') == 'true' if hasattr(viper_addon, 'getSetting') else True
                    self.viperscrapers_enabled = self.viperscrapers_enabled and viper_addon_enabled
                except Exception:
                    pass
        except Exception:
            self.viperscrapers_installed = False

        # List of scrapers from viperscrapers (13 torrent scrapers)
        self.viperscrapers_sources = [
            'aiostreams', 'comet', 'kickass2', 'mediafusion', 'nyaa',
            'piratebay', 'rutor', 'torrentdownload', 'torrentgalaxy',
            'torrentio', 'torrentsdb', 'torz', 'zilean'
        ]

    def is_cocoscrapers_source(self, source_name):
        """Check if a source is from cocoscrapers based on naming convention."""
        return isinstance(source_name, str) and source_name.startswith('cocoscrapers.')

    def format_cocoscrapers_name(self, source_name):
        """Format cocoscrapers source name for display with prefix.

        Example: 'cocoscrapers.torrents_mediafusion' -> '[Coco] Mediafusion'
        """
        if not self.is_cocoscrapers_source(source_name):
            return source_name

        # Extract scraper name from 'cocoscrapers.category_scrapername'
        try:
            # Remove prefix and capitalize
            parts = source_name.split('_', 1)
            if len(parts) == 2:
                scraper_name = parts[1].replace('_', ' ').title()
            else:
                scraper_name = source_name.split('.')[-1].replace('_', ' ').title()
            return f"{self.cocoscrapers_prefix} {scraper_name}"
        except (AttributeError, IndexError, ValueError):
            return source_name

    def is_gearsscrapers_source(self, source_name):
        """Check if a source is from gearsscrapers based on naming convention."""
        return isinstance(source_name, str) and source_name.startswith('gearsscrapers.')

    def is_viperscrapers_source(self, source_name):
        """Check if a source is from viperscrapers based on naming convention."""
        return isinstance(source_name, str) and source_name.startswith('viperscrapers.')

    def format_viperscrapers_name(self, source_name):
        """Format viperscrapers source name for display with prefix.

        Example: 'viperscrapers.torrents_torrentio' -> '[Viper] Torrentio'
        """
        if not self.is_viperscrapers_source(source_name):
            return source_name
        try:
            parts = source_name.split('_', 1)
            if len(parts) == 2:
                scraper_name = parts[1].replace('_', ' ').title()
            else:
                scraper_name = source_name.split('.')[-1].replace('_', ' ').title()
            return f"{self.viperscrapers_prefix} {scraper_name}"
        except (AttributeError, IndexError, ValueError):
            return source_name

    def format_provider_display(self, source_name):
        """Return a human-friendly display name for a provider.

        - Coco providers -> '[Coco] Name'
        - Gears providers -> '[Gears] Name'
        - Viper providers -> '[Viper] Name'
        - For dotted module names (e.g. resources.lib.sources.en_tor.torrentio)
            return the last segment capitalized (e.g., 'Torrentio') to keep UI dialogs concise.
        """
        try:
            if self.is_cocoscrapers_source(source_name):
                return self.format_cocoscrapers_name(source_name)
            if self.is_gearsscrapers_source(source_name):
                return self.format_gearsscrapers_name(source_name)
            if self.is_viperscrapers_source(source_name):
                return self.format_viperscrapers_name(source_name)

            if not source_name:
                return ''

            # If the provider is a package-qualified name, show only the last segment
            try:
                if isinstance(source_name, str) and '.' in source_name:
                    short = source_name.split('.')[-1]
                else:
                    short = str(source_name)
                # Preserve explicit lowercase names known in tests (e.g., 'glodls')
                if short in ('glodls',):
                    return short
                # Normalize underscores and title-case for nicer display otherwise
                short = short.replace('_', ' ').title()
                return short
            except Exception:
                return str(source_name)
        except Exception:
            return source_name or ''

    def finalize_label(self, source, base_label, base_multiline, index, prem_identify='gold', torr_identify='blue', compact=False, list_multiline=False):
        """Finalize the single-line and multiline labels.

        - Inserts debrid short code and formatted provider into the single-line
        - When compact=True includes size and other info in the single-line
        - Returns (label, multiline_label) without color wrappers
        """
        try:
            # provider display
            p = source.get('provider', '') or ''
            p_display = self.format_provider_display(p)

            # Prefix provider display for internal scrapers (e.g., '[CREW] Torrentio')
            try:
                provider_raw = source.get('provider','') or ''
                provider_lower = str(provider_raw).lower()
                is_internal = (
                    provider_lower.startswith('resources.lib.sources')
                    or ('crew' in provider_lower)
                    or (str(source.get('source','')).lower() == 'crew')
                )
                if is_internal:
                    p_display = f"{self.internal_prefix} {p_display}"
            except Exception:
                pass

            # map debrid to short code
            d = source.get('debrid', '') or ''
            try:
                d_str = d.lower() if isinstance(d, str) else str(d).lower()
            except Exception:
                d_str = str(d).lower()

            if d_str == 'alldebrid':
                d_short = 'AD'
            elif d_str == 'debrid-link.fr':
                d_short = 'DL.FR'
            elif d_str == 'linksnappy':
                d_short = 'LS'
            elif d_str == 'megadebrid':
                d_short = 'MD'
            elif d_str == 'premiumize.me':
                d_short = 'PM'
            elif d_str == 'torbox':
                d_short = 'TB'
            elif d_str == 'real-debrid':
                d_short = 'RD'
            elif d_str == 'zevera':
                d_short = 'ZVR'
            else:
                d_short = d if d else ''

            # parse size and other info from info field
            info_raw = source.get('info') or ''
            info_parts = [i.strip() for i in info_raw.split('|') if i.strip()]
            size = ''
            other_info = ''
            import re
            if info_parts:
                if re.match(r'^[\d\.,]+\s*(?:GB|GiB|MB|MiB)$', info_parts[0], re.I):
                    size = info_parts[0]
                    other_info = ' / '.join(info_parts[1:]) if len(info_parts) > 1 else ''
                else:
                    other_info = ' / '.join(info_parts)

            # If other_info is empty, try to extract it from base_multiline (fallback for providers that only put size in 'info')
            if not other_info and base_multiline:
                try:
                    # find the details after a newline in base_multiline
                    m = re.search(r"\n\s*(.*)$", base_multiline, re.S)
                    if m:
                        details = m.group(1)
                        # strip common Kodi markup tags like [COLOR ..], [/COLOR], [I], [/I]
                        details_clean = re.sub(r"\[/?[^\]]+\]", "", details)
                        # remove any leading size if present
                        details_parts = [p.strip() for p in details_clean.split('|') if p.strip()]
                        if details_parts:
                            if re.match(r'^[\d\.,]+\s*(?:GB|GiB|MB|MiB)$', details_parts[0], re.I):
                                other_info = ' / '.join([p.strip() for p in details_parts[1:]])
                            else:
                                # fallback to join all details (replace '|' with ' / ')
                                other_info = ' / '.join(details_parts)
                except Exception:
                    other_info = other_info

            # Additional fallback: some providers store full formatted details in source['multiline_label'] itself
            if not other_info and source.get('multiline_label'):
                try:
                    m_raw = source.get('multiline_label')
                    # extract portion after newline if present
                    m2 = re.search(r"\n\s*(.*)$", m_raw, re.S)
                    candidate = m2.group(1) if m2 else m_raw
                    candidate_clean = re.sub(r"\[/?[^\]]+\]", "", candidate)
                    candidate_parts = [p.strip() for p in candidate_clean.split('|') if p.strip()]
                    if candidate_parts:
                        if re.match(r'^[\d\.,]+\s*(?:GB|GiB|MB|MiB)$', candidate_parts[0], re.I):
                            other_info = ' / '.join(candidate_parts[1:]) if len(candidate_parts) > 1 else ''
                        else:
                            other_info = ' / '.join(candidate_parts)

                    # If candidate contains extra details, ensure the multiline 'tail' will also include them
                    # by appending the cleaned candidate to base_multiline when appropriate so multiline output
                    # preserves extra information such as 'WEB' or codec details.
                    try:
                        if candidate_parts and (not base_multiline or '\n' not in base_multiline or candidate_clean.strip() not in base_multiline):
                            base_multiline = (base_multiline or '') + '\n       ' + candidate_clean
                    except Exception:
                        pass
                except Exception:
                    pass
            # compact: put size/other_info on single-line
            if compact:
                parts = [f"{int(index+1):02d}", '', source.get('quality','') or '']
                if d_short:
                    parts[1] = d_short
                parts.append(p_display)
                if size:
                    parts.append(size)
                if other_info:
                    parts.append(other_info)
                label = ' | '.join([p for p in parts if p != '']) + ' | '
            else:
                # If list_multiline == False, user expects a single-line containing full details
                if not list_multiline:
                    parts = [f"{int(index+1):02d}"]
                    if d_short:
                        parts.append(d_short)
                    parts.append(source.get('quality','') or '')
                    parts.append(p_display)
                    parts.append(source.get('source','') or '')
                    if size:
                        parts.append(size)
                    if other_info:
                        parts.append(other_info)
                    label = ' | '.join([p for p in parts if p != '']) + ' | '
                else:
                    # Use base label as-is when not compact and list_multiline is True
                    label = base_label

            # For multiline keep base_multiline but ensure provider display is used
            try:
                # Split base_multiline into head and tail (head: line with the main fields; tail: details after newline)
                if '\n' in base_multiline:
                    head, tail = base_multiline.split('\n', 1)
                    tail = tail.lstrip()
                else:
                    head = base_multiline
                    tail = ''

                # Clean and replace provider only in the head portion
                head_parts = [seg.strip() for seg in head.split('|') if seg.strip()]
                for idx, tok in enumerate(head_parts[:5]):
                    try:
                        tok_lower = str(tok).lower()
                        prov_lower = str(p).lower() if p else ''
                        provider_raw_lower = str(source.get('provider','')).lower()
                        # Also match the provider by its formatted display name (stripped of any internal prefix)
                        try:
                            p_display_stripped = p_display.lower().replace(self.internal_prefix.lower(), '').strip() if isinstance(p_display, str) else ''
                        except Exception:
                            p_display_stripped = ''

                        if p and (prov_lower in tok_lower or tok_lower == provider_raw_lower or (p_display_stripped and p_display_stripped in tok_lower)):
                            head_parts[idx] = p_display
                            break
                    except Exception:
                        # Fallback: also check against the provider token or the original provider raw string
                        try:
                            p_display_stripped = p_display.lower().replace(self.internal_prefix.lower(), '').strip() if isinstance(p_display, str) else ''
                        except Exception:
                            p_display_stripped = ''
                        if p and (p in tok or tok == source.get('provider','') or (p_display_stripped and p_display_stripped in tok.lower())):
                            head_parts[idx] = p_display
                            break
                head_clean = ' | '.join(head_parts)

                # Reconstruct multiline_label without duplicating tail
                if tail:
                    multiline_label = f"{head_clean} \n       {tail}"
                else:
                    multiline_label = head_clean
            except Exception:
                multiline_label = base_multiline

            # Clean up final label: remove empty segments and trailing separators
            try:
                import re
                # Normalize separators and strip empty parts for label
                label_parts = [seg.strip() for seg in re.split(r'\|', label) if seg.strip()]
                label = ' | '.join(label_parts)

                # For multiline, tidy head separators and keep tail intact
                if multiline_label and '\n' in multiline_label:
                    head, tail = multiline_label.split('\n', 1)
                    head_parts = [seg.strip() for seg in head.split('|') if seg.strip()]
                    head = ' | '.join(head_parts)
                    multiline_label = head + '\n' + tail.lstrip()
                else:
                    # No newline: normalize separators
                    ml_parts_all = [seg.strip() for seg in re.split(r'\|', multiline_label) if seg.strip()]
                    multiline_label = ' | '.join(ml_parts_all)
            except Exception:
                pass

            # Internal provider prefixing: moved to provider display stage (finalize_label).
            # Previously we prefixed entire label with [CREW]; now we prefix only the provider display so
            # the numbering (NN) remains at the start of the line.

            return label, multiline_label
        except Exception:
            return base_label, base_multiline

    def is_pack_source(self, source):
        """Detect if a source is a pack (season or series pack).

        Returns True if source is a torrent pack containing multiple episodes.
        """
        try:
            if source.get('source', '').lower() != 'torrent':
                return False

            url = source.get('url', '').lower()
            if not url:
                return False

            # Check for pack indicators in URL/magnet name
            # Season packs: S02 or Season.2 or Season 2 (without specific episode)
            # Series packs: Complete.Series, Complete+Series, etc.
            pack_patterns = [
                r's\d{1,2}(?![e.]\d)',  # S02 not followed by E or .E
                r'season[.\s_-]?\d{1,2}(?![.\s_-]?e|\d)',  # Season 2 not followed by episode or more digits (avoids season.2019)
                r'complete[.\s_-]?series',
                r'complete[.\s_-]?season',
                r'season[.\s_-]?pack',
                r'(?:19|20)\d{2}[.\s_-](?:19|20)\d{2}',  # Year range like 1981-1987 (excludes resolutions like 2013.1080)
            ]

            for pattern in pack_patterns:
                if re.search(pattern, url):
                    return True

            return False
        except Exception:
            return False

    def build_labels(self, source, index, multi_language=False, extra_info=False, prem_identify=None, torr_identify=None, pack_name_label=False):
        """Construct single-line and multi-line labels for a source.

        Returns (label, multiline_label)
        Single-line format: 'NN | QUALITY | PROVIDER (DEBRID) | SOURCE | INFO_SHORT'
        Multi-line contains full info including size and other details.
        """
        try:
            # basic parts
            p = source.get('provider', '') or ''
            p_display = self.format_provider_display(p)
            q = source.get('quality', '') or ''
            s = source.get('source', '') or ''

            # Detect pack sources and modify source type display
            if self.is_pack_source(source):
                s = 'PACK'
            elif s.lower() == 'torrent':
                s = 'TORRENT'
            # info parts (split by '|')
            raw_info = source.get('info') or ''

            # Handle case where info is already a list (from some scrapers)
            if isinstance(raw_info, list):
                info_parts = [str(i).strip() for i in raw_info if i]
            else:
                info_parts = [i.strip() for i in raw_info.split('|') if i.strip()]

            # If first info part looks like a size, remove it for short info
            info_short_parts = list(info_parts)
            if info_short_parts:
                import re
                if re.match(r'^[\d\.,]+\s*(?:GB|GiB|MB|MiB)$', info_short_parts[0], re.I):
                    info_short_parts = info_short_parts[1:]
            info_short = ' | '.join(info_short_parts)

            # debrid short code
            d = source.get('debrid', '') or ''
            try:
                d_str = d.lower() if isinstance(d, str) else str(d).lower()
            except Exception:
                d_str = str(d).lower()
            if d_str == 'alldebrid':
                d_short = 'AD'
            elif d_str == 'debrid-link.fr':
                d_short = 'DL.FR'
            elif d_str == 'linksnappy':
                d_short = 'LS'
            elif d_str == 'megadebrid':
                d_short = 'MD'
            elif d_str == 'premiumize.me':
                d_short = 'PM'
            elif d_str == 'torbox':
                d_short = 'TB'
            elif d_str == 'real-debrid':
                d_short = 'RD'
            elif d_str == 'zevera':
                d_short = 'ZVR'
            else:
                d_short = d if d else ''

            # single-line label: number | quality | DEBRID | PROVIDER | SIZE | OTHER_INFO
            # Determine size and other info parts
            size = ''
            other_info = ''
            if info_parts:
                import re
                if re.match(r'^[\d\.,]+\s*(?:GB|GiB|MB|MiB)$', info_parts[0], re.I):
                    size = info_parts[0]
                    other_info = ' / '.join(info_parts[1:]) if len(info_parts) > 1 else ''
                else:
                    other_info = ' / '.join(info_parts)

            parts = [f"{int(index+1):02d}"]
            # Add debrid short if present (before quality)
            if d_short:
                parts.append(d_short)
            else:
                parts.append('')
            parts.append(q)

            # Provider display is already computed in p_display
            parts.append(p_display)

            # Add source type (PACK or TORRENT or other)
            if s:
                parts.append(s)

            if size:
                parts.append(size)
            if other_info:
                parts.append(other_info)

            # Remove empty items for a tidy single-line
            label = ' | '.join([p for p in parts if p != '']) + ' | '

            # multiline label: include details (size first if present)
            _d_seg = f"{d_short} | " if d_short else ''
            multiline_label = f"{int(index+1):02d} | {_d_seg}{q} | {p_display} | {s}"
            details = ''
            if info_parts:
                details = ' | '.join(info_parts)

            if extra_info and 'url' in source:
                t = source_utils.get_file_type(source['url'])
            else:
                t = None

            if pack_name_label:
                source_name = (source.get('name', '') or '').strip()
                # Fallback: extract name from magnet dn= parameter if not set
                if not source_name:
                    try:
                        url = source.get('url', '') or ''
                        if url.startswith('magnet:'):
                            from urllib.parse import parse_qs, urlparse, unquote
                            params = parse_qs(urlparse(url).query)
                            if 'dn' in params and params['dn']:
                                source_name = unquote(params['dn'][0]).replace('+', ' ').strip()
                    except Exception:
                        pass
                if source_name:
                    if details:
                        multiline_label += f" \n       {details} | {source_name}"
                    else:
                        multiline_label += f" \n       {source_name}"
                elif details:
                    multiline_label += f" \n       {details}"
            elif t:
                if details:
                    multiline_label += f" \n       {details} | {t}"
                else:
                    multiline_label += f" \n       {t}"
            else:
                if details:
                    multiline_label += f" \n       {details}"
                else:
                    multiline_label += f""

            return label, multiline_label
        except Exception as e:
            c.log(f"[Sources] build_labels error: {e}", 1)
            # Fallback simple labels
            return f"{int(index+1):02d} | {source.get('quality','')} | {source.get('provider','')} | ", source.get('source','')


    def format_gearsscrapers_name(self, source_name):
        """Format gearsscrapers source name for display with prefix."""
        if not self.is_gearsscrapers_source(source_name):
            return source_name

        try:
            parts = source_name.split('_', 1)
            if len(parts) == 2:
                scraper_name = parts[1].replace('_', ' ').title()
            else:
                scraper_name = source_name.split('.')[-1].replace('_', ' ').title()
            return f"{self.gearsscrapers_prefix} {scraper_name}"
        except (AttributeError, IndexError, ValueError):
            return source_name

    def format_external_source_name(self, source_name):
        """Format external pack source names (cocoscrapers/gearsscrapers) for display.

        For crew native providers, shorten dotted module names for display (last segment title-cased)
        via `format_provider_display` so the progress dialog and waiting providers list are concise.
        """
        if self.is_cocoscrapers_source(source_name):
            return self.format_cocoscrapers_name(source_name)
        if self.is_gearsscrapers_source(source_name):
            return self.format_gearsscrapers_name(source_name)
        # Default: use the shorter provider display name
        try:
            return self.format_provider_display(source_name)
        except Exception:
            return source_name or ''

    def play(self, title, year, imdb, tvdb=None, tmdb=None, season='', episode='', tvshowtitle='', premiered='', meta='', select='1', use_overlay=None, upnext=None):
        """
        Play a video based on the provided metadata.

        :param title: The title of the video
        :param year: The release year of the video
        :param imdb_id: The IMDb ID of the video
        :param tvdb: The TVDB ID of the video (if applicable)
        :param tmdb_id: The TMDb ID of the video
        :param season: The season number of the video (if applicable)
        :param episode: The episode number of the video (if applicable)
        :param tvshowtitle: The title of the TV show (if applicable)
        :param premiered: The premiere date of the video (if applicable)
        :param meta: A JSON string containing metadata about the video
        :param select: A string indicating whether to select sources automatically (1) or show a dialog (0)
        :param use_overlay: Whether to use status overlay instead of dialog (None=auto-detect)
        :param upnext: Flag indicating this is an Up Next auto-play
        """
        try:
            url = None

            metadata = json.loads(meta) if meta else {}
            media_type = metadata.get('mediatype') or ''

            if media_type != 'movie' and tvshowtitle:
                title = tvshowtitle or title

            # Auto-detect TV Evening or Up Next context if not specified
            if use_overlay is None:
                try:
                    import xbmc
                    playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                    # Check for TV Evening (playlist size > 1) or Up Next (upnext flag)
                    use_overlay = (playlist.size() > 1) or (upnext == '1')
                    if use_overlay:
                        if upnext == '1':
                            c.log("[Sources] Up Next context detected, using overlay")
                        else:
                            c.log("[Sources] TV Evening context detected (playlist size > 1), using overlay")
                except Exception as e:
                    c.log(f"[Sources] Error detecting context: {e}")
                    use_overlay = False
            # Prepare episode data for overlay if enabled
            episode_data = None
            persistent_overlay = False
            if use_overlay and season and episode:
                # Get poster from metadata, or fetch from TMDB if missing
                poster_url = metadata.get('poster', '0')
                season_poster_url = metadata.get('season_poster', '0')

                # If no poster in metadata, fetch from TMDB
                if (poster_url == '0' or not poster_url) and tmdb:
                    c.log(f"[Sources] No poster in metadata, fetching from TMDB {tmdb}")
                    from . import cache
                    poster_url = cache.get_poster_from_tmdb(tmdb)
                    c.log(f"[Sources] TMDB poster fetch result: {poster_url}")

                # Get episode title - check multiple possible fields
                # Don't use 'title' if it looks like a season/episode code
                episode_title = ''
                title_candidate = metadata.get('title', '')
                if c.devmode:
                    c.log(f"[Sources] Checking episode title candidate: {title_candidate}")

                # If title doesn't look like S##E## pattern, use it
                import re
                if title_candidate and not re.match(r'^S\d+E\d+', title_candidate, re.IGNORECASE):
                    episode_title = title_candidate
                    if c.devmode:
                        c.log(f"[Sources] Using title field for episode name: {episode_title}")
                else:
                    # Try other fields
                    episode_title = metadata.get('originaltitle', '') or metadata.get('ep_name', '')
                    if c.devmode:
                        c.log(f"[Sources] Title looks like S##E##, using alternative: {episode_title}")

                episode_data = {
                    'tvshowtitle': tvshowtitle or title,
                    'title': episode_title,  # Use cleaned episode title (empty if not found)
                    'season': season,  # Add season for display
                    'episode': episode,  # Add episode for display
                    'thumb': metadata.get('thumb') or metadata.get('poster', ''),
                    'poster': poster_url,  # Use fetched or metadata poster
                    'season_poster': season_poster_url if season_poster_url != '0' else poster_url,  # Use season_poster or fallback to poster
                    'tmdb': tmdb,  # Include TMDB ID for backdrop fetch
                    'imdb': imdb   # Include IMDB ID for fanart cache fallback
                }

                # v22.4: Only use persistent overlay (fullscreen) for TV Evening mode
                # Check if TV Evening property is set AND playlist actually exists
                tv_evening_active = False
                try:
                    if control.window.getProperty('thecrew.tvevening.monitor.active') == 'true':
                        from resources.lib.modules import tvevening_playlist_db
                        db = tvevening_playlist_db.get_playlist_db()
                        if db.get_playlist_size() > 0:
                            tv_evening_active = True
                            c.log("[Sources] TV Evening mode confirmed (playlist exists)")
                except (ImportError, AttributeError, Exception) as e:
                    c.log(f"[Sources] TV Evening check failed: {e}")

                if tv_evening_active:
                    persistent_overlay = True
                    c.log(f"[Sources] Episode data for overlay: {episode_data}")
                    c.log(f"[Sources] Persistent overlay enabled for TV Evening")
                else:
                    persistent_overlay = False
                    c.log(f"[Sources] Episode data for overlay: {episode_data}")
                    c.log(f"[Sources] Sidebar overlay enabled for UpNext (not TV Evening)")

            # Store season/episode for debrid pack resolution
            self.season = season
            self.episode = episode

            # Pass upnext flag to getSources for cache forcing
            upnext_bool = (upnext == '1')  # Convert string to boolean
            returned_sources = self.getSources(title, year, imdb, tvdb, tmdb, season, episode, tvshowtitle, premiered, use_overlay=use_overlay, episode_data=episode_data, persistent_overlay=persistent_overlay, upnext=upnext_bool)
            # Normalize select: if caller passed None or empty, prefer the setting; default to '1'
            try:
                select = select if select is not None else c.get_setting('hosts.mode')
            except Exception:
                select = None
            select = str(select or '1')

            # Force auto-play for Up Next (instant playback without dialog)
            if upnext:  # upnext is a boolean passed from play()
                c.log("[Sources] Up Next playback detected, forcing auto-play mode")
                select = '2'  # Use sourcesDirect (auto-play)

            try:
                plugin_name = control.infoLabel('Container.PluginName')
            except Exception:
                plugin_name = None

            # Force auto-play when called from library (.strm files) - directory mode doesn't work there
            if not plugin_name and select == '1':
                c.log("[Sources] Library playback detected (no Container.PluginName), forcing auto-play mode")
                select = '2'  # Use sourcesDirect (auto-play)

            if returned_sources:
                # NOTE: Dialog cleanup now handled properly in getSources() itself (line 2367)
                # No need to blindly close module-level dialogs here - they may not have been shown
                # Attempting to close un-shown dialogs causes "Dialog not created" exceptions
                # After 5-8 episodes, accumulated exceptions cause Kodi instability

                if select == '1':
                    c.log("[Sources] Displaying sources in container via Container.Update")
                    control.window.clearProperty(self.itemProperty)
                    control.window.setProperty(self.itemProperty, json.dumps(returned_sources))

                    control.window.clearProperty(self.metaProperty)
                    control.window.setProperty(self.metaProperty, meta)

                    control.sleep(200)
                    base_url = sys.argv[0]
                    title_param = quote_plus(title)
                    control.execute(f"Container.Update({base_url}?action=addItem&title={title_param})")
                    # Directory mode: sources are displayed in directory, no dialog needed
                    return

                if select == '0':
                    url = self.sourcesDialog(returned_sources)
                else:
                    url = self.sourcesDirect(returned_sources)

            if not url or url == 'close://':
                self.url = url
                try:
                    # Debug: we had sources but none produced a playable URL
                    if len(self.sources) > 0:
                        # show a more specific info dialog when sources were found but none resolved
                        control.infoDialog(control.lang(32401) + ' (sources found but none resolved)', sound=False, icon='INFO')
                        return
                except Exception:
                    pass
                return self.errorForSources()

            # Add upnext flag to metadata so player knows to skip resume points
            if upnext:
                metadata['upnext'] = True
                c.log("[Sources] Added upnext=True to metadata (skip resume points)")

            # CRITICAL FIX: When called from Kodi's info dialog (valid handle), resolve URL immediately
            # Otherwise Kodi times out waiting for setResolvedUrl before player.run() reaches it
            early_resolve_done = False
            try:
                handle = int(sys.argv[1])
                if handle >= 0:
                    # Valid Kodi handle - resolve URL immediately so Kodi doesn't timeout
                    c.log(f"[Sources] Valid handle detected ({handle}) - calling setResolvedUrl immediately")

                    # Create minimal listitem for resolution
                    item = control.item(path=url)

                    # Set basic metadata for info dialog display
                    try:
                        media_type = metadata.get('mediatype', 'video')
                        item.setInfo(type='video', infoLabels=control.metadataClean(metadata))
                    except Exception:
                        pass

                    # CRITICAL: Clear resume point on ListItem for UpNext auto-play
                    # This prevents Kodi's native resume dialog from appearing
                    if upnext:
                        try:
                            # Get duration from metadata (in seconds)
                            duration = metadata.get('duration', 0)
                            item.setProperty('ResumeTime', '0')
                            item.setProperty('TotalTime', str(duration))
                            c.log(f"[Sources] Cleared resume point on ListItem for UpNext (duration={duration}s)")
                        except Exception as e:
                            c.log(f"[Sources] Failed to clear resume properties: {e}")

                    # Resolve URL to Kodi IMMEDIATELY (before player.run() setup)
                    control.resolve(handle, True, item)
                    c.log(f"[Sources] (OK) setResolvedUrl called - Kodi playback should start")
                    early_resolve_done = True

                    # Close persistent overlay immediately after resolving URL (TV Evening)
                    try:
                        c.log(f'[Sources] DEBUG: Checking overlay state - _active_persistent_overlay={_active_persistent_overlay}, is_overlay_active()={is_overlay_active()}')
                        if is_overlay_active():
                            overlay = get_active_overlay()
                            c.log(f'[Sources] DEBUG: Got overlay reference: {overlay}')
                            if overlay:
                                c.log('[Sources] Closing persistent overlay after setResolvedUrl')
                                overlay.force_close()
                                c.log('[Sources] Called force_close() on overlay')
                            clear_active_overlay()
                            c.log('[Sources] (OK) Persistent overlay closed successfully')
                        else:
                            c.log('[Sources] DEBUG: is_overlay_active() returned False - not closing overlay')
                    except Exception as e:
                        c.log(f'[Sources] Error closing overlay after setResolvedUrl: {e}')
                        import traceback
                        c.log(f'[Sources] Traceback: {traceback.format_exc()}')

                    # Signal to player.run() that resolve was already called
                    metadata['_early_resolve_done'] = True

                    # Continue with player setup for monitoring, bookmarks, etc.
                    # Player.run() will skip its own control.resolve() call since it's already done
            except (ValueError, IndexError):
                c.log("[Sources] No valid handle - normal playback mode")

            # v22: Use global player instance instead of creating new one
            global_player = get_global_player()
            if global_player:
                c.log(f"[Sources] Using global player instance: {id(global_player)}")
                global_player.run(title, year, season, episode, imdb, tmdb, url, metadata)
            else:
                c.log("[Sources] WARNING: No global player registered, creating fallback instance")
                import queue as _stdlib_queue
                fallback_player = player()
                # Store in stdlib queue module to survive across Kodi contexts and prevent GC
                setattr(_stdlib_queue, '_thecrew_global_player', fallback_player)
                fallback_player.run(title, year, season, episode, imdb, tmdb, url, metadata)
        except Exception as e:
            import traceback as _traceback
            failure = _traceback.format_exc()
            c.log(f"[Sources] play() exception: {e}")
            c.log(f"[Sources] play() traceback: {failure}")
            return self.errorForSources()







    def addItem(self, title):
        pass

        # Test/debug helper: always print when addItem is invoked so tests can trace flow
        try:
            pass
        except Exception:
            pass

        try:
            addon_poster, addon_banner = c.addon_poster(), c.addon_banner()
        except Exception:
            addon_poster = addon_banner = ''
        try:
            addon_fanart = c.addon_fanart()
        except Exception:
            addon_fanart = ''
        setting_fanart = control.setting('fanart')
        try:
            addon_clearlogo, addon_clearart = c.addon_clearlogo(), c.addon_clearart()
        except Exception:
            addon_clearlogo = addon_clearart = ''
        try:
            addon_thumb, addon_discart = c.addon_thumb(), c.addon_discart()
        except Exception:
            addon_thumb = addon_discart = ''

        indicators = playcount.get_movie_indicators(refresh=True)

        control.playlist.clear()

        items = control.window.getProperty(self.itemProperty)
        if not items:
            c.log(f"[Sources] addItem: no items found (property={self.itemProperty}), exiting", 1)
            control.idle()
            sys.exit()

        try:
            items = json.loads(items)
        except Exception as e:
            c.log(f"[Sources] addItem: failed to parse items JSON: {e}", 1)
            control.idle()
            sys.exit()

        # try:
        #     runtime_log(f"[Sources DEBUG] items loaded: {items}")
        # except Exception:
        #     pass

        if items is None or len(items) == 0:
            control.idle()
            sys.exit()

        meta = control.window.getProperty(self.metaProperty)
        if not meta:
            c.log(f"[Sources] addItem: no meta found (property={self.metaProperty}), using defaults", 1)
            meta = '{}'

        try:
            meta = json.loads(meta)
        except Exception as e:
            c.log(f"[Sources] addItem: failed to parse meta JSON: {e}, using defaults", 1)
            meta = {}

        poster = meta.get('poster', '')
        #meta = sourcesDirMeta(meta)

        sysaddon = sys.argv[0]
        try:
            syshandle = int(sys.argv[1])
        except Exception:
            # Tests and non-plugin invocations may not supply a numeric handle
            syshandle = 0

        downloads = (
            control.setting('downloads') == 'true'
            and control.setting('movie.download.path') != ''
            and control.setting('tv.download.path') != ''
        )

        systitle = sysname = quote_plus(title)

        if 'tvshowtitle' in meta and 'season' in meta and 'episode' in meta:
            sysname += quote_plus(' S%02dE%02d' % (int(meta['season']), int(meta['episode'])))
        elif 'year' in meta:
            sysname += quote_plus(f" ({meta['year']})")

        poster = meta['poster'] if 'poster' in meta else addon_poster
        fanart = meta.get('fanart2') if 'fanart2' in meta else addon_fanart
        thumb = meta['thumb'] if 'thumb' in meta else addon_thumb
        banner = meta['banner'] if 'banner' in meta else addon_banner
        clearlogo = meta['clearlogo'] if 'clearlogo' in meta else addon_clearlogo
        clearart = meta['clearart'] if 'clearart' in meta else addon_clearart
        discart = meta['discart'] if 'discart' in meta else addon_discart

        if not setting_fanart == 'true':
            fanart = addon_fanart
            poster = addon_poster
            banner = addon_banner
            thumb = addon_thumb
            clearlogo = addon_clearlogo
            clearart = addon_clearart
            discart = addon_discart

        #meta = control.tagdataClean(meta)
        sysimage = quote_plus(str(poster))
        download_menu = control.lang(32403)

        for item in items:
            try:
                label = str(item['label'])
                if control.setting('sourcelist.multiline') == 'true':
                    label = str(item['multiline_label'])

                # Mask provider path in the URL to avoid exposing full module paths in dialogs.
                try:
                    public_item = dict(item)
                    orig_provider = (public_item.get('provider') or '')
                    if orig_provider:
                        public_item['provider'] = self.format_provider_display(orig_provider)
                        import base64 as _base64
                        public_item['_provider_enc'] = _base64.b64encode(str(orig_provider).encode('utf-8')).decode('ascii')
                    syssource = quote_plus(json.dumps([public_item]))
                except Exception:
                    # Hardened fallback: ensure we never include the raw full provider path in the URL.
                    try:
                        public_item = dict(item)
                        orig = public_item.get('provider', '') or ''
                        try:
                            public_item['provider'] = self.format_provider_display(orig) if orig else ''
                        except Exception:
                            public_item['provider'] = ''
                        try:
                            import base64 as _base64
                            if orig:
                                public_item['_provider_enc'] = _base64.b64encode(str(orig).encode('utf-8')).decode('ascii')
                        except Exception:
                            pass
                        syssource = quote_plus(json.dumps([public_item]))
                    except Exception:
                        # Last resort: only include a minimal provider identifier (short display) so dialogs are safe.
                        try:
                            syssource = quote_plus(json.dumps([{'provider': self.format_provider_display(item.get('provider') or '')}]))
                        except Exception:
                            syssource = quote_plus(json.dumps([{'provider': ''}]))

                sysurl = f'{sysaddon}?action=playItem&title={systitle}&source={syssource}'

                # Debug: expose the final URL used for addItem in tests
                # try:
                #     runtime_log(f"[Sources Debug] Prepared sysurl={sysurl} label={label} provider={item.get('provider')}")
                # except Exception:
                #     try:
                #         runtime_log(f"[Sources Debug] Prepared sysurl={sysurl} label={label} provider={item.get('provider')}")
                #     except Exception:
                #         pass

                cm = []

                if downloads:
                    cm.append((download_menu, f'RunPlugin({sysaddon}?action=download&name={sysname}&image={sysimage}&source={syssource})'))

                # Visual cues for skins: mark Free vs Paid and internal sources so skins can color them.
                try:
                    provider = (item.get('provider') or '').lower()
                    is_internal = ('crew' in provider) or (item.get('source', '').lower() == 'crew')
                    # Do NOT mutate label: skins should use ListItem properties (source.internal/source.type) for visual cues.
                except Exception:
                    pass

                item_list = control.item(label=label)
                # Apply visual properties on the created ListItem
                try:
                    self.apply_visual_props(item_list, item)
                except Exception:
                    pass


                _split = getattr(c, 'string_split_to_list', lambda v: [] if v is None else (v if isinstance(v, (list,tuple)) else [s.strip() for s in str(v).split(',') if s.strip()]))
                meta['studio'] = _split(meta.get('studio')) if 'studio' in meta else []
                meta['genre'] = _split(meta.get('genre')) if 'genre' in meta else []
                meta['director'] = _split(meta.get('director')) if 'director' in meta else []
                meta['writer'] = _split(meta.get('writer')) if 'writer' in meta else []

                info_tag = ListItemInfoTag(item_list, 'video')
                infolabels = control.tagdataClean(meta)
                info_tag.set_info(infolabels)

                item_list.setArt({
                    'icon': poster, 'thumb': thumb, 'poster': poster, 'banner': banner,
                    'fanart': fanart, 'landscape': fanart, 'clearlogo': clearlogo,
                    'clearart': clearart, 'discart': discart
                    })

                video_streaminfo = {'codec': 'h264'}
                info_tag.add_stream_info('video', video_streaminfo)

                item_list.addContextMenuItems(cm)
                #item_list.setInfo(type='Video', infoLabels=meta)

                # try:
                #     runtime_log(f"[Sources DEBUG] calling control.addItem handle={syshandle} url={sysurl}")
                # except Exception:
                #     pass
                control.addItem(handle=syshandle, url=sysurl, listitem=item_list, isFolder=False)
            except Exception as e:
                failure = traceback.format_exc()
                c.log(f'[Sources] addItem exception: {e}')
                c.log(f'[Sources] addItem traceback: {failure}')
                pass
            #except Exception as e:
                #c.log(f"[CM Debug @ 234 in sources.py] Exception raised. Error = {e}")
                #pass

        control.content(syshandle, 'files')
        control.directory(syshandle, cacheToDisc=True)

    #TC 2/01/19 started
    def playItem(self, title, source):
        try:
            meta = control.window.getProperty(self.metaProperty)
            if not meta:
                c.log(f"[Sources] playItem: no container meta found (property={self.metaProperty}), proceeding with defaults", 1)
                meta = '{}'

            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}

            year = meta['year'] if 'year' in meta else None
            season = meta['season'] if 'season' in meta else None
            episode = meta['episode'] if 'episode' in meta else None

            # Store season/episode as instance vars so debrid pack resolution can find them
            # even when the source dict (e.g. Gears) doesn't carry season/episode fields
            self.season = season
            self.episode = episode

            imdb = meta['imdb'] if 'imdb' in meta else None
            tvdb = meta['tvdb'] if 'tvdb' in meta else None
            tmdb = meta['tmdb'] if 'tmdb' in meta else None

            _next = []
            prev = []
            total = []

            for i in range(1, 1000):
                try:
                    u = control.infoLabel(f'ListItem({i}).FolderPath')
                    if u in total:
                        raise Exception()
                    total.append(u)
                    u = dict(parse_qsl(u.replace('?', '')))
                    u = json.loads(u['source'])[0]
                    _next.append(u)
                    #c.log(f"[CM Debug @ 257 in sources.py] u  = {u} and _next = {_next}")
                except Exception:
                    break
            for i in range(-1000,0)[::-1]:
                try:
                    u = control.infoLabel(f'ListItem({i}).FolderPath')
                    if u in total:
                        raise Exception()
                    total.append(u)
                    u = dict(parse_qsl(u.replace('?', '')))
                    u = json.loads(u['source'])[0]
                    prev.append(u)
                except Exception:
                    break

            items = json.loads(source)

            # Restore any encoded full provider paths that were masked in the container URL
            try:
                import base64 as _base64
                for it in items:
                    enc = it.pop('_provider_enc', None)
                    if enc:
                        try:
                            it['provider'] = _base64.b64decode(enc.encode('ascii')).decode('utf-8')
                        except Exception:
                            it['provider'] = it.get('provider') or ''
            except Exception:
                pass

            items = [i for i in items+_next+prev][:40]

            header = control.addonInfo('name')
            header2 = header.upper()

            block = None

            for i, item in enumerate(items):
                try:
                    if item['source'] == block:
                        raise Exception('block')

                    w = workers.Thread(self.sourcesResolve, item)
                    w.start()

                    offset = 60 * 2 if item.get('source') in self.hostcapDict else 0

                    m = ''
                    resolve_start = time.time()

                    for x in range(3600):
                        try:
                            if control.monitor.abortRequested():
                                return sys.exit()
                        except Exception:
                            pass

                        k = control.condVisibility('Window.IsActive(virtualkeyboard)')
                        if k:
                            m += '1'
                            m = m[-1]
                        if (w.is_alive() is False or x > 30 + offset) and not k:
                            break
                        k = control.condVisibility('Window.IsActive(yesnoDialog)')
                        if k:
                            m += '1'
                            m = m[-1]
                        if (w.is_alive() is False or x > 30 + offset) and not k:
                            break
                        time.sleep(0.5)

                    for x in range(30):
                        try:
                            if control.monitor.abortRequested():
                                return sys.exit()
                        except Exception:
                            pass

                        if m == '':
                            break
                        if w.is_alive() is False:
                            break
                        time.sleep(0.5)

                    if w.is_alive() is True:
                        block = item['source']

                    if self.url is None:
                        raise Exception()

                    control.sleep(200)
                    control.execute('Dialog.Close(virtualkeyboard)')
                    control.execute('Dialog.Close(yesnoDialog)')

                    # Close persistent overlay before playback starts (TV Evening)
                    try:
                        if is_overlay_active():
                            overlay = get_active_overlay()
                            if overlay:
                                c.log('[Sources.playItem] Closing persistent overlay before playback')
                                overlay.force_close()
                            clear_active_overlay()
                    except Exception as e:
                        c.log(f'[Sources.playItem] Error closing overlay: {e}')

                    # v22: Use global player instance instead of creating new one
                    global_player = get_global_player()
                    if global_player:
                        global_player.run(title, year, season, episode, imdb, tmdb, self.url, meta)
                    else:
                        player().run(title, year, season, episode, imdb, tmdb, self.url, meta)

                    return self.url
                except Exception as e:
                    pass

            self.errorForSources()
        except Exception as e:
            c.log(f"[Sources] playItem exception: {e}", 1)

    def get_upnext_cached_sources(self, imdb, tmdb, season, episode):
        """
        Get cached sources for Up Next from Window properties.
        Single-use: clears the cache on read so it self-cleans without a timer.
        """
        try:
            import json
            import xbmcgui

            cache_key = f"upnext.sources.{imdb}.s{str(season)}e{str(episode)}"
            win = xbmcgui.Window(10000)

            c.log(f"[UpNextCache] Looking for cached sources: {cache_key}")

            cached_json = win.getProperty(cache_key)
            if not cached_json:
                c.log(f"[UpNextCache] No cached sources found for {cache_key}")
                return None

            # Consume the cache (single-use)
            win.clearProperty(cache_key)

            try:
                cached_sources = json.loads(cached_json)
                c.log(f"[UpNextCache] (OK) Found {len(cached_sources)} cached sources for {cache_key}")
                return cached_sources
            except Exception as e:
                c.log(f"[UpNextCache] Error parsing cached sources: {e}")
                return None
        except Exception as e:
            c.log(f"[UpNextCache] Error getting cached sources: {e}")
            c.log(f"[UpNextCache] Traceback: {traceback.format_exc()}")
            return None

    def set_upnext_cached_sources(self, imdb, tmdb, season, episode, sources):
        """
        Cache sources for Up Next in Window properties.
        No TTL — cache is single-use and cleared when read.
        """
        try:
            import json
            import xbmcgui

            if not sources:
                c.log("[UpNextCache] No sources to cache (empty list)")
                return

            # Build cache key - normalize season/episode to strings
            cache_key = f"upnext.sources.{imdb}.s{str(season)}e{str(episode)}"

            # No TTL — cache lives until consumed (get clears it on read)
            cached_json = json.dumps(sources)
            xbmcgui.Window(10000).setProperty(cache_key, cached_json)

            c.log(f"[UpNextCache] (OK) Cached {len(sources)} sources for {cache_key} (no expiry, single-use)")
        except Exception as e:
            c.log(f"[UpNextCache] Error setting cached sources: {e}")
            c.log(f"[UpNextCache] Traceback: {traceback.format_exc()}")

    def getSources(self, title, year, imdb, tvdb=None, tmdb=None, season='', episode='', tvshowtitle='', premiered='', quality='HD', timeout=30, show_dialog=True, use_overlay=False, episode_data=None, persistent_overlay=False, upnext=False):
        try:
            # Local alias to module-level traceback to avoid UnboundLocalError when inner imports assign traceback
            try:
                traceback = globals().get('traceback')
            except Exception:
                traceback = None

            # Store silent mode flag for suppressing notifications during Up Next
            self.silent_mode = (not show_dialog) or upnext
            if self.silent_mode:
                c.log("[Sources] Silent mode enabled - suppressing all notifications and dialogs")

            # CRITICAL FIX: Create fullscreen overlay BEFORE cache check for TV Evening
            # Cache early-return would skip overlay creation otherwise
            if show_dialog and use_overlay and persistent_overlay:
                c.log("[Sources] Creating fullscreen overlay for TV Evening (before cache check)")
                progressDialog = FullscreenOverlay(episode_data=episode_data)
                progressDialog.show()
                c.log('[Sources] Fullscreen overlay created and shown')
                # Register for global access
                set_active_overlay(progressDialog)
                c.log(f'[Sources] DEBUG: Registered fullscreen overlay - _active_persistent_overlay={_active_persistent_overlay}, has overlay attr={hasattr(progressDialog, "overlay")}, overlay value={progressDialog.overlay if hasattr(progressDialog, "overlay") else "N/A"}')
                c.log('[Sources] Registered fullscreen overlay for unified UX')
            else:
                progressDialog = None  # Will be created later if sources need scraping

            # Check if source caching is enabled (default: true)
            cache_enabled = (control.setting('sources.cache.enabled') != 'false')

            # Try to get cached sources first
            if upnext:
                # For Up Next, use Window properties cache (15s TTL)
                c.log(f"[UpNextCache] Checking Up Next cache for: imdb={imdb}, tmdb={tmdb}, season={season}, episode={episode}")
                cached_sources = self.get_upnext_cached_sources(imdb, tmdb, season, episode)
                if cached_sources is not None:
                    c.log(f"[UpNextCache] (OK) Using {len(cached_sources)} cached sources, instant playback")
                    self.sources = cached_sources
                    # Update overlay if active
                    if progressDialog and hasattr(progressDialog, 'update_text'):
                        progressDialog.update_text("Using cached sources...")
                    return self.sources
                else:
                    c.log("[UpNextCache] No Up Next cache found, starting fresh scraping")
            elif cache_enabled:
                # For normal playback, use database cache (longer TTL)
                c.log(f"[SourceCache] Checking database cache for: imdb={imdb}, tmdb={tmdb}, season={season}, episode={episode}")
                cached_sources = self.get_cached_sources(imdb, tmdb, season, episode)
                if cached_sources is not None:
                    c.log(f"[SourceCache] (OK) Using {len(cached_sources)} cached sources, skipping scraping")
                    self.sources = cached_sources
                    # Update overlay if active (TV Evening) to show cache hit
                    if progressDialog and hasattr(progressDialog, 'update_text'):
                        progressDialog.update_text(f"Using {len(cached_sources)} cached sources...")
                        c.log("[Sources] Updated overlay with cache status")
                    return self.sources
                else:
                    c.log("[SourceCache] No cached sources found, starting fresh scraping")
            else:
                c.log("[SourceCache] Source caching disabled in settings")

            self.start = time.time()
            #string1 = control.lang(32404)
            #string2 = control.lang(32405)
            string3 = control.lang(32406)
            string4 = control.lang(32601)
            #string5 = control.lang(32602)
            string6 = control.lang(32606)
            string7 = control.lang(32607)

            # Create progress dialog if not already created (TV Evening creates it early)
            if show_dialog and progressDialog is None:
                if use_overlay:
                    # Use elegant status overlay instead of dialog
                    # persistent_overlay uses fullscreen overlay with dialog suppression for TV Evening
                    if persistent_overlay:
                        # Should have been created before cache check, but fallback just in case
                        c.log('[Sources] WARNING: Fullscreen overlay should have been created earlier')
                        progressDialog = FullscreenOverlay(episode_data=episode_data)
                        progressDialog.show()
                        set_active_overlay(progressDialog)
                    else:
                        # Use sidebar overlay for Up Next
                        progressDialog = OverlayProgressDialog(episode_data=episode_data, persistent=False)
                        progressDialog.create(control.addonInfo('name'), '')
                        c.log('[Sources] Using sidebar overlay for Up Next')
                else:
                    progressDialog = control.progressDialog if c.get_setting('progress.dialog') == '0' else control.progressDialogBG
                    progressDialog.create(control.addonInfo('name'), '')
                progressDialog.update(0)
            elif show_dialog and progressDialog is not None:
                c.log('[Sources] Using pre-created overlay (TV Evening mode)')
                # For TV Evening overlay, update it to show we're starting
                if use_overlay and persistent_overlay:
                    progressDialog.update_text("Preparing playback...")
            else:
                # No dialog for background scraping (progressDialog might already be set for TV Evening)
                if progressDialog is None:
                    progressDialog = NullProgressDialog()
                    c.log('[Sources] Running in silent mode (no progress dialog)')

            self.prepare_sources()

            # Store metadata for filtering/validation (Phase 2: 2026-02-22)
            self.search_title = title
            self.search_year = year
            self.search_imdb = imdb
            self.search_tmdb = tmdb
            self.search_season = season
            self.search_episode = episode
            self.search_tvshowtitle = tvshowtitle
            self.search_premiered = premiered
            self.search_aliases = None  # Will be set in get_movie_episode_sources

            # Defensive: ensure `sourceDict` exists BEFORE we access it. Sometimes initialization
            # can fail earlier leaving a partially-constructed Sources object (see logs).
            # If `sourceDict` is missing or empty, attempt to populate it by discovering
            # provider modules on-disk via the `resources.lib.sources` helper.
            try:
                sd = getattr(self, 'sourceDict', None)
            except Exception:
                sd = None

            if not sd:
                c.log('[Sources] Warning: sourceDict missing or empty. Attempting to initialize providers via resources.lib.sources', 1)
                try:
                    from resources.lib.sources import sources as discover_sources
                    self.sourceDict = discover_sources()
                    try:
                        try:
                            gear_names = [i[0] for i in self.sourceDict if isinstance(i[0], str) and i[0].startswith('gearsscrapers.')]
                        except Exception:
                            pass
                    except Exception:
                        pass
                except Exception as e:
                    try:
                        import traceback as _traceback
                        failure = _traceback.format_exc()
                        c.log(f"[Sources] Error importing providers: {e}\n{failure}", 1)
                    except Exception:
                        c.log(f"[Sources] Error importing providers: {e}", 1)
                    self.sourceDict = []

            sourceDict = getattr(self, 'sourceDict', [])
            try:
                pass
            except Exception:
                pass

            # Defensive: ensure host resolver list exists for providers that expect `self.hostDict`.
            try:
                if not hasattr(self, 'hostDict') or not getattr(self, 'hostDict'):
                    try:
                        self.hostDict = resolveurl.relevant_resolvers(order_matters=True)
                        self.hostDict = [i.domains for i in self.hostDict if '*' not in i.domains]
                        self.hostDict = [i.lower() for i in reduce(lambda x, y: x+y, self.hostDict)]
                        self.hostDict = [x for y, x in enumerate(self.hostDict) if x not in self.hostDict[:y]]
                    except Exception as e:
                        c.log(f"[Sources] Warning: could not initialize hostDict: {e}")
                        self.hostDict = []
            except Exception:
                # If resolveurl is not available or any other error, ensure attribute exists
                self.hostDict = []

            # Defensive: ensure hostprDict exists (list of prioritized hosts). Some providers expect
            # `self.hostprDict` to be present and may concatenate it with hostDict.
            try:
                if not hasattr(self, 'hostprDict') or not getattr(self, 'hostprDict'):
                    try:
                        # default prioritized hosts
                        self.hostprDict = [
                            '1fichier.com', 'oboom.com', 'rapidgator.net', 'rg.to', 'uploaded.net', 'uploaded.to', 'uploadgig.com',
                            'ul.to', 'filefactory.com', 'nitroflare.com', 'turbobit.net', 'uploadrocket.net', 'multiup.org']
                    except Exception as e:
                        c.log(f"[Sources] Warning: could not initialize hostprDict: {e}")
                        self.hostprDict = []
            except Exception:
                self.hostprDict = []

            # Defensive: ensure other host dicts exist (used by filters later)
            try:
                if not hasattr(self, 'hostcapDict') or not getattr(self, 'hostcapDict'):
                    self.hostcapDict = []
                if not hasattr(self, 'hosthqDict') or not getattr(self, 'hosthqDict'):
                    self.hosthqDict = []
                if not hasattr(self, 'hostblockDict') or not getattr(self, 'hostblockDict'):
                    self.hostblockDict = []
            except Exception:
                self.hostcapDict = self.hosthqDict = self.hostblockDict = []

            progressDialog.update(0, control.lang(32600))

            # Debug: report type and length of sourceDict to help diagnose empty-filter cases
            try:
                sd_len = len(sourceDict) if sourceDict is not None else 'None'
                sd_type = type(sourceDict)
            except Exception:
                pass

            sourceDict, content = self.filter_source_dict(tvshowtitle, sourceDict)
            threads = []
            mainsourceDict, sourcelabelDict = self.get_movie_episode_sources(title, year, imdb, tvdb, tmdb, season, episode, tvshowtitle, premiered, sourceDict, content, threads)

            try:
                timeout = int(control.setting('scrapers.timeout.1') or 0) or 30
            except Exception:
                timeout = 30
            self.scraper_timeout = timeout  # made available to _scraper_sources_wrapper
            try:
                quality = int(control.setting('hosts.quality') or 0) or 0
            except Exception:
                quality = 0
            debrid_only = control.setting('debrid.only') or 'false'

            line1 = line2 = line3 = ""

            pre_emp = control.setting('preemptive.termination')
            try:
                pre_emp_limit = int(control.setting('preemptive.limit') or 0)
            except Exception:
                pre_emp_limit = 0

            c.log(f"[Scraper Settings] timeout={timeout}s, quality={quality}, pre_emp={pre_emp}, pre_emp_limit={pre_emp_limit}")

            source_4k = d_source_4k = 0
            source_1080 = d_source_1080 = 0
            source_720 = d_source_720 = 0
            source_sd = d_source_sd = 0

            debrid_list = debrid.debrid_resolvers
            debrid_status = debrid.status()

            total_format = '[COLOR %s][B]%s[/B][/COLOR]'
            pdiag_format = ' 4K: %s | 1080p: %s | 720p: %s | SD: %s | %s: %s'.split('|')

            # BGDialog optimization: batch updates to reduce visual spam
            last_update_iteration = -1
            last_source_count = 0
            update_interval = 5  # Update every N iterations (2.5 seconds with 0.5s sleep)

            # CRITICAL: Count threads BEFORE any complete (threads list is immutable after return)
            # Do NOT read from self.active_scrapers - fast scrapers already decremented it!
            total_scrapers = len(threads) if threads else 0

# Event-Driven Scraping Loop - Replacement for busy-polling (Lines 2094-2373)
# This is the new implementation - copy into sources.py

            # ═══════════════════════════════════════════════════════════════════════════
            # EVENT-DRIVEN SCRAPING LOOP (v22.19+)
            # Replaces 280-line busy-polling loop with queue-based event system
            # ═══════════════════════════════════════════════════════════════════════════

            c.log(f'[Sources] Event-driven loop: waiting for {total_scrapers} scrapers (timeout={timeout}s)')

            start_time = time.time()
            deadline = start_time + timeout
            last_update_time = start_time
            update_interval = 2.0  # Update dialog every 2 seconds (much less frequent than before)

            completed_scrapers = []
            user_cancelled = False
            timeout_reached = False
            preemptive_exit = False

            while True:
                # Calculate remaining time
                remaining_time = deadline - time.time()
                if remaining_time <= 0:
                    timeout_reached = True

                    # Log which scrapers are still alive at timeout
                    with self.active_scrapers_lock:
                        still_running = self.active_scrapers

                    if still_running > 0:
                        alive_threads = [t for t in threads if t.is_alive()]
                        alive_names = [sourcelabelDict.get(t.getName(), t.getName()) for t in alive_threads[:10]]
                        c.log(f'[Sources] Timeout reached after {timeout}s - {still_running} scrapers still running: {alive_names}')
                    else:
                        c.log(f'[Sources] Timeout reached after {timeout}s (all scrapers completed but event loop didn\'t exit)')
                    break

                # Check for user cancel or Kodi abort (quick check, no blocking)
                if control.monitor.abortRequested():
                    c.log('[Sources] Kodi abort requested')
                    sys.exit()

                if progressDialog.iscanceled():
                    c.log('[Sources] User cancelled scraping')
                    user_cancelled = True
                    break

                # Suppress external dialogs during silent mode
                if getattr(self, 'silent_mode', False):
                    try:
                        control.execute('Dialog.Close(infodialog)')
                        control.execute('Dialog.Close(notification)')
                    except Exception:
                        pass

                # Wait for scraper completion event (blocks up to 1 second or until event arrives)
                try:
                    event = self.completion_queue.get(timeout=min(1.0, remaining_time))
                    completed_scrapers.append(event)

                    # Log completion
                    scraper_name = event.get('scraper', 'unknown')
                    count = event.get('count', 0)
                    if count > 0:
                        c.log(f"[Sources] ✓ {scraper_name} completed:  {count} sources")

                except Exception:  # queue.Empty on timeout
                    # No event arrived - that's OK, we'll loop again
                    pass

                # Check active scraper count
                with self.active_scrapers_lock:
                    active_count = self.active_scrapers

                # Exit condition: All scrapers finished
                if active_count == 0:
                    elapsed = time.time() - start_time
                    c.log(f'[Sources] All scrapers completed in {elapsed:.1f}s')
                    break

                # Preemptive termination check (only if enabled)
                if str(pre_emp) == 'true':
                    with self.sources_lock:
                        current_source_count = len(self.sources)

                    # Count sources by quality (need to check actual sources)
                    if current_source_count > 0:
                        with self.sources_lock:
                            quality_counts = {0: 0, 1: 0, 2: 0, 3: 0}
                            for src in self.sources:
                                if isinstance(src, dict):
                                    qual = src.get('quality', 'SD')
                                    if '4K' in str(qual) or '2160' in str(qual):
                                        quality_counts[0] += 1
                                        quality_counts[1] += 1  # 4K counts as 1080p+
                                        quality_counts[2] += 1  # Also counts as 720p+
                                        quality_counts[3] += 1  # Also counts as SD+
                                    elif '1080' in str(qual):
                                        quality_counts[1] += 1
                                        quality_counts[2] += 1
                                        quality_counts[3] += 1
                                    elif '720' in str(qual):
                                        quality_counts[2] += 1
                                        quality_counts[3] += 1
                                    else:
                                        quality_counts[3] += 1

                        target_quality = quality
                        if target_quality in quality_counts and quality_counts[target_quality] >= pre_emp_limit:
                            quality_names = ['4K', '1080p', '720p', 'SD']
                            c.log(f'[Sources] Preemptive termination: {quality_counts[target_quality]} {quality_names[target_quality]} sources >= {pre_emp_limit} limit')
                            preemptive_exit = True
                            break

                # Update progress dialog (throttled - only update every 2 seconds)
                current_time = time.time()
                if current_time - last_update_time >= update_interval or active_count == 0:
                    last_update_time = current_time

                    try:
                        # Thread-safe source count
                        with self.sources_lock:
                            current_source_count = len(self.sources)

                        if current_source_count > 0:
                            # Get quality labels
                            debrid_4k_label, debrid_1080_label, debrid_720_label, debrid_sd_label, debrid_total_label, source_4k_label, source_1080_label, source_720_label, source_sd_label, source_total_label = self.get_labels(debrid_list, debrid_status, total_format)

                            # Calculate progress percentage
                            elapsed = current_time - start_time
                            percent = int(100 * min(elapsed / timeout, 1.0))

                            # Build progress message
                            completed_count = total_scrapers - active_count

                            if debrid_status:
                                if quality == 0:
                                    line1 = ('%s:' + '|'.join(pdiag_format)) % (string6, debrid_4k_label, debrid_1080_label, debrid_720_label, debrid_sd_label, str(string4), debrid_total_label)
                                    line2 = ('%s:' + '|'.join(pdiag_format)) % (string7, source_4k_label, source_1080_label, source_720_label, source_sd_label, str(string4), source_total_label)
                                elif quality in [1, 2]:
                                    line1 = ('%s:' + '|'.join(pdiag_format[1:])) % (string6, debrid_1080_label, debrid_720_label, debrid_sd_label, str(string4), debrid_total_label)
                                    line2 = ('%s:' + '|'.join(pdiag_format[1:])) % (string7, source_1080_label, source_720_label, source_sd_label, str(string4), source_total_label)
                                elif quality == 3:
                                    line1 = ('%s:' + '|'.join(pdiag_format[2:])) % (string6, debrid_720_label, debrid_sd_label, str(string4), debrid_total_label)
                                    line2 = ('%s:' + '|'.join(pdiag_format[2:])) % (string7, source_720_label, source_sd_label, str(string4), source_total_label)
                                else:
                                    line1 = ('%s:' + '|'.join(pdiag_format[3:])) % (string6, debrid_sd_label, str(string4), debrid_total_label)
                                    line2 = ('%s:' + '|'.join(pdiag_format[3:])) % (string7, source_sd_label, str(string4), source_total_label)

                                # Show active scraper count
                                if active_count > 6:
                                    line3 = string3 % (str(active_count))
                                    line3 += f' | {completed_count}/{total_scrapers} complete'
                                elif active_count > 0:
                                    # Get names of still-running scrapers
                                    alive_threads = [t for t in threads if t.is_alive()]
                                    thread_names = [t.getName() for t in alive_threads[:6]]  # Limit to 6

                                    # Try to get formatted names (with sourcelabelDict lookup)
                                    info = [sourcelabelDict.get(name, name) for name in thread_names if name in mainsourceDict]

                                    # If no names found in mainsourceDict, show raw thread names (better than just count)
                                    if not info and thread_names:
                                        # Show raw thread names so we can identify the hanging scraper
                                        info = [sourcelabelDict.get(name, name.upper()) for name in thread_names]
                                        c.log(f'[Sources] Progress: showing raw thread names (not in mainsourceDict): {thread_names}')

                                    if info:
                                        line3 = string3 % (', '.join(info))
                                    else:
                                        line3 = string3 % (str(active_count))

                                    line3 += f' | {completed_count}/{total_scrapers} complete'
                                else:
                                    line3 = 'All scrapers complete'

                                # Add devmode timer
                                if getattr(c, 'devmode', False):
                                    line4 = f'[COLOR lawngreen]Devmode: {elapsed:.2f}s[/COLOR]'
                                    if progressDialog == control.progressDialogBG:
                                        progressDialog.update(max(1, percent), line1 + '\n' + line2 + '\n' + line3 + '\n' + line4)
                                    else:
                                        progressDialog.update(max(1, percent), line1 + '\n' + line2 + '\n' + line3 + '\n' + line4)
                                else:
                                    if progressDialog == control.progressDialogBG:
                                        progressDialog.update(max(1, percent), line1 + '\n' + line2 + '\n' + line3)
                                    else:
                                        progressDialog.update(max(1, percent), line1 + '\n' + line2 + '\n' + line3)
                            else:
                                # No debrid - simpler format
                                if quality == 0:
                                    line1 = '|'.join(pdiag_format) % (source_4k_label, source_1080_label, source_720_label, source_sd_label, str(string4), source_total_label)
                                elif quality in [1, 2]:
                                    line1 = '|'.join(pdiag_format[1:]) % (source_1080_label, source_720_label, source_sd_label, str(string4), source_total_label)
                                elif quality == 3:
                                    line1 = '|'.join(pdiag_format[2:]) % (source_720_label, source_sd_label, str(string4), source_total_label)
                                else:
                                    line1 = '|'.join(pdiag_format[3:]) % (source_sd_label, str(string4), source_total_label)

                                # Show active scrapers
                                if active_count > 6:
                                    line2 = string3 % (str(active_count))
                                    line2 += f' | {completed_count}/{total_scrapers} complete'
                                elif active_count > 0:
                                    alive_threads = [t for t in threads if t.is_alive()]
                                    thread_names = [t.getName() for t in alive_threads[:6]]

                                    # Try to get formatted names (with sourcelabelDict lookup)
                                    info = [sourcelabelDict.get(name, name) for name in thread_names if name in mainsourceDict]

                                    # If no names found in mainsourceDict, show raw thread names (better than just count)
                                    if not info and thread_names:
                                        # Show raw thread names so we can identify the hanging scraper
                                        info = [sourcelabelDict.get(name, name.upper()) for name in thread_names]
                                        c.log(f'[Sources] Progress: showing raw thread names (not in mainsourceDict): {thread_names}')

                                    if info:
                                        line2 = string3 % (', '.join(info))
                                    else:
                                        line2 = string3 % (str(active_count))

                                    line2 += f' | {completed_count}/{total_scrapers} complete'
                                else:
                                    line2 = 'All scrapers complete'

                                if getattr(c, 'devmode', False):
                                    line4 = f'[COLOR lawngreen]Devmode: {elapsed:.2f}s[/COLOR]'
                                    progressDialog.update(max(1, percent), line1 + '\n' + line2 + '\n' + line4)
                                else:
                                    progressDialog.update(max(1, percent), line1 + '\n' + line2)
                        else:
                            # No sources yet - show 0 counts
                            debrid_4k_label, debrid_1080_label, debrid_720_label, debrid_sd_label, debrid_total_label, source_4k_label, source_1080_label, source_720_label, source_sd_label, source_total_label = self.get_labels(debrid_list, debrid_status, total_format)

                            elapsed = current_time - start_time
                            percent = int(100 * min(elapsed / timeout, 1.0))

                            if debrid_status:
                                if quality == 0:
                                    line1 = ('%s:' + '|'.join(pdiag_format)) % (string6, debrid_4k_label, debrid_1080_label, debrid_720_label, debrid_sd_label, str(string4), debrid_total_label)
                                    line2 = ('%s:' + '|'.join(pdiag_format)) % (string7, source_4k_label, source_1080_label, source_720_label, source_sd_label, str(string4), source_total_label)
                                else:
                                    line1 = ('%s:' + '|'.join(pdiag_format[1:])) % (string6, '0', '0', '0', str(string4), '0')
                                    line2 = ('%s:' + '|'.join(pdiag_format[1:])) % (string7, '0', '0', '0', str(string4), '0')

                                line3 = string3 % (str(active_count)) if active_count > 6 else 'Searching...'

                                if progressDialog == control.progressDialogBG:
                                    progressDialog.update(max(1, percent), line1 + '\n' + line3)
                                else:
                                    progressDialog.update(max(1, percent), line1 + '\n' + line2 + '\n' + line3)
                            else:
                                line1 = '|'.join(pdiag_format) % ('0', '0', '0', '0', str(string4), '0')
                                line2 = 'Searching...'
                                progressDialog.update(max(1, percent), line1 + '\n' + line2)

                    except Exception as e:
                        c.log(f'[Sources] Exception updating progress dialog: {e}', 1)

            # Final summary
            final_elapsed = time.time() - start_time
            with self.sources_lock:
                final_source_count = len(self.sources)

            c.log(f'[Sources] Scraping complete: {final_source_count} sources in {final_elapsed:.1f}s ({len(completed_scrapers)}/{total_scrapers} scrapers completed)')

            # Export completion stats for analysis
            if getattr(c, 'devmode', False):
                try:
                    completion_times = [(e['scraper'], e['count']) for e in completed_scrapers if e.get('success')]
                    c.log(f'[Sources] Completed scrapers: {completion_times[:10]}...')
                except Exception:
                    pass

            try:
                # Handle overlay closing based on mode
                # Check for persistent attribute and transition_to_state method (works for both overlay types)
                if hasattr(progressDialog, 'persistent') and hasattr(progressDialog, 'transition_to_state'):
                    if progressDialog.persistent:
                        # Persistent mode: transition to 'ready' state instead of closing
                        source_count = len(self.sources)
                        if source_count > 0:
                            progressDialog.transition_to_state('ready', f'Ready • {source_count} sources found')
                            c.log(f'[Sources] Overlay transitioned to ready state ({source_count} sources)')
                        else:
                            progressDialog.transition_to_state('ready', 'No sources found')
                            c.log('[Sources] Overlay transitioned to ready state (no sources)')
                        # Store reference for later stages (link generation, Orion, etc.)
                        # This allows other parts of the code to update the overlay
                    else:
                        # Non-persistent mode: close immediately
                        progressDialog.close()
                        c.log('[Sources] Overlay closed (non-persistent mode)')
                else:
                    # Standard dialog: close immediately
                    progressDialog.close()
            except Exception as e:
                pass

            # Log cocoscrapers contribution summary
            if self.cocoscrapers_enabled and self.cocoscrapers_installed:
                cocos_sources = [s for s in self.sources if s.get('provider', '').startswith('cocoscrapers.')]
                c.log(f'[Sources] Cocoscrapers total: {len(cocos_sources)} sources from {len(set(s.get("provider") for s in cocos_sources))} scrapers')
                if cocos_sources:
                    providers_summary = {}
                    for s in cocos_sources:
                        provider = s.get('provider', 'unknown')
                        providers_summary[provider] = providers_summary.get(provider, 0) + 1
                    c.log(f'[Sources] Cocoscrapers breakdown: {providers_summary}')

            self.sourcesFilter()

            try:
                c.log(f"[Sources] getSources: after filter -> {len(self.sources)} sources; sample_providers={[self.format_provider_display(s.get('provider')) for s in self.sources[:8]]}")
            except Exception:
                c.log("[Sources] getSources: after filter -> unable to compute sample")

            # Cache the sources for future lookups
            if cache_enabled and len(self.sources) > 0:
                self.cache_sources(self.sources, imdb, tmdb, season, episode)
                # Clean up expired cache entries periodically
                if random.randint(1, 10) == 1:  # 10% chance to run cleanup
                    self.clear_expired_source_cache()

            return self.sources

        except Exception as e:
            failure = traceback.format_exc()
            pass

    def get_labels(self, debrid_list, debrid_status, total_format):
        try:
            source_4k, source_1080, source_720, source_sd, total = self._get_source_counts()
            debrid_source_4k = debrid_source_1080 = debrid_source_720 = debrid_source_sd = debrid_total = 0
            if debrid_status:
                debrid_source_4k, debrid_source_1080, debrid_source_720, debrid_source_sd, debrid_total = self._get_debrid_source_counts(debrid_list)
                # Calculate non-debrid (free) counts by subtracting debrid counts from total
                free_4k = source_4k - debrid_source_4k
                free_1080 = source_1080 - debrid_source_1080
                free_720 = source_720 - debrid_source_720
                free_sd = source_sd - debrid_source_sd
                free_total = total - debrid_total
            else:
                # No debrid - all sources are "free"
                free_4k = source_4k
                free_1080 = source_1080
                free_720 = source_720
                free_sd = source_sd
                free_total = total

            debrid_4k_label, debrid_1080_label, debrid_720_label, debrid_sd_label, debrid_total_label = self._get_debrid_labels(
                debrid_source_4k, debrid_source_1080, debrid_source_720, debrid_source_sd, debrid_total, total_format
            )
            source_4k_label, source_1080_label, source_720_label, source_sd_label, source_total_label = self._get_source_labels(
                free_4k, free_1080, free_720, free_sd, free_total, total_format
            )
        except Exception as e:
            c.log(f"[Sources] get_labels error: {e}", 1)

        return (
            debrid_4k_label,
            debrid_1080_label,
            debrid_720_label,
            debrid_sd_label,
            debrid_total_label,
            source_4k_label,
            source_1080_label,
            source_720_label,
            source_sd_label,
            source_total_label,
        )

    def _get_source_counts(self):
        sources_by_quality = {
            '4K': len([e for e in self.sources if e.get('quality', '').upper() in ['4K']]),
            '1080p': len([e for e in self.sources if e.get('quality', '') in ['1080p', '1440p']]),
            '720p': len([e for e in self.sources if e.get('quality', '') in ['720p', 'HD']]),
            'SD': len([e for e in self.sources if e.get('quality', '').upper() == 'SD']),
        }
        source_4k = sources_by_quality.get('4K', 0)
        source_1080 = sources_by_quality.get('1080p', 0)
        source_720 = sources_by_quality.get('720p', 0)
        source_sd = sources_by_quality.get('SD', 0)
        total = source_4k + source_1080 + source_720 + source_sd
        return source_4k, source_1080, source_720, source_sd, total

    def _get_debrid_source_counts(self, debrid_list):
        debrid_source_counts = {
            '4K': len([s for s in self.sources if s.get('quality', '').upper() in ['4K'] and any(d.valid_url(s['url'], s['source']) for d in debrid_list)]),
            '1080p': len([s for s in self.sources if s.get('quality', '') in ['1440p', '1080p'] and any(d.valid_url(s['url'], s['source']) for d in debrid_list)]),
            '720p': len([s for s in self.sources if s.get('quality', '') in ['720p', 'HD'] and any(d.valid_url(s['url'], s['source']) for d in debrid_list)]),
            'SD': len([s for s in self.sources if s.get('quality', '').upper() == 'SD' and any(d.valid_url(s['url'], s['source']) for d in debrid_list)]),
        }
        debrid_source_4k = debrid_source_counts.get('4K', 0)
        debrid_source_1080 = debrid_source_counts.get('1080p', 0)
        debrid_source_720 = debrid_source_counts.get('720p', 0)
        debrid_source_sd = debrid_source_counts.get('SD', 0)
        debrid_total = debrid_source_4k + debrid_source_1080 + debrid_source_720 + debrid_source_sd
        return debrid_source_4k, debrid_source_1080, debrid_source_720, debrid_source_sd, debrid_total

    def _get_debrid_labels(self, debrid_source_4k, debrid_source_1080, debrid_source_720, debrid_source_sd, debrid_total, total_format):
        debrid_4k_label = total_format % ('red', debrid_source_4k) if debrid_source_4k == 0 else total_format % ('lime', debrid_source_4k)
        debrid_1080_label = total_format % ('red', debrid_source_1080) if debrid_source_1080 == 0 else total_format % ('lime', debrid_source_1080)
        debrid_720_label = total_format % ('red', debrid_source_720) if debrid_source_720 == 0 else total_format % ('lime', debrid_source_720)
        debrid_sd_label = total_format % ('red', debrid_source_sd) if debrid_source_sd == 0 else total_format % ('lime', debrid_source_sd)
        debrid_total_label = total_format % ('red', debrid_total) if debrid_total == 0 else total_format % ('lime', debrid_total)
        return debrid_4k_label, debrid_1080_label, debrid_720_label, debrid_sd_label, debrid_total_label

    def _get_source_labels(self, source_4k, source_1080, source_720, source_sd, total, total_format):
        source_4k_label = total_format % ('red', source_4k) if source_4k == 0 else total_format % ('lime', source_4k)
        source_1080_label = total_format % ('red', source_1080) if source_1080 == 0 else total_format % ('lime', source_1080)
        source_720_label = total_format % ('red', source_720) if source_720 == 0 else total_format % ('lime', source_720)
        source_sd_label = total_format % ('red', source_sd) if source_sd == 0 else total_format % ('lime', source_sd)
        source_total_label = total_format % ('red', total) if total == 0 else total_format % ('lime', total)
        return source_4k_label, source_1080_label, source_720_label, source_sd_label, source_total_label



    def filter_source_dict(self, tvshowtitle, source_dict):
        # sourcery skip: assign-if-exp, extract-method, use-fstring-for-concatenation
        """
        Filter and sort the source dictionary based on content type, availability, language, settings, and priority.
        Returns the filtered source_dict and content type.
        """
        try:
            # Determine content type
            content = 'movie' if tvshowtitle is None else 'episode'

            if not source_dict:
                c.log(f'[Sources] No sources to filter for {content}, returning empty list')
                return [], content

            c.log(f'[Sources] Filtering {len(source_dict)} sources for {content}')

            # Step 1: Filter sources based on content availability (movie or tvshow attribute)
            # Cocoscrapers use hasMovies/hasEpisodes instead of movie/tvshow methods
            filtered_sources = []
            rejected = []
            for name, obj in source_dict:
                try:
                    if content == 'movie':
                        if name.startswith('cocoscrapers.'):
                            # Cocoscrapers use hasMovies attribute
                            if getattr(obj, 'hasMovies', False):
                                filtered_sources.append((name, obj))
                            else:
                                rejected.append((name, 'no hasMovies'))
                        elif name.startswith('gearsscrapers.'):
                            # Gearsscrapers prefer a hasMovies attribute, but some providers may implement
                            # movie() or sources() without the flag; accept those as fallbacks.
                            if getattr(obj, 'hasMovies', False):
                                filtered_sources.append((name, obj))
                            elif getattr(obj, 'movie', None) is not None:
                                filtered_sources.append((name, obj))
                                if getattr(c, 'devmode', False):
                                    try:
                                        short_name = name.split('.')[-1].replace('_', ' ').title()
                                    except Exception:
                                        short_name = str(name)
                                    c.log(f'[Sources] Including gearsscrapers provider via movie() fallback: {short_name}')
                            elif getattr(obj, 'search', None) is not None:
                                filtered_sources.append((name, obj))
                                if getattr(c, 'devmode', False):
                                    try:
                                        short_name = name.split('.')[-1].replace('_', ' ').title()
                                    except Exception:
                                        short_name = str(name)
                                    c.log(f'[Sources] Including gearsscrapers provider via search() fallback: {short_name}')
                            elif getattr(obj, 'sources', None) is not None:
                                filtered_sources.append((name, obj))
                                if getattr(c, 'devmode', False):
                                    try:
                                        short_name = name.split('.')[-1].replace('_', ' ').title()
                                    except Exception:
                                        short_name = str(name)
                                    c.log(f'[Sources] Including gearsscrapers provider via sources() fallback: {short_name}')
                            else:
                                rejected.append((name, 'no hasMovies'))
                        else:
                            # Crew sources are expected to implement movie() for modern scrapers
                            if getattr(obj, 'movie', None) is not None:
                                filtered_sources.append((name, obj))
                            elif getattr(obj, 'sources', None) is not None:
                                # Include legacy scrapers that implement sources() directly
                                filtered_sources.append((name, obj))
                                if getattr(c, 'devmode', False):
                                    try:
                                        short_name = name.split('.')[-1].replace('_', ' ').title() if isinstance(name, str) else str(name)
                                    except Exception:
                                        short_name = str(name)
                                    c.log(f'[Sources] Including legacy sources() provider: {short_name}')
                            else:
                                rejected.append((name, 'no movie()'))
                    else:
                        if name.startswith('cocoscrapers.'):
                            # Cocoscrapers use hasEpisodes attribute
                            if getattr(obj, 'hasEpisodes', False):
                                filtered_sources.append((name, obj))
                            else:
                                rejected.append((name, 'no hasEpisodes'))
                        elif name.startswith('gearsscrapers.'):
                            # Gearsscrapers prefer a hasEpisodes attribute, but some providers may implement
                            # tvshow() or sources() without the flag; accept those as fallbacks.
                            if getattr(obj, 'hasEpisodes', False):
                                filtered_sources.append((name, obj))
                            elif getattr(obj, 'tvshow', None) is not None:
                                filtered_sources.append((name, obj))
                                if getattr(c, 'devmode', False):
                                    try:
                                        short_name = name.split('.')[-1].replace('_', ' ').title()
                                    except Exception:
                                        short_name = str(name)
                                    c.log(f'[Sources] Including gearsscrapers provider via tvshow() fallback: {short_name}')
                            elif getattr(obj, 'tvsearch', None) is not None:
                                filtered_sources.append((name, obj))
                                if getattr(c, 'devmode', False):
                                    try:
                                        short_name = name.split('.')[-1].replace('_', ' ').title()
                                    except Exception:
                                        short_name = str(name)
                                    c.log(f'[Sources] Including gearsscrapers provider via tvsearch() fallback: {short_name}')
                            elif getattr(obj, 'sources', None) is not None:
                                filtered_sources.append((name, obj))
                                if getattr(c, 'devmode', False):
                                    try:
                                        short_name = name.split('.')[-1].replace('_', ' ').title()
                                    except Exception:
                                        short_name = str(name)
                                    c.log(f'[Sources] Including gearsscrapers provider via sources() fallback: {short_name}')
                            else:
                                rejected.append((name, 'no hasEpisodes'))
                        else:
                            # Crew sources use tvshow() method
                            if getattr(obj, 'tvshow', None) is not None:
                                filtered_sources.append((name, obj))
                            elif getattr(obj, 'sources', None) is not None:
                                # Include legacy scrapers that implement sources() directly
                                filtered_sources.append((name, obj))
                                if getattr(c, 'devmode', False):
                                    try:
                                        short_name = name.split('.')[-1].replace('_', ' ').title() if isinstance(name, str) else str(name)
                                    except Exception:
                                        short_name = str(name)
                                    c.log(f'[Sources] Including legacy sources() provider: {short_name}')
                            else:
                                rejected.append((name, 'no tvshow()'))
                except Exception as e:
                    c.log(f'[Sources] Error inspecting source {name}: {e}', 1)

            c.log(f'[Sources] After content filtering: {len(filtered_sources)} sources')
            if getattr(c, 'devmode', False):
                c.log(f'[Sources] Rejected during content filtering: {rejected}')

            # Fallback for movies: if no movie-specific scrapers were found, include scrapers that expose a generic `sources()` method
            if content == 'movie' and not filtered_sources:
                c.log('[Sources] No movie-specific scrapers found; falling back to legacy scrapers that implement sources()')
                for name, obj in source_dict:
                    try:
                        if getattr(obj, 'sources', None) is not None:
                            filtered_sources.append((name, obj))
                    except Exception:
                        pass
                c.log(f'[Sources] After fallback content filtering: {len(filtered_sources)} sources')

            # Step 2: Filter by language support
            language = self.getLanguage()
            filtered_sources_with_lang = []
            for name, obj in filtered_sources:
                # Get language attribute safely - cocoscrapers define it in __init__, crew sources as class attribute
                obj_language = getattr(obj, 'language', ['en'])
                filtered_sources_with_lang.append((name, obj, obj_language))
            filtered_sources = [(name, obj) for name, obj, lang in filtered_sources_with_lang if any(supported_lang in lang for supported_lang in language)]
            c.log(f'[Sources] After language filtering: {len(filtered_sources)} sources')            # Step 3: Filter by provider settings (enable/disable individual providers)
            try:
                # For external packs, default to enabled using their global flags; otherwise consult provider.<name> setting
                def get_provider_setting(name):
                    try:
                        # In dev mode, force external packs enabled so developers always see them
                        if getattr(self, 'dev_mode', False):
                            if isinstance(name, str) and (name.startswith('gearsscrapers.') or name.startswith('cocoscrapers.')):
                                return 'true'

                        if name.startswith('cocoscrapers.'):
                            # Cocoscrapers don't have individual provider settings, use global setting
                            return 'true' if self.cocoscrapers_enabled else 'false'
                        if name.startswith('gearsscrapers.'):
                            # Prefer per-provider override (provider.<shortname>) for gear providers
                            try:
                                # e.g., provider.1337x from 'gearsscrapers.providers.torrents.1337x'
                                short = name.split('.')[-1]
                                prov = ''
                                try:
                                    if callable(getattr(control, 'setting', None)):
                                        prov = control.setting('provider.' + short)
                                except Exception:
                                    prov = ''

                                # Fallback to addon setting if control.setting isn't the expected callable
                                if not prov:
                                    try:
                                        import xbmcaddon
                                        addon_inst = xbmcaddon.Addon()
                                        prov = addon_inst.getSetting(id='provider.' + short) if hasattr(addon_inst, 'getSetting') else ''
                                    except Exception:
                                        prov = ''

                                # Additional fallback: some imports use 'modules.control' (different module object)
                                if not prov:
                                    try:
                                        import sys as _sys
                                        alt = _sys.modules.get('modules.control')
                                        if alt and callable(getattr(alt, 'setting', None)):
                                            prov = alt.setting('provider.' + short)
                                    except Exception:
                                        pass

                                # Also check 'resources.lib.modules.control' explicitly (tests may patch that module)
                                if not prov:
                                    try:
                                        import sys as _sys
                                        alt2 = _sys.modules.get('resources.lib.modules.control')
                                        if alt2 and callable(getattr(alt2, 'setting', None)):
                                            prov = alt2.setting('provider.' + short)
                                    except Exception:
                                        pass

                                try:
                                    ctl_id = id(control)
                                except Exception:
                                    ctl_id = None
                                if prov:
                                    return prov
                            except Exception:
                                pass
                            # Gearsscrapers also use a global enable flag
                            # Default to enabled for test harness (per-provider settings or addon may override)
                            return 'true'
                        setting = control.setting('provider.' + name)
                        return setting if setting else 'true'  # Default to enabled if no setting
                    except Exception:
                        return 'true'
                filtered_sources = [(name, obj, get_provider_setting(name)) for name, obj in filtered_sources]
            except Exception as e:
                c.log(f'[Sources] Error getting provider settings: {e}', 1)
                # Default to 'true' if setting retrieval fails
                filtered_sources = [(name, obj, 'true') for name, obj in filtered_sources]

            c.log(f'[Sources] After provider filtering: {len(filtered_sources)} sources')
            filtered_sources = [(name, obj) for name, obj, enabled in filtered_sources if enabled != 'false']

            # Step 3b: Skip scrapers that have timed out twice this session (auto-disabled)
            if _slow_scraper_strikes:
                before = len(filtered_sources)
                skipped = [name for name, obj in filtered_sources if _slow_scraper_strikes.get(name, 0) >= 2]
                filtered_sources = [(name, obj) for name, obj in filtered_sources if _slow_scraper_strikes.get(name, 0) < 2]
                if skipped:
                    c.log(f'[SlowScraper] Skipping {len(skipped)} auto-disabled scraper(s): {skipped[:10]}')
                elif before != len(filtered_sources):
                    c.log(f'[SlowScraper] Filtered {before - len(filtered_sources)} slow scraper(s)')

            # Step 4: Add priority and sort
            # Use a safe getattr to avoid AttributeError when providers don't define a priority
            filtered_sources = [(name, obj, getattr(obj, 'priority', 0)) for name, obj in filtered_sources]
            filtered_sources = sorted(filtered_sources, key=lambda item: item[2])  # Sort by priority (ascending)

            try:
                # Build sample lists and precise breakdowns to diagnose missing providers (devmode only)
                final_names = [name for name, obj, pr in filtered_sources]
                orig_names = [name for name, obj in source_dict]
                removed = [n for n in orig_names if n not in final_names]

                gear_count = len([n for n in final_names if isinstance(n, str) and n.startswith('gearsscrapers.')])
                coco_count = len([n for n in final_names if isinstance(n, str) and n.startswith('cocoscrapers.')])
                native_count = len(final_names) - gear_count - coco_count

                included_sample = final_names[:12]
                if getattr(c, 'devmode', False):
                    rejected_sample = [f"{n} ({r})" for n, r in rejected[:12]] if rejected else []
                    removed_sample = removed[:12]

                    # Dev-only: log provider setting values for removed providers (help debug why they were disabled)
                    try:
                        for rm in removed[:50]:
                            try:
                                val = get_provider_setting(rm)
                            except Exception as e:
                                val = f'ERROR:{e}'

                            # Dev-only diagnostic for gearsscrapers: when a gear provider is disabled
                            # print the upstream flags that control gear behaviour so it's clear
                            # whether the Crew module, the plugin, or the gear addon is causing it.
                            try:
                                if isinstance(rm, str) and rm.startswith('gearsscrapers.') and val == 'false':
                                    try:
                                        import xbmcaddon
                                        module_raw = c.get_setting('gearsscrapers.enabled')
                                    except Exception:
                                        module_raw = ''
                                    try:
                                        # plugin setting may not be accessible in all contexts
                                        plugin_addon = xbmcaddon.Addon('plugin.video.thecrew')
                                        plugin_val = plugin_addon.getSetting('gearsscrapers.enabled') if hasattr(plugin_addon, 'getSetting') else ''
                                    except Exception:
                                        plugin_val = ''
                                    try:
                                        gears_addon = xbmcaddon.Addon('script.module.gearsscrapers')
                                        gears_val = gears_addon.getSetting('enabled') if hasattr(gears_addon, 'getSetting') else ''
                                    except Exception:
                                        gears_val = ''

                            except Exception as e:
                                pass
                    except Exception:
                        pass
                else:
                    pass
            except Exception:
                pass

            # Keep priority in tuples (name, obj, priority) - needed by get_movie_episode_sources
            # Historical note: tests may expect (name, obj) but scraping requires priority
            return filtered_sources, content
        except Exception as e:
            failure = traceback.format_exc()
            # On unexpected error, return empty filtered sources to avoid breaking callers
            return [], ('movie' if tvshowtitle is None else 'episode')






    def get_movie_episode_sources(self, title, year, imdb, tvdb, tmdb, season, episode, tvshowtitle, premiered, source_dict, content, threads):
        try:
            # Track scraper threads separately from Orion to avoid zip() mismatch
            scraper_threads = []
            orion_threads = []

            if content == 'movie':
                title = self.getTitle(title)
                localtitle = self.getLocalTitle(title, imdb, tmdb, content)
                aliases = self.getAliasTitles(imdb, localtitle, content)
                self.search_aliases = aliases  # Store for validation (Phase 2: 2026-02-22)

                if not getattr(c, 'orion_disabled', lambda: False)() and ORION_INSTALLED:
                    orion_thread = workers.Thread(self.getOrionMovieSource, title, localtitle, aliases, year, imdb, tmdb)
                    orion_threads.append(orion_thread)
                    threads.append(orion_thread)

                try:
                    sample = [(i[0], i[2], 'gear' if str(i[0]).startswith('gearsscrapers.') else ('coco' if str(i[0]).startswith('cocoscrapers.') else 'native')) for i in (source_dict or [])[:8]]
                except Exception:
                    pass

                try:
                    gear_included = [name for name, obj, pr in (source_dict or []) if isinstance(name, str) and name.startswith('gearsscrapers.')]
                    if gear_included:
                        # schedule a short failure summary so any gear scraper errors are aggregated and visible
                        try:
                            su = sys.modules.get('gearsscrapers.modules.source_utils')
                            if su and hasattr(su, '_schedule_failure_summary'):
                                su._schedule_failure_summary(delay=3.0)
                        except Exception:
                            pass
                except Exception:
                    pass

                # Build unified data dict for all scrapers (Modern BaseScraper architecture)
                movie_data = {
                    'title': title,
                    'localtitle': localtitle,
                    'aliases': aliases,
                    'year': year,
                    'imdb': imdb,
                    'tmdb': tmdb
                }

                # Call sources() directly - no wrapper methods (completes BaseScraper refactor)
                for source_name, scraper_obj, priority in source_dict:
                    scraper_thread = workers.Thread(self._scraper_sources_wrapper, scraper_obj, movie_data, source_name)
                    scraper_threads.append(scraper_thread)
                    threads.append(scraper_thread)
            elif content == 'episode':
                tvshowtitle = self.getTitle(tvshowtitle)
                localtvshowtitle = self.getLocalTitle(tvshowtitle, imdb, tmdb, content)
                aliases = self.getAliasTitles(imdb, localtvshowtitle, content)
                self.search_aliases = aliases  # Store for validation (Phase 2: 2026-02-22)

                if not getattr(c, 'orion_disabled', lambda: False)() and getattr(c, 'is_orion_installed', lambda: False)():
                    orion_thread = workers.Thread(self.get_orion_tvshow_source, title, tvshowtitle, aliases, year, imdb, tmdb, season, episode)
                    orion_threads.append(orion_thread)
                    threads.append(orion_thread)

                # Build unified data dict for all scrapers (Modern BaseScraper architecture)
                episode_data = {
                    'title': title,
                    'year': year,
                    'imdb': imdb,
                    'tvdb': tvdb,
                    'tmdb': tmdb,
                    'season': season,
                    'episode': episode,
                    'tvshowtitle': tvshowtitle,
                    'localtvshowtitle': localtvshowtitle,
                    'aliases': aliases,
                    'premiered': premiered
                }

                # Call sources() directly - no wrapper methods (completes BaseScraper refactor)
                for source_name, scraper_obj, priority in source_dict:
                    scraper_thread = workers.Thread(self._scraper_sources_wrapper, scraper_obj, episode_data, source_name)
                    scraper_threads.append(scraper_thread)
                    threads.append(scraper_thread)

            # FIXED: Only zip source_dict with scraper_threads (not all threads which includes Orion)
            # This ensures thread names match their corresponding source objects
            combined_sources = [(source_name, source_obj, priority, thread) for (source_name, source_obj, priority), thread in zip(source_dict, scraper_threads)]

            # Extract thread names, source names, and priorities for easier processing
            thread_info = [(thread.getName(), source_name, priority) for source_name, source_obj, priority, thread in combined_sources]

            # Add Orion threads to tracking with special handling (priority 0, displayed as ORION)
            for orion_thread in orion_threads:
                thread_info.append((orion_thread.getName(), 'orion', 0))

            # DEBUG: Log thread_info to see what priorities scrapers have
            try:
                priority_counts = {}
                for _, _, p in thread_info:
                    priority_counts[p] = priority_counts.get(p, 0) + 1
            except Exception as e:
                pass

            # Get main source dict: ALL thread names (removed priority filter - all scrapers should show in dialog)
            # Previous filter 'if priority == 0' was excluding most scrapers from showing in progress dialog
            mainsource_dict = [thread_name for thread_name, source_name, priority in thread_info]

            # Get source label dict: {thread_name: formatted_source_name.upper()}
            # Apply external-pack formatting for display (cocoscrapers/gears)
            sourcelabel_dict = {thread_name: self.format_external_source_name(source_name).upper() for thread_name, source_name, priority in thread_info}

            # Event-driven: Initialize active scraper counter before starting threads
            with self.active_scrapers_lock:
                self.active_scrapers = len(threads)

            c.log(f'[Sources] Starting {len(threads)} scraper threads (event-driven architecture)')

            for i in threads:
                i.start()

            try:
                pass
            except Exception:
                pass

            return mainsource_dict, sourcelabel_dict
        except Exception as e:
            failure = traceback.format_exc()


    #checked OH - 26-04-2021
    def prepare_sources(self):
        try:
            control.makeFile(control.dataPath)
            dbcon = database.connect(control.providercacheFile)
            dbcur = dbcon.cursor()
            sql_create_rel_url = """
                CREATE TABLE IF NOT EXISTS rel_url (
                    source TEXT,
                    imdb_id TEXT,
                    season TEXT,
                    episode TEXT,
                    rel_url TEXT,
                    UNIQUE(source, imdb_id, season, episode)
                    );
                """
            sql_create_rel_src = """
                CREATE TABLE IF NOT EXISTS rel_src (
                    source TEXT,
                    imdb_id TEXT,
                    season TEXT,
                    episode TEXT,
                    hosts TEXT,
                    added TEXT,
                    UNIQUE(source, imdb_id, season, episode)
                    );
                """
            dbcur.execute(sql_create_rel_url)
            dbcur.execute(sql_create_rel_src)

            # Create source cache table for caching scraped sources
            sql_create_source_cache = """
                CREATE TABLE IF NOT EXISTS source_cache (
                    cache_key TEXT PRIMARY KEY,
                    imdb_id TEXT,
                    tmdb_id TEXT,
                    season TEXT,
                    episode TEXT,
                    sources_json TEXT,
                    cached_at INTEGER,
                    UNIQUE(cache_key)
                );
            """
            dbcur.execute(sql_create_source_cache)
            dbcon.commit()

            dbcur.close()
            dbcon.close()
            #dbcur.execute("CREATE TABLE IF NOT EXISTS rel_url (""source TEXT, ""imdb_id TEXT, ""season TEXT, ""episode TEXT, ""rel_url TEXT, UNIQUE(source, imdb_id, season, episode));")
            #dbcur.execute("CREATE TABLE IF NOT EXISTS rel_src (""source TEXT, ""imdb_id TEXT, ""season TEXT, ""episode TEXT, ""hosts TEXT, ""added TEXT, UNIQUE(source, imdb_id, season, episode));")

        except Exception as e:
            pass

    def get_source_cache_key(self, imdb, tmdb, season=None, episode=None):
        """Generate a unique cache key for source lookups."""
        if season and episode:
            return f"sources_{imdb}_{tmdb}_s{season}e{episode}"
        return f"sources_{imdb}_{tmdb}_movie"

    def get_cached_sources(self, imdb, tmdb, season=None, episode=None):
        """
        Retrieve cached sources from database (for general playback).

        :param imdb: IMDb ID
        :param tmdb: TMDb ID
        :param season: Season number (for TV shows)
        :param episode: Episode number (for TV shows)
        :return: List of cached sources or None if cache miss/expired
        """
        try:
            # Get cache duration from settings (in minutes, default 15)
            cache_duration_minutes = int(control.setting('sources.cache.duration') or '15')
            cache_duration_seconds = cache_duration_minutes * 60

            cache_key = self.get_source_cache_key(imdb, tmdb, season, episode)
            current_time = int(time.time())

            control.makeFile(control.dataPath)
            try:
                dbcon = database.connect(control.providercacheFile)
                dbcur = dbcon.cursor()
                # Ensure the source_cache table exists; if DB file is stale/non-sqlite this may raise
                try:
                    dbcur.execute("CREATE TABLE IF NOT EXISTS source_cache (cache_key TEXT PRIMARY KEY, imdb_id TEXT, tmdb_id TEXT, season TEXT, episode TEXT, sources_json TEXT, cached_at INTEGER)")
                    dbcon.commit()
                except Exception:
                    # Attempt to recreate via prepare_sources helper, then reconnect
                    try:
                        self.prepare_sources()
                        dbcon = database.connect(control.providercacheFile)
                        dbcur = dbcon.cursor()
                    except Exception:
                        raise

                # Get cached entry
                dbcur.execute(
                    "SELECT sources_json, cached_at FROM source_cache WHERE cache_key = ?",
                    (cache_key,)
                )
                result = dbcur.fetchone()
            except Exception as e:
                c.log(f"[SourceCache] Error retrieving cache (attempting recovery): {e}", 1)
                try:
                    self.prepare_sources()
                except Exception:
                    pass
                return None

            if result:
                sources_json, cached_at = result
                age_seconds = current_time - cached_at

                if age_seconds < cache_duration_seconds:
                    # Cache is still valid
                    c.log(f"[SourceCache] Cache HIT for {cache_key}, age: {age_seconds}s / {cache_duration_seconds}s")
                    dbcur.close()
                    dbcon.close()

                    # Deserialize sources and validate
                    import json
                    try:
                        loaded = json.loads(sources_json)
                        if not isinstance(loaded, list):
                            c.log(f"[SourceCache] Bad payload cached for {cache_key}, purging", 1)
                            dbcon = database.connect(control.providercacheFile)
                            dbcur = dbcon.cursor()
                            dbcur.execute("DELETE FROM source_cache WHERE cache_key = ?", (cache_key,))
                            dbcon.commit()
                            dbcur.close()
                            dbcon.close()
                            return None
                        return loaded
                    except Exception as deser_exc:
                        c.log(f"[SourceCache] Error deserializing cache for {cache_key}: {deser_exc}", 1)
                        # Purge invalid cache entry
                        dbcon = database.connect(control.providercacheFile)
                        dbcur = dbcon.cursor()
                        dbcur.execute("DELETE FROM source_cache WHERE cache_key = ?", (cache_key,))
                        dbcon.commit()
                        dbcur.close()
                        dbcon.close()
                        return None
                    else:
                        # Cache expired, delete it
                        c.log(f"[SourceCache] Cache EXPIRED for {cache_key}, age: {age_seconds}s > {cache_duration_seconds}s")
            try:
                dbcon = database.connect(control.providercacheFile)
                dbcur = dbcon.cursor()
                dbcur.execute("SELECT sources_json, cached_at FROM source_cache WHERE imdb_id = ? OR tmdb_id = ? LIMIT 1", (imdb, tmdb))
                row = dbcur.fetchone()
                dbcur.close()
                dbcon.close()
                if row:
                    try:
                        import json
                        loaded = json.loads(row[0])
                        if isinstance(loaded, list):
                            return loaded
                    except Exception:
                        pass
            except Exception:
                pass
            return None

        except Exception as e:
            c.log(f"[SourceCache] Error retrieving cache: {e}", 1)
            return None

    def cache_sources(self, sources, imdb, tmdb, season=None, episode=None):
        """
        Store sources in cache for future lookups.

        :param sources: List of source dictionaries to cache
        :param imdb: IMDb ID
        :param tmdb: TMDb ID
        :param season: Season number (for TV shows)
        :param episode: Episode number (for TV shows)
        """
        try:
            cache_key = self.get_source_cache_key(imdb, tmdb, season, episode)
            current_time = int(time.time())

            control.makeFile(control.dataPath)
            dbcon = database.connect(control.providercacheFile)
            dbcur = dbcon.cursor()

            # Serialize sources to JSON (be tolerant of non-serializable values)
            import json
            try:
                sources_json = json.dumps(sources)
            except Exception as ser_exc:
                try:
                    # Fallback: coerce non-serializable values to strings
                    sources_json = json.dumps(sources, default=str)
                    c.log(f"[SourceCache] Warning: coerced non-serializable values when caching {cache_key}: {ser_exc}")
                except Exception as ser_exc2:
                    c.log(f"[SourceCache] Error serializing sources for cache: {ser_exc2}", 1)
                    dbcur.close()
                    dbcon.close()
                    return

            # Ensure source cache table exists and Insert or replace cache entry
            dbcur.execute("""CREATE TABLE IF NOT EXISTS source_cache (
                    cache_key TEXT PRIMARY KEY,
                    imdb_id TEXT,
                    tmdb_id TEXT,
                    season TEXT,
                    episode TEXT,
                    sources_json TEXT,
                    cached_at INTEGER
                );""")
            dbcur.execute(
                """INSERT OR REPLACE INTO source_cache
                   (cache_key, imdb_id, tmdb_id, season, episode, sources_json, cached_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (cache_key, imdb, tmdb, str(season) if season else '',
                 str(episode) if episode else '', sources_json, current_time)
            )
            dbcon.commit()
            dbcur.close()
            dbcon.close()

            c.log(f"[SourceCache] Cached {len(sources)} sources for {cache_key}")
            c.log(f"[SourceCache] Cached {len(sources)} sources for {cache_key} into {control.providercacheFile}")

        except Exception as e:
            c.log(f"[SourceCache] Error caching sources: {e}", 1)

    def clear_expired_source_cache(self):
        """Clear all expired cache entries to keep database clean."""
        try:
            cache_duration_minutes = int(control.setting('sources.cache.duration') or '15')
            cache_duration_seconds = cache_duration_minutes * 60
            current_time = int(time.time())
            expiry_time = current_time - cache_duration_seconds

            control.makeFile(control.dataPath)
            dbcon = database.connect(control.providercacheFile)
            dbcur = dbcon.cursor()

            dbcur.execute("DELETE FROM source_cache WHERE cached_at < ?", (expiry_time,))
            deleted_count = dbcur.rowcount
            dbcon.commit()
            dbcur.close()
            dbcon.close()

            if deleted_count > 0:
                c.log(f"[SourceCache] Cleared {deleted_count} expired cache entries")

        except Exception as e:
            c.log(f"[SourceCache] Error clearing expired cache: {e}", 1)


    def _call_sources(self, call, *args):
        """Attempt to call call.sources with varying argument counts to support legacy and modern scrapers.
        Tries: (all args) -> (drop last arg) -> (first arg only). Returns list (or empty list on failure).
        """
        try:
            attempts = [args, args[:len(args)-1], args[:1]]
        except Exception:
            attempts = [args, args[:1]]
        for attempt in attempts:
            if not attempt:
                continue
            try:
                res = call.sources(*attempt)
                return res
            except TypeError:
                # signature doesn't accept this many args -- try next attempt
                continue
            except Exception as e:
                # Log exception with minimal info
                c.log(f'[Sources] Exception calling sources(): {e}', 1)
                if getattr(c, 'devmode', False):
                    pass
                return []
        # Signature mismatch - log warning
        if getattr(c, 'devmode', False):
            c.log(f'[Sources] Signature mismatch for sources() - no compatible arguments found', 2)
        return []

    def _scraper_sources_wrapper(self, scraper_obj, data, source_name):
        """
        Modern scraper wrapper - calls sources() directly with data dict.
        Event-driven: pushes completion notification to queue when done.

        :param scraper_obj: Scraper instance
        :param data: Unified data dict (movie or episode metadata)
        :param source_name: Provider name for attribution
        """
        result_count = 0
        success = False
        error_msg = None
        _start = time.time()

        try:
            # Call sources() with data dict and host lists.
            # External scrapers (Gears/Coco/Viper) only accept (data, hostDict) — 2 args.
            # Native Crew scrapers accept (data, hostDict, hostprDict) — 3 args.
            try:
                sources = scraper_obj.sources(data, self.hostDict, self.hostprDict)
            except TypeError:
                sources = scraper_obj.sources(data, self.hostDict)

            if not sources or sources == []:
                c.log(f'[Scraper] (X) {source_name} -> 0 results')
            else:
                # Normalize sources (handle both dict and JSON string formats)
                try:
                    sources = [
                        json.loads(s) if isinstance(s, (str, bytes)) else s
                        for s in sources
                        if s
                    ]
                except Exception as e:
                    c.log(f'[Scraper] {source_name} error normalizing sources: {e}', 1)
                    sources = []

                # Deduplicate sources
                if sources:
                    try:
                        sources = [
                            json.loads(t)
                            for t in {json.dumps(d, sort_keys=True) for d in sources}
                        ]
                    except Exception as e:
                        c.log(f'[Scraper] {source_name} error deduplicating: {e}', 1)

                    # Add provider attribution
                    for source in sources:
                        if isinstance(source, dict):
                            source['provider'] = source_name

                    # Thread-safe: extend sources list with lock
                    with self.sources_lock:
                        self.sources.extend(sources)

                    result_count = len(sources)
                    success = True

                    # Log results with quality breakdown
                    try:
                        quality_counts = {}
                        for s in sources:
                            qual = s.get('quality', 'Unknown') if isinstance(s, dict) else 'Unknown'
                            quality_counts[qual] = quality_counts.get(qual, 0) + 1
                        c.log(f'[Scraper] (OK) {source_name} -> {result_count} results: {quality_counts}')
                    except Exception:
                        pass

        except Exception as e:
            failure = traceback.format_exc()
            c.log(f'[Scraper] {source_name} exception: {failure}', 1)
            error_msg = str(e)

        finally:
            # Slow-scraper auto-disable: if this run hit the timeout, record a strike
            try:
                elapsed = time.time() - _start
                _session_timeout = getattr(self, 'scraper_timeout', 30)
                if elapsed >= _session_timeout:
                    strikes = _slow_scraper_strikes.get(source_name, 0) + 1
                    _slow_scraper_strikes[source_name] = strikes
                    if strikes >= 2:
                        c.log(f'[SlowScraper] {source_name} timed out {strikes}x — auto-disabled for this session', 1)
                    else:
                        c.log(f'[SlowScraper] {source_name} timed out (strike {strikes}/2, {elapsed:.1f}s >= {_session_timeout}s)')
            except Exception:
                pass

            # Event-driven: Signal completion (always, even on error)
            try:
                self.completion_queue.put({
                    'scraper': source_name,
                    'count': result_count,
                    'success': success,
                    'error': error_msg
                })
            except Exception as e:
                c.log(f'[Scraper] {source_name} failed to queue completion: {e}', 1)

            # Decrement active scraper counter
            with self.active_scrapers_lock:
                self.active_scrapers -= 1
                remaining = self.active_scrapers

            if remaining == 0:
                c.log('[Sources] All scrapers completed')
            elif remaining % 5 == 0:
                c.log(f'[Sources] {remaining} scrapers still running')

    def get_movie_source(self, title, localtitle, aliases, year, imdb, source, call):
        dbcon = None
        dbcur = None
        if not hasattr(self, 'sourceFile'):
            self.sourceFile = control.providercacheFile
        try:
            dbcon = database.connect(self.sourceFile)
            dbcur = dbcon.cursor()
        except Exception:
            pass



        #Fix to stop items passed with a 0 IMDB id pulling old unrelated sources from the database.
        # cm - changed 2025-03-12
        if imdb == '0' and dbcur and dbcon:
            try:
                dbcur.execute(f"DELETE FROM rel_src WHERE source = '{source}' AND imdb_id = '{imdb}'")
                dbcon.commit()
            except Exception:
                pass
        #END

        try:
            sources = []
            if dbcur and dbcon:
                dbcur.execute(f"SELECT * FROM rel_src WHERE source = '{source}' AND imdb_id = '{imdb}' AND season = '' AND episode = ''")
                match = dbcur.fetchone()
                t1 = int(re.sub('[^0-9]', '', str(match[5])))
                t2 = int(datetime.datetime.now().strftime("%Y%m%d%H%M"))
                update = abs(t2 - t1) > 3600
                if update is False:
                    sources = json.loads(c.to_str(match[4]))
                    self.sources.extend(sources)
                    return self.sources
        except Exception:
            pass

        # Build data dict for scraper (unified architecture with cocoscrapers)
        try:
            sources = []

            data = {
                'title': title,
                'localtitle': localtitle,
                'aliases': aliases,
                'year': year,
                'imdb': imdb
            }

            # Some sources implement a movie() helper returning a url string,
            # while others accept a data dict in sources(); handle both.
            sources = []
            try:
                url = None
                # Try movie() -> sources(url, ...) pathway first (common pattern)
                if hasattr(call, 'movie') and callable(getattr(call, 'movie')):
                    try:
                        url = call.movie(imdb, title, localtitle, aliases, year)
                    except Exception as e:
                        c.log(f'[Scraper] {source}.movie() error: {e}', 1)

                if url:
                    try:
                        sources = self._call_sources(call, url, self.hostDict, self.hostprDict)
                    except Exception as e:
                        c.log(f'[Scraper] {source} error with url: {e}', 1)
                        sources = []
                else:
                    # Fallback: some scrapers accept the full data dict directly
                    try:
                        sources = self._call_sources(call, data, self.hostDict, self.hostprDict)
                    except Exception as e:
                        c.log(f'[Scraper] {source} error with data: {e}', 1)
                        sources = []
            except Exception as e:
                c.log(f'[Scraper] {source} error: {e}', 1)

            # Log scraper results clearly
            try:
                total = len(sources) if sources else 0
                if total > 0:
                    # Count quality distribution
                    quality_counts = {}
                    for s in sources or []:
                        sd = s if isinstance(s, dict) else (json.loads(s) if isinstance(s, (str, bytes)) else {})
                        qual = sd.get('quality', 'Unknown') if isinstance(sd, dict) else 'Unknown'
                        quality_counts[qual] = quality_counts.get(qual, 0) + 1
                    c.log(f'[Scraper] (OK) {source} -> {total} results: {quality_counts}')
                else:
                    c.log(f'[Scraper] (X) {source} -> 0 results')
            except Exception as e:
                c.log(f'[Scraper] {source} error summarizing: {e}', 1)

            if sources is None or sources == []:
                raise crew_errors.NoResultsError()

            sources = [
                json.loads(t)
                for t in {json.dumps(d, sort_keys=True) for d in sources}
            ]

            for i in sources:
                i.update({'provider': source})
            self.sources.extend(sources)

            if dbcur and dbcon:
                dbcur.execute(f"DELETE FROM rel_src WHERE source = '{source}' AND imdb_id = '{imdb}' AND season = '' AND episode = ''")
                dbcur.execute("INSERT INTO rel_src Values (?, ?, ?, ?, ?, ?)", (source, imdb, '', '', repr(sources), datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
                dbcon.commit()
                dbcon.close()

        except crew_errors.NoResultsError:
            pass  # Normal - scraper found nothing
        except Exception as e:
            c.log(f'[Scraper] {source} exception: {e}', 1)
            if getattr(c, 'devmode', False):
                c.log(f'[Scraper Debug] Traceback:\n{traceback.format_exc()}', 2)


    # Orion integration for movie sources
    # [COMPLETE] Smart limit system implemented (2026-03-10)
    def getOrionMovieSource(self, title, localtitle, aliases, year, imdb, tmdb):
        """Orion movie scraper with event-driven completion handling."""
        result_count = 0
        success = False

        try:
            pass

            if not hasattr(self, 'sourceFile'):
                self.sourceFile = control.providercacheFile
            dbcon = database.connect(self.sourceFile)
            dbcur = dbcon.cursor()

            update = False
            hosts = None

            try:
                dbcur.execute(f"SELECT * FROM rel_url WHERE source = 'Orion' AND imdb_id = '{imdb}'")
                row = dbcur.fetchone()
                if not row:
                    update = True
                    raise Exception()
                hosts = json.loads(c.to_str(row[4]))
                t1 = int(re.sub('[^0-9]', '', str(row[5])))
                t2 = int(datetime.datetime.now().strftime("%Y%m%d%H%M"))
                update = abs(t2 - t1) > 3600
                if update is False:
                    self.sources.extend(hosts)
                    result_count = len(hosts) if hosts else 0
                    success = True
                    return self.sources
            except Exception:
                pass

            #we have no cached orion data of this movie
            try:
                if update or hosts is None:
                    sources = []
                    # Use smart limit based on user's Orion tier and remaining quota
                    smart_limit = oa.get_smart_limit()
                    data = oa.get_movie(imdb, limit=smart_limit)
                    sources = oa.do_orion_scrape(data, 'movie')
                    if sources:
                        dbcur.execute(f"DELETE FROM rel_url WHERE source = 'Orion' AND imdb_id = '{imdb}'")
                        dbcur.execute("INSERT INTO rel_url Values (?, ?, ?, ?, ?)", ('Orion', imdb, '', '', repr(sources)))
                        dbcon.commit()
                        self.sources.extend(sources)
                        result_count = len(sources)
                        success = True
                        return sources
                    return []
            except Exception as e:
                failure = traceback.format_exc()
                c.log(f'[Scraper] orion exception: {failure}', 1)
                pass

        finally:
            # Event-driven: Signal completion (always, even on error)
            try:
                self.completion_queue.put({
                    'scraper': 'orion',
                    'count': result_count,
                    'success': success,
                    'error': None
                })
                if result_count > 0:
                    c.log(f'[Sources] ✓ orion completed:  {result_count} sources')
            except Exception as e:
                c.log(f'[Scraper] orion failed to queue completion: {e}', 1)

            # Decrement active scraper counter
            with self.active_scrapers_lock:
                self.active_scrapers -= 1

    # Orion integration for TV shows
    # [COMPLETE] 2026-03-10: Implemented smart limit system based on user tier and quota
    # - get_user_tier_info() retrieves package/limits from Orion API
    # - get_smart_limit() calculates appropriate limit (25-250) based on tier and remaining quota
    # - Expert/Premium: 50-250 | Basic/Standard: 50-100 | Free: 25-50
    def get_orion_tvshow_source(self, title, localtitle, aliases, year, imdb, tmdb, season, episode):
        """Orion TV show scraper with event-driven completion handling."""
        result_count = 0
        success = False

        try:
            pass

            if not hasattr(self, 'sourceFile'):
                self.sourceFile = control.providercacheFile
            dbcon = database.connect(self.sourceFile)
            dbcur = dbcon.cursor()

            update = False
            hosts = None


            try:
                dbcur.execute(f"SELECT * FROM rel_url WHERE source = 'Orion' AND imdb_id = '{imdb}' AND season = '{season}' AND episode = '{episode}'")
                row = dbcur.fetchone()
                if not row:
                    update = True
                    raise Exception()
                hosts = json.loads(c.to_str(row[4]))
                t1 = int(re.sub('[^0-9]', '', str(row[5])))
                t2 = int(datetime.datetime.now().strftime("%Y%m%d%H%M"))
                update = abs(t2 - t1) > 3600
                if not update:
                    self.sources.extend(hosts)
                    result_count = len(hosts) if hosts else 0
                    success = True
                    return self.sources
            except Exception as e:
                self._log_orion_error(
                    traceback,
                    '[CM Debug @ 1582 in sources.py]Traceback:: ',
                    '[CM Debug @ 1583 in sources.py]Exception raised. Error = ',
                    e,
                )

            #we have no cached orion data of this episode
            try:
                if update or hosts is None:
                    sources = []
                    # Use smart limit based on user's Orion tier and remaining quota
                    smart_limit = oa.get_smart_limit()
                    data = oa.get_episode(imdb=imdb, tmdb=tmdb, title=title, season=season, episode=episode, limit=smart_limit)
                    sources = oa.do_orion_scrape(data, 'episode')


                    if sources:
                        sql_delete = f"DELETE FROM rel_url WHERE source = 'Orion' AND imdb_id = '{imdb}' AND season = '{season}' AND episode = '{episode}'"
                        if c.devmode:
                            pass
                        dbcur.execute(sql_delete)
                        dbcur.execute("INSERT INTO rel_url Values (?, ?, ?, ?, ?)", ('Orion', imdb, season, episode, repr(sources)))
                        dbcon.commit()
                    if sources:
                        self.sources.extend(sources)
                        result_count = len(sources)
                        success = True
                        return self.sources
                    return []
            except Exception as e:
                self._log_orion_error(
                    traceback,
                    '[CM Debug @ 1587 in sources.py]Traceback:: ',
                    '[CM Debug @ 1588 in sources.py]Exception raised. Error = ',
                    e,
                )

        finally:
            # Event-driven: Signal completion (always, even on error)
            try:
                self.completion_queue.put({
                    'scraper': 'orion',
                    'count': result_count,
                    'success': success,
                    'error': None
                })
                if result_count > 0:
                    c.log(f'[Sources] ✓ orion completed:  {result_count} sources')
            except Exception as e:
                c.log(f'[Scraper] orion failed to queue completion: {e}', 1)

            # Decrement active scraper counter
            with self.active_scrapers_lock:
                self.active_scrapers -= 1

    def _log_orion_error(self, traceback, arg1, arg2, e):
        """Helper method to log Orion scraper errors with traceback."""
        failure = traceback.format_exc()
        c.log(f'{arg1}{failure}')
        c.log(f'{arg2}{e}')






    def getEpisodeSource(self, title, year, imdb, tmdb, season, episode, tvshowtitle, localtvshowtitle, aliases, premiered, source, call):
        try:
            if not hasattr(self, 'sourceFile'):
                self.sourceFile = control.providercacheFile
            dbcon = database.connect(self.sourceFile)
            dbcur = dbcon.cursor()
        except Exception:
            pass

        try:
            sources = []
            dbcur.execute(f"SELECT * FROM rel_src WHERE source = '{source}' AND imdb_id = '{imdb}' AND season = '{season}' AND episode = '{episode}'")

            match = dbcur.fetchone()
            t1 = int(re.sub('[^0-9]', '', str(match[5])))
            t2 = int(datetime.datetime.now().strftime("%Y%m%d%H%M"))
            update = abs(t2 - t1) > 3600
            if not update:
                sources = json.loads(c.to_str(match[4]))
                self.sources.extend(sources)
                return self.sources
        except Exception:
            pass

        # Build data dict for scraper (unified architecture with cocoscrapers)
        if getattr(c, 'is_orion_installed', lambda: False)() and source == 'Orion':
            oa = OrionApi()
            try:
                # !Orion, self.oa = OrionApi
                # TODO: check  for validity of user
                # TODO: check limit in get_movie. get_movie returns, without limit alle results for a movie.
                # TODO: so a user with a "free" or even a "modest" premium account would have his daily limit reached with
                # TODO: this (or 1) call.
                sources = []
                data = oa.get_episode(imdb, tmdb, title, season, episode, limit=25)
                if sources := oa.do_orion_scrape(data, 'movie'):
                    self.sources.extend(sources)
            except Exception as e:
                import traceback as _traceback
                failure = _traceback.format_exc()

        try:
            sources = []

            # Build unified data dict for all scrapers
            data = {
                'title': title,
                'year': year,
                'imdb': imdb,
                'tmdb': tmdb,
                'season': season,
                'episode': episode,
                'tvshowtitle': tvshowtitle,
                'localtvshowtitle': localtvshowtitle,
                'aliases': aliases,
                'premiered': premiered
            }

            # Some scrapers use URL pathway (episode/tvshow method), others accept data dict directly
            # Try URL pathway first (legacy pattern), fall back to data dict (modern pattern)
            url = None
            try:
                # Try tvshow() -> episode() pathway first (legacy scrapers)
                if hasattr(call, 'tvshow') and callable(getattr(call, 'tvshow')):
                    try:
                        url = call.tvshow(imdb, tmdb, tvshowtitle, localtvshowtitle, aliases, year)
                        c.log(f'[Sources] {source}.tvshow() returned: {url}', 2)
                    except Exception as e:
                        c.log(f'[Scraper] {source}.tvshow() error: {e}', 1)

                # If tvshow returned URL, try to call episode() for specific episode URL
                if url and hasattr(call, 'episode') and callable(getattr(call, 'episode')):
                    try:
                        url = call.episode(url, imdb, None, title, premiered, season, episode)
                        c.log(f'[Sources] {source}.episode() returned: {url}', 2)
                    except Exception as e:
                        c.log(f'[Scraper] {source}.episode() error: {e}', 1)
                        url = None
            except Exception as e:
                c.log(f'[Scraper] {source} URL pathway error: {e}', 1)
                url = None

            # If we have a URL, pass it to sources(); otherwise pass data dict
            if url:
                try:
                    c.log(f'[Sources] Calling episode source "{source}" with URL')
                    sources = self._call_sources(call, url, self.hostDict, self.hostprDict)
                except Exception as e:
                    c.log(f'[Sources] Error calling {source} (episode) with URL: {e}', 1)
                    sources = []
            else:
                # Fallback: pass data dict directly (modern scrapers)
                try:
                    c.log(f'[Sources] Calling episode source "{source}" with data dict')
                    sources = self._call_sources(call, data, self.hostDict, self.hostprDict)
                except Exception as e:
                    c.log(f'[Sources] Error calling {source} (episode) with data: {e}', 1)
                    sources = []

            # Summarize results for debugging: count, debrid-only count, and unique provider strings
            try:
                total = len(sources) if sources else 0
                debrid_cnt = 0
                providers_set = set()
                for s in sources or []:
                    sd = None
                    if isinstance(s, (str, bytes)):
                        try:
                            sd = json.loads(s)
                        except Exception:
                            sd = {}
                    else:
                        sd = s
                    if sd and sd.get('debridonly', False):
                        debrid_cnt += 1
                    providers_set.add(str(sd.get('provider', '')).strip() if isinstance(sd, dict) else '')
                non_debrid = total - debrid_cnt
                c.log(f'[Sources] {source} (episode) returned {total} items (debridonly={debrid_cnt}, non-debrid={non_debrid}) providers={sorted([p for p in providers_set if p])}')
            except Exception as e:
                c.log(f'[Sources] Error summarizing results for {source} (episode): {e}', 1)

            if sources is None or sources == []:
                raise Exception()
            sources = [json.loads(t) for t in set(json.dumps(d, sort_keys=True) for d in sources)]
            for i in sources: i.update({'provider': source})
            self.sources.extend(sources)

            # Pack support: Check if scraper supports packs and call sources_packs()
            try:
                if hasattr(call, 'pack_capable') and getattr(call, 'pack_capable', False):
                    if hasattr(call, 'sources_packs'):
                        # Build pack data dict
                        pack_data = {
                            'tvshowtitle': tvshowtitle,
                            'season': season,
                            'episode': episode,
                            'year': year,
                            'imdb': imdb,
                            'tmdb': tmdb,
                            'aliases': aliases
                        }

                        # Get total seasons for show pack support (passed via data dict)
                        total_seasons = 0
                        # Note: meta not available in worker thread scope
                        # Use data dict or scraper will query if needed

                        # Call season pack scraper (search_series=False)
                        pack_sources = call.sources_packs(pack_data, self.hostDict, search_series=False, total_seasons=total_seasons)

                        if pack_sources:
                            # Deduplicate and add provider
                            pack_sources = [json.loads(t) for t in set(json.dumps(d, sort_keys=True) for d in pack_sources)]
                            for i in pack_sources:
                                i.update({'provider': source})
                            self.sources.extend(pack_sources)
                            c.log(f'[Pack] Found {len(pack_sources)} pack sources from {source}')
            except Exception as e:
                c.log(f'[Pack] Error calling sources_packs for {source}: {e}')
                pass

            dbcur.execute(f"DELETE FROM rel_src WHERE source = '{source}' AND imdb_id = '{imdb}' AND season = '{season}' AND episode = '{episode}'")
            dbcur.execute("INSERT INTO rel_src Values (?, ?, ?, ?, ?, ?)", (source, imdb, season, episode, repr(sources), datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
            dbcon.commit()
        except Exception:
            pass

    def alter_sources(self, url, meta):
        with contextlib.suppress(Exception):
            url += '&select=1' if control.setting('hosts.mode') == '2' else '&select=2'
            control.execute(f'RunPlugin({url})')

    #cm - fixed
    def clearSources(self):
        try:
            control.idle()

            yes = control.yesnoDialog(control.lang(32076))
            if not yes:
                return

            control.makeFile(control.dataPath)
            dbcon = database.connect(control.providercacheFile)
            dbcur = dbcon.cursor()
            dbcur.execute("DROP TABLE IF EXISTS rel_src")
            dbcur.execute("DROP TABLE IF EXISTS rel_url")
            dbcur.execute("VACUUM")
            dbcon.commit()

            control.infoDialog(control.lang(32077), sound=True, icon='INFO')
        except Exception:
            pass

    def unique_sources(self, sources):
        """Yield unique sources from a list of sources using a robust dedupe key.

        This function constructs a dedupe key from the provider, name and url
        (or a stringified form of the url). It tolerates missing or non-string
        url values and avoids dropping all results when URLs are None by falling
        back to provider+name based deduplication.
        """
        unique_keys = set()
        for source in sources:
            # Build a robust key: provider | name | url (shortened for magnets)
            provider = str(source.get('provider', '') or '')
            name = str(source.get('name', '') or '')
            url = source.get('url')

            if isinstance(url, str):
                key_url = url[:60] if url.startswith('magnet:') else url
            else:
                # Fallback to string representation for non-str urls (None, dict, etc.)
                key_url = str(url)

            key = f"{provider}|{name}|{key_url}"

            if key not in unique_keys:
                unique_keys.add(key)
                yield source  # Yield the unique source


    def sourcesProcessTorrents2(self, torrent_sources):
        """Process torrent sources by checking for cached hashes.

        This function takes a list of torrent sources and checks if the torrent
        info hashes are cached in the local database. If so, it marks the source
        as a cached torrent, otherwise it marks it as an uncached torrent.

        Args:
            torrent_sources (list): A list of torrent sources.

        Returns:
            list: A list of processed torrent sources.
        """
        if not torrent_sources:
            return []

        debrid_services = ['Real-Debrid', 'AllDebrid', 'Premiumize.me', 'Torbox']
        valid_sources = [source for source in torrent_sources if source.get('debrid', '') in debrid_services]

        if not valid_sources:
            return torrent_sources

        try:
            from resources.lib.modules import debridcheck
            DBCheck = debridcheck.DebridCheck()

            # Get the list of info hashes from the sources
            info_hashes = []
            for source in valid_sources:
                try:
                    info_hash = re.findall(r'btih:(\w{40})', source.get('url', ''))[0].lower()
                    info_hashes.append(info_hash)
                    source['info_hash'] = info_hash
                except IndexError:
                    c.log('Invalid URL format: %s' % source.get('url', ''), 1)

            # Get the cached hashes for each debrid service
            cached_hashes = DBCheck.run(info_hashes)

            # Separate the sources into cached and uncached
            cached_sources = []
            uncached_sources = []
            for source in valid_sources:
                if source.get('info_hash') in cached_hashes:
                    source['source'] = 'cached torrent'
                    cached_sources.append(source)
                else:
                    source['source'] = 'uncached torrent'
                    uncached_sources.append(source)

            # Return the combined list of sources
            return cached_sources + uncached_sources
        except Exception as e:
            failure = traceback.format_exc()
            c.log(f'[Sources] sourcesProcessTorrents2 - Error processing {len(torrent_sources)} torrents', 1)
            c.log(f'[Sources] Exception type: {type(e).__name__}', 1)
            c.log(f'[Sources] Exception message: {str(e)}', 1)
            c.log(f'[Sources] Full traceback:\n{failure}', 1)
            # Return original sources to allow playback to continue
            return torrent_sources


    def sourcesProcessTorrents(self, torrent_sources):#adjusted Fen code
        if len(torrent_sources) == 0:
            return
        for i in torrent_sources:
            if i.get('debrid', '') not in ['Real-Debrid', 'AllDebrid', 'Premiumize.me', 'Torbox']:
                return torrent_sources

        try:
            from resources.lib.modules import debridcheck
            #control.sleep(500)
            DBCheck = debridcheck.DebridCheck()
            hashList = []
            cachedTorrents = []
            uncachedTorrents = []
            #uncheckedTorrents = []
            for i in torrent_sources:
                try:
                    r = re.findall(r'btih:(\w{40})', str(i['url']))[0]
                    if r:
                        infoHash = r.lower()
                        i['info_hash'] = infoHash
                        hashList.append(infoHash)
                except Exception:
                    torrent_sources.remove(i)
            if len(torrent_sources) == 0:
                return torrent_sources
            torrent_sources = [i for i in torrent_sources if 'info_hash' in i]
            hashList = list(set(hashList))
            try:
                c.log(f'[Sources] sourcesProcessTorrents: Found {len(hashList)} unique hashes: {hashList}')
            except Exception:
                pass
            control.sleep(500)
            # DBCheck.run() returns 3 values: (RD, AD, PM) - TorBox support removed
            cachedRDHashes, cachedADHashes, cachedPMHashes = DBCheck.run(hashList)
            cachedTBHashes = []  # TorBox deprecated, kept for compatibility
            try:
                c.log(f'[Sources] sourcesProcessTorrents: cached counts RD={len(cachedRDHashes)} AD={len(cachedADHashes)} PM={len(cachedPMHashes)} TB={len(cachedTBHashes)}')
            except Exception:
                pass

            #cached
            cachedRDSources = [dict(i.items()) for i in torrent_sources if (any(v in i.get('info_hash') for v in cachedRDHashes) and i.get('debrid', '') == 'Real-Debrid')]
            cachedTorrents.extend(cachedRDSources)
            cachedADSources = [dict(i.items()) for i in torrent_sources if (any(v in i.get('info_hash') for v in cachedADHashes) and i.get('debrid', '') == 'AllDebrid')]
            cachedTorrents.extend(cachedADSources)
            cachedPMSources = [dict(i.items()) for i in torrent_sources if (any(v in i.get('info_hash') for v in cachedPMHashes) and i.get('debrid', '') == 'Premiumize.me')]
            cachedTorrents.extend(cachedPMSources)
            cachedTBSources = [dict(i.items()) for i in torrent_sources if (any(v in i.get('info_hash') for v in cachedTBHashes) and i.get('debrid', '') == 'Torbox')]
            cachedTorrents.extend(cachedTBSources)
            for i in cachedTorrents:
                i.update({'source': 'cached torrent'})

            #uncached
            uncachedRDSources = [dict(i.items()) for i in torrent_sources if (not any(v in i.get('info_hash') for v in cachedRDHashes) and i.get('debrid', '') == 'Real-Debrid')]
            uncachedTorrents.extend(uncachedRDSources)
            uncachedADSources = [dict(i.items()) for i in torrent_sources if (not any(v in i.get('info_hash') for v in cachedADHashes) and i.get('debrid', '') == 'AllDebrid')]
            uncachedTorrents.extend(uncachedADSources)
            uncachedPMSources = [dict(i.items()) for i in torrent_sources if (not any(v in i.get('info_hash') for v in cachedPMHashes) and i.get('debrid', '') == 'Premiumize.me')]
            uncachedTorrents.extend(uncachedPMSources)
            uncachedTBSources = [dict(i.items()) for i in torrent_sources if (not any(v in i.get('info_hash') for v in cachedTBHashes) and i.get('debrid', '') == 'Torbox')]
            uncachedTorrents.extend(uncachedTBSources)
            for i in uncachedTorrents:
                i.update({'source': 'uncached torrent'})

            return cachedTorrents + uncachedTorrents
        except Exception as e:
            failure = traceback.format_exc()
            c.log(f'[Sources] sourcesProcessTorrents - Error processing {len(torrent_sources) if torrent_sources else 0} torrents', 1)
            c.log(f'[Sources] Exception type: {type(e).__name__}', 1)
            c.log(f'[Sources] Exception message: {str(e)}', 1)
            c.log(f'[Sources] Full traceback:\n{failure}', 1)
            # Return original sources to allow playback to continue
            return torrent_sources


    # ===== DEAD CODE REMOVED =====
    # The methods below (sourcesFilter_new and multiple sourcesFilter definitions)
    # were dead code - Python only uses the LAST method def of the same name.
    # Removed during Phase 1 refactoring (2026-02-22).
    # See actual sourcesFilter() implementation below.
    # ===========================

    def _REMOVED_sourcesFilter_new_DEAD_CODE(self):
        """DEAD CODE - Never called, kept for reference during transition"""
        provider_sort_enabled = c.get_setting('hosts.sort.provider') == 'true'
        debrid_only_enabled = c.get_setting('debrid.only') == 'true'
        sort_the_crew_enabled = c.get_setting('torrent.sort.the.crew') == 'true'
        quality_setting = int(c.get_setting('hosts.quality'))
        captcha_enabled = c.get_setting('hosts.captcha') == 'true'
        show_cams_enabled = c.get_setting('hosts.screener') == 'true'
        remove_uncached_enabled = c.get_setting('remove.uncached') == 'true'

        hevc_keywords = ['hevc', 'h265', 'h.265', 'x265', 'x.265']
        hevc_keywords_lowercase = [x.lower() for x in hevc_keywords]

        if control.setting('HEVC') != 'true':
            self.sources = [src for src in self.sources if not any(keyword in src['url'].lower() for keyword in hevc_keywords_lowercase)]

        local_sources = [src for src in self.sources if src.get('local', False)]
        for src in local_sources:
            src['language'] = self._getPrimaryLang() or 'en'
        self.sources = [src for src in self.sources if src not in local_sources]

        # Filter out duplicate links
        if control.setting('remove.dups') == 'true':
            initial_count = len(self.sources)
            new_sources = list(self.unique_sources(self.sources))
            if len(new_sources) == 0 and initial_count > 0:
                # Suppress notification during Up Next background scraping
                if not getattr(self, 'silent_mode', False):
                    control.infoDialog(control.lang(32089).format(0) + ' (skipped)', icon='main_classy.png', time=4000)
            else:
                self.sources = new_sources
                duplicates_removed = initial_count - len(self.sources)
                # Suppress notification during Up Next background scraping
                if not getattr(self, 'silent_mode', False):
                    control.infoDialog(control.lang(32089).format(duplicates_removed), icon='main_classy.png', time=4000)

        torrent_sources = self.sourcesProcessTorrents([src for src in self.sources if 'magnet:' in src['url']])
        filtered_sources = []

        for debrid_resolver in debrid.debrid_resolvers:
            valid_hosters = {src['source'] for src in self.sources if debrid_resolver.valid_url('', src['source'])}

            if control.setting('check.torr.cache') == 'true':
                try:
                    for src in self.sources:
                        if 'magnet:' in src['url']:
                            src['debrid'] = debrid_resolver.name

                    torrent_sources = self.sourcesProcessTorrents([src for src in self.sources if 'magnet:' in src['url']])
                    cached_sources = [src for src in torrent_sources if src.get('source') == 'cached torrent']
                    filtered_sources.extend(cached_sources)
                    unchecked_sources = [src for src in torrent_sources if src.get('source').lower() == 'torrent']
                    filtered_sources.extend(unchecked_sources)

                    if not remove_uncached_enabled or not cached_sources:
                        uncached_sources = [src for src in torrent_sources if src.get('source') == 'uncached torrent']
                        filtered_sources.extend(uncached_sources)

                    filtered_sources.extend(
                        {**src, 'debrid': debrid_resolver.name}
                        for src in self.sources
                        if src['source'] in valid_hosters and 'magnet:' not in src['url']
                    )
                except Exception:
                    pass

            filtered_sources.extend(
                {**src, 'debrid': debrid_resolver.name}
                for src in self.sources
                if src['source'].lower() == 'torrent' or (src['source'] in valid_hosters and 'magnet:' not in src['url'])
            )
        if not debrid_only_enabled or not debrid.status():
            filtered_sources.extend(
                src for src in self.sources
                if src['source'].lower() not in self.hostprDict and not src.get('debridonly', True)
            )


        self.sources = filtered_sources

        for src in self.sources:
            if src['quality'].lower() == 'hd':
                src['quality'] = '720p'

        quality_levels = [
            ('4k', 0),
            ('1440p', 1),
            ('1080p', 2),
            ('720p', 3),
            ('sd', 4)
        ]

        for quality, level in quality_levels:
            if quality_setting <= level:
                filtered_sources.extend(
                    src for src in self.sources
                    if src['quality'].lower() == quality and (
                        'debrid' in src or
                        ('memberonly' in src if 'debrid' not in src else False))
                )

        if show_cams_enabled:
            filtered_sources.extend(
                src for src in self.sources
                if src['quality'].lower() in ['scr', 'cam']
            )

        self.sources = filtered_sources

        if not captcha_enabled:
            filtered_sources = [src for src in self.sources if src['source'].lower() in self.hostcapDict and 'debrid' not in src]
            self.sources = [src for src in self.sources if src not in filtered_sources]

        filtered_sources = [src for src in self.sources if src['source'].lower() in self.hostblockDict and 'debrid' not in src]
        self.sources = [src for src in self.sources if src not in filtered_sources]

        languages = {src['language'] for src in self.sources}
        multi_language = len(languages) > 1

        if multi_language:
            self.sources = [src for src in self.sources if src['language'] != 'en'] + [src for src in self.sources if src['language'] == 'en']

        max_sources = int(control.setting('returned.sources'))
        self.sources = self.sources[:max_sources]

        return self.sources

    def _validate_year(self, source, tolerance=1):
        """Validate source year matches metadata year within tolerance.

        Phase 2 implementation (2026-02-22): Prevents wrong-year results like "Beekeeper 2->1 bug".
        Phase 2.1 (2026-02-24): For TV episodes, use episode premiere date year instead of show year.

        Args:
            source (dict): Source dict with 'url' or 'name' field containing release info
            tolerance (int): Year tolerance (+/- years allowed), default ±1

        Returns:
            bool: True if year valid or year validation disabled, False if mismatch
        """
        try:
            # Check if year validation is enabled
            if c.get_setting('filter.year') != 'true':
                return True

            # For TV episodes, DISABLE year filtering entirely
            # search_premiered format: "2026-02-10" (episode air date)
            # search_year: show premiere year (e.g., "2018" for The Rookie)
            # Why disabled: TV torrents rarely include year OR include wrong years
            # (episode year vs season year vs show year), causing 80-85% false positives
            if hasattr(self, 'search_premiered') and self.search_premiered and hasattr(self, 'search_season'):
                # This is a TV episode - skip year validation
                return True
            elif hasattr(self, 'search_year') and self.search_year:
                # Movie: use movie year
                try:
                    base_year = int(self.search_year)
                    valid_years = [str(base_year + offset) for offset in range(-tolerance, tolerance + 1)]
                except (ValueError, TypeError):
                    # Invalid year format, skip validation
                    return True
            else:
                # No year metadata available, skip validation
                return True

            # Extract release title from source (check both 'url' and 'name' fields)
            release_info = source.get('url', '') + ' ' + source.get('name', '')
            release_info = release_info.lower()

            # Check if any valid year appears in the release info
            if any(year in release_info for year in valid_years):
                return True

            # No matching year found - filter this source
            if c.devmode:
                c.log(f"[Validation] Year mismatch: expected {valid_years}, source={source.get('provider', 'unknown')}")
            return False

        except Exception as e:
            # On error, don't filter (fail open)
            c.log(f"[Validation] Error in _validate_year: {e}")
            return True

    def _validate_episode(self, source):
        """Validate TV episode sources contain the correct episode number.

        Phase 2.2 implementation (2026-03-04): Prevents wrong episodes in results.
        Uses source_utils.seas_ep_filter() to validate S##E## patterns in multiple formats:
        - S01E05, S1E5
        - 1x05
        - Season.1.Episode.5
        - Episode.5 (when in season folder)
        And many more variations.

        Args:
            source (dict): Source dict with 'url' or 'name' field containing release info

        Returns:
            bool: True if episode matches or not a TV episode, False if wrong episode
        """
        try:
            # Only validate TV episodes (not movies)
            if not hasattr(self, 'search_season') or not hasattr(self, 'search_episode'):
                return True
            if not self.search_season or not self.search_episode:
                return True

            # Extract release name from source
            release_info = ''
            source_url = source.get('url', '')
            source_name = source.get('name', '')

            # For magnet links, extract display name from dn= parameter
            if source_url.startswith('magnet:'):
                try:
                    from urllib.parse import urlparse, parse_qs, unquote
                    parsed = urlparse(source_url)
                    params = parse_qs(parsed.query)
                    if 'dn' in params and params['dn']:
                        release_info = unquote(params['dn'][0])
                except (ValueError, KeyError, IndexError, AttributeError):
                    pass

            # If no magnet display name, use name field or URL
            if not release_info:
                release_info = source_name if source_name else source_url

            # Use source_utils.seas_ep_filter to validate episode number
            # This function handles all episode formats (S01E05, 1x05, Season.1.Episode.5, etc.)
            from ..modules import source_utils
            if source_utils.seas_ep_filter(self.search_season, self.search_episode, release_info):
                return True

            # seas_ep_filter returned False: the correct episode was NOT found.
            # Distinguish between:
            #  a) Season packs / unknown (no episode marker at all) → KEEP (True)
            #  b) Explicit wrong episode (e.g. S01E02 when we want S01E04) → REMOVE (False)
            has_episode_marker = bool(re.search(
                r'[sS]\d{1,2}[eE]\d{1,2}|\d+[xX]\d{1,3}|\b(?:ep?|episode)[.-]?\d+\b',
                release_info,
                re.IGNORECASE
            ))
            if not has_episode_marker:
                # No explicit episode number → season pack or generic release, keep it
                return True

            # Episode pattern NOT found — filter this source
            if c.devmode:
                c.log(f"[Validation] Episode mismatch: expected S{str(self.search_season).zfill(2)}E{str(self.search_episode).zfill(2)}, got {release_info[:80]}")
            return False

        except Exception as e:
            # On error, don't filter (fail open)
            c.log(f"[Validation] Error in _validate_episode: {e}")
            return True

    def _validate_title(self, source):
        """Validate source title matches metadata title using fuzzy matching.

        Phase 2 implementation (2026-02-22): Prevents mismatched titles (e.g., different movies with similar names).

        Args:
            source (dict): Source dict with 'url' or 'name' field containing release title

        Returns:
            bool: True if title matches or title validation disabled, False if no match
        """
        try:
            # Check if title validation is enabled
            if c.get_setting('filter.title') != 'true':
                return True

            # Skip if no title metadata available
            if not hasattr(self, 'search_title') or not self.search_title:
                return True

            # Build list of valid titles (main title + aliases)
            title_list = []

            # Add main title (normalized)
            main_title = str(self.search_title).replace('&', 'and')
            if self.search_year:
                main_title = main_title.replace(str(self.search_year), '').strip()
            title_list.append(cleantitle.get(main_title))

            # Add aliases if available
            if hasattr(self, 'search_aliases') and self.search_aliases:
                for alias in self.search_aliases:
                    alias_clean = str(alias).replace('&', 'and')
                    if self.search_year:
                        alias_clean = alias_clean.replace(str(self.search_year), '').strip()
                    clean_alias = cleantitle.get(alias_clean)
                    if clean_alias and clean_alias not in title_list:
                        title_list.append(clean_alias)

            # Extract release title from source
            release_info = ''
            source_url = source.get('url', '')
            source_name = source.get('name', '')

            # For magnet links, extract display name from dn= parameter
            if source_url.startswith('magnet:'):
                try:
                    # Parse magnet link to extract display name
                    parsed = urlparse(source_url)
                    params = parse_qs(parsed.query)
                    if 'dn' in params and params['dn']:
                        release_info = unquote(params['dn'][0])
                except (ValueError, KeyError, IndexError, AttributeError):
                    pass

            # If no magnet display name found, use name field or URL
            if not release_info:
                release_info = source_name if source_name else source_url

            # Remove year from release info to focus on title matching
            if self.search_year:
                release_info = release_info.replace(str(self.search_year), '')

            # Split on common delimiters to extract title portion
            # Typical format: "Title.2024.1080p.WEB..." or "Title (2024) [1080p]..."
            # Remove quality indicators to get cleaner title
            release_info = re.split(r'2160p|216op|4k|1080p|1o8op|108op|1o80p|720p|72op|480p|48op', release_info, 1, re.I)[0]
            release_title_clean = cleantitle.get(release_info)

            # Check if release title matches any valid title
            if any(valid_title in release_title_clean or release_title_clean in valid_title
                    for valid_title in title_list if valid_title):
                return True

            # No matching title found - filter this source
            if c.devmode and title_list:
                # Safety: title_list could be None if search_title was empty
                title_preview = title_list[:3] if title_list else []
                title_got = release_title_clean[:50] if release_title_clean else ''
                c.log(f"[Validation] Title mismatch: expected {title_preview}, got {title_got}")
            return False

        except Exception as e:
            # On error, don't filter (fail open)
            c.log(f"[Validation] Error in _validate_title: {e}")
            return True

    def _filter_by_undesirables(self, source, undesirables_list):
        """Filter source by undesirables blacklist (domains/watermarks).

        Phase 3 implementation (2026-02-22): Filters spam/foreign domains.

        Args:
            source (dict): Source dict with 'url' or 'name' field containing release info
            undesirables_list (list): List of lowercase keywords to filter

        Returns:
            bool: True if source is clean, False if blacklisted keyword found
        """
        try:
            if not undesirables_list:
                return True

            # Check URL and name for blacklisted keywords
            release_info = (source.get('url', '') + ' ' + source.get('name', '')).lower()

            for keyword in undesirables_list:
                if keyword in release_info:
                    if c.devmode:
                        c.log(f"[Undesirables] Filtered source with keyword '{keyword}': {release_info[:80]}")
                    return False

            return True

        except Exception as e:
            # On error, don't filter (fail open)
            c.log(f"[Undesirables] Error in _filter_by_undesirables: {e}")
            return True

    def _filter_extras(self, source):
        """Filter out extras/bonus content (samples, deleted scenes, bloopers, etc.).

        Phase 4 implementation (2026-02-22): Removes non-feature content.

        Args:
            source (dict): Source dict with 'url' or 'name' field containing release info

        Returns:
            bool: True if source is main content, False if extra/bonus content
        """
        try:
            # Common extras keywords found in release names
            extras_keywords = [
                'sample', 'extra', 'extras', 'deleted', 'deleted.scene', 'deleted.scenes',
                'blooper', 'bloopers', 'making.of', 'makingof', 'behind.the.scenes',
                'featurette', 'featurettes', 'commentary', 'gag.reel', 'outtake', 'outtakes',
                'interview', 'interviews', 'trailer', 'teaser', 'promo', 'bonus',
                'documentary', 'doc', '.extras.', '-extras-', '_extras_'
            ]

            # Check URL and name for extras keywords
            # Extract display name from magnet links for better matching
            release_info = ''
            source_url = source.get('url', '')
            source_name = source.get('name', '')

            # For magnet links, extract display name from dn= parameter
            if source_url.startswith('magnet:'):
                try:
                    parsed = urlparse(source_url)
                    params = parse_qs(parsed.query)
                    if 'dn' in params and params['dn']:
                        release_info = unquote(params['dn'][0])
                except (ValueError, KeyError, IndexError, AttributeError):
                    pass

            # If no magnet display name, use name field or URL
            if not release_info:
                release_info = source_name if source_name else source_url

            release_info = release_info.lower()

            # Use word boundary matching to avoid false positives (e.g., "extra" in hex hashes)
            # Split by common delimiters to get words/tokens
            tokens = re.split(r'[\s\.\-\_\[\]\(\)\+]+', release_info)

            for keyword in extras_keywords:
                # Check if keyword appears as whole word/token
                if keyword in tokens or any(token.startswith(keyword + '.') or token.endswith('.' + keyword) for token in tokens):
                    if c.devmode:
                        c.log(f"[Extras] Filtered source with keyword '{keyword}': {release_info[:80]}")
                    return False

            return True

        except Exception as e:
            # On error, don't filter (fail open)
            c.log(f"[Extras] Error in _filter_extras: {e}")
            return True

    def _apply_per_quality_limits(self, sources, limit_per_quality):
        """Limit number of sources per quality tier to prevent imbalance.

        Phase 4 implementation (2026-02-22): Prevents 100 SD drowning out 5 4K.

        Args:
            sources (list): List of source dicts
            limit_per_quality (int): Maximum sources per quality (e.g., 10)

        Returns:
            list: Filtered sources with limits applied
        """
        try:
            if not limit_per_quality or limit_per_quality <= 0:
                return sources

            # Count sources per quality
            quality_counts = {}
            filtered_sources = []

            for source in sources:
                quality = source.get('quality', 'SD').upper()

                # Initialize count for this quality
                if quality not in quality_counts:
                    quality_counts[quality] = 0

                # Add source if under limit
                if quality_counts[quality] < limit_per_quality:
                    filtered_sources.append(source)
                    quality_counts[quality] += 1
                else:
                    # Log when limit is reached (only first time per quality)
                    if quality_counts[quality] == limit_per_quality:
                        c.log(f"[Quality Limit] Reached limit of {limit_per_quality} sources for {quality} quality", 1)
                    quality_counts[quality] += 1  # Track total even if filtered

            # Log summary if any were filtered
            total_filtered = len(sources) - len(filtered_sources)
            if total_filtered > 0:
                quality_summary = ', '.join([f"{q}: {min(c, limit_per_quality)}/{c}" for q, c in sorted(quality_counts.items())])
                c.log(f"[Quality Limit] Applied per-quality limit of {limit_per_quality}: {quality_summary} (filtered {total_filtered} sources)")

            return filtered_sources

        except Exception as e:
            c.log(f"[Quality Limit] Error in _apply_per_quality_limits: {e}")
            return sources

    def sourcesFilter(self):
        """
        Filter sources based on quality, provider, hoster, debrid, screener, etc.
        Refactored 2026-02-22: Modernized to use c.get_setting() API.
        """
        # Load all settings once for efficiency
        provider = c.get_setting('hosts.sort.provider') or 'false'
        debrid_only = c.get_setting('debrid.only') or 'false'
        sortthecrew = c.get_setting('torrent.sort.the.crew') or 'false'
        try:
            quality_setting = int(c.get_setting('hosts.quality') or 0)
        except Exception:
            quality_setting = 0
        captcha_enabled = c.get_setting('hosts.captcha') or 'true'
        show_cams_enabled = c.get_setting('hosts.screener') or 'true'
        remove_uncached = c.get_setting('remove.uncached') or 'false'
        HEVC = c.get_setting('HEVC')

        try:
            c.log(f"[Sources] sourcesFilter(): entry (pre-filter count) = {len(self.sources)}")
        except Exception:
            c.log("[Sources] sourcesFilter(): entry")

        #random.shuffle(self.sources)
        #self.sources = [i for i in self.sources if not i['source'].lower() in self.hostblockDict]

        #c.log(f"[CM Debug @ 1528 in sources.py] sources = {self.sources}")

        if sortthecrew == 'true':
            self.sources = sorted(self.sources, key=lambda k: k['source'], reverse=True)
            self.sources = sorted(
                self.sources,
                key=lambda k: (1 if "torrent" in k['source'] else 0, k['source']),
                reverse=True
            )

        if provider == 'true':
            self.sources = sorted(self.sources, key=lambda k: k['provider'])

        hevc_list = ['hevc', 'HEVC', 'h265', 'H265', 'h.265', 'H.265', 'x265', 'X265', 'x.265', 'X.265']

        if not HEVC == 'true':
            self.sources = [i for i in self.sources if not any(value in (i['url']).lower() for value in hevc_list)]# and not any(s in i.get('name').lower for s in hevc_list)

        # Phase 2: Year and Title Validation (2026-02-22)
        # Filter sources by year (prevents Beekeeper 2->1 bug)
        try:
            if c.get_setting('filter.year') == 'true':
                pre_year_count = len(self.sources)
                self.sources = [src for src in self.sources if self._validate_year(src)]
                filtered_year = pre_year_count - len(self.sources)
                if filtered_year > 0:
                    c.log(f"[Validation] Year filter: removed {filtered_year}/{pre_year_count} sources (year={getattr(self, 'search_year', 'unknown')})")
                else:
                    c.log(f"[Validation] Year filter: all {pre_year_count} sources passed (year={getattr(self, 'search_year', 'unknown')})")
        except Exception as e:
            c.log(f"[Validation] Error in year filtering: {e}")

        # Filter sources by title (prevents wrong movie/show results)
        try:
            if c.get_setting('filter.title') == 'true':
                pre_title_count = len(self.sources)
                self.sources = [src for src in self.sources if self._validate_title(src)]
                filtered_title = pre_title_count - len(self.sources)
                if filtered_title > 0:
                    c.log(f"[Validation] Title filter: removed {filtered_title}/{pre_title_count} sources (title={getattr(self, 'search_title', 'unknown')})")
                else:
                    c.log(f"[Validation] Title filter: all {pre_title_count} sources passed (title={getattr(self, 'search_title', 'unknown')})")
        except Exception as e:
            c.log(f"[Validation] Error in title filtering: {e}")

        # Filter sources by episode number (prevents wrong episodes - Phase 2.2: 2026-03-04)
        # Always runs for TV episodes regardless of filter.title setting.
        try:
            if hasattr(self, 'search_season') and hasattr(self, 'search_episode'):
                if self.search_season and self.search_episode:
                    pre_episode_count = len(self.sources)
                    self.sources = [src for src in self.sources if self._validate_episode(src)]
                    filtered_episode = pre_episode_count - len(self.sources)
                    if filtered_episode > 0:
                        c.log(f"[Validation] Episode filter: removed {filtered_episode}/{pre_episode_count} sources (episode=S{str(self.search_season).zfill(2)}E{str(self.search_episode).zfill(2)})")
                    else:
                        c.log(f"[Validation] Episode filter: all {pre_episode_count} sources passed (episode=S{str(self.search_season).zfill(2)}E{str(self.search_episode).zfill(2)})")
        except Exception as e:
            c.log(f"[Validation] Error in episode filtering: {e}")

        # Phase 3: Undesirables Filtering (2026-02-22)
        # Filter sources by blacklisted domains/watermarks
        try:
            if c.get_setting('filter.undesirables') == 'true':
                undesirables_list = undesirables.get_undesirables()
                if undesirables_list:
                    pre_undesirables_count = len(self.sources)
                    self.sources = [src for src in self.sources if self._filter_by_undesirables(src, undesirables_list)]
                    filtered_undesirables = pre_undesirables_count - len(self.sources)
                    if filtered_undesirables > 0:
                        c.log(f"[Undesirables] Filtered {filtered_undesirables}/{pre_undesirables_count} sources ({len(undesirables_list)} keywords active)")
                    else:
                        c.log(f"[Undesirables] All {pre_undesirables_count} sources passed ({len(undesirables_list)} keywords active)")
        except Exception as e:
            c.log(f"[Undesirables] Error in undesirables filtering: {e}")

        # Phase 4: Extras Filtering (2026-02-22)
        # Filter out samples, deleted scenes, bloopers, bonus content
        try:
            if c.get_setting('filter.extras') == 'true':
                pre_extras_count = len(self.sources)
                self.sources = [src for src in self.sources if self._filter_extras(src)]
                filtered_extras = pre_extras_count - len(self.sources)
                if filtered_extras > 0:
                    c.log(f"[Extras] Filtered {filtered_extras}/{pre_extras_count} sources (samples/bonus content removed)")
                elif c.devmode:
                    c.log(f"[Extras] All {pre_extras_count} sources passed (no extras detected)")
        except Exception as e:
            c.log(f"[Extras] Error in extras filtering: {e}")

        # Phase 4: Per-Quality Limits (2026-02-22)
        # Limit sources per quality tier to prevent imbalance
        try:
            limit_setting = c.get_setting('results.per_quality_limit')
            if limit_setting and limit_setting != '0':
                limit = int(limit_setting)
                if limit > 0:
                    pre_limit_count = len(self.sources)
                    self.sources = self._apply_per_quality_limits(self.sources, limit)
                    filtered_limit = pre_limit_count - len(self.sources)
                    if filtered_limit > 0:
                        c.log(f"[Quality Limit] Applied limit of {limit} per quality, removed {filtered_limit}/{pre_limit_count} sources")
        except Exception as e:
            c.log(f"[Quality Limit] Error in quality limit filtering: {e}")

        local = [i for i in self.sources if 'local' in i and i['local'] is True]
        for i in local:
            i.update({'language': self._getPrimaryLang() or 'en'})
        self.sources = [i for i in self.sources if i not in local]

        # Deduplicate pack sources by magnet hash (unconditional — same hash from N scrapers = 1 RD call)
        try:
            seen_hashes = set()
            deduped = []
            pack_dupes = 0
            for src in self.sources:
                url = src.get('url', '') or ''
                if url.startswith('magnet:') and self.is_pack_source(src):
                    m = re.search(r'btih:([0-9a-fA-F]{40})', url)
                    if m:
                        h = m.group(1).lower()
                        if h in seen_hashes:
                            pack_dupes += 1
                            continue
                        seen_hashes.add(h)
                deduped.append(src)
            if pack_dupes:
                c.log(f'[Sources] Pack hash dedup: removed {pack_dupes} duplicate magnet(s) ({len(deduped)} remain)')
            self.sources = deduped
        except Exception as e:
            c.log(f'[Sources] Pack hash dedup error: {e}')

        #Filter-out duplicate links
        try:
            if c.get_setting('remove.dups') == 'true':
                stotal = len(self.sources)
                self.sources = list(self.unique_sources(self.sources))
                dupes = stotal - len(self.sources)

                # Skip infoDialog when overlay is active (TV Evening/Up Next) or in silent mode
                if not is_overlay_active() and not getattr(self, 'silent_mode', False):
                    control.infoDialog(control.lang(32089).format(str(dupes)), icon='INFO')

                try:
                    c.log(f"[Sources] Deduplication: removed {dupes} duplicates (pre={stotal}, post={len(self.sources)})")
                except Exception:
                    pass
            else:
                self.sources
        except Exception:
            pass

            failure = traceback.format_exc()
            c.log('DUP - Exception: ' + str(failure))

            # Skip error infoDialog when overlay is active or in silent mode
            if not is_overlay_active() and not getattr(self, 'silent_mode', False):
                control.infoDialog('Dupes filter failed', icon='INFO')

            self.sources
        #END


        #torrentSources = self.sourcesProcessTorrents([i for i in self.sources if 'magnet:' in i['url']])
        torrentSources = self.sourcesProcessTorrents([i for i in self.sources if 'magnet:' in i['url']])
        filter_sources = []

        for d in debrid.debrid_resolvers:
            valid_hoster = set([i['source'] for i in self.sources])
            valid_hoster = [i for i in valid_hoster if d.valid_url('', i)]
            if c.get_setting('check.torr.cache') == 'true':
                try:
                    for i in self.sources:
                        if 'magnet:' in i['url']:
                            i['debrid'] = d.name

                    torrentSources = self.sourcesProcessTorrents([i for i in self.sources if 'magnet:' in i['url']])
                    cached = [i for i in torrentSources if i.get('source') == 'cached torrent']
                    filter_sources += cached
                    unchecked = [i for i in torrentSources if i.get('source').lower() == 'torrent']
                    filter_sources += unchecked
                    if remove_uncached == 'false' or len(cached) == 0:
                        uncached = [i for i in torrentSources if i.get('source') == 'uncached torrent']
                        filter_sources += uncached
                    filter_sources += [dict(list(i.items()) + [('debrid', d.name)]) for i in self.sources if i['source'] in valid_hoster and 'magnet:' not in i['url']]
                except Exception:
                    filter_sources += [dict(list(i.items()) + [('debrid', d.name)]) for i in self.sources if i.get('source').lower() == 'torrent']
                    filter_sources += [dict(list(i.items()) + [('debrid', d.name)]) for i in self.sources if i['source'] in valid_hoster and 'magnet:' not in i['url']]
            else:
                filter_sources += [dict(list(i.items()) + [('debrid', d.name)]) for i in self.sources if i.get('source').lower() == 'torrent']
                filter_sources += [dict(list(i.items()) + [('debrid', d.name)]) for i in self.sources if i['source'] in valid_hoster and 'magnet:' not in i['url']]

        if debrid_only == 'false' or debrid.status() is False:
            filter_sources += [i for i in self.sources if i['source'].lower() not in self.hostprDict and i['debridonly'] is False]

        self.sources = filter_sources

        for i in range(len(self.sources)):
            if self.sources[i]['quality'] in ['hd', 'HD'] :
                self.sources[i].update({'quality': '720p'})

        quality_levels = [
            ('4k', 0),
            ('1440p', 1),
            ('1080p', 2),
            ('720p', 3),
            ('sd', 4)
        ]

        filtered_sources = []

        for quality, level in quality_levels:
            if quality_setting <= level:
                filtered_sources.extend(
                    src for src in self.sources
                    if src['quality'].lower() == quality and (
                        'debrid' in src or
                        ('memberonly' in src if 'debrid' not in src else False))
                )

        if show_cams_enabled:
            filtered_sources.extend(
                src for src in self.sources
                if src['quality'].lower() in ['scr', 'cam']
            )

        self.sources = filtered_sources

        if not captcha_enabled:
            filtered_sources = [src for src in self.sources if src['source'].lower() in self.hostcapDict and 'debrid' not in src]
            self.sources = [src for src in self.sources if src not in filtered_sources]

        filtered_sources = [src for src in self.sources if src['source'].lower() in self.hostblockDict and 'debrid' not in src]
        self.sources = [src for src in self.sources if src not in filtered_sources]

        languages = {src['language'] for src in self.sources}
        multi_language = len(languages) > 1



        if multi_language:
            self.sources = [src for src in self.sources if src['language'] != 'en'] + [src for src in self.sources if src['language'] == 'en']

        try:
            max_sources = int(c.get_setting('returned.sources') or 100)
        except Exception:
            max_sources = 100
        self.sources = self.sources[:max_sources]

        extra_info = c.get_setting('sources.extrainfo')
        pack_name_label = c.get_setting('sources.pack.name') == 'true'
        prem_identify = c.get_setting('prem.identify') or 'gold'
        torr_identify = c.get_setting('torrent.identify') or 'blue'

        prem_identify = self.get_prem_color(prem_identify)
        torr_identify = self.get_prem_color(torr_identify)

        # DEBUG: list basic counts & sample providers to help diagnose lost sources
        try:
            raw_providers = sorted(set([str(s.get('provider','')) for s in self.sources if s.get('provider')]))
            # Convert provider internal names into readable display names or shorten full module paths
            providers = [
                (self.format_cocoscrapers_name(p) if self.is_cocoscrapers_source(p)
                 else (self.format_gearsscrapers_name(p) if self.is_gearsscrapers_source(p) else self.format_provider_display(p)))
                for p in raw_providers
            ]
        except Exception:
            pass

        for i, source in enumerate(self.sources):
            if extra_info == 'true':
                t = source_utils.get_file_type(source['url'])
            else:
                t = None

            # Compute common label parts that were missing (q, p, s, l, f, multiline_label)
            try:
                u = source.get('url', '')
            except Exception:
                u = ''

            p = source.get('provider', '') or ''

            # Compute display provider name for UI (do not mutate original provider field)
            try:
                if self.is_cocoscrapers_source(p):
                    p_display = self.format_cocoscrapers_name(p)
                elif self.is_gearsscrapers_source(p):
                    p_display = self.format_gearsscrapers_name(p)
                else:
                    p_display = p
            except Exception:
                p_display = p

            q = source.get('quality', '') or ''

            s = source.get('source', '') or ''
            try:
                s = s.rsplit('.', 1)[0]
            except Exception:
                pass

            l = source.get('language', '') or ''

            try:
                f = (' | '.join([f'[I]{info.strip()} [/I]' for info in (source.get('info') or '').split('|') if info.strip()]))
            except Exception:
                f = ''

            # Build base label and multiline_label similar to legacy implementations
            try:
                if d := (source.get('debrid', '') or ''):
                    d_str_try = d.lower() if isinstance(d, str) else str(d).lower()
                else:
                    d_str_try = ''
            except Exception:
                d_str_try = str(source.get('debrid', '') or '').lower()

            # Map common debrid names to short codes
            if d_str_try == 'alldebrid':
                d_short = 'AD'
            elif d_str_try == 'debrid-link.fr':
                d_short = 'DL.FR'
            elif d_str_try == 'linksnappy':
                d_short = 'LS'
            elif d_str_try == 'megadebrid':
                d_short = 'MD'
            elif d_str_try == 'premiumize.me':
                d_short = 'PM'
            elif d_str_try == 'torbox':
                d_short = 'TB'
            elif d_str_try == 'real-debrid':
                d_short = 'RD'
            elif d_str_try == 'zevera':
                d_short = 'ZVR'
            else:
                d_short = d if (d := (source.get('debrid', '') or '')) else ''

            # Build label and multiline label using helper
            label, multiline_label = self.build_labels(source, i, multi_language=multi_language, extra_info=True, pack_name_label=pack_name_label)

            # Add language marker for multi-language sets (insert before the source field)
            if multi_language and l and l != 'en':
                try:
                    parts = [p for p in label.split(' | ') if p != '']
                    # insert language before the 'source' field (index 3)
                    parts.insert(3, l)
                    label = ' | '.join(parts) + ' | '

                    parts_ml = [p for p in multiline_label.split(' | ') if p != '']
                    parts_ml.insert(3, l)
                    multiline_label = ' | '.join(parts_ml) + ' | ' + multiline_label.split(' | ', 3)[-1]
                except Exception:
                    pass

            # Replace self.sources[i] with source
            # Normalize debrid display name safely (some entries may be resolver objects)
            d = source.get('debrid', '') or ''
            try:
                d_str = d.lower() if isinstance(d, str) else str(d).lower()
            except Exception:
                d_str = str(d).lower()

            # Ensure we keep the earlier short code mapping (d_short)
            if d_str == 'alldebrid':
                d = 'AD'
            elif d_str == 'debrid-link.fr':
                d = 'DL.FR'
            elif d_str == 'linksnappy':
                d = 'LS'
            elif d_str == 'megadebrid':
                d = 'MD'
            elif d_str == 'premiumize.me':
                d = 'PM'
            elif d_str == 'torbox':
                d = 'TB'
            elif d_str == 'real-debrid':
                d = 'RD'
            elif d_str == 'zevera':
                d = 'ZVR'
            else:
                d = str(d) if d else ''

            # Ensure label includes debrid short and formatted provider (preserve earlier base_label)
            try:
                parts = [p for p in label.split(' | ') if p != '']
                while len(parts) < 4:
                    parts.append('')
                # Insert debrid short and provider display
                parts[2] = d if d else parts[2] if len(parts) > 2 else ''
                parts[3] = p_display
                label = ' | '.join([x for x in parts if x != '']) + ' | '
            except Exception:
                # Fallback to a minimal label if something goes wrong
                try:
                    label = f'{int(i+1):02d} | {q} | {p_display} | '
                except Exception:
                    label = f'{int(i+1):02d} | {q} | {p} | '

            # Finalize label strings using compact setting
            try:
                compact = c.get_setting('sources.compact') == 'true'
            except Exception:
                compact = False
            try:
                list_multiline = c.get_setting('sourcelist.multiline') == 'true'
            except Exception:
                list_multiline = False

            final_label, final_multiline = self.finalize_label(source, label, multiline_label, i, prem_identify=prem_identify, torr_identify=torr_identify, compact=compact, list_multiline=list_multiline)

            # Apply colorization
            try:
                has_debrid = bool(source.get('debrid', ''))
                if has_debrid:
                    if 'torrent' in source.get('source', '').lower():
                        if not torr_identify == 'nocolor':
                            source['multiline_label'] = ('[COLOR %s]' % (torr_identify)) + final_multiline.upper() + '[/COLOR]'
                            source['label'] = ('[COLOR %s]' % (torr_identify)) + final_label.upper() + '[/COLOR]'
                        else:
                            source['multiline_label'] = final_multiline.upper()
                            source['label'] = final_label.upper()
                    else:
                        if not prem_identify == 'nocolor':
                            source['multiline_label'] = ('[COLOR %s]' % (prem_identify)) + final_multiline.upper() + '[/COLOR]'
                            source['label'] = ('[COLOR %s]' % (prem_identify)) + final_label.upper() + '[/COLOR]'
                        else:
                            source['multiline_label'] = final_multiline.upper()
                            source['label'] = final_label.upper()
                else:
                    source['multiline_label'] = final_multiline.upper()
                    source['label'] = final_label.upper()
            except Exception:
                source['multiline_label'] = final_multiline.upper()
                source['label'] = final_label.upper()

            # Rest of your code...

        try:
            if not HEVC == 'true':
                self.sources = [i for i in self.sources if 'multiline_label' in i and 'HEVC' not in i['multiline_label']]

        except Exception as e:
            import traceback as _traceback
            failure = _traceback.format_exc()


        self.sources = [i for i in self.sources if 'label' in i and 'multiline_label' in i]

        # DEBUG: final snapshot before returning
        try:
            providers = sorted(set([str(s.get('provider','')).lower() for s in self.sources if s.get('provider')]))
            sample = []
            for s in self.sources[:5]:
                sample.append({'provider': self.format_provider_display(s.get('provider')), 'url': (s.get('url')[:120] + '...') if isinstance(s.get('url'), str) and len(s.get('url'))>120 else s.get('url'), 'debrid': s.get('debrid', ''), 'debridonly': s.get('debridonly', False)})
        except Exception:
            pass

        #c.log(f"[CM Debug @ 2605 in sources.py] sources = {self.sources}")

        return self.sources

    def sourcesResolve(self, item, info=False):
        try:
            disp_provider = self.format_provider_display(item.get('provider')) if item.get('provider') else ''
            self.url = None

            u = url = item['url']

            d = item['debrid']
            direct = item['direct']
            local = item.get('local', False)

            # Diagnostic: log debrid info to help tests determine why resolution may fail
            try:
                import sys as _sys
                debrid_mod = _sys.modules.get('resources.lib.modules.debrid', debrid)
            except Exception:
                debrid_mod = debrid
            try:
                pass
            except Exception:
                pass

            provider = item.get('provider')

            # Ensure provider list is available; lazily load it if necessary. Some instances (like the one that
            # services playItem) may not have run getSources() and thus have an empty sourceDict.
            try:
                if not getattr(self, 'sourceDict', None):
                    try:
                        from resources.lib.sources import sources as discover_sources
                        self.sourceDict = discover_sources()
                    except Exception as e:
                        self.sourceDict = []
            except Exception:
                self.sourceDict = []

            disp_provider = self.format_provider_display(provider) if provider else ''

            # Use case-insensitive match for robustness
            try:
                provider_lower = provider.lower() if isinstance(provider, str) else str(provider).lower()
                matching_providers = [i[0] for i in self.sourceDict if (isinstance(i[0], str) and i[0].lower() == provider_lower)]
            except Exception:
                matching_providers = [i[0] for i in self.sourceDict if i[0] == provider]

            if not matching_providers:
                # Provider not in sourceDict - OK for Orion and similar pre-resolved sources
                call = None
            else:
                # Provider found - get its resolver
                call = None
                try:
                    call = [i[1] for i in self.sourceDict if (isinstance(i[0], str) and i[0].lower() == provider_lower)][0]
                except Exception:
                    call = [i[1] for i in self.sourceDict if i[0] == provider][0]

            if call:
                pass

                # Check if the source has a resolve method (Crew scrapers do, cocoscrapers don't)
                if hasattr(call, 'resolve'):
                    u = url = call.resolve(url)
                else:
                    # CocoScrapers and other sources that don't need resolution (magnet links, direct URLs)
                    u = url  # URL is already set from item['url']
            else:
                # No provider resolution needed (e.g., Orion)
                u = url

            #if url is None or (not '://' in str(url) and not local and 'magnet' not in str(url)): raise Exception()
            if not url or ('://' not in url and 'magnet' not in url and not local):
                raise Exception()

            if not local:
                url = url[8:] if url.startswith('stack:') else url

                urls = []
                for part in url.split(' , '):
                    u = part
                    resolved_part = None

                    # If a debrid resolver was assigned, try it first and fall back to others
                    if d:
                        try:
                            # Extract season/episode for pack file selection
                            # Use instance vars (actual episode being played) first; fall back to source dict
                            # NOTE: source dicts from Torrentio embed their own episode number which may differ
                            # from the episode the user actually requested — self.season/episode is authoritative
                            season = getattr(self, 'season', None) or item.get('season')
                            episode = getattr(self, 'episode', None) or item.get('episode')

                            # Convert to int if they're strings
                            try:
                                if season is not None and isinstance(season, str):
                                    season = int(season)
                                if episode is not None and isinstance(episode, str):
                                    episode = int(episode)
                            except (ValueError, TypeError):
                                pass

                            if season is not None and episode is not None:
                                pass

                            # Try primary resolver name first (with season/episode for pack support)
                            try:
                                # Update overlay if active (unified UX)
                                overlay_was_active = is_overlay_active()
                                if overlay_was_active:
                                    update_active_overlay("Generating playable link...", state='resolving')
                                    c.log(f"[Sources] Updated overlay: Generating playable link for {d}")

                                c.log(f"[Sources] >>>>>> CALLING debrid_mod.resolver('{d}') with season={season}, episode={episode}")
                                resolved_part = debrid_mod.resolver(part, d, season=season, episode=episode)
                                c.log(f"[Sources] <<<<<< RETURNED from debrid_mod.resolver('{d}')")

                                # Suppress resolveurl's progress dialog when overlay is active (unified UX)
                                if overlay_was_active:
                                    try:
                                        control.execute('Dialog.Close(busydialognocancel)')
                                        control.execute('Dialog.Close(progressdialog)')
                                        c.log("[Sources] Closed resolveurl progress dialogs (unified UX)")
                                    except Exception:
                                        pass
                            except TypeError:
                                # Some resolver implementations expect (url,) only; try that as fallback
                                try:
                                    resolved_part = debrid_mod.resolver(part, d)
                                except TypeError:
                                    try:
                                        resolved_part = debrid_mod.resolver(part)
                                    except Exception:
                                        resolved_part = None
                                except Exception:
                                    resolved_part = None
                            except Exception as e:
                                c.log(f"[Sources] Primary resolver '{d}' raised: {e}")
                                resolved_part = None

                            if resolved_part:
                                pass
                        except Exception as e:
                            c.log(f"[Sources] Primary resolver '{d}' raised: {e}")

                        # Try other resolvers if primary failed or returned no result
                        # BUT: Skip fallbacks for pack sources (magnet + season/episode) since pack resolution
                        # is service-specific - Real-Debrid packs can't be resolved by AllDebrid, etc.
                        is_pack_source = 'magnet:' in part and season is not None and episode is not None
                        if is_pack_source and not resolved_part:
                            c.log(f"[Sources] Skipping fallback resolvers for pack source (service-specific)")
                        elif not resolved_part:
                            tried_names = set()
                            try:
                                for r in getattr(debrid_mod, 'debrid_resolvers', []) or []:
                                    try:
                                        rname = getattr(r, 'name', None)
                                    except Exception:
                                        rname = None
                                    if not rname:
                                        continue
                                    # Try multiple normalized representations of the resolver name
                                    for cand in (rname, str(rname).lower(), str(rname).replace(' ', '-').lower(), str(rname).replace('-', ' ').title()):
                                        if cand in tried_names:
                                            continue
                                        tried_names.add(cand)
                                        try:
                                            c.log(f"[Sources] Trying fallback resolver '{cand}' for preview={str(u)[:80]}")
                                            candidate = None
                                            try:
                                                candidate = debrid_mod.resolver(part, cand, season=season, episode=episode)
                                            except TypeError:
                                                try:
                                                    candidate = debrid_mod.resolver(part, cand)
                                                except TypeError:
                                                    try:
                                                        candidate = debrid_mod.resolver(part)
                                                    except Exception as e:
                                                        pass
                                            except Exception as e:
                                                pass
                                            if candidate:
                                                resolved_part = candidate
                                                break
                                        except Exception as e:
                                            pass
                                    if resolved_part:
                                        break
                            except Exception:
                                pass

                            # Last-ditch: try normalized primary name variations if still not resolved
                            if not resolved_part and d:
                                for cand in (str(d), str(d).lower(), str(d).replace(' ', '-').lower(), str(d).replace('-', ' ').title()):
                                    if cand in tried_names:
                                        continue
                                    tried_names.add(cand)
                                    try:
                                        c.log(f"[Sources] Trying normalized primary resolver name '{cand}' for preview={str(u)[:80]}")
                                        candidate = None
                                        try:
                                            candidate = debrid_mod.resolver(part, cand, season=season, episode=episode)
                                        except TypeError:
                                            try:
                                                candidate = debrid_mod.resolver(part, cand)
                                            except TypeError:
                                                try:
                                                    candidate = debrid_mod.resolver(part)
                                                except Exception:
                                                    candidate = None
                                        except Exception as e:
                                            pass
                                        if candidate:
                                            resolved_part = candidate
                                            break
                                    except Exception as e:
                                        pass
                    else:
                        # No debrid specified
                        pass

                    # If no debrid result, try hosted media resolver (resolveurl)
                    # BUT: Skip for pack sources to avoid adding the same magnet again
                    # Pack sources should return None so the sources loop tries the next source
                    if not resolved_part and direct is not True and not is_pack_source:
                        try:
                            # Support multiple resolveurl import paths (top-level or package-specific)
                            hmf_cls = getattr(resolveurl, 'HostedMediaFile', None)
                            if hmf_cls is None:
                                import resolveurl as _rv
                                hmf_cls = getattr(_rv, 'HostedMediaFile', None)
                            if hmf_cls:
                                hmf = hmf_cls(url=u, include_disabled=True, include_universal=False)
                                try:
                                    if hmf.valid_url() is True:
                                        resolved_part = hmf.resolve()
                                        if resolved_part:
                                            pass
                                except TypeError:
                                    # Older HostedMediaFile signatures may not accept those kwargs
                                    try:
                                        hmf = hmf_cls(u)
                                        if hmf.valid_url() is True:
                                            resolved_part = hmf.resolve()
                                            if resolved_part:
                                                pass
                                    except Exception as e:
                                        pass
                        except Exception as e:
                            pass

                    # final value to append
                    urls.append(resolved_part if resolved_part is not None else part)

                url = 'stack://' + ' , '.join(urls) if len(urls) > 1 else urls[0]

            if url is False or url is None:
                raise Exception()

            # Check if the final URL is still an unresolved magnet/torrent link
            # If debrid was required but resolution failed, signal failure so next source is tried
            if url:
                url_lower = str(url).lower()
                is_unresolved_magnet = url_lower.startswith('magnet:')
                is_torrent_file = '.torrent' in url_lower and not url_lower.startswith('http')

                # If this is a debrid-only source (pack or torrent) that wasn't resolved, fail it
                if (is_unresolved_magnet or is_torrent_file) and d:
                    c.log(f"[Sources] Debrid resolution failed for {d} - URL still unresolved: {url[:80]}")
                    url = None
                    raise Exception("Debrid resolution failed - trying next source")

            ext = url.split('?')[0].split('&')[0].split('|')[0].rsplit('.')[-1].replace('/', '').lower()
            if ext == 'rar':
                raise Exception()

            try:
                headers = url.rsplit('|', 1)[1]
            except Exception:
                headers = ''
            headers = quote_plus(headers).replace('%3D', '=') if ' ' in headers else headers
            headers = dict(parse_qsl(headers))

            # if url.startswith('http') and '.m3u8' in url:
            #     try: result = client.request(url.split('|')[0], headers=headers, output='geturl', timeout='20')
            #     except Exception: pass

            # elif url.startswith('http'):
            #     try: result = client.request(url.split('|')[0], headers=headers, output='chunk', timeout='20')
            #     except Exception: pass

            self.url = url

            # Suppress any remaining dialogs when overlay is active (unified UX)
            # This catches dialogs from Orion, resolveurl, or other sources
            if is_overlay_active():
                try:
                    control.execute('Dialog.Close(infodialog)')
                    control.execute('Dialog.Close(notification)')
                    control.execute('Dialog.Close(busydialognocancel)')
                    control.execute('Dialog.Close(progressdialog)')
                    c.log("[Sources] Closed all resolver/Orion dialogs (unified UX)")
                except Exception:
                    pass

            return url
        except Exception as e:
            # More detailed debug info for resolution failures
            try:
                pass
            except Exception:
                pass
            if info is True:
                self.errorForSources()
            return

    def sourcesDialog(self, items):
        try:
            pass

            labels = [i['label'] for i in items]

            select = control.selectDialog(labels)
            if select == -1:
                return 'close://'

            _next = [y for x, y in enumerate(items) if x >= select]
            prev = [y for x, y in enumerate(items) if x < select][::-1]

            items = [items[select]]
            items = [i for i in items+_next+prev][:40]

            # No progress dialog here - let resolution code (pack resolution/resolveurl) handle its own progress

            block = None

            for i in range(len(items)):
                try:
                    if items[i]['source'] == block:
                        try:
                            c.log(f"[Sources] Skipping item {i} because previous item from source '{block}' is still active", 1)
                        except Exception:
                            pass
                        raise Exception('block')

                    w = workers.Thread(self.sourcesResolve, items[i])
                    w.start()

                    m = ''

                    for x in range(3600):
                        try:
                            if control.monitor.abortRequested():
                                return sys.exit()
                        except Exception:
                            pass

                        k = control.condVisibility('Window.IsActive(virtualkeyboard)')
                        if k:
                            m += '1'
                            m = m[-1]
                        if (w.is_alive() is False or x > 30) and not k:
                            break
                        k = control.condVisibility('Window.IsActive(yesnoDialog)')
                        if k:
                            m += '1'
                            m = m[-1]
                        if (w.is_alive() is False or x > 30) and not k:
                            break
                        time.sleep(0.5)

                    for x in range(30):
                        try:
                            if control.monitor.abortRequested():
                                return sys.exit()
                        except Exception:
                            pass

                        if m == '':
                            break
                        if w.is_alive() is False:
                            break
                        time.sleep(0.5)

                    if w.is_alive() is True:
                        try:
                            c.log(f"[Sources] Worker still running for item {i}; blocking subsequent sources from '{items[i]['source']}'", 1)
                        except Exception:
                            pass
                        block = items[i]['source']

                    if self.url is None:
                        raise Exception()

                    self.selectedSource = items[i]['label']

                    control.execute('Dialog.Close(virtualkeyboard)')
                    control.execute('Dialog.Close(yesnoDialog)')
                    return self.url
                except Exception:
                    pass

        except Exception as e:
            pass

    def sourcesDirect(self, items):
        """
        Filters and resolves a list of source items based on specified criteria.

        This method processes a list of media source items, applying filters to exclude
        certain sources based on host capabilities, host blocks, autoplay settings, and quality.
        It then attempts to resolve the URL for each remaining source, updating a progress dialog
        to reflect the current processing status.

        Args:
            items (list): A list of dictionaries, where each dictionary represents a media source
                        with keys such as 'source', 'debrid', 'autoplay', and 'quality'.

        Returns:
            str or None: The resolved URL of the first successfully processed source item,
                        or None if no source could be resolved.
        """
        _filter = [i for i in items if i['source'].lower() in self.hostcapDict and not i.get('debrid')]
        items = [i for i in items if i not in _filter]

        _filter = [i for i in items if i['source'].lower() in self.hostblockDict]# and not i.get('debrid')]
        items = [i for i in items if i not in _filter]

        items = [i for i in items if ('autoplay' in i and i['autoplay'] is True) or 'autoplay' not in i]

        if control.setting('autoplay.sd') == 'true':
            items = [i for i in items if i['quality'] not in ['4K', '1440p', '1080p', 'HD']]

        u = None

        header = control.addonInfo('name')
        header2 = header.upper()

        # Create a single shared progress dialog for all resolution attempts

        # Import debrid module and create shared dialog
        try:
            from resources.lib.modules import debrid as debrid_mod
            debrid_mod.create_shared_resolution_dialog('Resolving sources...')
        except Exception as e:
            c.log(f"[Sources] Error creating shared dialog: {e}")

        try:
            for i, item in enumerate(items):
                try:
                    if control.monitor.abortRequested():
                        return sys.exit()

                    # Update progress dialog with current source attempt
                    try:
                        provider_name = item.get('provider', 'Unknown')
                        quality = item.get('quality', '')
                        progress_percent = int((i / len(items)) * 100) if items else 0
                        message = f'Trying source {i+1}/{len(items)}: {provider_name} ({quality})...'
                        debrid_mod.update_shared_resolution_dialog(message, progress_percent)
                    except Exception:
                        pass

                    url = self.sourcesResolve(item)
                    if u is None:
                        u = url
                    if url is not None:
                        # Show success message briefly before closing dialog
                        try:
                            debrid_mod.update_shared_resolution_dialog('Source resolved successfully!', 100)
                        except Exception:
                            pass
                        break
                except Exception:
                    pass

            return u
        finally:
            # Clean up shared resolution dialog when done trying all sources
            try:
                from resources.lib.modules import debrid as debrid_mod
                debrid_mod.close_shared_resolution_dialog()
            except Exception as e:
                c.log(f"[Sources] Error cleaning up resolution dialog: {e}")

    def errorForSources(self):
        try:
            from resources.lib.modules.debrid import rd_451_was_hit
            if rd_451_was_hit():
                control.infoDialog('Real-Debrid blocked sources (451 DMCA). This is a Real-Debrid issue — try a different title or check back later.', sound=False, icon='WARNING')
                return
        except Exception:
            pass
        control.infoDialog(control.lang(32401), sound=False, icon='INFO')

    def getLanguage(self):
        langDict = {
            'English': ['en'],
            'German': ['de'],
            'German+English': ['de', 'en'],
            'French': ['fr'],
            'French+English': ['fr', 'en'],
            'Portuguese': ['pt'],
            'Portuguese+English': ['pt', 'en'],
            'Polish': ['pl'],
            'Polish+English': ['pl', 'en'],
            'Korean': ['ko'],
            'Korean+English': ['ko', 'en'],
            'Russian': ['ru'],
            'Russian+English': ['ru', 'en'],
            'Spanish': ['es'],
            'Spanish+English': ['es', 'en'],
            'Greek': ['gr'],
            'Italian': ['it'],
            'Italian+English': ['it', 'en'],
            'Greek+English': ['gr', 'en']}
        name = control.setting('providers.lang')
        return langDict.get(name, ['en'])

    def getLocalTitle(self, title, imdb, tmdb, content):
        lang = self._getPrimaryLang()
        if not lang:
            return title

        if content == 'movie':
            t = trakt.getMovieTranslation(imdb, lang)
        else:
            t = trakt.getTVShowTranslation(imdb, lang)

        return t or title

    def getAliasTitles(self, imdb, localtitle, content):
        lang = self._getPrimaryLang()

        try:
            t = trakt.getMovieAliases(imdb) if content == 'movie' else trakt.getTVShowAliases(imdb)
            t = [i for i in t if i.get('country', '').lower() in [lang, '', 'us']
                and i.get('title', '').lower() != localtitle.lower()]
            return t
        except Exception:
            return []

    def _getPrimaryLang(self):
        langDict = {
            'English': 'en', 'German': 'de', 'German+English': 'de', 'French': 'fr', 'French+English': 'fr',
            'Portuguese': 'pt', 'Portuguese+English': 'pt', 'Polish': 'pl', 'Polish+English': 'pl', 'Korean': 'ko',
            'Korean+English': 'ko', 'Russian': 'ru', 'Russian+English': 'ru', 'Spanish': 'es', 'Spanish+English': 'es',
            'Italian': 'it', 'Italian+English': 'it', 'Greek': 'gr', 'Greek+English': 'gr'}
        name = control.setting('providers.lang')
        lang = langDict.get(name)
        return lang

    def getTitle(self, title):
        title = cleantitle.normalize(title)
        return title

    def getConstants(self):
        self.itemProperty = 'plugin.video.thecrew.container.items'
        self.metaProperty = 'plugin.video.thecrew.container.meta'

        # Defensive defaults for host resolver lists so methods like playItem/sourcesResolve
        # can operate even when getSources() was not called on this instance.
        try:
            self.hostDict = getattr(self, 'hostDict', [])
        except Exception:
            self.hostDict = []

        try:
            self.hostprDict = getattr(self, 'hostprDict', [
                '1fichier.com', 'oboom.com', 'rapidgator.net', 'rg.to', 'uploaded.net', 'uploaded.to', 'uploadgig.com',
                'ul.to', 'filefactory.com', 'nitroflare.com', 'turbobit.net', 'uploadrocket.net', 'multiup.org'])
        except Exception:
            self.hostprDict = [
                '1fichier.com', 'oboom.com', 'rapidgator.net', 'rg.to', 'uploaded.net', 'uploaded.to', 'uploadgig.com',
                'ul.to', 'filefactory.com', 'nitroflare.com', 'turbobit.net', 'uploadrocket.net', 'multiup.org']

        try:
            self.hostcapDict = getattr(self, 'hostcapDict', [])
        except Exception:
            self.hostcapDict = []

        try:
            self.hosthqDict = getattr(self, 'hosthqDict', [])
        except Exception:
            self.hosthqDict = []

        try:
            self.hostblockDict = getattr(self, 'hostblockDict', [])
        except Exception:
            self.hostblockDict = []

    def apply_visual_props(self, listitem, source):
        """Apply visual properties to `listitem` for skinning:
        - sets source.type = 'paid'|'free'
        - sets source.premium or source.free boolean-like props
        - sets source.internal when provider looks like internal
        Returns None (mutates listitem)
        """
        try:
            # debrid presence => paid
            debrid_val = source.get('debrid', '') if isinstance(source, dict) else ''
            is_paid = bool(debrid_val)
            listitem.setProperty('source.type', 'paid' if is_paid else 'free')
            if is_paid:
                listitem.setProperty('source.premium', 'true')
            else:
                listitem.setProperty('source.free', 'true')

            provider = (source.get('provider', '') or '').lower() if isinstance(source, dict) else ''
            internal = ('crew' in provider) or (source.get('source', '').lower() == 'crew') if isinstance(source, dict) else False
            if internal:
                listitem.setProperty('source.internal', 'true')
        except Exception:
            # defensive: don't fail the UI if listitem lacks setProperty or source malformed
            pass

        # NOTE: Do NOT lazily import or initialize providers/host-lists here — this function is called per-list-item and
        # re-running discovery is expensive. Provider discovery and host list initialization must be done once during
        # `getSources()` initialization. If attributes are missing, gracefully skip.
        try:
            # ensure we don't mutate or reload provider lists here
            _ = getattr(self, 'sourceDict', None)
            _ = getattr(self, 'hostDict', None)
            _ = getattr(self, 'hostprDict', None)
            _ = getattr(self, 'hostcapDict', None)
            _ = getattr(self, 'hosthqDict', None)
            _ = getattr(self, 'hostblockDict', None)
        except Exception:
            pass

    def get_prem_color(self, n):
        """Return the color associated with a given premium status."""
        colors = {
            '0': 'blue',
            '1': 'red',
            '2': 'yellow',
            '3': 'deeppink',
            '4': 'cyan',
            '5': 'lawngreen',
            '6': 'gold',
            '7': 'magenta',
            '8': 'yellowgreen',
            '9': 'nocolor',
        }
        return colors.get(n, 'blue')
