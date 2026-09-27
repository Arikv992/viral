"""PILOTO AUTOMÁTICO: o ciclo inteiro, a cada N horas, com travões de orçamento e de qualidade.

1. Orçamento: se o mês está gasto, só corre análise (custo zero).
2. Radar: scan dos nichos dos canais ativos.
3. Ideias: repõe o banco de cada canal (mín. 12 ideias vivas), com tendências e vencedores.
4. Capital: realoca orçamento entre canais (bandit sobre ROI).
5. Fábrica: produz as melhores ideias até cobrir a frequência recomendada para as próximas 48h.
6. Publicação: agenda nos melhores slots; publica automaticamente só se `auto_publish` estiver ligado.
7. Análise: sincroniza métricas, diagnostica e age (escala/republica/reembala/mata).
"""
from __future__ import annotations

import logging
import traceback

from sqlmodel import select

from ..db import session_scope, touch
from ..models import Channel, Idea, JobRun, Publication, Video, now
from ..state import setting
from . import analytics, finance, ideas, publisher, timing, trends
from .production import pipeline, planner

log = logging.getLogger("viral.autopilot")


def _needed(ch: Channel) -> dict[str, int]:
    """Quantos vídeos de cada formato faltam para cobrir as próximas 48h."""
    freq = timing.frequency(ch)
    need = {"short": freq["shorts_per_day"] * 2, "long": max(1, round(freq["long_per_week"] * 2 / 7))
            if freq["long_per_week"] else 0}
    with session_scope() as s:
        vids = s.exec(select(Video).where(Video.channel_id == ch.id,
                                          Video.status.in_(["ready", "rendering", "scripting", "planned"]))).all()
        pubs = s.exec(select(Publication).where(Publication.channel_id == ch.id,
                                                Publication.status == "scheduled")).all()
        pub_vids = {p.video_id for p in pubs}
        for fmt in need:
            have = sum(1 for v in vids if v.format == fmt and v.id not in pub_vids) + \
                sum(1 for p in pubs if (s.get(Video, p.video_id) or Video()).format == fmt)
            need[fmt] = max(0, need[fmt] - have)
    return need


def run_cycle(dry_run: bool = False, render: bool = True) -> dict:
    with session_scope() as s:
        job = JobRun(kind="autopilot")
        s.add(job)
        s.commit()
        s.refresh(job)
    summary: dict = {"steps": []}

    def step(name: str, data) -> None:
        summary["steps"].append({"step": name, "result": data})
        log.info("autopilot %s: %s", name, data)

    try:
        with session_scope() as s:
            chans = s.exec(select(Channel).where(Channel.status == "active")).all()
        if not chans:
            step("canais", "Nenhum canal ativo — cria/ativa um canal na Estratégia.")
            return _finish(job.id, "ok", summary)
        status = finance.budget_status()
        broke = status["remaining"] <= 0.01
        step("orçamento", {"restante": status["remaining"], "orçamento": status["budget"], "sem_verba": broke})

        # 2. radar
        niche_keys = sorted({c.niche_key for c in chans if c.niche_key})
        langs = {c.language for c in chans}
        found = []
        if not broke and not dry_run:
            for lang in langs:
                geo = next((c.target_geos[0] for c in chans if c.language == lang and c.target_geos), "US")
                found += trends.scan([k for k in niche_keys if any(c.niche_key == k and c.language == lang
                                                                   for c in chans)], geo=geo, lang=lang)
        step("radar", {"tendências": len(found)})

        # 3. ideias
        created = 0
        for ch in chans:
            with session_scope() as s:
                alive = len(s.exec(select(Idea).where(Idea.channel_id == ch.id,
                                                      Idea.status.in_(["backlog", "approved"]))).all())
            if alive < 12 and not broke and not dry_run:
                hot = [t.id for t in trends.latest(20, ch.niche_key) if (t.analysis or {}).get("verdict") != "skip"][:6]
                fmt = "both" if len(ch.formats) > 1 else ch.formats[0]
                created += len(ideas.generate(ch.id, count=15, fmt=fmt, trend_ids=hot,
                                              winners=ideas.winners_for(ch.id)))
        step("ideias", {"criadas": created})

        # 4. capital
        alloc = finance.allocate_budget()
        step("capital", {a["name"]: a["share"] for a in alloc["allocations"]} | {"avisos": alloc["notes"]})

        # 5. fábrica
        produced, skipped = [], []
        max_videos = int(setting("max_videos_per_cycle"))
        min_score = float(setting("min_idea_score"))
        if not broke:
            for ch in chans:
                need = _needed(ch)
                for fmt, n in need.items():
                    if n <= 0:
                        continue
                    with session_scope() as s:
                        cands = s.exec(select(Idea).where(Idea.channel_id == ch.id, Idea.format == fmt,
                                                          Idea.status.in_(["approved", "backlog"]))).all()
                    cands = sorted(cands, key=lambda i: (i.status != "approved", -i.score))
                    for idea in cands[:n]:
                        if len(produced) >= max_videos:
                            break
                        if idea.status != "approved" and idea.score < min_score:
                            skipped.append({"idea": idea.id, "motivo": f"score {idea.score} < {min_score}"})
                            continue
                        est = planner.estimate_cost("ai_images_narrated", fmt, planner.target_duration(fmt, ch.niche_key))
                        if not finance.can_spend(est["total"]):
                            skipped.append({"idea": idea.id, "motivo": "orçamento"})
                            continue
                        if dry_run:
                            produced.append({"idea": idea.id, "title": idea.title, "dry_run": True})
                            continue
                        try:
                            v = pipeline.produce_idea(idea.id, render=render)
                            produced.append({"idea": idea.id, "video": v.id, "status": v.status})
                        except Exception as e:  # noqa: BLE001
                            produced.append({"idea": idea.id, "erro": str(e)[:200]})
        step("fábrica", {"produzidos": produced, "ignorados": skipped[:20]})

        # 6. publicação
        scheduled = 0
        if not dry_run:
            for ch in chans:
                scheduled += len(publisher.schedule_channel(ch.id))
        step("publicação", {"agendados": scheduled, "auto_publish": bool(setting("auto_publish"))})

        # 7. análise
        acted = {}
        if not dry_run:
            for ch in chans:
                try:
                    analytics.sync_channel(ch.id)
                except Exception as e:  # noqa: BLE001
                    log.info("sync %s: %s", ch.id, e)
                acted[ch.name] = analytics.act(ch.id)
        step("análise", acted)
        return _finish(job.id, "ok", summary)
    except Exception as e:  # noqa: BLE001
        summary["error"] = str(e)
        summary["trace"] = traceback.format_exc()[-2000:]
        return _finish(job.id, "error", summary)


def _finish(job_id: int, status: str, summary: dict) -> dict:
    with session_scope() as s:
        job = s.get(JobRun, job_id)
        job.status, job.finished_at, job.summary = status, now(), summary
        touch(job, "summary")
        s.add(job)
        s.commit()
    return {"job_id": job_id, "status": status, **summary}


_scheduler = None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler or not setting("autopilot_enabled"):
        return
    from apscheduler.schedulers.background import BackgroundScheduler

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(run_cycle, "interval", hours=int(setting("autopilot_interval_hours")), id="cycle",
                       max_instances=1, coalesce=True)
    _scheduler.add_job(_publish_due, "interval", minutes=15, id="publish_due", max_instances=1)
    _scheduler.start()
    log.info("piloto automático ligado")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def _publish_due() -> None:
    if not setting("auto_publish"):
        return
    for p in publisher.due_publications():
        publisher.publish(p.id)


def today() -> dict:
    """'O que fazer hoje': a lista de ações de maior impacto, calculada do estado atual."""
    actions = []
    with session_scope() as s:
        chans = s.exec(select(Channel)).all()
        active = [c for c in chans if c.status == "active"]
        ready = s.exec(select(Video).where(Video.status == "ready")).all()
        sched_ids = {p.video_id for p in s.exec(select(Publication)).all()}
        winners = s.exec(select(Publication).where(Publication.verdict == "scale")).all()
        gems = s.exec(select(Publication).where(Publication.verdict == "republish")).all()
        approved = s.exec(select(Idea).where(Idea.status == "approved")).all()
        failed = s.exec(select(Video).where(Video.status == "failed")).all()
    if not chans:
        actions.append({"priority": 1, "area": "estrategia", "text": "Cria o primeiro canal: abre Estratégia e escolhe "
                        "um conceito com maior lucro a 12 meses."})
    elif not active:
        actions.append({"priority": 1, "area": "canais", "text": "Ativa pelo menos um canal para o piloto automático."})
    for c in active:
        if not (c.branding or {}).get("avatar_path"):
            actions.append({"priority": 2, "area": "estudio", "text": f"Gera o kit de marca de '{c.name}'."})
        if not (c.oauth_token or {}).get("google"):
            actions.append({"priority": 3, "area": "publicacao",
                            "text": f"Liga o YouTube de '{c.name}' (OAuth) para publicar e ler Analytics — "
                                    "até lá os vídeos são exportados para upload manual."})
    unscheduled = [v for v in ready if v.id not in sched_ids]
    if unscheduled:
        actions.append({"priority": 1, "area": "publicacao",
                        "text": f"{len(unscheduled)} vídeo(s) pronto(s) por agendar — agenda nos melhores horários."})
    if winners:
        actions.append({"priority": 1, "area": "analise", "text": f"{len(winners)} vencedor(es) — escala a série."})
    if gems:
        actions.append({"priority": 2, "area": "analise", "text": f"{len(gems)} joia(s) escondida(s) para republicar."})
    if approved:
        actions.append({"priority": 2, "area": "fabrica", "text": f"{len(approved)} ideia(s) aprovada(s) à espera de produção."})
    if failed:
        actions.append({"priority": 3, "area": "fabrica", "text": f"{len(failed)} vídeo(s) falharam/bloqueados — rever."})
    b = finance.budget_status()
    if not b["on_track"]:
        actions.append({"priority": 1, "area": "cofre", "text": f"Ritmo de gasto acima do orçamento "
                        f"(projeção ${b['projected_spend']} vs ${b['budget']}) — reduzir modos caros."})
    return {"actions": sorted(actions, key=lambda a: a["priority"]), "budget": b}
