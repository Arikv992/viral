"""PUBLICAÇÃO: agenda nos melhores slots e publica.

- YouTube: OAuth por canal; upload resumível como 'private' + `publishAt` (o YouTube liberta à hora exata),
  thumbnail personalizada (longos), rótulo de conteúdo sintético quando aplicável, comentário inicial.
- Sem OAuth: modo EXPORTAÇÃO — pasta pronta (vídeo, thumbnail, metadata.json com hora ideal) para carregar à mão.
- TikTok: adaptador da Content Posting API (pronto para quando ligares a app TikTok).
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import timedelta
from pathlib import Path

from sqlmodel import select

from ..config import get_settings
from ..db import session_scope, touch
from ..models import Channel, Idea, Publication, Video, now
from ..state import setting
from .http import client
from .timing import next_slots

log = logging.getLogger("viral.publisher")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/yt-analytics.readonly",
          "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"]
CATEGORY = {"money": "27", "history": "27", "science": "28", "tech": "28", "mind": "27", "crime": "24",
            "mystery": "24", "horror": "24", "world": "25", "health": "27", "nature": "15", "stories": "24",
            "entertainment": "24"}


# ------------------------------------------------------------------ OAuth
def _flow(redirect_uri: str):
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_secrets_file(get_settings().google_client_secrets, scopes=SCOPES, redirect_uri=redirect_uri)


def oauth_url(channel_id: int, redirect_uri: str) -> str:
    flow = _flow(redirect_uri)
    url, _ = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent",
                                    state=str(channel_id))
    return url


def oauth_callback(channel_id: int, code: str, redirect_uri: str) -> dict:
    flow = _flow(redirect_uri)
    flow.fetch_token(code=code)
    creds = flow.credentials
    data = json.loads(creds.to_json())
    yt = _service("youtube", "v3", creds)
    me = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    with session_scope() as s:
        ch = s.get(Channel, channel_id)
        ch.oauth_token = {**(ch.oauth_token or {}), "google": data}
        if me:
            ch.youtube_channel_id = me[0]["id"]
        touch(ch, "oauth_token")
        s.add(ch)
        s.commit()
    return {"youtube_channel_id": me[0]["id"] if me else None, "title": me[0]["snippet"]["title"] if me else None}


def credentials(channel: Channel):
    tok = (channel.oauth_token or {}).get("google")
    if not tok:
        return None
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_info(tok, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with session_scope() as s:
            ch = s.get(Channel, channel.id)
            ch.oauth_token = {**ch.oauth_token, "google": json.loads(creds.to_json())}
            touch(ch, "oauth_token")
            s.add(ch)
            s.commit()
    return creds


def _service(name: str, version: str, creds):
    from googleapiclient.discovery import build

    return build(name, version, credentials=creds, cache_discovery=False)


# ------------------------------------------------------------------ agendamento
def schedule_channel(channel_id: int, publish_now: bool | None = None) -> list[Publication]:
    """Atribui slots ótimos a todos os vídeos prontos do canal (melhor score primeiro)."""
    with session_scope() as s:
        ch = s.get(Channel, channel_id)
        ready = s.exec(select(Video).where(Video.channel_id == channel_id, Video.status == "ready")).all()
        taken = {p.video_id for p in s.exec(select(Publication).where(Publication.channel_id == channel_id)).all()}
        todo = [v for v in ready if v.id not in taken]
        scores = {v.id: (s.get(Idea, v.idea_id).score if v.idea_id and s.get(Idea, v.idea_id) else 0) for v in todo}
    todo.sort(key=lambda v: -scores[v.id])
    created: list[Publication] = []
    for fmt in ("short", "long"):
        vids = [v for v in todo if v.format == fmt]
        if not vids:
            continue
        for v in vids:
            attempt, not_before = _republish_info(v)
            # slot seguinte livre (os já atribuídos ficam ocupados porque são gravados um a um)
            nxt = next_slots(ch, fmt, 1, after=max(now(), not_before) if not_before else None)
            if not nxt:
                continue
            when = nxt[0]
            with session_scope() as s:
                p = Publication(video_id=v.id, channel_id=channel_id, scheduled_at=when, attempt=attempt,
                                platform="youtube_shorts" if fmt == "short" else "youtube",
                                title=(v.packaging or {}).get("title", ""), status="scheduled")
                s.add(p)
                # TikTok (quando ligado): os Shorts são cross-postados 2h depois
                if fmt == "short" and (ch.oauth_token or {}).get("tiktok"):
                    s.add(Publication(video_id=v.id, channel_id=channel_id, scheduled_at=when + timedelta(hours=2),
                                      platform="tiktok", title=p.title, status="scheduled", attempt=attempt))
                s.commit()
                s.refresh(p)
            created.append(p)
    auto = setting("auto_publish") if publish_now is None else publish_now
    if auto:
        created = [publish(p.id) for p in created]
    return created


def _republish_info(v: Video) -> tuple[int, object]:
    """Republicações: nº da tentativa e data mínima (>= 7 dias após a publicação original, para não competir)."""
    with session_scope() as s:
        idea = s.get(Idea, v.idea_id) if v.idea_id else None
        if not idea or idea.origin != "republish" or not idea.parent_video_id:
            return 1, None
        prev = s.exec(select(Publication).where(Publication.video_id == idea.parent_video_id)).all()
    if not prev:
        return 2, None
    last = max(prev, key=lambda p: p.attempt)
    base = last.published_at or last.scheduled_at or now()
    return last.attempt + 1, base + timedelta(days=7)


def publish(pub_id: int) -> Publication:
    with session_scope() as s:
        p = s.get(Publication, pub_id)
        v = s.get(Video, p.video_id)
        ch = s.get(Channel, p.channel_id)
    if not v.output_path or not Path(v.output_path).exists():
        return _set(pub_id, status="failed", diagnosis={"error": "ficheiro de vídeo em falta"})
    if (v.compliance or {}).get("verdict") == "block":
        return _set(pub_id, status="failed", diagnosis={"error": "bloqueado pelo Guardião"})
    if p.platform == "tiktok":
        return tiktok_publish(p, v, ch)
    creds = credentials(ch) if ch else None
    if not creds:
        return export(p, v, ch)
    try:
        return youtube_upload(p, v, ch, creds)
    except Exception as e:  # noqa: BLE001
        log.exception("upload falhou")
        return _set(pub_id, status="failed", diagnosis={"error": str(e)[:500]})


def _set(pub_id: int, **fields) -> Publication:
    with session_scope() as s:
        p = s.get(Publication, pub_id)
        for k, val in fields.items():
            setattr(p, k, val)
        if "diagnosis" in fields:
            touch(p, "diagnosis")
        s.add(p)
        s.commit()
        s.refresh(p)
        return p


def youtube_upload(p: Publication, v: Video, ch: Channel, creds) -> Publication:
    from googleapiclient.http import MediaFileUpload

    from ..knowledge.niches import get_niche

    yt = _service("youtube", "v3", creds)
    pk = v.packaging or {}
    niche = get_niche(ch.niche_key) or {}
    when = p.scheduled_at if p.scheduled_at and p.scheduled_at > now() else None
    status = {"privacyStatus": "private" if when else "public", "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": bool((v.compliance or {}).get("synthetic_disclosure"))}
    if when:
        status["publishAt"] = when.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = {"snippet": {"title": (p.title or pk.get("title", ""))[:100], "description": pk.get("description", "")[:4900],
                        "tags": pk.get("tags", [])[:30], "categoryId": CATEGORY.get(niche.get("category", ""), "24"),
                        "defaultLanguage": ch.language, "defaultAudioLanguage": ch.language},
            "status": status}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(v.output_path, chunksize=8 * 1024 * 1024, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    if v.format == "long" and v.thumbnail_path and Path(v.thumbnail_path).exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(v.thumbnail_path)).execute()
        except Exception as e:  # noqa: BLE001  (thumbnails exigem canal verificado)
            log.warning("thumbnail falhou: %s", e)
    if pk.get("pinned_comment"):
        try:
            yt.commentThreads().insert(part="snippet", body={"snippet": {"videoId": vid, "topLevelComment": {
                "snippet": {"textOriginal": pk["pinned_comment"]}}}}).execute()
        except Exception as e:  # noqa: BLE001
            log.warning("comentário falhou: %s", e)
    url = f"https://youtube.com/shorts/{vid}" if v.format == "short" else f"https://youtu.be/{vid}"
    _mark_published(v.id)
    return _set(p.id, status="published", external_id=vid, url=url, published_at=when or now())


def _mark_published(video_id: int) -> None:
    with session_scope() as s:
        vv = s.get(Video, video_id)
        vv.status = "published"
        s.add(vv)
        idea = s.get(Idea, vv.idea_id) if vv.idea_id else None
        if idea:
            idea.status = "published"
            s.add(idea)
        s.commit()


def export(p: Publication, v: Video, ch: Channel | None) -> Publication:
    """Sem OAuth: pacote pronto para upload manual (ou para outra ferramenta)."""
    when = p.scheduled_at or now()
    safe = "".join(c if c.isalnum() else "_" for c in (p.title or "video"))[:50]
    out = get_settings().data_dir / "exports" / (ch.handle or str(ch.id) if ch else "sem-canal") / \
        f"{when:%Y%m%d_%H%M}_{safe}"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(v.output_path, out / "video.mp4")
    if v.thumbnail_path and Path(v.thumbnail_path).exists():
        shutil.copy(v.thumbnail_path, out / "thumbnail.jpg")
    pk = v.packaging or {}
    meta = {"title": p.title or pk.get("title"), "alt_titles": pk.get("titles", []),
            "description": pk.get("description"), "tags": pk.get("tags"),
            "publish_at_utc": when.isoformat(), "pinned_comment": pk.get("pinned_comment"),
            "altered_or_synthetic_content": bool((v.compliance or {}).get("synthetic_disclosure")),
            "made_for_kids": False, "format": v.format}
    (out / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    _mark_published(v.id)
    return _set(p.id, status="exported", url=str(out), diagnosis={"export_dir": str(out)})


# ------------------------------------------------------------------ TikTok (futuro)
def tiktok_publish(p: Publication, v: Video, ch: Channel) -> Publication:
    token = ((ch.oauth_token or {}).get("tiktok") or {}).get("access_token") if ch else None
    if not token:
        return export(p, v, ch)
    size = Path(v.output_path).stat().st_size
    pk = v.packaging or {}
    caption = (pk.get("title", "") + " " + " ".join(f"#{t.replace(' ', '')}" for t in pk.get("tags", [])[:4]))[:2200]
    r = client().post("https://open.tiktokapis.com/v2/post/publish/video/init/",
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
                      json={"post_info": {"title": caption, "privacy_level": "PUBLIC_TO_EVERYONE",
                                          "is_aigc": bool((v.compliance or {}).get("synthetic_disclosure"))},
                            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size,
                                            "total_chunk_count": 1}})
    data = r.json().get("data", {}) if r.status_code == 200 else {}
    if not data.get("upload_url"):
        return _set(p.id, status="failed", diagnosis={"error": r.text[:400]})
    with open(v.output_path, "rb") as f:
        up = client().put(data["upload_url"], content=f.read(),
                          headers={"Content-Type": "video/mp4", "Content-Range": f"bytes 0-{size - 1}/{size}"},
                          timeout=600.0)
    if up.status_code not in (200, 201):
        return _set(p.id, status="failed", diagnosis={"error": up.text[:400]})
    return _set(p.id, status="published", external_id=data.get("publish_id", ""), published_at=now())


def due_publications() -> list[Publication]:
    with session_scope() as s:
        return s.exec(select(Publication).where(Publication.status == "scheduled",
                                                Publication.scheduled_at <= now())).all()
