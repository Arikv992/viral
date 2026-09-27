"""PLANNER DE PRODUÇÃO: decide COMO fazer cada vídeo para maximizar lucro.

Para cada modo viável calcula:
  custo estimado (LLM + voz + visuais + vídeo IA + render)
  valor esperado = views esperadas × multiplicador de qualidade do modo × RPM / 1000
                   (para canais ainda sem YPP, valor estratégico descontado a 50%)
  risco (políticas/copyright) -> penalização
e escolhe o de maior lucro esperado que caiba no orçamento diário do canal.
As melhorias pagas (voz premium, imagens melhores, clips de vídeo IA) só entram quando
o retorno marginal esperado é >= 3× o custo marginal.
"""
from __future__ import annotations

from ...config import get_settings
from ...knowledge.niches import get_niche
from ...knowledge.providers import llm_cost, price
from ..finance import budget_status

MODES: dict[str, dict] = {
    "text_story": {
        "label": "História em texto + voz sobre fundo (estilo Reddit)",
        "desc": "Guião/narração + voz + fundo em loop (gameplay/abstrato) + legendas grandes. O mais barato; ótimo "
                "para volume em Shorts. Qualidade percebida baixa em longos.",
        "formats": ["short", "long"], "quality": {"short": 0.85, "long": 0.6}, "risk": 10,
    },
    "stock_narrated": {
        "label": "Documentário com stock footage",
        "desc": "Guião + voz + vídeos de stock grátis (Pexels/Pixabay) cortados a cada 3-6s + legendas + música. "
                "Excelente relação qualidade/custo para finanças, engenharia, natureza, geopolítica.",
        "formats": ["short", "long"], "quality": {"short": 0.95, "long": 0.95}, "risk": 8,
    },
    "ai_images_narrated": {
        "label": "Documentário com imagens IA (Ken Burns)",
        "desc": "Guião + voz + imagens geradas por IA por cena com movimento de câmara. Visual único e coerente — o "
                "padrão para história, mistério, terror, espaço.",
        "formats": ["short", "long"], "quality": {"short": 1.0, "long": 1.05}, "risk": 10,
    },
    "ai_video_full": {
        "label": "Vídeo IA generativo (Kling/Veo)",
        "desc": "Cenas em vídeo gerado por IA. Máximo impacto visual, custo alto; usado só em Shorts com potencial "
                "viral elevado ou como 'hero shots' pontuais num longo.",
        "formats": ["short", "long"], "quality": {"short": 1.3, "long": 1.15}, "risk": 12,
    },
    "clip_commentary": {
        "label": "Recorte + comentário (transformativo)",
        "desc": "Momentos fortes de vídeos com licença Creative Commons (ou com autorização), com gancho narrado, "
                "título no ecrã, contexto e legendas. Custo quase zero — mas SÓ com licença e valor original "
                "(política de conteúdo reutilizado).",
        "formats": ["short"], "quality": {"short": 1.1, "long": 0.9}, "risk": 35,
    },
}


def target_duration(fmt: str, niche_key: str = "") -> int:
    if fmt == "short":
        return 45
    if niche_key == "history_for_sleep":
        return 60 * 60
    return 10 * 60  # >8 min = mid-rolls


def estimate_cost(mode: str, fmt: str, seconds: int, voice: str = "tts:edge", image_tier: str = "img:flux-schnell",
                  ai_video_share: float = 0.0, video_tier: str = "vid:kling-std") -> dict:
    model = get_settings().llm_model
    words = seconds * (2.5 if fmt == "short" else 2.5)
    chars = words * 6
    scene_len = 3.5 if fmt == "short" else 9.0
    scenes = max(4, int(seconds / scene_len))
    # LLM: guião (+ thinking), packaging e compliance
    out_tok = words * 1.6 + scenes * 60 + 2500
    llm = llm_cost(model, 6000, int(out_tok)) + llm_cost(model, 4000 + words * 1.5, 1800) * 2
    tts = chars / 1000 * price(voice, "per_1k_chars")
    visuals = 0.0
    ai_video = 0.0
    if mode == "ai_images_narrated":
        visuals = scenes * price(image_tier, "per_image")
    elif mode == "ai_video_full":
        vid_scenes = max(1, int(scenes * (ai_video_share or (1.0 if fmt == "short" else 0.1))))
        ai_video = vid_scenes * 5 * price(video_tier, "per_second")
        visuals = (scenes - vid_scenes) * price(image_tier, "per_image")
    elif mode == "text_story":
        visuals = 0.0
    thumb = price("img:flux-dev", "per_image") if fmt == "long" else 0.0
    render = seconds / 60 * price("render:local", "per_minute")
    if mode == "clip_commentary":
        llm *= 0.6
        tts = 60 * 6 / 1000 * price(voice, "per_1k_chars")
    total = llm + tts + visuals + ai_video + thumb + render
    return {"llm": round(llm, 4), "tts": round(tts, 4), "visuals": round(visuals, 4), "ai_video": round(ai_video, 4),
            "thumbnail": round(thumb, 4), "render": round(render, 4), "total": round(total, 4), "scenes": scenes}


def plan(idea_scores: dict, fmt: str, niche_key: str, channel_monetized: bool = False,
         channel_budget_share: float = 1.0, source_license: str | None = None,
         capabilities: dict | None = None, force_mode: str | None = None) -> dict:
    caps = capabilities or get_settings().capabilities()
    niche = get_niche(niche_key) or {"best_modes": list(MODES), "policy_risk": 20, "clip_fit": 30}
    seconds = target_duration(fmt, niche_key)
    views = float(idea_scores.get("expected_views", 1500 if fmt == "short" else 400))
    rpm = float(idea_scores.get("rpm", 0.05 if fmt == "short" else 3.0))
    value_factor = 1.0 if channel_monetized else 0.5
    status = budget_status()
    per_video_cap = max(0.02, status["daily_allowance"] * max(channel_budget_share, 0.1) * 1.5)

    options = []
    for key, m in MODES.items():
        if fmt not in m["formats"]:
            continue
        reasons, blocked = [], None
        if key == "clip_commentary":
            if not source_license:
                blocked = "sem fonte licenciada (CC-BY/autorização) — recorte bloqueado para proteger o canal"
            if niche.get("clip_fit", 0) < 30:
                reasons.append("nicho com poucas fontes licenciáveis")
        if key == "ai_video_full" and not caps.get("ai_video"):
            blocked = "sem FAL_API_KEY (vídeo IA)"
        if key == "stock_narrated" and not caps.get("stock_media"):
            reasons.append("sem chave Pexels/Pixabay: cai para imagens IA/procedurais")
        if key == "ai_images_narrated" and not caps.get("ai_images"):
            reasons.append("sem FAL_API_KEY: usa arte procedural (qualidade inferior)")
        q = m["quality"][fmt]
        if key not in niche["best_modes"]:
            q *= 0.85
            reasons.append("modo fora dos recomendados para o nicho")
        if key in ("stock_narrated",) and not caps.get("stock_media"):
            q *= 0.75
        if key == "ai_images_narrated" and not caps.get("ai_images"):
            q *= 0.8
        cost = estimate_cost(key, fmt, seconds)
        value = views * q * rpm / 1000 * value_factor
        risk = (m["risk"] + niche.get("policy_risk", 20)) / 2
        profit = value * (1 - risk / 200) - cost["total"]
        options.append({"mode": key, "label": m["label"], "quality": round(q, 2), "cost": cost,
                        "expected_value": round(value, 4), "risk": round(risk, 1), "expected_profit": round(profit, 4),
                        "blocked": blocked, "over_budget": cost["total"] > per_video_cap, "notes": reasons})

    viable = [o for o in options if not o["blocked"] and not o["over_budget"]]
    if force_mode:
        chosen = next((o for o in options if o["mode"] == force_mode), None) or (viable or options)[0]
    else:
        # pré-monetização o objetivo é crescer: desempate por qualidade/retenção quando lucros são ~iguais
        pool = viable or sorted([o for o in options if not o["blocked"]], key=lambda o: o["cost"]["total"])[:1]
        chosen = max(pool, key=lambda o: (o["expected_profit"] + 0.02 * o["quality"], o["quality"]))

    upgrades = decide_upgrades(chosen, fmt, seconds, views, rpm * value_factor, caps, per_video_cap)
    why = (f"Modo '{chosen['label']}': lucro esperado ${chosen['expected_profit']:.3f} com custo "
           f"${chosen['cost']['total']:.3f} (teto por vídeo ${per_video_cap:.2f}). ")
    if not channel_monetized:
        why += "Canal ainda sem YPP: valor contado a 50% (estratégico), por isso o plano favorece custo mínimo. "
    return {"mode": chosen["mode"], "format": fmt, "target_seconds": seconds, "chosen": chosen,
            "options": sorted(options, key=lambda o: -o["expected_profit"]), "upgrades": upgrades,
            "per_video_cap": round(per_video_cap, 3), "why": why}


def decide_upgrades(chosen: dict, fmt: str, seconds: int, views: float, rpm_value: float, caps: dict,
                    cap: float) -> dict:
    """Melhorias pagas só quando retorno marginal >= 3× custo marginal."""
    words = seconds * 2.5
    up = {"voice": "tts:edge", "image_tier": "img:flux-schnell", "thumbnail_tier": "img:flux-dev",
          "ai_video_share": 0.0, "reasons": []}
    base_value = views * rpm_value / 1000
    voice_cost = words * 6 / 1000 * price("tts:elevenlabs", "per_1k_chars")
    voice_gain = base_value * (0.12 if fmt == "long" else 0.05)  # retenção melhor com voz premium
    if caps.get("premium_voice") and voice_gain >= 3 * voice_cost and chosen["cost"]["total"] + voice_cost <= cap:
        up["voice"] = "tts:elevenlabs"
        up["reasons"].append(f"Voz premium: ganho ${voice_gain:.2f} vs custo ${voice_cost:.2f}")
    else:
        up["reasons"].append(f"Voz grátis (premium custaria ${voice_cost:.2f} para ganho esperado ${voice_gain:.2f})")
    if chosen["mode"] in ("ai_images_narrated", "ai_video_full") and caps.get("ai_images"):
        scenes = chosen["cost"]["scenes"]
        extra = scenes * (price("img:flux-dev", "per_image") - price("img:flux-schnell", "per_image"))
        if base_value * 0.08 >= 3 * extra:
            up["image_tier"] = "img:flux-dev"
            up["reasons"].append(f"Imagens Flux Dev: +${extra:.2f} justificado")
    if fmt == "long" and caps.get("ai_images"):
        tgain = base_value * 0.15  # thumbnail forte ~ +CTR
        if tgain >= 3 * price("img:flux-pro", "per_image"):
            up["thumbnail_tier"] = "img:flux-pro"
    if chosen["mode"] == "ai_video_full":
        up["ai_video_share"] = 1.0 if fmt == "short" else 0.1
    elif chosen["mode"] == "ai_images_narrated" and caps.get("ai_video") and fmt == "short":
        # 'hero shot': 1 clip de vídeo IA no gancho se o Short tiver potencial alto
        hero = 5 * price("vid:kling-std", "per_second")
        if base_value * 0.2 >= 3 * hero:
            up["ai_video_share"] = 0.15
            up["reasons"].append(f"Hero shot em vídeo IA no gancho (+${hero:.2f})")
    return up
