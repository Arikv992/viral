"""RADAR DE TENDÊNCIAS.

1. Recolha (grátis primeiro): Google Trends RSS, autocomplete YouTube, Reddit top semanal,
   YouTube Data API (vídeos outlier recentes por nicho), séries do Wikipedia.
2. Diagnóstico matemático da série temporal -> momentum, classe de longevidade e dias de vida útil.
3. Score de oportunidade = momentum × longevidade × (1 - saturação) × valor do nicho (RPM).
4. Enriquecimento LLM nos melhores: veredito (ride_now/build_series/evergreen_asset/skip) e ângulos dark.
"""
from __future__ import annotations

import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from sqlmodel import select

from .. import prompts
from ..db import session_scope
from ..knowledge.geo import effective_rpm_mult
from ..knowledge.niches import NICHES, get_niche
from ..llm import INT, S, arr, enum, get_llm, obj
from ..models import Trend, now
from . import youtube_data as yt
from .http import get_json, get_text

# ----------------------------------------------------------------------------- séries temporais


def analyze_series(values: list[float]) -> dict:
    """Classifica a vida de um tema a partir de uma série diária de interesse.

    Devolve momentum (0-100), longevity (flash|wave|evergreen|seasonal), longevity_days e métricas."""
    v = [max(float(x), 0.0) for x in values]
    n = len(v)
    if n < 21 or max(v) <= 0:
        return {"momentum": 0.0, "longevity": "unknown", "longevity_days": 0, "growth": 0.0}
    last7 = statistics.fmean(v[-7:])
    prev = v[-35:-7] if n >= 35 else v[:-7]
    prev28 = statistics.fmean(prev) if prev else last7
    hist = v[:-14]
    baseline = statistics.median(hist) if hist else statistics.median(v)
    peak = max(v)
    peak_idx = v.index(peak)
    mean = statistics.fmean(v)
    cv = statistics.pstdev(v) / mean if mean else 0
    growth = (last7 + 1e-9) / (prev28 + 1e-9)
    # momentum: crescimento recente (log) + posição atual face ao pico
    momentum = 50 + 22 * math.log2(max(min(growth, 16), 1 / 16)) + 15 * (last7 / peak - 0.5)
    momentum = max(0.0, min(100.0, momentum))

    seasonal = False
    if n >= 400:
        wk = [statistics.fmean(v[i:i + 7]) for i in range(0, n - 6, 7)]
        lag = 52
        if len(wk) > lag + 8:
            a, b = wk[:-lag], wk[lag:]
            ma, mb = statistics.fmean(a), statistics.fmean(b)
            cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
            den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) or 1
            seasonal = cov / den > 0.5

    days_since_peak = n - 1 - peak_idx
    ratio_base = baseline / peak if peak else 0
    if seasonal:
        cls, days = "seasonal", 45
    elif ratio_base >= 0.35 and cv < 0.65:
        cls, days = "evergreen", 365
    elif days_since_peak <= 21 and ratio_base < 0.2 and peak > 3 * (baseline + 1e-9):
        # pico recente sobre base baixa: explosão. Estimar decaimento exponencial até 20% do pico.
        cur = statistics.fmean(v[-3:])
        if days_since_peak >= 2 and cur < peak:
            k = -math.log(max(cur, 1e-9) / peak) / days_since_peak
            remaining = math.log(max(cur, 1e-9) / (0.2 * peak)) / k if k > 0 else 7
            days = int(max(1, min(remaining, 21)))
        else:
            days = 7
        cls = "flash"
    else:
        cls = "wave"
        days = int(max(14, min(90, 30 * max(growth, 0.5))))
    return {"momentum": round(momentum, 1), "longevity": cls, "longevity_days": days,
            "growth": round(growth, 2), "cv": round(cv, 2), "baseline_ratio": round(ratio_base, 2),
            "days_since_peak": days_since_peak, "last7": round(last7, 1), "peak": round(peak, 1)}


# ----------------------------------------------------------------------------- fontes


def wikipedia_series(topic: str, lang: str = "en", days: int = 540) -> tuple[str, list[float]]:
    """Mapeia o tema para um artigo e devolve as visualizações diárias (proxy de interesse público)."""
    s = get_json(f"https://{lang}.wikipedia.org/w/api.php",
                 {"action": "opensearch", "search": topic, "limit": 1, "namespace": 0, "format": "json"}, ttl=86400)
    if not s or len(s) < 2 or not s[1]:
        return "", []
    article = s[1][0].replace(" ", "_")
    end = datetime.now(timezone.utc) - timedelta(days=1)
    start = end - timedelta(days=days)
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{lang}.wikipedia/all-access/user/"
           f"{quote(article, safe='')}/daily/{start:%Y%m%d}00/{end:%Y%m%d}00")
    data = get_json(url, ttl=12 * 3600) or {}
    return article, [it["views"] for it in data.get("items", [])]


def google_trending(geo: str = "US") -> list[dict]:
    xml = get_text("https://trends.google.com/trending/rss", {"geo": geo}, ttl=3600)
    if not xml:
        return []
    out = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    ns = {"ht": "https://trends.google.com/trending/rss"}
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        traffic = item.findtext("ht:approx_traffic", default="", namespaces=ns) or ""
        num = int(re.sub(r"[^\d]", "", traffic) or 0)
        news = [n.findtext("ht:news_item_title", default="", namespaces=ns) for n in item.findall("ht:news_item", ns)]
        if title:
            out.append({"topic": title, "traffic": num, "news": [x for x in news if x][:3]})
    return out


def reddit_top(sub: str, limit: int = 10) -> list[dict]:
    data = get_json(f"https://www.reddit.com/r/{sub}/top.json", {"t": "week", "limit": limit}, ttl=6 * 3600)
    out = []
    for ch in (data or {}).get("data", {}).get("children", []):
        d = ch.get("data", {})
        if d.get("over_18"):
            continue
        out.append({"title": d.get("title", ""), "score": d.get("score", 0), "comments": d.get("num_comments", 0),
                    "url": "https://reddit.com" + d.get("permalink", "")})
    return out


# ----------------------------------------------------------------------------- scoring


def match_niche(text: str) -> str:
    t = text.lower()
    best, best_hits = "", 0
    for n in NICHES:
        hits = sum(1 for k in n["keywords"] if any(w in t for w in k.lower().split() if len(w) > 3))
        if hits > best_hits:
            best, best_hits = n["key"], hits
    return best


LONGEVITY_WEIGHT = {"evergreen": 1.0, "seasonal": 0.8, "wave": 0.85, "flash": 0.6, "unknown": 0.55}


def opportunity(momentum: float, longevity: str, saturation: float, niche_key: str, lang: str = "en") -> float:
    niche = get_niche(niche_key)
    rpm = (sum(niche["rpm_long"]) / 2 if niche else 3.0) * effective_rpm_mult(lang)
    value = min(1.0, 0.35 + rpm / 8)  # RPM efetivo de ~5$ ou mais = valor máximo
    score = (0.55 * momentum + 45 * LONGEVITY_WEIGHT.get(longevity, 0.5)) * (1 - 0.6 * saturation / 100) * value
    return round(max(0.0, min(100.0, score)), 1)


def saturation_from_outliers(items: list[dict]) -> float:
    """Muitos vídeos recentes de canais grandes = saturado. Muitos outliers de canais pequenos = oportunidade."""
    if not items:
        return 50.0
    big = sum(1 for i in items if i["subs"] > 500_000)
    small_winners = sum(1 for i in items if i["outlier_ratio"] >= 3)
    return round(max(5.0, min(95.0, 40 + 4 * big - 6 * small_winners + 0.5 * len(items))), 1)


# ----------------------------------------------------------------------------- scan


def scan(niche_keys: list[str] | None = None, geo: str = "US", lang: str = "en", use_llm: bool = True,
         max_candidates: int = 30) -> list[Trend]:
    niche_keys = niche_keys or [n["key"] for n in NICHES[:8]]
    cands: dict[str, dict] = {}

    def add(topic: str, source: str, niche: str, evidence: dict, momentum_hint: float = 0.0):
        topic = re.sub(r"\s+", " ", topic).strip()[:140]
        if len(topic) < 3:
            return
        key = topic.lower()
        c = cands.setdefault(key, {"topic": topic, "sources": set(), "niche": niche, "evidence": {},
                                   "hint": 0.0})
        c["sources"].add(source)
        c["evidence"].setdefault(source, []).append(evidence)
        c["hint"] = max(c["hint"], momentum_hint)
        c["niche"] = c["niche"] or niche

    # 1) Google Trends (explosões do dia)
    for g in google_trending(geo)[:20]:
        niche = match_niche(g["topic"] + " " + " ".join(g["news"]))
        if niche in niche_keys:
            add(g["topic"], "google_trends", niche, g, momentum_hint=min(100, 40 + 10 * math.log10(g["traffic"] + 1)))

    outliers_by_niche: dict[str, list[dict]] = {}
    for key in niche_keys:
        niche = get_niche(key)
        if not niche:
            continue
        # 2) Autocomplete: temas com procura ativa
        for kw in niche["keywords"][:3]:
            for sug in yt.autocomplete(kw, lang, geo)[:4]:
                add(sug, "autocomplete", key, {"seed": kw})
        # 3) Reddit
        for sub in niche["subreddits"][:2]:
            for post in reddit_top(sub, 5):
                if post["score"] > 2000:
                    add(post["title"], "reddit", key, post, momentum_hint=min(90, 30 + post["score"] / 1000))
        # 4) YouTube: outliers recentes (quota: 1 search por nicho)
        if yt.enabled():
            items = yt.enrich_outliers(yt.search_recent(niche["keywords"][0], geo, lang, days=14, max_results=25))
            outliers_by_niche[key] = items
            for it in sorted(items, key=lambda x: -x["outlier_ratio"])[:4]:
                if it["outlier_ratio"] >= 2:
                    add(it["title"], "youtube_outlier", key, it,
                        momentum_hint=min(100, 35 + 12 * math.log2(it["outlier_ratio"])))
        # 5) sementes evergreen do nicho (série do Wikipedia decide se estão em alta)
        for seed in niche["wiki_seeds"][:2]:
            add(seed.replace("_", " "), "wikipedia", key, {"seed": seed})

    ranked = sorted(cands.values(), key=lambda c: (-len(c["sources"]), -c["hint"]))[:max_candidates]
    trends: list[Trend] = []
    for c in ranked:
        article, series = wikipedia_series(c["topic"], lang if lang in ("en", "pt", "es", "de", "fr") else "en")
        diag = analyze_series(series) if series else {"momentum": 0.0, "longevity": "unknown", "longevity_days": 0}
        momentum = max(diag["momentum"], c["hint"]) if diag["longevity"] != "unknown" else c["hint"]
        longevity = diag["longevity"]
        if longevity == "unknown":
            longevity = "flash" if "google_trends" in c["sources"] else "wave"
            diag["longevity_days"] = 5 if longevity == "flash" else 21
        sat = saturation_from_outliers(outliers_by_niche.get(c["niche"], [])) if outliers_by_niche else \
            float((get_niche(c["niche"]) or {}).get("competition", 60))
        opp = opportunity(momentum, longevity, sat, c["niche"], lang)
        trends.append(Trend(
            topic=c["topic"], source="+".join(sorted(c["sources"])), geo=geo, niche_key=c["niche"],
            momentum=round(momentum, 1), longevity=longevity, longevity_days=int(diag.get("longevity_days", 0)),
            saturation=sat, opportunity=opp, series=series[-120:],
            evidence={"wiki_article": article, "diagnostics": diag,
                      **{k: v[:3] for k, v in c["evidence"].items()}},
        ))
    trends.sort(key=lambda t: -t.opportunity)
    if use_llm:
        enrich(trends[:12], geo=geo, lang=lang)
    with session_scope() as s:
        for t in trends:
            s.add(t)
        s.commit()
    return trends


TREND_SCHEMA = obj({"trends": arr(obj({
    "topic": S, "verdict": enum("ride_now", "build_series", "evergreen_asset", "skip"), "longevity_days": INT,
    "why": S, "dark_angles": arr(S), "best_format": enum("short", "long", "both"), "best_niche": S, "risks": S,
}))})


def enrich(trends: list[Trend], geo: str, lang: str) -> None:
    llm = get_llm()
    if not trends:
        return
    payload = [{"topic": t.topic, "momentum": t.momentum, "longevity_class": t.longevity,
                "longevity_days_model": t.longevity_days, "saturation": t.saturation, "niche_guess": t.niche_key,
                "sources": t.source,
                "evidence": {k: v for k, v in t.evidence.items() if k in ("diagnostics", "youtube_outlier",
                                                                          "google_trends")}} for t in trends]
    out = llm.json(system=prompts.SYSTEM,
                   prompt=prompts.TREND_ANALYSIS.format(
                       context=json.dumps({"geo": geo, "language": lang}),
                       trends=json.dumps(payload, ensure_ascii=False, default=str)[:30000],
                       niche_keys=", ".join(n["key"] for n in NICHES)),
                   schema=TREND_SCHEMA, effort="medium", purpose="trend_analysis")
    if not out:
        for t in trends:
            t.analysis = heuristic_verdict(t)
        return
    by_topic = {x["topic"].lower(): x for x in out.get("trends", [])}
    for i, t in enumerate(trends):
        a = by_topic.get(t.topic.lower()) or (out["trends"][i] if i < len(out.get("trends", [])) else None)
        if a:
            t.analysis = a
            if a.get("best_niche") and get_niche(a["best_niche"]):
                t.niche_key = a["best_niche"]
            if a.get("verdict") == "skip":
                t.opportunity = round(t.opportunity * 0.3, 1)
        else:
            t.analysis = heuristic_verdict(t)


def heuristic_verdict(t: Trend) -> dict:
    verdict = {"flash": "ride_now", "wave": "build_series", "evergreen": "evergreen_asset",
               "seasonal": "build_series"}.get(t.longevity, "build_series")
    if t.opportunity < 25:
        verdict = "skip"
    fmt = "short" if t.longevity == "flash" else ("long" if t.longevity == "evergreen" else "both")
    return {"topic": t.topic, "verdict": verdict, "longevity_days": t.longevity_days,
            "why": f"Momentum {t.momentum:.0f}, classe {t.longevity}, saturação {t.saturation:.0f} (heurística).",
            "dark_angles": [f"The untold side of {t.topic}", f"What nobody tells you about {t.topic}",
                            f"The hidden cost of {t.topic}"],
            "best_format": fmt, "best_niche": t.niche_key, "risks": "rever manualmente"}


def latest(limit: int = 60, niche: str | None = None) -> list[Trend]:
    since = now() - timedelta(days=10)
    with session_scope() as s:
        q = select(Trend).where(Trend.created_at >= since)
        if niche:
            q = q.where(Trend.niche_key == niche)
        rows = s.exec(q.order_by(Trend.opportunity.desc())).all()
    seen, out = set(), []
    for r in rows:  # último scan de cada tema
        if r.topic.lower() in seen:
            continue
        seen.add(r.topic.lower())
        out.append(r)
    return out[:limit]


def outlier_videos(niche_key: str, geo: str = "US", lang: str = "en", short: bool | None = None) -> list[dict]:
    niche = get_niche(niche_key)
    if not niche or not yt.enabled():
        return []
    items = yt.enrich_outliers(yt.search_recent(niche["keywords"][0], geo, lang, days=30, max_results=30,
                                                duration="short" if short else None))
    return sorted(items, key=lambda x: -x["outlier_ratio"])
