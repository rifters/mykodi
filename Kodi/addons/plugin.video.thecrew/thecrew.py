# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file thecrew.py
* @package plugin.video.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import sys
import xbmc
from resources.lib.modules.crewruntime import c

# ENTRY POINT LOGGING - Log before ANY imports
try:
	c.log('[THE CREW ENTRY] thecrew.py STARTED - argv=' + str(sys.argv), trace=1)
except:
	pass  # If this fails, nothing we can do

from sys import argv

try:
	c.log('[THE CREW ENTRY] Importing crew module...', 1)
	from resources.lib.modules import crew
	c.log('[THE CREW ENTRY] crew module imported successfully', 1)
except Exception as e:
	c.log('[THE CREW ENTRY] FAILED to import crew: ' + str(e), 1)
	import traceback
	c.log('[THE CREW ENTRY] Traceback: ' + traceback.format_exc(), 1)
	raise

from urllib.parse import parse_qsl

try:
	c.log('[THE CREW ENTRY] Parsing params from argv[2]=' + str(argv[2] if len(argv) > 2 else 'MISSING'), 1)
	params = dict(parse_qsl(argv[2].replace('?', '')))
	c.log('[THE CREW ENTRY] Parsed params=' + str(params), 1)
except Exception as e:
	c.log('[THE CREW ENTRY] Error parsing params: ' + str(e), 1)
	params = {}

try:
	c.log('[THE CREW ENTRY] Calling crew.router with params=' + str(params), 1)
	crew.router(params)
	c.log('[THE CREW ENTRY] crew.router completed', 1)
except Exception as e:
	c.log('[THE CREW ENTRY] crew.router FAILED: ' + str(e), 1)
	import traceback
	c.log('[THE CREW ENTRY] Traceback: ' + traceback.format_exc(), 1)
	raise