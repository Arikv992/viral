"""Imagens: fal.ai (Flux) quando compensa, arte procedural local (grátis) quando não.

Também contém utilitários de tipografia partilhados (thumbnails, banners, legendas)."""
from __future__ import annotations

import hashlib
import logging
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import get_settings
from ..knowledge.providers import FAL_ENDPOINTS, price
from .finance import book_cost, can_spend
from .http import client, download

log = logging.getLogger("viral.image")
FONTS = Path(__file__).resolve().parents[1] / "assets" / "fonts"


def font(size: int, kind: str = "display") -> ImageFont.FreeTypeFont:
    files = {"display": "Anton-Regular.ttf", "condensed": "BebasNeue-Regular.ttf", "body": "Montserrat.ttf",
             "oswald": "Oswald.ttf"}
    path = FONTS / files.get(kind, files["display"])
    try:
        f = ImageFont.truetype(str(path), size)
        if kind == "body":
            try:
                f.set_variation_by_name("ExtraBold")
            except Exception:  # noqa: BLE001
                pass
        return f
    except OSError:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)


def hex_rgb(h: str, fallback=(20, 20, 24)) -> tuple[int, int, int]:
    h = (h or "").lstrip("#")
    if len(h) != 6:
        return fallback
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def fit_text(draw: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int, kind: str = "display",
             start: int = 220, min_size: int = 18) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Maior tamanho de letra em que o texto (com quebra de linha) cabe na caixa."""
    words = text.split()
    size = start
    while size >= min_size:
        f = font(size, kind)
        lines: list[str] = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            if draw.textlength(test, font=f) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        line_h = f.getbbox("Ag")[3] * 1.08
        if len(lines) * line_h <= max_h and all(draw.textlength(li, font=f) <= max_w for li in lines):
            return f, lines
        size = int(size * 0.92)
    return font(min_size, kind), [text]


def draw_text_block(img: Image.Image, text: str, box: tuple[int, int, int, int], fill=(255, 255, 255),
                    stroke=(0, 0, 0), kind: str = "display", align: str = "center", highlight: set[str] | None = None,
                    highlight_fill=(255, 214, 0), shadow: bool = True, start: int = 220) -> None:
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    f, lines = fit_text(d, text, x1 - x0, y1 - y0, kind, start=start)
    line_h = int(f.getbbox("Ag")[3] * 1.08)
    total = line_h * len(lines)
    y = y0 + (y1 - y0 - total) // 2
    sw = max(2, f.size // 14)
    for line in lines:
        lw = d.textlength(line, font=f)
        x = x0 + (x1 - x0 - lw) / 2 if align == "center" else x0
        if shadow and img.mode == "RGBA":
            sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).text((x + sw, y + sw), line, font=f, fill=(0, 0, 0, 200))
            img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(sw)))
        cx = x
        for wi, word in enumerate(line.split(" ")):
            token = word + (" " if wi < len(line.split(" ")) - 1 else "")
            col = highlight_fill if highlight and word.strip(".,!?").upper() in highlight else fill
            d.text((cx, y), token, font=f, fill=col, stroke_width=sw, stroke_fill=stroke)
            cx += d.textlength(token, font=f)
        y += line_h


def vignette(img: Image.Image, strength: float = 0.75) -> Image.Image:
    w, h = img.size
    dark = Image.new(img.mode, img.size, (0, 0, 0, 255) if img.mode == "RGBA" else (0, 0, 0))
    edge = Image.radial_gradient("L").resize((w, h))
    edge = edge.point(lambda p: int(min(255, p * strength * 1.1)))
    return Image.composite(dark, img, edge)


def procedural(prompt: str, width: int, height: int, palette: list[str] | None = None) -> Image.Image:
    """Arte abstrata escura determinística a partir do prompt: gradiente, névoa, partículas, forma central.
    Serve como placeholder de qualidade decente e custo zero."""
    seed = int(hashlib.sha256(prompt.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    pal = [hex_rgb(c) for c in (palette or [])] or [
        (8, 8, 12), rng.choice([(150, 20, 30), (20, 90, 160), (190, 140, 30), (90, 30, 140), (20, 130, 110)]),
        (230, 230, 235)]
    bg, accent = pal[0], pal[1]
    sw, sh = max(width // 4, 64), max(height // 4, 64)
    img = Image.new("RGB", (sw, sh), bg)
    px = img.load()
    cx, cy = rng.uniform(0.3, 0.7) * sw, rng.uniform(0.3, 0.6) * sh
    for y in range(sh):
        for x in range(sw):
            dist = math.hypot((x - cx) / sw, (y - cy) / sh)
            glow = max(0.0, 1 - dist * 1.8) ** 2
            n = (math.sin(x * 0.05 + seed % 7) + math.cos(y * 0.07 + seed % 11)) * 0.04
            t = max(0.0, min(1.0, glow + n))
            px[x, y] = tuple(int(bg[i] * (1 - t) + accent[i] * t) for i in range(3))
    img = img.resize((width, height), Image.BICUBIC).convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # partículas / poeira
    for _ in range(int(width * height / 9000)):
        x, y = rng.uniform(0, width), rng.uniform(0, height)
        r = rng.uniform(0.5, 2.2) * width / 1280
        d.ellipse([x - r, y - r, x + r, y + r], fill=(*pal[-1], rng.randint(20, 110)))
    # silhueta central (monólito/portal/lua) para dar ponto focal
    shape = seed % 3
    s = min(width, height)
    if shape == 0:
        d.ellipse([cx * 4 - s * 0.16, cy * 4 - s * 0.16, cx * 4 + s * 0.16, cy * 4 + s * 0.16],
                  fill=(*pal[-1], 38), outline=(*accent, 160), width=max(2, s // 180))
    elif shape == 1:
        d.rectangle([cx * 4 - s * 0.05, cy * 4 - s * 0.28, cx * 4 + s * 0.05, height], fill=(0, 0, 0, 200))
    else:
        d.polygon([(cx * 4, cy * 4 - s * 0.25), (cx * 4 - s * 0.2, height), (cx * 4 + s * 0.2, height)],
                  fill=(0, 0, 0, 185))
    layer = layer.filter(ImageFilter.GaussianBlur(max(1, width // 900)))
    img.alpha_composite(layer)
    # horizonte / nevoeiro
    fog = Image.linear_gradient("L").resize((width, height)).point(lambda p: int(p * 0.55))
    img = Image.composite(Image.new("RGBA", img.size, (*bg, 255)), img, fog)
    return vignette(img.convert("RGB"), 0.8)


def fal_generate(model_key: str, prompt: str, width: int, height: int) -> str | None:
    key = get_settings().fal_api_key
    endpoint = FAL_ENDPOINTS.get(model_key)
    if not key or not endpoint:
        return None
    body = {"prompt": prompt, "image_size": {"width": width, "height": height}, "num_images": 1,
            "enable_safety_checker": True}
    try:
        r = client().post(f"https://fal.run/{endpoint}", json=body, headers={"Authorization": f"Key {key}"},
                          timeout=180.0)
        if r.status_code != 200:
            log.warning("fal %s -> %s %s", endpoint, r.status_code, r.text[:300])
            return None
        imgs = r.json().get("images") or []
        return imgs[0]["url"] if imgs else None
    except Exception as e:  # noqa: BLE001
        log.warning("fal falhou: %s", e)
        return None


def generate(prompt: str, dest: Path, width: int, height: int, tier: str = "img:flux-schnell",
             palette: list[str] | None = None, channel_id: int | None = None, video_id: int | None = None) -> dict:
    """Gera uma imagem. Tier pago só se houver chave e orçamento; senão procedural."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cost = price(tier, "per_image")
    if tier != "img:procedural" and get_settings().fal_api_key and can_spend(cost):
        # fal trabalha em múltiplos de 8/16; pedimos aproximado e recortamos
        gw, gh = _fal_size(width, height)
        url = fal_generate(tier, prompt, gw, gh)
        if url:
            tmp = dest.with_suffix(".src")
            if download(url, tmp):
                im = Image.open(tmp).convert("RGB")
                cover(im, width, height).save(dest, quality=94)
                tmp.unlink(missing_ok=True)
                book_cost("image", cost, memo=f"{tier}: {prompt[:80]}", channel_id=channel_id, video_id=video_id)
                return {"path": str(dest), "provider": tier, "cost": cost}
    procedural(prompt, width, height, palette).save(dest, quality=92)
    return {"path": str(dest), "provider": "img:procedural", "cost": 0.0}


def _fal_size(w: int, h: int) -> tuple[int, int]:
    scale = min(1.0, 1440 / max(w, h))
    return int(w * scale) // 16 * 16, int(h * scale) // 16 * 16


def cover(im: Image.Image, w: int, h: int) -> Image.Image:
    """Redimensiona e recorta ao centro para preencher w×h (como CSS object-fit: cover)."""
    r = max(w / im.width, h / im.height)
    im = im.resize((max(w, int(im.width * r + 0.5)), max(h, int(im.height * r + 0.5))), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))
