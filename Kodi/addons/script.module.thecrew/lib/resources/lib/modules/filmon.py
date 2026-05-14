# -*- coding: utf-8 -*-
'''
 ***********************************************************
 * The Crew Add-on
 *
 * @file filmon.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2023-2026, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
FilmOn.com streaming URL resolver for VOD and live TV channels.
'''
import re
from typing import Optional
import json
from resources.lib.modules import client

def resolve(url: str) -> Optional[str]:
    """Resolve FilmOn.com URL to direct M3U8 stream URL."""
    try:
        # Normalize URL format
        if '/vod/' in url:
            video_id = re.compile(r'/(\d+)').findall(url)[-1]
            api_url = f'https://www.filmon.com/vod/info/{video_id}'
        elif '/tv/' in url:
            api_url = url.replace('/tv/', '/channel/')
        elif '/channel/' not in url:
            raise ValueError('Invalid FilmOn URL format')
        else:
            api_url = url

        headers = {'X-Requested-With': 'XMLHttpRequest'}

        cookie = client.request(api_url, output='cookie')

        channel_response = client.request(api_url, headers=headers)
        channel_id = json.loads(channel_response)['id']

        headers = {'X-Requested-With': 'XMLHttpRequest', 'Referer': api_url}

        info_url = f'https://www.filmon.com/ajax/getChannelInfo?channel_id={channel_id}'

        result = client.request(info_url, cookie=cookie, headers=headers)

        channel_info = json.loads(result)
        try:
            streams = channel_info['streams']
        except (KeyError, TypeError):
            streams = channel_info['data']['streams']
            streams = [stream_data[1] for stream_data in streams.items()]

        # Extract stream URLs with timeout values, then filter for M3U8 streams
        stream_tuples = [(stream['url'], int(stream['watch-timeout'])) for stream in streams]
        m3u8_streams = [stream_tuple for stream_tuple in stream_tuples if '.m3u8' in stream_tuple[0]]

        # Sort and get the highest quality stream (last in sorted list)
        m3u8_streams.sort()
        stream_url = m3u8_streams[-1][0]

        return stream_url
    except Exception:
        return None
