# youtube_guide.py
import json
import xbmc
import xbmcgui
import urllib.request
import urllib.parse
import os
import threading
from datetime import datetime, timedelta
from tools import debug_log

# Global variables for YouTube playlist management
_youtube_playback_cancelled = False
_current_youtube_playlist = []
_cancellation_lock = threading.Lock()
_cancellation_event = threading.Event()  # More reliable than flag checking

def cancel_youtube_playback():
    """Cancel any running YouTube sequential playback and stop all YouTube content"""
    global _youtube_playback_cancelled
    
    # Import xbmc at the top level to avoid scope issues
    try:
        import xbmc
        import xbmcgui
        
        # Use both flag and event for maximum reliability
        with _cancellation_lock:
            debug_log(f"DEBUG: cancel_youtube_playback called - setting flag from {_youtube_playback_cancelled} to True", xbmc.LOGINFO)
            _youtube_playback_cancelled = True
            _cancellation_event.set()  # Set the event for immediate notification
            debug_log("DEBUG: YouTube sequential playback cancelled - force stopping everything", xbmc.LOGINFO)
        
        # More aggressive stopping
        player = xbmc.Player()
        if player.isPlaying():
            try:
                playing_file = player.getPlayingFile()
                debug_log(f"DEBUG: Currently playing: {playing_file}", xbmc.LOGINFO)
                
                # Stop any content that might be YouTube related or just stop everything
                if playing_file and any(x in playing_file for x in ['youtube', 'plugin.video.youtube']):
                    debug_log("DEBUG: Stopping YouTube content", xbmc.LOGINFO)
                else:
                    debug_log("DEBUG: Stopping any playing content to prevent conflicts", xbmc.LOGINFO)
                
                player.stop()
                
                # Wait for stop to take effect
                for i in range(30):  # Wait up to 3 seconds
                    if not player.isPlaying():
                        break
                    xbmc.sleep(100)
                    
                debug_log(f"DEBUG: Player stopped, isPlaying: {player.isPlaying()}", xbmc.LOGINFO)
                
            except Exception as e:
                debug_log(f"DEBUG: Error getting/stopping playing file: {str(e)}", xbmc.LOGINFO)
                # Force stop anyway
                try:
                    player.stop()
                except:
                    pass
        
        # Try to close any busy dialogs that might be causing conflicts
        try:
            xbmc.executebuiltin('Dialog.Close(busydialog)')
            xbmc.executebuiltin('Dialog.Close(all)')
            xbmc.sleep(500)
        except:
            pass
            
    except Exception as e:
        # Fallback debug logging without xbmc if import fails
        print(f"DEBUG: Error in cancel_youtube_playback: {str(e)}")

def reset_youtube_playback_state():
    """Reset the YouTube playback cancellation state"""
    global _youtube_playback_cancelled
    with _cancellation_lock:
        _youtube_playback_cancelled = False
        _cancellation_event.clear()
        debug_log("DEBUG: YouTube playback state reset via reset_youtube_playback_state()", xbmc.LOGINFO)

def get_youtube_sleep_time():
    """Get the sleep time setting from addon settings"""
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon()
        sleep_time = int(addon.getSetting('youtube_sleep_time'))
        return sleep_time
    except:
        return 5  # Default fallback

def fetch_links(url):
    """Fetch directory links from URL, returns (dirs, files) tuples"""
    try:
        debug_log(f"DEBUG: fetch_links called with URL: {url}", xbmc.LOGINFO)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode('utf-8', errors='ignore')
        
        import re
        # Find directory links (ending with /)
        dir_links = re.findall(r'href="([^"]+)/"[^>]*>([^<]+)', content)
        # Find file links (ending with .json)
        file_links = re.findall(r'href="([^"]+\.json)"[^>]*>([^<]+)', content)
        
        # Filter out navigation links
        dirs = [(href, name) for href, name in dir_links if href not in ['.', '..']]
        files = [(href, name) for href, name in file_links]
        
        return dirs, files
    except Exception as e:
        debug_log(f"DEBUG: Failed to fetch links from {url}: {str(e)}", xbmc.LOGERROR)
        return [], []

def fetch_json_content(json_url):
    """Fetch JSON from URL as a dict (in-memory, no file)"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        req = urllib.request.Request(json_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode('utf-8')
        return json.loads(data)  # Return as dict for easy parsing
    except Exception as e:
        debug_log(f"DEBUG: Failed to fetch/parse {json_url}: {str(e)}", xbmc.LOGERROR)
        return None

def youtube_json_to_epggrid(data_source, source_name=None):
    """
    Parse YouTube JSON: now accepts path (str) or dict/content (str/dict)
    """
    debug_log(f"DEBUG: youtube_json_to_epggrid called with data_source type: {type(data_source)}, value: {str(data_source)[:100]}...", xbmc.LOGINFO)
    
    if isinstance(data_source, str) and not data_source.startswith(('http://', 'https://')) and os.path.exists(data_source):
        # Original: Load from file
        debug_log(f"DEBUG: Loading from local file: {data_source}", xbmc.LOGINFO)
        with open(data_source, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Extract channel name from file name (remove .json extension)
        channel_name = os.path.splitext(os.path.basename(data_source))[0]
    elif isinstance(data_source, dict):
        data = data_source
        # Use provided source_name or try to extract from data
        channel_name = source_name or data.get('title', 'Unknown Channel')
    elif isinstance(data_source, str) and (data_source.startswith(('http://', 'https://')) or not os.path.exists(data_source)):
        # Assume it's raw JSON string or URL (URLs should not be passed here, but handle gracefully)
        if data_source.startswith(('http://', 'https://')):
            # This shouldn't happen in normal flow, but handle gracefully
            debug_log(f"ERROR: URL incorrectly passed to youtube_json_to_epggrid: {data_source}", xbmc.LOGERROR)
            debug_log(f"ERROR: This is likely the source of the file path error!", xbmc.LOGERROR)
            raise ValueError("URLs should not be passed directly to youtube_json_to_epggrid. Use fetch_json_content first.")
        else:
            # Assume it's raw JSON string
            debug_log(f"DEBUG: Parsing as JSON string, length: {len(data_source)}", xbmc.LOGINFO)
            data = json.loads(data_source)
            channel_name = source_name or 'Unknown Channel'
    else:
        raise ValueError("Invalid data_source: must be file path, dict, or JSON string")
    
    # Create tvg_id by removing spaces and making lowercase
    tvg_id = channel_name.lower().replace(' ', '_').replace('-', '_')
    
    # Get logo from first item if available
    logo = data['items'][0].get('thumbnail', '') if data.get('items') else ''
    
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
    
    for item in data.get('items', []):
        duration_str = item.get('duration', '0:00')
        try:
            duration_parts = duration_str.split(':')
            if len(duration_parts) == 2:
                duration_seconds = int(duration_parts[0]) * 60 + int(duration_parts[1])
            elif len(duration_parts) == 3:
                duration_seconds = int(duration_parts[0]) * 3600 + int(duration_parts[1]) * 60 + int(duration_parts[2])
            else:
                duration_seconds = 300  # Default to 5 minutes
        except Exception:
            duration_seconds = 300  # Default to 5 minutes if invalid
            
        end_time = start_time + timedelta(seconds=duration_seconds)
        
        programs.append({
            'title': item['title'],
            'channel': tvg_id,
            'desc': item.get('summary', ''),
            'start': start_time,
            'stop': end_time,  # EPGGrid expects 'stop' not 'end'
            'link': item['link'],
            'logo': item.get('thumbnail', ''),
        })
        
        # Add configurable delay between programs
        start_time = end_time + timedelta(seconds=sleep_time)
        
    return [channel], programs
def play_youtube_programs(programs, delay=None, is_new_channel=True):
    """
    YouTube playlist playback with improved conflict handling
    """
    # Declare global variable first
    global _youtube_playback_cancelled
    
    if delay is None:
        delay = get_youtube_sleep_time()
        
    try:
        import xbmc
        import xbmcgui
        import re
        import random
        
        # Generate a unique thread ID for this playback session
        import time
        thread_id = int(time.time() * 1000) % 100000  # Last 5 digits of timestamp
        debug_log(f"DEBUG: Sequential thread {thread_id} starting", xbmc.LOGINFO)
        
        # Only reset cancellation flag for genuinely new channel selections
        # Don't reset if this is a continuation of existing playlist
        if is_new_channel:
            with _cancellation_lock:
                debug_log(f"DEBUG: Thread {thread_id} - Reset flag from {_youtube_playback_cancelled} to False", xbmc.LOGINFO)
                _youtube_playback_cancelled = False
                _cancellation_event.clear()  # Clear the event for new channel
                debug_log(f"DEBUG: Thread {thread_id} - Starting new channel - reset cancellation flag and event", xbmc.LOGINFO)
        else:
            with _cancellation_lock:
                debug_log(f"DEBUG: Thread {thread_id} - Continuing playlist - cancellation flag is {_youtube_playback_cancelled}", xbmc.LOGINFO)
        
        debug_log(f"DEBUG: play_youtube_programs started with {len(programs)} programs", xbmc.LOGINFO)
        
        # Force stop any existing playback more aggressively
        try:
            player = xbmc.Player()
            if player.isPlaying():
                debug_log("DEBUG: Stopping existing player before starting YouTube playback", xbmc.LOGINFO)
                player.stop()
                xbmc.sleep(2000)  # Longer wait for clean stop
        except Exception as e:
            debug_log(f"DEBUG: Error checking/stopping existing player: {str(e)}", xbmc.LOGINFO)
        
        if not programs:
            xbmcgui.Dialog().ok("Error", "No programs to play")
            return
            
        # Show playback options to user
        dialog = xbmcgui.Dialog()
        options = ["Play One Random Video", "Play All Videos Sequentially"]
        play_mode = dialog.select("YouTube Playback Mode", options)
        
        if play_mode == -1:  # User cancelled
            return
        elif play_mode == 0:  # Single video
            prog = random.choice(programs)
            url = prog['link']
            
            # Convert YouTube URL to plugin format
            match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
            if match:
                youtube_url = f"plugin://plugin.video.youtube/play/?video_id={match.group(1)}"
            else:
                youtube_url = url
                
            listitem = xbmcgui.ListItem(label=prog['title'])
            if prog.get('logo'):
                listitem.setArt({'thumb': prog['logo']})
            
            player = xbmc.Player()
            player.play(youtube_url, listitem)
            xbmcgui.Dialog().notification("YouTube Player", f"Playing: {prog['title']}", xbmcgui.NOTIFICATION_INFO, 3000)
            
        else:  # Sequential playback
            # Use a much simpler approach for sequential playback
            # Cancellation flag already reset at function start
            
            total_videos = len(programs)
            dialog = xbmcgui.DialogProgress()
            dialog.create("YouTube Playlist", f"Playing {total_videos} videos...")
            
            player = xbmc.Player()
            
            for i, prog in enumerate(programs):
                # Check for cancellation using both flag and event
                with _cancellation_lock:
                    cancelled = _youtube_playback_cancelled
                event_set = _cancellation_event.is_set()
                if cancelled or event_set or dialog.iscanceled():
                    debug_log(f"DEBUG: Thread {thread_id} - YouTube playback cancelled - exiting function (flag={cancelled}, event={event_set})", xbmc.LOGINFO)
                    try:
                        dialog.close()
                    except:
                        pass
                    return
                    
                # Update progress
                dialog.update(int((i / total_videos) * 100), f"Playing: {prog['title']} ({i+1}/{total_videos})")
                
                url = prog['link']
                match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
                if match:
                    youtube_url = f"plugin://plugin.video.youtube/play/?video_id={match.group(1)}"
                else:
                    youtube_url = url
                    
                listitem = xbmcgui.ListItem(label=prog['title'])
                if prog.get('logo'):
                    listitem.setArt({'thumb': prog['logo']})
                
                # Play the video
                player.play(youtube_url, listitem)
                
                # Wait for video to start
                start_wait = 0
                while not player.isPlaying() and start_wait < 10:
                    if _youtube_playback_cancelled or dialog.iscanceled():
                        debug_log("DEBUG: YouTube playback cancelled while waiting for start", xbmc.LOGINFO)
                        try:
                            dialog.close()
                        except:
                            pass
                        return
                    xbmc.sleep(1000)
                    start_wait += 1
                
                if not player.isPlaying():
                    debug_log(f"Failed to start {prog['title']}, skipping", xbmc.LOGWARNING)
                    continue
                
                # Close dialog after first video starts so user can watch
                if i == 0:
                    dialog.close()
                    xbmcgui.Dialog().notification("YouTube Playlist", f"Playing {total_videos} videos with {delay}s delays", xbmcgui.NOTIFICATION_INFO, 5000)
                
                # Wait for video to finish
                while player.isPlaying():
                    # Check both flag and event for cancellation
                    with _cancellation_lock:
                        cancelled = _youtube_playback_cancelled
                    event_set = _cancellation_event.is_set()
                    
                    if cancelled or event_set:
                        debug_log(f"DEBUG: Thread {thread_id} - YouTube playback cancelled during video - stopping and exiting (flag={cancelled}, event={event_set})", xbmc.LOGINFO)
                        player.stop()
                        try:
                            dialog.close()
                        except:
                            pass
                        return
                    xbmc.sleep(250)  # Check every 250ms for faster response
                    # Add periodic logging to track playback state - log every 5 seconds to avoid spam
                    import time
                    current_time = time.time()
                    if not hasattr(play_youtube_programs, '_last_log_time'):
                        play_youtube_programs._last_log_time = 0
                    
                    if current_time - play_youtube_programs._last_log_time >= 5:  # Log every 5 seconds
                        with _cancellation_lock:
                            flag_state = _youtube_playback_cancelled
                        event_state = _cancellation_event.is_set()
                        debug_log(f"DEBUG: Thread {thread_id} - Video playing, cancellation flag = {flag_state}, event = {event_state}", xbmc.LOGINFO)
                        play_youtube_programs._last_log_time = current_time
                
                # Check cancellation again after video finishes
                with _cancellation_lock:
                    cancelled = _youtube_playback_cancelled
                event_set = _cancellation_event.is_set()
                if cancelled or event_set:
                    debug_log(f"DEBUG: Thread {thread_id} - YouTube playback cancelled after video finished (flag={cancelled}, event={event_set})", xbmc.LOGINFO)
                    try:
                        dialog.close()
                    except:
                        pass
                    return
                
                # Sleep between videos (except last one)
                if i < len(programs) - 1:
                    # Check cancellation before starting sleep
                    with _cancellation_lock:
                        cancelled = _youtube_playback_cancelled
                    event_set = _cancellation_event.is_set()
                    if cancelled or event_set:
                        debug_log(f"DEBUG: YouTube playback cancelled before inter-video delay (flag={cancelled}, event={event_set})", xbmc.LOGINFO)
                        try:
                            dialog.close()
                        except:
                            pass
                        return
                        
                    for sleep_sec in range(delay):
                        with _cancellation_lock:
                            cancelled = _youtube_playback_cancelled
                        event_set = _cancellation_event.is_set()
                        if cancelled or event_set:
                            debug_log(f"DEBUG: YouTube playback cancelled during sleep (flag={cancelled}, event={event_set})", xbmc.LOGINFO)
                            try:
                                dialog.close()
                            except:
                                pass
                            return
                        xbmc.sleep(1000)
            
            try:
                dialog.close()
            except:
                pass
                
            if not _youtube_playback_cancelled:
                xbmcgui.Dialog().notification("YouTube Playlist", "Finished playing all videos", xbmcgui.NOTIFICATION_INFO, 3000)
        
    except Exception as e:
        debug_log(f"DEBUG: Error in play_youtube_programs: {str(e)}", xbmc.LOGERROR)
        xbmcgui.Dialog().ok("Playback Error", f"Failed to start YouTube playback: {str(e)}")
def export_epg_xml(programs, xml_path):
    from xml.etree.ElementTree import Element, SubElement, ElementTree
    tv = Element('tv')
    for prog in programs:
        channel_elem = SubElement(tv, 'channel', id=prog['channel'])
        SubElement(channel_elem, 'display-name').text = prog['title']
        SubElement(channel_elem, 'icon', src=prog['logo'])
        prog_elem = SubElement(tv, 'programme', start=prog['start'].strftime('%Y%m%d%H%M%S'), stop=prog['end'].strftime('%Y%m%d%H%M%S'), channel=prog['channel'])
        SubElement(prog_elem, 'title').text = prog['title']
        SubElement(prog_elem, 'desc').text = prog['desc']
        SubElement(prog_elem, 'url').text = prog['link']
    tree = ElementTree(tv)
    tree.write(xml_path, encoding='utf-8', xml_declaration=True)

def export_m3u8(programs, m3u_path):
    with open(m3u_path, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U\n')
        for prog in programs:
            f.write(f'#EXTINF:-1 tvg-id="{prog["channel"]}" tvg-name="{prog["title"]}" tvg-logo="{prog["logo"]}",{prog["title"]}\n')
            f.write(f'{prog["link"]}\n')