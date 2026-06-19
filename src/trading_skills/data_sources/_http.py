# ABOUTME: Minimal resilient HTTP layer for the fallback data sources.
# ABOUTME: requests-based (not curl_cffi), never raises, with a short TTL cache.

import time
from urllib.parse import urlencode

import requests

DEFAULT_TIMEOUT = 15
DEFAULT_TTL = 900  # 15 minutes, matching the project's data_delay convention
NEGATIVE_TTL = 60  # cache a failure briefly so a down source isn't hammered

_cache: dict[str, tuple[float, object]] = {}


def clear_cache() -> None:
    """Drop all cached responses (used by tests)."""
    _cache.clear()


def _cache_key(url: str, params: dict | None) -> str:
    if not params:
        return url
    return url + "?" + urlencode(sorted(params.items()))


def get_json(
    url: str,
    headers: dict | None = None,
    params: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = 1,
    ttl: int = DEFAULT_TTL,
):
    """GET a JSON document. Returns the parsed object, or None on any failure.

    Never raises: connection errors, non-200 status, and JSON parse errors all
    resolve to None so callers can fall through to the next source.
    """
    key = _cache_key(url, params)
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]  # may be a cached None (negative cache)

    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                _cache[key] = (time.time() + ttl, data)
                return data
        except Exception:
            pass
        if attempt < retries:
            time.sleep(0.4)
    # Negative-cache the failure so the same down source is skipped fast across
    # a multi-symbol run, rather than retried (with sleeps) on every call.
    _cache[key] = (time.time() + NEGATIVE_TTL, None)
    return None
