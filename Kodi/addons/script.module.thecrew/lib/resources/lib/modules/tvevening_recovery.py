# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file tvevening_recovery.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
TV Evening Recovery System

Detects and handles stale TV Evening sessions after Kodi crashes or restarts.
Provides user options to continue, start fresh, or delete the stale playlist.
'''

import xbmc
from . import control
from . import tvevening_playlist_db
from . import tv_evening_recovery_dialog
from .crewruntime import c


def has_stale_session():
    """
    Check if there's a stale TV Evening session.

    A session is "stale" if:
    - Database has episodes (size > 0)
    - Monitor is NOT currently active
    - This indicates Kodi crashed or was closed during playback

    :return: True if stale session exists
    :rtype: bool
    """
    try:
        # Check database
        db = tvevening_playlist_db.get_playlist_db()
        playlist_size = db.get_playlist_size()

        if playlist_size == 0:
            return False

        # Check if monitor is currently active
        monitor_active = control.window.getProperty('thecrew.tvevening.monitor.active')

        # Stale session = has playlist but monitor not active
        is_stale = (playlist_size > 0 and monitor_active != 'true')

        if is_stale:
            c.log(f"[TV Evening Recovery] Stale session detected: {playlist_size} episodes, monitor_active={monitor_active}")

        return is_stale

    except Exception as e:
        c.log(f"[TV Evening Recovery] Error checking for stale session: {e}")
        return False


def get_session_info():
    """
    Get information about the stale session.

    :return: Dict with session info (playlist_size, current_position, episodes)
    :rtype: dict
    """
    try:
        db = tvevening_playlist_db.get_playlist_db()

        playlist_size = db.get_playlist_size()
        current_position = int(control.window.getProperty('thecrew.tvevening.position') or '0')

        # Get episode titles for context
        episodes = db.get_all_episodes()
        episode_titles = [
            f"{ep.get('tvshowtitle', 'Unknown')} S{ep.get('season', 0):02d}E{ep.get('episode', 0):02d}"
            for ep in episodes
        ]

        return {
            'playlist_size': playlist_size,
            'current_position': current_position,
            'episodes': episodes,
            'episode_titles': episode_titles
        }

    except Exception as e:
        c.log(f"[TV Evening Recovery] Error getting session info: {e}")
        return None


def handle_recovery():
    """
    Main recovery handler - shows dialog and handles user choice.

    Returns the user's choice for the navigator to act on.

    :return: User choice ('continue', 'fresh', 'delete', or None if no stale session)
    :rtype: str or None
    """
    try:
        # Check if there's a stale session
        if not has_stale_session():
            return None

        c.log("[TV Evening Recovery] Handling stale session recovery")

        # Get session info
        session_info = get_session_info()
        if not session_info:
            c.log("[TV Evening Recovery] Could not get session info")
            return None

        playlist_size = session_info['playlist_size']
        current_position = session_info['current_position']
        episode_titles = session_info['episode_titles']

        # Show recovery dialog
        user_choice = tv_evening_recovery_dialog.show_recovery_dialog(
            playlist_size,
            current_position,
            episode_titles
        )

        c.log(f"[TV Evening Recovery] User choice: {user_choice}")

        # Handle user choice
        if user_choice == 'continue':
            # Continue from where they left off
            c.log("[TV Evening Recovery] User chose to continue playlist")
            return 'continue'

        elif user_choice == 'fresh':
            # Clear and start fresh
            c.log("[TV Evening Recovery] User chose to start fresh")
            clear_stale_session()
            return 'fresh'

        elif user_choice == 'delete':
            # Just delete the stale data
            c.log("[TV Evening Recovery] User chose to delete playlist")
            clear_stale_session()
            return 'delete'

        else:
            # Dialog was cancelled or error occurred
            c.log("[TV Evening Recovery] Dialog cancelled or error")
            return None

    except Exception as e:
        c.log(f"[TV Evening Recovery] Error in handle_recovery: {e}")
        import traceback
        c.log(f"[TV Evening Recovery] Traceback: {traceback.format_exc()}")
        return None


def clear_stale_session():
    """
    Clear stale session data.

    Removes:
    - All episodes from database
    - Metadata
    - Window properties
    """
    try:
        c.log("[TV Evening Recovery] Clearing stale session")

        # Clear database
        db = tvevening_playlist_db.get_playlist_db()
        db.clear_playlist()

        # Clear window properties
        control.window.clearProperty('thecrew.tvevening.monitor.active')
        control.window.clearProperty('thecrew.tvevening.position')
        control.window.clearProperty('thecrew.tvevening.total')
        control.window.clearProperty('thecrew.tvevening.current.title')
        control.window.clearProperty('thecrew.tvevening.current.show')
        control.window.clearProperty('thecrew.tvevening.next.title')
        control.window.clearProperty('thecrew.tvevening.next.show')

        # Clear Kodi playlist
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        playlist.clear()

        c.log("[TV Evening Recovery] Stale session cleared")
        return True

    except Exception as e:
        c.log(f"[TV Evening Recovery] Error clearing stale session: {e}")
        return False


def resume_session(session_info):
    """
    Resume a stale session from where it left off.

    :param dict session_info: Session info from get_session_info()
    :return: True if resume successful
    :rtype: bool
    """
    try:
        c.log("[TV Evening Recovery] Resuming session")

        # This will be called by tvevening.py to resume playback
        # For now, just log - the actual resume logic will be in tvevening.py
        c.log(f"[TV Evening Recovery] Resume info: position={session_info['current_position']}, "
              f"total={session_info['playlist_size']}")

        return True

    except Exception as e:
        c.log(f"[TV Evening Recovery] Error resuming session: {e}")
        return False
