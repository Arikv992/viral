"""API REST. Tarefas pesadas (render, scans, ciclos) correm em background e são consultadas por polling."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from .config import get_settings
from .db import get_session, touch
from .knowledge.geo import COUNTRIES, LANGUAGES
from .knowledge.niches import NICHES, get_niche
from .knowledge.providers import PRICES
from .models import Channel, Idea, JobRun, LedgerEntry, MetricSnapshot, Publication, Trend, Video
from .services import (analytics, audience, autopilot, branding, finance, ideas, publisher, strategy, timing,
                       trends)
from .services.production import clipper, pipeline, planner
from .state import all_settings, update_settings

api = APIRouter(prefix="/api")


def media_url(path: str | None) -> str | None:
    if not path:
        return None
    try:
        rel = Path(path).resolve().relative_to(get_settings().media_dir.resolve())
    except ValueError:
        return None
    return f"/media/{rel.as_posix()}"


def dump(obj) -> dict:
    d = obj.model_dump()
    for k, v in list(d.items()):
        if k.endswith("_path") and isinstance(v, str):
            d[k.replace("_path", "_url")] = media_url(v)
    return d


# ------------------------------------------------------------------ sistema
@api.get("/status")
def status():
    s = get_settings()
    return {"capabilities": s.capabilities(), "settings": all_settings(), "budget": finance.budget_status(),
            "model": s.llm_model, "prices": PRICES}


class SettingsIn(BaseModel):
    values: dict[str, Any]


@api.put("/settings")
def put_settings(body: SettingsIn):
    out = update_settings(body.values)
    autopilot.stop_scheduler()
    autopilot.start_scheduler()
    return out


@api.get("/today")
def today():
    return autopilot.today()


@api.get("/meta")
def meta():
    return {"niches": [{"key": n["key"], "name": n["name"], "category": n["category"]} for n in NICHES],
            "languages": [{"code": k, "name": v["name"]} for k, v in LANGUAGES.items()],
            "countries": [{"code": k, "name": v["name"], "tier": v["tier"]} for k, v in COUNTRIES.items()],
            "modes": {k: {"label": m["label"], "desc": m["desc"], "formats": m["formats"]}
                      for k, m in planner.MODES.items()}}


# ------------------------------------------------------------------ tendências
class ScanIn(BaseModel):
    niches: list[str] | None = None
    geo: str = "US"
    lang: str = "en"
    use_llm: bool = True


@api.post("/trends/scan")
def trends_scan(body: ScanIn, bg: BackgroundTasks):
    bg.add_task(trends.scan, body.niches, body.geo, body.lang, body.use_llm)
    return {"started": True}


@api.post("/trends/scan-sync")
def trends_scan_sync(body: ScanIn):
    return [t.model_dump() for t in trends.scan(body.niches, body.geo, body.lang, body.use_llm)]


@api.get("/trends")
def trends_list(niche: str | None = None, limit: int = 60):
    return [t.model_dump() for t in trends.latest(limit, niche)]


@api.get("/trends/outliers")
def trends_outliers(niche: str, geo: str = "US", lang: str = "en", short: bool | None = None):
    return trends.outlier_videos(niche, geo, lang, short)


# ------------------------------------------------------------------ estratégia
@api.get("/niches")
def niches(language: str = "en", budget: float = 50, prefer: str = "both"):
    counts: dict[str, float] = {}
    for t in trends.latest(200):
        counts[t.niche_key] = counts.get(t.niche_key, 0) + t.opportunity / 5
    return strategy.rank_niches(language, budget, prefer, counts)


@api.get("/niches/{key}")
def niche_detail(key: str):
    n = get_niche(key)
    if not n:
        raise HTTPException(404)
    return n


@api.get("/languages")
def languages():
    return strategy.language_economics()


class ConceptIn(BaseModel):
    language: str = "en"
    budget: float = 50
    prefer: str = "both"
    count: int = 5
    notes: str = ""


@api.post("/strategy/concepts")
def concepts(body: ConceptIn):
    hot = [{"topic": t.topic, "niche": t.niche_key, "opportunity": t.opportunity, "longevity": t.longevity}
           for t in trends.latest(25)]
    return strategy.channel_concepts(body.language, body.budget, body.prefer, body.count, hot, body.notes)


class NamesIn(BaseModel):
    niche_key: str
    concept: str = ""
    language: str = "en"
    count: int = 12
    style: str = "mixed"
    check_handles: bool = True


@api.post("/strategy/names")
def names(body: NamesIn):
    return strategy.generate_names(body.niche_key, body.concept, body.language, body.count, body.style,
                                   body.check_handles)


# ------------------------------------------------------------------ canais
class ChannelIn(BaseModel):
    name: str
    handle: str = ""
    niche_key: str
    language: str = "en"
    target_geos: list[str] = ["US"]
    formats: list[str] = ["short", "long"]
    status: str = "active"
    strategy: dict = {}


@api.get("/channels")
def channels(s: Session = Depends(get_session)):
    return [dump(c) | {"has_youtube": bool((c.oauth_token or {}).get("google")),
                       "branding_urls": {k.replace("_path", "_url"): media_url(v)
                                         for k, v in (c.branding or {}).items() if k.endswith("_path")}}
            for c in s.exec(select(Channel)).all()]


@api.post("/channels")
def create_channel(body: ChannelIn, s: Session = Depends(get_session)):
    c = Channel(**body.model_dump())
    c.handle = c.handle or c.name.lower().replace(" ", "")
    s.add(c)
    s.commit()
    s.refresh(c)
    return dump(c)


@api.patch("/channels/{cid}")
def update_channel(cid: int, body: dict, s: Session = Depends(get_session)):
    c = s.get(Channel, cid)
    if not c:
        raise HTTPException(404)
    for k, v in body.items():
        if k in {"name", "handle", "niche_key", "language", "target_geos", "formats", "status", "strategy"}:
            setattr(c, k, v)
    touch(c, "strategy", "target_geos", "formats")
    s.add(c)
    s.commit()
    return dump(c)


@api.delete("/channels/{cid}")
def delete_channel(cid: int, s: Session = Depends(get_session)):
    c = s.get(Channel, cid)
    if c:
        c.status = "killed"
        s.add(c)
        s.commit()
    return {"ok": True}


class BrandIn(BaseModel):
    premium: bool = False


@api.post("/channels/{cid}/branding")
def channel_branding(cid: int, body: BrandIn):
    kit = branding.build_channel_branding(cid, body.premium)
    return {**kit, **{k.replace("_path", "_url"): media_url(v) for k, v in kit.items() if k.endswith("_path")}}


# ------------------------------------------------------------------ público
class AudienceIn(BaseModel):
    niche_key: str
    language: str = "en"
    geo: str = "US"
    deep: bool = True
    channel_id: int | None = None


@api.post("/audience")
def audience_analyze(body: AudienceIn, s: Session = Depends(get_session)):
    res = audience.analyze(body.niche_key, body.language, body.geo, body.deep, body.channel_id)
    if body.channel_id:
        c = s.get(Channel, body.channel_id)
        if c:
            c.strategy = {**(c.strategy or {}), "audience_brief": res["brief"]}
            touch(c, "strategy")
            s.add(c)
            s.commit()
    return res


@api.get("/audience/geo")
def audience_geo(niche: str, language: str = "en"):
    return audience.geo_rpm_table(niche, language)


# ------------------------------------------------------------------ ideias
@api.get("/ideas")
def ideas_list(channel_id: int | None = None, status: str | None = None, s: Session = Depends(get_session)):
    q = select(Idea)
    if channel_id:
        q = q.where(Idea.channel_id == channel_id)
    if status:
        q = q.where(Idea.status == status)
    else:
        q = q.where(Idea.status != "discarded")
    return [i.model_dump() for i in s.exec(q.order_by(Idea.score.desc())).all()]


class GenIn(BaseModel):
    channel_id: int
    count: int = 20
    fmt: str = "both"
    trend_ids: list[int] = []


@api.post("/ideas/generate")
def ideas_generate(body: GenIn):
    return [i.model_dump() for i in ideas.generate(body.channel_id, body.count, body.fmt, body.trend_ids,
                                                   ideas.winners_for(body.channel_id))]


class IdeaIn(BaseModel):
    channel_id: int
    title: str
    hook: str = ""
    format: str = "short"
    pillar: str = ""


@api.post("/ideas")
def idea_create(body: IdeaIn, s: Session = Depends(get_session)):
    ch = s.get(Channel, body.channel_id)
    sc = ideas.score_idea({"format": body.format}, get_niche(ch.niche_key) if ch else None, ch.language if ch else "en")
    sc["expected_views"] = ideas.expected_views(body.format, sc)
    sc["expected_revenue_usd"] = round(sc["expected_views"] / 1000 * sc["rpm"], 3)
    i = Idea(**body.model_dump(), scores=sc, score=sc["total"], origin="manual")
    s.add(i)
    s.commit()
    s.refresh(i)
    return i.model_dump()


@api.patch("/ideas/{iid}")
def idea_update(iid: int, body: dict, s: Session = Depends(get_session)):
    i = s.get(Idea, iid)
    if not i:
        raise HTTPException(404)
    for k in ("status", "title", "hook", "angle", "format", "pillar", "notes", "series_key"):
        if k in body:
            setattr(i, k, body[k])
    s.add(i)
    s.commit()
    return i.model_dump()


@api.post("/ideas/consolidate")
def ideas_consolidate(channel_id: int | None = None):
    return ideas.consolidate(channel_id)


@api.get("/ideas/series")
def ideas_series(channel_id: int | None = None):
    return ideas.series_overview(channel_id)


# ------------------------------------------------------------------ produção
@api.post("/production/plan/{iid}")
def production_plan(iid: int, s: Session = Depends(get_session)):
    i = s.get(Idea, iid)
    ch = s.get(Channel, i.channel_id) if i else None
    if not i or not ch:
        raise HTTPException(404)
    return planner.plan(i.scores, i.format, ch.niche_key, bool(ch.strategy.get("monetized")),
                        ch.monthly_budget_share or 1.0)


class ProduceIn(BaseModel):
    idea_id: int
    force_mode: str | None = None
    render: bool = True


@api.post("/production/produce")
def production_produce(body: ProduceIn, bg: BackgroundTasks):
    v = pipeline.plan_idea(body.idea_id, body.force_mode)
    bg.add_task(pipeline.produce, v.id, body.render)
    return dump(v)


class ClipIn(BaseModel):
    url: str
    channel_id: int
    permission: bool = False
    count: int = 3
    angle: str = ""


@api.post("/production/inspect-source")
def inspect_source(body: dict):
    try:
        return clipper.inspect(body["url"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Não consegui ler a fonte: {e}") from e


@api.post("/production/clips")
def production_clips(body: ClipIn, bg: BackgroundTasks):
    try:
        info = clipper.inspect(body.url)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Não consegui ler a fonte: {e}") from e
    if not (info["is_cc"] or body.permission):
        raise HTTPException(403, f"Licença '{info['license']}': recorte bloqueado. Usa fontes Creative Commons "
                                 "ou confirma que tens autorização.")
    bg.add_task(pipeline.produce_clips, body.url, body.channel_id, body.permission, body.count, body.angle)
    return {"started": True, "source": info}


@api.get("/videos")
def videos(channel_id: int | None = None, status: str | None = None, s: Session = Depends(get_session)):
    q = select(Video)
    if channel_id:
        q = q.where(Video.channel_id == channel_id)
    if status:
        q = q.where(Video.status == status)
    return [dump(v) for v in s.exec(q.order_by(Video.id.desc())).all()]


@api.get("/videos/{vid}")
def video(vid: int, s: Session = Depends(get_session)):
    v = s.get(Video, vid)
    if not v:
        raise HTTPException(404)
    return dump(v)


@api.post("/videos/{vid}/rerender")
def video_rerender(vid: int, bg: BackgroundTasks):
    bg.add_task(pipeline.produce, vid, True)
    return {"started": True}


# ------------------------------------------------------------------ publicação
def _channel(s: Session, cid: int) -> Channel:
    c = s.get(Channel, cid)
    if not c:
        raise HTTPException(404, "canal não encontrado")
    return c


@api.get("/publish/plan/{cid}")
def publish_plan(cid: int, s: Session = Depends(get_session)):
    c = _channel(s, cid)
    return {"frequency": timing.frequency(c),
            "slots": {f: timing.best_slots(c, f, 7) for f in ("short", "long")},
            "heatmap": {f: timing.weekly_heatmap(c, f) for f in ("short", "long")},
            "audience_weights": timing.audience_weights(c)}


@api.post("/publish/schedule/{cid}")
def publish_schedule(cid: int, publish_now: bool | None = None):
    return [p.model_dump() for p in publisher.schedule_channel(cid, publish_now)]


@api.post("/publish/{pid}")
def publish_one(pid: int):
    return publisher.publish(pid).model_dump()


@api.get("/publications")
def publications(channel_id: int | None = None, s: Session = Depends(get_session)):
    q = select(Publication)
    if channel_id:
        q = q.where(Publication.channel_id == channel_id)
    out = []
    for p in s.exec(q.order_by(Publication.scheduled_at.desc())).all():
        v = s.get(Video, p.video_id)
        out.append(p.model_dump() | {"format": v.format if v else "", "thumbnail_url": media_url(v.thumbnail_path)
                                     if v else None, "video_url": media_url(v.output_path) if v else None})
    return out


@api.get("/publish/oauth/start/{cid}")
def oauth_start(cid: int, request: Request):
    if not get_settings().capabilities()["youtube_oauth"]:
        raise HTTPException(400, "Define GOOGLE_CLIENT_SECRETS (client_secret.json da Google Cloud) no .env")
    return RedirectResponse(publisher.oauth_url(cid, str(request.url_for("oauth_callback"))))


@api.get("/publish/oauth/callback", name="oauth_callback")
def oauth_callback(code: str, state: str, request: Request):
    publisher.oauth_callback(int(state), code, str(request.url_for("oauth_callback")))
    return RedirectResponse("/#/publish")


# ------------------------------------------------------------------ análise
@api.post("/analytics/sync/{cid}")
def analytics_sync(cid: int):
    return analytics.sync_channel(cid)


class MetricsIn(BaseModel):
    views: int = 0
    likes: int = 0
    comments: int = 0
    impressions: int = 0
    ctr: float = 0.0
    avg_view_pct: float = 0.0
    avg_view_s: float = 0.0
    subs_gained: int = 0
    revenue_usd: float = 0.0
    age_hours: float | None = None


@api.post("/analytics/metrics/{pid}")
def analytics_metrics(pid: int, body: MetricsIn, s: Session = Depends(get_session)):
    p = s.get(Publication, pid)
    if not p:
        raise HTTPException(404)
    if p.published_at is None:
        from .models import now

        p.published_at = now()
        p.status = "published" if p.status != "exported" else p.status
        s.add(p)
        s.commit()
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    return analytics.record(pid, **data).model_dump()


@api.get("/analytics/performance")
def analytics_performance(channel_id: int | None = None):
    return analytics.performance_table(channel_id)


@api.post("/analytics/diagnose/{cid}")
def analytics_diagnose(cid: int):
    return analytics.diagnose(cid)


@api.post("/analytics/act/{cid}")
def analytics_act(cid: int):
    return analytics.act(cid)


@api.get("/analytics/history/{pid}")
def analytics_history(pid: int, s: Session = Depends(get_session)):
    return [m.model_dump() for m in s.exec(select(MetricSnapshot).where(MetricSnapshot.publication_id == pid)
                                           .order_by(MetricSnapshot.captured_at)).all()]


# ------------------------------------------------------------------ cofre
@api.get("/finance/budget")
def fin_budget():
    return finance.budget_status()


@api.get("/finance/pnl")
def fin_pnl(days: int = 90):
    return finance.pnl(days)


@api.post("/finance/allocate")
def fin_allocate():
    return finance.allocate_budget()


class RevenueIn(BaseModel):
    amount: float
    channel_id: int | None = None
    memo: str = ""
    category: str = "revenue_ads"


@api.post("/finance/revenue")
def fin_revenue(body: RevenueIn):
    finance.book_revenue(body.amount, body.memo, body.channel_id, category=body.category)
    return finance.budget_status()


@api.get("/finance/ledger")
def fin_ledger(limit: int = 200, s: Session = Depends(get_session)):
    return [e.model_dump() for e in s.exec(select(LedgerEntry).order_by(LedgerEntry.at.desc()).limit(limit)).all()]


class YppIn(BaseModel):
    subs: int = 0
    watch_hours: float = 0
    shorts_views_90d: int = 0
    daily_subs: float = 0
    daily_hours: float = 0
    daily_shorts_views: float = 0


@api.post("/finance/ypp")
def fin_ypp(body: YppIn):
    return finance.ypp_projection(**body.model_dump())


# ------------------------------------------------------------------ piloto automático
class RunIn(BaseModel):
    dry_run: bool = False
    render: bool = True


@api.post("/autopilot/run")
def autopilot_run(body: RunIn, bg: BackgroundTasks):
    if body.dry_run:
        return autopilot.run_cycle(dry_run=True)
    bg.add_task(autopilot.run_cycle, False, body.render)
    return {"started": True}


@api.get("/autopilot/runs")
def autopilot_runs(s: Session = Depends(get_session)):
    return [j.model_dump() for j in s.exec(select(JobRun).order_by(JobRun.id.desc()).limit(20)).all()]


@api.get("/dashboard")
def dashboard(s: Session = Depends(get_session)):
    vids = s.exec(select(Video)).all()
    pubs = s.exec(select(Publication)).all()
    ideas_ = s.exec(select(Idea).where(Idea.status != "discarded")).all()
    pipeline_counts: dict[str, int] = {}
    for i in ideas_:
        pipeline_counts[i.status] = pipeline_counts.get(i.status, 0) + 1
    perf = analytics.performance_table()
    return {
        "channels": len(s.exec(select(Channel).where(Channel.status == "active")).all()),
        "ideas": pipeline_counts, "videos": {st: sum(1 for v in vids if v.status == st)
                                             for st in {v.status for v in vids}},
        "publications": {st: sum(1 for p in pubs if p.status == st) for st in {p.status for p in pubs}},
        "trends": len(trends.latest(100)),
        "views_total": sum(r["views"] for r in perf), "revenue_total": round(sum(r["revenue"] for r in perf), 2),
        "top": perf[:5], "budget": finance.budget_status(), "pnl": finance.pnl(30),
        "today": autopilot.today()["actions"][:6],
        "recent_trends": [t.model_dump(include={"id", "topic", "opportunity", "longevity", "momentum", "niche_key"})
                          for t in trends.latest(8)],
    }
