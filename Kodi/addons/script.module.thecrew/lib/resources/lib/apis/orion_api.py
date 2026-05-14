# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file orion_api.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2025, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import os
import traceback

import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmcvfs
import math

from orion import Orion
from ..modules.crewruntime import c
from ..modules import keys
from ..modules import control
from ..modules import source_utils


class OrionAPI:
    """
    Modern Orion API wrapper for The Crew addon

    Orion stores credentials in its own addon (script.module.orion)
    This wrapper provides a clean interface matching debrid API patterns
    """

    def __init__(self):
        self.name = 'Orion'
        self.app_key = keys.orion_key
        try:
            # Test if Orion module can be instantiated
            test_orion = Orion(self.app_key)
            self.available = True
        except (ImportError, AttributeError, TypeError) as e:
            c.log(f'[Orion API] Error initializing Orion: {e}', 1)
            import traceback
            c.log(f'[Orion API] Traceback: {traceback.format_exc()}', 1)
            self.available = False

    def is_enabled(self):
        """Check if Orion is enabled and user is authenticated"""
        try:

            if not self.available:
                return False

            # Create fresh Orion instance (following old orionApi pattern)
            orion = Orion(self.app_key)

            enabled = orion.userEnabled()
            valid = orion.userValid()


            return enabled and valid
        except (AttributeError, TypeError) as e:
            c.log(f'[Orion API] Error checking enabled status: {e}', 1)
            import traceback
            c.log(f'[Orion API] Traceback: {traceback.format_exc()}', 1)
            return False

    def account_info(self):
        """
        Get Orion account information for display

        Returns:
            Dictionary with account details or None if not available
        """
        try:

            if not self.is_enabled():
                return None


            # Create fresh Orion instance (following old orionApi pattern)
            orion = Orion(self.app_key)

            # Retrieve user account data from Orion using user() method per documentation
            user_data = orion.user()


            if not user_data:
                return None

            # Orion returns data directly at root level, not wrapped in result.data
            username = user_data.get('username', 'N/A')
            email = user_data.get('email', 'N/A')

            # Extract subscription information
            subscription = user_data.get('subscription', {})
            package_info = subscription.get('package', {})
            package_name = package_info.get('name', 'Unknown')

            time_info = subscription.get('time', {})
            expiration = time_info.get('expiration', 0)  # Unix timestamp


            # Extract usage limits
            requests = user_data.get('requests', {})
            streams = requests.get('streams', {})
            daily = streams.get('daily', {})

            result = {
                'active': True,
                'username': username,
                'email': email,
                'package': package_name,
                'expiration': expiration,
                'type': package_name,
                'link_total': daily.get('limit', 0),
                'link_used': daily.get('used', 0),
                'link_remaining': daily.get('remaining', 0)
            }

            return result

        except (KeyError, TypeError, AttributeError) as e:
            c.log(f'[Orion API] Error getting account info: {e}', 1)
            return None

    def authorize(self):
        """Show Orion login dialog"""
        try:
            if not self.available:
                return False
            orion = Orion(self.app_key)
            return orion.userLogin()
        except (AttributeError, TypeError, RuntimeError) as e:
            c.log(f'[Orion API] Error during authorization: {e}', 1)
            return False

    def open_settings(self):
        """Open Orion settings dialog"""
        try:
            if not self.available:
                return
            orion = Orion(self.app_key)
            orion.settingsLaunch()
        except (AttributeError, RuntimeError) as e:
            c.log(f'[Orion API] Error opening settings: {e}', 1)

    def open_filter_settings(self):
        """Open Orion filter settings"""
        try:
            if not self.available:
                return
            orion = Orion(self.app_key)
            orion.settingsFilters()
        except (AttributeError, RuntimeError) as e:
            c.log(f'[Orion API] Error opening filter settings: {e}', 1)

    def show_user_dialog(self):
        """Show Orion account info dialog"""
        try:
            if not self.available:
                return
            orion = Orion(self.app_key)
            orion.userDialog()
        except (AttributeError, RuntimeError) as e:
            c.log(f'[Orion API] Error showing user dialog: {e}', 1)


class orionApi:
    def __init__(self):
        self.base_url = 'https://api.orionoid.com'
        self.appkey = keys.orion_key
        self.testkey = 'TESTTESTTESTTESTTESTTESTTESTTEST'
        self.orion_installed = self.is_orion_installed()
        self.session = requests.Session()
        self.retries = Retry(total=3, backoff_factor=0.5)
        self.session.mount(self.base_url, HTTPAdapter(max_retries=self.retries))
        self.orion = Orion(self.appkey)

    def __del__(self):
        if hasattr(self, 'session'):
            try:
                self.session.close()
            except Exception:
                pass

    def get_orion(self, mode, action, data):
        try:
            headers = {
                'Content-Type': 'application/json',
            }
            addonID = xbmcaddon.Addon().getAddonInfo("id")

            data = json.dumps(data) if data else None
            #build url

            response = self.session.post(url, json=data, headers=headers, timeout=15)


        except (requests.RequestException, json.JSONDecodeError, NameError) as e:
            pass

            failure = traceback.format_exc()
            pass





    def is_orion_installed(self):# -> Any:
        return xbmc.getCondVisibility('System.HasAddon(script.module.orion)')

    def get_credentials_info(self) -> bool:
        """Check if user has valid Orion credentials."""
        try:
            orion = Orion(self.appkey)
            # Orion module stores credentials internally, check if enabled and valid
            return orion.userEnabled() and orion.userValid()
        except (AttributeError, TypeError) as e:
            return False

    def get_user_tier_info(self) -> dict:
        """Get Orion user account tier information programmatically.

        Returns:
            dict with keys: 'package', 'link_limit', 'link_used', 'link_remaining'
            Returns None if user not authenticated or API call fails
        """
        try:
            orion = Orion(self.appkey)

            # Check if user is authenticated
            if not (orion.userEnabled() and orion.userValid()):
                c.log("[Orion] User not authenticated, cannot retrieve tier info")
                return None

            # Retrieve user account information
            user_data = orion.user()

            if user_data and user_data.get('result') and user_data['result'].get('data'):
                data = user_data['result']['data']

                # Extract tier information
                tier_info = {
                    'package': data.get('package', {}).get('name', 'Unknown'),
                    'link_limit': data.get('limit', {}).get('link', {}).get('total', 0),
                    'link_used': data.get('limit', {}).get('link', {}).get('used', 0),
                    'link_remaining': data.get('limit', {}).get('link', {}).get('remaining', 0),
                    'hash_limit': data.get('limit', {}).get('hash', {}).get('total', 0),
                    'container_limit': data.get('limit', {}).get('container', {}).get('total', 0),
                }

                return tier_info
            else:
                c.log("[Orion] Failed to retrieve user data from API")
                return None

        except (AttributeError, KeyError, TypeError) as e:
            c.log(f"[Orion] Error retrieving tier info: {e}")
            return None

    def get_smart_limit(self) -> int:
        """Get smart result limit based on user's Orion tier and remaining quota.

        Returns:
            Appropriate limit (10-250) based on tier and usage, or None to use Orion settings
        """
        tier_info = self.get_user_tier_info()

        if not tier_info:
            # User not authenticated or API failed - use conservative default
            c.log("[Orion] No tier info available, using conservative limit: 25")
            return 25

        package = tier_info.get('package', '').lower()
        remaining = tier_info.get('link_remaining', 0)
        total_limit = tier_info.get('link_limit', 0)

        # Calculate percentage remaining
        if total_limit > 0:
            percent_remaining = (remaining / total_limit) * 100
        else:
            percent_remaining = 0


        # Tier-based limits with quota awareness
        if 'expert' in package or 'premium' in package:
            # High-tier users: 100-250 based on remaining quota
            if percent_remaining > 50:
                limit = 250
            elif percent_remaining > 25:
                limit = 150
            elif percent_remaining > 10:
                limit = 100
            else:
                limit = 50  # Low quota - conserve

        elif 'basic' in package or 'standard' in package:
            # Mid-tier users: 50-100 based on remaining quota
            if percent_remaining > 50:
                limit = 100
            elif percent_remaining > 25:
                limit = 75
            else:
                limit = 50

        else:
            # Free or unknown tier: conservative 25-50
            if percent_remaining > 50:
                limit = 50
            elif percent_remaining > 25:
                limit = 35
            else:
                limit = 25

        return limit

    def get_movie(self, imdb, limit=None) -> dict:
        """Get movie streams from Orion.

        Args:
            imdb: IMDb ID
            limit: Override Orion's configured limit (None = use Orion settings)
        """
        # Use FilterSettings (None) to respect user's Orion settings, or override with limit parameter
        limitCount = limit if limit is not None else Orion.FilterSettings
        results = self.orion.streams(
            type=Orion.TypeMovie,
            idImdb=imdb,
            limitCount=limitCount
        )
        return results

    def get_episode(self, imdb=0, tmdb=0, title='', season=0, episode=0, limit=None) -> dict:
        """Get episode streams from Orion.

        Args:
            imdb: IMDb ID
            tmdb: TMDB ID
            title: Show title (fallback search)
            season: Season number
            episode: Episode number
            limit: Override Orion's configured limit (None = use Orion settings)
        """
        # Use FilterSettings (None) to respect user's Orion settings, or override with limit parameter
        limitCount = limit if limit is not None else Orion.FilterSettings

        if imdb and imdb != 0:
            results = self.orion.streams(
                type=Orion.TypeShow,
                idImdb=imdb,
                numberSeason=season,
                numberEpisode=episode,
                limitCount=limitCount
            )
        elif tmdb and tmdb != 0:
            results = self.orion.streams(
                type=Orion.TypeShow,
                idTmdb=tmdb,
                numberSeason=season,
                numberEpisode=episode,
                limitCount=limitCount
            )
        elif title and title != '':
            results = self.orion.streams(
                type=Orion.TypeShow,
                query=title,
                limitCount=limitCount
            )
        else:
            return None
        return results

    def do_orion_scrape(self, data, _type='movie'):
        """Parse Orion API results into source format.

        Args:
            data: List of stream dictionaries from Orion API
            _type: 'movie' or 'episode'
        """
        try:
            sources = []

            # Validate data
            if data is None:
                c.log("[Orion] No data returned (API key not configured or service unavailable)")
                return []

            if not isinstance(data, list):
                c.log(f"[Orion] Unexpected data type: {type(data)}")
                return []

            if len(data) == 0:
                c.log("[Orion] No streams found for this title")
                return []


            # Log first item structure for debugging (only once)
            if len(data) > 0 and c.devmode:
                pass  # Debug logs removed, keeping structure for future use

            if _type == 'movie':
                for i, item in enumerate(data):
                    try:
                        # Extract link
                        links = item.get("links", [])
                        url = ''
                        for link in links:
                            if link.startswith("magnet:") and url == '':
                                url = link
                                break

                        if not url:
                            continue

                        # Extract file info
                        fileinfo = item.get("file", {})
                        name = fileinfo.get("name", "")
                        path = fileinfo.get("path", "")  # Full path if available (Orion API improvement)
                        size = fileinfo.get("size", 0)
                        pack = fileinfo.get("pack", None)  # Check if it's a pack

                        # Prefer path over name for better context (e.g., "Show.2160p/S01/E01.mkv" vs "E01.mkv")
                        display_name = path if path else name

                        if not name:
                            continue

                        # Log pack detection for movies (this should NOT be a pack)
                        if pack and c.devmode:
                            pass  # Debug log removed

                        # Extract video metadata from API if available
                        video = item.get("video", {})
                        audio = item.get("audio", {})
                        stream_info = item.get("stream", {})

                        # Get quality from path (if available) or filename
                        # Path often contains better quality info than filename alone
                        quality, info = source_utils.get_release_quality(display_name)

                        # Enhance info with Orion API metadata (video/audio specs)
                        if video:
                            codec = video.get("codec", "")
                            if codec:
                                codec_map = {"h264": "H.264", "h265": "HEVC", "hevc": "HEVC", "x264": "H.264", "x265": "HEVC"}
                                codec_display = codec_map.get(codec.lower(), codec.upper())
                                if codec_display not in ' '.join(info):
                                    info.append(codec_display)

                        if audio:
                            channels = audio.get("channels", "")
                            codec = audio.get("codec", "")
                            if codec:
                                audio_map = {"dd": "DD", "ddp": "DD+", "dts": "DTS", "atmos": "ATMOS", "truehd": "TrueHD"}
                                audio_display = audio_map.get(codec.lower(), codec.upper())
                                if audio_display not in ' '.join(info):
                                    info.append(audio_display)
                            if channels and str(channels) not in ' '.join(info):
                                info.append(f"{channels}CH")

                        if stream_info:
                            source_type = stream_info.get("source", "")
                            if source_type:
                                source_map = {"webrip": "WEB-DL", "webdl": "WEB-DL", "bluray": "BluRay", "brrip": "BRRip"}
                                source_display = source_map.get(source_type.lower(), source_type)
                                if source_display not in ' '.join(info):
                                    info.append(source_display)

                        try:
                            dsize, isize = source_utils.file_size(size)
                        except (ValueError, TypeError, AttributeError, Exception):
                            dsize, isize = 0.0, ''  # Size parsing failed
                            info.insert(0, isize)

                        # Log enhanced info in devmode
                        if c.devmode and i < 3:  # Log first 3 items
                            pass  # Debug log removed

                        sources.append({
                            'provider': 'Orion',
                            'source': 'Torrent',
                            'quality': quality,
                            'language': 'en',
                            'url': url,
                            'info': ' | '.join(info) if isinstance(info, list) else info,
                            'direct': False,
                            'debridonly': True,
                            'size': dsize,
                            'name': display_name  # Use path if available for better context
                        })
                    except Exception as item_error:
                        c.log(f"[Orion] Error processing movie item {i}: {item_error}")
                        import traceback
                        c.log(f"[Orion] Traceback: {traceback.format_exc()}")
                        continue

                return sources

            else:  # episode
                for i, item in enumerate(data):
                    try:
                        # Extract link
                        links = item.get("links", [])
                        url = ''
                        for link in links:
                            if link.startswith("magnet:") and url == '':
                                url = link
                                break

                        if not url:
                            continue

                        # Extract file info
                        fileinfo = item.get("file", {})
                        name = fileinfo.get("name", "")
                        path = fileinfo.get("path", "")  # Full path if available (Orion API improvement)
                        size = fileinfo.get("size", 0)
                        pack = fileinfo.get("pack", None)  # Pack info (season/show pack)

                        # Prefer path over name for better context (e.g., "Show.2160p/S01/E01.mkv" vs "E01.mkv")
                        display_name = path if path else name

                        if not name:
                            continue

                        # Extract video/audio metadata from API
                        video = item.get("video", {})
                        audio = item.get("audio", {})
                        stream_info = item.get("stream", {})

                        # Get quality from path (if available) or filename
                        # Path often contains better quality info than filename alone
                        quality, info = source_utils.get_release_quality(display_name)

                        # Enhance info with Orion API metadata (video/audio specs)
                        if video:
                            codec = video.get("codec", "")
                            if codec:
                                codec_map = {"h264": "H.264", "h265": "HEVC", "hevc": "HEVC", "x264": "H.264", "x265": "HEVC"}
                                codec_display = codec_map.get(codec.lower(), codec.upper())
                                if codec_display not in ' '.join(info):
                                    info.append(codec_display)

                        if audio:
                            channels = audio.get("channels", "")
                            codec = audio.get("codec", "")
                            if codec:
                                audio_map = {"dd": "DD", "ddp": "DD+", "dts": "DTS", "atmos": "ATMOS", "truehd": "TrueHD"}
                                audio_display = audio_map.get(codec.lower(), codec.upper())
                                if audio_display not in ' '.join(info):
                                    info.append(audio_display)
                            if channels and str(channels) not in ' '.join(info):
                                info.append(f"{channels}CH")

                        if stream_info:
                            source_type = stream_info.get("source", "")
                            if source_type:
                                source_map = {"webrip": "WEB-DL", "webdl": "WEB-DL", "bluray": "BluRay", "brrip": "BRRip"}
                                source_display = source_map.get(source_type.lower(), source_type)
                                if source_display not in ' '.join(info):
                                    info.append(source_display)

                        try:
                            dsize, isize = source_utils.file_size(size)
                        except (ValueError, TypeError, AttributeError, Exception):
                            dsize, isize = 0.0, ''  # Size parsing failed
                            info.insert(0, isize)

                        # Log pack info in devmode
                        if c.devmode and i < 3:  # Log first 3 items
                            pass  # Debug log removed

                        source_dict = {
                            'provider': 'Orion',
                            'source': 'Torrent',
                            'quality': quality,
                            'language': 'en',
                            'url': url,
                            'info': ' | '.join(info) if isinstance(info, list) else info,
                            'direct': False,
                            'debridonly': True,
                            'size': dsize,
                            'name': display_name  # Use path if available for better context
                        }

                        # Add pack metadata if present
                        if pack:
                            source_dict['package'] = pack  # 'season' or 'show'

                        sources.append(source_dict)
                    except (KeyError, TypeError, AttributeError, ValueError) as item_error:
                        c.log(f"[Orion] Error processing episode item {i}: {item_error}")
                        import traceback
                        c.log(f"[Orion] Traceback: {traceback.format_exc()}")
                        continue

                return sources

        except (TypeError, AttributeError) as e:
            pass

            failure = traceback.format_exc()
            return []





    def authorize_orion(self):
        """Show Orion login dialog for user to enter credentials (API key, username/password)."""
        try:
            orion = Orion(self.appkey)
            # userLogin() shows the login dialog where users can enter their API key or credentials
            result = orion.userLogin()
            return result
        except (AttributeError, RuntimeError) as e:
            return False

    def settings_orion(self):
        """Open Orion's full settings dialog."""
        try:
            orion = Orion(self.appkey)
            orion.settingsLaunch()
        except (AttributeError, RuntimeError) as e:
            pass

    def settings_orion_filters(self):
        """Open Orion's filter settings dialog specifically."""
        try:
            orion = Orion(self.appkey)
            orion.settingsFilters()
        except (AttributeError, RuntimeError) as e:
            pass

    def user_info_orion(self):
        """Show Orion user account information dialog."""
        try:
            orion = Orion(self.appkey)
            # userDialog() shows account info (username, package, expiration, usage stats)
            orion.userDialog()
        except (AttributeError, RuntimeError) as e:
            pass

    def info_orion(self):
        """Get Orion info for a test movie."""
        results = self.get_movie('tt5519340')

    @classmethod
    def auth_orion(cls):
        """
        Authenticate with Orion - shows login dialog.
        This is a classmethod to match the pattern of other auth methods.
        """
        try:
            orion = Orion(keys.orion_key)

            # Show the Orion login dialog where users can enter their API key or credentials
            result = orion.userLogin()

            if result:
                control.infoDialog("Orion authentication successful", icon='INFO')
            else:
                pass

            return result
        except (AttributeError, RuntimeError) as e:
            pass

            failure = traceback.format_exc()
            control.infoDialog("Orion authentication failed", icon='ERROR')
            return False





oa = orionApi()
####################################################################################################


def window():
    file = 'LogViewer_QR.xml'
    path = c.artwork_path
    skin = c.appearance()
    resolution = '1080i'
    return xbmcgui.WindowXMLDialog(file, path, skin, resolution)

def get_orion_qr():
    try:
        #r = open(CHANGELOG_FILE)
        #text = r.read()
        header = "authenticate orion"
        url = "https%3A%2F%2Ftrakt.tv%2Factivate%2FECFABC3" # test for now
        size = "260"
        text = "for now just some text"
        qr_code = f"https://api.qrserver.com/v1/create-qr-code/?data={url}&size={size}x{size}"
        #view_orion_qr(window(),header, str(text), qr_code)
        # Call the function to show the dialog
        show_custom_dialog()
    except (ValueError, TypeError) as e:
        pass

        failure = traceback.format_exc()
        pass





def view_orion_qr(xml, header, message, qr_code) -> None:
    class orionQRViewer(xbmcgui.WindowXMLDialog):
        def __init__(self, xml, header, message, qr_code):
            if not header or not message or not qr_code:
                return
            super().__init__()
            self.initialize(self)
            self.header = header
            self.message = message
            self.qr_code = qr_code
            self.xml = xml

        def initialize(self):
            #key id's
            self.KEY_NAV_ENTER = 7
            self.KEY_NAV_ESC = 10
            self.KEY_NAV_BACK = 92

            self.KEY_NAV_MOVEUP = 3
            self.KEY_NAV_MOVEDOWN = 4
            self.KEY_NAV_PAGEUP = 5
            self.KEY_NAV_PAGEDOWN = 6

            #xml id's
            self.HEADERLABEL = 101
            self.TEXT = 502
            self.QR_IMAGE = 501
            self.CLOSEBUTTON = 503

            self.TITLE = '[B]' + c.module_addon + ' v.' + c.moduleversion + '[/B]'


        def onInit(self):
            HEADERTITLE = self.TITLE if header == '' else header
            self.getControl(self.HEADERLABEL).setLabel(HEADERTITLE)
            self.getControl(self.TEXT).setText(message)
            self.getControl(self.QR_IMAGE).setImage(qr_code)

        def onAction(self, action):
            try:
                actionID = action.getId()
            except (AttributeError, Exception):
                return  # Invalid action object

            if actionID in[self.KEY_NAV_BACK, self.KEY_NAV_ENTER, self.KEY_NAV_ESC]:
                self.close()

            if actionID in [self.KEY_NAV_MOVEUP, self.KEY_NAV_PAGEUP]:
                self.getControl(self.TEXT).scroll(1)

            if actionID in [self.KEY_NAV_MOVEDOWN, self.KEY_NAV_PAGEDOWN]:
                self.getControl(self.TEXT).scroll(-1)

        def onClick(self, controlId):
            try:
                if controlId == self.CLOSEBUTTON:
                    self.close()
            except (Exception):
                pass  # Control operation failed

    try:
        d = orionQRViewer(header, message, qr_code)
        d.doModal()
        del d
    except (AttributeError, RuntimeError) as e:
        pass

        failure = traceback.format_exc()
        pass
















class CustomDialog(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialize necessary variables for the dialog
        self.label = None
        self.title = None
        self.background = None
        self.qr_code = None

    def onInit(self):
        # Called when the dialog is initialized (window is loaded)
        self.background_id = 100
        self.header_id = 101
        self.qr_code_id = 501
        self.qr_code_text_id = 502
        self.button_id = 503

        self.set_title("Default Title")
        self.set_label("Default Label")
        self.set_background("logviewer_bg.png")

    def onAction(self, action):
        """Handle all keystrokes."""
        if action is None:
            return

        keycode = action.getId()

        if keycode == xbmcgui.ACTION_NAV_BACK:
            # Example: Close the dialog if the back button is pressed
            self.close()
        elif keycode == xbmcgui.ACTION_SELECT_ITEM:
            # Handle the select button (Enter key) if needed
            pass
        elif keycode == xbmcgui.ACTION_MOVE_UP:
            # Handle up movement
            pass
        elif keycode == xbmcgui.ACTION_MOVE_DOWN:
            # Handle down movement
            pass
        else:
            if keycode != "107":
                pass

    def set_label(self, text):
        """Set the text for the label in the dialog."""
        if self.label:
            self.label.setLabel(text)
        else:
            c.log("Label not found!")

    def set_title(self, title):
        """Set the title for the dialog."""
        if title:
            self.getLabel(self.header_id).setLabel(title)
        else:
            c.log("Title not found!")

    def set_background(self, background_image):
        """Set the background image."""
        if self.background:
            self.getLabel(self.background_id).setImage(background_image)
        else:
            c.log("Background image not found!")

    def load_custom_elements(self):
        """Load the custom elements from the XML (e.g., label, title, background)."""
        # Example: Assuming the label is a control named 'label' in the XML  # Example control ID for the label
        try:
            self.title = self.getControl(101)  # Example control ID for the title
            self.background = self.getControl("100")
            self.qr_code = self.getControl("501")  # Example control ID for the background image
            self.qr_txt = self.getControl("502")  # Example control ID for the background image
            self.button = self.getControl("503")  # Example control ID for the background image
        except (RuntimeError, ValueError, TypeError) as e:
            pass

            failure = traceback.format_exc()
            pass

# Function to create and show the dialog
def show_custom_dialog(*args, **kwargs):
    # Path to your custom XML file. Make sure to replace this with your actual file path.
    try:
        xml_path = "LogViewer_QR.xml"  # Replace with your actual path

        # Path to the skin directory (required for non-standard XML files)
        #skin_path = xbmcvfs.translatePath("special://skin/")

        skin_path = c.artwork_path # Using Kodi's special path for skin location
        temp = c.get_artwork_path()

        skin_path = temp +  "resources/skins/thecrew/1080i/"


        # Create an instance of the custom dialog class
        #dialog = CustomDialog(xml_path, skin_path, "default", "1080i")
        ARTADDON_PATH = xbmcaddon.Addon('script.thecrew.artwork').getAddonInfo('path')
        dialog = CustomDialog('LogViewer_QR.xml', ARTADDON_PATH, c.appearance(), '1080i')



        # Load custom elements (like label, title, background)
        #dialog.load_custom_elements()

        # Show the dialog
        dialog.doModal()

        # Cleanup after dialog is closed
        del dialog
    except (RuntimeError, ImportError, AttributeError) as e:
        c.log(f"Failed to load custom dialog: {str(e)}")

# Call the function to show the dialog
#show_custom_dialog()
