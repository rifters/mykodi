# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file bookmarks.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import traceback
from typing import Optional, List, Dict, Any

import sqlite3 as database

from . import cache
from . import control
from . import trakt
from .crewruntime import c



def get_progress_bookmark(imdb: str = '', tmdb: int = 0, traktid: int = 0, tvdb: int = 0, mediatype: str = '', season: int = 0, episode: int = 0) -> float:
    try:
        if not trakt.table_exists('progress'):
            dbcon = trakt.get_connection(control.traktsyncFile, return_as_dict=True)
            dbcur = trakt.get_connection_cursor(dbcon)
            trakt.create_table('trakt_progress', dbcur)

        sql_base = "SELECT * from progress WHERE "
        if mediatype != '':
            sql_base += f"media_type = '{mediatype}' and "

        tmdb = int(tmdb)
        traktid = int(traktid)
        tvdb = int(tvdb)

        sql_conditions = []
        sql_season_conditions = []

        if season != 0 and episode != 0:
            if imdb != '':
                sql_conditions.append(f"showimdb = '{imdb}'")
            if tmdb != 0:
                sql_conditions.append(f"showtmdb = {tmdb}")
            if traktid != 0:
                sql_conditions.append(f"showtrakt = {traktid}")
            if tvdb != 0:
                sql_conditions.append(f"showtvdb = {tvdb}")
        else:
            if imdb != '':
                sql_conditions.append(f"imdb = '{imdb}'")
            if tmdb != 0:
                sql_conditions.append(f"tmdb = {tmdb}")
            if traktid != 0:
                sql_conditions.append(f"trakt = {traktid}")
            if tvdb != 0:
                sql_conditions.append(f"tvdb = {tvdb}")

        sql = sql_base + '(' + ' OR '.join(sql_conditions) + ')'

        if season != 0:
            sql_season_conditions.append(f"season = {season}")
        if episode != 0:
            sql_season_conditions.append(f"episode = {episode}")

        if len(sql_season_conditions) > 0:
            sql_select = sql + ' AND ' + ' AND '.join(sql_season_conditions)
        else:
            sql_select = sql

        if mediatype == 'movie':
            sql_select += " ORDER BY year DESC"
        elif mediatype == 'episode':
            sql_select += " ORDER BY tvshowtitle, season, episode ASC"
        else:
            sql_select += " ORDER BY tvshowtitle ASC"

        control.makeFile(control.dataPath)
        dbcon = trakt.get_connection(control.traktsyncFile, return_as_dict=True)
        dbcur = trakt.get_connection_cursor(dbcon)
        result = None
        if dbcur is not None:
            dbcur.execute(sql_select)
            result = dbcur.fetchone()
        if dbcon is not None:
            dbcon.commit()
        if result:
            return result['resume_point']
        else:
            return 0
    except Exception as e:
        c.log(f'Exception in get_progress_bookmark(): {e}')
        return 0

def get_episode_progress(imdb: str, tmdb: int = 0, traktid: int = 0, tvdb: int = 0, season: int = 0, episode: int = 0) -> float:
    return get_progress_bookmark(imdb=imdb, tmdb=tmdb, traktid=traktid, tvdb=tvdb, mediatype='episode', season=season, episode=episode)

def get_movie_progress(imdb: str, tmdb: int = 0, traktid: int = 0, tvdb: int = 0, season: int = 0, episode: int = 0) -> float:
    return get_progress_bookmark(imdb=imdb, tmdb=tmdb, traktid=traktid, tvdb=tvdb, mediatype='movie', season=season, episode=episode)

def get_local_bookmark(imdb: str, media_type: str, season: int, episode: int) -> float:
    """Return the seek position in seconds for a given movie or episode."""
    try:
        if media_type == 'episode':
            sql_select = "SELECT * FROM bookmarks WHERE imdb = ? AND season = ? AND episode = ?"
            params = (imdb, season, episode)
        else:
            sql_select = "SELECT * FROM bookmarks WHERE imdb = ?"
            params = (imdb,)

        control.makeFile(control.dataPath)
        dbcon = database.connect(control.bookmarksFile)
        dbcur = dbcon.cursor()
        dbcur.execute("CREATE TABLE IF NOT EXISTS bookmarks (timeInSeconds TEXT, type TEXT, imdb TEXT, season TEXT, episode TEXT, playcount INTEGER, overlay INTEGER, UNIQUE(imdb, season, episode))")
        dbcur.execute(sql_select, params)
        result = dbcur.fetchone()
        dbcon.commit()
        if result:
            return float(result[0])
        else:
            return 0
    except Exception:
        return 0

def get(media_type: str, imdb: str, tmdb: int = 0, traktid: int = 0, tvdb: int = 0, season: int = 0, episode: int = 0, local: bool = False) -> float:
    """Return the seek position in seconds for a movie or episode."""
    if control.setting('bookmarks') == 'true' and trakt.get_trakt_credentials_info() and not local:
        try:
            # First check if there's queued progress (most recent, not yet synced)
            queued_progress = trakt.get_queued_progress(media_type, imdb, season, episode)
            if queued_progress is not None and 0 < queued_progress < 92:
                # Convert percentage to time (requires total duration)
                # For now, fall through to get from Trakt progress table which has actual time
                pass

            # Get from Trakt progress table
            if media_type == 'episode':
                result = get_episode_progress(imdb=imdb, tmdb=tmdb, traktid=traktid, tvdb=tvdb, season=season, episode=episode)
            else:
                result = get_movie_progress(imdb=imdb, tmdb=tmdb, traktid=traktid, tvdb=tvdb)

            # Fall back to local bookmarks if the progress table has no entry.
            # bookmarks.reset() always writes to local bookmarks, so this covers the
            # case where update_progress_in_database failed or the table is empty.
            if not result:
                return get_local_bookmark(imdb, media_type, season, episode)
            return result
        except Exception:
            return get_local_bookmark(imdb, media_type, season, episode)
    else:
        try:
            return get_local_bookmark(imdb, media_type, season, episode)
        except Exception:
            c.log('Exception in bookmarks.get()')
            return 0

def reset(current_time: int, total_time: int, media_type: str, imdb: str, season: str = '', episode: str = '', tmdb: int = 0) -> None:
    """Reset bookmark, marking media as watched or unwatched based on progress."""
    try:
        _playcount = 0
        overlay = 6
        time_in_seconds = str(current_time)
        in_progress = int(current_time) > 0 and (current_time / total_time) < .92
        is_fully_watched = (current_time / total_time) >= .92
        resume_point = float(float(current_time) / float(total_time))

        if media_type == 'episode':
            sql_select = "SELECT * FROM bookmarks WHERE imdb = ? AND season = ? AND episode = ?"
            select_params = (imdb, season, episode)
            sql_update = "UPDATE bookmarks SET timeInSeconds = ? WHERE imdb = ? AND season = ? AND episode = ?"
            update_params = (time_in_seconds, imdb, season, episode)
            sql_update_watched = "UPDATE bookmarks SET timeInSeconds = '0', playcount = ?, overlay = ? WHERE imdb = ? AND season = ? AND episode = ?"
            sql_insert = "INSERT INTO bookmarks VALUES (?, ?, ?, ?, ?, ?, ?)"
            insert_params = (time_in_seconds, media_type, imdb, season, episode, _playcount, overlay)
            sql_insert_watched = "INSERT INTO bookmarks VALUES (?, ?, ?, ?, ?, ?, ?)"
        else:
            sql_select = "SELECT * FROM bookmarks WHERE imdb = ?"
            select_params = (imdb,)
            sql_update = "UPDATE bookmarks SET timeInSeconds = ? WHERE imdb = ?"
            update_params = (time_in_seconds, imdb)
            sql_update_watched = "UPDATE bookmarks SET timeInSeconds = '0', playcount = ?, overlay = ? WHERE imdb = ?"
            sql_insert = "INSERT INTO bookmarks VALUES (?, ?, ?, '', '', ?, ?)"
            insert_params = (time_in_seconds, media_type, imdb, _playcount, overlay)
            sql_insert_watched = "INSERT INTO bookmarks VALUES (?, ?, ?, '', '', ?, ?)"

        control.makeFile(control.dataPath)
        dbcon = database.connect(control.bookmarksFile)
        dbcur = dbcon.cursor()

        sql = '''
                CREATE TABLE IF NOT EXISTS bookmarks (
                timeInSeconds TEXT,
                type TEXT,
                imdb TEXT,
                season TEXT,
                episode TEXT,
                playcount INTEGER,
                overlay INTEGER,
                UNIQUE(imdb, season, episode)
                )
        '''

        dbcur.execute(sql)
        dbcur.execute(sql_select, select_params)
        existing_bookmark = dbcur.fetchone()
        if existing_bookmark:
            if in_progress:
                dbcur.execute(sql_update, update_params)
            elif is_fully_watched:
                _playcount = existing_bookmark[5] + 1
                overlay = 7
                if media_type == 'episode':
                    dbcur.execute(sql_update_watched, (_playcount, overlay, imdb, season, episode))
                else:
                    dbcur.execute(sql_update_watched, (_playcount, overlay, imdb))
        else:
            if in_progress:
                dbcur.execute(sql_insert, insert_params)
            elif is_fully_watched:
                _playcount = 1
                overlay = 7
                if media_type == 'episode':
                    dbcur.execute(sql_insert_watched, (time_in_seconds, media_type, imdb, season, episode, _playcount, overlay))
                else:
                    dbcur.execute(sql_insert_watched, (time_in_seconds, media_type, imdb, _playcount, overlay))
        dbcon.commit()

        # Also update Trakt progress table when Trakt sync is enabled
        if control.setting('bookmarks') == 'true' and trakt.get_trakt_credentials_info():
            try:
                # CRITICAL: Only in-progress episodes should be in the progress table
                # Fully watched episodes (resume_point >= 0.92) should be DELETED
                if is_fully_watched:
                    # Episode/movie is fully watched - DELETE from progress table
                    if media_type == 'movie':
                        trakt.delete_progress_from_database('imdb', imdb)
                    else:
                        trakt.delete_progress_from_database('imdb', imdb, season=int(season), episode=int(episode))
                elif in_progress:
                    # Episode/movie is in progress - UPDATE progress table
                    resume_seconds = current_time  # Use actual time position in seconds
                    if media_type == 'movie':
                        trakt.update_progress_in_database(imdb_id=imdb, tmdb_id=int(tmdb), progress=int(resume_point * 100), resume_point=resume_seconds)
                    else:
                        trakt.update_progress_in_database(imdb_id=imdb, tmdb_id=int(tmdb), season=int(season), episode=int(episode), progress=int(resume_point * 100), resume_point=resume_seconds)
            except Exception as e:
                c.log(f"[Bookmarks] Error updating Trakt progress table: {e}")

    except Exception as e:
        c.log(f'Exception in bookmarks.reset(): {e}')
        pass

def set_scrobble2(current_time: int, total_time: int, content: str, imdb: str = '', season: str = '', episode: str = '', action: str = 'pause') -> None:
    """Update the scrobble status for a movie or TV episode on Trakt (simplified version)."""
    try:
        progress = current_time / total_time * 100 if current_time != 0 and total_time != 0 else 0
        if 0 < progress < 92:
            if content == 'movie':
                trakt.scrobbleMovie(imdb, progress, action)
            else:
                trakt.scrobbleEpisode(imdb, season, episode, progress, action)
        elif progress >= 92:
            if content == 'movie':
                trakt.scrobbleMovie(imdb, progress, 'stop')
            else:
                trakt.scrobbleEpisode(imdb, str(season), str(episode), progress, 'stop')
            if not control.player.isPlayingVideo():
                control.infoDialog('Trakt: Scrobbled')
    except Exception as e:
        c.log(f'Exception raised in bookmarks.set_scrobble() Scrobble failed with error: {e}')




def set_scrobble(current_time: int, total_time: int, content: str, imdb: str = '', season: str = '', episode: str = '', action: str = 'pause') -> None:
    """Update the scrobble status for a movie or TV episode on Trakt. Always sends directly."""
    try:
        percent = current_time / total_time * 100 if current_time != 0 and total_time != 0 else 0
        if 0 < percent < 92:
            if content == 'movie':
                trakt.scrobbleMovie(imdb, percent, action)
            else:
                trakt.scrobbleEpisode(imdb, season, episode, percent, action)

            if not control.player.isPlayingVideo():
                if control.setting('trakt.scrobble.notify') == 'true':
                    control.sleep(1000)
                    control.infoDialog(f'Trakt: Scrobble, action = {action}')
                elif c.devmode:
                    control.sleep(1000)
                    control.infoDialog(f'[Devmode] Trakt: Scrobble, action = {action}')
        elif percent >= 92:
            if content == 'movie':
                trakt.scrobbleMovie(imdb, percent, 'stop')
            else:
                trakt.scrobbleEpisode(imdb, str(season), str(episode), percent, 'stop')
            if not control.player.isPlayingVideo():
                if control.setting('trakt.scrobble.notify') == 'true':
                    control.sleep(1000)
                    control.infoDialog('Trakt: Scrobbled')
                elif c.devmode:
                    control.sleep(1000)
                    control.infoDialog('Devmode - Trakt: Scrobbled')
    except Exception as e:
        c.log(f'Exception raised in bookmarks.set_scrobble(): {e}')


def get_indicators() -> List[str]:
    """Return a list of IMDB IDs for media items marked as watched."""
    control.makeFile(control.dataPath)
    dbcon = database.connect(control.bookmarksFile)
    dbcur = dbcon.cursor()
    dbcur.execute("SELECT * FROM bookmarks WHERE overlay = 7")
    watched_items = dbcur.fetchall()
    dbcon.commit()
    if watched_items:
        return [item[2] for item in watched_items]
    else:
        return []

def get_watched(media_type: str, imdb: str, season: str, episode: str) -> int:
    """Return the watched status (6=unwatched, 7=watched) from local bookmarks database."""
    control.makeFile(control.dataPath)
    dbcon = database.connect(control.bookmarksFile)
    dbcur = dbcon.cursor()

    # Use parameterized query to prevent SQL injection
    if media_type == 'episode':
        sql_select = "SELECT * FROM bookmarks WHERE imdb = ? AND overlay = 7 AND season = ? AND episode = ?"
        dbcur.execute(sql_select, (imdb, season, episode))
    else:
        sql_select = "SELECT * FROM bookmarks WHERE imdb = ? AND overlay = 7"
        dbcur.execute(sql_select, (imdb,))

    result = dbcur.fetchone()
    dbcon.close()

    return 7 if result else 6

def update_watched(media_type: str, new_value: int, imdb: str, season: str, episode: str) -> None:
    """Update the watched status of a media item in the bookmarks database."""
    if media_type == 'episode':
        sql_update = "UPDATE bookmarks SET overlay = ? WHERE imdb = ? AND season = ? AND episode = ?"
        params = (new_value, imdb, season, episode)
    else:
        sql_update = "UPDATE bookmarks SET overlay = ? WHERE imdb = ?"
        params = (new_value, imdb)

    dbcon = database.connect(control.bookmarksFile)
    dbcur = dbcon.cursor()
    dbcur.execute(sql_update, params)
    dbcon.commit()

def delete_record(media_type: str, imdb: str, season: str, episode: str) -> None:
    """Delete a record from the bookmarks database."""
    if media_type == 'episode':
        sql_delete = "DELETE FROM bookmarks WHERE imdb = ? AND season = ? AND episode = ?"
        params = (imdb, season, episode)
    else:
        sql_delete = "DELETE FROM bookmarks WHERE imdb = ?"
        params = (imdb,)

    dbcon = database.connect(control.bookmarksFile)
    dbcur = dbcon.cursor()
    dbcur.execute(sql_delete, params)
    dbcon.commit()


def clear_resume_point(media_type: str, imdb: str, season: Optional[str] = None, episode: Optional[str] = None, tmdb: Optional[str] = None, redirect: Optional[str] = None) -> None:
    """Clear resume point, remove from Trakt, and refresh UI."""
    try:
        # Use tmdb as fallback if imdb is missing (some shows don't have IMDB IDs)
        if not imdb or imdb in ['', '0', 'None']:
            if not tmdb or tmdb in ['', '0', 'None']:
                c.log(f"[bookmarks] Warning: No valid IMDB or TMDB ID provided")
                return

        # Get resume_id from progress table to delete from Trakt
        resume_id = None
        try:
            dbcon = database.connect(control.traktsyncFile)
            dbcur = dbcon.cursor()

            # Build query - try IMDB first, then TMDB
            if imdb and imdb not in ['', '0', 'None']:
                sql = "SELECT resume_id FROM progress WHERE imdb = ?"
                params = [imdb]
            elif tmdb and tmdb not in ['', '0', 'None']:
                sql = "SELECT resume_id FROM progress WHERE tmdb = ?"
                params = [tmdb]
            else:
                dbcon.close()
                return

            if media_type == 'episode' and season and episode:
                sql += " AND season = ? AND episode = ?"
                params.extend([str(int(season)), str(int(episode))])

            dbcur.execute(sql, params)
            result = dbcur.fetchone()
            resume_id = result[0] if result and result[0] else None
            dbcon.close()

            # If not found locally, fall back to fetching from the Trakt API.
            # This handles the case where the local DB row was already evicted
            # (e.g. by a concurrent sync) but the playback record still exists
            # on Trakt's server and would be re-synced on next startup.
            if not resume_id:
                c.log(f"[bookmarks] resume_id not in local DB for {imdb}, fetching from Trakt API")
                resume_id = trakt.get_resume_id_from_trakt_api(imdb, media_type)

            # Delete from Trakt if we have a resume_id
            if resume_id:
                success = trakt.deleteTraktPlayback(resume_id)
                if not success:
                    c.log(f"[bookmarks] Failed to delete from Trakt (may not be authenticated)")

        except Exception as e:
            c.log(f"[bookmarks] Error deleting from Trakt: {e}")

        # Delete from bookmarks table (old system)
        if imdb and imdb not in ['', '0', 'None']:
            delete_record(media_type, imdb, season or '', episode or '')

        # Delete from progress table (trakt sync system)
        season_int = int(season) if season else 0
        episode_int = int(episode) if episode else 0

        if imdb and imdb not in ['', '0', 'None']:
            trakt.delete_progress_from_database('imdb', imdb, season_int, episode_int)
        elif tmdb and tmdb not in ['', '0', 'None']:
            trakt.delete_progress_from_database('tmdb', tmdb, season_int, episode_int)
        else:
            c.log(f"[bookmarks] Error: No valid identifier for progress deletion")
            return

        # Clear Trakt playback cache
        try:
            url = "https://api.trakt.tv/sync/playback/episodes?extended=full"
            cache_key = f"trakt_playback_episodes_{hash(url)}"
            cache.cache_delete(cache_key, 'trakt')
        except Exception as e:
            c.log(f"[bookmarks] Failed to clear cache: {e}")

        control.infoDialog("Resume point cleared", time=1500)
        control.sleep(200)

        # Force container reload
        try:
            if redirect:
                control.execute(f'Container.Update({redirect})')
            else:
                control.refresh()
        except Exception as e:
            c.log(f"[bookmarks] Container update failed: {e}")
            control.refresh()

    except Exception as e:
        c.log(f"[bookmarks] clear_resume_point failed: {e}")


def sync_with_trakt() -> None:
    """Sync bookmarks with Trakt (wrapper for trakt.sync_bookmarks)"""
    trakt.sync_bookmarks()
