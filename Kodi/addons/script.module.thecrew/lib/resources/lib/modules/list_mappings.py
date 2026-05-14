# -*- coding: utf-8 -*-
'''
 ***********************************************************
 * The Crew Add-on
 *
 * @file list_mappings.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''
import os
import json
from ..modules import control
from ..modules.crewruntime import c

_MAPPINGS = None


def _mappings_path():
    # Load mapping file from package data
    base = os.path.join(os.getcwd(), 'lib', 'resources', 'lib', 'data')
    return os.path.join(base, 'list_replacements.json')


def load_mappings():
    global _MAPPINGS
    if _MAPPINGS is not None:
        return _MAPPINGS
    path = _mappings_path()
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            _MAPPINGS = json.load(fh)
            c.log(f'[ListMappings] Loaded {len(_MAPPINGS)} mappings from {path}')
            return _MAPPINGS
    except Exception as e:
        c.log(f'[ListMappings] Failed to load mappings: {e}')
        _MAPPINGS = {}
        return _MAPPINGS


def get_replacement_for_trakt_url(trakt_url: str):
    """Return a mapping dict for a trakt list URL or None.

    Matching strategy:
    - exact match on path
    - substring match (if any key found inside trakt_url)
    """
    try:
        mappings = load_mappings()
        # Normalize
        for key, val in mappings.items():
            if trakt_url.endswith(key) or key in trakt_url:
                return val
        return None
    except Exception as e:
        c.log(f'[ListMappings] Error looking up mapping for {trakt_url}: {e}')
        return None
