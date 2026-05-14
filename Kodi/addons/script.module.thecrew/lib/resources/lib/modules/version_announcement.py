# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file version_announcement.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
Version Announcement Dialog
Custom dialog for new version announcements, alpha warnings, and highlights
'''

import os
import xbmc
import xbmcaddon
import xbmcgui

from . import control
from . import version_config
from . import changelog
from .crewruntime import c


class VersionAnnouncementDialog(xbmcgui.WindowXMLDialog):
    """
    Custom dialog for version announcements.
    """

    def __init__(self, *args, **kwargs):
        """Initialize dialog with announcement data."""
        self.version = kwargs.get('version', '')
        self.announcement_type = kwargs.get('announcement_type', 'NEW VERSION')
        self.highlights = kwargs.get('highlights', [])
        self.show_alpha_warning = kwargs.get('show_alpha_warning', False)
        self.changelog_path = kwargs.get('changelog_path', '')
        self.github_url = kwargs.get('github_url', 'https://github.com/classymouse/script.module.thecrew')
        self.action = None

    def onInit(self):
        """Initialize the dialog window."""
        try:
            # Set version
            self.setProperty('version', self.version)

            # Set announcement type
            self.setProperty('announcement_type', self.announcement_type)

            # Set highlights (up to 3)
            for i, highlight in enumerate(self.highlights[:3], 1):
                self.setProperty(f'highlight{i}', highlight)

            # Set alpha warning
            if self.show_alpha_warning:
                self.setProperty('show_alpha_warning', 'true')

            # Set focus on Continue button by default
            self.setFocusId(103)

        except Exception as e:
            c.log(f"[Version Announcement] Error in onInit: {e}")

    def onClick(self, control_id):
        """Handle button clicks."""
        try:
            c.log(f"[Version Announcement] Button clicked: {control_id}")

            if control_id == 101:
                # View Changelog - show but keep dialog open
                c.log("[Version Announcement] Opening changelog...")
                if self.changelog_path and os.path.exists(self.changelog_path):
                    try:
                        with open(self.changelog_path, 'r', encoding='utf-8') as f:
                            changelog_text = f.read()
                        # Use custom LogViewer dialog instead of basic textviewer
                        changelog.log_viewer(changelog_text, 'The Crew Changelog')
                    except Exception as e:
                        c.log(f"[Version Announcement] Error showing changelog: {e}")
                else:
                    control.dialog.ok('Changelog', 'Changelog file not found.')

            elif control_id == 102:
                # Beta/Alpha Info - open browser but keep dialog open
                # Detect if this is beta or alpha based on current version info

                addon = xbmcaddon.Addon('script.module.thecrew')
                current_version = addon.getAddonInfo('version')
                is_beta = 'beta' in current_version.lower()

                info_type = 'Beta' if is_beta else 'Alpha'
                c.log(f"[Version Announcement] Opening {info_type.lower()} info page...")
                info_url = 'https://classymouse.github.io'
                try:
                    import webbrowser
                    webbrowser.open(info_url)
                except:
                    # Fallback: show URL in dialog
                    control.dialog.ok(f'{info_type} Info', f'Visit our website for {info_type.lower()} version information:\n\n{info_url}')
            elif control_id == 103:
                # Close button - close the dialog
                c.log("[Version Announcement] Closing dialog...")
                self.action = 'close'
                self.close()

        except Exception as e:
            c.log(f"[Version Announcement] Error in onClick: {e}")
            import traceback
            c.log(f"[Version Announcement] Traceback: {traceback.format_exc()}")

    def onAction(self, action):
        """Handle keyboard/remote actions."""
        if action.getId() in (9, 10, 92, 216, 247, 257, 275, 61467, 61448):
            # Back/Escape actions - close dialog
            self.action = 'close'
            self.close()


def show_version_announcement(version, announcement_type='NEW VERSION', highlights=None,
                            show_alpha_warning=False, changelog_path=''):
    """
    Show the version announcement dialog.

    Args:
        version (str): Version string to display (e.g., "v2.3.0", "2.2.5-alpha")
        announcement_type (str): Type of announcement (e.g., "NEW VERSION", "UPDATE AVAILABLE")
        highlights (list): List of highlight strings (max 3)
        show_alpha_warning (bool): Whether to show alpha version warning
        changelog_path (str): Path to changelog file

    Returns:
        str: User action ('changelog', 'github', 'close', or None)
    """
    try:
        if highlights is None:
            highlights = []

        # Determine skin path based on user's appearance setting
        appearance = control.setting('appearance.1') or 'modern'
        if appearance not in ['modern', 'thecrew']:
            appearance = 'modern'

        addon = xbmcaddon.Addon('script.thecrew.artwork')
        xml_file = 'VersionAnnouncement.xml'
        skin_path = os.path.join(addon.getAddonInfo('path'), 'resources', 'skins', appearance, '1080i')

        c.log(f"[Version Announcement] Opening dialog: version={version}, type={announcement_type}")
        c.log(f"[Version Announcement] Highlights: {highlights}")
        c.log(f"[Version Announcement] Alpha warning: {show_alpha_warning}")

        dialog = VersionAnnouncementDialog(
            xml_file,
            addon.getAddonInfo('path'),
            appearance,
            '1080i',
            version=version,
            announcement_type=announcement_type,
            highlights=highlights,
            show_alpha_warning=show_alpha_warning,
            changelog_path=changelog_path
        )

        dialog.doModal()
        action = dialog.action

        c.log(f"[Version Announcement] Dialog closed with action: {action}")

        # All actions are now handled inside onClick, so we just clean up
        del dialog
        return action

    except Exception as e:
        c.log(f"[Version Announcement] Error showing dialog: {e}")
        import traceback
        c.log(f"[Version Announcement] Traceback: {traceback.format_exc()}")
        return None


def check_and_show_version_announcement():
    """
    Check if version announcement should be shown and display it.

    This is called from startup_maintenance.
    Shows announcement:
    - Once per version when version changes
    - Always for alpha versions (once per Kodi session)

    Returns:
        bool: True if announcement was shown, False otherwise
    """
    try:
        # Get current versions
        module_addon = xbmcaddon.Addon('script.module.thecrew')
        current_version = module_addon.getAddonInfo('version')

        # Check if version contains 'alpha' or 'beta'
        is_alpha = 'alpha' in current_version.lower()
        is_beta = 'beta' in current_version.lower()

        # Get last shown version from settings
        last_shown_version = control.setting('last_version_announcement') or ''

        # Check if we should show announcement
        should_show = False
        reason = ''

        # For alpha/beta, show once per Kodi session (not persistent)
        if is_alpha or is_beta:
            session_shown = control.window.getProperty('thecrew.version_announcement.shown')
            if session_shown != 'true':
                should_show = True
                reason = 'alpha_session'
        # For stable releases, show once when version changes
        elif current_version != last_shown_version:
            should_show = True
            reason = 'new_version'

        if not should_show:
            c.log(f"[Version Announcement] No announcement needed (current: {current_version}, last: {last_shown_version})")
            return False

        c.log(f"[Version Announcement] Showing announcement for {current_version} (reason: {reason})")

        # Get plugin version too
        try:
            plugin_addon = xbmcaddon.Addon('plugin.video.thecrew')
            plugin_version = plugin_addon.getAddonInfo('version')
            version_display = f"Module v{current_version} | Plugin v{plugin_version}"
        except:
            # Fallback if plugin not found
            version_display = f"v{current_version}"

        # Get announcement data from config
        announcement_data = version_config.get_announcement_data(current_version)

        # Get changelog path
        changelog_path = os.path.join(module_addon.getAddonInfo('path'), 'changelog.txt')

        # Show the dialog
        action = show_version_announcement(
            version=version_display,
            announcement_type=announcement_data['announcement_type'],
            highlights=announcement_data['highlights'],
            show_alpha_warning=announcement_data['show_warning'],
            changelog_path=changelog_path
        )

        # Mark as shown
        if reason == 'new_version':
            # Update last shown version in settings
            control.setSetting('last_version_announcement', current_version)
        elif reason == 'alpha_session':
            # Mark as shown this session (doesn't persist across Kodi restarts)
            control.window.setProperty('thecrew.version_announcement.shown', 'true')

        return True

    except Exception as e:
        c.log(f"[Version Announcement] Error in check_and_show: {e}")
        import traceback
        c.log(f"[Version Announcement] Traceback: {traceback.format_exc()}")
        return False
