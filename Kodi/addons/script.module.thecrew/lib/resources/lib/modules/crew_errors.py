# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file crew_errors.py
* @package script.module.thecrew
*
* @copyright (c) 2025-2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

class TraktResourceError(Exception):
    pass
class TraktError(Exception):
    pass

class NoResultsError(Exception):
    pass

class GeneralError(Exception):
    pass