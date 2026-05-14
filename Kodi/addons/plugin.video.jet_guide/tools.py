import xbmcaddon
import xbmc

def debug_log(msg, level=xbmc.LOGINFO):
    addon = xbmcaddon.Addon()
    if addon.getSettingBool('debug_logging'):
        xbmc.log(msg, level)
# Use debug_log in other files by importing from tools.py
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
from reminders import RemindersManager
xbc=xbmc
xbcaddon=xbmcaddon
xbcgui=xbmcgui
xbcvfs=xbmcvfs
ffmpeg_proc = None

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ADDON = xbmcaddon.Addon()
addon__id = ADDON.getAddonInfo('id')
JET_GUIDE_IMPORTED_PATH = xbmcvfs.translatePath("special://userdata/addon_data/plugin.video.jet_guide/jet_guide_imported.json")

class ToolsWindow(xbmcgui.WindowXML):
    def __init__(self, xml_file, addon_path):
        super().__init__(xml_file, addon_path)
        self.buttons = {
            201: "Settings",
            202: "Clear Cache",
            203: "Manage Widgets",
            204: "Live Score Alerts",
            # 205: "Exit",
            206: "Reminders",
            207: "Browse Saved Links",
            208: "Search Kodi Addons button",
            209: "Import Kodi Favourites button",
            210: "Scraper",  # New button for scraper section
        }
        self.widget_list = None
        self.widget_list2 = None

    

    def onInit(self):
        for btn_id in self.buttons:
            try:
                control = self.getControl(btn_id)
                control.setLabel(self.buttons[btn_id])
                control.setEnabled(True)
            except Exception:
                pass

    def load_pinned_widgets(self, widget_list=None, widget_row=1):
        """
        Load pinned widget links from widgets.json and display in the given widget_list.
        widget_row can be used to filter or split widgets between rows if needed.
        """
        debug_log(f"DEBUG: load_pinned_widgets called for row {widget_row}", xbmc.LOGINFO)
        if widget_list is None:
            widget_list = self.widget_list
        if not widget_list:
            debug_log(f"DEBUG: widget_list (row {widget_row}) is None", xbmc.LOGINFO)
            return
        try:
            widget_list.reset()
            try:
                WIDGETS_PATH = xbmcvfs.translatePath("special://userdata/addon_data/plugin.video.jet_guide/widgets.json")
                debug_log(f"DEBUG: Resolved widgets.json path: {WIDGETS_PATH}", xbmc.LOGINFO)
                exists = xbmcvfs.exists(WIDGETS_PATH)
                debug_log(f"DEBUG: widgets.json exists? {exists}", xbmc.LOGINFO)
                if not exists:
                    debug_log("DEBUG: widgets.json does not exist", xbmc.LOGINFO)
                    return
                with xbmcvfs.File(WIDGETS_PATH, "r") as f:
                    links = json.loads(f.read())
                debug_log(f"DEBUG: widgets.json loaded, {len(links)} widgets", xbmc.LOGINFO)
            except Exception as e:
                debug_log(f"DEBUG: Exception in load_pinned_widgets: {e}", xbmc.LOGERROR)
                return
            debug_log(f"DEBUG: widgets.json loaded, {len(links)} widgets", xbmc.LOGINFO)
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
                            thumb = (
                                item.get("thumbnail")
                                or item.get("fanart")
                                or item.get("icon")
                                or (item.get("art", {}).get("thumb") if "art" in item else None)
                                or (item.get("art", {}).get("icon") if "art" in item else None)
                                or ""
                            )
                            icon = thumb if thumb else "special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/folders.PNG"
                            # Custom sports icon logic
                            sports_keywords = ["NBA", "NFL", "MLB", "Soccer"]
                            if any(word.lower() in label.lower() or word.lower() in widget_link.lower() for word in sports_keywords):
                                icon = "special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/sports_icon.png"
                            if not thumb and widget_link.startswith("plugin://"):
                                m = re.match(r"plugin://([^/]+)/", widget_link)
                                if m:
                                    addon_id = m.group(1)
                                    icon_path = f"special://home/addons/{addon_id}/icon.png"
                                    if xbmcvfs.exists(icon_path):
                                        icon = icon_path
                            list_item = xbmcgui.ListItem(label)
                            debug_log(f"Widget Item Debug: label={label}, widget_link={widget_link}, item={item}", xbmc.LOGINFO)
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
                            debug_log(f"Widget Art Debug: label={label}, widget_link={widget_link}, art={art_dict}", xbmc.LOGINFO)
                            list_item.setArt(art_dict)
                            list_item.setProperty("widget_link", widget_link)
                            widget_list.addItem(list_item)
                            count += 1
                    except Exception as e:
                        debug_log(f"Widget dynamic refresh failed: {e}", xbmc.LOGERROR)
                elif "links" in link and isinstance(link["links"], list):
                    for item in link["links"]:
                        widget_link = item["file"] if isinstance(item, dict) else item
                        label = item["label"] if isinstance(item, dict) and "label" in item else link.get("title", "Widget")
                        icon = "special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/folders.PNG"
                        # Custom sports icon logic for static links
                        sports_keywords = ["NBA", "NFL", "MLB", "Soccer"]
                        if any(word.lower() in label.lower() or word.lower() in widget_link.lower() for word in sports_keywords):
                            icon = "special://home/addons/plugin.video.jet_guide/resources/skins/default/720p/media/sports_icon.png"
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

    def onClick(self, control_id):
        if control_id == 210:
            # Open scraper results window using Python logic
            import scraper_results_window
            win = scraper_results_window.ScraperResultsWindow(
                "scraper_results.xml",
                xbmcaddon.Addon().getAddonInfo('path')
            )
            win.doModal()
            del win
        elif control_id in (310, 311):  # Widget bar clicked (support both rows)
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

        if control_id == 201:  # Settings
            xbmc.executebuiltin(f'Addon.OpenSettings({ADDON_ID})')
        elif control_id == 299:  # Exit button
                xbmc.executebuiltin('Dialog.Close(all)')
                self.close()
                # xbmc.executebuiltin('ActivateWindow(Videos,Addons,return)')
                xbmc.executebuiltin('ActivateWindow(Home)')
        elif control_id == 202:  # Clear Cache
            cache_path = xbmcvfs.translatePath("special://home/userdata/addon_data/plugin.video.jet_guide/cache")
            if xbmcvfs.exists(cache_path):
                for root, dirs, files in os.walk(cache_path):
                    for f in files:
                        try:
                            os.remove(os.path.join(root, f))
                        except Exception:
                            pass
                xbmcgui.Dialog().ok("Clear Cache", "Cache cleared.")
            else:
                xbmcgui.Dialog().ok("Clear Cache", "No cache found.")
        
        elif control_id == 203:  # Manage Widgets
            action = xbmcgui.Dialog().select(
                "Manage Widgets",
                [
                    "Create Widget",
                    "Create Widget (All Items from Addon Page)",
                    "Delete Widget",
                    "Cancel"
                ]
            )
            selected_addon = None  # Ensure always defined
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
                # import json
                # import xbmcvfs
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
            # xbmcgui.Dialog().ok("Manage Widgets", "Widget management logic moved here. (Implement as needed)")
        
        elif control_id == 204:  # Button 7 - LiveScore Alerts Menu
                try:
                    main_addon_id = "plugin.video.jet_guide"
                    main_addon = xbmcaddon.Addon(id=main_addon_id)
                    main_addon_name = main_addon.getAddonInfo('name')
                    livescore_addon_id = "script.service.livescore_alerts"
                    try:
                        livescore_addon = xbmcaddon.Addon(id=livescore_addon_id)
                        livescore_addon_name = livescore_addon.getAddonInfo('name')
                    except RuntimeError as e:
                        # debug_log(f"Addon {livescore_addon_id} not found: {str(e)}", level=xbmc.LOGERROR)
                        xbmcgui.Dialog().ok("Error", f"Addon {livescore_addon_name} not installed or not found.")
                        return

                    # Define fetch_games
                    def get_game_status(gamecard):
                            """Extract game status from a game card element"""
                            try:
                                # List of known team names to avoid returning them as status
                                team_keywords = [
                                    'twins', 'cardinals', 'rays', 'reds', 'angels', 'guardians', 'orioles',
                                    'astros', 'giants', 'royals', 'white sox', 'yankees', 'dodgers', 'cubs',
                                    'mets', 'phillies', 'braves', 'marlins', 'nationals', 'pirates',
                                    'brewers', 'tigers', 'rangers', 'athletics', 'mariners', 'padres',
                                    'diamondbacks', 'rockies', 'blue jays', 'red sox', 'indians', 'a\'s',
                                    # WNBA teams
                                    'fever', 'sky', 'sun', 'wings', 'aces', 'lynx', 'liberty', 'mercury',
                                    'storm', 'mystics', 'dream'
                                ]
                                
                                # Try to find status div first
                                status_div = gamecard.find("div", class_="status")
                                if status_div:
                                    status_text = status_div.get_text(separator=" ", strip=True)
                                    if status_text and status_text.lower() not in team_keywords:
                                        return status_text
                                
                                # Search through all spans for status indicators
                                for span in gamecard.find_all("span"):
                                    text = span.get_text(strip=True)
                                    if text and any(keyword in text for keyword in ["Final", "inning", "Inning", "Top", "Bot", "Quarter", "Period", "Half", "OT", "Live", "Ppd"]):
                                        # Make sure it's not just a team name
                                        if text.lower() not in team_keywords:
                                            return text
                                
                                # Look for specific game status patterns
                                all_text = gamecard.get_text(separator=" ", strip=True)
                                
                                # Look for "Bot", "Top", etc - these are definitely status
                                if re.search(r'(Top|Bot)\s+\d+', all_text, re.IGNORECASE):
                                    match = re.search(r'(Top|Bot)\s+\d+', all_text, re.IGNORECASE)
                                    return match.group(0)
                                
                                # Look for "Final"
                                if re.search(r'\bFinal\b', all_text, re.IGNORECASE):
                                    return "Final"
                                
                                # Look for "Ppd" (postponed)
                                if re.search(r'\bPpd\b', all_text, re.IGNORECASE):
                                    return "Postponed"
                                
                                # Look for quarters, periods, innings with numbers
                                if re.search(r'\d+(st|nd|rd|th)\s+(Quarter|Period|Inning)', all_text, re.IGNORECASE):
                                    match = re.search(r'\d+(st|nd|rd|th)\s+(Quarter|Period|Inning)', all_text, re.IGNORECASE)
                                    return match.group(0)
                                
                                # Look for live indicators
                                if re.search(r'\bLive\b', all_text, re.IGNORECASE):
                                    return "Live"
                                
                                # Look for start times
                                if re.search(r'\d{1,2}:\d{2}\s*(AM|PM)', all_text, re.IGNORECASE):
                                    match = re.search(r'\d{1,2}:\d{2}\s*(AM|PM)', all_text, re.IGNORECASE)
                                    return f"Starts {match.group(0)}"
                                # various status selectors as fallback
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
                                
                                # Default return
                                return "Scheduled"
                                
                            except Exception as e:
                                return "TBD"

                    def fetch_games():
                        try:
                            sports_settings = {
                                "mlb": livescore_addon.getSettingBool('sport_mlb'),
                                "nba": livescore_addon.getSettingBool('sport_nba'),
                                "wnba": livescore_addon.getSettingBool('sport_wnba'),
                                "nhl": livescore_addon.getSettingBool('sport_nhl'),
                                "nfl": livescore_addon.getSettingBool('sport_nfl'),
                                "college-football": livescore_addon.getSettingBool('sport_college_football'),
                                "mls": livescore_addon.getSettingBool('sport_mls'),
                                "premier-league": livescore_addon.getSettingBool('sport_premier_league'),
                                "fifa-club-world-cup": livescore_addon.getSettingBool('sport_fifa_club_world_cup')
                            }
                            enabled_sports = [sport for sport, enabled in sports_settings.items() if enabled]
                            if not enabled_sports:
                                debug_log("No sports selected for notifications", level=xbmc.LOGINFO)
                                return {}

                            games = {}
                            for sport in enabled_sports:
                                if sport == "mls":
                                    url = "https://sports.yahoo.com/soccer/mls/scoreboard"
                                elif sport == "premier-league":
                                    url = "https://sports.yahoo.com/soccer/premier-league/scoreboard"
                                elif sport == "fifa-club-world-cup":
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
                                            status_elem = game.find('span', {'class': 'Fz(12px) C(secondary-text) Fw(b)'})
                                            status_text = status_elem.text.strip() if status_elem else get_game_status(game)
                                            key = f"{sport.upper().replace('-', ' ')}: {team1_name} vs {team2_name}"
                                            games[key] = {
                                                'score': f"{score1} - {score2}",
                                                'status': status_text,
                                                'sport': sport.upper().replace('-', ' ')
                                            }
                                except Exception as e:
                                    debug_log(f"Error fetching {sport.upper()} scores: {str(e)}", level=xbmc.LOGERROR)
                                    continue
                            return games
                        except Exception as e:
                            debug_log(f"Error in fetch_games: {str(e)}", level=xbmc.LOGERROR)
                            return {}

                    # Show dialog menu
                    options = [
                        "Enable/Disable LiveScore Alerts",
                        "Show Catch-Up Scores",
                        "Open LiveScore Alerts Settings"
                    ]
                    selected = xbmcgui.Dialog().select("LiveScore Alerts Menu", options)
                    
                    if selected == -1:  # Dialog cancelled
                        return

                    if selected == 0:  # Enable/Disable
                        try:
                            try:
                                current_state = main_addon.getSettingBool('livescore_alerts_enabled')
                            except Exception as e:
                                debug_log(f"Error accessing livescore_alerts_enabled setting: {str(e)}", level=xbmc.LOGERROR)
                                try:
                                    current_state = livescore_addon.getSettingBool('service_enabled')
                                    debug_log(f"Falling back to {livescore_addon_id} service_enabled: {current_state}", level=xbmc.LOGINFO)
                                except Exception as e:
                                    debug_log(f"Error accessing service_enabled setting: {str(e)}", level=xbmc.LOGERROR)
                                    current_state = True

                            new_state = not current_state
                            try:
                                main_addon.setSettingBool('livescore_alerts_enabled', new_state)
                                # debug_log(f"Set {main_addon_id} livescore_alerts_enabled to {new_state}", level=xbmc.LOGINFO)
                            except Exception as e:
                                debug_log(f"Error setting livescore_alerts_enabled: {str(e)}", level=xbmc.LOGERROR)

                            try:
                                livescore_addon.setSettingBool('service_enabled', new_state)
                                # debug_log(f"Set {livescore_addon_id} service_enabled to {new_state}", level=xbmc.LOGINFO)
                                xbmcgui.Dialog().notification(main_addon_name, f"LiveScore Alerts Service {'enabled' if new_state else 'disabled'}", xbmcgui.NOTIFICATION_INFO, 5000)
                            except Exception as e:
                                debug_log(f"Error setting {livescore_addon_id} service_enabled: {str(e)}", level=xbmc.LOGERROR)
                                xbmcgui.Dialog().ok("Error", f"Failed to toggle {livescore_addon_name} service: {str(e)}")
                        except Exception as e:
                            debug_log(f"Error in enable/disable action: {str(e)}", level=xbmc.LOGERROR)
                            xbmcgui.Dialog().ok("Error", f"Failed to toggle service: {str(e)}")

                    elif selected == 1:  # Show Catch-Up Scores
                        try:
                            xbmcgui.Dialog().notification(main_addon_name, "Fetching catch-up scores...", xbmcgui.NOTIFICATION_INFO, 5000)
                            games = fetch_games()
                            if games:
                                for title, g in games.items():
                                    xbmcgui.Dialog().notification('Catch-Up Score', f'{title}: {g["score"]} ({g["status"]})', xbmcgui.NOTIFICATION_INFO, 10000)
                            else:
                                xbmcgui.Dialog().notification(main_addon_name, "No scores available or no sports selected.", xbmcgui.NOTIFICATION_INFO, 5000)
                        except Exception as e:
                            debug_log(f"Error fetching catch-up scores: {str(e)}", level=xbmc.LOGERROR)
                            xbmcgui.Dialog().ok("Error", f"Failed to fetch scores: {str(e)}")

                    elif selected == 2:  # Open LiveScore Alerts Settings
                        try:
                            xbmc.executebuiltin(f'Addon.OpenSettings({livescore_addon_id})')
                        except Exception as e:
                            debug_log(f"Error opening {livescore_addon_id} settings: {str(e)}", level=xbmc.LOGERROR)
                            xbmcgui.Dialog().ok("Error", f"Failed to open {livescore_addon_name} settings: {str(e)}")

                    # Refresh the UI
                    xbmc.executebuiltin('Container.Refresh')

                except Exception as e:
                    debug_log(f"Error in LiveScore Alerts menu: {str(e)}", level=xbmc.LOGERROR)
                    xbmcgui.Dialog().ok("Error", f"Failed to process menu action: {str(e)}")
                return      # Live Score Alerts
            # xbmcgui.Dialog().ok("Live Score Alerts", "Live score alerts logic moved here. (Implement as needed)")

        elif control_id == 206:  # Reminders dialog button
                
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
        if control_id == 207:  # Browse Saved Links button
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

        if control_id == 9001:  # YouTube Guide button
            xbmc.executebuiltin('RunPlugin(plugin://plugin.video.jet_guide/?action=show_youtube_guide)')
            return

        if control_id == 9002:  # YouTube EPG button
            xbmc.executebuiltin('RunPlugin(plugin://plugin.video.jet_guide/?action=show_youtube_epg)')
            return

        FOLDERS_BASE_PATH = "special://userdata/addon_data/plugin.video.jet_guide/jet_guide_folders"
        try:
            if control_id == 208:  # Search Kodi Addons button
                
                selected_addon = browse_installed_video_addons()
                if not selected_addon:
                    return
                # Open custom dialog to browse folders and links
                browse_addon_plugin_folders(selected_addon)
                return
            if control_id == 209:  # Import Kodi Favourites button
                import_channels_from_favourites()
                return
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Error handling click: {str(e)}")


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

def show_tools():
    addon_path = ADDON.getAddonInfo('path')
    win = ToolsWindow('tools.xml', addon_path)
    win.doModal()
    del win


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

def save_widget_link(link_obj):
    """
    Save a link object to the widgets.json file for widget display.
    """
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
    # Use "link" if present, else "source_folder" for uniqueness
    def get_widget_key(w):
        return w.get("link") or w.get("source_folder")
    new_key = get_widget_key(link_obj)
    if isinstance(link_obj, dict) and new_key and not any(get_widget_key(l) == new_key for l in links):
        links.append(link_obj)
        with xbmcvfs.File(WIDGETS_PATH, "w") as f:
            f.write(json.dumps(links, indent=2))
    return