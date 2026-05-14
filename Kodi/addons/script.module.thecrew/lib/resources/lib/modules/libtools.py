# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 * @file bookmarks.py
 * @package script.module.thecrew
 *
 * @copyright 2023, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''


import sqlite3 as database

import datetime
import json
import os
import re
import sys
import traceback

from urllib.parse import parse_qsl, quote_plus
from ftplib import FTP

from . import control
from . import cleantitle
from . import sources
from .crewruntime import c

from ..indexers import movies
from ..indexers import tvshows


class lib_tools:
    @staticmethod
    def create_folder(folder):
        try:
            folder = control.legalFilename(folder)
            control.makeFile(folder)

            try:
                if 'ftp://' not in folder:
                    raise Exception()


                ftparg = re.compile(r'ftp://(.+?):(.+?)@(.+?):?(\d+)?/(.+/?)').findall(folder)
                ftp = FTP(ftparg[0][2], ftparg[0][0], ftparg[0][1])
                try:
                    ftp.cwd(ftparg[0][4])
                except Exception:
                    ftp.mkd(ftparg[0][4])
                ftp.quit()
            except Exception:
                pass
        except Exception:
            pass

    @staticmethod
    def write_file(path, content):
        try:
            path = control.legalFilename(path)
            #if not isinstance(content, six.string_types):
            #cm - version py3 fix: six.string_types == str
            if not isinstance(content, str):
                content = str(content)

            file = control.openFile(path, 'w')
            file.write(str(content))
            file.close()
        except Exception as e:
            pass

    @staticmethod
    def nfo_url(media_string, ids):
        if 'imdb' in ids:
            return f'https://www.imdb.com/title/{str(ids["imdb"])}'
        elif 'tmdb' in ids:
            return f'https://www.themoviedb.org/{media_string}/{str(ids["tmdb"])}' % (media_string, str(ids['tmdb']))
        elif 'tvdb' in ids:
            return f'https://thetvdb.com/?tab=series&id={str(ids["tvdb"])}'
        else:
            return ''

    @staticmethod
    def check_sources(title, year, imdb, tmdb=None, season=None, episode=None, tvshowtitle=None, premiered=None):
        try:
            src = sources.Sources().getSources(title, year, imdb, tmdb, season, episode, tvshowtitle, premiered)
            return src and len(src) > 5
        except Exception:
            return False

    @staticmethod
    def legal_filename(filename):
        try:
            filename = filename.strip()
            filename = re.sub(r'(?!%s)[^\w\-_\.]', '.', filename)
            filename = re.sub(r'\.+', '.', filename)
            filename = re.sub(re.compile(r'(CON|PRN|AUX|NUL|COM\d|LPT\d)\.', re.I), '\\1_', filename)
            control.legalFilename(filename)
            return filename
        except Exception:
            return filename

    @staticmethod
    def make_path(base_path, title, year='', season=''):
        """
        This function generates a file path for a TV show. It takes a base path, title, year,
        and season as input, and returns a path in the format base_path/title (year)/Season season.
        The title is sanitized to replace special characters with underscores.

        Args:
            base_path (_type_): _description_
            title (_type_): _description_
            year (str, optional): _description_. Defaults to ''.
            season (str, optional): _description_. Defaults to ''.

        Returns:
            _type_: _description_
        """
        show_folder = re.sub(r'[^\w\-_\. ]', '_', title)
        show_folder = f'{show_folder} ({year})' if year else show_folder
        path = os.path.join(base_path, show_folder)
        if season:
            path = os.path.join(path, f'Season {season}')
        return path

    @staticmethod
    def setup_library_sources():
        """
        Automatically adds The Crew library folders to Kodi's video sources.
        This sets up both Movies and TV Shows folders with proper content types.
        """
        try:
            import xml.etree.ElementTree as ET

            # Get paths
            movies_path = c.transpath(c.get_setting('library.movie'))
            tv_path = c.transpath(c.get_setting('library.tv'))
            sources_file = c.transpath('special://userdata/sources.xml')

            c.log(f'[LibTools] Setting up library sources: Movies={movies_path}, TV={tv_path}')

            # Create folders if they don't exist
            lib_tools.create_folder(movies_path)
            lib_tools.create_folder(tv_path)

            # Read or create sources.xml
            try:
                tree = ET.parse(sources_file)
                root = tree.getroot()
            except Exception:
                c.log('[LibTools] Creating new sources.xml')
                root = ET.Element('sources')
                tree = ET.ElementTree(root)

            # Get or create video section
            video = root.find('video')
            if video is None:
                video = ET.SubElement(root, 'video')
                default = ET.SubElement(video, 'default')
                default.set('pathversion', '1')

            # Check if sources already exist
            existing_paths = [s.find('path').text for s in video.findall('source') if s.find('path') is not None]

            # Add Movies source if not exists
            if movies_path not in existing_paths:
                c.log(f'[LibTools] Adding Movies source: {movies_path}')
                source = ET.SubElement(video, 'source')
                name = ET.SubElement(source, 'name')
                name.text = 'The Crew Movies'
                path = ET.SubElement(source, 'path')
                path.set('pathversion', '1')
                path.text = movies_path
                allowsharing = ET.SubElement(source, 'allowsharing')
                allowsharing.text = 'true'

            # Add TV Shows source if not exists
            if tv_path not in existing_paths:
                c.log(f'[LibTools] Adding TV Shows source: {tv_path}')
                source = ET.SubElement(video, 'source')
                name = ET.SubElement(source, 'name')
                name.text = 'The Crew TV Shows'
                path = ET.SubElement(source, 'path')
                path.set('pathversion', '1')
                path.text = tv_path
                allowsharing = ET.SubElement(source, 'allowsharing')
                allowsharing.text = 'true'

            # Write sources.xml
            tree.write(sources_file, encoding='utf-8', xml_declaration=True)
            c.log('[LibTools] sources.xml updated successfully')

            # Now set content types in Kodi database
            try:
                # Set Movies folder content type
                control.jsonrpc(json.dumps({
                    'jsonrpc': '2.0',
                    'method': 'Files.SetFileDetails',
                    'params': {
                        'file': movies_path,
                        'media': 'video'
                    },
                    'id': 1
                }))

                # Set TV Shows folder content type
                control.jsonrpc(json.dumps({
                    'jsonrpc': '2.0',
                    'method': 'Files.SetFileDetails',
                    'params': {
                        'file': tv_path,
                        'media': 'video'
                    },
                    'id': 1
                }))
            except Exception as e:
                c.log(f'[LibTools] Could not set content types via JSON-RPC: {e}')

            # Notify user
            c.infoDialog('Library sources added! Please go to:\nSettings > Media > Library > Videos\nand set content types for:\n"The Crew Movies" (Movies)\n"The Crew TV Shows" (TV Shows)', time=8000)

            return True

        except Exception as e:
            c.log(f'[LibTools] Failed to setup library sources: {e}')
            c.infoDialog('Failed to setup library sources. Please add manually.', time=5000)
            return False

#TC 2/01/19 started
#CM 2/26/26 was here ;)
class libmovies:
    def __init__(self):
        self.library_folder = os.path.join(c.transpath(c.get_setting('library.movie')), '')

        self.check_setting = c.get_setting('library.check_movie') or 'false'
        self.library_setting = c.get_setting('library.update') or 'true'
        self.dupe_setting = c.get_setting('library.check') or 'true'
        self.silentDialog = False
        self.infoDialog = False


    def add(self, name, title, year, imdb, _range=False):
        if not control.condVisibility('Window.IsVisible(infodialog)')\
                and not control.condVisibility('Player.HasVideo')\
                and self.silentDialog is False:
            c.infoDialog(c.lang(32552), time=10000000)
            self.infoDialog = True

        try:
            if self.dupe_setting != 'true':
                raise Exception()


            lib = control.jsonrpc('{"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies", "params": {"filter":{"or": [{"field": "year", "operator": "is", "value": "%s"}, {"field": "year", "operator": "is", "value": "%s"}, {"field": "year", "operator": "is", "value": "%s"}]}, "properties" : ["imdbnumber", "originaltitle", "year"]}, "id": 1}' % (year, str(int(year)+1), str(int(year)-1)))
            lib = c.to_str(lib, errors='ignore')
            lib_result = json.loads(lib).get('result', {})
            if 'movies' not in lib_result or not lib_result['movies']:
                lib = []
            else:
                lib = lib_result['movies']
                lib = [i for i in lib if str(i['imdbnumber']) in imdb or (str(i['title']) == title and str(i['year']) == year)]
                lib = lib[0] if lib else []
        except Exception as e:
            lib = []

        files_added = 0

        try:
            if lib != []:
                raise Exception()

            if self.check_setting == 'true':
                src = lib_tools.check_sources(title, year, imdb, None, None, None, None, None)
                if not src:
                    raise Exception()

            self.strmFile({'name': name, 'title': title, 'year': year, 'imdb': imdb})
            files_added += 1
        except Exception as e:
            pass

        if _range is True:
            return

        if self.infoDialog is True:
            c.infoDialog(c.lang(32554), time=1)

        if self.library_setting == 'true' and not\
            control.condVisibility('Library.IsScanningVideo') and\
            files_added > 0:
            control.execute('UpdateLibrary(video)')
    def add_movie(self, name: str, title: str, year: int, imdb_id: str, add_range: bool = False) -> None:
        """
        Adds a movie to the user's library.

        Args:
            name (str): The name of the movie.
            title (str): The title of the movie.
            year (int): The year of the movie.
            imdb_id (str): The IMDB ID of the movie.
            add_range (bool, optional): Whether to add a range of years or not. Defaults to False.
        """
        # Show a dialog if the user is not watching a video and the silent dialog setting is off
        if not control.condVisibility('Window.IsVisible(infodialog)') and not control.condVisibility('Player.HasVideo') and not self.silentDialog:
            c.infoDialog(c.lang(32552), time=10000000)
            self.infoDialog = True

        try:
            # Check if the movie is already in the user's library
            if self.dupe_setting != 'true':
                raise Exception

            lib = control.jsonrpc(
                '{"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies", "params": {"filter":{"or": [{"field": "year", "operator": "is", "value": "%s"}, {"field": "year", "operator": "is", "value": "%s"}, {"field": "year", "operator": "is", "value": "%s"}]}, "properties" : ["imdbnumber", "originaltitle", "year"]}, "id": 1}' % (year, str(int(year)+1), str(int(year)-1))
            )
            lib = c.to_str(lib, errors='ignore')
            lib_result = json.loads(lib).get('result', {})
            if 'movies' not in lib_result or not lib_result['movies']:
                lib = []
            else:
                lib = lib_result['movies']
                lib = [i for i in lib if str(i['imdbnumber']) in imdb_id or (str(i['title']) == title and str(i['year']) == year)]
                lib = lib[0] if lib else []
        except Exception:
            lib = []

        files_added = 0

        try:
            # Add the movie to the user's library
            if lib != []:
                raise Exception

            if self.check_setting == 'true':
                src = lib_tools.check_sources(title, year, imdb_id, None, None, None, None, None)
                if not src:
                    raise Exception

            self.strmFile({'name': name, 'title': title, 'year': year, 'imdb': imdb_id})
            files_added += 1
        except Exception:
            pass

        if add_range is True:
            return

        # Hide the dialog if it was shown
        if self.infoDialog is True:
            c.infoDialog(c.lang(32554), time=1)

        # Update the user's library if the library setting is on and the library is not already being updated
        if self.library_setting == 'true' and not control.condVisibility('Library.IsScanningVideo') and files_added > 0:
            control.execute('UpdateLibrary(video)')




    def add_backup(self, name, title, year, imdb, _range=False):
        if not control.condVisibility('Window.IsVisible(infodialog)')\
                and not control.condVisibility('Player.HasVideo')\
                and self.silentDialog is False:
            c.infoDialog(c.lang(32552), time=10000000)
            self.infoDialog = True

        try:
            if self.dupe_setting != 'true':
                raise Exception()


            lib = control.jsonrpc('{"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies", "params": {"filter":{"or": [{"field": "year", "operator": "is", "value": "%s"}, {"field": "year", "operator": "is", "value": "%s"}, {"field": "year", "operator": "is", "value": "%s"}]}, "properties" : ["imdbnumber", "originaltitle", "year"]}, "id": 1}' % (year, str(int(year)+1), str(int(year)-1)))
            lib = c.to_str(lib, errors='ignore')
            lib_result = json.loads(lib).get('result', {})
            if 'movies' not in lib_result or not lib_result['movies']:
                lib = []
            else:
                lib = lib_result['movies']
                lib = [i for i in lib if str(i['imdbnumber']) in imdb or (str(i['title']) == title and str(i['year']) == year)]
                lib = lib[0] if lib else []
        except Exception as e:
            lib = []

        files_added = 0

        try:
            if lib != []:
                raise Exception()

            if self.check_setting == 'true':
                src = lib_tools.check_sources(title, year, imdb, None, None, None, None, None)
                if not src:
                    raise Exception()

            self.strmFile({'name': name, 'title': title, 'year': year, 'imdb': imdb})
            files_added += 1
        except Exception as e:
            pass

        if _range is True:
            return

        if self.infoDialog is True:
            c.infoDialog(c.lang(32554), time=1)

        if self.library_setting == 'true' and not control.condVisibility('Library.IsScanningVideo') and files_added > 0:
            control.execute('UpdateLibrary(video)')






    def silent(self, url):
        control.idle()

        if not control.condVisibility('Window.IsVisible(infodialog)') and\
            not control.condVisibility('Player.HasVideo'):
            c.infoDialog(c.lang(32552), time=10000000)
            self.infoDialog = True
            self.silentDialog = True

        c.log(f'[LibTools] Movie silent import starting with url={url}')
        items = movies.Movies().get(url, idx=False, create_directory=False) or []

        c.log(f'[LibTools] Movie silent got {len(items)} items from Trakt')

        for i in items:
            try:
                if control.monitor.abortRequested():
                    return sys.exit()
                title = i['title']
                year = i['year']
                c.log(f'[LibTools] Adding movie: {title} ({year})')
                self.add(f'{title} ({year})', title, year, i['imdb'], _range=True)
            except Exception as e:
                c.log(f'[LibTools] Failed to add movie: {e}')
                pass

        if self.infoDialog is True:
            self.silentDialog = False
            c.infoDialog(f"Trakt Movies Sync Complete - Added {len(items)} movies", time=3000)

        if self.library_setting == 'true' and not control.condVisibility('Library.IsScanningVideo') and len(items) > 0:
            control.execute('UpdateLibrary(video)')

    def range(self, url):
        control.idle()

        yes = control.yesnoDialog(c.lang(32056))
        if not yes:
            return

        if not control.condVisibility('Window.IsVisible(infodialog)') and\
            not control.condVisibility('Player.HasVideo'):
            c.infoDialog(c.lang(32552), time=10000000)
            self.infoDialog = True

        items = movies.Movies().get(url, idx=False, create_directory=False)
        if items is None:
            items = []

        for i in items:
            try:
                #if control.monitor.abortRequested(): return sys.exit()
                self.add(f"{i['title']} ({i['year']})", i['title'], i['year'], i['imdb'], _range=True)
            except Exception:
                pass

        if self.infoDialog is True:
            c.infoDialog(c.lang(32554), time=1)

        if self.library_setting == 'true' and not control.condVisibility('Library.IsScanningVideo'):
            control.execute('UpdateLibrary(video)')


    def strmFile(self, i):
        try:
            name, title, year, imdb = i['name'], i['title'], i['year'], i['imdb']

            sysname, systitle = quote_plus(name), quote_plus(title)

            try:
                transtitle = title.translate(None, r'\/:*?"<>|')
            except Exception:
                transtitle = title.translate(str.maketrans('', '', r'\/:*?"<>|'))
            transtitle = cleantitle.normalize(transtitle)

            content = '%s?action=play&name=%s&title=%s&year=%s&imdb=%s' % (sys.argv[0], sysname, systitle, year, imdb)

            folder = lib_tools.make_path(self.library_folder, transtitle, year)

            lib_tools.create_folder(folder)
            lib_tools.write_file(os.path.join(folder, lib_tools.legal_filename(transtitle) + '.' + year + '.strm'), content)
            lib_tools.write_file(os.path.join(folder, lib_tools.legal_filename(transtitle) + '.' + year + '.nfo'), lib_tools.nfo_url('movie', i))
        except Exception:
            pass


class libtvshows:
    def __init__(self):
        self.library_folder = os.path.join(c.transpath(c.get_setting('library.tv')),'')

        self.version = c.pluginversion
        self.check_setting = c.get_setting('library.check_episode') or 'false'
        self.include_unknown = c.get_setting('library.include_unknown') or 'true'
        self.library_setting = c.get_setting('library.update') or 'true'
        self.dupe_setting = c.get_setting('library.check') or 'true'

        self.datetime = datetime.datetime.now()
        if c.get_setting('library.importdelay') != 'true':
            self.date = self.datetime.strftime('%Y%m%d')
        else:
            self.date = (self.datetime - datetime.timedelta(hours=24)).strftime('%Y%m%d')
        self.silentDialog = False
        self.infoDialog = False
        self.block = False


    def add(self, tvshowtitle, year, imdb, tmdb, _range=False):
        try:
            if not control.condVisibility('Window.IsVisible(infodialog)') and not control.condVisibility('Player.HasVideo')\
                    and self.silentDialog is False:
                c.infoDialog(c.lang(32552), time=100) # Adding to library...
                self.infoDialog = True


            from lib.resources.lib.indexers import episodes
            seasons = episodes.Seasons().get(tvshowtitle, year, imdb, tmdb, meta=None, idx=False, create_directory=False)
            if not seasons:
                c.log(f'[LibTools] No seasons found for {tvshowtitle}')
                return
            seasons = [i['season'] for i in seasons]
            c.log(f'[LibTools] Processing {len(seasons)} seasons for {tvshowtitle}')
            for s in seasons:
                c.log(f'[LibTools] Fetching episodes for {tvshowtitle} season {s}')
                items = episodes.Episodes().get(tvshowtitle, year, imdb, tmdb, meta=None, season=s, create_directory=False)
                if not items:
                    c.log(f'[LibTools] No episodes found for {tvshowtitle} season {s}')
                    continue

                c.log(f'[LibTools] Got {len(items)} episodes for {tvshowtitle} season {s}')

                try:
                    items = [{
                        'title': i['title'],
                        'year': i['year'],
                        'imdb': i['imdb'],
                        'tvdb': i['tvdb'],
                        'tmdb': i['tmdb'],
                        'season': i['season'],
                        'episode': i['episode'],
                        'tvshowtitle': i['tvshowtitle'],
                        'premiered': i['premiered']
                        } for i in items]
                except Exception:
                    items = []

                try:
                    if self.dupe_setting != 'true':
                        raise Exception()
                    if items == []:
                        raise Exception('items is empty')

                    _id = [items[0]['imdb'], items[0]['tmdb']]

                    lib = control.jsonrpc('{"jsonrpc": "2.0", "method": "VideoLibrary.GetTVShows", "params": {"properties" : ["imdbnumber", "title", "year"]}, "id": 1}')
                    lib = c.to_str(lib, errors='ignore')
                    lib_result = json.loads(lib).get('result', {})
                    if 'tvshows' not in lib_result or not lib_result['tvshows']:
                        raise Exception('No TV shows in library')
                    lib = lib_result['tvshows']
                    lib = [str(i['title']) for i in lib if str(i['imdbnumber']) in _id or (str(i['title']) == items[0]['tvshowtitle'] and str(i['year']) == items[0]['year'])]

                    # Only query episodes if show exists in library
                    if not lib:
                        raise Exception('Show not in library')

                    show_title = lib[0]  # Get first matching show title
                    lib = control.jsonrpc('{"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes", "params": {"filter":{"and": [{"field": "tvshow", "operator": "is", "value": "%s"}]}, "properties": ["season", "episode"]}, "id": 1}' % show_title)
                    lib = c.to_str(lib, errors='ignore')
                    lib = json.loads(lib).get('result', {}).get('episodes', [])
                    lib = ['S%02dE%02d' % (int(i['season']), int(i['episode'])) for i in lib]

                    original_count = len(items)
                    items = [i for i in items if 'S%02dE%02d' % (int(i['season']), int(i['episode'])) not in lib]
                    filtered_count = original_count - len(items)

                    if filtered_count > 0:
                        c.log(f"[LibTools] Filtered out {filtered_count} episodes already in library, {len(items)} new episodes to add")

                except Exception as e:
                    c.log(f"[LibTools] Exception during episode processing: {type(e).__name__}: {str(e)}")
                    c.log(f"[LibTools] Continuing to file creation for all episodes")


                files_added = 0

                c.log(f"[LibTools] About to create .strm files for {len(items)} episodes of {tvshowtitle} season {s}")
                for i in items:
                    try:
                        if control.monitor.abortRequested():
                            return sys.exit()

                        if self.check_setting == 'true':
                            if i['episode'] == '1':
                                self.block = True
                                src = lib_tools.check_sources(i['title'], i['year'], i['imdb'], i['tmdb'], i['season'], i['episode'], i['tvshowtitle'], i['premiered'])
                                if src:
                                    self.block = False
                            if self.block is True:
                                raise Exception()

                        premiered = i.get('premiered', '0')
                        if (premiered != '0' and int(re.sub('[^0-9]', '', str(premiered))) > int(self.date)) or (premiered == '0' and not self.include_unknown):
                            c.log(f"[LibTools] Skipping {tvshowtitle} S{i['season']}E{i['episode']} - premiered={premiered}, date={self.date}")
                            continue

                        c.log(f"[LibTools] Creating .strm for {tvshowtitle} S{i['season']}E{i['episode']}")
                        self.strmFile(i)
                        files_added += 1
                    except Exception:
                        pass

            c.log(f"[LibTools] Created {files_added} .strm files for {tvshowtitle}, _range={_range}")
            # cm - because running silent has range true, no lib update.
            # Lib is never control-executed even without the bool-checks, need to find out why
            if _range is True:
                return

            if self.infoDialog is True:
                c.infoDialog(c.lang(32554), time=1) # Process Complete

            # TEMP DISABLED FOR TESTING - avoid scanning entire collection
            # if self.library_setting == 'true' and not control.condVisibility('Library.IsScanningVideo') and files_added > 0:
            #     control.execute('UpdateLibrary(video)')
            c.log(f"[LibTools] Skipping library update - disabled for testing")

        except Exception as e:
            c.log(f"[LibTools] CRITICAL EXCEPTION in libtvshows.add(): {e}")
            import traceback

    def silent(self, url):
        control.idle()

        if not control.condVisibility('Window.IsVisible(infodialog)') and not control.condVisibility('Player.HasVideo'):
            c.infoDialog(c.lang(32608), time=10000000)
            self.infoDialog = True
            self.silentDialog = True

        c.log(f'[LibTools] TV silent import starting with url={url}')
        items = tvshows.TVShows().get(url, create_directory=False)

        if items is None:
            items = []

        c.log(f'[LibTools] TV silent got {len(items)} items from Trakt')

        for i in items:
            try:
                if control.monitor.abortRequested():
                    return sys.exit()
                c.log(f"[LibTools] Adding TV show: {i.get('title', 'Unknown')} ({i.get('year', '?')})")
                self.add(i['title'], i['year'], i['imdb'], i['tmdb'], _range=True)
            except Exception as e:
                c.log(f'[LibTools] Failed to add TV show: {e}')
                pass

        if self.infoDialog is True:
            self.silentDialog = False
            c.infoDialog(f"Trakt TV Show Sync Complete - Added {len(items)} shows", time=3000)

        if self.library_setting == 'true' and not control.condVisibility('Library.IsScanningVideo') and len(items) > 0:
            control.execute('UpdateLibrary(video)')

    def range(self, url):
        control.idle()

        yes = control.yesnoDialog(c.lang(32056))
        if not yes:
            return

        if not control.condVisibility('Window.IsVisible(infodialog)') and not control.condVisibility('Player.HasVideo'):
            c.infoDialog(c.lang(32552), time=10000000)
            self.infoDialog = True


        items = tvshows.TVShows().get(url, create_directory=False)
        if items is None:
            items = []

        for i in items:
            try:
                #if control.monitor.abortRequested(): return sys.exit()
                self.add(i['title'], i['year'], i['imdb'], i['tmdb'], _range=True)
            except Exception:
                pass

        if self.infoDialog is True:
            c.infoDialog(c.lang(32554), time=1)

        if self.library_setting == 'true' and not control.condVisibility('Library.IsScanningVideo'):
            control.execute('UpdateLibrary(video)')

    def strmFile(self, i):
        try:
            title, year, imdb, tmdb, season, episode, tvshowtitle, premiered = i['title'], i['year'], i['imdb'], i['tmdb'], i['season'], i['episode'], i['tvshowtitle'], i['premiered']

            _episodetitle = quote_plus(cleantitle.normalize(title))
            _tvshowtitle, _premiered = quote_plus(cleantitle.normalize(tvshowtitle)), quote_plus(premiered)

            try:
                transtitle = tvshowtitle.translate(None, r'\/:*?"<>|')
            except Exception:
                transtitle = tvshowtitle.translate(str.maketrans('', '', r'\/:*?"<>|'))
            _transtitle = cleantitle.normalize(transtitle)

            #cm - 2.0.6 changed from play1
            content = '%s?action=play&title=%s&year=%s&imdb=%s&tmdb=%s&season=%s&episode=%s&tvshowtitle=%s&date=%s' % (sys.argv[0], _episodetitle, year, imdb, tmdb, season, episode, _tvshowtitle, _premiered)

            folder = lib_tools.make_path(self.library_folder, _transtitle, year)
            if not os.path.isfile(os.path.join(folder, 'tvshow.nfo')):
                lib_tools.create_folder(folder)
                lib_tools.write_file(os.path.join(folder, 'tvshow.nfo'), lib_tools.nfo_url('tv', i))

            folder = lib_tools.make_path(self.library_folder, _transtitle, year, season)
            lib_tools.create_folder(folder)
            lib_tools.write_file(os.path.join(folder, lib_tools.legal_filename('%s S%02dE%02d' % (_transtitle, int(season), int(episode))) + '.strm'), content)
        except Exception:
            pass


class libepisodes:
    def __init__(self):
        self.library_folder = os.path.join(c.transpath(c.get_setting('library.tv')),'')

        self.library_setting = c.get_setting('library.update') or 'true'
        self.include_unknown = c.get_setting('library.include_unknown') or 'true'
        self.property = '%s_service_property' % control.addonInfo('name').lower()

        self.datetime = datetime.datetime.utcnow()
        if c.get_setting('library.importdelay') != 'true':
            self.date = self.datetime.strftime('%Y%m%d')
        else:
            self.date = (self.datetime - datetime.timedelta(hours=24)).strftime('%Y%m%d')

        self.infoDialog = False


    def update(self, query=None, info='true'):
        if query is not None:
            control.idle()

        # Gather TV show items from .strm files in the library folder
        items = []
        try:
            season, episode = [], []
            show = [os.path.join(self.library_folder, i) for i in control.listDir(self.library_folder)[0]]
            for s in show:
                try:
                    season += [os.path.join(s, i) for i in control.listDir(s)[0]]
                except FileNotFoundError:
                    pass
            for s in season:
                try:
                    episode.append([os.path.join(s, i) for i in control.listDir(s)[1] if i.endswith('.strm')][-1])
                except (OSError, IndexError):
                    pass
            for file in episode:
                try:
                    f = control.openFile(file)
                    read = c.to_str(f.read())
                    f.close()
                    if not read.startswith(sys.argv[0]):
                        continue
                    params = dict(parse_qsl(read.replace('?', '')))
                    tvshowtitle = params.get('tvshowtitle') or params.get('show')
                    if not tvshowtitle:
                        continue
                    imdb = 'tt' + re.sub('[^0-9]', '', str(params['imdb']))
                    items.append({'tvshowtitle': tvshowtitle, 'year': params['year'], 'imdb': imdb, 'tmdb': params.get('tmdb', '0')})
                except Exception:
                    pass
            items = [i for x, i in enumerate(items) if i not in items[x + 1:]]
        except Exception:
            pass

        if not items:
            return

        # Get current Kodi TV library to find the last watched episode per show
        try:
            lib_raw = control.jsonrpc('{"jsonrpc": "2.0", "method": "VideoLibrary.GetTVShows", "params": {"properties": ["imdbnumber", "title", "year"]}, "id": 1}')
            lib = json.loads(c.to_str(lib_raw, errors='ignore')).get('result', {}).get('tvshows', [])
        except Exception:
            lib = []

        if info == 'true' and not control.condVisibility('Window.IsVisible(infodialog)') and not control.condVisibility('Player.HasVideo'):
            c.infoDialog(c.lang(32553), time=10000000)
            self.infoDialog = True

        try:
            control.makeFile(control.dataPath)
            dbcon = database.connect(control.libcacheFile)
            dbcur = dbcon.cursor()

            dbcur.execute(
                "CREATE TABLE IF NOT EXISTS tvshows ("
                "id TEXT PRIMARY KEY, "
                "items TEXT, "
                "last_season_check TEXT, "
                "season_count INTEGER, "
                "status TEXT"
                ");"
            )

            # Migrate old schema: add missing columns if needed
            try:
                dbcur.execute("SELECT last_season_check FROM tvshows LIMIT 1")
            except Exception:
                c.log('[LibTools] Migrating tvshows table schema to support season tracking')
                for col_def in [
                    "last_season_check TEXT DEFAULT '1970-01-01'",
                    "season_count INTEGER DEFAULT 0",
                    "status TEXT DEFAULT ''",
                ]:
                    try:
                        dbcur.execute(f"ALTER TABLE tvshows ADD COLUMN {col_def}")
                    except Exception:
                        pass
                dbcon.commit()

        except Exception as e:
            c.log(f'[LibTools] Error creating tvshows table: {e}', 1)
            if self.infoDialog:
                c.infoDialog(c.lang(32554), time=1)
                self.infoDialog = False
            return

        try:
            from lib.resources.lib.indexers import episodes
        except Exception:
            if self.infoDialog:
                c.infoDialog(c.lang(32554), time=1)
                self.infoDialog = False
            return

        files_added = 0
        self.datetime = datetime.datetime.utcnow()
        if c.get_setting('library.importdelay') != 'true':
            self.date = self.datetime.strftime('%Y%m%d')
        else:
            self.date = (self.datetime - datetime.timedelta(hours=24)).strftime('%Y%m%d')

        for item in items:
            it = None
            cached_status = ''
            cached_season_count = 0
            cached_last_check = '1970-01-01'
            force_season_refresh = False

            if control.monitor.abortRequested():
                if self.infoDialog:
                    c.infoDialog(c.lang(32554), time=1)
                    self.infoDialog = False
                return sys.exit()

            try:
                dbcur.execute(
                    "SELECT items, last_season_check, season_count, status FROM tvshows WHERE id = ?",
                    (item['imdb'],)
                )
                fetch = dbcur.fetchone()
                if fetch:
                    it = json.loads(c.to_str(fetch[0]))
                    cached_last_check = fetch[1] or '1970-01-01'
                    cached_season_count = fetch[2] or 0
                    cached_status = fetch[3] or ''
                    if cached_status.lower() in ['continuing', 'returning series']:
                        try:
                            last_check_date = datetime.datetime.strptime(cached_last_check, '%Y-%m-%d')
                            days_since_check = (self.datetime - last_check_date).days
                            if days_since_check > 3:
                                force_season_refresh = True
                                c.log(f'[LibTools] {item["tvshowtitle"]}: {days_since_check} days since last season check, refreshing')
                        except Exception as e:
                            c.log(f'[LibTools] Error parsing last_season_check date: {e}', 1)
                            force_season_refresh = True
            except Exception as e:
                c.log(f'[LibTools] Cache lookup error for {item.get("tvshowtitle")}: {e}', 1)

            if it is None or force_season_refresh:
                try:
                    seasons = episodes.Seasons().get(item['tvshowtitle'], item['year'], item['imdb'], item['tmdb'], meta=None, idx=False, create_directory=False)
                    if not seasons:
                        c.log(f'[LibTools] No seasons found for {item["tvshowtitle"]}')
                        continue
                    current_season_count = len(seasons)
                    current_status = seasons[0]['status'].lower() if seasons else ''
                    season_numbers = [i['season'] for i in seasons]

                    if force_season_refresh and it is not None:
                        c.log(f'[LibTools] {item["tvshowtitle"]}: Cached {cached_season_count} seasons, found {current_season_count} seasons')
                        if current_season_count > cached_season_count:
                            new_season_numbers = season_numbers[cached_season_count:]
                            c.log(f'[LibTools] {item["tvshowtitle"]}: New seasons detected: {new_season_numbers}')
                            new_episodes = []
                            for s in new_season_numbers:
                                eps = episodes.Episodes().get(
                                    item['tvshowtitle'], item['year'], item['imdb'], item['tmdb'],
                                    meta=None, season=s, create_directory=False
                                )
                                if eps:
                                    new_episodes.extend([{
                                        'title': i['title'], 'year': i['year'], 'imdb': i['imdb'],
                                        'tmdb': i['tmdb'], 'season': i['season'], 'episode': i['episode'],
                                        'tvshowtitle': i['tvshowtitle'], 'premiered': i['premiered']
                                    } for i in eps])
                            it.extend(new_episodes)
                            c.log(f'[LibTools] {item["tvshowtitle"]}: Added {len(new_episodes)} new episodes from {len(new_season_numbers)} new season(s)')
                            self._notify_new_seasons(item["tvshowtitle"], new_season_numbers)
                        else:
                            c.log(f'[LibTools] {item["tvshowtitle"]}: No new seasons (still {current_season_count})')
                        dbcur.execute(
                            "UPDATE tvshows SET items = ?, last_season_check = ?, season_count = ?, status = ? WHERE id = ?",
                            (json.dumps(it), self.datetime.strftime('%Y-%m-%d'), current_season_count, current_status, item['imdb'])
                        )
                        dbcon.commit()

                    else:
                        it = []
                        for s in season_numbers:
                            eps = episodes.Episodes().get(
                                item['tvshowtitle'], item['year'], item['imdb'], item['tmdb'],
                                meta=None, season=s, create_directory=False
                            )
                            if eps:
                                it.extend([{
                                    'title': i['title'], 'year': i['year'], 'imdb': i['imdb'],
                                    'tmdb': i['tmdb'], 'season': i['season'], 'episode': i['episode'],
                                    'tvshowtitle': i['tvshowtitle'], 'premiered': i['premiered']
                                } for i in eps])
                        c.log(f'[LibTools] {item["tvshowtitle"]}: Fetched {len(it)} episodes from {current_season_count} season(s), status={current_status}')
                        if current_status not in ['continuing', 'returning series']:
                            dbcur.execute("INSERT OR REPLACE INTO tvshows (id, items, last_season_check, season_count, status) VALUES (?, ?, ?, ?, ?)",
                                        (item['imdb'], json.dumps(it), '1970-01-01', current_season_count, current_status))
                        else:
                            dbcur.execute("INSERT OR REPLACE INTO tvshows (id, items, last_season_check, season_count, status) VALUES (?, ?, ?, ?, ?)",
                                        (item['imdb'], json.dumps(it), self.datetime.strftime('%Y-%m-%d'), current_season_count, current_status))
                        dbcon.commit()

                except Exception as e:
                    c.log(f'[LibTools] Error processing {item.get("tvshowtitle")}: {e}', 1)
                    continue

            if not it:
                continue

            try:
                show_id = [item['imdb'], item['tmdb']]
                ep = [c.to_str(x['title']) for x in lib if str(x['imdbnumber']) in show_id or (c.to_str(x['title']) == item['tvshowtitle'] and str(x['year']) == item['year'])][0]
                ep = control.jsonrpc('{"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes", "params": {"filter":{"and": [{"field": "tvshow", "operator": "is", "value": "%s"}]}, "properties": ["season", "episode"]}, "id": 1}' % ep)
                ep = json.loads(ep).get('result', {}).get('episodes', {})
                ep = [{'season': int(i['season']), 'episode': int(i['episode'])} for i in ep]
                ep = sorted(ep, key=lambda x: (x['season'], x['episode']))[-1]
                num = [x for x, y in enumerate(it) if str(y['season']) == str(ep['season']) and str(y['episode']) == str(ep['episode'])][-1]
                it = [y for x, y in enumerate(it) if x > num]
                if not it:
                    continue
            except Exception:
                continue

            for i in it:
                try:
                    if control.monitor.abortRequested():
                        if self.infoDialog:
                            c.infoDialog(c.lang(32554), time=1)
                            self.infoDialog = False
                        return sys.exit()
                    premiered = i.get('premiered', '0')
                    if (premiered != '0' and int(re.sub('[^0-9]', '', str(premiered))) > int(self.date)) or (premiered == '0' and not self.include_unknown):
                        continue
                    libtvshows().strmFile(i)
                    files_added += 1
                except Exception:
                    pass

        if self.infoDialog:
            c.infoDialog(c.lang(32554), time=1)

        if self.library_setting == 'true' and not control.condVisibility('Library.IsScanningVideo') and files_added > 0:
            control.execute('UpdateLibrary(video)')


    def _notify_new_seasons(self, tvshowtitle, new_season_numbers):
        try:
            season_text = "season" if len(new_season_numbers) == 1 else "seasons"
            c.infoDialog(
                f'{tvshowtitle}: New {season_text} {", ".join(map(str, new_season_numbers))} added',
                heading='The Crew - Library Update',
                icon=c.addon_icon(),
                time=5000,
                sound=False
            )
        except Exception:
            pass

    def service(self):
        try:
            lib_tools.create_folder(os.path.join(c.transpath(c.get_setting('library.movie')), ''))
            lib_tools.create_folder(os.path.join(c.transpath(c.get_setting('library.tv')), ''))
        except Exception:
            pass

        try:
            control.makeFile(control.dataPath)
            dbcon = database.connect(control.libcacheFile)
            dbcur = dbcon.cursor()
            dbcur.execute("CREATE TABLE IF NOT EXISTS service (""setting TEXT, ""value TEXT, ""UNIQUE(setting)"");")
            dbcur.execute("SELECT * FROM service WHERE setting = 'last_run'")
            fetch = dbcur.fetchone()
            if fetch is None:
                serviceProperty = "1970-01-01 23:59:00.000000"
                dbcur.execute("INSERT INTO service Values (?, ?)", ('last_run', serviceProperty))
                dbcon.commit()
            else:
                serviceProperty = str(fetch[1])
            dbcon.close()
        except Exception:
            try:
                return dbcon.close()
            except Exception:
                return

        try:
            pass

            control.window.setProperty(self.property, serviceProperty)
        except Exception:
            return

        while not control.monitor.abortRequested():
            try:
                serviceProperty = control.window.getProperty(self.property)

                t1 = datetime.timedelta(hours=6)
                t2 = datetime.datetime.strptime(serviceProperty, '%Y-%m-%d %H:%M:%S.%f')
                t3 = datetime.datetime.now()

                check = abs(t3 - t2) > t1
                if check is False:
                    raise Exception()

                if (control.player.isPlaying() or control.condVisibility('Library.IsScanningVideo')):
                    raise Exception()

                serviceProperty = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')

                control.window.setProperty(self.property, serviceProperty)

                try:
                    dbcon = database.connect(control.libcacheFile)
                    dbcur = dbcon.cursor()
                    dbcur.execute("CREATE TABLE IF NOT EXISTS service (""setting TEXT, ""value TEXT, ""UNIQUE(setting)"");")
                    #dbcur.execute("DELETE FROM service WHERE setting = 'last_run'")
                    dbcur.execute("REPLACE INTO service Values (?, ?)", ('last_run', serviceProperty))
                    dbcon.commit()
                    dbcon.close()
                except Exception:
                    try:
                        dbcon.close()
                    except Exception:
                        pass

                if not c.get_setting('library.service.update') == 'true':
                    raise Exception()
                info = c.get_setting('library.service.notification') or 'true'
                self.update(info=info)
            except Exception:
                pass

            control.sleep(10000)
