import xbmcgui
import xbmc
import json
from scrapers.ddlv import Ddlv
from tools import show_tools, debug_log

class ScraperResultsWindow(xbmcgui.WindowXML):
    def __init__(self, xml_file, addon_path):
        super().__init__(xml_file, addon_path)
        self.results_list = None

    def onInit(self):
        self.results_list = self.getControl(402)
        if not hasattr(self, "scraper_selection"):
            choice = xbmcgui.Dialog().contextmenu(['Channels', 'Events'])
            if choice == 0:
                self.scraper_selection = 'ddlv/channels'
            elif choice == 1:
                self.scraper_selection = 'ddlv/events/'
            else:
                self.scraper_selection = 'ddlv/channels'
        self.load_scraper_results(self.scraper_selection)

    def load_scraper_results(self, url_type='ddlv/channels'):
        ddlv = Ddlv()
        if url_type == 'ddlv/channels':
            html = ddlv.get(ddlv.channels_url).text
            debug_log(f"DEBUG: Scraper fetched HTML from {ddlv.channels_url}: {repr(html[:500])}", level=xbmc.LOGINFO)
            items = ddlv.parse_list('ddlv/channels', html)
        elif url_type == 'ddlv/events/':
            html = ddlv.get(ddlv.schedule_url).text
            debug_log(f"DEBUG: Scraper fetched HTML from {ddlv.schedule_url}: {repr(html[:500])}", level=xbmc.LOGINFO)
            try:
                events_json = json.loads(html)
            except Exception as e:
                debug_log(f"ERROR: Failed to parse events JSON: {e}", level=xbmc.LOGERROR)
                events_json = []
            items = ddlv.parse_list('ddlv/events/', events_json)
        else:
            items = []
        debug_log(f"DEBUG: Parsed items: {repr(items)}", level=xbmc.LOGINFO)
        if items and self.results_list:
            self.results_list.reset()
            for item in items:
                label = item.get('title', 'No Title') 
                link = item.get('link', '')
                debug_log(f"DEBUG: Adding channel/event to list: {label} ({link})", level=xbmc.LOGINFO)
                list_item = xbmcgui.ListItem()
                list_item.setLabel(label)
                list_item.setProperty("channel_link", link)
                # Set icon if label matches any key in icons
                from scrapers.icons import icons
                icon_path = None
                label_lower = label.lower()
                for key in icons:
                    if key in label_lower:
                        icon_path = icons[key]
                        break
                if icon_path:
                    list_item.setArt({'icon': icon_path})
                self.results_list.addItem(list_item)
            if hasattr(self, "selected_index"):
                if 0 <= self.selected_index < self.results_list.size():
                    self.results_list.selectItem(self.selected_index)
            self.results_list.setVisible(True)
            debug_log(f"DEBUG: Results list item count: {self.results_list.size()}", level=xbmc.LOGINFO)
            debug_log(f"DEBUG: Results list visible: {self.results_list.isVisible()}", level=xbmc.LOGINFO)
        else:
            debug_log("DEBUG: No items parsed from HTML or results_list missing.", level=xbmc.LOGINFO)

    def onClick(self, controlId):
        if controlId == 402 and self.results_list:
            self.selected_index = self.results_list.getSelectedPosition()
            selected = self.results_list.getSelectedItem()
            if selected:
                item = {
                    "link": selected.getProperty("channel_link"),
                    "title": selected.getLabel()
                }
                from scrapers.ddlv import Ddlv
                # If link is a JSON array, keep as-is; if not, wrap in JSON for play_video
                try:
                    json.loads(item["link"])
                except Exception:
                    item["link"] = json.dumps(item["link"])
                Ddlv().play_video(item)