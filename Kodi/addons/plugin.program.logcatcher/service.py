import xbmc
import xbmcaddon
import xbmcvfs
import json
import os
import re
import time

addon = xbmcaddon.Addon()
addon_id = addon.getAddonInfo('id')
profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))

captured_file = os.path.join(profile, "captured.json")

filtered_media  = os.path.join(profile, "filtered_media.json")
filtered_plugin = os.path.join(profile, "filtered_plugin.json")
filtered_http   = os.path.join(profile, "filtered_http.json")
filtered_local  = os.path.join(profile, "filtered_local.json")
filtered_nested = os.path.join(profile, "filtered_nested.json")
filtered_cache  = os.path.join(profile, "filtered_cache.json")
filtered_all    = os.path.join(profile, "filtered_all.json")

log_path = xbmcvfs.translatePath("special://logpath/kodi.log")

media_exts = [".mkv", ".mp4", ".avi", ".ts", ".m3u8", ".mov"]


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


def save_json(path, data):
    with xbmcvfs.File(path, "w") as f:
        f.write(json.dumps(data, indent=2))


# Clean URL: strip everything after first "|"
def normalize(url):
    if not url:
        return ""
    url = url.strip()
    if "|" in url:
        url = url.split("|", 1)[0].strip()
    return url


def dedupe(entries):
    seen = set()
    out = []
    for e in entries:
        clean = normalize(e.get("url", ""))
        if clean and clean not in seen:
            seen.add(clean)
            e["url"] = clean
            out.append(e)
    return out


def sort_newest(entries):
    return sorted(entries, key=lambda e: e.get("ts", 0), reverse=True)


def is_nested(url):
    u = url.lower()
    return ("url=" in u) or ("url%3d" in u)


def is_cache(url):
    u = url.lower()
    return (
        "/cache/" in u or
        "\\cache\\" in u or
        "special://temp" in u or
        "special://home/cache" in u
    )


def rebuild_filtered():
    entries = load_json(captured_file)

    # Normalize + dedupe + sort
    entries = dedupe(entries)
    entries = sort_newest(entries)

    media  = []
    plugin = []
    http   = []
    local  = []
    nested = []
    cache  = []
    all_urls = entries[:]  # already clean

    for e in entries:
        clean = normalize(e.get("url", ""))
        url_norm = clean.lower()
        e["url"] = clean

        ext = os.path.splitext(url_norm)[1]

        if ext in media_exts:
            media.append(e)

        if url_norm.startswith("plugin://"):
            plugin.append(e)

        if url_norm.startswith("http://") or url_norm.startswith("https://"):
            http.append(e)

        if url_norm.startswith("c:\\") or url_norm.startswith("special://"):
            local.append(e)

        if is_nested(url_norm):
            nested.append(e)

        if is_cache(url_norm):
            cache.append(e)

    # Final clean + sort
    media  = sort_newest(dedupe(media))
    plugin = sort_newest(dedupe(plugin))
    http   = sort_newest(dedupe(http))
    local  = sort_newest(dedupe(local))
    nested = sort_newest(dedupe(nested))
    cache  = sort_newest(dedupe(cache))

    save_json(filtered_media,  media)
    save_json(filtered_plugin, plugin)
    save_json(filtered_http,   http)
    save_json(filtered_local,  local)
    save_json(filtered_nested, nested)
    save_json(filtered_cache,  cache)
    save_json(filtered_all,    all_urls)


def tail_log():
    last_size = 0
    monitor = xbmc.Monitor()

    while not monitor.abortRequested():
        try:
            if not os.path.exists(log_path):
                xbmc.sleep(1000)
                continue

            size = os.path.getsize(log_path)
            if size < last_size:
                last_size = 0

            if size > last_size:
                with open(log_path, "r", errors="ignore") as f:
                    f.seek(last_size)
                    new = f.read()
                last_size = size

                # Capture plugin:// and http(s)://
                urls = re.findall(r'(https?://[^\s]+|plugin://[^\s]+)', new)

                if urls:
                    entries = load_json(captured_file)
                    ts_now = time.time()
                    for u in urls:
                        entries.append({"url": u, "ts": ts_now})
                    save_json(captured_file, entries)
                    rebuild_filtered()

        except Exception as e:
            xbmc.log(f"[LogCatcher] service error: {e}", xbmc.LOGERROR)

        if monitor.waitForAbort(0.5):
            break


if __name__ == "__main__":
    tail_log()
