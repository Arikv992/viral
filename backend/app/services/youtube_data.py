"""YouTube Data API v3 (só leitura, com API key) + autocomplete público do YouTube.

Quota diária grátis: 10.000 unidades. search.list = 100, videos/channels.list = 1, commentThreads = 1.
Por isso o radar usa search com parcimónia e compensa com fontes grátis.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..config import get_settings
from .http import get_json

API = "https://www.googleapis.com/youtube/v3"


def _key() -> str:
    return get_settings().youtube_api_key


def enabled() -> bool:
    return bool(_key())


def parse_duration(iso: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def hours_since(iso: str) -> float:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return max((datetime.now(timezone.utc) - t).total_seconds() / 3600, 1.0)


def autocomplete(q: str, lang: str = "en", geo: str = "US") -> list[str]:
    """Sugestões reais de pesquisa do YouTube (grátis, sem quota)."""
    data = get_json("https://suggestqueries.google.com/complete/search",
                    {"client": "firefox", "ds": "yt", "q": q, "hl": lang, "gl": geo}, ttl=6 * 3600)
    if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
        return [s for s in data[1] if isinstance(s, str)]
    return []


def autocomplete_harvest(seed: str, lang: str = "en", geo: str = "US", deep: bool = True) -> list[str]:
    """'Alphabet soup' + prefixos de pergunta: mapeia o que o público realmente procura."""
    out: list[str] = []
    seen: set[str] = set()
    probes = [seed] + [f"{w} {seed}" for w in ("why", "how", "what", "what if")]
    if deep:
        probes += [f"{seed} {c}" for c in "abcdefghijklmnoprstw"]
    for p in probes:
        for s in autocomplete(p, lang, geo):
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def videos(ids: list[str]) -> list[dict]:
    if not enabled() or not ids:
        return []
    out = []
    for i in range(0, len(ids), 50):
        data = get_json(f"{API}/videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(ids[i:i + 50]),
                                          "key": _key()}, ttl=3600)
        out += (data or {}).get("items", [])
    return out


def channels(ids: list[str]) -> dict[str, dict]:
    if not enabled() or not ids:
        return {}
    out = {}
    uniq = list(dict.fromkeys(ids))
    for i in range(0, len(uniq), 50):
        data = get_json(f"{API}/channels", {"part": "snippet,statistics", "id": ",".join(uniq[i:i + 50]),
                                            "key": _key()}, ttl=6 * 3600)
        for it in (data or {}).get("items", []):
            out[it["id"]] = it
    return out


def most_popular(geo: str = "US", category_id: str | None = None, max_results: int = 50) -> list[dict]:
    if not enabled():
        return []
    p = {"part": "snippet,statistics,contentDetails", "chart": "mostPopular", "regionCode": geo,
         "maxResults": max_results, "key": _key()}
    if category_id:
        p["videoCategoryId"] = category_id
    return (get_json(f"{API}/videos", p, ttl=3600) or {}).get("items", [])


def search_recent(q: str, geo: str = "US", lang: str = "en", days: int = 14, max_results: int = 25,
                  duration: str | None = None, license_cc: bool = False) -> list[dict]:
    """search.list (100 unidades!) + videos.list para estatísticas."""
    if not enabled():
        return []
    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    p = {"part": "snippet", "q": q, "type": "video", "order": "viewCount", "publishedAfter": after,
         "regionCode": geo, "relevanceLanguage": lang, "maxResults": max_results, "key": _key()}
    if duration:
        p["videoDuration"] = duration  # short (<4min) | medium | long (>20min)
    if license_cc:
        p["videoLicense"] = "creativeCommon"
    data = get_json(f"{API}/search", p, ttl=6 * 3600) or {}
    ids = [it["id"]["videoId"] for it in data.get("items", []) if it.get("id", {}).get("videoId")]
    return videos(ids)


def enrich_outliers(items: list[dict]) -> list[dict]:
    """Views/hora e rácio views/subscritores. Rácio alto = o TEMA puxou as views, não o canal."""
    chans = channels([it["snippet"]["channelId"] for it in items])
    out = []
    for it in items:
        st = it.get("statistics", {})
        views = int(st.get("viewCount", 0))
        ch = chans.get(it["snippet"]["channelId"], {})
        subs = int(ch.get("statistics", {}).get("subscriberCount", 0) or 0)
        age_h = hours_since(it["snippet"]["publishedAt"])
        dur = parse_duration(it.get("contentDetails", {}).get("duration", ""))
        out.append({
            "video_id": it["id"], "title": it["snippet"]["title"], "channel": it["snippet"]["channelTitle"],
            "channel_id": it["snippet"]["channelId"], "views": views, "subs": subs,
            "likes": int(st.get("likeCount", 0) or 0), "comments": int(st.get("commentCount", 0) or 0),
            "age_hours": round(age_h, 1), "views_per_hour": round(views / age_h, 1),
            "outlier_ratio": round(views / max(subs, 1000), 2), "duration_s": dur, "is_short": dur <= 60,
            "published_at": it["snippet"]["publishedAt"],
            "url": f"https://www.youtube.com/watch?v={it['id']}",
            "thumbnail": it["snippet"].get("thumbnails", {}).get("high", {}).get("url", ""),
        })
    return out


def top_comments(video_id: str, max_results: int = 50) -> list[str]:
    if not enabled():
        return []
    data = get_json(f"{API}/commentThreads", {"part": "snippet", "videoId": video_id, "order": "relevance",
                                              "maxResults": max_results, "textFormat": "plainText",
                                              "key": _key()}, ttl=12 * 3600) or {}
    return [it["snippet"]["topLevelComment"]["snippet"]["textDisplay"][:300] for it in data.get("items", [])]


def handle_available(handle: str) -> bool | None:
    """True se @handle parece livre (sem página). None se não foi possível verificar."""
    from .http import client

    try:
        r = client().get(f"https://www.youtube.com/@{handle}", timeout=10.0)
    except Exception:  # noqa: BLE001
        return None
    if r.status_code == 404:
        return True
    if r.status_code == 200:
        return False
    return None
