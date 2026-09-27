"""ESTRATÉGIA DE CANAIS: que canais criar, em que língua, para que países, com que nome.

O ranking é um modelo económico explícito (não uma opinião):
  receita esperada/vídeo = views esperadas × RPM efetivo (nicho × mistura de países da língua)
  custo/vídeo           = custo do modo de produção recomendado
  opportunity           = mistura ponderada de RPM, procura, (1-concorrência), evergreen, viralidade,
                          adequação à produção sem rosto e (1-risco de políticas)
"""
from __future__ import annotations

import itertools
import json
import random
import re

from .. import prompts
from ..knowledge.geo import COUNTRIES, DEFAULT_AUDIENCE_MIX, LANGUAGES, effective_rpm_mult
from ..knowledge.niches import NICHES, get_niche
from ..llm import INT, S, arr, get_llm, obj
from . import youtube_data as yt


def score_niche(n: dict, language: str = "en", budget: float = 50, prefer: str = "both",
                trend_boost: float = 0.0) -> dict:
    mult = effective_rpm_mult(language)
    rpm_long = round(sum(n["rpm_long"]) / 2 * mult, 2)
    rpm_short = round(sum(n["rpm_short"]) / 2 * mult, 3)
    # adequação ao orçamento: modos baratos pontuam melhor quando o orçamento é curto
    cheap = any(m in n["best_modes"] for m in ("stock_narrated", "text_story", "clip_commentary"))
    budget_fit = 1.0 if budget >= 150 or cheap else 0.75
    fmt_fit = {"short": n["virality"] / 100, "long": n["evergreen"] / 100}.get(prefer, (n["virality"] + n["evergreen"]) / 200)
    rpm_norm = min(1.0, rpm_long / 10)
    parts = {
        "rpm": 30 * rpm_norm,
        "competition": 14 * (1 - n["competition"] / 100),
        "evergreen": 12 * n["evergreen"] / 100,
        "virality": 10 * n["virality"] / 100,
        "production_fit": 12 * max(n["ai_fit"], n["clip_fit"]) / 100 * budget_fit,
        "policy_safety": 12 * (1 - n["policy_risk"] / 100),
        "format_fit": 6 * fmt_fit,
        "ease": 4 * (1 - n["complexity"] / 100),
        "trend": min(10, trend_boost / 10),
    }
    score = sum(parts.values())
    # projeção simples de um canal saudável ao mês 12 (views/mês long e shorts)
    long_views, short_views = 120_000 * (0.6 + n["evergreen"] / 250), 2_500_000 * (0.4 + n["virality"] / 150)
    rev12 = long_views / 1000 * rpm_long + short_views / 1000 * rpm_short
    return {
        **{k: n[k] for k in ("key", "name", "category", "description", "competition", "evergreen", "virality",
                             "policy_risk", "best_modes", "audience", "pillars")},
        "language": language, "rpm_long_effective": rpm_long, "rpm_short_effective": rpm_short,
        "score": round(score, 1), "score_parts": {k: round(v, 1) for k, v in parts.items()},
        "month12_revenue_estimate": [round(rev12 * 0.35), round(rev12 * 1.6)],
    }


def rank_niches(language: str = "en", budget: float = 50, prefer: str = "both",
                trend_counts: dict[str, float] | None = None) -> list[dict]:
    trend_counts = trend_counts or {}
    rows = [score_niche(n, language, budget, prefer, trend_counts.get(n["key"], 0)) for n in NICHES]
    return sorted(rows, key=lambda r: -r["score"])


def language_economics() -> list[dict]:
    """Quanto vale cada língua (RPM efetivo) — responde 'em que público apostar'."""
    rows = []
    for code, lang in LANGUAGES.items():
        mix = DEFAULT_AUDIENCE_MIX.get(code) or {g: 1 for g in lang["geos"]}
        rows.append({"language": code, "name": lang["name"], "rpm_mult": round(effective_rpm_mult(code), 3),
                     "top_geos": [{"geo": g, "name": COUNTRIES[g]["name"], "share": round(w / sum(mix.values()), 2),
                                   "rpm_mult": COUNTRIES[g]["rpm_mult"]}
                                  for g, w in sorted(mix.items(), key=lambda x: -x[1])[:5] if g in COUNTRIES]})
    return sorted(rows, key=lambda r: -r["rpm_mult"])


STRATEGY_SCHEMA = obj({"concepts": arr(obj({
    "niche_key": S, "positioning": S, "target_audience": S, "language": S, "target_geos": arr(S),
    "format_mix": S, "content_pillars": arr(S), "signature_style": S, "monetization_path": S,
    "revenue_12m_usd": arr(INT), "production_mode": S, "kill_criteria": S, "first_10_videos": arr(S),
}))})


def channel_concepts(language: str = "en", budget: float = 50, prefer: str = "both", count: int = 5,
                     trends: list[dict] | None = None, notes: str = "") -> dict:
    ranked = rank_niches(language, budget, prefer)
    llm = get_llm()
    constraints = {"monthly_budget_usd": budget, "language": language, "format_preference": prefer,
                   "operator_notes": notes or "faceless only, maximise profit, reinvest winnings"}
    out = llm.json(system=prompts.SYSTEM,
                   prompt=prompts.CHANNEL_STRATEGY.format(
                       constraints=json.dumps(constraints), niches=json.dumps(ranked[:14], ensure_ascii=False),
                       trends=json.dumps(trends or [], ensure_ascii=False)[:8000], count=count),
                   schema=STRATEGY_SCHEMA, effort="high", purpose="channel_strategy")
    if out:
        return {"source": "llm", "ranked_niches": ranked, "concepts": out["concepts"]}
    return {"source": "heuristic", "ranked_niches": ranked,
            "concepts": [heuristic_concept(r, budget) for r in ranked[:count]]}


def heuristic_concept(r: dict, budget: float) -> dict:
    n = get_niche(r["key"])
    shorts_per_day = 3 if budget >= 30 else 2
    return {
        "niche_key": r["key"],
        "positioning": f"{r['name']}: {r['description']}",
        "target_audience": r["audience"],
        "language": r["language"],
        "target_geos": LANGUAGES[r["language"]]["geos"][:4],
        "format_mix": f"{shorts_per_day} Shorts/dia + {2 if budget >= 50 else 1} longos/semana",
        "content_pillars": n["pillars"],
        "signature_style": "Voz grave e calma, música ambiente escura, cortes a cada 3-4s, legendas palavra-a-palavra.",
        "monetization_path": "Shorts para descoberta e subscritores; longos 8-12 min para horas de exibição e mid-rolls.",
        "revenue_12m_usd": r["month12_revenue_estimate"],
        "production_mode": n["best_modes"][0],
        "kill_criteria": "Após 30 vídeos/60 dias: < 300 views médias nos longos e < 1.000 nos Shorts => congelar.",
        "first_10_videos": launch_titles(n, 10),
    }


GENERIC_HOOKS = ["The dark side of {X}", "What nobody tells you about {X}", "Why {X} is worse than you think",
                 "{X}: the untold story", "How {X} really works", "The truth about {X} they buried",
                 "The {X} secret that changes everything"]


def launch_titles(n: dict, count: int) -> list[str]:
    """Títulos distintos: ganchos do nicho + ganchos universais × palavras-chave (fallback sem LLM)."""
    subjects = [k.title() for k in n["keywords"]]
    hooks = [h for h in n["hooks"] if "{X}" in h] + GENERIC_HOOKS
    out = [h for h in n["hooks"] if "{" not in h]
    for i in range(len(hooks) * len(subjects)):
        t = hooks[i % len(hooks)].replace("{X}", subjects[i % len(subjects)])
        if t not in out:
            out.append(t)
        if len(out) >= count:
            break
    return out[:count]


NAMES_SCHEMA = obj({"names": arr(obj({"name": S, "handle": S, "style": S, "why_it_works": S,
                                      "memorability": INT, "niche_clarity": INT}))})

_LEXICON = {
    "mystery": ["Vault", "Cipher", "Enigma", "Obscura", "Nocturne", "Shadow", "Veil", "Hollow", "Abyss", "Relic"],
    "money": ["Ledger", "Capital", "Sovereign", "Fortune", "Mint", "Empire", "Crown", "Asset", "Titan", "Bullion"],
    "mind": ["Mind", "Psyche", "Stoic", "Cortex", "Mentor", "Logos", "Axiom", "Oracle", "Codex", "Monk"],
    "history": ["Chronicle", "Archive", "Epoch", "Annals", "Dynasty", "Legacy", "Relic", "Codex", "Ruins", "Era"],
    "science": ["Cosmos", "Void", "Quantum", "Horizon", "Orbit", "Nebula", "Depth", "Signal", "Atlas", "Vector"],
    "crime": ["Case", "Files", "Evidence", "Verdict", "Dossier", "Docket", "Witness", "Trace", "Motive", "Alibi"],
}
_SUFFIX = ["Files", "Archive", "Vault", "Society", "Institute", "Chronicles", "Room", "Protocol", "Lab", "Club"]
_ADJ = ["Dark", "Silent", "Hidden", "Black", "Deep", "Lost", "Obsidian", "Midnight", "Crimson", "Iron"]

CATEGORY_LEX = {"money": "money", "mind": "mind", "history": "history", "science": "science", "crime": "crime",
                "mystery": "mystery", "horror": "mystery", "world": "history", "tech": "science",
                "health": "science", "nature": "science", "stories": "mystery", "entertainment": "mystery"}


def generate_names(niche_key: str, concept: str = "", language: str = "en", count: int = 12,
                   style: str = "mixed", check_handles: bool = True) -> list[dict]:
    niche = get_niche(niche_key) or NICHES[0]
    out = get_llm().json(system=prompts.SYSTEM,
                         prompt=prompts.CHANNEL_NAMES.format(count=count, concept=concept or niche["description"],
                                                             language=language, style=style),
                         schema=NAMES_SCHEMA, effort="low", purpose="channel_names")
    names = out["names"] if out else heuristic_names(niche, count)
    for n in names:
        n["handle"] = re.sub(r"[^a-z0-9._-]", "", n.get("handle") or n["name"].lower())[:30]
        n["score"] = round(0.5 * n.get("memorability", 60) + 0.3 * n.get("niche_clarity", 60)
                           + 20 * (1 if 6 <= len(n["name"]) <= 16 else 0.4), 1)
        n["handle_available"] = yt.handle_available(n["handle"]) if check_handles else None
        if n["handle_available"] is False:
            n["score"] -= 25
    return sorted(names, key=lambda n: -n["score"])


def heuristic_names(niche: dict, count: int) -> list[dict]:
    lex = _LEXICON[CATEGORY_LEX.get(niche["category"], "mystery")]
    rng = random.Random(niche["key"])
    pool = set()
    for w in lex:
        pool.add((f"The {w} {rng.choice(_SUFFIX)}", "institucional"))
        pool.add((f"{rng.choice(_ADJ)} {w}", "evocativo"))
        pool.add((w + rng.choice(["ly", "ra", "on", "ix", "um"]), "marca inventada"))
    picks = rng.sample(sorted(pool), min(count, len(pool)))
    return [{"name": name, "handle": name.lower().replace(" ", "").replace("the", "", 1) if name.startswith("The ")
             else name.lower().replace(" ", ""), "style": st,
             "why_it_works": f"Nome {st} que evoca o tom do nicho {niche['name']}.",
             "memorability": 55 + len(set(name)) % 30, "niche_clarity": 60} for name, st in picks]
