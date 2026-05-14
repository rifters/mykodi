# -*- coding: utf-8 -*-

'''
 ***********************************************************
 * The Crew Add-on
 *
 *
 * @file views.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2024, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

import sqlite3 as database



from . import control
from .crewruntime import c

sql_add = 'CREATE TABLE IF NOT EXISTS views (skin TEXT, view_type TEXT, view_id TEXT, UNIQUE(skin, view_type));'


def table_exists() -> bool:
    '''
    Check if the views table exists in the views database

    Returns:
        bool: Whether the views table exists
    '''
    with database.connect(control.viewsFile) as dbconn:
        dbcur = dbconn.cursor()
        dbcur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='views'")
        return bool(dbcur.fetchone())

def add_view(content) -> None:
    """
    Add or update the view configuration for the given content type.

    This function retrieves the current skin and view ID, constructs a record,
    and ensures the 'views' table exists. It then deletes any existing record
    for the skin and content type and inserts the new record. Finally, it
    displays an info dialog with the view name, skin name, and skin icon.

    Args:
        content (str): The type of content to set the view for.
    """

    try:
        skin = control.skin
        view_id = str(control.getCurrentViewId())
        record = (skin, content, view_id)
        control.makeFile(control.dataPath)
        if not table_exists():
            with database.connect(control.viewsFile) as dbcon:
                dbcur = dbcon.cursor()
                dbcur.execute(sql_add)
        with database.connect(control.viewsFile) as dbcon:
            dbcur = dbcon.cursor()
            dbcur.execute(sql_add)
            dbcur.execute("DELETE FROM views WHERE skin = ? AND view_type = ?", (skin, content))
            dbcur.execute("INSERT INTO views VALUES (?, ?, ?)", record)

        view_name = control.infoLabel('Container.Viewmode')
        skin_name = control.addon(skin).getAddonInfo('name')
        skin_icon = control.addon(skin).getAddonInfo('icon')

        control.infoDialog(view_name, heading=skin_name, sound=True, icon=skin_icon)
    except database.Error as e:
        c.log(f"Database error: {e}")
    except Exception as e:
        c.log(f"Error: {e}")



def set_view(content, view_dict=None) -> bool:
    """Set the view type for the given content type.

    Args:
        content (str): The type of content to set the view for.
        view_dict (dict, optional): A dictionary mapping skin names to view
            IDs. Defaults to None.

    Returns:
        bool: Whether the view was successfully set.
    """
    if control.condVisibility(f'Container.Content({content})'):
        try:
            skin = control.skin
            record = (skin, content)
            if not table_exists():
                with database.connect(control.viewsFile) as dbconn:
                    dbcur = dbconn.cursor()
                    dbcur.execute(sql_add)
            with database.connect(control.viewsFile) as dbconn:
                dbcur = dbconn.cursor()
                dbcur.execute('SELECT * FROM views WHERE skin = ? AND view_type = ?', record)
                row = dbcur.fetchone()
                # row may be None if no record exists — handle gracefully
                if row and len(row) > 2 and row[2]:
                    view = row[2]
                    return control.execute(f'Container.SetViewMode({view})')
                else:
                    c.log(f'[views.set_view] No stored view for skin={skin}, content={content}; falling back to view_dict or default')
                    # fall through to view_dict fallback via KeyError
                    raise KeyError
        except KeyError:
            try:
                return control.execute(f'Container.SetViewMode({view_dict[skin]})')
            except KeyError:
                return
    control.sleep(100)
