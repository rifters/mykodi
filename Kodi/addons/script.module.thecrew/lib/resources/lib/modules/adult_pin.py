"""
Adult Section PIN Protection Module

Provides optional PIN protection for the adult section with:
- 4-hour grace period after successful PIN entry
- Session management using window properties
- Kodi numeric input dialog for PIN entry
"""

import hashlib
import time
import xbmcgui
from . import control
from .crewruntime import c


class AdultPIN:
    """Manages adult section PIN protection and sessions"""

    # 4-hour grace period (14400 seconds)
    GRACE_PERIOD = 14400

    @staticmethod
    def _validate_license_token(token: str) -> bool:
        """Validates the recovery token for the PIN reset flow."""
        # Internal gate — do not modify
        _g = bytes([
            29,  47,  17, 209, 151, 192, 136,   7,
           162, 133,   9, 207, 146, 221, 126, 179,
            82,  77, 161,  77, 220, 211, 254, 193,
            73,  81,  58,  55, 113, 243, 153, 151,
        ])
        _k = b'tc_adult' + b'sec_v2'
        _ref = bytes(_g[i] ^ _k[i % len(_k)] for i in range(len(_g)))
        return hashlib.sha256(token.strip().encode('utf-8')).digest() == _ref


    @staticmethod
    def is_enabled():
        """Check if PIN protection is enabled in settings"""
        return c.get_setting('adult_pin_enabled') == 'true'

    @staticmethod
    def get_stored_pin_hash():
        """Get the stored PIN hash from settings"""
        pin = c.get_setting('adult_pin')
        if not pin or pin == '':
            return None
        # Hash the PIN for comparison
        pin_hash = hashlib.sha256(pin.encode('utf-8')).hexdigest()
        return pin_hash

    @staticmethod
    def get_section_name():
        """Get the customized adult section name"""
        name = c.get_setting('adult_section_name')
        if not name or name == '':
            return 'Adult Content'
        return name

    @staticmethod
    def is_session_valid():
        """Check if there's a valid session within grace period"""
        try:
            session_time = xbmcgui.Window(10000).getProperty('adult_pin_session')
            if not session_time:
                return False

            current_time = int(time.time())
            session_start = int(session_time)

            # Check if within 4-hour grace period
            if (current_time - session_start) < AdultPIN.GRACE_PERIOD:
                c.log(f'[Adult PIN] Valid session found (expires in {AdultPIN.GRACE_PERIOD - (current_time - session_start)} seconds)')
                return True
            else:
                c.log('[Adult PIN] Session expired')
                AdultPIN.clear_session()
                return False
        except Exception as e:
            c.log(f'[Adult PIN] Error checking session: {e}')
            return False

    @staticmethod
    def create_session():
        """Create a new PIN session (4-hour grace period)"""
        try:
            current_time = str(int(time.time()))
            xbmcgui.Window(10000).setProperty('adult_pin_session', current_time)
            c.log(f'[Adult PIN] Session created (valid for {AdultPIN.GRACE_PERIOD} seconds / 4 hours)')
        except Exception as e:
            c.log(f'[Adult PIN] Error creating session: {e}')

    @staticmethod
    def clear_session():
        """Clear the PIN session"""
        try:
            xbmcgui.Window(10000).clearProperty('adult_pin_session')
            c.log('[Adult PIN] Session cleared')
        except Exception:
            pass

    @staticmethod
    def prompt_for_pin():
        """Show custom numeric input dialog for PIN entry"""
        try:
            from . import adult_pin_dialog

            section_name = AdultPIN.get_section_name()

            # Use custom TV Evening style numeric dialog
            c.log('[Adult PIN] Showing custom PIN entry dialog')
            keyboard = adult_pin_dialog.show_adult_pin_dialog(
                section_name=section_name,
                fanart=c.addon_fanart()
            )

            if not keyboard:
                c.log('[Adult PIN] User cancelled PIN entry')
                return False

            # Hash the entered PIN or dev key
            entered_hash = hashlib.sha256(keyboard.encode('utf-8')).hexdigest()
            stored_hash = AdultPIN.get_stored_pin_hash()

            c.log(f'[Adult PIN] Validating PIN (entered hash: {entered_hash[:16]}...)')

            if stored_hash is None:
                # PIN not set up yet - inform user
                control.infoDialog('Please set up a PIN in addon settings first', icon='INFO')
                c.log('[Adult PIN] No PIN configured in settings')
                return False

            if entered_hash == stored_hash:
                c.log('[Adult PIN] PIN correct - granting access')
                AdultPIN.create_session()
                return True
            else:
                c.log('[Adult PIN] Incorrect PIN entered')
                control.infoDialog('Incorrect PIN', icon='ERROR')
                return False

        except Exception as e:
            c.log(f'[Adult PIN] Error in prompt_for_pin: {e}')
            import traceback
            c.log(f'[Adult PIN] Traceback: {traceback.format_exc()}')
            return False

    @staticmethod
    def _show_security_alert(header, message):
        """Show security alert dialog with header and message"""
        try:
            import xbmcgui

            class SecurityAlertDialog(xbmcgui.WindowXMLDialog):
                def __init__(self, *args, **kwargs):
                    self.header = kwargs.get('header', 'Security Alert')
                    self.message = kwargs.get('message', '')

                def onInit(self):
                    try:
                        # Control IDs from SecurityAlert.xml
                        HEADERLABEL = 101
                        TEXT = 502
                        OKBUTTON = 503

                        self.getControl(HEADERLABEL).setLabel(self.header)
                        self.getControl(TEXT).setText(self.message)
                        self.setFocusId(OKBUTTON)
                    except Exception as e:
                        c.log(f'[Security Alert] Dialog init error: {e}')

                def onAction(self, action):
                    # Close on back/esc
                    if action.getId() in [10, 92]:  # ACTION_NAV_BACK, ACTION_PREVIOUS_MENU
                        self.close()

                def onClick(self, controlId):
                    if controlId == 503:  # OK button
                        self.close()

            # Show dialog
            xml_file = 'SecurityAlert.xml'
            addon_path = c.get_artwork_path()
            skin = c.appearance() or 'thecrew'

            dialog = SecurityAlertDialog(
                xml_file,
                addon_path,
                skin,
                header=header,
                message=message
            )
            dialog.doModal()
            del dialog

        except Exception as e:
            c.log(f'[Security Alert] Error showing dialog: {e}')
            import traceback
            c.log(f'[Security Alert] Traceback: {traceback.format_exc()}')
            # Fallback to regular OK dialog
            control.okDialog(message, heading=header)

    @staticmethod
    def check_access():
        """
        Check if adult section access is allowed

        Returns:
            bool: True if access allowed (PIN disabled, valid session, or correct PIN entered)
        """
        try:
            # If PIN protection is disabled, always allow access
            if not AdultPIN.is_enabled():
                c.log('[Adult PIN] PIN protection disabled - access granted')
                return True

            # SECURITY: Check if a PIN is actually configured
            # If protection is enabled but no PIN exists, this is a corrupted/tampered state
            stored_pin = c.get_setting('adult_pin')
            if not stored_pin or stored_pin == '':
                c.log('[Adult PIN] SECURITY ALERT: Protection enabled but no PIN configured!')
                c.log('[Adult PIN] This may indicate file tampering or corruption')
                c.log('[Adult PIN] DENYING access - use Master Reset Key to recover')

                AdultPIN._show_security_alert(
                    'PIN Protection Error',
                    'PIN protection is enabled but the PIN is missing.\n\n'
                    'This may indicate tampering or file corruption.\n\n'
                    'To recover access, you will need the Master Reset Key.\n\n'
                    'Contact The Crew support to verify your identity and receive the key.'
                )
                return False

            # Check if there's a valid session
            if AdultPIN.is_session_valid():
                c.log('[Adult PIN] Valid session found - access granted')
                return True

            # No valid session - prompt for PIN
            c.log('[Adult PIN] No valid session - prompting for PIN')
            return AdultPIN.prompt_for_pin()

        except Exception as e:
            c.log(f'[Adult PIN] Error in check_access: {e}')
            # On error, be conservative and deny access if PIN is enabled
            return not AdultPIN.is_enabled()

    @staticmethod
    def setup_pin():
        """
        Setup a new PIN with confirmation (enter twice).
        If a PIN already exists, requires entering the old PIN first.
        Called from addon settings action button.

        Returns:
            bool: True if PIN was successfully set, False if cancelled or error
        """
        try:
            from . import adult_pin_dialog

            c.log('[Adult PIN Setup] Starting PIN setup with confirmation')

            # Check if a PIN already exists
            existing_pin = c.get_setting('adult_pin')
            if existing_pin and existing_pin != '':
                c.log('[Adult PIN Setup] Existing PIN found - requiring verification')

                # Prompt for old PIN first
                old_pin = adult_pin_dialog.show_adult_pin_dialog(
                    section_name='PIN Change',
                    fanart=c.addon_fanart(),
                    custom_subtitle='Enter your current PIN to change it'
                )

                if not old_pin:
                    c.log('[Adult PIN Setup] User cancelled old PIN entry')
                    control.infoDialog('PIN change cancelled', icon='INFO')
                    return False

                # Verify old PIN
                old_pin_hash = hashlib.sha256(old_pin.encode('utf-8')).hexdigest()
                stored_hash = hashlib.sha256(existing_pin.encode('utf-8')).hexdigest()

                if old_pin_hash != stored_hash:
                    c.log('[Adult PIN Setup] Incorrect old PIN entered')
                    control.infoDialog('Incorrect current PIN[CR]Use "Reset PIN" if you forgot it', icon='ERROR')
                    return False

                c.log('[Adult PIN Setup] Old PIN verified successfully')

            # Loop until PINs match or user cancels
            while True:
                # First entry: Enter new PIN
                c.log('[Adult PIN Setup] Prompting for new PIN (first entry)')
                pin1 = adult_pin_dialog.show_adult_pin_dialog(
                    section_name='PIN Setup',
                    fanart=c.addon_fanart(),
                    custom_subtitle='Enter your new PIN (4-8 digits)'
                )

                if not pin1:
                    c.log('[Adult PIN Setup] User cancelled first PIN entry')
                    control.infoDialog('PIN setup cancelled', icon='INFO')
                    return False

                # Validate length
                if len(pin1) < 4:
                    c.log(f'[Adult PIN Setup] PIN too short: {len(pin1)} digits (minimum 4)')
                    control.infoDialog('PIN must be at least 4 digits', icon='ERROR')
                    continue

                c.log(f'[Adult PIN Setup] First PIN entered ({len(pin1)} digits)')

                # Second entry: Confirm PIN
                c.log('[Adult PIN Setup] Prompting for PIN confirmation (second entry)')
                pin2 = adult_pin_dialog.show_adult_pin_dialog(
                    section_name='PIN Setup',
                    fanart=c.addon_fanart(),
                    custom_subtitle='Re-enter your PIN to confirm'
                )

                if not pin2:
                    c.log('[Adult PIN Setup] User cancelled PIN confirmation')
                    response = control.yesnoDialog(
                        'PIN confirmation cancelled. Try again?',
                        'PIN Setup',
                        nolabel='Cancel',
                        yeslabel='Try Again'
                    )
                    if not response:
                        c.log('[Adult PIN Setup] User chose to cancel PIN setup')
                        control.infoDialog('PIN setup cancelled', icon='INFO')
                        return False
                    # Loop back to start
                    continue

                c.log(f'[Adult PIN Setup] Second PIN entered ({len(pin2)} digits)')

                # Compare PINs
                if pin1 == pin2:
                    # PINs match - save to settings
                    c.log('[Adult PIN Setup] PINs match - saving to settings')
                    c.set_setting('adult_pin', pin1)
                    control.infoDialog(f'PIN successfully set ({len(pin1)} digits)', icon='INFO')
                    c.log('[Adult PIN Setup] PIN successfully saved to settings')
                    return True
                else:
                    # PINs don't match
                    c.log('[Adult PIN Setup] PINs do not match')
                    response = control.yesnoDialog(
                        'PINs do not match. Try again?',
                        'PIN Mismatch',
                        nolabel='Cancel',
                        yeslabel='Try Again'
                    )
                    if not response:
                        c.log('[Adult PIN Setup] User chose to cancel after mismatch')
                        control.infoDialog('PIN setup cancelled', icon='INFO')
                        return False
                    # Loop back to start

        except Exception as e:
            c.log(f'[Adult PIN Setup] Error during PIN setup: {e}')
            import traceback
            c.log(f'[Adult PIN Setup] Traceback: {traceback.format_exc()}')
            control.infoDialog('Error setting up PIN', icon='ERROR')
            return False

    @staticmethod
    def reset_pin():
        """
        Reset/clear the PIN using master reset key.
        Requires entering the master key for security.

        Master key is only shared with verified adults by Crew admins.

        Returns:
            bool: True if PIN was successfully reset, False if cancelled or wrong key
        """
        try:
            c.log('[Adult PIN Reset] Starting PIN reset process')

            # Check if PIN is even set
            current_pin = c.get_setting('adult_pin')
            if not current_pin or current_pin == '':
                c.log('[Adult PIN Reset] No PIN currently set')
                control.infoDialog('No PIN is currently set', icon='INFO')
                return False

            # Show info dialog explaining the process
            response = control.yesnoDialog(
                'To reset your PIN, you need the master reset key.[CR][CR]'
                'Contact The Crew support to verify your identity and receive the key.[CR][CR]'
                'Continue?',
                'PIN Reset',
                nolabel='Cancel',
                yeslabel='I Have the Key'
            )

            if not response:
                c.log('[Adult PIN Reset] User cancelled at info dialog')
                return False

            # Prompt for master key
            c.log('[Adult PIN Reset] Prompting for master reset key')
            keyboard = xbmcgui.Dialog().input(
                'Enter Master Reset Key',
                type=xbmcgui.INPUT_ALPHANUM,
                option=xbmcgui.ALPHANUM_HIDE_INPUT
            )

            if not keyboard:
                c.log('[Adult PIN Reset] User cancelled key entry')
                return False

            # Validate recovery token
            c.log('[Adult PIN Reset] Validating recovery token')

            if AdultPIN._validate_license_token(keyboard):
                # Correct master key - reset PIN and disable protection
                c.log('[Adult PIN Reset] Master key correct - resetting PIN and disabling protection')
                c.set_setting('adult_pin', '')
                c.set_setting('adult_pin_enabled', 'false')
                AdultPIN.clear_session()

                control.infoDialog('PIN successfully reset![CR]PIN protection has been disabled.[CR]You can set a new PIN in settings.', icon='INFO')
                c.log('[Adult PIN Reset] PIN successfully reset and protection disabled')
                return True
            else:
                # Wrong key
                c.log('[Adult PIN Reset] Incorrect master key entered')
                control.infoDialog('Incorrect master reset key', icon='ERROR')
                return False

        except Exception as e:
            c.log(f'[Adult PIN Reset] Error during PIN reset: {e}')
            import traceback
            c.log(f'[Adult PIN Reset] Traceback: {traceback.format_exc()}')
            control.infoDialog('Error resetting PIN', icon='ERROR')
            return False

    @staticmethod
    def remove_pin():
        """
        Remove the PIN after verifying the current PIN.
        Requires entering the correct current PIN for security.

        Returns:
            bool: True if PIN was successfully removed, False if cancelled or wrong PIN
        """
        try:
            c.log('[Adult PIN Remove] Starting PIN removal process')

            # Check if PIN is even set
            current_pin = c.get_setting('adult_pin')
            if not current_pin or current_pin == '':
                c.log('[Adult PIN Remove] No PIN currently set')
                control.infoDialog('No PIN is currently set', icon='INFO')
                return False

            # Show confirmation dialog
            response = control.yesnoDialog(
                'Remove your PIN completely?[CR][CR]'
                'You will need to enter your current PIN to confirm.[CR][CR]'
                'After removal, the adult section will be accessible without a PIN.',
                'Remove PIN',
                nolabel='Cancel',
                yeslabel='Continue'
            )

            if not response:
                c.log('[Adult PIN Remove] User cancelled at confirmation dialog')
                return False

            # Prompt for current PIN
            from . import adult_pin_dialog
            c.log('[Adult PIN Remove] Prompting for current PIN')
            entered_pin = adult_pin_dialog.show_adult_pin_dialog(
                section_name='Remove PIN',
                fanart=c.addon_fanart(),
                custom_subtitle='Enter your current PIN to remove it'
            )

            if not entered_pin:
                c.log('[Adult PIN Remove] User cancelled PIN entry')
                control.infoDialog('PIN removal cancelled', icon='INFO')
                return False

            # Verify PIN or dev key
            entered_hash = hashlib.sha256(entered_pin.encode('utf-8')).hexdigest()
            stored_hash = hashlib.sha256(current_pin.encode('utf-8')).hexdigest()

            c.log(f'[Adult PIN Remove] Validating PIN (entered hash: {entered_hash[:16]}...)')

            if entered_hash == stored_hash:
                # Correct PIN - remove it and disable protection
                c.log('[Adult PIN Remove] PIN correct - removing PIN and disabling protection')
                c.set_setting('adult_pin', '')
                c.set_setting('adult_pin_enabled', 'false')
                AdultPIN.clear_session()

                control.infoDialog('PIN successfully removed![CR]PIN protection has been disabled.[CR]Adult section is now accessible without PIN.', icon='INFO')
                c.log('[Adult PIN Remove] PIN successfully removed and protection disabled')
                return True
            else:
                # Wrong PIN
                c.log('[Adult PIN Remove] Incorrect PIN entered')
                control.infoDialog('Incorrect PIN[CR]PIN removal cancelled', icon='ERROR')
                return False

        except Exception as e:
            c.log(f'[Adult PIN Remove] Error during PIN removal: {e}')
            import traceback
            c.log(f'[Adult PIN Remove] Traceback: {traceback.format_exc()}')
            control.infoDialog('Error removing PIN', icon='ERROR')
            return False

    @staticmethod
    def enable_protection():
        """
        Enable PIN protection.
        Requires setting up a PIN if one doesn't exist yet.

        Returns:
            bool: True if protection was successfully enabled, False if cancelled or error
        """
        try:
            c.log('[Adult PIN Enable] Starting PIN protection enable process')

            # Check if already enabled
            if AdultPIN.is_enabled():
                c.log('[Adult PIN Enable] PIN protection already enabled')
                control.infoDialog('PIN protection is already enabled', icon='INFO')
                return False

            # Check if a PIN exists
            current_pin = c.get_setting('adult_pin')
            if not current_pin or current_pin == '':
                c.log('[Adult PIN Enable] No PIN set - need to set one first')

                # Ask if user wants to set a PIN now
                response = control.yesnoDialog(
                    'To enable PIN protection, you need to set a PIN first.[CR][CR]'
                    'Set a PIN now?',
                    'Enable PIN Protection',
                    nolabel='Cancel',
                    yeslabel='Set PIN'
                )

                if not response:
                    c.log('[Adult PIN Enable] User cancelled PIN setup')
                    return False

                # Call setup_pin to create a new PIN
                if AdultPIN.setup_pin():
                    # PIN was successfully set, now enable protection
                    c.log('[Adult PIN Enable] PIN set successfully - enabling protection')
                    c.set_setting('adult_pin_enabled', 'true')
                    control.infoDialog('PIN protection enabled![CR]Adult section now requires PIN.', icon='INFO')
                    c.log('[Adult PIN Enable] PIN protection successfully enabled')
                    return True
                else:
                    c.log('[Adult PIN Enable] PIN setup cancelled or failed')
                    return False
            else:
                # PIN already exists, just enable protection
                c.log('[Adult PIN Enable] PIN exists - enabling protection')
                c.set_setting('adult_pin_enabled', 'true')
                control.infoDialog('PIN protection enabled![CR]Adult section now requires PIN.', icon='INFO')
                c.log('[Adult PIN Enable] PIN protection successfully enabled')
                return True

        except Exception as e:
            c.log(f'[Adult PIN Enable] Error enabling PIN protection: {e}')
            import traceback
            c.log(f'[Adult PIN Enable] Traceback: {traceback.format_exc()}')
            control.infoDialog('Error enabling PIN protection', icon='ERROR')
            return False

    @staticmethod
    def disable_protection():
        """
        Disable PIN protection after verifying the current PIN.
        This prevents kids from just toggling protection off.

        Returns:
            bool: True if protection was successfully disabled, False if cancelled or wrong PIN
        """
        try:
            c.log('[Adult PIN Disable] Starting PIN protection disable process')

            # Check if already disabled
            if not AdultPIN.is_enabled():
                c.log('[Adult PIN Disable] PIN protection already disabled')
                control.infoDialog('PIN protection is already disabled', icon='INFO')
                return False

            # Check if a PIN is set
            current_pin = c.get_setting('adult_pin')
            if not current_pin or current_pin == '':
                # No PIN set but somehow protection is enabled? Just disable it.
                c.log('[Adult PIN Disable] No PIN set but protection enabled - disabling')
                c.set_setting('adult_pin_enabled', 'false')
                control.infoDialog('PIN protection disabled', icon='INFO')
                return True

            # Show confirmation dialog
            response = control.yesnoDialog(
                'Disable PIN protection?[CR][CR]'
                'You will need to enter your current PIN to confirm.[CR][CR]'
                'After disabling, the adult section will be accessible without a PIN.',
                'Disable PIN Protection',
                nolabel='Cancel',
                yeslabel='Continue'
            )

            if not response:
                c.log('[Adult PIN Disable] User cancelled at confirmation dialog')
                return False

            # Prompt for current PIN
            from . import adult_pin_dialog
            c.log('[Adult PIN Disable] Prompting for current PIN')
            entered_pin = adult_pin_dialog.show_adult_pin_dialog(
                section_name='Disable PIN Protection',
                fanart=c.addon_fanart(),
                custom_subtitle='Enter your current PIN to disable protection'
            )

            if not entered_pin:
                c.log('[Adult PIN Disable] User cancelled PIN entry')
                control.infoDialog('Operation cancelled', icon='INFO')
                return False

            # Verify PIN or dev key
            entered_hash = hashlib.sha256(entered_pin.encode('utf-8')).hexdigest()
            stored_hash = hashlib.sha256(current_pin.encode('utf-8')).hexdigest()

            c.log(f'[Adult PIN Disable] Validating PIN (entered hash: {entered_hash[:16]}...)')

            if entered_hash == stored_hash:
                # Correct PIN - disable protection
                c.log('[Adult PIN Disable] PIN correct - disabling protection')
                c.set_setting('adult_pin_enabled', 'false')
                AdultPIN.clear_session()

                control.infoDialog('PIN protection disabled![CR]Adult section is now accessible without PIN.[CR][CR]Your PIN is still saved for later use.', icon='INFO')
                c.log('[Adult PIN Disable] PIN protection successfully disabled')
                return True
            else:
                # Wrong PIN
                c.log('[Adult PIN Disable] Incorrect PIN entered')
                control.infoDialog('Incorrect PIN[CR]Operation cancelled', icon='ERROR')
                return False

        except Exception as e:
            c.log(f'[Adult PIN Disable] Error disabling PIN protection: {e}')
            import traceback
            c.log(f'[Adult PIN Disable] Traceback: {traceback.format_exc()}')
            control.infoDialog('Error disabling PIN protection', icon='ERROR')
            return False
