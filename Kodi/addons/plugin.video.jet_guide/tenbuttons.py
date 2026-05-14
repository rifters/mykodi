def save_widget_link(link_obj):
    """
    Save a link object to the widgets.json file for widget display.
    """
    import xbmcvfs
    import json
    WIDGETS_PATH = xbmcvfs.translatePath("special://userdata/addon_data/plugin.video.jet_guide/widgets.json")
    try:
        if xbmcvfs.exists(WIDGETS_PATH):
            with xbmcvfs.File(WIDGETS_PATH, "r") as f:
                links = json.loads(f.read())
        else:
            links = []
    except Exception:
        links = []
    # Accept widgets with either "link" or "source_folder"
    links = [l for l in links if isinstance(l, dict) and "title" in l and ("link" in l or "source_folder" in l)]
    # Use "link" if present, else "source_folder"
    def get_widget_key(w):
        return w.get("link") or w.get("source_folder")
    new_key = get_widget_key(link_obj)
    if isinstance(link_obj, dict) and new_key and not any(get_widget_key(l) == new_key for l in links):
        links.append(link_obj)
        with xbmcvfs.File(WIDGETS_PATH, "w") as f:
            f.write(json.dumps(links, indent=2))
    return

import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin
import xbmcvfs
import requests
import xml.etree.ElementTree as ET
import re
from bs4 import BeautifulSoup
import os
import random
import subprocess
import base64
import json
import time
import urllib.parse
import time
import threading
import sys
xbc=xbmc
xbcaddon=xbmcaddon
xbcgui=xbmcgui
xbcvfs=xbmcvfs
ffmpeg_proc = None
from addon import (parse_m3u8, parse_xmltv, M3U8_PATH, XMLTV_PATH,
                   show_sports_guide, show_channel_listings,
                   last_watched_manager, show_sports_grid)
from searchwindow import SearchWindow
from favoriteswindow import FavoritesWindow
from favorites import favorites_manager
from reminders import RemindersManager
from tools import show_tools, debug_log
# import base64

JET_GUIDE_IMPORTED_PATH = xbmcvfs.translatePath("special://userdata/addon_data/plugin.video.jet_guide/jet_guide_imported.json")

def play_saved_jet_guide_link(link):
    """Play a saved JetGuide link"""
    if isinstance(link, str) and (link.startswith("http") or link.endswith(".m3u8") or link.startswith("plugin://")):
        if link.startswith("plugin://"):
            xbmc.executebuiltin(f'PlayMedia("{link}")')
        else:
            xbmc.Player().play(link)
    else:
        debug_log(f"JetGuide DEBUG: Not playable. Link: {link}", xbmc.LOGERROR)
        xbmcgui.Dialog().ok("Error", f"This link is not a direct playable stream.\n\nLink: {link}")

def save_link_to_jet_guide(link_obj):
    # Base folder for custom folders
    FOLDERS_BASE_PATH = "special://userdata/addon_data/plugin.video.jet_guide/jet_guide_folders"

    dialog = xbmcgui.Dialog()
    choices = ["Create new folder", "Add to existing folder", "Add to jet_guide_imported"]
    choice = dialog.select("Save link - Choose destination", choices)

    if choice == 0:  # Create new folder
        suggested_name = link_obj.get("title", "New Folder")
        folder_name = dialog.input("Enter folder name", defaultt=suggested_name)
        if not folder_name:
            return
        folder_path = xbmcvfs.translatePath(FOLDERS_BASE_PATH + "/" + folder_name)
        if not xbmcvfs.exists(folder_path):
            xbmcvfs.mkdirs(folder_path)
        links_file = folder_path + "/links.json"
        try:
            if xbmcvfs.exists(links_file):
                with xbmcvfs.File(links_file, "r") as f:
                    links = json.loads(f.read())
            else:
                links = []
        except Exception:
            links = []
        links = [l for l in links if isinstance(l, dict) and "title" in l and "link" in l]
        if isinstance(link_obj, dict) and not any(l.get("link") == link_obj["link"] for l in links):
            links.append(link_obj)
            with xbmcvfs.File(links_file, "w") as f:
                f.write(json.dumps(links, indent=2))
        return

    elif choice == 1:  # Add to existing folder
        # List folders
        debug_log(f"DEBUG: FOLDERS_BASE_PATH={FOLDERS_BASE_PATH}", level=xbmc.LOGINFO)
        folder_base = xbmcvfs.translatePath(FOLDERS_BASE_PATH)
        debug_log(f"DEBUG: Translated folder_base={folder_base}", level=xbmc.LOGINFO)
        exists = xbmcvfs.exists(folder_base)
        debug_log(f"DEBUG: xbmcvfs.exists(folder_base)={exists}", level=xbmc.LOGINFO)
        if not exists:
            debug_log(f"DEBUG: Folders base does not exist, attempting to create: {folder_base}", level=xbmc.LOGINFO)
            try:
                xbmcvfs.mkdirs(folder_base)
                debug_log(f"DEBUG: mkdirs called for {folder_base}", level=xbmc.LOGINFO)
            except Exception as e:
                debug_log(f"DEBUG: mkdirs failed for {folder_base}: {e}", level=xbmc.LOGERROR)
            exists = xbmcvfs.exists(folder_base)
            debug_log(f"DEBUG: xbmcvfs.exists(folder_base) after mkdirs={exists}", level=xbmc.LOGINFO)
        debug_folders = []
        debug_log(f"DEBUG: Entering os.listdir block for {folder_base}", level=xbmc.LOGINFO)
        try:
            for f in os.listdir(folder_base):
                full_path = os.path.join(folder_base, f)
                isdir = os.path.isdir(full_path)
                debug_log(f"DEBUG: OS Folder candidate: {full_path} isdir={isdir}", level=xbmc.LOGINFO)
                if isdir:
                    debug_folders.append(f)
        except Exception as e:
            debug_log(f"DEBUG: os.listdir failed for {folder_base}: {e}", level=xbmc.LOGERROR)
        debug_log(f"DEBUG: Exiting os.listdir block for {folder_base}", level=xbmc.LOGINFO)
        folders = debug_folders
        debug_log(f"DEBUG: Folders detected by os.listdir: {folders}", level=xbmc.LOGINFO)
        if not folders:
            debug_log(f"DEBUG: No folders found after filtering", level=xbmc.LOGINFO)
            dialog.notification("No folders found", "Create a folder first", xbmcgui.NOTIFICATION_INFO)
            return
        # Search/filter loop
        filtered_folders = folders
        while True:
            search_term = dialog.input("Search folders (leave blank to show all)")
            if search_term:
                filtered_folders = [f for f in folders if search_term.lower() in f.lower()]
                if not filtered_folders:
                    dialog.notification("No matching folders", "Try another search", xbmcgui.NOTIFICATION_INFO)
                    continue
            selected = dialog.select("Select folder", filtered_folders)
            if selected == -1:
                exit_choice = dialog.yesno("Cancel", "Do you want to exit folder selection?", "No = Search again", "Yes = Exit")
                if exit_choice:
                    return
                else:
                    continue
            folder_path = folder_base + "/" + filtered_folders[selected]
            links_file = folder_path + "/links.json"
            try:
                if xbmcvfs.exists(links_file):
                    with xbmcvfs.File(links_file, "öd") as f:
                        links = json.loads(f.read())
                else:
                    links = []
            except Exception:
                links = []
            links = [l for l in links if isinstance(l, dict) and "title" in l and "link" in l]
            if isinstance(link_obj, dict) and not any(l.get("link") == link_obj["link"] for l in links):
                links.append(link_obj)
                with xbmcvfs.File(links_file, "w") as f:
                    f.write(json.dumps(links, indent=2))
            return

    # Default: Add to jet_guide_imported
    # Load existing links
    try:
        if xbmcvfs.exists(JET_GUIDE_IMPORTED_PATH):
            with xbmcvfs.File(JET_GUIDE_IMPORTED_PATH, "r") as f:
                links = json.loads(f.read())
        else:
            links = []
    except Exception:
        links = []
    # Remove any legacy string entries
    links = [l for l in links if isinstance(l, dict) and "title" in l and "link" in l]

    if isinstance(link_obj, dict) and not any(l.get("link") == link_obj["link"] for l in links):
        links.append(link_obj)
        with xbmcvfs.File(JET_GUIDE_IMPORTED_PATH, "w") as f:
            f.write(json.dumps(links, indent=2))
ACTIVE_WINDOW = None

ADDON = xbmcaddon.Addon()
addon__id = ADDON.getAddonInfo('id')

class TickerDialog(xbmcgui.WindowXMLDialog):
    def __init__(self, xmlFilename, scriptPath, messages, display_time=10):
        self.messages = messages if isinstance(messages, list) else [messages]
        self.display_time = display_time
        self.current_message = 0
        super().__init__(xmlFilename, scriptPath)

    def onInit(self):
        try:
            self.setProperty('ticker_text', self.messages[self.current_message])
            start_time = time.time()
            while time.time() - start_time < self.display_time and not xbmc.Monitor().abortRequested():
                if self.current_message < len(self.messages) - 1:
                    if not self.getControl(1000).isScrolling():
                        self.current_message += 1
                        self.setProperty('ticker_text', self.messages[self.current_message])
                xbmc.sleep(100)
            self.close()
        except Exception as e:
            debug_log(f"TickerDialog error: {str(e)}", level=xbmc.LOGERROR)
            self.close()



class TenButtonsWindow(xbmcgui.WindowXML):
    def __init__(self, xml_file, addon_path):
        super().__init__(xml_file, addon_path)
        global ACTIVE_WINDOW
        ACTIVE_WINDOW = self
        self.buttons = {
            101: "",# EPG GUIDE
            102: "",# SPORTS GUIDE
            # 103: "",# Channel List
            104: "", # Search Channel or Programs
            105: "", # Favorites
            106: "", # Sports Stats
            # 107: "", # Alerts
            108: "", # Main Menu List
            # 109: "", # Clear Cache
            # 110: "", # Settings
            # 111: "", # Search Kodi Addons
            # 112: "", # Import Kodi Favourites
            # 113: "", # Clear Reminders
            114: "", # EXIT
            # 115: "", # Folders and Links
            # 120: "Manage Widgets", # Manage Widgets
            199: "", # Record/Play Stream
            # 960: "", # Youtube Search
        }
        self.buttons[120] = "Manage Widgets"
        self.last_watched_list = None
        self.widget_list = None
        self.widget_list2 = None
        self.ticker_control = None
        self.ticker_thread = None
        self.ticker_running = False
        self.ticker_interval = int(xbmcaddon.Addon().getSetting("ticker_interval"))



    def onInit(self):
        debug_log("DEBUG: TenButtonsWindow onInit called", level=xbmc.LOGINFO)
        try:
            xbmc.executebuiltin('Dialog.Close(all)')
            xbmc.sleep(100)
            self.ticker_running = False
            if self.ticker_thread and self.ticker_thread.is_alive():
                self.ticker_thread.join(timeout=1)
            debug_log("DEBUG: Initializing buttons", level=xbmc.LOGINFO)
            for btn_id in self.buttons:
                try:
                    control = self.getControl(btn_id)
                    control.setLabel(self.buttons[btn_id])
                    control.setEnabled(True)
                except Exception as e:
                    debug_log(f"Error initializing button {btn_id}: {str(e)}", level=xbmc.LOGERROR)
            debug_log("DEBUG: Initializing widget list", level=xbmc.LOGINFO)
            try:
                self.widget_list = self.getControl(310)
                self.widget_list2 = self.getControl(311)
                if self.widget_list:
                    debug_log("DEBUG: widget_list control 310 found", level=xbmc.LOGINFO)
                else:
                    debug_log("DEBUG: widget_list control 310 NOT found", level=xbmc.LOGINFO)
                if self.widget_list2:
                    debug_log("DEBUG: widget_list control 311 found", level=xbmc.LOGINFO)
                else:
                    debug_log("DEBUG: widget_list control 311 NOT found", level=xbmc.LOGINFO)
                self.load_pinned_widgets(self.widget_list)
                self.load_pinned_widgets(self.widget_list2, widget_row=2)
            except Exception as e:
                debug_log(f"Error initializing widget lists: {str(e)}", level=xbmc.LOGERROR)
            debug_log("DEBUG: Initializing last watched list", level=xbmc.LOGINFO)
            try:
                self.last_watched_list = self.getControl(200)
                self.load_last_watched_channels()
            except Exception as e:
                debug_log(f"Error initializing last watched list: {str(e)}", level=xbmc.LOGERROR)
            debug_log("DEBUG: Initializing ticker", level=xbmc.LOGINFO)
            try:
                self.ticker_control = self.getControl(300)
                self.ticker_running = True
                self.start_ticker_updates()
            except Exception as e:
                debug_log(f"Error initializing ticker: {str(e)}", level=xbmc.LOGERROR)
        except Exception as e:
            debug_log(f"Failed to initialize TenButtonsWindow: {str(e)}", level=xbmc.LOGERROR)
            xbmcgui.Dialog().ok("Error", f"Failed to initialize window: {str(e)}")

    def load_pinned_widgets(self, widget_list=None, widget_row=1):
        """
        Load pinned widget links from widgets.json and display in the given widget_list.
        widget_row can be used to filter or split widgets between rows if needed.
        """
        debug_log(f"DEBUG: load_pinned_widgets called for row {widget_row}", level=xbmc.LOGINFO)
        if widget_list is None:
            widget_list = self.widget_list
        if not widget_list:
            debug_log(f"DEBUG: widget_list (row {widget_row}) is None", level=xbmc.LOGINFO)
            return
        try:
            widget_list.reset()
            try:
                WIDGETS_PATH = xbmcvfs.translatePath("special://userdata/addon_data/plugin.video.jet_guide/widgets.json")
                debug_log(f"DEBUG: Resolved widgets.json path: {WIDGETS_PATH}", level=xbmc.LOGINFO)
                exists = xbmcvfs.exists(WIDGETS_PATH)
                debug_log(f"DEBUG: widgets.json exists? {exists}", level=xbmc.LOGINFO)
                if not exists:
                    debug_log("DEBUG: widgets.json does not exist", level=xbmc.LOGINFO)
                    return
                with xbmcvfs.File(WIDGETS_PATH, "r") as f:
                    links = json.loads(f.read())
                debug_log(f"DEBUG: widgets.json loaded, {len(links)} widgets", level=xbmc.LOGINFO)
            except Exception as e:
                debug_log(f"DEBUG: Exception in load_pinned_widgets: {e}", level=xbmc.LOGERROR)
                return
            debug_log(f"DEBUG: widgets.json loaded, {len(links)} widgets", level=xbmc.LOGINFO)
            count = 0
            # Assign widgets to rows based on "row" property if present, else fallback to even/odd split
            for idx, link in enumerate(links):
                row_prop = link.get("row")
                if row_prop:
                    if int(row_prop) != widget_row:
                        continue
                else:
                    if widget_row == 2:
                        if idx % 2 == 0:
                            continue
                    elif widget_row == 1:
                        if idx % 2 == 1:
                            continue
                # --- original widget item creation logic below ---
                if "source_folder" in link:
                    try:
                        params = {
                            "jsonrpc": "2.0",
                            "method": "Files.GetDirectory",
                            "id": 1,
                            "params": {
                                "directory": link["source_folder"],
                                "media": "files"
                            }
                        }
                        response = xbmc.executeJSONRPC(json.dumps(params))
                        data = json.loads(response)
                        items = data.get("result", {}).get("files", [])
                        for item in items:
                            widget_link = item.get("file", "")
                            label = item.get("label", widget_link)
                            # Try to extract thumbnail from base64-encoded plugin links
                            thumb = ""
                            import base64
                            import json as _json
                            import re as _re
                            # Improved base64 extraction for plugin links
                            b64_match = _re.search(r"plugin://[^/]+/[^/]+/([^/?]+)", widget_link)
                            if b64_match:
                                try:
                                    b64_str = b64_match.group(1)
                                    # Remove any trailing path or query
                                    b64_str = b64_str.split('/')[0].split('?')[0]
                                    # Remove non-base64 chars and whitespace
                                    import re as _re2
                                    b64_str = _re2.sub(r'[^A-Za-z0-9_\-+=]', '', b64_str)
                                    b64_str = b64_str.strip().replace('\n', '').replace('\r', '')
                                    # Pad base64 if needed
                                    missing_padding = len(b64_str) % 4
                                    if missing_padding:
                                        b64_str += "=" * (4 - missing_padding)
                                    try:
                                        decoded = base64.urlsafe_b64decode(b64_str).decode("utf-8")
                                        decoded_json = _json.loads(decoded)
                                        thumb = decoded_json.get("thumbnail") or decoded_json.get("fanart") or ""
                                        if thumb:
                                            debug_log(f"DEBUG: Extracted thumbnail from base64: {thumb}", level=xbmc.LOGINFO)
                                    except Exception as e2:
                                        debug_log(f"DEBUG: Secondary decode fail: {e2}", level=xbmc.LOGERROR)
                                except Exception as e:
                                    debug_log(f"DEBUG: Failed to decode base64 from widget_link: {e}", level=xbmc.LOGERROR)
                            if not thumb:
                                thumb = (
                                    item.get("thumbnail")
                                    or item.get("fanart")
                                    or item.get("icon")
                                    or (item.get("art", {}).get("thumb") if "art" in item else None)
                                    or (item.get("art", {}).get("icon") if "art" in item else None)
                                    or ""
                                )
                            icon = thumb if thumb else "special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/folders.PNG"
                            if not thumb and widget_link.startswith("plugin://"):
                                m = re.match(r"plugin://([^/]+)/", widget_link)
                                if m:
                                    addon_id = m.group(1)
                                    icon_path = f"special://home/addons/{addon_id}/icon.png"
                                    if xbmcvfs.exists(icon_path):
                                        icon = icon_path
                            # Custom sports icon logic with debug (must be last)
                            sports_keywords = ["NBA","NFL","Soccer"]
                            label_lower = label.lower()
                            if "mlb" in label_lower or "mlb" in widget_link.lower():
                                debug_log(f"DEBUG: MLB found in label or widget_link, setting MLB icon", level=xbmc.LOGINFO)
                                icon = "special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/mlb.jpg"
                            # elif "nba" in label_lower or "nba" in widget_link.lower():
                            #     debug_log(f"DEBUG: NBA found in label or widget_link, setting NBA icon", level=xbmc.LOGINFO)
                            #     icon = "special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/mlb.jpg"
                            elif any(word.lower() in label_lower or word.lower() in widget_link.lower() for word in sports_keywords):
                                debug_log(f"DEBUG: Other sports keyword found in label='{label}' or widget_link='{widget_link}', setting default sports icon", level=xbmc.LOGINFO)
                                icon = "special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/sports_icon.png"
                            else:
                                debug_log(f"DEBUG: No sports keyword in label='{label}' or widget_link='{widget_link}'", level=xbmc.LOGINFO)
                            list_item = xbmcgui.ListItem(label)
                            debug_log(f"Widget Item Debug: label={label}, widget_link={widget_link}, item={item}", level=xbmc.LOGINFO)
                            # If a thumbnail was extracted, always use it and skip sports icon logic
                            if thumb:
                                icon = thumb
                            else:
                                sports_keywords = ["NFL","Soccer"]
                                if any(word.lower() in label.lower() or word.lower() in widget_link.lower() for word in sports_keywords):
                                    debug_log(f"DEBUG: Sports keyword found and no thumbnail, setting sports icon", level=xbmc.LOGINFO)
                                    icon = "special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/sports_icon.png"
                            # If sports icon is used, set all art fields to it
                            if icon == "special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/sports_icon.png":
                                art_dict = {
                                    'icon': icon,
                                    'thumb': icon,
                                    'poster': icon,
                                    'banner': icon,
                                    'fanart': icon,
                                    'landscape': icon,
                                    'clearart': icon,
                                    'clearlogo': icon
                                }
                            else:
                                art_dict = {
                                    'icon': icon,
                                    'thumb': icon,
                                    'poster': icon,
                                    'banner': icon,
                                    'fanart': item.get("fanart", icon),
                                    'landscape': icon,
                                    'clearart': icon,
                                    'clearlogo': icon
                                }
                            debug_log(f"Widget Art Debug: label={label}, widget_link={widget_link}, art={art_dict}, icon={icon}", level=xbmc.LOGINFO)
                            list_item.setArt(art_dict)
                            list_item.setProperty("widget_link", widget_link)
                            widget_list.addItem(list_item)
                            count += 1
                    except Exception as e:
                        debug_log(f"Widget dynamic refresh failed: {e}", level=xbmc.LOGERROR)
                elif "links" in link and isinstance(link["links"], list):
                    for item in link["links"]:
                        widget_link = item["file"] if isinstance(item, dict) else item
                        label = item["label"] if isinstance(item, dict) and "label" in item else link.get("title", "Widget")
                        icon = "special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/folders.PNG"
                        # Custom sports icon logic for static links with debug
                        sports_keywords = ["NFL", "Soccer"]
                        if any(word.lower() in label.lower() or word.lower() in widget_link.lower() for word in sports_keywords):
                            debug_log(f"DEBUG: Sports keyword found in static label='{label}' or widget_link='{widget_link}', setting sports icon", level=xbmc.LOGINFO)
                            icon = "special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/sports_icon.png"
                        else:
                            debug_log(f"DEBUG: No sports keyword in static label='{label}' or widget_link='{widget_link}'", level=xbmc.LOGINFO)
                        if widget_link.startswith("plugin://"):
                            m = re.match(r"plugin://([^/]+)/", widget_link)
                            if m:
                                addon_id = m.group(1)
                                icon_path = f"special://home/addons/{addon_id}/icon.png"
                                if xbmcvfs.exists(icon_path):
                                    icon = icon_path
                        list_item = xbmcgui.ListItem(label)
                        list_item.setArt({'icon': icon, 'thumb': icon})
                        list_item.setProperty("widget_link", widget_link)
                        widget_list.addItem(list_item)
                        count += 1
                else:
                    label = link.get("title", "Widget")
                    widget_link = link.get("link", "")
                    if (not label or label == "Widget") and widget_link.startswith("plugin://plugin.video."):
                        label = widget_link.replace("plugin://plugin.video.", "").split("/")[0]
                    icon = "special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/folders.PNG"
                    if widget_link.startswith("plugin://"):
                        m = re.match(r"plugin://([^/]+)/", widget_link)
                        if m:
                            addon_id = m.group(1)
                            icon_path = f"special://home/addons/{addon_id}/icon.png"
                            if xbmcvfs.exists(icon_path):
                                icon = icon_path
                    list_item = xbmcgui.ListItem(label)
                    list_item.setArt({'icon': icon, 'thumb': icon})
                    list_item.setProperty("widget_link", widget_link)
                    widget_list.addItem(list_item)
                    count += 1
        except Exception as e:
            debug_log(f"Error loading pinned widgets: {str(e)}", level=xbmc.LOGERROR)


    def start_ticker_updates(self):
        self.ticker_thread = threading.Thread(target=self.update_ticker)
        self.ticker_thread.daemon = True
        self.ticker_thread.start()
        # debug_log("Started ticker update thread", level=xbmc.LOGDEBUG)

    def remove_widget_by_link(self, widget_link):
        """Remove a widget from widgets.json by its link and refresh the list."""
        WIDGETS_PATH = xbmcvfs.translatePath("special://userdata/addon_data/plugin.video.jet_guide/widgets.json")
        try:
            with xbmcvfs.File(WIDGETS_PATH, "r") as f:
                links = json.loads(f.read())
            new_links = [
                w for w in links
                if not (
                    (w.get("link") == widget_link) or
                    (w.get("source_folder") == widget_link)
                )
            ]
            with xbmcvfs.File(WIDGETS_PATH, "w") as f:
                f.write(json.dumps(new_links, indent=2))
            xbmcgui.Dialog().notification("Widget Removed", "The widget has been deleted.", xbmcgui.NOTIFICATION_INFO, 3000)
            self.load_pinned_widgets()
        except Exception as e:
            xbmcgui.Dialog().notification("Error", f"Failed to remove widget: {e}", xbmcgui.NOTIFICATION_ERROR, 3000)

    def update_ticker(self):
        main_addon = xbmcaddon.Addon()
        if not main_addon.getSettingBool('livescore_alerts_enabled'):
            self.ticker_control.setText("LiveScore Alerts disabled")
            debug_log("LiveScore Alerts disabled, ticker not updated", level=xbmc.LOGINFO)
            return
        while self.ticker_running and not xbmc.Monitor().abortRequested():
            try:
                games = self.fetch_games()
                if games:
                    messages = [f"{title}: {g['score']} ({g['status']})" for title, g in games.items()]
                    ticker_text = "  |  ".join(messages)
                    self.ticker_control.setText(ticker_text)
                    # debug_log(f"Updated ticker with {len(messages)} games", level=xbmc.LOGDEBUG)
                else:
                    self.ticker_control.setText("No live scores available")
                    debug_log("No live scores available for ticker", level=xbmc.LOGINFO)
            except Exception as e:
                debug_log(f"Ticker update error: {str(e)}", level=xbmc.LOGERROR)
                self.ticker_control.setText("Error fetching scores")
            xbmc.sleep(5*60)

    def load_last_watched_channels(self):
        """Load and display last watched channels"""
        if not self.last_watched_list:
            return
            
        try:
            # Clear existing items
            self.last_watched_list.reset()
            # Get last watched channels
            channels = last_watched_manager.load_last_watched()
            # Add channel icons as items
            for channel in channels:
                list_item = xbmcgui.ListItem(channel.get('name', 'Unknown'))
                list_item.setArt({'icon': channel.get('logo', '')})
                list_item.setProperty('channel_id', channel.get('tvg_id', ''))
                self.last_watched_list.addItem(list_item)
                
        except Exception as e:
            xbmcgui.Dialog().notification('Error', 'Failed to load recent channels')

    def onClick(self, control_id):
        """Handle click events on controls"""
        global ffmpeg_proc

        if control_id == 150:  # Tools button
            show_tools()
            return

        if control_id in (310, 311):  # Widget bar clicked (support both rows)
            widget_list = self.widget_list if control_id == 310 else self.widget_list2
            if widget_list:
                item = widget_list.getSelectedItem()
                if item:
                    widget_link = item.getProperty("widget_link")
                    if widget_link:
                        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
                        xbmc.executebuiltin('Dialog.Close(busydialog)')
                        xbmc.executebuiltin('Dialog.Close(all,true)')
                        xbmc.sleep(250)
                        if widget_link.startswith("plugin://"):
                            xbmc.executebuiltin(f'RunPlugin({widget_link})')
                            xbmc.sleep(100)
                            xbmc.executebuiltin(f'ActivateWindow(Videos,"{widget_link}",return)')
                        elif widget_link.startswith("http") or widget_link.endswith(".m3u8"):
                            xbmc.executebuiltin(f'PlayMedia("{widget_link}")')
                        else:
                            xbmc.executebuiltin(f'ActivateWindow(Videos,"{widget_link}",return)')
                        return
                

        if control_id == 120:  # Manage Widgets button
            action = xbmcgui.Dialog().select(
                "Manage Widgets",
                [
                    "Create Widget",
                    "Create Widget (All Items from Addon Page)",
                    "Delete Widget",
                    "Cancel"
                ]
            )
            if action == 0:
                # Create Widget (existing logic)
                selected_addon = browse_installed_video_addons()
                if not selected_addon:
                    return
                # Ask user which row to add the widget to
                row_choice = xbmcgui.Dialog().select("Select Widget Row", ["First Row", "Second Row"])
                if row_choice == -1:
                    return
                widget_row = row_choice + 1  # 1 or 2

                def pin_flow(addon_id, start_path=None):
                    if not start_path:
                        plugin_url = f"plugin://{addon_id}/"
                    else:
                        plugin_url = start_path
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
                        if start_path:
                            plugin_url = start_path
                        else:
                            plugin_url = f"plugin://{addon_id}/"
                        if xbmcgui.Dialog().yesno("No Items Found", "No items found in this folder.\nWould you like to pin the root plugin as a widget?"):
                            title = xbmcgui.Dialog().input("Enter a name for this widget", defaultt=plugin_url)
                            if title:
                                save_widget_link({"title": title, "link": plugin_url, "row": widget_row})
                                xbmcgui.Dialog().ok("Widget Saved", f"Widget pinned:\n{title}")
                                self.load_pinned_widgets(self.widget_list if widget_row == 1 else self.widget_list2, widget_row=widget_row)
                        return
                    display_names = []
                    item_urls = []
                    is_folder = []
                    for item in items:
                        display_names.append(item.get("label", item.get("file", "")))
                        item_urls.append(item.get("file", ""))
                        is_folder.append(item.get("filetype", "") == "directory")
                    while True:
                        choice = xbmcgui.Dialog().select("Browse Addon", display_names + ["[Pin this folder as Widget]", "[Go Back]"])
                        if choice < 0 or choice == len(display_names) + 1:
                            return
                        if choice == len(display_names):
                            title = xbmcgui.Dialog().input("Enter a name for this widget", defaultt=plugin_url)
                            if title:
                                save_widget_link({"title": title, "link": plugin_url, "row": widget_row})
                                xbmcgui.Dialog().ok("Widget Saved", f"Widget pinned:\n{title}")
                                self.load_pinned_widgets(self.widget_list if widget_row == 1 else self.widget_list2, widget_row=widget_row)
                            continue
                        if is_folder[choice]:
                            pin_flow(addon_id, item_urls[choice])
                            return
                        else:
                            title = xbmcgui.Dialog().input("Enter a name for this widget", defaultt=display_names[choice])
                            if title:
                                save_widget_link({"title": title, "link": item_urls[choice], "row": widget_row})
                                xbmcgui.Dialog().ok("Widget Saved", f"Widget pinned:\n{title}")
                                self.load_pinned_widgets(self.widget_list if widget_row == 1 else self.widget_list2, widget_row=widget_row)
                            return
                if selected_addon:
                    pin_flow(selected_addon)
            elif action == 1:
                # Create Widget (All Items from Addon Page)
                selected_addon = browse_installed_video_addons()
                if not selected_addon:
                    return
                # Ask user which row to add the widget to
                row_choice = xbmcgui.Dialog().select("Select Widget Row", ["First Row", "Second Row"])
                if row_choice == -1:
                    return
                widget_row = row_choice + 1  # 1 or 2

                def browse_and_select_folder(addon_id, start_path=None):
                    if not start_path:
                        plugin_url = f"plugin://{addon_id}/"
                    else:
                        plugin_url = start_path
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
                        xbmcgui.Dialog().ok("No Items", "No items found in this folder.")
                        return None, None
                    display_names = []
                    item_urls = []
                    is_folder = []
                    for item in items:
                        display_names.append(item.get("label", item.get("file", "")))
                        item_urls.append(item.get("file", ""))
                        is_folder.append(item.get("filetype", "") == "directory")
                    while True:
                        choice = xbmcgui.Dialog().select("Select Addon Page", display_names + ["[Select this folder]", "[Go Back]"])
                        if choice < 0 or choice == len(display_names) + 1:
                            return None, None
                        if choice == len(display_names):
                            # User selected this folder
                            return plugin_url, items
                        if is_folder[choice]:
                            return browse_and_select_folder(addon_id, item_urls[choice])
                        else:
                            xbmcgui.Dialog().ok("Select a folder", "Please select a folder, not a file.")
                folder_url, folder_items = browse_and_select_folder(selected_addon)
                if folder_url and folder_items:
                    all_items = [item for item in folder_items if item.get("file", "")]
                    if not all_items:
                        xbmcgui.Dialog().ok("No Items", "No items found in this folder.")
                        return
                    title = xbmcgui.Dialog().input("Enter a name for this widget", defaultt=folder_url)
                    if title:
                        widget_data = {
                            "title": title,
                            "source_folder": folder_url,
                            "row": widget_row
                        }
                        save_widget_link(widget_data)
                        xbmcgui.Dialog().ok("Widget Saved", f"Widget created with {len(all_items)} items:\n{title}")
                        self.load_pinned_widgets(self.widget_list if widget_row == 1 else self.widget_list2, widget_row=widget_row)
            elif action == 2:
                # Delete Widget
                WIDGETS_PATH = xbmcvfs.translatePath("special://userdata/addon_data/plugin.video.jet_guide/widgets.json")
                try:
                    with xbmcvfs.File(WIDGETS_PATH, "r") as f:
                        links = json.loads(f.read())
                    if not links:
                        xbmcgui.Dialog().ok("Delete Widget", "No widgets to delete.")
                        return
                    display_names = [w.get("title") or w.get("link") for w in links]
                    idx = xbmcgui.Dialog().select("Delete Widget", display_names + ["Cancel"])
                    if idx < 0 or idx >= len(links):
                        return
                    widget = links[idx]
                    widget_link = widget.get("link") or widget.get("source_folder")
                    if widget_link:
                        self.remove_widget_by_link(widget_link)
                except Exception as e:
                    xbmcgui.Dialog().notification("Error", f"Failed to delete widget: {e}", xbmcgui.NOTIFICATION_ERROR, 3000)
            else:
                return
            # Browse folders/links and allow pinning as widget
            def pin_flow(addon_id, start_path=None):
                # Start at root if not specified
                if not start_path:
                    plugin_url = f"plugin://{addon_id}/"
                else:
                    plugin_url = start_path
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
                    return
                display_names = []
                item_urls = []
                is_folder = []
                for item in items:
                    display_names.append(item.get("label", item.get("file", "")))
                    item_urls.append(item.get("file", ""))
                    is_folder.append(item.get("filetype", "") == "directory")
                while True:
                    choice = xbmcgui.Dialog().select("Browse Addon", display_names + ["[Pin this folder as Widget]", "[Go Back]"])
                    if choice < 0 or choice == len(display_names) + 1:
                        return
                    if choice == len(display_names):
                        # Pin current folder as widget
                        title = xbmcgui.Dialog().input("Enter a name for this widget", defaultt=plugin_url)
                        if title:
                            save_widget_link({"title": title, "link": plugin_url})
                            xbmcgui.Dialog().ok("Widget Saved", f"Widget pinned:\n{title}")
                            self.load_pinned_widgets()
                        continue
                    if is_folder[choice]:
                        pin_flow(addon_id, item_urls[choice])
                        return
                    else:
                        # Pin/playable link as widget
                        title = xbmcgui.Dialog().input("Enter a name for this widget", defaultt=display_names[choice])
                        if title:
                            save_widget_link({"title": title, "link": item_urls[choice]})
                            xbmcgui.Dialog().ok("Widget Saved", f"Widget pinned:\n{title}")
                            self.load_pinned_widgets()
                        continue
            pin_flow(selected_addon)
            return
        FOLDERS_BASE_PATH = "special://userdata/addon_data/plugin.video.jet_guide/jet_guide_folders"
        try:
            if control_id == 111:  # Search Kodi Addons button
                selected_addon = browse_installed_video_addons()
                if not selected_addon:
                    return
                # Open custom dialog to browse folders and links
                browse_addon_plugin_folders(selected_addon)
                return
            if control_id == 112:  # Import Kodi Favourites button
                import_channels_from_favourites()
                return
            if control_id == 113:  # Reminders dialog button
                
                manager = RemindersManager()
                options = ["Show Reminders", "Clear Reminders", "Remove Specific Reminder"]
                choice = xbmcgui.Dialog().select("Reminders", options)
                if choice == 0:
                    reminders_text = manager.list_reminders()
                    xbmcgui.Dialog().ok("Reminders", reminders_text)
                elif choice == 1:
                    manager.clear_reminders()
                    xbmcgui.Dialog().ok("Reminders", "All reminders have been cleared.")
                elif choice == 2:
                    reminders = manager.load_reminders()
                    if not reminders:
                        xbmcgui.Dialog().ok("Reminders", "No reminders to remove.")
                    else:
                        display_list = [
                            f"{r['program']} on {r['channel']} at {__import__('time').strftime('%Y-%m-%d %H:%M', __import__('time').localtime(r['start_time']))}"
                            for r in reminders
                        ]
                        idx = xbmcgui.Dialog().select("Select Reminder to Remove", display_list)
                        if idx != -1:
                            r = reminders[idx]
                            manager.remove_reminder(r["channel"], r["program"], r["start_time"])
                            xbmcgui.Dialog().ok("Reminders", "Selected reminder has been removed.")
                return
            if control_id == 115:  # Browse Saved Links button
                FOLDERS_BASE_PATH = "special://userdata/addon_data/plugin.video.jet_guide/jet_guide_folders"
                folders_base = xbmcvfs.translatePath(FOLDERS_BASE_PATH)
                profile_path = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
                imported_path = profile_path + "jet_guide_imported.json"

                area_choice = xbmcgui.Dialog().select("Browse Links", ["Jet Guide Imported", "Saved Folders","INFO"])
                if area_choice == 2:  # Directions
                    readme_path = os.path.join(os.path.dirname(__file__), "README_tenbuttons_115.md")
                    if os.path.exists(readme_path):
                        with open(readme_path, "r", encoding="utf-8") as f:
                            directions = f.read()
                        xbmcgui.Dialog().textviewer("Directions", directions)
                    else:
                        xbmcgui.Dialog().ok("Directions", "Directions file not found.")
                    return
                if area_choice == 0:  # Jet Guide Imported
                    if xbmcvfs.exists(imported_path):
                        with xbmcvfs.File(imported_path, 'r') as f:
                            imported = json.loads(f.read())
                        if not imported:
                            xbmcgui.Dialog().ok('Jet Guide', 'No imported channels saved.')
                        else:
                            titles = [c.get('title', 'Unknown') for c in imported]
                            idx = xbmcgui.Dialog().select('Play Imported Channel', titles)
                            if idx >= 0:
                                link = imported[idx].get('link')
                                action = xbmcgui.Dialog().select('Choose Action', ['Play', 'Delete', 'Move to Folder'])
                                if action == 0 and link:
                                    xbmc.Player().play(link)
                                elif action == 1:
                                    del imported[idx]
                                    with xbmcvfs.File(imported_path, 'w') as f:
                                        f.write(json.dumps(imported, indent=2))
                                    xbmcgui.Dialog().ok('Jet Guide', 'Link deleted.')
                                elif action == 2:
                                    # Move to Folder
                                    FOLDERS_BASE_PATH = "special://userdata/addon_data/plugin.video.jet_guide/jet_guide_folders"
                                    folders_base = xbmcvfs.translatePath(FOLDERS_BASE_PATH)
                                    try:
                                        folders = [f for f in os.listdir(folders_base) if os.path.isdir(os.path.join(folders_base, f))]
                                    except Exception as e:
                                        debug_log(f"DEBUG: os.listdir failed for {folders_base}: {e}", level=xbmc.LOGERROR)
                                        folders = []
                                    if not folders:
                                        xbmcgui.Dialog().ok('Jet Guide', 'No folders found.')
                                    else:
                                        folder_idx = xbmcgui.Dialog().select('Select Folder', folders)
                                        if folder_idx >= 0:
                                            folder_path = os.path.join(folders_base, folders[folder_idx])
                                            links_file = os.path.join(folder_path, "links.json")
                                            # Load or create links.json
                                            if os.path.exists(links_file):
                                                with open(links_file, "r", encoding="utf-8") as f:
                                                    folder_links = json.load(f)
                                            else:
                                                folder_links = []
                                            folder_links.append(imported[idx])
                                            with open(links_file, "w", encoding="utf-8") as f:
                                                json.dump(folder_links, f, indent=2)
                                            xbmcgui.Dialog().ok('Jet Guide', 'Link moved to folder.')
                                            # Optionally remove from imported
                                            del imported[idx]
                                            with xbmcvfs.File(imported_path, 'w') as f:
                                                f.write(json.dumps(imported, indent=2))
                    else:
                        xbmcgui.Dialog().ok('Jet Guide', 'No imported channels saved.')
                elif area_choice == 1:  # Saved Folders
                    try:
                        folders = [f for f in os.listdir(folders_base) if os.path.isdir(os.path.join(folders_base, f))]
                    except Exception as e:
                        debug_log(f"DEBUG: os.listdir failed for {folders_base}: {e}", level=xbmc.LOGERROR)
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
                                        action = xbmcgui.Dialog().select('Choose Action', ['Play', 'Delete'])
                                        if action == 0 and link:
                                            xbmc.Player().play(link)
                                        elif action == 1:
                                            del links[idx]
                                            with open(links_file, "w", encoding="utf-8") as f:
                                                json.dump(links, f, indent=2)
                                            xbmcgui.Dialog().ok('Jet Guide', 'Link deleted.')
                            else:
                                xbmcgui.Dialog().ok('Jet Guide', 'No links.json found in folder.')
                    return

            # Handle widget tile clicks (control 210)
            if control_id == 210:
                if self.widget_list:
                    item = self.widget_list.getSelectedItem()
                    if item:
                        widget_link = item.getProperty("widget_link")
                        if widget_link:
                            play_saved_jet_guide_link(widget_link)
                return



            if control_id == 199:
                player = xbc.Player()
                stream_url = None
                try:
                    stream_url = player.getPlayingFile()
                except Exception as e:
                    stream_url = None

                # Detect platform for path selection
                is_android = "ANDROID_DATA" in os.environ or "ANDROID_ROOT" in os.environ

                # Get platform-specific paths from settings
                if is_android:
                    ffmpeg_path = xbcaddon.Addon().getSetting("android_mpv_path") or "/data/data/com.termux/files/usr/bin/mpv"
                    mpv_path = xbcaddon.Addon().getSetting("android_mpv_path") or "/data/data/com.termux/files/usr/bin/mpv"
                    default_recording_path = xbcaddon.Addon().getSetting("android_recording_path") or "/data/data/com.termux/files/home/recordings"
                else:
                    ffmpeg_path = xbcaddon.Addon().getSetting("ffmpeg_path") or r"C:\ffmpeg\bin\ffmpeg.exe"
                    mpv_path = xbcaddon.Addon().getSetting("mpv_path") or r"C:\Users\user\Desktop\mpv_player\mpv.exe"
                    default_recording_path = xbcaddon.Addon().getSetting("recording_path") or r"C:\Users\home\Videos"

                choice = xbcgui.Dialog().select(
                    "Choose Action",
                    ["Play Stream in mpv", "Record Stream (ffmpeg)", "Play Multiple Streams in mpv ([COLORred]BROKEN[/COLOR])", "Stop Recording", "Watch Recording", "Directions"]
                )
                if choice == -1:
                    return
                if choice == 5:  # Directions
                    readme_path = os.path.join(os.path.dirname(__file__), "README_tenbuttons_199.md")
                    if os.path.exists(readme_path):
                        with open(readme_path, "r", encoding="utf-8") as f:
                            directions = f.read()
                        xbmcgui.Dialog().textviewer("Directions", directions)
                    else:
                        xbmcgui.Dialog().ok("Directions", "Directions file not found.")
                    return
                
                if choice in [0, 1, 2, 3]:
                    if not stream_url or not (str(stream_url).startswith("http") or str(stream_url).endswith(".m3u8")):
                        xbc.log(f"DEBUG: Invalid or no current stream: {stream_url}", level=xbc.LOGERROR)
                        xbmcgui.Dialog().ok("Error", "No valid stream is currently playing. Start a stream to use this option.")
                        return
                url = stream_url
                headers = ""
                header_dict = {}
                # Do NOT strip headers from stream_url; pass full value to get_resolved_url

                def get_resolved_url(url):
                    import time
                    import urllib.parse
                    resolved_url = None
                    resolved_headers = {}
                    if url.startswith("plugin://"):
                        try:
                            list_item = xbcgui.ListItem()
                            list_item.setPath(url)
                            player = xbc.Player()
                            player.play(url, list_item)
                            start_time = time.time()
                            while time.time() - start_time < 10 and not player.isPlaying():
                                time.sleep(0.1)
                            if player.isPlaying():
                                resolved_url = player.getPlayingFile()
                                xbc.log(f"DEBUG: Resolved URL from player: {resolved_url}", level=xbc.LOGINFO)
                                player.stop()
                            else:
                                xbc.log(f"DEBUG: Player failed to start for URL: {url}", level=xbc.LOGWARNING)
                        except Exception as e:
                            xbc.log(f"DEBUG: Error resolving plugin URL {url}: {str(e)}", level=xbc.LOGERROR)
                        # Try extracting direct URL from plugin parameters
                        if not resolved_url:
                            try:
                                parsed_url = urllib.parse.urlparse(url)
                                query_params = urllib.parse.parse_qs(parsed_url.query)
                                if 'urls' in query_params and query_params['urls'][0].startswith("direct://"):
                                    resolved_url = query_params['urls'][0].replace("direct://", "")
                                    xbc.log(f"DEBUG: Extracted direct URL from plugin: {resolved_url}", level=xbc.LOGINFO)
                            except Exception as e:
                                xbc.log(f"DEBUG: Error extracting direct URL from plugin: {str(e)}", level=xbc.LOGERROR)
                    else:
                        resolved_url = url
                        xbc.log(f"DEBUG: Using provided URL as resolved: {resolved_url}", level=xbc.LOGINFO)

                    # Extract headers if present
                    if resolved_url and '|' in resolved_url:
                        url_parts = resolved_url.split('|', 1)
                        resolved_url = url_parts[0]
                        try:
                            # Kodi-style: Referer=...&Origin=...&User-Agent=...
                            header_string = url_parts[1]
                            for header in header_string.split('&'):
                                if '=' in header:
                                    key, value = header.split('=', 1)
                                    resolved_headers[key.lower()] = urllib.parse.unquote(value)
                        except Exception as e:
                            xbc.log(f"DEBUG: Error parsing headers from URL: {str(e)}", level=xbc.LOGWARNING)

                    return resolved_url, resolved_headers

                if choice == 0:
                    resolved_url, resolved_headers = get_resolved_url(url)
                    if not resolved_url or not resolved_url.startswith("http"):
                        xbc.log(f"DEBUG: Invalid or unresolved stream URL: {resolved_url}", level=xbc.LOGERROR)
                        xbcgui.Dialog().ok("Error", "Unable to resolve a valid stream URL. Try playing the stream in Kodi first or use a direct URL.")
                        return

                    # If resolved_url is a proxy URL, extract the real stream URL for mpv
                    import re
                    proxy_match = re.match(r"http://127\.0\.0\.1:\d+\?url=(http.*)", resolved_url)
                    if proxy_match:
                        resolved_url = proxy_match.group(1)

                    if xbc.getCondVisibility('system.platform.android'):
                        package = 'is.xyz.mpv'
                        intent = 'android.intent.action.VIEW'
                        # Append headers to URL if needed
                        import urllib.parse
                        android_url = resolved_url
                        if resolved_headers:
                            # Use Kodi-style headers (not percent-encoded) for Android mpv
                            header_params = "&".join([f"{k}={v}" for k, v in resolved_headers.items() if k.lower() in ["user-agent", "referer", "origin"]])
                            if header_params:
                                android_url += f"|{header_params}"
                            # If headers present, try sending only the URL (no Kodi-style headers) for Android mpv
                            if header_params:
                                android_url = resolved_url

                        # Try launching mpv via intent with explicit activity
                        try:
                            # Use raw android_url, do not quote
                            try:
                                xbc.executebuiltin(f'StartAndroidActivity("{package}","{intent}","video/*","{android_url}")')
                                xbc.log(f"DEBUG: Attempted to launch mpv with intent URL: {android_url}", level=xbc.LOGINFO)
                            except Exception as e:
                                xbc.log(f"DEBUG: Failed to launch mpv intent: {str(e)}", level=xbc.LOGERROR)
                                xbcgui.Dialog().ok("Error", f"Failed to launch mpv app: {str(e)}")
                            xbcgui.Dialog().notification("mpv", "Stream sent to mpv app", xbcgui.NOTIFICATION_INFO, 2000)
                        except Exception as e:
                            xbc.log(f"DEBUG: Failed to launch mpv intent: {str(e)}", level=xbc.LOGERROR)
                            xbcgui.Dialog().ok("Error", f"Failed to launch mpv: {str(e)}\nManually enter this URL in mpv:\n{android_url}")
                        return
                    else:
                        # Non-Android handling
                        mpv_args = []
                        if resolved_headers:
                            mpv_headers = ",".join([f"{k.title().replace('-', '-')}: {v}" for k, v in resolved_headers.items()])
                            mpv_args += [f'--http-header-fields={mpv_headers}']
                        mpv_command = [mpv_path] + mpv_args + [resolved_url]
                        xbc.log(f"DEBUG: Launching mpv with command: {mpv_command}", level=xbc.LOGINFO)
                        try:
                            if sys.platform.startswith('win'):
                                CREATE_NEW_CONSOLE = 0x00000010
                                proc = subprocess.Popen(mpv_command, creationflags=CREATE_NEW_CONSOLE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                            else:
                                proc = subprocess.Popen(mpv_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                            time.sleep(1)
                            if proc.poll() is None:
                                xbc.log(f"DEBUG: mpv process started with PID: {proc.pid}", level=xbc.LOGINFO)
                                xbcgui.Dialog().notification("mpv", "Stream opened in mpv", xbcgui.NOTIFICATION_INFO, 2000)
                            else:
                                stdout, stderr = proc.communicate(timeout=5)
                                xbc.log(f"DEBUG: mpv stdout: {stdout}", level=xbc.LOGINFO)
                                xbc.log(f"DEBUG: mpv stderr: {stderr}", level=xbc.LOGINFO)
                                raise subprocess.CalledProcessError(proc.returncode, mpv_command, stdout, stderr)
                        except Exception as e:
                            xbc.log(f"DEBUG: Failed to launch mpv: {str(e)}", level=xbc.LOGERROR)
                            xbcgui.Dialog().ok("Error", f"Failed to launch mpv: {str(e)}")
                        return

                elif choice == 1:
                    # Use the already detected platform and paths
                    folder_path = xbcaddon.Addon().getSetting("android_recording_path" if is_android else "recording_path")
                    if not folder_path:
                        folder_path = default_recording_path
                    
                    # For Android, try to create the directory if it doesn't exist
                    if is_android and not os.path.isdir(folder_path):
                        try:
                            os.makedirs(folder_path, exist_ok=True)
                            xbc.log(f"DEBUG: Created Android recording directory: {folder_path}", level=xbc.LOGINFO)
                        except Exception as e:
                            xbc.log(f"DEBUG: Failed to create Android recording directory {folder_path}: {str(e)}", level=xbc.LOGERROR)
                    
                    # If folder still doesn't exist or isn't accessible, prompt user
                    if not folder_path or not os.path.isdir(folder_path):
                        folder_path = xbcgui.Dialog().browse(0, "Select Output Folder", "files")
                        if not folder_path:
                            xbc.log(f"DEBUG: No folder selected for recording", level=xbc.LOGINFO)
                            return
                    
                    filename = xbcgui.Dialog().input("Enter filename (e.g. recorded.ts)", type=xbcgui.INPUT_ALPHANUM)
                    if not filename:
                        xbc.log(f"DEBUG: No filename provided for recording", level=xbc.LOGINFO)
                        return
                    if not filename.lower().endswith(".ts"):
                        filename += ".ts"
                    output_path = os.path.join(folder_path, filename)
                    
                    # Handle file overwrite with Kodi dialog
                    if os.path.exists(output_path):
                        if not xbcgui.Dialog().yesno("Overwrite File", f"File '{filename}' already exists. Overwrite it?"):
                            xbc.log(f"DEBUG: User chose not to overwrite file {output_path}", level=xbc.LOGINFO)
                            return
                        try:
                            os.remove(output_path)
                            xbc.log(f"DEBUG: Deleted existing file {output_path}", level=xbc.LOGINFO)
                        except Exception as e:
                            xbc.log(f"DEBUG: Failed to delete existing file {output_path}: {str(e)}", level=xbc.LOGERROR)
                            xbcgui.Dialog().ok("Error", f"Cannot overwrite {filename}: {str(e)}")
                            return
                    
                    # Verify folder is writable
                    try:
                        temp_file = os.path.join(folder_path, f"test_{random.randint(1000,9999)}.tmp")
                        with open(temp_file, 'w') as f:
                            f.write("test")
                        os.remove(temp_file)
                    except Exception as e:
                        xbc.log(f"DEBUG: Output folder {folder_path} is not writable: {str(e)}", level=xbc.LOGERROR)
                        xbcgui.Dialog().ok("Error", f"Cannot write to folder: {str(e)}")
                        return
                    
                    if is_android:
                        # Android recording using mpv through Termux
                        xbc.log(f"DEBUG: Android detected, using mpv for recording", level=xbc.LOGINFO)
                        xbc.log(f"DEBUG: Using mpv path: {mpv_path}", level=xbc.LOGINFO)
                        
                        # Find mpv executable on Android/Termux
                        def find_android_mpv():
                            # Show debug info via notifications instead of logs
                            xbcgui.Dialog().notification("Debug", f"Starting mpv search...", xbcgui.NOTIFICATION_INFO, 2000)
                            
                            # Common Termux paths for mpv
                            possible_paths = [
                                "/data/data/com.termux/files/usr/bin/mpv",
                                "/system/bin/mpv",
                                "/system/xbin/mpv",
                                "/data/data/com.termux/files/usr/local/bin/mpv",
                                mpv_path  # User-specified path
                            ]
                            
                            # Try to use 'which' command to find mpv
                            try:
                                which_result = subprocess.run(["which", "mpv"], capture_output=True, text=True, timeout=5)
                                if which_result.returncode == 0 and which_result.stdout.strip():
                                    which_path = which_result.stdout.strip()
                                    possible_paths.insert(0, which_path)  # Add to front of list
                                    xbcgui.Dialog().notification("Debug", f"which found: {which_path}", xbcgui.NOTIFICATION_INFO, 3000)
                            except Exception as e:
                                xbcgui.Dialog().notification("Debug", f"which failed: {str(e)}", xbcgui.NOTIFICATION_ERROR, 3000)
                            
                            # Try each possible path
                            tested_paths = []
                            for test_path in possible_paths:
                                if not test_path:
                                    continue
                                tested_paths.append(test_path)
                                try:
                                    test_proc = subprocess.run([test_path, "--version"], capture_output=True, text=True, timeout=5)
                                    if test_proc.returncode == 0:
                                        xbcgui.Dialog().notification("Debug", f"Found working: {test_path}", xbcgui.NOTIFICATION_INFO, 4000)
                                        return test_path
                                except FileNotFoundError:
                                    xbcgui.Dialog().notification("Debug", f"Not found: {test_path}", xbcgui.NOTIFICATION_WARNING, 2000)
                                except Exception as e:
                                    xbcgui.Dialog().notification("Debug", f"Error at {test_path}: {str(e)}", xbcgui.NOTIFICATION_ERROR, 3000)
                            
                            # Show all tested paths if nothing worked
                            all_paths = "\n".join(tested_paths[:3])  # Show first 3 paths
                            xbcgui.Dialog().ok("mpv Search Results", f"Tested paths:\n{all_paths}\n\nNone worked. Try manually setting the path in Android settings.")
                            return None
                        
                        # Find working mpv path
                        working_mpv_path = find_android_mpv()
                        if not working_mpv_path:
                            return
                        
                        # Update mpv_path to the working path
                        mpv_path = working_mpv_path
                        
                        # Build mpv recording command for Android/Termux
                        mpv_command = [
                            mpv_path,
                            "--no-video",  # Don't display video during recording
                            "--ao=null",   # No audio output during recording
                            "--stream-record=" + output_path,
                            "--no-terminal",  # Reduce terminal output
                            "--msg-level=all=warn",  # Reduce log verbosity
                            "--idle=no",   # Exit when done
                        ]
                        
                        # Add headers if present
                        if headers:
                            # Format headers properly for mpv
                            header_list = []
                            for k, v in header_dict.items():
                                if k.lower() in ["referer", "user-agent", "origin"]:
                                    header_list.append(f"{k}: {v}")
                            if header_list:
                                mpv_command.extend(["--http-header-fields=" + ",".join(header_list)])
                        
                        # Add the stream URL
                        mpv_command.append(url)
                        
                        xbc.log(f"DEBUG: Launching mpv recording with command: {' '.join(mpv_command)}", level=xbc.LOGINFO)
                        
                        try:
                            # Use Termux-compatible process creation
                            ffmpeg_proc = subprocess.Popen(
                                mpv_command,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True
                            )
                            xbc.log(f"DEBUG: mpv recording process started with PID: {ffmpeg_proc.pid}", level=xbc.LOGINFO)
                            xbcgui.Dialog().notification("Record", f"Recording started: {filename}\nUsing mpv on Android", xbcgui.NOTIFICATION_INFO, 3000)
                            
                            # Monitor process for Android
                            def monitor_android_recording():
                                global ffmpeg_proc
                                try:
                                    stdout, stderr = ffmpeg_proc.communicate(timeout=None)
                                    exit_code = ffmpeg_proc.returncode if ffmpeg_proc is not None else 'unknown'
                                    if ffmpeg_proc is not None and exit_code == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                                        xbc.log(f"DEBUG: Android recording completed successfully: {output_path}", level=xbc.LOGINFO)
                                        xbcgui.Dialog().notification("Record", f"Recording completed: {filename}", xbcgui.NOTIFICATION_INFO, 5000)
                                    else:
                                        xbc.log(f"DEBUG: mpv recording failed with exit code {exit_code}", level=xbc.LOGERROR)
                                        xbc.log(f"DEBUG: mpv stderr: {stderr}", level=xbc.LOGERROR)
                                        xbcgui.Dialog().notification("Record", f"Recording failed: Exit code {exit_code}", xbcgui.NOTIFICATION_ERROR, 5000)
                                except Exception as e:
                                    xbc.log(f"DEBUG: Error monitoring mpv recording process: {str(e)}", level=xbc.LOGERROR)
                                    xbcgui.Dialog().notification("Record", f"Recording error: {str(e)}", xbcgui.NOTIFICATION_ERROR, 5000)
                                finally:
                                    ffmpeg_proc = None  # Reset after completion
                            threading.Thread(target=monitor_android_recording, daemon=True).start()
                            
                        except Exception as e:
                            xbc.log(f"DEBUG: Failed to launch mpv recording: {str(e)}", level=xbc.LOGERROR)
                            xbcgui.Dialog().ok("Error", f"Failed to launch mpv recording: {str(e)}")
                    
                    else:
                        # PC recording using ffmpeg (existing code)
                        xbc.log(f"DEBUG: PC detected, using ffmpeg for recording", level=xbc.LOGINFO)
                        
                        # Verify ffmpeg exists
                        if not os.path.isfile(ffmpeg_path):
                            xbc.log(f"DEBUG: ffmpeg not found at {ffmpeg_path}", level=xbc.LOGERROR)
                            xbcgui.Dialog().ok("Error", f"ffmpeg not found at {ffmpeg_path}")
                            return
                        
                        # Build ffmpeg command
                        # Extract headers from url if present
                        ffmpeg_headers = ""
                        ffmpeg_url = url
                        header_string = ""
                        if "|" in url:
                            ffmpeg_url, header_string = url.split("|", 1)
                            header_lines = []
                            import urllib.parse
                            for header in header_string.split("&"):
                                if "=" in header:
                                    k, v = header.split("=", 1)
                                    # Remove quotes, ensure proper line endings, and strip trailing slash for Referer/Origin
                                    clean_v = urllib.parse.unquote(v)
                                    if k.lower() in ["referer", "origin"] and clean_v.endswith("/"):
                                        clean_v = clean_v[:-1]
                                    header_lines.append(f"{k}: {clean_v}\\r\\n")
                            if header_lines:
                                ffmpeg_headers = "".join(header_lines)
                        ffmpeg_command = [
                            ffmpeg_path,
                            "-loglevel", "verbose",
                        ]
                        if ffmpeg_headers:
                            ffmpeg_command += ["-headers", ffmpeg_headers]
                        # Add explicit user_agent and referer flags if present
                        for k, v in [("user-agent", None), ("referer", None)]:
                            for header in header_string.split("&"):
                                if "=" in header:
                                    hk, hv = header.split("=", 1)
                                    if hk.lower() == k:
                                        import urllib.parse
                                        clean_v = urllib.parse.unquote(hv)
                                        if k == "user-agent":
                                            ffmpeg_command += ["-user_agent", clean_v]
                                        elif k == "referer":
                                            ffmpeg_command += ["-referer", clean_v]
                        ffmpeg_command += [
                            "-i", ffmpeg_url,
                            "-c:v", "copy",
                            "-c:a", "copy",
                            "-f", "mpegts",
                            output_path
                        ]
                        xbc.log(f"DEBUG: Launching ffmpeg with command: {' '.join(ffmpeg_command)}", level=xbc.LOGINFO)
                        CREATE_NEW_CONSOLE = 0x00000010
                        try:
                            ffmpeg_proc = subprocess.Popen(
                                ffmpeg_command,
                                creationflags=0x00000010
                            )
                            xbc.log(f"DEBUG: ffmpeg process started with PID: {ffmpeg_proc.pid}", level=xbc.LOGINFO)
                            xbcgui.Dialog().notification("Record", f"Recording started: {filename}\nCheck console for progress", xbcgui.NOTIFICATION_INFO, 3000)
                            
                            # Monitor process
                            def monitor_process():
                                global ffmpeg_proc
                                try:
                                    stdout, stderr = ffmpeg_proc.communicate()
                                    exit_code = ffmpeg_proc.returncode if ffmpeg_proc is not None else 'unknown'
                                    if ffmpeg_proc is not None and exit_code == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                                        xbc.log(f"DEBUG: Recording completed successfully: {output_path}", level=xbc.LOGINFO)
                                        xbcgui.Dialog().notification("Record", f"Recording completed: {filename}", xbcgui.NOTIFICATION_INFO, 5000)
                                    else:
                                        xbc.log(f"DEBUG: ffmpeg process failed with exit code {exit_code}", level=xbc.LOGERROR)
                                        xbc.log(f"DEBUG: ffmpeg stdout: {stdout}", level=xbc.LOGERROR)
                                        xbc.log(f"DEBUG: ffmpeg stderr: {stderr}", level=xbc.LOGERROR)
                                        error_msg = "ffmpeg failed:\n"
                                        if stderr:
                                            error_msg += stderr
                                        elif stdout:
                                            error_msg += stdout
                                        else:
                                            error_msg += "No error output. Try running the command manually in a terminal for more details."
                                        xbcgui.Dialog().ok("ffmpeg Error Output", error_msg)
                                except Exception as e:
                                    xbc.log(f"DEBUG: Error monitoring ffmpeg process: {str(e)}", level=xbc.LOGERROR)
                                    xbcgui.Dialog().notification("Record", f"Recording error: {str(e)}", xbcgui.NOTIFICATION_ERROR, 5000)
                                finally:
                                    ffmpeg_proc = None  # Reset after completion
                            threading.Thread(target=monitor_process, daemon=True).start()
                        except Exception as e:
                            xbc.log(f"DEBUG: Failed to launch ffmpeg: {str(e)}", level=xbc.LOGERROR)
                            xbcgui.Dialog().ok("Error", f"Failed to launch ffmpeg: {str(e)}")
                    return

                elif choice == 4:
                    # Watch Recording
                    folder_path = xbmcaddon.Addon().getSetting("recording_path")
                    if not folder_path or not os.path.isdir(folder_path):
                        xbcgui.Dialog().ok("Error", "Recording path is not set or invalid.")
                        return
                    files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
                    if not files:
                        xbcgui.Dialog().ok("Error", "No recordings found in the folder.")
                        return
                    idx = xbcgui.Dialog().select("Select Recording to Play", files)
                    if idx == -1:
                        return
                    file_to_play = os.path.join(folder_path, files[idx])
                    xbmc.Player().play(file_to_play)
                    xbcgui.Dialog().notification("Kodi", f"Playing: {files[idx]}", xbcgui.NOTIFICATION_INFO, 3000)
                    return

                elif choice == 3:
                    try:
                        if ffmpeg_proc and ffmpeg_proc.poll() is None:
                            ffmpeg_proc.terminate()
                            try:
                                ffmpeg_proc.wait(timeout=5)
                                xbc.log(f"DEBUG: ffmpeg process (PID: {ffmpeg_proc.pid}) terminated successfully", level=xbc.LOGINFO)
                                xbcgui.Dialog().notification("Record", "Recording stopped.", xbcgui.NOTIFICATION_INFO, 3000)
                            except subprocess.TimeoutExpired:
                                ffmpeg_proc.kill()
                                xbc.log(f"DEBUG: ffmpeg process (PID: {ffmpeg_proc.pid}) forcibly killed after timeout", level=xbc.LOGWARNING)
                                xbcgui.Dialog().notification("Record", "Recording forcibly stopped.", xbcgui.NOTIFICATION_INFO, 3000)
                            ffmpeg_proc = None
                        else:
                            xbc.log(f"DEBUG: No active ffmpeg process to stop", level=xbc.LOGINFO)
                            xbcgui.Dialog().notification("Record", "No active recording to stop.", xbcgui.NOTIFICATION_INFO, 3000)
                    except Exception as e:
                        xbc.log(f"DEBUG: Error stopping ffmpeg process: {str(e)}", level=xbc.LOGERROR)
                        xbcgui.Dialog().notification("Record", f"Error stopping recording: {str(e)}", xbcgui.NOTIFICATION_ERROR, 3000)
                    return

                elif choice == 2:
                    temp_file = xbcvfs.translatePath("special://temp/resolved_streams.json")
                    resolved_streams = []
                    try:
                        response = requests.head(url, headers=header_dict, timeout=5, allow_redirects=True)
                        if response.status_code == 200:
                            xbc.log(f"DEBUG: Currently playing URL {url} is accessible", level=xbc.LOGINFO)
                            resolved_streams.append({"url": url, "headers": header_dict, "title": "Currently Playing Stream"})
                        else:
                            xbc.log(f"DEBUG: Currently playing URL {url} returned status {response.status_code}", level=xbc.LOGWARNING)
                            xbcgui.Dialog().ok("Error", f"Currently playing stream is not accessible: {url}. Status: {response.status_code}")
                            return
                    except Exception as e:
                        xbc.log(f"DEBUG: Failed to access currently playing URL {url}: {str(e)}", level=xbc.LOGERROR)
                        xbcgui.Dialog().ok("Error", f"Failed to access currently playing stream: {url}. Error: {str(e)}")
                        return
                    try:
                        xbc.log(f"DEBUG: Attempting to read {JET_GUIDE_IMPORTED_PATH}", level=xbc.LOGINFO)
                        if xbcvfs.exists(JET_GUIDE_IMPORTED_PATH):
                            with xbcvfs.File(JET_GUIDE_IMPORTED_PATH, "r") as f:
                                links = json.loads(f.read())
                            xbc.log(f"DEBUG: Loaded {len(links)} entries from jet_guide_imported.json: {json.dumps(links, indent=2)}", level=xbc.LOGINFO)
                        else:
                            xbc.log(f"DEBUG: File {JET_GUIDE_IMPORTED_PATH} does not exist", level=xbc.LOGERROR)
                            xbcgui.Dialog().ok("Error", f"No saved streams found at {JET_GUIDE_IMPORTED_PATH}.")
                            return
                    except Exception as e:
                        xbc.log(f"DEBUG: Failed to load jet_guide_imported.json: {str(e)}", level=xbc.LOGERROR)
                        xbcgui.Dialog().ok("Error", f"Failed to load saved streams: {str(e)}")
                        return
                    valid_links = [l for l in links if isinstance(l, dict) and "link" in l and (l["link"].startswith("http") or l["link"].endswith(".m3u8") or l["link"].startswith("plugin://"))]
                    xbc.log(f"DEBUG: Found {len(valid_links)} valid streams after filtering", level=xbc.LOGINFO)
                    if not valid_links:
                        xbcgui.Dialog().ok("Error", f"No valid streams found in jet_guide_imported.json. Ensure streams have 'link' field with http, .m3u8, or plugin:// URLs.\n\nContents: {json.dumps(links, indent=2)}")
                        return
                    titles = [l.get("title", "Untitled Stream") for l in valid_links]
                    selected_indices = xbcgui.Dialog().multiselect("Select ONE Additional Stream to Play", titles)
                    if not selected_indices or len(selected_indices) != 1:
                        xbcgui.Dialog().ok("Error", "You must select exactly one additional stream.")
                        return
                    for idx in selected_indices:
                        plugin_url = valid_links[idx]["link"]
                        stream_title = valid_links[idx].get("title", "Untitled Stream")
                        xbc.log(f"DEBUG: Processing stream: {stream_title} ({plugin_url})", level=xbc.LOGINFO)
                        if plugin_url.startswith("http") and (plugin_url.endswith(".m3u8") or plugin_url.endswith(".mp4") or plugin_url.endswith(".ts")):
                            plugin_url = f"plugin://plugin.video.madtitansports/sportjetextractors/play?urls=direct://{plugin_url}"
                            xbc.log(f"DEBUG: Wrapped HTTP URL as plugin URL: {plugin_url}", level=xbc.LOGINFO)
                        resolved_url, resolved_headers = get_resolved_url(plugin_url)
                        if not resolved_url:
                            xbc.log(f"DEBUG: Failed to resolve stream via playback: {stream_title}", level=xbc.LOGWARNING)
                            fallback_url = None
                            fallback_headers = {}
                            if plugin_url.startswith("plugin://") and "/play_video/" in plugin_url:
                                try:
                                    b64 = plugin_url.split("/play_video/")[1]
                                    decoded = base64.urlsafe_b64decode(b64).decode("utf-8")
                                    data = json.loads(decoded)
                                    if "sportjetextractors" in data and data["sportjetextractors"]:
                                        fallback_url = data["sportjetextractors"][0]
                                        fallback_headers = header_dict
                                        xbc.log(f"DEBUG: Fallback to sportjetextractors URL: {fallback_url}", level=xbc.LOGINFO)
                                    elif "link" in data and data["link"].startswith("http"):
                                        fallback_url = data["link"]
                                        fallback_headers = {}
                                        if "|" in fallback_url:
                                            fallback_url, headers_str = fallback_url.split("|", 1)
                                            for part in headers_str.split("&"):
                                                if "=" in part:
                                                    k, v = part.split("=", 1)
                                                    fallback_headers[k.lower()] = urllib.parse.unquote(v)
                                        xbc.log(f"DEBUG: Fallback to link URL: {fallback_url}", level=xbc.LOGINFO)
                                    if fallback_url and fallback_url.lower().endswith((".m3u8", ".mp4", ".ts")):
                                        try:
                                            response = requests.head(fallback_url, headers=fallback_headers or header_dict, timeout=5, allow_redirects=True)
                                            if response.status_code == 200:
                                                xbc.log(f"DEBUG: Fallback URL {fallback_url} is accessible and valid stream", level=xbc.LOGINFO)
                                                resolved_url = fallback_url
                                                resolved_headers = fallback_headers
                                            else:
                                                xbc.log(f"DEBUG: Fallback URL {fallback_url} returned status {response.status_code}", level=xbc.LOGWARNING)
                                        except Exception as e:
                                            xbc.log(f"DEBUG: Failed to access fallback URL {fallback_url}: {str(e)}", level=xbc.LOGERROR)
                                except Exception as e:
                                    xbc.log(f"DEBUG: Failed to decode plugin URL for fallback: {str(e)}", level=xbc.LOGWARNING)
                            if not resolved_url:
                                xbc.log(f"DEBUG: Prompting manual URL input for stream: {stream_title}", level=xbc.LOGINFO)
                                manual_url = xbcgui.Dialog().input(f"Failed to resolve stream: {stream_title}\nEnter the stream URL manually (e.g., from VLC):", type=xbcgui.INPUT_ALPHANUM)
                                if manual_url and manual_url.startswith("http") and manual_url.lower().endswith((".m3u8", ".mp4", ".ts")):
                                    try:
                                        response = requests.head(manual_url, headers=header_dict, timeout=5, allow_redirects=True)
                                        if response.status_code == 200:
                                            xbc.log(f"DEBUG: Manual URL {manual_url} is accessible", level=xbc.LOGINFO)
                                            resolved_url = manual_url
                                            resolved_headers = header_dict
                                        else:
                                            xbc.log(f"DEBUG: Manual URL {manual_url} returned status {response.status_code}", level=xbc.LOGWARNING)
                                            xbcgui.Dialog().ok("Error", f"Manual URL is not accessible: {manual_url}. Status: {response.status_code}")
                                            continue
                                    except Exception as e:
                                        xbc.log(f"DEBUG: Failed to access manual URL {manual_url}: {str(e)}", level=xbc.LOGERROR)
                                        xbcgui.Dialog().ok("Error", f"Failed to access manual URL: {manual_url}. Error: {str(e)}")
                                        continue
                                else:
                                    xbcgui.Dialog().ok("Error", f"Invalid or no URL provided for {stream_title}. Try playing it in VLC to verify.")
                                    continue
                        if resolved_url == url:
                            xbcgui.Dialog().ok("Error", f"Stream {stream_title} resolved to the same URL as the current stream: {resolved_url}")
                            continue
                        if xbcgui.Dialog().yesno("Save Stream", f"Stream resolved: {resolved_url}\nSave to temporary file for multi-stream playback?"):
                            resolved_streams.append({"url": resolved_url, "headers": resolved_headers, "title": stream_title})
                            xbc.log(f"DEBUG: Saved resolved stream: {resolved_url}", level=xbc.LOGINFO)
                        else:
                            xbc.log(f"DEBUG: User chose not to save stream: {resolved_url}", level=xbc.LOGINFO)
                    try:
                        with xbcvfs.File(temp_file, "w") as f:
                            f.write(json.dumps(resolved_streams, indent=2))
                        xbc.log(f"DEBUG: Saved resolved streams to {temp_file}: {json.dumps(resolved_streams, indent=2)}", level=xbc.LOGINFO)
                    except Exception as e:
                        xbc.log(f"DEBUG: Failed to save resolved streams to {temp_file}: {str(e)}", level=xbc.LOGERROR)
                        xbcgui.Dialog().ok("Error", f"Failed to save resolved streams: {str(e)}")
                        return
                    if len(resolved_streams) < 2:
                        xbcgui.Dialog().ok("Error", "Fewer than two streams could be resolved. At least two valid streams are required.")
                        return
                    mpv_args = []
                    all_headers = []
                    for stream in resolved_streams:
                        all_headers.extend([f"{k.title().replace('-', '-')}: {v}" for k, v in stream["headers"].items()])
                    if all_headers:
                        mpv_args += [f'--http-header-fields={",".join(set(all_headers))}']
                    video_filters = []
                    for i in range(len(resolved_streams)):
                        video_filters.append(f"[vid{i+1}]scale=1280:720[v{i}];")
                    num_streams = len(resolved_streams)
                    if num_streams <= 4:
                        video_filters.append("".join(f"[v{i}]" for i in range(num_streams)) + f"hstack=inputs={num_streams}[vo];")
                    else:
                        grid_cols = 2
                        grid_rows = (num_streams + 1) // 2
                        video_filters.append("".join(f"[v{i}]" for i in range(num_streams)) + f"xstack=inputs={num_streams}:layout=0_0|0_h0|w0_0|w0_h0[vo];")
                    audio_titles = [stream["title"] for stream in resolved_streams]
                    audio_choice = xbcgui.Dialog().select("Select which stream's audio to use", audio_titles)
                    if audio_choice == -1:
                        xbcgui.Dialog().ok("Error", "No audio stream selected.")
                        return
                    audio_filters = [f"[aid{audio_choice+1}]anull[ao]"]
                    lavfi_filter = "".join(video_filters) + "".join(audio_filters)
                    for i in range(1, num_streams):
                        stream_url = resolved_streams[i]["url"]
                        if "|" in stream_url:
                            stream_url = stream_url.split("|", 1)[0]
                        mpv_args.append(f'--external-file={stream_url}')
                    mpv_args.append(f'--lavfi-complex={lavfi_filter}')
                    first_stream_url = resolved_streams[0]["url"]
                    if "|" in first_stream_url:
                        first_stream_url = first_stream_url.split("|", 1)[0]
                    mpv_command = [mpv_path] + mpv_args + [first_stream_url]
                    xbc.log(f"DEBUG: Launching mpv with command: {mpv_command}", level=xbc.LOGINFO)
                    CREATE_NEW_CONSOLE = 0x00000010
                    try:
                        proc = subprocess.Popen(mpv_command, creationflags=CREATE_NEW_CONSOLE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        xbcgui.Dialog().notification("mpv", f"Starting {num_streams} streams in mpv...", xbcgui.NOTIFICATION_INFO, 2000)
                        time.sleep(2)
                        if proc.poll() is None:
                            xbc.log(f"DEBUG: mpv process started with PID: {proc.pid}", level=xbc.LOGINFO)
                            xbcgui.Dialog().notification("mpv", f"Playing {num_streams} streams in mpv", xbcgui.NOTIFICATION_INFO, 2000)
                        else:
                            stdout, stderr = proc.communicate(timeout=5)
                            xbc.log(f"DEBUG: mpv stdout: {stdout}", level=xbc.LOGINFO)
                            xbc.log(f"DEBUG: mpv stderr: {stderr}", level=xbc.LOGINFO)
                            raise subprocess.CalledProcessError(proc.returncode, mpv_command, stdout, stderr)
                    except Exception as e:
                        xbc.log(f"DEBUG: Caught exception launching mpv: {str(e)}", level=xbc.LOGERROR)
                        time.sleep(2)
                        if proc.poll() is None:
                            xbc.log(f"DEBUG: mpv process is running despite exception, PID: {proc.pid}", level=xbc.LOGINFO)
                            xbcgui.Dialog().notification("mpv", f"Playing {num_streams} streams in mpv", xbcgui.NOTIFICATION_INFO, 2000)
                        else:
                            xbcgui.Dialog().ok("Error", f"Failed to launch mpv: {str(e)}")
                            xbcgui.Dialog().notification("mpv", "Multi-stream playback failed. Trying to play streams individually.", xbcgui.NOTIFICATION_WARNING, 2000)
                            for stream in resolved_streams:
                                mpv_args_single = []
                                if stream["headers"]:
                                    mpv_headers = ",".join([f"{k.title().replace('-', '-')}: {v}" for k, v in stream["headers"].items()])
                                    mpv_args_single += [f'--http-header-fields={mpv_headers}']
                                stream_url = stream["url"]
                                if "|" in stream_url:
                                    stream_url = stream_url.split("|", 1)[0]
                                mpv_command_single = [mpv_path] + mpv_args_single + [stream_url]
                                xbc.log(f"DEBUG: Launching mpv single stream with command: {mpv_command_single}", level=xbc.LOGINFO)
                                try:
                                    proc = subprocess.Popen(mpv_command_single, creationflags=CREATE_NEW_CONSOLE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                                    time.sleep(1)
                                    if proc.poll() is None:
                                        xbc.log(f"DEBUG: mpv single stream process started with PID: {proc.pid}", level=xbc.LOGINFO)
                                        xbcgui.Dialog().notification("mpv", f"Trying single stream: {stream['title']}", xbcgui.NOTIFICATION_INFO, 2000)
                                        time.sleep(5)
                                    else:
                                        stdout, stderr = proc.communicate(timeout=5)
                                        xbc.log(f"DEBUG: mpv single stream stdout: {stdout}", level=xbc.LOGINFO)
                                        xbc.log(f"DEBUG: mpv single stream stderr: {stderr}", level=xbc.LOGINFO)
                                        xbc.log(f"DEBUG: mpv single stream failed with exit code: {proc.returncode}", level=xbc.LOGERROR)
                                        xbcgui.Dialog().ok("Error", f"Failed to launch mpv single stream {stream['title']}: Exit code {proc.returncode}")
                                except Exception as e:
                                    xbc.log(f"DEBUG: Failed to launch mpv single stream {stream['url']}: {str(e)}", level=xbc.LOGERROR)
                                    xbcgui.Dialog().ok("Error", f"Failed to launch mpv single stream {stream['title']}: {str(e)}")
                    return

            if control_id == 114:  # Exit button
                xbmc.executebuiltin('Dialog.Close(all)')
                self.close()
                # xbmc.executebuiltin('ActivateWindow(Videos,Addons,return)')
                xbmc.executebuiltin('ActivateWindow(Home)')

            if control_id == 960:  # YouTube Genre Channels button
               
                base_url = "https://magnetic.website/MAD_TITAN_SPORTS/RADIO/Music101/"
                # Fetch list of JSON files from the remote directory (assume directory listing is enabled)
                try:
                    resp = requests.get(base_url)
                    files = re.findall(r'href="([^"]+\.json)"', resp.text)
                    if not files:
                        xbmcgui.Dialog().ok("YouTube Genre Channels", "No JSON files found at remote address.")
                        return
                    file_idx = xbmcgui.Dialog().select("Select Music Channel JSON", files)
                    if file_idx == -1:
                        return
                    json_url = base_url + files[file_idx]
                    data = requests.get(json_url).json()
                except Exception as e:
                    xbmcgui.Dialog().ok("Error", f"Failed to fetch JSON list or file: {e}")
                    return
                # Group by genre
                genre_map = {}
                for item in data.get("items", []):
                    m = re.search(r"Genre:\s*([^\n]+)", item.get("summary", ""))
                    genres = [g.strip() for g in m.group(1).split(",")] if m else ["Unknown"]
                    for genre in genres:
                        genre_map.setdefault(genre, []).append(item)
                # Let user pick genre
                genre_list = sorted(genre_map.keys())
                genre_idx = xbmcgui.Dialog().select("Select Genre Channel", genre_list)
                if genre_idx == -1:
                    return
                selected_genre = genre_list[genre_idx]
                videos = genre_map[selected_genre]
                
                play_mode = xbmcgui.Dialog().select(
                    "Playback Mode",
                    ["Play All (Random Order, May Crash)", "Play One Random Song (Recommended)"]
                )
                if play_mode == -1:
                    return
                if play_mode == 1:
                    vid = random.choice(videos)
                    listitem = xbmcgui.ListItem(label=vid["title"])
                    if vid.get("thumbnail"):
                        listitem.setArt({'thumb': vid["thumbnail"]})
                    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", vid["link"])
                    if match:
                        youtube_url = f"plugin://plugin.video.youtube/play/?video_id={match.group(1)}"
                    else:
                        youtube_url = vid["link"]
                    xbmc.Player().play(youtube_url, listitem)
                    xbmcgui.Dialog().ok(
                        "YouTube Plugin Notice",
                        "Single random song played. Continuous playback is unstable due to Kodi/YouTube plugin limitations. For best results, use this mode or create a YouTube playlist in your browser and play it in Kodi."
                    )
                    return
                xbmcgui.Dialog().ok(
                    "YouTube Plugin Notice",
                    "Continuous playback of YouTube plugin videos in Kodi is unstable and may crash or skip tracks. For best results, use 'Play One Random Song' or create a playlist on YouTube and play it in Kodi."
                )
                # Play all in random order (may crash)
                playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                playlist.clear()
                random.shuffle(videos)
                time.sleep(2)
                for vid in videos:
                    listitem = xbmcgui.ListItem(label=vid["title"])
                    if vid.get("thumbnail"):
                        listitem.setArt({'thumb': vid["thumbnail"]})
                    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", vid["link"])
                    if match:
                        youtube_url = f"plugin://plugin.video.youtube/play/?video_id={match.group(1)}"
                    else:
                        youtube_url = vid["link"]
                    playlist.add(youtube_url, listitem)
                xbmc.Player().play(playlist)
                return
            if control_id == 200:  # Last Watched List
                if self.last_watched_list:
                    item = self.last_watched_list.getSelectedItem()
                    if item:
                        channel_id = item.getProperty('channel_id')
                        if channel_id:
                            self.play_last_watched(channel_id)
                return
            
                
            # if control_id == 107:  # Button 7 - LiveScore Alerts Menu
            #     main_addon = xbmcaddon.Addon()
            #     if not main_addon.getSettingBool('livescore_alerts_enabled'):
            #         xbmcgui.Dialog().ok("LiveScore Alerts Disabled", "Enable LiveScore Alerts in settings to use this feature.")
            #         return
            #     try:
            #         main_addon_id = "plugin.video.jet_guide"
            #         main_addon = xbmcaddon.Addon(id=main_addon_id)
            #         main_addon_name = main_addon.getAddonInfo('name')
            #         livescore_addon_id = "script.service.livescore_alerts"
            #         try:
            #             livescore_addon = xbmcaddon.Addon(id=livescore_addon_id)
            #             livescore_addon_name = livescore_addon.getAddonInfo('name')
            #         except RuntimeError as e:
            #             # debug_log(f"Addon {livescore_addon_id} not found: {str(e)}", level=xbmc.LOGERROR)
            #             xbmcgui.Dialog().ok("Error", f"Addon {livescore_addon_id} not installed or not found.")
            #             return

            #         # Define fetch_games
            #         def get_game_status(gamecard):
            #                 """Extract game status from a game card element"""
            #                 try:
            #                     # List of known team names to avoid returning them as status
            #                     team_keywords = [
            #                         'twins', 'cardinals', 'rays', 'reds', 'angels', 'guardians', 'orioles',
            #                         'astros', 'giants', 'royals', 'white sox', 'yankees', 'dodgers', 'cubs',
            #                         'mets', 'phillies', 'braves', 'marlins', 'nationals', 'pirates',
            #                         'brewers', 'tigers', 'rangers', 'athletics', 'mariners', 'padres',
            #                         'diamondbacks', 'rockies', 'blue jays', 'red sox', 'indians', 'a\'s',
            #                         # WNBA teams
            #                         'fever', 'sky', 'sun', 'wings', 'aces', 'lynx', 'liberty', 'mercury',
            #                         'storm', 'mystics', 'dream'
            #                     ]
                                
            #                     # Try to find status div first
            #                     status_div = gamecard.find("div", class_="status")
            #                     if status_div:
            #                         status_text = status_div.get_text(separator=" ", strip=True)
            #                         if status_text and status_text.lower() not in team_keywords:
            #                             return status_text
                                
            #                     # Search through all spans for status indicators
            #                     for span in gamecard.find_all("span"):
            #                         text = span.get_text(strip=True)
            #                         if text and any(keyword in text for keyword in ["Final", "inning", "Inning", "Top", "Bot", "Quarter", "Period", "Half", "OT", "Live", "Ppd"]):
            #                             # Make sure it's not just a team name
            #                             if text.lower() not in team_keywords:
            #                                 return text
                                
            #                     # Look for specific game status patterns
            #                     all_text = gamecard.get_text(separator=" ", strip=True)
                                
            #                     # Look for "Bot", "Top", etc - these are definitely status
            #                     if re.search(r'(Top|Bot)\s+\d+', all_text, re.IGNORECASE):
            #                         match = re.search(r'(Top|Bot)\s+\d+', all_text, re.IGNORECASE)
            #                         return match.group(0)
                                
            #                     # Look for "Final"
            #                     if re.search(r'\bFinal\b', all_text, re.IGNORECASE):
            #                         return "Final"
                                
            #                     # Look for "Ppd" (postponed)
            #                     if re.search(r'\bPpd\b', all_text, re.IGNORECASE):
            #                         return "Postponed"
                                
            #                     # Look for quarters, periods, innings with numbers
            #                     if re.search(r'\d+(st|nd|rd|th)\s+(Quarter|Period|Inning)', all_text, re.IGNORECASE):
            #                         match = re.search(r'\d+(st|nd|rd|th)\s+(Quarter|Period|Inning)', all_text, re.IGNORECASE)
            #                         return match.group(0)
                                
            #                     # Look for live indicators
            #                     if re.search(r'\bLive\b', all_text, re.IGNORECASE):
            #                         return "Live"
                                
            #                     # Look for start times
            #                     if re.search(r'\d{1,2}:\d{2}\s*(AM|PM)', all_text, re.IGNORECASE):
            #                         match = re.search(r'\d{1,2}:\d{2}\s*(AM|PM)', all_text, re.IGNORECASE)
            #                         return f"Starts {match.group(0)}"
            #                     # various status selectors as fallback
            #                     status_selectors = [
            #                         'div.Ta\(end\) Cl\(b\) Fw\(b\) YahooSans Fw\(700\)! Fz\(11px\)!',
            #                         'div.game-status',
            #                         'div.Fz\(12px\)',
            #                         'span[data-tst="game-status"]'
            #                     ]
                                
            #                     for selector in status_selectors:
            #                         try:
            #                             elements = gamecard.select(selector)
            #                             for elem in elements:
            #                                 text = elem.get_text(strip=True)
            #                                 if text and text not in ['', ' '] and text.lower() not in team_keywords:
            #                                     return text
            #                         except:
            #                             continue
                                
            #                     # Default return
            #                     return "Scheduled"
                                
            #                 except Exception as e:
            #                     return "TBD"

            #         def fetch_games():
            #             try:
            #                 sports_settings = {
            #                     "mlb": livescore_addon.getSettingBool('sport_mlb'),
            #                     "nba": livescore_addon.getSettingBool('sport_nba'),
            #                     "wnba": livescore_addon.getSettingBool('sport_wnba'),
            #                     "nhl": livescore_addon.getSettingBool('sport_nhl'),
            #                     "nfl": livescore_addon.getSettingBool('sport_nfl'),
            #                     "college-football": livescore_addon.getSettingBool('sport_college_football'),
            #                     "mls": livescore_addon.getSettingBool('sport_mls'),
            #                     "premier-league": livescore_addon.getSettingBool('sport_premier_league'),
            #                     "fifa-club-world-cup": livescore_addon.getSettingBool('sport_fifa_club_world_cup')
            #                 }
            #                 enabled_sports = [sport for sport, enabled in sports_settings.items() if enabled]
            #                 if not enabled_sports:
            #                     debug_log("No sports selected for notifications", level=xbmc.LOGINFO)
            #                     return {}

            #                 games = {}
            #                 for sport in enabled_sports:
            #                     if sport == "mls":
            #                         url = "https://sports.yahoo.com/soccer/mls/scoreboard"
            #                     elif sport == "premier-league":
            #                         url = "https://sports.yahoo.com/soccer/premier-league/scoreboard"
            #                     elif sport == "fifa-club-world-cup":
            #                         url = "https://sports.yahoo.com/soccer/fifa-club-world-cup/scoreboard"
            #                     else:
            #                         url = f"https://sports.yahoo.com/{sport.lower()}/scoreboard"
            #                     debug_log(f"Fetching scores for {sport.upper()} from {url} -- {addon__id}", level=xbmc.LOGINFO)
            #                     try:
            #                         response = requests.get(
            #                             url,
            #                             headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'},
            #                             timeout=10
            #                         )
            #                         response.raise_for_status()
            #                         soup = BeautifulSoup(response.text, "html.parser")
            #                         game_lists = soup.find_all('ul')
            #                         for game_list in game_lists:
            #                             for game in game_list.find_all('li'):
            #                                 team_elements = game.find_all('span', {'data-tst': 'first-name'})
            #                                 if len(team_elements) < 2:
            #                                     continue
            #                                 def get_team_name(elem):
            #                                     try:
            #                                         city = elem.text.strip()
            #                                         if not city:
            #                                             return None
            #                                         nickname_elem = elem.find_next('div', {'class': 'Fw(n) Fz(12px)'}) or elem.find_next('span', {'data-tst': 'last-name'})
            #                                         if not nickname_elem:
            #                                             return city
            #                                         nickname = nickname_elem.text.strip()
            #                                         if not nickname:
            #                                             return city
            #                                         return f"{city} {nickname}".strip()
            #                                     except Exception:
            #                                         return None
            #                                 team1_name = get_team_name(team_elements[0])
            #                                 team2_name = get_team_name(team_elements[1])
            #                                 if not team1_name or not team2_name:
            #                                     continue
            #                                 score_elements = game.find_all('span', {'class': 'YahooSans Fw(700)! Va(m) Fz(24px)!'})
            #                                 score1 = score_elements[0].text.strip() if score_elements else ''
            #                                 score2 = score_elements[1].text.strip() if len(score_elements) >= 2 else ''
            #                                 status_elem = game.find('span', {'class': 'Fz(12px) C(secondary-text) Fw(b)'})
            #                                 status_text = status_elem.text.strip() if status_elem else get_game_status(game)
            #                                 key = f"{sport.upper().replace('-', ' ')}: {team1_name} vs {team2_name}"
            #                                 games[key] = {
            #                                     'score': f"{score1} - {score2}",
            #                                     'status': status_text,
            #                                     'sport': sport.upper().replace('-', ' ')
            #                                 }
            #                     except Exception as e:
            #                         debug_log(f"Error fetching {sport.upper()} scores: {str(e)}", level=xbmc.LOGERROR)
            #                         continue
            #                 return games
            #             except Exception as e:
            #                 debug_log(f"Error in fetch_games: {str(e)}", level=xbmc.LOGERROR)
            #                 return {}

            #         # Show dialog menu
            #         options = [
            #             "Enable/Disable LiveScore Alerts",
            #             "Show Catch-Up Scores",
            #             "Open LiveScore Alerts Settings"
            #         ]
            #         selected = xbmcgui.Dialog().select("LiveScore Alerts Menu", options)
                    
            #         if selected == -1:  # Dialog cancelled
            #             return

            #         if selected == 0:  # Enable/Disable
            #             try:
            #                 try:
            #                     current_state = main_addon.getSettingBool('livescore_alerts_enabled')
            #                 except Exception as e:
            #                     debug_log(f"Error accessing livescore_alerts_enabled setting: {str(e)}", level=xbmc.LOGERROR)
            #                     try:
            #                         current_state = livescore_addon.getSettingBool('service_enabled')
            #                         debug_log(f"Falling back to {livescore_addon_id} service_enabled: {current_state}", level=xbmc.LOGINFO)
            #                     except Exception as e:
            #                         debug_log(f"Error accessing service_enabled setting: {str(e)}", level=xbmc.LOGERROR)
            #                         current_state = True

            #                 new_state = not current_state
            #                 try:
            #                     main_addon.setSettingBool('livescore_alerts_enabled', new_state)
            #                     # debug_log(f"Set {main_addon_id} livescore_alerts_enabled to {new_state}", level=xbmc.LOGINFO)
            #                 except Exception as e:
            #                     debug_log(f"Error setting livescore_alerts_enabled: {str(e)}", level=xbmc.LOGERROR)

            #                 try:
            #                     livescore_addon.setSettingBool('service_enabled', new_state)
            #                     # debug_log(f"Set {livescore_addon_id} service_enabled to {new_state}", level=xbmc.LOGINFO)
            #                     xbmcgui.Dialog().notification(main_addon_name, f"LiveScore Alerts Service {'enabled' if new_state else 'disabled'}", xbmcgui.NOTIFICATION_INFO, 5000)
            #                 except Exception as e:
            #                     debug_log(f"Error setting {livescore_addon_id} service_enabled: {str(e)}", level=xbmc.LOGERROR)
            #                     xbmcgui.Dialog().ok("Error", f"Failed to toggle {livescore_addon_name} service: {str(e)}")
            #             except Exception as e:
            #                 debug_log(f"Error in enable/disable action: {str(e)}", level=xbmc.LOGERROR)
            #                 xbmcgui.Dialog().ok("Error", f"Failed to toggle service: {str(e)}")

            #         elif selected == 1:  # Show Catch-Up Scores
            #             try:
            #                 xbmcgui.Dialog().notification(main_addon_name, "Fetching catch-up scores...", xbmcgui.NOTIFICATION_INFO, 5000)
            #                 games = fetch_games()
            #                 if games:
            #                     for title, g in games.items():
            #                         xbmcgui.Dialog().notification('Catch-Up Score', f'{title}: {g["score"]} ({g["status"]})', xbmcgui.NOTIFICATION_INFO, 10000)
            #                 else:
            #                     xbmcgui.Dialog().notification(main_addon_name, "No scores available or no sports selected.", xbmcgui.NOTIFICATION_INFO, 5000)
            #             except Exception as e:
            #                 debug_log(f"Error fetching catch-up scores: {str(e)}", level=xbmc.LOGERROR)
            #                 xbmcgui.Dialog().ok("Error", f"Failed to fetch scores: {str(e)}")

            #         elif selected == 2:  # Open LiveScore Alerts Settings
            #             try:
            #                 xbmc.executebuiltin(f'Addon.OpenSettings({livescore_addon_id})')
            #             except Exception as e:
            #                 debug_log(f"Error opening {livescore_addon_id} settings: {str(e)}", level=xbmc.LOGERROR)
            #                 xbmcgui.Dialog().ok("Error", f"Failed to open {livescore_addon_name} settings: {str(e)}")

            #         # Refresh the UI
            #         xbmc.executebuiltin('Container.Refresh')

            #     except Exception as e:
            #         debug_log(f"Error in LiveScore Alerts menu: {str(e)}", level=xbmc.LOGERROR)
            #         xbmcgui.Dialog().ok("Error", f"Failed to process menu action: {str(e)}")
            #     return
            if control_id == 101:  # Button 1 - Show EPG Grid
                from epggrid import EPGGrid
                # Show progress dialog
                progress = xbmcgui.DialogProgress()
                progress.create('Loading TV Guide', 'Loading channel data...\nThis may take a moment on first run')
                progress.update(0)
                try:
                    # Load channels
                    channels = parse_m3u8(M3U8_PATH)
                    progress.update(33, 'Loading program data...\nThis may take a moment on first run')
                    # Load programs
                    programs = parse_xmltv(XMLTV_PATH)
                    progress.update(66, 'Preparing guide...')
                    addon_path = ADDON.getAddonInfo('path')
                    xml_file = 'tuepg.guide.experimental.xml'
                    epg_window = EPGGrid(xml_file, addon_path, channels=channels, programs=programs)
                    progress.update(100)
                    progress.close()
                    epg_window.doModal()
                    del epg_window
                except Exception as e:
                    progress.close()
                    xbmcgui.Dialog().ok("Error", f"Failed to load TV Guide: {str(e)}")
                
            elif control_id == 102:  # Button 2 - Show Sports Events
                progress = xbmcgui.DialogProgress()
                progress.create('Loading Sports Guide', 'Loading sports data...')
                progress.update(0)
                time.sleep(0.5)
                try:
                    progress.update(25, 'Fetching team statistics...')
                    time.sleep(0)
                    progress.update(50, 'Loading game schedules...')
                    time.sleep(0)
                    progress.update(75, 'Preparing sports interface...')
                    time.sleep(0)
                    show_sports_guide()
                    time.sleep(0)
                    progress.update(100, 'Sports guide loaded successfully!')
                   
                finally:
                    progress.close()
                    
            # elif control_id == 103:  # Button 3 - Show Channel Listings
            #     show_channel_listings()
                
            elif control_id == 104:  # Button 4 - Search
                try:
                    channels = parse_m3u8(M3U8_PATH)
                    programs = parse_xmltv(XMLTV_PATH)
                    
                    addon_path = ADDON.getAddonInfo('path')
                    search_window = SearchWindow('search_window.xml', addon_path, channels=channels, programs=programs)
                    search_window.doModal()
                    del search_window
                except Exception as e:
                    xbmcgui.Dialog().ok("Search Error", f"Error during search: {str(e)}")
                    
            elif control_id == 105:  # Button 5 - Favorites
                
                try:
                    from epggrid import EPGGrid
                    
                    # Get channels and programs
                    channels = parse_m3u8(M3U8_PATH)
                    programs = parse_xmltv(XMLTV_PATH)
                    # Filter to favorites
                    favorite_channels = [c for c in channels if favorites_manager.is_favorite(c['tvg_id'])]
                    if not favorite_channels:
                        xbmcgui.Dialog().ok("TV Guide", "No favorite channels added yet")
                        return
                    # Filter programs to favorites
                    favorite_channel_ids = [c['tvg_id'] for c in favorite_channels]
                    favorite_programs = [p for p in programs if p['channel'] in favorite_channel_ids]
                    # Show EPG grid with favorites
                    addon_path = ADDON.getAddonInfo('path')
                    epg_window = EPGGrid('tuepg.guide.experimental.xml', addon_path,
                                     channels=favorite_channels,
                                     programs=favorite_programs)
                    epg_window.doModal()
                    del epg_window
                except Exception as e:
                    xbmcgui.Dialog().ok("Favorites Error", f"Error showing favorites: {str(e)}")
                    
            elif control_id == 106:  # Button 6 - Sports Grid
                try:
                    # Sports options
                    sports = [
                        ("MLB", "mlb"),
                        ("NBA", "nba"),
                        ("WNBA", "wnba"),
                        ("NHL", "nhl"),
                        ("NFL", "nfl"),
                        # ("Premier League", "premier_league")
                    ]
                    # Create list of sport names for dialog
                    sport_names = [f"{name} Grid View" for name, _ in sports]
                    dialog = xbmcgui.Dialog()
                    choice = dialog.select('[COLOR gold]Select Sport Grid View[/COLOR]', [f"[COLOR orange]{name}[/COLOR]" for name, _ in sports])
                    if choice >= 0: 
                        sport_code = sports[choice][1]
                        sport_name = sports[choice][0]
                        
                        # Show progress dialog for sports grid
                        progress = xbmcgui.DialogProgress()
                        progress.create(f'Loading {sport_name} Stats', f'Loading {sport_name} statistics...')
                        progress.update(0)
                        
                        try:
                            # Update progress
                            progress.update(25, f'Fetching {sport_name} team data...')
                            
                            # Update progress
                            progress.update(50, f'Loading {sport_name} game schedules...')
                            
                            # Update progress
                            progress.update(75, f'Preparing {sport_name} interface...')
                            
                            # Call the sports grid function
                            show_sports_grid(sport_code)
                            
                            # Complete progress
                            progress.update(100, f'{sport_name} stats loaded successfully!')
                            
                        finally:
                            # Close progress dialog
                            progress.close()
                except Exception as e:
                    xbmcgui.Dialog().ok("Sports Error", f"Error showing sports grid: {str(e)}")
                    
            elif control_id == 108:  # Button 8 - Show Main Menu
                plugin_url = f"plugin://{ADDON.getAddonInfo('id')}/?action=show_main"
                xbmc.executebuiltin('Dialog.Close(all)')
                xbmc.sleep(20)
                self.close()
                xbmc.executebuiltin(f'Container.Update({plugin_url})')
                
            elif control_id in self.buttons:
                # Skip notifications for buttons 8 and 9
                if control_id not in [108, 109]:
                    xbmcgui.Dialog().notification('Button Click', f'Clicked {self.buttons[control_id]}')

        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Error handling click: {str(e)}")

    def play_last_watched(self, channel_id):
        """Play a channel from last watched"""
        try:
            # Get channel info
            channels = parse_m3u8(M3U8_PATH)
            channel = next((c for c in channels if c['tvg_id'] == channel_id), None)
            if not channel:
                xbmcgui.Dialog().notification('Error', 'Channel not found')
                return
            # Create list item
            list_item = xbmcgui.ListItem(channel['name'])
            list_item.setArt({'icon': channel.get('logo', '')})
            # Get stream URL
            url = channel['url']
            if '|' in url:
                url = url.split('|')[0].strip()
            # Play without dialogs
            xbmc.executebuiltin('Dialog.Close(busydialog)')
            xbmc.Player().play(url, list_item)
            
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Failed to play channel: {str(e)}")

    def onAction(self, action):
        try:
            # Stop ticker thread when window is closed
            self.ticker_running = False
            if self.ticker_thread and self.ticker_thread.is_alive():
                self.ticker_thread.join(timeout=1)
            action_id = action.getId()
            # debug_log(f"Action received: {action_id}", level=xbmc.LOGDEBUG)
            if action_id in [9, 10, 92, 216, 247, 257, 275, 61467, 61448]:
                self.ticker_running = False
                if self.ticker_thread:
                    self.ticker_thread.join(timeout=1.0)
                self.close()
                # debug_log("Closed TenButtonsWindow", level=xbmc.LOGDEBUG)
        except Exception as e:
            # debug_log(f"Error handling action: {str(e)}", level=xbmc.LOGERROR)
            xbmcgui.Dialog().ok("Error", f"Error handling action: {str(e)}")

    def fetch_games(self):
        try:
            livescore_addon_id = "script.service.livescore_alerts"
            livescore_addon = xbmcaddon.Addon(id=livescore_addon_id)
            sports_settings = {
                "mlb": False,
                "nba": False,
                "wnba": False,
                "nhl": False,
                "nfl": False,
                "college_football": False,
                "mls": False,
                "premier_league": False,
                "fifa_club_world_cup": False
            }
            for sport in sports_settings:
                setting_id = f'sport_{sport}'
                try:
                    sports_settings[sport] = livescore_addon.getSettingBool(setting_id)
                    # debug_log(f"Retrieved setting {setting_id}: {sports_settings[sport]}", level=xbmc.LOGDEBUG)
                except Exception as e:
                    debug_log(f"Error accessing setting {setting_id}: {str(e)}", level=xbmc.LOGERROR)
                    sports_settings[sport] = False

            enabled_sports = [sport for sport, enabled in sports_settings.items() if enabled]
            if not enabled_sports:
                debug_log("No sports selected for notifications", level=xbmc.LOGINFO)
                return {}

            games = {}
            for sport in enabled_sports:
                if sport == "mls":
                    url = "https://sports.yahoo.com/soccer/mls/scoreboard"
                elif sport == "premier_league":
                    url = "https://sports.yahoo.com/soccer/premier-league/scoreboard"
                elif sport == "fifa_club_world_cup":
                    url = "https://sports.yahoo.com/soccer/fifa-club-world-cup/scoreboard"
                else:
                    url = f"https://sports.yahoo.com/{sport.lower()}/scoreboard"
                debug_log(f"Fetching scores for {sport.upper()} from {url} -- {addon__id}", level=xbmc.LOGINFO)
                try:
                    response = requests.get(
                        url,
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'},
                        timeout=10
                    )
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, "html.parser")
                    game_lists = soup.find_all('ul')
                    for game_list in game_lists:
                        for game in game_list.find_all('li'):
                            team_elements = game.find_all('span', {'data-tst': 'first-name'})
                            if len(team_elements) < 2:
                                continue
                            def get_team_name(elem):
                                try:
                                    city = elem.text.strip()
                                    if not city:
                                        return None
                                    nickname_elem = elem.find_next('div', {'class': 'Fw(n) Fz(12px)'}) or elem.find_next('span', {'data-tst': 'last-name'})
                                    if not nickname_elem:
                                        return city
                                    nickname = nickname_elem.text.strip()
                                    if not nickname:
                                        return city
                                    return f"{city} {nickname}".strip()
                                except Exception:
                                    return None
                            team1_name = get_team_name(team_elements[0])
                            team2_name = get_team_name(team_elements[1])
                            if not team1_name or not team2_name:
                                continue
                            score_elements = game.find_all('span', {'class': 'YahooSans Fw(700)! Va(m) Fz(24px)!'})
                            score1 = score_elements[0].text.strip() if score_elements else ''
                            score2 = score_elements[1].text.strip() if len(score_elements) >= 2 else ''
                            status_text = self.get_game_status(game)
                            key = f"[COLORyellow]{sport.upper().replace('_', ' ')}[/COLOR]: {team1_name} vs {team2_name}"
                            games[key] = {
                                'score': f"[COLORaqua]{score1} - {score2}[/COLOR]",
                                'status': f"[COLORlime]{status_text}[/COLOR]",
                                'sport': f"[COLORyellow]{sport.upper().replace('_', ' ')}[/COLOR]"
                            }
                except Exception as e:
                    debug_log(f"Error fetching {sport.upper()} scores: {str(e)}", level=xbmc.LOGERROR)
                    continue
            return games
        except Exception as e:
            debug_log(f"Error in fetch_games: {str(e)}", level=xbmc.LOGERROR)
            return {}

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
            return "TBD"

class ButtonState:
    window = None

def show_ten_buttons():
    """Show the ten buttons window"""
    try:
        # Close any open dialogs first
        xbmc.executebuiltin('Dialog.Close(all)')
        xbmc.sleep(200)  # Give time for dialogs to close
        
        addon_path = ADDON.getAddonInfo('path')
        ButtonState.window = TenButtonsWindow('ten_buttons.xml', addon_path)
        ButtonState.window.doModal()
        del ButtonState.window
        ButtonState.window = None
    except Exception as e:
        xbmcgui.Dialog().ok("Error", f"Failed to show window: {str(e)}")

def browse_installed_video_addons():
    """Browse installed video addons and return selected addon ID"""
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

def browse_addon_json_channels(addon_id):
    
    # Get addon path
    addon_path = xbmcvfs.translatePath(f"special://home/addons/{addon_id}")
    json_files = []
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
            

def import_channels_from_favourites():
    
    debug_log("JetGuide DEBUG: Starting import_channels_from_favourites()", level=xbmc.LOGINFO)
    fav_path = xbmcvfs.translatePath("special://userdata/favourites.xml")
    if not xbmcvfs.exists(fav_path):
        debug_log("JetGuide DEBUG: favourites.xml not found at path: " + fav_path, level=xbmc.LOGERROR)
        xbmcgui.Dialog().ok("Import Favourites", "No favourites.xml found.")
        return
    try:
        tree = ET.parse(fav_path)
        root = tree.getroot()
        imported = []
        for item in root.findall(".//favourite"):
            name = item.get("name", "Unknown")
            url = item.text.strip() if item.text else ""
            # Extract URL from PlayMedia("...")
            m = re.search(r'PlayMedia\("([^"]+)"\)', url)
            if m:
                play_url = m.group(1)
                
                if play_url.startswith("http") or play_url.endswith(".m3u8") or play_url.startswith("plugin://"):
                    imported.append({"title": name, "link": play_url})
            elif url.startswith("http") or url.endswith(".m3u8") or url.startswith("plugin://"):
                imported.append({"title": name, "link": url})
        if not imported:
            debug_log("JetGuide DEBUG: No playable channels found in favourites.xml", level=xbmc.LOGINFO)
            xbmcgui.Dialog().ok("Import Favourites", "No playable channels found in favourites.")
            return
        profile_path = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
        save_path = profile_path + "jet_guide_imported.json"
        if xbmcvfs.exists(save_path):
            with xbmcvfs.File(save_path, 'r') as f:
                existing = json.loads(f.read())
        else:
            existing = []
        # Avoid duplicates
        for ch in imported:
            if not any(e['link'] == ch['link'] for e in existing):
                existing.append(ch)
        with xbmcvfs.File(save_path, 'w') as f:
            f.write(json.dumps(existing, indent=2, ensure_ascii=False))
            # xbmcgui.Dialog().ok("Import Favourites", f'Successfully imported{len(imported)} channels from favourites., 2000, {icon_path})')
            
        debug_log(f"JetGuide DEBUG: Successfully imported {len(imported)} channels from favourites.", level=xbmc.LOGINFO)
        icon_path = ""
        xbmcgui.Dialog().ok("Import Favourites", f'Successfully imported [COLOR yellow]{len(imported)}[/COLOR] channels from  KODI favourites.')
        
        # xbmc.executebuiltin(f'Notification(Jet Guide, Imported {len(imported)} channels from favourites., 2000, {icon_path})')
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        debug_log(f"JetGuide DEBUG: Exception in import_channels_from_favourites: {str(e)}\n{tb}", level=xbmc.LOGERROR)
        xbmcgui.Dialog().ok("Import Favourites", f"Error importing favourites:\n{str(e)}")