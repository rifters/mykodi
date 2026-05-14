# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file debridapis.py (Legacy Compatibility Wrapper)
 * @package script.module.thecrew
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 * DEPRECATED: This file is maintained for backward compatibility only.
 * New code should import from apis/ directory:
 *   from ..apis import RealDebridAPI, AllDebridAPI, PremiumizeAPI
 *
 ********************************************************cm*
'''

# Import the new API classes from dedicated modules
from ..apis.realdebrid_api import RealDebridAPI
from ..apis.alldebrid_api import AllDebridAPI
from ..apis.premiumize_api import PremiumizeAPI

# Backward compatibility aliases (lowercase names)
realdebrid = RealDebridAPI
alldebrid = AllDebridAPI
premiumize = PremiumizeAPI

# Export for import * statements
__all__ = ['realdebrid', 'alldebrid', 'premiumize', 'RealDebridAPI', 'AllDebridAPI', 'PremiumizeAPI']
