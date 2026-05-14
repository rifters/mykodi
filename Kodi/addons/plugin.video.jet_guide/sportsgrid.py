import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs
import os
import re
from datetime import datetime, timedelta, timezone
# from epggrid import EPGGrid
import requests
from bs4 import BeautifulSoup
from tools import show_tools, debug_log

ADDON = xbmcaddon.Addon()
TEMP_PATH = xbmcvfs.translatePath('special://temp')

class TimeListControl(xbmcgui.ControlList):
    def __init__(self, *args, **kwargs):
        self.grid = kwargs.pop('grid', None)
        super().__init__(*args, **kwargs)
        TimeoutError
    def onAction(self, action):
        if action.getId() == 7:  # ACTION_SELECT_ITEM
            if self.grid:
                self.grid.handleGameSelection()
        super().onAction(action)

class SportsGrid(xbmcgui.WindowXML):
    # Sport-specific team name mappings
    TEAM_MAPPINGS = {
        'mlb': {
            'chi': 'chicago',
            'la': 'los angeles',
            'ny': 'new york',
            'chi cubs': 'chicago cubs',
            'chi white sox': 'chicago white sox',
            'la angels': 'los angeles angels',
            'la dodgers': 'los angeles dodgers',
            'ny yankees': 'new york yankees',
            'ny mets': 'new york mets',
            'athletics': 'oakland athletics',
            'a\'s': 'oakland athletics',
            'jays': 'toronto blue jays',
            'rays': 'tampa bay rays',
            'nats': 'washington nationals',
            'detroit': 'detroit tigers',
            'cincinnati': 'cincinnati reds',
            'toronto': 'toronto blue jays',
            'philadelphia': 'philadelphia phillies',
            'miami': 'miami marlins',
            'washington': 'washington nationals',
            'colorado': 'colorado rockies',
            'atlanta': 'atlanta braves',
            'boston': 'boston red sox',
            'baltimore': 'baltimore orioles',
            'tampa bay': 'tampa bay rays',
            'minnesota': 'minnesota twins',
            'houston': 'houston astros',
            'st. louis': 'st. louis cardinals',
            'milwaukee': 'milwaukee brewers',
            'kansas city': 'kansas city royals',
            'pittsburgh': 'pittsburgh pirates',
            'texas': 'texas rangers',
            'san diego': 'san diego padres',
            'arizona': 'arizona diamondbacks',
            'cleveland': 'cleveland guardians',
            'seattle': 'seattle mariners',
            'san francisco': 'san francisco giants'
        },
        'nba': {
            'cleveland': 'cleveland cavaliers',
            'boston': 'boston celtics',
            'new york': 'new york knicks',
            'indiana': 'indiana pacers',
            'milwaukee': 'milwaukee bucks',
            'detroit': 'detroit pistons',
            'orlando': 'orlando magic',
            'atlanta': 'atlanta hawks',
            'chicago': 'chicago bulls',
            'miami': 'miami heat',
            'toronto': 'toronto raptors',
            'brooklyn': 'brooklyn nets',
            'philadelphia': 'philadelphia 76ers',
            'charlotte': 'charlotte hornets',
            'washington': 'washington wizards',
            'oklahoma city': 'oklahoma city thunder',
            'houston': 'houston rockets',
            'la lakers': 'los angeles lakers',
            'la clippers': 'los angeles clippers',
            'denver': 'denver nuggets',
            'minnesota': 'minnesota timberwolves',
            'golden state': 'golden state warriors',
            'memphis': 'memphis grizzlies',
            'sacramento': 'sacramento kings',
            'dallas': 'dallas mavericks',
            'phoenix': 'phoenix suns',
            'portland': 'portland trail blazers',
            'san antonio': 'san antonio spurs',
            'new orleans': 'new orleans pelicans',
            'utah': 'utah jazz'
        },
        'wnba': {
            'atlanta': 'atlanta dream',
            'chicago': 'chicago sky',
            'connecticut': 'connecticut sun',
            'dallas': 'dallas wings',
            'indiana': 'indiana fever',
            'las vegas': 'las vegas aces',
            'minnesota': 'minnesota lynx',
            'new york': 'new york liberty',
            'phoenix': 'phoenix mercury',
            'seattle': 'seattle storm',
            'washington': 'washington mystics',
            'fever': 'indiana fever',
            'sky': 'chicago sky',
            'sun': 'connecticut sun',
            'wings': 'dallas wings',
            'aces': 'las vegas aces',
            'lynx': 'minnesota lynx',
            'liberty': 'new york liberty',
            'mercury': 'phoenix mercury',
            'storm': 'seattle storm',
            'mystics': 'washington mystics',
            'dream': 'atlanta dream'
        },
        'nhl': {
            'boston': 'boston bruins',
            'buffalo': 'buffalo sabres',
            'detroit': 'detroit red wings',
            'florida': 'florida panthers',
            'montreal': 'montreal canadiens',
            'ottawa': 'ottawa senators',
            'tampa bay': 'tampa bay lightning',
            'toronto': 'toronto maple leafs',
            'carolina': 'carolina hurricanes',
            'columbus': 'columbus blue jackets',
            'new jersey': 'new jersey devils',
            'ny islanders': 'new york islanders',
            'ny rangers': 'new york rangers',
            'philadelphia': 'philadelphia flyers',
            'pittsburgh': 'pittsburgh penguins',
            'washington': 'washington capitals',
            'arizona': 'arizona coyotes',
            'chicago': 'chicago blackhawks',
            'colorado': 'colorado avalanche',
            'dallas': 'dallas stars',
            'minnesota': 'minnesota wild',
            'nashville': 'nashville predators',
            'st. louis': 'st. louis blues',
            'winnipeg': 'winnipeg jets',
            'anaheim': 'anaheim ducks',
            'calgary': 'calgary flames',
            'edmonton': 'edmonton oilers',
            'los angeles': 'los angeles kings',
            'san jose': 'san jose sharks',
            'seattle': 'seattle kraken',
            'vancouver': 'vancouver canucks',
            'vegas': 'vegas golden knights'
        },
        'nfl': {
            'buffalo': 'buffalo bills',
            'miami': 'miami dolphins',
            'new england': 'new england patriots',
            'ny jets': 'new york jets',
            'baltimore': 'baltimore ravens',
            'cincinnati': 'cincinnati bengals',
            'cleveland': 'cleveland browns',
            'pittsburgh': 'pittsburgh steelers',
            'houston': 'houston texans',
            'indianapolis': 'indianapolis colts',
            'jacksonville': 'jacksonville jaguars',
            'tennessee': 'tennessee titans',
            'denver': 'denver broncos',
            'kansas city': 'kansas city chiefs',
            'la chargers': 'los angeles chargers',
            'las vegas': 'las vegas raiders',
            'dallas': 'dallas cowboys',
            'ny giants': 'new york giants',
            'philadelphia': 'philadelphia eagles',
            'washington': 'washington commanders',
            'chicago': 'chicago bears',
            'detroit': 'detroit lions',
            'green bay': 'green bay packers',
            'minnesota': 'minnesota vikings',
            'atlanta': 'atlanta falcons',
            'carolina': 'carolina panthers',
            'new orleans': 'new orleans saints',
            'tampa bay': 'tampa bay buccaneers',
            'arizona': 'arizona cardinals',
            'la rams': 'los angeles rams',
            'san francisco': 'san francisco 49ers',
            'seattle': 'seattle seahawks'
        }
    }

    @classmethod
    def normalize_team_name(cls, name, sport):
        """Normalize team name for comparison"""
        if not name:
            return ''
        # Clean up the input name
        name = name.lower().strip()
        original = name
        # Remove playoff seeds and qualifiers (e.g., "(4)", "-z", "-y", "-x")
        name = re.sub(r'\(\d+\)|-[xyz]', '', name).strip()
        # Special case for MLB A's/Athletics
        if sport == 'mlb' and name in ['a\'s', 'athletics', 'oakland a\'s', 'oakland athletics']:
            return 'oakland athletics'
        # Remove division prefix
        if name.startswith(('e-', 'c-', 'w-')):
            name = name[2:].strip()
        # Try direct mapping first
        sport_mappings = cls.TEAM_MAPPINGS.get(sport, {})
        mapped = sport_mappings.get(name)
        if mapped:
            return mapped
        # Split into parts and handle duplicates
        parts = name.split()
        if len(parts) >= 2:
            # Try city mapping
            city = ' '.join(parts[:-1])  # Everything except last word
            nickname = parts[-1]
            # Check if nickname repeats city
            if nickname in city:
                name = city  # Use city as base if nickname is redundant
            else:
                name = ' '.join(parts)
            # Check city mapping again
            mapped_city = sport_mappings.get(city)
            if mapped_city:
                result = mapped_city
                return result
            # Try full team name
            mapped = sport_mappings.get(name)
            if mapped:
                return mapped
        return name

    def __init__(self, xml_file: str, addon_path: str, sport: str):
        # Call parent constructor first to ensure window is properly initialized
        super().__init__(xml_file, addon_path)
        # Initialize controls
        self.time_panel = None
        self.channel_panel = None
        self.sport = sport.lower()
        self.local_tz = datetime.now().astimezone().tzinfo
        # Initialize basic attributes needed by EPGGrid
        self.all_channels = []
        self.channels = []
        self.programs = []
        self.is_sports_view = True
        self.program_cache = {}
        self.visible_rows = 13
        self.current_page = 0
        self.time_scroll_pos = 0
        self.time_slots = []
        self.selected_program = None
        # Set up initial time slots
        self.set_time_slots()
        # Get sports data
        
        try:
            # Load data
            scores = self.get_scores()
            # debug_log(f"SportsGrid: Found {len(scores)} games for {self.sport}", xbmc.LOGINFO)
            standings_data = self.get_standings()
            # debug_log(f"SportsGrid: Found {len(standings_data)} standings entries for {self.sport}", xbmc.LOGINFO)
            # Format data
            self.all_channels = self.format_channels(standings_data)
            # debug_log(f"SportsGrid: Created {len(self.all_channels)} channels", xbmc.LOGINFO)
            self.channels = self.all_channels[:]
            self.programs = self.format_programs(scores)
            # debug_log(f"SportsGrid: Created {len(self.programs)} programs", xbmc.LOGINFO)
            
        except Exception as e:
            xbmcgui.Dialog().ok("Error", "Failed to load sports data. Please try again.")
            self.channels = []
            self.programs = []
            self.close()
            return
            
        if not self.channels or not self.programs:
            xbmcgui.Dialog().ok("Error", "No sports data available. Please try again.")
            self.close()
            return

    def onInit(self):
        """Override onInit to handle sports-specific initialization"""
        try:
            # Initialize panels before parent onInit
            self.channel_panel = None
            self.time_panel = None
            # Call parent onInit
            super().onInit()
            # Set window title
            self.setProperty('SportTitle', self.sport.upper())
            # Verify we have data to display
            if not self.channels or not self.programs:
                xbmcgui.Dialog().ok("Error", "No sports data available. Please try again.")
                self.close()
                return
            # Initialize and populate panels
            self.channel_panel = self.getControl(100)
            self.time_panel = self.getControl(101)
            # Configure panels
            self.channel_panel.setEnabled(True)
            self.time_panel.setEnabled(True)
            # Populate data
            self.populate_channel_panel()
            self.populate_time_panel()
            # Initial focus and selection - start with teams panel
            if self.channel_panel.size() > 0:
                self.channel_panel.selectItem(0)
                self.setFocusId(100)
            # Make sure both panels are visible and enabled
            self.channel_panel.setVisible(True)
            self.time_panel.setVisible(True)
            
            # Update initial info display
            self.update_selected_info()
            
            # Hide loading overlay
            self.hide_loading()
                
        except Exception as e:
            xbmcgui.Dialog().ok("Error", "Failed to initialize display. Please try again.")
            self.close()
            return
        
    def onControl(self, control):
        """Handle control events"""
        control_id = control.getId()
        if control_id == 950:
            from reminders import RemindersManager
            manager = RemindersManager()
            manager.clear_reminders()
            xbmcgui.Dialog().ok("Reminders", "All reminders have been cleared.")
        else:
            # Let onAction handle all other input
            pass
            
    # def onInit(self):
    #     """Override onInit to handle sports-specific initialization"""
    #     try:
    #         # Initialize panels before parent onInit
    #         self.channel_panel = None
    #         self.time_panel = None
    #         # Call parent onInit
    #         super().onInit()
    #         # Set window title
    #         self.setProperty('SportTitle', self.sport.upper())
    #         # Verify we have data to display
    #         if not self.channels or not self.programs:
    #             xbmcgui.Dialog().ok("Error", "No sports data available. Please try again.")
    #             self.close()
    #             return
    #         # Initialize and populate panels
    #         self.channel_panel = self.getControl(100)
    #         self.time_panel = self.getControl(101)
    #         # Configure panels
    #         self.channel_panel.setEnabled(True)
    #         self.time_panel.setEnabled(True)
    #         # Populate data
    #         self.populate_channel_panel()
    #         self.populate_time_panel()
    #         # Initial focus and selection - start with teams panel
    #         if self.channel_panel.size() > 0:
    #             self.channel_panel.selectItem(0)
    #             self.setFocusId(100)
    #         # Make sure both panels are visible and enabled
    #         self.channel_panel.setVisible(True)
    #         self.time_panel.setVisible(True)
            
    #         # Update initial info display
    #         self.update_selected_info()
            
    #         # Hide loading overlay
    #         self.hide_loading()
                
    #     except Exception as e:
    #         xbmcgui.Dialog().ok("Error", "Failed to initialize display. Please try again.")
    #         self.close()
    #         return
        
    def populate_channel_panel(self):
        """Populate or repopulate the channel panel"""
        debug_log("SportsGrid DEBUG: Entered populate_channel_panel", xbmc.LOGINFO)
        self.channel_panel.reset()
        for idx, channel in enumerate(self.channels):
            team_name = channel.get('name', '')
            record = channel.get('record', '')
            item = xbmcgui.ListItem(label=team_name.upper())
            item.setProperty('record', record)
            logo_url = channel.get('logo', '')
            if logo_url:
                # debug_log(f"SportsGrid DEBUG: Setting logo for {team_name}: {logo_url}", xbmc.LOGINFO)
                item.setArt({'thumb': logo_url, 'icon': logo_url})
                item.setProperty('logo', logo_url)
            else:
                debug_log(f"SportsGrid DEBUG: No logo for {team_name}", xbmc.LOGINFO)
            
            # Store additional team statistics if available
            for stat in ['wins', 'losses', 'pct', 'gb', 'home', 'away', 'l10', 'strk']:
                value = channel.get(stat, '')
                if value:
                    item.setProperty(stat, str(value))
            
            self.channel_panel.addItem(item)
            
    def populate_time_panel(self):
        """Populate or repopulate the time panel"""
        self.time_panel.reset()
        # Sort games by time and status
        sorted_programs = sorted(
            self.programs,
            key=lambda x: (
                x.get('time', datetime.max) if isinstance(x.get('time'), datetime) else datetime.max,
                'A' if 'final' in str(x.get('status', '')).lower() else
                'B' if any(hint in str(x.get('status', '')).lower() for hint in ['live', 'quarter', 'period', 'inning']) else 'C'
            )
        )
        # Add each game
        for idx, program in enumerate(sorted_programs, 1):
            title = program.get('title', '')
            desc = program.get('desc', '')
            status = program.get('status', '')
            # Get time string
            if isinstance(program.get('time'), datetime):
                time_str = program['time'].strftime('%I:%M %p').lstrip('0')
            else:
                time_str = 'TBD'
            # Create display item
            item = xbmcgui.ListItem(label=title.upper())
            item.setProperty('time', time_str)
            item.setProperty('game', title)
            item.setProperty('status', status)
            item.setProperty('description', desc)
            self.time_panel.addItem(item)
            
    def handleGameSelection(self):
        """Handle game selection and stream dialog"""
        try:
            item = self.time_panel.getSelectedItem()
            if not item:
                return

            game_title = item.getProperty('game')
            if not game_title:
                return
            # Split title into parts
            parts = game_title.split('|')
            if len(parts) < 2:
                return
            # Extract team names from main part
            teams_part = parts[1].strip()
            teams = teams_part.split('vs')
            if len(teams) != 2:
                return

            team1_full = teams[0].strip()
            team2_full = teams[1].strip()
            team1_name = team1_full.split()[-1].lower()
            team2_name = team2_full.split()[-1].lower()
            # Show progress dialog
            progress = xbmcgui.DialogProgress()
            progress.create('Searching', f'Searching for {team1_name} vs {team2_name}...\n{game_title}')
            # Load games from JSON
            if "wnba" in self.sport:
                url = f'https://magnetic.website/MAD_TITAN_SPORTS/SPORTS/LEAGUE/titansports_nba.json'
            else:
                url = f'https://magnetic.website/MAD_TITAN_SPORTS/SPORTS/LEAGUE/titansports_{self.sport}.json'
            try:
                response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                progress.close()
                xbmcgui.Dialog().ok("Error", f"Failed to load game data: {str(e)}")
                return
            progress.update(25, 'Loading game data...')
            # Find matching game and collect stream links
            stream_links = []
            stream_names = []
            total_items = len(data.get('items', []))
            if total_items == 0:
                progress.close()
                xbmcgui.Dialog().ok("Error", "No games found in data source")
                return
            for idx, game in enumerate(data['items']):
                if progress.iscanceled():
                    progress.close()
                    return
                progress.update(50 + int((idx / total_items) * 50), f'Checking game {idx + 1} of {total_items}...')
                if (game.get('type') == 'item' and
                    game.get('title') and
                    (team1_name in game['title'].lower() or
                    team2_name in game['title'].lower())):
                    
                    if 'link' in game:
                        links = game.get('link', [])
                        for i, link in enumerate(links):
                            # Clean URL and extract stream name
                            clean_url = link
                            stream_name = f"Stream {i + 1}"
                            if '(' in link and ')' in link:
                                stream_name = link[link.rindex('(')+1:link.rindex(')')].strip()
                                clean_url = link[:link.rindex('(')].strip()
                            elif '[COLOR' in link and '[/COLOR]' in link:
                                # Remove [COLOR] tags if present
                                clean_url = re.sub(r'\[COLOR.*?\](.*?)\[/COLOR\]', r'\1', link).strip()
                                if '(' in clean_url and ')' in clean_url:
                                    stream_name = clean_url[clean_url.rindex('(')+1:clean_url.rindex(')')].strip()
                                    clean_url = clean_url[:clean_url.rindex('(')].strip()

                            stream_links.append(clean_url)
                            stream_names.append(stream_name)
            progress.close()
            if not stream_links:
                return
            # Show stream selection dialog
            dialog = xbmcgui.Dialog()
            choice = dialog.select('Choose Stream', stream_names)
        
            if choice >= 0:
                selected_url = stream_links[choice]
                list_item = xbmcgui.ListItem(game_title)
                list_item.setInfo('video', {'Title': game_title})
                list_item.setProperty('IsPlayable', 'true')
                
                # Cancel any running YouTube sequential playback before playing new content
                try:
                    from youtube_guide import cancel_youtube_playback
                    cancel_youtube_playback()
                except ImportError:
                    pass  # youtube_guide not available
                
                xbmc.Player().play(selected_url, list_item)
            else:
                pass

        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Failed to play stream: {str(e)}")
        finally:
            if 'progress' in locals() and progress:
                progress.close()
            
    def onClick(self, control_id):
        """Handle click events - let onAction handle selection"""
        pass

    def onAction(self, action):
        """Handle navigation and selection actions"""
        try:
            action_id = action.getId()
            focused_id = self.getFocusId()
            
            # Handle Enter/Click actions
            if action_id in [7, 100]:  # Enter or Click
                if focused_id == 101 and self.time_panel:  # Time panel
                    self.handleGameSelection()
                    return
                elif focused_id == 100 and self.channel_panel:  # Channel panel
                    # Just highlight, don't do anything else
                    return
                    
            # Handle Left/Right navigation between panels
            elif action_id == 1 and focused_id == 101:  # Left from time panel
                if self.channel_panel and self.channel_panel.size() > 0:
                    self.setFocusId(100)
                    self.channel_panel.selectItem(0)
                    self.update_selected_info()
                return
                
            elif action_id == 2 and focused_id == 100:  # Right from channel panel
                if self.time_panel and self.time_panel.size() > 0:
                    self.setFocusId(101)
                    self.time_panel.selectItem(0)
                    self.update_selected_info()
                return
            
            # Handle Up/Down navigation within panels
            elif action_id in [3, 4]:  # Up/Down
                if focused_id in [100, 101]:
                    # Let the current panel handle up/down navigation and update info
                    if focused_id == 100 and self.channel_panel:
                        # Don't call parent - handle locally or let control handle it
                        self.update_selected_info()
                        pass
                    elif focused_id == 101 and self.time_panel:
                        # Don't call parent - handle locally or let control handle it
                        self.update_selected_info()
                        pass
                    return
            
            # Handle Mouse Wheel and Touch Scroll navigation with seamless scrolling
            elif action_id in [104, 105, 106, 107]:  # Mouse wheel + touch gestures (WHEEL_UP, WHEEL_DOWN, GESTURE_SWIPE_UP, GESTURE_SWIPE_DOWN)
                focused_id = self.getFocusId()
                if focused_id == 100 and self.channel_panel:  # Channel/Team panel
                    current_pos = self.channel_panel.getSelectedPosition()
                    total_items = self.channel_panel.size()
                    
                    if action_id in [104, 107]:  # Wheel up or swipe down
                        if current_pos == 0:
                            # At top, wrap to bottom
                            new_pos = total_items - 1
                        else:
                            new_pos = current_pos - 1
                    elif action_id in [105, 106]:  # Wheel down or swipe up
                        if current_pos >= total_items - 1:
                            # At bottom, wrap to top
                            new_pos = 0
                        else:
                            new_pos = current_pos + 1
                    
                    self.channel_panel.selectItem(new_pos)
                    self.update_selected_info()
                    return
                    
                elif focused_id == 101 and self.time_panel:  # Games panel
                    current_pos = self.time_panel.getSelectedPosition()
                    total_items = self.time_panel.size()
                    
                    if action_id in [104, 107]:  # Wheel up or swipe down
                        if current_pos == 0:
                            # At top, wrap to bottom
                            new_pos = total_items - 1
                        else:
                            new_pos = current_pos - 1
                    elif action_id in [105, 106]:  # Wheel down or swipe up
                        if current_pos >= total_items - 1:
                            # At bottom, wrap to top
                            new_pos = 0
                        else:
                            new_pos = current_pos + 1
                    
                    self.time_panel.selectItem(new_pos)
                    self.update_selected_info()
                    return
                
            elif action_id in [9, 10, 92]:  # Back/Exit actions
                self.close()
                return
            
            # For sports grid, don't call parent for most actions to prevent EPG interference
            # Only call parent for very specific cases
            
        except Exception as e:
            xbmcgui.Dialog().ok("Error", str(e))
        
    def connect_category_filter(self):
        """Override to disable category functionality"""
        pass

    def create_category_buttons(self):
        """Override to disable category functionality"""
        pass

    def check_category_filter(self):
        """Override to disable category functionality"""
        pass
        
    def create_grid(self):
        """Override to prevent clearing our manually populated lists"""
        pass
    
    def update_grid(self):
        """Override to prevent parent EPG updates"""
        pass
    
    def populate_grid(self):
        """Override to prevent parent EPG population"""
        pass
    
    def update_time_labels(self):
        """Override to prevent time label updates that show time slots"""
        pass

    def get_game_status(self, gamecard):
        try:
            team_keywords = [
                'twins', 'cardinals', 'rays', 'reds', 'angels', 'guardians', 'orioles',
                'astros', 'giants', 'royals', 'white sox', 'yankees', 'dodgers', 'cubs',
                'mets', 'phillies', 'braves', 'marlins', 'nationals', 'pirates',
                'brewers', 'tigers', 'rangers', 'athletics', 'mariners', 'padres',
                'diamondbacks', 'rockies', 'blue jays', 'red sox', 'indians', 'a\'s',
                'fever', 'sky', 'sun', 'wings', 'aces', 'lynx', 'liberty', 'mercury',
                'storm', 'mystics', 'dream'
            ]
            status_div = gamecard.find("div", class_="status")
            if status_div:
                status_text = status_div.get_text(separator=" ", strip=True)
                if status_text and status_text.lower() not in team_keywords:
                    return status_text
            for span in gamecard.find_all("span"):
                text = span.get_text(strip=True)
                if text and any(keyword in text for keyword in ["Final", "inning", "Inning", "Top", "Bot", "Quarter", "Period", "Half", "OT", "Live", "Ppd"]):
                    if text.lower() not in team_keywords:
                        return text
            all_text = gamecard.get_text(separator=" ", strip=True)
            if re.search(r'(Top|Bot)\s+\d+', all_text, re.IGNORECASE):
                match = re.search(r'(Top|Bot)\s+\d+', all_text, re.IGNORECASE)
                return match.group(0)
            if re.search(r'\bFinal\b', all_text, re.IGNORECASE):
                return "Final"
            if re.search(r'\bPpd\b', all_text, re.IGNORECASE):
                return "Postponed"
            if re.search(r'\d+(st|nd|rd|th)\s+(Quarter|Period|Inning)', all_text, re.IGNORECASE):
                match = re.search(r'\d+(st|nd|rd|th)\s+(Quarter|Period|Inning)', all_text, re.IGNORECASE)
                return match.group(0)
            if re.search(r'\bLive\b', all_text, re.IGNORECASE):
                return "Live"
            if re.search(r'\d{1,2}:\d{2}\s*(AM|PM)', all_text, re.IGNORECASE):
                match = re.search(r'\d{1,2}:\d{2}\s*(AM|PM)', all_text, re.IGNORECASE)
                return f"Starts {match.group(0)}"
            status_selectors = [
                'div.Ta\(end\) Cl\(b\) Fw\(b\) YahooSans Fw\(700\)! Fz\(11px\)!',
                'div.game-status',
                'div.Fz\(12px\)',
                'span[data-tst="game-status"]'
            ]
            for selector in status_selectors:
                try:
                    elements = gamecard.select(selector)
                    for elem in elements:
                        text = elem.get_text(strip=True)
                        if text and text not in ['', ' '] and text.lower() not in team_keywords:
                            return text
                except:
                    continue
            return "Scheduled"
        except Exception as e:
            debug_log(f"SportsGrid: Error in get_game_status: {str(e)}", xbmc.LOGERROR)
            return "TBD"
        
    def set_time_slots(self):
        """Set up sports-appropriate time slots for the grid."""
        now = datetime.now().astimezone(self.local_tz)
        # Create predefined time slots for games
        self.time_slots = [
            # Morning games
            (now.replace(hour=9, minute=0, second=0, microsecond=0),
             now.replace(hour=12, minute=0, second=0, microsecond=0)),
            # Early afternoon games
            (now.replace(hour=12, minute=0, second=0, microsecond=0),
             now.replace(hour=15, minute=0, second=0, microsecond=0)),
            # Late afternoon games
            (now.replace(hour=15, minute=0, second=0, microsecond=0),
             now.replace(hour=18, minute=0, second=0, microsecond=0)),
            # Evening games
            (now.replace(hour=18, minute=0, second=0, microsecond=0),
             now.replace(hour=21, minute=0, second=0, microsecond=0)),
            # Night games
            (now.replace(hour=21, minute=0, second=0, microsecond=0),
             now.replace(hour=23, minute=59, second=59, microsecond=999999))
        ]
        
    def get_scores(self):
        try:
            url = f"https://sports.yahoo.com/{self.sport}/scoreboard"
            # debug_log(f"SportsGrid: Fetching scores from: {url}", xbmc.LOGINFO)
            response = requests.get(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'},
                timeout=10
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            games = []
            game_lists = soup.find_all('ul')
            if not game_lists:
                debug_log("SportsGrid: No game lists found in HTML", xbmc.LOGWARNING)
                return []
            for game_list in game_lists:
                for game in game_list.find_all('li'):
                    team_elements = game.find_all('span', {'data-tst': 'first-name'})
                    if len(team_elements) < 2:
                        debug_log("SportsGrid: Skipping game with insufficient team elements", xbmc.LOGDEBUG)
                        continue
                    def get_team_name(elem):
                        try:
                            city = elem.text.strip()
                            if not city:
                                debug_log("SportsGrid: Empty city name", xbmc.LOGDEBUG)
                                return None
                            nickname_elem = elem.find_next('div', {'class': 'Fw(n) Fz(12px)'}) or elem.find_next('span', {'data-tst': 'last-name'})
                            if not nickname_elem:
                                debug_log("SportsGrid: No nickname element found", xbmc.LOGDEBUG)
                                return city
                            nickname = nickname_elem.text.strip()
                            if not nickname:
                                debug_log("SportsGrid: Empty nickname", xbmc.LOGDEBUG)
                                return city
                            full_name = f"{city} {nickname}".strip()
                            normalized_name = self.normalize_team_name(full_name, self.sport)
                            return normalized_name
                        except Exception as e:
                            debug_log(f"SportsGrid: Error parsing team name: {str(e)}", xbmc.LOGERROR)
                            return None
                    team1_name = get_team_name(team_elements[0])
                    team2_name = get_team_name(team_elements[1])
                    if not team1_name or not team2_name:
                        debug_log("SportsGrid: Skipping game due to missing team names", xbmc.LOGDEBUG)
                        continue
                    score_elements = game.find_all('span', {'class': 'YahooSans Fw(700)! Va(m) Fz(24px)!'})
                    score1 = score_elements[0].text.strip() if score_elements else ''
                    score2 = score_elements[1].text.strip() if len(score_elements) >= 2 else ''
                    status_text = self.get_game_status(game)
                    network_element = game.find('div', {'class': 'Ta(start) D(b) C(secondary-text)'})
                    network = network_element.find_all('span')[-1].text.strip() if network_element else 'TBD'
                    games.append({
                        'team1': team1_name,
                        'team2': team2_name,
                        'score1': score1,
                        'score2': score2,
                        'status': status_text,
                        'network': network,
                        'time': None
                    })
            # debug_log(f"SportsGrid: Parsed {len(games)} games", xbmc.LOGINFO)
            return games
        except Exception as e:
            debug_log(f"SportsGrid: Error in get_scores: {str(e)}", xbmc.LOGERROR)
            return []

    def get_standings(self):
        try:
            suffixes = {
                "mlb": "WILDCARD",
                "nhl": "CONFERENCE",
                "nba": "CONFERENCE",
                "wnba": "PLAYOFFS",
                "nfl": "PLAYOFFS"
            }
            url = f"https://sports.yahoo.com/{self.sport}/standings/?selectedTab={suffixes.get(self.sport, '')}"
            # debug_log(f"SportsGrid: Fetching standings from: {url}", xbmc.LOGINFO)
            response = requests.get(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                timeout=10
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            standings = []
            tables = soup.find_all("table", {"data-tst": "group-table"})
            if not tables:
                tables = soup.find_all("table", {"class": lambda x: x and ('Table' in x or 'standings' in x.lower())})
            if not tables:
                standings_section = soup.find('section', {'class': lambda x: x and 'standings' in x.lower()})
                if standings_section:
                    tables = standings_section.find_all('table')
            if not tables:
                debug_log("SportsGrid: No standings tables found", xbmc.LOGWARNING)
                return []
            stat_headers = {
                "mlb": ['wins', 'losses', 'pct', 'gb', 'home', 'away', 'last10', 'streak'],
                "nba": ['wins', 'losses', 'pct', 'gb', 'home', 'div', 'conf', 'last10', 'streak'],
                "wnba": ['wins', 'losses', 'pct', 'gb', 'home', 'div', 'conf', 'last10', 'streak'],
                "nhl": ['wins', 'losses', 'otl', 'pts', 'row', 'home', 'road', 'last10', 'streak'],
                "nfl": ['wins', 'losses', 'pct', 'div', 'home', 'away', 'div', 'conf', 'last5', 'streak']
            }
            for table_idx, table in enumerate(tables):
                header = table.find_previous_sibling(['h2', 'h3', 'h4'])
                if header:
                    division = header.get_text(strip=True)
                    standings.append({'team_name': division})
                rows = table.find_all('tr')
                header_row = rows[0] if rows else None
                headers = [th.get_text(strip=True).lower() for th in header_row.find_all(['th', 'td'])] if header_row else []
                for row_idx, row in enumerate(rows[1:], 1):
                    try:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) < 3:
                            debug_log(f"SportsGrid: Skipping standings row {row_idx} due to insufficient cells", xbmc.LOGDEBUG)
                            continue
                        team_elem = cells[0].find('a')
                        team_name = team_elem.get_text(strip=True) if team_elem else cells[0].get_text(strip=True)
                        # Extract logo URL from any <img> in the first cell (skip spaceball.gif)
                        logo_url = ""
                        imgs = cells[0].find_all('img')
                        for img in imgs:
                            if img.has_attr('src') and 'spaceball.gif' not in img['src']:
                                logo_url = img['src']
                                break
                            # If src is spaceball.gif, try to extract real logo from style attribute
                            if img.has_attr('src') and img['src'].endswith('spaceball.gif') and img.has_attr('style'):
                                import re
                                m = re.search(r'background-image:\s*url\((["\']?)(.*?)\1\)', img['style'])
                                if m:
                                    logo_url = m.group(2).strip(' "\'')
                                    break
                        if not team_name or team_name.isspace():
                            debug_log(f"SportsGrid: Skipping standings row {row_idx} due to empty team name", xbmc.LOGDEBUG)
                            continue
                        # if not logo_url:
                        #     # Log tag names and attributes of all children in the cell for debugging
                        #     for child in cells[0].descendants:
                        #         if hasattr(child, 'name') and child.name:
                        #             debug_log(f"SportsGrid DEBUG: Cell child tag: <{child.name}> attrs: {child.attrs}", xbmc.LOGINFO)
                        if any(word in team_name.lower() for word in ['division', 'conference', 'league', 'wild card']):
                            standings.append({'team_name': team_name})
                            continue
                        normalized_name = self.normalize_team_name(team_name, self.sport)
                        record = {'team_name': normalized_name, 'logo_url': logo_url}
                        for i, cell in enumerate(cells[1:], 1):
                            text = cell.get_text(strip=True)
                            header = headers[i] if i < len(headers) else ''
                            stat_key = stat_headers.get(self.sport, [])[i-1] if i-1 < len(stat_headers.get(self.sport, [])) else f'stat{i}'
                            if header and 'pct' in header.lower():
                                stat_key = 'pct'
                            elif header and 'gb' in header.lower():
                                stat_key = 'gb'
                            elif header and 'point' in header.lower():
                                stat_key = 'pts'
                            record[stat_key] = text
                        standings.append(record)
                    except Exception as e:
                        debug_log(f"SportsGrid: Error processing standings row {row_idx}: {str(e)}", xbmc.LOGERROR)
                        continue
            # debug_log(f"SportsGrid: Parsed {len(standings)} standings entries", xbmc.LOGINFO)
            return standings
        except Exception as e:
            debug_log(f"SportsGrid: Error in get_standings: {str(e)}", xbmc.LOGERROR)
            return []

    def format_channels(self, standings):
        """Format standings data as channels for the grid"""
        channels = []
        channel_number = 1
        for entry in standings:
            if 'team_name' in entry and len(entry) == 1:
                continue
            stats = []
            if entry.get('wins') and entry.get('losses'):
                stats.append(f"{entry['wins']} - {entry['losses']}")
            if entry.get('pct'):
                stats.append(f"{entry['pct']}")
            if entry.get('gb'):
                stats.append(f"{entry['gb']}")
            if entry.get('home'):
                stats.append(f"{entry['home']}")
            if entry.get('away') or entry.get('road'):
                stats.append(f"{entry.get('away', entry.get('road', ''))}")
            if entry.get('last10') or entry.get('last5'):
                stats.append(f"{entry.get('last10', entry.get('last5', ''))}")
            if entry.get('streak'):
                stats.append(f"{entry['streak']}")
            record = " | ".join(stats)
            channel = {
                'name': entry['team_name'],
                'tvg_id': f"sports_{self.sport}_{channel_number}",
                'logo': entry.get('logo_url', ''),
                'group': self.sport.upper(),
                'record': record,
                'label': str(channel_number),
                'label2': entry['team_name']
            }
            channels.append(channel)
            channel_number += 1
        return channels

    def format_programs(self, games):
        """Format game data as programs for the grid"""
        programs = []
        processed_games = set()
        if not self.time_slots:
            self.set_time_slots()
        now = datetime.now().astimezone(self.local_tz)
        
        for game in games:
            game_id = f"{game['team1']}-{game['team2']}"
            if game_id in processed_games:
                continue
            processed_games.add(game_id)
            status_text = game['status'] if game['status'] else "TBD"
            
            # Simplified - just use default time slot and focus on status
            slot_start, slot_end = self.time_slots[3]  # Default to evening slot
            time_text = status_text  # Use status as time display
            
            team1_norm = game['team1']
            team2_norm = game['team2']
            
            team1_channel = next((c['tvg_id'] for c in self.channels
                                if self.normalize_team_name(c['name'], self.sport) == team1_norm), None)
            team2_channel = next((c['tvg_id'] for c in self.channels
                                if self.normalize_team_name(c['name'], self.sport) == team2_norm), None)
            
            # if not team1_channel:
            #     # debug_log(f"SportsGrid: Could not find channel for team {game['team1']} (normalized: {team1_norm})", xbmc.LOGWARNING)
            # if not team2_channel:
                # debug_log(f"SportsGrid: Could not find channel for team {game['team2']} (normalized: {team2_norm})", xbmc.LOGWARNING)
            # Add program even if only one channel is found
            if team1_channel or team2_channel:
                score_text = f" ({game['score1']}-{game['score2']})" if game['score1'] and game['score2'] else ""
                if 'final' in status_text.lower():
                    prefix = "[FINAL]"
                elif 'postponed' in status_text.lower() or 'ppd' in status_text.lower():
                    prefix = "[POSTPONED]"
                elif any(hint in status_text.lower() for hint in ['inning', 'quarter', 'period', 'live', 'bot', 'top']):
                    prefix = f"[[COLORlime]Live[/COLOR] - {status_text}]"
                elif 'scheduled' in status_text.lower():
                    prefix = "[SCHEDULED]"
                else:
                    prefix = f"[{status_text}]" if status_text != "Scheduled" else "[TBD]"
                game_text = f"{team1_norm.upper()} vs {team2_norm.upper()}{score_text}"
                game_title = f"{prefix} | {game_text}"
                desc_lines = [
                    f"Status: {status_text}",
                    f"Time: {time_text}",
                    f"Teams: {team1_norm.upper()} vs {team2_norm.upper()}{score_text}",
                    f"Network: {game['network'] or 'TBD'}"
                ]
                program_data = {
                    'start': slot_start,
                    'stop': slot_end,
                    'title': game_title,
                    'desc': "\n".join(desc_lines),
                    'category': self.sport.upper(),
                    'time': time_text,
                    'status': status_text
                }
                program_data['channel'] = team1_channel or team2_channel
                program_data['away_channel'] = team2_channel if team1_channel else None
                programs.append(program_data)
        return programs
        
    def update_selected_info(self):
        """Update info panel based on current selection"""
        try:
            focused_id = self.getFocusId()
            
            if focused_id == 100 and self.channel_panel:  # Team stats panel
                # Show team statistics
                selected_pos = self.channel_panel.getSelectedPosition()
                if 0 <= selected_pos < self.channel_panel.size():
                    selected_item = self.channel_panel.getSelectedItem()
                    team_name = selected_item.getLabel()
                    team_record = selected_item.getProperty('record')
                    
                    # Build team stats info
                    stats_info = []
                    if team_record:
                        stats_info.append(f"Record: {team_record}")
                    
                    # Add any additional team stats from properties
                    for prop in ['wins', 'losses', 'pct', 'gb', 'home', 'away', 'l10']:
                        value = selected_item.getProperty(prop)
                        if value:
                            stats_info.append(f"{prop.upper()}: {value}")
                    
                    self.setProperty('GameTitle', f"[B]{team_name.upper()} Statistics[/B]")
                    self.setProperty('GameInfo', '\n'.join(stats_info) if stats_info else 'No statistics available')
                    
            elif focused_id == 101 and self.time_panel:  # Games panel
                # Show game information
                selected_pos = self.time_panel.getSelectedPosition()
                if 0 <= selected_pos < self.time_panel.size():
                    selected_item = self.time_panel.getSelectedItem()
                    game_info_text = selected_item.getProperty('game')
                    
                    if game_info_text:
                        self.setProperty('GameTitle', '[B]Game Information[/B]')
                        self.setProperty('GameInfo', game_info_text)
                    else:
                        self.setProperty('GameTitle', '[B]No Game Selected[/B]')
                        self.setProperty('GameInfo', 'Select a game to view details')
            else:
                # Clear info if no valid selection
                self.setProperty('GameTitle', '')
                self.setProperty('GameInfo', '')
                
        except Exception as e:
            # Clear properties on error
            self.setProperty('GameTitle', '')
            self.setProperty('GameInfo', '')

    def update_program_info(self, selected_item, channel=None):
        """Update the info panel with sports-specific information"""
        try:
            # Clear properties if no item
            self.setProperty('GameTitle', '')
            self.setProperty('GameInfo', '')
            if not selected_item:
                return
            # Get game title from item or dict
            game = (selected_item.getProperty('game') if isinstance(selected_item, xbmcgui.ListItem)
                   else selected_item.get('title', ''))
            if not game:
                return
            # Build info display
            game_info = []
            self.setProperty('GameTitle', f"[B]{game}[/B]")
            # Add channel/team info if available
            if channel and isinstance(channel, dict):
                record = channel.get('record', '')
                team_name = channel.get('name', '')
                if record and team_name:
                    game_info.append(f"[COLOR yellow]{team_name.upper()}:[/COLOR] {record}")
            # Add program details
            for program in self.programs:
                if program.get('title') == game and program.get('desc'):
                    for line in program['desc'].split('\n'):
                        game_info.append(line)
            self.setProperty('GameInfo', '\n'.join(game_info))
            
        except Exception as e:
            # debug_log(f"SportsGrid: Error updating program info: {str(e)}", xbmc.LOGERROR)
            # Clear properties on error
            self.setProperty('GameTitle', '')
            self.setProperty('GameInfo', '')
    
    def show_loading(self):
        """Show the loading overlay"""
        try:
            loading_control = self.getControl(999)
            loading_control.setVisible(True)
        except Exception as e:
            pass
    
    def hide_loading(self):
        """Hide the loading overlay"""
        try:
            loading_control = self.getControl(999)
            loading_control.setVisible(False)
        except Exception as e:
            pass
    
    def update_loading_progress(self, progress_text="", percent=0):
        """Update loading progress text and bar"""
        try:
            # Update loading text
            if progress_text:
                text_control = self.getControl(998)
                text_control.setLabel(progress_text)
            
            # Update progress bar width (360px max width)
            if 0 <= percent <= 100:
                progress_width = int((percent / 100) * 360)
                progress_control = self.getControl(997)
                progress_control.setWidth(progress_width)
        except Exception as e:
            pass