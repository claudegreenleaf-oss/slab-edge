"""HTTP session that sends every request through the scotus-vps SOCKS tunnel."""
import os
import random
import time

from curl_cffi import requests

PROXY = os.environ.get("CARDARB_PROXY", "socks5h://127.0.0.1:1088")
_last = {}


class Blocked(Exception):
    pass


def session():
    s = requests.Session(impersonate="chrome", proxies={"http": PROXY, "https": PROXY})
    s.timeout = 30
    return s


def polite(host, gap):
    """Wait so requests to one host are at least `gap` seconds apart (with jitter)."""
    wait = _last.get(host, 0) + gap * random.uniform(0.8, 1.4) - time.time()
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.time()


def get(s, url, host, gap=2.5, tries=3):
    for i in range(tries):
        polite(host, gap)
        try:
            r = s.get(url, timeout=30)
        except Exception:
            time.sleep(5 * (i + 1))
            continue
        if r.status_code == 200 and "Just a moment" not in r.text[:5000]:
            return r
        if r.status_code in (403, 429):
            time.sleep(30 * (i + 1))
            continue
        if r.status_code == 404:
            return None
    raise Blocked(f"{host} refused {url}")
