# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file alldebrid_api.py
 * @package script.module.thecrew.apis
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 * AllDebrid API Documentation: https://docs.alldebrid.com/
 * API Version: v4
 *
 ********************************************************cm*
'''

import requests

from ..modules import control
from ..modules.crewruntime import c


class AllDebridAPI:
    """
    AllDebrid API wrapper for The Crew addon

    API Base: https://api.alldebrid.com/v4/
    Credentials: Read from ResolveURL addon
    """

    def __init__(self):
        self.name = 'AllDebrid'
        self.base_url = 'https://api.alldebrid.com/v4/'
        # Read API key from ResolveURL addon (single source of truth)
        self.resolver_addon = control.addon('script.module.resolveurl')
        self.api_key = self.resolver_addon.getSetting('AllDebridResolver_token') if self.resolver_addon else ''
        c.log(f'[AllDebrid API] Token from ResolveURL: {"SET" if self.api_key else "EMPTY"}', 1)
        self.user_agent = 'TheCrew'

    def _get(self, url, **params):
        """
        Make authenticated GET request to AllDebrid API

        Args:
            url: API endpoint path
            **params: Query parameters
        Returns: Response data dictionary or None
        """
        try:
            params['agent'] = self.user_agent
            params['apikey'] = self.api_key
            full_url = self.base_url + url
            c.log(f"[AD API] GET {url} with key: {self.api_key[:10] if self.api_key else 'NONE'}...", 1)
            response = requests.get(full_url, params=params, timeout=30).json()
            c.log(f"[AD API] Response status: {response.get('status', 'NO STATUS')}", 1)

            if response.get('status') == 'success':
                return response.get('data', {})
            else:
                error = response.get('error', {})
                c.log(f"[AD API] Error: {error.get('message', 'Unknown error')}, Full response: {response}", 1)
            return None
        except Exception as e:
            c.log(f'[AD API] GET error: {e}', 1)
            return None

    def _post(self, url, data=None):
        """
        Make authenticated POST request to AllDebrid API

        Args:
            url: API endpoint path
            data: POST data dictionary
        Returns: Response data dictionary or None
        """
        try:
            params = {'agent': self.user_agent, 'apikey': self.api_key}
            response = requests.post(
                self.base_url + url,
                params=params,
                data=data or {},
                timeout=30
            ).json()

            if response.get('status') == 'success':
                return response.get('data', {})
            else:
                error = response.get('error', {})
                c.log(f"[AD API] Error: {error.get('message', 'Unknown error')}", 1)
            return None
        except Exception as e:
            c.log(f'[AD API] POST error: {e}', 1)
            return None

    # ===== CLOUD BROWSING METHODS =====

    def user_cloud(self):
        """
        Get list of magnets in AllDebrid cloud storage

        Endpoint: GET /magnet/status
        Returns: List of ready magnet dictionaries
        """
        try:
            response = self._get('magnet/status')
            if response and 'magnets' in response:
                # Filter to only show ready/downloaded magnets (statusCode 4)
                return [m for m in response['magnets'] if m.get('statusCode') == 4]
            return []
        except Exception as e:
            c.log(f'[AD API] Error getting cloud storage: {e}', 1)
            return []

    def magnet_status(self, magnet_id):
        """
        Get status of a specific magnet

        Endpoint: GET /magnet/status?id={magnet_id}
        Args:
            magnet_id: ID of the magnet
        Returns: Magnet status dictionary
        """
        try:
            return self._get('magnet/status', id=magnet_id)
        except Exception as e:
            c.log(f'[AD API] Error getting magnet status: {e}', 1)
            return None

    def unrestrict_link(self, link):
        """
        Unrestrict a hoster link

        Endpoint: GET /link/unlock?link={link}
        Args:
            link: URL to unrestrict
        Returns: Direct download link
        """
        try:
            response = self._get('link/unlock', link=link)
            if response and 'link' in response:
                return response['link']
            return None
        except Exception as e:
            c.log(f'[AD API] Error unrestricting link: {e}', 1)
            return None

    def delete_magnet(self, magnet_id):
        """
        Delete a magnet from cloud storage

        Endpoint: GET /magnet/delete?id={magnet_id}
        Args:
            magnet_id: ID of the magnet to delete
        Returns: Boolean success status
        """
        try:
            response = self._get('magnet/delete', id=magnet_id)
            return response is not None
        except Exception as e:
            c.log(f'[AD API] Error deleting magnet: {e}', 1)
            return False

    def get_user(self):
        """
        Get user information

        Endpoint: GET /user
        Returns: User information dictionary
        """
        try:
            return self._get('user')
        except Exception as e:
            c.log(f'[AD API] Error getting user info: {e}', 1)
            return None

    def upload_magnet(self, magnet_url):
        """
        Upload a magnet link to AllDebrid cloud

        Endpoint: POST /magnet/upload
        Args:
            magnet_url: Magnet link to upload
        Returns: Magnet information dictionary with id, filename, size, status
        """
        try:
            data = {'magnets[]': magnet_url}
            response = self._post('magnet/upload', data=data)
            return response
        except Exception as e:
            c.log(f'[AD API] Error uploading magnet: {e}', 1)
            return None


# Backward compatibility alias
alldebrid = AllDebridAPI
