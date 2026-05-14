# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file sources.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''


import os
import sys
import time
import json
from urllib.parse import urlencode
import sqlite3 as db
from datetime import datetime
import traceback

import importlib.util
import importlib.machinery
import requests


import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from . import keys
from .crewruntime import c
from . import http_client



lang2 = xbmc.getLocalizedString
addon = xbmcaddon.Addon
addItem = xbmcplugin.addDirectoryItem
addItems = xbmcplugin.addDirectoryItems
item = xbmcgui.ListItem
directory = xbmcplugin.endOfDirectory
content = xbmcplugin.setContent
sortMethod = xbmcplugin.addSortMethod
property = xbmcplugin.setProperty
infoLabel = xbmc.getInfoLabel
condVisibility = xbmc.getCondVisibility
jsonrpc = xbmc.executeJSONRPC
window = xbmcgui.Window(10000)
dialog = xbmcgui.Dialog()
progressDialog = xbmcgui.DialogProgress()
progressDialogBG = xbmcgui.DialogProgressBG()
windowDialog = xbmcgui.WindowDialog()
button = xbmcgui.ControlButton
image = xbmcgui.ControlImage
getCurrentDialogId = xbmcgui.getCurrentWindowDialogId()
keyboard = xbmc.Keyboard
monitor = xbmc.Monitor()
execute = xbmc.executebuiltin
skin = xbmc.getSkinDir()
player = xbmc.Player()
playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
resolve = xbmcplugin.setResolvedUrl
legalFilename = xbmcvfs.makeLegalFilename
openFile = xbmcvfs.File
makeFile = xbmcvfs.mkdir
deleteFile = xbmcvfs.delete
deleteDir = xbmcvfs.rmdir
listDir = xbmcvfs.listdir
transPath = xbmcvfs.translatePath
skinPath = transPath('special://skin/')

# Compute addon path from CrewRuntime (evaluated after c is initialized)
def _compute_addon_path():
    try:
        return transPath(c.addonInfo('path'))
    except:
        return None
addonPath = _compute_addon_path()

# All paths now computed from CrewRuntime (cached for performance)
dataPath = c.datapath
settingsFile = c.get_path('settings')
viewsFile = c.get_path('views')
bookmarksFile = c.get_path('bookmarks')
providercacheFile = c.get_path('providercache')
metacacheFile = c.get_path('metacache')
searchFile = c.get_path('search')
libcacheFile = c.get_path('libcache')
cacheFile = c.get_path('cache')
dbFile = c.get_path('debridcache')
dbSettings = c.get_path('dbsettings')
traktsyncFile = c.get_path('traktsync')



key = "RgUkXp2s5v8x/A?D(G+KbPeShVmYq3t6"

iv = "p2s5v8y/B?E(H+Mb"

integer = 1000


# Backwards compatibility wrapper for control.log()
def log(msg, trace=0):
    return c.log(msg, trace)

# Backward-compatible wrappers forwarding to CrewRuntime
# These are callables so they work for both control.lang(32001) and control.lang
def lang(string_id):
    """Get localized string - forwards to CrewRuntime."""
    return c.lang(string_id)

def setting(setting_id):
    """Get addon setting - forwards to CrewRuntime."""
    return c.get_setting(setting_id)

def setSetting(setting_id, value):
    """Set addon setting - forwards to CrewRuntime."""
    return c.set_setting(setting_id, value)
def addonInfo(info_id):
    """Get addon info - forwards to CrewRuntime."""
    return c.addonInfo(info_id)

def six_encode(txt, char='utf-8', errors='replace'):
    """
    Backwards compatibility wrapper - delegates to c.to_bytes().
    Used by regex.py (3 calls).
    """
    return c.to_bytes(txt, encoding=char, errors=errors)

def six_decode(txt, char='utf-8', errors='replace'):
    """
    Backwards compatibility wrapper - delegates to c.to_str().
    Used by regex.py (3 calls).
    """
    return c.to_str(txt, encoding=char, errors=errors)




def encode(s, encoding='utf-8') -> bytes:
    """
    Encodes a string to bytes using the specified encoding.

    Parameters:
        s (str): The string to be encoded. It can be a str (Python 3) or unicode (Python 2).
        encoding (str): The encoding type. Default is 'utf-8'.

    Returns:
        bytes: The encoded byte string.
    """

    # Check if the input is a string
    if isinstance(s, str):
        # In Python 3, 'str' is already Unicode, so we encode it.
        return s.encode(encoding)

    if isinstance(s, bytes):
        # If it's already bytes, just return it as is (Python 3)
        return s

    # If it's neither a string nor bytes, raise an error
    raise TypeError(f"Input must be a string or bytes, not '{type(s).__name__}'")

def decode(data, encoding='utf-8') -> str:

    # Check if the input data is already of type string
    """
    Decodes a byte string into a string.

    If the input data is already a string, it is returned unchanged.
    If the input data is not a byte string, a ValueError is raised.
    If the decoding fails, a UnicodeDecodeError is raised.

    Parameters
    ----------
    data : bytes
        The byte string to decode.
    encoding : str
        The encoding of the byte string. Defaults to 'utf-8'.

    Returns
    -------
    str
        The decoded string.

    Raises
    ------
    ValueError
        If the input data is not a byte string.
    UnicodeDecodeError
        If the decoding fails.
    """
    if isinstance(data, str):
        return data

    # Check if the input data is of type bytes
    if not isinstance(data, bytes):
        raise ValueError("Input data must be a byte string.")

    try:
        # Try to decode the byte string
        return data.decode(encoding)
    except UnicodeDecodeError as e:
        # Re-raise a UnicodeDecodeError with the required constructor parameters
        raise UnicodeDecodeError(e.encoding, e.object, e.start, e.end, f"Decoding failed: {e}") from e


# Modified `sleep` command that honors a user exit request
def sleep(time):
    while time > 0 and not monitor.abortRequested():
        xbmc.sleep(min(100, time))
        time = time - 100


def getKodiVersion(as_string=False, as_full=False):
    """Get Kodi version - forwards to CrewRuntime  (cached)."""
    return c.kodi_version(as_string, as_full)


def metadataClean(metadata): # Filter out non-existing/custom keys. Otherise there are tons of errors in Kodi log.
    """
    Filter out non-existing/custom keys from Kodi metadata.

    :param metadata: A dictionary containing Kodi metadata.
    :return: A dictionary containing only the metadata keys that are known to Kodi.
    """
    if metadata is None:
        return metadata
    allowed = [
        'genre', 'country', 'year', 'episode', 'season', 'sortepisode',
        'sortseason', 'episodeguide', 'showlink', 'top250', 'setid',
        'tracknumber', 'rating', 'userrating', 'watched', 'playcount',
        'overlay', 'cast', 'castandrole', 'director', 'mpaa', 'plot',
        'plotoutline', 'title', 'originaltitle', 'sorttitle', 'duration',
        'studio', 'tagline', 'writer', 'tvshowtitle', 'premiered', 'status',
        'set', 'setoverview', 'tag', 'imdbnumber', 'code', 'aired', 'credits',
        'lastplayed', 'album', 'artist', 'votes', 'path', 'trailer', 'dateadded',
        'mediatype', 'dbid'
        ]
    return {k: v for k, v in metadata.items() if k in allowed}


def tagdataClean(tagdata): # Filter out non-existing in litItem.
    """
    Filter out non-existing in litItem.

    :param tagdata: A dictionary of tag data.
    :type tagdata: dict
    :return: A filtered dictionary of tag data.
    :rtype: dict
    """
    if tagdata is None:
        return tagdata

    # Normalize country/countries to a single key 'country' as a list for Kodi compatibility
    # Some indexers provide 'countries' (list) or 'country' (string); Kodi requires a list/tuple
    if 'countries' in tagdata:
        val = tagdata.pop('countries')
        if isinstance(val, str):
            tagdata['country'] = c.string_split_to_list(val) if ('/' in val or ',' in val) else [val]
        elif isinstance(val, (list, tuple)):
            tagdata['country'] = list(val)
        else:
            tagdata['country'] = []
    elif 'country' in tagdata:
        val = tagdata['country']
        if isinstance(val, str):
            tagdata['country'] = c.string_split_to_list(val) if ('/' in val or ',' in val) else [val]
        elif isinstance(val, tuple):
            tagdata['country'] = list(val)

    allowed = [
        'size','count','date','genre','country','year','episode','season',
        'sortepisode','sortseason','episodeguide','showlink','top250','setid',
        'tracknumber','rating','userrating','watched','playcount','overlay',
        'cast','castandthumb','castandrole','director','mpaa','plot','plotoutline','title',
        'originaltitle','sorttitle','duration','studio','tagline','writer',
        'tvshowtitle','premiered','status','set','setoverview','tag','imdbnumber',
        'code','aired','credits','lastplayed','album','artist','votes','path',
        'trailer','dateadded','mediatype','dbid'
        ] #, 'resume_point', 'offset'

    if 'votes' in tagdata:
        tagdata['votes'] = str(tagdata['votes']).replace(",", "")
        tagdata['votes'] = int(tagdata['votes'])
    return {k: v for k, v in tagdata.items() if k in allowed}






# Artwork functions - forward to CrewRuntime  (deduplicated)
def addonIcon():
    """Get addon icon - forwards to CrewRuntime."""
    return c.addon_icon()

def addonThumb():
    """Get addon thumbnail - forwards to CrewRuntime."""
    return c.addon_thumb()

def addonPoster():
    """Get addon poster - forwards to CrewRuntime."""
    return c.addon_poster()

def addonBanner():
    """Get addon banner - forwards to CrewRuntime."""
    return c.addon_banner()

def addonFanart():
    """Get addon fanart - forwards to CrewRuntime."""
    return c.addon_fanart()

def addonClearart():
    """Get addon clear art - forwards to CrewRuntime."""
    return c.addon_clearart()

def addonDiscart():
    """Get addon disc art - forwards to CrewRuntime."""
    return c.addon_discart()

def addonClearlogo():
    """Get addon clear logo - forwards to CrewRuntime."""
    return c.addon_clearlogo()

def addonNext():
    """Get addon next icon - forwards to CrewRuntime."""
    return c.addon_next()

def addonAdultIcon():
    """Get adult icon - forwards to CrewRuntime."""
    return c.addon_adult_icon()

def addonId():
    return addonInfo('id')


def addonName():
    return addonInfo('name')


def get_plugin_url(queries):
    try:
        query = urlencode(queries)
    except UnicodeEncodeError:
        for k in queries:
            if isinstance(queries[k], str):
                #queries[k] = six_encode(queries[k])
                queries[k] = c.encode(queries[k])
        query = urlencode(queries)
    addon_id = sys.argv[0]
    if not addon_id:
        addon_id = addonId()
    #return addon_id + '?' + query
    return f'{addon_id}?{query}'


def artPath():
    theme = appearance()
    if theme in ['-', '']:
        return
    elif condVisibility('System.HasAddon(script.thecrew.artwork)'):
        return os.path.join(xbmcaddon.Addon('script.thecrew.artwork').getAddonInfo('path'), 'resources', 'media', theme)



def appearance():
    """Get appearance theme - forwards to CrewRuntime."""
    return c.appearance()

def artwork():
    """Open artwork tool - forwards to CrewRuntime."""
    return c.artwork()



def okDialog(message, heading='Info'):
    """
    Display a simple OK dialog with the given message and optional heading.
    """
    xbmcgui.Dialog().ok(heading, message)


def infoDialog(message, heading=addonInfo('name'), icon='', time=3000, sound=False):
    """Show info dialog - forwards to CrewRuntime."""
    return c.infoDialog(message, heading, icon, time, sound)

def startupMaintenance():
    """
    Run comprehensive startup maintenance.
    Forwards to new startup_maintenance module for organized maintenance tasks.
    """
    try:
        from . import startup_maintenance
        return startup_maintenance.run_startup_maintenance()
    except Exception as e:
        c.log(f'[startupMaintenance] Error: {e}', 1)
        c.log(traceback.format_exc(), 1)
        return False


def yesnoDialog(message, heading=addonInfo('name'), nolabel='', yeslabel=''):
    return dialog.yesno(heading, message, nolabel, yeslabel)

#TC 2/01/19 started
#CM 2/26/26 was here ;)

def selectDialog(_list, heading=addonInfo('name'), useDetails=False):
    return dialog.select(heading, _list, useDetails=useDetails)

def metaFile():
    """Get meta database path - forwards to CrewRuntime."""
    return c.get_path('meta')

def metaFile_old():
    if condVisibility('System.HasAddon(script.thecrew.metadata)'):
        return os.path.join( xbmcaddon.Addon('script.thecrew.metadata').getAddonInfo('path'), 'resources', 'data', 'meta.db')

def apiLanguage(ret_name=None):
    langDict = {
        'Bulgarian': 'bg', 'Chinese': 'zh', 'Croatian': 'hr', 'Czech': 'cs', 'Danish': 'da', 'Dutch': 'nl',
        'English': 'en', 'Finnish': 'fi', 'French': 'fr', 'German': 'de', 'Greek': 'el', 'Hebrew': 'he',
        'Hungarian': 'hu', 'Italian': 'it', 'Japanese': 'ja', 'Korean': 'ko', 'Norwegian': 'no', 'Polish': 'pl',
        'Portuguese': 'pt', 'Romanian': 'ro', 'Russian': 'ru', 'Serbian': 'sr', 'Slovak': 'sk', 'Slovenian': 'sl',
        'Spanish': 'es', 'Swedish': 'sv', 'Thai': 'th', 'Turkish': 'tr', 'Ukrainian': 'uk'}


    trakt = ['bg', 'cs', 'da', 'de', 'el', 'en', 'es', 'fi', 'fr', 'he', 'hr', 'hu', 'it', 'ja',
            'ko', 'nl', 'no', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl', 'sr', 'sv', 'th', 'tr', 'uk', 'zh']
    tvdb = ['en', 'sv', 'no', 'da', 'fi', 'nl', 'de', 'it', 'es', 'fr', 'pl',
            'hu', 'el', 'tr', 'ru', 'he', 'ja', 'pt', 'zh', 'cs', 'sl', 'hr', 'ko']

    youtube = ['gv', 'gu', 'gd', 'ga', 'gn', 'gl', 'ty', 'tw', 'tt', 'tr', 'ts', 'tn', 'to', 'tl', 'tk', 'th', 'ti',
                'tg', 'te', 'ta', 'de', 'da', 'dz', 'dv', 'qu', 'zh', 'za', 'zu', 'wa', 'wo', 'jv', 'ja', 'ch', 'co',
                'ca', 'ce', 'cy', 'cs', 'cr', 'cv', 'cu', 'ps', 'pt', 'pa', 'pi', 'pl', 'mg', 'ml', 'mn', 'mi', 'mh',
                'mk', 'mt', 'ms', 'mr', 'my', 've', 'vi', 'is', 'iu', 'it', 'vo', 'ii', 'ik', 'io', 'ia', 'ie', 'id',
                'ig', 'fr', 'fy', 'fa', 'ff', 'fi', 'fj', 'fo', 'ss', 'sr', 'sq', 'sw', 'sv', 'su', 'st', 'sk', 'si',
                'so', 'sn', 'sm', 'sl', 'sc', 'sa', 'sg', 'se', 'sd', 'lg', 'lb', 'la', 'ln', 'lo', 'li', 'lv', 'lt',
                'lu', 'yi', 'yo', 'el', 'eo', 'en', 'ee', 'eu', 'et', 'es', 'ru', 'rw', 'rm', 'rn', 'ro', 'be', 'bg',
                'ba', 'bm', 'bn', 'bo', 'bh', 'bi', 'br', 'bs', 'om', 'oj', 'oc', 'os', 'or', 'xh', 'hz', 'hy', 'hr',
                'ht', 'hu', 'hi', 'ho', 'ha', 'he', 'uz', 'ur', 'uk', 'ug', 'aa', 'ab', 'ae', 'af', 'ak', 'am', 'an',
                'as', 'ar', 'av', 'ay', 'az', 'nl', 'nn', 'no', 'na', 'nb', 'nd', 'ne', 'ng', 'ny', 'nr', 'nv', 'ka',
                'kg', 'kk', 'kj', 'ki', 'ko', 'kn', 'km', 'kl', 'ks', 'kr', 'kw', 'kv', 'ku', 'ky']


    #CM - As of 2022/12/08 these are the official supported TMDB languages
    langDictTMDB = {'Abkhazian':'ab', 'Afar':'aa', 'Afrikaans':'af', 'Akan':'ak', 'Albanian':'sq',
                    'Amharic':'am', 'Arabic':'ar', 'Aragonese':'an', 'Armenian':'hy', 'Assamese':'as',
                    'Avaric':'av', 'Avestan':'ae', 'Aymara':'ay', 'Azerbaijani':'az', 'Bambara':'bm',
                    'Bashkir':'ba', 'Basque':'eu', 'Belarusian':'be', 'Bengali':'bn', 'Bislama':'bi',
                    'Bosnian':'bs', 'Breton':'br', 'Bulgarian':'bg', 'Burmese':'my', 'Cantonese':'cn',
                    'Catalan':'ca', 'Chamorro':'ch', 'Chechen':'ce', 'Chichewa Nyanja':'ny',
                    'Chuvash':'cv', 'Cornish':'kw', 'Corsican':'co', 'Cree':'cr', 'Croatian':'hr',
                    'Czech':'cs', 'Danish':'da', 'Divehi':'dv', 'Dutch':'nl', 'Dzongkha':'dz',
                    'English':'en', 'Esperanto':'eo', 'Estonian':'et', 'Ewe':'ee', 'Faroese':'fo',
                    'Fijian':'fj', 'Finnish':'fi', 'French':'fr', 'Frisian':'fy', 'Fulah':'ff',
                    'Gaelic':'gd', 'Galician':'gl', 'Ganda':'lg', 'Georgian':'ka', 'German':'de',
                    'Greek':'el', 'Guarani':'gn', 'Gujarati':'gu', 'Haitian':'ht', 'Hausa':'ha',
                    'Hebrew':'he', 'Herero':'hz', 'Hindi':'hi', 'Hiri Motu':'ho', 'Hungarian':'hu',
                    'Icelandic':'is', 'Ido':'io', 'Igbo':'ig', 'Indonesian':'id', 'Interlingua':'ia',
                    'Interlingue':'ie', 'Inuktitut':'iu', 'Inupiaq':'ik', 'Irish':'ga', 'Italian':'it',
                    'Japanese':'ja', 'Javanese':'jv', 'Kalaallisut':'kl', 'Kannada':'kn', 'Kanuri':'kr',
                    'Kashmiri':'ks', 'Kazakh':'kk', 'Khmer':'km', 'Kikuyu':'ki', 'Kinyarwanda':'rw',
                    'Kirghiz':'ky', 'Komi':'kv', 'Kongo':'kg', 'Korean':'ko', 'Kuanyama':'kj',
                    'Kurdish':'ku', 'Lao':'lo', 'Latin':'la', 'Latvian':'lv', 'Letzeburgesch':'lb',
                    'Limburgish':'li', 'Lingala':'ln', 'Lithuanian':'lt', 'Luba-Katanga':'lu',
                    'Macedonian':'mk', 'Malagasy':'mg', 'Malay':'ms', 'Malayalam':'ml', 'Maltese':'mt',
                    'Mandarin':'zh', 'Manx':'gv', 'Maori':'mi', 'Marathi':'mr', 'Marshall':'mh',
                    'Moldavian':'mo', 'Mongolian':'mn', 'Nauru':'na', 'Navajo':'nv', 'Ndebele':'nr',
                    'Ndonga':'ng', 'Nepali':'ne', 'No Language':'xx',
                    'Northern Sami':'se', 'Norwegian':'no', 'Norwegian Bokmal':'nb',
                    'Norwegian Nynorsk':'nn', 'Occitan':'oc', 'Ojibwa':'oj', 'Oriya':'or', 'Oromo':'om',
                    'Ossetian':'os', 'Pali':'pi', 'Persian':'fa', 'Polish':'pl', 'Portuguese':'pt',
                    'Punjabi':'pa', 'Pushto':'ps', 'Quechua':'qu', 'Raeto-Romance':'rm',
                    'Romanian':'ro', 'Rundi':'rn', 'Russian':'ru', 'Samoan':'sm', 'Sango':'sg',
                    'Sanskrit':'sa', 'Sardinian':'sc', 'Serbian':'sr', 'Serbo-Croatian':'sh',
                    'Shona':'sn', 'Sindhi':'sd', 'Sinhalese':'si', 'Slavic':'cu', 'Slovak':'sk',
                    'Slovenian':'sl', 'Somali':'so', 'Sotho':'st', 'Spanish':'es', 'Sundanese':'su',
                    'Swahili':'sw', 'Swati':'ss', 'Swedish':'sv', 'Tagalog':'tl', 'Tahitian':'ty',
                    'Tajik':'tg', 'Tamil':'ta', 'Tatar':'tt', 'Telugu':'te', 'Thai':'th', 'Tibetan':'bo',
                    'Tigrinya':'ti', 'Tonga':'to', 'Tsonga':'ts', 'Tswana':'tn', 'Turkish':'tr',
                    'Turkmen':'tk', 'Twi':'tw', 'Uighur':'ug', 'Ukrainian':'uk', 'Urdu':'ur',
                    'Uzbek':'uz', 'Venda':'ve', 'Vietnamese':'vi', 'Volapuk':'vo', 'Walloon':'wa',
                    'Welsh':'cy', 'Wolof':'wo', 'Xhosa':'xh', 'Yi':'ii', 'Yiddish':'yi', 'Yoruba':'yo',
                    'Zhuang':'za', 'Zulu':'zu'}

    tmdb = ['aa', 'ab', 'ae', 'af', 'ak', 'am', 'an', 'ar', 'as', 'av', 'ay', 'az', 'ba', 'be', 'bg', 'bi',
            'bm', 'bn', 'bo', 'br', 'bs', 'ca', 'ce', 'ch', 'cn', 'co', 'cr', 'cs', 'cu', 'cv', 'cy', 'da',
            'de', 'dv', 'dz', 'ee', 'el', 'en', 'eo', 'es', 'et', 'eu', 'fa', 'ff', 'fi', 'fj', 'fo', 'fr',
            'fy', 'ga', 'gd', 'gl', 'gn', 'gu', 'gv', 'ha', 'he', 'hi', 'ho', 'hr', 'ht', 'hu', 'hy', 'hz',
            'ia', 'id', 'ie', 'ig', 'ii', 'ik', 'io', 'is', 'it', 'iu', 'ja', 'jv', 'ka', 'kg', 'ki', 'kj',
            'kk', 'kl', 'km', 'kn', 'ko', 'kr', 'ks', 'ku', 'kv', 'kw', 'ky', 'la', 'lb', 'lg', 'li', 'ln',
            'lo', 'lt', 'lu', 'lv', 'mg', 'mh', 'mi', 'mk', 'ml', 'mn', 'mo', 'mr', 'ms', 'mt', 'my', 'na',
            'nb', 'nd', 'ne', 'ng', 'nl', 'nn', 'no', 'nr', 'nv', 'ny', 'oc', 'oj', 'om', 'or', 'os', 'pa',
            'pi', 'pl', 'ps', 'pt', 'qu', 'rm', 'rn', 'ro', 'ru', 'rw', 'sa', 'sc', 'sd', 'se', 'sg', 'sh',
            'si', 'sk', 'sl', 'sm', 'sn', 'so', 'sq', 'sr', 'ss', 'st', 'su', 'sv', 'sw', 'ta', 'te', 'tg',
            'th', 'ti', 'tk', 'tl', 'tn', 'to', 'tr', 'ts', 'tt', 'tw', 'ty', 'ug', 'uk', 'ur', 'uz', 've',
            'vi', 'vo', 'wa', 'wo', 'xh', 'xx', 'yi', 'yo', 'za', 'zh', 'zu']


    name = setting('api.language') or 'AUTO'

    if name[-1].isupper():
        try:
            name = xbmc.getLanguage(xbmc.ENGLISH_NAME).split(' ')[0]
        except Exception:
            pass
    try:
        name = langDict[name]
    except:
        name = 'en'

    lang = {'trakt': name} if name in trakt else {'trakt': 'en'}
    lang['tvdb'] = name if name in tvdb else 'en'
    lang['tmdb'] = name if name in tmdb else 'en'
    lang['youtube'] = name if name in youtube else 'en'

    if ret_name:
        lang['trakt'] = [i[0] for i in list(langDict.items()) if i[1] == lang['trakt']][0]
        lang['tvdb'] = [i[0] for i in list(langDict.items()) if i[1] == lang['tvdb']][0]
        lang['tmdb'] = [i[0] for i in list(langDictTMDB.items()) if i[1] == lang['tmdb']][0]
        lang['youtube'] = [i[0] for i in list(langDict.items()) if i[1] == lang['youtube']][0]

    return lang


def version():

    try:
        version = addon('xbmc.addon').getAddonInfo('version')
    except:
        version = '999'

    return int(''.join(filter(str.isdigit, version)))


def cdnImport(uri, name):

    from resources.lib.modules import client

    # Check for local XML file in addon root first
    local_xml = os.path.join(addonPath, f'{name}.xml')
    if os.path.isfile(local_xml):
        c.log(f'[cdnImport] Using local file for {name}: {local_xml}')
        # Read the local XML file
        with open(local_xml, 'r', encoding='utf-8') as f:
            r = f.read()

        # Save to persistent location
        makeFile(dataPath)
        p = os.path.join(dataPath, f'{name}.py')
        f = openFile(p, 'w')
        f.write(r)
        f.close()
        m = load_source(name, p)
        return m

    # Check for local override .py file
    # Use __file__-relative path: control.py lives in lib/resources/lib/modules/, so local_overrides is one level up
    # addonPath resolves to the *calling* addon (plugin.video.thecrew), not script.module.thecrew — so we can't use it here
    _modules_dir = os.path.dirname(os.path.abspath(__file__))
    local_override = os.path.normpath(os.path.join(_modules_dir, '..', 'local_overrides', f'{name}.py'))
    if os.path.isfile(local_override):
        c.log(f'[cdnImport] Using local override for {name}: {local_override}')
        m = load_source(name, local_override)
        return m

    # Check if already cached in addon_data (persistent)
    cached_file = os.path.join(dataPath, f'{name}.py')
    if os.path.isfile(cached_file):
        c.log(f'[cdnImport] Using cached file for {name}: {cached_file}')
        try:
            m = load_source(name, cached_file)
            return m
        except Exception as e:
            c.log(f'[cdnImport] Failed to load cached file, will re-download: {e}')
            # Delete corrupted cache and continue to download
            try:
                deleteFile(cached_file)
            except Exception:
                pass

    # Remote download from URL (fallback when no local/cached file found)
    c.log(f'[cdnImport] No local file found for {name}, attempting remote download from {uri}')
    try:
        makeFile(dataPath)
        r = client.request(uri)
        p = os.path.join(dataPath, f'{name}.py')
        f = openFile(p, 'w')
        f.write(r)
        f.close()
        m = load_source(name, p)
        c.log(f'[cdnImport] Successfully downloaded and loaded {name} from {uri}')
        return m
    except Exception as e:
        c.log(f'[cdnImport] ERROR: Failed to download {name} from {uri}: {e}')
        raise FileNotFoundError(f'No local file found for {name} and remote download failed: {e}')


def load_source(modname, filename):
    loader = importlib.machinery.SourceFileLoader(modname, filename)
    spec = importlib.util.spec_from_file_location(modname, filename, loader=loader)
    module = importlib.util.module_from_spec(spec)
    # The module is always executed and not cached in sys.modules.
    # Uncomment the following line to cache the module.
    # sys.modules[module.__name__] = module
    loader.exec_module(module)
    return module

#cm -
def openSettings(query='', addon_id=addonInfo('id')):
    """Open addon settings dialog and optionally navigate to specific tab/field.

    Args:
        query: Optional navigation string in format 'category.field' (e.g., '8.0' for category 8)
        addon_id: Addon ID to open settings for
    """
    try:
        idle()
        execute(f'Addon.OpenSettings({addon_id})')
        if query:
            c.log(f'[openSettings] Attempting to navigate to query: {query}', 1)
            parts = query.split('.')
            if len(parts) == 2:
                e, f = parts
                c.log(f'[openSettings] Category: {e}, Field: {f}', 1)
                # Control ID offsets changed in Kodi v21+
                if getKodiVersion() > 20.0:
                    control_e = int(e) - 200
                    control_f = int(f) - 180
                else:
                    control_e = int(e) - 100
                    control_f = int(f) - 80
                c.log(f'[openSettings] Kodi v{getKodiVersion()}: SetFocus({control_e}) then SetFocus({control_f})', 1)
                execute('SetFocus(%i)' % control_e)
                execute('SetFocus(%i)' % control_f)
    except Exception as ex:
        c.log(f'[openSettings] Error: {ex}', 1)




def getCurrentViewId():
    win = xbmcgui.Window(xbmcgui.getCurrentWindowId())
    return str(win.getFocusId())


def refresh():
    return execute('Container.Refresh')


def busy():
    return execute('ActivateWindow(busydialognocancel)')


def idle():
    return execute('Dialog.Close(busydialognocancel)')


def queueItem():
    return execute('Action(Queue)')


def installAddon(addon_id):
    addon_path = os.path.join(transPath('special://home/addons'), addon_id)
    if os.path.exists(addon_path) is not True:
        xbmc.executebuiltin(f'InstallAddon({addon_id})')
    else:
        infoDialog(f"{addon_id} is already installed", sound=True)