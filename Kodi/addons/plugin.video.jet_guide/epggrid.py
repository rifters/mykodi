from tenbuttons import browse_installed_video_addons, browse_addon_plugin_folders
import xbmc
import xbmcgui
import xbmcaddon
import time
import os,json
import sys
import xbmcplugin
import tzlocal
from datetime import datetime, timedelta, timezone
import xbmcvfs
from typing import Dict, List, Any
from reminders import add_reminder, list_reminders
from tools import show_tools, debug_log
# from tenbuttons import onClick
JET_GUIDE_IMPORTED_PATH = xbmcvfs.translatePath("special://userdata/addon_data/plugin.video.jet_guide/jet_guide_imported.json")

addon = xbmcaddon.Addon()
ADDON = xbmcaddon.Addon()

class EPGGrid(xbmcgui.WindowXML):
    def __init__(self, xml_file: str, addon_path: str, channels: List[Dict[str, Any]] = None, programs: List[Dict[str, Any]] = None):
        """Initialize EPG Grid window"""
        self.is_closing = False  # Flag to stop background processes
        try:
            super().__init__(xml_file, addon_path, "default")
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Failed to initialize EPG: {str(e)}")
            raise
            
        self.is_favorites_view = False
        self.is_sports_view = False
        self.all_channels = channels if channels else []
        self.channels = self.all_channels[:]
        self.current_category = ''
        self.last_category = ''
        self.programs = programs or []
        self.channel_panel = None
        self.program_cache = {}
        self.visible_rows = 5000
        self.current_page = 0
        self.current_channel_idx = 0  # Track absolute channel index
        self.time_scroll_pos = 0
        self.last_play_time = 0  # Initialize for playback 
        self.selected_program = None
        self.categories = []
        self.button_controls = {}
        self.local_tz = datetime.now().astimezone().tzinfo
        self.set_time_slots()
        # Defensive: avoid NoneType in len()
        prog_len = len(programs) if programs is not None else 0
        chan_len = len(channels) if channels is not None else 0
        debug_log(f"DEBUG: EPGGrid init, programs_len={prog_len}, channels_len={chan_len}", xbmc.LOGINFO)
        self.build_program_cache()

    def onInit(self):
        """Initialize grid after window creation"""
        try:
            self.last_category = ''
            self.connect_category_filter()
            self.categories = self.get_unique_categories()
            self.channel_panel = self.getControl(110)  # Single panel for channels and programs
            if not self.channel_panel:
                raise Exception("Failed to get channel panel")
                
            self.create_category_buttons()
            self.create_grid()
            self.setFocusId(110)
            self.channel_panel.selectItem(0)
            self.update_selected_program_info()
            
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Failed to initialize EPG: {str(e)}")
            self.close()

    def get_unique_categories(self) -> List[str]:
        """Extract unique categories from channels or programs."""
        if self.is_favorites_view:
            return []
            
        categories = set()
        for channel in self.all_channels:
            group = channel.get('group', '')
            if group:
                categories.add(group)
                
        unique_categories = sorted(list(categories))
        return unique_categories

    def build_program_cache(self):
        """Build cache of programs."""
        if self.is_closing:
            # debug_log(f"DEBUG: build_program_cache aborted due to window closing", xbmc.LOGINFO)
            return
        start_time = time.time()
        self.program_cache = {}
        # debug_log(f"DEBUG: build_program_cache started, programs_len={len(self.programs)}, channels_len={len(self.channels)}", xbmc.LOGINFO)
        local_tz = self.local_tz
        channel_ids = {channel['tvg_id'] for channel in self.channels}
        now = datetime.now().astimezone(local_tz)
        start_window = now - timedelta(hours=7)
        end_time = now + timedelta(hours=24)
        if not self.programs:
            debug_log(f"DEBUG: build_program_cache: no programs provided", xbmc.LOGERROR)
            return
        filtered_programs = 0
        for i, program in enumerate(self.programs):
            if self.is_closing:
                debug_log(f"DEBUG: build_program_cache interrupted due to window closing", xbmc.LOGINFO)
                break
            channel = program.get('channel')
            if not channel or channel not in channel_ids:
                continue
            try:
                start = program.get('start')
                stop = program.get('stop')
                if isinstance(start, str):
                    try:
                        if ' -0' in start or ' +0' in start:
                            start = start.replace(' ', 'T')
                            start_dt = datetime.strptime(start, '%Y%m%d%H%M%ST%z')
                            start_dt = start_dt.astimezone(local_tz)
                        else:
                            start_dt = datetime.strptime(start[:14], '%Y%m%d%H%M%S')
                            edt = timezone(timedelta(hours=0))
                            start_dt = start_dt.replace(tzinfo=edt)
                            start_dt = start_dt.astimezone(local_tz)
                    except ValueError:
                        continue
                elif isinstance(start, datetime):
                    if start.tzinfo is None:
                        start_dt = start.replace(tzinfo=local_tz)
                    else:
                        start_dt = start
                else:
                    continue
                if isinstance(stop, str):
                    try:
                        if ' -0' in stop or ' +0' in stop:
                            stop = stop.replace(' ', 'T')
                            stop_dt = datetime.strptime(stop, '%Y%m%d%H%M%ST%z')
                            stop_dt = stop_dt.astimezone(local_tz)
                        else:
                            stop_dt = datetime.strptime(stop[:14], '%Y%m%d%H%M%S')
                            edt = timezone(timedelta(hours=0))
                            stop_dt = stop_dt.replace(tzinfo=edt)
                            stop_dt = stop_dt.astimezone(local_tz)
                    except ValueError:
                        continue
                elif isinstance(stop, datetime):
                    if stop.tzinfo is None:
                        stop_dt = stop.replace(tzinfo=local_tz)
                    else:
                        stop_dt = stop
                else:
                    continue
                start_local = start_dt
                stop_local = stop_dt
                if stop_local >= start_window and start_local <= end_time:
                    if channel not in self.program_cache:
                        self.program_cache[channel] = []
                    program_info = {
                        'start': start_local,
                        'stop': stop_local,
                        'title': program.get('title', 'No Title'),
                        'channel': channel,
                        'desc': program.get('desc', 'No description available'),
                        'category': program.get('category', ''),
                        'episode': program.get('episode-num', ''),
                        'rating': program.get('rating', ''),
                        'sub_title': program.get('sub-title', ''),
                        'actors': program.get('actors', []),
                        'icon': program.get('icon', None)
                    }
                    self.program_cache[channel].append(program_info)
                    filtered_programs += 1
                    # if filtered_programs % 100 == 0:
                    #     debug_log(f"DEBUG: Added program {filtered_programs}: {program_info['title']} for channel {channel}", xbmc.LOGDEBUG)
            except Exception:
                continue
        for channel in self.program_cache:
            self.program_cache[channel].sort(key=lambda x: x['start'])
        # debug_log(f"DEBUG: build_program_cache created {filtered_programs} program entries for {len(self.program_cache)} channels in {time.time() - start_time:.2f} seconds", xbmc.LOGINFO)

    def format_time(self, dt: datetime) -> str:
        """Format time according to user preference."""
        time_format = ADDON.getSetting('time_format')
        if time_format == '12h':
            return dt.strftime('%I:%M %p').lstrip('0')
        return dt.strftime('%H:%M')

    def set_time_slots(self):
        """Set up time slots for the grid."""
        now = datetime.now().astimezone(self.local_tz)
        current_minute = now.minute
        start_time = now.replace(minute=0, second=0, microsecond=0)
        if current_minute >= 30:
            start_time += timedelta(minutes=30)
        self.time_slots = []
        start_time = start_time - timedelta(hours=0)
        for i in range(96):
            slot_start = start_time + timedelta(minutes=30 * i)
            slot_end = slot_start + timedelta(minutes=30)
            self.time_slots.append((slot_start, slot_end))

    def update_time_labels(self):
        """Update time slot labels based on current scroll position."""
        for display_idx in range(4):
            slot_idx = self.time_scroll_pos + display_idx
            if slot_idx < len(self.time_slots):
                slot_start = self.time_slots[slot_idx][0]
                self.setProperty(f'time{display_idx}', self.format_time(slot_start))
            else:
                self.setProperty(f'time{display_idx}', '')

    def get_program_for_channel(self, channel_id: str, slot_start: datetime, slot_end: datetime) -> Dict[str, Any]:
        """Get program for a channel that overlaps with the given time slot."""
        if channel_id not in self.program_cache:
            return None
        for program in self.program_cache[channel_id]:
            prog_start = program['start']
            prog_stop = program['stop']
            if prog_start < slot_end and prog_stop > slot_start:
                return program
        return None

    def connect_category_filter(self):
        """Initialize category filter."""
        try:
            self.setProperty('CategoryFilter', '')
        except Exception:
            pass

    def create_category_buttons(self):
        """Dynamically populate category list control."""
        try:
            category_list = self.getControl(200)
            category_list.reset()
            item = xbmcgui.ListItem("All")
            item.setProperty("Category", "")
            category_list.addItem(item)
            for category in self.categories:
                item = xbmcgui.ListItem(category)
                item.setProperty("Category", category)
                category_list.addItem(item)
        except Exception:
            pass

    def check_category_filter(self):
        """Check and apply category filter if changed."""
        try:
            if not self.channel_panel:
                return
            category_list = self.getControl(200)
            selected_pos = category_list.getSelectedPosition()
            selected_item = category_list.getListItem(selected_pos)
            category = selected_item.getProperty("Category")
            if category == self.last_category:
                return
            self.last_category = category
            if category:
                self.filter_channels(category)
            else:
                self.channels = self.all_channels[:]
            self.current_page = 0
            self.current_channel_idx = -1
            self.create_grid()
            self.setFocusId(200)
            # self.channel_panel.selectItem(0)
        except Exception:
            pass

    def filter_channels(self, category: str):
        """Filter channels by category."""
        try:
            self.current_category = category
            if not category:
                self.channels = self.all_channels[:]
            else:
                self.channels = [c for c in self.all_channels if c.get('group', '').lower() == category.lower()]
            self.current_page = 0
            self.current_channel_idx = -1
            self.create_grid()
            self.setFocusId(200)
            # self.channel_panel.selectItem(0)
        except Exception:
            self.channels = self.all_channels[:]
            self.create_grid()

    def create_grid(self):
        """Create the EPG grid display."""
        try:
            if not self.channel_panel:
                return
            start_time = time.time()
            # Ensure current_channel_idx is within bounds
            if self.current_channel_idx >= len(self.channels):
                self.current_channel_idx = max(0, len(self.channels) - 1)
            if self.current_channel_idx < 0:
                self.current_page = 0
                start_idx = 0
            else:
                self.current_page = self.current_channel_idx // self.visible_rows
                start_idx = self.current_page * self.visible_rows
            end_idx = min(start_idx + self.visible_rows, len(self.channels))
            self.channel_panel.reset()
            self.update_time_labels()
            for idx in range(start_idx, end_idx):
                try:
                    channel = self.channels[idx]
                    item = xbmcgui.ListItem(str(idx + 1))
                    item.setLabel2(channel['name'])
                    item.setArt({'icon': channel.get('logo', '')})
                    for display_idx in range(4):
                        slot_idx = self.time_scroll_pos + display_idx
                        if slot_idx < len(self.time_slots):
                            slot_start, slot_end = self.time_slots[slot_idx]
                            program = self.get_program_for_channel(channel['tvg_id'], slot_start, slot_end)
                            item.setProperty(f'label{display_idx}', program['title'] if program else 'No Program')
                        else:
                            item.setProperty(f'label{display_idx}', 'No Program')
                    if idx == self.current_channel_idx:
                        item.select(True)
                    self.channel_panel.addItem(item)
                except Exception:
                    pass
            row = self.channel_panel.getSelectedPosition()
            # debug_log(f"DEBUG: create_grid completed in {time.time() - start_time:.2f} seconds, current_page={self.current_page}, current_channel_idx={self.current_channel_idx}, row={row}", xbmc.LOGINFO)
        except Exception as e:
            debug_log(f"DEBUG: create_grid error: {str(e)}", xbmc.LOGERROR)

    def update_selected_program_info(self):
        """Update the program info based on current selection."""
        try:
            channel_idx = self.current_channel_idx
            row = self.channel_panel.getSelectedPosition()
            expected_row = channel_idx % self.visible_rows
            # debug_log(f"DEBUG: update_selected_program_info: channel_idx={channel_idx}, row={row}, expected_row={expected_row}, channels_len={len(self.channels)}", xbmc.LOGINFO)
            if channel_idx < len(self.channels):
                channel = self.channels[channel_idx]
                # debug_log(f"DEBUG: Selected channel: {channel.get('name', 'Unknown')} (tvg_id={channel.get('tvg_id', '')}), logo={channel.get('logo', 'None')}", xbmc.LOGINFO)
                slot_idx = self.time_scroll_pos
                # debug_log(f"DEBUG: slot_idx={slot_idx}, time_slots_len={len(self.time_slots)}", xbmc.LOGINFO)
                if slot_idx < len(self.time_slots):
                    slot_start, slot_end = self.time_slots[slot_idx]
                    # debug_log(f"DEBUG: Checking programs for slot: {slot_start.isoformat()} to {slot_end.isoformat()}", xbmc.LOGINFO)
                    program = self.get_program_for_channel(channel['tvg_id'], slot_start, slot_end)
                    # if program:
                    #     debug_log(f"DEBUG: Found program: title={program.get('title', 'Unknown')}, start={program.get('start').isoformat()}, stop={program.get('stop').isoformat()}, icon={program.get('icon', 'None')}", xbmc.LOGINFO)
                    # else:
                    #     debug_log(f"DEBUG: No program found for channel {channel.get('tvg_id')} in slot {slot_start.isoformat()} to {slot_end.isoformat()}", xbmc.LOGWARNING)
                    self.update_program_info(program, channel)
                else:
                    debug_log(f"DEBUG: Invalid slot_idx={slot_idx}, setting default info", xbmc.LOGWARNING)
                    self.update_program_info(None, channel)
            else:
                debug_log(f"DEBUG: Invalid channel_idx={channel_idx}, no channel selected", xbmc.LOGWARNING)
                self.update_program_info(None, None)
        except Exception as e:
            debug_log(f"DEBUG: update_selected_program_info error: {str(e)}", xbmc.LOGERROR)

    def update_program_info(self, program: Dict[str, Any], channel: Dict[str, Any] = None):
        """Update the program info window with given program details."""
        profile_path = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
        debug_log_path = os.path.join(profile_path, "debug_log.txt")
        try:
            if not xbmcvfs.exists(profile_path):
                xbmcvfs.mkdirs(profile_path)
        except Exception:
            debug_log_path = xbmcvfs.translatePath("special://temp/debug_log.txt")
        
        def log_debug(message):
            try:
                with open(debug_log_path, "a", encoding='utf-8') as debug_file:
                    debug_file.write(f"{message}\n")
            except Exception:
                pass
        
        log_debug(f"\n\nUpdating program info at {datetime.now()}")
        if program:
            log_debug(f"Program: {program.get('title', 'Unknown').encode('utf-8', 'ignore').decode('utf-8')}")
            log_debug(f"Available keys: {', '.join(program.keys())}")
            
            title = program.get('title', 'Unknown').encode('utf-8', 'ignore').decode('utf-8')
            if program.get('sub_title'):
                title = f"{title} - {program['sub_title']}"
            self.setProperty('ProgramTitle', title)
            
            start_time = self.format_time(program['start']) if 'start' in program else 'Unknown'
            end_time = self.format_time(program['stop']) if 'stop' in program else 'Unknown'
            self.setProperty('ProgramTime', f"{start_time} - {end_time}")
            
            if channel:
                self.setProperty('ProgramChannel', f"{channel.get('name', 'Unknown')} (Channel {channel.get('tvg_id', '')})")
            else:
                self.setProperty('ProgramChannel', program.get('channel', 'Unknown'))
            sports_icon = ['soccer', 'football', 'basketball', 'hockey', 'baseball', 'tennis']
            default_icon = 'special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/HDHR.png'
            default_sports_icon = 'special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/sports_icon.png'
            if any(sport in title.lower() for sport in sports_icon):
                default_icon = default_sports_icon
            icon_url = channel.get('logo', default_icon) if channel else default_icon
            log_debug(f"Using icon: {icon_url}")
            self.setProperty('ProgramIcon', icon_url)
            
            desc = program.get('desc', 'No description available').encode('utf-8', 'ignore').decode('utf-8')
            if program.get('actors'):
                desc += f"\n\nActors: {', '.join(program['actors'])}"
            if program.get('rating'):
                desc += f"\nRating: {program['rating']}"
            if program.get('category'):
                if isinstance(program['category'], list):
                    desc += f"\nCategory: {', '.join(program['category'])}"
                else:
                    desc += f"\nCategory: {program['category']}"
            if program.get('episode'):
                desc += f"\nEpisode: {program['episode']}"
            self.setProperty('ProgramDescription', desc)
        else:
            log_debug("No program provided, setting default properties")
            self.setProperty('ProgramTitle', 'No Program')
            self.setProperty('ProgramTime', '')
            self.setProperty('ProgramChannel', channel.get('name', 'Unknown') if channel else 'Unknown')
            self.setProperty('ProgramIcon', 'special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/HDHR.png','special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/sports_icon.png')
            self.setProperty('ProgramDescription', 'No program information available.')
        
        log_debug("Program info update complete")

    def onAction(self, action):
        """Handle user actions."""
        try:
            action_id = action.getId()
            focus_id = self.getFocusId()
            debug_log(f"DEBUG: onAction received: action_id={action_id}, focus_id={focus_id}", xbmc.LOGINFO)
            if action_id in [xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK]:
                debug_log(f"DEBUG: Back action detected, closing EPGGrid", xbmc.LOGINFO)
                self.close()
                return
            if action_id == xbmcgui.ACTION_SELECT_ITEM and focus_id == 200:
                debug_log(f"DEBUG: Category selection triggered, focus_id=200", xbmc.LOGINFO)
                self.check_category_filter()
                return
            if action_id in [xbmcgui.ACTION_MOVE_UP, xbmcgui.ACTION_MOVE_DOWN]:
                if focus_id == 200 and action_id == xbmcgui.ACTION_MOVE_DOWN and self.channel_panel:
                    self.setFocusId(110)
                    self.current_channel_idx = 0
                    self.channel_panel.selectItem(0)
                    self.update_selected_program_info()
                    return
                if focus_id == 110 and self.channel_panel:
                    new_channel_idx = self.current_channel_idx
                    if action_id == xbmcgui.ACTION_MOVE_UP and new_channel_idx > 0:
                        new_channel_idx -= 1
                        new_page = new_channel_idx // self.visible_rows
                        new_pos = new_channel_idx % self.visible_rows
                        if new_page != self.current_page:
                            self.current_page = new_page
                            self.create_grid()
                        self.channel_panel.selectItem(new_pos)
                        self.current_channel_idx = new_channel_idx
                        xbmc.sleep(10)  # Brief delay to ensure selection is applied
                        debug_log(f"DEBUG: Arrow up, channel_idx={new_channel_idx}, new_pos={new_pos}, current_page={self.current_page}", xbmc.LOGINFO)
                        self.update_selected_program_info()
                        return  # Prevent native list navigation
                    elif action_id == xbmcgui.ACTION_MOVE_DOWN and new_channel_idx < len(self.channels) - 1:
                        new_channel_idx += 1
                        new_page = new_channel_idx // self.visible_rows
                        new_pos = new_channel_idx % self.visible_rows
                        if new_page != self.current_page:
                            self.current_page = new_page
                            self.create_grid()
                        self.channel_panel.selectItem(new_pos)
                        self.current_channel_idx = new_channel_idx
                        xbmc.sleep(10)  # Brief delay to ensure selection is applied
                        debug_log(f"DEBUG: Arrow down, channel_idx={new_channel_idx}, new_pos={new_pos}, current_page={self.current_page}", xbmc.LOGINFO)
                        self.update_selected_program_info()
                        return  # Prevent native list navigation
            if action_id in [xbmcgui.ACTION_MOUSE_WHEEL_UP, xbmcgui.ACTION_MOUSE_WHEEL_DOWN,
                            xbmcgui.ACTION_GESTURE_SWIPE_UP, xbmcgui.ACTION_GESTURE_SWIPE_DOWN]:
                if focus_id == 110 and self.channel_panel:
                    new_channel_idx = self.current_channel_idx
                    if action_id in [xbmcgui.ACTION_MOUSE_WHEEL_UP, xbmcgui.ACTION_GESTURE_SWIPE_DOWN]:
                        if new_channel_idx > 0:
                            new_channel_idx -= 1
                            new_page = new_channel_idx // self.visible_rows
                            if new_page != self.current_page:
                                self.current_page = new_page
                                self.create_grid()
                            self.channel_panel.selectItem(new_channel_idx % self.visible_rows)
                            # Update current_channel_idx to match highlighted channel
                            row = self.channel_panel.getSelectedPosition()
                            self.current_channel_idx = self.current_page * self.visible_rows + row
                            debug_log(f"DEBUG: Wheel up/swipe down, channel_idx={self.current_channel_idx}, current_page={self.current_page}", xbmc.LOGINFO)
                            self.update_selected_program_info()
                    elif action_id in [xbmcgui.ACTION_MOUSE_WHEEL_DOWN, xbmcgui.ACTION_GESTURE_SWIPE_UP]:
                        if new_channel_idx < len(self.channels) - 1:
                            new_channel_idx += 1
                            new_page = new_channel_idx // self.visible_rows
                            if new_page != self.current_page:
                                self.current_page = new_page
                                self.create_grid()
                            self.channel_panel.selectItem(new_channel_idx % self.visible_rows)
                            # Update current_channel_idx to match highlighted channel
                            row = self.channel_panel.getSelectedPosition()
                            self.current_channel_idx = self.current_page * self.visible_rows + row
                            debug_log(f"DEBUG: Wheel down/swipe up, channel_idx={self.current_channel_idx}, current_page={self.current_page}", xbmc.LOGINFO)
                            self.update_selected_program_info()
                    return
            if action_id in [xbmcgui.ACTION_MOVE_LEFT, xbmcgui.ACTION_MOVE_RIGHT]:
                if focus_id == 110:
                    if action_id == xbmcgui.ACTION_MOVE_LEFT and self.time_scroll_pos > 0:
                        self.time_scroll_pos -= 1
                        debug_log(f"DEBUG: Scrolled left, time_scroll_pos={self.time_scroll_pos}", xbmc.LOGINFO)
                        self.create_grid()
                        self.channel_panel.selectItem(self.current_channel_idx % self.visible_rows)
                        self.update_selected_program_info()
                    elif action_id == xbmcgui.ACTION_MOVE_RIGHT and self.time_scroll_pos < len(self.time_slots) - 4:
                        self.time_scroll_pos += 1
                        debug_log(f"DEBUG: Scrolled right, time_scroll_pos={self.time_scroll_pos}", xbmc.LOGINFO)
                        self.create_grid()
                        self.channel_panel.selectItem(self.current_channel_idx % self.visible_rows)
                        self.update_selected_program_info()
                    return
            if action_id == xbmcgui.ACTION_SELECT_ITEM and focus_id == 110:
                debug_log(f"DEBUG: ACTION_SELECT_ITEM triggered for channel_idx={self.current_channel_idx}, focus_id=110", xbmc.LOGINFO)
                self.play_selected_channel()
                return
            if action_id == 117:  # Context menu
                debug_log(f"DEBUG: Context menu triggered for channel_idx={self.current_channel_idx}", xbmc.LOGINFO)
                row = self.channel_panel.getSelectedPosition()
                channel_idx = self.current_page * self.visible_rows + row
                if channel_idx < len(self.channels):
                    channel = self.channels[channel_idx]
                    from favorites import favorites_manager
                    options = []
                    if favorites_manager.is_favorite(channel['tvg_id']):
                        options.append(('Remove from Favorites', 'remove'))
                    else:
                        options.append(('Add to Favorites', 'add'))
                    options.append(('Return to Video Player', 'return_video'))
                    options.append(('Play Channel', 'play'))
                    options.append(('Play from Jet Guide Imported', 'play_imported'))
                    options.append(('Play from Folder', 'play_from_folder'))
                    # options.append(('Remove from Jet Guide Imported', 'remove_imported'))
                    options.append(('Stop YouTube Playlist', 'stop_youtube'))
                    options.append(('Set Reminder for Current Program', 'remind'))
                    options.append(('Show All Reminders', 'show_reminders'))
                    options.append(('Search Addons', 'search_addons'))
                    options.append(('Play Stream in mpv', 'mpv'))
                    
                    dialog = xbmcgui.Dialog()
                    choice = dialog.select('Channel Options', [option[0] for option in options])
                    if choice >= 0:
                        action = options[choice][1]
                        if action == 'play':
                            self.play_selected_channel()
                        elif action == 'add':
                            if favorites_manager.add_favorite(channel['tvg_id']):
                                xbmcgui.Dialog().notification('Favorites', f'Added {channel["name"]} to favorites', xbmcgui.NOTIFICATION_INFO, 2000)
                        elif action == 'remove':
                            favorites_manager.remove_favorite(channel['tvg_id'])
                            xbmcgui.Dialog().notification('Favorites', f'Removed {channel["name"]} from favorites', xbmcgui.NOTIFICATION_INFO, 2000)
                        elif action == 'stop_youtube':
                            try:
                                from youtube_guide import cancel_youtube_playback
                                cancel_youtube_playback()
                                xbmcgui.Dialog().notification('YouTube Playlist', 'Playlist stopped', xbmcgui.NOTIFICATION_INFO, 2000)
                            except Exception as e:
                                debug_log(f"DEBUG: Error stopping YouTube playlist: {str(e)}", xbmc.LOGERROR)
                                xbmcgui.Dialog().notification('Error', 'Failed to stop YouTube playlist', xbmcgui.NOTIFICATION_ERROR, 2000)
                        elif action == 'mpv':
                            self.onClick(199)
                        elif action == 'play_imported':
                            # import xbmcvfs, json
                            profile_path = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
                            save_path = profile_path + "jet_guide_imported.json"
                            if xbmcvfs.exists(save_path):
                                with xbmcvfs.File(save_path, 'r') as f:
                                    imported = json.loads(f.read())
                                if not imported:
                                    xbmcgui.Dialog().ok('Jet Guide', 'No imported channels saved.')
                                else:
                                    titles = [c.get('title', 'Unknown') for c in imported]
                                    idx = xbmcgui.Dialog().select('Play Imported Channel', titles)
                                    if idx >= 0:
                                        link = imported[idx].get('link')
                                        if isinstance(link, list):
                                            link = link[0]
                                        if isinstance(link, str) and (link.startswith("http") or link.endswith(".m3u8") or link.startswith("plugin://")):
                                            if link.startswith("plugin://"):
                                                xbmc.executebuiltin(f'PlayMedia("{link}")')
                                            else:
                                                # Cancel any running YouTube sequential playback before playing new content
                                                try:
                                                    from youtube_guide import cancel_youtube_playback
                                                    cancel_youtube_playback()
                                                except ImportError:
                                                    pass  # youtube_guide not available
                                                
                                                xbmc.Player().play(link)
                                        else:
                                            debug_log(f"JetGuide DEBUG: Not playable (EPGGrid). Link: {link}", xbmc.LOGERROR)
                                            xbmcgui.Dialog().ok("Error", f"This link is not a direct playable stream.\n\nLink: {link}")
                            else:
                                xbmcgui.Dialog().ok('Jet Guide', 'No imported channels saved.')
                        elif action == 'remind':
                            from reminders import add_reminder
                            channel_name = channel.get('name', 'Unknown') if isinstance(channel, dict) else str(channel)
                            self.update_selected_program_info()
                            program_title = self.getProperty('ProgramTitle')
                            slot_idx = self.time_scroll_pos
                            slot_start, slot_end = self.time_slots[slot_idx]
                            add_reminder(channel_name, program_title, int(slot_start.timestamp()))
                            xbmcgui.Dialog().notification('Reminder', f'Reminder set for {program_title}', xbmcgui.NOTIFICATION_INFO, 2000)
                        elif action == 'show_reminders':
                            from reminders import list_reminders
                            xbmcgui.Dialog().ok('Scheduled Reminders', list_reminders())
                        elif action == 'return_video':
                            self.return_to_video()
                        elif action == 'remove_imported':
                            # import xbmcvfs, json
                            profile_path = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
                            save_path = profile_path + "jet_guide_imported.json"
                            if xbmcvfs.exists(save_path):
                                with xbmcvfs.File(save_path, 'r') as f:
                                    imported = json.loads(f.read())
                                if not imported:
                                    xbmcgui.Dialog().ok('Jet Guide', 'No imported channels saved.')
                                else:
                                    titles = [c.get('title', 'Unknown') for c in imported]
                                    idx = xbmcgui.Dialog().select('Remove Imported Channel', titles)
                                    if idx >= 0:
                                        del imported[idx]
                                        with xbmcvfs.File(save_path, 'w') as f:
                                            f.write(json.dumps(imported, indent=2, ensure_ascii=False))
                                        xbmcgui.Dialog().notification('Jet Guide', 'Channel removed!', xbmcgui.NOTIFICATION_INFO, 2000)
                            else:
                                xbmcgui.Dialog().ok('Jet Guide', 'No imported channels saved.')

                        elif action == 'play_from_folder':
                            # import os
                            profile_path = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
                            folders_base = os.path.join(profile_path, "jet_guide_folders")
                            try:
                                folders = [f for f in os.listdir(folders_base) if os.path.isdir(os.path.join(folders_base, f))]
                            except Exception as e:
                                debug_log(f"DEBUG: os.listdir failed for {folders_base}: {e}", xbmc.LOGERROR)
                                folders = []
                            if not folders:
                                xbmcgui.Dialog().ok('Jet Guide', 'No folders found.')
                            else:
                                folder_idx = xbmcgui.Dialog().select('Select Folder', folders)
                                if folder_idx >= 0:
                                    folder_path = os.path.join(folders_base, folders[folder_idx])
                                    links_file = os.path.join(folder_path, "links.json")
                                    if os.path.exists(links_file):
                                        with open(links_file, "r", encoding="utf-8") as f:
                                            links = json.load(f)
                                        if not links:
                                            xbmcgui.Dialog().ok('Jet Guide', 'No links found in folder.')
                                        else:
                                            titles = [c.get('title', 'Unknown') for c in links]
                                            idx = xbmcgui.Dialog().select('Play Folder Link', titles)
                                            if idx >= 0:
                                                link = links[idx].get('link')
                                                if link:
                                                    # Cancel any running YouTube sequential playback before playing new content
                                                    try:
                                                        from youtube_guide import cancel_youtube_playback
                                                        cancel_youtube_playback()
                                                    except ImportError:
                                                        pass  # youtube_guide not available
                                                    
                                                    xbmc.Player().play(link)
                                    else:
                                        xbmcgui.Dialog().ok('Jet Guide', 'No links.json found in folder.')
                                        if isinstance(link, list):
                                            link = link[0]
                                        if isinstance(link, str) and (link.startswith("http") or link.endswith(".m3u8") or link.startswith("plugin://")):
                                            if link.startswith("plugin://"):
                                                xbmc.executebuiltin(f'PlayMedia("{link}")')
                                            else:
                                                # Cancel any running YouTube sequential playback before playing new content
                                                try:
                                                    from youtube_guide import cancel_youtube_playback
                                                    cancel_youtube_playback()
                                                except ImportError:
                                                    pass  # youtube_guide not available
                                                
                                                xbmc.Player().play(link)
                                        else:
                                            debug_log(f"JetGuide DEBUG: Not playable (EPGGrid). Link: {link}", xbmc.LOGERROR)
                                            xbmcgui.Dialog().ok("Error", f"This link is not a direct playable stream.\n\nLink: {link}")
                                else:
                                    xbmcgui.Dialog().ok('Jet Guide', 'No imported channels saved.')

                        elif action == 'search_addons':
                            from epggrid import browse_installed_video_addons
                            from epggrid import browse_addon_plugin_folders
                            selected_addon = browse_installed_video_addons()
                            if not selected_addon:
                                return
                            # Open custom dialog to browse folders and links
                            browse_addon_plugin_folders(selected_addon)
                            return
        except Exception as e:
            debug_log(f"DEBUG: onAction error: {str(e)}", xbmc.LOGERROR)

    def return_to_video(self):
        """Closes the guide and returns to video playback."""
        self.close()
        xbmc.executebuiltin('Action(FullScreen)')

    def onClick(self, control_id: int):
        """Handle click events."""
        try:
            debug_log(f"DEBUG: onClick received: control_id={control_id}", xbmc.LOGINFO)
            if control_id == 200:  # Category selection
                try:
                    category_list = self.getControl(200)
                    if not category_list:
                        return
                    selected_pos = category_list.getSelectedPosition()
                    selected_item = category_list.getListItem(selected_pos)
                    if not selected_item:
                        return
                    category = selected_item.getProperty("Category")
                    display_name = selected_item.getLabel()
                    debug_log(f"DEBUG: Category filter clicked, category={category}, display_name={display_name}", xbmc.LOGINFO)
                    xbmcgui.Dialog().notification("Category Filter", f"Showing {display_name}", xbmcgui.NOTIFICATION_INFO, 2000)
                    self.setProperty('CategoryFilter', category)
                    self.check_category_filter()
                except Exception as e:
                    debug_log(f"DEBUG: Category filter click error: {str(e)}", xbmc.LOGERROR)
            elif control_id == 110 and self.channel_panel:
                # Sync current_channel_idx with highlighted channel on click/touch
                row = self.channel_panel.getSelectedPosition()
                self.current_channel_idx = self.current_page * self.visible_rows + row
                debug_log(f"DEBUG: Channel panel clicked, updated current_channel_idx={self.current_channel_idx}", xbmc.LOGINFO)
                self.update_selected_program_info()
                self.play_selected_channel()
            elif control_id == 110:  # Grid click
                debug_log(f"DEBUG: Grid clicked, control_id=110, channel_idx={self.current_channel_idx}", xbmc.LOGINFO)
                self.play_selected_channel()
            elif control_id == 400:  # Left scroll button
                if self.time_scroll_pos > 0:
                    self.time_scroll_pos -= 1
                    debug_log(f"DEBUG: Left button clicked, time_scroll_pos={self.time_scroll_pos}", xbmc.LOGINFO)
                    self.create_grid()
                    self.channel_panel.selectItem(self.current_channel_idx % self.visible_rows)
                    self.update_selected_program_info()
                self.setFocusId(110)
            elif control_id == 401:  # Right scroll button
                if self.time_scroll_pos < len(self.time_slots) - 4:
                    self.time_scroll_pos += 1
                    debug_log(f"DEBUG: Right button clicked, time_scroll_pos={self.time_scroll_pos}", xbmc.LOGINFO)
                    self.create_grid()
                    self.channel_panel.selectItem(self.current_channel_idx % self.visible_rows)
                    self.update_selected_program_info()
                self.setFocusId(110)
        except Exception as e:
            debug_log(f"DEBUG: onClick error: {str(e)}", xbmc.LOGERROR)
        # --- Add mpv launch for context menu ---
        if control_id == 199:
            import threading
            def launch_mpv_from_context():
                try:
                    import time
                    time.sleep(0.2)  # Let context menu close
                    channel_idx = self.current_channel_idx
                    if channel_idx >= len(self.channels):
                        debug_log(f"DEBUG: Invalid channel_idx={channel_idx}, channels_len={len(self.channels)}", xbmc.LOGERROR)
                        xbmcgui.Dialog().notification('Error', 'Invalid channel selected', xbmcgui.NOTIFICATION_ERROR, 3000)
                        return
                    channel = self.channels[channel_idx]
                    stream_url = channel.get('url') or channel.get('stream_url')
                    if not stream_url:
                        xbmcgui.Dialog().notification('Error', 'No stream URL found for channel', xbmcgui.NOTIFICATION_ERROR, 3000)
                        return

                    # --- Robust URL resolution (proxy, plugin, headers) ---
                    import re
                    import xbmc
                    import urllib.parse
                    def get_resolved_url(url):
                        resolved_headers = {}
                        # Remove JetProxy/local proxy for mpv
                        proxy_match = re.match(r"http://127\.0\.0\.1:\d+\?url=(http.*)", url)
                        if proxy_match:
                            url = proxy_match.group(1)
                        # Resolve plugin:// URLs
                        if url.startswith("plugin://"):
                            try:
                                player = xbmc.Player()
                                player.play(url)
                                start_time = time.time()
                                while time.time() - start_time < 10 and not player.isPlaying():
                                    time.sleep(0.1)
                                if player.isPlaying():
                                    resolved = player.getPlayingFile()
                                    player.stop()
                                    url = resolved
                            except Exception as e:
                                debug_log(f"DEBUG: Failed to resolve plugin URL: {str(e)}", xbmc.LOGERROR)
                        # Extract headers if present
                        if url and "|" in url:
                            url_parts = url.split("|", 1)
                            url = url_parts[0]
                            try:
                                header_string = url_parts[1]
                                for header in header_string.split('&'):
                                    if '=' in header:
                                        key, value = header.split('=', 1)
                                        resolved_headers[key.lower()] = urllib.parse.unquote(value)
                            except Exception as e:
                                debug_log(f"DEBUG: Error parsing headers from URL: {str(e)}", xbmc.LOGWARNING)
                        return url, resolved_headers

                    resolved_url, resolved_headers = get_resolved_url(stream_url)
                    if not resolved_url.startswith("http"):
                        xbmcgui.Dialog().notification('Error', 'Could not resolve direct stream URL', xbmcgui.NOTIFICATION_ERROR, 3000)
                        return

                    import xbmcaddon
                    import subprocess
                    mpv_path = xbmcaddon.Addon().getSetting("mpv_path") or r"C:\Users\user\Desktop\mpv_player\mpv.exe"
                    mpv_command = [mpv_path]
                    if resolved_headers:
                        mpv_headers = ",".join([f"{k.title()}: {v}" for k, v in resolved_headers.items()])
                        mpv_command += [f'--http-header-fields={mpv_headers}']
                    mpv_command.append(resolved_url)
                    debug_log(f"DEBUG: Launching mpv with command: {mpv_command}", xbmc.LOGINFO)
                    CREATE_NEW_CONSOLE = 0x00000010
                    subprocess.Popen(mpv_command, creationflags=CREATE_NEW_CONSOLE)
                    xbmcgui.Dialog().notification("mpv", "Stream sent to mpv player", xbmcgui.NOTIFICATION_INFO, 2000)
                except Exception as e:
                    debug_log(f"DEBUG: Failed to launch mpv: {str(e)}", xbmc.LOGERROR)
                    xbmcgui.Dialog().ok("Error", f"Failed to launch mpv: {str(e)}")
            threading.Thread(target=launch_mpv_from_context, daemon=True).start()
            return

    def play_selected_channel(self):
        """Play the selected channel via addon.py's play_channel."""
        try:
            current_time = time.time()
            if current_time - self.last_play_time < 1.0:  # Debounce: ignore calls within 1 second
                debug_log(f"DEBUG: play_selected_channel ignored due to debounce, last_play_time={self.last_play_time}, current_time={current_time}", xbmc.LOGINFO)
                return
            self.last_play_time = current_time
            debug_log(f"DEBUG: play_selected_channel started, channel_idx={self.current_channel_idx}", xbmc.LOGINFO)
            
            channel_idx = self.current_channel_idx
            if channel_idx >= len(self.channels):
                debug_log(f"DEBUG: Invalid channel_idx={channel_idx}, channels_len={len(self.channels)}", xbmc.LOGERROR)
                xbmcgui.Dialog().notification('Error', 'Invalid channel selected', xbmcgui.NOTIFICATION_ERROR, 3000)
                return
            channel = self.channels[channel_idx]
            channel_id = channel.get('tvg_id', '')
            name = channel.get('name', 'Unknown')
            debug_log(f"DEBUG: Attempting to play channel: {name} (tvg_id={channel_id})", xbmc.LOGINFO)
            
            # Close all dialogs to prevent concurrent dialog crash
            debug_log(f"DEBUG: Closing all open dialogs before playback", xbmc.LOGINFO)
            xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
            xbmc.executebuiltin('Dialog.Close(busydialog)')
            xbmc.executebuiltin('Dialog.Close(all,true)')  # Close all dialog types
            xbmc.sleep(250)  # Increased delay to ensure dialogs are closed
            
            if not channel_id:
                debug_log(f"DEBUG: Channel ID missing for {name}", xbmc.LOGERROR)
                xbmcgui.Dialog().notification('Error', 'Channel ID missing', xbmcgui.NOTIFICATION_ERROR, 3000)
                return
            
            if self.is_sports_view and 'all_links' in channel and channel['all_links']:
                debug_log(f"DEBUG: Sports view active, showing stream selection for {name}", xbmc.LOGINFO)
                stream_names = channel.get('stream_names', [])
                dialog = xbmcgui.Dialog()
                choice = dialog.select('Choose Stream', stream_names)
                if choice >= 0:
                    url = channel['all_links'][choice]
                    debug_log(f"DEBUG: Selected stream URL: {url}", xbmc.LOGINFO)
                    if '(' in url:
                        url = url[:url.rindex('(')].strip()
                    list_item = xbmcgui.ListItem(name)
                    list_item.setPath(url)
                    debug_log(f"DEBUG: Playing stream directly: {url}", xbmc.LOGINFO)
                    xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
                    xbmc.executebuiltin('Dialog.Close(busydialog)')
                    xbmc.executebuiltin('Dialog.Close(all,true)')
                    xbmc.sleep(250)  # Increased delay for direct playback
                    # Unified play logic for favourites and direct links
                    if isinstance(url, str) and (url.startswith("http") or url.endswith(".m3u8") or url.startswith("plugin://")):
                        if url.startswith("plugin://"):
                            xbmc.executebuiltin(f'PlayMedia("{url}")')
                        else:
                            # Cancel any running YouTube sequential playback before playing new content
                            try:
                                from youtube_guide import cancel_youtube_playback
                                cancel_youtube_playback()
                            except ImportError:
                                pass  # youtube_guide not available
                            
                            xbmc.Player().play(url, list_item)
                        debug_log(f"DEBUG: Playback initiated for direct stream", xbmc.LOGINFO)
                    else:
                        debug_log(f"JetGuide DEBUG: Not playable (EPGGrid). Link: {url}", xbmc.LOGERROR)
                        xbmcgui.Dialog().ok("Error", f"This link is not a direct playable stream.\n\nLink: {url}")
                else:
                    debug_log(f"DEBUG: Stream selection cancelled for {name}", xbmc.LOGINFO)
                return
            
            from urllib.parse import quote
            play_url = f"plugin://{addon.getAddonInfo('id')}/?action=play_channel&id={quote(channel_id)}"
            debug_log(f"DEBUG: Executing RunPlugin: {play_url}", xbmc.LOGINFO)
            xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
            xbmc.executebuiltin('Dialog.Close(busydialog)')
            xbmc.executebuiltin('Dialog.Close(all,true)')
            xbmc.sleep(250)  # Increased delay before RunPlugin
            xbmc.executebuiltin(f'RunPlugin({play_url})')
            debug_log(f"DEBUG: RunPlugin executed for {name}", xbmc.LOGINFO)
            
        except Exception as e:
            debug_log(f"DEBUG: play_selected_channel error: {str(e)}", xbmc.LOGERROR)
            xbmcgui.Dialog().notification('Error', f'Failed to play channel: {str(e)}', xbmcgui.NOTIFICATION_ERROR, 5000)
            
    def close(self):
        """Clean up resources and close the window."""
        debug_log(f"DEBUG: EPGGrid closing, cleaning up resources", xbmc.LOGINFO)
        try:
            self.is_closing = True
            if hasattr(self, 'program_cache'):
                self.program_cache.clear()
                debug_log(f"DEBUG: Cleared program_cache", xbmc.LOGINFO)
            if hasattr(self, 'channels'):
                self.channels.clear()
                debug_log(f"DEBUG: Cleared channels", xbmc.LOGINFO)
            if hasattr(self, 'all_channels'):
                self.all_channels.clear()
                debug_log(f"DEBUG: Cleared all_channels", xbmc.LOGINFO)
            if hasattr(self, 'time_slots'):
                self.time_slots.clear()
                debug_log(f"DEBUG: Cleared time_slots", xbmc.LOGINFO)
            if hasattr(self, 'channel_panel') and self.channel_panel:
                self.channel_panel.reset()
                debug_log(f"DEBUG: Reset channel_panel", xbmc.LOGINFO)
            super().close()
            debug_log(f"DEBUG: EPGGrid closed", xbmc.LOGINFO)
        except Exception as e:
            debug_log(f"DEBUG: close error: {str(e)}", xbmc.LOGERROR)
def browse_installed_video_addons():
    # import xbmcaddon, xbmcgui
    # import os

    # Get all installed addons
    addons_dir = xbmcvfs.translatePath('special://home/addons')
    addon_ids = []
    addon_names = []
    for addon_id in os.listdir(addons_dir):
        addon_xml = os.path.join(addons_dir, addon_id, 'addon.xml')
        if os.path.isfile(addon_xml):
            try:
                with open(addon_xml, encoding='utf-8') as f:
                    xml = f.read()
                if 'extension point="xbmc.python.pluginsource"' in xml and '<provides>video</provides>' in xml:
                    addon_ids.append(addon_id)
                    # Extract name
                    import re
                    m = re.search(r'name="([^"]+)"', xml)
                    addon_names.append(m.group(1) if m else addon_id)
            except Exception:
                continue
    if not addon_ids:
        xbmcgui.Dialog().ok('Kodi Addons', 'No video addons found.')
        return None
    choice = xbmcgui.Dialog().select('Select Kodi Addon', addon_names)
    if choice < 0:
        return None
    return addon_ids[choice]

def browse_addon_plugin_folders(addon_id, start_path=None):
    # Start at root if not specified
    if not start_path:
        plugin_url = f"plugin://{addon_id}/"
    else:
        plugin_url = start_path


    # Use Kodi JSON-RPC to get directory listing
    params = {
        "jsonrpc": "2.0",
        "method": "Files.GetDirectory",
        "id": 1,
        "params": {
            "directory": plugin_url,
            "media": "files"
        }
    }
    response = xbmc.executeJSONRPC(json.dumps(params))
    data = json.loads(response)
    items = data.get("result", {}).get("files", [])

    if not items:
        xbmcgui.Dialog().ok("Browse Addon", "No items found in this folder.")
        return None

    display_names = []
    item_urls = []
    is_folder = []
    for item in items:
        display_names.append(item.get("label", item.get("file", "")))
        item_urls.append(item.get("file", ""))
        is_folder.append(item.get("filetype", "") == "directory")

    while True:
        choice = xbmcgui.Dialog().select("Browse Addon", display_names + ["[Save this link]", "[Go Back]"])
        if choice < 0 or choice == len(display_names) + 1:
            return None
        if choice == len(display_names):
            # Save current link
            # Ask for a title and save current folder link as an object
            title = xbmcgui.Dialog().input("Enter a name for this folder/link", defaultt=plugin_url)
            if title:
                save_link_to_jet_guide({"title": title, "link": plugin_url})
                xbmcgui.Dialog().ok("Saved", f"Link saved:\n{title}")
            continue
        if is_folder[choice]:
            browse_addon_plugin_folders(addon_id, item_urls[choice])
            return
        else:
            # Save/playable link
            # Ask for a title and save playable link as an object
            title = xbmcgui.Dialog().input("Enter a name for this link", defaultt=display_names[choice])
            if title:
                save_link_to_jet_guide({"title": title, "link": item_urls[choice]})
                xbmcgui.Dialog().ok("Saved", f"Link saved:\n{title}")
            continue
            # for root, dirs, files in os.walk(addon_path):
            #     for file in files:
            #         if file.endswith(".json"):
            #             json_files.append(os.path.join(root, file))
            # if not json_files:
            #     xbmcgui.Dialog().ok("Browse Addon", "No JSON files found in addon.")
            #     return None
            # choice = xbmcgui.Dialog().select("Select JSON file", [os.path.basename(f) for f in json_files])
            # if choice < 0:
            #     return None
            # selected_file = json_files[choice]
            # with open(selected_file, encoding="utf-8") as f:
            #     data = json.load(f)
            
            # if isinstance(data, list):
            #     channels = data
            # elif isinstance(data, dict):
            
            #     for key in ["channels", "channel_list", "streams"]:
            #         if key in data and isinstance(data[key], list):
            #             channels = data[key]
            #             break
            #     else:
            #         xbmcgui.Dialog().ok("Browse Addon", "No channel list found in JSON file.")
            #         return None
            # else:
            #     xbmcgui.Dialog().ok("Browse Addon", "Unrecognized JSON format.")
            #     return None
            
            # return channels

def save_link_to_jet_guide(link_obj):
    import base64
    import re

    # Load existing links
    try:
        if xbmcvfs.exists(JET_GUIDE_IMPORTED_PATH):
            with xbmcvfs.File(JET_GUIDE_IMPORTED_PATH, "r") as f:
                links = json.loads(f.read())
        else:
            links = []
    except Exception:
        links = []
    
    links = [l for l in links if isinstance(l, dict) and "title" in l and "link" in l]

    if isinstance(link_obj, dict) and not any(l.get("link") == link_obj["link"] for l in links):
        links.append(link_obj)
        with xbmcvfs.File(JET_GUIDE_IMPORTED_PATH, "w") as f:
            f.write(json.dumps(links, indent=2))
ACTIVE_WINDOW = None

ADDON = xbmcaddon.Addon()
addon__id = ADDON.getAddonInfo('id')
def get_youtube_sleep_time():
    """Get the sleep time setting from addon settings"""
    try:
        sleep_time = int(ADDON.getSetting('youtube_sleep_time'))
        return sleep_time
    except:
        return 5  # Default fallback

def youtube_json_to_epggrid(json_path):
    import json
    from datetime import datetime, timedelta

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    channel_name = "Alternative Metal"
    tvg_id = "altmetal"
    logo = data['items'][0].get('thumbnail', '')
    channel = {
        'name': channel_name,
        'tvg_id': tvg_id,
        'logo': logo,
        'group': 'YouTube'
    }

    programs = []
    start_time = datetime.now()
    # Get user-configurable sleep time
    sleep_time = get_youtube_sleep_time()
    
    for item in data['items']:
        duration_parts = item['duration'].split(':')
        duration_seconds = int(duration_parts[0]) * 60 + int(duration_parts[1])
        end_time = start_time + timedelta(seconds=duration_seconds)
        programs.append({
            'title': item['title'],
            'channel': tvg_id,
            'desc': item['summary'],
            'start': start_time,
            'end': end_time,
            'link': item['link'],
            'logo': item.get('thumbnail', ''),
        })
        # Add configurable delay between programs
        start_time = end_time + timedelta(seconds=sleep_time)
    return [channel], programs