# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file base.py
* @package script.module.thecrew
*
* Base class for adult site handlers
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''


import re
import sys
import traceback
from ..modules import client
from ..modules.crewruntime import c


class CrewAdult:
    """Base class for adult site handlers"""

    # Class-level registry of all site instances
    _sites = {}

    def __init__(self, name, title, icon=None, fanart=None):
        """
        Initialize an adult site handler

        Args:
            name: Unique identifier for the site (used in routing)
            title: Display title for the site
            icon: Path to icon image (full path)
            fanart: Path to fanart image
        """
        self.name = name
        self.title = title
        # Store full path directly
        self.icon = icon or c.addon_adult_icon()
        self.fanart = fanart or c.addon_fanart()

        # Register this site
        CrewAdult._sites[name] = self

    @classmethod
    def get_site(cls, name):
        """Get a registered site by name"""
        return cls._sites.get(name)

    @classmethod
    def get_all_sites(cls):
        """Get all registered sites"""
        return list(cls._sites.values())

    def get_categories(self):
        """
        Get categories for this site (if applicable)
        Returns: List of tuples (category_url, category_name, thumbnail)
        """
        return []

    def get_videos(self, url, page=1):
        """
        Get videos from a listing page

        Args:
            url: The page URL
            page: Page number

        Returns:
            List of tuples (video_url, title, thumbnail)
        """
        raise NotImplementedError("Subclass must implement get_videos()")

    def search(self, keyword):
        """
        Search for videos

        Args:
            keyword: Search term

        Returns:
            List of tuples (video_url, title, thumbnail)
        """
        return []

    def resolve(self, url):
        """
        Resolve a video page URL to a playable video URL

        Args:
            url: Video page URL

        Returns:
            Playable video URL or None
        """
        raise NotImplementedError("Subclass must implement resolve()")

    def _cleanup_title(self, title):
        """Remove HTML entities from title"""
        if not title:
            return ''
        # Remove &#digits; patterns
        title = re.sub(r'&#(\d+);', '', title)
        # Basic HTML entity replacements
        title = title.replace('&amp;', '&')
        title = title.replace('&quot;', '"')
        title = title.replace('&apos;', "'")
        title = title.replace('&lt;', '<')
        title = title.replace('&gt;', '>')
        return title.strip()

    def _try_resolveurl(self, url):
        """
        Try to resolve URL using resolveurl framework

        Args:
            url: URL to resolve

        Returns:
            Resolved URL or None
        """
        try:
            import resolveurl

            c.log(f'[CrewAdult.{self.name}] Attempting resolveurl for: {url}')

            # Add xxx plugins path
            xxx_plugins_path = 'special://home/addons/script.module.resolveurl.xxx/resources/plugins/'
            try:
                import xbmcvfs
                translated_path = xbmcvfs.translatePath(xxx_plugins_path)
                if xbmcvfs.exists(translated_path):
                    resolveurl.add_plugin_dirs(translated_path)
                    c.log(f'[CrewAdult.{self.name}] Added xxx plugin directory: {translated_path}')
                else:
                    c.log(f'[CrewAdult.{self.name}] WARNING: xxx plugin directory not found: {translated_path}')
            except Exception as e:
                c.log(f'[CrewAdult.{self.name}] Failed to add plugin directory: {e}')

            hmf = resolveurl.HostedMediaFile(url=url)
            c.log(f'[CrewAdult.{self.name}] HostedMediaFile valid_url: {hmf.valid_url()}')

            if hmf.valid_url():
                c.log(f'[CrewAdult.{self.name}] Attempting to resolve...')
                resolved = hmf.resolve()
                if resolved:
                    c.log(f'[CrewAdult.{self.name}] (OK) Resolved via resolveurl: {resolved[:100]}...')
                    return resolved
                else:
                    c.log(f'[CrewAdult.{self.name}] (X) Resolve returned None/empty')
            else:
                c.log(f'[CrewAdult.{self.name}] (X) URL not recognized as valid by resolveurl')

        except Exception as e:

            c.log(f'[CrewAdult.{self.name}] (X) Resolveurl exception: {e}')
            c.log(traceback.format_exc())

        return None

    def _extract_video_url(self, html, patterns=None):
        """
        Extract video URL from HTML using common patterns

        Args:
            html: HTML content
            patterns: List of regex patterns to try (uses defaults if None)

        Returns:
            Video URL or None
        """
        if patterns is None:
            patterns = [
                r'<video[^>]*src=["\']([^"\']+)["\']',
                r'<source[^>]*src=["\']([^"\']+)["\']',
                r'video_url\s*=\s*["\']([^"\']+)["\']',
                r'https?://[^"\'\s<>]+\.mp4[^"\'\s<>]*',
            ]

        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                url = match.group(1) if match.lastindex else match.group(0)
                c.log(f'[CrewAdult.{self.name}] Found video URL with pattern: {url[:100]}...')
                return url

        return None
