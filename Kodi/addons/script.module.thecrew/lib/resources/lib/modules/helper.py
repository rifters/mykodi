# -*- coding: utf-8 -*-
'''
***********************************************************
*
* @file helper.py
* @package script.module.thecrew
*
* Created on 2024-03-06.
* Copyright 2024 by The Crew. All rights reserved.
*
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''



import xbmc

from .crewruntime import c

def make_safe(value = "") -> str:
    if isinstance(value, str):
        return value.replace("'", "\'")
    else:
        return str(value).replace("'", "\'")


def handle_cast(cast):
    cast_list = []
    try:
        for actor in cast:
            name = actor.get("name", "")
            role = actor.get("known_for_department", "")
            thumbnail = actor.get("thumbnail", "")
            actor = xbmc.Actor(
                name=name,
                role=role,
                thumbnail=thumbnail
            )
            cast_list.append(actor)
    except BaseException as e:


    return cast_list
