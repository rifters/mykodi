# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crewy Add-on
*
* @file __init__.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import pkgutil
import os.path
import importlib.util
import importlib.abc
import sys
import traceback

from ..modules.crewruntime import c


def _load_sources_from_dir(src_dir, prefix=None):
    """
    Safely load .py modules from an arbitrary directory and call their source().
    Uses importlib.spec_from_file_location to avoid clashing module names.
    """
    results = []
    if not os.path.isdir(src_dir):
        return results

    # Add parent directories to sys.path for proper imports
    parent_dir = os.path.dirname(src_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    for fname in os.listdir(src_dir):
        if not fname.endswith('.py') or fname == '__init__.py':
            continue

        module_basename = os.path.splitext(fname)[0]
        load_name = f"{prefix}.{module_basename}" if prefix else module_basename

        path = os.path.join(src_dir, fname)

        try:
            spec = importlib.util.spec_from_file_location(load_name, path)
            if spec is None or spec.loader is None:
                c.log(f'Could not load spec for "{path}": spec or loader is None', 1)
                continue
            module = importlib.util.module_from_spec(spec)
            try:
                # Preferred API
                spec.loader.exec_module(module)
            except AttributeError:
                # Fallback for legacy loaders that only implement load_module
                if hasattr(spec.loader, 'load_module'):
                    try:
                        module = spec.loader.load_module(load_name)
                    except Exception as e:
                        c.log(f'Could not load module "{path}" via load_module: {e}', 1)
                        continue
                else:
                    c.log(f'Loader for "{path}" does not support exec_module or load_module', 1)
                    continue
            # Prefix external pack sources to differentiate from crew sources
            source_name = f"{prefix}.{module_basename}" if prefix else module_basename
            # Ensure commonly referenced helper names are available in module namespace
            try:
                if 'gearsscrapers.modules.log_utils' in sys.modules and not hasattr(module, 'log_utils'):
                    setattr(module, 'log_utils', sys.modules['gearsscrapers.modules.log_utils'])
                if 'gearsscrapers.modules.source_utils' in sys.modules and not hasattr(module, 'source_utils'):
                    setattr(module, 'source_utils', sys.modules['gearsscrapers.modules.source_utils'])
            except Exception:
                pass

            # Only instantiate modules that expose a `source` factory
            if hasattr(module, 'source') and callable(getattr(module, 'source')):
                try:
                    results.append((source_name, module.source()))
                except Exception as e:
                    c.log(f'[Sources] Failed to instantiate source "{source_name}": {e}', 1)
            else:
                # Skip utility modules that do not implement a source() class/function
                c.log(f'[Sources] Skipping non-source module: {source_name}', 2)
            # c.log(f"[CM Debug @ 64 in __init__.py] appended sourcename = {source_name}")  # --- IGNORE ---
        except Exception as e:
            failure = traceback.format_exc()
            continue

    return results


def sources():
    """
    Load scrapers from resources.lib.scrapers/ directory (single source of truth)
    and external addon packs (CocoScrapers, Gearsscrapers, Viperscrapers).

    All legacy crew scrapers have been refactored to BaseScraper and moved
    to the scrapers/ directory for unified architecture.
    """
    sources = []

    # Load refactored scrapers from resources.lib.scrapers/ directory
    # This is the single source of truth for all Crew scrapers
    try:
        scrapers_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scrapers')
        if os.path.isdir(scrapers_dir):
            pkg_prefix = "resources.lib.scrapers"
            loaded = _load_sources_from_dir(scrapers_dir, prefix=pkg_prefix)
            if loaded:
                sources.extend(loaded)
                try:
                    short_names = [ (n.split('.')[-1].replace('_', ' ').title() if isinstance(n, str) else str(n)) for n, _ in loaded[:8] ]
                    c.log(f'[Sources] Loaded {len(loaded)} scrapers from scrapers/: {short_names}')
                except Exception:
                    c.log(f'[Sources] Loaded {len(loaded)} scrapers from scrapers/')
            else:
                c.log('[Sources] No scrapers found in scrapers/', 2)
    except Exception as e:
        c.log(f'[Sources] Failed loading scrapers: {e}', 1)
        c.log(f'[Sources] Traceback: {traceback.format_exc()}', 1)

    c.log(f'[Sources] Crew scrapers loaded: {len(sources)}')

    # Try to load CocoScrapers if installed and enabled
    try:
        import xbmc
        cocoscrapers_enabled = c.get_setting('cocoscrapers.enabled') == 'true'

        if xbmc.getCondVisibility('System.HasAddon(script.module.cocoscrapers)') and cocoscrapers_enabled:
            c.log('[Sources] CocoScrapers detected and enabled, attempting to load scrapers')

            # Discover addons directory
            cur = os.path.dirname(__file__)
            addons_dir = None
            for _ in range(6):
                if os.path.basename(cur).lower() == 'addons':
                    addons_dir = cur
                    break
                parent = os.path.dirname(cur)
                if parent == cur:
                    break
                cur = parent

            if addons_dir:
                cocos_base_dir = os.path.join(addons_dir, 'script.module.cocoscrapers', 'lib', 'cocoscrapers', 'sources_cocoscrapers')
                cocos_lib_dir = os.path.join(addons_dir, 'script.module.cocoscrapers', 'lib')

                # Add cocoscrapers lib to path for imports
                if cocos_lib_dir not in sys.path:
                    sys.path.insert(0, cocos_lib_dir)

                # Load from all source subdirectories (torrents, hosters, etc.)
                if os.path.isdir(cocos_base_dir):
                    for subdir in os.listdir(cocos_base_dir):
                        full_subdir_path = os.path.join(cocos_base_dir, subdir)
                        if os.path.isdir(full_subdir_path) and not subdir.startswith('_'):
                            try:
                                loaded = _load_sources_from_dir(full_subdir_path, prefix=f'cocoscrapers.{subdir}')
                                sources.extend(loaded)
                                c.log(f'[Sources] Loaded {len(loaded)} scrapers from cocoscrapers/{subdir}')
                            except Exception as e:
                                c.log(f'[Sources] Failed to load cocoscrapers/{subdir}: {e}', 1)
                else:
                    c.log('[Sources] CocoScrapers sources directory not found', 1)
        elif not cocoscrapers_enabled:
            c.log('[Sources] CocoScrapers installed but disabled in settings')
        else:
            c.log('[Sources] CocoScrapers not installed, using crew sources only')
    except Exception as e:
        c.log(f'[Sources] Error during CocoScrapers detection: {e}', 1)
        c.log(f'[Sources] Traceback: {traceback.format_exc()}', 1)

    c.log(f'[Sources] Total sources loaded: {len(sources)}')

    # Try to load Gearsscrapers if installed and enabled
    try:
        import xbmc
        gearsscrapers_enabled = c.get_setting('gearsscrapers.enabled') == 'true'

        has_addon = False
        try:
            has_addon = xbmc.getCondVisibility('System.HasAddon(script.module.gearsscrapers)')
        except Exception:
            # getCondVisibility may fail in some environments; fall back to filesystem check below
            has_addon = False

        # If Kodi reports the addon installed and the setting is enabled, proceed
        if has_addon and gearsscrapers_enabled:
            c.log('[Sources] Gearsscrapers detected and enabled, attempting to load scrapers')
            detected_via = 'kodi'
        # If addon appears installed but disabled in settings
        elif has_addon and not gearsscrapers_enabled:
            c.log('[Sources] Gearsscrapers installed but disabled in settings')
            detected_via = 'kodi'
        else:
            # Filesystem fallback: if an addon folder exists under the addons dir, treat it as installed
            detected_via = 'none'
            cur = os.path.dirname(__file__)
            addons_dir = None
            for _ in range(6):
                if os.path.basename(cur).lower() == 'addons':
                    addons_dir = cur
                    break
                parent = os.path.dirname(cur)
                if parent == cur:
                    break
                cur = parent

            if addons_dir:
                gear_path = os.path.join(addons_dir, 'script.module.gearsscrapers')
                if os.path.isdir(gear_path):
                    detected_via = 'filesystem'
                    c.log(f'[Sources] Gearsscrapers addon folder found at {gear_path} (filesystem fallback)')

        # If we detected via Kodi or filesystem and enabled in settings, try to load
        if detected_via in ('kodi', 'filesystem') and gearsscrapers_enabled:
            c.log(f'[Sources] Gearsscrapers detected ({detected_via}), attempting to load scrapers')

            # Add minimal shims for commonly used helper modules in Gearsscrapers
            try:
                import types, re

                # log_utils shim
                if 'gearsscrapers.modules.log_utils' not in sys.modules:
                    _log_mod = types.ModuleType('gearsscrapers.modules.log_utils')
                    def _gear_log(*a, level='INFO', **k):
                        try:
                            # replicates basic logging for providers
                            msg = ' '.join(str(x) for x in a)
                            c.log(f'[GearLog] {level}: ' + msg)
                        except Exception:
                            pass
                    _log_mod.log = _gear_log
                    _log_mod.debug = lambda *a, **k: _gear_log(*a, level='DEBUG', **k)
                    _log_mod.error = lambda *a, **k: _gear_log(*a, level='ERROR', **k)
                    _log_mod.warn = lambda *a, **k: _gear_log(*a, level='WARN', **k)
                    _log_mod.request_error = lambda url, *a, **k: _gear_log(f'Request-Error url=({url})', level='ERROR')
                    sys.modules['gearsscrapers.modules.log_utils'] = _log_mod

                # source_utils shim (more complete minimal implementation)
                if 'gearsscrapers.modules.source_utils' not in sys.modules:
                    _su = types.ModuleType('gearsscrapers.modules.source_utils')

                    # simple failure aggregation so we can produce a short summary
                    _su._scraper_failures = {}

                    def _scraper_error(name, *a, exc_info=None, **k):
                        """Log scraper errors and capture traceback when available.

                        Accepts either a message (name plus optional args) or an exception
                        passed as the first positional argument or via exc_info=. We
                        forward Exception objects to c.scraper_error for full tracebacks
                        and keep a per-scraper list of failure messages for a short
                        aggregated summary. For textual messages we log and also
                        forward to c.scraper_error (so with addon_debug enabled the
                        full SCRAPER ERROR block will be visible).
                        """
                        try:
                            import threading
                            import time as _time

                            # Helper to record failure message for summary
                            def _record(name_key, msg_text):
                                try:
                                    lst = _su._scraper_failures.setdefault(name_key, [])
                                    if isinstance(msg_text, str):
                                        lst.append(msg_text)
                                    else:
                                        lst.append(str(msg_text))
                                except Exception:
                                    pass

                            # If an Exception object was passed as a positional arg
                            if a and isinstance(a[0], Exception):
                                exc = a[0]
                                try:
                                    c.scraper_error(exc, scraper=name)
                                except Exception:
                                    # Ensure we still record the failure even if c.scraper_error is quiet
                                    c.log(f'[Gear source_utils.scraper_error] {name} (exception forwarded)', 1)
                                tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                                _record(name, tb)
                                return

                            # If exc_info provided and is an Exception, forward full traceback
                            if exc_info is not None:
                                if isinstance(exc_info, Exception):
                                    exc = exc_info
                                    try:
                                        c.scraper_error(exc, scraper=name)
                                    except Exception:
                                        c.log(f'[Gear source_utils.scraper_error] {name} (exception forwarded)', 1)
                                    tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                                    _record(name, tb)
                                    return
                                # otherwise treat exc_info as text
                                msg = str(exc_info)
                                try:
                                    c.scraper_error(msg, scraper=name)
                                except Exception:
                                    c.log(f'[Gear source_utils.scraper_error] {name} {msg}')
                                _record(name, msg)
                                return

                            # No exception object passed - try to capture active exception from context
                            msg = ' '.join(str(x) for x in a) if a else ''

                            # If there is no textual message but an exception is active in the caller, capture it
                            if not msg:
                                try:
                                    import sys
                                    exc_type, exc_value, exc_tb = sys.exc_info()
                                    if exc_value is not None:
                                        try:
                                            c.scraper_error(exc_value, scraper=name)
                                        except Exception:
                                            c.log(f'[Gear source_utils.scraper_error] {name} (exception forwarded)', 1)
                                        tb = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
                                        _record(name, tb)
                                        return
                                except Exception:
                                    # ignore sys.exc retrieval failures
                                    pass

                            try:
                                if msg:
                                    c.log(f'[Gear source_utils.scraper_error] {name} {msg}')
                                else:
                                    c.log(f'[Gear source_utils.scraper_error] {name}')
                            except Exception:
                                pass

                            # Forward textual message to c.scraper_error to surface in debug mode
                            try:
                                if msg:
                                    c.scraper_error(msg, scraper=name)
                            except Exception:
                                # ignore failures in forwarding
                                pass

                            _record(name, msg or '<no message>')

                        except Exception:
                            # Never let shim raise
                            try:
                                c.log('[Gear source_utils.scraper_error] internal logging failure', 1)
                            except Exception:
                                pass

                    _su.scraper_error = _scraper_error

                    # simple scheduled summary to help triage errors quickly during a run
                    def _schedule_failure_summary(delay=3.0):
                        def _runner(d):
                            try:
                                import time as _time
                                _time.sleep(d)
                                failures = getattr(_su, '_scraper_failures', {}) or {}
                                if not failures:
                                    return
                                total = sum(len(v) for v in failures.values())
                                try:
                                    c.log(f'[Sources] Gear failure summary: total={total} unique_scrapers={len(failures)}')
                                    # log a short sample per scraper
                                    for sname, msgs in failures.items():
                                        sample = msgs[0] if msgs else '<no message>'
                                        short = sample.splitlines()[0][:240]
                                        c.log(f'[Sources] Gear failure: {sname} -> count={len(msgs)} sample="{short}"')
                                except Exception:
                                    pass
                            except Exception:
                                pass

                        try:
                            import threading
                            t = threading.Thread(target=_runner, args=(delay,), daemon=True)
                            t.start()
                        except Exception:
                            pass

                    _su._schedule_failure_summary = _schedule_failure_summary

                    _su.get_undesirables = lambda: []
                    _su.check_foreign_audio = lambda: False

                    def _get_release_quality(name, url=None):
                        ln = str(name).lower()
                        if '4k' in ln or '2160' in ln or 'uhd' in ln:
                            return '4k', []
                        if '1080' in ln or '1080p' in ln:
                            return '1080p', []
                        if '720' in ln or '720p' in ln:
                            return '720p', []
                        if any(x in ln for x in ['cam', 'scr', 'hdcam']):
                            return 'cam', []
                        return 'sd', []
                    _su.get_release_quality = _get_release_quality

                    def _size(s):
                        try:
                            if not s:
                                return 0, ''
                            ss = str(s)
                            m = re.search(r'([\d\.,]+)\s*(GB|GiB|MB|MiB)', ss, re.IGNORECASE)
                            if m:
                                num = m.group(1).replace(',', '.')
                                unit = m.group(2).upper()
                                return 0, f"{num} {unit}"
                        except Exception:
                            pass
                        return 0, ''
                    _su._size = _size

                    # title matching heuristics used by many providers
                    def _check_title(title, aliases, name, hdlr=None, year=None, years=None):
                        try:
                            tn = str(title).lower()
                            nm = str(name).lower()
                            if tn in nm:
                                return True
                            for a in (aliases or []):
                                if str(a).lower() in nm:
                                    return True
                            # fallback: check year
                            if year and str(year) in nm:
                                return True
                            return False
                        except Exception:
                            return False
                    _su.check_title = _check_title

                    def _info_from_name(name, title=None, year=None, hdlr=None, episode_title=None):
                        # return a minimal dict that other helpers expect
                        return {'raw': name}
                    _su.info_from_name = _info_from_name

                    def _remove_lang(name_info, check_foreign_audio=False):
                        # if foreign audio detection desired, conservatively return False
                        return False
                    _su.remove_lang = _remove_lang

                    def _remove_undesirables(name_info, undesirables=None):
                        return False
                    _su.remove_undesirables = _remove_undesirables

                    # pack helpers (basic defaults)
                    _su.filter_show_pack = lambda *a, **k: (True, 0)
                    _su.filter_season_pack = lambda *a, **k: (True, 0, 0)

                    def clean_name(release_title):
                        try:
                            import re
                            s = str(release_title)
                            # remove CJK decorative brackets and leading/trailing separators
                            s = re.sub(r'【.*?】', '', s)
                            # remove non-printable chars
                            s = ''.join(ch for ch in s if ch.isprintable())
                            s = s.lstrip('+.-:/ ').rstrip()
                            s = s.replace(' ', '.')
                            # remove leading bracketed groups like [RARBG]
                            s = re.sub(r'^\[.*?\]', '', s, 1, re.I)
                            s = s.lstrip('.-[](){}:/')
                            return s
                        except Exception:
                            try:
                                c.log('[Gear shim] clean_name failed', 1)
                            except Exception:
                                pass
                            return release_title

                    _su.clean_name = clean_name

                    sys.modules['gearsscrapers.modules.source_utils'] = _su
            except Exception:
                pass

            # Discover addons directory (reuse the earlier resolution if available)
            if 'addons_dir' not in locals() or not addons_dir:
                cur = os.path.dirname(__file__)
                addons_dir = None
                for _ in range(6):
                    if os.path.basename(cur).lower() == 'addons':
                        addons_dir = cur
                        break
                    parent = os.path.dirname(cur)
                    if parent == cur:
                        break
                    cur = parent

            if addons_dir:
                gear_base_dir = os.path.join(addons_dir, 'script.module.gearsscrapers', 'lib', 'gearsscrapers')

                # Add gearsscrapers lib to path for imports
                gear_lib_dir = os.path.join(addons_dir, 'script.module.gearsscrapers', 'lib')
                if gear_lib_dir not in sys.path:
                    sys.path.insert(0, gear_lib_dir)

                # Load from all provider subdirectories if present
                if os.path.isdir(gear_base_dir):
                    for subdir in os.listdir(gear_base_dir):
                        full_subdir_path = os.path.join(gear_base_dir, subdir)
                        if not os.path.isdir(full_subdir_path) or subdir.startswith('_'):
                            continue
                        try:
                            # 'providers' contains nested provider categories (e.g., 'torrents', 'hosters')
                            if subdir == 'providers':
                                for provider_group in os.listdir(full_subdir_path):
                                    provider_path = os.path.join(full_subdir_path, provider_group)
                                    if os.path.isdir(provider_path) and not provider_group.startswith('_'):
                                        try:
                                            loaded = _load_sources_from_dir(provider_path, prefix=f'gearsscrapers.providers.{provider_group}')
                                            sources.extend(loaded)
                                            c.log(f'[Sources] Loaded {len(loaded)} scrapers from gearsscrapers/providers/{provider_group}')
                                        except Exception as e:
                                            c.log(f'[Sources] Failed to load gearsscrapers/providers/{provider_group}: {e}', 1)
                            else:
                                loaded = _load_sources_from_dir(full_subdir_path, prefix=f'gearsscrapers.{subdir}')
                                sources.extend(loaded)
                                c.log(f'[Sources] Loaded {len(loaded)} scrapers from gearsscrapers/{subdir}')
                        except Exception as e:
                            c.log(f'[Sources] Failed to load gearsscrapers/{subdir}: {e}', 1)
                else:
                    c.log('[Sources] Gearsscrapers sources directory not found', 1)
            else:
                c.log('[Sources] Could not locate addons directory for Gearsscrapers', 1)
        elif detected_via == 'filesystem' and not gearsscrapers_enabled:
            c.log('[Sources] Gearsscrapers addon folder found but disabled in settings')
        elif detected_via == 'none':
            c.log('[Sources] Gearsscrapers not installed, skipping')

    except Exception as e:
        c.log(f'[Sources] Error during Gearsscrapers detection: {e}', 1)
        c.log(f'[Sources] Traceback: {traceback.format_exc()}', 1)

    # Try to load Viperscrapers if installed and enabled
    try:
        import xbmc
        viperscrapers_enabled = c.get_setting('viperscrapers.enabled') == 'true'

        if xbmc.getCondVisibility('System.HasAddon(script.module.viperscrapers)') and viperscrapers_enabled:
            c.log('[Sources] Viperscrapers detected and enabled, attempting to load scrapers')

            # Discover addons directory
            cur = os.path.dirname(__file__)
            addons_dir = None
            for _ in range(6):
                if os.path.basename(cur).lower() == 'addons':
                    addons_dir = cur
                    break
                parent = os.path.dirname(cur)
                if parent == cur:
                    break
                cur = parent

            if addons_dir:
                vipers_base_dir = os.path.join(addons_dir, 'script.module.viperscrapers', 'lib', 'viperscrapers', 'sources_viperscrapers')
                vipers_lib_dir = os.path.join(addons_dir, 'script.module.viperscrapers', 'lib')

                # Add viperscrapers lib to path for imports
                if vipers_lib_dir not in sys.path:
                    sys.path.insert(0, vipers_lib_dir)

                # Load from all source subdirectories (torrents, hosters, etc.)
                if os.path.isdir(vipers_base_dir):
                    for subdir in os.listdir(vipers_base_dir):
                        full_subdir_path = os.path.join(vipers_base_dir, subdir)
                        if os.path.isdir(full_subdir_path) and not subdir.startswith('_'):
                            try:
                                loaded = _load_sources_from_dir(full_subdir_path, prefix=f'viperscrapers.{subdir}')
                                sources.extend(loaded)
                                c.log(f'[Sources] Loaded {len(loaded)} scrapers from viperscrapers/{subdir}')
                            except Exception as e:
                                c.log(f'[Sources] Failed to load viperscrapers/{subdir}: {e}', 1)
                else:
                    c.log('[Sources] Viperscrapers sources directory not found', 1)
        elif not viperscrapers_enabled:
            c.log('[Sources] Viperscrapers installed but disabled in settings')
        else:
            c.log('[Sources] Viperscrapers not installed, skipping')
    except Exception as e:
        c.log(f'[Sources] Error during Viperscrapers detection: {e}', 1)
        c.log(f'[Sources] Traceback: {traceback.format_exc()}', 1)

    # Finalize: report and return collected sources
    try:
        c.log(f'[Sources] Final total scrapers loaded: {len(sources)}')
    except Exception:
        c.log('[Sources] Final total scrapers loaded: <unknown>', 1)

    return sources
