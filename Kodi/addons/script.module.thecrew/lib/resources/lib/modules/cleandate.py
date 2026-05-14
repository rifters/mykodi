# -*- coding: utf-8 -*-

'''
 ***********************************************************
 *
 * The Crew Addon
 *
 * @file cleandate.py
 * @package script.module.thecrew
 *
 * @copyright 2025, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

import time
import datetime
import re


def new_iso_to_utc(iso_ts):
    if not iso_ts:
        return 0
    return int(time.mktime(time.strptime(iso_ts, "%Y-%m-%dT%H:%M:%S.000Z")))

def now_to_iso():
    return datetime.datetime.now().isoformat('T', 'milliseconds') + 'Z'


def has_aired(air_date):
    """
    Check if content has aired based on premiere/air date.

    Centralized utility for consistent aired date validation across the addon.
    Replaces scattered date comparison logic in episodes.py, seasons.py, movies.py, etc.

    :param str air_date: Air/premiere date in format 'YYYY-MM-DD' or '0' or None/''
    :return: True if aired (date <= today), False if not aired (date > today) or no date
    :rtype: bool

    Examples:
        has_aired('2025-01-15')  # True if today is >= 2025-01-15
        has_aired('2027-12-31')  # False (future date)
        has_aired('0')           # False (no date)
        has_aired(None)          # False (no date)
        has_aired('')            # False (no date)
    """
    if not air_date or air_date == '0' or air_date == '':
        return False

    try:
        # Remove all non-numeric characters for comparison (YYYYMMDD format)
        air_date_num = int(re.sub(r'[^0-9]', '', air_date))
        today_num = int(datetime.datetime.now().strftime('%Y%m%d'))

        # Has aired if air date <= today
        return air_date_num <= today_num

    except (ValueError, TypeError):
        # If date parsing fails, assume not aired (safe default)
        return False
