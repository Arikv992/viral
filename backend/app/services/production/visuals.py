"""Visual de cada cena: stock grátis, imagem IA, vídeo IA ou arte procedural — por ordem de ROI."""
from __future__ import annotations

import logging
import random
import time
from pathlib import Path

from ...config import get_settings
from ...knowledge.providers import FAL_ENDPOINTS, price
from ..finance import book_cost, can_spend
from ..http import client, download, get_json
from ..imagegen import generate as gen_image

log = logging.getLogger("viral.visuals")


def dims(fmt: str) -> tuple[int, int]:
    return (1080, 1920) if fmt == "short" else (1920, 1080)


def pexels_video(query: str, fmt: str, used: set[str]) -> str | None:
    key = get_settings().pexels_api_key
    if not key:
        return None
    data = get_json("https://api.pexels.com/videos/search",
                    {"query": query, "orientation": "portrait" if fmt == "short" else "landscape", "per_page": 10},
                    headers={"Authorization": key}, ttl=86400) or {}
    need = 1080 if fmt == "short" else 1920
    for v in data.get("videos", []):
        if f"pexels:{v['id']}" in used:
            continue
        files = sorted((f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4"),
                       key=lambda f: (max(f.get("width") or 0, f.get("height") or 0) < need,
                                      (f.get("width") or 0) * (f.get("height") or 0)))
        if files:
            used.add(f"pexels:{v['id']}")
            return files[0]["link"]
    return None


def pixabay_video(query: str, used: set[str]) -> str | None:
    key = get_settings().pixabay_api_key
    if not key:
        return None
    data = get_json("https://pixabay.com/api/videos/", {"key": key, "q": query, "per_page": 10, "safesearch": "true"},
                    ttl=86400) or {}
    for h in data.get("hits", []):
        if f"pixabay:{h['id']}" in used:
            continue
        vids = h.get("videos", {})
        best = vids.get("large") or vids.get("medium")
        if best and best.get("url"):
            used.add(f"pixabay:{h['id']}")
            return best["url"]
    return None


def pexels_photo(query: str, fmt: str, used: set[str]) -> str | None:
    key = get_settings().pexels_api_key
    if not key:
        return None
    data = get_json("https://api.pexels.com/v1/search",
                    {"query": query, "orientation": "portrait" if fmt == "short" else "landscape", "per_page": 10},
                    headers={"Authorization": key}, ttl=86400) or {}
    for p in data.get("photos", []):
        if f"pexphoto:{p['id']}" not in used:
            used.add(f"pexphoto:{p['id']}")
            return p["src"].get("large2x") or p["src"]["original"]
    return None


def fal_video(prompt: str, fmt: str, dest: Path, tier: str = "vid:kling-std", video_id: int | None = None,
              seconds: int = 5) -> str | None:
    key = get_settings().fal_api_key
    cost = seconds * price(tier, "per_second")
    if not key or not can_spend(cost):
        return None
    hdr = {"Authorization": f"Key {key}"}
    try:
        r = client().post(f"https://queue.fal.run/{FAL_ENDPOINTS[tier]}", headers=hdr, timeout=60.0,
                          json={"prompt": prompt, "duration": str(seconds),
                                "aspect_ratio": "9:16" if fmt == "short" else "16:9"})
        if r.status_code not in (200, 201, 202):
            log.warning("fal video %s: %s", r.status_code, r.text[:200])
            return None
        job = r.json()
        deadline = time.time() + 600
        while time.time() < deadline:
            st = client().get(job["status_url"], headers=hdr, timeout=30.0).json()
            if st.get("status") == "COMPLETED":
                break
            if st.get("status") in ("FAILED", "ERROR"):
                return None
            time.sleep(6)
        else:
            return None
        res = client().get(job["response_url"], headers=hdr, timeout=60.0).json()
        url = (res.get("video") or {}).get("url")
        if url and download(url, dest):
            book_cost("video_ai", cost, memo=f"{tier}: {prompt[:60]}", video_id=video_id)
            return str(dest)
    except Exception as e:  # noqa: BLE001
        log.warning("fal video falhou: %s", e)
    return None


def background_loop(fmt: str, used: set[str], out_dir: Path) -> str | None:
    """Fundo para text_story: ficheiros teus em data/backgrounds (gameplay/satisfying) ou stock."""
    bg_dir = get_settings().data_dir / "backgrounds"
    files = sorted(bg_dir.glob("*.mp4")) if bg_dir.exists() else []
    if files:
        return str(random.choice(files))
    url = pexels_video("abstract dark loop", fmt, used) or pixabay_video("dark abstract background", used)
    if url:
        dest = out_dir / "bg_loop.mp4"
        if download(url, dest):
            return str(dest)
    return None


def scene_visual(scene: dict, idx: int, mode: str, fmt: str, out_dir: Path, upgrades: dict, palette: list[str],
                 used: set[str], video_id: int | None = None, n_scenes: int = 1) -> dict:
    w, h = dims(fmt)
    q = scene.get("stock_query") or "dark cinematic"
    vprompt = scene.get("visual_prompt") or q
    style = ", cinematic, dark moody lighting, high detail, film grain, no text, no watermark"
    ai_share = upgrades.get("ai_video_share", 0.0)
    if ai_share > 0 and idx < max(1, round(n_scenes * ai_share)):
        p = fal_video(vprompt + style, fmt, out_dir / f"scene_{idx:03d}.mp4", video_id=video_id)
        if p:
            return {"type": "video", "path": p, "provider": "vid:kling-std"}
    if mode in ("stock_narrated", "clip_commentary"):
        url = pexels_video(q, fmt, used) or pixabay_video(q, used)
        if url:
            dest = out_dir / f"scene_{idx:03d}.mp4"
            if download(url, dest):
                return {"type": "video", "path": str(dest), "provider": "stock_video"}
        url = pexels_photo(q, fmt, used)
        if url:
            dest = out_dir / f"scene_{idx:03d}.jpg"
            if download(url, dest):
                return {"type": "image", "path": str(dest), "provider": "stock_photo"}
    tier = upgrades.get("image_tier", "img:flux-schnell") if mode in ("ai_images_narrated", "ai_video_full",
                                                                     "stock_narrated") else "img:procedural"
    res = gen_image(vprompt + style, out_dir / f"scene_{idx:03d}.jpg", w, h, tier=tier, palette=palette,
                    video_id=video_id)
    if res["provider"] == "img:procedural" and mode == "ai_images_narrated":
        url = pexels_photo(q, fmt, used)
        if url:
            dest = out_dir / f"scene_{idx:03d}_s.jpg"
            if download(url, dest):
                return {"type": "image", "path": str(dest), "provider": "stock_photo"}
    return {"type": "image", "path": res["path"], "provider": res["provider"]}
