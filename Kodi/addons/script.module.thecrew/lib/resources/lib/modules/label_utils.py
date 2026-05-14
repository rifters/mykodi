# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file label_utils.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re

def build_labels_static(source, index, multi_language=False, extra_info=False):
    """Construct single-line and multi-line labels for a source.

    Returns (label, multiline_label)
    Single-line format: 'NN | QUALITY | PROVIDER (DEBRID) | SOURCE | INFO_SHORT'
    Multi-line contains full info including size and other details.
    """
    try:
        # basic parts
        p = source.get('provider', '') or ''
        # For display, use the raw provider string; callers can format if desired
        p_display = p
        q = source.get('quality', '') or ''
        s = source.get('source', '') or ''
        # info parts (split by '|')
        raw_info = source.get('info') or ''
        info_parts = [i.strip() for i in raw_info.split('|') if i.strip()]

        # If first info part looks like a size, remove it for short info
        info_short_parts = list(info_parts)
        if info_short_parts:
            if re.match(r'^[\d\.,]+\s*(?:GB|GiB|MB|MiB)$', info_short_parts[0], re.I):
                info_short_parts = info_short_parts[1:]
        info_short = ' | '.join(info_short_parts)

        # debrid short code
        d = source.get('debrid', '') or ''
        try:
            d_str = d.lower() if isinstance(d, str) else str(d).lower()
        except Exception:
            d_str = str(d).lower()
        if d_str == 'alldebrid':
            d_short = 'AD'
        elif d_str == 'debrid-link.fr':
            d_short = 'DL.FR'
        elif d_str == 'linksnappy':
            d_short = 'LS'
        elif d_str == 'megadebrid':
            d_short = 'MD'
        elif d_str == 'premiumize.me':
            d_short = 'PM'
        elif d_str == 'torbox':
            d_short = 'TB'
        elif d_str == 'real-debrid':
            d_short = 'RD'
        elif d_str == 'zevera':
            d_short = 'ZVR'
        else:
            d_short = d if d else ''

        # single-line label: number | quality | DEBRID | PROVIDER | SIZE | OTHER_INFO
        # Determine size and other info
        size = ''
        other_info = ''
        if info_parts:
            if re.match(r'^[\d\.,]+\s*(?:GB|GiB|MB|MiB)$', info_parts[0], re.I):
                size = info_parts[0]
                other_info = ' / '.join(info_parts[1:]) if len(info_parts) > 1 else ''
            else:
                other_info = ' / '.join(info_parts)

        parts = [f"{int(index+1):02d}", q, d_short, p_display]
        if size:
            parts.append(size)
        if other_info:
            parts.append(other_info)

        # Remove empty items for a tidy single-line
        label = ' | '.join([p for p in parts if p != '']) + ' | '

        # multiline label: include details (size first if present)
        details = ''
        if info_parts:
            details = ' | '.join(info_parts)

        if extra_info and 'url' in source:
            t = None
        else:
            t = None

        multiline_label = f"{int(index+1):02d} | {q} | {d_short} | {p_display} | {s}"
        if t:
            if details:
                multiline_label += f" \n       {details} | {t}"
            else:
                multiline_label += f" \n       {t}"
        else:
            if details:
                multiline_label += f" \n       {details}"
            else:
                multiline_label += ""

        return label, multiline_label
    except Exception:
        # Fallback simple labels
        return f"{int(index+1):02d} | {source.get('quality','')} | {source.get('provider','')} | ", source.get('source','')
