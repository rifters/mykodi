# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file api_tester.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 * API Testing Module - Tests new API classes from within Kodi
 *
 ********************************************************cm*
'''

from ..apis.tmdb_api import TMDbAPI
from ..apis.tvdb_api import TVDbAPI
from ..apis.fanart_api import FanartAPI
from .crewruntime import c
import xbmcgui


def test_tmdb_api():
    """Test TMDb API with simple calls"""
    results = []
    results.append("="*80)
    results.append("TESTING TMDb API")
    results.append("="*80)

    try:
        api = TMDbAPI()
        results.append(f"(OK) TMDbAPI initialized")
        results.append(f"  - API Key: {api.api_key[:8]}...")
        results.append(f"  - Language: {api.language}")

        # Test 1: Get popular movies
        results.append("")
        results.append("[Test 1] Getting popular movies...")
        try:
            movies = api.get_popular_movies()
            if movies and 'results' in movies:
                results.append(f"(OK) Success! Found {len(movies['results'])} popular movies")
                if movies['results']:
                    first = movies['results'][0]
                    results.append(f"  - First movie: {first.get('title', 'N/A')} ({first.get('release_date', 'N/A')[:4]})")
            else:
                results.append("(X) Failed - No results returned")
        except Exception as e:
            results.append(f"(X) Error: {e}")

        # Test 2: Get specific movie (Fight Club - TMDb ID: 550)
        results.append("")
        results.append("[Test 2] Getting movie details (Fight Club - ID: 550)...")
        try:
            movie = api.get_movie('550')
            if movie:
                results.append(f"(OK) Success!")
                results.append(f"  - Title: {movie.get('title', 'N/A')}")
                results.append(f"  - Release Date: {movie.get('release_date', 'N/A')}")
                results.append(f"  - Rating: {movie.get('vote_average', 'N/A')}/10")
            else:
                results.append("(X) Failed - No movie data returned")
        except Exception as e:
            results.append(f"(X) Error: {e}")

        # Test 3: Search for a movie
        results.append("")
        results.append("[Test 3] Searching for 'The Matrix'...")
        try:
            search_results = api.search_movie('The Matrix')
            if search_results and 'results' in search_results:
                results.append(f"(OK) Success! Found {len(search_results['results'])} results")
                if search_results['results']:
                    first = search_results['results'][0]
                    results.append(f"  - Top result: {first.get('title', 'N/A')} ({first.get('release_date', 'N/A')[:4]})")
            else:
                results.append("(X) Failed - No results returned")
        except Exception as e:
            results.append(f"(X) Error: {e}")

    except Exception as e:
        results.append(f"(X) Fatal Error: {e}")

    results.append("="*80)
    return results


def test_tvdb_api():
    """Test TVDb API with simple calls"""
    results = []
    results.append("")
    results.append("="*80)
    results.append("TESTING TVDb API")
    results.append("="*80)

    try:
        api = TVDbAPI()
        results.append(f"(OK) TVDbAPI initialized")
        results.append(f"  - API Key: {api.api_key[:8]}...")
        results.append(f"  - Base URL: {api.BASE_URL} (v3)")
        results.append(f"  - Authenticated: {bool(api.token)}")

        if not api.token:
            results.append("")
            results.append("(X) Authentication failed - cannot proceed with tests")
            results.append("="*80)
            return results

        # Test 1: Get series (Breaking Bad - TVDb ID: 81189)
        results.append("")
        results.append("[Test 1] Getting series details (Breaking Bad - ID: 81189)...")
        try:
            series = api.get_series('81189')
            if series:
                results.append(f"(OK) Success!")
                # v3 uses 'seriesName' not 'name'
                results.append(f"  - Name: {series.get('seriesName', series.get('name', 'N/A'))}")
                results.append(f"  - First Aired: {series.get('firstAired', 'N/A')}")
                # v3 status is a string, not an object
                status = series.get('status', 'N/A')
                if isinstance(status, dict):
                    status = status.get('name', 'N/A')
                results.append(f"  - Status: {status}")
            else:
                results.append("(X) Failed - No series data returned")
        except Exception as e:
            results.append(f"(X) Error: {e}")

        # Test 2: Search for a series
        results.append("")
        results.append("[Test 2] Searching for 'Game of Thrones'...")
        try:
            search_results = api.search_series('Game of Thrones')
            if search_results and isinstance(search_results, list):
                results.append(f"(OK) Success! Found {len(search_results)} results")
                if search_results:
                    first = search_results[0]
                    # v3 uses 'seriesName' not 'name'
                    results.append(f"  - Top result: {first.get('seriesName', first.get('name', 'N/A'))}")
            else:
                results.append("(X) Failed - No results returned")
        except Exception as e:
            results.append(f"(X) Error: {e}")

    except Exception as e:
        results.append(f"(X) Fatal Error: {e}")

    results.append("="*80)
    return results


def test_fanart_api():
    """Test Fanart API with simple calls"""
    results = []
    results.append("")
    results.append("="*80)
    results.append("TESTING Fanart.tv API")
    results.append("="*80)

    try:
        api = FanartAPI()
        results.append(f"(OK) FanartAPI initialized")
        results.append(f"  - API Key: {api.api_key[:8]}...")
        results.append(f"  - Base URL: {api.BASE_URL}")
        results.append(f"  - VIP Enabled: {bool(api.client_key)}")

        # Test 1: Get TV artwork (Breaking Bad - TVDb ID: 81189)
        results.append("")
        results.append("[Test 1] Getting TV artwork (Breaking Bad - TVDb ID: 81189)...")
        try:
            artwork = api.get_tv_artwork('81189')
            if artwork:
                results.append(f"(OK) Success! Found artwork types:")
                for art_type, items in artwork.items():
                    if items:
                        results.append(f"  - {art_type}: {len(items)} items")
            else:
                results.append("(X) Failed - No artwork returned")
        except Exception as e:
            results.append(f"(X) Error: {e}")

        # Test 2: Get specific TV poster
        results.append("")
        results.append("[Test 2] Getting TV poster (Breaking Bad)...")
        try:
            poster = api.get_tv_poster('81189')
            if poster:
                results.append(f"(OK) Success!")
                results.append(f"  - Poster URL: {poster[:60]}...")
            else:
                results.append("(X) Failed - No poster returned")
        except Exception as e:
            results.append(f"(X) Error: {e}")

        # Test 3: Get movie artwork (Fight Club - TMDb ID: 550)
        results.append("")
        results.append("[Test 3] Getting movie artwork (Fight Club - TMDb ID: 550)...")
        try:
            artwork = api.get_movie_artwork('550')
            if artwork:
                results.append(f"(OK) Success! Found artwork types:")
                for art_type, items in artwork.items():
                    if items:
                        results.append(f"  - {art_type}: {len(items)} items")
            else:
                results.append("(X) Failed - No artwork returned")
        except Exception as e:
            results.append(f"(X) Error: {e}")

    except Exception as e:
        results.append(f"(X) Fatal Error: {e}")

    results.append("="*80)
    return results


def run_api_tests():
    """
    Run all API tests and display results in Kodi text viewer.
    This function is called from the DevTools menu.
    """
    c.log("[API Tester] Starting API class tests...", 1)

    # Collect all test results
    all_results = []

    all_results.append("="*80)
    all_results.append("NEW API CLASSES - TEST SUITE")
    all_results.append("="*80)
    all_results.append("")
    all_results.append("This test suite verifies the new API classes:")
    all_results.append("  • TMDbAPI  - The Movie Database API")
    all_results.append("  • TVDbAPI  - TheTVDB API")
    all_results.append("  • FanartAPI - Fanart.tv API")
    all_results.append("")

    # Run tests
    try:
        all_results.extend(test_tmdb_api())
    except Exception as e:
        all_results.append(f"(X) TMDb tests crashed: {e}")

    try:
        all_results.extend(test_tvdb_api())
    except Exception as e:
        all_results.append(f"(X) TVDb tests crashed: {e}")

    try:
        all_results.extend(test_fanart_api())
    except Exception as e:
        all_results.append(f"(X) Fanart tests crashed: {e}")

    # Summary
    all_results.append("")
    all_results.append("="*80)
    all_results.append("TEST SUITE COMPLETED")
    all_results.append("="*80)
    all_results.append("")
    all_results.append("NOTE: Some tests may fail if:")
    all_results.append("  • API keys are not properly configured")
    all_results.append("  • Network connection is unavailable")
    all_results.append("  • API services are experiencing issues")
    all_results.append("  • Rate limits are exceeded")
    all_results.append("")

    # Join results and display in Kodi text viewer
    result_text = '\n'.join(all_results)

    # Log results to log file
    c.log("[API Tester] Test Results:", 1)
    for line in all_results:
        c.log(f"[API Tester] {line}", 1)

    # Show results in Kodi text viewer
    dialog = xbmcgui.Dialog()
    dialog.textviewer('[COLOR cyan]API Test Results[/COLOR]', result_text)

    c.log("[API Tester] Tests completed", 1)
