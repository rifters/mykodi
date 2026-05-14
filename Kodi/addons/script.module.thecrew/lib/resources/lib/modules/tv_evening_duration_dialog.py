# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file tv_evening_duration_dialog.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

import xbmcgui

from . import control
from .crewruntime import c


class TVEveningDurationDialog(xbmcgui.WindowXMLDialog):
    """
    Custom dialog for TV Evening duration selection.
    Beautiful fullscreen dialog matching Up Next style.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the dialog."""
        super(TVEveningDurationDialog, self).__init__(*args, **kwargs)
        self.button_id = None
        self.fanart = kwargs.get('fanart', '')

    def onInit(self):
        """Called when dialog is initialized."""
        try:
            c.log("[TV Evening Duration] Dialog initialized")

            # Set backdrop with fallback to addon fanart
            fanart = self.fanart if self.fanart else c.addon_fanart()
            self.setProperty('tvevening.fanart', fanart)
            c.log(f"[TV Evening Duration] Set backdrop: {fanart[:80]}")

            # Hide center progress group initially (will be shown during building)
            try:
                self.getControl(8000).setVisible(False)  # Parent group
                c.log("[TV Evening Duration] Center progress group (8000) hidden during init")
            except Exception as ge:
                c.log(f"[TV Evening Duration] Could not hide center group 8000: {ge}")

            # Hide center progress controls individually as backup (they're visible by default in XML now)
            try:
                self.getControl(8001).setVisible(False)  # Title
                self.getControl(8002).setVisible(False)  # Textbox
                self.getControl(8003).setVisible(False)  # Spinner
                c.log("[TV Evening Duration] Center controls hidden during init")
            except Exception as ce:
                c.log(f"[TV Evening Duration] Could not hide center controls: {ce}")

            # Set focus to first button (30 minutes)
            self.setFocusId(100)

        except Exception as e:
            c.log(f"[TV Evening Duration] Error in onInit: {e}")

    def onClick(self, controlId):
        """Handle button clicks."""
        try:
            c.log(f"[TV Evening Duration] Button clicked: {controlId}")
            self.button_id = controlId
            self.close()
        except Exception as e:
            c.log(f"[TV Evening Duration] Error in onClick: {e}")

    def onAction(self, action):
        """Handle user actions (like back button)."""
        try:
            # Close on back/escape
            if action.getId() in (9, 10, 92, 216, 247, 257, 275, 61467, 61448):
                c.log("[TV Evening Duration] Dialog cancelled by user")
                self.button_id = None
                self.close()
        except Exception as e:
            c.log(f"[TV Evening Duration] Error in onAction: {e}")


    def update_progress(self, message, percentage=None):
        """
        Update the progress message and optional progress bar during playlist building.

        Args:
            message: Text message to display
            percentage: Optional integer 0-100 for progress bar
        """
        try:
            c.log(f"[TV Evening Duration] ========== UPDATE_PROGRESS() CALLED ==========")
            c.log(f"[TV Evening Duration] Message: {message}")
            c.log(f"[TV Evening Duration] Percentage: {percentage}")

            # Update centered textbox (id=8002) - large space available
            center_textbox = self.getControl(8002)
            center_textbox.setText(message)
            c.log(f"[TV Evening Duration] Progress text updated successfully")

            # Update progress bar if percentage provided
            if percentage is not None:
                self._update_progress_bar(percentage)

        except Exception as e:
            c.log(f"[TV Evening Duration] ========== ERROR IN UPDATE_PROGRESS() ==========")
            c.log(f"[TV Evening Duration] Error: {e}")
            import traceback
            c.log(f"[TV Evening Duration] Traceback: {traceback.format_exc()}")

    def _update_progress_bar(self, percentage):
        """
        Update the visual progress bar.

        Args:
            percentage: Integer 0-100
        """
        try:
            # Clamp percentage to 0-100
            percentage = max(0, min(100, percentage))

            # Calculate fill bar width (596 pixels max = 600 - 4px for 2px borders)
            max_width = 596
            fill_width = int((percentage / 100.0) * max_width)

            c.log(f"[TV Evening Duration] Updating progress bar: {percentage}% (width={fill_width}px)")

            # Update fill bar width (control 8005)
            fill_bar = self.getControl(8005)
            fill_bar.setWidth(fill_width)

            # Update percentage text (control 8006)
            percentage_label = self.getControl(8006)
            percentage_label.setLabel(f"{percentage}%")

            c.log(f"[TV Evening Duration] Progress bar updated to {percentage}%")

        except Exception as e:
            c.log(f"[TV Evening Duration] Error updating progress bar: {e}")
            import traceback
            c.log(f"[TV Evening Duration] Traceback: {traceback.format_exc()}")
    def show_building(self):
        """Transform dialog to show 'Building playlist...' state."""
        try:
            c.log("[TV Evening Duration] ========== SHOW_BUILDING() CALLED ==========")
            c.log(f"[TV Evening Duration] Dialog object: {self}")
            c.log("[TV Evening Duration] Hiding sidebar and showing center progress...")

            # CRITICAL: Make the parent center progress group (8000) visible FIRST
            # Without this, child controls won't be visible even if individually set visible
            try:
                center_group = self.getControl(8000)
                center_group.setVisible(True)
                c.log("[TV Evening Duration] Made parent center group (8000) visible")
            except Exception as e:
                c.log(f"[TV Evening Duration] Could not show parent center group (8000): {e}")

            # Hide the entire right panel (id=9001)
            try:
                right_panel = self.getControl(9001)
                right_panel.setVisible(False)
                c.log("[TV Evening Duration] Hid right panel (9001)")
            except Exception as e:
                c.log(f"[TV Evening Duration] Could not hide right panel: {e}")

            # Hide instruction label (id=9002)
            try:
                instruction_label = self.getControl(9002)
                instruction_label.setVisible(False)
                c.log("[TV Evening Duration] Hid instruction label (9002)")
            except Exception as e:
                c.log(f"[TV Evening Duration] Could not hide instruction label: {e}")

            # Hide all duration buttons (IDs 100-106)
            for button_id in range(100, 107):
                try:
                    button = self.getControl(button_id)
                    button.setVisible(False)
                    c.log(f"[TV Evening Duration] Hid button {button_id}")
                except Exception as e:
                    c.log(f"[TV Evening Duration] Could not hide button {button_id}: {e}")

            # Hide the grouplist container (id 9000)
            try:
                grouplist = self.getControl(9000)
                grouplist.setVisible(False)
                c.log("[TV Evening Duration] Hid grouplist 9000")
            except Exception as e:
                c.log(f"[TV Evening Duration] Could not hide grouplist: {e}")

            # Hide sidebar title and subtitle (we're using center now)
            try:
                self.getControl(201).setVisible(False)  # Title
                c.log("[TV Evening Duration] Hid sidebar title")
            except Exception as e:
                c.log(f"[TV Evening Duration] Could not hide title: {e}")

            try:
                self.getControl(200).setVisible(False)  # Subtitle
                c.log("[TV Evening Duration] Hid sidebar subtitle")
            except Exception as e:
                c.log(f"[TV Evening Duration] Could not hide subtitle: {e}")

            # Update center controls (make them visible and set content)
            try:
                c.log("[TV Evening Duration] Showing and setting center title...")
                center_title = self.getControl(8001)
                center_title.setVisible(True)
                center_title.setLabel('BUILDING YOUR PLAYLIST')
                c.log("[TV Evening Duration] Center title visible and updated")
            except Exception as e:
                c.log(f"[TV Evening Duration] Could not update center title (8001): {e}")
                import traceback
                c.log(f"[TV Evening Duration] Traceback: {traceback.format_exc()}")

            # Set initial progress message and make visible
            try:
                c.log("[TV Evening Duration] Showing and setting center textbox...")
                center_textbox = self.getControl(8002)
                center_textbox.setVisible(True)
                center_textbox.setText('The Crew is building your TV Evening...\n\nThis may take a moment.')
                c.log("[TV Evening Duration] Center textbox visible and updated")
            except Exception as e:
                c.log(f"[TV Evening Duration] Could not set initial message (8002): {e}")
                import traceback
                c.log(f"[TV Evening Duration] Traceback: {traceback.format_exc()}")

            # Show spinning icon
            try:
                c.log("[TV Evening Duration] Showing progress bar group...")
                progress_group = self.getControl(8003)
                progress_group.setVisible(True)
                c.log("[TV Evening Duration] Progress bar group visible")

                # Initialize progress bar at 0%
                self._update_progress_bar(0)

            except Exception as e:
                c.log(f"[TV Evening Duration] Could not show progress bar (8003): {e}")
                import traceback
                c.log(f"[TV Evening Duration] Traceback: {traceback.format_exc()}")

            c.log("[TV Evening Duration] ========== SHOW_BUILDING() COMPLETE ==========")
            c.log("[TV Evening Duration] Center progress should now be visible")
        except Exception as e:
            c.log(f"[TV Evening Duration] ========== ERROR IN SHOW_BUILDING() ==========")
            c.log(f"[TV Evening Duration] Error: {e}")
            import traceback
            c.log(f"[TV Evening Duration] Traceback: {traceback.format_exc()}")


class TVEveningNumericInputDialog(xbmcgui.WindowXMLDialog):
    """
    Custom numeric input dialog for TV Evening.
    Beautiful number pad matching the TV Evening style.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the dialog."""
        super(TVEveningNumericInputDialog, self).__init__(*args, **kwargs)
        self.button_id = None
        self.fanart = kwargs.get('fanart', '')
        self.value = kwargs.get('default', '60')

    def onInit(self):
        """Called when dialog is initialized."""
        try:
            c.log("[TV Evening Numeric] Dialog initialized")

            # Set backdrop with fallback to addon fanart
            fanart = self.fanart if self.fanart else c.addon_fanart()
            self.setProperty('tvevening.fanart', fanart)

            # Dynamically set button labels (bypasses XML string ID interpretation)
            # Digits needed because Kodi reads "numbers" as a string ID and doesn't allow direct "number" labels in XML
            # Number buttons
            self.getControl(101).setLabel('1')
            self.getControl(102).setLabel('2')
            self.getControl(103).setLabel('3')
            self.getControl(104).setLabel('4')
            self.getControl(105).setLabel('5')
            self.getControl(106).setLabel('6')
            self.getControl(107).setLabel('7')
            self.getControl(108).setLabel('8')
            self.getControl(109).setLabel('9')
            self.getControl(100).setLabel('0')
            # Special buttons
            self.getControl(110).setLabel('<')
            self.getControl(111).setLabel('C')
            self.getControl(112).setLabel('OK')
            self.getControl(113).setLabel('Cancel')

            # Update display with default value
            self.update_display()

            # Set focus to default button (5)
            self.setFocusId(105)

        except Exception as e:
            c.log(f"[TV Evening Numeric] Error in onInit: {e}")

    def update_display(self):
        """Update the value display label."""
        try:
            label = self.getControl(200)
            label.setLabel(self.value)
        except Exception as e:
            c.log(f"[TV Evening Numeric] Error updating display: {e}")

    def onClick(self, controlId):
        """Handle button clicks."""
        try:
            c.log(f"[TV Evening Numeric] Button clicked: {controlId}")

            if controlId >= 100 and controlId <= 109:
                # Number button (0-9)
                digit = str(controlId - 100) if controlId != 100 else '0'
                # Don't allow leading zeros
                if self.value == '0':
                    self.value = digit
                else:
                    # Limit to 4 digits (9999 minutes max)
                    if len(self.value) < 4:
                        self.value += digit
                self.update_display()

            elif controlId == 110:
                # Backspace
                if len(self.value) > 0:
                    self.value = self.value[:-1]
                    if self.value == '':
                        self.value = '0'
                self.update_display()

            elif controlId == 111:
                # Clear
                self.value = '0'
                self.update_display()

            elif controlId == 112:
                # OK
                self.button_id = 112
                self.close()

            elif controlId == 113:
                # Cancel
                self.button_id = 113
                self.close()

        except Exception as e:
            c.log(f"[TV Evening Numeric] Error in onClick: {e}")

    def onAction(self, action):
        """Handle user actions (like back button)."""
        try:
            # Close on back/escape
            if action.getId() in (9, 10, 92, 216, 247, 257, 275, 61467, 61448):
                c.log("[TV Evening Numeric] Dialog cancelled by user")
                self.button_id = 113  # Treat as Cancel
                self.close()
        except Exception as e:
            c.log(f"[TV Evening Numeric] Error in onAction: {e}")


def show_tv_evening_duration_dialog(fanart=''):
    """
    Show TV Evening duration selection dialog.

    :param str fanart: Backdrop URL
    :return: Duration in minutes or None if cancelled
    :rtype: int or None
    """
    try:
        c.log("[TV Evening Duration] Showing duration dialog")

        # Get artwork addon path and current skin
        addon_path = c.get_artwork_path()
        skin = c.appearance() or 'thecrew'

        c.log(f"[TV Evening Duration] Using skin: {skin}, addon path: {addon_path}")

        # Map button IDs to durations
        duration_map = {
            100: 30,   # 30 minutes
            101: 60,   # 1 hour
            102: 120,  # 2 hours
            103: 180,  # 3 hours
            104: 240,  # 4 hours
            105: -1,   # Custom (special value)
            106: None, # Cancel
        }

        # Loop to handle custom duration with return to dialog on cancel
        while True:
            # Create and show dialog
            dialog = TVEveningDurationDialog(
                'TVEveningDuration.xml',
                addon_path,
                skin,
                fanart=fanart
            )
            dialog.doModal()

            # Get selected button
            button_id = dialog.button_id

            # Clean up
            del dialog

            if button_id not in duration_map:
                c.log("[TV Evening Duration] Cancelled by user")
                return None

            duration = duration_map[button_id]

            if duration == -1:  # Custom
                c.log("[TV Evening Duration] User selected custom duration")
                # Use custom numeric input dialog
                custom = show_tv_evening_numeric_input(fanart=fanart)
                if custom:
                    c.log(f"[TV Evening Duration] Custom duration entered: {custom} minutes")
                    return int(custom)
                else:
                    c.log("[TV Evening Duration] Custom duration cancelled, returning to dialog")
                    # Loop will reshow the dialog
                    continue

            # Normal duration selected or cancel
            if duration is not None:
                c.log(f"[TV Evening Duration] User selected: {duration} minutes")
            else:
                c.log("[TV Evening Duration] Cancelled by user")

            return duration

    except Exception as e:
        c.log(f"[TV Evening Duration] Error showing dialog: {e}")
        import traceback
        c.log(f"[TV Evening Duration] Traceback: {traceback.format_exc()}")
        return None


def show_tv_evening_numeric_input(fanart='', default='60'):
    """
    Show TV Evening custom numeric input dialog.

    :param str fanart: Backdrop URL
    :param str default: Default value to display
    :return: Entered value or None if cancelled
    :rtype: str or None
    """
    try:
        c.log("[TV Evening Numeric] Showing numeric input dialog")

        # Get artwork addon path and current skin
        addon_path = c.get_artwork_path()
        skin = c.appearance() or 'thecrew'

        # Create and show dialog
        dialog = TVEveningNumericInputDialog(
            'TVEveningNumericInput.xml',
            addon_path,
            skin,
            fanart=fanart,
            default=default
        )
        dialog.doModal()

        # Get result
        button_id = dialog.button_id
        value = dialog.value

        # Clean up
        del dialog

        if button_id == 112:  # OK
            c.log(f"[TV Evening Numeric] Value entered: {value}")
            return value
        else:
            c.log("[TV Evening Numeric] Cancelled by user")
            return None

    except Exception as e:
        c.log(f"[TV Evening Numeric] Error showing dialog: {e}")
        import traceback
        c.log(f"[TV Evening Numeric] Traceback: {traceback.format_exc()}")
        return None


def show_tv_evening_duration_with_progress(fanart=''):
    """
    Show TV Evening duration selection dialog and keep it open for progress display.

    :param str fanart: Backdrop URL
    :return: Tuple of (duration in minutes, dialog object) or (None, None) if cancelled
    :rtype: tuple (int or None, TVEveningDurationDialog or None)
    """
    try:
        c.log("[TV Evening Duration] ========== STARTING DURATION DIALOG ===========")
        c.log(f"[TV Evening Duration] Fanart: {fanart}")

        # Get artwork addon path and current skin
        addon_path = c.get_artwork_path()
        skin = c.appearance() or 'thecrew'

        # Map button IDs to durations
        duration_map = {
            100: 30,   # 30 minutes
            101: 60,   # 1 hour
            102: 120,  # 2 hours
            103: 180,  # 3 hours
            104: 240,  # 4 hours
            105: -1,   # Custom (special value)
            106: None, # Cancel
        }

        # Loop to handle custom duration with return to dialog on cancel
        while True:
            # Create and show dialog
            dialog = TVEveningDurationDialog(
                'TVEveningDuration.xml',
                addon_path,
                skin,
                fanart=fanart
            )
            dialog.doModal()

            # Get selected button
            button_id = dialog.button_id

            if button_id not in duration_map:
                c.log("[TV Evening Duration] Cancelled by user")
                del dialog
                return (None, None)

            duration = duration_map[button_id]

            if duration == -1:  # Custom
                c.log("[TV Evening Duration] User selected custom duration")
                # Use custom numeric input dialog (temporarily)
                custom = show_tv_evening_numeric_input(fanart=fanart)
                if custom:
                    c.log(f"[TV Evening Duration] Custom duration entered: {custom} minutes")
                    # Reshow dialog (non-modal) to keep it visible during building
                    c.log("[TV Evening Duration] Re-showing dialog for progress display...")
                    dialog.show()
                    # Keep the duration dialog alive and return it
                    return (int(custom), dialog)
                else:
                    c.log("[TV Evening Duration] Custom duration cancelled, returning to dialog")
                    del dialog
                    # Loop will reshow the dialog
                    continue

            # Normal duration selected or cancel
            if duration is not None:
                c.log(f"[TV Evening Duration] User selected: {duration} minutes")
                c.log("[TV Evening Duration] ========== DIALOG CREATED AND READY FOR PROGRESS ==========")
                c.log(f"[TV Evening Duration] Dialog object: {dialog}")
                c.log("[TV Evening Duration] Dialog will stay open for progress updates")
                # Reshow dialog (non-modal) to keep it visible during building
                c.log("[TV Evening Duration] Re-showing dialog for progress display...")
                dialog.show()
                c.log("[TV Evening Duration] Dialog is now visible again")
                # Keep dialog alive and return it
                return (duration, dialog)
            else:
                c.log("[TV Evening Duration] Cancelled by user")
                del dialog
                return (None, None)

    except Exception as e:
        c.log(f"[TV Evening Duration] Error showing dialog: {e}")
        import traceback
        c.log(f"[TV Evening Duration] Traceback: {traceback.format_exc()}")
        return (None, None)
