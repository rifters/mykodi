# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file tvevening_complete.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
TV Evening Completion Dialog
Shows a friendly completion message when TV Evening playlist finishes.
'''

import datetime
import threading
import time

import xbmc
import xbmcgui

from .crewruntime import c


class TVEveningComplete(xbmcgui.WindowXMLDialog):
    """
    Completion dialog shown when TV Evening playlist finishes.
    Features:
    - Time-based greeting (morning/afternoon/evening)
    - Auto-close countdown (30 seconds)
    - Stats about episodes watched
    """

    def __init__(self, *args, **kwargs):
        """Initialize the completion dialog."""
        xbmcgui.WindowXMLDialog.__init__(self)

        self.episodes_watched = kwargs.get('episodes_watched', 0)
        self.fanart = kwargs.get('fanart', '')

        self.countdown_seconds = 30
        self.countdown_active = True
        self.user_closed = False
        self._stop_event = threading.Event()

    def onInit(self):
        """Initialize the dialog UI."""
        c.log("[TV Evening Complete] Initializing completion dialog")

        # Set fanart background with fallback to addon fanart
        fanart = self.fanart if self.fanart else c.addon_fanart()
        self.setProperty('fanart', fanart)

        # Set time-based greeting
        greeting = self._get_time_based_greeting()
        self.setProperty('greeting', greeting)

        # Set stats
        if self.episodes_watched > 0:
            self.setProperty('stats', 'You watched {} episode{}'.format(
                self.episodes_watched,
                's' if self.episodes_watched > 1 else ''
            ))

        # Start countdown timer
        self._start_countdown()

    def _get_time_based_greeting(self):
        """Get greeting based on time of day."""
        now = datetime.datetime.now()
        hour = now.hour

        if 5 <= hour < 12:
            return "Have a great day!"
        elif 12 <= hour < 17:
            return "Enjoy your day!"
        elif 17 <= hour < 22:
            return "Have a wonderful evening!"
        else:
            return "Sleep well!"

    def _start_countdown(self):
        """Start the auto-close countdown."""
        self._stop_event.clear()
        countdown_thread = threading.Thread(target=self._countdown_loop)
        countdown_thread.daemon = True
        countdown_thread.start()

    def _countdown_loop(self):
        """Countdown loop from 30 to 0."""
        for remaining in range(self.countdown_seconds, 0, -1):
            if not self.countdown_active or self.user_closed:
                break

            # Update timer display
            self.setProperty('timer', 'Closing in {} second{}...'.format(
                remaining,
                's' if remaining > 1 else ''
            ))

            # Wait 1 second — wakes immediately if stop is requested
            self._stop_event.wait(1)

        # Auto-close if user didn't close manually
        if self.countdown_active and not self.user_closed:
            c.log("[TV Evening Complete] Auto-closing after {} seconds".format(self.countdown_seconds))
            self.close()

    def onClick(self, controlID):
        """Handle button clicks."""
        if controlID == 5:  # Close button
            c.log("[TV Evening Complete] User clicked Close")
            self.user_closed = True
            self.countdown_active = False
            self._stop_event.set()
            self.close()

    def onAction(self, action):
        """Handle user actions."""
        # Close on back/escape
        if action.getId() in (9, 10, 92, 216, 247, 257, 275, 61467, 61448):
            c.log("[TV Evening Complete] User pressed back/escape")
            self.user_closed = True
            self.countdown_active = False
            self._stop_event.set()
            self.close()


def show_completion_dialog(episodes_watched=0, fanart=''):
    """
    Show the TV Evening completion dialog.

    Args:
        episodes_watched: Number of episodes in the completed playlist
        fanart: Fanart image URL for background

    Returns:
        None
    """
    c.log("[TV Evening Complete] Showing completion dialog: {} episodes watched".format(episodes_watched))

    import xbmcaddon
    artwork_addon = xbmcaddon.Addon('script.thecrew.artwork')
    addon_path = artwork_addon.getAddonInfo('path')

    # Get user's theme preference (modern or thecrew)
    theme = c.appearance() or 'thecrew'
    c.log(f"[TV Evening Complete] Using theme: {theme}")

    dialog = TVEveningComplete(
        'TVEveningComplete.xml',
        addon_path,
        theme,
        episodes_watched=episodes_watched,
        fanart=fanart
    )

    dialog.doModal()
    del dialog

    c.log("[TV Evening Complete] Completion dialog closed")
