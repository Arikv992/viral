"""Thumbnails de alto CTR: 1 ponto focal, 2-4 palavras enormes (nunca repetir o título), contraste máximo
contra a UI do YouTube, gradiente lateral para legibilidade, palavra-chave destacada a amarelo."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from ..imagegen import cover, draw_text_block, generate


def compose(bg_path: str, text: str, dest: Path, size=(1280, 720), accent=(255, 214, 0), side: str = "left") -> str:
    w, h = size
    img = cover(Image.open(bg_path).convert("RGB"), w, h)
    img = ImageEnhance.Contrast(img).enhance(1.25)
    img = ImageEnhance.Color(img).enhance(1.15)
    img = img.convert("RGBA")
    # gradiente escuro do lado do texto
    grad = Image.linear_gradient("L").rotate(90 if side == "left" else -90, expand=True).resize((w, h))
    grad = grad.point(lambda p: int(p * 0.85))
    dark = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    img = Image.composite(dark, img, grad)
    words = text.upper().split()
    hl = {max(words, key=len)} if words else set()
    box = (40, 60, int(w * 0.58), h - 60) if side == "left" else (int(w * 0.42), 60, w - 40, h - 60)
    draw_text_block(img, " ".join(words), box, fill=(255, 255, 255), stroke=(0, 0, 0), highlight=hl,
                    highlight_fill=accent, start=200)
    # moldura subtil para destacar no feed
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline=(*accent, 255), width=6)
    img = img.convert("RGB").filter(ImageFilter.UnsharpMask(radius=2, percent=80))
    img.save(dest, quality=95)
    return str(dest)


def make_thumbnail(packaging: dict, fmt: str, out_dir: Path, fallback_bg: str | None, tier: str,
                   palette: list[str] | None = None, video_id: int | None = None) -> str:
    th = packaging.get("thumbnail", {})
    text = th.get("text") or packaging.get("title", "")[:24]
    if fmt == "short":
        size = (1080, 1920)
    else:
        size = (1280, 720)
    bg = None
    prompt = th.get("image_prompt")
    if prompt:
        res = generate(prompt + ", dramatic, high contrast, single focal subject on the right, no text",
                       out_dir / "thumb_bg.jpg", *size, tier=tier, palette=palette, video_id=video_id)
        bg = res["path"] if res["provider"] != "img:procedural" or not fallback_bg else None
    bg = bg or fallback_bg
    if not bg:
        bg = generate(text, out_dir / "thumb_bg.jpg", *size, tier="img:procedural", palette=palette)["path"]
    return compose(bg, text, out_dir / "thumbnail.jpg", size=size)
