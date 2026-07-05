"""util.py — helpers HTTP communs (headers navigateur, GET avec retry).
Le réseau est injectable (paramètre `getter`) pour permettre les tests hors-ligne."""
import time
import requests

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
}


def http_get(url, headers=None, timeout=20, retries=1, delay=5, getter=None):
    """GET avec headers navigateur + retry (garde-fou : max `retries` tentatives sup.).
    `getter` par défaut = requests.get ; injectable pour les tests."""
    getter = getter or requests.get
    h = dict(BROWSER_HEADERS)
    if headers:
        h.update(headers)
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return getter(url, headers=h, timeout=timeout)
        except Exception as e:  # réseau/timeout
            last_exc = e
            if attempt < retries:
                time.sleep(delay)
    raise last_exc
