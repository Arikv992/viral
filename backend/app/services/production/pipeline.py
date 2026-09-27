"""Orquestrador da FÁBRICA: ideia -> plano -> guião -> packaging -> compliance -> voz + visuais ->
montagem -> thumbnail -> compliance final -> pronto a publicar."""
from __future__ import annotations

import logging
import os
import shutil
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ...config import get_settings
from ...db import session_scope, touch
from ...models import Channel, Idea, Video, now
from .. import compliance
from ..imagegen import generate as gen_image
from . import assembler, captions, clipper, media, planner, script as scripting, thumbnails, tts, visuals

log = logging.getLogger("viral.pipeline")
WORKERS = max(2, (os.cpu_count() or 2) // 2)


def _log(video_id: int, msg: str, **fields) -> None:
    with session_scope() as s:
        v = s.get(Video, video_id)
        if not v:
            return
        v.log = [*(v.log or []), {"at": now().isoformat(timespec="seconds"), "msg": msg}]
        for k, val in fields.items():
            setattr(v, k, val)
        touch(v, "log", *[k for k in fields if k in ("plan", "script", "packaging", "compliance", "source")])
        s.add(v)
        s.commit()
    log.info("video %s: %s", video_id, msg)


def _channel_dict(ch: Channel) -> dict:
    return {"id": ch.id, "name": ch.name, "language": ch.language, "niche": ch.niche_key,
            "positioning": ch.strategy.get("positioning", ""), "style": ch.strategy.get("signature_style", ""),
            "pillars": ch.strategy.get("content_pillars", [])}


def plan_idea(idea_id: int, force_mode: str | None = None) -> Video:
    with session_scope() as s:
        idea = s.get(Idea, idea_id)
        ch = s.get(Channel, idea.channel_id) if idea else None
        if not idea or not ch:
            raise ValueError("ideia/canal não encontrado")
        p = planner.plan(idea.scores, idea.format, ch.niche_key,
                         channel_monetized=bool(ch.strategy.get("monetized")),
                         channel_budget_share=ch.monthly_budget_share or 1.0, force_mode=force_mode)
        v = Video(idea_id=idea.id, channel_id=ch.id, format=idea.format, mode=p["mode"], plan=p, status="planned")
        idea.status = "producing"
        s.add(v)
        s.add(idea)
        s.commit()
        s.refresh(v)
    return v


def produce(video_id: int, render: bool = True) -> Video:
    try:
        return _produce(video_id, render)
    except Exception as e:  # noqa: BLE001
        _log(video_id, f"ERRO: {e}", status="failed")
        log.error(traceback.format_exc())
        raise


def _produce(video_id: int, render: bool) -> Video:
    with session_scope() as s:
        v = s.get(Video, video_id)
        idea = s.get(Idea, v.idea_id)
        ch = s.get(Channel, v.channel_id)
    chd = _channel_dict(ch)
    plan = v.plan
    seconds = plan["target_seconds"]
    _log(video_id, f"Plano: {plan['why']}", status="scripting")

    idea_d = {"title": idea.title, "hook": idea.hook, "angle": idea.angle, "pillar": idea.pillar}
    sc = scripting.write_script(idea_d, chd, v.format, v.mode, seconds, video_id=video_id)
    pk = scripting.package(sc, chd, v.format, video_id=video_id)
    _log(video_id, f"Guião ({sc['source']}): {len(sc['scenes'])} cenas, {sc['word_count']} palavras",
         script=sc, packaging=pk)

    # compliance pré-render: não gastar em visuais num vídeo que seria bloqueado
    with session_scope() as s:
        v = s.get(Video, video_id)
    pre = compliance.check(v, ch.niche_key, use_llm=False)
    if pre["verdict"] != "publish":
        fixed = compliance.auto_fix_title(pk["title"])
        if fixed != pk["title"]:
            pk["title"] = fixed
            _log(video_id, f"Título corrigido pelo Guardião: {fixed}", packaging=pk)
            with session_scope() as s:
                v = s.get(Video, video_id)
            pre = compliance.check(v, ch.niche_key, use_llm=False)
    if pre["verdict"] == "block":
        _log(video_id, "BLOQUEADO pelo Guardião antes do render", status="failed", compliance=pre)
        return v
    if not render:
        _log(video_id, "Guião pronto (render adiado)", status="planned", compliance=pre)
        return v

    out = get_settings().media_dir / "videos" / str(video_id)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    _log(video_id, "A gerar voz e visuais", status="rendering")
    w, h = visuals.dims(v.format)
    palette = (ch.branding or {}).get("palette")
    ups = plan.get("upgrades", {})
    scenes = sc["scenes"]

    def voice_job(i):
        return tts.synth_scene(scenes[i]["narration"], ch.language, out / f"voice_{i:03d}.wav",
                               voice=ups.get("voice", "tts:edge"), video_id=video_id)

    used: set[str] = set()
    if v.mode == "text_story":
        bg = visuals.background_loop(v.format, used, out)

    def visual_job(i):
        if v.mode == "text_story":
            return {"type": "video", "path": bg, "provider": "bg"} if bg else \
                visuals.scene_visual(scenes[i], i, v.mode, v.format, out, ups, palette, used, video_id, len(scenes))
        return visuals.scene_visual(scenes[i], i, v.mode, v.format, out, ups, palette, used, video_id, len(scenes))

    with ThreadPoolExecutor(WORKERS) as pool:
        voices = list(pool.map(voice_job, range(len(scenes))))
        vis = list(pool.map(visual_job, range(len(scenes))))

    providers = {x["provider"] for x in voices} | {x["provider"] for x in vis}
    _log(video_id, f"Voz/visuais prontos ({', '.join(sorted(providers))})")

    # timeline
    t, words, overlays, bg_offset = 0.0, [], [], 0.0
    for i, (sc_i, vo) in enumerate(zip(scenes, voices)):
        words += [{**wd, "start": wd["start"] + t, "end": wd["end"] + t} for wd in vo["words"]]
        if sc_i.get("on_screen_text") and v.format == "short":
            overlays.append({"text": sc_i["on_screen_text"], "start": t, "end": t + min(vo["duration"], 2.2)})
        vo["t0"] = t
        t += vo["duration"]
    total = t

    def scene_job(i):
        dur, vis_i = voices[i]["duration"], vis[i]
        dest = out / f"seg_{i:03d}.mp4"
        if vis_i["type"] == "video":
            start = voices[i]["t0"] if v.mode == "text_story" else 0.0  # fundo contínuo
            return assembler.render_video_scene(vis_i["path"], dur, dest, w, h, start=start)
        return assembler.render_image_scene(vis_i["path"], dur, dest, w, h, i)

    with ThreadPoolExecutor(WORKERS) as pool:
        segs = list(pool.map(scene_job, range(len(scenes))))
    video_track = assembler.concat_video(segs, out / "video_track.mp4")
    voice_track = media.concat_audio([Path(x["path"]) for x in voices], out / "voice.wav")
    music = assembler.music_track(total, out / "music.wav")
    ass = captions.build_ass(words, v.format, out / "captions.ass", overlays)
    wm = (ch.branding or {}).get("watermark_path")
    final = assembler.final_mix(video_track, voice_track, music, ass, out / "final.mp4", watermark=wm, fmt=v.format)
    _log(video_id, f"Render final: {total:.1f}s")

    thumb_tier = ups.get("thumbnail_tier", "img:flux-dev") if v.format == "long" else "img:procedural"
    first_img = next((x["path"] for x in vis if x["type"] == "image"), None)
    thumb = thumbnails.make_thumbnail(pk, v.format, out, first_img, thumb_tier, palette, video_id)

    with session_scope() as s:
        v = s.get(Video, video_id)
        v.output_path, v.thumbnail_path, v.duration_s = str(final), thumb, round(total, 2)
        s.add(v)
        s.commit()
    final_check = compliance.check(v, ch.niche_key, use_llm=True)
    status = "ready" if final_check["verdict"] != "block" else "failed"
    _log(video_id, f"Guardião: {final_check['verdict']} (risco {final_check['risk']})", status=status,
         compliance=final_check)
    with session_scope() as s:
        idea = s.get(Idea, idea.id)
        idea.status = "ready" if status == "ready" else "backlog"
        s.add(idea)
        s.commit()
        return s.get(Video, video_id)


def produce_idea(idea_id: int, force_mode: str | None = None, render: bool = True) -> Video:
    v = plan_idea(idea_id, force_mode)
    return produce(v.id, render)


# ------------------------------------------------------------------------------ recortes


def produce_clips(url: str, channel_id: int, permission: bool = False, count: int = 3, angle: str = "") -> list[Video]:
    with session_scope() as s:
        ch = s.get(Channel, channel_id)
    if not ch:
        raise ValueError("canal não encontrado")
    info = clipper.inspect(url)
    if not (info["is_cc"] or permission):
        raise PermissionError(f"'{info['title']}' tem licença '{info['license']}'. Recorte bloqueado: usa fontes "
                              "Creative Commons ou marca 'tenho autorização' (conteúdo teu/licenciado).")
    work = get_settings().media_dir / "sources" / info["id"]
    segs = clipper.transcript(url, ch.language, work)
    if not segs:
        raise RuntimeError("Sem legendas/transcrição disponíveis para escolher momentos.")
    clips = clipper.select_clips(info, segs, angle or ch.strategy.get("positioning", ""), count)
    src_path = clipper.download(url, work)
    videos: list[Video] = []
    for n, clip in enumerate(clips):
        with session_scope() as s:
            idea = Idea(channel_id=channel_id, title=clip["headline"][:90] or info["title"][:90], hook=clip["hook_text"],
                        angle=clip["why"], format="short", origin="clip", status="producing",
                        scores={"virality": clip.get("virality", 50)}, score=float(clip.get("virality", 50)))
            s.add(idea)
            s.commit()
            s.refresh(idea)
            v = Video(idea_id=idea.id, channel_id=channel_id, format="short", mode="clip_commentary",
                      status="rendering", source={**info, "permission": permission, "clips": [clip]},
                      plan={"mode": "clip_commentary", "why": "Recorte licenciado com comentário original"})
            s.add(v)
            s.commit()
            s.refresh(v)
        try:
            videos.append(_render_clip(v.id, ch, info, segs, clip, src_path))
        except Exception as e:  # noqa: BLE001
            _log(v.id, f"ERRO: {e}", status="failed")
    return videos


def _render_clip(video_id: int, ch: Channel, info: dict, segs: list[dict], clip: dict, src_path: str) -> Video:
    out = get_settings().media_dir / "videos" / str(video_id)
    out.mkdir(parents=True, exist_ok=True)
    hook = tts.synth_scene(clip["hook_text"], ch.language, out / "hook.wav", video_id=video_id)
    frame = out / "frame.jpg"
    media.run(["-ss", f"{clip['start']:.2f}", "-i", src_path, "-frames:v", "1", frame])
    intro = assembler.render_image_scene(str(frame), hook["duration"], out / "intro.mp4", 1080, 1920, 0)
    intro_av = out / "intro_av.mp4"
    media.run(["-i", intro, "-i", hook["path"], "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2",
               "-shortest", intro_av])
    body = assembler.render_clip_vertical(src_path, clip["start"], clip["end"], out / "body.mp4")
    if not media.has_audio(body):
        media.run(["-i", body, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-c:v", "copy", "-c:a", "aac",
                   "-shortest", out / "body_a.mp4"])
        body = out / "body_a.mp4"
    joined = out / "joined.mp4"
    media.run(["-i", intro_av, "-i", body, "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
               "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac",
               joined])
    words = hook["words"] + clipper.words_in_range(segs, clip["start"], clip["end"], hook["duration"])
    total = hook["duration"] + clip["end"] - clip["start"]
    ass = captions.build_ass(words, "short", out / "captions.ass",
                             [{"text": clip["headline"], "start": 0, "end": total}])
    final = assembler.final_mix(joined, None, None, ass, out / "final.mp4",
                                watermark=(ch.branding or {}).get("watermark_path"), fmt="short",
                                keep_video_audio=True)
    pk = {"title": clip["headline"].title()[:90], "titles": [clip["headline"].title()[:90]],
          "description": f"{clip['context']}\n\n{clipper.attribution(info)}\n#shorts",
          "tags": [w.lower() for w in clip["headline"].split()][:10], "thumbnail": {"text": clip["headline"]},
          "pinned_comment": "Do you agree? 👇", "ai_disclosure_needed": False}
    sc = {"title": pk["title"], "hook": clip["hook_text"],
          "scenes": [{"narration": clip["hook_text"] + " " + clip["context"], "on_screen_text": clip["headline"]}]}
    thumb = thumbnails.compose(str(frame), clip["headline"], out / "thumbnail.jpg", size=(1080, 1920))
    with session_scope() as s:
        v = s.get(Video, video_id)
        v.output_path, v.thumbnail_path, v.duration_s = str(final), thumb, round(total, 2)
        v.packaging, v.script = pk, sc
        touch(v, "packaging", "script")
        s.add(v)
        s.commit()
    check = compliance.check(v, ch.niche_key, use_llm=True)
    _log(video_id, f"Recorte pronto ({total:.1f}s); Guardião: {check['verdict']}",
         status="ready" if check["verdict"] != "block" else "failed", compliance=check)
    with session_scope() as s:
        return s.get(Video, video_id)


def preview_image(prompt: str, fmt: str = "short") -> str:
    w, h = visuals.dims(fmt)
    return gen_image(prompt, get_settings().media_dir / "previews" / f"{abs(hash(prompt))}.jpg", w, h)["path"]

