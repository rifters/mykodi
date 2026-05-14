# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file trakt_stats_dialog.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
Trakt Statistics Dialog
Beautiful custom dialog showing user's watch statistics
'''

import os
import xbmcaddon
import xbmcgui

from ..modules import control
from ..modules import trakt
from ..modules.crewruntime import c


class TraktStatsDialog(xbmcgui.WindowXMLDialog):
    """
    Custom dialog for displaying Trakt user statistics.
    Shows movies, shows, and episodes watch data with visual progress indicators.
    """

    def __init__(self, *args, **kwargs):
        """Initialize dialog."""
        xbmcgui.WindowXMLDialog.__init__(self)
        self.stats = kwargs.get('stats', {})
        self.username = kwargs.get('username', 'User')
        self.action = None

    def onInit(self):
        """Initialize the dialog window with stats data."""
        try:
            c.log("[Trakt Stats] Initializing dialog")

            # Set username
            self.setProperty('username', self.username)

            # Parse and set movie stats
            movies = self.stats.get('movies', {})
            self.setProperty('movies_watched', str(movies.get('watched', 0)))
            self.setProperty('movies_plays', str(movies.get('plays', 0)))
            self.setProperty('movies_minutes', str(movies.get('minutes', 0)))
            self.setProperty('movies_collected', str(movies.get('collected', 0)))
            self.setProperty('movies_ratings', str(movies.get('ratings', 0)))

            # Convert minutes to hours and days for movies
            movie_minutes = movies.get('minutes', 0)
            movie_hours = movie_minutes / 60
            movie_days = movie_hours / 24
            self.setProperty('movies_hours', f'{movie_hours:.1f}')
            self.setProperty('movies_days', f'{movie_days:.1f}')

            # Parse and set show stats
            shows = self.stats.get('shows', {})
            self.setProperty('shows_watched', str(shows.get('watched', 0)))
            self.setProperty('shows_collected', str(shows.get('collected', 0)))
            self.setProperty('shows_ratings', str(shows.get('ratings', 0)))

            # Parse and set episode stats
            episodes = self.stats.get('episodes', {})
            self.setProperty('episodes_watched', str(episodes.get('watched', 0)))
            self.setProperty('episodes_plays', str(episodes.get('plays', 0)))
            self.setProperty('episodes_minutes', str(episodes.get('minutes', 0)))
            self.setProperty('episodes_collected', str(episodes.get('collected', 0)))
            self.setProperty('episodes_ratings', str(episodes.get('ratings', 0)))

            # Convert minutes to hours and days for episodes
            episode_minutes = episodes.get('minutes', 0)
            episode_hours = episode_minutes / 60
            episode_days = episode_hours / 24
            self.setProperty('episodes_hours', f'{episode_hours:.1f}')
            self.setProperty('episodes_days', f'{episode_days:.1f}')

            # Calculate total watch time
            total_minutes = movie_minutes + episode_minutes
            total_hours = total_minutes / 60
            total_days = total_hours / 24
            self.setProperty('total_hours', f'{total_hours:.1f}')
            self.setProperty('total_days', f'{total_days:.1f}')

            # Calculate progress bar percentages (relative to total content)
            total_content = movies.get('watched', 0) + episodes.get('watched', 0)
            if total_content > 0:
                movie_percent = (movies.get('watched', 0) / total_content) * 100
                episode_percent = (episodes.get('watched', 0) / total_content) * 100
            else:
                movie_percent = 0
                episode_percent = 0

            self.setProperty('movies_percent', f'{movie_percent:.0f}')
            self.setProperty('episodes_percent', f'{episode_percent:.0f}')

            # Set focus on Close button
            self.setFocusId(101)

            c.log(f"[Trakt Stats] Dialog initialized - Movies: {movies.get('watched', 0)}, "
                  f"Episodes: {episodes.get('watched', 0)}, Total hours: {total_hours:.1f}")

        except Exception as e:
            c.log(f"[Trakt Stats] Error in onInit: {e}", 1)

    def onClick(self, control_id):
        """Handle button clicks."""
        try:
            c.log(f"[Trakt Stats] Button clicked: {control_id}")

            if control_id == 101:
                # Close button
                c.log("[Trakt Stats] Closing dialog")
                self.action = 'close'
                self.close()

        except Exception as e:
            c.log(f"[Trakt Stats] Error in onClick: {e}", 1)

    def onAction(self, action):
        """Handle actions (back button, etc)."""
        try:
            action_id = action.getId()

            # Close on back/escape
            if action_id in (9, 10, 92, 216, 247, 257, 275, 61467, 61448):
                c.log("[Trakt Stats] Back/Escape pressed")
                self.action = 'close'
                self.close()

        except Exception as e:
            c.log(f"[Trakt Stats] Error in onAction: {e}", 1)
