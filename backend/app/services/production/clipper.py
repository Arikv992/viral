"""RECORTES: transforma vídeos longos licenciados em Shorts com valor original.

Regras de ferro (protegem o canal — um strike custa mais que qualquer poupança):
1. Só fontes com licença Creative Commons (CC-BY) ou com autorização explícita (`permission=True`,
   p.ex. conteúdo teu, domínio público, ou acordo com o criador).
2. Cada recorte leva gancho narrado original + título no ecrã + contexto + legendas (transformação),
   e a atribuição vai na descrição (obrigatória na CC-BY).
3. Transcrição via legendas do próprio YouTube (grátis) — sem custos de Whisper.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ... import prompts
from ...llm import INT, S, arr, get_llm, obj

log = logging.getLogger("viral.clipper")

CLIP_SCHEMA = obj({"clips": arr(obj({"start": {"type": "number"}, "end": {"type": "number"}, "why": S,
                                     "hook_text": S, "headline": S, "context": S, "virality": INT}))})


def _ydl(opts: dict):
    import yt_dlp

    base = {"quiet": True, "no_warnings": True, "noplaylist": True}
    return yt_dlp.YoutubeDL({**base, **opts})


def inspect(url: str) -> dict:
    with _ydl({"skip_download": True}) as y:
        info = y.extract_info(url, download=False)
    lic = (info.get("license") or "").lower()
    return {"url": url, "id": info.get("id"), "title": info.get("title"), "channel": info.get("channel") or
            info.get("uploader"), "channel_url": info.get("channel_url"), "duration": info.get("duration"),
            "license": info.get("license") or "standard", "is_cc": "creative commons" in lic,
            "has_subs": bool(info.get("subtitles") or info.get("automatic_captions")),
            "view_count": info.get("view_count"), "language": info.get("language")}


def parse_vtt(text: str) -> list[dict]:
    segs, cur = [], None
    for line in text.splitlines():
        m = re.match(r"(\d+):(\d+):(\d+\.\d+) --> (\d+):(\d+):(\d+\.\d+)", line)
        if m:
            h1, m1, s1, h2, m2, s2 = m.groups()
            cur = {"start": int(h1) * 3600 + int(m1) * 60 + float(s1),
                   "end": int(h2) * 3600 + int(m2) * 60 + float(s2), "text": ""}
            segs.append(cur)
        elif cur is not None and line.strip() and not line.startswith(("WEBVTT", "Kind:", "Language:")):
            clean = re.sub(r"<[^>]+>", "", line).strip()
            if clean:
                cur["text"] = (cur["text"] + " " + clean).strip()
    out: list[dict] = []
    for s in segs:  # legendas automáticas repetem linhas: remover sobreposições
        if not s["text"]:
            continue
        if out and (s["text"] == out[-1]["text"] or s["text"].startswith(out[-1]["text"])):
            out[-1]["end"] = s["end"]
            out[-1]["text"] = s["text"]
            continue
        out.append(dict(s))
    return out


def transcript(url: str, lang: str, work: Path) -> list[dict]:
    work.mkdir(parents=True, exist_ok=True)
    opts = {"skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
            "subtitleslangs": [lang, f"{lang}.*", "en"], "subtitlesformat": "vtt",
            "outtmpl": str(work / "src.%(ext)s")}
    with _ydl(opts) as y:
        y.download([url])
    vtts = sorted(work.glob("src*.vtt"))
    return parse_vtt(vtts[0].read_text(encoding="utf-8", errors="ignore")) if vtts else []


def download(url: str, work: Path) -> str:
    opts = {"format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b", "merge_output_format": "mp4",
            "outtmpl": str(work / "source.%(ext)s")}
    with _ydl(opts) as y:
        y.download([url])
    files = sorted(work.glob("source.*"))
    if not files:
        raise RuntimeError("download falhou")
    return str(files[0])


STRONG = re.compile(r"\b(never|nobody|secret|million|billion|dead|died|truth|actually|insane|crazy|impossible|"
                    r"first|last|only|biggest|worst|why|how|what|shocking|hidden|lie|lied|wrong|mistake)\b", re.I)


def heuristic_clips(segs: list[dict], count: int = 3, min_len: float = 25, max_len: float = 55) -> list[dict]:
    """Janela deslizante: densidade de palavras fortes, números e perguntas; sem sobreposição."""
    if not segs:
        return []
    cands = []
    for i, s in enumerate(segs):
        j, text, end = i, "", s["start"]
        while j < len(segs) and segs[j]["end"] - s["start"] <= max_len:
            text += " " + segs[j]["text"]
            end = segs[j]["end"]
            j += 1
        if end - s["start"] < min_len:
            continue
        words = max(len(text.split()), 1)
        score = (len(STRONG.findall(text)) * 3 + len(re.findall(r"\d", text)) + text.count("?") * 2) / words * 100
        score += 8 if STRONG.search(s["text"]) else 0  # começa forte
        cands.append({"start": s["start"], "end": end, "score": score, "text": text.strip()})
    cands.sort(key=lambda c: -c["score"])
    picked: list[dict] = []
    for c in cands:
        if all(c["end"] <= p["start"] or c["start"] >= p["end"] for p in picked):
            picked.append(c)
        if len(picked) >= count:
            break
    return [{"start": round(p["start"], 2), "end": round(p["end"], 2), "why": "densidade de ganchos (heurística)",
             "hook_text": "Wait for it...", "headline": " ".join(p["text"].split()[:5]).upper(),
             "context": p["text"][:120], "virality": int(min(100, p["score"] * 4))} for p in picked]


def select_clips(info: dict, segs: list[dict], angle: str, count: int = 3, video_id: int | None = None) -> list[dict]:
    lines = "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segs)[:60000]
    out = get_llm().json(system=prompts.SYSTEM,
                         prompt=prompts.CLIP_SELECTION.format(count=count, title=info.get("title"),
                                                              channel=info.get("channel"), license=info.get("license"),
                                                              angle=angle, transcript=lines),
                         schema=CLIP_SCHEMA, effort="medium", purpose="clip_selection", video_id=video_id)
    clips = out["clips"] if out else heuristic_clips(segs, count)
    valid = []
    dur = info.get("duration") or 1e9
    for c in clips:
        c["start"], c["end"] = max(0.0, float(c["start"])), min(float(c["end"]), dur)
        if 12 <= c["end"] - c["start"] <= 62:
            valid.append(c)
    return sorted(valid, key=lambda c: -c.get("virality", 0))[:count]


def words_in_range(segs: list[dict], start: float, end: float, offset: float) -> list[dict]:
    """Palavras com tempos (proporcionais dentro de cada segmento) deslocadas para a timeline do Short."""
    out = []
    for s in segs:
        if s["end"] <= start or s["start"] >= end:
            continue
        ws = s["text"].split()
        if not ws:
            continue
        d = (s["end"] - s["start"]) / len(ws)
        for k, w in enumerate(ws):
            t = s["start"] + k * d
            if start <= t < end:
                out.append({"word": w, "start": round(t - start + offset, 3), "end": round(t - start + offset + d, 3)})
    return out


def attribution(info: dict) -> str:
    return (f"Source: \"{info.get('title')}\" by {info.get('channel')} ({info.get('url')}) — "
            f"licensed under {info.get('license')}. Commentary, edit and narration are original.")


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False)
