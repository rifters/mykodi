import xbmc
import xbmcgui
import xbmcvfs
import xbmcaddon
import json
import os

ADDON = xbmcaddon.Addon()

class FavoritesManager:
    """Manage favorite channels"""
    def __init__(self):
        profile_path = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
        if not xbmcvfs.exists(profile_path):
            xbmcvfs.mkdirs(profile_path)
        self.favorites_path = os.path.join(profile_path, 'favorites.json')
        if not xbmcvfs.exists(self.favorites_path):
            self.favorites = []
            self.save_favorites()
        else:
            self.favorites = self.load_favorites()

    def load_favorites(self):
        """Load favorites from file"""
        try:
            with xbmcvfs.File(self.favorites_path, 'r') as f:
                data = f.read()
                if data:
                    return json.loads(data)
        except Exception as e:
            xbmc.log(f"Failed to load favorites: {str(e)}", xbmc.LOGERROR)
        return []

    def save_favorites(self):
        """Save favorites to file"""
        try:
            with xbmcvfs.File(self.favorites_path, 'w') as f:
                json_data = json.dumps(self.favorites, indent=2)
                f.write(json_data)
        except Exception as e:
            # xbmc.log(f"Failed to save favorites: {str(e)}", xbmc.LOGERROR)
            xbmcgui.Dialog().notification('Error', 'Failed to save favorites')

    def is_favorite(self, channel_id: str) -> bool:
        """Check if channel is in favorites"""
        return channel_id in self.favorites

    def add_favorite(self, channel_id: str) -> bool:
        """Add channel to favorites"""
        if channel_id not in self.favorites:
            self.favorites.append(channel_id)
            self.save_favorites()
            return True
        return False

    def remove_favorite(self, channel_id: str) -> bool:
        """Remove channel from favorites"""
        if channel_id in self.favorites:
            self.favorites.remove(channel_id)
            self.save_favorites()
            return True
        return False

# Global instance
favorites_manager = FavoritesManager()