# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file changelog.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''
import os

import xbmcgui
import xbmcaddon


from . import control
from .crewruntime import c


ADDON = xbmcaddon.Addon()
ADDON_INFO = ADDON.getAddonInfo
ADDON_PATH = control.transPath(ADDON_INFO('path'))
ARTADDON_PATH = xbmcaddon.Addon('script.thecrew.artwork').getAddonInfo('path')
MODULEADDON_PATH = xbmcaddon.Addon('script.module.thecrew').getAddonInfo('path')
CHANGELOG_FILE = os.path.join(MODULEADDON_PATH, 'changelog.txt')


TITLE = '[B]' + ADDON_INFO('name') + ' v.' + ADDON_INFO('version') + '[/B]'


def get():
    try:
        r = open(CHANGELOG_FILE, 'r', encoding='utf-8')
        text = r.read()
        log_viewer(str(text))
    except Exception as e:
        c.log(f'Exception raised in changelog: error = {e}')

def log_viewer(message: str, header = ''):

    class LogViewer(xbmcgui.WindowXMLDialog):
        # Key action IDs for navigation
        ACTION_PREVIOUS_MENU = 10
        ACTION_NAV_BACK = 92
        ACTION_SELECT_ITEM = 7
        ACTION_MOUSE_CLICK = 100
        ACTION_MOUSE_DOUBLE_CLICK = 103
        ACTION_MOUSE_WHEEL_UP = 104
        ACTION_MOUSE_WHEEL_DOWN = 105
        ACTION_MOVE_UP = 3
        ACTION_MOVE_DOWN = 4
        ACTION_PAGE_UP = 5
        ACTION_PAGE_DOWN = 6
        ACTION_FIRST_PAGE = 159  # Home key
        ACTION_LAST_PAGE = 160   # End key

        # XML control IDs
        HEADER = 101
        TEXT = 102
        SCROLLBAR = 103
        CLOSEBUTTON = 201

        def onInit(self):
            """Initialize the dialog with content."""
            try:
                HEADERTITLE = TITLE if header == '' else header
                self.getControl(self.HEADER).setLabel(HEADERTITLE)
                self.getControl(self.TEXT).setText(message)
                # Focus will be set to close button by defaultcontrol in XML
            except Exception as e:
                c.log(f'[LogViewer] Error in onInit: {e}')

        def onAction(self, action):
            """Handle all keyboard, remote, and mouse actions."""
            try:
                action_id = action.getId()

                # Close dialog actions
                if action_id in [self.ACTION_PREVIOUS_MENU, self.ACTION_NAV_BACK]:
                    self.close()
                    return

                # Get currently focused control
                try:
                    focused_control_id = self.getFocusId()
                except:
                    focused_control_id = None

                # Handle scrolling actions
                # Mousewheel scrolling works no matter what's focused (3 lines)
                if action_id == self.ACTION_MOUSE_WHEEL_UP:
                    for _ in range(3):
                        self.getControl(self.TEXT).scroll(1)
                    return

                elif action_id == self.ACTION_MOUSE_WHEEL_DOWN:
                    for _ in range(3):
                        self.getControl(self.TEXT).scroll(-1)
                    return

                # Page up/down and Home/End work when scrollbar or close button is focused
                # (Don't intercept arrow keys - let them navigate between close button and scrollbar)
                if focused_control_id in [self.SCROLLBAR, self.CLOSEBUTTON]:
                    # Page up - scroll more
                    if action_id == self.ACTION_PAGE_UP:
                        for _ in range(10):
                            self.getControl(self.TEXT).scroll(1)
                        return

                    # Page down - scroll more
                    elif action_id == self.ACTION_PAGE_DOWN:
                        for _ in range(10):
                            self.getControl(self.TEXT).scroll(-1)
                        return

                    # Jump to top (Home key)
                    elif action_id == self.ACTION_FIRST_PAGE:
                        # Scroll to top by scrolling up many times
                        for _ in range(1000):
                            self.getControl(self.TEXT).scroll(1)
                        return

                    # Jump to bottom (End key)
                    elif action_id == self.ACTION_LAST_PAGE:
                        # Scroll to bottom by scrolling down many times
                        for _ in range(1000):
                            self.getControl(self.TEXT).scroll(-1)
                        return

            except Exception as e:
                c.log(f'[LogViewer] Error in onAction: {e}')

        def onClick(self, control_id):
            """Handle button clicks."""
            try:
                if control_id == self.CLOSEBUTTON:
                    self.close()
            except Exception as e:
                c.log(f'[LogViewer] Error in onClick: {e}')

    dialog = LogViewer('LogViewer.xml', ARTADDON_PATH, control.appearance(), '1080i')
    dialog.doModal()
    del dialog