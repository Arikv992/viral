"""Cliente HTTP partilhado com cache em memória (poupa quota das APIs)."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

log = logging.getLogger("viral.http")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36 viral-ops/1.0"

_client: httpx.Client | None = None
_cache: dict[str, tuple[float, Any]] = {}


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": UA})
    return _client


def get_json(url: str, params: dict | None = None, ttl: int = 1800, headers: dict | None = None) -> Any | None:
    key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()) if k != "key")
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        r = client().get(url, params=params, headers=headers)
        if r.status_code != 200:
            log.warning("GET %s -> %s %s", url, r.status_code, r.text[:200])
            return None
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("GET %s falhou: %s", url, e)
        return None
    _cache[key] = (time.time(), data)
    return data


def get_text(url: str, params: dict | None = None, ttl: int = 1800) -> str | None:
    key = "T" + url + str(sorted((params or {}).items()))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        r = client().get(url, params=params)
        if r.status_code != 200:
            log.warning("GET %s -> %s", url, r.status_code)
            return None
    except httpx.HTTPError as e:
        log.warning("GET %s falhou: %s", url, e)
        return None
    _cache[key] = (time.time(), r.text)
    return r.text


def download(url: str, dest, headers: dict | None = None) -> bool:
    try:
        with client().stream("GET", url, headers=headers, timeout=120.0) as r:
            if r.status_code != 200:
                return False
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
        return True
    except httpx.HTTPError as e:
        log.warning("download %s falhou: %s", url, e)
        return False
