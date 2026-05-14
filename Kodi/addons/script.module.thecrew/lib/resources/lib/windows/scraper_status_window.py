# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on - Scraper Status Window
 *
 * @file scraper_status_window.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ***********************************************************
'''

import xbmc
import xbmcgui
import xbmcvfs
from datetime import datetime
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from resources.lib.modules import control
from resources.lib.modules.scraper_test import ScraperTester
from resources.lib.modules.crewruntime import c


class ScraperStatusWindow(xbmcgui.WindowXMLDialog):
    """Window to display scraper status and testing."""

    def __init__(self, *args, **kwargs):
        xbmcgui.WindowXMLDialog.__init__(self)
        self.tester = ScraperTester()
        self.current_category = 'direct'
        self.status_data = None
        self.testing_in_progress = False

    def onInit(self):
        """Initialize the window."""
        # Set modern fanart background
        try:
            fanart = c.addon_fanart()
            self.setProperty('fanart', fanart)
        except:
            pass

        # Load cached status or test if needed
        self.load_status()

        # Set default category to direct sources
        self.setProperty('category', 'direct')
        xbmc.executebuiltin('Control.SetFocus(3001)')

        # Update category display
        self.update_category_display('direct')
        self.update_category_display('direct')

    def load_status(self):
        """Load scraper status from cache or run basic test."""
        c.log('[ScraperStatus] load_status() called')
        self.status_data = self.tester.load_status()
        c.log(f'[ScraperStatus] Loaded status_data from cache: {self.status_data is not None}')

        if self.status_data:
            c.log(f'[ScraperStatus] Cache has {len(self.status_data.get("direct", []))} direct scrapers')

        if not self.status_data or not self.tester.is_cache_valid(max_age_hours=24):
            c.log('[ScraperStatus] Cache invalid or empty, testing scrapers...')
            # No valid cache, show loading dialog
            progress = xbmcgui.DialogProgress()
            progress.create('[COLOR orchid]THE CREW[/COLOR]', 'Testing scrapers...')

            def progress_callback(current, total, name):
                percent = int((current / total) * 100)
                progress.update(percent, f'Testing {current}/{total}: {name}')
                if progress.iscanceled():
                    return False
                return True

            self.status_data = self.tester.test_all_scrapers(
                test_type='connectivity',
                progress_callback=progress_callback
            )
            c.log(f'[ScraperStatus] After testing: {len(self.status_data.get("direct", []))} direct scrapers')
            progress.close()

        # Update summary display
        self.update_summary()

    def update_summary(self):
        """Update the summary information."""
        if not self.status_data:
            return

        summary = self.status_data.get('summary', {})

        summary_text = (
            f"Total: {summary.get('total', 0)} | "
            f"[COLOR lime]Working: {summary.get('working', 0)}[/COLOR] | "
            f"[COLOR orange]Accessible: {summary.get('accessible', 0)}[/COLOR] | "
            f"[COLOR red]Blocked: {summary.get('blocked', 0)}[/COLOR] | "
            f"[COLOR gray]Disabled: {summary.get('disabled', 0)}[/COLOR]")

        # Format the timestamp
        last_updated_raw = summary.get('last_updated')
        if last_updated_raw:
            try:
                # Parse ISO format timestamp
                dt = datetime.fromisoformat(last_updated_raw)
                # Format as readable string
                last_updated = dt.strftime('%b %d, %Y %I:%M %p')
            except:
                last_updated = 'Click "Test All Scrapers" to run tests'
        else:
            last_updated = 'Click "Test All Scrapers" to run tests'

        self.setProperty('summary_text', summary_text)
        self.setProperty('last_updated', last_updated)

    def update_category_display(self, category):
        """Update the scraper list for the selected category."""
        c.log(f'[ScraperStatus] update_category_display called for category: {category}')

        if not self.status_data:
            c.log('[ScraperStatus] No status_data available!')
            return

        self.current_category = category
        scrapers = self.status_data.get(category, [])
        c.log(f'[ScraperStatus] Found {len(scrapers)} scrapers for category {category}')

        # Clear the list
        self.clearList()

        # Populate the list
        for scraper in scrapers:
            c.log(f'[ScraperStatus] Adding scraper: {scraper.get("name")}')
            list_item = self.create_list_item(scraper)
            self.getControl(5000).addItem(list_item)

    def create_list_item(self, scraper):
        """Create a list item for a scraper."""
        name = scraper.get('name', 'Unknown')
        accessible = scraper.get('accessible', False)
        working = scraper.get('working', False)
        disabled = scraper.get('disabled', False)
        defunct = scraper.get('defunct', False)
        pack_capable = scraper.get('pack_capable', False)
        response_time = scraper.get('response_time')
        error = scraper.get('error')

        # Create list item
        list_item = xbmcgui.ListItem(label=name)

        # Set properties based on status
        if disabled and defunct:
            # Defunct scrapers (site permanently closed)
            status_icon = 'DefaultAddonBroken.png'  # Red X
            status_text = f'[COLOR gray]X Defunct (Site Closed)[/COLOR]'
            if error:
                status_text += f' - {error[:50]}'
            status_color = 'FF606060'
        elif disabled:
            # Disabled scrapers - SHOW IN RED
            status_icon = 'DefaultAddonBroken.png'  # Red X
            status_text = '[COLOR red]X DISABLED[/COLOR]'
            status_color = 'FFFF0000'
        elif working:
            # Fully tested and working
            status_icon = 'DefaultAddonEnabled.png'  # Green checkmark
            status_text = '[COLOR lime]OK Working[/COLOR]'
            status_color = 'FF00FF00'
        elif accessible:
            # Accessible but not fully tested
            status_icon = 'DefaultAddonEnabled.png'
            status_text = '[COLOR orange]OK Accessible[/COLOR]'
            status_color = 'FFFFA500'
        else:
            # Not accessible
            status_icon = 'DefaultAddonBroken.png'  # Red X
            status_text = f'[COLOR red]X Blocked[/COLOR]'
            if error:
                status_text += f' - {error[:40]}'
            status_color = 'FFFF0000'

        list_item.setProperty('status_icon', status_icon)
        list_item.setProperty('status', status_text)
        list_item.setProperty('status_color', status_color)
        list_item.setProperty('pack_capable', str(pack_capable).lower())

        if pack_capable:
            list_item.setProperty('pack_badge', '[PACK]')  # Show PACK text badge

        if response_time:
            response_text = f'{response_time:.2f}s'
            list_item.setProperty('response_time', response_text)
        else:
            response_text = 'N/A'

        # Store complete scraper data in the list item for details dialog
        list_item.setProperty('scraper_name', name)
        list_item.setProperty('scraper_module', scraper.get('module', ''))
        list_item.setProperty('scraper_category', scraper.get('category', ''))
        list_item.setProperty('scraper_accessible', str(accessible))
        list_item.setProperty('scraper_working', str(working))
        list_item.setProperty('scraper_disabled', str(disabled))
        list_item.setProperty('scraper_defunct', str(defunct))
        list_item.setProperty('scraper_pack_capable', str(pack_capable))
        list_item.setProperty('scraper_response_time', response_text)
        list_item.setProperty('scraper_error', error or 'None')

        return list_item

    def clearList(self):
        """Clear the scraper list."""
        try:
            self.getControl(5000).reset()
        except Exception:
            pass

    def show_scraper_details(self):
        """Show detailed information about the selected scraper."""
        try:
            selected_item = self.getControl(5000).getSelectedItem()
            if not selected_item:
                return

            name = selected_item.getProperty('scraper_name')
            module = selected_item.getProperty('scraper_module')
            category = selected_item.getProperty('scraper_category')
            accessible = selected_item.getProperty('scraper_accessible') == 'True'
            working = selected_item.getProperty('scraper_working') == 'True'
            disabled = selected_item.getProperty('scraper_disabled') == 'True'
            defunct = selected_item.getProperty('scraper_defunct') == 'True'
            pack_capable = selected_item.getProperty('scraper_pack_capable') == 'True'
            response_time = selected_item.getProperty('scraper_response_time')
            error = selected_item.getProperty('scraper_error')

            # Build status summary
            if disabled and defunct:
                status = '[COLOR gray]Defunct (Site Closed)[/COLOR]'
            elif disabled:
                status = '[COLOR gray]Disabled[/COLOR]'
            elif working:
                status = '[COLOR lime]Working[/COLOR]'
            elif accessible:
                status = '[COLOR orange]Accessible[/COLOR]'
            else:
                status = '[COLOR red]Blocked[/COLOR]'

            # Build category name
            category_names = {
                'en': 'Direct (English)',
                'en_de': 'Direct (English/German)',
                'en_tor': 'Torrent'
            }
            category_text = category_names.get(category, category)

            # Build message
            message = (
                f'[B]Name:[/B] {name}\n'
                f'[B]Category:[/B] {category_text}\n'
                f'[B]Module:[/B] {module}\n'
                f'[B]Status:[/B] {status}\n'
                f'[B]Response Time:[/B] {response_time}\n'
                f'[B]Pack Capable:[/B] {"Yes" if pack_capable else "No"}'
            )

            if error and error != 'None':
                message += f'\n[B]Error:[/B] {error}'

            xbmcgui.Dialog().textviewer(
                f'[COLOR orchid]THE CREW[/COLOR] - Scraper Details',
                message
            )

        except Exception as e:
            c.log(f'[ScraperStatus] Error showing details: {e}')

    def onClick(self, controlID):
        """Handle button clicks."""
        if controlID == 5000:  # Scraper list item clicked
            self.show_scraper_details()

        elif controlID == 3001:  # Direct sources tab
            self.update_category_display('direct')

        elif controlID == 3002:  # Torrent sources tab
            self.update_category_display('torrent')

        elif controlID == 3003:  # Usenet sources tab
            self.update_category_display('usenet')

        elif controlID == 8001:  # Refresh status
            self.refresh_status()

        elif controlID == 8002:  # Test all scrapers
            self.test_all_scrapers()

        elif controlID == 8003:  # Close
            self.close()

    def refresh_status(self):
        """Reload status from cache."""
        self.load_status()
        self.update_category_display(self.current_category)

    def test_all_scrapers(self):
        """Run full test on all scrapers."""
        if self.testing_in_progress:
            xbmcgui.Dialog().notification(
                '[COLOR orchid]THE CREW[/COLOR]',
                'Test already in progress',
                xbmcgui.NOTIFICATION_WARNING,
                3000
            )
            return

        # Confirm with user
        if not xbmcgui.Dialog().yesno(
            '[COLOR orchid]THE CREW[/COLOR] - Test All Scrapers',
            'This will test all scrapers for connectivity.\nThis may take several minutes.\n\nContinue?'
        ):
            return

        self.testing_in_progress = True

        # Show progress dialog
        progress = xbmcgui.DialogProgress()
        progress.create('[COLOR orchid]THE CREW[/COLOR]', 'Testing all scrapers...')

        def progress_callback(current, total, name):
            percent = int((current / total) * 100)
            progress.update(percent, f'Testing {current}/{total}: {name}')
            if progress.iscanceled():
                return False
            return True

        try:
            self.status_data = self.tester.test_all_scrapers(
                test_type='connectivity',
                progress_callback=progress_callback
            )

            progress.close()

            # Update display
            self.update_summary()
            self.update_category_display(self.current_category)

            xbmcgui.Dialog().notification(
                '[COLOR orchid]THE CREW[/COLOR]',
                'Scraper testing complete!',
                xbmcgui.NOTIFICATION_INFO,
                3000
            )

        except Exception as e:
            c.log(f'[ScraperStatus] Test error: {e}')
            progress.close()
            xbmcgui.Dialog().notification(
                '[COLOR orchid]THE CREW[/COLOR]',
                f'Test failed: {str(e)}',
                xbmcgui.NOTIFICATION_ERROR,
                5000
            )

        finally:
            self.testing_in_progress = False

    def onAction(self, action):
        """Handle navigation actions."""
        if action.getId() in (9, 10, 92, 216, 247, 257, 275, 61467, 61448):
            # Close window on back/escape
            self.close()


def open_scraper_status():
    """Open the scraper status window."""
    try:
        # Use the artwork addon path - Kodi will append resources/skins/{skin}/{resolution}
        addon_path = xbmcvfs.translatePath('special://home/addons/script.thecrew.artwork')
        window = ScraperStatusWindow('ScraperStatus.xml', addon_path, 'modern', '1080i')
        window.doModal()
        del window
    except Exception as e:
        c.log(f'[ScraperStatus] Error opening window: {e}')
        xbmcgui.Dialog().notification(
            '[COLOR orchid]THE CREW[/COLOR]',
            f'Error opening scraper status: {str(e)}',
            xbmcgui.NOTIFICATION_ERROR,
            5000
        )
