# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file tvevening.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
TV Evening - Watch your shows in sequence
'''

import json
import random
import traceback
from urllib.parse import quote_plus

import xbmc
import xbmcgui

from . import control
from . import trakt
from .crewruntime import c
from . import tvevening_playlist_db
from . import tvevening_monitor
from ..models.episode import Episode


def is_trakt_enabled():
    """Check if Trakt is configured."""
    try:
        return trakt.get_trakt_credentials_info()
    except:
        return False


def get_show_playlist_setting():
    """Check if playlist preview should be shown."""
    try:
        return control.setting('tvevening.show_playlist') == 'true'
    except:
        return True


def get_gap_countdown():
    """Get gap countdown duration in seconds (default 60)."""
    try:
        return int(control.setting('tvevening.gap_countdown'))
    except:
        return 60


def get_randomize():
    """Check if show order should be randomized."""
    try:
        return control.setting('tvevening.randomize') == 'true'
    except:
        return False


def get_source_count():
    """Get number of shows to include (default 15)."""
    try:
        return int(control.setting('tvevening.source_count'))
    except:
        return 15


def get_min_episode_age():
    """Get minimum episode age in hours (default 48)."""
    try:
        return int(control.setting('tvevening.min_episode_age'))
    except:
        return 48


def show_skipped_notification(skipped_episodes, min_age_hours):
    """
    Show notification about skipped too-recent episodes.

    :param list skipped_episodes: List of skipped episode dicts
    :param int min_age_hours: Minimum age threshold that was used
    """
    try:
        if not skipped_episodes:
            return

        c.log(f"[TV Evening] Showing notification for {len(skipped_episodes)} skipped episodes")

        # Build notification message
        if len(skipped_episodes) == 1:
            ep = skipped_episodes[0]
            title = "Too Recent Episode Replaced"
            message = f"{ep['tvshowtitle']} S{ep['season']:02d}E{ep['episode']:02d}\n"
            message += f"Aired less than {min_age_hours}h ago - Replaced with different episode"
        else:
            title = f"{len(skipped_episodes)} Too Recent Episodes Replaced"
            message = f"The following episodes aired less than {min_age_hours}h ago:\n"
            for ep in skipped_episodes[:3]:  # Show first 3
                message += f"• {ep['tvshowtitle']} S{ep['season']:02d}E{ep['episode']:02d}\n"
            if len(skipped_episodes) > 3:
                message += f"• ...and {len(skipped_episodes) - 3} more\n"
            message += "\nReplaced with alternative episodes"

        # Show notification dialog (8 second auto-dismiss)
        control.dialog.notification(
            title,
            message,
            icon=control.addonIcon(),
            time=8000,
            sound=False
        )

    except Exception as e:
        c.log(f"[TV Evening] Error showing skipped notification: {e}")


def ask_duration():
    """
    Ask user for TV Evening duration using beautiful fullscreen dialog.

    :return: Duration in minutes or None if cancelled
    :rtype: int or None
    """
    try:
        # Get random backdrop from user's shows for visual appeal
        fanart = get_random_show_backdrop()

        c.log(f"[TV Evening] Showing duration dialog with backdrop: {fanart}")

        # Show custom duration dialog
        from . import tv_evening_duration_dialog
        duration = tv_evening_duration_dialog.show_tv_evening_duration_dialog(fanart or '')

        if duration:
            c.log(f"[TV Evening] User selected duration: {duration} minutes")
        else:
            c.log("[TV Evening] Duration selection cancelled")

        return duration

    except Exception as e:
        c.log(f"[TV Evening] Error showing duration dialog: {e}")
        c.log(f"[TV Evening] Traceback: {traceback.format_exc()}")

        # Fallback to simple dialog
        c.log("[TV Evening] Falling back to simple dialog")
        options = ['30 minutes', '1 hour', '2 hours', '3 hours', '4 hours', 'Custom']
        dialog = xbmcgui.Dialog()
        choice = dialog.select('How long is your TV Evening?', options)

        if choice == -1:  # Cancelled
            return None
        elif choice == 0:  # 30 minutes
            return 30
        elif choice == 1:  # 1 hour
            return 60
        elif choice == 2:  # 2 hours
            return 120
        elif choice == 3:  # 3 hours
            return 180
        elif choice == 4:  # 4 hours
            return 240
        elif choice == 5:  # Custom
            custom = dialog.numeric(0, 'Enter duration in minutes', '60')
            if custom:
                return int(custom)
            return None


def ask_duration_with_progress():
    """
    Ask user for TV Evening duration and return dialog for progress display.

    :return: Tuple of (duration in minutes, dialog object) or (None, None) if cancelled
    :rtype: tuple (int or None, dialog or None)
    """
    try:
        # Get random backdrop from user's shows for visual appeal
        fanart = get_random_show_backdrop()

        c.log(f"[TV Evening] Showing duration dialog with backdrop: {fanart}")

        # Show custom duration dialog with progress retention
        from . import tv_evening_duration_dialog
        duration, dialog = tv_evening_duration_dialog.show_tv_evening_duration_with_progress(fanart or '')

        if duration:
            c.log(f"[TV Evening] User selected duration: {duration} minutes, dialog retained")
        else:
            c.log("[TV Evening] Duration selection cancelled")

        return (duration, dialog)

    except Exception as e:
        c.log(f"[TV Evening] Error showing duration dialog: {e}")
        c.log(f"[TV Evening] Traceback: {traceback.format_exc()}")

        # Fallback returns no dialog
        return (None, None)


def get_random_show_backdrop():
    """
    Get a random backdrop from user's Trakt shows for visual appeal.

    :return: Backdrop URL or None
    :rtype: str or None
    """
    try:
        from . import keys, client
        import random

        c.log("[TV Evening] Getting random backdrop from Trakt shows")

        # Get user's shows from Trakt
        url = "https://api.trakt.tv/sync/watched/shows?extended=full&limit=20"
        result = trakt.getTraktAsJson(url)

        if not result or len(result) == 0:
            c.log("[TV Evening] No Trakt shows for backdrop")
            return None

        # Pick random show
        random_show = random.choice(result)
        show_data = random_show.get('show', {})
        show_tmdb = str(show_data.get('ids', {}).get('tmdb', '0'))

        if not show_tmdb or show_tmdb == '0':
            c.log("[TV Evening] No TMDB ID for random show")
            return None

        # Fetch backdrop from TMDB
        tmdb_key = keys.tmdb_key
        show_url = f'https://api.themoviedb.org/3/tv/{show_tmdb}?api_key={tmdb_key}'
        show_response = client.request(show_url, timeout='10')

        if show_response:
            show_json = json.loads(show_response)
            backdrop_path = show_json.get('backdrop_path', '')
            if backdrop_path:
                backdrop_url = f'https://image.tmdb.org/t/p/original{backdrop_path}'
                c.log(f"[TV Evening] Got backdrop from {show_data.get('title', 'Unknown')}")
                return backdrop_url

        c.log("[TV Evening] Could not get backdrop")
        return None

    except Exception as e:
        c.log(f"[TV Evening] Error getting backdrop: {e}")
        return None


def fetch_next_episodes_data():
    """
    Fetch next episodes data from Trakt without displaying.
    Returns list of episode dicts ready for playback.

    :return: List of episode data dicts
    :rtype: list
    """
    try:
        c.log("[TV Evening] Fetching next episodes from Trakt progress API")

        # Get progress from Trakt API (same endpoint as Progress indexer)
        url = "https://api.trakt.tv/sync/watched/shows?extended=full"
        result = trakt.getTraktAsJson(url)

        if not result:
            c.log("[TV Evening] No Trakt progress data")
            return []

        c.log(f"[TV Evening] Got progress data for {len(result)} shows")

        episodes = []

        for item in result:
            try:
                show_data = item.get('show', {})
                show_title = show_data.get('title', 'Unknown')
                show_imdb = show_data.get('ids', {}).get('imdb', '0')
                show_tmdb = str(show_data.get('ids', {}).get('tmdb', '0'))
                show_year = str(show_data.get('year', ''))

                seasons = item.get('seasons', [])
                if isinstance(seasons, dict):
                    seasons = list(seasons.values())

                # Find highest watched episode
                max_season = 0
                max_episode = 0
                last_watched_at = None

                sorted_seasons = sorted(
                    [s for s in seasons if s.get('number', 0) > 0],
                    key=lambda s: s.get('number', 0)
                )

                for s in sorted_seasons:
                    season_num = s.get('number')
                    eps = s.get('episodes') or []

                    if eps:
                        max_ep_in_season = max(e.get('number', 0) for e in eps)
                        if season_num > max_season or (season_num == max_season and max_ep_in_season > max_episode):
                            max_season = season_num
                            max_episode = max_ep_in_season
                            # Get timestamp
                            for ep in eps:
                                if ep.get('number') == max_ep_in_season:
                                    ep_timestamp = ep.get('last_watched_at')
                                    if ep_timestamp:
                                        last_watched_at = ep_timestamp
                                    break

                # Determine next episode (NO API CALLS - just math)
                if max_season == 0:
                    next_season = 1
                    next_episode = 1
                else:
                    next_season = max_season
                    next_episode = max_episode + 1

                # Create episode dict with minimal data (no metadata fetching)
                # Validation will happen later for only the episodes we actually need
                episode = {
                    'tvshowtitle': show_title,
                    'title': f"Episode {next_episode}",  # Placeholder, will be updated after validation
                    'season': next_season,
                    'episode': next_episode,
                    'showimdb': show_imdb,
                    'showtmdb': show_tmdb,
                    'year': show_year,
                    'duration': 45,  # Default, will be updated after metadata fetch
                    'plot': '',
                    'thumb': '',
                    'poster': '',
                    'fanart': '',
                    'last_watched_at': last_watched_at or '1900-01-01T00:00:00.000Z'
                }

                episodes.append(episode)

            except Exception as e:
                c.log(f"[TV Evening] Error processing show: {e}")
                continue

        # Sort by last_watched_at (most recent first)
        episodes.sort(key=lambda x: x.get('last_watched_at', '1900-01-01T00:00:00.000Z'), reverse=True)

        c.log(f"[TV Evening] Returning {len(episodes)} next episodes (no validation yet - will validate selected episodes only)")
        return episodes

    except Exception as e:
        c.log(f"[TV Evening] Error fetching next episodes: {e}")
        c.log(f"[TV Evening] Traceback: {traceback.format_exc()}")
        return []


def validate_episode_exists(episode):
    """
    Check if episode exists on TMDB (lightweight validation).
    If not, tries next season episode 1.

    :param dict episode: Episode dict with showtmdb, season, episode
    :return: Updated episode dict or None if validation failed
    :rtype: dict or None
    """
    try:
        show_title = episode.get('tvshowtitle', 'Unknown')
        show_tmdb = episode.get('showtmdb', '0')
        season = episode.get('season', 0)
        ep_num = episode.get('episode', 0)

        if show_tmdb == '0':
            c.log(f"[TV Evening] {show_title} - No TMDB ID, skipping validation")
            return episode  # Can't validate without TMDB ID, return as-is

        # Create Episode object for validation
        episode_obj = Episode.from_trakt_progress(
            {
                'title': episode.get('tvshowtitle', ''),
                'year': episode.get('year', ''),
                'ids': {
                    'imdb': episode.get('showimdb', '0'),
                    'tmdb': show_tmdb
                }
            },
            season,
            ep_num
        )

        if not episode_obj:
            c.log(f"[TV Evening] Failed to create Episode object for {show_title}")
            return None

        # Try to fetch metadata (validates existence)
        c.log(f"[TV Evening] Validating {show_title} S{season:02d}E{ep_num:02d}")
        validation_success = episode_obj.fetch_tmdb_metadata()

        # If episode doesn't exist and not first episode, try next season E01
        if not validation_success and ep_num > 1:
            c.log(f"[TV Evening] S{season:02d}E{ep_num:02d} doesn't exist, trying S{season+1:02d}E01")
            season += 1
            ep_num = 1

            # Try validating next season E01
            episode_obj = Episode.from_trakt_progress(
                {
                    'title': episode.get('tvshowtitle', ''),
                    'year': episode.get('year', ''),
                    'ids': {
                        'imdb': episode.get('showimdb', '0'),
                        'tmdb': show_tmdb
                    }
                },
                season,
                ep_num
            )

            if episode_obj:
                validation_success = episode_obj.fetch_tmdb_metadata()

        # Skip if still failed
        if not validation_success:
            c.log(f"[TV Evening] Validation failed for {show_title} - skipping")
            return None

        c.log(f"[TV Evening] (OK) Validated {show_title} S{season:02d}E{ep_num:02d}")

        # Parse cast data (castwiththumb contains guest_stars from TMDB)
        # Split into leads (first 3) and guests (next 3) for countdown display - 6 total (2 rows of 3)
        all_cast = episode_obj.castwiththumb if episode_obj else []
        cast_leads = all_cast[:3]  # First 3 as main cast
        cast_guests = all_cast[3:6]  # Next 3 as guest stars (6 total for 2x3 grid)

        c.log(f"[TV Evening] Cast data: {len(cast_leads)} leads, {len(cast_guests)} guests")

        # Prepare cast data with full TMDB URLs
        cast_leads_data = [
            {
                'name': c.get('name', ''),
                'character': c.get('role', ''),
                'thumb': c.get('thumbnail', '')
            }
            for c in cast_leads
        ]

        # Log first lead's thumbnail to verify full URL
        if cast_leads_data:
            c.log(f"[TV Evening] Sample lead thumb URL: {cast_leads_data[0].get('thumb', 'none')[:80]}")

        # Update episode dict with validated data INCLUDING cast
        episode.update({
            'season': season,
            'episode': ep_num,
            'title': episode_obj.title or f"Episode {ep_num}",
            'duration': episode_obj.duration or 45,
            'plot': episode_obj.plot or '',
            'thumb': episode_obj.thumb or '',
            'cast_leads': cast_leads_data,
            'cast_guests': [
                {
                    'name': c.get('name', ''),
                    'character': c.get('role', ''),
                    'thumb': c.get('thumbnail', '')
                }
                for c in cast_guests
            ]
        })

        return episode

    except Exception as e:
        c.log(f"[TV Evening] Error validating episode: {e}")
        return None


def validate_episodes_parallel(episodes):
    """
    Validate episodes in parallel using ThreadPool.
    Much faster than sequential validation when checking 5-10 episodes.

    :param list episodes: List of episode dicts to validate
    :return: List of validated episode dicts
    :rtype: list
    """
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        c.log(f"[TV Evening] Validating {len(episodes)} episodes in parallel...")

        validated = []

        # Use ThreadPool to validate episodes in parallel
        # Max 10 workers to avoid overwhelming API
        with ThreadPoolExecutor(max_workers=min(10, len(episodes))) as executor:
            # Submit all validation tasks
            future_to_ep = {executor.submit(validate_episode_exists, ep): ep for ep in episodes}

            # Collect results as they complete
            for future in as_completed(future_to_ep):
                result = future.result()
                if result:
                    validated.append(result)

        c.log(f"[TV Evening] Validated {len(validated)}/{len(episodes)} episodes successfully")
        return validated

    except Exception as e:
        c.log(f"[TV Evening] Error in parallel validation: {e}")
        c.log(f"[TV Evening] Traceback: {traceback.format_exc()}")
        # Fallback to sequential validation
        c.log("[TV Evening] Falling back to sequential validation...")
        validated = []
        for ep in episodes:
            result = validate_episode_exists(ep)
            if result:
                validated.append(result)
        return validated


def get_recently_watched_shows():
    """
    Get recently watched shows from Trakt.

    :return: List of show progress data
    :rtype: list
    """
    try:
        if not is_trakt_enabled():
            control.dialog.ok('Trakt Required', 'TV Evening requires Trakt to be configured.\n\nPlease set up Trakt in settings.')
            return []

        c.log("[TV Evening] Getting recently watched shows from Trakt")

        # Get number of shows from settings
        limit = get_source_count()

        # Get progress data from Trakt sync database
        # This returns shows with watch progress from local database
        progress_data = trakt.get_trakt_progress('episode')

        if not progress_data:
            c.log("[TV Evening] No progress data from Trakt")
            return []

        # Group episodes by show and get unique shows
        shows_dict = {}
        for ep in progress_data:
            show_imdb = ep.get('showimdb')
            if show_imdb and show_imdb not in shows_dict:
                shows_dict[show_imdb] = {
                    'show': {
                        'title': ep.get('tvshowtitle', 'Unknown Show'),
                        'year': ep.get('showyear', ''),
                        'ids': {
                            'imdb': show_imdb,
                            'tmdb': ep.get('showtmdb', ''),
                            'tvdb': ep.get('showtvdb', '')
                        }
                    },
                    'last_watched': ep.get('paused_at', '')
                }

        # Sort by last watched and limit
        shows_list = sorted(
            shows_dict.values(),
            key=lambda x: x.get('last_watched', ''),
            reverse=True
        )[:limit]

        c.log(f"[TV Evening] Got {len(shows_list)} unique shows from Trakt")
        return shows_list

    except Exception as e:
        c.log(f"[TV Evening] Error getting recently watched shows: {e}")
        c.log(f"[TV Evening] Traceback: {traceback.format_exc()}")
        return []


def get_next_episode_for_show(show_data):
    """
    Get next unwatched episode for a show.

    :param dict show_data: Show progress data from Trakt
    :return: Episode data dict or None
    :rtype: dict or None
    """
    try:
        show = show_data.get('show', {})
        show_imdb = show.get('ids', {}).get('imdb', '')
        show_tmdb = show.get('ids', {}).get('tmdb', '')

        if not show_imdb:
            c.log(f"[TV Evening] No IMDB for {show.get('title', 'Unknown')}")
            return None

        c.log(f"[TV Evening] Getting next episode for {show.get('title', 'Unknown')} (IMDB: {show_imdb})")

        # Try to get from Trakt progress API
        try:
            from . import client
            url = f'https://api.trakt.tv/shows/{show_imdb}/progress/watched?hidden=false&specials=false&count_specials=false'
            headers = {
                'Content-Type': 'application/json',
                'trakt-api-version': '2',
                'trakt-api-key': trakt.CLIENT_ID
            }

            # Add auth if available
            token = control.setting('trakt.token')
            if token:
                headers['Authorization'] = f'Bearer {token}'

            result = client.request(url, headers=headers)
            if result:
                progress_data = json.loads(result)
                next_ep = progress_data.get('next_episode')

                if next_ep:
                    episode_data = {
                        'tvshowtitle': show.get('title', 'Unknown Show'),
                        'year': show.get('year', ''),
                        'imdb': show_imdb,
                        'tmdb': show_tmdb,
                        'tvdb': show.get('ids', {}).get('tvdb', ''),
                        'season': next_ep.get('season', 1),
                        'episode': next_ep.get('number', 1),
                        'title': next_ep.get('title', 'Unknown Episode'),
                        'plot': next_ep.get('overview', ''),
                        'thumb': '',
                        'runtime': next_ep.get('runtime', 45)
                    }

                    c.log(f"[TV Evening] Next episode: {episode_data['tvshowtitle']} S{episode_data['season']:02d}E{episode_data['episode']:02d}")
                    return episode_data
        except Exception as e:
            c.log(f"[TV Evening] Error getting next episode from Trakt API: {e}")

        # Fallback: No next episode found
        c.log(f"[TV Evening] No next episode for {show.get('title', 'Unknown')}")
        return None

    except Exception as e:
        c.log(f"[TV Evening] Error getting next episode: {e}")
        c.log(f"[TV Evening] Traceback: {traceback.format_exc()}")
        return None


def fetch_episode_air_date(episode):
    """
    Fetch ONLY the air date for an episode (lightweight, single API call).

    :param dict episode: Episode data dict with showtmdb, season, and episode
    :return: None (updates episode dict with air_date)
    """
    show_tmdb = episode.get('showtmdb')
    season = episode.get('season')
    ep_num = episode.get('episode')
    show_title = episode.get('tvshowtitle', 'Unknown')

    if not show_tmdb or show_tmdb == '0':
        return

    try:
        from . import client
        from .crewruntime import keys

        tmdb_key = keys.tmdb_key

        # Single API call to get episode details (includes air_date)
        episode_url = f'https://api.themoviedb.org/3/tv/{show_tmdb}/season/{season}/episode/{ep_num}?api_key={tmdb_key}'
        episode_data = client.request(episode_url, timeout='10')
        if episode_data:
            episode_json = json.loads(episode_data)
            air_date = episode_json.get('air_date')
            if air_date:
                episode['air_date'] = air_date
    except Exception as e:
        c.log(f"[TV Evening] Error fetching air date for {show_title} S{season:02d}E{ep_num:02d}: {e}")


def fetch_episode_artwork(episode):
    """
    Fetch season poster, show fanart, episode title and plot from TMDB.

    :param dict episode: Episode data dict with showtmdb, season, and episode
    :return: None (updates episode dict in place)
    """
    show_tmdb = episode.get('showtmdb')
    season = episode.get('season')
    ep_num = episode.get('episode')
    show_title = episode.get('tvshowtitle', 'Unknown')

    if not show_tmdb or show_tmdb == '0':
        return

    try:
        from . import keys, client
        import json

        tmdb_key = keys.tmdb_key

        # Fetch episode details (title, plot, runtime) - CACHED
        from . import cache as caching
        details = caching.get_episode_details(show_tmdb, season, ep_num)
        if details:
            if details.get('title'):
                episode['title'] = details['title']
            if details.get('plot'):
                episode['plot'] = details['plot']
            if details.get('duration'):
                episode['duration'] = details['duration']
            if details.get('air_date'):
                episode['air_date'] = details['air_date']
                c.log(f"[TV Evening] Got air date for {show_title} S{season:02d}E{ep_num:02d}: {details['air_date']}")

            c.log(f"[TV Evening] Got episode details for {show_title} S{season:02d}E{ep_num:02d}")

        # Fetch season poster - CACHED
        poster_url = caching.get_season_artwork(show_tmdb, season)
        if poster_url:
            episode['thumb'] = poster_url
            episode['poster'] = poster_url
            c.log(f"[TV Evening] Got season {season} poster for {show_title}")

        # Fetch show fanart for background - CACHED
        backdrop_url = caching.get_show_artwork(show_tmdb)
        if backdrop_url:
            episode['fanart'] = backdrop_url

    except Exception as art_err:
        c.log(f"[TV Evening] Could not fetch artwork for {show_title}: {art_err}")


def build_playlist(duration_minutes, progress_dialog=None):
    """
    Build TV Evening playlist using existing Next Episodes data.
    Filters out episodes that aired too recently (< min_episode_age hours).
    OPTIMIZED: Only fetches artwork for final selected episodes.

    :param int duration_minutes: Target duration in minutes
    :param progress_dialog: Optional dialog to update progress messages
    :return: List of episode data dicts
    :rtype: list
    """
    try:
        from datetime import datetime, timedelta

        c.log(f"[TV Evening] Building playlist for {duration_minutes} minutes")
        c.log("[TV Evening] ========== FIRST PROGRESS UPDATE ==========")
        if progress_dialog:
            c.log("[TV Evening] Calling update_progress('Fetching your watched shows from Trakt...', 10%)")
            progress_dialog.update_progress('Fetching your watched shows from Trakt...\n\nPlease wait while we connect to your account.', 10)
            c.log("[TV Evening] update_progress() returned")
        else:
            c.log("[TV Evening] WARNING: progress_dialog is None!")

        # Get minimum episode age setting
        min_age_hours = get_min_episode_age()
        c.log(f"[TV Evening] Minimum episode age: {min_age_hours} hours")

        # Fetch next episodes data without displaying
        c.log("[TV Evening] Fetching next episodes from Trakt")
        all_episodes = fetch_next_episodes_data()
        c.log("[TV Evening] ========== SECOND PROGRESS UPDATE ==========")
        if progress_dialog:
            msg = f'Selecting episodes for your {duration_minutes} minute evening...\n\nFiltering by air date and runtime.'
            c.log(f"[TV Evening] Calling update_progress('{msg}', 30%)")
            progress_dialog.update_progress(msg, 30)
            c.log("[TV Evening] update_progress() returned")
        else:
            c.log("[TV Evening] WARNING: progress_dialog is None!")

        if not all_episodes:
            control.dialog.ok('No Episodes Found', 'Could not find any unwatched episodes.\n\nYou\'re all caught up!')
            return []

        c.log(f"[TV Evening] Found {len(all_episodes)} next episodes available")

        # Randomize if enabled
        if get_randomize():
            c.log("[TV Evening] Randomizing episode order")
            random.shuffle(all_episodes)

        # OPTIMIZATION: Only fetch air_date if filtering is enabled
        if min_age_hours > 0:
            c.log(f"[TV Evening] Fetching air dates for filtering (lightweight API calls)")
            for ep in all_episodes:
                fetch_episode_air_date(ep)

        # Calculate cutoff time for air date filtering
        now = datetime.utcnow()
        cutoff_time = now - timedelta(hours=min_age_hours)
        c.log(f"[TV Evening] Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        if min_age_hours > 0:
            c.log(f"[TV Evening] Cutoff time ({min_age_hours}h ago): {cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # Fill playlist to target duration with air-date filtering
        playlist = []
        skipped = []
        total_runtime = 0
        reserve_buffer = 45  # One episode worth of buffer (reserve episode)
        target_runtime = duration_minutes + reserve_buffer
        c.log(f"[TV Evening] Target: {duration_minutes}min + {reserve_buffer}min reserve = {target_runtime}min")

        for ep in all_episodes:
            if total_runtime >= target_runtime:
                break

            # Check air date if available (skip if 0 hours = disabled)
            air_date_str = ep.get('air_date')
            if air_date_str and min_age_hours > 0:
                try:
                    # Parse TMDB air_date format: "YYYY-MM-DD"
                    air_date = datetime.strptime(air_date_str, '%Y-%m-%d')

                    # Check if episode aired too recently
                    if air_date > cutoff_time:
                        hours_ago = (now - air_date).total_seconds() / 3600
                        c.log(f"[TV Evening] SKIPPING {ep['tvshowtitle']} S{ep['season']:02d}E{ep['episode']:02d} - Aired {hours_ago:.1f}h ago (min: {min_age_hours}h)")
                        skipped.append(ep)
                        continue
                    else:
                        hours_ago = (now - air_date).total_seconds() / 3600
                        c.log(f"[TV Evening] ACCEPTED {ep['tvshowtitle']} S{ep['season']:02d}E{ep['episode']:02d} - Aired {hours_ago:.1f}h ago")
                except (ValueError, TypeError) as e:
                    c.log(f"[TV Evening] Could not parse air_date '{air_date_str}' for {ep.get('tvshowtitle', 'Unknown')}: {e}")
                    # If we can't parse air_date, include the episode (fail-safe)

            playlist.append(ep)
            total_runtime += int(ep.get('duration', 45))

        # Add replacements for skipped episodes from remaining pool
        if skipped:
            c.log(f"[TV Evening] Skipped {len(skipped)} too-recent episodes, adding replacements...")

            # Find episodes not yet in playlist or skipped list
            used_episodes = set((ep['showimdb'], ep['season'], ep['episode']) for ep in (playlist + skipped))
            replacement_pool = [ep for ep in all_episodes
                              if (ep['showimdb'], ep['season'], ep['episode']) not in used_episodes]

            for skipped_ep in skipped:
                if not replacement_pool:
                    c.log("[TV Evening] No more replacement episodes available")
                    break

                replacement = replacement_pool.pop(0)
                playlist.append(replacement)
                total_runtime += int(replacement.get('duration', 45))
                c.log(f"[TV Evening] Added replacement: {replacement['tvshowtitle']} S{replacement['season']:02d}E{replacement['episode']:02d}")

        c.log(f"[TV Evening] Selected {len(playlist)} episodes for playlist")

        # VALIDATE episodes in parallel (checks if they exist on TMDB)
        # This catches issues like The Rookie S07E19 (doesn't exist, finale was S07E18)
        c.log(f"[TV Evening] Validating {len(playlist)} episodes in parallel...")
        c.log("[TV Evening] ========== VALIDATION PROGRESS UPDATE ==========")
        if progress_dialog:
            msg = f'Validating {len(playlist)} episodes with TMDB...\n\nChecking if episodes exist and fetching metadata.'
            c.log(f"[TV Evening] Calling update_progress('{msg}', 40%)")
            progress_dialog.update_progress(msg, 40)
            c.log("[TV Evening] update_progress() returned")
        else:
            c.log("[TV Evening] WARNING: progress_dialog is None!")

        validated_playlist = validate_episodes_parallel(playlist)

        if len(validated_playlist) < len(playlist):
            c.log(f"[TV Evening] WARNING: {len(playlist) - len(validated_playlist)} episodes failed validation")
            # If we lost episodes, try to add more from remaining pool
            shortage = len(playlist) - len(validated_playlist)
            if shortage > 0:
                used_episodes = set((ep['showimdb'], ep['season'], ep['episode']) for ep in (validated_playlist + skipped))
                replacement_pool = [ep for ep in all_episodes
                                  if (ep['showimdb'], ep['season'], ep['episode']) not in used_episodes]

                if replacement_pool:
                    c.log(f"[TV Evening] Adding {min(shortage, len(replacement_pool))} replacements for failed validations")
                    additional = validate_episodes_parallel(replacement_pool[:shortage])
                    validated_playlist.extend(additional)

        playlist = validated_playlist
        c.log(f"[TV Evening] Validated playlist now has {len(playlist)} episodes")

        # Recalculate total runtime after validation
        total_runtime = sum(int(ep.get('duration', 45)) for ep in playlist)

        # OPTIMIZATION: NOW fetch artwork only for the final validated episodes
        c.log(f"[TV Evening] Fetching artwork for {len(playlist)} selected episodes (MAX {len(playlist)} API calls)")
        c.log("[TV Evening] ========== ARTWORK PROGRESS UPDATE ==========")
        if progress_dialog:
            msg = f'Loading cast info and artwork...\n\nFetching thumbnails for {len(playlist)} episodes.'
            c.log(f"[TV Evening] Calling update_progress('{msg}', 50%)")
            progress_dialog.update_progress(msg, 50)
            c.log("[TV Evening] update_progress() returned")
        else:
            c.log("[TV Evening] WARNING: progress_dialog is None!")
        for i, ep in enumerate(playlist, 1):
            if progress_dialog and i % 2 == 0:  # Update every 2 episodes to avoid too many updates
                # Calculate progress: 50% at start, 100% at end
                progress_pct = 50 + int((i / len(playlist)) * 50)
                progress_dialog.update_progress(
                    f'Loading cast info and artwork...\n\nProgress: {i}/{len(playlist)} episodes',
                    progress_pct
                )
            fetch_episode_artwork(ep)

        # Final progress update - 100% complete
        if progress_dialog:
            progress_dialog.update_progress(
                f'Playlist ready!\\n\\n{len(playlist)} episodes selected.',
                100
            )

        c.log(f"[TV Evening] Built playlist with {len(playlist)} episodes, total runtime: {total_runtime} minutes")

        # Notify user if episodes were skipped
        if skipped:
            show_skipped_notification(skipped, min_age_hours)

        return playlist

    except Exception as e:
        c.log(f"[TV Evening] Error building playlist: {e}")
        c.log(f"[TV Evening] Traceback: {traceback.format_exc()}")
        return []


def show_playlist_preview(playlist):
    """
    Show playlist preview to user with options using custom dialog.

    :param list playlist: List of episode data dicts
    :return: User choice ('play', 'first', or None for cancel)
    :rtype: str or None
    """
    try:
        from . import tv_evening_dialog

        user_action = tv_evening_dialog.show_tv_evening_playlist(playlist)

        c.log(f"[TV Evening] User action from dialog: {user_action}")
        return user_action

    except Exception as e:
        c.log(f"[TV Evening] Error showing preview: {e}")
        c.log(f"[TV Evening] Traceback: {traceback.format_exc()}")
        return 'play'  # Default to play on error


def play_playlist(playlist):
    """
    Play TV Evening playlist using database-backed playlist with Kodi playback.

    Stores episodes in SQLite database for reliable state tracking,
    while using Kodi's playlist for actual playback.

    :param list playlist: List of episode data dicts
    """
    try:
        if not playlist:
            return

        c.log(f"[TV Evening] Building playlist with {len(playlist)} episodes")

        # Get database instance
        db = tvevening_playlist_db.get_playlist_db()

        # Clear both Kodi playlist and database
        c.log("[TV Evening] Clearing playlist database and Kodi playlist")
        db.clear_playlist()

        # Create Kodi video playlist
        kodi_playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        kodi_playlist.clear()

        # Add all episodes to both database and Kodi playlist
        for i, episode in enumerate(playlist):
            c.log(f"[TV Evening] Adding episode {i+1}/{len(playlist)}: {episode['tvshowtitle']} S{episode['season']:02d}E{episode['episode']:02d}")

            # Build playback URL - use SHOW IDs (showimdb/showtmdb) not episode IDs
            url = 'plugin://plugin.video.thecrew/?action=play'
            url += f"&title={quote_plus(str(episode.get('title', '')))}"
            url += f"&year={quote_plus(str(episode.get('year', '')))}"
            url += f"&imdb={quote_plus(str(episode.get('showimdb', '0')))}"
            url += f"&tmdb={quote_plus(str(episode.get('showtmdb', '0')))}"
            url += f"&season={quote_plus(str(episode['season']))}"
            url += f"&episode={quote_plus(str(episode['episode']))}"
            url += f"&tvshowtitle={quote_plus(str(episode.get('tvshowtitle', '')))}"
            url += "&select=2"  # Force auto-play (2 = auto-select best source)

            # Add URL to episode data for database storage
            episode['url'] = url

            # Store in database (position is zero-based)
            db.add_episode(i, episode)
            c.log(f"[TV Evening] Stored episode {i} in database")

            # Create list item for Kodi playlist
            listitem = control.item(label=f"{episode['tvshowtitle']} - S{episode['season']:02d}E{episode['episode']:02d}")
            listitem.setInfo('video', {
                'title': episode.get('title', ''),
                'tvshowtitle': episode.get('tvshowtitle', ''),
                'season': episode['season'],
                'episode': episode['episode'],
                'plot': episode.get('plot', '')
            })
            if episode.get('thumb'):
                listitem.setArt({'thumb': episode['thumb']})

            # Add to Kodi playlist
            kodi_playlist.add(url, listitem)
            c.log(f"[TV Evening] Added to Kodi playlist position {i}: {episode['tvshowtitle']} S{episode['season']:02d}E{episode['episode']:02d}")

        c.log(f"[TV Evening] Playlist built: Kodi={kodi_playlist.size()} items, DB={db.get_playlist_size()} items")

        # Store metadata about this playlist session
        db.set_metadata('playlist_started', xbmc.getInfoLabel('System.Date'))
        db.set_metadata('playlist_total', len(playlist))

        # Verify playlist contents
        for i in range(kodi_playlist.size()):
            item = kodi_playlist[i]
            if item:
                path = item.getPath() if hasattr(item, 'getPath') else 'unknown'
                label = item.getLabel() if hasattr(item, 'getLabel') else 'unknown'
                c.log(f"[TV Evening] Kodi Playlist[{i}]: {label} - {path[:100]}...")

        # Verify playlist was created
        if kodi_playlist.size() == 0 or db.get_playlist_size() == 0:
            c.log("[TV Evening] ERROR: Playlist is empty after building!")
            control.dialog.ok('Error', 'Failed to build playlist.\n\nPlease try again.')
            return

        # Start TV Evening Monitor BEFORE playback
        # This ensures player.onPlayBackStarted sees active monitor and skips legacy system
        c.log("[TV Evening] Starting TV Evening Monitor (BEFORE playback)")

        try:
            # Get all episodes from database
            monitor_episodes = db.get_all_episodes()
            c.log(f"[TV Evening] Loaded {len(monitor_episodes)} episodes for monitoring")

            # Create and start monitor BEFORE player.play()
            monitor = tvevening_monitor.start_tv_evening_session(monitor_episodes)
            c.log("[TV Evening] Monitor started successfully with session_active=True")

        except Exception as monitor_error:
            c.log(f"[TV Evening] Error starting monitor: {monitor_error}")
            c.log(f"[TV Evening] Traceback: {traceback.format_exc()}")
            control.dialog.ok('Error', 'Failed to start TV Evening monitor.\n\nPlease try again.')
            return

        # NOW start playlist playback - monitor is ready
        player = xbmc.Player()
        player.play(kodi_playlist, startpos=0)

        c.log("[TV Evening] Started playback, waiting for player to initialize...")

        # Wait a moment for playback to initiate
        import time
        time.sleep(0.5)

        # Verify playback started
        playlist_after = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        c.log(f"[TV Evening] After play() call - Playlist size: {playlist_after.size()}, Player active: {player.isPlaying()}")

        # Skip info notification - fullscreen overlay handles this
        # control.infoDialog(f'Playing {len(playlist)} episodes', heading='TV Evening', time=3000)
        c.log(f"[TV Evening] Skipping infoDialog (overlay active)")

    except Exception as e:
        c.log(f"[TV Evening] Error playing playlist: {e}")
        c.log(f"[TV Evening] Traceback: {traceback.format_exc()}")


def show_gap_countdown(next_episode, countdown_seconds):
    """
    Show countdown between playlist episodes.
    NOTE: This is not currently used with native Kodi playlists.
    Kodi handles playlist transitions automatically.
    Keeping this function for future enhancement if needed.

    :param dict next_episode: Next episode data
    :param int countdown_seconds: Countdown duration
    """
    try:
        c.log("[TV Evening] Gap countdown feature (currently unused)")
        return True

    except Exception as e:
        c.log(f"[TV Evening] Error in gap countdown: {e}")
        return True


def show_current_playlist():
    """
    Show the current Kodi video playlist.
    """
    try:
        c.log("[TV Evening] Showing current playlist")

        # Get current video playlist
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        playlist_size = playlist.size()

        # Check player status
        player = xbmc.Player()
        is_playing = player.isPlaying()
        c.log(f"[TV Evening] Playlist size: {playlist_size}, Player active: {is_playing}")

        if playlist_size == 0:
            c.log("[TV Evening] Playlist is empty - showing dialog")
            control.dialog.ok('Playlist Empty', 'There are no items in the current playlist.\n\nAdd episodes using "My TV Evening" feature.')
            return

        # Get current playing position
        current_pos = playlist.getposition()

        # Build playlist info
        lines = []

        for i in range(playlist_size):
            item = playlist[i]
            label = item.getLabel()

            # Mark currently playing item
            if i == current_pos and xbmc.Player().isPlayingVideo():
                lines.append(f"> {i+1}. {label}")
            else:
                lines.append(f"  {i+1}. {label}")

        lines.append('')
        lines.append(f"Total: {playlist_size} episode{'s' if playlist_size != 1 else ''}")
        if current_pos >= 0:
            lines.append(f"Currently at position: {current_pos + 1}")

        playlist_text = '\n'.join(lines)

        # Show playlist with options
        dialog = xbmcgui.Dialog()

        # First show the playlist
        dialog.textviewer('Current Video Playlist', playlist_text)

        # Ask what to do
        options = [
            'Continue Playing',
            'Clear Playlist',
            'Jump to Episode...'
        ]

        choice = dialog.select('Playlist Options', options)

        if choice == 1:  # Clear playlist
            if dialog.yesno('Clear Playlist', 'Are you sure you want to clear the entire playlist?'):
                playlist.clear()
                control.infoDialog('Playlist cleared', time=2000)
        elif choice == 2:  # Jump to episode
            # Build list of episodes for selection
            episode_list = []
            for i in range(playlist_size):
                item = playlist[i]
                label = item.getLabel()
                episode_list.append(f"{i+1}. {label}")

            selected = dialog.select('Jump to Episode', episode_list)
            if selected >= 0:
                xbmc.Player().stop()
                xbmc.sleep(500)
                xbmc.Player().play(playlist, startpos=selected)

    except Exception as e:
        c.log(f"[TV Evening] Error showing playlist: {e}")
        c.log(f"[TV Evening] Traceback: {traceback.format_exc()}")
        control.dialog.ok('Error', f'Failed to show playlist.\n\n{str(e)}')




def resume_playlist(session_info):
    """
    Resume a stale TV Evening playlist.

    :param dict session_info: Session info from tvevening_recovery
    """
    try:
        c.log("[TV Evening] Resuming playlist from stale session")

        playlist_size = session_info['playlist_size']
        current_position = session_info['current_position']
        episodes = session_info['episodes']

        c.log(f"[TV Evening] Resuming at position {current_position} of {playlist_size}")

        # Rebuild Kodi playlist from database episodes
        kodi_playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        kodi_playlist.clear()

        for i, ep in enumerate(episodes):
            url = ep.get('url', '')
            if not url:
                c.log(f"[TV Evening] Episode {i} has no URL, skipping")
                continue

            listitem = xbmcgui.ListItem(
                label=f"{ep.get('tvshowtitle', 'Unknown')} S{ep.get('season', 0):02d}E{ep.get('episode', 0):02d}"
            )

            listitem.setInfo('video', {
                'title': ep.get('title', 'Unknown'),
                'tvshowtitle': ep.get('tvshowtitle', 'Unknown'),
                'season': ep.get('season', 0),
                'episode': ep.get('episode', 0)
            })

            kodi_playlist.add(url, listitem)

        c.log(f"[TV Evening] Rebuilt playlist with {kodi_playlist.size()} episodes")

        # Start TV Evening Monitor
        monitor = tvevening_monitor.start_tv_evening_session(episodes)

        # Start playback from current position
        player = xbmc.Player()
        player.play(kodi_playlist, startpos=current_position)

        c.log(f"[TV Evening] Started playback at position {current_position}")

        control.infoDialog('TV Evening resumed', time=2000)

    except Exception as e:
        c.log(f"[TV Evening] Error resuming playlist: {e}")
        import traceback
        c.log(f"[TV Evening] Traceback: {traceback.format_exc()}")
        control.dialog.ok('Error', f'Failed to resume playlist.\n\n{str(e)}')


def start_tv_evening():
    """
    Main entry point for TV Evening feature.
    """
    try:
        c.log("[TV Evening] Starting TV Evening")

        # Check if Trakt is enabled
        if not is_trakt_enabled():
            control.dialog.ok('Trakt Required', 'TV Evening requires Trakt to be configured.\n\nPlease set up Trakt in settings.')
            return

        # Check for stale session (Kodi crashed/restarted during playback)
        from . import tvevening_recovery
        recovery_choice = tvevening_recovery.handle_recovery()

        if recovery_choice == 'continue':
            # Resume existing playlist
            c.log("[TV Evening] Resuming stale session")
            session_info = tvevening_recovery.get_session_info()
            if session_info:
                resume_playlist(session_info)
            return

        elif recovery_choice == 'delete':
            # User chose to delete - just return
            c.log("[TV Evening] User deleted stale session, not starting new one")
            return

        # If recovery_choice == 'fresh' or None, proceed with normal flow
        # Clear any leftover database from previous sessions
        if recovery_choice == 'fresh' or recovery_choice is None:
            c.log("[TV Evening] Clearing database for fresh start")
            from . import tvevening_recovery
            tvevening_recovery.clear_stale_session()

        # Ask user for duration and keep dialog for progress
        duration, progress_dialog = ask_duration_with_progress()
        if duration is None:
            c.log("[TV Evening] User cancelled duration selection")
            # Make sure database is cleared if user cancels
            c.log("[TV Evening] Clearing database after user cancelled")
            from . import tvevening_recovery
            tvevening_recovery.clear_stale_session()
            return

        c.log(f"[TV Evening] User selected {duration} minutes")

        # Transform the duration dialog into "building" state
        c.log("[TV Evening] ========== CALLING SHOW_BUILDING() ==========")
        c.log(f"[TV Evening] progress_dialog object: {progress_dialog}")
        if progress_dialog:
            c.log("[TV Evening] Calling progress_dialog.show_building()...")
            progress_dialog.show_building()
            c.log("[TV Evening] show_building() returned")
        else:
            c.log("[TV Evening] WARNING: progress_dialog is None! Dialog not showing!")

        # Build playlist
        playlist = build_playlist(duration, progress_dialog)

        # Close the progress dialog
        c.log("[TV Evening] ========== CLOSING PROGRESS DIALOG ==========")
        if progress_dialog:
            c.log("[TV Evening] Calling progress_dialog.close()...")
            progress_dialog.close()
            c.log("[TV Evening] Dialog closed, deleting object...")
            del progress_dialog
            c.log("[TV Evening] Dialog deleted")
        else:
            c.log("[TV Evening] WARNING: progress_dialog is None!")

        if not playlist:
            c.log("[TV Evening] Empty playlist, cleaning up")
            from . import tvevening_recovery
            tvevening_recovery.clear_stale_session()
            return

        # Show playlist preview if enabled
        if get_show_playlist_setting():
            choice = show_playlist_preview(playlist)
            if choice is None:
                c.log("[TV Evening] User cancelled at preview")
                # Clear database when user cancels
                from . import tvevening_recovery
                tvevening_recovery.clear_stale_session()
                return
            elif choice == 'first':
                c.log("[TV Evening] User chose to play first episode only")
                playlist = [playlist[0]]  # Keep only first episode

        # Play playlist
        play_playlist(playlist)

    except Exception as e:
        c.log(f"[TV Evening] Error in start_tv_evening: {e}")
        c.log(f"[TV Evening] Traceback: {traceback.format_exc()}")
        control.dialog.ok('Error', f'An error occurred building your TV Evening.\n\n{str(e)}')
