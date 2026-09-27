"""Utilitários ffmpeg (binário embutido via imageio-ffmpeg: funciona sem instalação no sistema)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


class FFmpegError(RuntimeError):
    pass


def run(args: list[str], timeout: int = 1800) -> str:
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise FFmpegError(f"ffmpeg falhou ({p.returncode}): {p.stderr[-1500:]}\nCMD: {' '.join(cmd)[:800]}")
    return p.stderr


def duration(path: str | Path) -> float:
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", p.stderr)
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def has_audio(path: str | Path) -> bool:
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    return "Audio:" in p.stderr


def silence(dest: Path, seconds: float) -> Path:
    run(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{seconds:.3f}", "-c:a", "pcm_s16le", dest])
    return dest


def to_wav(src: Path, dest: Path, pad_end: float = 0.0) -> Path:
    af = f"apad=pad_dur={pad_end:.3f}" if pad_end > 0 else "anull"
    run(["-i", src, "-af", af, "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", dest])
    return dest


def concat_audio(parts: list[Path], dest: Path) -> Path:
    lst = dest.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    run(["-f", "concat", "-safe", "0", "-i", lst, "-c:a", "pcm_s16le", dest])
    return dest
