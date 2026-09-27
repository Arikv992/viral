"""COFRE — o centro de lucro.

- Livro-razão de cada custo (API, voz, imagens, vídeo IA) e de cada receita.
- Orçamento mensal dinâmico: base + reinvestimento automático de X% da receita do mês anterior.
- Alocação de capital entre canais por "bandit" (Thompson sampling sobre o ROI):
  canais que devolvem mais recebem mais orçamento; canais novos têm um piso de exploração;
  canais que falham os critérios de corte são congelados.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

from sqlmodel import select

from ..db import session_scope
from ..models import Channel, LedgerEntry, Publication, Video, now
from ..state import setting


def book_cost(category: str, amount: float, memo: str = "", channel_id: int | None = None,
              video_id: int | None = None) -> None:
    if amount <= 0:
        return
    with session_scope() as s:
        s.add(LedgerEntry(kind="cost", category=category, amount_usd=round(amount, 6), memo=memo[:300],
                          channel_id=channel_id, video_id=video_id))
        if video_id:
            v = s.get(Video, video_id)
            if v:
                v.cost_usd = round((v.cost_usd or 0) + amount, 6)
                s.add(v)
        s.commit()


def book_revenue(amount: float, memo: str = "", channel_id: int | None = None, video_id: int | None = None,
                 at: datetime | None = None, category: str = "revenue_ads") -> None:
    with session_scope() as s:
        s.add(LedgerEntry(kind="revenue", category=category, amount_usd=round(amount, 4), memo=memo[:300],
                          channel_id=channel_id, video_id=video_id, at=at or now()))
        s.commit()


def _month_bounds(ref: datetime) -> tuple[datetime, datetime]:
    start = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt


def _sum(kind: str, start: datetime, end: datetime, channel_id: int | None = None) -> float:
    with session_scope() as s:
        q = select(LedgerEntry).where(LedgerEntry.kind == kind, LedgerEntry.at >= start, LedgerEntry.at < end)
        if channel_id is not None:
            q = q.where(LedgerEntry.channel_id == channel_id)
        return round(sum(e.amount_usd for e in s.exec(q)), 4)


def budget_status(ref: datetime | None = None) -> dict:
    ref = ref or now()
    start, end = _month_bounds(ref)
    prev_start, _ = _month_bounds(start - timedelta(days=1))
    base = float(setting("monthly_budget_usd"))
    ratio = float(setting("reinvest_ratio"))
    prev_revenue = _sum("revenue", prev_start, start)
    reinvest = round(prev_revenue * ratio, 2)
    budget = round(base + reinvest, 2)
    spent = _sum("cost", start, end)
    revenue = _sum("revenue", start, end)
    days_elapsed = max((ref - start).total_seconds() / 86400, 0.5)
    days_total = (end - start).days
    burn = spent / days_elapsed
    return {
        "month": start.strftime("%Y-%m"),
        "base_budget": base,
        "reinvest_from_last_month": reinvest,
        "budget": budget,
        "spent": spent,
        "remaining": round(max(budget - spent, 0), 4),
        "revenue_month": revenue,
        "profit_month": round(revenue - spent, 4),
        "burn_per_day": round(burn, 4),
        "projected_spend": round(burn * days_total, 2),
        "daily_allowance": round(max(budget - spent, 0) / max(days_total - days_elapsed, 1), 4),
        "on_track": burn * days_total <= budget * 1.05,
    }


def can_spend(amount: float) -> bool:
    return amount <= budget_status()["remaining"] + 1e-9


def pnl(days: int = 90) -> dict:
    since = now() - timedelta(days=days)
    with session_scope() as s:
        entries = s.exec(select(LedgerEntry).where(LedgerEntry.at >= since)).all()
        channels = {c.id: c for c in s.exec(select(Channel)).all()}
        videos = {v.id: v for v in s.exec(select(Video)).all()}
    by_ch: dict = {}
    by_cat: dict = {}
    by_video: dict = {}
    for e in entries:
        key = e.channel_id or 0
        row = by_ch.setdefault(key, {"channel_id": key, "name": channels[key].name if key in channels else "Plataforma",
                                     "cost": 0.0, "revenue": 0.0})
        row[e.kind if e.kind == "revenue" else "cost"] += e.amount_usd
        by_cat[e.category] = round(by_cat.get(e.category, 0) + (e.amount_usd if e.kind == "cost" else 0), 4)
        if e.video_id:
            vr = by_video.setdefault(e.video_id, {"video_id": e.video_id, "cost": 0.0, "revenue": 0.0,
                                                  "title": (videos[e.video_id].packaging or {}).get("title", "")
                                                  if e.video_id in videos else ""})
            vr["revenue" if e.kind == "revenue" else "cost"] += e.amount_usd
    for row in list(by_ch.values()) + list(by_video.values()):
        row["cost"], row["revenue"] = round(row["cost"], 4), round(row["revenue"], 4)
        row["profit"] = round(row["revenue"] - row["cost"], 4)
        row["roi"] = round(row["profit"] / row["cost"], 2) if row["cost"] > 0 else None
    total_cost = sum(r["cost"] for r in by_ch.values())
    total_rev = sum(r["revenue"] for r in by_ch.values())
    return {
        "days": days,
        "cost": round(total_cost, 4),
        "revenue": round(total_rev, 4),
        "profit": round(total_rev - total_cost, 4),
        "roi": round((total_rev - total_cost) / total_cost, 2) if total_cost else None,
        "by_channel": sorted(by_ch.values(), key=lambda r: -r["profit"]),
        "by_category": by_cat,
        "top_videos": sorted(by_video.values(), key=lambda r: -r["profit"])[:20],
        "cost_per_video": round(total_cost / max(len(videos), 1), 4),
    }


def allocate_budget(seed: int | None = None) -> dict:
    """Thompson sampling: amostra o ROI de cada canal de uma Beta(sucessos, falhas) derivada do
    retorno por dólar. Canais novos (< 21 dias ou < 15 vídeos) recebem piso de exploração de 15%."""
    rng = random.Random(seed)
    status = budget_status()
    with session_scope() as s:
        chans = s.exec(select(Channel).where(Channel.status == "active")).all()
        pubs = s.exec(select(Publication)).all()
    if not chans:
        return {"allocations": [], "budget": status["budget"], "notes": ["Sem canais ativos."]}
    n_videos = {c.id: 0 for c in chans}
    for p in pubs:
        if p.channel_id in n_videos:
            n_videos[p.channel_id] += 1
    rows, notes = [], []
    for c in chans:
        start = now() - timedelta(days=60)
        cost = _sum("cost", start, now() + timedelta(days=1), c.id)
        rev = _sum("revenue", start, now() + timedelta(days=1), c.id)
        age_days = (now() - c.created_at).days
        young = age_days < 21 or n_videos[c.id] < 15
        # retorno por dólar -> pseudo-contagens (prior fraco Beta(1,1))
        ret = rev / cost if cost > 0 else 0.0
        a = 1 + 10 * min(ret, 5) / 5
        b = 1 + 10 * (1 - min(ret, 5) / 5)
        sample = rng.betavariate(a, b)
        rows.append({"channel_id": c.id, "name": c.name, "cost_60d": cost, "revenue_60d": rev,
                     "return_per_dollar": round(ret, 2), "young": young, "sample": sample,
                     "videos": n_videos[c.id], "age_days": age_days})
        if not young and n_videos[c.id] >= 30 and ret < 0.2 and age_days > 75:
            notes.append(f"{c.name}: {n_videos[c.id]} vídeos em {age_days} dias e só ${rev:.2f} por ${cost:.2f} "
                         "gasto — recomendação: CONGELAR e realocar orçamento.")
    floor = 0.15 if len(rows) > 1 else 1.0
    young_rows = [r for r in rows if r["young"]]
    reserved = min(floor * len(young_rows), 0.6)
    total_sample = sum(r["sample"] for r in rows) or 1.0
    for r in rows:
        share = (1 - reserved) * r["sample"] / total_sample + (floor if r["young"] else 0)
        r["share"] = share
    norm = sum(r["share"] for r in rows) or 1.0
    for r in rows:
        r["share"] = round(r["share"] / norm, 3)
        r["budget_usd"] = round(status["budget"] * r["share"], 2)
        del r["sample"]
    with session_scope() as s:
        for r in rows:
            ch = s.get(Channel, r["channel_id"])
            ch.monthly_budget_share = r["share"]
            s.add(ch)
        s.commit()
    return {"allocations": sorted(rows, key=lambda r: -r["share"]), "budget": status["budget"], "notes": notes}


def ypp_projection(subs: int, watch_hours: float, shorts_views_90d: int, daily_subs: float,
                   daily_hours: float, daily_shorts_views: float) -> dict:
    """Dias estimados até ao YPP pelos dois caminhos."""
    def days_to(target: float, have: float, rate: float) -> float:
        if have >= target:
            return 0
        return math.inf if rate <= 0 else (target - have) / rate

    subs_days = days_to(1000, subs, daily_subs)
    long_days = max(subs_days, days_to(4000, watch_hours, daily_hours))
    shorts_days = max(subs_days, days_to(10_000_000, shorts_views_90d, daily_shorts_views))
    best = min(long_days, shorts_days)
    return {"long_path_days": None if math.isinf(long_days) else round(long_days),
            "shorts_path_days": None if math.isinf(shorts_days) else round(shorts_days),
            "best_path": "long" if long_days <= shorts_days else "shorts",
            "eta_days": None if math.isinf(best) else round(best)}
