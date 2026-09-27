"""BANCO DE IDEIAS: gerar, pontuar, deduplicar e consolidar em séries.

Score (0-100) = procura × CTR × valor (RPM do formato) × momentum × evergreen × facilidade − risco.
Cada ideia recebe também o valor esperado em USD (views esperadas × RPM), que alimenta o Planner.
"""
from __future__ import annotations

import json
import re
from collections import Counter

from sqlmodel import select

from .. import prompts
from ..db import session_scope
from ..knowledge.geo import effective_rpm_mult
from ..knowledge.niches import get_niche
from ..llm import INT, S, arr, enum, get_llm, obj
from ..models import Channel, Idea, Publication, Trend, Video

IDEA_SCHEMA = obj({"ideas": arr(obj({
    "title": S, "hook": S, "angle": S, "format": enum("short", "long"), "pillar": S, "demand": INT,
    "ctr_potential": INT, "evergreen": INT, "production_difficulty": INT, "policy_risk": INT, "thumbnail_concept": S,
}))})

STOP = set("the a an of to in on for and or is are was why how what if with you your this that it its from at by "
           "be not vs who when de da do das dos o a os as e que para com um uma".split())


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9à-ÿ]+", text.lower()) if w not in STOP and len(w) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def expected_views(fmt: str, scores: dict, channel_videos: int = 0, baseline: float | None = None) -> float:
    """Views esperadas nos primeiros 28 dias. Usa a baseline real do canal quando existe."""
    base = baseline if baseline else (1500 if fmt == "short" else 400) * (1 + min(channel_videos, 60) / 20)
    q = (scores.get("demand", 50) / 50) * (scores.get("ctr", 50) / 50) * (0.6 + scores.get("momentum", 30) / 75)
    return round(base * q, 0)


def score_idea(raw: dict, niche: dict | None, language: str, momentum: float = 0.0) -> dict:
    fmt = raw.get("format", "short")
    mult = effective_rpm_mult(language)
    rpm = (sum(niche["rpm_short"]) / 2 if fmt == "short" else sum(niche["rpm_long"]) / 2) * mult if niche else 1.0
    rpm_norm = min(100.0, (rpm / 0.12 * 50) if fmt == "short" else (rpm / 8 * 100))
    s = {
        "demand": float(raw.get("demand", 50)), "ctr": float(raw.get("ctr_potential", 50)),
        "rpm": round(rpm, 3), "rpm_norm": round(rpm_norm, 1), "momentum": float(momentum),
        "evergreen": float(raw.get("evergreen", 50)), "ease": 100 - float(raw.get("production_difficulty", 50)),
        "risk": float(raw.get("policy_risk", 20)),
    }
    total = (0.24 * s["demand"] + 0.22 * s["ctr"] + 0.14 * s["rpm_norm"] + 0.14 * s["momentum"]
             + 0.12 * s["evergreen"] + 0.14 * s["ease"]) - 0.35 * max(0.0, s["risk"] - 25)
    s["total"] = round(max(0.0, min(100.0, total)), 1)
    return s


def existing_titles(channel_id: int | None) -> list[str]:
    with session_scope() as s:
        q = select(Idea.title)
        if channel_id:
            q = q.where(Idea.channel_id == channel_id)
        return list(s.exec(q).all())


def generate(channel_id: int, count: int = 20, fmt: str = "both", trend_ids: list[int] | None = None,
             winners: list[str] | None = None, audience: dict | None = None, origin: str = "generated",
             parent_video_id: int | None = None) -> list[Idea]:
    with session_scope() as s:
        ch = s.get(Channel, channel_id)
        if not ch:
            raise ValueError("canal não encontrado")
        trends = [s.get(Trend, t) for t in (trend_ids or [])]
        trends = [t for t in trends if t]
    niche = get_niche(ch.niche_key)
    existing = existing_titles(channel_id)
    trend_payload = [{"topic": t.topic, "verdict": t.analysis.get("verdict"), "angles": t.analysis.get("dark_angles"),
                      "longevity_days": t.longevity_days, "id": t.id} for t in trends]
    out = get_llm().json(
        system=prompts.SYSTEM,
        prompt=prompts.IDEAS.format(
            count=count,
            channel=json.dumps({"name": ch.name, "niche": niche["name"] if niche else ch.niche_key,
                                "language": ch.language, "positioning": ch.strategy.get("positioning", ""),
                                "pillars": ch.strategy.get("content_pillars") or (niche or {}).get("pillars", [])},
                               ensure_ascii=False),
            audience=json.dumps((audience or ch.strategy.get("audience_brief") or {}), ensure_ascii=False)[:6000],
            trends=json.dumps(trend_payload, ensure_ascii=False), winners=json.dumps(winners or [], ensure_ascii=False),
            existing=json.dumps(existing[-150:], ensure_ascii=False), fmt=fmt),
        schema=IDEA_SCHEMA, effort="medium", purpose="ideas", channel_id=channel_id)
    raws = out["ideas"] if out else (sequel_ideas(winners or [], niche, count, fmt) if origin == "scale"
                                     else heuristic_ideas(niche, trends, winners, count, fmt))
    dup_limit = 0.85 if origin == "scale" else 0.6  # sequelas são próximas do vencedor de propósito
    momentum_by_topic = {t.topic.lower(): t.momentum for t in trends}
    created: list[Idea] = []
    ex_tokens = [tokens(t) for t in existing]
    with session_scope() as s:
        for r in raws:
            if fmt in ("short", "long"):
                r["format"] = fmt
            tk = tokens(r["title"])
            if any(jaccard(tk, e) >= dup_limit for e in ex_tokens):
                continue  # duplicado
            ex_tokens.append(tk)
            trend = next((t for t in trends if tokens(t.topic) & tk), None)
            momentum = momentum_by_topic.get(trend.topic.lower(), 0.0) if trend else (35.0 if origin == "scale" else 0.0)
            sc = score_idea(r, niche, ch.language, momentum)
            sc["expected_views"] = expected_views(r["format"], sc)
            sc["expected_revenue_usd"] = round(sc["expected_views"] / 1000 * sc["rpm"], 3)
            idea = Idea(channel_id=channel_id, trend_id=trend.id if trend else None, title=r["title"][:200],
                        hook=r.get("hook", ""), angle=r.get("angle", ""), format=r["format"],
                        pillar=r.get("pillar", ""), scores={**sc, "thumbnail_concept": r.get("thumbnail_concept", "")},
                        score=sc["total"], origin=origin, parent_video_id=parent_video_id)
            s.add(idea)
            created.append(idea)
        s.commit()
    consolidate(channel_id)
    return created


def heuristic_ideas(niche: dict | None, trends: list[Trend], winners: list[str] | None, count: int,
                    fmt: str) -> list[dict]:
    niche = niche or {"hooks": ["The truth about {X}"], "pillars": ["Geral"], "keywords": ["mystery"]}
    subjects = [t.topic for t in trends] + (winners or []) + niche["keywords"]
    out = []
    i = 0
    while len(out) < count and i < count * 3:
        subj = subjects[i % len(subjects)]
        hook = niche["hooks"][i % len(niche["hooks"])]
        title = hook.replace("{X}", subj.title()).replace("{country}", "Switzerland")
        if "{X}" not in hook and subj.lower() not in title.lower():
            title = f"{title} ({subj.title()})"
        f = fmt if fmt in ("short", "long") else ("short" if i % 3 else "long")
        out.append({"title": title[:95], "hook": title, "angle": "Ângulo heurístico — reescrever com LLM para qualidade.",
                    "format": f, "pillar": niche["pillars"][i % len(niche["pillars"])], "demand": 55,
                    "ctr_potential": 50, "evergreen": 60, "production_difficulty": 40, "policy_risk": 15,
                    "thumbnail_concept": ""})
        i += 1
    return out


SEQUEL_TEMPLATES = ["{W}: Part 2", "What Happened After {W}", "The Real Reason Behind {W}",
                    "{W} — The Part They Cut", "5 More Stories Like {W}", "The Darker Truth Behind {W}"]


def sequel_ideas(winners: list[str], niche: dict | None, count: int, fmt: str) -> list[dict]:
    """Escala sem LLM: sequelas e variações diretas do vencedor (mesmo tema, novo ângulo)."""
    out = []
    for i in range(count):
        w = winners[i % len(winners)] if winners else "this story"
        t = SEQUEL_TEMPLATES[i % len(SEQUEL_TEMPLATES)].replace("{W}", w.rstrip("?!. "))
        out.append({"title": t[:95], "hook": t, "angle": f"Escala do vencedor '{w}'.",
                    "format": fmt if fmt in ("short", "long") else "short",
                    "pillar": (niche or {}).get("pillars", [""])[0], "demand": 70, "ctr_potential": 65,
                    "evergreen": 55, "production_difficulty": 35, "policy_risk": 15, "thumbnail_concept": ""})
    return out


def consolidate(channel_id: int | None = None) -> dict:
    """Funde duplicados (fica o melhor) e agrupa ideias em séries por semelhança lexical."""
    with session_scope() as s:
        q = select(Idea).where(Idea.status.in_(["backlog", "approved"]))
        if channel_id:
            q = q.where(Idea.channel_id == channel_id)
        ideas = sorted(s.exec(q).all(), key=lambda i: -i.score)
        kept: list[tuple[Idea, set[str]]] = []
        merged = 0
        for idea in ideas:
            tk = tokens(idea.title)
            dup = next((k for k, t in kept if k.channel_id == idea.channel_id and jaccard(tk, t) >=
                        (0.85 if {k.origin, idea.origin} & {"scale", "republish"} else 0.6)), None)
            if dup:
                idea.status = "discarded"
                idea.notes = f"Fundida na ideia #{dup.id}"
                merged += 1
                s.add(idea)
                continue
            kept.append((idea, tk))
        # séries: agrupar por termo dominante partilhado
        clusters: list[dict] = []
        for idea, tk in kept:
            best = None
            for c in clusters:
                if jaccard(tk, c["tokens"]) >= 0.2 or (idea.pillar and idea.pillar == c["pillar"] and c["pillar"]):
                    best = c
                    break
            if best is None:
                best = {"tokens": set(tk), "ideas": [], "pillar": idea.pillar}
                clusters.append(best)
            best["ideas"].append(idea)
            best["tokens"] |= tk
        for c in clusters:
            counts = Counter(w for i in c["ideas"] for w in tokens(i.title))
            label = c["pillar"] or " ".join(w for w, _ in counts.most_common(2)) or "misc"
            key = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40]
            for i in c["ideas"]:
                i.series_key = key
                s.add(i)
        s.commit()
    return {"merged": merged, "series": len(clusters), "kept": len(kept)}


def series_overview(channel_id: int | None = None) -> list[dict]:
    with session_scope() as s:
        q = select(Idea).where(Idea.status != "discarded")
        if channel_id:
            q = q.where(Idea.channel_id == channel_id)
        ideas = s.exec(q).all()
    groups: dict[str, list[Idea]] = {}
    for i in ideas:
        groups.setdefault(i.series_key or "sem-série", []).append(i)
    out = []
    for k, items in groups.items():
        out.append({"series": k, "count": len(items), "avg_score": round(sum(i.score for i in items) / len(items), 1),
                    "published": sum(1 for i in items if i.status == "published"),
                    "top": [i.title for i in sorted(items, key=lambda x: -x.score)[:3]]})
    return sorted(out, key=lambda r: -r["avg_score"])


def winners_for(channel_id: int, limit: int = 5) -> list[str]:
    with session_scope() as s:
        pubs = s.exec(select(Publication).where(Publication.channel_id == channel_id,
                                                Publication.verdict == "scale")).all()
        titles = []
        for p in pubs[-limit:]:
            v = s.get(Video, p.video_id)
            titles.append(p.title or (v.packaging.get("title") if v else ""))
    return [t for t in titles if t]
