# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file upnext.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

import threading
import traceback
import xbmc
import xbmcgui
from urllib.parse import quote_plus

from . import control
from . import trakt
from .crewruntime import c


# Global locks and state for preventing race conditions
_play_lock = threading.Lock()
_last_play_time = 0
_dialog_lock = threading.Lock()
_dialog_showing = False
_active_scrape_threads = []


def reset_to_zero_point():
    """
    ZERO POINT - Complete cleanup between episodes.

    This is the single moment where everything resets to a clean state:
    - Clear all tracking properties
    - Delete player instances (caller's responsibility)
    - Force garbage collection (Python objects)
    - Log resource state (threads)
    - Extended settling time for GPU/decoder resource release

    CRITICAL: The settling time (2.5s) is NOT arbitrary. Testing showed that:
    - Kodi's C++ video decoder needs time to fully release GPU resources
    - GPU drivers need time to flush video buffers
    - File handles must be fully released by OS
    - Repeated rapid play/stop cycles without settling cause "could not open video codec" errors
    - 750ms was insufficient - codec still failed after 5-12 episodes
    - 2.5s provides breathing room for low-end systems and GPU driver cleanup

    Call this AFTER stopping current playback, BEFORE starting next episode.
    Works for both regular UpNext and TV Evening playlist modes.
    """
    import gc
    import time

    if c.devmode:
        c.log("[ZeroPoint] Starting cleanup between episodes...")

    # 1. Clear all file tracking properties
    control.window.clearProperty('thecrew.player.last_processed_file')

    # 2. Delete any player instances in scope (will be handled by caller)
    # Note: Caller should del player before calling this

    # 3. Force garbage collection (multiple passes for thoroughness)
    # This frees Python objects but doesn't affect Kodi's C++ decoder state
    collected_counts = []
    for i in range(3):
        count = gc.collect()
        collected_counts.append(count)

    if c.devmode:
        c.log(f"[ZeroPoint] Garbage collection: {collected_counts} objects freed")

    # 4. Thread audit - verify zero-thread-growth architecture (v22.25)
    # ThreadPoolExecutor should keep thread count STABLE (16 threads across infinite episodes)
    # Any growth indicates a leak (workers not being reused properly)
    thread_count = threading.active_count()

    # Track baseline on first episode
    if not hasattr(reset_to_zero_point, '_baseline_thread_count'):
        reset_to_zero_point._baseline_thread_count = thread_count
        reset_to_zero_point._episode_count = 0
        if c.devmode:
            c.log(f"[ZeroPoint] Baseline thread count: {thread_count}")
    else:
        reset_to_zero_point._episode_count += 1
        baseline = reset_to_zero_point._baseline_thread_count
        growth = thread_count - baseline

        if growth > 0:
            # FAIL: Thread count increased = pool not reusing workers or leak elsewhere
            c.log(f"[ZeroPoint] [WARNING] THREAD GROWTH: {growth} threads leaked (episode {reset_to_zero_point._episode_count})")
            if c.devmode:
                c.log(f"[ZeroPoint] Details: {thread_count} threads (baseline: {baseline})")
                # List thread names to identify source of leak
                try:
                    thread_names = [t.name for t in threading.enumerate()]
                    c.log(f"[ZeroPoint] Active threads: {', '.join(thread_names)}")
                except:
                    pass
        else:
            # SUCCESS: Thread count stable
            if c.devmode:
                c.log(f"[ZeroPoint] Thread count stable: {thread_count} (episodes: {reset_to_zero_point._episode_count})")

    # 5. SETTLING TIME - Critical for GPU/decoder resource release
    # Why 2.5 seconds:
    # - Kodi's FFmpeg video decoder needs to fully release GPU codec resources
    # - GPU drivers (especially NVIDIA/AMD) buffer video frames that must flush
    # - Windows file system needs to release file handles completely
    # - Testing showed codec failures at 750ms, success with 2.5s
    # - This is a CPU-idle period (just sleeping), minimal impact on user experience
    # - Simple notification provides UX feedback during the brief pause
    if c.devmode:
        c.log("[ZeroPoint] Settling for 2.5s (GPU/decoder resource release)...")

    # Show notification during settling time
    try:
        import xbmc
        xbmc.executebuiltin('Notification(The Crew, Preparing next episode..., 2500, DefaultIconInfo.png)')
    except:
        pass

    time.sleep(2.5)

    if c.devmode:
        c.log("[ZeroPoint] Zero point reached - clean state established")


class UpNextDialog(xbmcgui.WindowXMLDialog):
    """
    Up Next dialog for auto-playing next episode.
    Shows countdown, episode info, and play/cancel buttons.
    """

    def __init__(self, *args, **kwargs):
        self.action_taken = None
        self.countdown_seconds = kwargs.get('countdown_seconds', 15)
        self.next_episode_data = kwargs.get('next_episode_data', {})
        self.autoplay = kwargs.get('autoplay', True)
        self.countdown_thread = None
        self.cancelled = False
        self.button_clicked = False  # Debouncing flag

    def onInit(self):
        """Initialize dialog and start countdown."""
        try:
            # Set properties on the dialog window itself (not home window)
            self.setProperty('upnext.show', self.next_episode_data.get('tvshowtitle', 'Unknown Show'))
            self.setProperty('upnext.title', self.next_episode_data.get('title', 'Unknown Episode'))
            self.setProperty('upnext.season', str(self.next_episode_data.get('season', '')))
            self.setProperty('upnext.episode', str(self.next_episode_data.get('episode', '')))
            self.setProperty('upnext.thumb', self.next_episode_data.get('thumb', ''))
            self.setProperty('upnext.poster', self.next_episode_data.get('poster', ''))

            if c.devmode:
                c.log(f"[UpNext] Dialog initialized - {self.next_episode_data.get('tvshowtitle')}, {self.next_episode_data.get('title')}")

            # Start countdown
            self.start_countdown()
        except Exception as e:
            c.log(f"[UpNext] Error in onInit: {e}")

    def start_countdown(self):
        """Start the countdown timer."""
        self.countdown_thread = threading.Thread(target=self._countdown_loop)
        self.countdown_thread.daemon = True
        self.countdown_thread.start()

    def _countdown_loop(self):
        """Countdown loop that updates the display."""
        try:
            for i in range(self.countdown_seconds, 0, -1):
                if self.cancelled:
                    return

                # Set countdown on dialog window
                self.setProperty('upnext.countdown', f'{i}')
                xbmc.sleep(1000)

                # Check if user clicked a button
                if self.action_taken is not None:
                    return

            # Countdown finished - auto-play if enabled
            if self.autoplay and not self.cancelled:
                self.action_taken = 'play'
                self.close()
        except Exception as e:
            c.log(f"[UpNext] Error in countdown loop: {e}")

    def onClick(self, controlID):
        """Handle button clicks."""
        try:
            # Debouncing - prevent multiple clicks
            if self.button_clicked:
                if c.devmode:
                    c.log("[UpNext] Duplicate click ignored")
                return
            self.button_clicked = True

            if controlID == 100:  # Play Now button
                c.log("[UpNext] Play Now button clicked")
                self.cancelled = True
                self.action_taken = 'play'
                self.close()
            elif controlID == 101:  # Cancel button
                c.log("[UpNext] Cancel button clicked")
                self.cancelled = True
                self.action_taken = 'cancel'
                self.close()
        except Exception as e:
            c.log(f"[UpNext] Error in onClick: {e}")

    def onAction(self, action):
        """Handle actions (ESC, back button, etc.)."""
        if action.getId() in [9, 10, 92, 216, 247, 257, 275, 61467, 61448]:  # Back/ESC actions
            if self.button_clicked:
                return  # Already handled
            self.button_clicked = True
            self.cancelled = True
            self.action_taken = 'cancel'
            self.close()

    def __del__(self):
        """Cleanup when dialog is destroyed."""
        try:
            # Stop countdown thread (don't join - it's daemon, will terminate automatically)
            self.cancelled = True
            c.log("[UpNext] (OK) Dialog destroyed and cleaned up")
        except Exception as e:
            c.log(f"[UpNext] Error in dialog cleanup: {e}")


def is_enabled():
    """Check if Up Next feature is enabled."""
    try:
        return control.setting('upnext.enabled') == 'true'
    except:
        return False


def get_trigger_percent():
    """Get the trigger percentage from settings (default 97)."""
    try:
        return int(control.setting('upnext.trigger_percent'))
    except:
        return 92


def get_countdown_seconds():
    """Get countdown duration from settings (default 15)."""
    try:
        return int(control.setting('upnext.countdown_seconds'))
    except:
        return 15


def get_autoplay():
    """Check if auto-play is enabled (default True)."""
    try:
        return control.setting('upnext.autoplay') == 'true'
    except:
        return True


def get_episode_metadata(imdb, tmdb, season, episode, tvshowtitle=None, year=None):
    """
    Get metadata for a specific episode from Trakt API.

    :param str imdb: IMDB ID of the show
    :param str tmdb: TMDb ID of the show
    :param int season: Season number
    :param int episode: Episode number
    :param str tvshowtitle: TV show title (fallback)
    :param str year: TV show year (fallback)
    :return: Episode data dict with title, plot, thumb or None
    :rtype: dict or None
    """
    try:
        from . import client
        import json

        if c.devmode:
            c.log(f"[UpNext] Fetching metadata for {tvshowtitle} S{season}E{episode}")

        # Get specific episode from Trakt API
        url = f'https://api.trakt.tv/shows/{imdb}/seasons/{season}/episodes/{episode}?extended=full'
        headers = {
            'Content-Type': 'application/json',
            'trakt-api-version': '2',
            'trakt-api-key': trakt.CLIENT_ID
        }

        # Add auth if available (not required for public metadata)
        token = control.setting('trakt.token')
        if token:
            headers['Authorization'] = f'Bearer {token}'

        result = client.request(url, headers=headers)
        if not result:
            if c.devmode:
                c.log("[UpNext] No result from Trakt API")
            return None

        ep_data = json.loads(result)

        # Build episode metadata dict
        metadata = {
            'imdb': imdb,
            'tmdb': tmdb,
            'season': season,
            'episode': episode,
            'tvshowtitle': tvshowtitle or 'Unknown Show',
            'year': year or '',
            'title': ep_data.get('title', f'Episode {episode}'),
            'plot': ep_data.get('overview', ''),
            'thumb': ''  # Could fetch from TMDb if needed
        }

        if c.devmode:
            c.log(f"[UpNext] Fetched: {metadata.get('title')}")
        return metadata

    except Exception as e:
        c.log(f"[UpNext] [WARNING] Error fetching metadata: {e}")
        if c.devmode:
            c.log(f"[UpNext] Traceback: {traceback.format_exc()}")
        return None


def get_next_episode(imdb, tmdb, season, episode, tvshowtitle=None, year=None):
    """
    Get next episode metadata with smart season boundary detection.
    Fetches artwork from TMDb and handles automatic season transitions.

    :param str imdb: IMDB ID of the show
    :param str tmdb: TMDb ID of the show
    :param int season: Current season number
    :param int episode: Current episode number
    :param str tvshowtitle: TV show title to pass along
    :param str year: TV show year to pass along
    :return: Next episode data dict or None
    :rtype: dict or None
    """
    try:
        from . import client, keys
        import json

        c.log(f"[UpNext] Getting next episode for {tvshowtitle or imdb} S{season}E{episode}")

        # ALWAYS use sequential increment for Up Next (not Trakt progress)
        # Trakt progress API returns "next unwatched" which can jump episodes
        # For linear watching, we want the actual next episode (current + 1)
        # Example: Watching E01 should show E02, not E08 (even if E02-E07 are marked watched)
        next_season = int(season)
        next_episode = int(episode) + 1

        # Try to fetch the next episode from TMDb to verify it exists AND get artwork
        # Check for valid tmdb ID before making API call
        if tmdb and tmdb not in ('None', '0', None):
            try:
                tmdb_key = keys.tmdb_key
                episode_url = f'https://api.themoviedb.org/3/tv/{tmdb}/season/{next_season}/episode/{next_episode}?api_key={tmdb_key}'

                result = client.request(episode_url, timeout='10')

                if result:
                    # Episode exists! Parse metadata and artwork
                    ep_data = json.loads(result)

                    # Check if episode has aired before showing UpNext
                    air_date = ep_data.get('air_date')
                    from . import cleandate
                    if not cleandate.has_aired(air_date):
                        c.log(f"[UpNext] S{next_season:02d}E{next_episode:02d} hasn't aired yet (air_date: {air_date}) - not showing UpNext")
                        return None

                    thumb = ''
                    if ep_data.get('still_path'):
                        thumb = f"https://image.tmdb.org/t/p/w500{ep_data['still_path']}"

                    # Also fetch show poster (vertical poster art)
                    poster = ''
                    try:
                        show_url = f'https://api.themoviedb.org/3/tv/{tmdb}?api_key={tmdb_key}'
                        show_result = client.request(show_url, timeout='10')
                        if show_result:
                            show_data = json.loads(show_result)
                            if show_data.get('poster_path'):
                                poster = f"https://image.tmdb.org/t/p/w500{show_data['poster_path']}"
                    except Exception as poster_err:
                        c.log(f"[UpNext] Could not fetch show poster: {poster_err}")

                    if c.devmode:
                        c.log(f"[UpNext] Found S{next_season:02d}E{next_episode:02d}: {ep_data.get('name', '')}")
                    return {
                        'imdb': imdb,
                        'tmdb': tmdb,
                        'season': next_season,
                        'episode': next_episode,
                        'tvshowtitle': tvshowtitle or 'Unknown Show',
                        'year': year or '',
                        'title': ep_data.get('name', f'Episode {next_episode}'),
                        'plot': ep_data.get('overview', ''),
                        'thumb': thumb,
                        'poster': poster
                    }
                else:
                    # Episode doesn't exist (404) - assume season finale, try next season
                    if c.devmode:
                        c.log(f"[UpNext] S{next_season}E{next_episode} not found, trying S{next_season + 1:02d}E01")

                    next_season += 1
                    next_episode = 1

                    # Try season+1, episode 1
                    episode_url = f'https://api.themoviedb.org/3/tv/{tmdb}/season/{next_season}/episode/{next_episode}?api_key={tmdb_key}'
                    result = client.request(episode_url, timeout='10')

                    if result:
                        ep_data = json.loads(result)

                        # Check if episode has aired before showing UpNext
                        air_date = ep_data.get('air_date')
                        from . import cleandate
                        if not cleandate.has_aired(air_date):
                            c.log(f"[UpNext] S{next_season:02d}E{next_episode:02d} hasn't aired yet (air_date: {air_date}) - not showing UpNext")
                            return None

                        thumb = ''
                        if ep_data.get('still_path'):
                            thumb = f"https://image.tmdb.org/t/p/w500{ep_data['still_path']}"

                        # Fetch show poster for new season
                        poster = ''
                        try:
                            show_url = f'https://api.themoviedb.org/3/tv/{tmdb}?api_key={tmdb_key}'
                            show_result = client.request(show_url, timeout='10')
                            if show_result:
                                show_data = json.loads(show_result)
                                if show_data.get('poster_path'):
                                    poster = f"https://image.tmdb.org/t/p/w500{show_data['poster_path']}"
                        except Exception as poster_err:
                            if c.devmode:
                                c.log(f"[UpNext] Could not fetch poster: {poster_err}")

                        c.log(f"[UpNext] Season {next_season} Episode {next_episode}")
                        return {
                            'imdb': imdb,
                            'tmdb': tmdb,
                            'season': next_season,
                            'episode': next_episode,
                            'tvshowtitle': tvshowtitle or 'Unknown Show',
                            'year': year or '',
                            'title': ep_data.get('name', f'Episode {next_episode}'),
                            'plot': ep_data.get('overview', ''),
                            'thumb': thumb,
                            'poster': poster
                        }
                    else:
                        if c.devmode:
                            c.log(f"[UpNext] No more episodes found (series ended)")
                        return None

            except Exception as e:
                if c.devmode:
                    c.log(f"[UpNext] TMDb fetch error: {e}")
                    import traceback
                    c.log(f"[UpNext] Traceback: {traceback.format_exc()}")
        else:
            if c.devmode:
                c.log(f"[UpNext] Skipping TMDb fetch - invalid tmdb ID: {tmdb}")

        # Fallback if no tmdb ID or fetch failed
        if c.devmode:
            c.log(f"[UpNext] Using fallback for S{next_season:02d}E{next_episode:02d}")
        return {
            'imdb': imdb,
            'tmdb': tmdb,
            'season': next_season,
            'episode': next_episode,
            'tvshowtitle': tvshowtitle or 'Unknown Show',
            'year': year or '',
            'title': f'S{next_season:02d}E{next_episode:02d}',
            'plot': 'Continue watching...',
            'thumb': ''
        }

    except Exception as e:
        c.log(f"[UpNext] [WARNING] Error getting next episode: {e}")
        if c.devmode:
            import traceback
            c.log(f"[UpNext] Traceback: {traceback.format_exc()}")
        return None


def get_next_from_trakt(imdb, tmdb, season, episode, tvshowtitle=None, year=None):
    """
    Get next episode from Trakt progress API.

    :param str imdb: IMDB ID of the show
    :param str tmdb: TMDb ID of the show
    :param int season: Current season number
    :param int episode: Current episode number
    :param str tvshowtitle: TV show title (fallback if API doesn't return it)
    :param str year: TV show year (fallback if API doesn't return it)
    :return: Next episode data dict or None
    :rtype: dict or None
    """
    try:
        from . import client
        import json

        # Get show progress from Trakt API
        url = f'https://api.trakt.tv/shows/{imdb}/progress/watched?hidden=false&specials=false&count_specials=false'
        headers = {
            'Content-Type': 'application/json',
            'trakt-api-version': '2',
            'trakt-api-key': trakt.CLIENT_ID
        }

        # Add auth if available
        token = control.setting('trakt.token')
        if token:
            headers['Authorization'] = f'Bearer {token}'

        result = client.request(url, headers=headers)
        if not result:
            return None

        progress_data = json.loads(result)
        next_ep = progress_data.get('next_episode')

        if next_ep:
            return {
                'imdb': imdb,
                'tmdb': tmdb,
                'season': next_ep.get('season', season),
                'episode': next_ep.get('number', episode + 1),
                'tvshowtitle': progress_data.get('show', {}).get('title', tvshowtitle or 'Unknown Show'),
                'year': progress_data.get('show', {}).get('year', year or ''),
                'title': next_ep.get('title', 'Unknown Episode'),
                'plot': next_ep.get('overview', ''),
                'thumb': ''
            }

        return None

    except Exception as e:
        c.log(f"[UpNext] Error getting next episode from Trakt API: {e}")
        c.log(f"[UpNext] Traceback: {traceback.format_exc()}")
        return None


def start_background_scraping(title, year, imdb, tmdb, season, episode, tvshowtitle=None):
    """
    Start background scraping for next episode.

    :param str title: Show title
    :param str year: Show year
    :param str imdb: IMDB ID
    :param str tmdb: TMDb ID
    :param int season: Season number
    :param int episode: Episode number
    :param str tvshowtitle: TV show title (defaults to title)
    :return: Thread object
    :rtype: threading.Thread
    """
    try:
        c.log(f"[UpNext] Starting background scraping for {title} S{season}E{episode}")

        if not tvshowtitle:
            tvshowtitle = title

        def scrape_sources():
            try:
                # Import sources module
                from . import sources as Sources

                # Create sources object and start scraping
                sources_obj = Sources.Sources()
                items = sources_obj.getSources(
                    title=title,
                    year=year,
                    imdb=imdb,
                    tmdb=tmdb,
                    season=str(season),
                    episode=str(episode),
                    tvshowtitle=tvshowtitle,
                    premiered=None,
                    timeout=30,  # Give scrapers more time for background scraping
                    show_dialog=False,  # Silent - no progress dialog
                    upnext=True  # Force cache bypass setting for instant playback
                )

                if items:
                    c.log(f"[UpNext] Background scraping complete, found {len(items)} sources")

                    # Cache sources for playback (15s TTL)
                    try:
                        c.log(f"[UpNext] Caching sources: imdb={imdb}, tmdb={tmdb}, season={season}, episode={episode}")
                        sources_obj.set_upnext_cached_sources(imdb, tmdb, str(season), str(episode), items)
                        c.log(f"[UpNext] (OK) Successfully cached {len(items)} sources for immediate playback")
                    except Exception as cache_error:
                        c.log(f"[UpNext] (X) Error caching sources: {cache_error}")
                        c.log(f"[UpNext] Cache error traceback: {traceback.format_exc()}")
                else:
                    c.log("[UpNext] Background scraping returned 0 sources")

            except Exception as e:
                c.log(f"[UpNext] Error in background scraping: {e}")
                c.log(f"[UpNext] Traceback: {traceback.format_exc()}")

        # Start scraping in background thread
        scrape_thread = threading.Thread(target=scrape_sources)
        scrape_thread.daemon = True
        scrape_thread.start()

        # Track active threads for cleanup
        global _active_scrape_threads
        _active_scrape_threads.append(scrape_thread)
        # Clean up finished threads
        _active_scrape_threads = [t for t in _active_scrape_threads if t.is_alive()]

        return scrape_thread

    except Exception as e:
        c.log(f"[UpNext] Error starting background scraping: {e}")
        return None


def show_upnext_dialog(current_title, current_year, current_imdb, current_tmdb, current_season, current_episode, from_playlist=False, from_database=False, playlist_position=None):
    """
    Show Up Next dialog for next episode.

    :param str current_title: Current show title (or NEXT show title if from_playlist/from_database=True)
    :param str current_year: Current show year (or NEXT show year if from_playlist/from_database=True)
    :param str current_imdb: Current IMDB ID (or NEXT show IMDB if from_playlist/from_database=True)
    :param str current_tmdb: Current TMDb ID (or NEXT show TMDb if from_playlist/from_database=True)
    :param int current_season: Current season number (or NEXT season if from_playlist/from_database=True)
    :param int current_episode: Current episode number (or NEXT episode if from_playlist/from_database=True)
    :param bool from_playlist: True if metadata is for next Kodi playlist item (already the "next" episode)
    :param bool from_database: True if metadata is from TV Evening database (already the "next" episode)
    :param int playlist_position: Current playlist position (captured before dialog shown, to avoid race conditions)
    :return: User action ('play', 'cancel', or None)
    :rtype: str or None
    """
    global _dialog_showing

    try:
        # CRITICAL: Prevent multiple simultaneous dialogs
        if not _dialog_lock.acquire(blocking=False):
            c.log("[UpNext] BLOCKED: Another UpNext dialog is already showing")
            return None

        try:
            if _dialog_showing:
                c.log("[UpNext] BLOCKED: Dialog flag already set (race condition prevented)")
                return None

            _dialog_showing = True
            c.log("[UpNext] Dialog lock acquired - showing dialog")

            if not is_enabled():
                c.log("[UpNext] Feature is disabled")
                return None

            c.log(f"[UpNext] Showing Up Next dialog for {current_title} S{current_season}E{current_episode}")
            c.log(f"[UpNext] from_playlist={from_playlist}, from_database={from_database}, playlist_position={playlist_position}")

            # If from_playlist or from_database=True, the metadata passed in IS the next episode already
            # But we still need to fetch the full episode details (title, plot, thumb)
            if from_playlist or from_database:
                mode = "database" if from_database else "Kodi playlist"
                c.log(f"[UpNext] Using next {mode} item metadata - fetching full episode details")
                # Fetch full episode details including title, plot, thumb
                next_ep = get_episode_metadata(current_imdb, current_tmdb, current_season, current_episode, current_title, current_year)
                if not next_ep:
                    c.log(f"[UpNext] Could not fetch episode metadata for {mode} item")
                    # Fallback to minimal data
                    next_ep = {
                        'imdb': current_imdb,
                        'tmdb': current_tmdb,
                        'season': current_season,
                        'episode': current_episode,
                        'tvshowtitle': current_title,
                        'year': current_year,
                        'title': f'S{current_season:02d}E{current_episode:02d}',
                        'plot': 'Continue watching...',
                        'thumb': ''
                    }
                next_ep['from_playlist'] = True  # Flag for play_next_episode (database items work like playlist)
                next_ep['_captured_playlist_pos'] = playlist_position  # Store captured position to avoid race condition
                scrape_thread = None  # Playlist/database items are already scraped - no need to scrape again
            else:
                # Single episode mode - find next episode of same show
                c.log("[UpNext] Finding next episode of same show (binge watch mode)")

                # Store current episode metadata (for marking as watched)
                current_episode_metadata = {
                    'imdb': current_imdb,
                    'tmdb': current_tmdb,
                    'season': current_season,
                    'episode': current_episode,
                    'title': current_title,
                    'year': current_year
                }

                # CONTAINER SYSTEM: Check if secondary container has pre-fetched data
                try:
                    from . import episode_container
                    secondary = episode_container.get_secondary()
                    if secondary is None:
                        raise Exception("No secondary container available")
                    # Stale-container guard: the secondary must be the episode AFTER the current one.
                    # If secondary.episode == current_episode (same episode) the container is stale
                    # (e.g. the previous episode's prefetch was never swapped out) and must be skipped.
                    _secondary_episode_num = int(secondary.episode) if secondary.episode else 0
                    _expected_next = current_episode + 1  # simplification; season wrap handled by fallback
                    _container_is_stale = (
                        _secondary_episode_num != _expected_next
                        or int(secondary.season or 0) != current_season
                    )
                    if secondary.is_ready() and not _container_is_stale:
                        # Use pre-fetched container data - instant metadata!
                        c.log(f"[UpNext] (OK) Using pre-fetched container data: {secondary.get_episode_string()}")
                        next_ep = {
                            'imdb': secondary.imdb,
                            'tmdb': secondary.tmdb,
                            'season': int(secondary.season),
                            'episode': int(secondary.episode),
                            'tvshowtitle': secondary.title,
                            'year': secondary.year,
                            'title': secondary.metadata.get('title', f'Episode {secondary.episode}'),
                            'plot': secondary.plot or secondary.metadata.get('plot', ''),
                            'thumb': secondary.poster or secondary.metadata.get('thumb', ''),
                            'rating': secondary.rating,
                            'aired': secondary.aired,
                            'from_playlist': False,
                            '_from_container': True,  # Flag that this came from container
                            '_current_episode': current_episode_metadata  # Current episode to mark as watched
                        }
                        scrape_thread = None  # No need to scrape - already done!
                        c.log(f"[UpNext] (OK) Container metadata loaded instantly (no fetch delay)")
                    elif _container_is_stale and secondary.is_ready():
                        # Container is ready but holds wrong (stale) episode — discard it
                        c.log(f"[UpNext] [WARNING] Stale container detected: has S{secondary.season}E{secondary.episode} but expected S{current_season}E{_expected_next} — discarding")
                        episode_container.cancel_upnext()
                        raise Exception(f"Stale container (S{secondary.season}E{secondary.episode}), expected E{_expected_next}")
                    else:
                        # Container not ready yet
                        c.log(f"[UpNext] Container not ready (status: {secondary.status}), using normal fetch")
                        raise Exception("Container not ready - use normal flow")
                except Exception as e:
                    # Fallback to original flow
                    c.log(f"[UpNext] Using fallback metadata fetch: {e}")
                    next_ep = get_next_episode(current_imdb, current_tmdb, current_season, current_episode,
                                               tvshowtitle=current_title, year=current_year)
                    if not next_ep:
                        c.log("[UpNext] Could not get next episode")
                        return None

                    next_ep['from_playlist'] = False  # Flag for play_next_episode
                    next_ep['_current_episode'] = current_episode_metadata  # Current episode to mark as watched

                    # Start background scraping for single episode mode
                    scrape_thread = start_background_scraping(
                        current_title,
                        current_year,
                        next_ep['imdb'],
                        next_ep['tmdb'],
                        next_ep['season'],
                        next_ep['episode'],
                        current_title  # tvshowtitle
                    )

            # Get settings
            countdown_seconds = get_countdown_seconds()
            autoplay = get_autoplay()

            # Get skin path
            skin = c.appearance() or 'thecrew'
            dialog_xml = 'UpNext.xml'
            addon_path = c.get_artwork_path()

            # Show dialog
            dialog = UpNextDialog(
                dialog_xml,
                addon_path,
                skin,
                countdown_seconds=countdown_seconds,
                next_episode_data=next_ep,
                autoplay=autoplay
            )
            dialog.doModal()

            # Get user action from dialog (thread-safe - no window property)
            action = dialog.action_taken

            # Ensure dialog fully closed before deletion
            try:
                dialog.close()
                c.log("[UpNext] (OK) Dialog closed")
            except Exception as e:
                c.log(f"[UpNext] Dialog already closed: {e}")

            # Clean up dialog reference
            del dialog
            c.log("[UpNext] (OK) Dialog reference deleted")

            c.log(f"[UpNext] User action: {action}")

            # If play action, proceed with playback
            if action == 'play':
                # Wait for background scraping if still active (simple join, no notification)
                # User already sees normal scraping progress dialogs when clicking Play
                if scrape_thread and scrape_thread.is_alive():
                    scrape_thread.join(timeout=15)

                # Play next episode
                play_next_episode(next_ep)
                return 'play'
            elif action == 'cancel':
                # User cancelled - reset the trigger flag so Up Next can trigger again
                # if they continue watching past 92%
                c.log("[UpNext] User cancelled dialog - resetting trigger flag")

                # CONTAINER SYSTEM: Destroy secondary container (no longer needed)
                try:
                    from . import episode_container
                    episode_container.cancel_upnext()
                    c.log("[UpNext] (OK) Destroyed secondary container after cancel")
                except Exception as e:
                    c.log(f"[UpNext] Could not cancel container: {e}")

                try:
                    # Import xbmc to get the player instance
                    import xbmc
                    player_instance = xbmc.Player()
                    if hasattr(player_instance, 'upnext_triggered'):
                        player_instance.upnext_triggered = False
                        c.log("[UpNext] (OK) Reset upnext_triggered flag after cancel")
                except Exception as e:
                    c.log(f"[UpNext] Could not reset flag (non-critical): {e}")

            return action

        finally:
            # Always release dialog lock
            _dialog_showing = False
            _dialog_lock.release()
            c.log("[UpNext] Dialog lock released")

    except Exception as e:
        c.log(f"[UpNext] Error showing Up Next dialog: {e}")
        c.log(f"[UpNext] Traceback: {traceback.format_exc()}")
        # Make sure to release lock even on error
        if _dialog_lock.locked():
            _dialog_showing = False
            _dialog_lock.release()
        return None


def play_next_episode(episode_data):
    """
    Play the next episode.

    :param dict episode_data: Episode metadata
    """
    global _last_play_time

    # Prevent race condition - only one playback attempt at a time
    # Use NON-BLOCKING lock so threads don't wait in line (no queuing!)
    if not _play_lock.acquire(blocking=False):
        c.log(f"[UpNext] Another playback attempt already in progress, skipping (prevented race)")
        return

    try:
        import time
        current_time = time.time()

        # Debounce - ignore if called within 2 seconds of last call
        if current_time - _last_play_time < 2.0:
            c.log(f"[UpNext] Ignoring duplicate play_next_episode call (debounce: {current_time - _last_play_time:.1f}s)")
            return
        _last_play_time = current_time

        from_playlist = episode_data.get('from_playlist', False)
        # Use the captured position if available (set before dialog was shown)
        captured_position = episode_data.get('_captured_playlist_pos')

        if from_playlist:
            # Playlist mode - play next item directly (don't stop first - that exits playback)
            c.log("[UpNext] Playlist mode - advancing to next item")
            import xbmc

            playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)

            # Use captured position if available, otherwise get current
            if captured_position is not None:
                current_pos = captured_position
                c.log(f"[UpNext] Using captured position: {current_pos}")
            else:
                current_pos = playlist.getposition()
                c.log(f"[UpNext] WARNING: No captured position, using current: {current_pos}")

            next_pos = current_pos + 1

            c.log(f"[UpNext] Playlist: current_pos={current_pos}, next_pos={next_pos}, size={playlist.size()}")

            if next_pos < playlist.size():
                # Signal to player that we're intentionally starting new playback
                # This resets onAVStarted debouncing so next episode gets a monitoring loop
                try:
                    from . import player as player_mod
                    with player_mod._expect_lock:
                        player_mod._expect_new_playback = True
                    c.log("[UpNext] Set expect_new_playback flag for next episode")
                except Exception as e:
                    c.log(f"[UpNext] Could not set expect flag (non-critical): {e}")

                player = xbmc.Player()

                # Mark current episode as watched BEFORE stopping (prevents race condition)
                # For playlist mode, we need to get current episode metadata from player's global state
                try:
                    from . import player as player_mod
                    from . import playcount
                    with player_mod._metadata_lock:
                        metadata = player_mod._latest_episode_metadata
                        if metadata.get('season') and metadata.get('episode') and metadata.get('imdb'):
                            c.log(f"[UpNext] Marking as watched (playlist mode): {metadata.get('title', 'Unknown')} S{metadata['season']}E{metadata['episode']}")
                            playcount.markEpisodeDuringPlayback(
                                metadata['imdb'],
                                metadata.get('tmdb', ''),
                                str(metadata['season']),
                                str(metadata['episode']),
                                '7'
                            )
                        else:
                            c.log(f"[UpNext] No episode metadata to mark as watched (playlist mode) - metadata: {metadata}")
                except Exception as e:
                    c.log(f"[UpNext] Error marking episode as watched: {e}")
                    import traceback
                    c.log(f"[UpNext] Traceback: {traceback.format_exc()}")

                # Stop current playback and log current file
                if player.isPlaying():
                    try:
                        current_file = player.getPlayingFile()
                        c.log(f"[UpNext] Current file: {current_file[:100]}...")
                    except:
                        pass
                    c.log("[UpNext] Stopping current playback")
                    player.stop()

                # Delete player instance before zero point
                del player
                c.log("[UpNext] (OK) Player instance deleted")

                # ═══ ZERO POINT: Complete cleanup between episodes ═══
                reset_to_zero_point()

                # Now start next episode from clean state
                c.log(f"[UpNext] Playing next playlist item {next_pos}")
                player = xbmc.Player()  # Fresh instance
                player.play(playlist, startpos=next_pos)
                c.log(f"[UpNext] Started playback of playlist item {next_pos}")
                del player  # Clean up immediately after use
            else:
                c.log("[UpNext] No more items in playlist")
        else:
            # Non-playlist mode - manually play next episode
            c.log("[UpNext] Non-playlist mode - building URL for next episode")

            # Extract metadata
            tvshowtitle = episode_data.get('tvshowtitle', '')

            # Build playback URL
            url = "plugin://plugin.video.thecrew/?action=play"
            url += f"&tvshowtitle={quote_plus(tvshowtitle)}"
            url += f"&year={episode_data.get('year', '')}"
            url += f"&imdb={episode_data['imdb']}"
            url += f"&tmdb={episode_data['tmdb']}"
            url += f"&season={episode_data['season']}"
            url += f"&episode={episode_data['episode']}"
            url += "&upnext=1"  # Signal Up Next for overlay

            c.log(f"[UpNext] Playback URL: {url}")

            # Mark current episode as watched BEFORE stopping (prevents race condition)
            # Use explicitly passed current episode metadata (more reliable than global state)
            current_ep = episode_data.get('_current_episode')
            if current_ep:
                try:
                    from . import playcount
                    c.log(f"[UpNext] Marking as watched: {current_ep.get('title', 'Unknown')} S{current_ep['season']}E{current_ep['episode']}")
                    playcount.markEpisodeDuringPlayback(
                        current_ep['imdb'],
                        current_ep.get('tmdb', ''),
                        str(current_ep['season']),
                        str(current_ep['episode']),
                        '7'
                    )
                except Exception as e:
                    c.log(f"[UpNext] Error marking episode as watched: {e}")
                    import traceback
                    c.log(f"[UpNext] Traceback: {traceback.format_exc()}")
            else:
                c.log("[UpNext] No _current_episode metadata to mark as watched")

            # Stop current playback and log current file
            import xbmc
            player = xbmc.Player()
            if player.isPlaying():
                try:
                    current_file = player.getPlayingFile()
                    c.log(f"[UpNext] Current file: {current_file[:100]}...")
                except:
                    pass
                c.log("[UpNext] Stopping current playback")
                player.stop()

            # Delete player instance before zero point
            del player
            c.log("[UpNext] (OK) Player instance deleted")

            # ═══ ZERO POINT: Complete cleanup between episodes ═══
            reset_to_zero_point()

            # Signal to player that we're intentionally starting new playback
            try:
                from . import player as player_mod
                with player_mod._expect_lock:
                    player_mod._expect_new_playback = True
                c.log("[UpNext] Set expect_new_playback flag for next episode")
            except Exception as e:
                c.log(f"[UpNext] Could not set expect flag (non-critical): {e}")

            # Execute playback from clean state
            control.execute(f'PlayMedia({url})')

    except Exception as e:
        c.log(f"[UpNext] Error playing next episode: {e}")
    finally:
        # ALWAYS release the lock
        _play_lock.release()
