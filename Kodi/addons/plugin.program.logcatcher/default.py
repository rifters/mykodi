import sys
import os
import json
import urllib.parse
import urllib.request
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

addon = xbmcaddon.Addon()
addon_id = addon.getAddonInfo('id')
handle = int(sys.argv[1])

profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))

filtered_media = os.path.join(profile, "filtered_media.json")
filtered_plugin = os.path.join(profile, "filtered_plugin.json")
filtered_http = os.path.join(profile, "filtered_http.json")
filtered_local = os.path.join(profile, "filtered_local.json")
filtered_nested = os.path.join(profile, "filtered_nested.json")
filtered_cache = os.path.join(profile, "filtered_cache.json")
filtered_all = os.path.join(profile, "filtered_all.json")


def load_json(path):
    if not xbmcvfs.exists(path):
        return []
    try:
        with xbmcvfs.File(path) as f:
            raw = f.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        return json.loads(raw)
    except:
        return []


# Unified filter → JSON path resolver
def get_filter_path():
    mode = addon.getSetting("filter_mode")

    if mode == "0":
        return filtered_media
    elif mode == "1":
        return filtered_all
    elif mode == "2":
        return filtered_plugin
    elif mode == "3":
        return filtered_http
    elif mode == "4":
        return filtered_local
    elif mode == "5":
        return filtered_nested
    elif mode == "6":
        return filtered_cache
    else:
        return filtered_all


def list_entries():
    path = get_filter_path()
    entries = load_json(path)

    if not entries:
        li = xbmcgui.ListItem(label="No entries for this filter.")
        xbmcplugin.addDirectoryItem(handle, "", li, False)
        xbmcplugin.endOfDirectory(handle)
        return

    max_display = addon.getSettingInt("max_entries_display")
    if max_display <= 0:
        max_display = 200

    entries = entries[:max_display]

    for idx, e in enumerate(entries):
        url = e.get("url", "")
        li = xbmcgui.ListItem(label=url)

        cm = []
        cm.append(("Copy URL", f'RunPlugin(plugin://{addon_id}/?action=copy&idx={idx})'))

        if addon.getSettingBool("aria2_enabled"):
            cm.append(("Send to Aria2", f'RunPlugin(plugin://{addon_id}/?action=aria2&idx={idx})'))

        li.addContextMenuItems(cm)

        xbmcplugin.addDirectoryItem(handle, f"plugin://{addon_id}/?action=copy&idx={idx}", li, False)

    xbmcplugin.endOfDirectory(handle)


def router(params):
    action = params.get("action")

    if not action:
        list_entries()
        return

    path = get_filter_path()
    entries = load_json(path)

    try:
        idx = int(params.get("idx", -1))
    except:
        return

    if idx < 0 or idx >= len(entries):
        return

    url = entries[idx].get("url", "")

    if action == "copy":
        win = xbmcgui.Window(10000)
        win.setProperty("clipboard", url)
        xbmc.executebuiltin("SetClipboard(clipboard)")
        xbmcgui.Dialog().notification("Log Catcher", "Copied to clipboard", xbmcgui.NOTIFICATION_INFO, 2000)

    elif action == "aria2":
        send_to_aria2(url)


def send_to_aria2(url):
    if not addon.getSettingBool("aria2_enabled"):
        xbmcgui.Dialog().notification("Log Catcher", "Aria2 disabled", xbmcgui.NOTIFICATION_WARNING, 3000)
        return

    host = addon.getSetting("aria2_host") or "127.0.0.1"
    port = addon.getSetting("aria2_port") or "6800"
    secret = addon.getSetting("aria2_secret") or ""

    rpc_url = f"http://{host}:{port}/jsonrpc"
    headers = {"Content-Type": "application/json"}

    params = []
    if secret:
        params.append(f"token:{secret}")
    params.append([url])

    payload = {
        "jsonrpc": "2.0",
        "id": "logcatcher",
        "method": "aria2.addUri",
        "params": params
    }

    try:
        req = urllib.request.Request(rpc_url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        urllib.request.urlopen(req, timeout=3)
        xbmcgui.Dialog().notification("Log Catcher", "Sent to Aria2", xbmcgui.NOTIFICATION_INFO, 3000)
    except Exception as e:
        xbmcgui.Dialog().notification("Aria2 Error", str(e), xbmcgui.NOTIFICATION_ERROR, 4000)


if __name__ == "__main__":
    if len(sys.argv) > 2:
        qs = sys.argv[2][1:]
        params = dict(urllib.parse.parse_qsl(qs))
    else:
        params = {}
    router(params)
