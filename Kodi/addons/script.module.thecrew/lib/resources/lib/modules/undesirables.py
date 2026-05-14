# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on - Undesirables Management
 *
 * @package script.module.thecrew
 *
 * SQLite-backed blacklist system for filtering unwanted source domains/watermarks.
 * Provides user-configurable filtering with sensible defaults from Gears.
 *
 * @copyright (c) 2025, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ***********************************************************
'''

import os
import sqlite3 as database

from . import control
from .crewruntime import c


# Default blacklist from Gears addon (foreign torrent sites, spam watermarks)
DEFAULT_UNDESIRABLES = (
    # Tamil torrent sites
    'tamilrockers.com', 'www.tamilrockers.com', 'www.tamilrockers.ws',
    'www.tamilrockers.pl', 'www.tamilblasters.news', 'www.1tamilmv.hair',
    'www.1tamilmv.mov', '1tamilmv.press', 'www.1tamilmv.world',
    'www.tamilmv.bid', 'www.tamilmv.work',

    # MovieRulz variants
    'www.movierulz.com', 'movierulz.vpn', 'www.3movierulz.com',
    'www.3movierulz.watch', 'www.3movierulz.ws', 'www.movierulzhd.website',

    # Other foreign/spam sites
    'www.mkvcinemas.com', 'www.katmoviehd.se', 'www.torrenting.com',
    'movcr.cc', 'movcr.to', 'psarips.com',

    # Watermarks/spam
    'www.1xbet.com', 'crazy4tv.com', 'crazy4tv-com',
    'kickass.global', 'www.xbay.me',

    # Quality indicators to filter
    '(es)', '(imax)', '13+', '18+'
)


class Undesirables:
    """
    Manages user-configurable blacklist of domains/keywords to filter from scraper results.
    Uses SQLite database with defaults from Gears addon.
    """

    def __init__(self):
        """Initialize database connection and create table if needed."""
        self.db_path = os.path.join(control.dataPath, 'undesirables.db')
        self.dbcon = database.connect(self.db_path, timeout=60.0)
        self.dbcon.row_factory = self._dict_factory
        self.dbcur = self.dbcon.cursor()
        self._create_table()
        self._initialize_defaults()

    def __del__(self):
        """Close database connection."""
        try:
            self.dbcur.close()
            self.dbcon.close()
        except:
            pass

    @staticmethod
    def _dict_factory(cursor, row):
        """Convert database row to dictionary."""
        d = {}
        for idx, col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d

    def _create_table(self):
        """Create undesirables table if it doesn't exist."""
        try:
            self.dbcur.execute('''
                CREATE TABLE IF NOT EXISTS undesirables (
                    keyword TEXT NOT NULL UNIQUE,
                    user_defined INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (keyword)
                )
            ''')
            self.dbcon.commit()
        except Exception as e:
            c.log(f'[Undesirables] Error creating table: {e}', 1)

    def _initialize_defaults(self):
        """Populate database with default blacklist if empty."""
        try:
            # Check if we have any entries
            result = self.dbcur.execute('SELECT COUNT(*) as count FROM undesirables').fetchone()

            if result['count'] == 0:
                # Insert defaults
                default_entries = [(keyword, 0, 1) for keyword in DEFAULT_UNDESIRABLES]
                self.dbcur.executemany(
                    'INSERT OR IGNORE INTO undesirables (keyword, user_defined, enabled) VALUES (?, ?, ?)',
                    default_entries
                )
                self.dbcon.commit()
                c.log(f'[Undesirables] Initialized {len(DEFAULT_UNDESIRABLES)} default entries')
        except Exception as e:
            c.log(f'[Undesirables] Error initializing defaults: {e}', 1)

    def get_enabled(self):
        """
        Get list of enabled blacklist keywords.

        Returns:
            list: Enabled keywords (lowercase)
        """
        try:
            results = self.dbcur.execute(
                'SELECT keyword FROM undesirables WHERE enabled = 1'
            ).fetchall()

            keywords = [row['keyword'].lower() for row in results]
            c.log(f'[Undesirables] Loaded {len(keywords)} enabled keywords')
            return keywords
        except Exception as e:
            c.log(f'[Undesirables] Error getting enabled: {e}', 1)
            # Fallback to defaults
            return [k.lower() for k in DEFAULT_UNDESIRABLES]

    def get_all(self):
        """
        Get all blacklist entries with metadata.

        Returns:
            list: Dictionaries with keys: keyword, user_defined, enabled
        """
        try:
            results = self.dbcur.execute(
                'SELECT keyword, user_defined, enabled FROM undesirables ORDER BY keyword'
            ).fetchall()
            return results
        except Exception as e:
            c.log(f'[Undesirables] Error getting all: {e}', 1)
            return []

    def get_user_defined(self):
        """
        Get list of user-defined keywords only.

        Returns:
            list: User-defined keywords (lowercase)
        """
        try:
            results = self.dbcur.execute(
                'SELECT keyword FROM undesirables WHERE user_defined = 1 ORDER BY keyword'
            ).fetchall()
            keywords = [row['keyword'] for row in results]
            return keywords
        except Exception as e:
            c.log(f'[Undesirables] Error getting user-defined: {e}', 1)
            return []

    def add(self, keyword, user_defined=True):
        """
        Add a new keyword to blacklist.

        Args:
            keyword (str): Keyword to add
            user_defined (bool): Whether this is user-defined (default: True)

        Returns:
            bool: True if added successfully
        """
        try:
            self.dbcur.execute(
                'INSERT OR REPLACE INTO undesirables (keyword, user_defined, enabled) VALUES (?, ?, 1)',
                (keyword.lower(), 1 if user_defined else 0)
            )
            self.dbcon.commit()
            c.log(f'[Undesirables] Added keyword: {keyword}')
            return True
        except Exception as e:
            c.log(f'[Undesirables] Error adding keyword: {e}', 1)
            return False

    def remove(self, keyword):
        """
        Remove a keyword from blacklist.

        Args:
            keyword (str): Keyword to remove

        Returns:
            bool: True if removed successfully
        """
        try:
            self.dbcur.execute('DELETE FROM undesirables WHERE keyword = ?', (keyword.lower(),))
            self.dbcon.commit()
            c.log(f'[Undesirables] Removed keyword: {keyword}')
            return True
        except Exception as e:
            c.log(f'[Undesirables] Error removing keyword: {e}', 1)
            return False

    def set_enabled(self, keyword, enabled):
        """
        Enable or disable a keyword.

        Args:
            keyword (str): Keyword to update
            enabled (bool): Whether to enable (True) or disable (False)

        Returns:
            bool: True if updated successfully
        """
        try:
            self.dbcur.execute(
                'UPDATE undesirables SET enabled = ? WHERE keyword = ?',
                (1 if enabled else 0, keyword.lower())
            )
            self.dbcon.commit()
            c.log(f'[Undesirables] Set {keyword} enabled={enabled}')
            return True
        except Exception as e:
            c.log(f'[Undesirables] Error setting enabled: {e}', 1)
            return False

    def set_many(self, entries):
        """
        Batch update blacklist entries.

        Args:
            entries (list): List of tuples (keyword, user_defined, enabled)

        Returns:
            bool: True if updated successfully
        """
        try:
            self.dbcur.executemany(
                'INSERT OR REPLACE INTO undesirables (keyword, user_defined, enabled) VALUES (?, ?, ?)',
                [(kw.lower(), ud, en) for kw, ud, en in entries]
            )
            self.dbcon.commit()
            c.log(f'[Undesirables] Batch updated {len(entries)} entries')
            return True
        except Exception as e:
            c.log(f'[Undesirables] Error in batch update: {e}', 1)
            return False

    def remove_many(self, keywords):
        """
        Batch remove keywords from blacklist.

        Args:
            keywords (list): List of keywords to remove

        Returns:
            bool: True if removed successfully
        """
        try:
            self.dbcur.executemany(
                'DELETE FROM undesirables WHERE keyword = ?',
                [(kw.lower(),) for kw in keywords]
            )
            self.dbcon.commit()
            c.log(f'[Undesirables] Batch removed {len(keywords)} entries')
            return True
        except Exception as e:
            c.log(f'[Undesirables] Error in batch remove: {e}', 1)
            return False

    def reset_to_defaults(self):
        """
        Reset blacklist to default entries only.

        Returns:
            bool: True if reset successfully
        """
        try:
            # Remove all user-defined entries
            self.dbcur.execute('DELETE FROM undesirables WHERE user_defined = 1')

            # Re-enable all defaults
            self.dbcur.execute('UPDATE undesirables SET enabled = 1 WHERE user_defined = 0')

            self.dbcon.commit()
            c.log('[Undesirables] Reset to defaults')
            return True
        except Exception as e:
            c.log(f'[Undesirables] Error resetting to defaults: {e}', 1)
            return False


def get_undesirables():
    """
    Convenience function to get enabled blacklist keywords.
    Respects filter.undesirables setting and per-search bypass.

    Returns:
        list: Enabled keywords or empty list if filtering disabled
    """
    # Check if filtering is disabled globally
    if c.get_setting('filter.undesirables') != 'true':
        return []

    # Check for per-search bypass (set by "Search without filters" context menu)
    if control.window.getProperty('thecrew.filterless_search') == 'true':
        c.log('[Undesirables] Bypass enabled, skipping filtering')
        return []

    try:
        undesirables = Undesirables().get_enabled()
        return undesirables
    except Exception as e:
        c.log(f'[Undesirables] Error loading, using defaults: {e}', 1)
        # Fallback to static defaults
        return [k.lower() for k in DEFAULT_UNDESIRABLES]


# GUI Handler Functions for User Management

def undesirablesSelect():
    """
    Multi-select dialog to enable/disable default blacklist entries.
    Shows all default keywords with checkboxes, pre-selected if enabled.
    """
    try:
        undesirables_cache = Undesirables()
        all_entries = undesirables_cache.get_all()

        # Filter to defaults only (user_defined = 0)
        defaults = [entry['keyword'] for entry in all_entries if entry['user_defined'] == 0]
        enabled = [entry['keyword'] for entry in all_entries if entry['user_defined'] == 0 and entry['enabled'] == 1]

        if not defaults:
            control.infoDialog('No default undesirables found', time=3000)
            return

        # Create preselect indices
        preselect = [defaults.index(kw) for kw in enabled if kw in defaults]

        # Show multi-select dialog
        choices = control.dialog.multiselect(control.lang(90227) or 'Select Keywords to Enable/Disable', defaults, preselect=preselect)

        if choices is None:  # User cancelled
            return

        # Update database
        enabled_keywords = [defaults[i] for i in choices]
        disabled_keywords = [kw for kw in defaults if kw not in enabled_keywords]

        # Set enabled state for all defaults
        for kw in enabled_keywords:
            undesirables_cache.set_enabled(kw, True)
        for kw in disabled_keywords:
            undesirables_cache.set_enabled(kw, False)

        control.infoDialog(f'Updated {len(enabled_keywords) + len(disabled_keywords)} keywords', time=2000)
        c.log(f'[Undesirables] Updated {len(enabled_keywords)} enabled, {len(disabled_keywords)} disabled')
    except Exception as e:
        c.log(f'[Undesirables] Error in undesirablesSelect: {e}', 1)
        control.infoDialog('Error updating undesirables', time=3000)


def undesirablesInput():
    """
    Text input dialog for adding user-defined blacklist keywords.
    Accepts comma-separated list of keywords.
    """
    try:
        undesirables_cache = Undesirables()
        user_defined = undesirables_cache.get_user_defined()

        # Show current user keywords
        current_string = ','.join(user_defined) if user_defined else ''

        # Get input from user
        keyboard = control.keyboard(current_string, control.lang(90228) or 'Define Extra Keywords (Comma Separated)')
        keyboard.doModal()

        if not keyboard.isConfirmed():
            return

        new_string = keyboard.getText()
        if not new_string or new_string == current_string:
            return

        # Parse input
        new_keywords = [kw.strip().lower() for kw in new_string.split(',') if kw.strip()]

        if not new_keywords:
            return

        # Add to database (user_defined=1, enabled=1)
        for kw in new_keywords:
            undesirables_cache.add(kw, user_defined=True)

        control.infoDialog(f'Added {len(new_keywords)} user keywords', time=2000)
        c.log(f'[Undesirables] Added {len(new_keywords)} user-defined keywords')
    except Exception as e:
        c.log(f'[Undesirables] Error in undesirablesInput: {e}', 1)
        control.infoDialog('Error adding keywords', time=3000)


def undesirablesUserRemove():
    """
    Multi-select dialog to remove user-defined keywords.
    Shows only user-defined keywords.
    """
    try:
        undesirables_cache = Undesirables()
        user_undesirables = undesirables_cache.get_user_defined()

        if not user_undesirables:
            control.infoDialog('No user-defined keywords set', time=3000)
            return

        # Show multi-select dialog
        choices = control.dialog.multiselect(control.lang(90229) or 'Select Keywords to Remove', user_undesirables)

        if not choices:  # User cancelled or selected nothing
            return

        # Remove selected keywords
        removals = [user_undesirables[i] for i in choices]
        for kw in removals:
            undesirables_cache.remove(kw)

        control.infoDialog(f'Removed {len(removals)} keywords', time=2000)
        c.log(f'[Undesirables] Removed {len(removals)} user-defined keywords')
    except Exception as e:
        c.log(f'[Undesirables] Error in undesirablesUserRemove: {e}', 1)
        control.infoDialog('Error removing keywords', time=3000)


def undesirablesUserRemoveAll():
    """
    Remove all user-defined keywords with confirmation dialog.
    Leaves default keywords intact.
    """
    try:
        undesirables_cache = Undesirables()
        user_undesirables = undesirables_cache.get_user_defined()

        if not user_undesirables:
            control.infoDialog('No user-defined keywords set', time=3000)
            return

        # Confirm removal
        if not control.yesnoDialog(f'Remove all {len(user_undesirables)} user-defined keywords?', 'Are you sure?', ''):
            return

        # Remove all user-defined
        for kw in user_undesirables:
            undesirables_cache.remove(kw)

        control.infoDialog(f'Removed all {len(user_undesirables)} user keywords', time=2000)
        c.log(f'[Undesirables] Removed all {len(user_undesirables)} user-defined keywords')
    except Exception as e:
        c.log(f'[Undesirables] Error in undesirablesUserRemoveAll: {e}', 1)
        control.infoDialog('Error removing keywords', time=3000)
