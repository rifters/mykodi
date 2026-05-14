import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmcvfs
from xbmcvfs import exists, mkdirs, translatePath
import urllib.request
import urllib.parse
import re
import sys
import json
import xml.etree.ElementTree as ET
import os
from datetime import datetime, timedelta, timezone
from tools import debug_log
xbmc = xbmc
xbmcgui = xbmcgui
xbmcplugin = xbmcplugin

ADDON = xbmcaddon.Addon()
try:
    HANDLE = int(sys.argv[1])
except (IndexError, ValueError):
    HANDLE = 0
if HANDLE < 0:
    HANDLE = 0
BASE_URL = sys.argv[0]

CACHE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
SPORTS_CACHE_FILE = os.path.join(CACHE_PATH, 'sports_cache.json')
SPORTS_CACHE_TIME_FILE = os.path.join(CACHE_PATH, 'sports_cache_time.txt')
SPORTS_CACHE_DURATION = 6 * 60 * 60  # 6 hours in seconds

# YouTube guide cache
YOUTUBE_CACHE_FILE = os.path.join(CACHE_PATH, 'youtube_cache.json')
YOUTUBE_CACHE_TIME_FILE = os.path.join(CACHE_PATH, 'youtube_cache_time.txt')
YOUTUBE_CACHE_DURATION = 6 * 60 * 60  # 6 hours in seconds


if not xbmcvfs.exists(CACHE_PATH):
    xbmcvfs.mkdirs(CACHE_PATH)

def datetime_handler(obj):
    """JSON serializer for datetime objects"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

def parse_datetime(datetime_str):
    """Convert ISO format datetime string back to datetime object"""
    try:
        return datetime.fromisoformat(datetime_str)
    except:
        return None

def save_sports_cache(channels, programs, cache_file, time_file):
    """Save sports data to cache"""
    try:
        cache_data = {'channels': channels, 'programs': programs}
        with xbmcvfs.File(cache_file, 'w') as f:
            f.write(json.dumps(cache_data, default=datetime_handler, indent=2, ensure_ascii=False))
        with xbmcvfs.File(time_file, 'w') as f:
            f.write(datetime.now().isoformat())
        # debug_log(f"DEBUG: Saved sports cache to {cache_file}", xbmc.LOGINFO)
    except Exception as e:
        pass
        # debug_log(f"DEBUG: Failed to save sports cache: {str(e)}", xbmc.LOGERROR)

def load_sports_cache(cache_file, time_file):
    """Load sports data from cache"""
    try:
        if xbmcvfs.exists(cache_file) and xbmcvfs.exists(time_file):
            with xbmcvfs.File(time_file, 'r') as f:
                cache_time = parse_datetime(f.read().strip())
            if cache_time and (datetime.now() - cache_time).total_seconds() < SPORTS_CACHE_DURATION:
                with xbmcvfs.File(cache_file, 'r') as f:
                    data = json.loads(f.read())
                for program in data.get('programs', []):
                    if 'start' in program:
                        program['start'] = parse_datetime(program['start'])
                    if 'stop' in program:
                        program['stop'] = parse_datetime(program['stop'])
                # debug_log(f"DEBUG: Loaded sports cache from {cache_file}", xbmc.LOGINFO)
                return data.get('channels', []), data.get('programs', []), cache_time
    except Exception as e:
        # debug_log(f"DEBUG: Failed to load sports cache: {str(e)}", xbmc.LOGERROR)
        pass
    return [], [], None

def save_youtube_cache(channels, programs, cache_file, time_file):
    """Save YouTube guide data to cache"""
    try:
        cache_data = {'channels': channels, 'programs': programs}
        with xbmcvfs.File(cache_file, 'w') as f:
            f.write(json.dumps(cache_data, default=datetime_handler, indent=2, ensure_ascii=False))
        with xbmcvfs.File(time_file, 'w') as f:
            f.write(datetime.now().isoformat())
        debug_log(f"DEBUG: Saved YouTube cache to {cache_file}", xbmc.LOGINFO)
    except Exception as e:
        debug_log(f"DEBUG: Failed to save YouTube cache: {str(e)}", xbmc.LOGERROR)

def load_youtube_cache(cache_file, time_file):
    """Load YouTube guide data from cache"""
    try:
        if xbmcvfs.exists(cache_file) and xbmcvfs.exists(time_file):
            with xbmcvfs.File(time_file, 'r') as f:
                cache_time = parse_datetime(f.read().strip())
            if cache_time and (datetime.now() - cache_time).total_seconds() < YOUTUBE_CACHE_DURATION:
                with xbmcvfs.File(cache_file, 'r') as f:
                    data = json.loads(f.read())
                # Convert datetime strings back to datetime objects for programs
                for program in data.get('programs', []):
                    if 'start' in program:
                        program['start'] = parse_datetime(program['start'])
                    if 'stop' in program:
                        program['stop'] = parse_datetime(program['stop'])
                debug_log(f"DEBUG: Loaded YouTube cache from {cache_file}", xbmc.LOGINFO)
                return data.get('channels', []), data.get('programs', []), cache_time
    except Exception as e:
        debug_log(f"DEBUG: Failed to load YouTube cache: {str(e)}", xbmc.LOGERROR)
    return [], [], None

def parse_sports_data(data, sport_type):
    channels = []
    programs = []
    sports_icon = ['mlb', 'soccer', 'football', 'basketball', 'hockey', 'baseball', 'tennis', 'wnba']
    default_sports_icon = 'special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/sports_icon.png'
    
    debug_log(f"DEBUG: Parsing sports data for {sport_type}, items: {len(data.get('items', []))}", xbmc.LOGINFO)
    for item in data.get('items', []):
        if item.get('type') != 'item':
            continue
        title = item.get('title', '').replace('[COLOR]', '').replace('[/COOR]', '')
        league = item.get('league', sport_type)
        links = item.get('link', [])
        fanart = item.get('fanart', '') or default_sports_icon
        thumbnail = item.get('thumbnail', '') or default_sports_icon
        guide_data = item.get('guidedata', [])
        
        if not guide_data:
            # debug_log(f"DEBUG: Skipping item {title} due to no guide data", xbmc.LOGDEBUG)
            continue
        channel_id = f"sports_{sport_type}_{len(channels)}"
        stream_names = []
        for link in links:
            if '(' in link and ')' in link:
                name = link[link.rindex('(')+1:link.rindex(')')]
                stream_names.append(name)
            else:
                stream_names.append(f"Stream {len(stream_names)+1}")
                
        channel = {
            'name': title,
            'tvg_id': channel_id,
            'logo': fanart if fanart != default_sports_icon else thumbnail,
            'group': league.upper(),
            'url': links[0] if links else '',
            'all_links': links,
            'stream_names': stream_names
        }
        channels.append(channel)
        for event in guide_data:
            start_time = datetime.fromtimestamp(event.get('starttime', 0), tz=timezone.utc)
            duration = event.get('duration', 7200)
            stop_time = start_time + timedelta(seconds=duration)
            program = {
                'channel': channel_id,
                'start': start_time,
                'stop': stop_time,
                'title': event.get('label', title).replace('[COLOR]', '').replace('[/COOR]', ''),
                'desc': f"Available on: {len(links)} sources",
                'category': [league.upper()],
                'icon': {'src': fanart}
            }
            programs.append(program)
    
    # debug_log(f"DEBUG: Parsed {len(channels)} channels and {len(programs)} programs for {sport_type}", xbmc.LOGINFO)
    return channels, programs

def parse_sports_json():
    """Parse sports JSON files from enabled sources"""
    try:
        # Try loading from cache first
        cached_channels, cached_programs, cache_time = load_sports_cache(SPORTS_CACHE_FILE, SPORTS_CACHE_TIME_FILE)
        if cached_channels and cached_programs:
            # debug_log(f"DEBUG: Using cached sports data, channels: {len(cached_channels)}, programs: {len(cached_programs)}", xbmc.LOGINFO)
            return cached_channels, cached_programs
        
        all_channels = []
        all_programs = []
        headers = {'User-Agent': 'Mozilla/5.0'}
        sports_urls = [
            ('ppv', 'include_ppv', 'ppv_url'),
            ('nba', 'include_nba', 'nba_url'),
            ('ufc', 'include_ufc', 'ufc_url'),
            ('boxing', 'include_boxing', 'boxing_url'),
            ('nfl', 'include_nfl', 'nfl_url'),
            ('mlb', 'include_mlb', 'mlb_url'),
            ('nhl', 'include_nhl', 'nhl_url'),
            ('basketball', 'include_basketball', 'basketball_url'),
            ('ice_hockey', 'include_ice_hockey', 'ice_hockey_url'),
            ('ncaaf', 'include_ncaaf', 'ncaaf_url'),
            ('ncaab', 'include_ncaab', 'ncaab_url'),
            ('ncaa_baseball', 'include_ncaa_baseball', 'ncaa_baseball_url'),
            ('wrestling', 'include_wrestling', 'wrestling_url'),
            ('soccer', 'include_soccer', 'soccer_url'),
            ('england_soccer', 'include_england_soccer', 'england_soccer_url'),
            ('mls', 'include_mls', 'mls_url'),
            ('athletics', 'include_athletics', 'athletics_url'),
            ('aussie_rules', 'include_aussie_rules', 'aussie_rules_url'),
            ('bowling', 'include_bowling', 'bowling_url'),
            ('cfl', 'include_cfl', 'cfl_url'),
            ('cricket', 'include_cricket', 'cricket_url'),
            ('cycling', 'include_cycling', 'cycling_url'),
            ('darts', 'include_darts', 'darts_url'),
            ('futsal', 'include_futsal', 'futsal_url'),
            ('gaa', 'include_gaa', 'gaa_url'),
            ('golf', 'include_golf', 'golf_url'),
            ('gymnastics', 'include_gymnastics', 'gymnastics_url'),
            ('handball', 'include_handball', 'handball_url'),
            ('horse_racing', 'include_horse_racing', 'horse_racing_url'),
            ('lacrosse', 'include_lacrosse', 'lacrosse_url'),
            ('motorsport', 'include_motorsport', 'motorsport_url'),
            ('rugby', 'include_rugby', 'rugby_url'),
            ('sailing_boating', 'include_sailing_boating', 'sailing_boating_url'),
            ('snooker', 'include_snooker', 'snooker_url'),
            ('squash', 'include_squash', 'squash_url'),
            ('tennis', 'include_tennis', 'tennis_url'),
            ('volleyball', 'include_volleyball', 'volleyball_url'),
            ('water_sports', 'include_water_sports', 'water_sports_url'),
            ('espn_plus', 'include_espn_plus', 'espn_plus_url'),
            ('events', 'include_events', 'events_url')
        ]
        
        for sport_type, setting, url_setting in sports_urls:
            if ADDON.getSettingBool(setting):
                url = ADDON.getSetting(url_setting)
                if not url:
                    # debug_log(f"DEBUG: No URL set for {sport_type}", xbmc.LOGWARNING)
                    continue
                try:
                    request = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(request, timeout=10) as response:
                        data = json.loads(response.read())
                        channels, programs = parse_sports_data(data, sport_type)
                        all_channels.extend(channels)
                        all_programs.extend(programs)
                        # debug_log(f"DEBUG: Fetched {len(channels)} channels and {len(programs)} programs from {sport_type}", xbmc.LOGINFO)
                except Exception as e:
                    # debug_log(f"DEBUG: Failed to fetch {sport_type} data from {url}: {str(e)}", xbmc.LOGERROR)
                    continue
        
        if all_channels and all_programs:
            save_sports_cache(all_channels, all_programs, SPORTS_CACHE_FILE, SPORTS_CACHE_TIME_FILE)
        
        return all_channels, all_programs
    except Exception as e:
        # debug_log(f"DEBUG: parse_sports_json error: {str(e)}", xbmc.LOGERROR)
        return [], []

def show_sports_guide():
    """Show sports events in EPG grid view"""
    try:
        xbmc.executebuiltin('Dialog.Close(all, true)')
        xbmc.sleep(200)
        
        progress = xbmcgui.DialogProgress()
        progress.create('Loading Sports Guide', 'Fetching sports data...')
        progress.update(0)
        
        channels, programs = parse_sports_json()
        progress.update(50, 'Filtering sports events...')
        
        import re
        from datetime import datetime
        import tzlocal
        local_tz = tzlocal.get_localzone()
        now = datetime.now(local_tz)
        today = now.date()

        # Dialog for mode selection
        dlg = xbmcgui.Dialog()
        choice = dlg.select("Show Sports", ["Today's Games", "Live Now"])
        def is_today_local(dt):
            try:
                return dt.astimezone(local_tz).date() == today
            except Exception:
                return False
        def is_live_now(p):
            try:
                start = p.get('start')
                stop = p.get('stop')
                return start and stop and start.astimezone(local_tz) <= now <= stop.astimezone(local_tz)
            except Exception:
                return False
        if choice == 1:
            programs = [p for p in programs if is_live_now(p)]
        else:
            programs = [p for p in programs if p.get('start') and is_today_local(p['start'])]
        channel_ids = set(p['channel'] for p in programs)
        channels = [c for c in channels if c.get('tvg_id') in channel_ids]
        
        progress.update(75, 'Preparing guide...')
        if not channels or not programs:
            progress.close()
            xbmcgui.Dialog().ok('Sports Guide', 'No enabled sports events found')
            # debug_log(f"DEBUG: No sports events found, channels: {len(channels)}, programs: {len(programs)}", xbmc.LOGWARNING)
            return
            
        from epggrid import EPGGrid
        addon_path = ADDON.getAddonInfo('path')
        skin_xml = os.path.join(addon_path, 'resources', 'skins', 'default', '720p', 'tuepg.guide.experimental.xml')
        
        if not os.path.exists(skin_xml):
            progress.close()
            raise Exception(f"EPG skin XML not found at {skin_xml}")
            
        xml_file = 'tuepg.guide.experimental.xml'
        xbmc.sleep(100)
        window = EPGGrid(xml_file, addon_path, channels=channels, programs=programs)
        window.is_sports_view = True
        progress.update(100)
        progress.close()
        window.doModal()
        del window
        
    except Exception as e:
        if 'progress' in locals():
            progress.close()
        xbmcgui.Dialog().ok("Error", f"Failed to load sports guide: {str(e)}")
        # debug_log(f"DEBUG: show_sports_guide error: {str(e)}", xbmc.LOGERROR)

class FavoritesManager:
    """Manage favorite channels storage and operations"""
    def __init__(self):
        self.addon = xbmcaddon.Addon()
        self.profile_path = xbmcvfs.translatePath(self.addon.getAddonInfo('profile'))
        self.favorites_path = os.path.join(self.profile_path, 'favorites.json')
        
        if not xbmcvfs.exists(self.profile_path):
            xbmcvfs.mkdirs(self.profile_path)
            
        if not xbmcvfs.exists(self.favorites_path):
            self.save_favorites([])
    
    def load_favorites(self):
        """Load favorite channels from file"""
        try:
            with open(self.favorites_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            return []
    
    def save_favorites(self, favorites):
        """Save favorite channels to file"""
        try:
            with open(self.favorites_path, 'w') as f:
                json.dump(favorites, f, indent=2)
        except Exception as e:
            pass
    
    def is_favorite(self, channel_id):
        """Check if a channel is in favorites"""
        favorites = self.load_favorites()
        return any(f['tvg_id'] == channel_id for f in favorites)
    
    def add_favorite(self, channel):
        """Add a channel to favorites"""
        favorites = self.load_favorites()
        if not any(f['tvg_id'] == channel['tvg_id'] for f in favorites):
            favorites.append(channel)
            self.save_favorites(favorites)
            return True
        return False
    
    def remove_favorite(self, channel_id):
        """Remove a channel from favorites"""
        favorites = self.load_favorites()
        favorites = [f for f in favorites if f['tvg_id'] != channel_id]
        self.save_favorites(favorites)

favorites_manager = FavoritesManager()

class LastWatchedManager:
    """Manage last watched channels storage and operations"""
    def __init__(self):
        self.addon = xbmcaddon.Addon()
        self.profile_path = translatePath(self.addon.getAddonInfo('profile'))
        
        try:
            os.makedirs(self.profile_path, exist_ok=True)
        except PermissionError as e:
            self.profile_path = xbmcvfs.translatePath("special://temp/")
            self.last_watched_path = os.path.join(self.profile_path, 'last_watched.json')
            os.makedirs(self.profile_path, exist_ok=True)
        except Exception as e:
            raise RuntimeError(f"Cannot create directory: {str(e)}")
            
        if not hasattr(self, 'last_watched_path'):
            self.last_watched_path = os.path.join(self.profile_path, 'last_watched.json')
        
        try:
            self.max_channels = int(self.addon.getSetting('max_last_watched') or '10')
        except:
            self.max_channels = 10
            
        if not os.path.exists(self.last_watched_path):
            self.save_last_watched([])
    
    def load_last_watched(self):
        """Load last watched channels from file"""
        try:
            if not exists(self.last_watched_path):
                self.save_last_watched([])
                return []
            with open(self.last_watched_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content.strip():
                    return []
                data = json.loads(content)
                if not isinstance(data, list):
                    self.save_last_watched([])
                    return []
                return data
        except Exception as e:
            return []
    
    def save_last_watched(self, channels):
        """Save last watched channels to file"""
        try:
            directory = os.path.dirname(self.last_watched_path)
            if not exists(directory):
                mkdirs(directory)
            if not os.access(directory, os.W_OK):
                raise PermissionError(f"No write permission for {directory}")
                
            json_data = json.dumps(channels, indent=2, ensure_ascii=False)
            temp_path = self.last_watched_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(json_data)
            if exists(self.last_watched_path):
                os.remove(self.last_watched_path)
            os.rename(temp_path, self.last_watched_path)
        except Exception as e:
            if exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            raise IOError(f"Failed to save last watched file: {str(e)}")
    
    def add_last_watched(self, channel):
        """Add a channel to last watched, maintaining order and max size"""
        try:
            channel_name = channel.get('name', 'Unknown')
            required_fields = ['name', 'tvg_id', 'url']
            missing_fields = [field for field in required_fields if field not in channel or not channel[field]]
            if missing_fields:
                raise ValueError(f"Missing or empty fields: {missing_fields}")
            channels = self.load_last_watched()
            channels = [c for c in channels if c['tvg_id'] != channel['tvg_id']]
            
            channel_data = {
                'name': channel['name'],
                'tvg_id': channel['tvg_id'],
                'url': channel['url'],
                'logo': channel.get('logo', ''),
                'group': channel.get('group', ''),
                'added': datetime.now().isoformat()
            }
            
            channels.insert(0, channel_data)
            channels = channels[:self.max_channels]
            self.save_last_watched(channels)
            saved_channels = self.load_last_watched()
            if not saved_channels and channels:
                raise Exception("Failed to verify save channels")
        except Exception as e:
            raise IOError(f"Failed to add channel: {str(e)}")
    
    def clear_history(self):
        """Clear last watched history"""
        self.save_last_watched([])
        xbmcgui.Dialog().notification('TV Guide', 'Last watched history cleared')

last_watched_manager = LastWatchedManager()

def show_favorites():
    """Show favorites list"""
    show_favorites(HANDLE)

def get_url_settings(guide_number=1):
    """Get M3U8 and XMLTV URLs from settings for specified guide"""
    if guide_number == 2:
        m3u8_url = ADDON.getSetting('m3u8_url_2')
        xmltv_url = ADDON.getSetting('xmltv_url_2')
    else:
        m3u8_url = ADDON.getSetting('m3u8_url')
        xmltv_url = ADDON.getSetting('xmltv_url')
    return m3u8_url, xmltv_url

def get_active_guide():
    window = xbmcgui.Window(10000)
    return int(window.getProperty('tvguide.active_guide') or '1')

def set_active_guide(guide_number):
    window = xbmcgui.Window(10000)
    window.setProperty('tvguide.active_guide', str(guide_number))

active_guide = get_active_guide()
M3U8_PATH, XMLTV_PATH = get_url_settings(active_guide)

CACHE_DURATION = 6 * 60 * 60  # 6 hours in seconds

def datetime_handler(obj):
    """JSON serializer for datetime objects"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

def parse_datetime(datetime_str):
    """Convert ISO format datetime string back to datetime object"""
    try:
        return datetime.fromisoformat(datetime_str)
    except:
        return None

CACHE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))

if not xbmcvfs.exists(CACHE_PATH):
    xbmcvfs.mkdirs(CACHE_PATH)
    
def clear_cache(guide_number=None):
    """Clear cache for specified guide number or active guide"""
    try:
        if guide_number is None:
            guide_number = get_active_guide()
            
        cache_files = get_cache_files(guide_number)
        for cache_file in cache_files.values():
            if os.path.exists(cache_file):
                pass
                
        global M3U8_CACHE, M3U8_CACHE_TIME, XMLTV_CACHE, XMLTV_CACHE_TIME
        M3U8_CACHE = None
        M3U8_CACHE_TIME = None
        XMLTV_CACHE = None
        XMLTV_CACHE_TIME = None
        
    except Exception as e:
        pass

def get_cache_files(guide_number=1):
    """Get cache file paths for specified guide number"""
    suffix = f"_{guide_number}" if guide_number > 1 else ""
    return {
        'm3u8': os.path.join(CACHE_PATH, f'm3u8_cache{suffix}.json'),
        'xmltv': os.path.join(CACHE_PATH, f'xmltv_cache{suffix}.json'),
        'm3u8_time': os.path.join(CACHE_PATH, f'm3u8_cache_time{suffix}.txt'),
        'xmltv_time': os.path.join(CACHE_PATH, f'xmltv_cache_time{suffix}.txt'),
        'debug_log': os.path.join(CACHE_PATH, 'debug_log.txt')
    }

active_guide = get_active_guide()
cache_files = get_cache_files(active_guide)
M3U8_CACHE_FILE = cache_files['m3u8']
XMLTV_CACHE_FILE = cache_files['xmltv']
M3U8_CACHE_TIME_FILE = cache_files['m3u8_time']
XMLTV_CACHE_TIME_FILE = cache_files['xmltv_time']
DEBUG_LOG_FILE = cache_files['debug_log']

M3U8_CACHE = None
M3U8_CACHE_TIME = None
XMLTV_CACHE = None
XMLTV_CACHE_TIME = None
DEBUG_LOG_FILE = None

def save_cache(data, cache_file, time_file):
    """Save cache data to file"""
    try:
        with open(cache_file, 'w') as f:
            json.dump(data, f, default=datetime_handler)
        with open(time_file, 'w') as f:
            f.write(datetime.now().isoformat())
    except Exception as e:
        pass
def load_cache(cache_file, time_file):
    """Load cache data from file"""
    try:
        if xbmcvfs.exists(cache_file) and xbmcvfs.exists(time_file):
            with open(cache_file, 'r') as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            if 'start' in item:
                                item['start'] = parse_datetime(item['start'])
                            if 'stop' in item:
                                item['stop'] = parse_datetime(item['stop'])
            
            with open(time_file, 'r') as f:
                cache_time = parse_datetime(f.read().strip())
                
            if cache_time and is_cache_valid(cache_time):
                return data, cache_time
    except Exception as e:
        pass
    return None, None

def is_cache_valid(cache_time):
    """Check if cache is still valid"""
    if not cache_time:
        return False
    return (datetime.now() - cache_time).total_seconds() < CACHE_DURATION

def normalize_id(text):
    """Clean up channel IDs"""
    if not text:
        return ""
    text = text.lower()
    text = text.replace('.us', '').replace(',', '').replace('"', '').strip()
    text = re.sub(r'\s+', '.', text)
    text = re.sub(r'\.+', '.', text)
    return text

def parse_m3u8(path):
    """Parse M3U8 file to get channels"""
    global M3U8_CACHE, M3U8_CACHE_TIME
    current_time = datetime.now()
    
    cached_data, cached_time = load_cache(M3U8_CACHE_FILE, M3U8_CACHE_TIME_FILE)
    if cached_data:
        M3U8_CACHE = cached_data
        M3U8_CACHE_TIME = cached_time
        return cached_data
    channels = []
    channel_number = 1
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        request = urllib.request.Request(path, headers=headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            content = response.read().decode('utf-8', errors='ignore')
        lines = content.splitlines()
        current_channel = None
        
        for line in lines:
            line = line.strip()
            if line.startswith('#EXTINF'):
                try:
                    tvg_id_match = re.search(r'tvg-id="([^"]*)"', line)
                    tvg_name_match = re.search(r'tvg-name="([^"]*)"', line)
                    logo_match = re.search(r'tvg-logo="([^"]*)"', line)
                    group_match = re.search(r'group-title="([^"]*)"', line)
                    title_match = re.search(r',(?=(?:(?:"[^"]*")|[^"])*$)\s*([^\n]+)$', line)
                    
                    if title_match:
                        name = title_match.group(1).strip()
                    elif tvg_name_match and tvg_name_match.group(1).strip():
                        name = tvg_name_match.group(1).strip()
                    else:
                        name = f"Channel {channel_number}"
                    
                    tvg_id = tvg_id_match.group(1) if tvg_id_match else normalize_id(name)
                    logo = logo_match.group(1) if logo_match else ""
                    group = group_match.group(1) if group_match else ""
                    
                    current_channel = {
                        'name': name,
                        'tvg_id': tvg_id,
                        'logo': logo,
                        'group': group,
                        'normalized_name': normalize_id(name)
                    }
                    
                except Exception as e:
                    current_channel = None
                    continue
                
            elif line and not line.startswith('#') and current_channel:
                current_channel['url'] = line
                channels.append(current_channel)
                channel_number += 1
                current_channel = None
                
    except Exception as e:
        return []
    
    M3U8_CACHE = channels
    M3U8_CACHE_TIME = current_time
    save_cache(channels, M3U8_CACHE_FILE, M3U8_CACHE_TIME_FILE)
    return channels

def parse_xmltv(path):
    """Parse XMLTV file for program data"""
    global XMLTV_CACHE, XMLTV_CACHE_TIME
    current_time = datetime.now()
    
    cached_data, cached_time = load_cache(XMLTV_CACHE_FILE, XMLTV_CACHE_TIME_FILE)
    if cached_data:
        XMLTV_CACHE = cached_data
        XMLTV_CACHE_TIME = cached_time
        return cached_data
     
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        request = urllib.request.Request(path, headers=headers)
        
        with urllib.request.urlopen(request, timeout=10) as response:
            xml_data = response.read().decode('utf-8', errors='ignore')
            tree = ET.ElementTree(ET.fromstring(xml_data))
            
        programs = []
        local_tz = datetime.now().astimezone().tzinfo
        current_time = datetime.now().astimezone(local_tz)
        profile_path = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
        debug_log_path = os.path.join(profile_path, "debug_log.txt")
        try:
            if not xbmcvfs.exists(profile_path):
                xbmcvfs.mkdirs(profile_path)
        except Exception as e:
            # debug_log_path = xbmcvfs.translatePath("special://temp/debug_log.txt")
            pass
        
        # with open(debug_log_path, "w", encoding='utf-8') as debug_file:
        #     debug_file.write(f"XMLTV Parsing started at {datetime.now()}\n")
        #     debug_file.write(f"XMLTV URL: {path}\n")
        #     debug_file.write(f"XML data length: {len(xml_data)} bytes\n\n")
        program_count = 0
        desc_count = 0
        icon_count = 0
        
        for programme in tree.findall('.//programme'):
            try:
                # Create EDT timezone (UTC-4)
                edt = timezone(timedelta(hours=-4))
                # Parse times as EDT
                start = datetime.strptime(programme.get('start')[:14], '%Y%m%d%H%M%S').replace(tzinfo=edt)
                stop = datetime.strptime(programme.get('stop')[:14], '%Y%m%d%H%M%S').replace(tzinfo=edt)
                # Convert to local timezone (PDT)
                start_local = start.astimezone(local_tz)
                stop_local = stop.astimezone(local_tz)
                if stop_local < current_time - timedelta(hours=1):
                    continue
                title = programme.find('title').text if programme.find('title') is not None else "No Title"
                channel = programme.get('channel')
                
                desc_elem = programme.find('desc')
                desc = desc_elem.text if desc_elem is not None else ""
                
                icon_elem = programme.find('icon')
                icon = {'src': icon_elem.get('src')} if icon_elem is not None and icon_elem.get('src') else None
                
                sub_title_elem = programme.find('sub-title')
                sub_title = sub_title_elem.text if sub_title_elem is not None else ""
                
                categories = [cat.text for cat in programme.findall('category') if cat.text]
                
                episode_elem = programme.find('episode-num')
                episode = episode_elem.text if episode_elem is not None else ""
                
                rating_elem = programme.find('.//rating/value')
                rating = rating_elem.text if rating_elem is not None else ""
                
                actors = [actor.text for actor in programme.findall('.//credits/actor') if actor.text]
                
                # with open(debug_log_path, "a", encoding='utf-8') as debug_file:
                #     debug_file.write(f"Program: {title} on {channel}\n")
                #     debug_file.write(f"  Raw XML: {ET.tostring(programme, encoding='unicode')[:200]}...\n")
                #     if desc_elem is not None:
                #         debug_file.write(f"  Description found: {desc[:50]}...\n")
                #         desc_count += 1
                #     else:
                #         debug_file.write("  No description element found\n")
                #     if icon is not None:
                #         debug_file.write(f"  Icon found: {icon}\n")
                #         icon_count += 1
                #     else:
                #         debug_file.write("  No icon element found\n")
                
                programs.append({
                    'channel': channel,
                    'start': start_local,
                    'stop': stop_local,
                    'title': title,
                    'desc': desc,
                    'sub-title': sub_title,
                    'category': categories if categories else "",
                    'episode-num': episode,
                    'rating': rating,
                    'actors': actors,
                    'icon': icon
                })
                
                program_count += 1
                
            except Exception as e:
                continue
                
        # with open(debug_log_path, "a", encoding='utf-8') as debug_file:
        #     debug_file.write(f"\nSummary:\n")
        #     debug_file.write(f"Total programs processed: {program_count}\n")
        #     debug_file.write(f"Programs with descriptions: {desc_count}\n")
        #     debug_file.write(f"Programs with icons: {icon_count}\n")
        #     debug_file.write(f"Programs without descriptions: {program_count - desc_count}\n")
        
        XMLTV_CACHE = programs
        XMLTV_CACHE_TIME = current_time
        save_cache(programs, XMLTV_CACHE_FILE, XMLTV_CACHE_TIME_FILE)
        return programs
        
    except Exception as e:
        return []

def show_channel_listings():
    """Show channel listings"""
    try:
        if HANDLE > 0:
            channels = parse_m3u8(M3U8_PATH)
            for channel in channels:
                name = channel['name']
                list_item = xbmcgui.ListItem(name)
                list_item.setArt({'icon': channel.get('logo', '')})
                context_menu = []
                guide_url = f"{BASE_URL}?action=show_channel&id={urllib.parse.quote(channel['tvg_id'])}"
                context_menu.append(('Show Guide', f'Container.Update({guide_url})'))
                add_fav = f"{BASE_URL}?action=add_favorite&id={urllib.parse.quote(channel['tvg_id'])}"
                context_menu.append(('Add to Favorites', f'RunPlugin({add_fav})'))
                list_item.addContextMenuItems(context_menu)
                url = f"{BASE_URL}?action=play_channel&id={urllib.parse.quote(channel['tvg_id'])}"
                xbmcplugin.addDirectoryItem(HANDLE, url, list_item, False)
            xbmcplugin.endOfDirectory(HANDLE)
        else:
            from channellist import ChannelListWindow
            channels = parse_m3u8(M3U8_PATH)
            if not channels:
                xbmcgui.Dialog().ok('Channel List', 'No channels found')
                return
            addon_path = ADDON.getAddonInfo('path')
            window = ChannelListWindow('channel_list.xml', addon_path, channels=channels)
            window.doModal()
            del window
            
    except Exception as e:
        if HANDLE > 0:
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        xbmcgui.Dialog().ok("Error", f"Failed to load channel list: {str(e)}")

def show_favorites():
    """Show favorites in EPG grid view"""
    try:
        xbmc.executebuiltin('Dialog.Close(all)')
        xbmc.sleep(200)
        favorites = favorites_manager.load_favorites()
        if not favorites:
            xbmcgui.Dialog().ok('Favorites', 'No favorite channels added yet')
            return
        from epggrid import EPGGrid
        programs = parse_xmltv(XMLTV_PATH)
        addon_path = ADDON.getAddonInfo('path')
        skin_xml = os.path.join(addon_path, 'resources', 'skins', 'default', '720p', 'tuepg.guide.experimental.xml')
        if not os.path.exists(skin_xml):
            raise Exception(f"EPG skin XML not found at {skin_xml}")
        xml_file = 'tuepg.guide.experimental.xml'
        xbmc.sleep(100)
        window = EPGGrid(xml_file, addon_path, channels=favorites, programs=programs)
        window.is_favorites_view = True
        window.doModal()
        del window
        
    except Exception as e:
        xbmcgui.Dialog().ok("Error", f"Failed to load favorites grid: {str(e)}")

def add_context_menu_items(list_item, channel):
    """Add standard context menu items to a list item"""
    context_menu = []
    guide_url = f"{BASE_URL}?action=show_channel&id={urllib.parse.quote(channel['tvg_id'])}"
    context_menu.append(('Show Guide', f'Container.Update({guide_url})'))
    
    # Add Stop YouTube Playlist option for all channels (will work if YouTube is playing)
    stop_youtube_action = f"{BASE_URL}?action=stop_youtube_playlist"
    context_menu.append(('Stop YouTube Playlist', f'RunPlugin({stop_youtube_action})'))
    
    if favorites_manager.is_favorite(channel['tvg_id']):
        remove_action = f"{BASE_URL}?action=remove_favorite&id={urllib.parse.quote(channel['tvg_id'])}"
        context_menu.append(('Remove from Favorites', f'RunPlugin({remove_action})'))
    else:
        add_action = f"{BASE_URL}?action=add_favorite&id={urllib.parse.quote(channel['tvg_id'])}"
        context_menu.append(('Add to Favorites', f'RunPlugin({add_action})'))

    list_item.addContextMenuItems(context_menu)

def test_directory(handle):
    """Test directory to verify UI rendering"""
    test_item1 = xbmcgui.ListItem("[COLOR green]Simple Test Item[/COLOR]")
    xbmcplugin.addDirectoryItem(handle, "", test_item1, False)
    
    test_item2 = xbmcgui.ListItem("[COLOR blue]Test Item with URL[/COLOR]")
    test_url = f"{BASE_URL}?action=test_play"
    xbmcplugin.addDirectoryItem(handle, test_url, test_item2, False)
    
    test_item3 = xbmcgui.ListItem("[COLOR yellow]Test Video Item[/COLOR]")
    info_tag = test_item3.getVideoInfoTag()
    info_tag.setTitle("Test Video")
    info_tag.setPlot("This is a test video item")
    test_url = f"{BASE_URL}?action=test_play"
    xbmcplugin.addDirectoryItem(handle, test_url, test_item3, False)
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)
    
def return_to_buttons():
    """Helper to return to ten buttons window"""
    xbmc.executebuiltin('ActivateWindow(13002)')

def search_channels_and_programs(handle):
    """Search through channels and programs"""
    progress = None
    try:
        keyboard = xbmc.Keyboard('', 'Search')
        keyboard.doModal()
        if not keyboard.isConfirmed():
            xbmcplugin.endOfDirectory(handle, succeeded=False)
            return_to_buttons()
            return
            
        search_term = keyboard.getText().lower().strip()
        if not search_term:
            xbmcplugin.endOfDirectory(handle, succeeded=False)
            return_to_buttons()
            return
            
        progress = xbmcgui.DialogProgress()
        progress.create('Searching', 'Loading data...')
        
        channels = parse_m3u8(M3U8_PATH)
        programs = parse_xmltv(XMLTV_PATH)
        current_time = datetime.now().astimezone()
        
        progress.update(25, 'Indexing programs...')
        channel_programs = {}
        for program in programs:
            if program['stop'] >= current_time:
                channel_id = program['channel']
                if channel_id not in channel_programs:
                    channel_programs[channel_id] = []
                channel_programs[channel_id].append(program)
        
        progress.update(50, 'Searching...')
        found_channels = []
        found_programs = []
        
        for channel in channels:
            if progress.iscanceled():
                xbmcplugin.endOfDirectory(handle, succeeded=False)
                return_to_buttons()
                return
                
            if search_term in channel['name'].lower():
                found_channels.append(channel)
            
            channel_id = channel['tvg_id']
            if channel_id in channel_programs:
                for program in channel_programs[channel_id]:
                    if search_term in program['title'].lower():
                        found_programs.append({
                            'program': program,
                            'channel': channel
                        })
        
        progress.update(75, 'Displaying results...')
        header = xbmcgui.ListItem(f'[COLOR gold]Search Results for "{search_term}"[/COLOR]')
        xbmcplugin.addDirectoryItem(handle, '', header, False)
        if found_channels:
            section = xbmcgui.ListItem(f'[COLOR yellow]Matching Channels ({len(found_channels)})[/COLOR]')
            xbmcplugin.addDirectoryItem(handle, '', section, False)
            for channel in found_channels:
                name = f"[COLOR yellow]► {channel['name']}[/COLOR]"
                item = xbmcgui.ListItem(name)
                item.setArt({'icon': channel['logo'], 'thumb': channel['logo']})
                add_context_menu_items(item, channel)
                url = f"{BASE_URL}?action=play_channel&id={urllib.parse.quote(channel['tvg_id'])}"
                xbmcplugin.addDirectoryItem(handle, url, item, False)
        
        if found_programs:
            if found_channels:
                separator = xbmcgui.ListItem('[COLOR blue]════════════════════[/COLOR]')
                xbmcplugin.addDirectoryItem(handle, '', separator, False)
            section = xbmcgui.ListItem(f'[COLOR lime]Matching Programs ({len(found_programs)})[/COLOR]')
            xbmcplugin.addDirectoryItem(handle, '', section, False)
            for item in found_programs:
                program = item['program']
                channel = item['channel']
                start_time = program['start'].strftime('%H:%M')
                name = f"    {start_time} - {program['title']} ({channel['name']})"
                list_item = xbmcgui.ListItem(name)
                list_item.setArt({'icon': channel['logo'], 'thumb': channel['logo']})
                list_item.getVideoInfoTag().setTitle(program['title'])
                list_item.getVideoInfoTag().setPlot(program.get('desc', ''))
                add_context_menu_items(list_item, channel)
                url = f"{BASE_URL}?action=play_channel&id={urllib.parse.quote(channel['tvg_id'])}"
                xbmcplugin.addDirectoryItem(handle, url, list_item, False)
        if not found_channels and not found_programs:
            msg = xbmcgui.ListItem('[COLOR red]No matches found[/COLOR]')
            xbmcplugin.addDirectoryItem(handle, '', msg, False)
        
        xbmcplugin.endOfDirectory(handle, succeeded=True)
    except Exception as e:
        xbmcgui.Dialog().notification('Search Error', 'Failed to complete search', xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(handle, succeeded=False)
    
    finally:
        if progress:
            try:
                progress.close()
            except:
                pass

def show_main_menu():
    """Show the main menu organized by channel groups"""
    try:
        channels = parse_m3u8(M3U8_PATH)
        search_item = xbmcgui.ListItem("[COLOR lime]Search Channels & Programs[/COLOR]")
        search_url = f"{BASE_URL}?action=search"
        xbmcplugin.addDirectoryItem(HANDLE, search_url, search_item, True)
        # Add Sports Grid Items
        sports_header = xbmcgui.ListItem("[COLOR orange]===== Sports Grids =====[/COLOR]")
        xbmcplugin.addDirectoryItem(HANDLE, "", sports_header, False)
        
        sports = [
            ("MLB", "mlb"),
            ("NBA", "nba"),
            ("WNBA", "wnba"),
            ("NHL", "nhl"),
            ("NFL", "nfl")
        ]
        
        for name, sport in sports:
            sports_item = xbmcgui.ListItem(f"[COLOR orange]{name} Grid View[/COLOR]")
            sports_url = f"{BASE_URL}?action=sports_grid&sport={sport}"
            xbmcplugin.addDirectoryItem(HANDLE, sports_url, sports_item, False)
        
        sports_separator = xbmcgui.ListItem("[COLOR orange]==================[/COLOR]")
        xbmcplugin.addDirectoryItem(HANDLE, "", sports_separator, False)
        test_item = xbmcgui.ListItem("[COLOR red]Test Directory[/COLOR]")
        test_url = f"{BASE_URL}?action=test_directory&handle={HANDLE}"
        xbmcplugin.addDirectoryItem(HANDLE, test_url, test_item, True)
        
        settings_item = xbmcgui.ListItem("[COLOR lime]Settings[/COLOR]")
        settings_url = f"{BASE_URL}?action=settings"
        xbmcplugin.addDirectoryItem(HANDLE, settings_url, settings_item, False)
        
        epg_item = xbmcgui.ListItem("[COLOR yellow]EPG Grid View[/COLOR]")
        epg_url = f"{BASE_URL}?action=epg_grid"
        xbmcplugin.addDirectoryItem(HANDLE, epg_url, epg_item, False)
        
        favorites_item = xbmcgui.ListItem("[COLOR gold]Favorite Channels[/COLOR]")
        favorites_url = f"{BASE_URL}?action=show_favorites"
        xbmcplugin.addDirectoryItem(HANDLE, favorites_url, favorites_item, True)
        
        if last_watched_manager.load_last_watched():
            last_watched_item = xbmcgui.ListItem("[COLOR skyblue]Last Watched Channels[/COLOR]")
            last_watched_url = f"{BASE_URL}?action=show_last_watched"
            xbmcplugin.addDirectoryItem(HANDLE, last_watched_url, last_watched_item, True)
            
            clear_item = xbmcgui.ListItem("[COLOR red]Clear Last Watched History[/COLOR]")
            clear_url = f"{BASE_URL}?action=clear_last_watched"
            xbmcplugin.addDirectoryItem(HANDLE, clear_url, clear_item, False)
        else:
            disabled_item = xbmcgui.ListItem("[COLOR gray]Last Watched Channels (None)[/COLOR]")
            xbmcplugin.addDirectoryItem(HANDLE, "", disabled_item, False)
        
        sports_item = xbmcgui.ListItem("[COLOR orange]Sports Events[/COLOR]")
        sports_url = f"{BASE_URL}?action=show_sports"
        xbmcplugin.addDirectoryItem(HANDLE, sports_url, sports_item, False)
        
        ten_buttons_item = xbmcgui.ListItem("[COLOR cyan]Ten Buttons Interface[/COLOR]")
        ten_buttons_url = f"{BASE_URL}?action=show_ten_buttons"
        xbmcplugin.addDirectoryItem(HANDLE, ten_buttons_url, ten_buttons_item, False)
        
        channels_item = xbmcgui.ListItem("[COLOR yellow]All Channel Listings[/COLOR]")
        channels_url = f"{BASE_URL}?action=show_listings"
        xbmcplugin.addDirectoryItem(HANDLE, channels_url, channels_item, True)

        m3u8_url_2 = ADDON.getSetting('m3u8_url_2')
        if m3u8_url_2:
            active_guide = get_active_guide()
            guide_switch_item = xbmcgui.ListItem(f"[COLOR lime]Switch to Guide {1 if active_guide == 2 else 2}[/COLOR]")
            guide_switch_url = f"{BASE_URL}?action=switch_guide"
            xbmcplugin.addDirectoryItem(HANDLE, guide_switch_url, guide_switch_item, False)
        
        clear_cache_item = xbmcgui.ListItem("[COLOR red]Clear Cache[/COLOR]")
        clear_cache_url = f"{BASE_URL}?action=clear_cache"
        xbmcplugin.addDirectoryItem(HANDLE, clear_cache_url, clear_cache_item, False)
        xbmcplugin.endOfDirectory(HANDLE)
    
    except Exception as e:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)

def show_group(group_id):
    """Show channels for a specific group"""
    try:
        channels = parse_m3u8(M3U8_PATH)
        group_channels = [c for c in channels if c.get('group') == group_id]
        
        for channel in group_channels:
            name = channel['name']
            if favorites_manager.is_favorite(channel['tvg_id']):
                name = f"[COLOR gold]★[/COLOR] {name}"
            
            list_item = xbmcgui.ListItem(name)
            list_item.setArt({'icon': channel['logo']})
            
            if favorites_manager.is_favorite(channel['tvg_id']):
                remove_action = f"{BASE_URL}?action=remove_favorite&id={urllib.parse.quote(channel['tvg_id'])}"
                list_item.addContextMenuItems([('Remove from Favorites', f'RunPlugin({remove_action})')])
            else:
                add_action = f"{BASE_URL}?action=add_favorite&id={urllib.parse.quote(channel['tvg_id'])}"
                list_item.addContextMenuItems([('Add to addon Favorites', f'RunPlugin({add_action})')])
            
            url = f"{BASE_URL}?action=show_channel&id={urllib.parse.quote(channel['tvg_id'])}"
            xbmcplugin.addDirectoryItem(HANDLE, url, list_item, True)
            
        xbmcplugin.endOfDirectory(HANDLE)
        
    except Exception as e:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)

def show_channel(channel_id):
    """Show programs for a channel"""
    try:
        if channel_id.startswith('sports_'):
            channels, _ = parse_sports_json(ADDON.getSetting('sports_url'))
            channel = next((c for c in channels if c['tvg_id'] == channel_id), None)
            if not channel:
                raise ValueError(f"Sports event {channel_id} not found")
                
            if 'all_links' in channel and channel['all_links']:
                stream_names = channel.get('stream_names', [])
                dialog = xbmcgui.Dialog()
                choice = dialog.select('Choose Stream', stream_names)
                
                if choice >= 0:
                    url = channel['all_links'][choice]
                    if '(' in url:
                        url = url[:url.rindex('(')]
                    list_item = xbmcgui.ListItem(channel['name'])
                    list_item.setPath(url)
                    xbmc.Player().play(url, list_item)
            return
            
        channels = parse_m3u8(M3U8_PATH)
        programs = parse_xmltv(XMLTV_PATH)
        channel = next((c for c in channels if c['tvg_id'] == channel_id), None)
        if not channel:
            raise ValueError(f"Channel {channel_id} not found")
            
        normalized_id = normalize_id(channel_id)
        now = datetime.now().astimezone()
        
        current_program = None
        upcoming_programs = []
        
        for program in programs:
            if normalize_id(program['channel']) != normalized_id:
                continue
                
            if program['start'] <= now <= program['stop']:
                current_program = program
            elif program['start'] > now:
                upcoming_programs.append(program)
                if len(upcoming_programs) >= 5:
                    break
        
        if current_program:
            time_str = f"{current_program['start'].strftime('%H:%M')} - {current_program['stop'].strftime('%H:%M')}"
            title = f"{time_str}: [COLOR yellow]{current_program['title']}[/COLOR] [COLOR lime](Now)[/COLOR]"
            list_item = xbmcgui.ListItem(title)
            xbmcplugin.addDirectoryItem(HANDLE, channel['url'], list_item, False)
        
        today = now.date()
        for program in upcoming_programs:
            time_str = f"{program['start'].strftime('%H:%M')} - {program['stop'].strftime('%H:%M')}"
            if program['start'].date() > today:
                time_str = f"[Tomorrow] {time_str}"
            title = f"{time_str}: {program['title']}"
            list_item = xbmcgui.ListItem(title)
            xbmcplugin.addDirectoryItem(HANDLE, channel['url'], list_item, False)
        
        xbmcplugin.endOfDirectory(HANDLE)
        
    except Exception as e:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)

def show_last_watched():
    try:
        last_watched = last_watched_manager.load_last_watched()
        if not last_watched:
            no_channels = xbmcgui.ListItem("[COLOR red]No recently watched channels[/COLOR]")
            xbmcplugin.addDirectoryItem(HANDLE, "", no_channels, False)
            xbmcplugin.endOfDirectory(HANDLE, succeeded=True)
            xbmcgui.Dialog().notification('Last Watched', 'No recently watched channels', xbmcgui.NOTIFICATION_INFO, 2000)
            return
        
        for channel in last_watched:
            name = channel.get('name', 'Unknown Channel')
            list_item = xbmcgui.ListItem(name)
            list_item.setArt({'icon': channel.get('logo', '')})
            
            context_menu = []
            if favorites_manager.is_favorite(channel['tvg_id']):
                remove_action = f"{BASE_URL}?action=remove_favorite&id={urllib.parse.quote(channel['tvg_id'])}"
                context_menu.append(('Remove from Favorites', f'RunPlugin({remove_action})'))
            else:
                add_action = f"{BASE_URL}?action=add_favorite&id={urllib.parse.quote(channel['tvg_id'])}"
                list_item.addContextMenuItems([('Add to Favorites', f'RunPlugin({add_action})')])
            
            url = f"{BASE_URL}?action=play_channel&id={urllib.parse.quote(channel['tvg_id'])}"
            xbmcplugin.addDirectoryItem(HANDLE, url, list_item, False)
        
        xbmcplugin.setContent(HANDLE, 'videos')
        xbmcplugin.endOfDirectory(HANDLE, succeeded=True, cacheToDisc=False)
        
    except Exception as e:
        xbmcgui.Dialog().ok("Error", f"Failed to show last watched: {str(e)}")
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)

def switch_guide():
    """Switch between Guide 1 and Guide 2"""
    try:
        current_guide = get_active_guide()
        new_guide = 2 if current_guide == 1 else 1
        m3u8_url, xmltv_url = get_url_settings(new_guide)
        if not m3u8_url or not xmltv_url:
            xbmcgui.Dialog().ok("Error", f"Guide {new_guide} is not configured. Please set up the URLs in settings first.")
            return
        
        # Clear cache for new guide
        clear_cache(new_guide)
        set_active_guide(new_guide)
        global M3U8_PATH, XMLTV_PATH
        M3U8_PATH, XMLTV_PATH = m3u8_url, xmltv_url
        
        xbmc.executebuiltin('Container.Refresh')
        xbmcgui.Dialog().notification('TV Guide', f'Switched to Guide {new_guide}', xbmcgui.NOTIFICATION_INFO, 2000)
        
    except Exception as e:
        xbmcgui.Dialog().ok("Error", f"Failed to switch guide: {str(e)}")

def play_channel(channel_id):
    try:
        channels = parse_m3u8(M3U8_PATH)
        channel = next((c for c in channels if c['tvg_id'] == channel_id), None)
        
        if not channel:
            # Check if it's a YouTube channel using the new cleaner approach
            from youtube_guide import fetch_links, fetch_json_content, youtube_json_to_epggrid
            import urllib.parse

            json_dir = "https://magnetic.website/JET_GUIDE/YOUTUBE/genres/"
            youtube_channel = None
            youtube_programs = []
            
            try:
                xbmc.log(f"DEBUG: Searching for channel '{channel_id}' in remote JSON files", xbmc.LOGINFO)
                xbmc.log(f"DEBUG: Using json_dir: {json_dir}", xbmc.LOGINFO)
                
                # Fetch top-level genres
                dirs, _ = fetch_links(json_dir)
                xbmc.log(f"DEBUG: Found {len(dirs)} genre directories", xbmc.LOGINFO)
                
                for href, genre_name in dirs:
                    if youtube_channel:
                        break
                    
                    xbmc.log(f"DEBUG: Checking genre: {genre_name}", xbmc.LOGINFO)
                    xbmc.log(f"DEBUG: href={href}, json_dir={json_dir}", xbmc.LOGINFO)
                    genre_url = urllib.parse.urljoin(json_dir, href + '/')
                    xbmc.log(f"DEBUG: Constructed genre_url={genre_url}", xbmc.LOGINFO)
                    _, file_links = fetch_links(genre_url)
                    
                    for fhref, fname in file_links:
                        json_url = urllib.parse.urljoin(genre_url, fhref)
                        json_data = fetch_json_content(json_url)
                        
                        if json_data:
                            try:
                                # Extract channel name from filename (remove .json extension)
                                channel_name = fname.replace('.json', '') if fname.endswith('.json') else fname
                                ch, pr = youtube_json_to_epggrid(json_data, channel_name)  # Pass dict directly
                                
                                if ch and ch[0]['tvg_id'] == channel_id:
                                    xbmc.log(f"DEBUG: Found matching channel: {channel_id} in {fname}", xbmc.LOGINFO)
                                    youtube_channel = ch[0]
                                    youtube_programs = pr
                                    break
                                else:
                                    if ch:
                                        xbmc.log(f"DEBUG: Channel ID mismatch in {fname}. Looking for: {channel_id}, found: {ch[0].get('tvg_id', 'No ID')}", xbmc.LOGINFO)
                                        
                            except Exception as e:
                                xbmc.log(f"DEBUG: Failed to parse data from {json_url}: {str(e)}", xbmc.LOGERROR)
                        else:
                            xbmc.log(f"DEBUG: Skipped {json_url} (fetch failed)", xbmc.LOGWARNING)
                            
            except Exception as e:
                xbmc.log(f"Error fetching remote JSON files: {str(e)}", xbmc.LOGERROR)
            
            if youtube_channel:
                # Play YouTube playlist sequentially
                try:
                    # First, cancel any existing YouTube playback to prevent conflicts
                    from youtube_guide import cancel_youtube_playback, play_youtube_programs
                    debug_log("DEBUG: Cancelling any existing YouTube playback before starting new one", xbmc.LOGINFO)
                    cancel_youtube_playback()
                    
                    # Give a longer delay to allow cleanup and prevent conflicts
                    xbmc.sleep(2000)
                    
                    # Also try to stop any player that might still be running
                    try:
                        player = xbmc.Player()
                        if player.isPlaying():
                            debug_log("DEBUG: Force stopping player before new YouTube playlist", xbmc.LOGINFO)
                            player.stop()
                            xbmc.sleep(1000)
                    except:
                        pass
                    
                    debug_log(f"DEBUG: About to call play_youtube_programs with {len(youtube_programs)} programs", xbmc.LOGINFO)
                    play_youtube_programs(youtube_programs)  # Remove delay argument to match function signature
                    return
                except Exception as e:
                    debug_log(f"DEBUG: Error in play_youtube_programs: {str(e)}", xbmc.LOGERROR)
                    xbmcgui.Dialog().ok("Playback Error", f"Failed to start YouTube playback: {str(e)}")
                    return
            else:
                xbmcgui.Dialog().ok('Error', 'Channel not found')
                return
            
        channel_data = {
            'name': channel.get('name', 'Unknown'),
            'tvg_id': channel.get('tvg_id', ''),
            'url': channel.get('url', ''),
            'logo': channel.get('logo', ''),
            'group': channel.get('group', '')
        }
        try:
            last_watched_manager.add_last_watched(channel_data)
        except Exception as e:
            xbmcgui.Dialog().notification('Last Watched Error', f'Failed to save channel: {str(e)}', xbmcgui.NOTIFICATION_ERROR, 3000)
        
        url = channel.get('url', '')
        name = channel.get('name', '')
        
        if not url:
            xbmcgui.Dialog().ok('Error', 'No valid URL found for channel')
            return
        
        if '|' in url:
            streams = url.split('|')
            stream_names = []
            for stream in streams:
                if '(' in stream and ')' in stream:
                    stream_name = stream[stream.rindex('(')+1:stream.rindex(')')]
                    stream_names.append(stream_name)
                else:
                    stream_names.append(f"Stream {len(stream_names)+1}")
            
            dialog = xbmcgui.Dialog()
            choice = dialog.select('Choose Stream', stream_names)
            
            if choice >= 0:
                url = streams[choice].strip()
                if '(' in url:
                    url = url[:url.rindex('(')].strip()
            else:
                return
        
        list_item = xbmcgui.ListItem(name)
        list_item.setInfo('video', {'Title': name})
        list_item.setArt({'icon': channel.get('logo', '')})
        
        # Cancel any running YouTube sequential playback before playing new content
        try:
            from youtube_guide import cancel_youtube_playback
            cancel_youtube_playback()
        except ImportError:
            pass  # youtube_guide not available
        
        xbmc.Player().play(item=url, listitem=list_item)
        
    except Exception as e:
        xbmcgui.Dialog().ok("Error", f"Failed to play channel: {str(e)}")

def show_sports_grid(sport):
    """Show sports grid view for the specified sport"""
def show_last_watched(handle=None):
    """Show last watched channels"""
    try:
        if handle is not None and handle > 0:
            channels = last_watched_manager.load_last_watched()
            if not channels:
                xbmcgui.Dialog().ok("TV Guide", "No recently watched channels")
                xbmcplugin.endOfDirectory(handle, succeeded=False)
                return
            # Add channels as playable items
            for channel in channels:
                name = channel.get('name', 'Unknown')
                item = xbmcgui.ListItem(name)
                item.setArt({'icon': channel.get('logo', '')})
                # Add context menu
                context_menu = []
                if channel.get('tvg_id'):
                    guide_url = f"{BASE_URL}?action=show_channel&id={urllib.parse.quote(channel['tvg_id'])}"
                    context_menu.append(('Show Guide', f'Container.Update({guide_url})'))
                item.addContextMenuItems(context_menu)
                url = f"{BASE_URL}?action=play_channel&id={urllib.parse.quote(channel['tvg_id'])}"
                xbmcplugin.addDirectoryItem(handle, url, item, isFolder=False)
            xbmcplugin.endOfDirectory(handle)
            return

    except Exception as e:
        if handle is not None and handle > 0:
            xbmcplugin.endOfDirectory(handle, succeeded=False)
        xbmcgui.Dialog().ok("Error", f"Failed to show last watched: {str(e)}")

def show_favorites(handle=None):
    """Show favorites directory or EPG grid"""
    try:
        if handle is not None and handle > 0:
            from favorites import favorites_manager
            channels = parse_m3u8(M3U8_PATH)
            favorite_channels = [c for c in channels if favorites_manager.is_favorite(c['tvg_id'])]
            
            if not favorite_channels:
                xbmcgui.Dialog().ok("TV Guide", "No favorite channels added yet")
                xbmcplugin.endOfDirectory(handle, succeeded=False)
                return
            # Add guide view option first
            guide = xbmcgui.ListItem("[COLOR yellow]► Open EPG View[/COLOR]")
            guide.setProperty('IsPlayable', 'false')
            guide_url = f"{BASE_URL}?action=show_favorites_epg"
            xbmcplugin.addDirectoryItem(handle, guide_url, guide, isFolder=True)
            # Add channels as playable items
            for channel in favorite_channels:
                name = channel['name']
                item = xbmcgui.ListItem(name)
                item.setArt({'icon': channel.get('logo', '')})
                # Add context menu
                context_menu = []
                guide_url = f"{BASE_URL}?action=show_channel&id={urllib.parse.quote(channel['tvg_id'])}"
                context_menu.append(('Show Guide', f'Container.Update({guide_url})'))
                remove_url = f"{BASE_URL}?action=remove_favorite&id={urllib.parse.quote(channel['tvg_id'])}"
                context_menu.append(('Remove from Favorites', f'RunPlugin({remove_url})'))
                item.addContextMenuItems(context_menu)
                url = f"{BASE_URL}?action=play_channel&id={urllib.parse.quote(channel['tvg_id'])}"
                xbmcplugin.addDirectoryItem(handle, url, item, isFolder=False)
            
            xbmcplugin.endOfDirectory(handle)
            return
            
        # Called from Button 5 - show EPG grid directly
        show_favorites_epg()

    except Exception as e:
        if handle is not None and handle > 0:
            xbmcplugin.endOfDirectory(handle, succeeded=False)
        xbmcgui.Dialog().ok("Error", f"Failed to show favorites: {str(e)}")

def show_favorites_epg():
    """Show favorites in EPG grid"""
    try:
        from favorites import favorites_manager
        from epggrid import EPGGrid
        # Close any active dialogs first
        xbmc.executebuiltin('Dialog.Close(all)')
        xbmc.sleep(200)
        # Get channels and programs
        channels = parse_m3u8(M3U8_PATH)
        programs = parse_xmltv(XMLTV_PATH)
        favorite_channels = [c for c in channels if favorites_manager.is_favorite(c['tvg_id'])]
        if not favorite_channels:
            xbmcgui.Dialog().ok("TV Guide", "No favorite channels added yet")
            return

        favorite_channel_ids = [c['tvg_id'] for c in favorite_channels]
        favorite_programs = [p for p in programs if p['channel'] in favorite_channel_ids]
        # Show EPG grid
        addon_path = ADDON.getAddonInfo('path')
        epg_window = EPGGrid('tuepg.guide.experimental.xml', addon_path,
                          channels=favorite_channels,
                          programs=favorite_programs)
        epg_window.doModal()
        del epg_window
            
    except Exception as e:
        xbmcgui.Dialog().ok("Error", f"Failed to show favorites: {str(e)}")

def show_sports_grid(sport):
    """Show sports grid view for the specified sport"""
    try:
        xbmc.executebuiltin('Dialog.Close(all)')
        xbmc.sleep(200)
        from sportsgrid import SportsGrid
        addon_path = ADDON.getAddonInfo('path')
        skin_xml = os.path.join(addon_path, 'resources', 'skins', 'default', '720p', 'sports.guide.xml')
        if not os.path.exists(skin_xml):
            raise Exception(f"Sports grid skin XML not found at {skin_xml}")
        
        xml_file = 'sports.guide.xml'
        window = SportsGrid(xml_file, addon_path, sport=sport)
        window.doModal()
        del window
        
    except Exception as e:
        xbmcgui.Dialog().ok("Error", f"Failed to load sports grid: {str(e)}")

def show_youtube_guide():
    from youtube_guide import fetch_links, fetch_json_content, youtube_json_to_epggrid
    from epggrid import EPGGrid
    import urllib.parse

    # Try loading from cache first
    cached_channels, cached_programs, cache_time = load_youtube_cache(YOUTUBE_CACHE_FILE, YOUTUBE_CACHE_TIME_FILE)
    if cached_channels and cached_programs:
        debug_log(f"DEBUG: Using cached YouTube data, channels: {len(cached_channels)}, programs: {len(cached_programs)}", xbmc.LOGINFO)
        channels, programs = cached_channels, cached_programs
    else:
        debug_log("DEBUG: No valid cache found, fetching fresh YouTube data", xbmc.LOGINFO)
        json_dir = "https://magnetic.website/JET_GUIDE/YOUTUBE/genres/"
        debug_log(f"DEBUG: Using json_dir for caching: {json_dir}", xbmc.LOGINFO)
        channels = []
        programs = []
        
        try:
            # Fetch top-level genres
            dirs, _ = fetch_links(json_dir)
            debug_log(f"DEBUG: Found {len(dirs)} genre directories for YouTube guide", xbmc.LOGINFO)
            
            for href, genre_name in dirs:
                debug_log(f"DEBUG: Processing genre: {genre_name}", xbmc.LOGINFO)
                genre_url = urllib.parse.urljoin(json_dir, href + '/')
                _, file_links = fetch_links(genre_url)
                
                for fhref, fname in file_links:
                    json_url = urllib.parse.urljoin(genre_url, fhref)
                    json_data = fetch_json_content(json_url)
                    
                    if json_data:
                        try:
                            # Extract channel name from filename (remove .json extension)
                            channel_name = fname.replace('.json', '') if fname.endswith('.json') else fname
                            ch, pr = youtube_json_to_epggrid(json_data, channel_name)  # Pass dict directly
                            channels.extend(ch)
                            programs.extend(pr)
                            debug_log(f"DEBUG: Added channel {ch[0]['name'] if ch else 'Unknown'} with {len(pr)} programs from {fname}", xbmc.LOGINFO)
                        except Exception as e:
                            debug_log(f"DEBUG: Failed to parse data from {json_url}: {str(e)}", xbmc.LOGERROR)
                    else:
                        debug_log(f"DEBUG: Skipped {json_url} (fetch failed)", xbmc.LOGWARNING)
                        
            # Save to cache after successful fetch
            if channels and programs:
                save_youtube_cache(channels, programs, YOUTUBE_CACHE_FILE, YOUTUBE_CACHE_TIME_FILE)
                debug_log(f"DEBUG: Saved YouTube cache with {len(channels)} channels and {len(programs)} programs", xbmc.LOGINFO)
                        
        except Exception as e:
            debug_log(f"ERROR: Failed to fetch YouTube guide data: {str(e)}", xbmc.LOGERROR)
            xbmcgui.Dialog().ok("Error", f"Failed to load YouTube guide: {str(e)}")
            return
    
    debug_log(f"DEBUG: Total YouTube channels: {len(channels)}, Total programs: {len(programs)}", xbmc.LOGINFO)
    for i, channel in enumerate(channels):
        channel_programs = [p for p in programs if p['channel'] == channel['tvg_id']]
        debug_log(f"DEBUG: Channel {i}: {channel['name']} ({channel['tvg_id']}) has {len(channel_programs)} programs", xbmc.LOGINFO)
    
    # Launch EPGGrid window with YouTube channels/programs
    addon_path = xbmcaddon.Addon().getAddonInfo('path')
    win = EPGGrid('tuepg.guide.experimental.xml', addon_path, channels=channels, programs=programs)
    win.doModal()


def main():
    params = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
    action = params.get('action', '')
    try:
        handle = int(params.get('handle', sys.argv[1]))
    except (IndexError, ValueError):
        handle = 0
    if handle < 0:
        handle = 0
    if action == 'show_youtube_guide':
        show_youtube_guide()
    elif action == 'test_directory':
        test_directory(handle)
    elif action == 'show_last_watched':
        show_last_watched(handle)
    if action == 'live_score_alerts':
        import livescore_alerts
        livescore_alerts.main()

    elif action == 'search':
        search_channels_and_programs(handle)
    elif action == 'show_favorites':
        show_favorites(handle)
    elif action == 'show_favorites_epg':
        show_favorites_epg()
    elif action == 'remove_favorite':
        from favorites import favorites_manager
        channel_id = params.get('id')
        if channel_id and favorites_manager.remove_favorite(channel_id):
            xbmcgui.Dialog().notification('TV Guide', 'Channel removed from favorites')
            xbmc.executebuiltin('Container.Refresh')
    elif action == 'add_favorite':
        from favorites import favorites_manager
        channel_id = params.get('id')
        if channel_id and favorites_manager.add_favorite(channel_id):
            xbmcgui.Dialog().notification('TV Guide', 'Channel added to favorites')
    elif action == 'sports_grid':
        show_sports_grid(params.get('sport'))
    elif action == 'test_play':
        item = xbmcgui.ListItem("Test Playback")
        xbmcplugin.setResolvedUrl(handle, True, item)
    elif action == 'play_channel':
        play_channel(params.get('id'))
    elif action == 'settings':
        ADDON.openSettings()
    elif action == 'show_channel':
        show_channel(params['id'])
    elif action == 'show_group':
        show_group(params.get('group', ''))
    elif action == 'switch_guide':
        switch_guide()
    elif action == 'show_favorites':
        show_favorites()
    elif action == 'show_sports':
        show_sports_guide()
    elif action == 'show_ten_buttons':
        from tenbuttons import show_ten_buttons
        show_ten_buttons()
    elif action == 'show_last_watched':
        show_last_watched()
    elif action == 'clear_last_watched':
        last_watched_manager.clear_history()
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'add_favorite':
        channel_id = params.get('id')
        channels = parse_m3u8(M3U8_PATH)
        channel = next((c for c in channels if c['tvg_id'] == channel_id), None)
        if channel:
            if favorites_manager.add_favorite(channel):
                xbmcgui.Dialog().notification('Favorites', f'Added {channel["name"]} to favorites', xbmcgui.NOTIFICATION_INFO, 2000)
            else:
                xbmcgui.Dialog().notification('Favorites', 'Channel already in favorites', xbmcgui.NOTIFICATION_INFO, 2000)
    elif action == 'remove_favorite':
        channel_id = params.get('id')
        favorites_manager.remove_favorite(channel_id)
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'show_ten_buttons':
        from tenbuttons import show_ten_buttons
        show_ten_buttons()
        return
        
    elif action == 'epg_grid':
        try:
            xbmc.executebuiltin('Dialog.Close(all)')
            xbmc.sleep(200)
            # Show progress dialog
            progress = xbmcgui.DialogProgress()
            progress.create('Loading TV Guide', 'Loading channel data...This may take a moment on first run')
            progress.update(0)
            from epggrid import EPGGrid
            # Load channels
            channels = parse_m3u8(M3U8_PATH)
            progress.update(33, 'Loading program data...This may take a moment on first run')
            # Load programs
            programs = parse_xmltv(XMLTV_PATH)
            progress.update(66, 'Preparing guide...')
            addon_path = ADDON.getAddonInfo('path')
            skin_base = os.path.join(addon_path, 'resources', 'skins', 'default')
            resolution = '720p'
            skin_xml = os.path.join(skin_base, resolution, 'tuepg.guide.experimental.xml')
            if not os.path.exists(skin_xml):
                raise Exception(f"EPG skin XML not found at {skin_xml}")

            xml_file = 'tuepg.guide.experimental.xml'
            xbmc.sleep(100)
            try:
                import shutil
                media_paths = {
                    'source': [
                        os.path.join(addon_path, 'resources', 'media'),
                        os.path.join(addon_path, 'resources', 'skins', 'default', 'media'),
                        os.path.join(addon_path, 'resources', 'skins', 'default', '720p', 'media')
                    ],
                    'dest': [
                        os.path.join(addon_path, 'resources', 'skins', 'default', '720p', 'media'),
                        os.path.join(addon_path, 'resources', 'media')
                    ]
                }
                for dest in media_paths['dest']:
                    os.makedirs(dest, exist_ok=True)
                    
                required_files = [
                    {'file': 'Background.png', 'desc': 'EPG background', 'required': True},
                    {'file': 'ButtonFocus.png', 'desc': 'Button highlight', 'required': True},
                    {'file': 'Panel.png', 'desc': 'Info panel', 'required': True},
                    {'file': 'white.png', 'desc': 'Scrollbar texture', 'required': True}
                ]
                
                for item in required_files:
                    found = False
                    for src in media_paths['source']:
                        src_file = os.path.join(src, item['file'])
                        if os.path.exists(src_file):
                            for dst in media_paths['dest']:
                                dst_file = os.path.join(dst, item['file'])
                                if not os.path.exists(dst_file):
                                    shutil.copy2(src_file, dst_file)
                            found = True
                            break
                            
                    if not found and item['required']:
                        raise Exception(f"Required media file missing: {item['file']} ({item['desc']})")
                # Create and show EPG window
                window = EPGGrid(xml_file, addon_path, channels=channels, programs=programs)
                progress.update(100)
                progress.close()
                
                window.doModal()
                del window
                
            except Exception as e:
                progress.close()
                error_msg = f"EPG Error: {str(e)}"
                xbmcgui.Dialog().ok("EPG Error", error_msg)
                
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Failed to load EPG: {str(e)}")
    elif action == 'show_listings':
        show_channel_listings()
    elif action == 'stop_youtube_playlist':
        # Stop current YouTube playlist
        try:
            from youtube_guide import cancel_youtube_playback
            cancel_youtube_playback()
            xbmcgui.Dialog().notification("YouTube Playlist", "Playlist stopped", xbmcgui.NOTIFICATION_INFO, 2000)
        except Exception as e:
            debug_log(f"DEBUG: Error stopping YouTube playlist: {str(e)}", xbmc.LOGERROR)
    elif action == 'clear_cache':
        global M3U8_CACHE, XMLTV_CACHE, M3U8_CACHE_TIME, XMLTV_CACHE_TIME, SPORTS_CACHE, SPORTS_CACHE_TIME, DEBUG_LOG_FILE
        for cache_file in [M3U8_CACHE_FILE, XMLTV_CACHE_FILE, M3U8_CACHE_TIME_FILE, XMLTV_CACHE_TIME_FILE, SPORTS_CACHE_FILE, SPORTS_CACHE_TIME_FILE, YOUTUBE_CACHE_FILE, YOUTUBE_CACHE_TIME_FILE, DEBUG_LOG_FILE]:
            if xbmcvfs.exists(cache_file):
                xbmcvfs.delete(cache_file)
        # Delete Kodi log file using Kodi's log path
        log_path = xbmcvfs.translatePath('special://logpath/kodi.log')
        if xbmcvfs.exists(log_path):
            xbmcvfs.delete(log_path)
        M3U8_CACHE = None
        XMLTV_CACHE = None
        M3U8_CACHE_TIME = None
        XMLTV_CACHE_TIME = None
        SPORTS_CACHE = None
        SPORTS_CACHE_TIME = None
        DEBUG_LOG_FILE = None
        # Delete debug_log.txt in userdata folder
        debug_log_path = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.jet_guide/debug_log.txt')
        if xbmcvfs.exists(debug_log_path):
            xbmcvfs.delete(debug_log_path)
        # Try deleting debug_log.txt using special://userdata path
        debug_log_path_userdata = xbmcvfs.translatePath('special://userdata/addon_data/plugin.video.jet_guide/debug_log.txt')
        if xbmcvfs.exists(debug_log_path_userdata):
            xbmcvfs.delete(debug_log_path_userdata)
        xbmcgui.Dialog().notification('Cache', 'Cache cleared successfully', xbmcgui.NOTIFICATION_INFO, 2000)
        xbmc.executebuiltin('Container.Refresh')
    elif action == 'show_main':  # Handle main menu action
        show_main_menu()
        return
    else:  # Default to ten buttons interface
        try:
            # Always close any open dialogs
            xbmc.executebuiltin('Dialog.Close(all)')
            xbmc.sleep(200)
            # Show ten buttons interface
            from tenbuttons import show_ten_buttons
            show_ten_buttons()
            # If this was a directory request, end it
            if HANDLE > 0:
                xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Failed to start TV Guide: {str(e)}")

if __name__ == '__main__':
    main()
if __name__ == "__main__":
    url = sys.argv[0]
    handle = int(sys.argv[1])
    import urllib.parse
    params = dict(urllib.parse.parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 and sys.argv[2] else {}
    if not params or params.get("action") in ["open_guide", "show_main"]:
        li = xbmcgui.ListItem(label="Open TV Guide")
        xbmcplugin.addDirectoryItem(handle, url + "?action=open_guide", li, isFolder=True)
        xbmcplugin.endOfDirectory(handle)
    else:
        xbmcplugin.endOfDirectory(handle)