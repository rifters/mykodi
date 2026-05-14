# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file bs4_parser.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*

Modern HTML parser using BeautifulSoup4.

This module provides a clean, maintainable alternative to regex-based HTML parsing.
It offers both a backwards-compatible API (matching parseDom/parseDOM) and a new
CSS selector-based API for modern usage.

Benefits over regex parsing:
- Handles malformed/broken HTML gracefully
- CSS selectors are more readable and maintainable
- Rich traversal and searching capabilities
- Industry-standard, well-documented library
- Better performance on complex documents

'''
try:
    from bs4 import BeautifulSoup
except ImportError:
    # Kodi's BeautifulSoup might be under different import path
    try:
        from lib import BeautifulSoup
    except ImportError:
        BeautifulSoup = None


def parse_html(html, name='', attrs=None, ret=False):
    """
    BeautifulSoup-based parser with backwards-compatible API.

    This function matches the signature of parseDom/parseDOM but uses BeautifulSoup
    internally for robust HTML parsing.

    Args:
        html: HTML content (str or bytes) to parse
        name: Tag name to search for (e.g., 'div', 'a', 'span')
        attrs: Dictionary of attributes to filter by (key-value pairs)
               Example: {'class': 'title', 'id': 'main'}
        ret: Attribute name to extract (str) or False to return text content
             Example: ret='href' extracts href attribute values

    Returns:
        List of extracted values (either text content or attribute values)
        Returns empty list if parsing fails or no matches found

    Examples:
        # Extract all links
        links = parse_html(html, 'a', ret='href')

        # Get text from divs with specific class
        texts = parse_html(html, 'div', attrs={'class': 'content'})

        # Extract data attributes
        data = parse_html(html, 'li', attrs={'class': 'item'}, ret='data-id')
    """
    if BeautifulSoup is None:
        # Fallback to empty list if BeautifulSoup not available
        return []

    if not html:
        return []

    try:
        # Ensure html is string
        if isinstance(html, bytes):
            html = html.decode('utf-8', errors='replace')
        elif not isinstance(html, str):
            html = str(html)

        # Parse HTML with lxml parser if available, otherwise html.parser
        try:
            soup = BeautifulSoup(html, 'lxml')
        except Exception:
            soup = BeautifulSoup(html, 'html.parser')

        # Find elements
        if attrs is None:
            attrs = {}

        if name:
            # Convert class_ to class for BeautifulSoup
            bs4_attrs = {}
            for key, value in attrs.items():
                if key == 'class':
                    bs4_attrs['class_'] = value
                else:
                    bs4_attrs[key] = value

            elements = soup.find_all(name, attrs=bs4_attrs if bs4_attrs else None)
        else:
            # No tag name specified - search by attributes only
            elements = soup.find_all(attrs=attrs if attrs else None)

        # Extract results
        results = []
        if ret:
            # Extract specified attribute
            for elem in elements:
                attr_value = elem.get(ret, '')
                results.append(str(attr_value) if attr_value else '')
        else:
            # Extract text content
            for elem in elements:
                text = elem.get_text(strip=False)
                results.append(text)

        return results

    except Exception:
        # Return empty list on any error
        return []


def select_html(html, selector, ret=False):
    """
    Modern CSS selector-based HTML parser.

    This is the recommended function for new code. It uses CSS selectors which are
    more readable and powerful than the old attrs dictionary approach.

    Args:
        html: HTML content (str or bytes) to parse
        selector: CSS selector string
                Examples:
                - 'div.content' - divs with class 'content'
                - 'a[href]' - all links with href attribute
                - 'div#main > p' - paragraphs directly under div with id 'main'
                - 'li.item[data-id]' - li elements with class 'item' and data-id attribute
        ret: Attribute name to extract (str) or False to return text content

    Returns:
        List of extracted values (either text content or attribute values)
        Returns empty list if parsing fails or no matches found

    Examples:
        # Extract all links with specific class
        links = select_html(html, 'a.download-link', ret='href')

        # Get text from all paragraphs inside main content
        texts = select_html(html, 'div.main-content p')

        # Extract data attributes from list items
        data = select_html(html, 'li[data-video]', ret='data-video')

        # Complex selector
        titles = select_html(html, 'div.movie > h2.title > a', ret='title')
    """
    if BeautifulSoup is None:
        return []

    if not html:
        return []

    try:
        # Ensure html is string
        if isinstance(html, bytes):
            html = html.decode('utf-8', errors='replace')
        elif not isinstance(html, str):
            html = str(html)

        # Parse HTML
        try:
            soup = BeautifulSoup(html, 'lxml')
        except Exception:
            soup = BeautifulSoup(html, 'html.parser')

        # Use CSS selector
        elements = soup.select(selector)

        # Extract results
        results = []
        if ret:
            # Extract specified attribute
            for elem in elements:
                attr_value = elem.get(ret, '')
                results.append(str(attr_value) if attr_value else '')
        else:
            # Extract text content
            for elem in elements:
                text = elem.get_text(strip=False)
                results.append(text)

        return results

    except Exception:
        return []


def get_element(html, selector):
    """
    Get a single BeautifulSoup element for advanced manipulation.

    This function returns the actual BeautifulSoup element object, allowing
    you to use the full BS4 API for complex parsing scenarios.

    Args:
        html: HTML content to parse
        selector: CSS selector string

    Returns:
        BeautifulSoup Tag object or None if not found

    Example:
        elem = get_element(html, 'div.main-content')
        if elem:
            # Access attributes
            class_name = elem.get('class')

            # Navigate
            parent = elem.parent
            children = elem.find_all('p')

            # Extract data
            text = elem.get_text()
            html_content = str(elem)
    """
    if BeautifulSoup is None:
        return None

    if not html:
        return None

    try:
        if isinstance(html, bytes):
            html = html.decode('utf-8', errors='replace')

        try:
            soup = BeautifulSoup(html, 'lxml')
        except Exception:
            soup = BeautifulSoup(html, 'html.parser')

        return soup.select_one(selector)

    except Exception:
        return None


def get_soup(html):
    """
    Get a BeautifulSoup object for maximum flexibility.

    Use this when you need full control and want to use the BeautifulSoup API directly.

    Args:
        html: HTML content to parse

    Returns:
        BeautifulSoup object or None if parsing fails

    Example:
        soup = get_soup(html)
        if soup:
            # Use full BeautifulSoup API
            links = soup.find_all('a', class_='download')
            for link in links:
                href = link.get('href')
                title = link.get_text()
    """
    if BeautifulSoup is None:
        return None

    if not html:
        return None

    try:
        if isinstance(html, bytes):
            html = html.decode('utf-8', errors='replace')

        try:
            return BeautifulSoup(html, 'lxml')
        except Exception:
            return BeautifulSoup(html, 'html.parser')

    except Exception:
        return None
