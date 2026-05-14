# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file cleantitle.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''


import re

import unicodedata

from string import printable
from urllib.parse import unquote

def get(title):
    if not title:
        return
    # cm = changed 2024/11/10
    # cm = changed 2025/06/11
    # cm = changed 2026/03/04 - fixed regex patterns for Python 3 compatibility
    # cm - defensive check to convert to string (API responses are typically strings already)
    if not isinstance(title, str):
        title = str(title)
    title = re.sub(r'&#(\d+);', '', title) # removes all complete HTML entities like &#1234;
    title = re.sub(r'(&#[0-9]+)([^;0-9]+)', r'\1;\2', title) # fixes incomplete HTML entities by adding semicolon
    title = title.replace('&quot;', '"').replace('&amp;', 'and').replace('&', 'and').replace('–', '-').replace('!', '') # replaces HTML entities with their character equivalents
    # Remove: newlines, bracket chars (keep content), parens+content, vs/v., punctuation, whitespace
    title = re.sub(r'\n|[\[\]]|\(.*?\)|\s(vs|v\.)\s|[:|;|\-|–|"|,|\'|_|\.|?]|\s', '', title).lower()

    return title


def get_title(title):
    if not title:
        return

    try:
        title = str(title)
    except ValueError:
        pass
    title = unquote(title).lower()
    title = re.sub('[^a-z0-9 ]+', ' ', title)
    title = re.sub(' {2,}', ' ', title)
    return title


def geturl(title):
    '''
    Sanitizes a string to be used in a URL path
    Replaces spaces with hyphens and removes all special characters
    Also removes trailing spaces and replaces multiple hyphens with a single one
    '''
    if not title:
        return
    try:
        title = str(title)
    except ValueError:
        pass
    title = title.lower()
    title = title.rstrip()
    try:
        title = title.translate(None, r':*?"\'\.<>|&!,')
    except TypeError:
        title = title.translate(str.maketrans('', '', r':*?"\'\.<>|&!,'))
    title = title.replace('/', '-')
    title = title.replace(' ', '-')
    title = title.replace('--', '-')
    title = title.replace('–', '-')
    title = title.replace('!', '')
    return title


def get_url(title):
    '''
    Sanitizes a string to be used in a URL path
    Replaces spaces with %20 and removes all special characters
    '''
    if not title:
        return
    try:
        title = str(title)
    except ValueError:
        pass
    title = title.replace(' ', '%20').replace('–', '-').replace('!', '')
    return title


def get_gan_url(title):
    '''
    Sanitizes a string to be used in a URL path
    Replaces spaces with %20, and all dashes with +
    Replaces multiple spaces with +-+
    '''
    if not title:
        return
    title = title.lower()
    title = title.replace('-','+')
    title = title.replace(' + ', '+-+')
    title = title.replace(' ', '%20')
    return title


def get_query_(title):
    '''
    Sanitizes a string to be used in a query string
    Replaces spaces with _, single quotes with _, dashes with _, en dashes with _,
    colons with '', commas with '', and ! with ''
    Returns the string in lowercase
    '''
    if not title:
        return
    try:
        title = str(title)
    except ValueError:
        pass
    title = title.replace(' ', '_').replace("'", "_").replace('-', '_')
    title = title.replace('–', '_').replace(':', '').replace(',', '').replace('!', '')
    return title.lower()

def get_simple(title):
    """
    Simplifies a given title by applying a series of sanitizations.

    - Converts the title to lowercase.
    - Removes any 4-digit numbers (commonly years).
    - Removes HTML numeric character references (e.g., &#1234;).
    - Replaces certain HTML entities with their character equivalents.
    - Removes en dashes and replaces them with hyphens.
    - Eliminates newlines, parentheses, brackets, curly braces, and certain punctuation.
    - Removes instances of "vs" and "v." surrounded by spaces.
    - Strips HTML tags.

    Returns the simplified title as a lowercase string.
    """
    if title is None:
        return
    try:
        title = str(title)
    except ValueError:
        pass
    title = title.lower()
    title = re.sub(r'(\d{4})', '', title)
    title = re.sub(r'&#(\d+);', '', title)
    title = re.sub('(&#[0-9]+)([^;^0-9]+)', '\\1;\\2', title)
    title = title.replace('&quot;', '\"').replace('&amp;', '&').replace('–', '-')
    title = re.sub(r'\n|\(|\)|\[|\]|\{|\}|\s(vs|v[.])\s|(:|;|-|–|"|,|\'|\_|\.|\?)|\s', '', title)
    title = title.lower()
    title = re.sub(r'<.*?>', '', title, count=0)
    return title


def getsearch(title):
    """
    Cleans and sanitizes a given title string for search purposes.

    - Converts the title to lowercase.
    - Removes HTML numeric character references (e.g., &#1234;).
    - Fixes incomplete HTML numeric character references by adding semicolons.
    - Replaces certain HTML entities with their character equivalents.
    - Replaces en dashes with hyphens.
    - Removes backslashes, slashes, colons, semicolons, exclamation marks, asterisks, question marks,
    - double quotes, single quotes, angle brackets, and pipes.

    Returns the cleaned title as a lowercase string.
    """
    if title is None:
        return
    try:
        title = str(title)
    except ValueError:
        pass
    title = title.lower()
    title = re.sub(r'&#(\d+);', '', title)
    title = re.sub('(&#[0-9]+)([^;^0-9]+)', '\\1;\\2', title)
    title = title.replace('&quot;', '\"').replace('&amp;', '&').replace('–', '-')
    title = re.sub(r'\\\|/|-|–|:|;|!|\*|\?|"|\'|<|>|\|', '', title).lower()
    return title


def query(title):
    """
    Cleans and formats a given title string for query purposes.

    - Converts the title to a string if it's not already.
    - Removes single quotes.
    - Strips any content after the last colon and after the last hyphen.
    - Replaces hyphens and en dashes with spaces.
    - Removes exclamation marks.

    Returns the cleaned and formatted title.
    """
    if title is None:
        return
    try:
        title = str(title)
    except ValueError:
        pass
    title = title.replace('\'', '').rsplit(':', 1)[0].rsplit(' -', 1)[0].replace('-', ' ').replace('–', ' ').replace('!', '')
    return title


def get_query(title):
    """
    Sanitizes a given title string to be used in a query string

    - Removes colons and single quotes.
    - Converts the title to lowercase.

    Returns the cleaned title as a lowercase string.
    """
    if title is None:
        return
    try:
        title = str(title)
    except ValueError:
        pass

    return title.replace(':', '').replace("'", "").lower()


def normalize(title):
    """
    Normalize a given title string.

    - Converts the title to a string if it's not already.
    - Normalizes the title string using the Unicode Normalization Form
    - Compatibility Decomposition (NFKD) algorithm.
    - Removes any non-printable characters (e.g. non-ASCII characters).

    Returns the normalized title string.
    """
    try:
        title_str = str(title)
        normalized_title = unicodedata.normalize('NFKD', title_str)
        cleaned_title = ''.join(c for c in normalized_title if c in printable)
        return cleaned_title
    except (TypeError, ValueError):
        return title

def clean_search_query(query_string):
    """
    Clean up a search query string by replacing special characters with safe ones.
    """
    return query_string.replace("-", "+").replace(" ", "+").replace("–", "+").replace("!", "")
