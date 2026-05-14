# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file tvevening_playlist_db.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
Database-backed playlist for TV Evening

Replaces Kodi's native playlist to avoid state loss issues.
Stores playlist order, metadata, and playback state in SQLite.
'''

import sqlite3
import threading
import json
from datetime import datetime
from . import control
from .crewruntime import c


class TVEveningPlaylistDB:
    """
    Database-backed playlist for TV Evening.

    Provides reliable playlist management that persists across Kodi sessions
    and avoids Kodi's native playlist state loss bugs.
    """

    def __init__(self):
        """Initialize database connection."""
        self.db_path = control.dataPath + 'tvevening_playlist.db'
        self.lock = threading.RLock()
        self._init_database()

    def _init_database(self):
        """Create database schema if it doesn't exist."""
        try:
            with self.lock:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Create playlist table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS tv_evening_playlist (
                        position INTEGER PRIMARY KEY,
                        imdb TEXT,
                        tmdb TEXT,
                        tvshowtitle TEXT,
                        title TEXT,
                        year TEXT,
                        season INTEGER,
                        episode INTEGER,
                        duration INTEGER DEFAULT 0,
                        thumb TEXT,
                        poster TEXT,
                        fanart TEXT,
                        plot TEXT,
                        premiered TEXT,
                        showimdb TEXT,
                        showtmdb TEXT,
                        url TEXT,
                        cast_data TEXT,
                        watched INTEGER DEFAULT 0,
                        started INTEGER DEFAULT 0,
                        completed INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Create metadata table for playlist session info
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS tv_evening_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Migrate existing databases: Add cast_data column if it doesn't exist
                try:
                    cursor.execute("SELECT cast_data FROM tv_evening_playlist LIMIT 1")
                except sqlite3.OperationalError:
                    c.log("[TV Evening DB] Adding cast_data column to existing database")
                    cursor.execute("ALTER TABLE tv_evening_playlist ADD COLUMN cast_data TEXT")

                # Create index for quick position lookups
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_position
                    ON tv_evening_playlist(position)
                ''')

                # Create index for watched/started queries
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_watched
                    ON tv_evening_playlist(watched, started)
                ''')

                conn.commit()
                conn.close()

                c.log("[TV Evening DB] Database initialized successfully")

        except Exception as e:
            c.log(f"[TV Evening DB] Error initializing database: {e}")
            import traceback
            c.log(f"[TV Evening DB] Traceback: {traceback.format_exc()}")

    def clear_playlist(self):
        """Clear all episodes from playlist."""
        try:
            with self.lock:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                cursor = conn.cursor()

                cursor.execute('DELETE FROM tv_evening_playlist')
                cursor.execute('DELETE FROM tv_evening_metadata')

                conn.commit()
                conn.close()

                c.log("[TV Evening DB] Playlist cleared")
                return True

        except Exception as e:
            c.log(f"[TV Evening DB] Error clearing playlist: {e}")
            return False

    def add_episode(self, position, episode_data):
        """
        Add episode to playlist at specific position.

        :param int position: Zero-based position in playlist
        :param dict episode_data: Episode metadata (must include at minimum:
                                  tvshowtitle, season, episode, title)
        :return: True if successful
        """
        try:
            with self.lock:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                cursor = conn.cursor()

                # Extract data with defaults
                data = {
                    'position': position,
                    'imdb': episode_data.get('imdb', ''),
                    'tmdb': episode_data.get('tmdb', ''),
                    'tvshowtitle': episode_data.get('tvshowtitle', ''),
                    'title': episode_data.get('title', ''),
                    'year': episode_data.get('year', ''),
                    'season': episode_data.get('season', 0),
                    'episode': episode_data.get('episode', 0),
                    'duration': episode_data.get('duration', 0),
                    'thumb': episode_data.get('thumb', ''),
                    'poster': episode_data.get('poster', ''),
                    'fanart': episode_data.get('fanart', ''),
                    'plot': episode_data.get('plot', ''),
                    'premiered': episode_data.get('premiered', ''),
                    'showimdb': episode_data.get('showimdb', ''),
                    'showtmdb': episode_data.get('showtmdb', ''),
                    'url': episode_data.get('url', ''),
                }

                # Serialize cast data (cast_leads, cast_guests, or general cast array)
                cast_dict = {}
                if 'cast_leads' in episode_data or 'cast_guests' in episode_data:
                    cast_dict['cast_leads'] = episode_data.get('cast_leads', [])
                    cast_dict['cast_guests'] = episode_data.get('cast_guests', [])
                    c.log(f"[TV Evening DB] Saving cast for pos {position}: {len(cast_dict.get('cast_leads', []))} leads, {len(cast_dict.get('cast_guests', []))} guests")
                elif 'cast' in episode_data:
                    cast_dict['cast'] = episode_data.get('cast', [])
                cast_json = json.dumps(cast_dict) if cast_dict else ''

                cursor.execute('''
                    INSERT OR REPLACE INTO tv_evening_playlist
                    (position, imdb, tmdb, tvshowtitle, title, year, season, episode,
                     duration, thumb, poster, fanart, plot, premiered, showimdb, showtmdb,
                     url, cast_data, watched, started, completed, updated_at)
                    VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?)
                ''', (
                    data['position'], data['imdb'], data['tmdb'], data['tvshowtitle'],
                    data['title'], data['year'], data['season'], data['episode'],
                    data['duration'], data['thumb'], data['poster'], data['fanart'],
                    data['plot'], data['premiered'], data['showimdb'], data['showtmdb'],
                    data['url'], cast_json, datetime.now().isoformat()
                ))

                conn.commit()
                conn.close()

                c.log(f"[TV Evening DB] Added episode at position {position}: "
                      f"{data['tvshowtitle']} S{data['season']:02d}E{data['episode']:02d}")
                return True

        except Exception as e:
            c.log(f"[TV Evening DB] Error adding episode: {e}")
            import traceback
            c.log(f"[TV Evening DB] Traceback: {traceback.format_exc()}")
            return False

    def get_episode_at_position(self, position):
        """
        Get episode at specific position.

        :param int position: Zero-based position
        :return: Dict with episode data or None
        """
        try:
            with self.lock:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT * FROM tv_evening_playlist WHERE position = ?
                ''', (position,))

                row = cursor.fetchone()
                conn.close()

                if row:
                    episode_dict = dict(row)
                    # Deserialize cast data
                    if episode_dict.get('cast_data'):
                        try:
                            cast_dict = json.loads(episode_dict['cast_data'])
                            episode_dict.update(cast_dict)  # Merge cast_leads, cast_guests, or cast into episode dict
                            c.log(f"[TV Evening DB] Retrieved cast for pos {position}: {len(cast_dict.get('cast_leads', []))} leads, {len(cast_dict.get('cast_guests', []))} guests")
                        except Exception as e:
                            c.log(f"[TV Evening DB] Error deserializing cast_data: {e}")
                    else:
                        c.log(f"[TV Evening DB] No cast_data found for pos {position}")
                    return episode_dict
                return None

        except Exception as e:
            c.log(f"[TV Evening DB] Error getting episode at position {position}: {e}")
            return None

    def get_next_episode(self, current_position):
        """
        Get next episode after current position.

        :param int current_position: Current zero-based position
        :return: Dict with episode data or None
        """
        return self.get_episode_at_position(current_position + 1)

    def get_playlist_size(self):
        """
        Get total number of episodes in playlist.

        :return: Integer count
        """
        try:
            with self.lock:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                cursor = conn.cursor()

                cursor.execute('SELECT COUNT(*) FROM tv_evening_playlist')
                count = cursor.fetchone()[0]

                conn.close()
                return count

        except Exception as e:
            c.log(f"[TV Evening DB] Error getting playlist size: {e}")
            return 0

    def get_all_episodes(self):
        """
        Get all episodes in playlist order.

        :return: List of episode dicts ordered by position
        """
        try:
            with self.lock:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT * FROM tv_evening_playlist ORDER BY position
                ''')

                rows = cursor.fetchall()
                conn.close()

                episodes = []
                for row in rows:
                    episode_dict = dict(row)
                    # Deserialize cast data
                    if episode_dict.get('cast_data'):
                        try:
                            cast_dict = json.loads(episode_dict['cast_data'])
                            episode_dict.update(cast_dict)  # Merge cast_leads, cast_guests, or cast into episode dict
                        except:
                            pass
                    episodes.append(episode_dict)

                return episodes

        except Exception as e:
            c.log(f"[TV Evening DB] Error getting all episodes: {e}")
            return []

    def mark_episode_started(self, position):
        """Mark episode as started playback."""
        try:
            with self.lock:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                cursor = conn.cursor()

                cursor.execute('''
                    UPDATE tv_evening_playlist
                    SET started = 1, updated_at = ?
                    WHERE position = ?
                ''', (datetime.now().isoformat(), position))

                conn.commit()
                conn.close()

                c.log(f"[TV Evening DB] Marked episode {position} as started")
                return True

        except Exception as e:
            c.log(f"[TV Evening DB] Error marking episode started: {e}")
            return False

    def mark_episode_watched(self, position):
        """Mark episode as watched."""
        try:
            with self.lock:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                cursor = conn.cursor()

                cursor.execute('''
                    UPDATE tv_evening_playlist
                    SET watched = 1, completed = 1, updated_at = ?
                    WHERE position = ?
                ''', (datetime.now().isoformat(), position))

                conn.commit()
                conn.close()

                c.log(f"[TV Evening DB] Marked episode {position} as watched")
                return True

        except Exception as e:
            c.log(f"[TV Evening DB] Error marking episode watched: {e}")
            return False

    def get_current_position(self):
        """
        Get current playback position (last started episode).

        :return: Integer position or 0 if none started
        """
        try:
            with self.lock:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT MAX(position) FROM tv_evening_playlist WHERE started = 1
                ''')

                result = cursor.fetchone()[0]
                conn.close()

                return result if result is not None else 0

        except Exception as e:
            c.log(f"[TV Evening DB] Error getting current position: {e}")
            return 0

    def set_metadata(self, key, value):
        """Set metadata key-value pair."""
        try:
            with self.lock:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                cursor = conn.cursor()

                cursor.execute('''
                    INSERT OR REPLACE INTO tv_evening_metadata (key, value, updated_at)
                    VALUES (?, ?, ?)
                ''', (key, str(value), datetime.now().isoformat()))

                conn.commit()
                conn.close()
                return True

        except Exception as e:
            c.log(f"[TV Evening DB] Error setting metadata: {e}")
            return False

    def get_metadata(self, key, default=None):
        """Get metadata value by key."""
        try:
            with self.lock:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                cursor = conn.cursor()

                cursor.execute('SELECT value FROM tv_evening_metadata WHERE key = ?', (key,))
                result = cursor.fetchone()

                conn.close()

                if result:
                    return result[0]
                return default

        except Exception as e:
            c.log(f"[TV Evening DB] Error getting metadata: {e}")
            return default


# Singleton instance
_db_instance = None
_db_lock = threading.RLock()


def get_playlist_db():
    """Get singleton database instance."""
    global _db_instance

    with _db_lock:
        if _db_instance is None:
            _db_instance = TVEveningPlaylistDB()
        return _db_instance
