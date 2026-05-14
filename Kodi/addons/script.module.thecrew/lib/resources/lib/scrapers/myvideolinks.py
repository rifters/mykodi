# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file myvideolinks.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urljoin

from ..modules import cleantitle, client, debrid, source_utils
from .base import BaseScraper
from ..modules.crewruntime import c


class source(BaseScraper):
    def __init__(self):
        super().__init__(name='myvideolinks', language=['en'])
        self.domains = ['myvideolinks.org', 'iwantmyshow.tk', 'go.myvideolinks.net',
                       'to.myvideolinks.net/', 'see.home.kg', 'to.myvideolinks.net']
        self.base_link = 'https://myvideolinks.org/'
        self.search_link = '/?s=%s'

    def sources(self, url, hostDict, hostprDict=None):
        sources = []
        try:
            if not url or debrid.status() is False:
                return sources

            hostDict = (hostprDict or []) + hostDict
            data = self._parse_data(url)

            title = data.get('tvshowtitle', data.get('title'))
            hdlr = 'S%02dE%02d' % (int(data['season']), int(data['episode'])) if data.get('tvshowtitle') else data.get('year')

            # Search by IMDB
            url_search = urljoin(self.base_link, self.search_link % data.get('imdb', ''))
            r = client.request(url_search)

            if not r or 'Just a moment' in r or '404 Not Found' in r:
                return sources

            # Handle redirect
            if 'CLcBGAs/s1600/1.jpg' in r:
                try:
                    redirect_url = client.parseDom(r, 'a', ret='href')[0]
                    self.base_link = redirect_url
                    url_search = urljoin(redirect_url, self.search_link % data.get('imdb', ''))
                    r = client.request(url_search)
                except:
                    pass

            posts = client.parseDom(r, 'article') or []

            # Fallback for TV shows
            if not posts and data.get('tvshowtitle'):
                try:
                    query = cleantitle.geturl(title).replace('-', '+') + '+' + hdlr
                    url_search = urljoin(self.base_link, self.search_link % query)
                    r = client.request(url_search, headers={'User-Agent': client.agent()})
                    posts += client.parseDom(r, 'article') or []
                except:
                    pass

            if not posts:
                return sources

            # Parse posts
            items = []
            for post in posts:
                try:
                    t = client.parseDom(post, 'img', ret='title')[0]
                    u = client.parseDom(post, 'a', ret='href')[0]
                    s_match = re.search(r'((?:\d+\.\d+|\d+,\d+|\d+)\s*(?:GiB|MiB|GB|MB))', post)
                    s = s_match.group(1) if s_match else '0'
                    items.append((t, u, s))
                except:
                    continue

            items = set(items)
            items = [i for i in items if cleantitle.get(title) in cleantitle.get(i[0])]

            # Extract links from posts
            for item in items:
                try:
                    name = item[0]
                    detail_page = client.request(item[1])

                    links = []
                    if data.get('tvshowtitle'):
                        if hdlr.lower() not in name.lower():
                            pattern = r'<p>\s*%s\s*</p>(.+?)</ul>' % hdlr.lower()
                            r_match = re.search(pattern, detail_page, flags=re.I | re.S)
                            if r_match:
                                links = client.parseDom(r_match.group(1), 'a', ret='href')
                        else:
                            links = client.parseDom(detail_page, 'a', ret='href')
                    else:
                        links = client.parseDom(detail_page, 'a', ret='href')

                    for link in links:
                        valid, host = source_utils.is_host_valid(link, hostDict)
                        if not valid:
                            continue

                        host = client.replaceHTMLCodes(host)
                        quality, info = source_utils.get_release_quality(name, link)

                        try:
                            size_str = re.findall(r'((?:\d+\.\d+|\d+\,\d+|\d+) (?:GB|GiB|MB|MiB))', item[2])[0]
                            dsize, isize = self._parse_size(size_str)
                            info.insert(0, isize)
                        except:
                            pass

                        info = ' | '.join(info)
                        sources.append({
                            'source': host,
                            'quality': quality,
                            'language': 'en',
                            'url': link,
                            'info': info,
                            'direct': False,
                            'debridonly': False
                        })

                except:
                    continue

            return sources
        except:
            return sources
