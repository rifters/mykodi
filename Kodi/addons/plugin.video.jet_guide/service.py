import xbmc
import xbmcaddon
import time

ADDON = xbmcaddon.Addon()

def run():
    # Wait a moment for Kodi to fully start
    xbmc.sleep(1000)
    # Launch ten buttons interface
    addon_id = ADDON.getAddonInfo('id')
    xbmc.executebuiltin(f'RunPlugin(plugin://{addon_id}/?action=show_ten_buttons)')

if __name__ == '__main__':
    monitor = xbmc.Monitor()
    run()
    while not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break