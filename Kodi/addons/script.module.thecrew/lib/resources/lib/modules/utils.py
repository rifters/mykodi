# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file utils.py
* @package plugin.video.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
import json


def json_load_as_str(file_handle):
    """
    Load JSON data from a file handle and converts it to a string.

    This function reads JSON data from a provided file handle, applies the
    `byteify` function to ensure all strings are appropriately encoded, and
    returns the data as a string. The `byteify` function is used as an object
    hook during the JSON loading process to manage string encoding.

    Args:
        file_handle: A file-like object containing JSON data.

    Returns:
        The JSON data as a string with correct encoding.
    """

    return byteify(json.load(file_handle, object_hook=byteify), ignore_dicts=True)


def json_loads_as_str(json_text):
    """
    Load JSON data from a string and converts it to a string.

    This function reads JSON data from a provided string, applies the
    `byteify` function to ensure all strings are appropriately encoded, and
    returns the data as a string. The `byteify` function is used as an object
    hook during the JSON loading process to manage string encoding.

    Args:
        json_text: A string containing JSON data.

    Returns:
        The JSON data as a string with correct encoding.
    """
    return byteify(json.loads(json_text, object_hook=byteify), ignore_dicts=True)


def byteify(data, ignore_dicts=False):
    """
    Make sure that all strings contained in data are of type unicode/str.

    This function is used as an object hook during the JSON loading process to
    manage string encoding. It recursively goes through the provided data and
    applies the correct encoding to all strings. If the data is a dictionary and
    the `ignore_dicts` parameter is set to `True`, the function will not recurse
    into the dictionary and will return it unchanged. If the data is a list, the
    function will go through all items in the list and apply the correct
    encoding to all strings.

    Args:
        data: A object containing strings to be checked and encoded.
        ignore_dicts: If set to `True`, dictionaries will be returned unchanged.
    """
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        return [byteify(item, ignore_dicts=True) for item in data]
    if isinstance(data, dict) and not ignore_dicts:
        return dict([(byteify(key, ignore_dicts=True), byteify(value, ignore_dicts=True)) for key, value in data.items()])
    return data

def title_key(title):
    """
    Processes a title string to remove leading articles.

    This function takes a title, checks for leading articles (e.g., 'the', 'a', 'an' in English;
    'der', 'die', 'das' in German), and removes them to produce a key suitable for sorting or
    comparison. If the title is None, it is treated as an empty string.

    Args:
        title: A string representing the title to process.

    Returns:
        A string with the leading article removed, if present. If an error occurs during processing,
        the original title is returned unchanged.
    """

    try:
        if title is None:
            title = ''

        articles_en = ['the', 'a', 'an'] #English
        articles_de = ['der', 'die', 'das'] #German
        articles_nl = ['de', 'het', 'een'] #Dutch
        articles = articles_en + articles_de + articles_nl

        match = re.match(r'^((\w+)\s+)', title.lower())
        if match and match.group(2) in articles:
            offset = len(match.group(1))
        else:
            offset = 0

        return title[offset:]
    except:
        return title

def chunk_list(input_list, chunk_size):
    """
    Yield successive n-sized chunks from input_list.
    """
    for index in range(0, len(input_list), chunk_size):
        yield input_list[index:index + chunk_size]

def traverse(iterable, tree_types=(list, tuple)):
    """
    Yield values from irregularly nested iterables.

    Args:
        iterable: The iterable to traverse.
        tree_types: The types of iterables to traverse. Defaults to (list, tuple).
    """
    for item in iterable:
        if isinstance(item, tree_types):
            yield from traverse(item, tree_types)
        else:
            yield item

def parse_size(size):
    """
    Parse a size string and return a tuple with the size in bytes and a human-readable string.

    Args:
        size (str): The size string to parse.

    Returns:
        tuple: A tuple containing the size in bytes and a human-readable string.
    """
    if size in ('0', 0, '', None):
        return 0, ''

    # Determine the divisor based on the units of the size string
    divisor = 1024 if size.lower().endswith(('.gb', '.gib')) else 1

    # Extract the numeric value from the size string
    numeric_value = float(re.sub('[^0-9|/.|/,]', '', size.replace(',', '.')))

    # Calculate the size in bytes
    size_in_bytes = numeric_value / divisor

    # Format the human-readable string
    human_readable_string = f'{size_in_bytes:.2f} GB'

    return size_in_bytes, human_readable_string
