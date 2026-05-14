# -*- coding: utf-8 -*-

'''
 ********************************************************cm*
 * The Crew Add-on
 *
 * @package script.module.thecrew
 *
 * @copyright (c) 2023, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

import os
import re
import sys
import hashlib
import json
import base64
import random
import datetime
import traceback
import sqlite3 as database
from urllib.parse import urlparse, parse_qs, quote_plus, unquote_plus, parse_qsl

import xbmc
import xbmcaddon
import xbmcvfs

from ..modules import cache
from ..modules import metacache
from ..modules import client
from ..modules import control
from ..modules import regex
from ..modules import trailer
from ..modules import workers
from ..modules import youtube
from ..modules import views
from ..modules import sources
from ..modules import trakt
from ..modules import bookmarks
from ..modules.listitem import ListItemInfoTag
from ..modules.crewruntime import c


# Consolidated list of URLs (single central dict for maintainability)
ROOT_URLS = {
    'porn': 'special://home/addons/script.module.thecrew/xml/xxx.xml',
    'greyhat': 'https://raw.githubusercontent.com/posadka/xmls2/main/kids/greyhat_main.xml',
    'debridkids': 'https://raw.githubusercontent.com/posadka/xmls2/main/kids/debridkids.xml',
    'waltdisney': 'https://raw.githubusercontent.com/posadka/xmls2/main/kids/disney_years/main.xml',
    'learning': 'https://raw.githubusercontent.com/posadka/xmls2/main/kids/learning.xml',
    'songs': 'https://raw.githubusercontent.com/posadka/xmls2/main/kids/songs.xml',
    'greenhat': 'http://thechains24.com/GREENHAT/green.xml',
    'whitehat': 'special://home/addons/script.module.thecrew/xml/whitehat.xml',  # Fallback: 'https://pastebin.com/raw/tMSGGbxc' (client.request fails on pastebin)
    'ncaa': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/ncaa/ncaa.xml',
    'ncaab': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/ncaa/ncaab.xml',
    'lfl': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/lfl/lfl.xml',
    'mlb': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/mlb/mlb.xml',
    'nfl': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/nfl/nfl.xml',
    'nhl': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/nhl/nhl.xml',
    'nba': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/nba/nba.xml',
    'ufc': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/ufc_mma/ufc.xml',
    'motogp': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/motor/motogp.xml',
    'boxing': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/boxing/boxing.xml',
    'fifa': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/fifa/fifa.xml',
    'wwe': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/wwe/wwe.xml',
    'sports_channels': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/channels/channels.xml',
    'sreplays': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/replays/replays.xml',
    'misc_sports': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/misc/misc_sports.xml',
    'tennis': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/tennis/tennis.xml',
    'f1': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/motor/f1.xml',
    'pga': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/pga/pga.xml',
    'purplehat': 'https://raw.githubusercontent.com/classymouse/cc/main/CCcinema.xml',
    # 'personal' handled via settings
    'nascar': 'https://raw.githubusercontent.com/posadka/xmls2/main/sports/nascar/nascar.xml',
}


class Indexer:
    def __init__(self):
        self.list = []
        self.hash = []
        self.imdb_info_link = 'http://www.omdbapi.com/?i=%s&plot=full&r=json'
        self.tvmaze_info_link = 'http://api.tvmaze.com/lookup/shows?thetvdb=%s'
        self.lang = 'en'
        self.meta = []

    def _get_local_xml_content(self, url):
        """
        Check if a local XML file exists for the given URL.
        If found, return the file content. Otherwise return None.

        Local XML files should be placed in: <addon_path>/xml/
        The filename is extracted from the URL (e.g., xxx.xml from the GitHub URL).
        """
        if not url or not isinstance(url, str):
            return None

        try:
            # Extract filename from URL
            # Examples:
            # https://raw.githubusercontent.com/posadka/pinkhat/main/pinkhat/xxx.xml -> xxx.xml
            # http://cellardoortv.com/kiddo/master/main.xml -> main.xml
            filename = url.split('/')[-1]

            # Only check for .xml files
            if not filename.endswith('.xml'):
                return None

            # Build local path: <addon_path>/xml/<filename>
            # Note: The code runs from plugin.video.thecrew context, but XML files
            # are stored in script.module.thecrew, so we need to explicitly get that path

            module_addon = xbmcaddon.Addon('script.module.thecrew')
            addon_path = xbmcvfs.translatePath(module_addon.getAddonInfo('path'))
            local_path = os.path.join(addon_path, 'xml', filename)
            c.log(f"[Local XML] Checking for local file at: {local_path}")

            #Check if local file exists
            if os.path.exists(local_path):
                c.log(f"[Local XML] Found local override for {filename} at {local_path}")
                with open(local_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                c.log(f"[Local XML] Loaded {len(content)} bytes from local file")
                # Log first 200 chars to verify content
                c.log(f"[Local XML] Content starts with: {content[:200]}")
                return content
            else:
                c.log(f"[Local XML] No local file found for {filename}, will fetch from remote")
                return None

        except Exception as e:
            c.log(f"[Local XML] Error checking for local file: {e}")
            return None

    def _extract_xml_tag(self, content, tag, default='0'):
        """
        Extract value from XML tag with consistent error handling.
        Eliminates repeated try/except re.findall() patterns.

        Args:
            content: The XML content to search
            tag: The tag name to extract (without angle brackets)
            default: Default value if tag not found or extraction fails

        Returns:
            The extracted value or default

        Example:
            self._extract_xml_tag(item, 'title', '0')
            # Replaces:
            # try:
            #     value = re.findall(r'<title>(.+?)</title>', item)[0]
            # except Exception:
            #     value = '0'
        """
        try:
            return re.findall(rf'<{tag}>(.+?)</{tag}>', content)[0]
        except (IndexError, Exception):
            return default

    # simplified root methods that use the central dict
    def root_porn(self):
        """Adult Section - uses new class-based architecture"""
        from .adult import Adult
        return Adult().root()
    def root_base(self):
        return self.create_list(ROOT_URLS.get('base'))
    def root_waste(self):
        return self.create_list(ROOT_URLS.get('waste'))
    def root_titan(self):
        return self.create_list(ROOT_URLS.get('titan'))
    def root_greyhat(self):
        return self.create_list(ROOT_URLS.get('greyhat'))
    def root_debridkids(self):
        return self.create_list(ROOT_URLS.get('debridkids'))
    def root_waltdisney(self):
        return self.create_list(ROOT_URLS.get('waltdisney'))
    def root_learning(self):
        return self.create_list(ROOT_URLS.get('learning'))
    def root_songs(self):
        return self.create_list(ROOT_URLS.get('songs'))
    def root_yellowhat(self):
        return self.create_list(ROOT_URLS.get('yellowhat'))
    def root_redhat(self):
        return self.create_list(ROOT_URLS.get('redhat'))
    def root_blackhat(self):
        return self.create_list(ROOT_URLS.get('blackhat'))
    def root_food(self):
        return self.create_list(ROOT_URLS.get('food'))
    def root_greenhat(self):
        return self.create_list(ROOT_URLS.get('greenhat'))
    def root_whitehat(self):
        pass

    def root_absolution(self):
        return self.create_list(ROOT_URLS.get('absolution'))
    def root_ncaa(self):
        return self.create_list(ROOT_URLS.get('ncaa'))
    def root_ncaab(self):
        return self.create_list(ROOT_URLS.get('ncaab'))
    def root_lfl(self):
        return self.create_list(ROOT_URLS.get('lfl'))
    def root_mlb(self):
        return self.create_list(ROOT_URLS.get('mlb'))
    def root_nfl(self):
        return self.create_list(ROOT_URLS.get('nfl'))
    def root_nhl(self):
        return self.create_list(ROOT_URLS.get('nhl'))
    def root_nba(self):
        return self.create_list(ROOT_URLS.get('nba'))
    def root_ufc(self):
        return self.create_list(ROOT_URLS.get('ufc'))
    def root_motogp(self):
        return self.create_list(ROOT_URLS.get('motogp'))
    def root_boxing(self):
        return self.create_list(ROOT_URLS.get('boxing'))
    def root_fifa(self):
        return self.create_list(ROOT_URLS.get('fifa'))
    def root_wwe(self):
        return self.create_list(ROOT_URLS.get('wwe'))
    def root_sports_channels(self):
        return self.create_list(ROOT_URLS.get('sports_channels'))
    def root_sreplays(self):
        return self.create_list(ROOT_URLS.get('sreplays'))
    def root_misc_sports(self):
        return self.create_list(ROOT_URLS.get('misc_sports'))
    def root_tennis(self):
        return self.create_list(ROOT_URLS.get('tennis'))
    def root_f1(self):
        return self.create_list(ROOT_URLS.get('f1'))
    def root_pga(self):
        return self.create_list(ROOT_URLS.get('pga'))
    def root_kiddo(self):
        return self.create_list(ROOT_URLS.get('kiddo'))
    def root_purplehat(self):
        return self.create_list(ROOT_URLS.get('purplehat'))
    def root_classy(self):
        return self.create_list(ROOT_URLS.get('classy'))
    def root_personal(self):
        return self.create_personal('personal.list')
    def root_git(self):
        return self.create_list(ROOT_URLS.get('git'))
    def root_nascar(self):
        return self.create_list(ROOT_URLS.get('nascar'))
    def root_xfl(self):
        return self.create_list(ROOT_URLS.get('xfl'))
    def root_tubi(self):
        return self.create_list(ROOT_URLS.get('tubi'))
    def root_pluto(self):
        return self.create_list(ROOT_URLS.get('pluto'))
    def root_bumble(self):
        return self.create_list(ROOT_URLS.get('bumble'))
    def root_xumo(self):
        return self.create_list(ROOT_URLS.get('xumo'))
    def root_distro(self):
        return self.create_list(ROOT_URLS.get('distro'))
    def root_cricket(self):
        return self.create_list(ROOT_URLS.get('cricket'))

#OH added 1-5-2021
    def create_list(self, url):
        try:
            regex.clear()
            self.list = self.the_crew_list(url)
            for i in self.list:
                i.update({'content': 'addons'})
            self.addDirectory(self.list)
            return self.list
        except Exception:
            pass

#WhiteHat added 6-20-2022
    def create_personal(self, url):
        try:
            regex.clear()
            url = control.setting('personal.list')
            self.list = self.the_crew_list(url)
            for i in self.list:
                i.update({'content': 'addons'})
            self.addDirectory(self.list)
            return self.list
        except Exception:
            pass

#OH - checked
    def get(self, url):
        try:
            self.list = self.the_crew_list(url)
            self.worker()
            self.addDirectory(self.list)
            return self.list
        except Exception:
            pass

    def getq(self, url):
        """
        Queue Directory - Fetch XML list and add items to playlist queue.

        Legacy function for backward compatibility with external XML feeds.
        Used by custom XML lists to batch-add multiple items to playlist queue.

        Args:
            url (str): URL to XML list in the_crew_list format

        Returns:
            list: List of items added to queue, or None on error

        Note:
            - Registered in router as 'qdirectory' action
            - May be called by external/user XML feeds
            - queue=True parameter enables batch playlist queueing
        """
        try:
            self.list = self.the_crew_list(url)
            self.worker()  # Add metadata with threading
            self.addDirectory(self.list, queue=True)
            return self.list
        except Exception as e:
            c.log(f'[Lists] getq() error for url={url}: {e}')
            return None

    def getx(self, url, worker=False):
        """
        Regex Directory - Resolve dynamic URLs using regex patterns.

        Legacy function for backward compatibility with external XML feeds.
        Used by custom XML lists with obfuscated/protected URLs that require
        regex pattern resolution (e.g., "base_url|regex=pattern_id").

        Args:
            url (str): URL in format "base_url|regex=pattern_id"
            worker (bool): Currently unused, kept for compatibility

        Returns:
            list: List of resolved items, or None on error

        Note:
            - Registered in router as 'xdirectory' action
            - May be called by external/user XML feeds
            - Parses URL, fetches regex pattern, resolves final URL
        """
        try:
            c.log(f"[Lists] getx() parsing url: {url}")
            r, x = re.findall(r'(.+?)\|regex=(.+?)$', url)[0]
            x = regex.fetch(x)
            r += unquote_plus(x)
            c.log(f"[Lists] getx() regex resolved: r={repr(r)}, x={repr(x)}")
            url = regex.resolve(r)
            c.log(f"[Lists] getx() final url: {repr(url)}")

            self.list = self.the_crew_list('', result=url)
            self.addDirectory(self.list)
            return self.list
        except Exception as e:
            c.log(f'[Lists] getx() error: {e}')
            c.log(f'[Lists] getx() traceback: {traceback.format_exc()}')
            return None

    def get_x_url(self, url):
        try:
            # Get the current listitem title in case we need to extract URL from it
            listitem_title = control.infoLabel('listitem.label')

            r, x = re.findall(r'(.+?)\|regex=(.+?)$', url)[0]
            x = regex.fetch(x)
            r = unquote_plus(x)

            # Extract the regex name from the fetched XML and prepend $doregex[name]
            # This is needed so pyFunctions will be executed by getRegexParsed()
            try:
                regex_name = re.findall(r'<name>([^<]+)</name>', r)[0]
                url_with_doregex = f'$doregex[{regex_name}]' + r
            except Exception as e:
                url_with_doregex = r

            url = regex.resolve(url_with_doregex)

            # Safe logging - handle binary data or large strings
            if isinstance(url, bytes):
                url = None  # Set to None to trigger fallback
            elif isinstance(url, str):
                pass
            else:
                url = None  # Set to None to trigger fallback

            # Handle broken list entries where pyFunction returns 'async', None, or the real URL is in the title
            if not url or (isinstance(url, str) and url.strip().lower() in ['async', '']):
                if listitem_title and isinstance(listitem_title, str) and (listitem_title.startswith('http://') or listitem_title.startswith('https://')):
                    # Strip anchor fragments and use the URL from the title
                    url = listitem_title.split('#')[0].split('?')[0] if '#' in listitem_title or '?' in listitem_title else listitem_title

            self.list = self.the_crew_list('', result=url)
            return url

        except Exception as e:
            c.log(f'[Lists] get_x_url() error: {e}')
            pass

#OH - checked
    def developer(self):
        try:
            url = os.path.join(control.dataPath, 'testings.xml')
            f = control.openFile(url)
            result = f.read()
            f.close()

            self.list = self.the_crew_list('', result=result)
            for i in self.list:
                i.update({'content': 'videos'})
            self.addDirectory(self.list)
            return self.list
        except Exception:
            pass



    def youtube(self, url, action):
        try:
            key = trailer.Trailers().key_link.split('=', 1)[-1]
            if 'PlaylistTuner' in action:
                self.list = cache.get(youtube.youtube(key=key).playlist, 1, url)
            elif 'Playlist' in action:
                self.list = cache.get(youtube.youtube(key=key).playlist, 1, url, True)
            elif 'ChannelTuner' in action:
                self.list = cache.get(youtube.youtube(key=key).videos, 1, url)
            elif 'Channel' in action:
                self.list = cache.get(youtube.youtube(key=key).videos, 1, url, True)
            if 'Tuner' in action:
                for i in self.list:
                    i.update({
                        'name': i['title'], 'poster': i['image'],
                        'action': 'plugin', 'folder': False
                        })
                if 'Tuner2' in action:
                    self.list = sorted(self.list, key=lambda x: random.random())
                self.addDirectory(self.list, queue=True)
            else:
                for i in self.list:
                    i.update({
                        'name': i['title'], 'poster': i['image'], 'nextaction': action,
                        'action': 'play', 'folder': False
                        })
                self.addDirectory(self.list)
            return self.list
        except Exception:
            pass


    def the_crew_list(self, url, result=None):
        """
        Parse a remote/local "the_crew" list format into a normalized list of dicts.
        - result: optional pre-fetched payload (string). If None, will fetch via cache.get(client.request, 0, url).
        Returns: list of items (each a dict)
        """
        try:
            # fetch if needed
            if result is None:
                # First check for local XML file override
                result = self._get_local_xml_content(url)

                if result is not None:
                    c.log(f"[Local XML] Using local file content ({len(result)} bytes)")
                else:
                    c.log(f"[Local XML] No local file, will fetch from remote cache")

                # If no local file, fetch from remote
                if result is None:
                    result = cache.get(client.request, 0, url)

            if result is None:
                result = ''

            if result.strip().startswith('#EXTM3U') and '#EXTINF' in result:
                try:
                    result = re.compile(r'#EXTINF:.+?,(.+?)\n(.+?)\n', re.MULTILINE|re.DOTALL).findall(result)
                    result = [
                        f'<item><title>{i[0]}</title><link>{i[1]}</link></item>' for i in result
                        ]
                    result = ''.join(result)
                except ValueError:
                    pass

            # try base64 decode; if decode fails treat as original result
            r = ''
            try:
                # If result is a string, sanitize it to base64 alphabet to avoid UnicodeEncodeError
                if isinstance(result, str):
                    clean = re.sub(r'[^A-Za-z0-9+/=]', '', result)
                    if not clean:
                        raise ValueError('no base64 characters found')
                    decoded = base64.b64decode(clean)
                else:
                    decoded = base64.b64decode(result)

                if isinstance(decoded, (bytes, bytearray)):
                    r = c.to_str(decoded, errors='replace')
                else:
                    r = str(decoded)
            except Exception as e:
                failure = traceback.format_exc()
                c.log(f'[Lists] the_crew_list base64 decode error: {e}')

                # Diagnostic logging: fetch extended response (headers + bytes) when base64 fails
                try:
                    if url and str(url).startswith(('http://', 'https://')):
                        try:
                            ext = cache.get(client.request, 0, url, 'extended', None, None, None, None, None, None, None, None, True)
                        except Exception:
                            # older client.request signature compatibility
                            ext = cache.get(client.request, 0, url, output='extended', as_bytes=True)

                        if ext:
                            try:
                                data, headers, content_headers, cookie_str = ext
                            except Exception:
                                # fallback shape
                                try:
                                    data, headers, content_headers = ext
                                    cookie_str = ''
                                except Exception:
                                    data = ext
                                    headers = {}
                                    content_headers = {}
                                    cookie_str = ''

                            try:
                                ct = content_headers.get('Content-Type') if hasattr(content_headers, 'get') else None
                                ce = content_headers.get('Content-Encoding') if hasattr(content_headers, 'get') else None
                                cl = content_headers.get('Content-Length') if hasattr(content_headers, 'get') else None
                            except Exception:
                                ct = ce = cl = None

                            try:
                                if isinstance(data, (bytes, bytearray)):
                                    pass
                                else:
                                    pass
                            except Exception as diag_e:
                                pass
                except Exception as diag_ex:
                    pass

                # Attempt alternate recovery strategies when input isn't base64
                try:
                    # Try stripping non-base64 bytes from a UTF-8-encoded representation
                    alt = (result.encode('utf-8', errors='ignore') if isinstance(result, str) else result)
                    alt = re.sub(rb'[^A-Za-z0-9+/=]', b'', alt)
                    decoded = base64.b64decode(alt)
                    r = c.to_str(decoded, errors='replace')
                except Exception:
                    try:
                        # Treat the original response as raw bytes (latin-1 preserves octets)
                        b = (result.encode('latin-1', errors='ignore') if isinstance(result, str) else bytes(result))

                        # Detect common compressed formats
                        if b.startswith(b'\x1f\x8b'):
                            import gzip
                            r = c.to_str(gzip.decompress(b), errors='replace')
                        elif b.startswith(b'PK'):
                            # ZIP archive - try to read first file (best-effort)
                            try:
                                import zipfile, io
                                z = zipfile.ZipFile(io.BytesIO(b))
                                names = z.namelist()
                                if names:
                                    r = c.to_str(z.read(names[0]), errors='replace')
                                else:
                                    r = ''
                            except Exception:
                                r = ''
                        else:
                            # Try to decode as UTF-8 or latin-1 and hope for XML/text
                            try:
                                r = b.decode('utf-8', errors='replace')
                            except Exception:
                                r = b.decode('latin-1', errors='replace')

                        # If result still looks empty, fall back to original string
                        if not r:
                            r = result
                    except Exception:
                        r = result

            if '</link>' in r:
                result = r

            info = re.split(r'<item>|<dir>', result)[0]

            vip = self._extract_xml_tag(info, 'poster')
            image = self._extract_xml_tag(info, 'thumbnail')
            fanart = self._extract_xml_tag(info, 'fanart')

            pattern = re.compile(
                r'((?:<item>.+?</item>|<dir>.+?</dir>|<plugin>.+?</plugin>|<info>.+?</info>|'
                r'<name>[^<]+</name><link>[^<]+</link><thumbnail>[^<]+</thumbnail><mode>[^<]+</mode>|'
                r'<name>[^<]+</name><link>[^<]+</link><thumbnail>[^<]+</thumbnail><date>[^<]+</date>))',
                re.MULTILINE|re.DOTALL
                )
            items = pattern.findall(result)

            # compiled patterns used for safer substitutions
            regex_pattern = re.compile(r'<regex>.+?</regex>', re.DOTALL)
            sublink_pattern = re.compile(r'<sublink\s+name=(?:\'|\").*?(?:\'|\")></sublink>|<sublink></sublink>', re.DOTALL)
            link_empty_pattern = re.compile(r'<link></link>', re.DOTALL)

            for item in items:
                regdata_list = re.compile(r'(<regex>.+?</regex>)', re.MULTILINE|re.DOTALL).findall(item)
                regdata = ''.join(regdata_list)
                reglist = re.compile(r'(<listrepeat>.+?</listrepeat>)', re.MULTILINE|re.DOTALL).findall(regdata)
                # quote the regdata for storage
                regdata_q = quote_plus(regdata)

                # compute hash once from the full regdata bytes
                reghash = hashlib.md5()
                try:
                    reghash.update(regdata_q.encode('utf-8'))
                    reghash = str(reghash.hexdigest())
                except Exception:
                    reghash = hashlib.md5(regdata_q.encode('utf-8') if regdata_q else b'').hexdigest()

                # sanitize item
                item = item.replace('\r','').replace('\n','').replace('\t','').replace('&nbsp;','')

                # remove regex blocks and bad sublink placeholders
                item = regex_pattern.sub('', item)
                item = sublink_pattern.sub('', item)
                item = link_empty_pattern.sub('', item)

                name_block = re.sub(r'<meta>.+?</meta>', '', item, flags=re.DOTALL)
                name = self._extract_xml_tag(name_block, 'title')
                if name == '0':
                    name = self._extract_xml_tag(name_block, 'name')

                date = self._extract_xml_tag(item, 'date', '')

                if re.search(r'\d+', date):
                    name += f' [COLOR red] Updated {date}[/COLOR]'

                image2 = self._extract_xml_tag(item, 'thumbnail', image)
                fanart2 = self._extract_xml_tag(item, 'fanart', fanart)
                meta = self._extract_xml_tag(item, 'meta')
                url = self._extract_xml_tag(item, 'link')

                url = url.replace('>search<', f'><preset>search</preset>{meta}<')
                url = f'<preset>search</preset>{meta}' if url == 'search' else url
                url = url.replace('>searchsd<', f'><preset>searchsd</preset>{meta}<')
                url = f'<preset>searchsd</preset>{meta}'  if url == 'searchsd' else url
                url = sublink_pattern.sub('', url)

                if item.startswith('<item>'):
                    action = 'play'
                elif item.startswith('<plugin>'):
                    action = 'plugin'
                elif item.startswith('<info>') or url == '0':
                    action = '0'
                else:
                    action = 'directory'

                if action == 'play' and reglist:
                    action = 'xdirectory'

                if regdata != '':
                    self.hash.append({'regex': reghash, 'response': regdata_q})
                    url += f'|regex={reghash}'

                folder = action in ['directory', 'xdirectory', 'plugin']

                # Extract content tag from XML
                content = self._extract_xml_tag(meta, 'content')
                if content == '0':
                    content = self._extract_xml_tag(item, 'content')

                # Extract metadata for content inference
                imdb = self._extract_xml_tag(meta, 'imdb')
                tvdb = self._extract_xml_tag(meta, 'tvdb')
                tvshowtitle = self._extract_xml_tag(meta, 'tvshowtitle')
                title = self._extract_xml_tag(meta, 'title')
                season = self._extract_xml_tag(meta, 'season')
                episode = self._extract_xml_tag(meta, 'episode')

                # Intelligent content detection for XMLs without content tag (e.g., Greenhat/Purplehat)
                # Infer from metadata if content tag is missing
                if content == '0':
                    # Check for TV show indicators
                    if tvdb != '0' or tvshowtitle != '0' or (season != '0' and episode != '0'):
                        content = 'tvshow'
                        c.log(f"[Lists] Inferred content='tvshow' from metadata (tvdb={tvdb}, tvshowtitle={tvshowtitle}, S{season}E{episode})")
                    # Check for movie indicators
                    elif imdb != '0':
                        content = 'movie'
                        c.log(f"[Lists] Inferred content='movie' from metadata (imdb={imdb})")

                # Add plural 's' to content type
                if content != '0':
                    content += 's'

                # Special handling for tvshow content
                if 'tvshow' in content and not url.strip().endswith('.xml'):
                    url = f'<preset>tvindexer</preset><url>{url}</url><thumbnail>{image2}</thumbnail><fanart>{fanart2}</fanart>{meta}'
                    action = 'tvtuner'

                if 'tvtuner' in content and not url.strip().endswith('.xml'):
                    url = f'<preset>tvtuner</preset><url>{url}</url><thumbnail>{image2}</thumbnail><fanart>{fanart2}</fanart>{meta}'
                    action = 'tvtuner'

                if title == '0' and tvshowtitle != '0':
                    title = tvshowtitle

                year = self._extract_xml_tag(meta, 'year')
                premiered = self._extract_xml_tag(meta, 'premiered')

                self.list.append({
                    'name': name, 'vip': vip, 'url': url, 'action': action, 'folder': folder,
                    'poster': image2, 'banner': '0', 'fanart': fanart2,
                    'content': content, 'imdb': imdb, 'tvdb': tvdb, 'tmdb': '0', 'title': title,
                    'originaltitle': title, 'tvshowtitle': tvshowtitle, 'year': year,
                    'premiered': premiered, 'season': season, 'episode': episode
                    })

            regex.insert(self.hash)
            return self.list

        except Exception as e:
            c.log(f'[Lists] the_crew_list() error: {e}')
            pass


    def worker(self):
        """
        Fetch and cache metadata for items in self.list using threading.
        Processes movies and TV shows, with special handling for single unique IMDB.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed  # Import here for clarity

        try:
            total = len(self.list)
            if total == 0:
                return

            # Initial metacache fetch (mark all as not cached)
            for item in self.list:
                item['metacache'] = False
            self.list = metacache.fetch(self.list, self.lang)

            # Deduplicate IMDB IDs and handle single unique IMDB case
            imdb_ids = [item.get('imdb', '0') for item in self.list if item.get('imdb', '0') != '0']
            unique_imdb = list(dict.fromkeys(imdb_ids))  # Preserve order, dedupe
            if len(unique_imdb) == 1:
                # Process all items with this IMDB (not just the first)
                single_imdb = unique_imdb[0]
                for idx, item in enumerate(self.list):
                    if item.get('imdb') == single_imdb:
                        if item.get('content') == 'movies':
                            self.movie_info(idx)
                        elif item.get('content') in ['tvshows', 'seasons', 'episodes']:
                            self.tv_info(idx)
                if self.meta:
                    metacache.insert(self.meta)
                    self.meta = []  # Reset after insert

            # Refetch from metacache after single-IMDB processing
            for item in self.list:
                item['metacache'] = False
            self.list = metacache.fetch(self.list, self.lang)

            # Batch processing with ThreadPoolExecutor (limit to 20 workers per batch)
            batch_size = 50
            max_workers_per_batch = 20
            for r in range(0, total, batch_size):
                batch_end = min(r + batch_size, total)
                batch_items = [(i, self.list[i]) for i in range(r, batch_end)]

                with ThreadPoolExecutor(max_workers=max_workers_per_batch) as executor:
                    # Submit tasks for movie_info and tv_info based on content
                    futures = []
                    for idx, item in batch_items:
                        content = item.get('content', '')
                        if content == 'movies':
                            futures.append(executor.submit(self.movie_info, idx))
                        elif content in ['tvshows', 'seasons', 'episodes']:
                            futures.append(executor.submit(self.tv_info, idx))

                    # Wait for all futures to complete and handle exceptions
                    for future in as_completed(futures):
                        try:
                            future.result()  # Raises exception if task failed
                        except Exception as e:
                            pass

                # Insert meta after each batch
                if self.meta:
                    try:
                        metacache.insert(self.meta)
                        self.meta = []
                    except Exception as e:
                        pass

            # Final meta insert if any remaining
            if self.meta:
                try:
                    metacache.insert(self.meta)
                except Exception as e:
                    pass

        except Exception as e:
            pass



    def worker_orig(self):
        try:
            total = len(self.list)

            if total == 0:
                return

            for i in range(total):
                self.list[i].update({'metacache': False})
            self.list = metacache.fetch(self.list, self.lang)

            multi = [i['imdb'] for i in self.list]
            multi = [x for y,x in enumerate(multi) if x not in multi[:y]]
            if len(multi) == 1:
                self.movie_info(0)
                self.tv_info(0)
                if self.meta:
                    metacache.insert(self.meta)

            for i in range(total):
                self.list[i].update({'metacache': False})
            self.list = metacache.fetch(self.list, self.lang)

            for r in range(0, total, 50):
                threads = []
                for i in list(range(r, r+50)):
                    if i <= total:
                        threads.append(workers.Thread(self.movie_info, i))
                    if i <= total:
                        threads.append(workers.Thread(self.tv_info, i))
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

                if self.meta:
                    metacache.insert(self.meta)

            if self.meta:
                metacache.insert(self.meta)
        except Exception:
            pass

    def movie_info(self, i):
        try:
            if self.list[i]['metacache'] is True or not self.list[i]['content'] == 'movies':
                #raise Exception()
                return

            #if not self.list[i]['content'] == 'movies':
            #    raise Exception()

            imdb = self.list[i]['imdb']
            if imdb == '0':
                raise Exception()

            url = self.imdb_info_link % imdb

            item = client.request(url, timeout='10')
            item = json.loads(item)

            if 'Error' in item and 'incorrect imdb' in item['Error'].lower():
                return self.meta.append({
                    'imdb': imdb, 'tmdb': '0', 'tvdb': '0', 'lang': self.lang,
                    'item': {'code': '0'}
                    })

            title = item['Title']
            if not title == '0':
                self.list[i].update({'title': title})

            year = item['Year']
            if year != '0':
                self.list[i].update({'year': year})

            imdb = item['imdbID']
            if imdb in ['', None, 'N/A']:
                imdb = '0'
            if imdb != '0':
                self.list[i].update({'imdb': imdb, 'code': imdb})

            premiered = item['Released']
            if premiered in ['', None, 'N/A']:
                premiered = '0'
            premiered = re.findall(r'(\d*) (.+?) (\d*)', premiered)
            try:
                premiered = '%s-%s-%s' % (
                    premiered[0][2],
                    {
                        'Jan':'01', 'Feb':'02', 'Mar':'03', 'Apr':'04', 'May':'05', 'Jun':'06',
                        'Jul':'07', 'Aug':'08', 'Sep':'09', 'Oct':'10', 'Nov':'11', 'Dec':'12'
                    }[premiered[0][1]],
                    premiered[0][0]
                    )
            except Exception:
                premiered = '0'
            if premiered != '0':
                self.list[i].update({'premiered': premiered})

            genre = item['Genre']
            if genre is None or genre == '' or genre == 'N/A':
                genre = '0'
            genre = genre.replace(', ', ' / ')
            if genre != '0':
                self.list[i].update({'genre': genre})

            duration = item['Runtime']
            if duration is None or duration == '' or duration == 'N/A':
                duration = '0'
            duration = re.sub('[^0-9]', '', str(duration))
            try:
                duration = str(int(duration) * 60)
            except Exception:
                pass
            if duration != '0':
                self.list[i].update({'duration': duration})

            rating = item['imdbRating']
            if rating is None or rating == '' or rating == 'N/A' or rating == '0.0':
                rating = '0'
            if rating != '0':
                self.list[i].update({'rating': rating})

            votes = item['imdbVotes']
            try:
                votes = str(format(int(votes),',d'))
            except Exception:
                pass
            if votes is None or votes == '' or votes == 'N/A':
                votes = '0'
            if votes != '0':
                self.list[i].update({'votes': votes})

            mpaa = item['Rated']
            if mpaa is None or mpaa == '' or mpaa == 'N/A':
                mpaa = '0'
            if mpaa != '0':
                self.list[i].update({'mpaa': mpaa})

            director = item['Director']
            if director is None or director == '' or director == 'N/A':
                director = '0'
            director = director.replace(', ', ' / ')
            director = re.sub(r'\(.*?\)', '', director)
            director = ' '.join(director.split())
            if director != '0':
                self.list[i].update({'director': director})

            writer = item['Writer']
            if writer is None or writer == '' or writer == 'N/A':
                writer = '0'
            writer = writer.replace(', ', ' / ')
            writer = re.sub(r'\(.*?\)', '', writer)
            writer = ' '.join(writer.split())
            if writer != '0':
                self.list[i].update({'writer': writer})

            cast = item['Actors']
            if cast is None or cast == '' or cast == 'N/A':
                cast = '0'
            cast = [x.strip() for x in cast.split(',') if not x == '']
            try:
                cast = [(c.to_str(x), '') for x in cast]
            except Exception:
                cast = []
            if cast == []:
                cast = '0'
            if not cast == '0':
                self.list[i].update({'cast': cast})

            plot = item['Plot']
            if plot is None or plot == '' or plot == 'N/A':
                plot = '0'
            plot = client.replaceHTMLCodes(plot)
            c.to_str(plot)
            if not plot == '0':
                self.list[i].update({'plot': plot})

            self.meta.append({
                'imdb': imdb, 'tmdb': '0', 'tvdb': '0', 'lang': self.lang,
                'item': {
                    'title': title, 'year': year, 'code': imdb, 'imdb': imdb,
                    'premiered': premiered, 'genre': genre, 'duration': duration,
                    'rating': rating, 'votes': votes, 'mpaa': mpaa,
                    'director': director, 'writer': writer, 'cast': cast, 'plot': plot
                    }
                })
        except Exception:
            pass

    def tv_info(self, i):
        try:
            if self.list[i]['metacache'] is True:
                raise Exception()

            if self.list[i]['content'] not in ['tvshows', 'seasons', 'episodes']:
                raise Exception()

            tvdb = self.list[i]['tvdb']
            if tvdb == '0':
                raise Exception()

            url = self.tvmaze_info_link % tvdb
            item = client.request(url, output='extended', error=True, timeout='10')

            if item[1] == '404':
                return self.meta.append({
                    'imdb': '0', 'tmdb': '0', 'tvdb': tvdb, 'lang': self.lang, 'item': {'code': '0'}
                    })

            item = json.loads(item[0])

            tvshowtitle = item['name']
            c.to_str(tvshowtitle)
            if not tvshowtitle == '0':
                self.list[i].update({'tvshowtitle': tvshowtitle})

            year = item['premiered']
            year = re.findall(r'(\d{4})', year)[0]
            c.to_str(year)
            if not year == '0':
                self.list[i].update({'year': year})

            try:
                imdb = item['externals']['imdb']
            except Exception:
                imdb = '0'
            if imdb == '' or imdb is None:
                imdb = '0'
            c.to_str(imdb)
            if self.list[i]['imdb'] == '0' and not imdb == '0':
                self.list[i].update({'imdb': imdb})

            try:
                studio = item['network']['name']
            except Exception:
                studio = '0'
            if studio == '' or studio is None:
                studio = '0'
            c.to_str(studio)
            if not studio == '0':
                self.list[i].update({'studio': studio})

            genre = item['genres']
            if genre == '' or genre is None or genre == []:
                genre = '0'
            genre = ' / '.join(genre)
            c.to_str(genre)
            if genre != '0':
                self.list[i].update({'genre': genre})

            try:
                duration = str(item['runtime'])
            except Exception:
                duration = '0'

            if duration in ['', None]:
                duration = '0'
            try:
                duration = str(int(duration) * 60)
            except Exception:
                pass
            c.to_str(duration)
            if not duration == '0':
                self.list[i].update({'duration': duration})

            rating = str(item['rating']['average'])
            if rating == '' or rating is None:
                rating = '0'
            c.to_str(rating)
            if not rating == '0':
                self.list[i].update({'rating': rating})

            plot = item['summary']
            if plot == '' or plot is None:
                plot = '0'
            plot = re.sub(r'\n|<.+?>|</.+?>|.+?#\d*:', '', plot)
            c.to_str(plot)
            if not plot == '0':
                self.list[i].update({'plot': plot})

            self.meta.append({
                'imdb': imdb, 'tmdb': '0', 'tvdb': tvdb, 'lang': self.lang,
                'item': {
                    'tvshowtitle': tvshowtitle, 'year': year, 'code': imdb, 'imdb': imdb,
                    'tvdb': tvdb, 'studio': studio, 'genre': genre,
                    'duration': duration, 'rating': rating, 'plot': plot
                    }
                })
        except Exception:
            pass

    def addDirectory(self, items, queue=False):
        if items is None or len(items) == 0:
            return

        sysaddon = sys.argv[0]
        addon_poster = addon_banner = control.addonInfo('icon')
        addon_fanart = control.addonFanart()

        playlist = control.playlist
        if queue is not False:
            playlist.clear()

        try:
            devmode = 'testings.xml' in control.listDir(control.dataPath)[1]
        except FileNotFoundError:
            devmode = False

        content_type = next((item['content'] for item in items if 'content' in item), None)
        key = content_type if content_type is not None else 'addons'
        mode = {
            'movies': 'movies',
            'tvshows': 'tvshows',
            'seasons': 'seasons',
            'episodes': 'episodes',
            'videos': 'videos'
        }.get(key, 'addons')

        # Enrich metadata for movies/episodes with IDs (TMDB enrichment + Trakt watched/resume status)
        enriched_items = self._enrich_xml_metadata(items, mode)

        for i in items:
            try:
                name = c.lang(int(i['name']))
            except (ValueError, TypeError):
                name = i['name']

            # Clean up URL titles - convert URLs to readable titles
            if name and isinstance(name, str) and (name.startswith('http://') or name.startswith('https://')):
                try:
                    # Extract path from URL and clean it up
                    # E.g., "https://www.naughtyblog.org/black-is-better-gina-valentina/#more-498720"
                    # becomes "Black Is Better Gina Valentina"
                    path = urlparse(name).path
                    # Remove leading/trailing slashes and split on slashes
                    parts = path.strip('/').split('/')
                    # Take the last part (usually the slug)
                    slug = parts[-1] if parts else ''
                    # Remove anchors and query params
                    slug = slug.split('#')[0].split('?')[0]
                    # Replace hyphens with spaces and title case
                    cleaned = slug.replace('-', ' ').replace('_', ' ').title()
                    if cleaned:
                        name = cleaned
                except Exception as e:
                    # Keep original name if cleaning fails
                    pass

            url = f"{sysaddon}?action={i['action']}"

            try:
                url += f"&url={quote_plus(i['url'])}"
            except ValueError:
                pass

            try:
                url += f"&content={quote_plus(i['content'])}"
            except ValueError:
                pass

            if i['action'] == 'plugin' and 'url' in i:
                url = i['url']

            try:
                devurl = dict(parse_qsl(urlparse(url).query)).get('action')
            except ValueError:
                devurl = None

            if devurl == 'developer' and not devmode:
                continue
            poster = i['poster'] if 'poster' in i else '0'
            banner = i['banner'] if 'banner' in i else '0'
            fanart = i['fanart'] if 'fanart' in i else '0'
            if poster == '0':
                poster = addon_poster
            if banner == '0':
                banner = addon_banner if poster == '0' else poster
            content = i['content'] if 'content' in i else '0'
            folder = i['folder'] if 'folder' in i else True

            # Filter metadata to only include valid video info labels
            # Exclude keys like 'action', 'url', 'folder', 'metacache', 'name', 'poster', 'banner', 'fanart', 'content', 'next', 'nextaction'
            excluded_keys = {'action', 'url', 'folder', 'metacache', 'name', 'poster', 'banner', 'fanart', 'content', 'next', 'nextaction', 'context'}
            meta = {k: v for k, v in i.items() if k not in excluded_keys and v != '0'}

            cm = []

            if content in ['movies', 'tvshows']:
                meta['trailer'] = f'{sysaddon}?action=trailer&name={quote_plus(name)}'
                cm.append((c.lang(30707), f'RunPlugin({sysaddon}?action=trailer&name={quote_plus(name)})'))

            if content in ['movies', 'tvshows', 'seasons', 'episodes']:
                cm.append((c.lang(30708), 'XBMC.Action(Info)*'))

            if (folder is False and '|regex=' not in str(i.get('url'))) or (folder is True and content in ['tvshows', 'seasons']):
                cm.append((c.lang(30723), f'RunPlugin({sysaddon}?action=queueItem)'))

            if content == 'movies':
                dfile = f"{i['title']} ({i['year']})" or name
                cm.append((c.lang(30722),  f"RunPlugin({sysaddon}?action=addDownload&name={quote_plus(dfile)}&url={quote_plus(i['url'])}&image={quote_plus(poster)})"))

            elif content == 'episodes':
                dfile = f"{i['tvshowtitle']} S{int(i['season']):02d}E{int(i['episode']):02d}" or name
                cm.append((c.lang(30722),  f"RunPlugin({sysaddon}?action=addDownload&name={quote_plus(dfile)}&url={quote_plus(i['url'])}&image={quote_plus(poster)})"))

            elif content == 'songs':
                cm.append((c.lang(30722), f"RunPlugin({sysaddon}?action=addDownload&name={quote_plus(name)}&url={quote_plus(i['url'])}&image={quote_plus(poster)})"))

            if mode == 'movies':
                cm.append((c.lang(30711), f"RunPlugin({sysaddon}?action=addView&content=movies)"))
            elif mode == 'tvshows':
                cm.append((c.lang(30712), f"RunPlugin({sysaddon}?action=addView&content=tvshows)"))
            elif mode == 'seasons':
                cm.append((c.lang(30713), f"RunPlugin({sysaddon}?action=addView&content=seasons)"))
            elif mode == 'episodes':
                cm.append((c.lang(30714), f"RunPlugin({sysaddon}?action=addView&content=episodes)"))

            if devmode:
                cm.append(('Open in browser',f"RunPlugin({sysaddon}?action=browser&url={quote_plus(i['url'])}"))

            # Use enriched metadata if available (creates proper list items with watched/resume status)
            item_key = self._get_item_key(i)
            use_enriched = item_key in enriched_items

            if use_enriched:
                # Create enhanced list item with full metadata
                # Note: Keep original folder status - folders enable multi-link popup dialogs
                item = self._create_enriched_listitem(i, enriched_items[item_key], name, poster, banner, fanart, cm, addon_fanart)
            else:
                # Fallback to basic list item (original behavior)
                item = control.item(label=name)

                try:
                    item.setArt({
                        'icon': poster, 'thumb': poster, 'poster': poster, 'tvshow.poster': poster,
                        'season.poster': poster, 'banner': banner, 'tvshow.banner': banner,
                        'season.banner': banner
                        })
                except Exception:
                    pass

                if fanart != '0':
                    item.setProperty('Fanart_Image', fanart)
                elif addon_fanart is not None:
                    item.setProperty('Fanart_Image', addon_fanart)

                item.setInfo(type='Video', infoLabels = meta)
                # Note: System context menus cannot be removed (Kodi API limitation since v17/2016)
                item.addContextMenuItems(cm)

            # Preserve original folder status (important for multi-link popup dialogs)
            if not queue:
                control.addItem(handle=int(sys.argv[1]), url=url, listitem=item, isFolder=folder)
            else:
                if not use_enriched:
                    item.setInfo(type='Video', infoLabels = meta)
                playlist.add(url=url, listitem=item)


        if queue is not False:
            return control.player.play(playlist)

        try:
            # Only add "next page" item if items exist and the first item has valid 'next' and 'nextaction'
            if items and len(items) > 0:
                i = items[0]
                if 'next' in i and i['next'] and 'nextaction' in i:
                    url = f"{sysaddon}?action={i['nextaction']}&url={quote_plus(i['next'])}"

                    item = control.item(label=c.lang(30500))
                    item.setArt({
                        'addonPoster': addon_poster, 'thumb': addon_poster, 'poster': addon_poster,
                        'tvshow.poster': addon_poster, 'season.poster': addon_poster, 'banner': addon_poster,
                        'tvshow.banner': addon_poster, 'season.banner': addon_poster
                        })
                    item.setProperty('addonFanart_Image', addon_fanart)

                    control.addItem(handle=int(sys.argv[1]), url=url, listitem=item, isFolder=True)
        except Exception as e:
            c.log(f'[Lists] Failed to add next page item: {e}')

        if mode is not None:
            control.content(int(sys.argv[1]), mode)
        control.directory(int(sys.argv[1]), cacheToDisc=True)
        if mode in ['movies', 'tvshows', 'seasons', 'episodes']:
            views.set_view(mode, {'skin.estuary': 55})

    def _get_item_key(self, item):
        """Generate unique key for an item based on available IDs."""
        imdb = item.get('imdb', '0')
        tmdb = item.get('tmdb', '0')
        tvdb = item.get('tvdb', '0')

        if imdb != '0':
            return f"imdb_{imdb}"
        elif tmdb != '0':
            return f"tmdb_{tmdb}"
        elif tvdb != '0':
            return f"tvdb_{tvdb}"
        return None

    def _enrich_xml_metadata(self, items, mode):
        """Enrich XML list items with TMDB metadata and Trakt watched/resume status."""
        enriched = {}

        # Infer content type from item metadata if mode is 'addons' but items have IDs
        # Note: Items may be marked as folders (for multi-link popup) but still be movies/episodes
        if mode == 'addons':
            # Check if items have IMDB/TVDB IDs (regardless of folder status)
            has_movie_ids = any(item.get('imdb', '0') != '0' for item in items)
            has_tvshow_ids = any(
                (item.get('imdb', '0') != '0' or item.get('tvdb', '0') != '0') and
                item.get('tvshowtitle', '0') != '0'
                for item in items
            )

            if has_tvshow_ids:
                mode = 'episodes'
                c.log(f"[Lists] Inferred mode='episodes' from item metadata (has tvshowtitle + IDs)")
            elif has_movie_ids:
                mode = 'movies'
                c.log(f"[Lists] Inferred mode='movies' from item metadata (has IMDB IDs)")

        if mode not in ['movies', 'episodes']:
            c.log(f"[Lists] Skipping enrichment - mode '{mode}' not in ['movies', 'episodes']")
            return enriched

        try:
            # Filter items that have IDs and aren't folders
            # Note: Items marked as folders (for multi-link popups) can't show overlays/indicators
            # so we skip enrichment to save processing time
            items_with_ids = []
            for item in items:
                # Only enrich non-folder items
                if item.get('folder', True) == False:
                    if item.get('imdb', '0') != '0' or item.get('tvdb', '0') != '0' or item.get('tmdb', '0') != '0':
                        items_with_ids.append(item)

            if not items_with_ids:
                c.log("[Lists] No items with IDs found (or all items are folders), skipping metadata enrichment")
                c.log("[Lists] Note: Folder items (multi-link popups) can't display watched/resume overlays")
                return enriched

            c.log(f"[Lists] Enriching {len(items_with_ids)} items with TMDB metadata")

            # Convert TVDB to TMDB if needed
            for item in items_with_ids:
                if item.get('tmdb', '0') == '0' and item.get('tvdb', '0') != '0':
                    try:
                        tvdb_id = item['tvdb']
                        c.log(f"[Lists] Converting TVDB {tvdb_id} to TMDB")
                        lookup = trakt.IdLookup('show', 'tvdb', tvdb_id)
                        if lookup and 'tmdb' in lookup:
                            item['tmdb'] = str(lookup['tmdb'])
                            c.log(f"[Lists] Converted TVDB {tvdb_id} -> TMDB {item['tmdb']}")
                    except Exception as e:
                        c.log(f"[Lists] Failed to convert TVDB to TMDB: {e}")

                if item.get('tmdb', '0') == '0' and item.get('imdb', '0') != '0':
                    try:
                        imdb_id = item['imdb']
                        content_type = 'movie' if mode == 'movies' else 'show'
                        c.log(f"[Lists] Converting IMDB {imdb_id} to TMDB")
                        lookup = trakt.IdLookup(content_type, 'imdb', imdb_id)
                        if lookup and 'tmdb' in lookup:
                            item['tmdb'] = str(lookup['tmdb'])
                            c.log(f"[Lists] Converted IMDB {imdb_id} -> TMDB {item['tmdb']}")
                    except Exception as e:
                        c.log(f"[Lists] Failed to convert IMDB to TMDB: {e}")

            # Fetch enriched metadata from TMDB via metacache
            lang = control.apiLanguage()['tmdb'] or 'en'
            user = c.get_setting('trakt.user').strip() if trakt.get_trakt_credentials_info() else ''
            enriched_list = metacache.fetch(items_with_ids, lang, user)

            # Get watched status and resume points from Trakt if enabled
            if trakt.getTraktIndicatorsInfo():
                c.log("[Lists] Getting watched status from Trakt")
                try:
                    progress_data = trakt.get_trakt_progress(mode.rstrip('s')) # type: ignore  # 'movies' -> 'movie', 'episodes' -> 'episode'

                    for item in enriched_list:
                        imdb = item.get('imdb', '0')
                        tmdb = item.get('tmdb', '0')

                        if mode == 'episodes':
                            season = int(item.get('season', 0))
                            episode = int(item.get('episode', 0))

                            # Get resume point
                            resume_info = bookmarks.get_progress_bookmark(
                                imdb=imdb, tmdb=tmdb, mediatype='episode',
                                season=season, episode=episode
                            )
                            if resume_info:
                                item['resume_point'] = resume_info.get('resume_point', 0)
                                item['watched'] = resume_info.get('watched', False)
                        else:
                            # Get movie resume point
                            resume_info = bookmarks.get_progress_bookmark(
                                imdb=imdb, tmdb=tmdb, mediatype='movie'
                            )
                            if resume_info:
                                item['resume_point'] = resume_info.get('resume_point', 0)
                                item['watched'] = resume_info.get('watched', False)

                except Exception as e:
                    c.log(f"[Lists] Error getting Trakt progress: {e}")

            # Build enriched dict with item keys
            for item in enriched_list:
                key = self._get_item_key(item)
                if key:
                    enriched[key] = item

            c.log(f"[Lists] Successfully enriched {len(enriched)} items")

        except Exception as e:
            c.log(f"[Lists] Error enriching metadata: {e}")
            c.log(f"[Lists] Traceback: {traceback.format_exc()}")

        return enriched

    def _create_enriched_listitem(self, original_item, enriched_meta, name, poster, banner, fanart, cm, addon_fanart):
        """Create a ListItemInfoTag-based list item with full metadata."""
        try:
            # Calculate and add visual indicators to label for folder items
            resume_point = enriched_meta.get('resume_point', 0)
            duration = enriched_meta.get('duration', 0)
            is_watched = enriched_meta.get('watched', False)

            # Add watched/resume indicators to label (since folder items don't show overlays)
            if original_item.get('folder', True):  # If it's displayed as a folder
                if is_watched:
                    name = f'{name} [COLOR green](OK)[/COLOR]'  # Watched indicator
                elif resume_point and duration and float(resume_point) > 120:
                    percent = int((float(resume_point) / float(duration)) * 100)
                    name = f'{name} [COLOR gold]({percent}%)[/COLOR]'  # Progress indicator

            item = control.item(label=name)

            # Build comprehensive art dict
            art = {
                'icon': enriched_meta.get('poster', poster) or poster,
                'thumb': enriched_meta.get('thumb', poster) or poster,
                'poster': enriched_meta.get('poster', poster) or poster,
                'banner': enriched_meta.get('banner', banner) or banner,
            }

            # Add additional artwork if available
            if enriched_meta.get('clearlogo', '0') != '0':
                art['clearlogo'] = enriched_meta['clearlogo']
            if enriched_meta.get('clearart', '0') != '0':
                art['clearart'] = enriched_meta['clearart']
            if enriched_meta.get('landscape', '0') != '0':
                art['landscape'] = enriched_meta['landscape']

            item.setArt(art)

            # Set fanart
            fanart_val = enriched_meta.get('fanart', fanart)
            if fanart_val and fanart_val != '0':
                item.setProperty('Fanart_Image', fanart_val)
            elif addon_fanart:
                item.setProperty('Fanart_Image', addon_fanart)

            # Set ID properties
            imdb = enriched_meta.get('imdb', '0')
            tmdb = enriched_meta.get('tmdb', '0')
            tvdb = enriched_meta.get('tvdb', '0')

            if imdb != '0':
                item.setProperty('imdb_id', imdb)
            if tmdb != '0':
                item.setProperty('tmdb_id', tmdb)
            if tvdb != '0':
                item.setProperty('tvdb_id', tvdb)

            # Prepare metadata for InfoTag
            meta = dict((k, v) for k, v in enriched_meta.items() if v != '0')

            # Convert comma-separated strings to lists (Kodi v21+ requirement)
            meta['studio'] = c.string_split_to_list(meta.get('studio', '')) if 'studio' in meta else []
            meta['genre'] = c.string_split_to_list(meta.get('genre', '')) if 'genre' in meta else []
            meta['director'] = c.string_split_to_list(meta.get('director', '')) if 'director' in meta else []
            meta['writer'] = c.string_split_to_list(meta.get('writer', '')) if 'writer' in meta else []

            # Create InfoTag and set metadata
            info_tag = ListItemInfoTag(item, 'video')
            infolabels = control.tagdataClean(meta)
            info_tag.set_info(infolabels)

            # Set unique IDs
            unique_ids = {}
            if imdb != '0':
                unique_ids['imdb'] = imdb
            if tmdb != '0':
                unique_ids['tmdb'] = tmdb
            if tvdb != '0':
                unique_ids['tvdb'] = tvdb
            if unique_ids:
                info_tag.set_unique_ids(unique_ids)

            # Set resume point if available
            resume_point = enriched_meta.get('resume_point', 0)
            duration = enriched_meta.get('duration', 0)

            if resume_point and float(resume_point) > 120 and duration:
                try:
                    info_tag.set_resume_point({
                        'ResumeTime': float(resume_point),
                        'TotalTime': float(duration)
                    })
                    c.log(f"[Lists] Set resume point: {resume_point}s / {duration}s for {name}")
                except Exception as e:
                    c.log(f"[Lists] Error setting resume point: {e}")

            # Set watched overlay if marked as watched
            # Note: Folder items (for multi-link popup) show indicators in label text instead
            if enriched_meta.get('watched', False):
                try:
                    infolabels['playcount'] = 1
                    info_tag.set_info({'playcount': 1})
                except Exception:
                    pass

            # Set cast if available
            castwiththumb = enriched_meta.get('castwiththumb')
            if castwiththumb and castwiththumb != '0':
                info_tag.set_cast(castwiththumb)

            # Add context menu
            item.addContextMenuItems(cm, replaceItems=True)

            c.log(f"[Lists] Created enriched list item for: {name}")
            return item

        except Exception as e:
            c.log(f"[Lists] Error creating enriched listitem: {e}")
            c.log(f"[Lists] Traceback: {traceback.format_exc()}")
            # Fallback to basic item
            return self._create_basic_listitem(name, poster, banner, fanart, original_item, cm, addon_fanart)

    def _create_basic_listitem(self, name, poster, banner, fanart, meta_item, cm, addon_fanart):
        """Create basic list item (original behavior)."""
        item = control.item(label=name)

        try:
            item.setArt({
                'icon': poster, 'thumb': poster, 'poster': poster, 'tvshow.poster': poster,
                'season.poster': poster, 'banner': banner, 'tvshow.banner': banner,
                'season.banner': banner
            })
        except Exception:
            pass

        if fanart != '0':
            item.setProperty('Fanart_Image', fanart)
        elif addon_fanart is not None:
            item.setProperty('Fanart_Image', addon_fanart)

        # Filter metadata
        excluded_keys = {'action', 'url', 'folder', 'metacache', 'name', 'poster', 'banner', 'fanart', 'content', 'next', 'nextaction', 'context'}
        meta = {k: v for k, v in meta_item.items() if k not in excluded_keys and v != '0'}

        item.setInfo(type='Video', infoLabels=meta)
        item.addContextMenuItems(cm)

        return item

# Compiled regex patterns for resolver - defined once for performance
_RESOLVER_PATTERNS = {
    'regex_url': re.compile(r'(.+?)\|regex=(.+?)$'),
    'timeout': re.compile(r'\s*timeout=(\d*)'),
    'preset_search': re.compile(
        r'<preset>(?P<preset>.+?)</preset>.*?'
        r'<title>(?P<title>.+?)</title>.*?'
        r'<year>(?P<year>.+?)</year>.*?'
        r'<imdb>(?P<imdb>.+?)</imdb>.*?'
        r'(?:<tmdb>(?P<tmdb>.+?)</tmdb>)?',
        re.DOTALL
    ),
    'tv_metadata': re.compile(
        r'<tvdb>(?P<tvdb>.+?)</tvdb>.*?'
        r'<tvshowtitle>(?P<tvshowtitle>.+?)</tvshowtitle>.*?'
        r'<premiered>(?P<premiered>.+?)</premiered>.*?'
        r'<season>(?P<season>.+?)</season>.*?'
        r'<episode>(?P<episode>.+?)</episode>',
        re.DOTALL
    )
}

class resolver:
    def browser(self, url):
        try:
            if not url or not url.startswith('http'):
                return
            url = self.get(url)
            if not url:
                return
            control.execute(f'RunPlugin(plugin://plugin.program.chrome.launcher/?url={quote_plus(url)}&mode=showSite&stopPlayback=no)')
        except Exception:
            pass


    def link(self, url):
        try:
            url = self.get(url)
            if url is False:
                return
            control.execute('ActivateWindow(busydialognocancel)')
            url = self.process(url)
            control.execute('Dialog.Close(busydialognocancel)')

            if url is None:
                return c.infoDialog(c.lang(32401))
            return url
        except Exception:
            pass


    def get(self, url):
        try:
            if url is None:
                return None
            items = re.compile(r'<sublink(?:\s+name=|)(?:\'|\"|)(.*?)(?:\'|\"|)>(.+?)</sublink>').findall(url)

            if len(items) == 0:
                return url
            if len(items) == 1:
                return items[0][1]

            # Give unnamed sublinks a default label
            items = [(i[0] or f'Link {idx+1}', i[1]) for idx, i in enumerate(items)]

            select = control.selectDialog([i[0] for i in items], control.infoLabel('listitem.label'))

            if select == -1:
                return False
            else:
                return items[select][1]
        except Exception as e:
            # Return original URL on error instead of None
            return url

    def process(self, url, direct=True):
        # Handle None URL
        if url is None:
            return None

        # Handle image URLs
        if any(i in url for i in ['.jpg', '.png', '.gif']):
            ext = url.split('?')[0].split('&')[0].split('|')[0].rsplit('.')[-1].replace('/', '').lower()
            if ext in ['jpg', 'png', 'gif']:
                try:
                    i = os.path.join(control.dataPath, 'img')
                    control.deleteFile(i)
                    f = control.openFile(i, 'w')
                    f.write(client.request(url))
                    f.close()
                    control.execute(f'ShowPicture("{i}")')
                    return False
                except Exception:
                    return

        # Handle regex URLs
        match = _RESOLVER_PATTERNS['regex_url'].search(url)
        if match:
            try:
                r, x = match.groups()
                x = regex.fetch(x)
                r += unquote_plus(x)
                if '</regex>' in r:
                    u = regex.resolve(r)
                    if u is not None:
                        url = u
            except Exception:
                pass

        # Handle RTMP URLs
        if url.startswith('rtmp'):
            if not _RESOLVER_PATTERNS['timeout'].search(url):
                url += ' timeout=10'
            return url

        # Handle direct streaming formats (m3u8, f4m, ts)
        if any(i in url for i in ['.m3u8', '.f4m', '.ts']):
            ext = url.split('?')[0].split('&')[0].split('|')[0].rsplit('.')[-1].replace('/', '').lower()
            if ext in ['m3u8', 'f4m', 'ts']:
                return url

        # Handle preset search (movie/TV scraping)
        match = _RESOLVER_PATTERNS['preset_search'].search(url)
        if match:
            try:
                data = match.groupdict()
                if 'search' in data['preset']:
                    # Extract tmdb from preset search (optional)
                    tmdb = data.get('tmdb', None)

                    # Try to extract TV metadata
                    tv_match = _RESOLVER_PATTERNS['tv_metadata'].search(url)
                    if tv_match:
                        tv_data = tv_match.groupdict()
                        tvdb = tv_data['tvdb']
                        tvshowtitle = tv_data['tvshowtitle']
                        premiered = tv_data['premiered']
                        season = tv_data['season']
                        episode = tv_data['episode']
                    else:
                        tvdb = tvshowtitle = premiered = season = episode = None

                    direct = False
                    quality = 'SD' if data['preset'] == 'searchsd' else 'HD'

                    u = sources.Sources().getSources(
                        data['title'], data['year'], data['imdb'],
                        tvdb, tmdb, season, episode, tvshowtitle, premiered, quality
                    )
                    if u is not None:
                        return u
            except Exception:
                pass

        # Handle filmon.com URLs
        if 'filmon.com/' in url:
            try:
                from ..modules import filmon
                u = filmon.resolve(url)
                if u:
                    return u
            except Exception:
                pass

        # Handle google.com URLs
        if '.google.com' in url:
            try:
                from ..modules import directstream
                u = directstream.google(url)[0]['url']
                if u:
                    return u
            except Exception:
                pass

        # Handle resolveurl (ResolveURL/URLResolver for various hosters)
        try:
            import resolveurl
            hmf = resolveurl.HostedMediaFile(url=url)
            if hmf.valid_url():
                direct = False
                u = hmf.resolve()
                if u:
                    return u
        except Exception:
            pass

        # If nothing else worked and it's a direct URL, return it
        if direct is True:
            return url


# Backwards-compatible factory for older code expecting `indexer()` to exist
def indexer():
    """Return a new Indexer instance for backward compatibility."""
    return Indexer()

class player(xbmc.Player):
    """
    Simple player for direct URL playback (YouTube, IPTV, Adult content).

    This is a lightweight player WITHOUT:
    - Trakt scrobbling (privacy-focused - no tracking to external services)
    - Resume points / bookmarks (single-session playback)
    - Up Next auto-play (no binge mode)
    - Background monitoring (minimal resource usage)

    Use cases:
    - Adult content (privacy - no Trakt history)
    - IPTV live streams (no resume points needed)
    - YouTube videos (one-off playback)
    - Direct URL playback from XMLs

    For movies/episodes with full tracking, use player.py instead.
    """

    def __init__(self):
        """Initialize simple player with minimal state tracking."""
        # Playback timing
        self.totalTime = 0
        self.currentTime = 0

        # Basic metadata (for display and logging only)
        self.name = ''
        self.title = ''
        self.year = ''
        self.season = None
        self.episode = None

        # Database/API IDs (stored but not used for tracking)
        self.DBID = None
        self.imdb = None
        self.tmdb = None

        xbmc.Player.__init__(self)


    def play(self, url, content=None):
        """
        Simple player for direct URL playback (YouTube, Adult, IPTV).

        No Trakt tracking or resume points - designed for privacy and simplicity.
        For movies/episodes with tracking, use the main player in player.py instead.

        Args:
            url: Direct playable URL or URL requiring resolver processing
            content: Content type (unused - kept for backwards compatibility)
        """
        c.log(f"[Lists Player] play() called with url: {url[:100]}...")

        # Handle regex-based URL extraction (legacy XML format)
        if '$doregex[playurl]|' in url:
            c.log('[Lists Player] Processing $doregex pattern')
            url = Indexer().get_x_url(url)
            c.log(f"[Lists Player] Regex resolved to: {url[:100]}...")

        # First resolver pass: Extract base URL from complex patterns
        url = resolver().get(url)
        c.log(f"[Lists Player] After resolver.get(): {url[:100] if url else 'None'}...")

        if url is False or url is None:
            c.log('[Lists Player] resolver.get() failed - no URL to process')
            return

        # Second resolver pass: Process URL through provider-specific resolvers
        # Shows busy dialog during resolution (can be slow for some hosters)
        control.execute('ActivateWindow(busydialog)')
        url = resolver().process(url)
        c.log(f"[Lists Player] After resolver.process(): {url[:100] if url else 'None'}...")
        control.execute('Dialog.Close(busydialog)')

        # Check if resolution succeeded
        if url is None:
            c.log('[Lists Player] Resolution failed - no playable URL found')
            return c.infoDialog('No working url found')
        if url is False:
            c.log('[Lists Player] Resolution cancelled or blocked')
            return

        # Gather metadata from current listitem (if available)
        meta = {}
        for field in ['title', 'originaltitle', 'tvshowtitle', 'year', 'season', 'episode',
                        'genre', 'rating', 'votes', 'director', 'writer', 'plot', 'tagline']:
            try:
                value = control.infoLabel(f'listitem.{field}')
                if value:
                    meta[field] = value
            except Exception:
                pass

        # Ensure we have at least a title
        if 'title' not in meta:
            meta['title'] = control.infoLabel('listitem.label') or 'Video'

        icon = control.infoLabel('listitem.icon')

        # Store basic info for potential use in callbacks
        self.name = meta['title']
        self.year = meta.get('year', '0')

        # Create and configure listitem for playback
        item = control.item(path=url)

        if icon:
            try:
                item.setArt({'icon': icon})
            except Exception:
                pass

        item.setInfo(type='Video', infoLabels=meta)

        # Initiate playback using both methods for compatibility
        # control.player.play() starts playback, control.resolve() satisfies plugin handle
        control.player.play(url, item)
        control.resolve(int(sys.argv[1]), True, item)

        # Reset time tracking
        self.totalTime = 0
        self.currentTime = 0

        # Wait up to 240 seconds for playback to start
        c.log('[Lists Player] Waiting for playback to start...')
        for _ in range(240):
            if self.isPlayingVideo():
                c.log('[Lists Player] Playback started successfully')
                break
            control.sleep(1000)

        # Monitor playback and update time tracking (enables onPlayBack* callbacks)
        while self.isPlayingVideo():
            try:
                self.totalTime = self.getTotalTime()
                self.currentTime = self.getTime()
            except Exception:
                pass
            control.sleep(2000)

        c.log('[Lists Player] Playback ended')
        control.sleep(5000)

    def onPlayBackStarted(self):
        """
        Callback when playback starts.

        Closes all dialogs (progress, busy, etc.) to show the video.
        No tracking or scrobbling - keeps this player simple and private.
        """
        c.log('[Lists Player] onPlayBackStarted - closing dialogs')
        control.execute('Dialog.Close(all,true)')

    def onPlayBackStopped(self):
        """
        Callback when playback stops (user pressed stop).

        No cleanup needed - simple player doesn't track state.
        """
        c.log('[Lists Player] onPlayBackStopped')
        pass

    def onPlayBackEnded(self):
        """
        Callback when playback ends naturally (video finished).

        Delegates to onPlayBackStopped - no difference in handling.
        """
        c.log('[Lists Player] onPlayBackEnded')
        self.onPlayBackStopped()