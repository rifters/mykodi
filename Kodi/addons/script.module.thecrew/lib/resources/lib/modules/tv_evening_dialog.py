# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 * @file tv_evening_dialog.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2025, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

import xbmc
import xbmcgui
import traceback
from .crewruntime import c


class TVEveningPlaylistDialog(xbmcgui.WindowXMLDialog):
    """
    Custom dialog for displaying TV Evening playlist with posters and nice UI.
    """

    def __init__(self, *args, **kwargs):
        """Initialize dialog with playlist data."""
        xbmcgui.WindowXMLDialog.__init__(self)
        self.playlist = kwargs.get('playlist', [])
        self.user_action = None
        c.log(f"[TV Evening Dialog] Initialized with {len(self.playlist)} episodes")

    def onInit(self):
        """Called when dialog is initialized."""
        try:
            c.log("[TV Evening Dialog] onInit called")

            # Set background fanart from first episode's show
            if self.playlist:
                first_ep = self.playlist[0]
                fanart = first_ep.get('fanart', '')
                if not fanart:
                    # Try to get poster as fallback
                    fanart = first_ep.get('poster', '')
                if fanart:
                    self.setProperty('fanart', fanart)
                    c.log(f"[TV Evening Dialog] Set fanart: {fanart[:100]}")

            # Calculate and set runtime info
            total_runtime = sum(int(ep.get('duration', 45)) for ep in self.playlist)
            hours = total_runtime // 60
            minutes = total_runtime % 60
            runtime_text = f"{len(self.playlist)} episodes • {total_runtime} minutes ({hours}h {minutes}m)"
            self.setProperty('runtime_text', runtime_text)
            c.log(f"[TV Evening Dialog] Runtime: {runtime_text}")

            # Populate episode list
            list_control = self.getControl(9001)
            list_control.reset()

            for i, ep in enumerate(self.playlist, 1):
                # Create list item
                show_title = ep.get('tvshowtitle', 'Unknown Show')
                season = ep.get('season', 1)
                episode = ep.get('episode', 1)
                episode_title = ep.get('title', 'Unknown Episode')
                runtime = int(ep.get('duration', 45))
                thumb = ep.get('thumb', '') or ep.get('poster', '')

                # Label shows just the show name
                label = show_title

                list_item = xbmcgui.ListItem(label=label)
                list_item.setArt({'icon': thumb, 'thumb': thumb})

                # Set properties for XML display
                list_item.setProperty('episode_num', f"S{season:02d}E{episode:02d}")
                list_item.setProperty('episode_title', episode_title)
                list_item.setProperty('runtime', str(runtime))

                list_control.addItem(list_item)

            c.log(f"[TV Evening Dialog] Added {list_control.size()} items to list")

            # Set focus to first button
            self.setFocusId(9010)

        except Exception as e:
            c.log(f"[TV Evening Dialog] Error in onInit: {e}", 1)
            c.log(f"[TV Evening Dialog] Traceback: {traceback.format_exc()}", 1)

    def onClick(self, controlId):
        """Handle button and list clicks."""
        try:
            c.log(f"[TV Evening Dialog] Control clicked: {controlId}")

            if controlId == 9001:  # Episode list clicked
                # Get selected episode
                list_control = self.getControl(9001)
                selected_pos = list_control.getSelectedPosition()

                if selected_pos < len(self.playlist):
                    ep = self.playlist[selected_pos]
                    self.show_episode_info(ep)

            elif controlId == 9010:  # Play All
                self.user_action = 'play'
                self.setProperty('user_action', 'play_all')
                c.log("[TV Evening Dialog] User chose: Play All")
                self.close()
            elif controlId == 9011:  # Play First
                self.user_action = 'first'
                self.setProperty('user_action', 'play_first')
                c.log("[TV Evening Dialog] User chose: Play First")
                self.close()
            elif controlId == 9012:  # Cancel
                self.user_action = None
                self.setProperty('user_action', 'cancel')
                c.log("[TV Evening Dialog] User chose: Cancel")
                self.close()

        except Exception as e:
            c.log(f"[TV Evening Dialog] Error in onClick: {e}", 1)

    def show_episode_info(self, episode):
        """Show detailed info for an episode using custom dialog."""
        try:
            show_title = episode.get('tvshowtitle', 'Unknown Show')
            season = episode.get('season', 1)
            ep_num = episode.get('episode', 1)
            ep_title = episode.get('title', 'Unknown Episode')
            plot = episode.get('plot', 'No plot available.')
            runtime = int(episode.get('duration', 45))
            thumb = episode.get('thumb', '') or episode.get('poster', '')

            c.log(f"[TV Evening Dialog] Showing info for {show_title} S{season:02d}E{ep_num:02d}")

            # Get addon path and skin
            addon_path = c.get_artwork_path()
            skin = c.appearance() or 'thecrew'
            if skin in ['-', '']:
                skin = 'thecrew'

            # Create and show custom info dialog
            info_dialog = EpisodeInfoDialog(
                'EpisodeInfo.xml',
                addon_path,
                skin,
                '1080i',
                show_title=show_title,
                episode_badge=f"S{season:02d}E{ep_num:02d}",
                episode_title=ep_title,
                runtime=str(runtime),
                plot=plot,
                episode_poster=thumb
            )

            info_dialog.doModal()
            del info_dialog

            c.log("[TV Evening Dialog] Info dialog closed, restoring focus")

            # Restore focus to the episode list
            try:
                self.setFocusId(9001)
            except:
                pass

        except Exception as e:
            c.log(f"[TV Evening Dialog] Error showing episode info: {e}", 1)
            c.log(f"[TV Evening Dialog] Traceback: {traceback.format_exc()}", 1)

    def get_user_action(self):
        """Return the user's choice."""
        return self.user_action


class EpisodeInfoDialog(xbmcgui.WindowXMLDialog):
    """
    Custom dialog for displaying detailed episode information.
    Shows season poster, show title, episode details, and plot.
    """

    def __init__(self, *args, **kwargs):
        """Initialize dialog with episode data."""
        # Extract episode info from kwargs before passing to parent
        self.show_title = kwargs.pop('show_title', 'Unknown Show')
        self.episode_badge = kwargs.pop('episode_badge', 'S01E01')
        self.episode_title = kwargs.pop('episode_title', 'Unknown Episode')
        self.runtime = kwargs.pop('runtime', '45')
        self.plot = kwargs.pop('plot', 'No plot available.')
        self.episode_poster = kwargs.pop('episode_poster', '')

        # Initialize parent with XML arguments
        xbmcgui.WindowXMLDialog.__init__(self, *args, **kwargs)

        c.log(f"[Episode Info Dialog] Initialized: {self.show_title} {self.episode_badge}")

    def onInit(self):
        """Set all window properties from episode data."""
        try:
            # Set all window properties for the XML to display
            self.setProperty('episode_poster', self.episode_poster)
            self.setProperty('show_title', self.show_title)
            self.setProperty('episode_badge', self.episode_badge)
            self.setProperty('episode_title', self.episode_title)
            self.setProperty('runtime', self.runtime)
            self.setProperty('plot', self.plot)

            c.log(f"[Episode Info Dialog] Properties set for {self.show_title} {self.episode_badge}")

        except Exception as e:
            c.log(f"[Episode Info Dialog] Error in onInit: {e}", 1)

    def onClick(self, controlId):
        """Handle button clicks."""
        if controlId == 9000:  # OK button
            c.log("[Episode Info Dialog] OK clicked, closing")
            self.close()

    def onAction(self, action):
        """Handle keyboard/remote actions."""
        # Consume back/escape actions to prevent propagation to parent dialog
        if action in [xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK]:
            c.log("[Episode Info Dialog] Back action, closing")
            self.close()


def show_tv_evening_playlist(playlist):
    """
    Show TV Evening playlist dialog.

    :param list playlist: List of episode data dicts
    :return: User choice ('play', 'first', or None for cancel)
    :rtype: str or None
    """
    try:
        c.log(f"[TV Evening Dialog] Showing playlist with {len(playlist)} episodes")

        # Get addon path and skin from crewruntime
        addon_path = c.get_artwork_path()
        skin = c.appearance() or 'thecrew'
        if skin in ['-', '']:
            skin = 'thecrew'

        c.log(f"[TV Evening Dialog] Using addon_path='{addon_path}', skin='{skin}'")

        dialog = TVEveningPlaylistDialog(
            'TVEveningPlaylist.xml',
            addon_path,
            skin,
            '1080i',
            playlist=playlist
        )

        # Show dialog (modal - waits for user interaction)
        dialog.doModal()

        # Get user's choice
        user_action = dialog.get_user_action()
        c.log(f"[TV Evening Dialog] User action: {user_action}")

        # Clean up
        del dialog

        return user_action

    except Exception as e:
        c.log(f"[TV Evening Dialog] Error showing dialog: {e}", 1)
        c.log(f"[TV Evening Dialog] Traceback: {traceback.format_exc()}", 1)

        # Fallback to default behavior
        return 'play'
