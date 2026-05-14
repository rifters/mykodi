# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file adult.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import os
import sys
import traceback
from urllib.parse import quote_plus
from ..modules import control
from ..modules.crewruntime import c
from ..adult_sites.base import CrewAdult
from .. import adult_sites  # Trigger site registration via __init__.py


class Adult:
    """Main adult content indexer"""

    def __init__(self):
        self.list = []
        # Store full path directly
        self.icon = c.addon_adult_icon()
        self.fanart = c.addon_fanart()

        if c.devmode:
            c.log(f'[Adult] Initialized with icon: {self.icon}, fanart: {self.fanart}')

    def root(self):
        """Show main adult content menu"""
        try:
            c.log('[Adult] Building root menu')

            # Get all registered sites
            sites = CrewAdult.get_all_sites()

            sysaddon = sys.argv[0]
            self.list = []

            for site in sites:
                # RedTube goes directly to search, others to site handler
                if site.name == 'redtube':
                    url = f'{sysaddon}?action=adult_search&site={site.name}'
                else:
                    url = f'{sysaddon}?action=adult_site_handler&site={site.name}'

                if c.devmode:
                    c.log(f'[Adult] Registering site: {site.name}, title: {site.title}, icon: {site.icon}')

                item = {
                    'name': site.title,
                    'url': url,
                    'icon': site.icon,
                    'thumb': site.icon,
                    'fanart': site.fanart,
                    'isFolder': True
                }
                self.list.append(item)

            # Add mPorno as a regular site (now converted to Python)
            # No longer using the XML directory link

            # Add Developer Testings
            self.list.append({
                'name': 'Testings',
                'url': 'plugin://plugin.video.thecrew/?action=developer',
                'icon': self.icon,
                'thumb': self.icon,
                'fanart': self.fanart,
                'isFolder': False
            })

            c.log(f'[Adult] Built menu with {len(self.list)} items')
            self._addDirectory(self.list)
            return self.list

        except Exception as e:
            c.log(f'[Adult] Root menu error: {e}')
            return []

    def site_handler(self, site_name):
        """Handle a specific site's main page"""
        try:
            c.log(f'[Adult] Handling site: {site_name}')

            site = CrewAdult.get_site(site_name)
            if not site:
                c.log(f'[Adult] Site not found: {site_name}')
                return

            self.list = []

            sysaddon = sys.argv[0]

            # Check if site has categories
            categories = site.get_categories()
            if categories:
                c.log(f'[Adult] Site has {len(categories)} categories')
                for cat_url, cat_name, cat_thumb in categories:
                    url = f'{sysaddon}?action=adult_videos&site={site_name}&url={quote_plus(cat_url)}'
                    item = {
                        'name': cat_name,
                        'url': url,
                        'icon': cat_thumb or site.icon,
                        'fanart': site.fanart,
                        'isFolder': True
                    }
                    self.list.append(item)

            # Check if site has search
            if site_name == 'redtube':
                url = f'{sysaddon}?action=adult_search&site={site_name}'
                item = {
                    'name': '** Search **',
                    'url': url,
                    'icon': site.icon,
                    'fanart': site.fanart,
                    'isFolder': True
                }
                self.list.insert(0, item)

            # If no categories, show videos directly
            if not categories and site_name != 'redtube':
                return self.videos(site_name)

            self._addDirectory(self.list)
            return self.list

        except Exception as e:

            c.log(f'[Adult] Site handler error: {e}')
            c.log(traceback.format_exc())
            return []

    def videos(self, site_name, url=None, page='1'):
        """Show videos from a site or category"""
        try:
            page_num = int(page) if page else 1
            c.log(f'[Adult] Getting videos from {site_name}, url={url}, page={page_num}')

            site = CrewAdult.get_site(site_name)
            if not site:
                c.log(f'[Adult] Site not found: {site_name}')
                return []

            # Get videos
            videos = site.get_videos(url=url, page=page_num)

            sysaddon = sys.argv[0]

            self.list = []
            for video_url, title, thumbnail in videos:
                # Check for next page indicator
                if video_url == 'NEXT_PAGE':
                    # Build next page URL - handle None url for sites like XXXFiles
                    if url:
                        next_url = f'{sysaddon}?action=adult_videos&site={site_name}&url={quote_plus(url)}&page={page_num + 1}'
                    else:
                        next_url = f'{sysaddon}?action=adult_videos&site={site_name}&page={page_num + 1}'
                    item = {
                        'name': f'[COLOR orange]{title}[/COLOR]',
                        'url': next_url,
                        'icon': c.addon_next(),
                        'fanart': site.fanart,
                        'isPlayable': False,
                        'isFolder': True
                    }
                else:
                    item_url = f'{sysaddon}?action=adult_play&site={site_name}&url={quote_plus(video_url)}'
                    item = {
                        'name': title,
                        'url': item_url,
                        'icon': thumbnail or site.icon,
                        'fanart': site.fanart,
                        'isPlayable': True,
                        'isFolder': False
                    }
                self.list.append(item)

            c.log(f'[Adult] Showing {len(self.list)} items (page {page_num})')
            self._addDirectory(self.list)
            return self.list

        except Exception as e:

            c.log(f'[Adult] Videos error: {e}')
            c.log(traceback.format_exc())
            return []

    def search(self, site_name):
        """Search a site"""
        try:
            c.log(f'[Adult] Search for site: {site_name}')

            site = CrewAdult.get_site(site_name)
            if not site:
                c.log(f'[Adult] Site not found: {site_name}')
                return []

            # Get search keyword
            keyboard = control.keyboard('', site.title)
            keyboard.doModal()

            if not keyboard.isConfirmed():
                return []

            keyword = keyboard.getText()
            if not keyword:
                return []

            c.log(f'[Adult] Searching for: {keyword}')

            # Get search results
            results = site.search(keyword)

            sysaddon = sys.argv[0]

            self.list = []
            for video_url, title, thumbnail in results:
                item_url = f'{sysaddon}?action=adult_play&site={site_name}&url={quote_plus(video_url)}'
                item = {
                    'name': title,
                    'url': item_url,
                    'icon': thumbnail or site.icon,
                    'fanart': site.fanart,
                    'isPlayable': True,
                    'isFolder': False
                }
                self.list.append(item)

            c.log(f'[Adult] Found {len(self.list)} results')
            self._addDirectory(self.list)

            return self.list

        except Exception as e:

            c.log(f'[Adult] Search error: {e}')
            c.log(traceback.format_exc())
            return []

    def play(self, site_name, video_url):
        """Play a video"""
        try:
            c.log(f'[Adult] ====== PLAY START ======')
            c.log(f'[Adult] Site: {site_name}')
            c.log(f'[Adult] Video URL: {video_url}')

            site = CrewAdult.get_site(site_name)
            if not site:
                c.log(f'[Adult] (X) Site not found: {site_name}')
                control.infoDialog('Site not found', icon='ERROR')
                return

            # Resolve video URL
            c.log(f'[Adult] Calling site.resolve()...')
            playable_url = site.resolve(video_url)

            c.log(f'[Adult] Resolve returned: {playable_url[:200] if playable_url else "None"}')

            if not playable_url:
                c.log('[Adult] (X) Could not resolve video URL')
                control.infoDialog('Could not resolve video', icon='ERROR')
                return

            c.log(f'[Adult] (OK) Resolved successfully')
            c.log(f'[Adult] Creating player and playing...')

            # Create listitem and play
            from ..indexers import lists
            player = lists.player()
            player.play(playable_url)

            c.log(f'[Adult] ====== PLAY END ======')

        except Exception as e:

            c.log(f'[Adult] (X) Play error: {e}')
            c.log(traceback.format_exc())
            control.infoDialog(f'Playback error: {str(e)}', icon='ERROR')

    def _addDirectory(self, items, queue=False):
        """Add directory items to Kodi"""
        if items is None or len(items) == 0:
            return

        try:
            syshandle = int(sys.argv[1])
            addonFanart = c.addon_fanart()

            for i in items:
                try:
                    name = i['name']
                    url = i['url']
                    icon = i.get('icon', self.icon)
                    fanart = i.get('fanart', addonFanart)
                    isPlayable = i.get('isPlayable', False)
                    isFolder = i.get('isFolder', True)

                    if c.devmode:
                        c.log(f'[Adult] Adding item: {name}, icon: {icon}')

                    try:
                        item = control.item(label=name, offscreen=True)
                    except Exception:
                        item = control.item(label=name)

                    item.setArt({'icon': icon, 'thumb': icon, 'poster': icon, 'fanart': fanart})
                    control.addItem(handle=syshandle, url=url, listitem=item, isFolder=isFolder)
                except Exception as e:
                    c.log(f'[Adult] Error adding item {name}: {e}')
                    pass

            # Use 'addons' content type for directory listings like navigator does
            control.content(syshandle, 'addons')
            control.directory(syshandle, cacheToDisc=True)
        except Exception as e:

            c.log(f'[Adult] addDirectory error: {e}')
            c.log(traceback.format_exc())


def adult_indexer():
    """Factory function for backward compatibility"""
    return Adult()
