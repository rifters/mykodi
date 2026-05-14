# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file playcount.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

import contextlib
import sys
import traceback
#import xbmc

from . import bookmarks
from . import cache
from . import control
from . import trakt
from ..indexers import episodes
from .crewruntime import c


def get_movie_indicators(refresh=False):
    try:
        if trakt.getTraktIndicatorsInfo():
            raise Exception()
        return bookmarks.get_indicators()
    except Exception:
        pass

    try:
        if not trakt.getTraktIndicatorsInfo():
            raise Exception()
        if not refresh:
            timeout = 720
        elif trakt.getWatchedActivity_from_db() < trakt.timeoutsyncMovies():
            timeout = 720
        else:
            timeout = None

        return trakt.cachesyncMovies(timeout=timeout)
    except Exception:
        pass


def get_tvshow_indicators(refresh=False):
    try:
        if not trakt.getTraktIndicatorsInfo():
            raise Exception()
        if not refresh:
            timeout = 720
        elif trakt.getWatchedActivity_from_db() < trakt.timeoutsyncTVShows():
            timeout = 720
        else:
            timeout = None
        return trakt.cachesyncTVShows(timeout=timeout)
    except Exception as e:
        failure = traceback.format_exc()
        pass
    #except Exception:
    #    pass


def getSeasonIndicators(imdb):
    with contextlib.suppress(Exception):
        if not trakt.getTraktIndicatorsInfo():
            raise Exception()
        return trakt.syncSeason(imdb)


def get_movie_overlay(indicators, imdb):
    try:
        if trakt.getTraktIndicatorsInfo() is False:
            overlay = bookmarks.get_watched('movie', imdb, '', '')
        else:
            playcount = [i for i in indicators if i == imdb]
            overlay = 7 if playcount else 6
        return str(overlay)
    except Exception:
        return '6'

def movie_has_indicator(indicators, imdb):
    try:
        return False if trakt.getTraktIndicatorsInfo() is False else imdb in indicators
    except Exception:
        return False

def getTVShowOverlay(indicators, tmdb):
    try:
        playcount = [i[0] for i in indicators if i[0] == tmdb and len(i[2]) >= int(i[1])]
        #playcount = 7 if len(playcount) > 0 else 6
        playcount = 7 if playcount else 6
        return str(playcount)
    except (IndexError, ValueError, TypeError):
        return '6'

def getSeasonOverlay(indicators, season):
    try:
        playcount = [i for i in indicators if int(season) == int(i)]
        #playcount = 7 if len(playcount) > 0 else 6
        playcount = 7 if playcount else 6
        return str(playcount)
    except (ValueError, TypeError):
        return '6'

def get_episode_overlay(indicators, imdb, tmdb, season, episode):
    """
    Return the overlay value for a given episode. If trakt is not authenticated, looks up the overlay in the bookmarks database.
    Otherwise, looks up the overlay in the trakt indicators.

    :param indicators: List of playcount indicators from trakt.
    :param imdb: The IMDB ID of the TV show.
    :param tmdb: The TMDB ID of the TV show.
    :param season: The season number of the episode.
    :param episode: The episode number of the episode.
    :return: The overlay value, as a string.

    overlay 6: Not watched
    overlay 7: Watched
    """
    try:
        # Trakt watched status is authoritative - check it first.
        # Do NOT check the progress table here: fill_progress_table() stores
        # Trakt's in-progress percentage which would block the watched check.
        if not trakt.getTraktIndicatorsInfo():
            overlay = bookmarks.get_watched('episode', imdb, season, episode)
        else:
            playcount = [i[2] for i in indicators if i[0] == tmdb]
            playcount = playcount[0] if playcount else []
            playcount = [i for i in playcount if int(season) == int(i[0]) and int(episode) == int(i[1])]
            overlay = 7 if playcount else 6
        return str(overlay)
    except (IndexError, ValueError, TypeError, KeyError) as e:
        return '6'

def getEpisodeOverlay_old(indicators, imdb, tmdb, season, episode):
    try:
        if not trakt.getTraktIndicatorsInfo():
            overlay = bookmarks.get_watched('episode', imdb, season, episode)
        else:
            playcount = [i[2] for i in indicators if i[0] == tmdb]
            playcount = playcount[0] if playcount else []
            playcount = [i for i in playcount if int(season) == int(i[0]) and int(episode) == int(i[1])]
            overlay = 7 if playcount else 6
        return str(overlay)
    except Exception:
        return '6'

def markMovieDuringPlayback(imdb, watched):
    try:
        if not trakt.getTraktIndicatorsInfo():
            raise Exception()

        if int(watched) == 7:
            trakt.markMovieAsWatched('imdb', imdb)
        else:
            trakt.markMovieAsNotWatched('imdb', imdb)
        trakt.cachesyncMovies()
        if trakt.get_trakt_addon_movie_info():
            trakt.markMovieAsNotWatched('imdb', imdb)
    except Exception:
        pass

    try:
        if int(watched) == 7:
            bookmarks.reset(1, 1, 'movie', imdb, '', '')
    except Exception:
        pass

def markEpisodeDuringPlayback(imdb, tmdb, season, episode, watched):
    from resources.lib.modules import control as c

    try:
        if not trakt.getTraktIndicatorsInfo():
            raise Exception()

        key = 'imdb' if imdb else 'tmdb'
        media_id = imdb or tmdb

        if int(watched) == 7:
            trakt.markEpisodeAsWatched(key, media_id, season, episode)
        else:
            trakt.markEpisodeAsNotWatched(key, media_id, season, episode)
        trakt.cachesyncTVShows()

        if trakt.getTraktAddonEpisodeInfo():
            trakt.markEpisodeAsNotWatched(key, media_id, season, episode)
    except Exception as e:
        c.log(f"[Playcount] Trakt marking failed: {e}")

    try:
        if int(watched) == 7:
            c.log(f"[Playcount] Calling bookmarks.reset() for {imdb} S{season}E{episode}")
            bookmarks.reset(1, 1, 'episode', imdb, season, episode)
            c.log(f"[Playcount] (OK) bookmarks.reset() completed successfully")

            # Set flag for player to refresh container when user exits playback
            # (Can't refresh now - no visible container during fullscreen playback)
            from resources.lib.modules import control
            control.window.setProperty('thecrew.container.needs_refresh', 'true')
            c.log("[Playcount] Set container refresh flag")
    except Exception as e:
        c.log(f"[Playcount] ERROR in bookmarks.reset(): {e}")
        import traceback
        c.log(f"[Playcount] Traceback: {traceback.format_exc()}")

#TC 2/01/19 started
def movies(imdb, query):
    """
    Mark a movie watched/unwatched in Trakt (when available) and update local bookmarks.
    Provides explicit logging and isolates failures so one subsystem failing doesn't stop the other.
    """

    # validate/normalize input
    try:
        watched = int(query)
    except (ValueError, TypeError) as e:
        return

    # Update Trakt if indicators are available. Failures here should be logged but not prevent bookmarks update.
    try:
        if trakt.getTraktIndicatorsInfo():
            if watched == 7:
                trakt.markMovieAsWatched('imdb', imdb)
            else:
                trakt.markMovieAsNotWatched('imdb', imdb)

            try:
                trakt.cachesyncMovies()
            except Exception as e:
                pass
        else:
            pass
    except Exception as e:
        pass

    # Update local bookmarks independently of Trakt outcome.
    try:
        if watched == 7:
            bookmarks.reset(1, 1, 'movie', imdb, '', '')
        else:
            bookmarks.delete_record('movie', imdb, '', '')
    except Exception as e:
        pass

    # Refresh UI (best-effort)
    try:
        control.refresh()
    except Exception as e:
        pass

def movies2(imdb, query):
    try:
        if not trakt.getTraktIndicatorsInfo():
            raise Exception()
        if int(query) == 7:
            trakt.markMovieAsWatched('imdb', imdb)
        else:
            trakt.markMovieAsNotWatched('imdb', imdb)
        trakt.cachesyncMovies()
        control.refresh()
    except Exception:
        pass

    try:
        if int(query) == 7:
            bookmarks.reset(1, 1, 'movie', imdb, '', '')
        else:
            bookmarks.delete_record('movie', imdb, '', '')
        if not trakt.getTraktIndicatorsInfo():
            control.refresh()
    except Exception:
        pass


def episode(imdb, tmdb, season, episode, query):
    try:
        if not trakt.getTraktIndicatorsInfo():
            raise Exception()

        key = 'imdb' if imdb else 'tmdb'
        media_id = imdb or tmdb

        if int(query) == 7:
            trakt.markEpisodeAsWatched(key, media_id, season, episode)
        else:
            trakt.markEpisodeAsNotWatched(key,media_id,  season, episode)
        trakt.cachesyncTVShows()
        control.refresh()
    except Exception as e:
        pass


    try:
        if int(query) == 7:
            bookmarks.reset(1, 1, 'episode', imdb, season, episode)
        else:
            bookmarks.delete_record('episode', imdb, season, episode)
        if not trakt.getTraktIndicatorsInfo():
            control.refresh()
    except Exception as e:
        failure = traceback.format_exc()
        pass

def season(imdb, tmdb, season, query):
    """
    Marks a TV season as watched or not watched based on the provided parameters.

    Args:
        imdb (str): The IMDb ID of the TV show.
        tmdb (str): The TMDB ID of the TV show.
        season_id (int): The season number to be marked. Needs other name than season to avoid
                            confusion with the season parameter.
        watched (int): Indicator whether the season is watched (7) or not watched.

    Raises:
        Exception: If there is an error during processing, logs the exception details.
    """

    control.busy()

    try:
        #if trakt.getTraktIndicatorsInfo():
            #raise Exception()

        key = 'imdb' if imdb else 'tmdb'
        media_id = imdb or tmdb

        if int(query) == 7:
            trakt.markSeasonAsWatched(key,media_id, season)
        else:
            trakt.markSeasonAsNotWatched(key,media_id, season)

        # Clear cached Trakt activity AND syncTVShows cache so TV shows list refreshes indicators
        cache.cache_delete('trakt.last_activities', table='trakt')
        # Also clear the syncTVShows function cache to force immediate refresh
        sync_cache_key = cache._hash_function(trakt.syncTVShows, trakt.TRAKTUSER)
        cache.cache_delete(sync_cache_key)

        # Force immediate sync with timeout=None to get fresh data from Trakt
        trakt.cachesyncTVShows(timeout=None)

    except Exception as e:
        failure = traceback.format_exc()
        pass

    control.refresh()
    control.idle()


def tvshows(imdb, tmdb, watched):
    control.busy()

    try:
        #if trakt.getTraktIndicatorsInfo():
            #raise Exception()

        key = 'imdb' if imdb else 'tmdb'
        media_id = imdb or tmdb

        if not key or not media_id:
            raise Exception()

        if int(watched) == 7:
            trakt.markTVShowAsWatched(key,media_id)
        else:
            trakt.markTVShowAsNotWatched(key,media_id)
        trakt.cachesyncTVShows()

    except Exception as e:
        failure = traceback.format_exc()
        pass


    control.refresh()
    control.idle()


def tvshows_old(tvshowtitle, imdb, tmdb, season, watched):
    control.busy()
    try:
        if trakt.getTraktIndicatorsInfo():
            raise Exception()

        name = control.addonInfo('name')

        dialog = control.progressDialogBG
        dialog.create(str(name), str(tvshowtitle))
        dialog.update(0, str(name), str(tvshowtitle))

        items = []
        if season:
            items = episodes().get(tvshowtitle, '0', imdb, tmdb, meta=None, season=season, create_directory=False)
            items = [i for i in items if int('%01d' % int(season)) == int('%01d' % int(i['season']))]
            items = [{'label': '%s S%02dE%02d' % (tvshowtitle, int(i['season']), int(i['episode'])), 'season': int('%01d' % int(i['season'])), 'episode': int('%01d' % int(i['episode'])), 'unaired': i['unaired']} for i in items]

            #for i in range(len(items)):
            for i, item in enumerate(items):
                if control.monitor.abortRequested():
                    return sys.exit()

                #dialog.update(int((100 / float(len(items))) * i), str(name), str(items[i]['label']))
                dialog.update(int((100 / float(len(items))) * i), str(name), str(item['label']))

                #_season, _episode, unaired = items[i]['season'], items[i]['episode'], items[i]['unaired']
                _season = item['season']
                _episode = item['episode']
                unaired = item['unaired']

                if int(watched) == 7:
                    if unaired != 'true':
                        bookmarks.reset(1, 1, 'episode', imdb, _season, _episode)
                else:
                    bookmarks.delete_record('episode', imdb, _season, _episode)

        else:
            seasons = seasons().get(tvshowtitle, '0', imdb, tmdb, meta=None, idx=False, create_directory=False)
            seasons = [i['season'] for i in seasons]

            for s in seasons:
                items = episodes().get(tvshowtitle, '0', imdb, tmdb, meta=None, season=s, create_directory=False)
                items = [{
                    'label': '%s S%02dE%02d' % (tvshowtitle, int(i['season']), int(i['episode'])),
                    'season': int('%01d' % int(i['season'])),
                    'episode': int('%01d' % int(i['episode'])),
                    'unaired': i['unaired']
                    } for i in items]

                #for i in range(len(items)):
                for i, item in enumerate(items):
                    if control.monitor.abortRequested():
                        return sys.exit()

                    #dialog.update(int((100 / float(len(items))) * i), str(name), str(items[i]['label']))
                    dialog.update(int((100 / float(len(items))) * i), str(name), str(item['label']))

                    _season = item['season']
                    _episode = item['episode']
                    unaired = item['unaired']
                    if int(watched) == 7:
                        if unaired != 'true':
                            bookmarks.reset(1, 1, 'episode', imdb, _season, _episode)
                    else:
                        bookmarks.delete_record('episode', imdb, _season, _episode)

        try:
            dialog.close()
        except Exception as e:
            pass
    except Exception:
        try:
            dialog.close()
        except Exception as e:
            failure = traceback.format_exc()
            pass

    try:
        if trakt.getTraktIndicatorsInfo() is False:
            raise Exception()

        if season:
            items = episodes().get(tvshowtitle, '0', imdb, tmdb, meta=None, season=season, create_directory=False)
            items = [(int(i['season']), int(i['episode'])) for i in items]
            items = [i[1] for i in items if int('%01d' % int(season)) == int('%01d' % i[0])]
            for i in items:
                if int(watched) == 7:
                    trakt.markEpisodeAsWatched(imdb, season, i)
                else:
                    trakt.markEpisodeAsNotWatched(imdb, season, i)
        else:
            if int(watched) == 7:
                trakt.markTVShowAsWatched('imdb', imdb)
            else:
                trakt.markTVShowAsNotWatched('imdb', imdb)
        trakt.cachesyncTVShows()
    except Exception as e:
        failure = traceback.format_exc()

    control.refresh()
    control.idle()
