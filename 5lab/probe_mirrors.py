# Перевіряє дзеркала Overpass: маленький запит + реальний запит пам'яток у центрі Харкова.
import time, requests
from concurrent.futures import ThreadPoolExecutor

UA = 'LvivPolytechnic-SK26-coursework/1.0 (https://lpnu.ua; student lab assignment)'
MIRRORS = [
    'https://overpass-api.de/api',
    'https://lz4.overpass-api.de/api',
    'https://z.overpass-api.de/api',
    'https://overpass.private.coffee/api',
    'https://overpass.kumi.systems/api',
    'https://overpass.osm.jp/api',
]
SMALL = '[out:json][timeout:20];node(49.99,36.23,49.991,36.231);out count;'
REAL = ('[out:json][timeout:60];(nwr["historic"](49.98,36.20,50.01,36.26);'
        'nwr["tourism"="museum"](49.98,36.20,50.01,36.26););out count;')


def ask(base, q, t):
    t0 = time.time()
    try:
        r = requests.post(base + '/interpreter', data={'data': q},
                          headers={'User-Agent': UA}, timeout=t)
        ok = r.status_code == 200 and r.text.lstrip().startswith('{')
        return ('OK' if ok else 'HTTP %d' % r.status_code), time.time() - t0
    except Exception as e:
        return type(e).__name__, time.time() - t0


def probe(base):
    s, ts = ask(base, SMALL, 30)
    r, tr = ask(base, REAL, 90) if s == 'OK' else ('-', 0)
    return base, s, ts, r, tr


with ThreadPoolExecutor(len(MIRRORS)) as ex:
    for base, s, ts, r, tr in ex.map(probe, MIRRORS):
        print('%-40s малий: %-18s %5.1f c | пам\'ятки: %-18s %5.1f c' % (base, s, ts, r, tr))
