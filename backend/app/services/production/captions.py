"""Legendas ASS animadas.

Shorts: 1-3 palavras de cada vez, grandes, ao centro, palavra falada destacada a amarelo com "pop"
(o estilo que mais retém em vídeos curtos). Longos: frase inteira em baixo, discreta.
"""
from __future__ import annotations

from pathlib import Path


def _ts(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,Anton,{big},&H00FFFFFF,&H0000D7FF,&H00000000,&H96000000,0,0,0,0,100,100,1,0,1,{outline},3,5,60,60,0,1
Style: Line,Montserrat,{small},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,1,2,120,120,{mv},1
Style: Title,Anton,{title},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,1,0,1,6,3,8,60,60,{tv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

YELLOW = r"{\c&H00D7FF&}"
WHITE = r"{\c&HFFFFFF&}"


def build_ass(words: list[dict], fmt: str, dest: Path, overlays: list[dict] | None = None,
              group: int = 3) -> Path:
    """words: [{word,start,end}] em tempo absoluto do vídeo. overlays: [{text,start,end}] títulos no topo."""
    w, h = (1080, 1920) if fmt == "short" else (1920, 1080)
    lines = [HEADER.format(w=w, h=h, big=118 if fmt == "short" else 84, outline=7 if fmt == "short" else 5,
                           small=46, mv=70, title=96 if fmt == "short" else 72, tv=220 if fmt == "short" else 60)]
    if fmt == "short":
        # grupos curtos; a palavra atual acende a amarelo com pop de escala
        chunks = [words[i:i + group] for i in range(0, len(words), group)]
        for chunk in chunks:
            for j, cur in enumerate(chunk):
                start = cur["start"]
                end = chunk[j + 1]["start"] if j + 1 < len(chunk) else cur["end"] + 0.05
                parts = []
                for k, wd in enumerate(chunk):
                    txt = _esc(wd["word"]).upper()
                    parts.append(f"{YELLOW}{txt}{WHITE}" if k == j else txt)
                pop = r"{\an5\pos(%d,%d)\fscx112\fscy112\t(0,90,\fscx100\fscy100)}" % (w // 2, int(h * 0.62))
                lines.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Word,,0,0,0,,{pop}{' '.join(parts)}")
    else:
        # frases de até ~7 palavras em baixo
        chunk: list[dict] = []
        for wd in words:
            chunk.append(wd)
            if len(chunk) >= 7 or wd["word"].endswith((".", "?", "!")):
                lines.append(f"Dialogue: 0,{_ts(chunk[0]['start'])},{_ts(chunk[-1]['end'] + 0.1)},Line,,0,0,0,,"
                             f"{_esc(' '.join(x['word'] for x in chunk))}")
                chunk = []
        if chunk:
            lines.append(f"Dialogue: 0,{_ts(chunk[0]['start'])},{_ts(chunk[-1]['end'] + 0.1)},Line,,0,0,0,,"
                         f"{_esc(' '.join(x['word'] for x in chunk))}")
    for ov in overlays or []:
        if ov.get("text"):
            fade = r"{\fad(120,120)}"
            lines.append(f"Dialogue: 2,{_ts(ov['start'])},{_ts(ov['end'])},Title,,0,0,0,,{fade}{_esc(ov['text']).upper()}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest
