"""ANÁLISE & ESCALA: o ciclo que transforma dados em dinheiro.

Cada vídeo publicado é comparado com a baseline do próprio canal à mesma idade (outlier score) e
diagnosticado numa matriz CTR × retenção:
  scale      -> vencedor: gerar 5 sequelas/variações e subir a prioridade da série
  repackage  -> conteúdo bom, embalagem fraca: novo título/thumbnail (longos: atualiza no próprio vídeo)
  rehook     -> CTR bom, retenção cai cedo: reescrever a abertura na próxima versão
  republish  -> joia escondida (retenção/engajamento fortes, distribuição nula): repostar com novo gancho
  kill       -> fraco em tudo: despromover a série
  hold       -> cedo demais / na média
"""
from __future__ import annotations

import json
import logging
import statistics
from datetime import timedelta

from sqlmodel import select

from .. import prompts
from ..db import session_scope, touch
from ..llm import S, arr, enum, get_llm, obj
from ..models import Channel, Idea, MetricSnapshot, Publication, Video, now
from . import ideas as ideas_svc
from .finance import book_revenue
from . import youtube_data as ytd

log = logging.getLogger("viral.analytics")

DIAG_SCHEMA = obj({
    "videos": arr(obj({"publication_id": {"type": "integer"},
                       "verdict": enum("scale", "repackage", "rehook", "republish", "hold", "kill"),
                       "why": S, "follow_ups": arr(S), "new_titles": arr(S), "new_hook": S,
                       "new_thumbnail": S})),
    "lessons": arr(S),
})


# ------------------------------------------------------------------ recolha
def record(pub_id: int, **m) -> MetricSnapshot:
    """Grava um snapshot (usado pela sincronização e pela entrada manual)."""
    with session_scope() as s:
        p = s.get(Publication, pub_id)
        age = (now() - (p.published_at or now())).total_seconds() / 3600
        prev = s.exec(select(MetricSnapshot).where(MetricSnapshot.publication_id == pub_id)
                      .order_by(MetricSnapshot.captured_at.desc())).first()
        snap = MetricSnapshot(publication_id=pub_id, age_hours=round(m.pop("age_hours", age), 1), **m)
        s.add(snap)
        s.commit()
        s.refresh(snap)
    delta = snap.revenue_usd - (prev.revenue_usd if prev else 0.0)
    if delta > 0:
        book_revenue(delta, memo=f"pub {pub_id}", channel_id=p.channel_id, video_id=p.video_id)
    return snap


def sync_channel(channel_id: int) -> dict:
    from .publisher import _service, credentials

    with session_scope() as s:
        ch = s.get(Channel, channel_id)
        pubs = s.exec(select(Publication).where(Publication.channel_id == channel_id,
                                                Publication.status == "published",
                                                Publication.external_id != "")).all()
    if not pubs:
        return {"synced": 0}
    ids = [p.external_id for p in pubs]
    creds = credentials(ch)
    stats: dict[str, dict] = {}
    if creds:
        yt = _service("youtube", "v3", creds)
        for i in range(0, len(ids), 50):
            for it in yt.videos().list(part="statistics", id=",".join(ids[i:i + 50])).execute().get("items", []):
                stats[it["id"]] = it["statistics"]
    else:
        for it in ytd.videos(ids):
            stats[it["id"]] = it.get("statistics", {})
    an: dict[str, dict] = {}
    if creds:
        an = analytics_report(creds, ids, min(p.published_at for p in pubs if p.published_at))
    n = 0
    for p in pubs:
        st, a = stats.get(p.external_id, {}), an.get(p.external_id, {})
        if not st and not a:
            continue
        record(p.id, views=int(st.get("viewCount", a.get("views", 0)) or 0), likes=int(st.get("likeCount", 0) or 0),
               comments=int(st.get("commentCount", 0) or 0), impressions=int(a.get("impressions", 0)),
               ctr=float(a.get("ctr", 0.0)), avg_view_pct=float(a.get("averageViewPercentage", 0.0)),
               avg_view_s=float(a.get("averageViewDuration", 0.0)), subs_gained=int(a.get("subscribersGained", 0)),
               revenue_usd=float(a.get("estimatedRevenue", 0.0)))
        n += 1
    return {"synced": n}


def analytics_report(creds, video_ids: list[str], since) -> dict[str, dict]:
    from .publisher import _service

    ya = _service("youtubeAnalytics", "v2", creds)
    out: dict[str, dict] = {}
    base = dict(ids="channel==MINE", startDate=since.strftime("%Y-%m-%d"), endDate=now().strftime("%Y-%m-%d"),
                dimensions="video", maxResults=200)
    queries = [
        "views,averageViewDuration,averageViewPercentage,subscribersGained",
        "estimatedRevenue",
        "videoThumbnailImpressions,videoThumbnailImpressionsClickRate",
    ]
    for i in range(0, len(video_ids), 200):
        flt = "video==" + ",".join(video_ids[i:i + 200])
        for metrics in queries:
            try:
                r = ya.reports().query(metrics=metrics, filters=flt, **base).execute()
            except Exception as e:  # noqa: BLE001  (receita exige canal monetizado; impressões podem faltar)
                log.info("analytics '%s' indisponível: %s", metrics, str(e)[:120])
                continue
            cols = [c["name"] for c in r.get("columnHeaders", [])]
            for row in r.get("rows", []):
                d = dict(zip(cols, row))
                o = out.setdefault(d["video"], {})
                o.update({k: v for k, v in d.items() if k != "video"})
                if "videoThumbnailImpressions" in d:
                    o["impressions"] = d["videoThumbnailImpressions"]
                    o["ctr"] = float(d.get("videoThumbnailImpressionsClickRate", 0)) * (
                        100 if float(d.get("videoThumbnailImpressionsClickRate", 0)) <= 1 else 1)
    return out


# ------------------------------------------------------------------ diagnóstico
def _latest(s, pub_id: int) -> MetricSnapshot | None:
    return s.exec(select(MetricSnapshot).where(MetricSnapshot.publication_id == pub_id)
                  .order_by(MetricSnapshot.captured_at.desc())).first()


def performance_table(channel_id: int | None = None) -> list[dict]:
    with session_scope() as s:
        q = select(Publication).where(Publication.status.in_(["published", "exported"]))
        if channel_id:
            q = q.where(Publication.channel_id == channel_id)
        rows = []
        for p in s.exec(q).all():
            m = _latest(s, p.id)
            v = s.get(Video, p.video_id)
            if not m or not v:
                continue
            rows.append({"publication_id": p.id, "video_id": v.id, "channel_id": p.channel_id, "title": p.title,
                         "format": v.format, "mode": v.mode, "url": p.url, "attempt": p.attempt,
                         "age_hours": m.age_hours, "views": m.views, "likes": m.likes, "comments": m.comments,
                         "impressions": m.impressions, "ctr": m.ctr, "avg_view_pct": m.avg_view_pct,
                         "revenue": m.revenue_usd, "cost": v.cost_usd, "verdict": p.verdict,
                         "engagement": round((m.likes + 3 * m.comments) / max(m.views, 1) * 100, 2),
                         "series": (s.get(Idea, v.idea_id).series_key if v.idea_id and s.get(Idea, v.idea_id) else "")})
    # outlier: views vs mediana do canal/formato em idades comparáveis (escala √idade)
    for r in rows:
        peers = [x for x in rows if x["channel_id"] == r["channel_id"] and x["format"] == r["format"]
                 and x["publication_id"] != r["publication_id"] and x["age_hours"] > 0]
        if len(peers) >= 3:
            norm = [x["views"] * (max(r["age_hours"], 1) / max(x["age_hours"], 1)) ** 0.5 for x in peers]
            base = statistics.median(norm) or 1
        else:
            base = (1500 if r["format"] == "short" else 400) * (max(r["age_hours"], 1) / 168) ** 0.5
        r["baseline"] = round(base, 1)
        r["outlier"] = round(r["views"] / max(base, 1), 2)
    return sorted(rows, key=lambda r: -r["outlier"])


def rule_verdict(r: dict) -> tuple[str, str]:
    short = r["format"] == "short"
    min_age = 12 if short else 36
    if r["age_hours"] < min_age:
        return "hold", f"Só {r['age_hours']:.0f}h — cedo demais."
    ret_good = r["avg_view_pct"] >= (75 if short else 40) if r["avg_view_pct"] else None
    ret_weak = r["avg_view_pct"] < (55 if short else 28) if r["avg_view_pct"] else None
    ctr_good = r["ctr"] >= 5 if r["ctr"] else None
    ctr_weak = r["ctr"] < 3 if r["ctr"] else None
    o = r["outlier"]
    if o >= 1.5 and not ret_weak:
        return "scale", f"{o}× a baseline do canal — vencedor."
    if ret_good and (ctr_weak or o < 0.7):
        if short and o < 0.35:
            return "republish", f"Retenção {r['avg_view_pct']:.0f}% mas {o}× baseline — preso num mau teste."
        return "repackage", f"Retenção forte ({r['avg_view_pct']:.0f}%) mas CTR {r['ctr']:.1f}% / {o}× baseline."
    if ctr_good and ret_weak:
        return "rehook", f"CTR {r['ctr']:.1f}% bom, retenção {r['avg_view_pct']:.0f}% cai — abertura falha."
    if ret_good is None and ctr_good is None:  # só views (canal exportado/sem Analytics)
        if o < 0.35 and r["engagement"] >= 4 and r["age_hours"] >= 72:
            return "republish", f"Poucas views ({o}×) mas engajamento {r['engagement']}% — joia escondida."
        if o < 0.3 and r["age_hours"] >= 96:
            return "kill", f"{o}× baseline após {r['age_hours']:.0f}h."
        return "hold", f"{o}× baseline."
    if o < 0.4 and (ret_weak or ctr_weak):
        return "kill", f"{o}× baseline, métricas fracas."
    return "hold", f"{o}× baseline — na média."


def diagnose(channel_id: int, use_llm: bool = True) -> dict:
    rows = performance_table(channel_id)
    for r in rows:
        r["verdict"], r["why"] = rule_verdict(r)
    llm_out = None
    if use_llm and rows:
        base = {"short_median_views": statistics.median([r["views"] for r in rows if r["format"] == "short"] or [0]),
                "long_median_views": statistics.median([r["views"] for r in rows if r["format"] == "long"] or [0])}
        payload = [{k: r[k] for k in ("publication_id", "title", "format", "views", "impressions", "ctr",
                                      "avg_view_pct", "age_hours", "outlier", "engagement", "verdict")}
                   for r in rows[:60]]
        llm_out = get_llm().json(system=prompts.SYSTEM,
                                 prompt=prompts.DIAGNOSIS.format(baseline=json.dumps(base),
                                                                 videos=json.dumps(payload, ensure_ascii=False)),
                                 schema=DIAG_SCHEMA, effort="medium", purpose="diagnosis", channel_id=channel_id)
        if llm_out:
            by = {x["publication_id"]: x for x in llm_out["videos"]}
            for r in rows:
                x = by.get(r["publication_id"])
                if x:
                    r.update({"verdict": x["verdict"], "why": x["why"], "follow_ups": x["follow_ups"],
                              "new_titles": x["new_titles"], "new_hook": x["new_hook"],
                              "new_thumbnail": x["new_thumbnail"]})
    with session_scope() as s:
        for r in rows:
            p = s.get(Publication, r["publication_id"])
            p.verdict = r["verdict"]
            p.diagnosis = {k: r.get(k) for k in ("why", "follow_ups", "new_titles", "new_hook", "new_thumbnail",
                                                 "outlier", "baseline")}
            touch(p, "diagnosis")
            s.add(p)
        s.commit()
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"videos": rows, "counts": counts, "lessons": (llm_out or {}).get("lessons", [])}


# ------------------------------------------------------------------ ação
def act(channel_id: int) -> dict:
    """Executa os vereditos: escala vencedores, cria republicações, reembala, despromove séries."""
    diag = diagnose(channel_id)
    done = {"scaled": 0, "republish": 0, "repackaged": 0, "killed_series": 0, "ideas_created": 0}
    for r in diag["videos"]:
        with session_scope() as s:
            p = s.get(Publication, r["publication_id"])
            already = (p.diagnosis or {}).get("acted")
        if already:
            continue
        v_ = r["verdict"]
        if v_ == "scale":
            created = ideas_svc.generate(channel_id, count=5, fmt=r["format"],
                                         winners=[r["title"]] + (r.get("follow_ups") or []), origin="scale",
                                         parent_video_id=r["video_id"])
            with session_scope() as s:  # prioridade máxima à série vencedora
                for i in created:
                    i.score = min(100.0, i.score + 15)
                    i.status = "approved"
                    s.add(i)
                s.commit()
            done["scaled"] += 1
            done["ideas_created"] += len(created)
        elif v_ == "republish" or (v_ == "rehook" and r["format"] == "short"):
            with session_scope() as s:
                old = s.get(Video, r["video_id"])
                parent = s.get(Idea, old.idea_id) if old.idea_id else None
                idea = Idea(channel_id=channel_id, title=(r.get("new_titles") or [r["title"]])[0][:200],
                            hook=r.get("new_hook") or (parent.hook if parent else ""),
                            angle="Republicação de joia escondida — novo gancho nos 2 primeiros segundos.",
                            format=r["format"], pillar=parent.pillar if parent else "",
                            series_key=parent.series_key if parent else "", origin="republish",
                            parent_video_id=old.id, status="approved",
                            scores=parent.scores if parent else {}, score=(parent.score if parent else 60) + 10)
                s.add(idea)
                s.commit()
            done["republish"] += 1
        elif v_ == "repackage" and r["format"] == "long" and r.get("new_titles"):
            if update_title(r["publication_id"], r["new_titles"][0]):
                done["repackaged"] += 1
        elif v_ == "kill" and r.get("series"):
            with session_scope() as s:
                for i in s.exec(select(Idea).where(Idea.channel_id == channel_id, Idea.series_key == r["series"],
                                                   Idea.status == "backlog")).all():
                    i.score = round(i.score * 0.7, 1)
                    s.add(i)
                s.commit()
            done["killed_series"] += 1
        with session_scope() as s:
            p = s.get(Publication, r["publication_id"])
            if v_ != "hold":
                p.diagnosis = {**(p.diagnosis or {}), "acted": now().isoformat(timespec="seconds")}
                touch(p, "diagnosis")
                s.add(p)
                s.commit()
    return {**done, "counts": diag["counts"], "lessons": diag["lessons"]}


def update_title(pub_id: int, title: str) -> bool:
    """Reembala um longo no próprio vídeo (mantém views/histórico) via videos.update."""
    from .publisher import _service, credentials

    with session_scope() as s:
        p = s.get(Publication, pub_id)
        ch = s.get(Channel, p.channel_id)
    creds = credentials(ch) if ch else None
    if not creds or not p.external_id:
        return False
    yt = _service("youtube", "v3", creds)
    items = yt.videos().list(part="snippet", id=p.external_id).execute().get("items", [])
    if not items:
        return False
    sn = items[0]["snippet"]
    sn["title"] = title[:100]
    yt.videos().update(part="snippet", body={"id": p.external_id, "snippet": {
        k: sn[k] for k in ("title", "description", "tags", "categoryId", "defaultLanguage") if k in sn}}).execute()
    with session_scope() as s:
        p = s.get(Publication, pub_id)
        p.title = title
        s.add(p)
        s.commit()
    return True


def stale_syncs(hours: int = 6) -> list[int]:
    cutoff = now() - timedelta(hours=hours)
    with session_scope() as s:
        chans = s.exec(select(Channel).where(Channel.status == "active")).all()
        out = []
        for c in chans:
            last = s.exec(select(MetricSnapshot).join(Publication).where(Publication.channel_id == c.id)
                          .order_by(MetricSnapshot.captured_at.desc())).first()
            if not last or last.captured_at < cutoff:
                out.append(c.id)
    return out
