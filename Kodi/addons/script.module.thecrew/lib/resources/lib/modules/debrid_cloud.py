# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file debrid_cloud.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

import sys
import xbmcplugin
import xbmcgui
from urllib.parse import quote_plus

from . import debridapis
from .crewruntime import c
from . import control


def rd_cloud():
    """Display Real-Debrid cloud storage - list of torrents"""
    try:
        rd = debridapis.realdebrid()
        torrents = rd.user_cloud()

        if not torrents:
            control.infoDialog('No torrents found in Real-Debrid cloud storage')
            return

        items = []
        for idx, torrent in enumerate(torrents, 1):
            torrent_id = torrent.get('id', '')
            filename = torrent.get('filename', 'Unknown')

            # Create list item
            list_item = xbmcgui.ListItem(label=f'[B]{idx:02d}[/B] - {filename}')

            # Set info
            list_item.setInfo('video', {'title': filename, 'plot': f'Torrent ID: {torrent_id}'})

            # Create URL to browse this torrent's files
            url = f'plugin://plugin.video.thecrew/?action=rd_cloud_browse&torrent_id={torrent_id}'

            # Add enhanced context menu
            context_menu = []
            delete_url = f'RunPlugin(plugin://plugin.video.thecrew/?action=rd_cloud_delete&torrent_id={torrent_id})'
            context_menu.append(('[B]Delete Torrent[/B]', delete_url))
            refresh_url = f'Container.Refresh(plugin://plugin.video.thecrew/?action=rd_cloud)'
            context_menu.append(('[B]Refresh[/B]', refresh_url))
            add_url = f'RunPlugin(plugin://plugin.video.thecrew/?action=rd_cloud_add)'
            context_menu.append(('[B]Add to Cloud[/B]', add_url))
            list_item.addContextMenuItems(context_menu)

            items.append((url, list_item, True))

        # Add items to directory
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), items, len(items))
        xbmcplugin.endOfDirectory(int(sys.argv[1]))

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in rd_cloud: {e}', 1)
        control.infoDialog('Error loading Real-Debrid cloud', icon='ERROR')


def rd_cloud_browse(torrent_id):
    """Browse files in a Real-Debrid torrent"""
    try:
        rd = debridapis.realdebrid()
        torrent_info = rd.torrent_info(torrent_id)

        if not torrent_info:
            control.infoDialog('Could not load torrent information')
            return

        files = torrent_info.get('files', [])
        links = torrent_info.get('links', [])

        if not files:
            control.infoDialog('No files found in this torrent')
            return

        # Filter to selected video files
        video_extensions = ['.mkv', '.mp4', '.avi', '.m4v', '.mov', '.flv', '.wmv', '.mpg', '.mpeg']

        items = []
        file_idx = 0
        for idx, file_info in enumerate(files):
            if file_info.get('selected') != 1:
                continue

            path = file_info.get('path', '')

            # Check if it's a video file
            if not any(path.lower().endswith(ext) for ext in video_extensions):
                continue

            # Get filename from path
            filename = path.split('/')[-1] if '/' in path else path
            size_bytes = file_info.get('bytes', 0)
            size_gb = float(size_bytes) / (1024**3)

            # Get corresponding link
            link = links[idx] if idx < len(links) else None
            if not link:
                continue

            file_idx += 1
            label = f'[B]{file_idx:02d}[/B] - [{size_gb:.2f} GB] {filename}'

            # Create list item
            list_item = xbmcgui.ListItem(label=label)
            list_item.setInfo('video', {'title': filename, 'size': size_bytes})
            list_item.setProperty('IsPlayable', 'true')

            # Create URL to play this file
            url = f'plugin://plugin.video.thecrew/?action=rd_cloud_play&link={quote_plus(link)}'

            items.append((url, list_item, False))

        if not items:
            control.infoDialog('No playable video files found in this torrent')
            return

        # Add items to directory
        xbmcplugin.setContent(int(sys.argv[1]), 'videos')
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), items, len(items))
        xbmcplugin.endOfDirectory(int(sys.argv[1]))

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in rd_cloud_browse: {e}', 1)
        control.infoDialog('Error browsing torrent files', icon='ERROR')


def rd_cloud_play(link):
    """Play a RealDebrid cloud file"""
    try:
        rd = debridapis.realdebrid()
        resolved_link = rd.unrestrict_link(link)

        if not resolved_link:
            control.infoDialog('Could not resolve link', icon='ERROR')
            return

        # Create playable item
        list_item = xbmcgui.ListItem(path=resolved_link)
        xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, list_item)

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in rd_cloud_play: {e}', 1)
        control.infoDialog('Error playing file', icon='ERROR')


def rd_cloud_delete(torrent_id):
    """Delete a torrent from Real-Debrid cloud"""
    try:
        if not control.yesnoDialog('Are you sure you want to delete this torrent?'):
            return

        rd = debridapis.realdebrid()
        success = rd.delete_torrent(torrent_id)

        if success:
            control.infoDialog('Torrent deleted successfully')
            control.refresh()
        else:
            control.infoDialog('Failed to delete torrent', icon='ERROR')

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in rd_cloud_delete: {e}', 1)
        control.infoDialog('Error deleting torrent', icon='ERROR')


# ===== ALLDEBRID CLOUD =====

def ad_cloud():
    """Display AllDebrid cloud storage - list of magnets"""
    try:
        ad = debridapis.alldebrid()
        magnets = ad.user_cloud()

        if not magnets:
            control.infoDialog('No magnets found in AllDebrid cloud storage')
            return

        items = []
        for idx, magnet in enumerate(magnets, 1):
            magnet_id = magnet.get('id', '')
            filename = magnet.get('filename', 'Unknown')

            # Create list item
            list_item = xbmcgui.ListItem(label=f'[B]{idx:02d}[/B] - {filename}')
            list_item.setInfo('video', {'title': filename, 'plot': f'Magnet ID: {magnet_id}'})

            # Create URL to browse this magnet's files
            url = f'plugin://plugin.video.thecrew/?action=ad_cloud_browse&magnet_id={magnet_id}'

            # Add enhanced context menu
            context_menu = []
            delete_url = f'RunPlugin(plugin://plugin.video.thecrew/?action=ad_cloud_delete&magnet_id={magnet_id})'
            context_menu.append(('[B]Delete Magnet[/B]', delete_url))
            refresh_url = f'Container.Refresh(plugin://plugin.video.thecrew/?action=ad_cloud)'
            context_menu.append(('[B]Refresh[/B]', refresh_url))
            add_url = f'RunPlugin(plugin://plugin.video.thecrew/?action=ad_cloud_add)'
            context_menu.append(('[B]Add to Cloud[/B]', add_url))
            list_item.addContextMenuItems(context_menu)

            items.append((url, list_item, True))

        # Add items to directory
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), items, len(items))
        xbmcplugin.endOfDirectory(int(sys.argv[1]))

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in ad_cloud: {e}', 1)
        control.infoDialog('Error loading AllDebrid cloud', icon='ERROR')


def ad_cloud_browse(magnet_id):
    """Browse files in an AllDebrid magnet"""
    try:
        ad = debridapis.alldebrid()
        magnet_info = ad.magnet_status(magnet_id)

        if not magnet_info or 'magnets' not in magnet_info:
            control.infoDialog('Could not load magnet information')
            return

        magnet_data = magnet_info['magnets'][0] if magnet_info['magnets'] else {}
        links = magnet_data.get('links', [])

        if not links:
            control.infoDialog('No files found in this magnet')
            return

        # Filter to video files
        video_extensions = ['.mkv', '.mp4', '.avi', '.m4v', '.mov', '.flv', '.wmv', '.mpg', '.mpeg']

        items = []
        file_idx = 0
        for link_info in links:
            filename = link_info.get('filename', '')
            link = link_info.get('link', '')
            size_bytes = link_info.get('size', 0)

            # Check if it's a video file
            if not any(filename.lower().endswith(ext) for ext in video_extensions):
                continue

            size_gb = float(size_bytes) / (1024**3)
            file_idx += 1
            label = f'[B]{file_idx:02d}[/B] - [{size_gb:.2f} GB] {filename}'

            # Create list item
            list_item = xbmcgui.ListItem(label=label)
            list_item.setInfo('video', {'title': filename, 'size': size_bytes})
            list_item.setProperty('IsPlayable', 'true')

            # Create URL to play this file
            url = f'plugin://plugin.video.thecrew/?action=ad_cloud_play&link={quote_plus(link)}'

            items.append((url, list_item, False))

        if not items:
            control.infoDialog('No playable video files found in this magnet')
            return

        # Add items to directory
        xbmcplugin.setContent(int(sys.argv[1]), 'videos')
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), items, len(items))
        xbmcplugin.endOfDirectory(int(sys.argv[1]))

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in ad_cloud_browse: {e}', 1)
        control.infoDialog('Error browsing magnet files', icon='ERROR')


def ad_cloud_play(link):
    """Play an AllDebrid cloud file"""
    try:
        ad = debridapis.alldebrid()
        resolved_link = ad.unrestrict_link(link)

        if not resolved_link:
            control.infoDialog('Could not resolve link', icon='ERROR')
            return

        # Create playable item
        list_item = xbmcgui.ListItem(path=resolved_link)
        xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, list_item)

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in ad_cloud_play: {e}', 1)
        control.infoDialog('Error playing file', icon='ERROR')


def ad_cloud_delete(magnet_id):
    """Delete a magnet from AllDebrid cloud"""
    try:
        if not control.yesnoDialog('Are you sure you want to delete this magnet?'):
            return

        ad = debridapis.alldebrid()
        success = ad.delete_magnet(magnet_id)

        if success:
            control.infoDialog('Magnet deleted successfully')
            control.refresh()
        else:
            control.infoDialog('Failed to delete magnet', icon='ERROR')

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in ad_cloud_delete: {e}', 1)
        control.infoDialog('Error deleting magnet', icon='ERROR')


# ===== PREMIUMIZE CLOUD =====

def pm_cloud(folder_id=None):
    """Display Premiumize cloud storage"""
    try:
        pm = debridapis.premiumize()
        cloud_data = pm.user_cloud(folder_id)

        folders = cloud_data.get('folders', [])
        files = cloud_data.get('files', [])

        if not folders and not files:
            control.infoDialog('No items found in Premiumize cloud storage')
            return

        items = []
        idx = 0

        # Add folders
        for folder in folders:
            if folder.get('type') != 'folder':
                continue

            idx += 1
            folder_id = folder.get('id', '')
            folder_name = folder.get('name', 'Unknown Folder')

            # Create list item
            list_item = xbmcgui.ListItem(label=f'[B]{idx:02d}[/B] - [FOLDER] {folder_name}')
            list_item.setInfo('video', {'title': folder_name})

            # Create URL to browse this folder
            url = f'plugin://plugin.video.thecrew/?action=pm_cloud&folder_id={folder_id}'

            items.append((url, list_item, True))

        # Add video files
        video_extensions = ['.mkv', '.mp4', '.avi', '.m4v', '.mov', '.flv', '.wmv', '.mpg', '.mpeg']

        for file_info in files:
            if file_info.get('type') == 'folder':
                continue

            filename = file_info.get('name', 'Unknown')

            # Check if it's a video file
            if not any(filename.lower().endswith(ext) for ext in video_extensions):
                continue

            idx += 1
            size_bytes = file_info.get('size', 0)
            size_gb = float(size_bytes) / (1024**3)
            link = file_info.get('link', '')

            if not link:
                continue

            label = f'[B]{idx:02d}[/B] - [FILE] [{size_gb:.2f} GB] {filename}'

            # Create list item
            list_item = xbmcgui.ListItem(label=label)
            list_item.setInfo('video', {'title': filename, 'size': size_bytes})
            list_item.setProperty('IsPlayable', 'true')

            # Create URL to play this file
            url = f'plugin://plugin.video.thecrew/?action=pm_cloud_play&link={quote_plus(link)}'

            # Add context menu
            context_menu = []
            refresh_url = f'Container.Refresh(plugin://plugin.video.thecrew/?action=pm_cloud)'
            context_menu.append(('[B]Refresh[/B]', refresh_url))
            add_url = f'RunPlugin(plugin://plugin.video.thecrew/?action=pm_cloud_add)'
            context_menu.append(('[B]Add to Cloud[/B]', add_url))
            transfers_url = f'Container.Update(plugin://plugin.video.thecrew/?action=pm_transfers)'
            context_menu.append(('[B]View Transfers[/B]', transfers_url))
            item_id = file_info.get('id', '')
            delete_url = f'RunPlugin(plugin://plugin.video.thecrew/?action=pm_cloud_delete&item_id={item_id})'
            context_menu.append(('[B]Delete File[/B]', delete_url))
            list_item.addContextMenuItems(context_menu)

            items.append((url, list_item, False))

        if not items:
            control.infoDialog('No items found in this folder')
            return

        # Add items to directory
        xbmcplugin.setContent(int(sys.argv[1]), 'videos')
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), items, len(items))
        xbmcplugin.endOfDirectory(int(sys.argv[1]))

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in pm_cloud: {e}', 1)
        control.infoDialog('Error loading Premiumize cloud', icon='ERROR')


def pm_cloud_play(link):
    """Play a Premiumize cloud file"""
    try:
        # Premiumize links are direct, no need to unrestrict
        list_item = xbmcgui.ListItem(path=link)
        xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, list_item)

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in pm_cloud_play: {e}', 1)
        control.infoDialog('Error playing file', icon='ERROR')


def pm_cloud_delete(item_id):
    """Delete an item from Premiumize cloud"""
    try:
        if not control.yesnoDialog('Are you sure you want to delete this item?'):
            return

        pm = debridapis.premiumize()
        success = pm.delete_item(item_id)

        if success:
            control.infoDialog('Item deleted successfully')
            control.refresh()
        else:
            control.infoDialog('Failed to delete item', icon='ERROR')

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in pm_cloud_delete: {e}', 1)
        control.infoDialog('Error deleting item', icon='ERROR')


# ===== ADD TO CLOUD / UPLOAD FUNCTIONS =====

def rd_cloud_add():
    """Add a magnet/torrent to Real-Debrid cloud"""
    try:
        # Prompt user for magnet link
        keyboard = control.keyboard('', 'Enter Magnet Link or Torrent URL')
        keyboard.doModal()

        if not keyboard.isConfirmed():
            return

        magnet_url = keyboard.getText()
        if not magnet_url:
            return

        # Add to Real-Debrid
        rd = debridapis.realdebrid()
        result = rd.add_magnet(magnet_url)

        if result and 'id' in result:
            torrent_id = result['id']
            # Auto-select all files
            rd.select_files(torrent_id, 'all')
            control.infoDialog(f'Successfully added to Real-Debrid cloud')
            control.refresh()
        else:
            control.infoDialog('Failed to add to Real-Debrid', icon='ERROR')

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in rd_cloud_add: {e}', 1)
        control.infoDialog('Error adding to cloud', icon='ERROR')


def ad_cloud_add():
    """Add a magnet to AllDebrid cloud"""
    try:
        # Prompt user for magnet link
        keyboard = control.keyboard('', 'Enter Magnet Link')
        keyboard.doModal()

        if not keyboard.isConfirmed():
            return

        magnet_url = keyboard.getText()
        if not magnet_url:
            return

        # Add to AllDebrid
        ad = debridapis.alldebrid()
        result = ad.upload_magnet(magnet_url)

        if result:
            control.infoDialog(f'Successfully added to AllDebrid cloud')
            control.refresh()
        else:
            control.infoDialog('Failed to add to AllDebrid', icon='ERROR')

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in ad_cloud_add: {e}', 1)
        control.infoDialog('Error adding to cloud', icon='ERROR')


def pm_cloud_add():
    """Add a magnet/torrent to Premiumize cloud"""
    try:
        # Prompt user for magnet link
        keyboard = control.keyboard('', 'Enter Magnet Link or Torrent URL')
        keyboard.doModal()

        if not keyboard.isConfirmed():
            return

        magnet_url = keyboard.getText()
        if not magnet_url:
            return

        # Add to Premiumize
        pm = debridapis.premiumize()
        result = pm.transfer_create(magnet_url)

        if result and result.get('status') == 'success':
            control.infoDialog(f'Successfully added to Premiumize cloud')
            control.refresh()
        else:
            control.infoDialog('Failed to add to Premiumize', icon='ERROR')

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in pm_cloud_add: {e}', 1)
        control.infoDialog('Error adding to cloud', icon='ERROR')


# ===== TRANSFER MANAGEMENT (Premiumize) =====

def pm_transfers():
    """Display active Premiumize transfers with progress"""
    try:
        pm = debridapis.premiumize()
        transfers = pm.transfer_list()

        if not transfers:
            control.infoDialog('No active transfers found')
            return

        items = []
        for idx, transfer in enumerate(transfers, 1):
            transfer_id = transfer.get('id', '')
            name = transfer.get('name', 'Unknown')
            status = transfer.get('status', 'unknown')
            progress = transfer.get('progress', 0)

            # Format status label with progress
            if status == 'finished':
                status_text = '[COLOR green]Completed[/COLOR]'
            elif status == 'running':
                status_text = f'[COLOR yellow]Downloading ({progress}%)[/COLOR]'
            elif status == 'queued':
                status_text = '[COLOR cyan]Queued[/COLOR]'
            elif status == 'error':
                status_text = '[COLOR red]Error[/COLOR]'
            else:
                status_text = status

            label = f'[B]{idx:02d}[/B] - {name} - {status_text}'

            # Create list item
            list_item = xbmcgui.ListItem(label=label)
            list_item.setInfo('video', {
                'title': name,
                'plot': f'Status: {status}\\nProgress: {progress}%\\nID: {transfer_id}'
            })

            # For now, just make it browsable (could add actions later)
            url = f'plugin://plugin.video.thecrew/?action=pm_cloud'

            # Add context menu
            context_menu = []
            refresh_url = f'RunPlugin(plugin://plugin.video.thecrew/?action=pm_transfers)'
            context_menu.append(('[B]Refresh Transfers[/B]', refresh_url))
            list_item.addContextMenuItems(context_menu)

            items.append((url, list_item, False))

        # Add items to directory
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), items, len(items))
        xbmcplugin.endOfDirectory(int(sys.argv[1]))

    except Exception as e:
        c.log(f'[Debrid Cloud] Error in pm_transfers: {e}', 1)
        control.infoDialog('Error loading transfers', icon='ERROR')
