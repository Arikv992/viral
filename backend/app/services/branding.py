"""ESTÚDIO DE CANAL: kit de marca completo pronto a carregar no YouTube.

- Descrição SEO (primeiros 150 caracteres com a palavra-chave), keywords, tagline.
- Avatar 800×800 (legível a 48px), banner 2560×1440 com texto dentro da safe-area 1546×423
  (visível em TV, desktop e telemóvel), marca d'água 150×150.
- Trailer do canal e comentário fixado modelo.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .. import prompts
from ..config import get_settings
from ..db import session_scope, touch
from ..knowledge.niches import get_niche
from ..llm import S, arr, get_llm, obj
from ..models import Channel
from .imagegen import draw_text_block, font, generate, hex_rgb

BRAND_SCHEMA = obj({
    "tagline": S, "description": S, "keywords": arr(S), "palette": arr(S), "avatar_prompt": S,
    "banner_prompt": S, "banner_text": S, "watermark_text": S, "trailer_script": S, "first_comment_template": S,
})

NICHE_PALETTES = {
    "money": ["#0B0F0C", "#D4AF37", "#E8E6E1"], "mind": ["#0A0A0F", "#8B5CF6", "#E5E7EB"],
    "history": ["#0E0B08", "#B8860B", "#EDE3D1"], "science": ["#05070F", "#38BDF8", "#E0F2FE"],
    "crime": ["#0B0B0B", "#DC2626", "#F5F5F4"], "mystery": ["#07090B", "#14B8A6", "#E2E8F0"],
    "horror": ["#080506", "#9F1239", "#F1F5F9"], "world": ["#0A0C10", "#EAB308", "#F8FAFC"],
    "tech": ["#050810", "#22D3EE", "#F1F5F9"], "health": ["#06100D", "#10B981", "#ECFDF5"],
    "nature": ["#070B07", "#84CC16", "#F7FEE7"], "stories": ["#0B0710", "#F97316", "#FAFAF9"],
    "entertainment": ["#0B0710", "#F43F5E", "#FAFAF9"],
}


def brand_kit(channel: Channel) -> dict:
    niche = get_niche(channel.niche_key) or {}
    concept = channel.strategy.get("positioning") or niche.get("description", "")
    audience = channel.strategy.get("target_audience") or niche.get("audience", "")
    out = get_llm().json(system=prompts.SYSTEM,
                         prompt=prompts.BRANDING.format(name=channel.name, handle=channel.handle or channel.name,
                                                        concept=concept, language=channel.language,
                                                        audience=audience),
                         schema=BRAND_SCHEMA, effort="medium", purpose="branding", channel_id=channel.id)
    return out or heuristic_kit(channel, niche)


def heuristic_kit(channel: Channel, niche: dict) -> dict:
    pal = NICHE_PALETTES.get(niche.get("category", "mystery"), NICHE_PALETTES["mystery"])
    topic = niche.get("name", "stories")
    kw = niche.get("keywords", [])
    first = f"{channel.name}: {niche.get('description', '')}"
    return {
        "tagline": "The stories they never told you",
        "description": (f"{first[:150]}\n\nEvery week we uncover {', '.join(kw[:3])} and more — researched, "
                        "cinematic and straight to the point. No fluff, just the story.\n\n"
                        "New Shorts every day and a full documentary every week.\n"
                        "Subscribe and turn on notifications so you don't miss the next one."),
        "keywords": kw + [topic.lower(), "documentary", "explained", "faceless"],
        "palette": pal,
        "avatar_prompt": f"iconic minimal emblem symbolising {topic}, centered, dark background, cinematic rim light",
        "banner_prompt": f"wide atmospheric cinematic scene about {topic}, dark moody, volumetric light, no text",
        "banner_text": "Uncover what they never told you",
        "watermark_text": "SUBSCRIBE",
        "trailer_script": (f"What if everything you knew about {kw[0] if kw else 'this'} was only half the story? "
                           f"On {channel.name} we go where others stop. Every week, one story you won't forget. "
                           "Subscribe — the next one starts now."),
        "first_comment_template": "Which part surprised you the most? Tell me below 👇",
    }


def monogram(name: str) -> str:
    words = [w for w in name.replace("The ", "").split() if w]
    return (words[0][0] + (words[1][0] if len(words) > 1 else "")).upper() if words else "V"


def render_avatar(channel: Channel, kit: dict, out_dir: Path, tier: str) -> str:
    pal = kit.get("palette") or NICHE_PALETTES["mystery"]
    base = generate(kit["avatar_prompt"], out_dir / "avatar_bg.jpg", 800, 800, tier=tier, palette=pal,
                    channel_id=channel.id)
    img = Image.open(base["path"]).convert("RGBA")
    if base["provider"] == "img:procedural":
        # sem IA: emblema tipográfico forte (monograma) — legível a 48px
        d = ImageDraw.Draw(img)
        acc = hex_rgb(pal[1])
        d.ellipse([90, 90, 710, 710], outline=(*acc, 255), width=18)
        draw_text_block(img, monogram(channel.name), (170, 190, 630, 610), fill=hex_rgb(pal[2]), stroke=(0, 0, 0),
                        start=380)
    path = out_dir / "avatar.png"
    img.convert("RGB").save(path)
    return str(path)


def render_banner(channel: Channel, kit: dict, out_dir: Path, tier: str) -> str:
    pal = kit.get("palette") or NICHE_PALETTES["mystery"]
    base = generate(kit["banner_prompt"], out_dir / "banner_bg.jpg", 2560, 1440, tier=tier, palette=pal,
                    channel_id=channel.id)
    img = Image.open(base["path"]).convert("RGBA")
    # escurecer a faixa central para legibilidade
    band = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(band).rectangle([0, 560, 2560, 880], fill=(0, 0, 0, 120))
    img.alpha_composite(band)
    safe = (507, 509, 2053, 932)  # 1546×423 centrado
    x0, y0, x1, y1 = safe
    draw_text_block(img, channel.name.upper(), (x0 + 40, y0 + 20, x1 - 40, y0 + 270), fill=hex_rgb(pal[2]),
                    start=240)
    d = ImageDraw.Draw(img)
    sub = (kit.get("banner_text") or kit.get("tagline") or "").upper()
    f = font(64, "condensed")
    w = d.textlength(sub, font=f)
    d.text(((2560 - w) / 2, y0 + 290), sub, font=f, fill=hex_rgb(pal[1]))
    path = out_dir / "banner.png"
    img.convert("RGB").save(path)
    return str(path)


def render_watermark(channel: Channel, kit: dict, out_dir: Path) -> str:
    pal = kit.get("palette") or NICHE_PALETTES["mystery"]
    img = Image.new("RGBA", (150, 150), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 146, 146], fill=(*hex_rgb(pal[0]), 235), outline=(*hex_rgb(pal[1]), 255), width=6)
    draw_text_block(img, monogram(channel.name), (25, 30, 125, 120), fill=hex_rgb(pal[2]), start=80, shadow=False)
    path = out_dir / "watermark.png"
    img.save(path)
    return str(path)


def build_channel_branding(channel_id: int, premium: bool = False) -> dict:
    """Gera (ou regenera) o kit completo e grava no canal."""
    with session_scope() as s:
        channel = s.get(Channel, channel_id)
        if not channel:
            raise ValueError("canal não encontrado")
    kit = brand_kit(channel)
    out_dir = get_settings().media_dir / "channels" / str(channel.id)
    out_dir.mkdir(parents=True, exist_ok=True)
    tier = "img:flux-pro" if premium else "img:flux-dev"
    kit["avatar_path"] = render_avatar(channel, kit, out_dir, tier)
    kit["banner_path"] = render_banner(channel, kit, out_dir, tier)
    kit["watermark_path"] = render_watermark(channel, kit, out_dir)
    with session_scope() as s:
        ch = s.get(Channel, channel_id)
        ch.branding = kit
        touch(ch, "branding")
        s.add(ch)
        s.commit()
    return kit
