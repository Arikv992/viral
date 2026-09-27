"""Voz. Cadeia: ElevenLabs (premium, só quando o Planner o autoriza) -> Edge TTS (grátis, timestamps
por palavra) -> Piper (neural local, grátis, offline) -> silêncio com tempos estimados (nunca falha).

Sintetiza CENA A CENA: dá durações exatas por cena (sincronia perfeita imagem/voz) e timestamps
por palavra para as legendas animadas."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
import wave
from pathlib import Path

from ...config import get_settings
from ...knowledge.providers import price
from ..finance import book_cost
from ..http import client, download
from . import media

log = logging.getLogger("viral.tts")

EDGE_VOICES = {
    "en": "en-US-ChristopherNeural", "pt": "pt-BR-AntonioNeural", "pt-PT": "pt-PT-DuarteNeural",
    "es": "es-MX-JorgeNeural", "de": "de-DE-ConradNeural", "fr": "fr-FR-HenriNeural", "it": "it-IT-DiegoNeural",
}
PIPER_VOICES = {
    "en": ("en/en_US/ryan/high", "en_US-ryan-high"), "pt": ("pt/pt_BR/faber/medium", "pt_BR-faber-medium"),
    "es": ("es/es_MX/claude/high", "es_MX-claude-high"), "de": ("de/de_DE/thorsten/high", "de_DE-thorsten-high"),
    "fr": ("fr/fr_FR/siwis/medium", "fr_FR-siwis-medium"),
}


def proportional_words(text: str, dur: float, offset: float = 0.0) -> list[dict]:
    words = text.split()
    total = sum(len(w) + 1 for w in words) or 1
    t, out = offset, []
    for w in words:
        d = dur * (len(w) + 1) / total
        out.append({"word": w, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


# ------------------------------------------------------------------ provedores
def _edge(text: str, lang: str, dest: Path) -> list[dict] | None:
    try:
        import edge_tts
    except ImportError:
        return None
    voice = EDGE_VOICES.get(lang, EDGE_VOICES["en"])
    words: list[dict] = []

    async def go():
        c = edge_tts.Communicate(text, voice, rate="-4%", pitch="-3Hz", boundary="WordBoundary",
                                 proxy=os.environ.get("HTTPS_PROXY") or None)
        with open(dest, "wb") as f:
            async for ch in c.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    st = ch["offset"] / 1e7
                    words.append({"word": ch["text"], "start": round(st, 3), "end": round(st + ch["duration"] / 1e7, 3)})

    try:
        asyncio.run(go())
    except Exception as e:  # noqa: BLE001
        log.info("edge-tts indisponível: %s", e)
        return None
    return words if dest.exists() and dest.stat().st_size > 1000 else None


def _elevenlabs(text: str, dest: Path, video_id: int | None) -> list[dict] | None:
    s = get_settings()
    if not s.elevenlabs_api_key:
        return None
    try:
        r = client().post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{s.elevenlabs_voice_id}/with-timestamps",
            headers={"xi-api-key": s.elevenlabs_api_key},
            json={"text": text, "model_id": "eleven_multilingual_v2",
                  "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35}}, timeout=120.0)
        if r.status_code != 200:
            log.warning("elevenlabs %s: %s", r.status_code, r.text[:200])
            return None
        data = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("elevenlabs falhou: %s", e)
        return None
    dest.write_bytes(base64.b64decode(data["audio_base64"]))
    book_cost("tts", len(text) / 1000 * price("tts:elevenlabs", "per_1k_chars"), memo="elevenlabs", video_id=video_id)
    al = data.get("alignment") or {}
    chars, st, en = al.get("characters", []), al.get("character_start_times_seconds", []), \
        al.get("character_end_times_seconds", [])
    words, cur, cs = [], "", None
    for c, a, b in zip(chars, st, en):
        if c.isspace():
            if cur:
                words.append({"word": cur, "start": cs, "end": prev_end})
            cur, cs = "", None
        else:
            if cs is None:
                cs = a
            cur += c
            prev_end = b
    if cur:
        words.append({"word": cur, "start": cs, "end": prev_end})
    return words


_piper_cache: dict = {}
_down: dict[str, float] = {}  # provedor -> instante até ao qual fica ignorado (evita timeouts em série)


def _piper(text: str, lang: str, dest: Path) -> list[dict] | None:
    try:
        from piper import PiperVoice
    except ImportError:
        return None
    rel, name = PIPER_VOICES.get(lang, PIPER_VOICES["en"])
    vdir = get_settings().data_dir / "voices"
    vdir.mkdir(parents=True, exist_ok=True)
    model = vdir / f"{name}.onnx"
    if not model.exists():
        base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{rel}/{name}"
        if not (download(base + ".onnx", model) and download(base + ".onnx.json", vdir / f"{name}.onnx.json")):
            model.unlink(missing_ok=True)
            return None
    try:
        voice = _piper_cache.get(name) or PiperVoice.load(str(model))
        _piper_cache[name] = voice
        with wave.open(str(dest), "wb") as wf:
            voice.synthesize_wav(text, wf)
    except Exception as e:  # noqa: BLE001
        log.warning("piper falhou: %s", e)
        return None
    return proportional_words(text, media.duration(dest))


def synth_scene(text: str, lang: str, dest_wav: Path, voice: str = "tts:edge", video_id: int | None = None,
                gap: float = 0.12) -> dict:
    """Devolve {path, duration, words, provider}. O wav final inclui uma pequena pausa no fim."""
    raw = dest_wav.with_suffix(".raw")
    chain = (["elevenlabs"] if voice == "tts:elevenlabs" else []) + ["edge", "piper"]
    for prov in chain:
        if _down.get(prov, 0) > time.time():
            continue
        if prov == "elevenlabs":
            words = _elevenlabs(text, raw, video_id)
        elif prov == "edge":
            words = _edge(text, lang, raw)
        else:
            words = _piper(text, lang, raw)
        if words is not None and raw.exists():
            media.to_wav(raw, dest_wav, pad_end=gap)
            raw.unlink(missing_ok=True)
            dur = media.duration(dest_wav)
            if not words:
                words = proportional_words(text, dur - gap)
            return {"path": str(dest_wav), "duration": dur, "words": words, "provider": prov}
        _down[prov] = time.time() + 600
    # último recurso: silêncio com o tempo que a narração levaria (2.6 palavras/s)
    dur = max(1.2, len(text.split()) / 2.6) + gap
    media.silence(dest_wav, dur)
    return {"path": str(dest_wav), "duration": dur, "words": proportional_words(text, dur - gap),
            "provider": "silent"}
