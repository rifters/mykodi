# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file tvevening_monitor.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
TV Evening Monitor
Manages the entire TV Evening session lifecycle with pre-scraping during countdowns.
'''


import threading
import time

import xbmc
import xbmcgui
import xbmcaddon

from . import control
from .crewruntime import c
from . import tvevening_playlist_db
from . import tvevening_countdown
from . import tvevening_complete


# sources imported lazily to avoid circular dependency


class _PlaybackWatcher(xbmc.Player):
    """Thin xbmc.Player subclass that signals a threading.Event the instant
    Kodi reports A/V decoding has started (onAVStarted).  Allows event-based
    waiting instead of polling loops."""
    def __init__(self):
        super().__init__()
        self.started = threading.Event()

    def onAVStarted(self):
        self.started.set()


class TVEveningMonitor:
    """
    Dedicated monitor for TV Evening sessions.
    Responsibilities:
    - Monitors playback progress for all episodes in session
    - Pre-scrapes sources during countdown (uses 60 seconds productively!)
    - Manages episode transitions with countdown dialog
    - Handles errors (no sources, playback failures, etc.)
    - Maintains session state across all episodes
    - Provides real-time feedback to user
    """

    def __init__(self, playlist_episodes, test_mode=False):
        """
        Initialize TV Evening monitor.

        Args:
            playlist_episodes: List of episode dicts from database
            test_mode: If True, handle direct video URLs without source resolution
        """
        self.playlist_episodes = playlist_episodes
        self.current_position = 0
        self.session_active = False
        self.player = _PlaybackWatcher()
        self.monitor_thread = None
        self.stop_monitoring = False
        self.test_mode = test_mode
        if c.devmode:
            c.log(f"[TV Evening Monitor] Test mode: {self.test_mode}")
        self.transition_handled = False  # Flag to prevent double-incrementing position
        self.last_seek_time = 0  # Track when last seek occurred to stabilize after seeks
        self.last_current_time = 0  # Track last current_time to detect seeks
        if c.devmode:
            c.log(f"[TV Evening Monitor] Initialized with {len(playlist_episodes)} episodes")

    def start_session(self):
        """Start the TV Evening monitoring session."""
        self.session_active = True
        self.stop_monitoring = False
        c.log("[TV Evening Monitor] Starting session")

        # Set database metadata for crash recovery
        db = tvevening_playlist_db.get_playlist_db()
        db.set_metadata('session_active', 'true')
        db.set_metadata('started_at', str(time.time()))
        if c.devmode:
            c.log("[TV Evening Monitor] Set database metadata for crash detection")

        # Set window properties to track session state (visible to UpNext and other code)
        control.window.setProperty('thecrew.tvevening.monitor.active', 'true')
        control.window.setProperty('thecrew.tvevening.position', str(self.current_position))
        control.window.setProperty('thecrew.tvevening.total', str(len(self.playlist_episodes)))
        if c.devmode:
            c.log(f"[TV Evening Monitor] Set window properties: active=true, position={self.current_position}, total={len(self.playlist_episodes)}")

        # Set current episode info
        if self.playlist_episodes and len(self.playlist_episodes) > 0:
            current_ep = self.playlist_episodes[0]
            control.window.setProperty('thecrew.tvevening.current.title', current_ep.get('title', ''))
            control.window.setProperty('thecrew.tvevening.current.show', current_ep.get('tvshowtitle', ''))
            if c.devmode:
                c.log(f"[TV Evening Monitor] Current episode: {current_ep.get('tvshowtitle', '')} - {current_ep.get('title', '')}")

        # Start monitoring in background thread
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

        return True

    def stop_session(self):
        """Stop the TV Evening monitoring session."""
        c.log("[TV Evening Monitor] Stopping session")
        self.session_active = False
        self.stop_monitoring = True

        # Clear database metadata
        db = tvevening_playlist_db.get_playlist_db()
        db.set_metadata('session_active', 'false')
        if c.devmode:
            c.log("[TV Evening Monitor] Cleared database metadata")

        # Clear all window properties to signal Monitor is no longer active
        control.window.clearProperty('thecrew.tvevening.monitor.active')
        control.window.clearProperty('thecrew.tvevening.position')
        control.window.clearProperty('thecrew.tvevening.total')
        control.window.clearProperty('thecrew.tvevening.current.title')
        control.window.clearProperty('thecrew.tvevening.current.show')
        control.window.clearProperty('thecrew.tvevening.next.title')
        control.window.clearProperty('thecrew.tvevening.next.show')
        if c.devmode:
            c.log("[TV Evening Monitor] Cleared all TV Evening window properties")

        # Only join thread if we're not calling from within the thread itself
        # (prevents "cannot join current thread" error)
        current_thread = threading.current_thread()
        if self.monitor_thread and self.monitor_thread.is_alive() and current_thread != self.monitor_thread:
            if c.devmode:
                c.log("[TV Evening Monitor] Waiting for monitor thread to finish...")
            self.monitor_thread.join(timeout=2)
        elif c.devmode:
            c.log("[TV Evening Monitor] Thread will exit naturally (called from within thread)")

    def _monitor_loop(self):
        """Main monitoring loop - runs in background thread."""
        c.log("[TV Evening Monitor] Monitor loop started")

        # Event-based: block until AV starts (instant response) or 45s timeout
        startup_timeout = 45
        started = self.player.started.wait(timeout=startup_timeout)
        if not started:
            c.log("[TV Evening Monitor] Playback failed to start after {}s - skipping to next episode".format(startup_timeout))
            next_episode = self._get_next_episode()
            if next_episode:
                self.transition_handled = True
                self._handle_episode_transition(next_episode)
            else:
                self.stop_session()
            return

        try:
            while self.session_active and not self.stop_monitoring:
                # Tick rate for ongoing position monitoring
                time.sleep(1)

                # Check if player is active
                if not self.player.isPlaying():
                        # Playback was active but is now stopped
                        # Check if we should continue to next episode
                        # BUT: Don't double-handle if we already triggered at 92%
                        if self.transition_handled:
                            c.log("[TV Evening Monitor] Playback stopped but transition already handled at 92% - ignoring")
                            continue

                        next_episode = self._get_next_episode()

                        if next_episode:
                            # Episode ended (even if manually seeked to end) - continue to next
                            c.log("[TV Evening Monitor] Episode ended - transitioning to next episode")
                            self.current_position += 1
                            c.log(f"[TV Evening Monitor] Position moved to {self.current_position}")

                            # Update window properties
                            control.window.setProperty('thecrew.tvevening.position', str(self.current_position))
                            control.window.setProperty('thecrew.tvevening.current.title', next_episode.get('title', ''))
                            control.window.setProperty('thecrew.tvevening.current.show', next_episode.get('tvshowtitle', ''))

                            # Mark transition as handled BEFORE calling transition (prevents race condition)
                            self.transition_handled = True

                            # Trigger countdown with pre-scraping
                            self._handle_episode_transition(next_episode)

                            # Event-based: wait for new episode to start (up to 5 seconds)
                            c.log("[TV Evening Monitor] Waiting for new episode to start...")
                            self.player.started.clear()
                            if self.player.started.wait(timeout=5):
                                c.log("[TV Evening Monitor] New episode started, continuing monitor loop")
                                self.transition_handled = False  # Reset flag for new episode
                            continue
                        else:
                            # Last episode finished - show completion dialog
                            c.log("[TV Evening Monitor] Last episode finished - showing completion dialog")

                            xbmc.sleep(500)

                            # CRITICAL: Mark session as inactive BEFORE showing dialog
                            # This prevents race condition where monitor appears active during dialog init (4+ seconds)
                            self.stop_session()

                            # Show completion dialog (can be slow to initialize)
                            total_episodes = len(self.playlist_episodes)
                            last_episode = self.playlist_episodes[-1] if self.playlist_episodes else {}
                            fanart = last_episode.get('fanart', '')

                            c.log(f"[TV Evening Monitor] Completion dialog: {total_episodes} episodes watched")
                            tvevening_complete.show_completion_dialog(
                                episodes_watched=total_episodes,
                                fanart=fanart
                            )

                        break

                # Get playback times
                try:
                    current_time = self.player.getTime()
                    total_time = self.player.getTotalTime()
                except Exception as e:
                    if c.devmode:
                        c.log(f"[TV Evening Monitor] Error getting playback times: {e}")
                    continue

                # Detect seeks: if current_time jumped > 5 seconds (forward or backward)
                if self.last_current_time > 0:
                    time_diff = abs(current_time - self.last_current_time)
                    # Normal playback is ~1 second per check, seek would be a big jump
                    if time_diff > 5:
                        c.log(f"[TV Evening Monitor] SEEK DETECTED: time jumped {time_diff:.1f}s (from {self.last_current_time:.1f}s to {current_time:.1f}s)")
                        self.last_seek_time = time.time()

                self.last_current_time = current_time

                # DIAGNOSTIC: Log playback times every 10 checks (~10 seconds)
                if not hasattr(self, '_time_log_counter'):
                    self._time_log_counter = 0
                self._time_log_counter += 1
                if self._time_log_counter >= 10:
                    c.log(f"[TV Evening Monitor] Playback times: current={current_time:.1f}s, total={total_time:.1f}s, percent={current_time/total_time*100 if total_time > 0 else 0:.1f}%")
                    self._time_log_counter = 0

                if total_time <= 0:
                    if c.devmode:
                        c.log("[TV Evening Monitor] Invalid total_time (<=0), skipping check")
                    continue

                # CRITICAL FIX: Ignore timing right after seek (resume point)
                # Wait 15 seconds after a seek for player to stabilize
                if self.last_seek_time > 0 and (time.time() - self.last_seek_time) < 15:
                    if c.devmode:
                        c.log(f"[TV Evening Monitor] Ignoring timing - too soon after seek ({time.time() - self.last_seek_time:.1f}s ago)")
                    continue

                # CRITICAL FIX: Sanity check - total_time should be reasonable (>10 minutes for most episodes)
                # If total_time is suspiciously short, wait for it to stabilize
                if total_time < 600:  # Less than 10 minutes
                    c.log(f"[TV Evening Monitor] WARNING: Suspiciously short total_time={total_time:.1f}s (<10min), waiting for stabilization...")
                    continue

                # Calculate percentage
                current_percent = current_time / total_time

                # Check if we've hit the trigger point (92%)
                trigger_percent = 0.92  # Could be configurable

                if current_percent >= trigger_percent:
                    c.log("[TV Evening Monitor] Trigger reached at {:.1f}% (current={:.1f}s, total={:.1f}s)".format(current_percent * 100, current_time, total_time))

                    # Get next episode
                    next_episode = self._get_next_episode()

                    if next_episode:
                        # Increment position BEFORE transition (next episode will become current)
                        self.current_position += 1
                        if c.devmode:
                            c.log(f"[TV Evening Monitor] Position incremented to {self.current_position} before transition")

                        # Update window properties with new position and next episode info
                        control.window.setProperty('thecrew.tvevening.position', str(self.current_position))
                        control.window.setProperty('thecrew.tvevening.current.title', next_episode.get('title', ''))
                        control.window.setProperty('thecrew.tvevening.current.show', next_episode.get('tvshowtitle', ''))

                        # Set next-next episode info if available
                        peek_next = self._get_next_episode()
                        if peek_next:
                            control.window.setProperty('thecrew.tvevening.next.title', peek_next.get('title', ''))
                            control.window.setProperty('thecrew.tvevening.next.show', peek_next.get('tvshowtitle', ''))
                        else:
                            control.window.clearProperty('thecrew.tvevening.next.title')
                            control.window.clearProperty('thecrew.tvevening.next.show')

                        if c.devmode:
                            c.log(f"[TV Evening Monitor] Updated window properties: pos={self.current_position}, current={next_episode.get('tvshowtitle', '')}")

                        # Mark transition as handled BEFORE calling transition (prevents race condition)
                        # The transition calls player.stop() which triggers onPlayBackStopped immediately
                        self.transition_handled = True

                        # Trigger countdown with pre-scraping
                        self._handle_episode_transition(next_episode)

                        # Event-based: wait for new episode to start (up to 5 seconds)
                        if c.devmode:
                            c.log("[TV Evening Monitor] Waiting for new episode to start...")
                        self.player.started.clear()
                        if self.player.started.wait(timeout=5):
                            if c.devmode:
                                c.log("[TV Evening Monitor] New episode started, continuing monitor loop")
                            self.transition_handled = False  # Reset flag for new episode
                        # Continue monitoring (don't break - let loop continue)
                    else:
                        c.log("[TV Evening Monitor] No next episode - end of session")

                        # Stop playback before showing completion dialog
                        self.player.stop()
                        xbmc.sleep(500)

                        # CRITICAL: Mark session as inactive BEFORE showing dialog
                        # This prevents race condition where monitor appears active during dialog init (4+ seconds)
                        self.stop_session()

                        # Show completion dialog (can be slow to initialize)
                        total_episodes = len(self.playlist_episodes)
                        last_episode = self.playlist_episodes[-1] if self.playlist_episodes else {}
                        fanart = last_episode.get('fanart', '')

                        c.log(f"[TV Evening Monitor] Showing completion dialog: {total_episodes} episodes watched")
                        tvevening_complete.show_completion_dialog(
                            episodes_watched=total_episodes,
                            fanart=fanart
                        )

                        break

        except Exception as e:
            c.log("[TV Evening Monitor] Fatal error in monitor loop: {}".format(e))
        finally:
            c.log("[TV Evening Monitor] Monitor loop exited")

    def _get_next_episode(self):
        """Get the next episode from the playlist."""
        next_position = self.current_position + 1
        if c.devmode:
            c.log(f"[TV Evening Monitor] Getting next episode at position {self.current_position}, next_position={next_position}")

        if next_position < len(self.playlist_episodes):
            return self.playlist_episodes[next_position]

        return None

    def _handle_episode_transition(self, next_episode):
        """
        Handle transition to next episode with pause dialog.
        After pause dialog, normal scraping with dialog will occur.

        Args:
            next_episode: Episode dict with metadata
        """
        c.log("[TV Evening Monitor] Handling transition to: {} S{:02d}E{:02d}".format(
            next_episode.get('tvshowtitle'),
            next_episode.get('season', 0),
            next_episode.get('episode', 0)
        ))

        # Stop current playback
        self.player.stop()
        xbmc.sleep(500)

        # Create pause dialog (60 second countdown by default)
        # After this dialog, scraping will occur with normal scraping dialog visible

        artwork_addon = xbmcaddon.Addon('script.thecrew.artwork')
        addon_path = artwork_addon.getAddonInfo('path')

        # Use 1 second countdown in test mode for fast automated testing
        # Otherwise read from user setting (default: 60 seconds, range: 10-300)
        if self.test_mode:
            countdown_seconds = 1
        else:
            try:
                countdown_seconds = int(c.get_setting('tvevening.gap_countdown') or '60')
            except (ValueError, TypeError):
                countdown_seconds = 60
        if c.devmode:
            c.log(f"[TV Evening Monitor] Creating countdown dialog ({countdown_seconds}s)")

        # Get user's theme preference (modern or thecrew)
        theme = c.appearance() or 'thecrew'
        if c.devmode:
            c.log(f"[TV Evening Monitor] Using theme: {theme}")

        countdown_dialog = tvevening_countdown.TVEveningCountdown(
            'TVEveningCountdown.xml',
            addon_path,
            theme,
            next_episode=next_episode,
            countdown=countdown_seconds
        )

        # Show pause dialog (blocks until user action or timeout)
        # After dialog closes, we'll use plugin URL which shows scraping dialog
        # This makes the process transparent and consistent throughout the session
        countdown_dialog.doModal()
        user_choice = countdown_dialog.get_user_choice()
        del countdown_dialog

        c.log(f"[TV Evening Monitor] Countdown finished with choice: {user_choice}")

        # CRITICAL: Check if session is still active (could have been stopped during countdown)
        if not self.session_active:
            c.log("[TV Evening Monitor] WARNING: Session was stopped during countdown - aborting playback")
            return

        if user_choice == 'cancel':
            # User cancelled
            c.log("[TV Evening Monitor] User cancelled TV Evening")
            self.stop_session()
        elif user_choice == 'play' or user_choice is None:
            # Play next episode (with additional safety check inside)
            self._play_episode(next_episode)

    def _play_episode(self, episode_data):
        """Play the episode using pre-scraped sources or fallback."""
        try:
            # CRITICAL SAFETY CHECK: Abort if session is no longer active
            # This prevents zombie playback after session ends
            if not self.session_active:
                c.log("[TV Evening Monitor] ABORT: Playback requested but session is no longer active (zombie prevention)")
                return

            # Test mode: Direct URL playback using Kodi playlist
            if self.test_mode:
                url = episode_data.get('url')
                if url:
                    if c.devmode:
                        c.log(f"[TV Evening Monitor] TEST MODE: Playing via Kodi playlist (URL: {url})")
                    # Get Kodi playlist
                    playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)

                    # Play from current position in playlist
                    # This maintains playlist position tracking
                    if c.devmode:
                        c.log("[TV Evening Monitor] TEST MODE: Playing position {} from playlist".format(self.current_position))
                    self.player.play(playlist, startpos=self.current_position)
                    if c.devmode:
                        c.log("[TV Evening Monitor] TEST MODE: Playlist playback started")
                    return
                else:
                    if c.devmode:
                        c.log(f"[TV Evening Monitor] TEST MODE: No URL found in episode_data (keys: {list(episode_data.keys())})")
                    self.stop_session()
                    return

            # Normal mode: Use plugin URL (which will show scraping dialog)
            # This makes the scraping process transparent and consistent
            c.log("[TV Evening Monitor] Using plugin URL for source scraping")
            url = episode_data.get('url')
            if url:
                xbmc.executebuiltin(f'PlayMedia({url})')
                if c.devmode:
                    c.log("[TV Evening Monitor] Plugin URL playback started (will show scraping dialog)")
                # Note: current_position already incremented before transition
            else:
                c.log("[TV Evening Monitor] No URL available")
                self.stop_session()

        except Exception as e:
            c.log(f"[TV Evening Monitor] Error playing episode: {e}")
            self.stop_session()


# Singleton instance
_monitor_instance = None


def get_tv_evening_monitor(playlist_episodes=None, test_mode=False):
    """Get or create TV Evening monitor instance."""
    global _monitor_instance

    if playlist_episodes is not None:
        # Create new monitor for new session
        if c.devmode:
            c.log(f"[Monitor Singleton] Creating NEW monitor instance (test_mode={test_mode})")
        _monitor_instance = TVEveningMonitor(playlist_episodes, test_mode=test_mode)
        if c.devmode:
            c.log(f"[Monitor Singleton] Created monitor: {_monitor_instance}, session_active={_monitor_instance.session_active if _monitor_instance else 'N/A'}")
    elif c.devmode:
        c.log(f"[Monitor Singleton] GET request - Returning existing monitor: {_monitor_instance}, session_active={_monitor_instance.session_active if _monitor_instance else 'N/A'}")

    return _monitor_instance


def start_tv_evening_session(playlist_episodes, test_mode=False):
    """
    Start a new TV Evening monitoring session.

    Args:
        playlist_episodes: List of episode dicts
        test_mode: If True, enable test mode (direct URL playback)

    Returns:
        TVEveningMonitor instance, or None if session already active
    """
    global _monitor_instance

    # RACE CONDITION GUARD: Prevent starting new session while one is active
    # User could rapidly click "Start TV Evening" twice, or code could call this during cleanup
    if _monitor_instance and _monitor_instance.session_active:
        c.log("[Monitor Singleton] WARNING: Cannot start new session - another session is already active")
        if c.devmode:
            c.log("[Monitor Singleton] Active session: {}, position {}/{}".format(
                _monitor_instance,
                _monitor_instance.current_position,
                len(_monitor_instance.playlist_episodes)
            ))
        return None

    monitor = get_tv_evening_monitor(playlist_episodes, test_mode=test_mode)
    monitor.start_session()
    return monitor
