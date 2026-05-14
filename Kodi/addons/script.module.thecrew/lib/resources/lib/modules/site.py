# -*- coding: utf-8 -*-

"""
Compatibility shim for site.py module.

This module exists for backwards compatibility with remote downloaded files
(crewstreamer.xml, crewschedule.xml, crewreplays.xml from posadka/xmls2 repo)
that still import 'from resources.lib.modules import site'.

All functionality has been moved to client.py. This file simply re-exports
all client functions to maintain compatibility.

TODO: Remove this file once remote XML files are updated to import client directly.
"""

from resources.lib.modules.client import *

# Explicitly re-export commonly used functions for clarity
__all__ = [
    'request',
    'parseDOM',
    'parseDom',
    'parseHTML',
    'selectHTML',
    'retriever',
    'agent',
    'randomagent',
    'mobile_agent',
    'safari_agent',
    'source',
    'cfcookie',
    'cfScrape',
    'getWebURL',
    'replaceHTMLCodes',
    'cleanHTML',
]
