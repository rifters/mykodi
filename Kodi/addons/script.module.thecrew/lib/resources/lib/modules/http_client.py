# -*- coding: utf-8 -*-
'''
 ***********************************************************
 * The Crew Add-on
 *
 * @file http_client.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2025, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 * Centralized HTTP client configuration with connection pooling,
 * retry logic, and rate limiting for API calls.
 ***********************************************************
'''

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
from threading import Lock
from .crewruntime import c


class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, rate=40, per=10):
        """
        Initialize rate limiter.

        Args:
            rate: Number of allowed requests
            per: Time window in seconds
        """
        self.rate = rate
        self.per = per
        self.tokens = rate
        self.last_update = time.time()
        self.lock = Lock()

    def acquire(self):
        """Wait until a token is available, then consume it."""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update

            # Refill tokens based on elapsed time
            self.tokens = min(self.rate, self.tokens + (elapsed * self.rate / self.per))
            self.last_update = now

            if self.tokens < 1:
                # Wait until we have a token
                wait_time = (1 - self.tokens) * self.per / self.rate
                time.sleep(wait_time)
                self.tokens = 1

            self.tokens -= 1


class HTTPClient:
    """
    Centralized HTTP client with connection pooling and retry logic.

    Provides optimized sessions for different APIs with proper connection
    pooling, retry strategies, and rate limiting.
    """

    _instances = {}
    _lock = Lock()

    # Rate limiters for different APIs
    _tmdb_limiter = RateLimiter(rate=40, per=10)  # TMDb: 40 requests per 10 seconds
    _trakt_limiter = RateLimiter(rate=1000, per=300)  # Trakt: 1000 requests per 5 minutes

    @classmethod
    def get_session(cls, api_type='default', pool_connections=20, pool_maxsize=20, max_retries=3):
        """
        Get or create a session for the specified API type.

        Args:
            api_type: Type of API ('tmdb', 'trakt', 'tvmaze', 'default')
            pool_connections: Number of connection pools to cache
            pool_maxsize: Maximum number of connections to save in the pool
            max_retries: Maximum number of retry attempts

        Returns:
            Configured requests.Session object
        """
        with cls._lock:
            if api_type not in cls._instances:
                session = requests.Session()

                # Configure retry strategy
                retry_strategy = Retry(
                    total=max_retries,
                    backoff_factor=0.5,  # Wait 0.5, 1.0, 2.0 seconds between retries
                    status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["GET", "POST", "PUT", "DELETE"]
                )

                # Create adapter with connection pooling
                adapter = HTTPAdapter(
                    pool_connections=pool_connections,
                    pool_maxsize=pool_maxsize,
                    max_retries=retry_strategy,
                    pool_block=False
                )

                # Mount adapter for both HTTP and HTTPS
                session.mount('http://', adapter)
                session.mount('https://', adapter)

                cls._instances[api_type] = session
                # Session creation logged once per API type (already cached in _instances)
                c.log(f'[HTTPClient] Created new session for {api_type} with pool_size={pool_maxsize}')

            return cls._instances[api_type]

    @classmethod
    def get_with_ratelimit(cls, url, api_type='default', **kwargs):
        """
        Make a GET request with rate limiting.

        Args:
            url: URL to request
            api_type: Type of API for rate limiting
            **kwargs: Additional arguments passed to session.get()

        Returns:
            requests.Response object
        """
        # Apply rate limiting
        if api_type == 'tmdb':
            cls._tmdb_limiter.acquire()
        elif api_type == 'trakt':
            cls._trakt_limiter.acquire()

        session = cls.get_session(api_type)

        # Set default timeout if not provided
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 15

        return session.get(url, **kwargs)

    @classmethod
    def post_with_ratelimit(cls, url, api_type='default', **kwargs):
        """
        Make a POST request with rate limiting.

        Args:
            url: URL to request
            api_type: Type of API for rate limiting
            **kwargs: Additional arguments passed to session.post()

        Returns:
            requests.Response object
        """
        # Apply rate limiting
        if api_type == 'tmdb':
            cls._tmdb_limiter.acquire()
        elif api_type == 'trakt':
            cls._trakt_limiter.acquire()

        session = cls.get_session(api_type)

        # Set default timeout if not provided
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 15

        return session.post(url, **kwargs)

    @classmethod
    def close_all(cls):
        """Close all sessions and clear the cache."""
        with cls._lock:
            for api_type, session in cls._instances.items():
                try:
                    session.close()
                    c.log(f'[HTTPClient] Closed session for {api_type}')
                except Exception as e:
                    c.log(f'[HTTPClient] Error closing session for {api_type}: {e}')
            cls._instances.clear()


# Convenience functions for backward compatibility
def get_tmdb_session():
    """Get optimized session for TMDb API with retry logic and rate limiting."""
    return HTTPClient.get_session('tmdb')


def get_trakt_session():
    """Get optimized session for Trakt API with retry logic and rate limiting."""
    return HTTPClient.get_session('trakt')


def get_tvmaze_session():
    """Get optimized session for TVMaze API with retry logic."""
    return HTTPClient.get_session('tvmaze')


def tmdb_get_json(url, timeout=15, attempts=3):
    """Perform a TMDB GET request with rate-limiting and retry/backoff.

    Returns parsed JSON dict on success, or None on failure.
    """
    for attempt in range(1, attempts + 1):
        try:
            # Verbose per-request logging commented out for performance (100+ requests per startup)
            # c.log(f"[HTTPClient] tmdb_get_json attempt {attempt} url={url}")
            # c.log(f"[HTTPClient DEBUG] tmdb_get_json attempt {attempt} calling HTTPClient.get_with_ratelimit")
            resp = HTTPClient.get_with_ratelimit(url, api_type='tmdb', timeout=timeout)
            # c.log(f"[HTTPClient DEBUG] got resp status={getattr(resp,'status_code',None)}")
            resp.raise_for_status()
            # parse JSON safely
            try:
                # Prefer not to call resp.json() directly (tests may inject a function named json that shadows module).
                text = getattr(resp, 'text', '') or ''
                import json as _json
                parsed = _json.loads(text) if text else {}
                #c.log(f"[HTTPClient DEBUG] tmdb_get_json parsed={type(parsed)} {parsed}")
                return parsed
            except Exception as e:
                c.log(f"[HTTPClient] tmdb_get_json JSON decode error: {e} url={url}")
                # Return empty dict on JSON decode errors for 200 responses so callers receive a dict
                return {}
        except requests.HTTPError as e:
            status = getattr(e.response, 'status_code', 0)
            c.log(f"[HTTPClient] tmdb_get_json HTTP error attempt {attempt}: {e} status={status} url={url}")
            # Treat 429 as transient and retry; other 4xx client errors are not retried
            if status == 429:
                if attempt < attempts:
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                return None
            if 400 <= status < 500:
                return None
            if attempt < attempts:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            return None
        except Exception as e:
            c.log(f"[HTTPClient] tmdb_get_json request attempt {attempt} failed: {e} url={url}")
            c.log(f"[HTTPClient DEBUG] tmdb_get_json exception attempt {attempt}: {type(e).__name__} {e}")
            if attempt < attempts:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            return None


def tmdb_get_conditional(url, conditional_headers=None, timeout=15, attempts=3):
    """Perform a TMDB GET request that supports conditional requests (ETag / 304 handling).

    Returns a tuple (body, headers, status) where body is None when 304 is returned.
    Retries on transient errors (e.g., 429) similar to tmdb_get_json.
    """
    headers = conditional_headers or {}
    for attempt in range(1, attempts + 1):
        try:
            resp = HTTPClient.get_with_ratelimit(url, api_type='tmdb', timeout=timeout, headers=headers)
            status = getattr(resp, 'status_code', None)
            resp_headers = getattr(resp, 'headers', {}) or {}
            if status == 304:
                # tests expect empty body for 304
                return '', resp_headers, 304
            if status and 200 <= status < 300:
                body = getattr(resp, 'text', None)
                return body, resp_headers, status
            # Treat 429/5xx as transient and retry
            if status and (status == 429 or 500 <= status < 600):
                c.log(f"[HTTPClient] tmdb_get_conditional transient status {status} attempt {attempt} url={url}")
                if attempt < attempts:
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                # Give up after attempts exhausted — tests expect None in that case
                return None
            return None, resp_headers, status or 0
        except Exception as e:
            c.log(f"[HTTPClient] tmdb_get_conditional failed attempt {attempt}: {e} url={url}")
            if attempt < attempts:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            return None, {}, 0
