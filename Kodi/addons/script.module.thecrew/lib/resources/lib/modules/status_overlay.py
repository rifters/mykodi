# -*- coding: utf-8 -*-
"""
Unified Status Overlay
Replaces flashy popup dialogs with elegant right-side status bar.
Handles: TV Evening countdown, scraping progress, resolving status, etc.
"""

import xbmc
import xbmcgui
import threading
import traceback
from . import control
from .crewruntime import c


class StatusOverlay(xbmcgui.WindowXMLDialog):
    """
    Unified status overlay - elegant right-side bar.
    Replaces multiple popup dialogs with one persistent overlay.

    Usage examples:

    1. TV Evening Countdown:
        overlay = StatusOverlay('StatusOverlay.xml', c.artworkPath,
                                mode='countdown',
                                countdown_seconds=30,
                                message='Starting TV Evening...',
                                episode_data={...})
        overlay.doModal()

    2. Scraping Progress:
        overlay = StatusOverlay('StatusOverlay.xml', c.artworkPath,
                                mode='scraping',
                                message='Searching sources...')
        overlay.show()
        # Update as scraping progresses
        overlay.update_counter(42)  # 42 sources found
        overlay.update_message('Filtering results...')
        overlay.close()

    3. Generic Status:
        overlay = StatusOverlay('StatusOverlay.xml', c.artworkPath,
                                message='Processing...',
                                show_spinner=True)
        overlay.show()
        # ... do work ...
        overlay.close()
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize overlay.

        Args:
            mode: 'countdown', 'scraping', 'resolving', 'generic'
            countdown_seconds: For countdown mode (default 30)
            message: Status message to display
            episode_data: Dict with show info (tvshowtitle, title, thumb, etc.)
            show_spinner: Show animated spinner (default False)
            show_play_button: Show "Play Now" button (default for countdown mode)
            cancelable: Allow cancel button (default True)
        """
        super(StatusOverlay, self).__init__()

        self.mode = kwargs.get('mode', 'generic')
        self.countdown_seconds = kwargs.get('countdown_seconds', 30)
        self.message = kwargs.get('message', '')
        self.episode_data = kwargs.get('episode_data', {})
        self.spinner_enabled = kwargs.get('show_spinner', False)
        self.show_play_button = kwargs.get('show_play_button', self.mode == 'countdown')
        self.cancelable = kwargs.get('cancelable', True)

        self.action_taken = None
        self.cancelled = False
        self.countdown_thread = None

    def onInit(self):
        """Initialize dialog and set window properties."""
        try:
            # Set initial message
            self.setProperty('status.message', self.message)

            # Set episode data if provided
            if self.episode_data:
                self.setProperty('status.show', self.episode_data.get('tvshowtitle', ''))
                self.setProperty('status.episode', self.episode_data.get('title', ''))
                self.setProperty('status.poster', self.episode_data.get('thumb', ''))

            # Show spinner if requested
            if self.spinner_enabled:
                self.setProperty('status.spinning', '1')

            # Show play button if requested
            if self.show_play_button:
                self.setProperty('status.show_play_button', '1')

            # Start countdown if in countdown mode
            if self.mode == 'countdown':
                self.start_countdown()

        except Exception as e:
            c.log(f"[StatusOverlay] Error in onInit: {e}")

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

                self.setProperty('status.counter', str(i))
                xbmc.sleep(1000)

                # Check if user clicked a button
                action = self.getProperty('status.action')
                if action != '':
                    self.action_taken = action
                    self.close()
                    return

            # Countdown finished - auto-play
            if not self.cancelled:
                self.setProperty('status.action', 'play')
                self.action_taken = 'play'
                self.close()
        except Exception as e:
            c.log(f"[StatusOverlay] Error in countdown loop: {e}")

    def update_message(self, message):
        """
        Update the status message dynamically.

        Args:
            message: New message to display
        """
        try:
            self.setProperty('status.message', message)
            c.log(f"[StatusOverlay] Updated message: {message}")
        except Exception as e:
            c.log(f"[StatusOverlay] Error updating message: {e}")

    def update_counter(self, count):
        """
        Update the counter/progress display.

        Args:
            count: Number to display (sources found, etc.)
        """
        try:
            self.setProperty('status.counter', str(count))
        except Exception as e:
            c.log(f"[StatusOverlay] Error updating counter: {e}")

    def set_episode_data(self, episode_data):
        """
        Update episode information dynamically.

        Args:
            episode_data: Dict with show info (tvshowtitle, title, thumb)
        """
        try:
            self.setProperty('status.show', episode_data.get('tvshowtitle', ''))
            self.setProperty('status.episode', episode_data.get('title', ''))
            self.setProperty('status.poster', episode_data.get('thumb', ''))
        except Exception as e:
            c.log(f"[StatusOverlay] Error setting episode data: {e}")

    def show_spinner(self, show=True):
        """Toggle spinner visibility."""
        try:
            if show:
                self.setProperty('status.spinning', '1')
            else:
                self.clearProperty('status.spinning')
        except Exception as e:
            c.log(f"[StatusOverlay] Error toggling spinner: {e}")

    def onClick(self, controlID):
        """Handle button clicks."""
        try:
            if controlID == 200:  # Play Now button
                self.cancelled = True
                self.setProperty('status.action', 'play')
                self.action_taken = 'play'
                self.close()
            elif controlID == 201:  # Cancel button
                self.cancelled = True
                self.setProperty('status.action', 'cancel')
                self.action_taken = 'cancel'
                self.close()
        except Exception as e:
            c.log(f"[StatusOverlay] Error in onClick: {e}")

    def onAction(self, action):
        """Handle actions (ESC, back button, etc.)."""
        if self.cancelable and action.getId() in [9, 10, 92, 216, 247, 257, 275, 61467, 61448]:
            self.cancelled = True
            self.setProperty('status.action', 'cancel')
            self.action_taken = 'cancel'
            self.close()

    def cleanup(self):
        """Clean up window properties."""
        try:
            self.clearProperty('status.message')
            self.clearProperty('status.counter')
            self.clearProperty('status.show')
            self.clearProperty('status.episode')
            self.clearProperty('status.poster')
            self.clearProperty('status.spinning')
            self.clearProperty('status.show_play_button')
            self.clearProperty('status.action')
        except Exception as e:
            c.log(f"[StatusOverlay] Error in cleanup: {e}")

    def close(self):
        """Close the dialog and clean up."""
        self.cancelled = True
        self.cleanup()
        super(StatusOverlay, self).close()


# ==================== CONVENIENCE FUNCTIONS ====================

def show_tv_evening_countdown(episode_data, countdown_seconds=30):
    """
    Show TV Evening countdown overlay.

    Args:
        episode_data: Dict with show info (tvshowtitle, title, thumb, etc.)
        countdown_seconds: Countdown duration (default 30)

    Returns:
        'play' or 'cancel' based on user action
    """
    try:
        skin = c.appearance() or 'thecrew'
        if skin in ['-', '']:
            skin = 'thecrew'
        addon_path = c.get_artwork_path()

        import os
        xml_full_path = os.path.join(addon_path, 'resources', 'skins', skin, '1080i', 'StatusOverlay.xml')
        c.log(f"[StatusOverlay] Attempting to load: xml='StatusOverlay.xml', addon_path='{addon_path}', skin='{skin}'")
        c.log(f"[StatusOverlay] Complete XML path: {xml_full_path}")
        c.log(f"[StatusOverlay] XML file exists: {os.path.exists(xml_full_path)}")

        overlay = StatusOverlay(
            'StatusOverlay.xml',
            addon_path,
            skin,
            mode='countdown',
            countdown_seconds=countdown_seconds,
            message='Starting TV Evening...',
            episode_data=episode_data,
            show_play_button=True
        )
        overlay.doModal()
        return overlay.action_taken or 'cancel'
    except Exception as e:
        c.log(f"[StatusOverlay] Error showing TV Evening countdown: {e}")
        c.log(f"[StatusOverlay] Traceback: {traceback.format_exc()}")
        return 'cancel'


def show_scraping_progress(episode_data=None, initial_message='Searching sources...'):
    """
    Show scraping progress overlay (non-modal, can be updated).

    Args:
        episode_data: Optional dict with show info
        initial_message: Initial status message

    Returns:
        StatusOverlay instance (call .update_message(), .update_counter(), .close())
    """
    try:
        skin = c.appearance() or 'thecrew'
        addon_path = c.get_artwork_path()

        import os
        xml_full_path = os.path.join(addon_path, 'resources', 'skins', skin, '1080i', 'StatusOverlay.xml')
        c.log(f"[StatusOverlay] Scraping overlay - Complete XML path: {xml_full_path}, exists: {os.path.exists(xml_full_path)}")

        overlay = StatusOverlay(
            'StatusOverlay.xml',
            addon_path,
            skin,
            mode='scraping',
            message=initial_message,
            episode_data=episode_data,
            show_spinner=True,
            show_play_button=False
        )
        overlay.show()
        return overlay
    except Exception as e:
        c.log(f"[StatusOverlay] Error showing scraping progress: {e}")
        return None


def show_resolving_status(message='Resolving source...'):
    """
    Show resolving status overlay.

    Args:
        message: Status message

    Returns:
        StatusOverlay instance (call .close() when done)
    """
    try:
        skin = c.appearance() or 'thecrew'
        addon_path = c.get_artwork_path()

        import os
        xml_full_path = os.path.join(addon_path, 'resources', 'skins', skin, '1080i', 'StatusOverlay.xml')
        c.log(f"[StatusOverlay] Resolving overlay - Complete XML path: {xml_full_path}, exists: {os.path.exists(xml_full_path)}")

        overlay = StatusOverlay(
            'StatusOverlay.xml',
            addon_path,
            skin,
            mode='resolving',
            message=message,
            show_spinner=True,
            show_play_button=False,
            cancelable=False
        )
        overlay.show()
        return overlay
    except Exception as e:
        c.log(f"[StatusOverlay] Error showing resolving status: {e}")
        return None


def show_generic_status(message, show_spinner=False, cancelable=True):
    """
    Show generic status overlay.

    Args:
        message: Status message
        show_spinner: Show animated spinner
        cancelable: Allow cancel button

    Returns:
        StatusOverlay instance (call .close() when done)
    """
    try:
        skin = c.appearance() or 'thecrew'
        addon_path = c.get_artwork_path()

        import os
        xml_full_path = os.path.join(addon_path, 'resources', 'skins', skin, '1080i', 'StatusOverlay.xml')
        c.log(f"[StatusOverlay] Generic overlay - Complete XML path: {xml_full_path}, exists: {os.path.exists(xml_full_path)}")

        overlay = StatusOverlay(
            'StatusOverlay.xml',
            addon_path,
            skin,
            mode='generic',
            message=message,
            show_spinner=show_spinner,
            show_play_button=False,
            cancelable=cancelable
        )
        overlay.show()
        return overlay
    except Exception as e:
        c.log(f"[StatusOverlay] Error showing generic status: {e}")
        return None
