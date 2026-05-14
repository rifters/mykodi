import xbmc
import xbmcgui
import xbmcaddon
import urllib.parse
from urllib.parse import urlencode, quote
from typing import Dict, List, Any
from favorites import favorites_manager

ADDON = xbmcaddon.Addon()

class ChannelListWindow(xbmcgui.WindowXML):
    def __init__(self, xml_file: str, addon_path: str, channels: List[Dict[str, Any]] = None):
        super().__init__(xml_file, addon_path, "default")
        self.channels = channels or []
        self.list_control = None
    def onInit(self):
        """Initialize window after creation"""
        try:
            # Get list control
            self.list_control = self.getControl(100)
            # Populate channels
            for channel in self.channels:
                name = channel.get('name', channel.get('title', 'Unknown Channel'))
                # Add star to favorites
                if favorites_manager.is_favorite(channel['tvg_id']):
                    name = f"[COLOR gold]★[/COLOR] {name}"
                list_item = xbmcgui.ListItem(name)
                list_item.setArt({'icon': channel.get('logo', '')})
                # Context menu will be handled by onAction
                self.list_control.addItem(list_item)
            # Set focus to list
            self.setFocusId(100)
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Failed to initialize channel list: {str(e)}")
            self.close()
    def make_url(self, action: str, channel_id: str) -> str:
        """Create properly encoded plugin URL"""
        base = "plugin://plugin.video.jet_guide/"
        params = urllib.parse.urlencode({'action': action, 'id': channel_id})
        url = f"{base}?{params}"
        xbmc.log(f"ChannelList: Created URL for action={action}, id={channel_id}: {url}", xbmc.LOGINFO)
        return url
    def play_channel(self, channel: Dict[str, Any]):
        """Play a channel directly"""
        try:
            # Create list item
            list_item = xbmcgui.ListItem(channel['name'])
            list_item.setArt({'icon': channel.get('logo', '')})
            # Set stream URL directly
            url = channel['url']
            if '|' in url:
                url = url.split('|')[0].strip()
            # Play without dialogs
            xbmc.executebuiltin('Dialog.Close(busydialog)')
            
            # Cancel any running YouTube sequential playback before playing new content
            try:
                from youtube_guide import cancel_youtube_playback
                cancel_youtube_playback()
            except ImportError:
                pass  # youtube_guide not available
            
            xbmc.Player().play(url, list_item)
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Failed to play channel: {str(e)}")
    def onClick(self, control_id):
        """Handle click events"""
        try:
            if control_id == 100:  # Main list
                pos = self.list_control.getSelectedPosition()
                if 0 <= pos < len(self.channels):
                    channel = self.channels[pos]
                    xbmc.log(f"ChannelList: Playing channel {channel['name']} ({channel['tvg_id']})", xbmc.LOGINFO)
                    self.play_channel(channel)
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Error handling click: {str(e)}")
    def onAction(self, action):
        """Handle various window actions"""
        try:
            action_id = action.getId()
            if action_id in [11, 117]:  # Info button or context menu
                pos = self.list_control.getSelectedPosition()
                if 0 <= pos < len(self.channels):
                    channel = self.channels[pos]
                    dialog = xbmcgui.Dialog()
                    # Show different options based on favorite status
                    is_favorite = favorites_manager.is_favorite(channel['tvg_id'])
                    options = ["Play Channel", "Show Guide", "Save to Jet Guide"]
                    if is_favorite:
                        options = ["Play Channel", "Show Guide", "Remove from Favorites"]
                    else:
                        options.append("Remove from Favorites")
                    choice = dialog.select("Channel Options", options)
                    if choice == 0:  # Play Channel
                        self.play_channel(channel)
                    elif choice == 1:  # Show Guide
                        # Close window before opening guide
                        url = self.make_url('show_channel', channel['tvg_id'])
                        self.close()
                        xbmc.executebuiltin(f'ActivateWindow(videos,{url})')
                    elif choice == 2:  # Save to Jet Guide
                        try:
                            # Save channel to jet_guide_imported.json in addon profile
                            import xbmcvfs, json
                            profile_path = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
                            save_path = profile_path + "jet_guide_imported.json"
                            if xbmcvfs.exists(save_path):
                                with xbmcvfs.File(save_path, 'r') as f:
                                    imported = json.loads(f.read())
                            else:
                                imported = []
                            # Avoid duplicates
                            if not any(c['tvg_id'] == channel['tvg_id'] for c in imported):
                                imported.append(channel)
                                with xbmcvfs.File(save_path, 'w') as f:
                                    f.write(json.dumps(imported, indent=2, ensure_ascii=False))
                                xbmcgui.Dialog().notification('Jet Guide', 'Channel saved!', xbmcgui.NOTIFICATION_INFO, 2000)
                            else:
                                xbmcgui.Dialog().notification('Jet Guide', 'Channel already saved.', xbmcgui.NOTIFICATION_INFO, 2000)
                        except Exception as e:
                            xbmcgui.Dialog().ok('Error', f'Failed to save channel: {str(e)}')
                    elif choice == 2:  # Add/Remove from Favorites
                        if is_favorite:
                            if favorites_manager.remove_favorite(channel['tvg_id']):
                                xbmcgui.Dialog().notification('TV Guide', 'Channel removed from favorites')
                                self.close()
                        else:
                            if favorites_manager.add_favorite(channel['tvg_id']):
                                xbmcgui.Dialog().notification('TV Guide', 'Channel added to favorites')
                                self.close()
            elif action_id in [9, 10, 92, 216, 247, 257, 275, 61467, 61448]:
                # Handle Esc or Back button
                self.close()
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Error handling action: {str(e)}")