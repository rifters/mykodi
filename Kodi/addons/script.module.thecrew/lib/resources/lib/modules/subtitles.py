# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file subtitles.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
Subtitle Management
Handles fetching and loading subtitles from OpenSubtitles.com
'''

import base64
import codecs
import gzip
import json
import os
import re
import traceback
from io import BytesIO

import xbmc
import xbmcaddon
import requests

from . import control
from .crewruntime import c


class Subtitles:
    """
    Handles subtitle fetching and loading from OpenSubtitles.com REST API v1.

    Usage:
        subtitle_manager = Subtitles()
        subtitle_manager.fetch_and_load(name, imdb, season, episode)
    """

    # OpenSubtitles.com REST API v1 constants
    API_URL = 'https://api.opensubtitles.com/api/v1'
    USER_AGENT = f'The Crew {c.pluginversion}'

    # Language code mappings (ISO 639-2 to ISO 639-1 for new API)
    LANG_DICT = {
        'Afrikaans': 'af', 'Albanian': 'sq', 'Arabic': 'ar', 'Armenian': 'hy', 'Basque': 'eu',
        'Bengali': 'bn', 'Bosnian': 'bs', 'Breton': 'br', 'Bulgarian': 'bg', 'Burmese': 'my',
        'Catalan': 'ca', 'Chinese': 'zh', 'Croatian': 'hr', 'Czech': 'cs', 'Danish': 'da', 'Dutch': 'nl',
        'English': 'en', 'Esperanto': 'eo', 'Estonian': 'et', 'Finnish': 'fi', 'French': 'fr',
        'Galician': 'gl', 'Georgian': 'ka', 'German': 'de', 'Greek': 'el', 'Hebrew': 'he', 'Hindi': 'hi',
        'Hungarian': 'hu', 'Icelandic': 'is', 'Indonesian': 'id', 'Italian': 'it', 'Japanese': 'ja',
        'Kazakh': 'kk', 'Khmer': 'km', 'Korean': 'ko', 'Latvian': 'lv', 'Lithuanian': 'lt',
        'Luxembourgish': 'lb', 'Macedonian': 'mk', 'Malay': 'ms', 'Malayalam': 'ml', 'Manipuri': 'mni',
        'Mongolian': 'mn', 'Montenegrin': 'me', 'Norwegian': 'no', 'Occitan': 'oc', 'Persian': 'fa',
        'Polish': 'pl', 'Portuguese': 'pt', 'Portuguese(Brazil)': 'pb', 'Romanian': 'ro',
        'Russian': 'ru', 'Serbian': 'sr', 'Sinhalese': 'si', 'Slovak': 'sk', 'Slovenian': 'sl',
        'Spanish': 'es', 'Swahili': 'sw', 'Swedish': 'sv', 'Syriac': 'syr', 'Tagalog': 'tl', 'Tamil': 'ta',
        'Telugu': 'te', 'Thai': 'th', 'Turkish': 'tr', 'Ukrainian': 'uk', 'Urdu': 'ur'
    }

    # Legacy 3-letter codes to 2-letter (for settings compatibility)
    LANG_CODE_MAP = {
        'dut': 'nl', 'eng': 'en', 'fre': 'fr', 'ger': 'de', 'spa': 'es',
        'por': 'pt', 'ita': 'it', 'rus': 'ru', 'ara': 'ar', 'heb': 'he'
    }

    # Quality tags for release name matching
    QUALITY_TAGS = ['bluray', 'hdrip', 'brrip', 'bdrip', 'dvdrip', 'webrip', 'hdtv']

    def __init__(self):
        """Initialize subtitle manager."""
        self.enabled = control.setting('subtitles') == 'true'

        # OpenSubtitles credentials are stored in plugin.video.thecrew addon settings
        # Must read from plugin addon, not script.module addon
        try:
            plugin_addon = xbmcaddon.Addon('plugin.video.thecrew')
            self.os_user = plugin_addon.getSetting('OSuser') or ''
            self.os_pass = plugin_addon.getSetting('OSpass') or ''
            self.os_apikey = plugin_addon.getSetting('OSapikey') or ''
            c.log(f"[Subtitles Init] Reading credentials from plugin.video.thecrew addon")
        except Exception as e:
            c.log(f"[Subtitles Init] ERROR: Cannot access plugin.video.thecrew addon: {e}")
            self.os_user = ''
            self.os_pass = ''
            self.os_apikey = ''

        self.token = None  # Bearer token from authentication

        # Debug credential retrieval
        if self.enabled:
            if self.os_apikey:
                if self.os_user and self.os_pass:
                    c.log(f"[Subtitles Init] OpenSubtitles configured: user='{self.os_user}', API key={'***' if self.os_apikey else 'MISSING'}")
                else:
                    c.log(f"[Subtitles Init] WARNING: API key provided but missing username/password!")
            else:
                c.log("[Subtitles Init] No OpenSubtitles API key configured")
                c.log("[Subtitles Init] To use OpenSubtitles: Get API key from opensubtitles.com and enter in settings")
                c.log("[Subtitles Init] Alternative: Use another subtitle addon like a4kSubtitles")

    def _authenticate(self):
        """
        Authenticate with OpenSubtitles.com REST API.

        Returns:
            bool: True if authentication successful
        """
        if not self.os_user or not self.os_pass:
            c.log("[Subtitles Auth] No credentials - authentication skipped")
            control.infoDialog("OpenSubtitles: Login required! Set username/password in settings.", time=5000)
            return False

        if not self.os_apikey:
            c.log("[Subtitles Auth] No API key configured - authentication skipped")
            c.log("[Subtitles Auth] Get your API key from opensubtitles.com and enter it in settings")
            control.infoDialog("OpenSubtitles: API key required! Get from opensubtitles.com", time=5000)
            return False

        try:
            c.log(f"[Subtitles Auth] Authenticating with user='{self.os_user}'")

            headers = {
                'Content-Type': 'application/json',
                'Api-Key': self.os_apikey,
                'User-Agent': self.USER_AGENT
            }

            data = json.dumps({
                'username': self.os_user,
                'password': self.os_pass
            })

            url = f"{self.API_URL}/login"

            c.log(f"[Subtitles Auth] POST {url}")
            c.log(f"[Subtitles Auth] Headers: {headers}")

            response = None
            try:
                response = requests.post(url, data=data, headers=headers, timeout=30, verify=True)
                c.log(f"[Subtitles Auth] Response received: {response.status_code}")
            except requests.exceptions.Timeout:
                c.log("[Subtitles Auth] Request timed out after 30 seconds!")
                control.infoDialog("OpenSubtitles: Connection timeout", time=4000)
                return False
            except requests.exceptions.ConnectionError as e:
                c.log(f"[Subtitles Auth] Connection error: {e}")
                control.infoDialog("OpenSubtitles: Connection failed", time=4000)
                return False
            except Exception as e:
                c.log(f"[Subtitles Auth] Request exception: {e}")
                return False

            if response.status_code != 200:
                status_code = response.status_code
                c.log(f"[Subtitles Auth] Authentication failed! HTTP Status: {status_code}")

                # Log the API error response
                try:
                    error_body = response.text
                    c.log(f"[Subtitles Auth] API Response Body: {error_body}")

                    # Try to parse JSON error message
                    try:
                        error_json = json.loads(error_body)
                        error_msg = error_json.get('message', 'Unknown error')
                        c.log(f"[Subtitles Auth] API Error Message: {error_msg}")
                    except:
                        pass
                except Exception as e:
                    c.log(f"[Subtitles Auth] Could not read response body: {e}")

                if status_code == 401:
                    control.infoDialog("OpenSubtitles: Invalid username or password!", time=5000)
                elif status_code == 403:
                    control.infoDialog("OpenSubtitles: Access forbidden - check API key or account status", time=5000)
                else:
                    control.infoDialog(f"OpenSubtitles: Login failed (HTTP {status_code})", time=4000)
                return False

            result = json.loads(response.text)
            self.token = result.get('token')

            if not self.token:
                c.log("[Subtitles Auth] No token in response!")
                return False

            user_info = result.get('user', {})
            allowed_downloads = user_info.get('allowed_downloads', 0)

            c.log(f"[Subtitles Auth] (OK) Authenticated! User: {self.os_user}, Downloads remaining: {allowed_downloads}")

            if allowed_downloads == 0:
                c.log("[Subtitles Auth] WARNING: No downloads remaining today!")
                control.infoDialog("OpenSubtitles: No downloads left for today!", time=4000)
                return False

            return True

        except Exception as e:
            c.log(f"[Subtitles Auth] Exception during authentication: {e}")
            c.log(f"[Subtitles Auth] Traceback: {traceback.format_exc()}")
            return False

    def _get_language_codes(self):
        """
        Get preferred subtitle languages from settings.

        Returns:
            list: Language codes (e.g., ['eng', 'fre'])
        """
        langs = []

        # Primary language
        try:
            lang1 = control.setting('subtitles.lang.1')
            if lang1 in self.LANG_DICT:
                lang_codes = self.LANG_DICT[lang1].split(',')
                langs.extend(lang_codes)
        except Exception as e:
            c.log(f"[Subtitles] Error getting primary language: {e}")

        # Secondary language
        try:
            lang2 = control.setting('subtitles.lang.2')
            if lang2 in self.LANG_DICT:
                lang_codes = self.LANG_DICT[lang2].split(',')
                langs.extend(lang_codes)
        except Exception as e:
            c.log(f"[Subtitles] Error getting secondary language: {e}")

        return langs

    def _get_language_name(self, lang_code):
        """
        Convert language code to readable name.

        Args:
            lang_code: Language code (e.g., 'dut', 'eng', 'nl', 'en')

        Returns:
            str: Readable language name
        """
        lang_map = {
            'dut': 'Dutch',
            'nl': 'Dutch',
            'nld': 'Dutch',
            'eng': 'English',
            'en': 'English',
            'rus': 'Russian',
            'ru': 'Russian',
            'fra': 'French',
            'fr': 'French',
            'deu': 'German',
            'de': 'German',
            'ger': 'German',
            'spa': 'Spanish',
            'es': 'Spanish',
            'ita': 'Italian',
            'it': 'Italian',
            'por': 'Portuguese',
            'pt': 'Portuguese'
        }

        # Try direct lookup
        lang_lower = lang_code.lower().strip()
        if lang_lower in lang_map:
            return lang_map[lang_lower]

        # Try partial match
        for code, name in lang_map.items():
            if code in lang_lower or lang_lower in code:
                return name

        # Return original if no match
        return lang_code.upper()

    def _select_audio_track(self):
        """
        Automatically select preferred audio track (English preferred).

        Returns:
            bool: True if audio track was selected
        """
        try:
            player = xbmc.Player()
            available_audio = player.getAvailableAudioStreams()
            c.log(f"[Audio] Available audio tracks: {available_audio}")

            if not available_audio:
                c.log("[Audio] No audio tracks available")
                return False

            # Preferred audio languages in priority order
            preferred_langs = ['eng', 'en', 'english']

            # Try to find English audio track
            for idx, audio_lang in enumerate(available_audio):
                audio_lower = audio_lang.lower()
                for pref_lang in preferred_langs:
                    if pref_lang in audio_lower:
                        c.log(f"[Audio] Found English audio track {idx}: '{audio_lang}'")
                        player.setAudioStream(idx)
                        c.log(f"[Audio] Selected audio track {idx}: '{audio_lang}'")
                        return True

            # If no English found, log available tracks
            c.log(f"[Audio] No English audio track found, using default. Available: {available_audio}")
            return False

        except Exception as e:
            c.log(f"[Audio] Error selecting audio track: {e}")
            return False

    def _is_subtitle_already_active(self, preferred_langs):
        """
        Check if a subtitle in the preferred language is already active.

        Args:
            preferred_langs: List of preferred language codes

        Returns:
            bool: True if subtitle already active in preferred language
        """
        try:
            active_lang = xbmc.Player().getSubtitles()
            if active_lang and preferred_langs and active_lang == preferred_langs[0]:
                c.log(f"[Subtitles] Subtitle already active for language: {active_lang}")
                return True
        except Exception as e:
            c.log(f"[Subtitles] Error checking active subtitle: {e}")

        return False

    def _search_subtitles(self, langs, imdb, season=None, episode=None):
        """
        Search for subtitles using OpenSubtitles.com REST API v1.

        Args:
            langs: List of language codes (ISO 639-1, e.g., ['nl', 'en'])
            imdb: IMDB ID
            season: Season number (for TV shows)
            episode: Episode number (for TV shows)

        Returns:
            list: List of subtitle file IDs with metadata
        """
        if not self.token:
            c.log("[Subtitles Search] No authentication token")
            return []

        # Ensure IMDB ID has 'tt' prefix
        imdb_str = str(imdb) if imdb else ''
        if not imdb_str:
            c.log("[Subtitles Search] No IMDB ID provided")
            return []

        # If already has tt prefix, use as-is; otherwise add it
        if imdb_str.startswith('tt'):
            imdbid = imdb_str
        else:
            # Strip any non-numeric chars and add tt prefix
            numeric_id = re.sub('[^0-9]', '', imdb_str)
            if not numeric_id:
                c.log("[Subtitles Search] No valid IMDB ID")
                return []
            imdbid = f'tt{numeric_id}'

        # Build search parameters
        params = {
            'imdb_id': imdbid,
            'languages': ','.join(langs)
        }

        # TV episode search
        if season is not None and episode is not None:
            season_int = int(season) if season else 0
            episode_int = int(episode) if episode else 0
            params['type'] = 'episode'
            params['season_number'] = str(season_int)
            params['episode_number'] = str(episode_int)
            c.log(f"[Subtitles Search] TV episode: IMDB={imdbid}, S{season_int:02d}E{episode_int:02d}, langs={langs}")
        else:
            params['type'] = 'movie'
            c.log(f"[Subtitles Search] Movie: IMDB={imdbid}, langs={langs}")

        try:
            headers = {
                'Api-Key': self.os_apikey,
                'Authorization': f'Bearer {self.token}',
                'User-Agent': self.USER_AGENT
            }

            url = f"{self.API_URL}/subtitles"

            try:
                response = requests.get(url, params=params, headers=headers, timeout=30)
            except requests.exceptions.Timeout:
                c.log("[Subtitles Search] Request timed out!")
                return []
            except requests.exceptions.ConnectionError as e:
                c.log(f"[Subtitles Search] Connection error: {e}")
                return []
            except Exception as e:
                c.log(f"[Subtitles Search] Request exception: {e}")
                return []

            if not response or response.status_code != 200:
                status_code = response.status_code if response else 'no response'
                c.log(f"[Subtitles Search] Search failed! Status: {status_code}")
                return []

            result = json.loads(response.text)
            data = result.get('data', [])

            c.log(f"[Subtitles Search] Found {len(data)} subtitle results")

            # Extract file info from results
            subtitles = []
            for item in data:
                try:
                    attrs = item.get('attributes', {})
                    files = attrs.get('files', [])

                    if not files:
                        continue

                    # Get first file from subtitle
                    file_info = files[0]

                    subtitle = {
                        'file_id': file_info.get('file_id'),
                        'filename': file_info.get('file_name', ''),
                        'language': attrs.get('language', ''),
                        'rating': attrs.get('ratings', 0),
                        'hearing_impaired': attrs.get('hearing_impaired', False),
                        'moviehash_match': attrs.get('moviehash_match', False)
                    }

                    if subtitle['file_id']:
                        subtitles.append(subtitle)

                except Exception as e:
                    c.log(f"[Subtitles Search] Error parsing subtitle result: {e}")
                    continue

            c.log(f"[Subtitles Search] Parsed {len(subtitles)} valid subtitles")
            return subtitles

        except Exception as e:
            c.log(f"[Subtitles Search] Exception during search: {e}")
            c.log(f"[Subtitles Search] Traceback: {traceback.format_exc()}")
            return []

    def _select_best_subtitle(self, subtitles, preferred_langs):
        """
        Select the best subtitle from results based on language priority.

        Args:
            subtitles: List of subtitle dictionaries from search
            preferred_langs: Ordered list of preferred language codes

        Returns:
            dict: Best subtitle match, or None
        """
        if not subtitles:
            return None

        # Try each preferred language in order
        for lang in preferred_langs:
            for subtitle in subtitles:
                if subtitle['language'].lower() == lang.lower():
                    c.log(f"[Subtitles] Selected subtitle: {subtitle['filename']} ({lang})")
                    return subtitle

        # Fallback to first result
        c.log(f"[Subtitles] No exact language match, using first result")
        return subtitles[0]

    def _download_subtitle(self, file_id, language):
        """
        Download subtitle file from OpenSubtitles.com REST API v1.

        Args:
            file_id: File ID from search results
            language: Language code (ISO 639-1)

        Returns:
            bytes: Subtitle file content, or None if failed
        """
        if not self.token:
            c.log("[Subtitles Download] No authentication token")
            return None

        try:
            c.log(f"[Subtitles Download] Requesting download for file_id={file_id}, lang={language}")

            headers = {
                'Content-Type': 'application/json',
                'Api-Key': self.os_apikey,
                'Authorization': f'Bearer {self.token}',
                'User-Agent': self.USER_AGENT
            }

            data = json.dumps({'file_id': file_id})

            url = f"{self.API_URL}/download"

            try:
                response = requests.post(url, data=data, headers=headers, timeout=30)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                c.log(f"[Subtitles Download] Download request network error: {e}")
                return None

            if not response or response.status_code != 200:
                status_code = response.status_code if response else 'no response'
                c.log(f"[Subtitles Download] Download request failed! Status: {status_code}")

                if status_code == 406:
                    c.log("[Subtitles Download] No downloads remaining today!")
                    control.infoDialog("OpenSubtitles: Download limit reached!", time=4000)

                return None

            result = json.loads(response.text)
            download_link = result.get('link')
            remaining = result.get('remaining', -1)

            c.log(f"[Subtitles Download] Got download link, {remaining} downloads remaining today")

            if not download_link:
                c.log("[Subtitles Download] No download link in response")
                return None

            # Download the actual subtitle file
            c.log(f"[Subtitles Download] Downloading from: {download_link}")

            try:
                subtitle_response = requests.get(download_link, timeout=45)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                c.log(f"[Subtitles Download] Subtitle file download error: {e}")
                return None

            if not subtitle_response or subtitle_response.status_code != 200:
                c.log(f"[Subtitles Download] Failed to download subtitle file!")
                return None

            content = subtitle_response.content

            # Handle gzip compression if present
            try:
                if isinstance(content, bytes) and content.startswith(b'\x1f\x8b'):  # Gzip magic numbers
                    c.log("[Subtitles Download] Decompressing gzipped subtitle")
                    content = gzip.GzipFile(fileobj=BytesIO(content)).read()
            except Exception as e:
                c.log(f"[Subtitles Download] Gzip decompression failed: {e}")

            c.log(f"[Subtitles Download] Successfully downloaded {len(content)} bytes")
            return content

        except Exception as e:
            c.log(f"[Subtitles Download] Exception during download: {e}")
            c.log(f"[Subtitles Download] Traceback: {traceback.format_exc()}")
            return None

    def _save_and_load_subtitle(self, content, lang):
        """
        Save subtitle to temp file and load it in player.

        Args:
            content: Subtitle file content
            lang: Language code
        """
        subtitle_path = control.transPath('special://temp/')
        subtitle_path = os.path.join(subtitle_path, f'TemporarySubs.{lang}.srt')

        c.log(f"[Subtitles] Saving subtitle to: {subtitle_path}")

        # Write subtitle file
        file = control.openFile(subtitle_path, 'w')
        file.write(content)
        file.close()

        # Wait for file to be written
        control.sleep(1000)

        # Load subtitle in player
        xbmc.Player().setSubtitles(subtitle_path)

        # Enable subtitles display
        xbmc.Player().showSubtitles(True)

        c.log(f"[Subtitles] Subtitle loaded and enabled successfully")

        # Show notification to user
        language_name = self._get_language_name(lang)
        control.infoDialog(f"Subtitles: {language_name} (OpenSubtitles - {self.os_user})", time=3000)

    def fetch_and_load(self, name, imdb, season=None, episode=None):
        """
        Main method: Select audio track and fetch/load subtitles for current video.

        - Automatically selects English audio track if available
        - Checks for embedded subtitles in preferred language
        - Falls back to fetching from OpenSubtitles.com REST API

        Args:
            name: Video name/title
            imdb: IMDB ID
            season: Season number (None for movies)
            episode: Episode number (None for movies)

        Returns:
            bool: True if subtitles loaded successfully
        """
        try:
            # NOTE: Audio track selection moved to player.py (select_audio_track method)
            # This allows audio selection to work even when subtitles are disabled

            # Check if subtitles are enabled
            if not self.enabled:
                c.log("[Subtitles] Subtitles disabled in settings")
                return False

            # Validate IMDB ID
            if not imdb or imdb == '0':
                c.log("[Subtitles] No valid IMDB ID provided, skipping subtitle fetch")
                return False

            # Get preferred languages (will be 3-letter codes like 'dut', 'eng')
            langs_old = self._get_language_codes()
            if not langs_old:
                c.log("[Subtitles] No subtitle languages configured")
                return False

            # Convert old 3-letter codes to new 2-letter codes for REST API
            langs = []
            for old_code in langs_old:
                new_code = self.LANG_CODE_MAP.get(old_code, old_code[:2] if len(old_code) >= 2 else old_code)
                langs.append(new_code)

            c.log(f"[Subtitles] Preferred languages: {langs_old} -> {langs}")

            # Check for embedded subtitles - FIRST PREFERENCE ONLY
            # This ensures we fetch from OpenSubtitles if primary language isn't embedded
            try:
                player = xbmc.Player()
                available_subs = player.getAvailableSubtitleStreams()

                # Log all available tracks with indices
                c.log(f"[Subtitles] Available embedded tracks ({len(available_subs)} total):")
                for idx, sub_lang in enumerate(available_subs):
                    c.log(f"[Subtitles]   Track {idx}: '{sub_lang}'")

                if available_subs and langs_old:
                    first_lang = langs_old[0]  # Primary language preference (e.g., 'dut')
                    c.log(f"[Subtitles] Checking embedded tracks for FIRST preference only: '{first_lang}'")

                    for idx, sub_lang in enumerate(available_subs):
                        # Check if subtitle language matches (case-insensitive, partial match)
                        if first_lang.lower() in sub_lang.lower() or sub_lang.lower() in first_lang.lower():
                            c.log(f"[Subtitles] Found embedded subtitle for first preference: '{sub_lang}'")
                            player.setSubtitleStream(idx)
                            player.showSubtitles(True)
                            c.log(f"[Subtitles] Enabled embedded subtitle track {idx}: '{sub_lang}'")

                            # Show notification to user
                            language_name = self._get_language_name(sub_lang)
                            control.infoDialog(f"Subtitles: {language_name} (embedded)", time=2000)
                            return True

                    c.log(f"[Subtitles] No embedded '{first_lang}' found, will fetch from OpenSubtitles for all preferences")
                else:
                    c.log("[Subtitles] No embedded subtitles in video file")
            except Exception as e:
                c.log(f"[Subtitles] Error checking embedded subtitles: {e}")

            # Authenticate with OpenSubtitles.com REST API
            c.log("[Subtitles] Authenticating with OpenSubtitles.com")

            if not self._authenticate():
                c.log("[Subtitles] Authentication failed, cannot fetch subtitles")
                return False

            # Search for subtitles using REST API
            subtitles = self._search_subtitles(langs, imdb, season, episode)

            if not subtitles:
                c.log("[Subtitles] No subtitles found")
                control.infoDialog("No subtitles found", time=3000)
                return False

            # Select best matching subtitle
            best_subtitle = self._select_best_subtitle(subtitles, langs)

            if not best_subtitle:
                c.log("[Subtitles] No suitable subtitle selected")
                return False

            # Download subtitle
            content = self._download_subtitle(best_subtitle['file_id'], best_subtitle['language'])

            if not content:
                c.log("[Subtitles] Failed to download subtitle")
                control.infoDialog("Subtitle download failed", time=3000)
                return False

            # Save and load subtitle
            self._save_and_load_subtitle(content, best_subtitle['language'])

            return True

        except Exception as e:
            c.log(f"[Subtitles] Error fetching subtitles: {e}")
            c.log (f"[Subtitles] Traceback: {traceback.format_exc()}")
            return False


# [OK] COMPLETED 2026-03-10: Subtitle manager pattern migration
# All code now uses modern Subtitles class (uppercase)
# Legacy lowercase 'subtitles' wrapper removed - no usages found in codebase
# Current usage: subtitles.Subtitles().fetch_and_load(...) in player.py line 1364
