import requests
from caches.main_cache import cache_object
from caches.meta_cache import cache_function
from modules import kodi_utils, settings, utils

EXPIRES_1_HOURS = 1
base_url = 'https://api.mdblist.com'
review_provider_id = {1: 'Trakt', 2: 'TMDb', 3: 'RT', 4: 'Metacritics'}
timeout = 3.05
session = requests.Session()
retry = requests.adapters.Retry(total=None, status=1, status_forcelist=(429, 502, 503, 504))
session.mount(base_url, requests.adapters.HTTPAdapter(pool_maxsize=100, max_retries=retry))

def call_mdblist(path, params=None, json=None, method=None):
	params = params or {}
	params['apikey'] = kodi_utils.get_setting('mdblist.token')
	try:
		response = session.request(
			method or 'get',
			path,
			params=params,
			json=json,
			timeout=timeout
		)
		response.raise_for_status()
	except requests.exceptions.RequestException as e: kodi_utils.logger('mdblist error',
		f"{e}\n{e.response.text if response else e.request.url}")
	try: result = response.json()
	except: result = []
	return result

def mdb_searchlists(query):
	query = requests.utils.quote(query)
	string = 'mdb_searchlists_%s' % query
	url = '%s/lists/search?query=%s' % (base_url, query)
	return cache_object(call_mdblist, string, url, False, EXPIRES_1_HOURS)

def mdb_userlists():
	string = 'mdb_userlists'
	url = '%s/lists/user' % base_url
	return cache_object(call_mdblist, string, url, False, EXPIRES_1_HOURS)

def mdb_toplists():
	string = 'mdb_toplists'
	url = '%s/lists/top' % base_url
	return cache_object(call_mdblist, string, url, False)

def mdb_media_info(imdb_id, media_type):
	if not kodi_utils.get_setting('mdblist.token'): return
	media_type = 'show' if media_type == 'tvshow' else 'movie'
	string = 'mdb_%s_id_%s' % (media_type, imdb_id)
	url = '%s/%s/%s/%s?append_to_response=review' % (base_url, 'imdb', media_type, imdb_id)
	return cache_function(call_mdblist, string, url, json=False)

def mdb_list_items(list_id, list_type):
	sort_index = settings.lists_sort_order('mdblist')
	ignore_articles = settings.ignore_articles()
	if list_type: params = (
			{'sort': 'title', 'order': 'asc'},
			{'sort': 'added', 'order': 'desc'},
			{'sort': 'released', 'order': 'desc'},
			{'sort': 'random'}, {'sort': 'usort'}
		)[sort_index]
	else: params = None
	url = '%s/lists/%s/items?unified=true' % (base_url, list_id)
	results = call_mdblist(url, params=params)
	if list_type and ignore_articles and not sort_index:
		results.sort(key=lambda k: utils.title_key(k['title'], ignore_articles), reverse=False)
	return results

def mdb_modify_list(list_id, data, action='add'):
	url = '%s/lists/%s/items/%s' % (base_url, list_id, action)
	results = call_mdblist(url, json=data, method='post')
	if 'detail' in results: kodi_utils.notification(results['detail'])
	if 'added' in results and any(results['added'][i] for i in ('movies', 'shows')): return True
	else: return False

def mdb_clean_watchlist():
	if not kodi_utils.get_setting('mdblist.token'): return
	if not kodi_utils.confirm_dialog(): return
	try:
		from caches.watched_cache import get_watched_items, get_in_progress_tvshows
		m = get_watched_items('movie', 1, 'None', False)
		t = get_watched_items('tvshow', 1, 'None', False)
		p = get_in_progress_tvshows('tvshow', 1, 'None', False)
		data = {
			'movies': [{'tmdb': int(i['media_id'])} for i in m[0]],
			'shows': [{'tmdb': int(i['media_id'])} for i in t[0] + p[0]]
		}
		if not data['movies'] or not data['shows']: return
		u = mdb_userlists()
		list_id = next((i['id'] for i in u if i['slug'] == 'watchlist'), None)
		if not list_id: return
		url = '%s/lists/%s/items/%s' % (base_url, list_id, 'remove')
		call_mdblist(url, json=data, method='post')
	except: pass

