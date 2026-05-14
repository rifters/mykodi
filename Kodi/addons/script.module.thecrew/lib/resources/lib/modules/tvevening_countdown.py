# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file tvevening_countdown.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
TV Evening Countdown Dialog
Shows countdown screen between episodes while fetching and validating next episode.
'''


import xbmc
import xbmcgui
import threading
import time

from .crewruntime import c


class TVEveningCountdown(xbmcgui.WindowXMLDialog):
    """
    Countdown dialog shown between TV Evening episodes.

    Displays:
    - Countdown timer (60 seconds default)
    - Next episode info
    - Progress messages ("Fetching episode...", "Checking sources...", etc.)
    - Play Now button (skip countdown)
    - Stop Playlist button (exit TV Evening)
    """

    # Control IDs from XML
    STATUS_LABEL = 9001
    TITLE_LABEL = 9002
    COUNTDOWN_LABEL = 9003
    MESSAGES_TEXTBOX = 9004
    PLAY_NOW_BUTTON = 5
    CANCEL_BUTTON = 6

    def __init__(self, *args, **kwargs):
        self.next_episode = kwargs.get('next_episode', {})
        self.countdown_seconds = kwargs.get('countdown', 60)
        self.callback = kwargs.get('callback', None)

        self.user_choice = None  # 'play', 'cancel', or None (auto-continue)
        self.countdown_thread = None
        self.stop_countdown = False
        self._stop_event = threading.Event()
        self.current_countdown = self.countdown_seconds
        self.messages = []
        self.tmdb_img_link = 'https://image.tmdb.org/t/p/%s%s'

        xbmcgui.WindowXMLDialog.__init__(self)

    def onInit(self):
        """Called when dialog opens."""
        # Set show title (just the show name)
        show_title = self.next_episode.get('tvshowtitle', 'Unknown')
        self.setProperty('show_title', show_title)

        # Set episode number (formatted)
        season = self.next_episode.get('season', 0)
        episode = self.next_episode.get('episode', 0)
        episode_number = f"S{season:02d}E{episode:02d}"
        self.setProperty('episode_number', episode_number)

        # Set episode title
        episode_title = self.next_episode.get('title', 'Episode {}'.format(episode))
        self.setProperty('episode_title', episode_title)

        # Set plot
        plot = self.next_episode.get('plot', '')
        self.setProperty('episode_plot', plot)

        # Set poster
        poster = self.next_episode.get('poster', '')
        if poster:
            self.setProperty('episode_poster', poster)

        # Set fanart with fallback to addon fanart
        fanart = self.next_episode.get('fanart', '')
        if not fanart:
            fanart = c.addon_fanart()
        self.setProperty('fanart', fanart)

        # Set cast properties for leading roles (already formatted from database)
        cast_leads = self.next_episode.get('cast_leads', [])
        c.log(f"[TV Evening Countdown] Setting cast properties - found {len(cast_leads)} leads")

        # Fallback image for missing actor photos - use neutral poster placeholder
        fallback_thumb = 'special://home/addons/script.thecrew.artwork/resources/media/thecrew/poster.png'

        for i, lead in enumerate(cast_leads[:3], 1):
            name = lead.get('name', '')
            character = lead.get('character', '')
            thumb = lead.get('thumb', '') or fallback_thumb  # Use fallback if no thumb

            self.setProperty(f'lead{i}_name', name)
            self.setProperty(f'lead{i}_character', character)
            self.setProperty(f'lead{i}_thumb', thumb)
            if c.devmode:
                c.log(f"[TV Evening Countdown] Set lead{i}: {name} as {character}, thumb: {thumb[:50] if thumb else 'none'}")

        # Set cast properties for guest roles (3 guests for 2x3 grid)
        cast_guests = self.next_episode.get('cast_guests', [])
        c.log(f"[TV Evening Countdown] Setting cast properties - found {len(cast_guests)} guests")

        for i, guest in enumerate(cast_guests[:3], 1):
            name = guest.get('name', '')
            character = guest.get('character', '')
            thumb = guest.get('thumb', '') or fallback_thumb  # Use fallback if no thumb

            self.setProperty(f'guest{i}_name', name)
            self.setProperty(f'guest{i}_character', character)
            self.setProperty(f'guest{i}_thumb', thumb)
            if c.devmode:
                c.log(f"[TV Evening Countdown] Set guest{i}: {name} as {character}, thumb: {thumb[:50] if thumb else 'none'}")

        # Start countdown
        self.start_countdown()

        # Set focus to Play Now button (defensive - XML defaultcontrol should handle this)
        try:
            self.setFocusId(self.PLAY_NOW_BUTTON)
        except Exception as e:
            c.log(f"[TV Evening Countdown] Could not set focus to button {self.PLAY_NOW_BUTTON}: {e}")
            # Not fatal - defaultcontrol in XML will handle focus

    def start_countdown(self):
        """Start countdown timer in background thread."""
        self.stop_countdown = False
        self._stop_event.clear()
        self.countdown_thread = threading.Thread(target=self._countdown_loop)
        self.countdown_thread.daemon = True
        self.countdown_thread.start()

    def _countdown_loop(self):
        """Background thread that updates countdown every second."""
        while not self.stop_countdown and self.current_countdown > 0:
            # Update countdown label
            try:
                self.getControl(self.COUNTDOWN_LABEL).setLabel(str(self.current_countdown))
            except:
                pass  # Dialog might be closing

            # Wait 1 second — wakes immediately if stop is requested
            self._stop_event.wait(1)
            self.current_countdown -= 1

        # Countdown finished - auto-continue
        if not self.stop_countdown and self.current_countdown <= 0:
            self.user_choice = 'play'
            self.close()

    def update_status(self, message):
        """Update status message at top of dialog."""
        try:
            self.getControl(self.STATUS_LABEL).setLabel(message)
        except:
            pass

    def add_message(self, message):
        """Add progress message to scrolling textbox."""
        self.messages.append(f"• {message}")
        # Keep last 5 messages
        if len(self.messages) > 5:
            self.messages.pop(0)

        try:
            self.getControl(self.MESSAGES_TEXTBOX).setText('[CR]'.join(self.messages))
        except:
            pass

    def onClick(self, controlId):
        """Handle button clicks."""
        if controlId == self.PLAY_NOW_BUTTON:
            # User clicked Play Now
            self.user_choice = 'play'
            self.stop_countdown = True
            self._stop_event.set()
            self.close()

        elif controlId == self.CANCEL_BUTTON:
            # User clicked Cancel - confirm first
            if xbmcgui.Dialog().yesno('Stop TV Evening', 'Are you sure you want to stop the playlist?'):
                self.user_choice = 'cancel'
                self.stop_countdown = True
                self._stop_event.set()
                self.close()

    def onAction(self, action):
        """Handle remote control actions."""
        # ESC or Back button
        if action.getId() in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            # Treat ESC like Cancel button
            if xbmcgui.Dialog().yesno('Stop TV Evening', 'Are you sure you want to stop the playlist?'):
                self.user_choice = 'cancel'
                self.stop_countdown = True
                self._stop_event.set()
                self.close()

    def get_user_choice(self):
        """Return user's choice after dialog closes."""
        return self.user_choice


def show_countdown(next_episode, countdown_seconds=60):
    """
    Show countdown dialog and return user's choice.

    Args:
        next_episode: Dict with next episode metadata
        countdown_seconds: Countdown duration (default 60)

    Returns:
        'play': User clicked Play Now or countdown finished
        'cancel': User cancelled the playlist
        None: Dialog was interrupted
    """
    from resources.lib.modules import control as c

    try:
        # Get user's theme preference (modern or thecrew)
        theme = c.appearance() or 'thecrew'

        dialog = TVEveningCountdown(
            'TVEveningCountdown.xml',
            xbmcgui.Window(10000).getProperty('script.thecrew.artwork.path'),
            theme,
            '1080i',
            next_episode=next_episode,
            countdown=countdown_seconds
        )
        dialog.doModal()
        choice = dialog.get_user_choice()
        del dialog
        return choice
    except Exception as e:
        xbmc.log(f"[TV Evening] Error showing countdown dialog: {e}", xbmc.LOGERROR)
        return 'play'  # Default to continuing on error
