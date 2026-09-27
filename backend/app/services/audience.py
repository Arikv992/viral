"""PÚBLICO & CPM: quem atingir, onde está o dinheiro e o que essas pessoas procuram de facto.

Sinais usados:
- Autocomplete do YouTube (o que as pessoas escrevem, por país/língua) — grátis.
- Comentários dos vídeos outlier da concorrência (dores, desejos, perguntas) — YouTube API.
- Economia: RPM do nicho × mistura de países da língua.
"""
from __future__ import annotations

import json
import re
from collections import Counter

from .. import prompts
from ..knowledge.geo import COUNTRIES, DEFAULT_AUDIENCE_MIX, LANGUAGES, effective_rpm_mult
from ..knowledge.niches import get_niche
from ..llm import S, arr, get_llm, obj
from . import youtube_data as yt

AUDIENCE_SCHEMA = obj({
    "persona": obj({"name": S, "age_range": S, "gender_skew": S, "watch_context": S, "occupation": S, "wants": S}),
    "core_desires": arr(S), "core_fears": arr(S), "recurring_questions": arr(S), "their_words": arr(S),
    "content_gaps": arr(S), "highest_value_segment": S, "title_formulas": arr(S), "avoid": arr(S),
})

STOP = set("the a an of to in on for and or is are was why how what if with you your my i it this that do does "
           "can from at by be not vs".split())


def geo_rpm_table(niche_key: str, language: str) -> list[dict]:
    niche = get_niche(niche_key)
    base_long, base_short = sum(niche["rpm_long"]) / 2, sum(niche["rpm_short"]) / 2
    mix = DEFAULT_AUDIENCE_MIX.get(language) or {g: 1 for g in LANGUAGES[language]["geos"]}
    total = sum(mix.values())
    rows = []
    for g, w in sorted(mix.items(), key=lambda x: -x[1]):
        c = COUNTRIES.get(g)
        if not c:
            continue
        rows.append({"geo": g, "name": c["name"], "audience_share": round(w / total, 3),
                     "rpm_long": round(base_long * c["rpm_mult"], 2), "rpm_short": round(base_short * c["rpm_mult"], 3),
                     "revenue_share": 0.0, "tz": c["tz"]})
    tot_rev = sum(r["audience_share"] * r["rpm_long"] for r in rows) or 1
    for r in rows:
        r["revenue_share"] = round(r["audience_share"] * r["rpm_long"] / tot_rev, 3)
    return rows


def demand_map(niche_key: str, language: str = "en", geo: str = "US", deep: bool = True) -> dict:
    niche = get_niche(niche_key)
    queries: list[str] = []
    for kw in niche["keywords"][:4]:
        queries += yt.autocomplete_harvest(kw, language, geo, deep=deep)
    queries = list(dict.fromkeys(queries))
    words = Counter(w for q in queries for w in re.findall(r"[a-zà-ÿ']+", q.lower()) if w not in STOP and len(w) > 2)
    questions = [q for q in queries if re.match(r"^(why|how|what|who|when|is|can|does|porque|como|o que|qual)\b", q)]
    return {"queries": queries[:300], "top_terms": words.most_common(40), "questions": questions[:60],
            "count": len(queries)}


def competitor_comments(niche_key: str, language: str, geo: str, videos: int = 4) -> list[str]:
    from .trends import outlier_videos

    comments: list[str] = []
    for v in outlier_videos(niche_key, geo, language)[:videos]:
        comments += yt.top_comments(v["video_id"], 40)
    return comments


def analyze(niche_key: str, language: str = "en", geo: str = "US", deep: bool = True,
            channel_id: int | None = None) -> dict:
    niche = get_niche(niche_key)
    if not niche:
        raise ValueError(f"nicho desconhecido: {niche_key}")
    demand = demand_map(niche_key, language, geo, deep)
    comments = competitor_comments(niche_key, language, geo) if yt.enabled() else []
    mult = effective_rpm_mult(language)
    rpm_long = round(sum(niche["rpm_long"]) / 2 * mult, 2)
    rpm_short = round(sum(niche["rpm_short"]) / 2 * mult, 3)
    brief = get_llm().json(
        system=prompts.SYSTEM,
        prompt=prompts.AUDIENCE.format(niche=niche["name"], language=language, geos=LANGUAGES[language]["geos"][:5],
                                       queries="\n".join(demand["queries"][:250]) or "(sem dados)",
                                       comments=json.dumps(comments[:150], ensure_ascii=False) or "(sem dados)",
                                       rpm_long=rpm_long, rpm_short=rpm_short),
        schema=AUDIENCE_SCHEMA, effort="medium", purpose="audience", channel_id=channel_id)
    return {
        "niche": niche_key, "language": language, "geo": geo,
        "economics": {"rpm_long": rpm_long, "rpm_short": rpm_short, "geo_table": geo_rpm_table(niche_key, language)},
        "demand": demand, "comments_sample": comments[:30],
        "brief": brief or heuristic_brief(niche, demand),
        "source": "llm" if brief else "heuristic",
    }


def heuristic_brief(niche: dict, demand: dict) -> dict:
    terms = [t for t, _ in demand["top_terms"][:10]]
    return {
        "persona": {"name": "Espectador-alvo", "age_range": "18-44", "gender_skew": "masculino (estimado)",
                    "watch_context": "telemóvel à noite; TV/desktop ao fim de semana para longos",
                    "occupation": "misto", "wants": niche["audience"]},
        "core_desires": [f"Perceber {p.lower()}" for p in niche["pillars"]],
        "core_fears": ["Ser enganado", "Ficar para trás", "Perder dinheiro/tempo", "O desconhecido", "Ser manipulado"],
        "recurring_questions": demand["questions"][:8],
        "their_words": terms,
        "content_gaps": [f"{q} (resposta aprofundada)" for q in demand["questions"][:6]],
        "highest_value_segment": "EUA/UK/CA/AU em inglês; longos de 8-12 min com mid-rolls; publicar 1-2h antes do "
                                 "pico da noite (ET).",
        "title_formulas": niche["hooks"] + ["Why {X} is worse than you think", "The truth about {X}"],
        "avoid": ["Intro lenta", "Gore/violência gráfica", "Títulos que não se cumprem", "Voz robótica monótona",
                  "Temas fora do cluster do canal"],
    }
