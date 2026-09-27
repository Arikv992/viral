"""QUANDO e QUANTO publicar.

Horários: para cada uma das 168 horas da semana (UTC) soma-se a atividade esperada da audiência de cada
país, ponderada por (quota de audiência × RPM do país) — otimizamos RECEITA, não views brutas. Publica-se
antes do pico (longos ~2h, Shorts ~1h) para o vídeo estar indexado e testado quando o público chega.
Com >= 20 publicações medidas, as curvas aprendem com os teus próprios dados (views às 24h por hora).

Frequência: fase do canal × orçamento × canibalização observada (mais uploads a baixar views/vídeo)."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlmodel import select

from ..db import session_scope
from ..knowledge.geo import COUNTRIES, DEFAULT_AUDIENCE_MIX, LANGUAGES
from ..models import Channel, MetricSnapshot, Publication, Video, now
from .finance import budget_status

# atividade relativa por hora local (0-23)
LONG_WEEKDAY = [0.25, 0.15, 0.1, 0.07, 0.06, 0.08, 0.15, 0.25, 0.3, 0.32, 0.35, 0.4, 0.5, 0.52, 0.48, 0.5, 0.6,
                0.72, 0.85, 0.95, 1.0, 0.95, 0.75, 0.45]
LONG_WEEKEND = [0.35, 0.22, 0.14, 0.09, 0.07, 0.08, 0.12, 0.2, 0.35, 0.5, 0.65, 0.75, 0.8, 0.8, 0.78, 0.78, 0.8,
                0.85, 0.9, 0.95, 1.0, 0.92, 0.72, 0.5]
SHORT_WEEKDAY = [0.35, 0.2, 0.12, 0.08, 0.07, 0.12, 0.3, 0.55, 0.62, 0.5, 0.45, 0.5, 0.7, 0.72, 0.6, 0.6, 0.68,
                 0.78, 0.85, 0.92, 0.98, 1.0, 0.88, 0.6]
SHORT_WEEKEND = [0.45, 0.3, 0.18, 0.1, 0.08, 0.09, 0.14, 0.25, 0.4, 0.55, 0.68, 0.75, 0.8, 0.8, 0.78, 0.78, 0.8,
                 0.85, 0.9, 0.96, 1.0, 1.0, 0.85, 0.62]
LEAD_HOURS = {"long": 2, "short": 1}
DAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def audience_weights(channel: Channel) -> dict[str, float]:
    mix = DEFAULT_AUDIENCE_MIX.get(channel.language) or {g: 1 for g in LANGUAGES.get(channel.language, {}).get("geos", ["US"])}
    if channel.target_geos:
        # países-alvo explícitos pesam o dobro
        mix = {g: w * (2 if g in channel.target_geos else 1) for g, w in mix.items()}
        for g in channel.target_geos:
            mix.setdefault(g, 0.1)
    w = {g: share * COUNTRIES[g]["rpm_mult"] for g, share in mix.items() if g in COUNTRIES}
    tot = sum(w.values()) or 1
    return {g: v / tot for g, v in w.items()}


def weekly_heatmap(channel: Channel, fmt: str = "long") -> list[list[float]]:
    """heat[weekday_utc][hour_utc] = valor esperado (0-1) de PUBLICAR nesse slot (já com antecedência)."""
    weights = audience_weights(channel)
    heat = [[0.0] * 24 for _ in range(7)]
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)  # segunda-feira
    lead = LEAD_HOURS[fmt]
    for d in range(7):
        for h in range(24):
            slot = base + timedelta(days=d, hours=h + lead)  # quando o vídeo "chega" ao público
            val = 0.0
            for g, wgt in weights.items():
                loc = slot.astimezone(ZoneInfo(COUNTRIES[g]["tz"]))
                weekend = loc.weekday() >= 5
                curve = (LONG_WEEKEND if weekend else LONG_WEEKDAY) if fmt == "long" else \
                    (SHORT_WEEKEND if weekend else SHORT_WEEKDAY)
                # a janela seguinte à publicação também conta (3h)
                val += wgt * (curve[loc.hour] * 0.5 + curve[(loc.hour + 1) % 24] * 0.3 + curve[(loc.hour + 2) % 24] * 0.2)
            heat[d][h] = val
    learned = learned_heatmap(channel.id, fmt)
    if learned:
        n, lh = learned
        alpha = min(0.7, n / 60)
        mx = max(max(r) for r in heat) or 1
        heat = [[(1 - alpha) * heat[d][h] / mx + alpha * lh[d][h] for h in range(24)] for d in range(7)]
    mx = max(max(r) for r in heat) or 1
    return [[round(v / mx, 3) for v in row] for row in heat]


def learned_heatmap(channel_id: int | None, fmt: str) -> tuple[int, list[list[float]]] | None:
    if channel_id is None:
        return None
    with session_scope() as s:
        pubs = s.exec(select(Publication).where(Publication.channel_id == channel_id,
                                                Publication.published_at.is_not(None))).all()
        rows = []
        for p in pubs:
            v = s.get(Video, p.video_id)
            if not v or v.format != fmt:
                continue
            snaps = s.exec(select(MetricSnapshot).where(MetricSnapshot.publication_id == p.id)).all()
            near = [m for m in snaps if 18 <= m.age_hours <= 36]
            if near:
                rows.append((p.published_at, near[-1].views))
    if len(rows) < 20:
        return None
    med = statistics.median(v for _, v in rows) or 1
    acc: dict[tuple[int, int], list[float]] = defaultdict(list)
    for t, views in rows:
        acc[(t.weekday(), t.hour)].append(views / med)
    lh = [[0.0] * 24 for _ in range(7)]
    for d in range(7):
        for h in range(24):
            # suavização: média da vizinhança ±2h
            vals = [x for dh in range(-2, 3) for x in acc.get((d, (h + dh) % 24), [])]
            lh[d][h] = statistics.fmean(vals) if vals else 0.0
    mx = max(max(r) for r in lh) or 1
    return len(rows), [[v / mx for v in r] for r in lh]


def best_slots(channel: Channel, fmt: str, count: int = 5) -> list[dict]:
    heat = weekly_heatmap(channel, fmt)
    flat = sorted(((heat[d][h], d, h) for d in range(7) for h in range(24)), reverse=True)
    out, taken = [], []
    for val, d, h in flat:
        if any(min(abs((d * 24 + h) - (td * 24 + th)), 168 - abs((d * 24 + h) - (td * 24 + th)))
               < (20 if fmt == "long" else 3) for td, th in taken):
            continue
        taken.append((d, h))
        local = {}
        for g in list(audience_weights(channel))[:3]:
            dt = datetime(2024, 1, 1, h, tzinfo=timezone.utc) + timedelta(days=d)
            loc = dt.astimezone(ZoneInfo(COUNTRIES[g]["tz"]))
            local[g] = f"{DAYS[loc.weekday()]} {loc:%H:%M}"
        out.append({"weekday": d, "day": DAYS[d], "hour_utc": h, "score": val, "local": local})
        if len(out) >= count:
            break
    return out


def frequency(channel: Channel) -> dict:
    with session_scope() as s:
        pubs = s.exec(select(Publication).where(Publication.channel_id == channel.id)).all()
        vids = {p.video_id: s.get(Video, p.video_id) for p in pubs}
    n_short = sum(1 for p in pubs if vids.get(p.video_id) and vids[p.video_id].format == "short")
    n_long = len(pubs) - n_short
    stage = "lançamento" if len(pubs) < 30 else ("crescimento" if len(pubs) < 150 else "escala")
    shorts_day, long_week = {"lançamento": (2, 2), "crescimento": (2, 3), "escala": (3, 3)}[stage]
    reasons = [f"Fase '{stage}' ({n_short} Shorts, {n_long} longos publicados)."]
    if "short" not in channel.formats:
        shorts_day = 0
    if "long" not in channel.formats:
        long_week = 0
    # teto de orçamento
    from .production.planner import estimate_cost, target_duration

    b = budget_status()
    daily = b["daily_allowance"] * (channel.monthly_budget_share or 1.0)
    c_short = estimate_cost("ai_images_narrated", "short", target_duration("short"))["total"]
    c_long = estimate_cost("ai_images_narrated", "long", target_duration("long", channel.niche_key))["total"]
    need = shorts_day * c_short + long_week / 7 * c_long
    if need > daily > 0:
        f = daily / need
        shorts_day = max(1 if shorts_day else 0, int(shorts_day * f))
        long_week = max(1 if long_week else 0, int(long_week * f))
        reasons.append(f"Limitado pelo orçamento: ${daily:.2f}/dia para este canal (precisaria ${need:.2f}).")
    # canibalização: mais uploads/dia a reduzir views por vídeo?
    cann = cannibalization(channel.id)
    if cann is not None and cann < -0.25:
        shorts_day = max(1, shorts_day - 1)
        reasons.append(f"Canibalização detetada (correlação {cann:.2f} entre uploads/dia e views/vídeo): -1 Short/dia.")
    elif cann is not None and cann > 0.1 and stage != "lançamento":
        shorts_day += 1
        reasons.append("Mais uploads não estão a canibalizar (correlação positiva): +1 Short/dia.")
    reasons.append("Longos: consistência semanal nos mesmos dias/horas treina o público e o algoritmo.")
    return {"stage": stage, "shorts_per_day": shorts_day, "long_per_week": long_week, "reasons": reasons,
            "est_cost_per_short": round(c_short, 3), "est_cost_per_long": round(c_long, 3)}


def cannibalization(channel_id: int) -> float | None:
    since = now() - timedelta(days=60)
    with session_scope() as s:
        pubs = s.exec(select(Publication).where(Publication.channel_id == channel_id,
                                                Publication.published_at >= since)).all()
        by_day: dict = defaultdict(list)
        for p in pubs:
            snaps = s.exec(select(MetricSnapshot).where(MetricSnapshot.publication_id == p.id)).all()
            if snaps:
                by_day[p.published_at.date()].append(snaps[-1].views)
    if len(by_day) < 14:
        return None
    xs = [len(v) for v in by_day.values()]
    ys = [statistics.fmean(v) for v in by_day.values()]
    if len(set(xs)) < 2:
        return None
    return round(statistics.correlation(xs, ys), 3)


def next_slots(channel: Channel, fmt: str, n: int, after: datetime | None = None) -> list[datetime]:
    """Próximos n instantes (UTC naive) seguindo os melhores slots e a frequência recomendada."""
    after = after or now()
    freq = frequency(channel)
    per_week = freq["shorts_per_day"] * 7 if fmt == "short" else freq["long_per_week"]
    if per_week <= 0:
        return []
    slots = best_slots(channel, fmt, count=min(per_week, 21 if fmt == "short" else 7))
    with session_scope() as s:
        busy = {p.scheduled_at.replace(minute=0, second=0, microsecond=0)
                for p in s.exec(select(Publication).where(Publication.channel_id == channel.id,
                                                          Publication.scheduled_at >= after)).all() if p.scheduled_at}
    out: list[datetime] = []
    day0 = after.replace(hour=0, minute=0, second=0, microsecond=0)
    for week in range(8):
        cands = sorted(day0 + timedelta(days=(sl["weekday"] - day0.weekday()) % 7 + 7 * week, hours=sl["hour_utc"])
                       for sl in slots)
        for c in cands:
            if c > after + timedelta(minutes=30) and c not in busy and c not in out:
                out.append(c)
                if len(out) >= n:
                    return out
    return out
