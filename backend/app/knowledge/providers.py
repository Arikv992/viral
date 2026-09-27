"""Tabela de preços dos fornecedores (USD). Editável na UI (Configurações -> Preços).

A regra da casa: o grátis é o padrão; o pago só entra quando o ROI esperado o justifica.
"""
from __future__ import annotations

PRICES: dict[str, dict] = {
    # LLM (por 1M tokens)
    "llm:claude-opus-5": {"in": 5.00, "out": 25.00, "unit": "MTok"},
    "llm:claude-opus-5-5": {"in": 4.00, "out": 20.00, "unit": "MTok"},
    "llm:claude-sonnet-5": {"in": 2.00, "out": 10.00, "unit": "MTok"},
    "llm:claude-haiku-4-5": {"in": 1.00, "out": 5.00, "unit": "MTok"},
    # Voz
    "tts:edge": {"per_1k_chars": 0.0, "quality": 70, "label": "Edge TTS (grátis, neural)"},
    "tts:elevenlabs": {"per_1k_chars": 0.20, "quality": 95, "label": "ElevenLabs (premium)"},
    # Imagens IA (por imagem ~1MP)
    "img:procedural": {"per_image": 0.0, "quality": 35, "label": "Procedural local (grátis)"},
    "img:flux-schnell": {"per_image": 0.003, "quality": 72, "label": "Flux Schnell (fal.ai)"},
    "img:flux-dev": {"per_image": 0.025, "quality": 85, "label": "Flux Dev (fal.ai)"},
    "img:flux-pro": {"per_image": 0.04, "quality": 93, "label": "Flux Pro 1.1 (fal.ai) — thumbnails/branding"},
    # Vídeo IA (por segundo gerado)
    "vid:kling-std": {"per_second": 0.056, "quality": 82, "label": "Kling Standard (fal.ai)"},
    "vid:kling-pro": {"per_second": 0.098, "quality": 90, "label": "Kling Pro (fal.ai)"},
    "vid:veo-fast": {"per_second": 0.25, "quality": 95, "label": "Veo Fast c/ áudio (fal.ai)"},
    # Stock
    "stock:pexels": {"per_asset": 0.0, "quality": 75, "label": "Pexels (grátis)"},
    "stock:pixabay": {"per_asset": 0.0, "quality": 65, "label": "Pixabay (grátis)"},
    # Render local (energia/tempo) — custo simbólico por minuto de vídeo
    "render:local": {"per_minute": 0.002, "label": "Render ffmpeg local"},
}

FAL_ENDPOINTS = {
    "img:flux-schnell": "fal-ai/flux/schnell",
    "img:flux-dev": "fal-ai/flux/dev",
    "img:flux-pro": "fal-ai/flux-pro/v1.1",
    "vid:kling-std": "fal-ai/kling-video/v2.1/standard/text-to-video",
    "vid:kling-pro": "fal-ai/kling-video/v2.1/pro/text-to-video",
    "vid:veo-fast": "fal-ai/veo3/fast",
}


def llm_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    p = PRICES.get(f"llm:{model}", PRICES["llm:claude-opus-5"])
    return tokens_in / 1e6 * p["in"] + tokens_out / 1e6 * p["out"]


def price(key: str, field: str) -> float:
    return float(PRICES.get(key, {}).get(field, 0.0))
