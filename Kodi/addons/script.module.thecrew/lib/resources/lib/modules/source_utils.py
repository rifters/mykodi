# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file source_utils.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import base64
import hashlib
import re

from urllib.parse import unquote, urlparse, quote_plus
import xbmc

from . import cleantitle
from . import client
from . import directstream
from . import trakt
from . import pyaes
from . import log_utils
from .crewruntime import c

RES_4K = [' 4k', ' hd4k', ' 4khd', ' uhd', ' ultrahd', ' ultra hd', ' 2160', ' 2160p', ' hd2160', ' 2160hd']
RES_1080 = [' 1080', ' 1080p', ' 1080i', ' hd1080', ' 1080hd', ' m1080p', ' fullhd', ' full hd', ' 1o8o', ' 1o8op']
RES_720 = [' 720', ' 720p', ' 720i', ' hd720', ' 720hd', ' 72o', ' 72op']
RES_SD = [' 576', ' 576p', ' 576i', ' sd576', ' 576sd', ' 480', ' 480p', ' 480i', ' sd480', ' 480sd', ' 360', ' 360p', ' 360i', ' sd360', ' 360sd', ' 240', ' 240p', ' 240i', ' sd240', ' 240sd']
SCR = [' scr', ' screener', ' dvdscr', ' dvd scr', ' r5', ' r6']
CAM = [' camrip', ' tsrip', ' hdcam', ' hd cam', ' cam rip', ' hdts', ' dvdcam', ' dvdts', ' cam', ' telesync', ' ts']

# Season pack constants
SEASON_LIST = ('one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eigh', 'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen',
            'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty', 'twenty-one', 'twenty-two', 'twenty-three',
            'twenty-four', 'twenty-five')
SEASON_ORDINAL_LIST = ('first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth', 'eleventh', 'twelfth',
            'thirteenth', 'fourteenth', 'fifteenth', 'sixteenth', 'seventeenth', 'eighteenth', 'nineteenth', 'twentieth', 'twenty-first',
            'twenty-second', 'twenty-third', 'twenty-fourth', 'twenty-fifth')
SEASON_ORDINAL2_LIST = ('1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th', '10th', '11th', '12th', '13th', '14th', '15th', '16th',
            '17th', '18th', '19th', '20th', '21st', '22nd', '23rd', '24th', '25th')

def check_title(title, release_title, aliases, year=None, release_year=None):
    """Check if title matches release title.

    Args:
        title: Expected title
        release_title: Title from release
        aliases: List of alternate titles
        year: Expected year (optional)
        release_year: Year from release (optional)

    Returns:
        bool: True if title matches
    """
    try:
        from resources.lib.modules import cleantitle

        # Check year match (allow ±1 year tolerance) - only if both provided
        if year is not None and release_year is not None:
            try:
                if abs(int(year) - int(release_year)) > 1:
                    return False
            except:
                pass

        # Clean titles for comparison
        clean_title = cleantitle.get(title)
        clean_release = cleantitle.get(release_title)

        # Direct match
        if clean_title == clean_release:
            return True

        # Check if title is in release
        if clean_title in clean_release:
            return True

        # Check aliases
        if aliases:
            for alias in aliases:
                clean_alias = cleantitle.get(alias)
                if clean_alias == clean_release or clean_alias in clean_release:
                    return True

        return False
    except Exception:
        return True  # On error, allow through

#function only used in 1 scraper that needs fixing
def supported_video_extensions():
    supported_video_extensions = xbmc.getSupportedMedia('video').split('|')
    return [i for i in supported_video_extensions if i != '' and i != '.zip']

def seas_ep_filter(season, episode, release_title, split=False, return_match=False):
    """
    Validate and filter episode numbers in release names and pack files.

    Searches filename for patterns like S02E18, 2x18, Season 2 Episode 18, etc.
    Also supports episode pack ranges (e.g., S02E01-09, .2.1-9.) where the
    requested episode falls within the range.

    Used for:
    - Validating single episode sources match requested episode (sources.py filtering)
    - Selecting correct episode file from season/show packs (debrid.py pack selection)

    Args:
        season: Season number (int or str)
        episode: Episode number (int or str)
        release_title: Filename or release name to search
        split: If True, return text after match
        return_match: If True, return the matched pattern

    Returns:
        bool: True if season/episode pattern found in filename (including pack ranges)
        str: Split text or matched pattern if split/return_match=True

    Examples:
        S02E08 matches: "The.Pitt.S02E08.1080p" (exact match)
        S02E08 matches: "The.Pitt.2.1-9.2026.1080p" (pack range: episodes 1-9 includes 8)
        S02E08 matches: "The.Pitt.S02E01-09.1080p" (S##E##-## format)
    """
    try:
        # Convert to int first (defensive - handles both int and str input)
        season_int = int(season)
        episode_int = int(episode)

        str_season, str_episode = str(season_int), str(episode_int)
        season_fill, episode_fill = str_season.zfill(2), str_episode.zfill(2)
        str_ep_plus_1, str_ep_minus_1 = str(episode_int+1), str(episode_int-1)

        # Store original for debugging
        original_release = release_title
        release_title = re.sub(r'[^A-Za-z0-9-]+', '.', unquote(release_title).replace('\'', '')).lower()

        # Pattern templates with placeholders
        string1 = r'(s<<S>>[.-]?e[p]?[.-]?<<E>>[.-])'
        string2 = r'(season[.-]?<<S>>[.-]?episode[.-]?<<E>>[.-])'
        string3 = r'(s<<S>>e<<E1>>[.-]?e?<<E2>>[.-])'
        string4 = r'([.-]<<S>>[.-]?<<E>>[.-])'
        string5 = r'(episode[.-]?<<E>>[.-])'
        string6 = r'([.-]e[p]?[.-]?<<E>>[.-])'
        string7 = r'(^(?=.*\.e?0*<<E>>\.)(?:(?!((?:s|season)[.-]?\d+[.-x]?(?:ep?|episode)[.-]?\d+)|\d+x\d+).)*$)'
        string8 = r'([s]?<<S>>x<<E>>[.-])'

        string_list = []
        string_list_append = string_list.append

        # Build pattern variations
        string_list_append(string1.replace('<<S>>', season_fill).replace('<<E>>', episode_fill))
        string_list_append(string1.replace('<<S>>', str_season).replace('<<E>>', episode_fill))
        string_list_append(string1.replace('<<S>>', season_fill).replace('<<E>>', str_episode))
        string_list_append(string1.replace('<<S>>', str_season).replace('<<E>>', str_episode))
        string_list_append(string2.replace('<<S>>', season_fill).replace('<<E>>', episode_fill))
        string_list_append(string2.replace('<<S>>', str_season).replace('<<E>>', episode_fill))
        string_list_append(string2.replace('<<S>>', season_fill).replace('<<E>>', str_episode))
        string_list_append(string2.replace('<<S>>', str_season).replace('<<E>>', str_episode))
        string_list_append(string3.replace('<<S>>', season_fill).replace('<<E1>>', str_ep_minus_1.zfill(2)).replace('<<E2>>', episode_fill))
        string_list_append(string3.replace('<<S>>', season_fill).replace('<<E1>>', episode_fill).replace('<<E2>>', str_ep_plus_1.zfill(2)))
        string_list_append(string4.replace('<<S>>', season_fill).replace('<<E>>', episode_fill))
        string_list_append(string4.replace('<<S>>', str_season).replace('<<E>>', episode_fill))
        string_list_append(string5.replace('<<E>>', episode_fill))
        string_list_append(string5.replace('<<E>>', str_episode))
        string_list_append(string6.replace('<<E>>', episode_fill))
        string_list_append(string7.replace('<<E>>', episode_fill))
        string_list_append(string8.replace('<<S>>', season_fill).replace('<<E>>', episode_fill))
        string_list_append(string8.replace('<<S>>', str_season).replace('<<E>>', episode_fill))
        string_list_append(string8.replace('<<S>>', season_fill).replace('<<E>>', str_episode))
        string_list_append(string8.replace('<<S>>', str_season).replace('<<E>>', str_episode))

        final_string = '|'.join(string_list)
        reg_pattern = re.compile(final_string)

        if split:
            match = re.search(reg_pattern, release_title)
            return release_title.split(match.group(), 1)[1] if match else release_title
        if return_match:
            match = re.search(reg_pattern, release_title)
            return match.group() if match else None

        # Check standard patterns first
        match_found = bool(re.search(reg_pattern, release_title))

        # If no match, check for episode pack ranges (e.g., "1-9", "01-09", "e01-e09")
        if not match_found:
            # Pattern: season.episodes_range (e.g., ".2.1-9.", ".s02.01-09.", ".s2e01-e09.")
            pack_patterns = [
                # Dot-separated: .2.1-9. or .02.01-09.
                r'[.-]' + season_fill + r'[.-](\d+)-(\d+)[.-]',
                r'[.-]' + str_season + r'[.-](\d+)-(\d+)[.-]',
                # S##E##-E## format: S02E01-E09 or S2E1-E9
                r's' + season_fill + r'e(\d+)-e(\d+)[.-]',
                r's' + str_season + r'e(\d+)-e(\d+)[.-]',
                # S##E##-## format: S02E01-09 or S2E1-9
                r's' + season_fill + r'e(\d+)-(\d+)[.-]',
                r's' + str_season + r'e(\d+)-(\d+)[.-]',
            ]

            for pack_pattern in pack_patterns:
                match = re.search(pack_pattern, release_title)
                if match:
                    try:
                        start_ep = int(match.group(1))
                        end_ep = int(match.group(2))
                        # Check if requested episode falls within the range
                        if start_ep <= episode_int <= end_ep:
                            match_found = True
                            if c.devmode:
                                c.log(f"[seas_ep_filter] Pack range match: S{season_fill}E{episode_fill} found in range {start_ep}-{end_ep}")
                            break
                    except (ValueError, IndexError):
                        continue

        # Compact logging: one line per source (only in devmode)
        if c.devmode:
            status = "(OK)" if match_found else "(X)"
            c.log(f"[seas_ep_filter] S{season_fill}E{episode_fill}: {status} {original_release[:80]}")
        return match_found
    except Exception as e:
        try:
            if c.devmode:
                c.log(f"[seas_ep_filter] EXCEPTION: {e}")
        except:
            pass
        return False

def get_quality(term):
    """Return the video quality from a given string."""
    qualities = (
        ('4k', RES_4K),
        ('1080p', RES_1080),
        ('720p', RES_720),
        ('sd', RES_SD),
        ('scr', SCR),
        ('cam', CAM),
    )

    for quality, patterns in qualities:
        if any(pattern in term.lower() for pattern in patterns):
            return quality

#unused
def is_anime(content_type, content_id, genre_type):
    try:
        genres = trakt.getGenre(content_type, content_id, genre_type)
        return any(genre in genres for genre in ['anime', 'animation'])
    except Exception:
        return False

def get_release_quality(release_name, release_link=None):

    try:
        if release_name is None:
            return 'sd', []

        quality = None
        release_name = cleantitle.get_title(release_name)
        quality = get_quality(release_name)

        if not quality:
            if release_link:
                release_link = cleantitle.get_title(release_link)
                quality = get_quality(release_link)
                if not quality:
                    quality = 'sd'
            else:
                quality = 'sd'
        info = []
        return quality, info
    except Exception as e:
        c.log(f'Exception in get_release_quality: {e}')
        return 'sd', []


def get_file_type(url):
    """Get the file type from a given URL."""
    url = client.replaceHTMLCodes(url)
    url = unquote(url)
    url = url.lower()
    url = re.sub('[^a-z0-9 ]+', ' ', url)

    file_types = []

    if any(i in url for i in ['bluray', 'blu ray']):
        file_types.append('Bluray')
    if any(i in url for i in ['bd r', 'bdr', 'bd rip', 'bdrip', 'br rip', 'brrip']):
        file_types.append('BDRip')
    if 'remux' in url:
        file_types.append('Remux')
    if any(i in url for i in ['dvdrip', 'dvd rip']):
        file_types.append('DVDRip')
    if any(i in url for i in ['dvd', 'dvdr', 'dvd r']):
        file_types.append('DVD')
    if any(i in url for i in ['webdl', 'web dl', 'web', 'web rip', 'webrip']):
        file_types.append('Web')
    if 'hdtv' in url:
        file_types.append('HDTV')
    if 'sdtv' in url:
        file_types.append('SDTV')
    if any(i in url for i in ['hdrip', 'hd rip']):
        file_types.append('HDRip')
    if any(i in url for i in ['uhdrip', 'uhd rip']):
        file_types.append('UHDRip')
    if 'r5' in url:
        file_types.append('R5')
    if any(i in url for i in ['cam', 'hdcam', 'hd cam', 'cam rip', 'camrip']):
        file_types.append('CAM')
    if any(i in url for i in ['ts', 'telesync', 'hdts', 'pdvd']):
        file_types.append('TS')
    if any(i in url for i in ['tc', 'telecine', 'hdtc']):
        file_types.append('TC')
    if any(i in url for i in ['scr', 'screener', 'dvdscr', 'dvd scr']):
        file_types.append('SCR')
    if 'xvid' in url:
        file_types.append('XVID')
    if 'avi' in url:
        file_types.append('AVI')
    if any(i in url for i in ['h 264', 'h264', 'x264', 'avc']):
        file_types.append('H.264')
    if any(i in url for i in ['h 265', 'h256', 'x265', 'hevc']):
        file_types.append('HEVC')
    if 'hi10p' in url:
        file_types.append('HI10P')
    if '10bit' in url:
        file_types.append('10BIT')
    if '3d' in url:
        file_types.append('3D')
    if any(i in url for i in ['hdr', 'hdr10', 'hlg']):
        file_types.append('HDR')
    if any(i in url for i in ['dolby vision', 'dolbyvision']):
        file_types.append('DV')
    if 'imax' in url:
        file_types.append('IMAX')
    if any(i in url for i in ['ac3', 'ac 3']):
        file_types.append('AC3')
    if 'aac' in url:
        file_types.append('AAC')
    #cm doubles - AAC is already checked, 5.1 also
    #if 'aac5 1' in url:
        #file_types.append('AAC / 5.1')
    if any(i in url for i in ['ddplus', 'dd plus', 'ddp', 'eac3', 'eac 3']):
        file_types.append('DD+')
    if any(i in url for i in ['dd', 'dolby', 'dolbydigital', 'dolby digital']) and 'DD' not in file_types and 'DD+' not in file_types:
        file_types.append('DD')
    if any(i in url for i in ['truehd', 'true hd']):
        file_types.append('TRUEHD')
    if 'atmos' in url:
        file_types.append('ATMOS')
    if 'dts' in url:
        file_types.append('DTS')
    if any(i in url for i in ['hdma', 'hd ma']):
        file_types.append('HD.MA')
    if any(i in url for i in ['hdhra', 'hd hra']):
        file_types.append('HD.HRA')
    if any(i in url for i in ['dtsx', 'dts x']):
        file_types.append('DTS:X')
    #cm doubles
    #if 'dd5 1' in url:
        #file_types.append('DD / 5.1')
    #if 'ddp5 1' in url:
        #file_types.append('DD+ / 5.1')
    if any(i in url for i in ['5 1', '6ch']):
        file_types.append('5.1')
    if any(i in url for i in ['7 1', '8ch']):
        file_types.append('7.1')
    if 'korsub' in url:
        file_types.append('HC-SUBS')
    if any(i in url for i in ['subs', 'subbed', 'sub']):
        file_types.append('SUBS')
    if any(i in url for i in ['dub', 'dubbed', 'dublado']):
        file_types.append('DUB')
    if 'repack' in url:
        file_types.append('REPACK')
    if 'proper' in url:
        file_types.append('PROPER')
    if 'nuked' in url:
        file_types.append('NUKED')

    return '[COLOR lawngreen] / [/COLOR]'.join(file_types)



def getFileType_bak(url):

    try:
        url = c.to_str(url)
        url = client.replaceHTMLCodes(url)
        url = unquote(url)
        url = url.lower()
        url = re.sub('[^a-z0-9 ]+', ' ', url)
    except Exception:
        url = str(url)
    type = ''

    if any(i in url for i in [' bluray ', ' blu ray ']):
        type += ' BLURAY /'
    if any(i in url for i in [' bd r ', ' bdr ', ' bd rip ', ' bdrip ', ' br rip ', ' brrip ']):
        type += ' BD-RIP /'
    if ' remux ' in url:
        type += ' REMUX /'
    if any(i in url for i in [' dvdrip ', ' dvd rip ']):
        type += ' DVD-RIP /'
    if any(i in url for i in [' dvd ', ' dvdr ', ' dvd r ']):
        type += ' DVD /'
    if any(i in url for i in [' webdl ', ' web dl ', ' web ', ' web rip ', ' webrip ']):
        type += ' WEB /'
    if ' hdtv ' in url:
        type += ' HDTV /'
    if ' sdtv ' in url:
        type += ' SDTV /'
    if any(i in url for i in [' hdrip ', ' hd rip ']):
        type += ' HDRIP /'
    if any(i in url for i in [' uhdrip ', ' uhd rip ']):
        type += ' UHDRIP /'
    if ' r5 ' in url:
        type += ' R5 /'
    if any(i in url for i in [' cam ', ' hdcam ', ' hd cam ', ' cam rip ', ' camrip ']):
        type += ' CAM /'
    if any(i in url for i in [' ts ', ' telesync ', ' hdts ', ' pdvd ']):
        type += ' TS /'
    if any(i in url for i in [' tc ', ' telecine ', ' hdtc ']):
        type += ' TC /'
    if any(i in url for i in [' scr ', ' screener ', ' dvdscr ', ' dvd scr ']):
        type += ' SCR /'
    if ' xvid ' in url:
        type += ' XVID /'
    if ' avi' in url:
        type += ' AVI /'
    if any(i in url for i in [' h 264 ', ' h264 ', ' x264 ', ' avc ']):
        type += ' H.264 /'
    if any(i in url for i in [' h 265 ', ' h256 ', ' x265 ', ' hevc ']):
        type += ' HEVC /'
    if ' hi10p ' in url:
        type += ' HI10P /'
    if ' 10bit ' in url:
        type += ' 10BIT /'
    if ' 3d ' in url:
        type += ' 3D /'
    if any(i in url for i in [' hdr ', ' hdr10 ', ' dolby vision ', ' hlg ']):
        type += ' HDR /'
    if ' imax ' in url:
        type += ' IMAX /'
    if any(i in url for i in [' ac3 ', ' ac 3 ']):
        type += ' AC3 /'
    if ' aac ' in url:
        type += ' AAC /'
    if ' aac5 1 ' in url:
        type += ' AAC / 5.1 /'
    if any(i in url for i in [' dd ', ' dolby ', ' dolbydigital ', ' dolby digital ']):
        type += ' DD /'
    if any(i in url for i in [' truehd ', ' true hd ']):
        type += ' TRUEHD /'
    if ' atmos ' in url:
        type += ' ATMOS /'
    if any(i in url for i in [' ddplus ', ' dd plus ', ' ddp ', ' eac3 ', ' eac 3 ']):
        type += ' DD+ /'
    if ' dts ' in url:
        type += ' DTS /'
    if any(i in url for i in [' hdma ', ' hd ma ']):
        type += ' HD.MA /'
    if any(i in url for i in [' hdhra ', ' hd hra ']):
        type += ' HD.HRA /'
    if any(i in url for i in [' dtsx ', ' dts x ']):
        type += ' DTS:X /'
    if ' dd5 1 ' in url:
        type += ' DD / 5.1 /'
    if ' ddp5 1 ' in url:
        type += ' DD+ / 5.1 /'
    if any(i in url for i in [' 5 1 ', ' 6ch ']):
        type += ' 5.1 /'
    if any(i in url for i in [' 7 1 ', ' 8ch ']):
        type += ' 7.1 /'
    if ' korsub ' in url:
        type += ' HC-SUBS /'
    if any(i in url for i in [' subs ', ' subbed ', ' sub ']):
        type += ' SUBS /'
    if any(i in url for i in [' dub ', ' dubbed ', ' dublado ']):
        type += ' DUB /'
    if ' repack ' in url:
        type += ' REPACK /'
    if ' proper ' in url:
        type += ' PROPER /'
    if ' nuked ' in url:
        type += ' NUKED /'
    type = type.rstrip('/')
    return type

def check_sd_url(release_link):
    try:
        release_link = re.sub('[^A-Za-z0-9]+', ' ', release_link)
        release_link = release_link.lower()
        try:
            release_link = c.to_str(release_link)
        except Exception:
            pass
        quality = get_quality(release_link)
        if not quality:
            quality = 'sd'
        return quality
    except Exception:
        return 'sd'


def check_direct_url(url):
    try:
        url = re.sub('[^A-Za-z0-9]+', ' ', url)
        url = c.to_str(url)
        url = url.lower()
        quality = get_quality(url)
        if not quality:
            quality = 'sd'
        return quality
    except Exception:
        return 'sd'

def check_url(url):
    try:
        url = client.replaceHTMLCodes(url)
        url = unquote(url)
        url = re.sub('[^A-Za-z0-9]+', ' ', url)
        url = c.to_str(url)
        url = url.lower()
    except Exception:
        url = str(url)

    try:
        quality = get_quality(url)
        if not quality:
            quality = 'sd'
        return quality
    except Exception:
        return 'sd'

def label_to_quality(label):
    try:
        try:
            label = int(re.search('(\d+)', label).group(1))
        except Exception:
            label = 0

        if label >= 2160:
            return '4K'
        elif label >= 1080:
            return '1080p'
        elif 720 <= label < 1080:
            return '720p'
        elif label < 720:
            return 'sd'
    except Exception:
        return 'sd'

def strip_domain(url):
    try:
        url = c.to_str(url)
        if url.lower().startswith('http') or url.startswith('/'):
            url = re.findall('(?://.+?|)(/.+)', url)[0]
        url = client.replaceHTMLCodes(url)
        return url
    except Exception:
        return


def is_host_valid(url, domains):
    try:
        url = c.to_str(url).lower()
        if any(x in url for x in ['.rar.', '.zip.', '.iso.']) or any(url.endswith(x) for x in ['.rar', '.zip', '.idx', '.sub', '.srt']):
            return False, ''
        if any(x in url for x in ['sample', 'trailer', 'zippyshare', 'facebook', 'youtu']):
            return False, ''
        host = __top_domain(url)
        hosts = [domain.lower() for domain in domains if host and host in domain.lower()]

        if hosts and '.' not in host:
            host = hosts[0]
        if hosts and any([h for h in ['google', 'picasa', 'blogspot'] if h in host]):
            host = 'gvideo'
        if hosts and any([h for h in ['akamaized','ocloud'] if h in host]):
            host = 'CDN'
        return any(hosts), host
    except Exception:
        return False, ''


def __top_domain(url):
    if not (url.startswith('//') or url.startswith('http://') or url.startswith('https://')):
        url = '//' + url
    elements = urlparse(url)
    domain = elements.netloc or elements.path
    domain = domain.split('@')[-1].split(':')[0]
    regex = "(?:www\.)?([\w\-]*\.[\w\-]{2,3}(?:\.[\w\-]{2,3})?)$"
    res = re.search(regex, domain)
    if res:
        domain = res.group(1)
    domain = domain.lower()
    return domain

def aliases_to_array(aliases, filter=None):
    try:
        if not filter:
            filter = []
        if isinstance(filter, str):
            filter = [filter]

        return [x.get('title') for x in aliases if not filter or x.get('country') in filter]
    except Exception:
        return []


def append_headers(headers):
    return '|%s' % '&'.join(['%s=%s' % (key, quote_plus(headers[key])) for key in headers])


def _size(siz):
    if siz in ['0', 0, '', None]:
        return 0.0, ''
    div = 1 if siz.lower().endswith(('gb', 'gib')) else 1024
    float_size = float(re.sub('[^0-9|/.|/,]', '', siz.replace(',', '.'))) / div
    str_size = str('%.2f GB' % float_size)
    return float_size, str_size

def file_size(siz):
    if siz in ['0', 0, '', None]:
        return 0.0, ''
    div = 1 if siz.lower().endswith(('gb', 'gib')) else 1024
    float_size = float(re.sub('[^0-9|/.|/,]', '', siz.replace(',', '.'))) / div
    str_size = str('%.2f GB' % float_size)
    return float_size, str_size



def get_size(url):
    try:
        size = client.request(url, output='file_size')
        if size == '0':
            size = False
        size = convert_size(size)
        return size
    except Exception:
        return False


def convert_size_old(size_bytes):
    import math
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    if size_name[i] == 'B' or size_name[i] == 'KB':
        return None
    return "%s %s" % (s, size_name[i])

def convert_size(size_bytes):
    import math
    if size_bytes == 0:
        return "0B"
    units = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    index = int(math.floor(math.log(size_bytes, 1024)))
    power = math.pow(1024, index)
    size = round(size_bytes / power, 2)
    if units[index] in ('B', 'KB'):
        return None
    return f"{size} {units[index]}"



def check_directstreams(url, hoster='', quality='SD'):
    urls = []
    host = hoster

    if 'google' in url or any(x in url for x in ['youtube.', 'docid=']):
        urls = directstream.google(url)
        if not urls:
            tag = directstream.googletag(url)
            if tag:
                urls = [{'quality': tag[0]['quality'], 'url': url}]
        if urls:
            host = 'gvideo'
    elif 'ok.ru' in url:
        urls = directstream.odnoklassniki(url)
        if urls:
            host = 'vk'
    elif 'vk.com' in url:
        urls = directstream.vk(url)
        if urls:
            host = 'vk'
    elif any(x in url for x in ['akamaized', 'blogspot', 'ocloud.stream']):
        urls = [{'url': url}]
        if urls:
            host = 'CDN'

    direct = True if urls else False

    if not urls:
        urls = [{'quality': quality, 'url': url}]

    return urls, host, direct

def scraper_error(name):
    c.log('An exception error in scraper "' + name + '" occurred.')


def aliases_to_array(aliases, filter=None):
    """Convert aliases to array format."""
    try:
        if all(isinstance(x, str) for x in aliases): return aliases
        if not filter: filter = []
        if isinstance(filter, str): filter = [filter]
        return [x.get('title') for x in aliases if not filter or x.get('country') in filter]
    except:
        log_utils.error()
        return []


def release_title_format(release_title):
    """Format release title for pack filtering."""
    try:
        release_title = release_title.lower()
        release_title = release_title.replace(' ', '.')
        fmt = '.%s.' % release_title.replace('.', ' ').strip()
        return fmt
    except:
        log_utils.error()
        return release_title


def filter_season_pack(show_title, aliases, year, season, release_title):
    """
    Filter and validate season pack releases.

    Returns:
        tuple: (valid, episode_start, episode_end)
               valid: bool - True if this is a valid season pack
               episode_start: int - Starting episode for partial packs (0 if full season)
               episode_end: int - Ending episode for partial packs (0 if full season)
    """
    aliases = aliases_to_array(aliases)
    title_list = []
    title_list_append = title_list.append
    if aliases:
        for item in aliases:
            try:
                alias = item.replace('!', '').replace('(', '').replace(')', '').replace('&', 'and').replace(year, '')
                if alias in title_list: continue
                title_list_append(alias)
            except:
                log_utils.error()
    try:
        show_title = show_title.replace('!', '').replace('(', '').replace(')', '').replace('&', 'and').replace(year, '')
        if show_title not in title_list: title_list_append(show_title)

        season_fill = str(season).zfill(2)
        season_check = f'.s{season}.'
        season_fill_check = f'.s{season_fill}.'
        season_fill_checke = f'.s{season_fill}e'
        season_full_check = f'.season.{season}.'
        season_full_check_ns = f'.season{season}.'
        season_full_fill_check = f'.season.{season_fill}.'
        season_full_fill_check_ns = f'.season{season_fill}.'
        split_list = (season_check, season_fill_check, season_fill_checke, '.' + str(season) + '.season', 'total.season', 'season', 'the.complete', 'complete', str(year))
        string_list = (season_check, season_fill_check, season_fill_checke, season_full_check, season_full_check_ns, season_full_fill_check, season_full_fill_check_ns)

        release_title = release_title_format(release_title)
        t = release_title.replace('-', '.')
        for i in split_list:
            t = t.split(i)[0]
        cleantitle_t = cleantitle.get(t)
        if all(cleantitle.get(x) != cleantitle_t for x in title_list):
            return False, 0, 0

        # Return and identify episode ranges (partial season packs)
        range_regex = (
                r's\d{1,3}e(\d{1,3})[-.]e(\d{1,3})',
                r's\d{1,3}e(\d{1,3})[-.](\d{1,3})(?!p|bit|gb)(?!\d{1,3})',
                r's\d{1,3}[-.]e(\d{1,3})[-.]e(\d{1,3})',
                r'season[.-]?\d{1,3}[.-]?ep[.-]?(\d{1,3})[-.]ep[.-]?(\d{1,3})',
                r'season[.-]?\d{1,3}[.-]?episode[.-]?(\d{1,3})[-.]episode[.-]?(\d{1,3})')
        for regex in range_regex:
            match = re.search(regex, release_title)
            if match:
                episode_start = int(match.group(1))
                episode_end = int(match.group(2))
                return True, episode_start, episode_end

        # Remove single episodes ONLY (returned in single ep scrape), keep episode ranges as season packs
        episode_regex = (
                r's\d{1,3}e\d{1,3}[-.](?!\d{2,3}[-.])(?!e\d{1,3})(?!\d{2}gb)',
                r'season[.-]?\d{1,3}[.-]?ep[.-]?\d{1,3}[-.](?!\d{2,3}[-.])(?!e\d{1,3})(?!\d{2}gb)',
                r'season[.-]?\d{1,3}[.-]?episode[.-]?\d{1,3}[-.](?!\d{2,3}[-.])(?!e\d{1,3})(?!\d{2}gb)')
        for item in episode_regex:
            if bool(re.search(item, release_title)):
                return False, 0, 0

        # Remove season ranges - returned in showPack scrape
        rt = release_title.replace('-', '.')
        if any(i in rt for i in string_list):
            for item in (
                season_check.rstrip('.') + r'[.-]s([2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]|$)',
                season_fill_check.rstrip('.') + r'[.-]s\d{2}(?:[.-]|$)',
                season_fill_check.rstrip('.') + r'[.-]\d{2}(?:[.-]|$)',
                r'\Ws\d{2}\W%s' % season_fill_check.lstrip('.'),
                season_full_check.rstrip('.') + r'[.-]to[.-]([2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]|$)',
                season_full_check.rstrip('.') + r'[.-]season[.-]([2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]|$)',
                season_full_check.rstrip('.') + r'[.-]([2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]|$)',
                season_full_check.rstrip('.') + r'[.-]\d{1}[.-]\d{1,2}(?:[.-]|$)',
                season_full_check.rstrip('.') + r'[.-]\d{3}[.-](?:19|20)[0-9]{2}(?:[.-]|$)',
                season_full_fill_check.rstrip('.') + r'[.-]\d{3}[.-]\d{3}(?:[.-]|$)',
                season_full_fill_check.rstrip('.') + r'[.-]season[.-]\d{2}(?:[.-]|$)'
                    ):
                if bool(re.search(item, release_title)):
                    return False, 0, 0
            return True, 0, 0
        return False, 0, 0
    except:
        log_utils.error()
        return False, 0, 0


def filter_show_pack(show_title, aliases, imdb, year, season, release_title, total_seasons):
    """
    Filter and validate complete show pack releases.

    Returns:
        tuple: (valid, last_season)
            valid: bool - True if this is a valid show pack
            last_season: int - The last season included in the pack
    """
    aliases = aliases_to_array(aliases)
    title_list = []
    title_list_append = title_list.append
    if aliases:
        for item in aliases:
            try:
                alias = item.replace('!', '').replace('(', '').replace(')', '').replace('&', 'and').replace(year, '')
                if alias in title_list:
                    continue
                title_list_append(alias)
            except:
                log_utils.error()
    try:
        show_title = show_title.replace('!', '').replace('(', '').replace(')', '').replace('&', 'and').replace(year, '')
        if show_title not in title_list:
            title_list_append(show_title)

        split_list = ('.all.seasons', 'seasons', 'season', 'the.complete', 'complete', 'all.torrent', 'total.series', 'tv.series', 'series', 'edited', 's1', 's01', year)
        release_title = release_title_format(release_title)
        t = release_title.replace('-', '.')
        for i in split_list:
            t = t.split(i)[0]
        cleantitle_t = cleantitle.get(t)
        if all(cleantitle.get(x) != cleantitle_t for x in title_list):
            return False, 0

        # Remove single episodes (returned in single ep scrape)
        episode_regex = (
                r's\d{1,3}e\d{1,3}',
                r's[0-3]{1}[0-9]{1}[.-]e\d{1,2}',
                r's\d{1,3}[.-]\d{1,3}e\d{1,3}',
                r'season[.-]?\d{1,3}[.-]?ep[.-]?\d{1,3}',
                r'season[.-]?\d{1,3}[.-]?episode[.-]?\d{1,3}')
        for item in episode_regex:
            if bool(re.search(item, release_title)):
                return False, 0

        # Remove season ranges that do not begin at 1
        season_range_regex = (
                r'(?:season|seasons|s)[.-]?(?:0?[2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]?to[.-]?|[.-]?thru[.-]?|[.-])(?:season|seasons|s|)[.-]?(?:0?[3-9]{1}(?!\d{2}p)|[1-3]{1}[0-9]{1}(?!\d{2}p))',)
        for item in season_range_regex:
            if bool(re.search(item, release_title)):
                return False, 0

        # Remove single seasons - returned in seasonPack scrape
        season_regex = (
                r'season[.-]?([1-9]{1})[.-]0{1}\1[.-]?complete',
                r'season[.-]?([2-9]{1})[.-](?:[0-9]+)[.-]?complete',
                r'season[.-]?\d{1,2}[.-]s\d{1,2}',
                r'season[.-]?\d{1,2}[.-]complete',
                r'season[.-]?\d{1,2}[.-]\d{3,4}p{0,1}',
                r'season[.-]?\d{1,2}[.-](?!thru|to|\d{1,2}[.-])',
                r'season[.-]?\d{1,2}[.]?$',
                r'season[.-]?\d{1,2}[.-](?:19|20)[0-9]{2}',
                r'season[.-]?\d{1,2}[.-]\d{3}[.-]{1,2}(?:19|20)[0-9]{2}',
                r'(?<!thru)(?<!to)(?<!\d{2})[.-]s\d{2}[.-]complete',
                r'(?<!thru)(?<!to)(?<!s\d{2})[.-]s\d{2}(?![.-]thru)(?![.-]to)(?![.-]s\d{2})(?![.-]\d{2}[.-])'
                )
        for item in season_regex:
            if bool(re.search(item, release_title)):
                return False, 0

        # Remove spelled out single seasons
        season_regex = ()
        season_regex += tuple([r'complete[.-]%s[.-]season' % x for x in SEASON_ORDINAL_LIST])
        season_regex += tuple([r'complete[.-]%s[.-]season' % x for x in SEASON_ORDINAL2_LIST])
        season_regex += tuple([r'season[.-]%s' % x for x in SEASON_LIST])
        for item in season_regex:
            if bool(re.search(item, release_title)):
                return False, 0

        # Set last_season for range type ex "1.2.3.4" or "1.2.3.and.4"
        dot_release_title = release_title.replace('-', '.')
        dot_season_ranges = []
        all_seasons = '1'
        season_count = 2
        while season_count <= int(total_seasons):
            dot_season_ranges.append(all_seasons + '.and.%s' % str(season_count))
            all_seasons += '.%s' % str(season_count)
            dot_season_ranges.append(all_seasons)
            season_count += 1
        if any(i in dot_release_title for i in dot_season_ranges):
            keys = [i for i in dot_season_ranges if i in dot_release_title]
            last_season = int(keys[-1].split('.')[-1])
            return True, last_season

        # "1.to.9" type range filter
        to_season_ranges = []
        start_season = '1'
        season_count = 2
        while season_count <= int(total_seasons):
            to_season_ranges.append(start_season + f'.to.{season_count}')
            season_count += 1
        if any(i in dot_release_title for i in to_season_ranges):
            keys = [i for i in to_season_ranges if i in dot_release_title]
            last_season = int(keys[0].split('to.')[1])
            return True, last_season

        # "1.thru.9" range filter
        thru_ranges = [i.replace('to', 'thru') for i in to_season_ranges]
        if any(i in dot_release_title for i in thru_ranges):
            keys = [i for i in thru_ranges if i in dot_release_title]
            last_season = int(keys[0].split('thru.')[1])
            return True, last_season

        # "1-9" range filter
        dash_ranges = [i.replace('.to.', '-') for i in to_season_ranges]
        if any(i in release_title for i in dash_ranges):
            keys = [i for i in dash_ranges if i in release_title]
            last_season = int(keys[0].split('-')[1])
            return True, last_season

        # "1~9" range filter
        tilde_ranges = [i.replace('.to.', '~') for i in to_season_ranges]
        if any(i in release_title for i in tilde_ranges):
            keys = [i for i in tilde_ranges if i in release_title]
            last_season = int(keys[0].split('~')[1])
            return True, last_season

        # "01.to.09" 2 digit range filter
        to_season_ranges = []
        start_season = '01'
        season_count = 2
        while season_count <= int(total_seasons):
            to_season_ranges.append(start_season + '.to.%s' % ('0' + str(season_count) if int(season_count) < 10 else str(season_count)))
            season_count += 1
        if any(i in dot_release_title for i in to_season_ranges):
            keys = [i for i in to_season_ranges if i in dot_release_title]
            last_season = int(keys[0].split('to.')[1])
            return True, last_season

        # "01.thru.09" 2 digit range filter
        thru_ranges = [i.replace('to', 'thru') for i in to_season_ranges]
        if any(i in dot_release_title for i in thru_ranges):
            keys = [i for i in thru_ranges if i in dot_release_title]
            last_season = int(keys[0].split('thru.')[1])
            return True, last_season

        # "01-09" 2 digit range filtering
        dash_ranges = [i.replace('.to.', '-') for i in to_season_ranges]
        if any(i in release_title for i in dash_ranges):
            keys = [i for i in dash_ranges if i in release_title]
            last_season = int(keys[0].split('-')[1])
            return True, last_season

        # "01~09" 2 digit range filtering
        tilde_ranges = [i.replace('.to.', '~') for i in to_season_ranges]
        if any(i in release_title for i in tilde_ranges):
            keys = [i for i in tilde_ranges if i in release_title]
            last_season = int(keys[0].split('~')[1])
            return True, last_season

        # Complete series (all seasons)
        return True, int(total_seasons)
    except:
        log_utils.error()
        return False, 0


# if salt is provided, it should be string
# ciphertext is base64 and passphrase is string
def evp_decode(cipher_text, passphrase, salt=None):
    cipher_text = base64.b64decode(cipher_text)
    if not salt:
        salt = cipher_text[8:16]
        cipher_text = cipher_text[16:]
    data = evpKDF(passphrase, salt)
    decrypter = pyaes.Decrypter(pyaes.AESModeOfOperationCBC(data['key'], data['iv']))
    plain_text = decrypter.feed(cipher_text)
    plain_text += decrypter.feed()
    return plain_text


def evpKDF(passwd, salt, key_size=8, iv_size=4, iterations=1, hash_algorithm="md5"):
    target_key_size = key_size + iv_size
    derived_bytes = b""
    number_of_derived_words = 0
    block = None
    hasher = hashlib.new(hash_algorithm)
    while number_of_derived_words < target_key_size:
        if block is not None:
            hasher.update(block)

        hasher.update(passwd)
        hasher.update(salt)
        block = hasher.digest()
        hasher = hashlib.new(hash_algorithm)

        for _i in range(1, iterations):
            hasher.update(block)
            block = hasher.digest()
            hasher = hashlib.new(hash_algorithm)

        derived_bytes += block[0: min(len(block), (target_key_size - number_of_derived_words) * 4)]

        number_of_derived_words += len(block) / 4

    return {
        "key": derived_bytes[0: key_size * 4],
        "iv": derived_bytes[key_size * 4:]
    }
