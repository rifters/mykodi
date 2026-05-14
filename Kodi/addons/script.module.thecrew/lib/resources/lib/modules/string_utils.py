# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 * @file string_utils.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2025, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 * String utility functions for Python 3
 ***********************************************************
'''

import re
from typing import Any, Union


def ensure_str(data: Any, encoding: str = 'utf-8', errors: str = 'replace') -> str:
    """
    Convert data to str (unicode string in Python 3).

    Args:
        data: Input data of any type
        encoding: Encoding to use for bytes
        errors: Error handling strategy

    Returns:
        String representation of the data
    """
    if isinstance(data, str):
        return data
    if isinstance(data, bytes):
        return data.decode(encoding, errors=errors)
    return str(data)


def ensure_bytes(data: Any, encoding: str = 'utf-8', errors: str = 'replace') -> bytes:
    """
    Convert data to bytes.

    Args:
        data: Input data of any type
        encoding: Encoding to use for strings
        errors: Error handling strategy

    Returns:
        Bytes representation of the data
    """
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode(encoding, errors=errors)
    return str(data).encode(encoding, errors=errors)


def safe_decode(data: Union[str, bytes], encoding: str = 'utf-8') -> str:
    """
    Safely decode bytes to string, handling already-decoded strings.

    Args:
        data: String or bytes to decode
        encoding: Encoding to use

    Returns:
        Decoded string
    """
    if isinstance(data, bytes):
        return data.decode(encoding, errors='replace')
    return str(data)


def clean_html(text: str) -> str:
    """
    Remove HTML tags and unescape HTML entities.

    Args:
        text: HTML text to clean

    Returns:
        Clean text without HTML
    """
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Unescape HTML entities
    try:
        from html import unescape
        text = unescape(text)
    except ImportError:
        # Fallback for older Python versions (shouldn't happen in Python 3)
        import html.parser
        text = html.parser.HTMLParser().unescape(text)

    return text.strip()


def normalize_string(text: str, lowercase: bool = False, remove_special: bool = False) -> str:
    """
    Normalize string for comparison.

    Args:
        text: Text to normalize
        lowercase: Convert to lowercase
        remove_special: Remove special characters

    Returns:
        Normalized string
    """
    if lowercase:
        text = text.lower()

    if remove_special:
        # Keep only alphanumeric and spaces
        text = re.sub(r'[^a-zA-Z0-9\s]', '', text)

    # Normalize whitespace
    text = ' '.join(text.split())

    return text


def truncate(text: str, max_length: int, suffix: str = '...') -> str:
    """
    Truncate text to maximum length with suffix.

    Args:
        text: Text to truncate
        max_length: Maximum length including suffix
        suffix: Suffix to add if truncated

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text

    return text[:max_length - len(suffix)] + suffix


def join_non_empty(separator: str, *items: Any) -> str:
    """
    Join items with separator, skipping None and empty strings.

    Args:
        separator: Separator string
        *items: Items to join

    Returns:
        Joined string
    """
    return separator.join(str(item) for item in items if item not in (None, '', '0'))
