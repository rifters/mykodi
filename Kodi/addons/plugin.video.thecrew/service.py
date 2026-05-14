# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 * Thin launcher - all service logic lives in
 * script.module.thecrew/lib/resources/lib/modules/crewservice.py
 *
 * @file service.py
 * @package plugin.video.thecrew
 *
 * @copyright (c) 2023 - 2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

# cm - 04/25/2026 - reduced to launcher; all logic moved to crewservice.py in the module

import os
import sys
import xbmcaddon

_crew_addon = xbmcaddon.Addon('script.module.thecrew')
_lib_path = os.path.join(_crew_addon.getAddonInfo('path'), 'lib')
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

from resources.lib.modules import crewservice
crewservice.start()
