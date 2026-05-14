# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 * Background service implementation for script.module.thecrew.
 * Launched by plugin.video.thecrew/service.py at Kodi startup.
 *
 * @file crewservice.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023 - 2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

# CM - 06/07/2021  (original service.py)
# cm - 06/20/2023
# cm - 10/19/2024 - conversion check and fix from module v. 1.x to v. > 2.0.0
# cm - 11/01/2024 - added TraktMonitor for scrobble
# cm - 02/20/2026 - added CrewMonitor for global player monitoring (TV Evening playlist)
# cm - 02/22/2026 - added conversion check and fix for bookmarks file
# cm - 02/28/2026 - v22.26 ZERO-THREAD-GROWTH: CrewMonitor persistent worker thread for infinite episodes
# cm - 04/25/2026 - moved from plugin.video.thecrew/service.py into script.module.thecrew/lib

import os
import re
import sys
import traceback
import glob
import queue
import threading

from threading import Thread
from shutil import rmtree
from resources.lib.modules import control
from resources.lib.modules import trakt
from resources.lib.modules.crewruntime import c

import xbmc
import xbmcvfs
import xbmcgui
import xbmcaddon

QUARTERLY = 60 * 15
HALF_HOUR = 60 * 30
HOURLY = 60 * 60
FIVE_MINUTES = 60 * 5


class _PlaybackWatcher(xbmc.Player):
    """Thin xbmc.Player subclass that signals a threading.Event the instant
    Kodi reports A/V decoding has started (onAVStarted).  Used in the
    CrewMonitor worker to replace the old 240-iteration poll loop."""
    def __init__(self):
        super().__init__()
        self.started = threading.Event()

    def onAVStarted(self):
        self.started.set()


def conversion():
    # cm - 10/19/2024 Removed dialogs as being obsolete and not needed
    conversionFile = os.path.join(control.dataPath, 'conversion.v')
    bookmarkFile = control.bookmarksFile
    curVersion = c.moduleversion

    if not os.path.exists(conversionFile):
        f_path = xbmcvfs.translatePath('special://home/addons/script.thecrew.metadata')
        rmtree(f_path, ignore_errors=True)

        if os.path.isfile(bookmarkFile):
            os.remove(bookmarkFile)
            c.log(f'removing {str(bookmarkFile)}')

        if not os.path.isfile(bookmarkFile):
            with open(conversionFile, 'w', encoding="utf8") as fh:
                fh.write(curVersion)
            if c.devmode:
                c.log(f'File written, Conversion successful, version = {curVersion}')


def readProviders(scraper_path_fill, msg1, catnr):
    addon_name = c.name
    addon_icon = xbmcaddon.Addon('plugin.video.thecrew').getAddonInfo('icon')
    addon_path = xbmcvfs.translatePath('special://home/addons/plugin.video.thecrew')
    module_path = xbmcvfs.translatePath('special://home/addons/script.module.thecrew')

    xbmc.log(f"[ plugin.video.thecrew ] service - checking {msg1} providers started", 1)

    if c.has_silent_boot:
        if c.devmode:
            c.log(f"Preparing {msg1} Providers")
    else:
        xbmcgui.Dialog().notification(addon_name, f"Preparing {msg1} Providers", addon_icon)

    settings_xml_path = os.path.join(addon_path, 'resources/settings.xml')
    scraper_path = os.path.join(
        module_path, f'lib/resources/lib/sources/{scraper_path_fill}'
    )
    try:
        xml = _openfile(settings_xml_path)
    except (OSError, IOError) as e:
        c.log(f"The Crew Service - Exception: {e}")
        return

    new_settings = '\n'
    for file in glob.glob(f"{scraper_path}/*.py"):
        file = os.path.basename(file)
        if '__init__' not in file:
            file = file.replace('.py', '')
            new_settings += f'        <setting id="provider.{file.lower()}" type="bool" label="{file.upper()}" default="true" />\n'
        new_settings += '    '

    pattern = f'<category label="{str(catnr)}">' + r'([\s\S]*?)<\/category>'
    found = re.findall(pattern, xml, flags=re.DOTALL)
    xml = xml.replace(found[0], new_settings)
    _savefile(settings_xml_path, xml)

    if c.has_silent_boot:
        if c.devmode:
            c.log(f"{msg1} Providers Updated")
    else:
        xbmcgui.Dialog().notification(addon_name, f"{msg1} Providers Updated", addon_icon)


def _openfile(path_to_the_file):
    try:
        with open(path_to_the_file, 'r', encoding="utf8") as fh:
            contents = fh.read()
        return contents
    except (OSError, IOError) as e:
        c.log(f"Service Open File Exception - {path_to_the_file}: {e}")
        return None


def _savefile(path_to_the_file, content):
    try:
        with open(path_to_the_file, 'w', encoding="utf8") as fh:
            fh.write(content)
    except (OSError, IOError) as e:
        c.log(f"Service Save File Exception - {path_to_the_file}: {e}")


def syncTraktLibrary():
    control.execute('RunPlugin(plugin://plugin.video.thecrew/?action=tvshowsToLibrarySilent&url=traktcollection')
    control.execute('RunPlugin(plugin://plugin.video.thecrew/?action=moviesToLibrarySilent&url=traktcollection')


def syncTrakt():
    trakt.syncTrakt()


def main():
    """
    Run one-time startup tasks.
    Executes once when Kodi starts, NOT continuously.
    Scheduled/continuous tasks are in TraktMonitor.
    """
    try:
        # Rotate log file BEFORE any logging to prevent massive log files
        try:
            log_dir = xbmcvfs.translatePath('special://logpath')
            log_path = os.path.join(log_dir, 'the_crew.log')
            old_log_path = os.path.join(log_dir, 'the_crew.old.log')
            if os.path.exists(log_path) and os.path.getsize(log_path) > 0:
                try:
                    if os.path.exists(old_log_path):
                        os.remove(old_log_path)
                except Exception:
                    pass
                try:
                    os.rename(log_path, old_log_path)
                except Exception:
                    pass
        except Exception:
            pass  # Don't fail startup if log rotation fails

        c.log_boot_option()

        c.initialize_all()
        conversion()
        syncTrakt()

        control.startupMaintenance()

        module_version = xbmcaddon.Addon('script.module.thecrew').getAddonInfo('version')
        plugin_version = xbmcaddon.Addon('plugin.video.thecrew').getAddonInfo('version')
        xbmcaddon.Addon('plugin.video.thecrew').setSetting('module_base', module_version)
        xbmcaddon.Addon('plugin.video.thecrew').setSetting('plugin_base', plugin_version)

        checks = ['en|Free|32345', 'en_de|Debrid|90004', 'en_tor|Torrent|90005']
        for check in checks:
            items = check.split('|')
            readProviders(items[0], items[1], items[2])

        if c.devmode:
            c.log('Providers done')

        if control.setting('autoTraktOnStart') == 'true':
            if c.devmode:
                c.log('autoTraktOnStart Enabled: synctraktlib started')
            syncTraktLibrary()

    except Exception as e:
        failure = traceback.format_exc()
        c.log(f'Traceback:: {str(failure)}')
        c.log(f'Exception raised: {str(e)}')


class TraktMonitor(xbmc.Monitor):
    def __init__(self):
        xbmc.Monitor.__init__(self)

    def run(self):
        if c.devmode:
            c.log('[TraktMonitor] Service starting')
        xbmc.log('[script.module.thecrew][TraktMonitor] Service Starting', 2)

        # Clear any stale window properties left over from a previous Kodi session or crash.
        # thecrew.trakt_refreshing_token is a mutex guard - if it was left set it causes
        # every subsequent Trakt call to spin-wait 30 seconds before timing out.
        _win = xbmcgui.Window(10000)
        _win.clearProperty('thecrew.trakt_refreshing_token')
        _win.clearProperty('thecrew.trakt_auth_failed')
        _win.clearProperty('thecrew.trakt_auth_notified')
        _win.clearProperty('thecrew.trakt_token_logged')
        _win.clearProperty('thecrew.trakt_status')
        _win.clearProperty('thecrew.trakt_network_notified')
        _win.clearProperty('thecrew.debrid_unreachable_notified')
        if c.devmode:
            c.log('[TraktMonitor] Cleared stale Trakt window properties')

        try:
            trakt.process_scrobble_queue() # type: ignore
            if c.devmode:
                c.log('[TraktMonitor] Processed startup scrobble queue')
        except Exception as e:
            c.log(f'[TraktMonitor] Error processing startup scrobble queue: {e}')

        scrobble_counter = 0
        token_check_counter = 0
        trakt_sync_counter = 0
        trakt_sync_interval = int(control.setting('schedTraktTime')) * 3600

        if c.devmode and trakt_sync_interval > 0:
            c.log(f'[TraktMonitor] Scheduled Trakt sync enabled: every {trakt_sync_interval // 3600} hours')

        while not self.abortRequested():
            if self.waitForAbort(60):
                break

            scrobble_counter += 60
            trakt_sync_counter += 60
            token_check_counter += 60

            if token_check_counter >= HOURLY:
                try:
                    trakt.check_and_refresh_token()
                except Exception as e:
                    c.log(f'[TraktMonitor] Error in proactive token check: {e}')
                token_check_counter = 0

            if scrobble_counter >= FIVE_MINUTES:
                if c.devmode:
                    c.log('[TraktMonitor] Processing scrobble queue')
                try:
                    trakt.process_scrobble_queue() # type: ignore
                except Exception as e:
                    c.log(f'[TraktMonitor] Error processing scrobble queue: {e}')
                scrobble_counter = 0

            if trakt_sync_interval > 0 and trakt_sync_counter >= trakt_sync_interval:
                if c.devmode:
                    c.log(f'[TraktMonitor] Running scheduled Trakt sync (every {trakt_sync_interval // 3600} hours)')
                try:
                    syncTrakt()
                    syncTraktLibrary()
                except Exception as e:
                    c.log(f'[TraktMonitor] Error in scheduled Trakt sync: {e}')
                trakt_sync_counter = 0

        try:
            trakt.process_scrobble_queue() # type: ignore
        except Exception as e:
            c.log(f'[TraktMonitor] Error processing final scrobble queue: {e}')

        if c.devmode:
            c.log('[TraktMonitor] Service finished')
        xbmc.log('[script.module.thecrew][TraktMonitor] Service Finished', 2)


# v22.26: Module-level shutdown event for worker thread.
# Must be module-level so it survives CrewMonitor instance deletion during module reloads.
# Worker thread checks this instead of self.abortRequested() to avoid thread death
# from a deleted instance.
_worker_shutdown_event = threading.Event()

# Module-level monitor reference — set when CrewMonitor is instantiated.
_crewmonitor_instance = None


def get_crew_monitor():
    """Return the active CrewMonitor instance, or None if not yet running."""
    return _crewmonitor_instance


class CrewMonitor(xbmc.Monitor):
    def __init__(self):
        xbmc.Monitor.__init__(self)
        self.crew_player = None

        # v22.26: ZERO-THREAD-GROWTH — one persistent worker thread for the entire session.
        # Carry over the episode counter if an older instance existed.
        old_instance = getattr(queue, '_thecrew_crewmonitor_singleton', None)
        self.episodes_processed = old_instance.episodes_processed if old_instance else 0

        global _crewmonitor_instance
        _crewmonitor_instance = self
        setattr(queue, '_thecrew_crewmonitor_singleton', self)

        if not control.window.getProperty('thecrew.upnext.ready'):
            control.window.setProperty('thecrew.upnext.ready', 'true')
            if c.devmode:
                c.log("[CrewMonitor] Initialized upnext window properties")

        self.startServices()

    @classmethod
    def get_or_create_instance(cls):
        """Always create new instance — worker thread persists independently."""
        if c.devmode:
            c.log("[CrewMonitor] Creating instance")
        return cls()

    def _persistent_monitoring_worker(self):
        """
        v22.26: Window property-polling worker.

        ONE thread for the entire Kodi session:
        - Polls thecrew.upnext.active every second
        - When active: monitors playback, triggers UpNext, saves resume, scrobbles
        - Persists across module reloads (non-daemon thread)
        - Only exits on _worker_shutdown_event or Kodi shutdown
        """
        import time

        c.log("[CrewMonitor-Worker] UpNext monitoring started")
        if c.devmode:
            c.log("[CrewMonitor-Worker] Polling window properties for episode triggers")

        episodes_handled = 0

        global _worker_shutdown_event
        while not _worker_shutdown_event.is_set():
            try:
                upnext_active = control.window.getProperty('thecrew.upnext.active')

                if upnext_active == 'true':
                    episodes_handled += 1

                    title = control.window.getProperty('thecrew.upnext.title')
                    year = control.window.getProperty('thecrew.upnext.year')
                    season = control.window.getProperty('thecrew.upnext.season')
                    episode = control.window.getProperty('thecrew.upnext.episode')
                    imdb = control.window.getProperty('thecrew.upnext.imdb')
                    tmdb = control.window.getProperty('thecrew.upnext.tmdb')
                    content = control.window.getProperty('thecrew.upnext.content') or 'episode'
                    is_movie = content == 'movie'

                    if is_movie:
                        c.log(f"[CrewMonitor-Worker] Movie {episodes_handled}: {title} ({year})")
                    else:
                        c.log(f"[CrewMonitor-Worker] Episode {episodes_handled}: {title} S{season}E{episode}")

                    player = xbmc.Player()

                    if c.devmode:
                        c.log("[CrewMonitor-Worker] Waiting for playback to start...")
                    started = False
                    for _ in range(240):
                        if player.isPlayingVideo():
                            started = True
                            break
                        if _worker_shutdown_event.is_set():
                            break
                        time.sleep(1)

                    if not started:
                        c.log(f"[CrewMonitor-Worker] ⚠ Playback timeout for episode {episodes_handled}")
                        control.window.clearProperty('thecrew.upnext.active')
                        continue

                    if c.devmode:
                        c.log("[CrewMonitor-Worker] Playback active, monitoring for UpNext trigger")

                    # Read UpNext settings once before the monitoring loop
                    _upnext_end_seconds = int(float(control.setting('upnext.end_seconds') or 0))
                    _upnext_countdown = int(float(control.setting('upnext.countdown_seconds') or 15))
                    _upnext_trigger_pct = int(float(control.setting('upnext.trigger_percent') or 97)) / 100.0

                    c.log(f"[CrewMonitor-Worker] UpNext settings: end_seconds={_upnext_end_seconds}, countdown={_upnext_countdown}, trigger_pct={_upnext_trigger_pct:.2f}")
                    if _upnext_end_seconds > 0:
                        c.log(f"[CrewMonitor-Worker] UpNext mode: TIME-BASED (dialog at totalTime-{_upnext_end_seconds + _upnext_countdown}s, prefetch at totalTime-{_upnext_end_seconds + _upnext_countdown + 90}s)")
                    else:
                        c.log(f"[CrewMonitor-Worker] UpNext mode: PERCENT-BASED (dialog at {_upnext_trigger_pct*100:.0f}%)")

                    upnext_triggered = False
                    prefetch_triggered = False
                    last_current_time = 0
                    last_total_time = 0

                    while player.isPlayingVideo():
                        try:
                            totalTime = player.getTotalTime()
                            currentTime = player.getTime()

                            if totalTime <= 0:
                                time.sleep(2)
                                continue

                            last_current_time = currentTime
                            last_total_time = totalTime

                            percent = currentTime / totalTime

                            # Compute trigger conditions based on settings
                            if _upnext_end_seconds > 0:
                                _dialog_time = totalTime - _upnext_end_seconds - _upnext_countdown
                                should_trigger_upnext = currentTime >= _dialog_time
                                should_trigger_prefetch = currentTime >= (_dialog_time - 90)
                            else:
                                should_trigger_upnext = percent >= _upnext_trigger_pct
                                should_trigger_prefetch = percent >= max(0.75, _upnext_trigger_pct - 0.10)

                            # Pre-scrape trigger: start background scraping ~90s before dialog fires
                            if not prefetch_triggered and should_trigger_prefetch and not is_movie:
                                prefetch_triggered = True
                                try:
                                    from resources.lib.modules import episode_container as _ec_mod
                                    _next_ep_num = int(episode) + 1
                                    if c.devmode:
                                        c.log(f"[CrewMonitor-Worker] Starting prefetch S{int(season):02d}E{_next_ep_num:02d}")
                                    _ec_mod.start_prefetch(
                                        title=title,
                                        year=year,
                                        season=int(season),
                                        episode=_next_ep_num,
                                        imdb=imdb,
                                        tmdb=tmdb
                                    )
                                except Exception as e:
                                    c.log(f"[CrewMonitor-Worker] ⚠ Prefetch start error: {e}")

                            if not upnext_triggered and should_trigger_upnext and not is_movie:
                                tv_evening_active = control.window.getProperty('thecrew.tvevening.monitor.active') == 'true'
                                if tv_evening_active:
                                    if c.devmode:
                                        c.log("[CrewMonitor-Worker] Skipping UpNext - TV Evening playlist is active")
                                    upnext_triggered = True
                                    continue

                                if c.devmode:
                                    c.log(f"[CrewMonitor-Worker] UpNext trigger at {percent*100:.1f}% ({currentTime:.0f}s/{totalTime:.0f}s)")
                                upnext_triggered = True

                                try:
                                    from resources.lib.modules import upnext
                                    if c.devmode:
                                        c.log(f"[CrewMonitor-Worker] Showing UpNext dialog for {title} S{season}E{episode}")
                                    result = upnext.show_upnext_dialog(
                                        current_title=title,
                                        current_year=year,
                                        current_imdb=imdb,
                                        current_tmdb=tmdb,
                                        current_season=int(season),
                                        current_episode=int(episode)
                                    )
                                    if c.devmode:
                                        c.log(f"[CrewMonitor-Worker] UpNext result: {result}")
                                except Exception as e:
                                    c.log(f"[CrewMonitor-Worker] ⚠ UpNext error: {e}")
                                    if c.devmode:
                                        c.log(f"[CrewMonitor-Worker] Traceback: {traceback.format_exc()}")

                            time.sleep(2)

                        except Exception as e:
                            c.log(f"[CrewMonitor-Worker] ⚠ Error checking playback: {e}")
                            break

                    # Playback ended — save resume point and scrobble
                    try:
                        if last_total_time > 0:
                            resume_percent = last_current_time / last_total_time
                            is_fully_watched = resume_percent >= 0.92
                            is_in_progress = last_current_time > 60 and not is_fully_watched
                            raw_imdb = imdb if imdb and imdb not in ('None', 'null', '') else ''
                            raw_tmdb = int(tmdb) if tmdb and tmdb not in ('None', 'null', '') else 0

                            if is_in_progress or is_fully_watched:
                                from resources.lib.modules import bookmarks as bm
                                bm.reset(
                                    int(last_current_time), int(last_total_time), content,
                                    raw_imdb, season, episode, tmdb=raw_tmdb
                                )
                                c.log(f"[CrewMonitor-Worker] (OK) Resume saved: {last_current_time:.0f}s/{last_total_time:.0f}s ({resume_percent*100:.1f}%) imdb={raw_imdb} tmdb={raw_tmdb} content={content}")

                                if is_in_progress:
                                    xbmc.executebuiltin('Container.Refresh')
                                    c.log("[CrewMonitor-Worker] Container refreshed to show resume indicator")

                                if control.setting('trakt.scrobble') == 'true':
                                    scrobble_action = 'stop' if is_fully_watched else 'pause'
                                    bm.set_scrobble(int(last_current_time), int(last_total_time), content, raw_imdb, season, episode, scrobble_action)
                                    c.log(f"[CrewMonitor-Worker] Scrobbled to Trakt: {resume_percent*100:.1f}% ({scrobble_action})")
                            else:
                                c.log(f"[CrewMonitor-Worker] Skipping resume save: current={last_current_time:.0f}s, too short")
                    except Exception as e:
                        c.log(f"[CrewMonitor-Worker] Error saving resume: {e}")

                    control.window.clearProperty('thecrew.upnext.active')
                    control.window.clearProperty('thecrew.upnext.title')
                    control.window.clearProperty('thecrew.upnext.year')
                    control.window.clearProperty('thecrew.upnext.season')
                    control.window.clearProperty('thecrew.upnext.episode')
                    control.window.clearProperty('thecrew.upnext.imdb')
                    control.window.clearProperty('thecrew.upnext.tmdb')
                    control.window.clearProperty('thecrew.upnext.content')
                    if c.devmode:
                        c.log(f"[CrewMonitor-Worker] Episode {episodes_handled} finished")

                else:
                    # Check for widget refresh requests from background populate threads
                    # (they can't call executebuiltin safely from a non-service thread).
                    if control.window.getProperty('crew.widget.needs_refresh'):
                        refresh_url = control.window.getProperty('crew.widget.refresh_url') or ''
                        control.window.clearProperty('crew.widget.needs_refresh')
                        control.window.clearProperty('crew.widget.refresh_url')
                        control.window.setProperty('crew.widget.context', '1')
                        if refresh_url:
                            c.log(f"[CrewMonitor-Worker] Widget refresh requested - calling Container.Refresh({refresh_url})")
                            xbmc.executebuiltin(f'Container.Refresh({refresh_url})')
                        else:
                            c.log("[CrewMonitor-Worker] Widget refresh requested - calling Container.Refresh")
                            xbmc.executebuiltin('Container.Refresh')
                    time.sleep(1)

            except Exception as e:
                c.log(f"[CrewMonitor-Worker] ✗ Error: {e}")
                if c.devmode:
                    c.log(f"[CrewMonitor-Worker] Traceback: {traceback.format_exc()}")
                time.sleep(1)

        c.log(f"[CrewMonitor-Worker] Shutdown (handled {episodes_handled} episodes)")

    def __del__(self):
        c.log('[CrewMonitor] Instance being deleted (module reload)')
        if self.crew_player:
            del self.crew_player
        del self

    def startServices(self):
        xbmc.log('[script.module.thecrew][CrewMonitor] Service Starting', 2)
        Thread(target=TraktMonitor().run).start()

        # Start the persistent monitoring worker thread only once per Kodi session.
        if not hasattr(queue, '_thecrew_worker_started'):
            worker_thread = threading.Thread(
                target=self._persistent_monitoring_worker,
                name="CrewMonitor-Worker",
                daemon=False  # Must survive module reloads
            )
            worker_thread.start()
            setattr(queue, '_thecrew_worker_started', True)
            if c.devmode:
                c.log("[CrewMonitor] Started persistent monitoring worker")
        else:
            if c.devmode:
                c.log("[CrewMonitor] Worker thread already running")

        try:
            from resources.lib.modules.player import player as crewPlayer, register_global_player
            self.crew_player = crewPlayer()
            register_global_player(self.crew_player)
            xbmc.log('[script.module.thecrew][CrewMonitor] Global crewPlayer instance created and registered', xbmc.LOGINFO)
        except Exception as e:
            xbmc.log(f'[script.module.thecrew][CrewMonitor] Error creating global crewPlayer: {e}', xbmc.LOGERROR)
            xbmc.log(traceback.format_exc(), xbmc.LOGERROR)


def start():
    """Entry point called by plugin.video.thecrew/service.py."""
    control.execute('RunPlugin(plugin://%s)' % control.get_plugin_url({'action': 'service'}))

    main()

    monitor = CrewMonitor.get_or_create_instance()

    # Note: No waitForAbort() here. Kodi manages the service lifecycle.
    # The CrewMonitor worker thread runs autonomously and exits on _worker_shutdown_event.
