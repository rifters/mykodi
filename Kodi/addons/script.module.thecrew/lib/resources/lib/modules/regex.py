# -*- coding: utf-8 -*-

'''
********************************************************cm*
* The Crew Add-on
*
* @file regex.py
* @package script.module.thecrew
*
* Original code by lambda, modified by The Crew
* Copyright (c) 2015 lambda, (c) 2019-2026 The Crew
*
* @copyright (c) 2026, The Crew
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''


import re
import os
import sys
import traceback
import base64
import xbmc
import xbmcaddon
import xbmcvfs


from resources.lib.modules import client
from resources.lib.modules import control

from .crewruntime import c
from io import BytesIO
from urllib import request as urllib_request
from http import cookiejar as http_cookiejar
from html import parser as html_parser
import html

from urllib.parse import quote_plus, unquote_plus, urlencode, unquote

profile = functions_dir = control.transPath(xbmcaddon.Addon().getAddonInfo('profile'))

from sqlite3 import dbapi2 as database


def fetch(regex):
    """Retrieve regex pattern from SQLite cache."""
    try:
        cacheFile = os.path.join(control.dataPath, 'regex.db')
        dbcon = database.connect(cacheFile)
        dbcur = dbcon.cursor()
        # Python 3 + SQL injection fix: Use parameterized query
        dbcur.execute("SELECT * FROM regex WHERE regex = ?", (regex,))
        result = dbcur.fetchone()
        if result:
            return result[1]
        return None
    except Exception as e:
        c.log(f"[regex.py] fetch() error: {e}")
        return None


def insert(data):
    """Store regex patterns in SQLite cache."""
    try:
        control.makeFile(control.dataPath)
        cacheFile = os.path.join(control.dataPath, 'regex.db')
        dbcon = database.connect(cacheFile)
        dbcur = dbcon.cursor()
        dbcur.execute("CREATE TABLE IF NOT EXISTS regex (""regex TEXT, ""response TEXT, ""UNIQUE(regex)"");")
        for i in data:
            try:
                dbcur.execute("INSERT INTO regex Values (?, ?)", (i['regex'], i['response']))
            except Exception:
                pass
        dbcon.commit()
    except Exception as e:
        c.log(f"[regex.py] insert() error: {e}")
        return


def clear():
    """Clear regex cache database."""
    try:
        cacheFile = os.path.join(control.dataPath, 'regex.db')
        dbcon = database.connect(cacheFile)
        dbcur = dbcon.cursor()
        dbcur.execute("DROP TABLE IF EXISTS regex")
        dbcur.execute("VACUUM")
        dbcon.commit()
    except Exception as e:
        c.log(f"[regex.py] clear() error: {e}")


def resolve(regex):
    """Parse and resolve XML-formatted regex patterns."""
    try:
        vanilla = re.compile('(<regex>.+)', re.MULTILINE | re.DOTALL).findall(regex)[0]
        cddata = re.compile(r'<\!\[CDATA\[(.+?)\]\]>', re.MULTILINE | re.DOTALL).findall(regex)
        for i in cddata:
            regex = regex.replace('<![CDATA['+i+']]>', quote_plus(i))

        regexs = re.compile('(<regex>.+)', re.MULTILINE | re.DOTALL).findall(regex)[0]
        regexs = re.compile('<regex>(.+?)</regex>', re.MULTILINE | re.DOTALL).findall(regexs)
        regexs = [re.compile('<(.+?)>(.*?)</.+?>', re.MULTILINE | re.DOTALL).findall(i) for i in regexs]

        regexs = [dict([(client.replaceHTMLCodes(x[0]), client.replaceHTMLCodes(unquote_plus(x[1]))) for x in i]) for i in regexs]
        regexs = [(i['name'], i) for i in regexs]
        regexs = dict(regexs)

        url = regex.split('<regex>', 1)[0].strip()
        url = client.replaceHTMLCodes(url)
        url = c.to_str(url)

        r = getRegexParsed(regexs, url)

        try:
            ln = ''
            ret = r[1]
            listrepeat = r[2]['listrepeat']
            regexname = r[2]['name']

            for obj in ret:
                try:
                    item = listrepeat
                    for i in list(range(len(obj)+1)):
                        item = item.replace('[%s.param%s]' % (regexname, str(i)), obj[i-1])

                    item2 = vanilla
                    for i in list(range(len(obj)+1)):
                        item2 = item2.replace('[%s.param%s]' % (regexname, str(i)), obj[i-1])

                    item2 = re.compile('(<regex>.+?</regex>)', re.MULTILINE | re.DOTALL).findall(item2)
                    item2 = [x for x in item2 if f'<name>{regexname}</name>' not in x]
                    item2 = ''.join(item2)

                    ln += f'\n<item>{item}\n{item2}</item>\n'
                except Exception:
                    pass

            return ln
        except Exception:
            pass

        if r[1] is True:
            return r[0]
    except Exception as e:
        c.log(f"[regex.py] resolve() error: {e}")
        return None


class NoRedirection(urllib_request.HTTPErrorProcessor):
    """Custom HTTP handler to prevent automatic redirects."""
    def http_response(self, request, response):
        return response
    https_response = http_response


def getRegexParsed(regexs, url,cookieJar=None,forCookieJarOnly=False,recursiveCall=False,cachedPages={}, rawPost=False, cookie_jar_file=None):
    """Parse and execute $doregex[] patterns with HTTP requests, cookies, and JavaScript unpacking."""
    doRegexs = re.compile(r'\$doregex\[([^\]]*)\]').findall(url)
    setresolved=True
    for k in doRegexs:
        if k in regexs:
            m = regexs[k]
            cookieJarParam=False
            if  'cookiejar' in m:
                cookieJarParam=m['cookiejar']
                if  '$doregex' in cookieJarParam:
                    cookieJar=getRegexParsed(regexs, m['cookiejar'],cookieJar,True, True,cachedPages)
                    cookieJarParam=True
                else:
                    cookieJarParam=True
            if cookieJarParam:
                if cookieJar is None:
                    cookie_jar_file=None
                    if 'open[' in m['cookiejar']:
                        cookie_jar_file=m['cookiejar'].split('open[')[1].split(']')[0]
                    cookieJar=getCookieJar(cookie_jar_file)
                    if cookie_jar_file:
                        saveCookieJar(cookieJar,cookie_jar_file)
                elif 'save[' in m['cookiejar']:
                    cookie_jar_file=m['cookiejar'].split('save[')[1].split(']')[0]
                    complete_path=os.path.join(profile,cookie_jar_file)
                    saveCookieJar(cookieJar,cookie_jar_file)

            if  m['page'] and '$doregex' in m['page']:
                pg=getRegexParsed(regexs, m['page'],cookieJar,recursiveCall=True,cachedPages=cachedPages)
                if len(pg)==0:
                    pg='http://regexfailed'
                m['page']=pg

            if 'setcookie' in m and m['setcookie'] and '$doregex' in m['setcookie']:
                m['setcookie']=getRegexParsed(regexs, m['setcookie'],cookieJar,recursiveCall=True,cachedPages=cachedPages)
            if 'appendcookie' in m and m['appendcookie'] and '$doregex' in m['appendcookie']:
                m['appendcookie']=getRegexParsed(regexs, m['appendcookie'],cookieJar,recursiveCall=True,cachedPages=cachedPages)


            if  'post' in m and '$doregex' in m['post']:
                m['post']=getRegexParsed(regexs, m['post'],cookieJar,recursiveCall=True,cachedPages=cachedPages)

            if  'rawpost' in m and '$doregex' in m['rawpost']:
                m['rawpost']=getRegexParsed(regexs, m['rawpost'],cookieJar,recursiveCall=True,cachedPages=cachedPages,rawPost=True)

            if 'rawpost' in m and '$epoctime$' in m['rawpost']:
                m['rawpost']=m['rawpost'].replace('$epoctime$',getEpocTime())

            if 'rawpost' in m and '$epoctime2$' in m['rawpost']:
                m['rawpost']=m['rawpost'].replace('$epoctime2$',getEpocTime2())


            link=''
            if m['page'] and m['page'] in cachedPages and 'ignorecache' not in m and forCookieJarOnly is False :
                link = cachedPages[m['page']]
            else:
                if m['page'] and not m['page']=='' and m['page'].startswith('http'):
                    if '$epoctime$' in m['page']:
                        m['page'] = m['page'].replace('$epoctime$',getEpocTime())
                    if '$epoctime2$' in m['page']:
                        m['page'] = m['page'].replace('$epoctime2$',getEpocTime2())

                    page_split=m['page'].split('|')
                    pageUrl=page_split[0]
                    header_in_page=None
                    if len(page_split)>1:
                        header_in_page=page_split[1]

                    current_proxies=urllib_request.ProxyHandler(urllib_request.getproxies())
                    req = urllib_request.Request(pageUrl)
                    if 'proxy' in m:
                        proxytouse= m['proxy']
                        if pageUrl[:5]=="https":
                            proxy = urllib_request.ProxyHandler({ 'https' : proxytouse})
                        else:
                            proxy = urllib_request.ProxyHandler({ 'http'  : proxytouse})
                        opener = urllib_request.build_opener(proxy)
                        urllib_request.install_opener(opener)

                    req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 6.1; rv:14.0) Gecko/20100101 Firefox/14.0.1')
                    proxytouse=None

                    if 'referer' in m:
                        req.add_header('Referer', m['referer'])
                    if 'accept' in m:
                        req.add_header('Accept', m['accept'])
                    if 'agent' in m:
                        req.add_header('User-agent', m['agent'])
                    if 'x-req' in m:
                        req.add_header('X-Requested-With', m['x-req'])
                    if 'x-addr' in m:
                        req.add_header('x-addr', m['x-addr'])
                    if 'x-forward' in m:
                        req.add_header('X-Forwarded-For', m['x-forward'])
                    if 'setcookie' in m:
                        req.add_header('Cookie', m['setcookie'])
                    if 'appendcookie' in m:
                        cookiestoApend=m['appendcookie']
                        cookiestoApend=cookiestoApend.split(';')
                        for h in cookiestoApend:
                            n,v=h.split('=')
                            w,n= n.split(':')
                            ck = http_cookiejar.Cookie(version=0, name=n, value=v, port=None, port_specified=False, domain=w, domain_specified=False, domain_initial_dot=False, path='/', path_specified=True, secure=False, expires=None, discard=True, comment=None, comment_url=None, rest={'HttpOnly': None}, rfc2109=False)
                            cookieJar.set_cookie(ck)
                    if 'origin' in m:
                        req.add_header('Origin', m['origin'])
                    if header_in_page:
                        header_in_page=header_in_page.split('&')
                        for h in header_in_page:
                            n,v=h.split('=')
                            req.add_header(n,v)

                    if cookieJar is not None:
                        cookie_handler = urllib_request.HTTPCookieProcessor(cookieJar)
                        opener = urllib_request.build_opener(cookie_handler, urllib_request.HTTPBasicAuthHandler(), urllib_request.HTTPHandler())
                        opener = urllib_request.install_opener(opener)

                        if 'noredirect' in m:
                            opener = urllib_request.build_opener(cookie_handler,NoRedirection, urllib_request.HTTPBasicAuthHandler(), urllib_request.HTTPHandler())
                            opener = urllib_request.install_opener(opener)
                    elif 'noredirect' in m:
                        opener = urllib_request.build_opener(NoRedirection, urllib_request.HTTPBasicAuthHandler(), urllib_request.HTTPHandler())
                        opener = urllib_request.install_opener(opener)


                    if 'connection' in m:
                        from keepalive import HTTPHandler
                        keepalive_handler = HTTPHandler()
                        opener = urllib_request.build_opener(keepalive_handler)
                        urllib_request.install_opener(opener)

                    post=None

                    if 'post' in m:
                        postData=m['post']
                        splitpost=postData.split(',')
                        post={}
                        for p in splitpost:
                            n=p.split(':')[0]
                            v=p.split(':')[1]
                            post[n]=v
                        post = urlencode(post)

                    if 'rawpost' in m:
                        post=m['rawpost']
                    link=''
                    try:

                        if post:
                            response = urllib_request.urlopen(req,post)
                        else:
                            response = urllib_request.urlopen(req)
                        if response.info().get('Content-Encoding') == 'gzip':
                            import gzip
                            buf = BytesIO(response.read())
                            f = gzip.GzipFile(fileobj=buf)
                            link = f.read()
                            link = control.six_decode(link)  # Python 3 fix: decode gzip bytes
                        else:
                            link=response.read()
                            link = control.six_decode(link)


                        if 'proxy' in m and current_proxies is not None:
                            urllib_request.install_opener(urllib_request.build_opener(current_proxies))

                        link=javascriptUnEscape(link)
                        if 'includeheaders' in m:
                            link+='$$HEADERS_START$$:'
                            for b in response.headers:
                                link+= b+':'+response.headers.get(b)+'\n'
                            link+='$$HEADERS_END$$:'

                        response.close()
                    except Exception as e:
                        c.log(f"[regex.py] getRegexParsed() HTTP request error: {e}")
                    cachedPages[m['page']] = link

                    if forCookieJarOnly:
                        return cookieJar# do nothing
                elif m['page'] and  not m['page'].startswith('http'):
                    if m['page'].startswith('$pyFunction:'):
                        val=doEval(m['page'].split('$pyFunction:')[1],'',cookieJar,m )
                        if forCookieJarOnly:
                            return cookieJar# do nothing
                        link=val
                        link=javascriptUnEscape(link)
                    else:
                        link=m['page']

            if  '$doregex' in m['expres']:
                m['expres']=getRegexParsed(regexs, m['expres'],cookieJar,recursiveCall=True,cachedPages=cachedPages)

            if not m['expres']=='':
                if '$LiveStreamCaptcha' in m['expres']:
                    c.log("[CM Warning] $LiveStreamCaptcha not supported - askCaptcha undefined")
                    val = ''
                    url = url.replace("$doregex[" + k + "]", val)

                elif m['expres'].startswith('$pyFunction:') or '#$pyFunction' in m['expres']:
                    val=''
                    if m['expres'].startswith('$pyFunction:'):
                        val=doEval(m['expres'].split('$pyFunction:')[1],link,cookieJar,m)
                    else:
                        val=doEvalFunction(m['expres'],link,cookieJar,m)
                    if 'ActivateWindow' in m['expres']:
                        return
                    if forCookieJarOnly:
                        return cookieJar
                    if 'listrepeat' in m:
                        listrepeat=m['listrepeat']
                        if not val:
                            return listrepeat, [], m, regexs, cookieJar
                        return listrepeat, eval(val), m,regexs,cookieJar

                    try:
                        url = url.replace(u"$doregex[" + k + "]", val)
                    except:
                        url = url.replace("$doregex[" + k + "]", control.six_decode(val))
                else:
                    if 'listrepeat' in m:
                        listrepeat=m['listrepeat']
                        ret=re.findall(m['expres'],link)
                        return listrepeat,ret, m,regexs

                    val=''
                    if not link=='':
                        reg = re.compile(m['expres']).search(link)
                        try:
                            val=reg.group(1).strip()
                        except Exception as e:
                            c.log(f"[CM Error] regex.py getRegexParsed() regex match error: {e}")
                            traceback.print_exc()
                    elif m['page']=='' or m['page'] is None:
                        val=m['expres']

                    if rawPost:
                        val=quote_plus(val)
                    if 'htmlunescape' in m:
                        val=html.unescape(val)
                    try:
                        url = url.replace("$doregex[" + k + "]", val)
                    except:
                        url = url.replace("$doregex[" + k + "]", control.six_decode(val))
            else:
                url = url.replace("$doregex[" + k + "]",'')

        if '$epoctime$' in url:
            url=url.replace('$epoctime$',getEpocTime())
        if '$epoctime2$' in url:
            url=url.replace('$epoctime2$',getEpocTime2())

        if '$GUID$' in url:
            import uuid
            url=url.replace('$GUID$',str(uuid.uuid1()).upper())
        if '$get_cookies$' in url:
            url=url.replace('$get_cookies$',getCookiesString(cookieJar))

        if recursiveCall:
            return url
        #print 'final url',repr(url)
        if url=="":
            return
        else:
            return url,setresolved


def get_unwise( str_eval):
    """Unpack obfuscated JavaScript using wise encoding."""
    page_value=""
    try:
        ss="w,i,s,e=("+str_eval+')'
        exec(ss)  # Dynamic variables: w, i, s, e defined at runtime
        # pylint: disable=undefined-variable
        page_value=unwise_func(w,i,s,e)  # noqa: F821 - Variables created by exec()
    except Exception as e:
        c.log(f"[CM Error] get_unwise failed: {e}")
        traceback.print_exc(file=sys.stdout)
    return page_value


def unwise_func( w, i, s, e):
    """Core unwise decoding algorithm."""
    lIll = 0
    ll1I = 0
    Il1l = 0
    ll1l = []
    l1lI = []
    while True:
        if (lIll < 5):
            l1lI.append(w[lIll])
        elif (lIll < len(w)):
            ll1l.append(w[lIll])
        lIll+=1
        if (ll1I < 5):
            l1lI.append(i[ll1I])
        elif (ll1I < len(i)):
            ll1l.append(i[ll1I])
        ll1I+=1
        if (Il1l < 5):
            l1lI.append(s[Il1l])
        elif (Il1l < len(s)):
            ll1l.append(s[Il1l])
        Il1l+=1
        if (len(w) + len(i) + len(s) + len(e) == len(ll1l) + len(l1lI) + len(e)):
            break

    lI1l = ''.join(ll1l)#.join('');
    I1lI = ''.join(l1lI)#.join('');
    ll1I = 0
    l1ll = []
    for lIll in list(range(0,len(ll1l),2)):
        #print 'array i',lIll,len(ll1l)
        ll11 = -1
        if ( ord(I1lI[ll1I]) % 2):
            ll11 = 1
        l1ll.append(chr(int(lI1l[lIll: lIll+2], 36) - ll11))
        ll1I+=1
        if (ll1I >= len(l1lI)):
            ll1I = 0
    ret=''.join(l1ll)
    if 'eval(function(w,i,s,e)' in ret:
        ret=re.compile(r'eval\(function\(w,i,s,e\).*}\((.*?)\)').findall(ret)[0]
        return get_unwise(ret)
    else:
        return ret


def get_unpacked( page_value, regex_for_text='', iterations=1, total_iteration=1):
    """Unpack packed JavaScript, optionally extracting with regex first."""
    try:
        reg_data=None
        if page_value.startswith("http"):
            page_value= getUrl(page_value)
#        print 'page_value',page_value
        if regex_for_text and len(regex_for_text)>0:
            try:
                page_value=re.compile(regex_for_text).findall(page_value)[0] #get the js variable
            except:
                return 'NOTPACKED'

        page_value=unpack(page_value,iterations,total_iteration)
    except:
        page_value='UNPACKEDFAILED'
        traceback.print_exc(file=sys.stdout)
#    print 'unpacked',page_value
    if 'sav1live.tv' in page_value:
        page_value=page_value.replace('sav1live.tv','sawlive.tv') #quick fix some bug somewhere
#        print 'sav1 unpacked',page_value
    return page_value


def unpack(sJavascript,iteration=1, totaliterations=2  ):
#    print 'iteration',iteration
    if sJavascript.startswith('var _0xcb8a='):
        aSplit=sJavascript.split('var _0xcb8a=')
        ss="myarray="+aSplit[1].split("eval(")[0]
        exec(ss)  # Creates myarray dynamically
        # pylint: disable=undefined-variable
        a1=62
        c1=int(aSplit[1].split(",62,")[1].split(',')[0])
        p1=myarray[0]  # noqa: F821 - Variable created by exec()
        k1=myarray[3]  # noqa: F821 - Variable created by exec()
    else:

        if "rn p}('" in sJavascript:
            aSplit = sJavascript.split("rn p}('")
        else:
            aSplit = sJavascript.split("rn A}('")

        p1,a1,c1,k1=('','0','0','')

        ss="p1,a1,c1,k1=('"+aSplit[1].split(".spli")[0]+')'
        exec(ss)
    k1=k1.split('|')
    aSplit = aSplit[1].split("))'")

    e = ''
    d = ''

    sUnpacked1 = str(__unpack(p1, a1, c1, k1, e, d,iteration))

    if iteration>=totaliterations:
        return sUnpacked1
    else:
        return unpack(sUnpacked1,iteration+1)


def __unpack(p, a, c, k, e, d, iteration,v=1):
    """Core unpacking algorithm for packed JavaScript."""
    while (c >= 1):
        c = c -1
        if (k[c]):
            aa=str(__itoaNew(c, a))
            if v==1:
                p=re.sub('\\b' + aa +'\\b', k[c], p)
            else:
                p=findAndReplaceWord(p,aa,k[c])
    return p


def __itoa(num, radix):
    """Int to string conversion with custom radix."""
    result = ""
    if num==0:
        return '0'
    while num > 0:
        result = "0123456789abcdefghijklmnopqrstuvwxyz"[num % radix] + result
        num /= radix
    return result


def __itoaNew(cc, a):
    """Optimized base-36 conversion for unpacker."""
    aa="" if cc < a else __itoaNew(int(cc / a),a)
    cc = (cc % a)
    bb=chr(cc + 29) if cc> 35 else str(__itoa(cc,36))
    return aa+bb


def findAndReplaceWord(source_str, word_to_find,replace_with):
    """Replace whole words preserving JavaScript identifier boundaries."""
    splits=None
    splits=source_str.split(word_to_find)
    if len(splits)>1:
        new_string=[]
        current_index=0
        for current_split in splits:
            new_string.append(current_split)
            val=word_to_find
            if current_index==len(splits)-1:
                val=''
            else:
                if len(current_split)==0:
                    if (len(splits[current_index+1])==0 and word_to_find[0].lower() not in 'abcdefghijklmnopqrstuvwxyz1234567890_') or (len(splits[current_index+1])>0  and splits[current_index+1][0].lower() not in 'abcdefghijklmnopqrstuvwxyz1234567890_'):
                        val=replace_with
                else:
                    if (splits[current_index][-1].lower() not in 'abcdefghijklmnopqrstuvwxyz1234567890_') and (( len(splits[current_index+1])==0 and word_to_find[0].lower() not in 'abcdefghijklmnopqrstuvwxyz1234567890_') or (len(splits[current_index+1])>0  and splits[current_index+1][0].lower() not in 'abcdefghijklmnopqrstuvwxyz1234567890_')):
                        val=replace_with

            new_string.append(val)
            current_index+=1
        source_str=''.join(new_string)
    return source_str


def re_me(data, re_patten):
    """Extract first regex match group or return empty string."""
    match = ''
    m = re.search(re_patten, data)
    if m is not None:
        match = m.group(1)
    else:
        match = ''
    return match


def getCookiesString(cookieJar):
    """Convert cookie jar to string format."""
    try:
        cookieString=""
        for index, cookie in enumerate(cookieJar):
            cookieString+=cookie.name + "=" + cookie.value +";"
    except Exception as e:
        c.log(f"[regex.py] getCookiesString() error: {e}")
    return cookieString


def saveCookieJar(cookieJar,COOKIEFILE):
    """Persist cookie jar to file in profile directory."""
    try:
        complete_path=os.path.join(profile,COOKIEFILE)
        cookieJar.save(complete_path,ignore_discard=True)
    except Exception as e:
        c.log(f"[regex.py] saveCookieJar() error: {e}")


def getCookieJar(COOKIEFILE):
    """Load cookie jar from file or create new one."""
    cookieJar=None
    if COOKIEFILE:
        try:
            complete_path=os.path.join(profile,COOKIEFILE)
            cookieJar = http_cookiejar.LWPCookieJar()
            cookieJar.load(complete_path,ignore_discard=True)
        except:
            cookieJar=None

    if not cookieJar:
        cookieJar = http_cookiejar.LWPCookieJar()

    return cookieJar


def doEval(fun_call,page_data,Cookie_Jar,m):
    """Execute Python code from regex $pyFunction directive."""
    ret_val = ''
    if functions_dir not in sys.path:
        sys.path.append(functions_dir)

    try:
        py_file='import '+fun_call.split('.')[0]
        exec(py_file)
    except:
        traceback.print_exc(file=sys.stdout)

    exec('ret_val='+fun_call)  # pylint: disable=exec-used

    try:
        return str(ret_val)  # noqa: F821 - ret_val reassigned by exec()
    except:
        return ret_val  # noqa: F821 - ret_val reassigned by exec()



def doEvalFunction(fun_call,page_data,Cookie_Jar,m):
    """Execute dynamic Python code from file (used for adult/LSPro resolvers)."""
    ret_val=''
    if functions_dir not in sys.path:
        sys.path.append(functions_dir)

    dynamic_code_path = os.path.join(functions_dir, "LSProdynamicCode.py")

    try:
        with open(dynamic_code_path, "w", encoding='utf-8') as f:
            f.write(fun_call)

        try:
            import LSProdynamicCode
        except Exception as _e:
            c.log(f"[regex.py] LSProdynamic import failed: {_e}")
            raise

        try:
            control.busy()
            try:
                ret_val=LSProdynamicCode.GetLSProData(page_data,Cookie_Jar,m)
            finally:
                control.idle()

            if ret_val is None:
                c.log("[regex.py] pyFunction returned None - resolver failed or user cancelled")
        except Exception as _e:
            c.log(f"[regex.py] LSProdynamic execution failed: {_e}")
            raise

        try:
            return str(ret_val) if ret_val is not None else ''
        except:
            return ret_val if ret_val is not None else ''

    finally:
        try:
            if os.path.exists(dynamic_code_path):
                os.remove(dynamic_code_path)
            pyc_path = dynamic_code_path + 'c'
            if os.path.exists(pyc_path):
                os.remove(pyc_path)
            if 'LSProdynamicCode' in sys.modules:
                del sys.modules['LSProdynamicCode']
        except Exception as cleanup_e:
            c.log(f"[regex.py] Cleanup error: {cleanup_e}")


def getUrl(url, cookieJar=None,post=None, timeout=20, headers=None, noredir=False):
    """Perform HTTP request with cookie jar and custom headers."""
    cookie_handler = urllib_request.HTTPCookieProcessor(cookieJar)

    if noredir:
        opener = urllib_request.build_opener(NoRedirection,cookie_handler, urllib_request.HTTPBasicAuthHandler(), urllib_request.HTTPHandler())
    else:
        opener = urllib_request.build_opener(cookie_handler, urllib_request.HTTPBasicAuthHandler(), urllib_request.HTTPHandler())
    req = urllib_request.Request(url)
    req.add_header('User-Agent','Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/33.0.1750.154 Safari/537.36')
    if headers:
        for h,hv in headers:
            req.add_header(h,hv)

    response = opener.open(req,post,timeout=timeout)
    link=response.read()
    response.close()
    return link


def get_decode(str,reg=None):
    """Decode obfuscated string using character offset decoding."""
    if reg:
        str=re.findall(reg, str)[0]
    s1 = unquote(str[0: len(str)-1])
    t = ''
    for i in list(range(len(s1))):
        t += chr(ord(s1[i]) - ord(s1[len(s1)-1]))
    t=unquote(t)
    return t


def javascriptUnEscape(str):
    """Unescape JavaScript escaped strings."""
    js=re.findall(r'unescape\(\'(.*?)\'',str)
#    print 'js',js
    if (not js is None) and len(js)>0:
        for j in js:
            #print unquote(j)
            str=str.replace(j ,unquote(j))
    return str


def getEpocTime():
    import time
    return str(int(time.time()*1000))


def getEpocTime2():
    import time
    return str(int(time.time()))
