# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file metacache.py
* @package script.module.thecrew
*
* @copyright (c) 2025, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''


import time
import json
import sqlite3 as database



from . import control
from .crewruntime import c

CACHE_VERSION = 1  # Increment when cache schema changes
DEFAULT_TTL_HOURS = 720  # 30 days default


def get_content_ttl(item_data):
    """
    Calculate dynamic TTL based on content metadata.

    Args:
        item_data: Dict with show/movie metadata

    Returns:
        int: TTL in hours
    """
    try:
        status = item_data.get('status', '').lower()

        # Airing shows: 6 hours
        if status in ['returning series', 'in production', 'continuing']:
            return 6

        # Ended shows: 30 days
        elif status in ['ended', 'canceled', 'cancelled']:
            return 720

        # Check release date for movies
        premiered = item_data.get('premiered') or item_data.get('year')
        if premiered:
            try:
                import datetime
                if len(str(premiered)) == 4:  # Year only
                    year = int(premiered)
                    current_year = datetime.datetime.now().year
                    if current_year - year < 1:
                        return 6  # Recent: 6 hours
                    else:
                        return 720  # Old: 30 days
                else:  # Full date
                    release_date = datetime.datetime.strptime(str(premiered)[:10], '%Y-%m-%d')
                    days_old = (datetime.datetime.now() - release_date).days
                    if days_old < 365:
                        return 6
                    else:
                        return 720
            except:
                pass

        # Default
        return DEFAULT_TTL_HOURS
    except:
        return DEFAULT_TTL_HOURS


def fetch(items, lang='en', user=''):
    try:
        t2 = int(time.time())
        dbcon = database.connect(control.metacacheFile)
        dbcur = dbcon.cursor()
    except:
        return items

    for item in items:
        try:

            sql = f"""SELECT * FROM meta WHERE (
                                    imdb = '{item['imdb']}' and lang = '{lang}' and user = '{user}' and not imdb = '0'
                                ) or (
                                    tmdb = '{item['tmdb']}' and lang = '{lang}' and user = '{user}' and not tmdb = '0'
                                )
                        """
            dbcur.execute(sql)
            match = dbcur.fetchone()

            t1 = int(match[6])

            # Dynamic TTL based on content status
            item_data = json.loads(c.to_str(match[5]))
            ttl_hours = get_content_ttl(item_data)

            update = (abs(t2 - t1) / 3600) >= ttl_hours
            if update is True:
                raise Exception()

            # item_data = eval(c.to_str(match[5]))

            item_data = dict((k,v) for k, v in item_data.items() if not v == '0')

            item.update(item_data)
            item.update({'metacache': True})
        except Exception as e:
            pass

    return items


def insert(meta):
    try:
        control.makeFile(control.dataPath)
        dbcon = database.connect(control.metacacheFile)
        dbcur = dbcon.cursor()
        dbcur.execute("""
                                CREATE TABLE IF NOT EXISTS meta (
                                    imdb TEXT, tmdb TEXT, tvdb TEXT, lang TEXT, user TEXT, item TEXT, time TEXT,
                                    UNIQUE(imdb, tmdb, tvdb, user, lang)
                                    );
                        """)
        t = int(time.time())
        for m in meta:
            try:
                if "user" not in m:
                    m["user"] = ''
                if "lang" not in m:
                    m["lang"] = 'en'
                i = repr(m['item'])
                try:
                    # dbcur.execute("DELETE * FROM meta WHERE (imdb = '%s' and lang = '%s' and user = '%s' and not imdb = '0') or \
                    #                                         (tvdb = '%s' and lang = '%s' and user = '%s' and not tvdb = '0' or \
                    #                                         (tmdb = '%s' and lang = '%s' and user = '%s' and not tmdb = '0'))" % \
                    #                                         (m['imdb'], m['lang'], m['user'], m['tvdb'], m['lang'], m['user'], m['tmdb'], m['lang'], m['user']))


                    dbcur.execute("""
                                        DELETE FROM meta
                                        WHERE (imdb = ? AND lang = ? AND user = ? AND imdb != '0')
                                        OR (tvdb = ? AND lang = ? AND user = ? AND tvdb != '0')
                                        OR (tmdb = ? AND lang = ? AND user = ? AND tmdb != '0')
                                    """, (
                                        m['imdb'], m['lang'], m['user'],
                                        m['tvdb'], m['lang'], m['user'],
                                        m['tmdb'], m['lang'], m['user']
                                    ))
                except:
                    pass
                dbcur.execute("""
                                        INSERT OR REPLACE INTO meta Values (?, ?, ?, ?, ?, ?, ?)""",
                                        (
                                        m['imdb'], m['tmdb'], m['tvdb'], m['lang'], m['user'], i, t
                                        ))
            except:
                pass

        dbcon.commit()
    except:
        return


def local(items, link, poster, fanart):
    try:
        dbcon = database.connect(control.metaFile())
        dbcur = dbcon.cursor()
        # args = [i['imdb'] for i in items]
        # dbcur.execute('SELECT * FROM mv WHERE imdb IN (%s)'  % ', '.join(list(map(lambda arg:  "'%s'" % arg, args))))

        args = [i['imdb'] for i in items]
        placeholders = ', '.join(['?'] * len(args))
        # dbcur.execute('SELECT * FROM mv WHERE imdb IN (%s)' % placeholders, args)
        dbcur.execute(f'SELECT * FROM mv WHERE imdb IN ({placeholders})', args)
        data = dbcur.fetchall()
    except:
        return items

    for item in items:
        try:
            match = [x for x in data if x[1] == item['imdb']][0]

            try:
                if poster in item and item[poster] != '0':
                    raise Exception()
                if match[2] == '0':
                    raise Exception()
                # item.update({poster: link % ('300', '/%s.jpg' % match[2])})
                item.update({poster: f'{link}300/{match[2]}.jpg'})
            except:
                pass
            try:
                if fanart in item and item[fanart] != '0':
                    raise Exception()
                if match[3] == '0':
                    raise Exception()
                item.update({fanart: f'{link}1280/{match[3]}.jpg'})
            except:
                pass
        except:
            pass

    return items