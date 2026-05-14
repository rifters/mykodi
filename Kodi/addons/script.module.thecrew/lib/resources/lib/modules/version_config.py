# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file version_config.py
* @package script.module.thecrew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*

Version Announcement Configuration

This file contains all version-specific announcement data.
Easy to maintain - just add new versions or update templates!

How it works:
1. When a version announcement is shown, it first checks VERSION_ANNOUNCEMENTS
2. If the specific version exists, use that data
3. If not, detect version type (alpha/beta/stable) and use the appropriate TEMPLATE
4. You can override just specific fields by providing them in VERSION_ANNOUNCEMENTS

Maintenance:
- For new releases: Add entry to VERSION_ANNOUNCEMENTS with version-specific highlights
- For template changes: Update TEMPLATES (affects all versions of that type)
- Keep old version entries for historical reference (helpful for rollbacks)
'''

# ==========================================================================cm=
# TEMPLATES - Default announcements for version types
# ==========================================================================cm=

TEMPLATES = {
    'alpha': {
        'announcement_type': '>> ALPHA VERSION <<',
        'highlights': [
            '+ This is an experimental version, do not use in production (builds)',
            '+ Bugs and issues are expected',
            '+ Please report issues on GitHub - Classy'
        ],
        'show_warning': True
    },

    'beta': {
        'announcement_type': '>> BETA VERSION <<',
        'highlights': [
            '+ This is a pre-release build for testing, do not use in build/repos (no, really!)',
            '+ Most features are stable, but some bugs may exist',
            '+ Feedback and bug reports are appreciated'
        ],
        'show_warning': True
    },

    'stable': {
        'announcement_type': '** NEW VERSION **',
        'highlights': [
            '+ Welcome to the latest version of The Crew',
            '+ Check the changelog for all new features and fixes',
            '+ Report any issues on our GitHub'
        ],
        'show_warning': False
    }
}


# ==========================================================================cm=
# VERSION_ANNOUNCEMENTS - Specific announcements for individual versions
# ==========================================================================cm=
# Add entries here when you want custom text for a specific version.
# If a version isn't listed here, it will use the appropriate TEMPLATE above.
#
# Format:
# 'version': {
#     'announcement_type': 'Header text',  # Optional: overrides template
#     'highlights': [                      # Optional: overrides template
#         'First bullet point',
#         'Second bullet point',
#         'Third bullet point'             # Max 3 highlights
#     ],
#     'show_warning': True/False           # Optional: overrides template
# }
# ==========================================================================cm=

VERSION_ANNOUNCEMENTS = {
    # Example: Version 2.2.5-alpha with custom highlights
    '2.2.5-alpha': {
        'highlights': [
            '+ Comprehensive startup maintenance system',
            '+ TV Evening session tracking improvements',
            '+ OpenSubtitles REST API integration'
        ]
    },

    # Example: Future stable release with custom announcement
    # '2.3.0': {
    #     'announcement_type': '*** MAJOR UPDATE - v2.3.0 ***',
    #     'highlights': [
    #         '+ Brand new feature X',
    #         '+ Performance improvements',
    #         '+ 100+ bug fixes'
    #     ],
    #     'show_warning': False
    # },

    # Example: Beta release
    # '2.2.9-beta': {
    #     'highlights': [
    #         '+ Testing new scraper engine',
    #         '+ All features from 2.2.5 included',
    #         '+ Please test and report findings'
    #     ]
    # },
}


# ==========================================================================cm=
# HELPER FUNCTIONS - For advanced use cases
# ==========================================================================cm=

def get_announcement_data(version):
    """
    Get announcement data for a specific version.

    Logic:
    1. Check if version exists in VERSION_ANNOUNCEMENTS
    2. Determine version type (alpha/beta/stable)
    3. Get base template
    4. Override with version-specific data if available

    Args:
        version (str): Version string (e.g., '2.2.5-alpha')

    Returns:
        dict: Announcement data with keys:
            - announcement_type (str)
            - highlights (list of str, max 3)
            - show_warning (bool)
    """
    # Determine version type
    version_lower = version.lower()
    if 'alpha' in version_lower:
        version_type = 'alpha'
    elif 'beta' in version_lower:
        version_type = 'beta'
    else:
        version_type = 'stable'

    # Start with template
    data = TEMPLATES[version_type].copy()

    # Override with version-specific data if available
    if version in VERSION_ANNOUNCEMENTS:
        version_specific = VERSION_ANNOUNCEMENTS[version]
        data.update(version_specific)

    # Ensure highlights is max 3 items
    if 'highlights' in data:
        data['highlights'] = data['highlights'][:3]

    return data


def get_all_versions():
    """
    Get list of all versions with custom announcements.
    Useful for testing or documentation.

    Returns:
        list: List of version strings
    """
    return list(VERSION_ANNOUNCEMENTS.keys())


def add_version_to_announcement_type(announcement_type, version):
    """
    Helper to add version number to announcement type if not already present.

    Example: '** NEW VERSION **' + '2.3.0' -> '** NEW VERSION 2.3.0 **'

    Args:
        announcement_type (str): Original announcement type
        version (str): Version string

    Returns:
        str: Enhanced announcement type
    """
    # Check if version is already in announcement_type
    if version in announcement_type:
        return announcement_type

    # Insert version before closing markers
    if announcement_type.endswith('**'):
        return announcement_type[:-2] + ' ' + version + ' **'
    elif announcement_type.endswith('<<'):
        return announcement_type[:-2] + ' ' + version + ' <<'
    else:
        return f"{announcement_type} {version}"
