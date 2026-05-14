# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file 300mbfilms.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
from urllib.parse import urljoin, quote_plus

from ..modules import cleantitle, client, debrid, source_utils
from .base import BaseScraper


class source(BaseScraper):
    def __init__(self):
        super().__init__(name='300mbfilms', language=['en'])
        self.domains = ['300mbfilms.co', '300mbfilms.ws', '300mbfilms.cx']
        self.base_link = 'https://www.300mbfilms.cx'
        self.search_link = '/?s=%s'

    def sources(self, url, hostDict, hostprDict=None):
        sources = []
        try:
            if not url or debrid.status() is False:
                return sources

            hostDict = (hostprDict or []) + hostDict
            data = self._parse_data(url)

            title = data.get('tvshowtitle', data.get('title'))
            hdlr = 'S%02dE%02d' % (int(data['season']), int(data['episode'])) if data.get('tvshowtitle') else data['year']

            # Build search query
            if data.get('tvshowtitle'):
                query = '%s S%02dE%02d' % (data['tvshowtitle'], int(data['season']), int(data['episode']))
            else:
                query = '%s %s' % (data['title'], data['year'])

            query = re.sub(r'[\\\/\-:\;\*\?"\'\<\>\|]', ' ', query)
            query_url = urljoin(self.base_link, self.search_link % quote_plus(query))

            # Search
            r = self._request(query_url)
            if not r:
                return sources

            # Parse posts
            posts = re.findall(r'<h2 class="title">(.+?)</h2>', r, re.IGNORECASE)

            urls = []
            for item in posts:
                try:
                    link, name = re.findall(r'href="(.+?)" title="(.+?)"', item, re.IGNORECASE)[0]

                    if not cleantitle.get(title) in cleantitle.get(name):
                        continue

                    name = client.replaceHTMLCodes(name)
                    _name = name.lower().replace('permalink to', '')

                    quality, info = source_utils.get_release_quality(name, link)

                    # Extract size
                    try:
                        size_str = re.findall(r'((?:\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|MB|MiB))', name)[-1]
                        dsize, isize = self._parse_size(size_str)
                        info.insert(0, isize)
                    except:
                        dsize = 0.0

                    # Get links from detail page
                    links = self._get_links(link)
                    urls.extend([(l, quality, ' | '.join(info), dsize, _name) for l in links])

                except:
                    continue

            # Process links
            for item in urls:
                try:
                    url = item[0]

                    if 'earn-money' in url:
                        continue

                    if any(x in url for x in ['.rar', '.zip', '.iso']):
                        continue

                    valid, host = source_utils.is_host_valid(url, hostDict)
                    if not valid:
                        continue

                    sources.append({
                        'source': host,
                        'quality': item[1],
                        'language': 'en',
                        'url': url,
                        'info': item[2],
                        'direct': False,
                        'debridonly': True,
                        'size': item[3],
                        'name': item[4]
                    })

                except:
                    continue

            return sources
        except:
            return sources

    def _get_links(self, url):
        """Extract links from detail page"""
        urls = []
        try:
            r = self._request(url)
            if not r:
                return urls

            # Find earn-money link
            r_entries = client.parseDom(r, 'div', attrs={'class': 'entry'})
            r_links = client.parseDom(r_entries, 'a', ret='href')

            earn_links = [i for i in r_links if 'money' in i]
            if not earn_links:
                return urls

            r1_url = earn_links[0]
            r1 = self._request(r1_url)
            if not r1:
                return urls

            # Check for password protection
            r1_posts = client.parseDom(r1, 'div', attrs={'id': re.compile(r'post-\d+')})
            if r1_posts and 'enter the password' in r1_posts[0]:
                # Handle password-protected content
                form = client.parseDom(r1_posts[0], 'form', ret='action')
                if form:
                    plink = form[0]
                    post = {'post_password': '300mbfilms', 'Submit': 'Submit'}
                    cookie = client.request(plink, post=post, output='cookie')
                    link_page = client.request(r1_url, cookie=cookie)
                else:
                    link_page = r1
            else:
                link_page = r1

            # Extract Single Links section
            single_section = re.findall(r'<strong>Single(.+?)</tr', link_page, re.DOTALL)
            if not single_section:
                return urls

            section_links = client.parseDom(single_section[0], 'a', ret='href')

            for link in section_links:
                if 'earn-money-onlines.info' in link:
                    # Handle protector
                    trim = link.replace('protector1.php', 'protector.php')
                    prot_page = self._request(trim)
                    if prot_page:
                        filter_links = re.findall(r'<center> <a href="(.+?)"', prot_page)
                        for fl in filter_links:
                            if not any(x in fl for x in ['uptobox', 'clicknupload']):
                                urls.append(fl)
                else:
                    urls.append(link)

            return urls
        except:
            return urls
