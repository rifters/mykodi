# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file premiumize_api.py
 * @package script.module.thecrew.apis
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 * Premiumize API Documentation: https://www.premiumize.me/api
 * API Base: https://www.premiumize.me/api/
 *
 ********************************************************cm*
'''

import requests

from ..modules import control
from ..modules.crewruntime import c


class PremiumizeAPI:
    """
    Premiumize API wrapper for The Crew addon

    API Base: https://www.premiumize.me/api/
    Authentication: API Key (apikey parameter)
    Credentials: Read from ResolveURL addon
    """

    def __init__(self):
        self.name = 'Premiumize'
        self.base_url = 'https://www.premiumize.me/api/'
        # Read API key from ResolveURL addon (single source of truth)
        self.resolver_addon = control.addon('script.module.resolveurl')
        self.api_key = self.resolver_addon.getSetting('PremiumizeMeResolver_token')
        c.log(f'[Premiumize API] Token from ResolveURL: {"SET" if self.api_key else "EMPTY"}', 1)

    def _get(self, endpoint, **params):
        """
        Make authenticated GET request to Premiumize API

        Args:
            endpoint: API endpoint path
            **params: Query parameters
        Returns: Response dictionary or None
        """
        try:
            # Premiumize uses Authorization header, not query parameter
            headers = {'Authorization': f'Bearer {self.api_key}'}
            full_url = self.base_url + endpoint
            c.log(f"[PM API] GET {endpoint}", 1)
            response = requests.get(full_url, params=params, headers=headers, timeout=30).json()
            c.log(f"[PM API] Response status: {response.get('status', 'NO STATUS')}", 1)

            if response.get('status') == 'success':
                return response
            else:
                message = response.get('message', 'Unknown error')
                c.log(f"[PM API] Error: {message}", 1)
            return None
        except Exception as e:
            c.log(f'[PM API] GET error: {e}', 1)
            return None

    def _post(self, endpoint, data=None):
        """
        Make authenticated POST request to Premiumize API

        Args:
            endpoint: API endpoint path
            data: POST data dictionary
        Returns: Response dictionary or None
        """
        try:
            # Premiumize uses Authorization header, not query/body parameter
            headers = {'Authorization': f'Bearer {self.api_key}'}
            response = requests.post(self.base_url + endpoint, data=data or {}, headers=headers, timeout=30).json()

            if response.get('status') == 'success':
                return response
            else:
                message = response.get('message', 'Unknown error')
                c.log(f"[PM API] Error: {message}", 1)
            return None
        except Exception as e:
            c.log(f'[PM API] POST error: {e}', 1)
            return None

    # ===== CLOUD BROWSING METHODS =====

    def user_cloud(self, folder_id=None):
        """
        Get list of items in Premiumize cloud storage

        Endpoint: GET /folder/list
        Args:
            folder_id: Optional folder ID to browse specific folder
        Returns: Dictionary with 'folders' and 'files' lists
        """
        try:
            params = {}
            if folder_id:
                params['id'] = folder_id
                response = self._get('folder/list', **params)
            else:
                response = self._get('folder/list')

            if response:
                content = response.get('content', [])
                # Separate folders and files
                folders = [item for item in content if item.get('type') == 'folder']
                files = [item for item in content if item.get('type') == 'file']
                return {
                    'folders': folders,
                    'files': files
                }
            return {'folders': [], 'files': []}
        except Exception as e:
            c.log(f'[PM API] Error getting cloud storage: {e}', 1)
            return {'folders': [], 'files': []}

    def unrestrict_link(self, link):
        """
        Unrestrict a hoster link (Direct Download)

        Endpoint: POST /transfer/directdl
        Args:
            link: URL to unrestrict
        Returns: Direct download link
        """
        try:
            response = self._post('transfer/directdl', {'src': link})
            if response and 'content' in response:
                items = response['content']
                if items and len(items) > 0:
                    return items[0].get('link', '')
            return None
        except Exception as e:
            c.log(f'[PM API] Error unrestricting link: {e}', 1)
            return None

    def delete_item(self, item_id):
        """
        Delete an item from cloud storage

        Endpoint: POST /item/delete
        Args:
            item_id: ID of the item to delete
        Returns: Boolean success status
        """
        try:
            response = self._post('item/delete', {'id': item_id})
            return response is not None
        except Exception as e:
            c.log(f'[PM API] Error deleting item: {e}', 1)
            return False

    def account_info(self):
        """
        Get account information

        Endpoint: GET /account/info
        Returns: Account information dictionary including premium status, points, etc.
        """
        try:
            return self._get('account/info')
        except Exception as e:
            c.log(f'[PM API] Error getting account info: {e}', 1)
            return None

    def transfer_list(self):
        """
        Get list of active transfers

        Endpoint: GET /transfer/list
        Returns: List of active transfers
        """
        try:
            response = self._get('transfer/list')
            if response and 'transfers' in response:
                return response['transfers']
            return []
        except Exception as e:
            c.log(f'[PM API] Error getting transfer list: {e}', 1)
            return []

    def transfer_create(self, src):
        """
        Create a new transfer (magnet/torrent)

        Endpoint: POST /transfer/create
        Args:
            src: Magnet link or torrent URL
        Returns: Transfer information dictionary
        """
        try:
            return self._post('transfer/create', {'src': src})
        except Exception as e:
            c.log(f'[PM API] Error creating transfer: {e}', 1)
            return None

    def transfer_directdl(self, src):
        """
        Get direct download link for a URL/magnet (instant download if cached)

        Endpoint: POST /transfer/directdl
        Args:
            src: Magnet link or URL
        Returns: Direct download links or transfer info if not cached
        """
        try:
            data = {'src': src}
            return self._post('transfer/directdl', data=data)
        except Exception as e:
            c.log(f'[PM API] Error getting direct download: {e}', 1)
            return None


# Backward compatibility alias
premiumize = PremiumizeAPI
