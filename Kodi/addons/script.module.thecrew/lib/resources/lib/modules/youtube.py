# -*- coding: utf-8 -*-
'''
***********************************************************
*
* @file youtube.py
* @package script.module.thecrew
*
* @author The Crew (based on Genesis by lambda)
* @copyright 2019 The Crew
*
* @license GNU General Public License, version 3 (GPL-3.0)
*
* @description YouTube API integration for playlists and videos
*
********************************************************cm*
'''

import re
import simplejson as json

from resources.lib.modules import client
from resources.lib.modules import workers


class youtube:
    def __init__(self, key=''):
        self.list = []
        self.data = []
        self.base_link = 'https://www.youtube.com'
        self.key_link = f'&key={key}'
        self.playlists_link = 'https://www.googleapis.com/youtube/v3/playlists?part=snippet&maxResults=50&channelId='
        self.playlist_link = 'https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=50&playlistId='
        self.videos_link = 'https://www.googleapis.com/youtube/v3/search?part=snippet&order=date&maxResults=50&channelId='
        self.content_link = 'https://www.googleapis.com/youtube/v3/videos?part=contentDetails&id='
        self.play_link = 'plugin://plugin.video.youtube/play/?video_id='

    def playlists(self, url):
        url = self.playlists_link + url + self.key_link
        return self.play_list(url)

    def playlist(self, url, pagination=False):
        cid = url.split('&')[0]
        url = self.playlist_link + url + self.key_link
        return self.video_list(cid, url, pagination)

    def videos(self, url, pagination=False):
        cid = url.split('&')[0]
        url = self.videos_link + url + self.key_link
        return self.video_list(cid, url, pagination)

    def play_list(self, url):
        items = []
        try:
            result = client.request(url)
            result = json.loads(result)
            items = result.get('items', [])
        except Exception:
            return self.list

        # Fetch up to 4 additional pages
        for i in range(1, 5):
            try:
                if 'nextPageToken' not in result:
                    break
                next_url = f"{url}&pageToken={result['nextPageToken']}"
                result = client.request(next_url)
                result = json.loads(result)
                items += result.get('items', [])
            except Exception:
                pass

        for item in items:
            try:
                title = str(item['snippet']['title'])
                url = str(item['id'])
                image = item['snippet']['thumbnails']['high']['url']

                # Skip default images
                if '/default.jpg' in image:
                    continue

                image = str(image)
                self.list.append({'title': title, 'url': url, 'image': image})
            except Exception:
                pass

        return self.list

    def video_list(self, cid, url, pagination):
        items = []
        try:
            result = client.request(url)
            result = json.loads(result)
            items = result.get('items', [])
        except Exception:
            return self.list

        # Fetch up to 4 additional pages (unless pagination is enabled)
        for i in range(1, 5):
            try:
                if pagination:
                    break
                if 'nextPageToken' not in result:
                    break
                page_url = f"{url}&pageToken={result['nextPageToken']}"
                result = client.request(page_url)
                result = json.loads(result)
                items += result.get('items', [])
            except Exception:
                pass

        # Get next page token for pagination
        next_token = ''
        try:
            if pagination and 'nextPageToken' in result:
                next_token = f"{cid}&pageToken={result['nextPageToken']}"
        except Exception:
            pass

        for item in items:
            try:
                title = str(item['snippet']['title'])

                # Try different locations for video ID
                try:
                    url = item['snippet']['resourceId']['videoId']
                except Exception:
                    url = item['id']['videoId']
                url = str(url)

                image = item['snippet']['thumbnails']['high']['url']

                # Skip default images
                if '/default.jpg' in image:
                    continue

                image = str(image)

                append = {'title': title, 'url': url, 'image': image}
                if next_token:
                    append['next'] = next_token
                self.list.append(append)
            except Exception:
                pass

        # Fetch video durations
        try:
            # Split list into chunks of 50 (API limit)
            list_len = len(self.list)
            chunk_indices = [list(range(list_len))[i:i+50] for i in range(0, list_len, 50)]
            video_id_chunks = [','.join([self.list[x]['url'] for x in chunk]) for chunk in chunk_indices]
            api_urls = [f"{self.content_link}{ids}{self.key_link}" for ids in video_id_chunks]

            # Fetch durations in parallel
            threads = []
            for i, api_url in enumerate(api_urls):
                threads.append(workers.Thread(self.thread, api_url, i))
                self.data.append('')

            [thread.start() for thread in threads]
            [thread.join() for thread in threads]

            # Parse duration data
            items = []
            for data in self.data:
                try:
                    result = json.loads(data)
                    items += result.get('items', [])
                except Exception:
                    pass

            # Add durations to list
            for item in items:
                try:
                    video_id = item['id']
                    duration_str = item['contentDetails']['duration']

                    # Parse ISO 8601 duration (e.g., "PT1H23M45S")
                    duration = 0
                    try:
                        duration += 3600 * int(re.findall(r'(\d+)H', duration_str)[0])
                    except Exception:
                        pass
                    try:
                        duration += 60 * int(re.findall(r'(\d+)M', duration_str)[0])
                    except Exception:
                        pass
                    try:
                        duration += int(re.findall(r'(\d+)S', duration_str)[0])
                    except Exception:
                        pass

                    # Find matching video in list and add duration
                    for list_item in self.list:
                        if list_item['url'] == video_id:
                            list_item['duration'] = str(duration)
                            break
                except Exception:
                    pass
        except Exception:
            pass

        return self.list

    def thread(self, url, i):
        """Worker thread to fetch API data in parallel"""
        try:
            result = client.request(url)
            self.data[i] = result
        except Exception:
            return
