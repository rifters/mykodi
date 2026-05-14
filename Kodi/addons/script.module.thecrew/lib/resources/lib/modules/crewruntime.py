# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file crewruntime.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''


import os
import sys
import re
import platform
import json
import base64
import datetime
import importlib
import traceback
import time

from io import open
from inspect import getframeinfo, stack
from functools import wraps

import xbmc
import xbmcvfs
import xbmcaddon
import xbmcgui
import xbmcplugin

from . import keys


# ========================================================================cm=
# CONSTANTS SECTION
# ========================================================================cm=

# API Keys (imported from keys.py for backward compatibility)
TMDB_KEY = keys.tmdb_key
TVDB_KEY = keys.tvdb_key
FANART_KEY = keys.fanart_key
ORION_KEY = keys.orion_key
YT_KEY = keys.yt_key

# Color Identifier String IDs (localized strings for color selection dropdowns)
# Used by: unaired.identify, prem.identify, torrent.identify settings
# Maps to strings: Blue, Red, Yellow, Deep Pink, Cyan, Lawn Green, Gold, Magenta, Yellow Green, No Color
COLOR_STRING_IDS = [32753, 32754, 32755, 32756, 32757, 32758, 32759, 32760, 32761, 32762]

# Color names for direct color tag generation (alternative to localized strings)
COLOR_NAMES = ['blue', 'red', 'yellow', 'deeppink', 'cyan', 'lawngreen', 'gold', 'magenta', 'yellowgreen', 'nocolor']

# Kodi API function references (shared across all instances)
transpath = xbmcvfs.translatePath
lang = xbmcaddon.Addon().getLocalizedString
listItem = xbmcgui.ListItem
addon = xbmcaddon.Addon
addonInfo = xbmcaddon.Addon().getAddonInfo

# ========================================================================cm=
# DECORATOR FUNCTIONS
# ========================================================================cm=

def log_api_call(func):
    """
    Decorator to log API calls with timing information.
    Logs the function name, endpoint, and elapsed time.

    Usage:
        @log_api_call
        def getTraktAsJson(url, ...):
            # existing code
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        endpoint = args[0] if args else kwargs.get('url', 'unknown')

        # Get the global CrewRuntime instance for logging
        # Note: This will be available after module initialization
        try:
            from . import crewruntime
            crewruntime.c.log(f"[API] Calling {func.__name__}: {endpoint}")
        except (ImportError, AttributeError, Exception):
            pass  # Logging may fail during module initialization

        result = func(*args, **kwargs)

        elapsed = time.time() - start
        try:
            from . import crewruntime
            crewruntime.c.log(f"[API] {func.__name__} completed in {elapsed:.2f}s")
        except (ImportError, AttributeError, Exception):
            pass  # Logging may fail during module initialization

        return result
    return wrapper


def warn_if_slow(threshold_seconds=1.0):
    """
    Decorator to log performance warnings for slow operations.
    Logs a warning if the function execution exceeds the threshold.

    Usage:
        @warn_if_slow(threshold_seconds=2.0)
        def some_database_function(...):
            # existing code
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            result = func(*args, **kwargs)
            elapsed = time.time() - start

            if elapsed > threshold_seconds:
                try:
                    from . import crewruntime
                    crewruntime.c.log(f"[PERF WARNING] {func.__name__} took {elapsed:.2f}s (threshold: {threshold_seconds}s)")
                except (ImportError, AttributeError, Exception):
                    pass  # Logging may fail during module initialization

            return result
        return wrapper
    return decorator


def retry_on_failure(max_attempts=3, delay=1.0, exceptions=(Exception,)):
    """
    Decorator to retry a function on failure with exponential backoff.
    Useful for network calls that may fail temporarily.

    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
        delay: Initial delay between retries in seconds (default: 1.0)
        exceptions: Tuple of exception types to catch (default: all exceptions)

    Usage:
        @retry_on_failure(max_attempts=3, delay=1.0)
        def network_call(...):
            # existing code
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts - 1:
                        # Last attempt failed, re-raise the exception
                        try:
                            from . import crewruntime
                            crewruntime.c.log(f"[RETRY FAILED] {func.__name__} failed after {max_attempts} attempts: {e}")
                        except (ImportError, AttributeError, Exception):
                            pass  # Logging may fail during module initialization
                        raise

                    # Log retry attempt
                    try:
                        from . import crewruntime
                        crewruntime.c.log(f"[RETRY] {func.__name__} failed (attempt {attempt+1}/{max_attempts}): {e}. Retrying in {current_delay}s...")
                    except (ImportError, AttributeError, Exception):
                        pass  # Logging may fail during module initialization

                    time.sleep(current_delay)
                    current_delay *= 2  # Exponential backoff

            # This should never be reached, but just in case
            if last_exception:
                raise last_exception

        return wrapper
    return decorator


# ========================================================================cm=
# INTERNAL HELPER CLASSES
# ========================================================================cm=

class _SettingsManager:
    """
    Internal class to manage addon settings.
    Handles the complex logic of reading/writing settings with fallbacks.
    """

    def __init__(self, runtime):
        self.runtime = runtime
        self._cache = {}

    def get(self, setting: str) -> str:
        """Get a setting value with caching and fallback logic."""
        try:
            # Check programmatic cache first
            if setting in self._cache:
                return self._cache.get(setting, '')

            # Try to get addon instance
            addon_inst = self._get_addon_instance()

            if addon_inst and hasattr(addon_inst, 'getSetting'):
                try:
                    val = addon_inst.getSetting(id=setting)
                    return val
                except Exception:
                    try:
                        val = addon_inst.getSetting(setting)
                        return val
                    except Exception:
                        pass

            # Fallback to creating fresh instance
            try:
                return xbmcaddon.Addon().getSetting(id=setting)
            except Exception:
                return ''
        except Exception:
            return ''

    def set(self, setting: str, val: str) -> None:
        """Set a setting value and update cache."""
        try:
            # Update cache
            self._cache[setting] = val

            # Try to get addon instance
            addon_inst = self._get_addon_instance()

            if addon_inst and hasattr(addon_inst, 'setSetting'):
                try:
                    addon_inst.setSetting(id=setting, value=val)
                    return
                except Exception:
                    pass

            # Fallback to creating fresh instance
            try:
                xbmcaddon.Addon().setSetting(id=setting, value=val)
            except Exception:
                pass
        except Exception:
            pass

    def _get_addon_instance(self):
        """Get the addon instance from runtime."""
        try:
            raw_addon = getattr(self.runtime, 'addon', None)
            if callable(raw_addon):
                return raw_addon()
            return raw_addon
        except Exception:
            return None


class _EncodingHelper:
    """
    Internal class to handle text encoding/decoding operations.
    Consolidates multiple similar methods into a clean interface.
    """

    @staticmethod
    def to_str(data, encoding='utf-8', errors='replace') -> str:
        """
        Convert bytes/str/other to str.
        Main method for safe string conversion.
        """
        if isinstance(data, str):
            return data
        if isinstance(data, bytes):
            return data.decode(encoding, errors)
        return str(data)

    @staticmethod
    def to_bytes(s, encoding='utf-8', errors='replace') -> bytes:
        """Convert str/bytes to bytes. Matches six_encode behavior."""
        if isinstance(s, bytes):
            return s
        if isinstance(s, str):
            return s.encode(encoding, errors)
        return str(s).encode(encoding, errors)  # Fallback for other types

    @staticmethod
    def safe_decode(data, encoding='utf-8', errors='replace') -> str:
        """
        Safely decode data with error handling.
        Logs errors if they occur.
        """
        try:
            return _EncodingHelper.to_str(data, encoding, errors)
        except Exception as e:
            # If logging is needed, caller should handle
            return str(data)


class _PathManager:
    """
    Internal class to manage addon artwork and resource paths.
    Consolidates all addon_* methods for cleaner organization.
    """

    def __init__(self, runtime):
        self.runtime = runtime

    def _get_art_path(self, filename: str, fallback: str = '') -> str:
        """Helper to build artwork path with fallback."""
        if self.runtime.art is not None and self.runtime._theme not in ['-', '']:
            return os.path.join(self.runtime.art, filename)
        return fallback

    def icon(self) -> str:
        """Get addon icon path."""
        fallback = xbmcaddon.Addon().getAddonInfo('icon')
        return self._get_art_path('icon.png', fallback)

    def thumb(self) -> str:
        """Get addon thumb path."""
        return self._get_art_path('thumb.jpg', '')

    def poster(self) -> str:
        """Get addon poster path."""
        return self._get_art_path('poster.png', 'DefaultVideo.png')

    def banner(self) -> str:
        """Get addon banner path."""
        return self._get_art_path('banner.png', 'DefaultVideo.png')

    def fanart(self) -> str:
        """Get addon fanart path."""
        path = self._get_art_path('fanart.jpg', '')
        if not path:
            return xbmcaddon.Addon().getAddonInfo('fanart')
        # Handle tuple case (legacy)
        if isinstance(path, tuple):
            return path[0]
        return path

    def clearart(self) -> str:
        """Get addon clearart path."""
        return self._get_art_path('clearart.png', '')

    def discart(self) -> str:
        """Get addon discart path."""
        return self._get_art_path('discart.png', '')

    def clearlogo(self) -> str:
        """Get addon clearlogo path."""
        return self._get_art_path('clearlogo.png', '')

    def next_icon(self) -> str:
        """Get next icon path."""
        return self._get_art_path('next.png', 'DefaultVideo.png')

    def adult_icon(self) -> str:
        """Get adult icon path."""
        return self._get_art_path('adult.png', 'DefaultVideo.png')


class _LogManager:
    """Internal class to manage logging operations."""

    def __init__(self, runtime):
        self.runtime = runtime

    def log(self, msg, trace=0) -> None:
        '''
        General new log messages

        Args:
            msg (str): The message to log
            trace (int): If 1, includes caller information from stack
        '''
        # Early exit if logging disabled - avoid string processing
        debug_enabled = self.runtime.get_setting('addon_debug')
        if not debug_enabled:
            return

        debug_prefix = f' DEBUG [{self.runtime.name} {self.runtime.pluginversion} | {self.runtime.moduleversion} | {self.runtime.pyversion} | {self.runtime.kodiversion} | {self.runtime.platform}]'
        info_prefix = f' INFO [{self.runtime.name} {self.runtime.pluginversion}/{self.runtime.moduleversion} | {self.runtime.pyversion}]'

        log_path = xbmcvfs.translatePath('special://logpath')
        filename = 'the_crew.log'
        log_file = os.path.join(log_path, filename)
        debug_log = self.runtime.get_setting('debug.location')

        try:
            if not isinstance(msg, str):
                raise TypeError('c.log() msg not of type str!')

            if trace == 1:
                caller = getframeinfo(stack()[1][0])

                head = debug_prefix
                _msg = f'\n     {msg}:\n    \n--> called from file {caller.filename} @ {caller.lineno}'
            else:
                head = info_prefix
                _msg = f'\n    {msg}'

            if debug_log== '1':
                #xbmc.log(f"\n\n--> addon name @ 147 = {self.runtime.name} | {self.runtime.pluginversion} | {self.runtime.moduleversion}  \n\n")

                if not os.path.exists(log_file):
                    _file = open(log_file, 'a', encoding="utf8")
                    x = "="*68 + "cm=\n"

                    # Get anonymized system info for the header
                    system_info = self.runtime.get_anonymized_system_info()

                    s = [
                        x,
                        "The Crew Add-on - Debug Log\n",
                        "Created: " + datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S") + "\n",
                        x,
                        "\n",
                        "System Information (anonymized for log uploads):\n",
                        "-" * 68 + "\n",
                        system_info + "\n",
                        "-" * 68 + "\n",
                        "\n",
                        x,
                        "\n",
                    ]

                    with open(log_file, "w", encoding="utf8") as f:
                        f.writelines(s)

                with open(log_file, 'a', encoding="utf8") as _file:
                    now = datetime.datetime.now()
                    _dt = now.strftime("%Y-%m-%d %H:%M:%S")

                    #line = f'[{_date} {_time}] {head}: {msg}'
                    line = f'{_dt} {head}: {msg}'
                    #_file.write(line.rstrip('\r\n') + '\n\n')
                    _file.write(line.rstrip('\r\n') + '\n')

        except (TypeError, OSError, UnicodeError) as exc:
            xbmc.log(f'[ {self.runtime.name} ] Logging Failure: {exc}', 1)

    def scraper_error(self, msg, scraper=None, trace=0, exc_info=None):
        """
        Logs an error message associated with a specific scraper.

        Improvements:
        - Auto-detects scraper name from filename if not provided
        - Accepts Exception objects and automatically captures full traceback
        - Better formatting for readability

        Args:
            msg (str or Exception): The error message or exception object to log
            scraper (str, optional): The name of the scraper. Auto-detected if None
            trace (int, optional): If set to 1, includes caller info. Defaults to 0
            exc_info (Exception, optional): Exception object for full traceback capture

        Examples:
            c.scraper_error("Custom error message", "my_scraper")
            c.scraper_error(exception_object)  # Auto-detects scraper name
            c.scraper_error("Error context", exc_info=e)  # Combines message + traceback
        """
        # Early exit if logging disabled
        if not self.runtime.get_setting('addon_debug'):
            return

        # Handle exception objects passed as msg
        if isinstance(msg, Exception):
            exc_info = msg
            msg = str(msg)

        # Auto-detect scraper name from call stack if not provided
        if scraper is None:
            try:
                caller_frame = stack()[1]
                caller_file = caller_frame[0].f_code.co_filename
                # Extract scraper name from filename (e.g., "/path/to/filmxy.py" -> "filmxy")
                scraper = os.path.splitext(os.path.basename(caller_file))[0]
            except (Exception):
                scraper = "unknown"  # Fallback if frame inspection fails

        # Build error message with traceback if exception available
        error_lines = [
            '\n' + '='*70,
            f'SCRAPER ERROR: {scraper}',
            '='*70
        ]

        if exc_info:
            # Capture full traceback
            import sys
            tb_lines = traceback.format_exception(type(exc_info), exc_info, exc_info.__traceback__)
            error_lines.append(f'Exception Type: {type(exc_info).__name__}')
            error_lines.append(f'Exception Message: {msg}')
            error_lines.append('\nFull Traceback:')
            error_lines.extend(['  ' + line.rstrip() for line in tb_lines])
        else:
            error_lines.append(f'Error: {msg}')

        error_lines.append('='*70)

        formatted_msg = '\n'.join(error_lines)
        self.log(formatted_msg, trace)


class _DialogManager:
    """Internal class to manage Kodi dialog operations."""

    def __init__(self):
        self._dialog = xbmcgui.Dialog()

    def select(self, heading, list, autoclose=0):
        """Display a selection dialog with list of items."""
        return self._dialog.select(heading, list, autoclose)

    def ok(self, message, heading='Info'):
        """Display a simple OK dialog with the given message and optional heading."""
        return self._dialog.ok(heading, message)

    def yesno(self, message, heading, nolabel='', yeslabel=''):
        """Display a Yes/No dialog with the given message and optional heading."""
        return self._dialog.yesno(heading, message, nolabel, yeslabel)

    def notification(self, heading, message, icon, time=3000, sound=False):
        """Display a notification popup."""
        return self._dialog.notification(heading, message, icon, time, sound=sound)


# ========================================================================cm=


class CrewRuntime:
    '''
    Global new superclass starting to run alongside the old code

    '''

    # Class constants - TMDB image size configurations
    IMAGE_SIZES = (
        {'poster': 'w185', 'fanart': 'w300', 'still': 'w300', 'profile': 'w185'},
        {'poster': 'w342', 'fanart': 'w780', 'still': 'w500', 'profile': 'w342'},
        {'poster': 'w780', 'fanart': 'w1280', 'still': 'w780', 'profile': 'h632'},
        {'poster': 'original', 'fanart': 'original', 'still': 'original', 'profile': 'original'}
    )

    # Class variables that reference module-level functions (for backward compatibility with c.lang() calls)
    transpath = transpath
    lang = lang
    listItem = listItem
    addonInfo = addonInfo

    def __init__(self):
        pass

        '''
        # cm - can later be used on a child class as temp obj to super crewRuntime
        # super().__init__(self)
        '''

        # Initialize internal managers first (needed for initialize_all)
        self._settings = _SettingsManager(self)
        self._art_paths = _PathManager(self)
        self._logger = _LogManager(self)
        self._dialogs = _DialogManager()

        self.name = None
        self.platform = None
        self.kodiversion = None
        self.int_kodiversion = None

        self.moduleversion = None
        self.pluginversion = None
        self.addon = None
        self.toggle = None
        self.has_silent_boot = None

        self.artPoster = None
        self.artThumb = None
        self.artIcon = None
        self.artFanart = None
        self.artClearlogo = None
        self.artClearart = None
        self.artDiscart = None

        self.tmdb_postersize = ''
        self.tmdb_fanartsize = ''
        self.tmdb_stillsize = ''
        self.tmdb_profilesize = ''
        self.devmode = False

        self._theme = ''
        self.art = ''

        self.cores = 0
        self._orion_installed = None  # Cache for expensive Orion check

        self.initialize_all()

    def __del__(self):
        '''
        On destruction of the class
        '''
        self.deinit()

    def deinit(self):
        '''
        cleanup
        '''
        self.toggle = None
        self.addon = None

    def initialize_all(self):
        '''
        initialize all vars
        '''
        # Cache a single Addon instance to ensure settings persist across calls
        try:
            self.addon = xbmcaddon.Addon()
            self.plugin_id = self.addon.getAddonInfo("id")
            self.pluginversion = self.addon.getAddonInfo("version")
            self.name = self.addon.getAddonInfo('name')
        except Exception:
            # Fallback (prior behavior) - keep the class reference if instance creation fails
            self.addon = xbmcaddon.Addon
            self.plugin_id = self.addon().getAddonInfo("id")
            self.pluginversion = self.addon().getAddonInfo("version")
            self.name = self.addon().getAddonInfo('name')

        self.name = self.strip_tags(text=self.name).title()
        self.platform = self._get_current_platform()

        # Note: Settings cache now managed by _SettingsManager

        self.module_addon = xbmcaddon.Addon("script.module.thecrew")
        self.module_id = self.module_addon.getAddonInfo(id="id")
        self.moduleversion = self.module_addon.getAddonInfo(id="version")

        self.kodiversion = self._get_kodi_version(as_string=True, as_full=True)
        self.int_kodiversion = self._get_kodi_version(as_string=False, as_full=False)
        self.pyversion = self._get_python_version(as_string=True)
        self.int_pyversion = self._get_python_version(as_string=False)
        self.has_silent_boot = self._has_silent_boot()
        self.artwork_path = self.get_artwork_path()
        self.cores = os.cpu_count() or 1

        self.devmode = self.get_setting('dev_pw') == self.to_str(base64.b64decode(b'dGhlY3Jldw=='))
        self.is_orion_disabled = self.orion_disabled()


        self._theme = self.appearance()
        self.art = self.get_art_path()

        # Initialize paths
        self.datapath = self._compute_datapath()
        self._paths = self._init_paths()

        self.toggle = 1 # cm - internal debugging

        self.set_imagesizes()
        self.check_orion()

    def _compute_datapath(self):
        """Compute addon profile data path."""
        return xbmcvfs.translatePath(self.addonInfo('profile'))

    def _init_paths(self):
        """Initialize all file paths using a dict pattern."""
        return {
            'settings': os.path.join(self.datapath, 'settings.xml'),
            'views': os.path.join(self.datapath, 'views.db'),
            'bookmarks': os.path.join(self.datapath, 'bookmarks.db'),
            'providercache': os.path.join(self.datapath, 'providers.13.db'),
            'metacache': os.path.join(self.datapath, 'meta.5.db'),
            'search': os.path.join(self.datapath, 'search.1.db'),
            'libcache': os.path.join(self.datapath, 'library.db'),
            'cache': os.path.join(self.datapath, 'cache.db'),
            'debridcache': os.path.join(self.datapath, 'debridcache.db'),
            'dbsettings': os.path.join(self.datapath, 'settings.db'),
            'traktsync': os.path.join(self.datapath, 'traktsync.db'),
            'meta': os.path.join(self.datapath, 'meta.db'),
        }

    def get_path(self, path_key):
        """Get a file path by key. Cached in dict for performance."""
        return self._paths.get(path_key, '')

    def kodi_version(self, as_string=False, as_full=False):
        """Get Kodi version - public method wrapper."""
        return self._get_kodi_version(as_string, as_full)

    def get_max_threads(self,total_items: int, default_cap: int = 50) -> int:
        """Determine an appropriate number of threads for concurrent tasks."""
        try:
            user_defined = int(self.get_setting('max.threads') or 0)
        except (ValueError, TypeError):
            user_defined = 0

        cpu_cores = os.cpu_count() or 1
        thread_count = user_defined if user_defined > 0 else cpu_cores * 2
        thread_count = min(thread_count, default_cap, total_items)
        return max(5, thread_count)

    def orion_disabled(self) -> bool:
        '''Check if Orion is disabled'''

        if(self.get_setting('disable.orion') == 'true'):
            return True
        return False
    @staticmethod
    def addon_exists(script_name) -> bool:
        """
        Check if an add-on with the given script name is installed and enabled.

        Args:
            script_name (str): The name of the script or add-on to check.

        Returns:
            bool: True if the add-on is installed and enabled, False otherwise.
        """

        if not script_name:
            return False
        return xbmc.getCondVisibility(f'System.HasAddon({script_name})') == 1

    def _has_silent_boot(self) -> bool:
        return self.get_setting('silent.boot') == 'true'

    def log_boot_option(self) -> None:
        if self.has_silent_boot:
            self.log('User enabled silent boot option')
        else:
            self.log('User disabled silent boot option')

    @staticmethod
    def addon_path() -> str:
        """Returns the path to the current add-on's resources directory"""
        return xbmcaddon.Addon().getAddonInfo('path')

    def addon_path_for(self, addon_id) -> str:
        """Returns the path to a specific add-on's resources directory"""
        try:
            return xbmcaddon.Addon(addon_id).getAddonInfo('path')
        except Exception as e:
            self.log(f'Error getting path for add-on {addon_id}: {e}', 1)
            return ''

    @staticmethod
    def get_artwork_path() -> str:
        """Returns the path to the script.thecrew.artwork addon's resources directory"""
        return xbmcaddon.Addon('script.thecrew.artwork').getAddonInfo('path')



    def _get_current_platform(self):
        pass

        platform_name = platform.uname()
        _system = platform_name[0]
        _sysname = platform_name[1]
        _sysrelease = platform_name[2]
        _sysversion = platform_name[3]
        _sysmachine = platform_name[4]
        _sysprocessor = platform_name[5]
        is_64bits = sys.maxsize > 2**32
        pf = platform.python_version() # pylint disable=snake-case

        if _system == 'Windows' and int(_sysversion.split('.')[-1]) > 22000:
            _sysrelease = '11'

        _64bits = '64bits' if is_64bits else '32bits'

        return f"{_system} {_sysrelease} v.{_sysversion} ({_64bits})"

    def get_anonymized_system_info(self):
        """
        Generate anonymized system information for log file headers.

        Returns system configuration details useful for debugging uploaded logs,
        while excluding any personally identifiable information (no username,
        hostname, IP address, or MAC address).

        Returns:
            str: Formatted multi-line string with anonymized system info

        Example output:
            OS: Windows 11 v.10.0.26300 (64bits)
            Kodi: v.21.3 (Omega)
            Python: v.3.8.15
            CPU Cores: 8
            Addon: plugin.video.thecrew v.2.2.9-alpha
            Module: script.module.thecrew v.2.3.10-alpha
        """
        try:
            # Get platform info (already anonymized - no username/hostname)
            platform_info = self._get_current_platform()

            # Get Kodi version info
            kodi_version = self.kodiversion if hasattr(self, 'kodiversion') else self._get_kodi_version(as_string=True, as_full=True)

            # Get Kodi codename if available
            kodi_codename = xbmc.getInfoLabel("System.BuildVersionName")
            kodi_display = f"v.{kodi_version}"
            if kodi_codename and kodi_codename.strip():
                kodi_display += f" ({kodi_codename})"

            # Get Python version
            python_version = self.pyversion if hasattr(self, 'pyversion') else self._get_python_version(as_string=True)

            # Get CPU count (useful for debugging thread pool issues)
            cpu_cores = self.cores if hasattr(self, 'cores') else (os.cpu_count() or 1)

            # Get addon versions
            plugin_version = self.pluginversion if hasattr(self, 'pluginversion') else "unknown"
            module_version = self.moduleversion if hasattr(self, 'moduleversion') else "unknown"

            # Format the output
            lines = [
                f"OS: {platform_info}",
                f"Kodi: {kodi_display}",
                f"Python: v.{python_version}",
                f"CPU Cores: {cpu_cores}",
                f"Addon: plugin.video.thecrew v.{plugin_version}",
                f"Module: script.module.thecrew v.{module_version}",
            ]

            return "\n".join(lines)

        except Exception as e:
            # Fallback in case of any errors
            return f"System info unavailable: {str(e)}"

    def _get_kodi_version(self, as_string=False, as_full=False):
        version_raw = xbmc.getInfoLabel("System.BuildVersion").split(" ")

        v_temp = version_raw[0]

        if as_full is False:
            version = v_temp.split(".")[0]
            fversion = ''
        else:
            v_major = v_temp.split(".")[0]
            v_minor = v_temp.split(".")[1]
            fversion = f"{v_major}.{v_minor}"
            version = ''

        if as_string is True:
            return version if as_full is False else fversion

        return int(version)

    def _get_python_version(self, as_string=False, as_full=False):
        """
        Get the python version

        :param as_string: bool Return the python version as a string
        :param as_full: bool Return the full python version string
        :return: str or int
        """
        version = platform.python_version_tuple()

        if as_string and as_full:
            return sys.version

        return '.'.join(version[:3]) if as_string else float('.'.join(version[:2]))

    def log(self, msg, trace=0) -> None:
        """Delegate to _LogManager for all logging operations."""
        return self._logger.log(msg, trace)

    def scraper_error(self, msg, scraper=None, trace=0, exc_info=None):
        """Delegate to _LogManager for scraper error logging."""
        return self._logger.scraper_error(msg, scraper, trace, exc_info)

    def in_addon(self) -> bool:
        '''
        returns bool if we are inside addon
        '''
        return xbmc.getInfoLabel('Container.PluginName') == "plugin.video.thecrew"

    def get_setting(self, setting) -> str:
        '''
        Return a setting value.
        Delegates to _SettingsManager for clean logic with caching.
        '''
        return self._settings.get(setting)

    def set_setting(self, setting, val) -> None:
        '''
        Set a setting value.
        Delegates to _SettingsManager for clean logic with caching.
        .getSettingString
        .getSettingBool
        .getSettingNumber
        .setSettingInt
        .setSettingBool
        '''
        self._settings.set(setting, val)

    def strip_tags(self, text) -> str:
        '''
        Strip the tags, added to the name in the addon.xml file
        '''

        clean = re.compile(r'\[.*?\]')
        return re.sub(clean, '', text)




    def check_orion(self):
        #check if Orion is installed
        if self.is_orion_installed():
            try:
                OrionClass = getattr(self, 'Orion', None)
                if OrionClass is None:
                    import importlib
                    module = importlib.import_module('orion')
                    OrionClass = getattr(module, 'Orion', None)
                    self.Orion = OrionClass
                if OrionClass is None:
                    raise ImportError('Orion class not found in orion module')

                result = OrionClass(keys.orion_key).user()
                self.set_setting('orion.installed', '[COLOR lawngreen]Installed[/COLOR]')
                self.set_setting('orion.boolinstalled', 'true')

                if result.get('username') is not None:
                    temp = result.get("username")
                else:
                    temp = self.obscure_email(result.get('email'))
                self.set_setting('orion.username', temp)
                package = result.get('subscription').get('package').get('name')
                self.set_setting('orion.package', package)
                expiration = result.get('subscription').get('time').get('expiration')
                exp = datetime.datetime.fromtimestamp(expiration).strftime('%A %d %b, %Y')
                self.set_setting('orion.expiration', str(exp))

            except Exception as e:
                self.log(f'Error checking Orion installation: {e}', 1)
                self.set_setting('orion.installed', '[COLOR red]Not Installed![/COLOR]')
                self.set_setting('orion.boolinstalled', 'false')


    def is_orion_installed(self):# -> Any:
        """
        Safely check if Orion add-on is installed and import its Orion class if available.
        This avoids a bare module import at parse time and handles missing or broken modules.
        Cached to avoid repeated expensive system calls.
        """
        # Return cached result if available
        if self._orion_installed is not None:
            return self._orion_installed

        # Perform expensive check and cache result
        if not xbmc.getCondVisibility('System.HasAddon(script.module.orion)'):
            self._orion_installed = False
            return False

        try:
            module = importlib.import_module('orion')
            OrionClass = getattr(module, 'Orion', None)
            if OrionClass is None:
                self.log('Orion module found but Orion class missing', 1)
                self._orion_installed = False
                return False
            # attach the class to the instance so other methods can access it
            self.Orion = OrionClass
            self._orion_installed = True
            return True
        except Exception as e:
            self.log(f'Failed to import Orion module: {e}', 1)
            self.set_setting('orion.installed', '[COLOR red]Not Installed![/COLOR]')
            self.set_setting('orion.boolinstalled', 'false')
            self._orion_installed = False
            return False


    def obscure_email(self, email):
        return email[:2] + '*' * (len(email) - 4) + email[-2:]


    #######
    # cm - replacing the six standard functions with own code


    @staticmethod
    def encode(s, encoding='utf-8') -> bytes:
        """
        Encodes a string to bytes using the specified encoding.
        Delegates to _EncodingHelper.to_bytes() for consistent behavior.
        Legacy method kept for backwards compatibility.

        Parameters:
            s (str): The string to be encoded. It can be a str (Python 3) or unicode (Python 2).
            encoding (str): The encoding type. Default is 'utf-8'.

        Returns:
            bytes: The encoded byte string.
        """
        return _EncodingHelper.to_bytes(s, encoding, errors='strict')




    def to_unicode(self, data, encoding: str = 'utf-8', errors: str = 'replace') -> str:
        """
        Safely return a unicode (str) from bytes/str/other.
        Delegates to _EncodingHelper with error logging.
        - If already str -> return unchanged.
        - If bytes -> decode using encoding/errors.
        - Otherwise -> convert via str() (safe fallback).
        Logs and re-raises decoding errors.
        """
        try:
            return _EncodingHelper.to_str(data, encoding, errors)
        except Exception as e:
            failure = traceback.format_exc()

            # UnicodeDecodeError requires (encoding, object, start, end, reason)
            # use a safe empty bytes object with start=end=0 and include the original error message
            raise UnicodeDecodeError(encoding, b'', 0, 0, f"Decoding failed: {e}") from e

    def decode(self, data, encoding: str = 'utf-8', errors: str = 'replace') -> str:
        """Alias for to_unicode() for backwards compatibility."""
        return self.to_unicode(data, encoding, errors)

    def to_str(self, data, encoding: str = 'utf-8', errors: str = 'replace') -> str:
        """
        Convert bytes/str/other to str. Clean modern API.
        Replaces: ensure_text, ensure_str, decode_text, six_decode.
        Delegates to _EncodingHelper for consistent behavior.
        """
        return _EncodingHelper.to_str(data, encoding, errors)

    def to_bytes(self, data, encoding: str = 'utf-8', errors: str = 'replace') -> bytes:
        """
        Convert str to bytes. Clean modern API.
        Replaces: encode_text, six_encode.
        Delegates to _EncodingHelper for consistent behavior.
        """
        return _EncodingHelper.to_bytes(data, encoding, errors)




    def set_imagesizes(self) -> None:
        '''
        Return the correct image sizes according to settings
        '''
        # Be tolerant of missing or invalid settings during test collection/imports
        try:
            q = self.get_setting('fanart.quality')
            idx = int(q) if q not in (None, '') else 2
        except (ValueError, TypeError):
            idx = 2

        # IMAGE_SIZES is a tuple of dicts; index it safely with bounds checking
        if isinstance(idx, int) and 0 <= idx < len(self.IMAGE_SIZES):
            resolutions = self.IMAGE_SIZES[idx]
        else:
            resolutions = self.IMAGE_SIZES[2]
        self.tmdb_postersize = resolutions.get('poster')
        self.tmdb_fanartsize = resolutions.get('fanart')
        self.tmdb_stillsize = resolutions.get('still')
        self.tmdb_profilesize = resolutions.get('profile')
        old_imagesetting = self.get_setting('fanart.quality.old')
        cur_imagesetting = self.get_setting('fanart.quality')
        if old_imagesetting != cur_imagesetting:
            self.clear_imagecaches()


    def clear_imagecaches(self) -> None:
        '''
        Clear the image cache
        '''
        self.set_setting('fanart.quality.old', self.get_setting('fanart.quality'))


    def now(self):
        '''
        Return the current time
        '''
        return datetime.datetime.now()



    def is_widget_listing(self) -> bool:
        """Check if the current window is a widget listing.

        Returns
        -------
        bool
            True if the current window is a widget listing, else False.
        """
        plugin_name = xbmc.getInfoLabel('Container.PluginName')
        b = 'plugin' not in plugin_name
        return 'plugin' not in plugin_name


    #---Add Directory Method---#
    def addDirectoryItem(self, name, url, mode, icon, fanart, thumb, description='', page='', dir_name='', cm=None, labels=None, cast=None, the_id = '', season = '', episode = '', isAction = True, isFolder = True):
        sys_url = sys.argv[0]
        sys_handle = int(sys.argv[1])

        if isinstance(name, int):
            name = xbmcaddon.Addon().getLocalizedString(name)

        if description == '':
            description = name
        if cast is None:
            cast = []
        if labels is None:
            labels = {'title': name, 'plot': description, 'mediatype': 'video'}

        if mode == 'navigator':
            pass

            if sys_url not in url:
                url = f'{sys_url}?action={url}'

            #url = '%s?action=%s' % (sys_url, url) if isAction is True else query
            thumb = os.path.join(self.art, thumb) if self.art is not None else icon

            fanart = self.addon_fanart()

            li = self.listItem(name)
            vtag = li.getVideoInfoTag()
            vtag.setMediaType(labels.get("mediatype", "video"))
            vtag.setTitle(labels.get("title", self.lang(32566)))
            if cm is not None:
                li.addContextMenuItems(cm)
            li.setArt({'icon': icon, 'thumb': thumb, 'fanart': fanart, 'poster': thumb})

            if fanart is not None:
                li.setProperty('fanart', fanart)

        xbmcplugin.addDirectoryItem(handle=sys_handle, url=url, listitem=li, isFolder=isFolder)


    def setContent(self, content: str) -> None:
        return xbmcplugin.setContent(int(sys.argv[1]), content)


    def endDirectory(self) -> None:
        xbmcplugin.endOfDirectory(int(sys.argv[1]))

    ######
    #
    # moving this over from control with better code
    def addon_icon(self) -> str:
        """Get addon icon path - delegates to _PathManager."""
        return self._art_paths.icon()

    def addon_thumb(self) -> str:
        """Get addon thumb path - delegates to _PathManager."""
        return self._art_paths.thumb()

    def addon_poster(self) -> str:
        """Get addon poster path - delegates to _PathManager."""
        return self._art_paths.poster()

    def addon_banner(self) -> str:
        """Get addon banner path - delegates to _PathManager."""
        return self._art_paths.banner()

    def addon_fanart(self) -> str:
        """Get addon fanart path - delegates to _PathManager."""
        return self._art_paths.fanart()

    def addon_clearart(self) -> str:
        """Get addon clearart path - delegates to _PathManager."""
        return self._art_paths.clearart()

    def addon_discart(self) -> str:
        """Get addon discart path - delegates to _PathManager."""
        return self._art_paths.discart()

    def addon_clearlogo(self) -> str:
        """Get addon clearlogo path - delegates to _PathManager."""
        return self._art_paths.clearlogo()

    def addon_next(self) -> str:
        """Get next icon path - delegates to _PathManager."""
        return self._art_paths.next_icon()

    def addon_adult_icon(self) -> str:
        """Get adult icon path - delegates to _PathManager."""
        return self._art_paths.adult_icon()

    def get_art_path(self) -> str:
        """Get artwork path for current theme."""
        if self._theme in ['-', '']:
            return ''
        if xbmc.getCondVisibility('System.HasAddon(script.thecrew.artwork)'):
            return os.path.join(
                xbmcaddon.Addon('script.thecrew.artwork').getAddonInfo('path'),
                'resources',
                'media',
                str(self._theme)
            )
        return ''  # Fallback if addon not available

    def appearance(self):
        return (
            self.get_setting('appearance.1').lower()
            if xbmc.getCondVisibility('System.HasAddon(script.thecrew.artwork)')
            else "thecrew" # and NOT a minus sign! - like in appearance.alt
        )

    def artwork(self) -> None:
        xbmc.executebuiltin('RunPlugin(plugin://script.thecrew.artwork)')

    def capitalize_word(self, string) -> str:
        pass

        return string.title()

    def string_split_to_list(self, string) -> list:
        pass

        if string in ['0', None]:
            return []
        if(isinstance(string, list)):
            return string
        elif(isinstance(string, tuple)):
            return list(string)
        elif(isinstance(string, str)):
            string = string.strip()
        lst = string.split('/')
        lst = [s.strip() for s in lst]
        lst = [self.capitalize_word(s) for s in lst]

        return lst

    def search_tmdb_index_in_indicators(self, tmdb_id, indicator_list):
        try:
            pass

            if not indicator_list:
                return -1

            tmdb_id = str(tmdb_id)
            indices = [index for index, value in enumerate(indicator_list) if value[0] == tmdb_id]

            return indices[0] if indices else -1
        except Exception as e:
            failure = traceback.format_exc()
            pass

    def search_tmdb_index_in_indicators2(self, tmdb, indicators):
        pass

        if not indicators:
            return -1

        if not isinstance(tmdb, str):
            tmdb = str(tmdb)

        lst = [i for i, v in enumerate(indicators) if v[0] == tmdb]

        if len(lst) == 0:
            return -1
        else:
            return lst[0]


    def count_watched_items_in_indicators(self, index, indicators):
        """Count watched items in indicators list."""
        try:
            if not indicators[index]:
                return -1
            else:
                return len(indicators[index][2])

        except Exception as e:
            failure = traceback.format_exc()
            pass

    # Backwards compatibility alias (typo fix)
    def count_wachted_items_in_indicators(self, index, indicators):
        """Deprecated: typo in method name. Use count_watched_items_in_indicators instead."""
        return self.count_watched_items_in_indicators(index, indicators)


    @staticmethod
    def count_total_items_in_indicators(index, indicators):
        if not indicators[index]:
            return -1
        return indicators[index][1]

    @staticmethod
    def string_to_tuple(string):
        return tuple(map(str, string.split(',')))


    @staticmethod
    def unicode_art(_str) -> str:
        _str = re.sub('\\\\\\\\u([\\da-f]{4})', lambda x: chr(int(x.group(1), 16)), _str)
        return json.dumps(_str)

    def okDialog(self, message, heading='Info'):
        """Delegate to _DialogManager for OK dialog."""
        return self._dialogs.ok(message, heading)

    def yesnoDialog(self, message, heading=None, nolabel='', yeslabel=''):
        """Delegate to _DialogManager for Yes/No dialog."""
        if heading is None:
            heading = self.name
        return self._dialogs.yesno(message, heading, nolabel, yeslabel)

    def infoDialog(self, message, heading=None, icon='', time=3000, sound=False) -> None:
        """Delegate to _DialogManager for notification with icon handling."""
        if heading is None:
            heading = self.name
        if icon == '':
            icon = self.addon_icon()
        elif icon == 'INFO':
            icon = xbmcgui.NOTIFICATION_INFO
        elif icon == 'WARNING':
            icon = xbmcgui.NOTIFICATION_WARNING
        elif icon == 'ERROR':
            icon = xbmcgui.NOTIFICATION_ERROR
        elif icon.endswith('.png'):
            icon = os.path.join(self.art, icon)
        return self._dialogs.notification(heading, message, icon, time, sound)


c = CrewRuntime()
