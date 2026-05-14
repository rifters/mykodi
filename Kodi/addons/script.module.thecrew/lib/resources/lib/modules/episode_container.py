# -*- coding: utf-8 -*-

"""
Episode Container System for Up Next Auto-Play
Implements dual-container architecture to prevent metadata contamination during continuous playback

Architecture:
- Primary Container: Currently playing episode (E04)
- Secondary Container: Pre-fetched next episode (E05)
- At 85% playback: Secondary starts pre-fetching
- At 92% or "Play Now": Swap containers atomically
- On "Cancel": Destroy secondary, primary continues

Benefits:
- Zero metadata contamination (E04 offset can't leak to E05)
- Instant transitions (URL pre-scraped during E04 playback)
- Pre-loaded posters for Up Next dialog
- Clean cancel handling (secondary.destroy())
- No timing/synchronization issues
"""

import threading
import time
from resources.lib.modules import control
from resources.lib.modules import log_utils

c = control

# Module-level containers
_primary_episode = None
_secondary_episode = None
_container_lock = threading.Lock()


class EpisodeContainer:
    """Isolated container for episode data - prevents cross-contamination"""

    def __init__(self):
        # Episode identity
        self.title = None
        self.year = None
        self.season = None
        self.episode = None
        self.imdb = None
        self.tmdb = None
        self.tvdb = None
        self.content = 'episode'

        # Playback data
        self.url = None
        self.offset = 0.0  # Always 0.0 for Up Next episodes
        self.sources = []  # Raw scraped sources list
        self.selected_source = None  # Best source after filtering

        # Metadata (from TMDB/Trakt)
        self.metadata = {}  # Full episode metadata
        self.poster = None  # Episode poster/thumbnail
        self.plot = None
        self.rating = None
        self.aired = None

        # State tracking
        self.status = 'empty'  # 'empty', 'prefetching', 'ready', 'playing', 'finished', 'error'
        self.prefetch_thread = None
        self.prefetch_started = 0.0
        self.prefetch_completed = 0.0
        self.error_message = None

    def is_empty(self):
        """Check if container is empty (not initialized)"""
        return self.status == 'empty'

    def is_prefetching(self):
        """Check if container is currently fetching data"""
        return self.status == 'prefetching'

    def is_ready(self):
        """Check if container has all data and is ready to play"""
        return self.status == 'ready'

    def is_playing(self):
        """Check if this episode is currently playing"""
        return self.status == 'playing'

    def is_error(self):
        """Check if prefetch encountered an error"""
        return self.status == 'error'

    def get_episode_string(self):
        """Get formatted episode string (e.g., 'S01E05')"""
        if self.season and self.episode:
            return f"S{int(self.season):02d}E{int(self.episode):02d}"
        return "Unknown"

    def get_prefetch_duration(self):
        """Get how long prefetching took (in seconds)"""
        if self.prefetch_completed > 0 and self.prefetch_started > 0:
            return self.prefetch_completed - self.prefetch_started
        return 0.0

    def mark_watched(self):
        """Mark episode as watched in Trakt/bookmarks"""
        try:
            if self.status == 'playing' and self.imdb and self.season and self.episode:
                from resources.lib.modules import bookmarks
                from resources.lib.modules import trakt
                from resources.lib.modules import control

                # Mark as fully watched in local bookmarks (100% watched = total_time as both values)
                # This sets playcount=1 and overlay=7 (watched indicator)
                bookmarks.reset(
                    current_time=1000,  # >= 92% of total_time triggers "fully watched" logic
                    total_time=1000,    # 100% ratio
                    media_type=self.content,
                    imdb=self.imdb,
                    season=str(self.season),
                    episode=str(self.episode)
                )

                # Scrobble to Trakt as watched with 'stop' action (marks as fully watched)
                if trakt.get_trakt_credentials_info():
                    trakt.scrobbleEpisode(self.imdb, self.season, self.episode, 100, 'stop', use_queue=False)  # 100% progress, immediate API call

                # Set flag for player to refresh container when user exits playback
                # (Can't refresh now - no visible container during fullscreen playback)
                control.window.setProperty('thecrew.container.needs_refresh', 'true')

                c.log(f"[Container] (OK) Marked {self.get_episode_string()} as watched")
                self.status = 'finished'
        except Exception as e:
            c.log(f"[Container] Error marking watched: {e}")

    def destroy(self):
        """Clean disposal of container data"""
        c.log(f"[Container] Destroying container: {self.get_episode_string()} (status: {self.status})")

        # Stop any active prefetch thread
        if self.prefetch_thread and self.prefetch_thread.is_alive():
            # Thread will check status and exit
            self.status = 'destroyed'

        # Reset to empty state
        self.__init__()

    def to_dict(self):
        """Convert container to dictionary (for debugging/logging)"""
        return {
            'episode': self.get_episode_string(),
            'title': self.title,
            'status': self.status,
            'has_url': bool(self.url),
            'sources_count': len(self.sources),
            'prefetch_duration': f"{self.get_prefetch_duration():.1f}s" if self.get_prefetch_duration() > 0 else "N/A"
        }


def get_primary():
    """Get the primary (currently playing) episode container"""
    global _primary_episode
    if _primary_episode is None:
        _primary_episode = EpisodeContainer()
    return _primary_episode


def get_secondary():
    """Get the secondary (pre-fetched next) episode container"""
    global _secondary_episode
    if _secondary_episode is None:
        _secondary_episode = EpisodeContainer()
    return _secondary_episode


def swap_containers():
    """
    Atomic swap: Promote secondary to primary, destroy old primary
    Call this when Up Next triggers (92% or "Play Now")
    """
    global _primary_episode, _secondary_episode

    with _container_lock:
        # Mark old episode as watched
        if _primary_episode and _primary_episode.is_playing():
            _primary_episode.mark_watched()

        # Promote secondary to primary
        old_primary = _primary_episode
        _primary_episode = _secondary_episode
        _primary_episode.status = 'playing'  # Update status

        # Create fresh empty secondary
        _secondary_episode = EpisodeContainer()

        # Clean up old primary
        if old_primary:
            old_primary.destroy()

        c.log(f"[Container] (OK) SWAPPED: Now playing {_primary_episode.get_episode_string()}")
        c.log(f"[Container] Primary: {_primary_episode.to_dict()}")
        c.log(f"[Container] Secondary: {_secondary_episode.to_dict()}")

        return _primary_episode


def cancel_upnext():
    """
    Handle Up Next cancel: Destroy secondary, primary continues
    """
    global _secondary_episode

    with _container_lock:
        if _secondary_episode and not _secondary_episode.is_empty():
            c.log(f"[Container] Up Next canceled - destroying {_secondary_episode.get_episode_string()}")
            _secondary_episode.destroy()
            _secondary_episode = EpisodeContainer()


def initialize_primary(title, year, season, episode, imdb, tmdb, url, metadata):
    """
    Initialize primary container with current episode data
    Call this from player.run() for the first episode
    """
    global _primary_episode

    with _container_lock:
        _primary_episode = EpisodeContainer()
        _primary_episode.title = title
        _primary_episode.year = year
        _primary_episode.season = str(season)
        _primary_episode.episode = str(episode)
        _primary_episode.imdb = imdb
        _primary_episode.tmdb = tmdb
        _primary_episode.url = url
        _primary_episode.metadata = metadata
        _primary_episode.status = 'playing'

        c.log(f"[Container] (OK) Initialized primary: {_primary_episode.get_episode_string()}")
        return _primary_episode


def start_prefetch(title, year, season, episode, imdb, tmdb):
    """
    Start background prefetch for next episode
    Call this from keepPlaybackAlive() at ~85% playback

    Returns True if prefetch started, False if already in progress or error
    """
    global _secondary_episode

    with _container_lock:
        # Don't start if already prefetching or ready
        if _secondary_episode is not None and (_secondary_episode.is_prefetching() or _secondary_episode.is_ready()):
            c.log(f"[Container] Prefetch already in progress or ready (status: {_secondary_episode.status})")
            return False

        # Initialize secondary container
        _secondary_episode = EpisodeContainer()
        _secondary_episode.title = title
        _secondary_episode.year = year
        _secondary_episode.season = str(season)
        _secondary_episode.episode = str(episode)
        _secondary_episode.imdb = imdb
        _secondary_episode.tmdb = tmdb
        _secondary_episode.status = 'prefetching'
        _secondary_episode.prefetch_started = time.time()

        c.log(f"[Container] ▶ Starting prefetch: {_secondary_episode.get_episode_string()}")

        # Start background thread
        _secondary_episode.prefetch_thread = threading.Thread(
            target=_prefetch_worker,
            args=(title, year, season, episode, imdb, tmdb),
            name=f"Prefetch-S{season:02d}E{episode:02d}"
        )
        _secondary_episode.prefetch_thread.daemon = True
        _secondary_episode.prefetch_thread.start()

        return True


def _prefetch_worker(title, year, season, episode, imdb, tmdb):
    """
    Background worker thread: Scrape and prepare next episode
    This runs in parallel while current episode is playing
    """
    global _secondary_episode

    try:
        c.log(f"[Container] Prefetch worker started for S{season:02d}E{episode:02d}")

        # Import here to avoid circular dependencies
        from resources.lib.modules import sources as sources_module

        # Check if we should abort (user might have canceled)
        if _secondary_episode.status != 'prefetching':
            c.log("[Container] Prefetch aborted (status changed)")
            return

        # Step 1: Scrape sources (this is the time-consuming part)
        c.log(f"[Container] Step 1/3: Scraping sources for S{season:02d}E{episode:02d}...")
        try:
            # Use the existing sources scraping logic
            # Instantiate Sources class and call getSources
            sources_instance = sources_module.Sources()
            sources_list = sources_instance.getSources(
                title=title,
                year=year,
                imdb=imdb,
                tmdb=tmdb,
                season=season,
                episode=episode,
                tvshowtitle=title,
                premiered=None,
                quality='HD',
                timeout=30,
                show_dialog=False,  # Silent scraping
                use_overlay=False,
                upnext=True  # Flag to indicate this is prefetch
            )
            _secondary_episode.sources = sources_list if sources_list else []
            c.log(f"[Container] (OK) Found {len(_secondary_episode.sources)} sources")

            # Cache sources in Window properties so sources.play() can use them instantly
            if sources_list:
                sources_instance.set_upnext_cached_sources(imdb, tmdb, season, episode, sources_list)
                c.log(f"[Container] (OK) Cached {len(sources_list)} sources for instant playback")
        except Exception as e:
            c.log(f"[Container] (X) Source scraping failed: {e}")
            import traceback
            c.log(f"[Container] Traceback: {traceback.format_exc()}")
            _secondary_episode.status = 'error'
            _secondary_episode.error_message = str(e)
            return

        # Check abort again
        if _secondary_episode.status != 'prefetching':
            c.log("[Container] Prefetch aborted after scraping")
            return

        # Step 2: Sort sources (best quality first)
        # Note: URL resolution happens at play time to avoid debrid token expiration
        c.log(f"[Container] Step 2/3: Sorting sources...")
        try:
            if sources_list:
                # Sources are already sorted by getSources()
                # Just get the top sources for quick access
                _secondary_episode.selected_source = sources_list[0] if sources_list else None
                c.log(f"[Container] (OK) Top source ready: {sources_list[0].get('provider') if sources_list else 'None'}")
            else:
                raise Exception("No sources found")
        except Exception as e:
            c.log(f"[Container] (X) Source sorting failed: {e}")
            _secondary_episode.status = 'error'
            _secondary_episode.error_message = str(e)
            return

        # Step 3: Fetch metadata/poster
        c.log(f"[Container] Step 3/3: Fetching metadata...")
        try:
            # Metadata fetching is optional - upnext.py will fetch it when showing dialog
            # For now, skip this step to avoid complexity
            # TODO: Integrate with metacache properly if needed
            c.log(f"[Container] ⓘ Skipping metadata fetch (dialog will fetch it)")
        except Exception as e:
            # Metadata fetch failure is non-fatal, we can still play
            c.log(f"[Container] [WARNING] Metadata fetch failed: {e}")

        # Mark as ready
        _secondary_episode.prefetch_completed = time.time()
        _secondary_episode.status = 'ready'
        duration = _secondary_episode.get_prefetch_duration()
        c.log(f"[Container] (OK) READY: S{season:02d}E{episode:02d} prefetched in {duration:.1f}s")

    except Exception as e:
        import traceback
        c.log(f"[Container] (X) Prefetch failed with exception: {e}")
        c.log(f"[Container] Traceback: {traceback.format_exc()}")
        _secondary_episode.status = 'error'
        _secondary_episode.error_message = str(e)


def reset_all():
    """Reset both containers (for debugging or starting fresh)"""
    global _primary_episode, _secondary_episode

    with _container_lock:
        if _primary_episode:
            _primary_episode.destroy()
        if _secondary_episode:
            _secondary_episode.destroy()

        _primary_episode = EpisodeContainer()
        _secondary_episode = EpisodeContainer()

        c.log("[Container] (OK) Reset all containers")


def get_status_summary():
    """Get summary of both containers (for debugging)"""
    return {
        'primary': _primary_episode.to_dict() if _primary_episode else None,
        'secondary': _secondary_episode.to_dict() if _secondary_episode else None
    }
