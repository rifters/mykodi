# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file advanced_search.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

import xbmcgui
import json
import requests
from sqlite3 import dbapi2 as database
from urllib.parse import quote

from . import control
from . import cache
from . import keys
from .crewruntime import c

# Sort options
SORT_OPTIONS = {
    'Popularity': 'popularity.desc',
    'Rating': 'vote_average.desc',
    'Release Date': 'first_air_date.desc',
    'Title': 'original_title.asc'
}


def get_tmdb_genres(media_type='tv'):
    """Fetch genre list from TMDB API with 7-day cache"""
    try:
        def _fetch_genres():
            """Internal function to fetch genres from TMDB"""
            try:
                tmdb_key = control.setting('tm.personal_user') or control.setting('tm.user') or keys.tmdb_key
                endpoint = 'tv' if media_type == 'tv' else 'movie'
                url = f'https://api.themoviedb.org/3/genre/{endpoint}/list?api_key={tmdb_key}&language=en-US'

                if c.devmode:
                    c.log(f"[Advanced Search] Fetching {media_type} genres from TMDB")

                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    genres = data.get('genres', [])

                    if c.devmode:
                        c.log(f"[Advanced Search] Fetched {len(genres)} genres")

                    return genres
                else:
                    c.log(f"[Advanced Search] TMDB API error: {response.status_code}")
                    return []

            except Exception as e:
                c.log(f"[Advanced Search] Error fetching genres: {e}")
                return []

        # Cache for 7 days (168 hours)
        genres = cache.get(_fetch_genres, 168)
        return genres or []

    except Exception as e:
        c.log(f"[Advanced Search] Error in get_tmdb_genres: {e}")
        return []


class AdvancedSearchDialog(xbmcgui.WindowXMLDialog):
    """Advanced search dialog with multiple filter criteria"""

    def __init__(self, *args, **kwargs):
        super(AdvancedSearchDialog, self).__init__(*args, **kwargs)
        self.media_type = kwargs.get('media_type', 'tv')  # 'tv' or 'movie'
        self.filter_data = kwargs.get('filter_data', {})  # Pre-load from saved filter

        # Control IDs
        self.BUTTON_SEARCH = 100
        self.BUTTON_SAVE_FILTER = 101
        self.BUTTON_CANCEL = 102

        self.EDIT_KEYWORD = 200
        self.EDIT_YEAR_FROM = 201
        self.EDIT_YEAR_TO = 202
        self.EDIT_RATING = 203  # Changed from SLIDER to EDIT
        self.BUTTON_GENRE = 204  # Changed from SPINNER to BUTTON
        self.BUTTON_SORT = 205  # Changed from SPINNER to BUTTON

        self.result = None
        self.save_filter = False
        self.selected_genres = []  # List of selected genre dicts: [{'id': 28, 'name': 'Action'}, ...]
        self.selected_sort = 'Popularity'  # Currently selected sort option

    def onInit(self):
        """Initialize dialog with current filter values"""
        try:
            if c.devmode:
                c.log(f"[Advanced Search] Initializing dialog for {self.media_type}")

            # Initialize Sort spinner with options
            sort_control = self.getControl(self.SPINNER_SORT)
            for label in SORT_OPTIONS.keys():
                sort_control.addLabel(label)
            sort_control.setValue(0)  # Default to first option (Popularity)

            # Initialize Rating slider (0-100%, representing 0.0-10.0)
            rating_control = self.getControl(self.SLIDER_RATING)
            rating_control.setPercent(0)  # Default to 0 (no minimum rating)

            # Pre-fill from filter_data if loading saved filter
            if self.filter_data:
                if 'keyword' in self.filter_data and self.filter_data['keyword']:
                    self.getControl(self.EDIT_KEYWORD).setText(self.filter_data['keyword'])
                if 'year_from' in self.filter_data and self.filter_data['year_from']:
                    self.getControl(self.EDIT_YEAR_FROM).setText(str(self.filter_data['year_from']))
                if 'year_to' in self.filter_data and self.filter_data['year_to']:
                    self.getControl(self.EDIT_YEAR_TO).setText(str(self.filter_data['year_to']))

                # Pre-select genres if loading saved filter
                if 'genre_ids' in self.filter_data and self.filter_data['genre_ids']:
                    genre_id_str = self.filter_data['genre_ids']
                    if genre_id_str:
                        genre_ids = [int(gid) for gid in genre_id_str.split(',') if gid.strip()]
                        # Get full genre list to match IDs to names
                        all_genres = get_tmdb_genres(self.media_type)
                        self.selected_genres = [g for g in all_genres if g['id'] in genre_ids]

                # Pre-fill rating if present
                if 'min_rating' in self.filter_data and self.filter_data['min_rating']:
                    rating_percent = int(float(self.filter_data['min_rating']) * 10)
                    rating_control.setPercent(rating_percent)

                # Pre-select sort option if present
                if 'sort_by' in self.filter_data and self.filter_data['sort_by']:
                    # Find the matching label for this sort_by value
                    for label, value in SORT_OPTIONS.items():
                        if value == self.filter_data['sort_by']:
                            self.selected_sort = label
                            self.getControl(self.BUTTON_SORT).setLabel(label)
                            break

            self._update_genre_button()

        except Exception as e:
            c.log(f"[Advanced Search] Error in onInit: {e}")

    def onClick(self, controlId):
        """Handle button clicks"""
        if controlId == self.BUTTON_SEARCH:
            self._execute_search()
        elif controlId == self.BUTTON_SAVE_FILTER:
            self.save_filter = True
            self._execute_search()
        elif controlId == self.BUTTON_CANCEL:
            self.result = None
            self.close()
        elif controlId == self.BUTTON_GENRE:
            self._select_genres()
        elif controlId == self.BUTTON_SORT:
            self._select_sort()

    def _select_genres(self):
        """Open multiselect dialog for genre selection"""
        try:
            # Fetch genres from TMDB
            genres = get_tmdb_genres(self.media_type)
            if not genres:
                xbmcgui.Dialog().notification('Advanced Search', 'Failed to load genres', xbmcgui.NOTIFICATION_ERROR)
                return

            # Prepare for multiselect: list of names and preselected indices
            genre_names = [g['name'] for g in genres]
            preselected = []

            # Mark already selected genres
            for i, genre in enumerate(genres):
                if any(sg['id'] == genre['id'] for sg in self.selected_genres):
                    preselected.append(i)

            # Show multiselect dialog
            selected_indices = xbmcgui.Dialog().multiselect(
                'Select Genres (multiple allowed)',
                genre_names,
                preselect=preselected
            )

            if selected_indices is not None:
                # Update selected genres
                self.selected_genres = [genres[i] for i in selected_indices]
                self._update_genre_button()

                if c.devmode:
                    c.log(f"[Advanced Search] Selected genres: {[g['name'] for g in self.selected_genres]}")

        except Exception as e:
            c.log(f"[Advanced Search] Error in genre selection: {e}")

    def _update_genre_button(self):
        """Update genre button label with count"""
        try:
            if self.selected_genres:
                count = len(self.selected_genres)
                label = f"Genres ({count} selected)"
            else:
                label = "Select Genres..."

            self.getControl(self.BUTTON_GENRE).setLabel(label)
        except:
            pass

    def _select_sort(self):
        """Open selection dialog for sort option"""
        try:
            sort_labels = list(SORT_OPTIONS.keys())

            # Show select dialog
            selected = xbmcgui.Dialog().select('Sort Results By', sort_labels)

            if selected >= 0:
                self.selected_sort = sort_labels[selected]
                self.getControl(self.BUTTON_SORT).setLabel(self.selected_sort)

                if c.devmode:
                    c.log(f"[Advanced Search] Selected sort: {self.selected_sort}")

        except Exception as e:
            c.log(f"[Advanced Search] Error in sort selection: {e}")

    def _execute_search(self):
        """Gather filter values and execute search"""
        try:
            # Gather all filter values
            keyword = self.getControl(self.EDIT_KEYWORD).getText()
            year_from = self.getControl(self.EDIT_YEAR_FROM).getText()
            year_to = self.getControl(self.EDIT_YEAR_TO).getText()
            rating_text = self.getControl(self.EDIT_RATING).getText()

            # Get selected genres (now multiple IDs)
            genre_ids = ','.join(str(g['id']) for g in self.selected_genres) if self.selected_genres else ''

            # Get sort option from selected label
            sort_by = SORT_OPTIONS.get(self.selected_sort, 'popularity.desc')

            # Parse rating (text input 0-10)
            try:
                min_rating = float(rating_text) if rating_text and rating_text.strip() else 0.0
                # Clamp to 0-10 range
                min_rating = max(0.0, min(10.0, min_rating))
            except ValueError:
                min_rating = 0.0

            self.result = {
                'keyword': keyword.strip() if keyword else '',
                'genre_ids': genre_ids,  # Changed from genre_id to genre_ids (comma-separated)
                'year_from': int(year_from) if year_from and year_from.isdigit() else None,
                'year_to': int(year_to) if year_to and year_to.isdigit() else None,
                'min_rating': min_rating if min_rating > 0 else None,
                'sort_by': sort_by
            }

            if c.devmode:
                c.log(f"[Advanced Search] Filter data: {self.result}")

            self.close()

        except Exception as e:
            c.log(f"[Advanced Search] Error gathering filter data: {e}")
            self.result = None
            self.close()


class FilterManager:
    """Manage saved search filters"""

    def __init__(self):
        self.filters_db = control.searchFile  # Use same database as search history
        self._init_db()

    def _init_db(self):
        """Initialize filters table"""
        try:
            dbcon = database.connect(self.filters_db)
            dbcur = dbcon.cursor()

            # Create table if it doesn't exist
            dbcur.execute("""
                CREATE TABLE IF NOT EXISTS saved_filters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    keyword TEXT,
                    genre_ids TEXT,
                    year_from INTEGER,
                    year_to INTEGER,
                    min_rating REAL,
                    sort_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migrate existing tables - add missing columns
            # Check if columns exist by querying table info
            dbcur.execute("PRAGMA table_info(saved_filters)")
            columns = {row[1] for row in dbcur.fetchall()}  # row[1] is column name

            # Add missing columns if they don't exist
            if 'genre_ids' not in columns:
                c.log("[Filter Manager] Adding genre_ids column to saved_filters table")
                dbcur.execute("ALTER TABLE saved_filters ADD COLUMN genre_ids TEXT")

            if 'year_from' not in columns:
                c.log("[Filter Manager] Adding year_from column to saved_filters table")
                dbcur.execute("ALTER TABLE saved_filters ADD COLUMN year_from INTEGER")

            if 'year_to' not in columns:
                c.log("[Filter Manager] Adding year_to column to saved_filters table")
                dbcur.execute("ALTER TABLE saved_filters ADD COLUMN year_to INTEGER")

            if 'min_rating' not in columns:
                c.log("[Filter Manager] Adding min_rating column to saved_filters table")
                dbcur.execute("ALTER TABLE saved_filters ADD COLUMN min_rating REAL")

            if 'sort_by' not in columns:
                c.log("[Filter Manager] Adding sort_by column to saved_filters table")
                dbcur.execute("ALTER TABLE saved_filters ADD COLUMN sort_by TEXT")

            dbcon.commit()
            dbcur.close()
            dbcon.close()

        except Exception as e:
            c.log(f"[Filter Manager] Error initializing database: {e}")

    def save_filter(self, name, media_type, filter_data):
        """Save a filter with given name"""
        try:
            c.log(f"[Filter Manager] save_filter called: name='{name}', media_type='{media_type}', filter_data={filter_data}")
            c.log(f"[Filter Manager] Database path: {self.filters_db}")

            if not name or not name.strip():
                c.log(f"[Filter Manager] Empty name, returning False")
                return False

            dbcon = database.connect(self.filters_db)
            dbcur = dbcon.cursor()

            # Check if name exists
            dbcur.execute("SELECT id FROM saved_filters WHERE name = ? AND media_type = ?",
                         (name, media_type))
            existing = dbcur.fetchone()
            c.log(f"[Filter Manager] Existing filter check: {existing}")

            if existing:
                # Update existing
                c.log(f"[Filter Manager] Updating existing filter ID {existing[0]}")
                dbcur.execute("""
                    UPDATE saved_filters
                    SET keyword=?, genre_ids=?, year_from=?, year_to=?, min_rating=?, sort_by=?
                    WHERE id=?
                """, (
                    filter_data.get('keyword'),
                    filter_data.get('genre_ids'),
                    filter_data.get('year_from'),
                    filter_data.get('year_to'),
                    filter_data.get('min_rating'),
                    filter_data.get('sort_by'),
                    existing[0]
                ))
            else:
                # Insert new
                c.log(f"[Filter Manager] Inserting new filter")
                dbcur.execute("""
                    INSERT INTO saved_filters (name, media_type, keyword, genre_ids, year_from, year_to, min_rating, sort_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    name,
                    media_type,
                    filter_data.get('keyword'),
                    filter_data.get('genre_ids'),
                    filter_data.get('year_from'),
                    filter_data.get('year_to'),
                    filter_data.get('min_rating'),
                    filter_data.get('sort_by')
                ))

            dbcon.commit()
            c.log(f"[Filter Manager] Commit complete")

            # Verify it was saved
            dbcur.execute("SELECT COUNT(*) FROM saved_filters WHERE name = ? AND media_type = ?", (name, media_type))
            count = dbcur.fetchone()[0]
            c.log(f"[Filter Manager] Verification: {count} filter(s) with name '{name}' and media_type '{media_type}'")

            dbcur.close()
            dbcon.close()

            control.infoDialog(f"Filter '{name}' saved!", sound=True, icon='INFO')
            return True

        except Exception as e:
            c.log(f"[Filter Manager] Error saving filter: {e}")
            return False

    def get_filter(self, filter_id):
        """Get a single filter by ID"""
        try:
            dbcon = database.connect(self.filters_db)
            dbcur = dbcon.cursor()

            dbcur.execute("SELECT * FROM saved_filters WHERE id = ?", (filter_id,))
            row = dbcur.fetchone()

            dbcur.close()
            dbcon.close()

            if row:
                return {
                    'id': row[0],
                    'name': row[1],
                    'media_type': row[2],
                    'keyword': row[3],
                    'genre_id': row[4],
                    'year_from': row[5],
                    'year_to': row[6],
                    'min_rating': row[7],
                    'sort_by': row[8]
                }
            return None

        except Exception as e:
            c.log(f"[Filter Manager] Error getting filter: {e}")
            return None

    def list_filters(self, media_type):
        """List all saved filters for media type"""
        try:
            c.log(f"[Filter Manager] list_filters called for media_type='{media_type}'")
            c.log(f"[Filter Manager] Database path: {self.filters_db}")

            dbcon = database.connect(self.filters_db)
            dbcur = dbcon.cursor()

            dbcur.execute("SELECT id, name FROM saved_filters WHERE media_type = ? ORDER BY name",
                         (media_type,))
            rows = dbcur.fetchall()

            c.log(f"[Filter Manager] Found {len(rows)} filters: {rows}")

            dbcur.close()
            dbcon.close()

            return [(row[0], row[1]) for row in rows]

        except Exception as e:
            c.log(f"[Filter Manager] Error listing filters: {e}")
            import traceback
            c.log(f"[Filter Manager] Traceback: {traceback.format_exc()}")
            return []

    def delete_filter(self, filter_id):
        """Delete a filter"""
        try:
            dbcon = database.connect(self.filters_db)
            dbcur = dbcon.cursor()

            dbcur.execute("DELETE FROM saved_filters WHERE id = ?", (filter_id,))

            dbcon.commit()
            dbcur.close()
            dbcon.close()

            control.refresh()
            return True

        except Exception as e:
            c.log(f"[Filter Manager] Error deleting filter: {e}")
            return False

    def delete_all_filters(self, media_type):
        """Delete all filters for a given media type. Returns count of deleted filters."""
        try:
            dbcon = database.connect(self.filters_db)
            dbcur = dbcon.cursor()

            # Count filters before deletion
            dbcur.execute("SELECT COUNT(*) FROM saved_filters WHERE media_type = ?", (media_type,))
            count = dbcur.fetchone()[0]

            # Delete all filters for this media type
            dbcur.execute("DELETE FROM saved_filters WHERE media_type = ?", (media_type,))

            dbcon.commit()
            dbcur.close()
            dbcon.close()

            c.log(f"[Filter Manager] Deleted {count} {media_type} filter(s)")
            return count

        except Exception as e:
            c.log(f"[Filter Manager] Error deleting all filters: {e}")
            return 0


def get_keyword_ids(keyword_text, api_key):
    """
    Search for TMDB keyword IDs from text

    :param str keyword_text: Keyword search text
    :param str api_key: TMDB API key
    :return: Comma-separated keyword IDs or None
    """
    try:
        if not keyword_text or not keyword_text.strip():
            return None

        # Search TMDB for matching keywords
        url = f'https://api.themoviedb.org/3/search/keyword?api_key={api_key}&query={quote(keyword_text)}&page=1'
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])

            if results:
                # Get first matching keyword ID
                keyword_id = results[0].get('id')
                if keyword_id:
                    if c.devmode:
                        c.log(f"[Advanced Search] Keyword '{keyword_text}' -> ID {keyword_id}")
                    return str(keyword_id)

        return None

    except Exception as e:
        c.log(f"[Advanced Search] Error fetching keyword ID: {e}")
        return None


def show_advanced_search(media_type='tv', filter_data=None):
    """
    Show advanced search dialog

    :param str media_type: 'tv' or 'movie'
    :param dict filter_data: Pre-filled filter data (for editing saved filters)
    :return: tuple (filter_data, save_filter) or (None, False) if cancelled
    """
    try:
        addon_path = c.get_artwork_path()
        skin = c.appearance() or 'thecrew'

        dialog = AdvancedSearchDialog(
            'AdvancedSearch.xml',
            addon_path,
            skin,
            '1080i',
            media_type=media_type,
            filter_data=filter_data or {}
        )

        dialog.doModal()

        result = dialog.result
        save_filter = dialog.save_filter

        del dialog

        return result, save_filter

    except Exception as e:
        c.log(f"[Advanced Search] Error showing dialog: {e}")
        return None, False


def build_discover_url(tmdb_link, api_key, media_type, filter_data):
    """
    Build TMDB discover URL from filter data

    NOTE: TMDB's keyword system (with_keywords) is very sparsely populated for TV shows.
    Instead of using keywords in discover, we use /search when a keyword is provided,
    then filter the results by other criteria.

    :param str tmdb_link: Base TMDB API URL
    :param str api_key: TMDB API key
    :param str media_type: 'tv' or 'movie'
    :param dict filter_data: Filter criteria
    :return: Complete discover URL or search URL
    """
    try:
        endpoint = 'tv' if media_type == 'tv' else 'movie'

        # Normalize tmdb_link to ensure consistent URL construction
        base_url = tmdb_link.rstrip('/')

        # If keyword is provided, use search endpoint instead of discover
        # because TMDB's keyword tagging is very sparse for TV shows
        if filter_data.get('keyword'):
            keyword_encoded = quote(filter_data['keyword'])
            url = f"{base_url}/search/{endpoint}?api_key={api_key}&language=en-US&query={keyword_encoded}&page=1&include_adult=false"

            # Search endpoint supports year filtering
            year_from = filter_data.get('year_from')
            year_to = filter_data.get('year_to')

            # If both years are the same, use first_air_date_year (search supports this)
            if year_from and year_to and year_from == year_to:
                url += f"&first_air_date_year={year_from}"
            elif year_from and not year_to:
                url += f"&first_air_date_year={year_from}"
            # Otherwise, we'll need to post-filter by year range

            if c.devmode:
                c.log(f"[Advanced Search] Using search endpoint with keyword: {filter_data['keyword']}")

            # Note: Search doesn't support genre or rating filters - caller must post-filter
            return url

        # No keyword - use discover endpoint with all filters
        url = f"{base_url}/discover/{endpoint}?api_key={api_key}&language=en-US&page=1"

        if filter_data.get('genre_ids'):
            # Support comma-separated genre IDs (TMDB discover supports this)
            url += f"&with_genres={filter_data['genre_ids']}"

        if filter_data.get('year_from'):
            date_field = 'first_air_date' if media_type == 'tv' else 'release_date'
            url += f"&{date_field}.gte={filter_data['year_from']}-01-01"

        if filter_data.get('year_to'):
            date_field = 'first_air_date' if media_type == 'tv' else 'release_date'
            url += f"&{date_field}.lte={filter_data['year_to']}-12-31"

        if filter_data.get('min_rating'):
            url += f"&vote_average.gte={filter_data['min_rating']}"

        if filter_data.get('sort_by'):
            url += f"&sort_by={filter_data['sort_by']}"

        if c.devmode:
            c.log(f"[Advanced Search] Built URL: {url}")

        return url

    except Exception as e:
        c.log(f"[Advanced Search] Error building URL: {e}")
        return None
