# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file __init__.py
 * @package script.module.thecrew.apis
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

from .realdebrid_api import RealDebridAPI
from .alldebrid_api import AllDebridAPI
from .premiumize_api import PremiumizeAPI
from .trakt_api import TraktAPI
from .orion_api import OrionAPI
from .tmdb_api import TMDbAPI
from .tvdb_api import TVDbAPI
from .fanart_api import FanartAPI

__all__ = [
    'RealDebridAPI',
    'AllDebridAPI',
    'PremiumizeAPI',
    'TraktAPI',
    'OrionAPI',
    'TMDbAPI',
    'TVDbAPI',
    'FanartAPI'
]
