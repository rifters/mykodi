import xbmc
import xbmcgui
import urllib.parse
from typing import Dict, List, Any

class FavoritesWindow(xbmcgui.WindowXML):
    def __init__(self, xml_file: str, addon_path: str, channels: List[Dict[str, Any]] = None, favorites_manager=None):
        super().__init__(xml_file, addon_path, "default")
        self.channels = channels or []
        self.favorites_manager = favorites_manager
        self.list_control = None

    def onInit(self):
        """Initialize window after creation"""
        try:
            # Get list control
            self.list_control = self.getControl(100)
            # Get favorite channels
            favorite_channels = []
            for channel in self.channels:
                if self.favorites_manager.is_favorite(channel['tvg_id']):
                    favorite_channels.append(channel)
            # Add header
            header = xbmcgui.ListItem('[COLOR gold]Favorite Channels[/COLOR]')
            self.list_control.addItem(header)
            # Add channels
            if favorite_channels:
                for channel in favorite_channels:
                    name = f"[COLOR yellow]► {channel['name']}[/COLOR]"
                    list_item = xbmcgui.ListItem(name)
                    list_item.setArt({'icon': channel.get('logo', '')})
                    list_item.setProperty('channel_id', channel['tvg_id'])
                    self.list_control.addItem(list_item)
            else:
                no_favorites = xbmcgui.ListItem('[COLOR red]No favorite channels added yet[/COLOR]')
                self.list_control.addItem(no_favorites)
            # Set focus to list
            self.setFocusId(100)
            
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Failed to initialize favorites: {str(e)}")
            self.close()

    def play_channel(self, channel_id: str):
        """Play a channel directly"""
        try:
            # Find the channel
            channel = next((c for c in self.channels if c['tvg_id'] == channel_id), None)
            if not channel:
                return
            # Create list item
            list_item = xbmcgui.ListItem(channel['name'])
            list_item.setArt({'icon': channel.get('logo', '')})
            # Set stream URL directly
            url = channel['url']
            if '|' in url:
                url = url.split('|')[0].strip()
            # Close dialog and play
            xbmc.executebuiltin('Dialog.Close(busydialog)')
            self.close()
            
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
        try:
            if control_id == 100:
                pos = self.list_control.getSelectedPosition()
                item = self.list_control.getSelectedItem()
                if pos > 0:  # Skip header item
                    channel_id = item.getProperty('channel_id')
                    if channel_id:
                        self.play_channel(channel_id)

        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Error handling click: {str(e)}")

    def onAction(self, action):
        try:
            action_id = action.getId()
            if action_id in [11, 117]:  # Info button or context menu
                pos = self.list_control.getSelectedPosition()
                item = self.list_control.getSelectedItem()
                if pos > 0:  # Skip header item
                    channel_id = item.getProperty('channel_id')
                    if channel_id:
                        dialog = xbmcgui.Dialog()
                        choice = dialog.select("Channel Options", ["Play Channel", "Show Guide", "Remove from Favorites"])
                        
                        if choice == 0:  # Play Channel
                            self.play_channel(channel_id)
                        elif choice == 1:  # Show Guide
                            self.close()
                            url = f"plugin://plugin.video.jet_guide/?action=show_channel&id={urllib.parse.quote(channel_id)}"
                            xbmc.executebuiltin(f'ActivateWindow(videos,{url})')
                        elif choice == 2:  # Remove from Favorites
                            if self.favorites_manager.remove_favorite(channel_id):
                                xbmc.executebuiltin('Container.Refresh')
                                xbmcgui.Dialog().notification('TV Guide', 'Channel removed from favorites')
                                self.close()

            elif action_id in [9, 10, 92, 216, 247, 257, 275, 61467, 61448]:
                # Handle Esc or Back button
                self.close()
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Error handling action: {str(e)}")