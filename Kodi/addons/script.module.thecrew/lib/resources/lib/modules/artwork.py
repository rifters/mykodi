# -*- coding: utf-8 -*-
'''
***********************************************************
*
* @file artwork.py
* @package script.module.thecrew
*
* Created on 2024-06-11.
* Updated on 2026-03-15
* Copyright 2024 - 2026 by The Crew. All rights reserved.
*
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''
"""Artwork caching database manager for The Crew addon."""

import os
import time
import traceback
from datetime import datetime
from typing import Optional, Dict, Any

import xbmcvfs
import xbmcaddon

from .database import CMDatabase as db
from .crewruntime import c


########
# paths

# Database file configuration
ARTWORK_DB_FILE = 'artwork.db'

########
# sql

# SQL table schema
SQL_CREATE_ARTWORK_TABLE = (
    "CREATE TABLE artwork ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "imdb TEXT, tmdb TEXT, tvdb TEXT, trakt TEXT, slug TEXT, "
    "title TEXT, year INTEGER, season INTEGER, episode INTEGER, "
    "poster TEXT, fanart TEXT, season_poster TEXT, tvshow_poster TEXT, "
    "thumb TEXT, banner TEXT, clearart TEXT, clearlogo TEXT, "
    "added INTEGER)"
)


class Artwork():
    """Artwork database manager for caching media artwork URLs."""

    def __init__(self, *args, **kwargs):
        """Initialize artwork database connection and ensure table exists."""
        self.dbFile = ARTWORK_DB_FILE
        self.db = db(db_file=self.dbFile)
        self.timeout = 720  # timeout in hours
        self._check_databases()  # Fixed: added parentheses

    def __del__(self):
        """Clean up database connection."""
        self.db.close()


    def get(self, key: str, table: str = 'artwork', timeout: int = 720) -> Optional[Dict[str, Any]]:
        """Retrieve artwork from cache if still valid."""
        try:
            # Use parameterized query to prevent SQL injection
            sql = (
                f'SELECT * FROM {table} WHERE imdb=? OR tmdb=? OR tvdb=? '
                f'OR trakt=? OR slug=?'
            )
            row = self.db.fetch_one(sql, (key, key, key, key, key))

            if row and self._is_valid(timeout, row):
                return row
            return None

        except Exception as e:
            failure = traceback.format_exc()
            if 'no such table' in failure:
                self._check_databases()
            else:
                pass
            return None


    def insert(self, imdb: str, tmdb: str, tvdb: str, trakt: str, slug: str,
                title: str, year: int, season: int, episode: int, poster: str,
                fanart: str, season_poster: str, tvshow_poster: str, thumb: str,
                banner: str, clearart: str, clearlogo: str) -> None:
        """Insert new artwork entry into database."""
        try:
            if not self._table_exists('artwork'):
                self.db.execute(SQL_CREATE_ARTWORK_TABLE)
                self.db.commit()

            added = int(time.mktime(datetime.now().timetuple()))
            self.db.insert(
                'artwork',
                dict(
                    imdb=imdb, tmdb=tmdb, tvdb=tvdb, trakt=trakt, slug=slug,
                    title=title, year=year, season=season, episode=episode,
                    poster=poster, fanart=fanart, season_poster=season_poster,
                    tvshow_poster=tvshow_poster, thumb=thumb, banner=banner,
                    clearart=clearart, clearlogo=clearlogo, added=added
                )
            )
            self.db.commit()

        except Exception as e:
            pass

    def _check_databases(self) -> None:
        """Verify artwork table exists, create if missing."""
        try:
            if not self._table_exists('artwork'):
                self.db.execute(SQL_CREATE_ARTWORK_TABLE)
                self.db.commit()

        except Exception as e:
            pass

    def _table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        try:
            sql = (
                'SELECT name FROM sqlite_master WHERE '
                f'type="table" AND name="{table_name}"'
            )
            result = self.db.fetch_one(sql)
            return result is not None

        except Exception as e:
            return False

    def _is_valid(self, timeout: int, row: Dict[str, Any]) -> bool:
        """Check if cached artwork is still within timeout period."""
        current_timestamp = int(time.mktime(datetime.now().timetuple()))
        age_hours = (current_timestamp - row['added']) / 3600
        return age_hours < timeout