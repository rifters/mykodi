import xbmc
import xbmcgui
import sys

def main():
    if len(sys.argv) < 2:
        return
    category = sys.argv[1]
    window = xbmcgui.Window(33000)  # EPG window ID
    try:
        # Set window property for filtering
        window.setProperty('CategoryFilter', category)
        # Get EPG window instance
        epg_window = xbmcgui.Window(33000)
        if not epg_window:
            return
        # Update the grid based on category
        xbmc.executebuiltin('Container.Refresh')
        
    except Exception as e:
        xbmcgui.Dialog().notification("Error", f"Failed to set category: {str(e)}")

if __name__ == '__main__':
    main()
  



