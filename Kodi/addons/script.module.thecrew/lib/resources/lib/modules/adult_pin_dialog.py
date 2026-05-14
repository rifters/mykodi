# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file adult_pin_dialog.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*

Adult PIN Entry Dialog

Custom numeric input dialog for adult section PIN protection.
Uses the TV Evening numeric input style with parental control branding.
'''

import xbmcgui
from . import control
from .crewruntime import c


class AdultPINDialog(xbmcgui.WindowXMLDialog):
    """
    Custom PIN entry dialog with parental control styling.
    Beautiful number pad matching the TV Evening style.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the dialog."""
        super(AdultPINDialog, self).__init__(*args, **kwargs)
        self.button_id = None
        self.fanart = kwargs.get('fanart', '')
        self.section_name = kwargs.get('section_name', 'Adult Content')
        self.custom_subtitle = kwargs.get('custom_subtitle', None)  # Allow custom subtitle for PIN setup
        self.value = ''  # Start empty for security
        self.closing = False  # Flag to prevent button clicks during close

    def onInit(self):
        """Called when dialog is initialized."""
        try:
            c.log("[Adult PIN] Dialog initialized")

            # Set backdrop with fallback to addon fanart
            fanart = self.fanart if self.fanart else c.addon_fanart()
            self.setProperty('tvevening.fanart', fanart)

            # Customize title and subtitle for parental control
            try:
                # Title: PARENTAL CONTROL (orchid color to match theme)
                title_control = self.getControl(201)  # Title label
                title_control.setLabel('[COLOR orchid]PARENTAL CONTROL[/COLOR]')
            except:
                c.log("[Adult PIN] Warning: Could not set title label (control 201)")

            try:
                # Subtitle: Use custom subtitle if provided, otherwise default message
                subtitle_control = self.getControl(202)  # Subtitle label
                if self.custom_subtitle:
                    subtitle_control.setLabel(self.custom_subtitle)
                else:
                    subtitle_control.setLabel(f'Enter PIN to access {self.section_name}')
            except:
                c.log("[Adult PIN] Warning: Could not set subtitle label (control 202)")

            # Dynamically set button labels
            # Number buttons (0-9)
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
            self.getControl(110).setLabel('<')      # Backspace
            self.getControl(111).setLabel('C')      # Clear
            self.getControl(112).setLabel('OK')     # OK/Submit
            self.getControl(113).setLabel('Cancel') # Cancel

            # Update display (show masked PIN as dots)
            self.update_display()

            # Set focus to middle button (5)
            self.setFocusId(105)

        except Exception as e:
            c.log(f"[Adult PIN] Error in onInit: {e}")
            import traceback
            c.log(f"[Adult PIN] Traceback: {traceback.format_exc()}")

    def update_display(self):
        """Update the value display label with masked dots for security."""
        try:
            label = self.getControl(200)
            # Show dots (•) instead of actual digits for security
            if len(self.value) == 0:
                display = '[COLOR gray]Enter PIN[/COLOR]'
            else:
                display = '•' * len(self.value)
            label.setLabel(display)
        except Exception as e:
            c.log(f"[Adult PIN] Error updating display: {e}")

    def onClick(self, controlId):
        """Handle button clicks."""
        try:
            # Ignore button clicks if dialog is closing (prevents numpad Enter from clicking buttons)
            if self.closing:
                c.log(f"[Adult PIN] Ignoring button click {controlId} - dialog is closing")
                return

            c.log(f"[Adult PIN] Button clicked: {controlId}")

            if controlId >= 100 and controlId <= 109:
                # Number button (0-9)
                digit = str(controlId - 100) if controlId != 100 else '0'
                # Limit to 8 digits max (PIN should be 4-8 digits)
                if len(self.value) < 8:
                    self.value += digit
                self.update_display()

            elif controlId == 110:
                # Backspace
                if len(self.value) > 0:
                    self.value = self.value[:-1]
                self.update_display()

            elif controlId == 111:
                # Clear
                self.value = ''
                self.update_display()

            elif controlId == 112:
                # OK - validate PIN has been entered
                if len(self.value) >= 4:  # Minimum 4 digits
                    self.button_id = 112
                    c.log(f"[Adult PIN] PIN submitted ({len(self.value)} digits)")
                    self.closing = True
                    self.close()
                else:
                    # Show error - PIN too short
                    c.log("[Adult PIN] PIN too short (minimum 4 digits)")
                    control.infoDialog('PIN must be at least 4 digits', icon='ERROR')

            elif controlId == 113:
                # Cancel
                c.log("[Adult PIN] Dialog cancelled by user")
                self.button_id = 113
                self.closing = True
                self.close()

        except Exception as e:
            c.log(f"[Adult PIN] Error in onClick: {e}")
            import traceback
            c.log(f"[Adult PIN] Traceback: {traceback.format_exc()}")

    def onAction(self, action):
        """Handle user actions (keyboard input, back button)."""
        try:
            action_id = action.getId()

            # Handle number key input from keyboard/remote (Action IDs 58-67 = numbers 0-9 from main keyboard)
            if action_id >= 58 and action_id <= 67:
                # Map action ID to digit: 58=0, 59=1, 60=2, ..., 67=9
                if action_id == 58:
                    digit = '0'
                else:
                    digit = str(action_id - 58)

                # Limit to 8 digits max
                if len(self.value) < 8:
                    self.value += digit
                    c.log(f"[Adult PIN] Main keyboard digit entered: {digit} (total length: {len(self.value)})")
                    self.update_display()
                return

            # Handle numpad number keys (Action IDs 61472-61481 = numpad 0-9)
            elif action_id >= 61472 and action_id <= 61481:
                # Map action ID to digit: 61472=0, 61473=1, ..., 61481=9
                digit = str(action_id - 61472)

                # Limit to 8 digits max
                if len(self.value) < 8:
                    self.value += digit
                    c.log(f"[Adult PIN] Numpad digit entered: {digit} (total length: {len(self.value)})")
                    self.update_display()
                return

            # Backspace key (action ID 110)
            elif action_id == 110:
                if len(self.value) > 0:
                    self.value = self.value[:-1]
                    c.log(f"[Adult PIN] Backspace pressed (length: {len(self.value)})")
                    self.update_display()
                return

            # Enter key (action ID 7 = SELECT_ITEM, 61453 = numpad enter) - submit PIN
            elif action_id == 7 or action_id == 61453:
                if len(self.value) >= 4:  # Minimum 4 digits
                    self.button_id = 112
                    c.log(f"[Adult PIN] PIN submitted via Enter key (action_id={action_id}, {len(self.value)} digits)")
                    self.closing = True
                    self.close()
                else:
                    # Show error - PIN too short
                    c.log(f"[Adult PIN] Enter pressed (action_id={action_id}) but PIN too short (minimum 4 digits)")
                    control.infoDialog('PIN must be at least 4 digits', icon='ERROR')
                return

            # Close on back/escape
            if action_id in (9, 10, 92, 216, 247, 257, 275, 61467, 61448):
                c.log("[Adult PIN] Dialog cancelled by user (back button)")
                self.button_id = 113  # Treat as Cancel
                self.closing = True
                self.close()
            # Ignore common navigation actions (up, down, left, right, etc.) to reduce log spam
            elif action_id not in (1, 2, 3, 4, 5, 6, 100, 101, 102, 103, 104, 105, 106, 107, 117):
                # Log unhandled action IDs for debugging (excluding navigation)
                c.log(f"[Adult PIN] Unhandled action_id: {action_id}")
        except Exception as e:
            c.log(f"[Adult PIN] Error in onAction: {e}")
            import traceback
            c.log(f"[Adult PIN] Traceback: {traceback.format_exc()}")


def show_adult_pin_dialog(section_name='Adult Content', fanart='', custom_subtitle=None):
    """
    Show adult PIN entry dialog.

    :param str section_name: Name of the section being protected
    :param str fanart: Backdrop URL
    :param str custom_subtitle: Optional custom subtitle text (overrides default)
    :return: Entered PIN or None if cancelled
    :rtype: str or None
    """
    try:
        c.log(f"[Adult PIN] Showing PIN dialog for '{section_name}'")

        # Get artwork addon path and current skin
        addon_path = c.get_artwork_path()
        skin = c.appearance() or 'thecrew'

        c.log(f"[Adult PIN] Using skin: {skin}, addon path: {addon_path}")

        # Create and show dialog
        dialog = AdultPINDialog(
            'TVEveningNumericInput.xml',
            addon_path,
            skin,
            fanart=fanart,
            section_name=section_name,
            custom_subtitle=custom_subtitle
        )
        dialog.doModal()

        # Get result
        button_id = dialog.button_id
        value = dialog.value

        # Clean up
        del dialog

        if button_id == 112:  # OK
            c.log(f"[Adult PIN] PIN entered ({len(value)} digits)")
            return value
        else:
            c.log("[Adult PIN] Cancelled by user")
            return None

    except Exception as e:
        c.log(f"[Adult PIN] Error showing dialog: {e}")
        import traceback
        c.log(f"[Adult PIN] Traceback: {traceback.format_exc()}")
        # Fallback to built-in Kodi dialog if custom fails
        c.log("[Adult PIN] Falling back to Kodi built-in numeric dialog")
        from . import control
        return control.dialog.numeric(0, f'Enter PIN to access {section_name}')
