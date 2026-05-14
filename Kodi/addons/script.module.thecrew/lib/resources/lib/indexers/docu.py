# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file docu.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import os
import re
import sys
import time
import traceback

from urllib.parse import quote_plus, urlparse
import requests

import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin

import resolveurl

from bs4 import BeautifulSoup as bs

from ..modules.listitem import ListItemInfoTag

from ..modules import cache
from ..modules import client
from ..modules import control
from ..modules.crewruntime import c
from ..modules import http_client

_handle = syshandle = int(sys.argv[1])

# artPath = control.artPath()
# addonFanart = control.addonFanart()

artPath = c.get_art_path()
addonFanart = c.addon_fanart()



class Documentary:
    def __init__(self):
        self.list = []
        self.docu_link = 'https://topdocumentaryfilms.com/'
        self.docu_all = 'https://topdocumentaryfilms.com/all/'
        self.docu_cat_list = 'https://topdocumentaryfilms.com/list/'
        self.docu_top100 = 'https://topdocumentaryfilms.com/top-100/'
        self.session = requests.Session()
        self.addon = xbmcaddon.Addon
        self.session.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0"
        }
        self.YOUTUBE_PLUGIN = "plugin://plugin.video.youtube/"
        self.VIMEO_PLUGIN = "plugin://plugin.video.vimeo/"

    def __del__(self):
        if hasattr(self, 'session'):
            try:
                self.session.close()
            except Exception:
                pass
        self.DAILYMOTION_PLUGIN = "plugin://plugin.video.dailymotion_com/"

    def get_html(self, url):
        """
        Fetch HTML from URL with multiple fallback strategies to bypass bot detection.
        """
        # Strategy 1: Use HTTPClient with proper session
        try:
            session = http_client.HTTPClient.get_session('documentary')

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Referer": "https://topdocumentaryfilms.com/",
                "Cache-Control": "max-age=0"
            }

            response = session.get(url, headers=headers, timeout=15, allow_redirects=True)
            response.raise_for_status()
            return bs(response.text, "html.parser")
        except Exception as e:
            pass

        # Strategy 2: Use client.request with full headers for cloudflare bypass
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            }
            response = client.request(
                url,
                headers=headers,
                referer='https://topdocumentaryfilms.com/',
                timeout='15',
                redirect=True,
                verify=True
            )
            if response:
                return bs(response, "html.parser")
        except Exception as e2:
            pass

        # Strategy 3: Simple requests fallback (original method)
        try:
            response = requests.get(url, timeout=15, allow_redirects=True)
            response.raise_for_status()
            return bs(response.text, "html.parser")
        except Exception as e3:
            pass

        return None

    def get_json(self, url):
        page_response = self.session.get(url, timeout=15)
        json = page_response.json()
        return json

    def root(self):
        """
        This function creates the main documentary menu with three options:
        All Documentaries, Categories List, and Top 100.

        Returns:
            list: The list of documentary menu options.
        """
        try:
            cat_icon = c.addon_icon()

            # All Documentaries
            self.list.append({
                'name': 'All Documentaries',
                'url': self.docu_all,
                'image': cat_icon,
                'action': f'docuHeaven&docuCat={self.docu_all}'
            })

            # Categories List
            self.list.append({
                'name': 'Categories',
                'url': self.docu_cat_list,
                'image': cat_icon,
                'action': f'docuHeaven&docuCategories={self.docu_cat_list}'
            })

            # Top 100
            self.list.append({
                'name': 'Top 100 Documentaries',
                'url': self.docu_top100,
                'image': cat_icon,
                'action': f'docuHeaven&docuCat={self.docu_top100}'
            })
        except Exception as e:
            failure = traceback.format_exc()
            c.log(f'Exception in root: {failure}')

        self.addDirectory(self.list)
        return self.list

    def docu_categories(self, url):
        """
        Show documentary categories by scraping them from the categories list page.
        """
        try:
            soup = self.get_html(url)
            if soup is None:
                self.addDirectory(self.list)
                return self.list

            # Find the main content area
            main_content = soup.find('main') or soup.find('div', attrs={'id': 'content'}) or soup

            # Look for category links - they're usually in a list or specific container
            # Try multiple strategies to find categories
            category_links = []

            # Strategy 1: Look for links with /category/ in href
            all_links = main_content.find_all('a', href=True)

            seen_categories = set()
            for link in all_links:
                href = link.get('href', '')

                # Must contain /category/ and the domain
                if '/category/' not in href:
                    continue

                # Make URL absolute if needed
                if href.startswith('/'):
                    full_href = 'https://topdocumentaryfilms.com' + href
                else:
                    full_href = href

                # Extract category name from URL or link text
                title = link.get_text(strip=True)

                # Skip if no title or it's a generic navigation item
                if not title or len(title) < 2:
                    continue

                # Skip navigation/footer items
                skip_terms = ['home', 'about', 'contact', 'privacy', 'terms', 'subscribe',
                            'follow', 'login', 'register', 'search', 'menu', 'browse all']
                if any(skip in title.lower() for skip in skip_terms):
                    continue

                # Normalize the URL to avoid duplicates
                normalized_url = full_href.rstrip('/')

                # Skip if we've already seen this category URL
                if normalized_url in seen_categories:
                    continue

                seen_categories.add(normalized_url)

                # Clean up the title
                # Remove special characters that cause issues
                clean_title = title.replace('/', '').replace('\\', '')

                category_links.append((clean_title, normalized_url))

            # Sort categories alphabetically by title
            category_links.sort(key=lambda x: x[0].lower())

            # Add categories to list
            for title, href in category_links:
                docu_action = f'docuHeaven&docuCat={href}'
                self.list.append({
                    'name': title,
                    'url': href,
                    'image': c.addon_icon(),
                    'action': docu_action
                })

        except Exception as e:
            failure = traceback.format_exc()
            c.log(f'Exception in docu_categories: {failure}')

        self.addDirectory(self.list)
        return self.list

    def docu_list(self, url):
        try:
            soup = self.get_html(url)
            if soup is None:
                self.addDirectory(self.list)
                return self.list

            # For category pages, look for the main content area first
            main_content = soup.find('main') or soup.find('div', attrs={'id': 'content'}) or soup

            # Check if we're on a paginated page and show page number
            import re
            page_match = re.search(r'/page/(\d+)', url)
            if page_match:
                current_page = int(page_match.group(1))
                # Add page indicator at top of list
                self.list.append({
                    'name': f'[COLOR cyan]Page {current_page}[/COLOR]',
                    'url': url,
                    'image': c.addon_icon(),
                    'action': 'doNothing'  # Non-clickable info item
                })

            # Simplified approach: Find ALL links in main content, then filter
            all_links = main_content.find_all('a', href=True)

            # Filter to only documentary links
            exclude_patterns = ['#', 'javascript:', 'mailto:', '/list/', '/all/', '/top-100/',
                                '/about', '/contact', '/privacy', '/terms', '/feed', '/rss',
                                '/tag/', '/author/', '/search',
                                'facebook.com', 'twitter.com', 'youtube.com', 'instagram.com',
                                '/wp-', '/cdn-cgi/', '.css', '.js', '.jpg', '.png', '.gif']

            seen_urls = set()
            all_documentary_links = []

            for link in all_links:
                href = link.get('href', '')
                text = link.get_text(strip=True)

                # Must contain domain (or be relative path)
                if 'topdocumentaryfilms.com' not in href and not href.startswith('/'):
                    continue

                # Make URL absolute for comparison
                if href.startswith('/'):
                    full_href = 'https://topdocumentaryfilms.com' + href
                else:
                    full_href = href

                # Skip if URL matches exclude patterns
                if any(x in full_href.lower() for x in exclude_patterns):
                    continue

                # Skip /category/ in URL UNLESS we're already on a category page
                # (category pages contain links to documentaries, not more categories)
                is_on_category_page = '/category/' in url.lower()
                if '/category/' in full_href.lower() and not is_on_category_page:
                    continue

                # Skip /page/ pagination links (we handle those separately)
                if '/page/' in full_href.lower() and text.lower() not in ['next', '»', '›']:
                    continue

                # Skip if text matches exclude patterns
                if any(x in text.lower() for x in ['comment', 'reply', 'read more', 'continue reading', 'leave a comment']):
                    continue

                # Must not be the current page
                if full_href.rstrip('/') == url.rstrip('/'):
                    continue

                # Must have a path after domain (not just homepage)
                path_part = full_href.split('topdocumentaryfilms.com')[-1]
                if not path_part or path_part == '/' or len(path_part) < 3:
                    continue

                # Skip if already seen
                if full_href in seen_urls:
                    continue

                seen_urls.add(full_href)
                all_documentary_links.append(link)

            # Build a list of documentary items first (for sorting)
            documentary_items = []
            for link in all_documentary_links[:50]:  # Limit to first 50 documentaries
                try:
                    docu_url = link.get('href')
                    if not docu_url:
                        continue

                    # Make URL absolute if needed
                    if docu_url.startswith('/'):
                        docu_url = 'https://topdocumentaryfilms.com' + docu_url

                    docu_title = link.get('title') or link.text.strip()
                    if not docu_title or len(docu_title) < 2:
                        continue

                    # Skip navigation and category links by URL
                    skip_keywords = ['browse', 'list', 'top-100', 'verify', 'patron', '/category/', '/tag/', '/page/']
                    if any(keyword in docu_url.lower() for keyword in skip_keywords):
                        continue

                    # Skip non-documentary items by title
                    skip_titles = ['browse', 'list', 'top 100', 'verify', 'patron', 'about', 'contact',
                                    'search', 'read more', 'continue reading', 'leave a comment',
                                    'view all posts', 'posted in']
                    # Skip if title contains "comment" or "comments" as a standalone word
                    title_lower = docu_title.lower()
                    if (title_lower in skip_titles or
                        ' comment' in title_lower or
                        'comment' == title_lower or
                        title_lower.endswith(' comments') or
                        title_lower.startswith('comments')):
                        continue

                    # Skip gambling spam articles (these don't have real videos)
                    gambling_spam = ['casino', 'gambling', 'gamstop', 'payid', 'poker', 'bet',
                                    'slots', 'roulette', 'blackjack', 'rng-in', 'house-edge',
                                    'sportsbook', 'offshore', 'betting']
                    if any(spam in docu_url.lower() or spam in docu_title.lower() for spam in gambling_spam):
                        continue

                    # Skip if it's a category name (matches known categories)
                    category_names = ['9/11', 'art and artists', 'biography', 'conspiracy', 'crime',
                                    'cryptocurrency', 'drugs', 'economics', 'environment', 'gambling',
                                    'health', 'history', 'media', 'military and war', 'mystery',
                                    'nature', 'performing arts', 'philosophy', 'politics',
                                    'psychology', 'religion', 'science', 'sexuality', 'society',
                                    'sports', 'technology']
                    if docu_title.lower() in category_names:
                        continue

                    # Find image from the link or its parent
                    docu_img = link.find('img')
                    if not docu_img and link.parent:
                        docu_img = link.parent.find('img')
                    docu_icon = docu_img.get('src') if docu_img else c.addon_icon()

                    # Make image URL absolute if needed
                    if docu_icon and docu_icon.startswith('/'):
                        docu_icon = 'https://topdocumentaryfilms.com' + docu_icon

                    if docu_url and docu_title:
                        docu_action = f'docuHeaven&docuPlay={docu_url}'
                        documentary_items.append({'name': docu_title, 'url': docu_url, 'image': docu_icon, 'action': docu_action})
                except Exception as e:
                    continue

            # Sort documentaries alphabetically by title
            documentary_items.sort(key=lambda x: x['name'].lower())

            # Add sorted items to list
            self.list.extend(documentary_items)

            # Try to find pagination/next page
            try:
                # Look for pagination - could be in nav.navigation or div.pagination
                pagination = soup.find('nav', attrs={'class': 'navigation'})
                if not pagination:
                    pagination = soup.find('div', attrs={'class': 'pagination'})
                if not pagination:
                    # Try to find any link with 'page/2' or 'page/3' etc
                    next_links = soup.find_all('a', href=True)
                    for link in next_links:
                        href = link.get('href', '')
                        link_text = link.get_text(strip=True).lower()
                        # Look for "next" or page numbers
                        if '/page/' in href and ('next' in link_text or '»' in link_text or '>' in link_text or link_text.isdigit()):
                            pagination = link
                            break

                if pagination:
                    # If we found a specific link, use it
                    if pagination.name == 'a':
                        next_url = pagination.get('href')
                    else:
                        # Find the next/last link in the pagination container
                        links = pagination.find_all("a", href=True)
                        next_url = None
                        # Look for "next" link or highest page number
                        for link in links:
                            href = link.get('href', '')
                            link_text = link.get_text(strip=True).lower()
                            if '/page/' in href and ('next' in link_text or '»' in link_text):
                                next_url = href
                                break
                        # If no "next" found, use last link
                        if not next_url and links:
                            next_url = links[-1].get('href')

                    if next_url:
                        # Make URL absolute if needed
                        if next_url.startswith('/'):
                            next_url = 'https://topdocumentaryfilms.com' + next_url

                        # Extract current and next page numbers from URLs
                        current_page = 1
                        next_page = 2
                        import re
                        page_match = re.search(r'/page/(\d+)', url)
                        if page_match:
                            current_page = int(page_match.group(1))
                        next_match = re.search(r'/page/(\d+)', next_url)
                        if next_match:
                            next_page = int(next_match.group(1))

                        # Create page label
                        page_label = f"Next Page ({next_page})" if next_page > current_page else c.lang(32053)

                        docu_action = f'docuHeaven&docuCat={next_url}'
                        self.list.append({
                            'name': page_label,
                            'url': next_url,
                            'image': c.addon_next(),
                            'action': docu_action
                        })
            except Exception as e:
                pass

        except Exception as e:
            failure = traceback.format_exc()
            c.log(f'Exception in docu_list: {failure}')

        self.addDirectory(self.list)
        return self.list

    def docu_play(self, url):
        """
        Retrieves the documentary video from the given URL and plays it.

        Args:
            url (str): The URL of the documentary video.

        Raises:
            Exception: If there is an error during the process.

        Returns:
            None
        """
        try:
            # Use client.request with headers (same approach that works in get_html)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            }
            docu_page = client.request(
                url,
                headers=headers,
                referer='https://topdocumentaryfilms.com/',
                timeout='15',
                redirect=True,
                verify=True
            )

            if not docu_page:
                c.infoDialog("Failed to fetch page", sound=False, icon='ERROR')
                return

            # Use client.selectHTML for modern CSS selector-based parsing
            docu_item = None

            # Try embedUrl first (itemprop)
            if not docu_item:
                try:
                    results = client.selectHTML(docu_page, 'meta[itemprop="embedUrl"]', ret='content')
                    if results:
                        docu_item = results[0]
                except Exception as e:
                    pass

            # Try contentUrl (itemprop)
            if not docu_item:
                try:
                    results = client.selectHTML(docu_page, 'meta[itemprop="contentUrl"]', ret='content')
                    if results:
                        docu_item = results[0]
                except Exception as e:
                    pass

            # Try iframe src
            if not docu_item:
                try:
                    results = client.selectHTML(docu_page, 'iframe', ret='src')
                    if results:
                        docu_item = results[0]
                except Exception as e:
                    pass

            # Try og:video meta tag
            if not docu_item:
                try:
                    results = client.selectHTML(docu_page, 'meta[property="og:video"]', ret='content')
                    if results:
                        docu_item = results[0]
                except Exception as e:
                    pass

            # Try og:video:url meta tag
            if not docu_item:
                try:
                    results = client.selectHTML(docu_page, 'meta[property="og:video:url"]', ret='content')
                    if results:
                        docu_item = results[0]
                except Exception as e:
                    pass

            # If still not found, show error
            if not docu_item:
                c.infoDialog("This page doesn't have a playable video", sound=False, icon='ERROR')
                return

            if 'http:' not in docu_item and  'https:' not in docu_item:
                docu_item = f'https:{docu_item}'
            url = docu_item

            # Try to extract title
            try:
                docu_title = client.parseDom(docu_page, 'meta', attrs={'property':'og:title'}, ret='content')[0].replace("&amp;","&").replace('&#39;',"'").replace('&quot;','"').replace('&#39;',"'").replace('&#8211;',' - ').replace('&#8217;',"'").replace('&#8216;',"'").replace('&#038;','&').replace('&acirc;','')
            except:
                docu_title = "Documentary"

            if 'youtube' in url:
                if 'videoseries' not in url:
                    # Extract video ID from various YouTube URL formats
                    # Handle: /embed/VIDEO_ID?params, /v/VIDEO_ID, /watch?v=VIDEO_ID
                    if '/embed/' in url or '/v/' in url:
                        # Format: https://www.youtube.com/embed/VIDEO_ID?params
                        video_id = url.split("/")[-1].split("?")[0]
                    elif 'v=' in url:
                        # Format: https://www.youtube.com/watch?v=VIDEO_ID&params
                        video_id = url.split('v=')[1].split('&')[0]
                    else:
                        # Fallback: assume last path segment
                        video_id = url.split("/")[-1].split("?")[0]

                    url = f'plugin://plugin.video.youtube/play/?video_id={video_id}'
                else: pass
            elif 'dailymotion' in url:
                video_id = client.parseDom(docu_page, 'div', attrs={'class':'youtube-player'}, ret='data-id')[0]
                url = self.getDailyMotionStream(video_id)
            else:
                c.log(f'Play Documentary: Unknown Host: {url}', trace=1)
                c.infoDialog(message=f'Unknown Host - Report To Developer: {url}', heading='Unknown Host', icon='ERROR', time=3000, sound=False)

            listitem = xbmcgui.ListItem(label=docu_title, offscreen=True)
            listitem.setProperty('IsPlayable', 'true')
            listitem.setInfo('video', {'Title': docu_title, 'Genre': 'docu', 'Plot': 'Plot created by Classy ;-)'})

            # YouTube plugin URLs don't need resolveurl, use directly
            if url and url.startswith('plugin://'):
                resolved = url
            else:
                hmf = resolveurl.HostedMediaFile(url)
                if hmf:
                    resolved = hmf.resolve()
                else:
                    resolved = url  # Fallback to original URL

            # Use setResolvedUrl for all URLs (including plugin URLs)
            # This is the standard method and matches how trailers work
            item = xbmcgui.ListItem(path=resolved)
            item.setProperty('IsPlayable', 'true')
            xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, item)

        except Exception as e:
            failure = traceback.format_exc()
            c.log(f'Exception in docu_play: {failure}')




    def getDailyMotionStream(self, video_id):
        """
        Retrieves a playable URL for a given video id from DailyMotion.

        Parts of this Code was originally written by gujal, as part of the DailyMotion Addon in the official Kodi Repo.
        Modified to fit the needs here.

        Args:
            video_id (str): The video id to retrieve the URL for.

        Returns:
            str: A playable URL for the given video id.

        Raises:
            Exception: If there is an error during the process.

        Notes:
            The function will return the first playable URL found in the metadata response.
            If no playable URL is found, the function will return None.
        """
        headers = {'User-Agent':'Android'}
        cookie = {'Cookie':"lang=en_US; ff=off"}
        r = requests.get(f"http://www.dailymotion.com/player/metadata/video/{video_id}", headers=headers, cookies=cookie, timeout=10)
        content = r.json()
        if content.get('error') is not None:
            error = (content['error']['title'])
            xbmc.executebuiltin(f'XBMC.Notification(Info:,{error} ,5000)')
            return
        else:
            cc = content['qualities']
            cc = cc.items()
            cc = sorted(cc,key=self.sort_key,reverse=True)
            m_url = ''
            other_playable_url = []
            for source,json_source in cc:
                source = source.split("@")[0]
                for item in json_source:
                    if m_url := item.get('url', None):
                        if source == "auto" :
                            continue
                        elif  int(source) <= 2 :
                            if 'video' in item.get('type', None):
                                return m_url
                        elif '.mnft' in m_url:
                            continue
                        other_playable_url.append(m_url)
            if other_playable_url: # probably not needed, only for last resort
                for m_url in other_playable_url:
                    if '.m3u8?auth' in m_url:
                        rr = requests.get(m_url, cookies=r.cookies.get_dict() ,headers=headers, timeout=10)
                        if rr.headers.get('set-cookie'):
                            return (
                                re.findall(r'(http.+)', rr.text)[0].split('#cell')[
                                    0
                                ]
                                + '|Cookie='
                                + rr.headers['set-cookie']
                            )
                        else:
                            return re.findall(r'(http.+)', rr.text)[0].split('#cell')[0]

    def sort_key(self, item):
        """
        Sort key function for DailyMotion quality strings.
        Converts quality strings like '720' to integers for proper sorting.
        Returns 0 for 'auto' or non-numeric values to sort them to the bottom.
        """
        quality_str = item[0].split('@')[0]
        if quality_str == 'auto':
            return 0
        try:
            return int(quality_str)
        except ValueError:
            return 0

    def addDirectoryItem(self, name, query, thumb, icon, context=None, queue=False, is_action=True, is_folder=True) -> None:
        try:
            name = c.lang(name)
        except Exception:
            pass
        sysaddon = sys.argv[0]
        syshandle = int(sys.argv[1])
        queueMenu = c.lang(32065)

        url = f'{sysaddon}?action={query}' if is_action is True else query
        thumb = os.path.join(artPath, thumb) if artPath is not None else icon
        cm = []
        if queue:
            cm.append((queueMenu, f'RunPlugin({sysaddon}?action=playlist_QueueItem)'))
        if context:
            cm.append((c.lang(context[0]), f'RunPlugin({sysaddon}?action={context[1]})'))
        try:
            item = control.item(label=name, offscreen=True)
        except Exception:
            item = control.item(label=name)



        item.setProperty('IsPlayable', 'true')
        infolabels={'title': name, 'plot': "Documentary"}
        info_tag = ListItemInfoTag(item, 'video')
        info_tag.set_info(infolabels)

        item.addContextMenuItems(cm)
        item.setArt({'icon': thumb, 'thumb': thumb, 'fanart': addonFanart})
        control.addItem(handle=syshandle, url=url, listitem=item, isFolder=is_folder)

    def endDirectory(self):
        syshandle = int(sys.argv[1])
        control.content(syshandle, 'addons')
        control.directory(syshandle, cacheToDisc=True)

    def _add_folder_item(self, items, title, url, icon_url, fanart_url,
                            sort_title="", isfolder=True, isplayable=False,
                            date=None, info=None, context_menu_items=None,
                            offscreen=True):

        if fanart_url is None:
            fanart_url = os.path.join(self.addon.media, "fanart_blur.jpg")

        if icon_url is None:
            icon_url = os.path.join(self.addon.media, "icon_trans.png")

        try:
            listitem = control.item(label=title, offscreen=offscreen)
        except Exception:
            listitem = control.item(label=title)
        list_item = ListItemInfoTag(listitem, 'video')
        listitem.setArt({"thumb": icon_url, "fanart": fanart_url})
        listitem.setInfo("video", {"title": title, "sorttitle": sort_title})

        if isplayable:
            listitem.setProperty("IsPlayable", "true")
        else:
            listitem.setProperty("IsPlayable", "false")

        if date is not None:
            listitem.setInfo("video", {"date": date})

        if info is not None:
            listitem.setInfo("video", {"plot": info})

        if context_menu_items is not None:
            listitem.addContextMenuItems(context_menu_items)

        items.append((url, listitem, isfolder))








    def addDirectory(self, items, queue=False, isFolder=True):
        if items is None or len(items) == 0:
            control.idle()
            c.infoDialog( 'No Documentaries Found', heading=f'{c.lang(32002)}', sound=True, )
            return
        sysaddon = sys.argv[0]
        syshandle = int(sys.argv[1])
        addonThumb = c.addon_thumb()
        artPath = c.get_art_path()
        queueMenu = c.lang(32065)
        playRandom = c.lang(32535)
        addToLibrary = c.lang(32551)
        for i in items:
            try:
                name = i['name']
                if i['image'].startswith('http'):
                    thumb = i['image']
                elif artPath:
                    thumb = os.path.join(artPath, i['image'])
                else:
                    thumb = addonThumb
                try:
                    item = control.item(label=name, offscreen=True)
                except Exception:
                    item = control.item(label=name)

                url = f'{sysaddon}?action={i["action"]}'
                if 'url' in i:
                    url += f'&url={quote_plus(str(i["url"]))}'

                # Check if this is a playable item (docuPlay) or a folder (docuCat)
                is_playable = 'docuPlay' in i.get('action', '')
                item_is_folder = isFolder and not is_playable

                if item_is_folder:
                    item.setProperty('IsPlayable', 'false')
                else:
                    item.setProperty('IsPlayable', 'true')

                item.setArt({'icon': thumb, 'thumb': thumb, 'fanart': c.addon_fanart()})
                control.addItem(handle=syshandle, url=url, listitem=item, isFolder=item_is_folder)
            except Exception as e:
                failure = traceback.format_exc()
                c.log(f'Exception in addDirectory: {failure}')
                pass
        control.content(syshandle, 'addons')
        control.directory(syshandle, cacheToDisc=True)