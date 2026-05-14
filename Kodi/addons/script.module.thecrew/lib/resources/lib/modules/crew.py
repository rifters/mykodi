# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file crew.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import sys

# moved imports to module top-level for clarity and performance
import importlib
import inspect
import json
import traceback
import types
from random import randint
from urllib.parse import quote_plus


from . import cache
from . import control
from . import downloader
from . import sources as local_sources
from . import views
from .crewruntime import c

def _log_router_call(function_name, **kwargs):
    """
    Centralized devmode logging for router calls.
    Logs function name, params, sys.argv, and any additional context.
    Only active when c.devmode == True.
    """
    if not c.devmode:
        return

    log_parts = [f"[router.{function_name}] DEVMODE DEBUG"]

    # Log sys.argv if available
    if sys.argv:
        log_parts.append(f"  sys.argv: {sys.argv}")

    # Log all provided kwargs
    if kwargs:
        for key, value in kwargs.items():
            log_parts.append(f"  {key}: {value}")

    c.log("\n".join(log_parts))

def router(params):
    """
    Refactored single-entry router that preserves original behaviour.
    - Uses lazy imports
    - Handles instantiation heuristics
    - Maps every action from the original file to a handler
    """
    # Devmode logging for router entry (consolidated)
    _log_router_call("router", params=params, action=params.get('action'))

    # cm - internal local helper to read params
    def p(k, default=None):
        return params.get(k, default)

    # cm - robust call_module: import module, resolve attribute, optionally instantiate or call method
    def call_module(module_path, attr=None, inst=False, method=None, *a, **kw):
        """
        Lazily import module or accept a module object.
        - module_path: str module name or an already-imported module object
        - attr: attribute name in module (optional, can be passed as 2nd positional arg)
        - inst: if True, try to instantiate/resolve a class/constructor
        - method: call a method on the instance/attribute/module when provided
        """
        # Handle backward compatibility: extract attr, inst, method from positional args
        # Pattern 1: call_module('module', 'class', inst=True, method='method')
        # Pattern 2: call_module('module', 'class', True, 'method', *args)
        # Pattern 3: call_module('module', None, False, 'method', *args)
        a = list(a)  # Convert to list for easier manipulation

        # Try to extract positional attr, inst, method - use elif chain to avoid multiple extractions
        if len(a) >= 3 and isinstance(a[1], bool) and isinstance(a[2], str):
            # Pattern: [attr_or_None, bool, str, ...] -> extract attr, inst, method
            extracted_attr = a.pop(0)
            if attr is None and extracted_attr is not None:
                attr = extracted_attr
            # Now a[0] is the bool
            inst = a.pop(0)
            method = a.pop(0)
        elif len(a) >= 2 and isinstance(a[0], str) and isinstance(a[1], bool):
            # Pattern: [str, bool, ...] -> extract attr, inst
            if attr is None:
                attr = a.pop(0)
            inst = a.pop(0)
        elif len(a) >= 1 and isinstance(a[0], str) and not inst and not method:
            # Pattern: [str, ...] with no inst/method set yet (only attr extraction)
            if attr is None:
                attr = a.pop(0)

        a = tuple(a)  # Convert back to tuple

        # Devmode logging for call_module
        _log_router_call("call_module",
                        module_path=module_path,
                        attr=attr,
                        inst=inst,
                        method=method,
                        args=a,
                        kwargs=kw)

        if not isinstance(module_path, str):
            if inspect.ismodule(module_path):
                mod = module_path
            else:
                raise TypeError(f"module_path must be a string or module, got: {type(module_path)}")
        else:
            # Support relative imports (module_path starting with '.')
            try:
                if module_path.startswith('.'):
                    mod = importlib.import_module(module_path, package=__package__)
                else:
                    mod = importlib.import_module(module_path)
            except Exception:
                c.log(f"[router] Failed to import {module_path}")
                raise

        target = getattr(mod, attr) if attr else mod

        def _find_class_in_module(m, name_hint=None):
            hint = (name_hint or '').lower()
            for n, obj in inspect.getmembers(m, inspect.isclass):
                if n.lower() == hint:
                    return obj
            for n, obj in inspect.getmembers(m, inspect.isclass):
                if obj.__module__ == m.__name__:
                    return obj
            return None

        # cm - try to instantiate requested
        if inst:
            instance = None
            if inspect.isclass(target):
                instance = target()
            elif callable(target) and not inspect.ismodule(target):
                instance = target()
            elif inspect.ismodule(target):
                cls = _find_class_in_module(target, attr)
                if cls:
                    instance = cls()
            if instance is None:
                raise TypeError(f"'inst' requested but target is not callable: {module_path}{f'.{attr}' if attr else ''}")
            return getattr(instance, method)(*a, **kw) if method else instance

        # cm - try to call a method in module/attribute or call the callable
        if method:
            if inspect.ismodule(target):
                func = getattr(target, method, None)
                if callable(func):
                    return func(*a, **kw)
            else:
                func = getattr(target, method, None)
                if callable(func):
                    return func(*a, **kw)
            raise AttributeError(f"Method {method} not found on target {module_path}{f'.{attr}' if attr else ''}")

        if callable(target) and not inspect.ismodule(target):
            return target(*a, **kw)

        return target

    # cm - a helper to handle big actionlist with lists.indexer().root_<action>()
    actionlist = {
        '247movies','247tvshows','yss','weak',
        'sportsbay','sports24','gratis','base','waste','arconai','stratus','distro',
        'xumo','bumble','pluto','tubi','spanish','spanish2','bp','arabic','arabic2','india','chile','colombia','argentina',
        'spain','cctv','titan','porn','faith','lust','greyhat','absolution','eyecandy','purplehat','retribution','kiddo',
        'redhat','yellowhat','blackhat','food','ncaa','ncaab','lfl','xfl','boxing','tennis','mlb','nfl','nhl','nba',
        'ufc','fifa','wwe','motogp','f1','pga','nascar','cricket','sports_channels','sreplays','greenhat'
    }

    action = p('action')
    if action is None:
        # default action
        call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='root')
        cache.cache_version_check()
        return

    # cm - a helper to handle big actionlist with lists.Indexer().root_<action>()
    if action in actionlist:
        idx = call_module('resources.lib.indexers.lists', 'Indexer', inst=True)
        func_name = f'root_{action}'
        if hasattr(idx, func_name):
            func = getattr(idx, func_name)
            if callable(func):
                func()
            else:
                c.log(f"[router] Function {func_name} not callable for action: {action}")
        else:
            # Safely resolve and call the 'root' attribute only if callable.
            root = getattr(idx, 'root', None)
            if callable(root):
                root()
            else:
                c.log(f"[router] indexer 'root' not callable for action: {action}")
        return

    # cm - a helper for docuHeaven fallback
    def _docu_heaven():
        if p('docuCategories') is not None:
            call_module('resources.lib.indexers.docu', 'Documentary', True, 'docu_categories', * (p('docuCategories'),))
        elif p('docuCat') is not None:
            call_module('resources.lib.indexers.docu', 'Documentary', True, 'docu_list', * (p('docuCat'),))
        elif p('docuPlay') is not None:
            call_module('resources.lib.indexers.docu', 'Documentary', True, 'docu_play', * (p('docuPlay'),))
        else:
            call_module('resources.lib.indexers.docu', 'Documentary', inst=True, method='root')
    # cm - the complex 'play' handler reused by play/play1 where play1 needs to be discontinued
    def _play_handler(use_player=False):
        try:
            # Devmode logging for play handler
            _log_router_call("_play_handler",
                            title=p("title"),
                            year=p("year"),
                            imdb=p("imdb"),
                            season=p("season"),
                            episode=p("episode"),
                            content=p('content'))

            content = p('content')
            # Simple player routing logic:
            # - content='addons' -> Simple player (addon/plugin content, no metadata)
            # - content='0' -> Simple player (no IDs for scraping)
            # - content='movies'/'tvshows'/etc. -> Main player (has IDs, use Trakt tracking)
            # - content=None -> Main player (default for movies/episodes modules)
            if content == 'addons' or content == '0':
                _log_router_call("_play_handler.simple", player="lists.player", content=content)
                # lists.player().play(url, content)
                call_module('resources.lib.indexers.lists', 'player', True, 'play', * (p('url'), content))
                return
            # sources.Sources().play(...) - Use full scraper system with Trakt tracking
            # This handles: movies, tvshows, or None (normal playback with metadata)
            _log_router_call("_play_handler.main", player="Sources", content=content)
            call_module('resources.lib.modules.sources', 'Sources', inst=True, method='play', title=p('title'), year=p('year'), imdb=p('imdb'), tmdb=p('tmdb'), season=p('season'), episode=p('episode'), tvshowtitle=p('tvshowtitle'), premiered=p('premiered'), meta=p('meta'), select=p('select'), upnext=p('upnext'))
        except Exception as e:
            c.log(f'[router._play_handler] Traceback: {traceback.format_exc()}')
            c.log(f'[router._play_handler] Error: {e}')

    # cm - the download handler (keeps original silent failure behaviour)
    def _download_handler():
        try:
            src = p('source')
            # use top-level downloader/local_sources imported above
            downloader.download(p('name'), p('image'), local_sources.Sources().sourcesResolve(json.loads(src)[0], True))
        except (ValueError, IndexError, TypeError, KeyError, json.JSONDecodeError) as e:
            c.log(f"[router._download_handler] Download handler error: {e}")
            # ignore expected parsing/indexing/type errors but avoid catching all Exceptions


    # cm - the random handler preserves original branching
    def _random_handler():
        try:
            rtype = p('rtype')
            rlist = []
            r = f"{sys.argv[0]}?action=play"

            if rtype == 'movie':
                rlist = call_module('resources.lib.indexers.movies', 'Movies', inst=True, method='get', create_directory=False, url=p('url'))
            elif rtype == 'episode':
                # use the correct attribute/class name 'episodes' (not 'episode')
                rlist = call_module('resources.lib.indexers.episodes', 'Episodes', inst=True, method='get', create_directory=False, tvshowtitle=p('tvshowtitle'), year=p('year'), imdb=p('imdb'), tmdb=p('tmdb'), meta=p('meta'), season=p('season'))
            elif rtype == 'season':
                rlist = call_module('resources.lib.indexers.episodes', 'Seasons', inst=True, method='get', create_directory=False, tvshowtitle=p('tvshowtitle'), year=p('year'), imdb=p('imdb'), tmdb=p('tmdb'), meta=p('meta'))
                r = f"{sys.argv[0]}?action=random&rtype=episode"
            elif rtype == 'show':
                rlist = call_module('resources.lib.indexers.tvshows', 'TVShows', inst=True, method='get', create_directory=False, url=p('url'))
                r = f"{sys.argv[0]}?action=random&rtype=season"

            # Defensive normalization: ensure we have a sequence
            if not rlist:
                control.infoDialog(control.lang(32537), time=8000)
                return

            if not isinstance(rlist, (list, tuple)):
                if isinstance(rlist, dict):
                    rlist = [rlist]
                else:
                    # Only attempt to convert to list if object is actually iterable
                    if hasattr(rlist, '__iter__'):
                        try:
                            rlist = list(rlist) # type: ignore
                        except Exception:
                            c.log(f"[router._random_handler] converting rlist to list failed (type={type(rlist)}): {repr(rlist)}")
                            control.infoDialog(control.lang(32537), time=8000)
                            return
                    else:
                        c.log(f"[router._random_handler] rlist not iterable (type={type(rlist)}): {repr(rlist)}")
                        control.infoDialog(control.lang(32537), time=8000)
                        return

            rand = randint(0, len(rlist) - 1)
            for pkey in ['title', 'year', 'imdb', 'tmdb', 'season', 'episode', 'tvshowtitle', 'premiered', 'select']:
                try:
                    if rtype == "show" and pkey == "tvshowtitle":
                        r += '&' + pkey + '=' + quote_plus(rlist[rand].get('title', ''))
                    else:
                        r += '&' + pkey + '=' + quote_plus(str(rlist[rand].get(pkey, '')))
                except Exception:
                    pass
            try:
                r += f'&meta={quote_plus(json.dumps(rlist[rand]))}'
            except Exception:
                r += '&meta=' + quote_plus("{}")
            # feedback dialogs similar to original
            if rtype == "movie":
                try:
                    control.infoDialog(rlist[rand].get('title', ''), control.lang(32536), time=30000)
                except Exception:
                    pass
            elif rtype == "episode":
                try:
                    control.infoDialog(f"{rlist[rand].get('tvshowtitle','')} - Season {rlist[rand].get('season','')} - {rlist[rand].get('title','')}", control.lang(32536), time=30000)
                except Exception:
                    pass
            control.execute(f'RunPlugin({r})')
        except Exception:
            control.infoDialog(control.lang(32537), time=8000)

    # mapping of actions to handlers (covers all actions from original file)
    action_map = {
        # navigator group
        'bluehat': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='bluehat'),
        'movieNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='movies'),
        'movieliteNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='movies', lite=True),
        'mymovieNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='mymovies'),
        'mymovieliteNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='mymovies', lite=True),
        'nav_add_addons': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='add_addons'),
        'tvNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='tvshows'),
        'traktlist': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='traktlist'),
        'tmdbtvlist': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='tmdbtvlist'),
        'tmdbmovieslist': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='tmdbmovieslist'),
        'tvliteNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='tvshows', lite=True),
        'mytvNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='mytvshows'),
        'mytvliteNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='mytvshows', lite=True),
        'downloadNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='downloads'),
        'libraryNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='library'),
        'OrionNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='orionoid'),
        'toolNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='tools'),
        'developers': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='developers'),
        'cachingTools': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='cachingTools'),
        'searchNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='search'),
        'viewsNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='views'),
        'clearCache': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='clearCache'),
        'clearAllCache': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='clearCacheAll'),
        'clearMetaCache': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='clearCacheMeta'),
        'clearCacheSearch': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='clearCacheSearch'),
        'scraperStatus': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='scraperStatus'),
        'uploadLogs': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='uploadLogs'),
        'uploadKodiLog': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='uploadKodiLog'),
        'uploadCrewLog': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='uploadCrewLog'),
        'newsNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='news'),
        'collectionsNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='collections'),
        'collectionActors': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='collectionActors'),
        'collectionBoxset': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='collectionBoxset'),
        'collectionBoxsetKids': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='collectionBoxsetKids'),
        'collectionKids': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='collectionKids'),
        'collectionSuperhero': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='collectionSuperhero'),
        'holidaysNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='holidays'),
        'halloweenNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='halloween'),
        'kidsgreyNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='kidsgrey'),
        'kidsNavigator': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='kids'),

        # adult section with PIN protection
        'porn_check_pin': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='porn_check_pin'),
        'enable_adult_pin': lambda: call_module('resources.lib.modules.adult_pin', 'AdultPIN', inst=False, method='enable_protection'),
        'disable_adult_pin': lambda: call_module('resources.lib.modules.adult_pin', 'AdultPIN', inst=False, method='disable_protection'),
        'setup_adult_pin': lambda: call_module('resources.lib.modules.adult_pin', 'AdultPIN', inst=False, method='setup_pin'),
        'reset_adult_pin': lambda: call_module('resources.lib.modules.adult_pin', 'AdultPIN', inst=False, method='reset_pin'),
        'remove_adult_pin': lambda: call_module('resources.lib.modules.adult_pin', 'AdultPIN', inst=False, method='remove_pin'),

        # log upload handlers
        'upload_kodi_log': lambda: call_module('resources.lib.modules.log_uploader', 'LogUploader', inst=False, method='upload_kodi_log'),
        'upload_crew_log': lambda: call_module('resources.lib.modules.log_uploader', 'LogUploader', inst=False, method='upload_crew_log'),

        # adult section handlers
        'adult_site_handler': lambda: call_module('resources.lib.indexers.adult', 'Adult', inst=True, method='site_handler', site_name=p('site')),
        'adult_videos': lambda: call_module('resources.lib.indexers.adult', 'Adult', inst=True, method='videos', site_name=p('site'), url=p('url'), page=p('page')),
        'adult_search': lambda: call_module('resources.lib.indexers.adult', 'Adult', inst=True, method='search', site_name=p('site')),
        'adult_play': lambda: call_module('resources.lib.indexers.adult', 'Adult', inst=True, method='play', site_name=p('site'), video_url=p('url')),

        # lists indexer shortcuts
        'gitNavigator': lambda: call_module('resources.lib.indexers.lists', 'Indexer', inst=True, method='root_git'),
        'plist': lambda: call_module('resources.lib.indexers.lists', 'Indexer', inst=True, method='root_personal'),
        'directory': lambda: call_module('resources.lib.indexers.lists', 'Indexer', True, 'get', * (p('url'),)),
        'qdirectory': lambda: call_module('resources.lib.indexers.lists', 'Indexer', True, 'getq', * (p('url'),)),
        'xdirectory': lambda: call_module('resources.lib.indexers.lists', 'Indexer', True, 'getx', * (p('url'),)),
        'developer': lambda: call_module('resources.lib.indexers.lists', 'Indexer', inst=True, method='developer'),
        'tvtuner': lambda: call_module('resources.lib.indexers.lists', 'Indexer', True, 'tvtuner', * (p('url'),)),
        'youtube': lambda: call_module('resources.lib.indexers.lists', 'Indexer', True, 'youtube', * (p('url'), p('action'))),
        'browser': lambda: call_module('resources.lib.indexers.lists', 'Indexer', True, 'browser', * (p('url'),)),
        'docuNavigator': lambda: call_module('resources.lib.indexers.docu', 'Documentary', inst=True, method='root'),
        'docuHeaven': _docu_heaven,

        # movies
        'movies': lambda:
            call_module('resources.lib.indexers.movies', 'Movies', True, 'get', * (p('url'), p('tid')) )
            if p('url') in ['tmdb_networks', 'tmdb_networks_no_unaired'] else
            call_module('resources.lib.indexers.movies', 'Movies', True, 'get', * (p('url'),)),
        'movieProgress': lambda: call_module('resources.lib.indexers.movies', 'Movies', True, 'get', * (p('action'),)),
        'moviePage': lambda: call_module('resources.lib.indexers.movies', 'Movies', True, 'get', * (p('url'),)),
        'movieWidget': lambda: call_module('resources.lib.indexers.movies', 'Movies', inst=True, method='widget'),
        'movieSearch': lambda: call_module('resources.lib.indexers.movies', 'Movies', inst=True, method='search'),
        'movieSearchnew': lambda: call_module('resources.lib.indexers.movies', 'Movies', inst=True, method='search_new'),
        'movieSearchterm': lambda: call_module('resources.lib.indexers.movies', 'Movies', True, 'search_term', * (p('name'),)),
        'movieDeleteTerm': lambda: call_module('resources.lib.indexers.movies', 'Movies', True, 'delete_search_term', * (p('id'),)),
        'movieAdvancedSearch': lambda: call_module('resources.lib.indexers.movies', 'Movies', True, 'advanced_search', *(p('filter_id'),)),
        'movieSavedFilters': lambda: call_module('resources.lib.indexers.movies', 'Movies', True, 'saved_filters_list'),
        'movieExecuteFilter': lambda: call_module('resources.lib.indexers.movies', 'Movies', True, 'execute_saved_filter', *(p('id'),)),
        'movieDeleteFilter': lambda: call_module('resources.lib.indexers.movies', 'Movies', True, 'delete_saved_filter', *(p('id'),)),
        'movieClearAllFilters': lambda: call_module('resources.lib.indexers.movies', 'Movies', True, 'clear_all_saved_filters'),
        'moviePerson': lambda: call_module('resources.lib.indexers.movies', 'Movies', inst=True, method='person'),
        'movieGenres': lambda: call_module('resources.lib.indexers.movies', 'Movies', inst=True, method='genres'),
        'movieLanguages': lambda: call_module('resources.lib.indexers.movies', 'Movies', inst=True, method='languages'),
        'movieCertificates': lambda: call_module('resources.lib.indexers.movies', 'Movies', inst=True, method='certifications'),
        'movieYears': lambda: call_module('resources.lib.indexers.movies', 'Movies', inst=True, method='years'),
        'moviePersons': lambda: call_module('resources.lib.indexers.movies', 'Movies', True, 'persons', * (p('url'),)),
        'movieUserlists': lambda: call_module('resources.lib.indexers.movies', 'Movies', inst=True, method='userlists'),
        # tvshows
        'tvshows': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', True, 'get', * (p('url'), p('tid')) ) if p('url') == 'tmdb_networks' else call_module('resources.lib.indexers.tvshows', 'TVShows', True, 'get', * (p('url'),)),
        'tvshowPage': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', True, 'get', * (p('url'),)),
        'tvSearch': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', inst=True, method='search'),
        'tvSearchnew': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', inst=True, method='search_new'),
        'tvSearchterm': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', True, 'search_term', * (p('name'),)),
        'tvDeleteTerm': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', True, 'delete_search_term', * (p('id'),)),
        'tvAdvancedSearch': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', True, 'advanced_search', *(p('filter_id'),)),
        'tvSavedFilters': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', True, 'saved_filters_list'),
        'tvExecuteFilter': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', True, 'execute_saved_filter', *(p('id'),)),
        'tvDeleteFilter': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', True, 'delete_saved_filter', *(p('id'),)),
        'tvClearAllFilters': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', True, 'clear_all_saved_filters'),
        'tvPerson': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', inst=True, method='person'),
        'tvGenres': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', inst=True, method='genres'),
        'tvNetworks': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', inst=True, method='networks'),
        'tvLanguages': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', inst=True, method='languages'),
        'tvCertificates': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', inst=True, method='certifications'),
        'tvPersons': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', True, 'persons', * (p('url'),)),
        'tvUserlists': lambda: call_module('resources.lib.indexers.tvshows', 'TVShows', inst=True, method='userlists'),
        'tvevening': lambda: call_module('resources.lib.modules.tvevening', None, False, method='start_tv_evening'),
        'watchplaylist': lambda: call_module('resources.lib.modules.tvevening', None, False, method='show_current_playlist'),
        # seasons / episodes
        'seasons': lambda: call_module('resources.lib.indexers.episodes', 'Seasons', True, 'get', * (p('tvshowtitle'), p('year'), p('imdb'), p('tmdb'), p('meta'))),
        'episodes': lambda: call_module('resources.lib.indexers.episodes', 'Episodes', True, 'get',
                                       * (p('tvshowtitle'), p('year'), p('imdb'), p('tmdb'), p('meta'), p('season'), p('episode'))),
        'calendar': lambda: call_module('resources.lib.indexers.episodes', 'Episodes', True, 'calendar', * (p('url'),)),
        # Progress indexer - new clean implementation
        'progress_shows': lambda: call_module('resources.lib.indexers.progress', 'Progress', inst=True, method='get_in_progress_shows', page=p('page')),
        'progress_next_episodes': lambda: call_module('resources.lib.indexers.progress', 'Progress', inst=True, method='get_next_episodes', page=p('page')),
        'progress_in_progress_episodes': lambda: call_module('resources.lib.indexers.progress', 'Progress', inst=True, method='get_in_progress_episodes', page=p('page')),
        'tvWidget': lambda: call_module('resources.lib.indexers.episodes', 'Episodes', inst=True, method='widget'),
        'calendars': lambda: call_module('resources.lib.indexers.episodes', 'Episodes', inst=True, method='calendars'),
        # Calendar menus (added 2026-03-10, moved to navigator 2026-03-10 for maintainability)
        'calendars_menu': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='calendars_menu'),
        'movies_calendars_menu': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='movies_calendars_menu'),
        'movies_calendar': lambda: call_module('resources.lib.indexers.movies', 'Movies', True, 'get', * (p('url'),)),
        'episodeUserlists': lambda: call_module('resources.lib.indexers.episodes', 'Episodes', inst=True, method='userlists'),
        # settings / control
        'setfanartquality': lambda: call_module('resources.lib.modules.control', '', method='setFanartQuality'),
        'refresh': lambda: call_module('resources.lib.modules.control', '', method='refresh'),
        'queueItem': lambda: call_module('resources.lib.modules.control', '', method='queueItem'),
        'openSettings': lambda: call_module('resources.lib.modules.control', '', False, 'openSettings', * (p('query'),)),
        # orion
        'authorizeOrion': lambda: call_module('resources.lib.apis.orion_api', 'oa', method='authorize_orion'),
        'userInfoOrion': lambda: call_module('resources.lib.apis.orion_api', 'oa', method='user_info_orion'),
        'filtersOrion': lambda: call_module('resources.lib.apis.orion_api', 'oa', method='settings_orion_filters'),
        'get_qrcode': lambda: call_module('resources.lib.apis.orion_api', 'orion_api', method='get_orion_qr'),
        # trakt / maintenance / misc
        'traktSyncsetup': lambda: call_module('.trakt', None, False, method='traktSyncsetup'),
        'traktchecksync': lambda: call_module('.trakt', None, False, method='check_sync_tables'),
        'traktgetcollections': lambda: call_module('.trakt', None, False, 'get_trakt_collection', * ('all',)),
        'startupMaintenance': lambda: call_module('.control', None, False, method='startupMaintenance'),
        'setSizes': lambda: call_module('.control', None, False, method='setSizes'),
        'updateSizes': lambda: call_module('.control', None, False, method='updateSizes'),
        'changelog': lambda: call_module('resources.lib.modules.changelog', method='get'),
        'artwork': lambda: call_module('.control', None, False, method='artwork'),
        'addView': lambda: call_module('.views', None, False,  method='add_view', **{'content': p('content')}),

        'moviePlaycount': lambda: call_module('.playcount', None, False, 'movies', * (p('imdb'), p('query'))),
        'episodePlaycount': lambda: call_module('.playcount', None, False, 'episode', p('imdb'), p('tmdb'), p('season'), p('episode'), p('query')),
        'seasonPlaycount': lambda: call_module('.playcount', None, False, 'season', * (p('imdb'), p('tmdb'), p('season'), p('query'))),
        'tvPlaycount': lambda: call_module('.playcount', None, False, 'tvshows', * (p('imdb'), p('tmdb'), p('query'))),

        'movieClearBookmark': lambda: call_module('.bookmarks', None, False, 'clear_resume_point', 'movie', p('imdb'), None, None, None, p('redirect')),
        'episodeClearBookmark': lambda: call_module('.bookmarks', None, False, 'clear_resume_point', 'episode', p('imdb'), p('season'), p('episode'), p('tmdb'), p('redirect')),

        'trailer': lambda: call_module('.trailer', 'Trailers', True, 'get', * (p('name'), p('url'), p('imdb'), p('tmdb'), int(p('windowedtrailer') or 0), p('mediatype'), p('meta'))),

        'traktManager': lambda: call_module('resources.lib.modules.trakt','', False, 'manager', * (p('name'), p('imdb'), p('tmdb'), p('content'))),
        'traktMyRatings': lambda: call_module('resources.lib.modules.trakt', None, False, 'my_ratings_menu'),
        'traktMyStatistics': lambda: call_module('resources.lib.modules.trakt', None, False, 'show_stats_dialog'),
        'authTrakt': lambda: call_module('resources.lib.modules.trakt', None, False, method='auth_trakt'),
        'runTVEveningTest': lambda: call_module('resources.lib.modules.test_runner', 'TestRunner', inst=True, method='run_tv_evening_test'),
        'testSourcesArchEpisode': lambda: call_module('resources.lib.modules.sources_test', None, False, method='test_refactored_architecture_episode'),
        'testSourcesArchMovie': lambda: call_module('resources.lib.modules.sources_test', None, False, method='test_refactored_architecture_movie'),
        'devKeep': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='devKeep'),
        'devPurplehat': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='devPurplehat'),
        'devTools': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='devTools'),
        'encodeApiKey': lambda: call_module('resources.lib.modules.key_encoder', None, False, method='show_key_encoder_dialog'),
        'testAPIClasses': lambda: call_module('resources.lib.modules.api_tester', None, False, method='run_api_tests'),
        'authRD': lambda: (
            call_module('resources.lib.modules.debridapis.realdbrid', None, False, method='__dict__') ,
            call_module('.control', None, False, method='infoDialog'))[1],
        'debridAccountManager': lambda: call_module('resources.lib.modules.debrid_manager', 'DebridAccountManager', inst=True, method='show_account_info'),

        # Debrid management and cloud browsing
        'debridManagement': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='debridManagement'),
        'debridCloud': lambda: call_module('resources.lib.indexers.navigator', 'Navigator', inst=True, method='debridCloud'),

        # Real-Debrid cloud operations
        'rd_cloud': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='rd_cloud'),
        'rd_cloud_browse': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='rd_cloud_browse', **{'torrent_id': p('torrent_id')}),
        'rd_cloud_play': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='rd_cloud_play', **{'link': p('link')}),
        'rd_cloud_delete': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='rd_cloud_delete', **{'torrent_id': p('torrent_id')}),
        'rd_cloud_add': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='rd_cloud_add'),

        # AllDebrid cloud operations
        'ad_cloud': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='ad_cloud'),
        'ad_cloud_browse': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='ad_cloud_browse', **{'magnet_id': p('magnet_id')}),
        'ad_cloud_play': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='ad_cloud_play', **{'link': p('link')}),
        'ad_cloud_delete': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='ad_cloud_delete', **{'magnet_id': p('magnet_id')}),
        'ad_cloud_add': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='ad_cloud_add'),

        # Premiumize cloud operations
        'pm_cloud': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='pm_cloud', **{'folder_id': p('folder_id')}),
        'pm_cloud_play': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='pm_cloud_play', **{'link': p('link')}),
        'pm_cloud_delete': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='pm_cloud_delete', **{'item_id': p('item_id')}),
        'pm_cloud_add': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='pm_cloud_add'),
        'pm_transfers': lambda: call_module('resources.lib.modules.debrid_cloud', None, False, method='pm_transfers'),

        'ResolveUrlTorrent': lambda: call_module('.control', None, False, 'openSettings', * (p('query'), "script.module.resolveurl")),
        'ResolveUrlSettings': lambda: call_module('.control', None, False, 'openSettings', * (p('query'), "script.module.resolveurl")),
        'download': _download_handler,
        'play': _play_handler,
        'play1': _play_handler,
        'addItem': lambda: call_module('resources.lib.modules.sources', 'Sources', True, 'addItem', * (p('title'),)),
        'playItem': lambda: call_module('resources.lib.modules.sources', 'Sources', True, 'playItem', * (p('title'), p('source'))),
        'alter_sources': lambda: call_module('resources.lib.modules.sources', 'Sources', True, 'alter_sources', * (p('url'), p('meta'))),
        'clearSources': lambda: call_module('resources.lib.modules.sources', 'Sources', True, 'clearSources'),
        'random': _random_handler,
        # library / sync / tools
        'movieToLibrary': lambda: (
            call_module('resources.lib.modules.libtools', 'libmovies', inst=True),
            call_module('resources.lib.modules.libtools', 'libmovies', inst=True, method='add', **{'name': p('name'), 'title': p('title'), 'year': p('year'), 'imdb': p('imdb'), 'tmdb': p('tmdb')})
        )[1],
        'moviesToLibrary': lambda: (
            call_module('resources.lib.modules.libtools', 'libmovies', inst=True),
            call_module('resources.lib.modules.libtools', 'libmovies', inst=True, method='range', url=p('url'))
        )[1],
        'moviesToLibrarySilent': lambda: (
            call_module('resources.lib.modules.libtools', 'libmovies', inst=True),
            call_module('resources.lib.modules.libtools', 'libmovies', inst=True, method='silent', url=p('url'))
        )[1],
        'syncTrakt': lambda: call_module('resources.lib.modules.trakt', 'trakt', method='syncTrakt'),
        'tvshowToLibrary': lambda: (
            call_module('resources.lib.modules.libtools', 'libtvshows', inst=True),
            call_module('resources.lib.modules.libtools', 'libtvshows', inst=True, method='add', tvshowtitle=p('tvshowtitle'), year=p('year'), imdb=p('imdb'), tmdb=p('tmdb'))
        )[1],
        'tvshowsToLibrary': lambda: (
            call_module('resources.lib.modules.libtools', 'libtvshows', inst=True),
            call_module('resources.lib.modules.libtools', 'libtvshows', inst=True, method='range', url=p('url'))
        )[1],
        'tvshowsToLibrarySilent': lambda: (
            call_module('resources.lib.modules.libtools', 'libtvshows', inst=True),
            call_module('resources.lib.modules.libtools', 'libtvshows', inst=True, method='silent', url=p('url'))
        )[1],
        'updateLibrary': lambda:
            call_module('resources.lib.modules.libtools', 'libepisodes', inst=True, method='update', query=p('query')),
        'setupLibrarySources': lambda:
            call_module('resources.lib.modules.libtools', 'lib_tools', method='setup_library_sources'),
        'service': lambda: (
            call_module('resources.lib.modules.libtools', 'libepisodes', inst=True),
            call_module('resources.lib.modules.libtools', 'libepisodes', inst=True, method='service')
        )[1],
        'urlResolver': lambda: (importlib.import_module('resolveurl'),
                                call_module('resolveurl', None, method='display_settings'))[1],
        # more lists.indexer roots
        'debridkids': lambda: call_module('resources.lib.indexers.lists', 'Indexer', inst=True, method='root_debridkids'),
        'waltdisney': lambda: call_module('resources.lib.indexers.lists', 'Indexer', inst=True, method='root_waltdisney'),
        'learning': lambda: call_module('resources.lib.indexers.lists', 'Indexer', inst=True, method='root_learning'),
        'songs': lambda: call_module('resources.lib.indexers.lists', 'Indexer', inst=True, method='root_songs'),
        # undesirables management
        'undesirablesSelect': lambda: call_module('.undesirables', None, False, method='undesirablesSelect'),
        'undesirablesInput': lambda: call_module('.undesirables', None, False, method='undesirablesInput'),
        'undesirablesUserRemove': lambda: call_module('.undesirables', None, False, method='undesirablesUserRemove'),
        'undesirablesUserRemoveAll': lambda: call_module('.undesirables', None, False, method='undesirablesUserRemoveAll'),
    }

    # Execute handler if present
    _log_router_call("handler_lookup", action=action)
    handler = action_map.get(action)
    if handler:
        _log_router_call("handler_execute", action=action)
        try:
            result = handler()
            _log_router_call("handler_complete", action=action, status="success")
            return result
        except Exception as e:
            c.log(f"[router] Handler for {action} failed: {e}\n{traceback.format_exc()}")
            raise

    # If not handled, fallback to original verbose chain for any remaining actions
    try:
        # keep original fallback behaviour: try to import modules as in legacy
        # This block mirrors remaining branches that were not mapped above
        # (If you find an unhandled action in logs, add it to action_map)
        c.log(f"[router] Unhandled action: {action}")
    except Exception:
        c.log(f"[router] Unexpected error: {traceback.format_exc()}")
