# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file realdebrid_api.py
 * @package script.module.thecrew.apis
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 * Real-Debrid API Documentation: https://api.real-debrid.com/
 * REST API Version: 1.0
 *
 ********************************************************cm*
'''

import requests
import random

from ..modules import utils
from ..modules import cache
from ..modules import control
from ..modules.crewruntime import c


class RealDebridAPI:
    """
    Real-Debrid API wrapper for The Crew addon

    API Base: https://api.real-debrid.com/rest/1.0/
    OAuth: https://api.real-debrid.com/oauth/v2/
    """

    def __init__(self):
        self.name = 'RealDebrid'
        self.url = 'https://realdebrid.com'
        self.api = 'https://api.realdebrid.com'
        self.rest_base_url = 'https://api.real-debrid.com/rest/1.0/'
        self.oauth_url = 'https://api.real-debrid.com/oauth/v2/'
        # Read credentials from ResolveURL addon (single source of truth)
        self.resolver_addon = control.addon('script.module.resolveurl')
        self.token = self.resolver_addon.getSetting('RealDebridResolver_token')
        self.client_secret = self.resolver_addon.getSetting('RealDebridResolver_client_secret')
        self.client_id = self.resolver_addon.getSetting('RealDebridResolver_client_id') or 'X245A4XAIBGVM'
        self.refresh = self.resolver_addon.getSetting('RealDebridResolver_refresh')
        self.enabled = self.resolver_addon.getSetting('RealDebridResolver_enabled')
        c.log(f'[RealDebrid API] Token from ResolveURL: {"SET" if self.token else "EMPTY"}, Enabled: {self.enabled}', 1)
        self.user_agent = cache.get(self._randomagent, 12)

    def _get(self, url):
        """Make authenticated GET request to Real-Debrid API"""
        url = self.rest_base_url + url
        if '?' not in url:
            url += "?auth_token=%s" % self.token
        else:
            url += "&auth_token=%s" % self.token

        response = requests.get(url, timeout=15).text
        try:
            resp = utils.json_loads_as_str(response)
        except Exception as e:
            c.log(f"[RD API] JSON decode error: {e}", 1)
            resp = utils.byteify(response)
        return resp

    def _post(self, url, data={}):
        """Make authenticated POST request to Real-Debrid API"""
        if self.token == '':
            return None

        url = self.rest_base_url + url + '?agent=%s&apikey=%s' % (self.user_agent, self.token)
        resp = requests.post(url, data=data, timeout=15).json()

        if resp.get('status') == 'success':
            if 'data' in resp:
                resp = resp['data']['magnets']
        return resp

    def _put(self, url, data={}):
        """Make authenticated PUT request to Real-Debrid API"""
        if self.token == '':
            return None

        url = self.rest_base_url + url + '?agent=%s&apikey=%s' % (self.user_agent, self.token)
        resp = requests.put(url, data=data, timeout=15).json()

        if resp.get('status') == 'success':
            if 'data' in resp:
                resp = resp['data']['magnets']
        return resp

    def _delete(self, url, data={}):
        """Make authenticated DELETE request to Real-Debrid API"""
        if self.token == '':
            return None

        url = self.rest_base_url + url + '?agent=%s&apikey=%s' % (self.user_agent, self.token)
        resp = requests.delete(url, data=data, timeout=15).json()

        if resp.get('status') == 'success':
            if 'data' in resp:
                resp = resp['data']['magnets']
        return resp

    def refreshToken(self):
        """
        Refresh the OAuth2 access token using refresh token

        Endpoint: POST /oauth/v2/token
        """
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh
        }
        response = requests.post(self.oauth_url + 'token', data=data, timeout=30).json()

        self.token = response['access_token']
        self.refresh = response['refresh_token']
        self.resolver_addon.setSetting('RealDebridResolver_token', self.token)
        self.resolver_addon.setSetting('RealDebridResolver_refresh', self.refresh)

        return True

    def revoke(self):
        """Revoke authorization and clear all stored credentials"""
        self.resolver_addon.setSetting('RealDebridResolver_client_id', '')
        self.resolver_addon.setSetting('RealDebridResolver_client_secret', '')
        self.resolver_addon.setSetting('RealDebridResolver_refresh', '')
        self.resolver_addon.setSetting('RealDebridResolver_token', '')
        self.resolver_addon.setSetting('RealDebridResolver_enabled', 'false')
        return True

    def auth(self):
        """Load current authentication credentials from settings"""
        self.client_id = self.resolver_addon.getSetting('RealDebridResolver_client_id')
        self.client_secret = self.resolver_addon.getSetting('RealDebridResolver_client_secret')
        self.refresh = self.resolver_addon.getSetting('RealDebridResolver_refresh')
        self.token = self.resolver_addon.getSetting('RealDebridResolver_token')
        self.enabled = self.resolver_addon.getSetting('RealDebridResolver_enabled')
        return True

    def check(self):
        """Check and reload authentication credentials"""
        self.client_id = self.resolver_addon.getSetting('RealDebridResolver_client_id')
        self.client_secret = self.resolver_addon.getSetting('RealDebridResolver_client_secret')
        self.refresh = self.resolver_addon.getSetting('RealDebridResolver_refresh')
        self.token = self.resolver_addon.getSetting('RealDebridResolver_token')
        self.enabled = self.resolver_addon.getSetting('RealDebridResolver_enabled')
        return True

    def enabled(self):
        """Check if Real-Debrid is enabled"""
        self.client_id = self.resolver_addon.getSetting('RealDebridResolver_client_id')
        self.client_secret = self.resolver_addon.getSetting('RealDebridResolver_client_secret')
        self.refresh = self.resolver_addon.getSetting('RealDebridResolver_refresh')
        self.token = self.resolver_addon.getSetting('RealDebridResolver_token')
        self.enabled = self.resolver_addon.getSetting('RealDebridResolver_enabled')
        return True

    def disable(self):
        """Disable Real-Debrid (keep credentials)"""
        self.client_id = self.resolver_addon.getSetting('RealDebridResolver_client_id')
        self.client_secret = self.resolver_addon.getSetting('RealDebridResolver_client_secret')
        self.refresh = self.resolver_addon.getSetting('RealDebridResolver_refresh')
        self.token = self.resolver_addon.getSetting('RealDebridResolver_token')
        self.enabled = self.resolver_addon.getSetting('RealDebridResolver_enabled')
        return True

    @staticmethod
    def _randomagent():
        """Generate a random user agent string for API requests"""
        BR_VERS = [
            ['%s.0' % i for i in range(18, 50)],
            [
                '37.0.2062.103', '37.0.2062.120', '37.0.2062.124', '38.0.2125.101', '38.0.2125.104', '38.0.2125.111',
                '39.0.2171.71', '39.0.2171.95', '39.0.2171.99', '40.0.2214.93', '40.0.2214.111', '40.0.2214.115',
                '42.0.2311.90', '42.0.2311.135', '42.0.2311.152', '43.0.2357.81', '43.0.2357.124', '44.0.2403.155',
                '44.0.2403.157', '45.0.2454.101', '45.0.2454.85', '46.0.2490.71', '46.0.2490.80', '46.0.2490.86',
                '47.0.2526.73', '47.0.2526.80', '48.0.2564.116', '49.0.2623.112', '50.0.2661.86', '51.0.2704.103',
                '52.0.2743.116', '53.0.2785.143', '54.0.2840.71', '61.0.3163.100'
            ],
            ['11.0'],
            ['8.0', '9.0', '10.0', '10.6']
        ]
        WIN_VERS = [
            'Windows NT 10.0', 'Windows NT 7.0', 'Windows NT 6.3', 'Windows NT 6.2',
            'Windows NT 6.1', 'Windows NT 6.0', 'Windows NT 5.1', 'Windows NT 5.0'
        ]
        FEATURES = ['; WOW64', '; Win64; IA64', '; Win64; x64', '']
        RAND_UAS = [
            'Mozilla/5.0 ({win_ver}{feature}; rv:{br_ver}) Gecko/20100101 Firefox/{br_ver}',
            'Mozilla/5.0 ({win_ver}{feature}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{br_ver} Safari/537.36',
            'Mozilla/5.0 ({win_ver}{feature}; Trident/7.0; rv:{br_ver}) like Gecko',
            'Mozilla/5.0 (compatible; MSIE {br_ver}; {win_ver}{feature}; Trident/6.0)'
        ]
        index = random.randrange(len(RAND_UAS))
        return RAND_UAS[index].format(
            win_ver=random.choice(WIN_VERS),
            feature=random.choice(FEATURES),
            br_ver=random.choice(BR_VERS[index])
        )

    # ===== CLOUD BROWSING METHODS =====

    def user_cloud(self):
        """
        Get list of torrents in Real-Debrid cloud storage

        Endpoint: GET /torrents
        Returns: List of torrent dictionaries
        """
        try:
            response = self._get('torrents')
            if isinstance(response, list):
                # Filter to only show downloaded/ready torrents
                return [t for t in response if t.get('status') == 'downloaded']
            return []
        except Exception as e:
            c.log(f'[RD API] Error getting cloud storage: {e}', 1)
            return []

    def torrent_info(self, torrent_id):
        """
        Get detailed information about a specific torrent

        Endpoint: GET /torrents/info/{torrent_id}
        Args:
            torrent_id: ID of the torrent
        Returns: Torrent information dictionary
        """
        try:
            return self._get(f'torrents/info/{torrent_id}')
        except Exception as e:
            c.log(f'[RD API] Error getting torrent info: {e}', 1)
            return None

    def unrestrict_link(self, link):
        """
        Unrestrict a hoster link

        Endpoint: POST /unrestrict/link
        Args:
            link: URL to unrestrict
        Returns: Direct download link
        """
        try:
            data = {'link': link}
            url = 'unrestrict/link'
            if '?' not in url:
                url += f'?auth_token={self.token}'
            else:
                url += f'&auth_token={self.token}'

            response = requests.post(self.rest_base_url + url, data=data, timeout=30).json()
            return response.get('download', '')
        except Exception as e:
            c.log(f'[RD API] Error unrestricting link: {e}', 1)
            return None

    def delete_torrent(self, torrent_id):
        """
        Delete a torrent from cloud storage

        Endpoint: DELETE /torrents/delete/{torrent_id}
        Args:
            torrent_id: ID of the torrent to delete
        Returns: Boolean success status
        """
        try:
            url = f'torrents/delete/{torrent_id}'
            if '?' not in url:
                url += f'?auth_token={self.token}'
            else:
                url += f'&auth_token={self.token}'

            response = requests.delete(self.rest_base_url + url, timeout=30)
            return response.status_code == 204
        except Exception as e:
            c.log(f'[RD API] Error deleting torrent: {e}', 1)
            return False

    def get_user(self):
        """
        Get user account information

        Endpoint: GET /user
        Returns: User account details dictionary with username, email, expiration, type, points, limits
        """
        try:
            return self._get('user')
        except Exception as e:
            c.log(f'[RD API] Error getting user info: {e}', 1)
            return None

    def add_magnet(self, magnet_url):
        """
        Add a magnet link to Real-Debrid cloud

        Endpoint: POST /torrents/addMagnet
        Args:
            magnet_url: Magnet link to add
        Returns: Torrent information dictionary with id, uri, filename, status
        """
        try:
            url = f'torrents/addMagnet?auth_token={self.token}'
            data = {'magnet': magnet_url}
            response = requests.post(self.rest_base_url + url, data=data, timeout=30).json()
            return response
        except Exception as e:
            c.log(f'[RD API] Error adding magnet: {e}', 1)
            return None

    def select_files(self, torrent_id, file_ids='all'):
        """
        Select files from a torrent

        Endpoint: POST /torrents/selectFiles/{torrent_id}
        Args:
            torrent_id: ID of the torrent
            file_ids: Comma-separated file IDs or 'all' (default)
        Returns: None
        """
        try:
            url = f'torrents/selectFiles/{torrent_id}?auth_token={self.token}'
            data = {'files': file_ids}
            requests.post(self.rest_base_url + url, data=data, timeout=30)
            return True
        except Exception as e:
            c.log(f'[RD API] Error selecting files: {e}', 1)
            return False


# Backward compatibility alias
realdebrid = RealDebridAPI
