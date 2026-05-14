import xbmc
import xbmcgui
from datetime import datetime
import urllib.parse
from typing import Dict, List, Any

class SearchWindow(xbmcgui.WindowXML):
    def __init__(self, xml_file: str, addon_path: str, channels: List[Dict[str, Any]] = None, programs: List[Dict[str, Any]] = None):
        super().__init__(xml_file, addon_path, "default")
        self.channels = channels or []
        self.programs = programs
        self.list_control = None

    def onInit(self):
        try:
            # Get list control
            self.list_control = self.getControl(100)
            # Show keyboard
            keyboard = xbmc.Keyboard('', 'Search Channels and Programs')
            keyboard.doModal()
            
            if not keyboard.isConfirmed():
                self.close()
                return
                
            search_term = keyboard.getText().lower().strip()
            if not search_term:
                self.close()
                return
            # Search channels and programs
            current_time = datetime.now().astimezone()
            found_channels = []
            found_programs = []
            # Search channels
            for channel in self.channels:
                if search_term in channel['name'].lower():
                    found_channels.append(channel)
            # Search programs
            for program in self.programs:
                if program['stop'] >= current_time:
                    if search_term in program['title'].lower():
                        # Find matching channel
                        channel = next((c for c in self.channels if c['tvg_id'] == program['channel']), None)
                        if channel:
                            found_programs.append({
                                'program': program,
                                'channel': channel
                            })
            # Add results to list
            header = xbmcgui.ListItem(f'[COLOR gold]Search Results for "{search_term}"[/COLOR]')
            self.list_control.addItem(header)

            if found_channels:
                section = xbmcgui.ListItem(f'[COLOR yellow]Matching Channels ({len(found_channels)})[/COLOR]')
                self.list_control.addItem(section)
                
                for channel in found_channels:
                    name = f"[COLOR yellow]► {channel['name']}[/COLOR]"
                    item = xbmcgui.ListItem(name)
                    item.setArt({'icon': channel['logo'], 'thumb': channel['logo']})
                    item.setProperty('type', 'channel')
                    item.setProperty('channel_id', channel['tvg_id'])
                    self.list_control.addItem(item)

            if found_programs:
                section = xbmcgui.ListItem(f'[COLOR lime]Matching Programs ({len(found_programs)})[/COLOR]')
                self.list_control.addItem(section)
                
                for result in found_programs:
                    program = result['program']
                    channel = result['channel']
                    start_time = program['start'].strftime('%I:%M %p')
                    name = f"[COLOR lime]{program['title']}[/COLOR] on {channel['name']} at {start_time}"
                    
                    item = xbmcgui.ListItem(name)
                    item.setArt({'icon': channel['logo'], 'thumb': channel['logo']})
                    item.setProperty('type', 'program')
                    item.setProperty('channel_id', channel['tvg_id'])
                    self.list_control.addItem(item)

            if not found_channels and not found_programs:
                no_results = xbmcgui.ListItem('[COLOR red]No matches found[/COLOR]')
                self.list_control.addItem(no_results)
            # Set focus to list
            self.setFocusId(100)

        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Failed to initialize search: {str(e)}")
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
                
                item_type = item.getProperty('type')
                if item_type in ['channel', 'program']:
                    channel_id = item.getProperty('channel_id')
                    self.play_channel(channel_id)

        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Error handling click: {str(e)}")

    def onAction(self, action):
        try:
            if action.getId() in [9, 10, 92, 216, 247, 257, 275, 61467, 61448]:
                self.close()
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Error handling action: {str(e)}")