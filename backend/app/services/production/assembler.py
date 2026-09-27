"""Montagem final com ffmpeg: cenas (Ken Burns / vídeo recortado) -> concat -> voz + música com ducking
-> legendas animadas -> marca d'água -> loudness -14 LUFS (padrão YouTube) -> H.264/AAC."""
from __future__ import annotations

import random
from pathlib import Path

from ...config import get_settings
from ..imagegen import FONTS
from . import media

FPS = 30


def render_image_scene(img: str, dur: float, dest: Path, w: int, h: int, idx: int) -> Path:
    frames = max(1, int(dur * FPS))
    # zoom lento para dentro/fora e pan alternados — movimento contínuo = mais retenção
    z_in = idx % 2 == 0
    zexpr = f"min(1+0.0009*on,1.18)" if z_in else f"max(1.18-0.0009*on,1.0)"
    xexpr = "iw/2-(iw/zoom/2)" if idx % 3 else "(iw-iw/zoom)*on/{f}".format(f=frames)
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='{zexpr}':x='{xexpr}':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS},"
          "eq=contrast=1.06:saturation=0.9,setsar=1,format=yuv420p")
    media.run(["-loop", "1", "-i", img, "-t", f"{dur:.3f}", "-vf", vf, "-r", FPS, "-an", "-c:v", "libx264",
               "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", dest])
    return dest


def render_video_scene(src: str, dur: float, dest: Path, w: int, h: int, start: float = 0.0) -> Path:
    src_dur = media.duration(src)
    if src_dur and start >= src_dur:
        start = start % src_dur
    loop = ["-stream_loop", "-1"] if src_dur and src_dur < dur + start else []
    ss = ["-ss", f"{start:.3f}"] if start > 0 else []
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},setsar=1,"
          "eq=contrast=1.05:saturation=0.92,format=yuv420p")
    media.run([*loop, *ss, "-i", src, "-t", f"{dur:.3f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "20", "-pix_fmt", "yuv420p", dest])
    return dest


def render_clip_vertical(src: str, start: float, end: float, dest: Path) -> Path:
    """Recorte 16:9 -> 9:16 com fundo desfocado (mantém o enquadramento original inteiro) e com áudio."""
    dur = end - start
    fc = ("[0:v]split=2[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
          "boxblur=30:5,eq=brightness=-0.12[bg];[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,"
          f"fps={FPS},setsar=1,format=yuv420p[v]")
    media.run(["-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}", "-filter_complex", fc, "-map", "[v]",
               "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-ar", "44100",
               "-ac", "2", dest])
    return dest


def concat_video(parts: list[Path], dest: Path) -> Path:
    lst = dest.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    media.run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", dest])
    return dest


def music_track(dur: float, dest: Path, mood: str = "dark") -> Path:
    """Música: ficheiros teus em data/music/<mood>/ ou data/music/ (royalty-free: YouTube Audio Library),
    senão um 'drone' ambiente escuro sintetizado (grátis, sem risco de Content ID)."""
    mdir = get_settings().data_dir / "music"
    files = sorted((mdir / mood).glob("*.mp3")) + sorted(mdir.glob("*.mp3")) if mdir.exists() else []
    if files:
        src = random.choice(files)
        media.run(["-stream_loop", "-1", "-i", src, "-t", f"{dur:.3f}", "-af",
                   f"afade=t=in:d=1.5,afade=t=out:st={max(dur - 2.5, 0):.2f}:d=2.5", "-ar", "44100", "-ac", "2", dest])
        return dest
    base = random.choice([41.2, 43.65, 46.25, 49.0, 55.0])
    fc = (f"sine=f={base}:r=44100[s1];sine=f={base * 1.5:.2f}:r=44100[s2];sine=f={base * 2.38:.2f}:r=44100[s3];"
          "anoisesrc=c=brown:a=0.08:r=44100[n];"
          "[s1][s2][s3][n]amix=inputs=4:weights=1 0.5 0.18 0.6,lowpass=f=900,"
          "tremolo=f=0.12:d=0.5,aecho=0.8:0.7:420|780:0.35|0.25,"
          f"afade=t=in:d=3,afade=t=out:st={max(dur - 3, 0):.2f}:d=3,volume=0.9,aformat=channel_layouts=stereo[out]")
    media.run(["-filter_complex", fc, "-map", "[out]", "-t", f"{dur:.3f}", "-ar", "44100", dest])
    return dest


def final_mix(video: Path, voice: Path | None, music: Path | None, ass: Path | None, dest: Path,
              watermark: str | None = None, fmt: str = "short", music_gain: float = 0.18,
              keep_video_audio: bool = False) -> Path:
    inputs = ["-i", video]
    idx = 1
    a_labels = []
    fc_parts = []
    if keep_video_audio:
        fc_parts.append("[0:a]volume=1.0[va]")
        a_labels.append("[va]")
    vi = vo = None
    if voice:
        inputs += ["-i", voice]
        vi = idx
        idx += 1
    if music:
        inputs += ["-i", music]
        mi = idx
        idx += 1
        if vi is not None:
            # ducking: a música baixa automaticamente quando a voz fala
            fc_parts.append(f"[{vi}:a]asplit=2[vo][vsc]")
            fc_parts.append(f"[{mi}:a]volume={music_gain}[mu]")
            fc_parts.append("[mu][vsc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck]")
            a_labels += ["[vo]", "[duck]"]
            vo = True
        else:
            fc_parts.append(f"[{mi}:a]volume={music_gain * 2}[mu]")
            a_labels.append("[mu]")
    if voice and not vo:
        a_labels.append(f"[{vi}:a]")
    wm_idx = None
    if watermark and Path(watermark).exists():
        inputs += ["-i", watermark]
        wm_idx = idx
        idx += 1
    # vídeo: legendas + marca d'água
    vchain = "[0:v]"
    if ass:
        esc = str(ass).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        fonts = str(FONTS).replace(":", "\\:")
        fc_parts.append(f"{vchain}subtitles='{esc}':fontsdir='{fonts}'[vs]")
        vchain = "[vs]"
    if wm_idx is not None:
        size = 110 if fmt == "short" else 120
        pos = "W-w-40:H-h-360" if fmt == "short" else "W-w-40:H-h-40"
        fc_parts.append(f"[{wm_idx}:v]scale={size}:{size},format=rgba,colorchannelmixer=aa=0.55[wm]")
        fc_parts.append(f"{vchain}[wm]overlay={pos}[vw]")
        vchain = "[vw]"
    if len(a_labels) > 1:
        fc_parts.append(f"{''.join(a_labels)}amix=inputs={len(a_labels)}:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    elif a_labels:
        fc_parts.append(f"{a_labels[0]}loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    args = [*inputs, "-filter_complex", ";".join(fc_parts) if fc_parts else "null", "-map",
            vchain if vchain != "[0:v]" else "0:v"]
    if a_labels:
        args += ["-map", "[aout]"]
    args += ["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-profile:v", "high",
             "-movflags", "+faststart", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", dest]
    media.run(args, timeout=7200)
    return dest
