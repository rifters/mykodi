# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file client.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
* The Crew Add-on - rebuilt client.py (refactor)
*
* This file replaces the previous client implementation with a
* more robust, simpler and safer version while preserving the
* original public API and behavior as much as possible.
********************************************************cm*
'''

import re
import gzip
import time
import random
import base64
import ssl
import platform
import json
import os
from io import BytesIO
from typing import Any, cast

from . import cache
from . import dom_parser
from . import bs4_parser
from . import cfscrape
from . import control
from . import hunter
from .crewruntime import c
from . import crewruntime as crewruntime

try:
    from http import cookiejar as cookielib
    from html import unescape
    import urllib.request as urllib2
    from urllib.request import HTTPRedirectHandler
    from urllib.request import Request as URLRequest
    from urllib.parse import urlparse, urljoin, urlencode, quote_plus, unquote
    from urllib.error import HTTPError, URLError
    from urllib.response import addinfourl
except Exception:
    # In case of import issues we still want the addon to fail gracefully
    c.log('[client.py] Important urllib imports failed', 1)
    raise

STRING_TYPES = (str, bytes)

def _ensure_text(value) -> str:
    """
    Normalize value to native text (str). Always returns a str.
    Prefer c.ensure_text if available, then crewruntime helpers,
    otherwise decode bytes safely or fall back to str().
    """
    try:
        if value is None:
            return ''
        # bytes/bytearray -> decode reliably
        if isinstance(value, (bytes, bytearray)):
            try:
                return value.decode('utf-8')
            except Exception:
                try:
                    return value.decode('latin-1')
                except Exception:
                    return value.decode('utf-8', errors='replace')
        # prefer c.ensure_text if available
        try:
            if hasattr(c, 'ensure_text'):
                res = c.to_str(value)
                return res if isinstance(res, str) else str(res)
        except Exception:
            # ignore helper errors and continue
            pass
        # fall back to crewruntime helpers if present
        try:
            func = getattr(crewruntime, 'ensure_text', None)
            if callable(func):
                res = func(value)
                return res if isinstance(res, str) else str(res)
            func = getattr(crewruntime, 'to_unicode', None)
            if callable(func):
                res = func(value)
                return res if isinstance(res, str) else str(res)
        except Exception:
            pass
        # if it's already str, return it; else convert
        if isinstance(value, str):
            return value
        return str(value)
    except Exception:
        try:
            return '' if value is None else str(value)
        except Exception:
            return ''

def _decode_gzip_if_needed(data, headers):
    try:
        encoding = None
        if hasattr(headers, 'get'):
            encoding = headers.get('Content-Encoding')
        elif isinstance(headers, dict):
            encoding = headers.get('Content-Encoding')
        if encoding == 'gzip' and data:
            return gzip.GzipFile(fileobj=BytesIO(data)).read()
    except Exception:
        pass
    return data

def _prepare_post(post):
    try:
        if isinstance(post, dict):
            return bytes(urlencode(post), encoding='utf-8')
        if isinstance(post, str):
            return post.encode('utf-8')
        return post
    except Exception:
        return post

def _build_opener_and_cj(username, password, proxy, output, verify):
    """
    Build handlers list and optional cookie jar. Return (opener, cj)
    """
    handlers = []
    cj = None
    try:
        # Authentication
        if username is not None and password is not None and not proxy:
            passmgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
            passmgr.add_password(None, '', username, password)  # keep realm/uri loose
            handlers.append(urllib2.HTTPBasicAuthHandler(passmgr))

        # Proxy
        if proxy:
            handlers.append(urllib2.ProxyHandler({'http': proxy, 'https': proxy}))

        # Cookie support when needed
        if output in ('cookie', 'extended') or output != '' and output is not None:
            # preserve original logic: only create cookiejar when needed or close != True outside
            cj = cookielib.LWPCookieJar()
            handlers.append(urllib2.HTTPCookieProcessor(cj))

        # SSL handling
        # Xbox One (UWP) cannot use ssl._create_unverified_context() — restricted in UWP sandbox.
        # Detect Xbox and force the create_default_context() + CERT_NONE path instead.
        try:
            is_xbox = platform.uname()[1] == 'XboxOne'
        except Exception:
            is_xbox = False

        try:
            if not verify and not is_xbox:
                ctx = ssl._create_unverified_context()
            else:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                try:
                    import _ssl as _ssl_mod
                    ctx.verify_mode = _ssl_mod.CERT_NONE
                except Exception:
                    ctx.verify_mode = ssl.CERT_NONE
            handlers.append(urllib2.HTTPSHandler(context=ctx))
        except Exception:
            pass

        # Note: redirect handling is added by caller if needed
    except Exception:
        pass

    opener = urllib2.build_opener(*handlers) if handlers else urllib2.build_opener()
    return opener, cj

def _normalize_headers(headers, url, referer, mobile, XHR, cookie, compression, limit):
    try:
        if headers is None or not isinstance(headers, dict):
            headers = dict(headers) if headers else {}
        # User-Agent selection
        if not headers.get('User-Agent'):
            headers['User-Agent'] = cache.get(randommobileagent, 12) if mobile else cache.get(randomagent, 12)
        # Referer
        if 'Referer' not in headers:
            if referer:
                headers['Referer'] = referer
            else:
                try:
                    parsed_url = urlparse(cast(Any, _ensure_text(url)))
                    headers['Referer'] = '%s://%s/' % (parsed_url.scheme, parsed_url.netloc)
                except Exception:
                    headers['Referer'] = referer or ''
        headers.setdefault('Accept-Language', 'en-US')
        if XHR and 'X-Requested-With' not in headers:
            headers['X-Requested-With'] = 'XMLHttpRequest'
        if cookie and 'Cookie' not in headers:
            headers['Cookie'] = cookie
        if compression and 'Accept-Encoding' not in headers and limit is None:
            headers['Accept-Encoding'] = 'gzip'
        return headers
    except Exception:
        return headers or {}

def _read_response_content(response, limit=None, as_bytes=False):
    try:
        if limit == '0':
            raw = response.read(224 * 1024)
        elif limit:
            raw = response.read(int(limit) * 1024)
        else:
            raw = response.read(5242880)
        headers_obj = response.info() if hasattr(response, 'info') else {}
        raw = _decode_gzip_if_needed(raw, headers_obj)
        if not as_bytes:
            raw = _ensure_text(raw)
        return raw
    except Exception:
        return None

def _try_cfscrape_retry(url, post, headers, timeout, as_bytes):
    """
    Attempt to retry request using cfscrape cookie string on 503 responses.
    Returns raw content or None.
    """
    try:
        parsed_u = urlparse(cast(Any, _ensure_text(url)))
        netloc = '{0}://{1}'.format(parsed_u.scheme, parsed_u.netloc)
    except Exception:
        netloc = _ensure_text(url)
    try:
        ua = headers.get('User-Agent') if headers else ''
        cf_res = None
        try:
            cf_res = cache.get(cfscrape.get_cookie_string, 1, netloc, ua)
            if cf_res:
                cf = cf_res[0] if isinstance(cf_res, (list, tuple)) else cf_res
            else:
                cf = None
        except Exception:
            try:
                cf_res = cfscrape.get_cookie_string(netloc, ua)
                cf = cf_res[0] if isinstance(cf_res, (list, tuple)) else cf_res
            except Exception:
                cf = None
        if not cf:
            return None
        headers = headers or {}
        headers['Cookie'] = cf
        req = URLRequest(url, data=post, headers=headers)
        response = urllib2.urlopen(req, timeout=int(timeout))
        try:
            raw = response.read()
            raw = _decode_gzip_if_needed(raw, response.info() if hasattr(response, 'info') else {})
            if not as_bytes:
                raw = _ensure_text(raw)
            return raw
        finally:
            try:
                response.close()
            except Exception:
                pass
    except Exception:
        return None

def request(url, close=True, redirect=True, error=False, verify=True, proxy=None, post=None, headers=None, mobile=False, XHR=False,
            limit=None, referer=None, cookie=None, compression=False, output='', timeout='30', username=None, password=None, as_bytes=False):
    """
    Refactored robust HTTP request wrapper. Preserves original API and return shapes.
    """
    try:
        url = _ensure_text(url)
    except Exception:
        pass

    post = _prepare_post(post)

    # Build opener and cookiejar
    opener, cj = _build_opener_and_cj(username, password, proxy, output, verify)

    # If redirect is disabled append handler
    if not redirect:
        class NoRedirectHandler(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
            def http_error_302(self, req, fp, code, msg, headers):
                response = addinfourl(fp, headers, req.get_full_url())
                try:
                    response.code = code
                except Exception:
                    pass
                return response
            http_error_301 = http_error_303 = http_error_302
        opener = urllib2.build_opener(*[h for h in opener.handlers] + [NoRedirectHandler()])

    headers = _normalize_headers(headers, url, referer, mobile, XHR, cookie, compression, limit)
    ua = headers.get('User-Agent', '')

    req = URLRequest(url, data=post, headers=headers)
    # ensure headers are attached as before
    try:
        response = opener.open(req, timeout=int(timeout))
        try:
            status_code = getattr(response, 'code', None) or getattr(response, 'status', None)

            if output == 'headers':
                content_headers = response.info()
                if close:
                    try: response.close()
                    except Exception: pass
                return content_headers

            if output == 'file_size':
                try:
                    size = int(response.info().get('Content-Length') or 0)
                except Exception:
                    size = 0
                try: response.close()
                except Exception: pass
                return size

            if output == 'response':
                raw = _read_response_content(response, limit=limit, as_bytes=True)
                try: response.close()
                except Exception: pass
                return (str(status_code), raw)

            if output == 'json':
                raw = _read_response_content(response, limit=limit, as_bytes=True)
                try:
                    text = raw.decode('utf-8', errors='ignore') if isinstance(raw, (bytes, bytearray)) else _ensure_text(raw)
                    return json.loads(text)
                finally:
                    try: response.close()
                    except Exception: pass

            if output == 'cookie':
                try:
                    cookie_str = '; '.join(['{0}={1}'.format(i.name, i.value) for i in (cj or [])]) or (headers.get('Cookie') or '')
                    return cookie_str
                finally:
                    try: response.close()
                    except Exception: pass

            if output == 'extended':
                try:
                    cookie_str = '; '.join(['{0}={1}'.format(i.name, i.value) for i in (cj or [])]) or (headers.get('Cookie') or '')
                    content_headers = response.info()
                    data = _read_response_content(response, limit=limit, as_bytes=as_bytes)
                    return data, headers, content_headers, cookie_str
                finally:
                    try: response.close()
                    except Exception: pass

            # Default: return content
            raw = _read_response_content(response, limit=limit, as_bytes=as_bytes)
            if close:
                try: response.close()
                except Exception: pass
            return raw

        except HTTPError as he_inner:
            # Let outer HTTPError handler take care (fallback)
            try: response.close()
            except Exception: pass
            raise he_inner

    except HTTPError as he:
        # Safely obtain HTTP status code
        code = getattr(he, 'code', None)
        if code is None:
            if error:
                return he
            return

        # Cloudflare 503 handling: attempt retry using cfscrape cookies
        if code == 503:
            try_res = _try_cfscrape_retry(url, post, headers, timeout, as_bytes)
            if try_res is not None:
                return try_res

        if error:
            return he
        return

    except URLError:
        return
    except Exception:
        return

def _basic_request(url, headers=None, post=None, timeout='30', limit=None):
    try:
        if headers is None or not isinstance(headers, dict):
            headers = dict(headers) if headers else {}
        req = URLRequest(url, data=post, headers=headers)
        _add_request_header(req, headers)
        response = urllib2.urlopen(req, timeout=int(timeout))
        data = _get_result(response, limit)
        return data
    except Exception:
        return

def _add_request_header(_request, headers):
    try:
        if not headers:
            headers = {}
        try:
            scheme = _request.get_type()
        except Exception:
            scheme = 'http'
        referer = headers.get('Referer') if headers.get('Referer') else '%s://%s/' % (scheme, _request.get_host())
        _request.add_unredirected_header('Host', _request.get_host())
        _request.add_unredirected_header('Referer', referer)
        for key, val in headers.items():
            _request.add_header(key, val)
    except Exception:
        return

def external(url):
    from .crewruntime import c
    try:
        c.log(f'[client.external] Attempting to resolve: {url}')
        crewstreamer = control.cdnImport('https://raw.githubusercontent.com/posadka/xmls2/main/crewstreamer.xml', 'crewstreamer')
        c.log(f'[client.external] cdnImport successful, type: {type(crewstreamer)}')
        crewstreamer = crewstreamer.streamer()
        c.log(f'[client.external] streamer() called, type: {type(crewstreamer)}')
        result = crewstreamer.resolve(url)
        c.log(f'[client.external] resolve() returned: {result}')
        return result
    except Exception as e:
        c.log(f'[client.external] ERROR: {e}')
        import traceback
        c.log(f'[client.external] Traceback: {traceback.format_exc()}')
        return

def schedule(url):
    try:
        crewschedule = control.cdnImport('https://raw.githubusercontent.com/posadka/xmls2/main/crewschedule.xml', 'crewschedule')
        crewschedule = crewschedule.streamer()
        return crewschedule.resolve(url)
    except Exception:
        return

def replays(url):
    try:
        crewreplays = control.cdnImport('https://raw.githubusercontent.com/posadka/xmls2/main/crewreplays.xml', 'crewreplays')
        crewreplays = crewreplays.streamer()
        return crewreplays.resolve(url)
    except Exception:
        return

def _get_result(response, limit=None):
    try:
        if limit == '0':
            result = response.read(224 * 1024)
        elif limit:
            result = response.read(int(limit) * 1024)
        else:
            result = response.read(5242880)
        # Try to detect encoding header robustly
        try:
            info = response.info()
            encoding = info.get('Content-Encoding') if info is not None else None
        except Exception:
            encoding = response.getheader('Content-Encoding') if hasattr(response, 'getheader') else None
        if encoding == 'gzip':
            result = gzip.GzipFile(fileobj=BytesIO(result)).read()
        return result
    except Exception:
        return None

def parseDom(html, name='', attrs=None, ret=False):
    """
    Robust wrapper around dom_parser.parse_dom that safely handles different return shapes.

    Args:
        html: HTML content to parse
        name: Tag name to search for
        attrs: Dictionary of attributes to filter by (values are regex patterns)
        ret: Attribute name to extract (str) or False to return content

    Returns:
        List of extracted values (either content or attribute values)
    """
    if attrs:
        # convert attrs pattern values to regex like before
        attrs = {k: re.compile(v + ('$' if v else '')) for k, v in attrs.items()}
    # FIX: Don't pass ret to req parameter - they have different purposes
    results = dom_parser.parse_dom(html, name, attrs, req=False)
    out = []
    if ret:
        for item in (results or []):
            try:
                # If item has attrs dict
                if hasattr(item, 'attrs'):
                    attrs_obj = getattr(item, 'attrs') or {}
                    key = ret.lower() if isinstance(ret, STRING_TYPES) else ret
                    out.append(attrs_obj.get(key, ''))
                elif isinstance(item, dict):
                    out.append(item.get(ret, '') if isinstance(ret, STRING_TYPES) else item.get(ret, ''))
                elif isinstance(item, (bytes, str)):
                    out.append(_ensure_text(item))
                elif hasattr(item, ret):
                    val = getattr(item, ret, '')
                    out.append(_ensure_text(val))
                else:
                    out.append(_ensure_text(item))
            except Exception:
                out.append('')
    else:
        for item in (results or []):
            try:
                content = getattr(item, 'content', None)
                if content is not None:
                    out.append(content)
                elif isinstance(item, dict):
                    out.append(item.get('content', ''))
                else:
                    out.append(_ensure_text(item))
            except Exception:
                out.append('')
    return out

def parseHTML(html, name='', attrs=None, ret=False):
    """
    BeautifulSoup-based HTML parser (recommended for new code).

    This function provides the same API as parseDom() but uses BeautifulSoup internally
    for more robust HTML parsing. It handles malformed HTML better and is more maintainable.

    Args:
        html: HTML content to parse
        name: Tag name to search for (e.g., 'div', 'a', 'span')
        attrs: Dictionary of attributes to filter by
        ret: Attribute name to extract (str) or False to return text content

    Returns:
        List of extracted values

    Examples:
        # Old way (parseDom):
        links = client.parseDom(html, 'a', ret='href')

        # New way (parseHTML) - same API:
        links = client.parseHTML(html, 'a', ret='href')

        # Extract content:
        titles = client.parseHTML(html, 'h2', attrs={'class': 'title'})
    """
    return bs4_parser.parse_html(html, name, attrs, ret)

def selectHTML(html, selector, ret=False):
    """
    Modern CSS selector-based HTML parser (recommended for new code).

    This is the most modern and readable way to parse HTML. It uses CSS selectors
    which are more powerful and easier to understand than the attrs dictionary approach.

    Args:
        html: HTML content to parse
        selector: CSS selector string
                Examples:
                - 'a.download' - links with class 'download'
                - 'div#main > p' - paragraphs directly under div with id 'main'
                - 'li[data-id]' - li elements with data-id attribute
        ret: Attribute name to extract (str) or False to return text content

    Returns:
        List of extracted values

    Examples:
        # Extract all download links:
        links = client.selectHTML(html, 'a.download-link', ret='href')

        # Get text from specific divs:
        texts = client.selectHTML(html, 'div.content > p')

        # Extract data attributes:
        data = client.selectHTML(html, 'li[data-video]', ret='data-video')

        # Complex selector:
        titles = client.selectHTML(html, 'div.movie h2.title a', ret='title')
    """
    return bs4_parser.select_html(html, selector, ret)

def replaceHTMLCodes(text):
    try:
        text = re.sub(r"(&#[0-9]+)([^;^0-9]+)", r"\1;\2", _ensure_text(text))
        text = unescape(text)
        replacements = {
            "&quot;": "\"",
            "&amp;": "&",
            "&lt;": "<",
            "&gt;": ">",
            "&#38;": "&",
            "&nbsp;": "",
            "&#8230;": "...",
            "&#8217;": "'",
            "&#8211;": "-"
        }
        for key, value in replacements.items():
            text = text.replace(key, value)
        return text.strip()
    except Exception:
        return _ensure_text(text)

# Add a concise, maintainable fallback list of modern user-agents.
AGENT_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.117 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.5845.96 Safari/537.36 Edg/116.0.1938.62",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.117 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.117 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:118.0) Gecko/20100101 Firefox/118.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.117 Mobile Safari/537.36",
    "Mozilla/5.0 (iPad; CPU OS 16_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.117 Safari/537.36 OPR/104.0.0.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:118.0) Gecko/20100101 Firefox/118.0",
]

# internal cache for loaded agents
_AGENTS = None

def _load_agents():
    """
    Load agents from user_agents.json (next to this file) if present and valid,
    otherwise return the built-in AGENT_LIST. Result is cached in-module.
    """
    global _AGENTS
    if _AGENTS is not None:
        return _AGENTS
    # try to load override file
    try:
        path = os.path.join(os.path.dirname(__file__), 'user_agents.json')
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
                if isinstance(data, list) and data and all(isinstance(x, str) for x in data):
                    _AGENTS = data
                    return _AGENTS
    except Exception:
        # ignore parse/load errors and fall back to default
        pass
    _AGENTS = AGENT_LIST
    return _AGENTS

def set_agent_list(agent_list):
    """
    Programmatically replace the in-memory agent list. Accepts a non-empty list of strings.
    """
    global _AGENTS
    if isinstance(agent_list, list) and agent_list and all(isinstance(x, str) for x in agent_list):
        _AGENTS = agent_list

def agent():
    # return a random agent from the loaded list
    return random.choice(_load_agents())

def randomagent():
    BR_VERS = [
        [f'{i}.0' for i in range(18, 50)],
        [
            '37.0.2062.103', '37.0.2062.120', '37.0.2062.124', '38.0.2125.101', '38.0.2125.104',
            '38.0.2125.111', '39.0.2171.71', '39.0.2171.95', '39.0.2171.99', '40.0.2214.93',
            '40.0.2214.111', '40.0.2214.115', '42.0.2311.90', '42.0.2311.135', '42.0.2311.152',
            '43.0.2357.81', '43.0.2357.124', '44.0.2403.155', '44.0.2403.157', '45.0.2454.101',
        ],
        [
            '45.0.2454.85', '46.0.2490.71', '46.0.2490.80', '46.0.2490.86', '47.0.2526.73',
            '47.0.2526.80', '48.0.2564.116', '49.0.2623.112', '50.0.2661.86', '51.0.2704.103',
            '52.0.2743.116', '53.0.2785.143', '54.0.2840.71', '61.0.3163.100'
        ],
        ['11.0'],
        ['8.0', '9.0', '10.0', '10.6']
    ]
    WIN_VERS = ['Windows NT 10.0', 'Windows NT 7.0', 'Windows NT 6.3', 'Windows NT 6.2',
                'Windows NT 6.1', 'Windows NT 6.0', 'Windows NT 5.1', 'Windows NT 5.0']
    FEATURES = ['; WOW64', '; Win64; IA64', '; Win64; x64', '']
    RAND_UAS = ['Mozilla/5.0 ({win_ver}{feature}; rv:{br_ver}) Gecko/20100101 Firefox/{br_ver}',
                'Mozilla/5.0 ({win_ver}{feature}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{br_ver} Safari/537.36',
                'Mozilla/5.0 ({win_ver}{feature}; Trident/7.0; rv:{br_ver}) like Gecko',
                'Mozilla/5.0 (compatible; MSIE {br_ver}; {win_ver}{feature}; Trident/6.0)']
    index = random.randrange(len(RAND_UAS))
    return RAND_UAS[index].format(
        win_ver=random.choice(WIN_VERS),
        feature=random.choice(FEATURES),
        br_ver=random.choice(BR_VERS[index]))

def randommobileagent(mobile=None):
    # fixed list (commas were missing in original)
    _mobagents = [
        'Mozilla/5.0 (Linux; Android 12; SM-S906N Build/QP1A.190711.020; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/80.0.3987.119 Mobile Safari/537.36', # Galaxy S22 Ultra
        'Mozilla/5.0 (Linux; Android 10; SM-G996U Build/QP1A.190711.020; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Mobile Safari/537.36', # Galaxy S21 Ultra
        'Mozilla/5.0 (Linux; Android 10; SM-G980F Build/QP1A.190711.020; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/78.0.3904.96 Mobile Safari/537.36', # Galaxy S20
        'Mozilla/5.0 (iPhone14,6; U; CPU iPhone OS 15_4 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Version/10.0 Mobile/19E241 Safari/602.1', # iPhone SE (3rd gen)
        'Mozilla/5.0 (iPad; CPU OS 10_2_1 like Mac OS X) AppleWebKit/602.4.6 (KHTML, like Gecko) Version/10.0 Mobile/14D27 Safari/602.1'
    ]
    if mobile and 'android' in str(mobile).lower():
        return random.choice(_mobagents[:3])
    return random.choice(_mobagents[3:])

def tinyw(url):
    u = request(url)
    if not u:
        return None
    m = re.findall(r'(?s)location.href = \'([^\']*)', cast(str, _ensure_text(u)))
    return m[0] if m else None

def tinyl(url):
    u = request(url)
    if not u:
        return None
    text = _ensure_text(u)
    m = re.findall(r'(?s)#skip-btn".*?href = "([^"]*)', str(text))
    return m[0] if m else None

def tinyjs(url):
    u = request(url)
    if not u:
        return None
    try:
        w = re.findall(r"dF\('([^']*)", cast(str, _ensure_text(u)))[0]
        s = unquote(w[:-1])
        t = ''.join(chr(ord(char) - int(w[-1])) for char in s)
        h = unquote(t)
        return re.findall(r'(?s)var count .*?location.href =\s*"([^"]*)', h)[0]
    except Exception:
        return None

def tinyu(url):
    u = request(url)
    if not u:
        return None
    try:
        e = re.compile(r'decode.*?"([^"]*)",([^,]*),"([^"]*)",([^,]*),([^,]*),([^\)]*)').findall(cast(str, _ensure_text(u)))[0]
        f = hunter.hunter(e[0], int(e[1]), e[2], int(e[3]), int(e[4]), int(e[5]))
        g = re.findall(r'\.attr\(\"href\",\"(.+?)\"', f)[1]
        return g.replace(' ', '%20')
    except Exception:
        return None

class Cfcookie:
    def __init__(self):
        self.cookie = None

    def get(self, netloc, ua, timeout):
        """
        Attempt to obtain Cloudflare clearance cookie. We try to use cfscrape first,
        otherwise return None. Keep same signature as before.
        """
        try:
            self.cookie = None
            try:
                # prefer cached version via cache helper (use walrus to assign once)
                if (cf := cache.get(cfscrape.get_cookie_string, 1, netloc, ua)):
                    self.cookie = cf[0] if isinstance(cf, (list, tuple)) else cf
            except Exception:
                try:
                    # fallback to direct call if cache failed
                    if (cf := cfscrape.get_cookie_string(netloc, ua)):
                        self.cookie = cf[0] if isinstance(cf, (list, tuple)) else cf
                except Exception:
                    self.cookie = None
            if self.cookie is None:
                c.log(f'{netloc} returned an error. Could not collect tokens.', 1)
            return self.cookie
        except Exception as e:
            c.log(f'{netloc} returned an error. Could not collect tokens - Error:{e}.', 1)
            return None

class bfcookie:
    def __init__(self):
        self.COOKIE_NAME = 'BLAZINGFAST-WEB-PROTECT'

    def get(self, netloc, ua, timeout):
        try:
            headers = {'User-Agent': ua, 'Referer': netloc}
            result = _basic_request(netloc, headers=headers, timeout=timeout)
            if not result:
                return False
            match = re.findall(r'xhr\.open\("GET","([^,]+),', cast(str, _ensure_text(result)))
            if not match:
                return False
            url_Parts = match[0].split('"')
            url_Parts[1] = '1680'
            url = urljoin(netloc, ''.join(url_Parts))
            match_rid = re.findall('rid=([0-9a-zA-Z]+)', url_Parts[0])
            if not match_rid:
                return False
            headers['Cookie'] = 'rcksid=%s' % match_rid[0]
            result2 = _basic_request(url, headers=headers, timeout=timeout)
            return self.getCookieString(result2, headers['Cookie'])
        except Exception:
            return

    def getCookieString(self, content, rcksid):
        try:
            parsed_variables = re.findall(r'toNumbers\("([^"]+)"', cast(str, _ensure_text(content)))
            if not parsed_variables or len(parsed_variables) < 3:
                return False
            value = self._decrypt(parsed_variables[2], parsed_variables[0], parsed_variables[1])
            return "%s=%s;%s" % (self.COOKIE_NAME, value, rcksid)
        except Exception:
            return False

    def _decrypt(self, msg, key, iv):
        try:
            from binascii import unhexlify, hexlify
            import pyaes
            msg = unhexlify(msg)
            key = unhexlify(key)
            iv = unhexlify(iv)
            if len(iv) != 16:
                return False
            decrypter = pyaes.Decrypter(pyaes.AESModeOfOperationCBC(key, iv))
            plain_text = decrypter.feed(msg)
            plain_text += decrypter.feed()
            # Ensure plain_text is a bytes-like object for hexlify
            if isinstance(plain_text, (bytes, bytearray)):
                # normalize bytearray to bytes
                if isinstance(plain_text, bytearray):
                    plain_text = bytes(plain_text)
            else:
                # convert arbitrary objects to text, then encode safely
                plain_text = _ensure_text(plain_text).encode('utf-8', errors='ignore')
            return hexlify(plain_text).decode('utf-8')
        except Exception:
            return False

class sucuri:
    def __init__(self):
        self.cookie = None

    def get(self, result):
        try:
            s = re.compile(r"S\s*=\s*'([^']+)").findall(_ensure_text(result))[0]
            s = base64.b64decode(s)
            s = s.replace(b' ', b'')
            script = s.decode('utf-8', errors='ignore')
            script = re.sub(r'String\.fromCharCode\(([^)]+)\)', r'chr(\1)', script)
            script = re.sub(r'\.slice\((\d+),(\d+)\)', r'[\1:\2]', script)
            script = re.sub(r'\.charAt\(([^)]+)\)', r'[\1]', script)
            script = re.sub(r'\.substr\((\d+),(\d+)\)', r'[\1:\1+\2]', script)
            script = re.sub(r';location.reload\(\);', '', script)
            script = re.sub(r'\n', '', script)
            # document.cookie -> cookie
            script = re.sub(r'document\.cookie', 'cookie', script)
            cookie = ''
            # Safely extract cookie assignment without executing the transformed script
            m = re.search(r"cookie\s*=\s*['\"]([^'\"]+)['\"]", script)
            if not m:
                m = re.search(r"cookie\s*=\s*([^;]+);", script)
            if not m:
                # fallback: search original result for document.cookie assignment
                m = re.search(r"document\.cookie\s*=\s*['\"]([^'\"]+)['\"]", _ensure_text(result))
            if m:
                cookie_val = m.group(1)
                pair = re.compile('([^=]+)=(.*)').findall(cookie_val)
                if pair:
                    k, v = pair[0]
                    self.cookie = f'{k}={v}'
                    return self.cookie
        except Exception:
            pass

def _get_keyboard(default="", heading="", hidden=False):
    keyboard = control.keyboard(default, heading, hidden)
    keyboard.doModal()
    if keyboard.isConfirmed():
        return _ensure_text(keyboard.getText())
    return default

def removeNonAscii(s):
    try:
        return "".join(i for i in s if ord(i) < 128)
    except Exception:
        return _ensure_text(s)