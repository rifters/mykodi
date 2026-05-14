# -*- coding: utf-8 -*-
'''
 ***********************************************************
 * The Crew Add-on
 *
 * @file database.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2024-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

from sqlite3 import dbapi2 as db, OperationalError
import os
import time
import traceback
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union, cast

import xbmcvfs
import xbmcaddon

from .crewruntime import c

# translate profile path at module import (safe for Kodi environment)
try:
    _profile = xbmcaddon.Addon().getAddonInfo("profile")
    dataPath = (
        xbmcvfs.translatePath(_profile)
        if _profile
        else xbmcvfs.translatePath("special://profile/")
    )
except Exception:
    dataPath = xbmcvfs.translatePath("special://profile/")


class CMDatabase:
    """Small sqlite helper with dict row factory and simple CRUD helpers."""

    def __init__(self, **kwargs) -> None:
        self.con: Optional[db.Connection] = None
        self.cur: Optional[db.Cursor] = None
        self.db_file: Optional[str] = kwargs.get("db_file", None)
        self.table: Optional[str] = kwargs.get("table") or None
        self._get_connection()
        if self.con:
            self._set_settings()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def __del__(self) -> None:
        # best-effort cleanup, suppress errors
        try:
            if self.cur:
                self.cur.close()
        except Exception:
            pass
        try:
            if self.con:
                self.con.close()
        except Exception:
            pass

    def _get_connection(self) -> None:
        """Open sqlite connection if db_file provided."""
        if not self.db_file:
            return

        try:
            # ensure profile dir exists
            try:
                if not xbmcvfs.exists(dataPath):
                    xbmcvfs.mkdir(dataPath)
            except Exception:
                # xbmcvfs may not behave as expected on some platforms; fall back to os.makedirs on translated path
                try:
                    os.makedirs(dataPath, exist_ok=True)
                except Exception:
                    pass

            db_path = os.path.join(dataPath, self.db_file)
            # use timeout and default isolation (None -> autocommit); keep row_factory for dict rows
            self.con = db.connect(db_path, timeout=60, isolation_level=None)
            self.con.row_factory = self._dict_factory
            self.cur = self.con.cursor()
        except Exception as e:
            # keep attributes None on failure
            c.log(f'[Database] Failed to open {self.db_file}: {e}', 1)

    def _dict_factory(self, cursor, row) -> Dict[str, Any]:
        """Return rows as dicts keyed by column name."""
        return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

    def _set_settings(self) -> None:
        """Set pragmas to improve performance for addon usage."""
        try:
            # use safer journal_mode and synchronous defaults for speed in addon context
            self.execute("PRAGMA synchronous = OFF")
            self.execute("PRAGMA journal_mode = MEMORY")
            # commit if connection opened
            self.commit()
        except Exception as e:
            c.log(f'[Database] Failed to set pragmas: {e}', 1)

    def set_table(self, table: str) -> None:
        self.table = table

    def execute(
        self,
        query: str,
        params: Optional[Union[Sequence[Any], Iterable[Sequence[Any]]]] = None,
        many: bool = False,
    ):
        """
        Execute a query. If many=True, params should be an iterable of sequences and executemany is used.
        Returns the cursor for convenience.
        """
        if not self.cur:
            raise OperationalError("Database cursor is not available")

        try:
            if many:
                # executemany expects an iterable/sequence of sequences (tuples/lists)
                self.cur.executemany(query, cast(Iterable[Sequence[Any]], params or []))
            elif params is None:
                self.cur.execute(query)
            else:
                # ensure params is a sequence (tuple/list)
                self.cur.execute(query, cast(Sequence[Any], params))
            return self.cur
        except Exception:
            raise

    def commit(self) -> None:
        try:
            if self.con:
                self.con.commit()
        except Exception as e:
            c.log(f'[Database] Commit failed: {e}', 1)

    def close(self) -> None:
        try:
            if self.cur:
                self.cur.close()
        except Exception:
            pass
        try:
            if self.con:
                self.con.close()
        except Exception:
            pass
        self.cur = None
        self.con = None

    def fetch_all(
        self, query: str, params: Optional[Sequence[Any]] = None
    ) -> List[Dict[str, Any]]:
        cur = self.execute(query, params)
        return cur.fetchall()

    def fetch_one(
        self, query: str, params: Optional[Sequence[Any]] = None
    ) -> Optional[Dict[str, Any]]:
        cur = self.execute(query, params)
        return cur.fetchone()

    def fetch_column(
        self, query: str, column_name: str, params: Optional[Sequence[Any]] = None
    ) -> List[Any]:
        rows = self.fetch_all(query, params)
        return [row.get(column_name) for row in rows]

    def create_table(self, table_name: str, columns: Sequence[str]) -> None:
        """
        columns should be like: ["id INTEGER PRIMARY KEY", "name TEXT", ...]
        """
        query = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(columns)})"
        self.execute(query)

    def insert(self, table_name: str, values: Dict[str, Any]) -> int:
        """Insert a single dict and return lastrowid."""
        query = self._build_insert_replace_query(values, "INSERT INTO ", table_name)
        cur = self.execute(query, list(values.values()))
        # cursor.lastrowid may be None; normalize to 0 to satisfy return type
        lastrowid = getattr(cur, "lastrowid", None)
        return int(lastrowid) if lastrowid is not None else 0

    def insert_many(self, table_name: str, values: Sequence[Dict[str, Any]]) -> None:
        """Insert many rows. values is a sequence of dicts with identical keys."""
        if not values:
            return
        columns = list(values[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        query = (
            f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        )
        params = [tuple(v[col] for col in columns) for v in values]
        self.execute(query, params, many=True)

    def replace(self, table_name: str, values: Dict[str, Any]) -> None:
        """REPLACE INTO (upsert) single row."""
        query = self._build_insert_replace_query(values, "REPLACE INTO ", table_name)
        self.execute(query, list(values.values()))

    def _build_insert_replace_query(self, values, arg1, table_name):
        columns = ", ".join(values.keys())
        placeholders = ", ".join(["?"] * len(values))
        return f"{arg1}{table_name} ({columns}) VALUES ({placeholders})"

    def update(self, table_name: str, where: str, values: Dict[str, Any]) -> None:
        """Update rows matching WHERE clause. where must be a safe SQL fragment (params not supported here)."""
        set_clause = ", ".join([f"{col}=?" for col in values])
        query = f"UPDATE {table_name} SET {set_clause} WHERE {where}"
        self.execute(query, list(values.values()))

    def delete(self, table_name: str, where: str) -> None:
        query = f"DELETE FROM {table_name} WHERE {where}"
        self.execute(query)
