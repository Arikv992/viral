"""GUARDIÃO DE MONETIZAÇÃO: nada é publicado sem passar aqui.

Camada 1 (determinística, grátis): palavras que limitam anúncios no título/primeiros 30s, licença de
recortes, similaridade com vídeos anteriores (conteúdo "inautêntico"/produzido em massa), limites
técnicos do YouTube, necessidade de rótulo de conteúdo sintético.
Camada 2 (LLM, esforço baixo): revisão de políticas com correções exatas.
"""
from __future__ import annotations

import re

from sqlmodel import select

from .. import prompts
from ..db import session_scope
from ..llm import INT, S, arr, enum, get_llm, obj
from ..models import Video
from .ideas import jaccard, tokens

AD_UNFRIENDLY = {
    # palavra -> alternativa segura para anunciantes
    "murder": "case", "murdered": "killed", "killer": "suspect", "kill": "take down", "killed": "lost their life",
    "suicide": "tragic loss", "rape": "assault", "gore": "", "blood": "", "bloody": "brutal", "corpse": "remains",
    "dead body": "remains", "torture": "punishment", "massacre": "tragedy", "behead": "", "beheaded": "executed",
    "shooting": "incident", "terrorist": "attacker", "nazi": "regime", "porn": "", "sex": "", "cocaine": "substance",
    "heroin": "substance", "overdose": "tragedy", "fuck": "", "shit": "", "bitch": "",
}
SYNTHETIC_MODES = {"ai_video_full"}

REVIEW_SCHEMA = obj({
    "scores": obj({"advertiser_friendliness": INT, "reused_content": INT, "inauthentic_content": INT,
                   "copyright": INT, "misinformation": INT, "synthetic_media_disclosure": INT}),
    "issues": arr(obj({"area": S, "problem": S, "fix": S})),
    "verdict": enum("publish", "fix_then_publish", "block"),
})


def scan_words(text: str) -> list[str]:
    t = text.lower()
    return [w for w in AD_UNFRIENDLY if re.search(rf"\b{re.escape(w)}\b", t)]


def first_seconds_text(script: dict, seconds: float = 30.0) -> str:
    words, out = 0, []
    for s in script.get("scenes", []):
        out.append(s["narration"])
        words += len(s["narration"].split())
        if words / 2.5 >= seconds:
            break
    return " ".join(out)


def check(video: Video, niche_key: str = "", use_llm: bool = True) -> dict:
    issues: list[dict] = []
    risk = 0.0
    title = (video.packaging or {}).get("title") or (video.script or {}).get("title", "")
    full = " ".join(s["narration"] for s in (video.script or {}).get("scenes", []))

    bad_title = scan_words(title)
    if bad_title:
        risk += 30
        issues.append({"area": "advertiser_friendliness", "problem": f"Título com termos sensíveis: {bad_title}",
                       "fix": "Trocar por: " + ", ".join(f"{w}→{AD_UNFRIENDLY[w] or '(remover)'}" for w in bad_title)})
    bad_open = scan_words(first_seconds_text(video.script or {}))
    if bad_open:
        risk += 15
        issues.append({"area": "advertiser_friendliness",
                       "problem": f"Termos sensíveis nos primeiros 30s: {bad_open}",
                       "fix": "Suavizar a abertura (anúncios são decididos sobretudo pelo início)."})

    if video.mode == "clip_commentary":
        src = video.source or {}
        if not (src.get("is_cc") or src.get("permission")):
            risk += 100
            issues.append({"area": "copyright", "problem": "Recorte sem licença CC nem autorização registada.",
                           "fix": "Usar apenas fontes CC-BY (filtro 'Creative Commons') ou registar autorização."})
        clips = src.get("clips", [])
        if any(len((c.get("hook_text") or "").split()) < 3 for c in clips):
            risk += 25
            issues.append({"area": "reused_content", "problem": "Comentário original insuficiente num recorte.",
                           "fix": "Cada recorte precisa de gancho narrado + contexto próprios."})

    # similaridade com os últimos vídeos do canal (conteúdo inautêntico / em massa)
    mine = tokens(full)
    with session_scope() as s:
        prev = s.exec(select(Video).where(Video.channel_id == video.channel_id, Video.id != video.id)
                      .order_by(Video.id.desc()).limit(40)).all()
    sims = [(p.id, jaccard(mine, tokens(" ".join(sc["narration"] for sc in (p.script or {}).get("scenes", [])))))
            for p in prev if p.script]
    top = max(sims, key=lambda x: x[1]) if sims else (None, 0.0)
    if top[1] >= 0.55:
        risk += 40
        issues.append({"area": "inauthentic_content",
                       "problem": f"Guião {top[1]:.0%} semelhante ao vídeo #{top[0]} (risco de conteúdo repetitivo).",
                       "fix": "Reescrever com ângulo, estrutura e factos diferentes."})

    if len(title) > 100:
        risk += 5
        issues.append({"area": "technical", "problem": "Título > 100 caracteres.", "fix": "Encurtar."})
    tags = (video.packaging or {}).get("tags", [])
    if sum(len(t) + 1 for t in tags) > 480:
        issues.append({"area": "technical", "problem": "Tags excedem 500 caracteres.", "fix": "Cortar tags longas."})
    if video.format == "short" and video.duration_s > 180:
        risk += 20
        issues.append({"area": "technical", "problem": "Short com mais de 3 minutos.", "fix": "Cortar para <= 58s."})
    if video.format == "long" and 0 < video.duration_s < 480:
        issues.append({"area": "revenue", "problem": "Longo com menos de 8 min — sem mid-rolls.",
                       "fix": "Alongar para 8-12 min se o tema aguentar sem encher."})

    synthetic = video.mode in SYNTHETIC_MODES or bool((video.packaging or {}).get("ai_disclosure_needed"))

    llm_review = None
    if use_llm and full:
        llm_review = get_llm().json(
            system=prompts.SYSTEM,
            prompt=prompts.COMPLIANCE.format(niche=niche_key, mode=video.mode, source=str(video.source)[:1500],
                                             title=title, script=full[:40000]),
            schema=REVIEW_SCHEMA, effort="low", purpose="compliance", video_id=video.id)
        if llm_review:
            worst = max(llm_review["scores"].values()) if llm_review["scores"] else 0
            risk = max(risk, worst * 0.9)
            issues += [{"area": i["area"], "problem": i["problem"], "fix": i["fix"], "by": "llm"}
                       for i in llm_review["issues"]]
            if llm_review["verdict"] == "block":
                risk = max(risk, 80)

    risk = min(100.0, risk)
    verdict = "block" if risk >= 70 else ("fix_then_publish" if risk >= 35 else "publish")
    return {"risk": round(risk, 1), "verdict": verdict, "issues": issues, "synthetic_disclosure": synthetic,
            "max_similarity": round(top[1], 2), "llm": llm_review is not None}


def auto_fix_title(title: str) -> str:
    out = title
    for w in scan_words(title):
        out = re.sub(rf"\b{re.escape(w)}\b", AD_UNFRIENDLY[w], out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).strip()
