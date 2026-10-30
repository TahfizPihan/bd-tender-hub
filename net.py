"""Shared HTTP helpers."""
import time
from urllib import robotparser
from urllib.parse import urlparse

import requests

UA = "BD-Tender-Hub/0.1 (personal tender index; links back to originals)"
HEADERS = {"User-Agent": UA, "Accept-Language": "en,bn;q=0.8"}


def fetch(url, tries=3, params=None):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            r.raise_for_status()
            if not r.encoding or r.encoding.lower() == "iso-8859-1":
                r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except requests.RequestException as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def robots_allows(url):
    p = urlparse(url)
    rp = robotparser.RobotFileParser()
    try:
        rp.set_url(f"{p.scheme}://{p.netloc}/robots.txt")
        rp.read()
        return rp.can_fetch(UA, url)
    except Exception:
        return True  # no readable robots.txt -> nothing forbids it
