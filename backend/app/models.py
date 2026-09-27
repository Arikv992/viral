"""Modelo de dados. Um fluxo único: Trend -> Idea -> Video -> Publication -> MetricSnapshot,
com cada cêntimo gasto/ganho registado no Ledger."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def now() -> datetime:
    return datetime.now(timezone.utc)


def JSONField(default: Any = None) -> Any:  # noqa: N802
    factory = (lambda: dict(default)) if isinstance(default, dict) else (lambda: list(default or []))
    return Field(default_factory=factory, sa_column=Column(JSON))


class Channel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    handle: str = ""
    niche_key: str = ""
    language: str = "en"
    target_geos: list = JSONField(["US"])
    formats: list = JSONField(["short", "long"])  # short | long
    status: str = "planning"  # planning | active | paused | killed
    youtube_channel_id: str = ""
    oauth_token: dict = JSONField({})
    branding: dict = JSONField({})  # descrição, keywords, caminhos de avatar/banner, paleta
    strategy: dict = JSONField({})  # pilares, persona, tom, frequência alvo
    monthly_budget_share: float = 0.0  # fração do orçamento atribuída pelo Cofre
    created_at: datetime = Field(default_factory=now)


class Trend(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    topic: str = Field(index=True)
    source: str = ""  # youtube | google_trends | wikipedia | autocomplete | reddit | manual
    geo: str = "US"
    niche_key: str = ""
    momentum: float = 0.0  # 0-100 força agora
    longevity: str = ""  # flash | wave | evergreen | seasonal
    longevity_days: int = 0  # estimativa de vida útil
    saturation: float = 0.0  # 0-100 concorrência
    opportunity: float = 0.0  # 0-100 score final
    series: list = JSONField([])  # série temporal usada no diagnóstico
    evidence: dict = JSONField({})  # vídeos/queries/links que suportam
    analysis: dict = JSONField({})  # enriquecimento LLM (ângulos, ganchos, riscos)
    created_at: datetime = Field(default_factory=now)


class Idea(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    channel_id: Optional[int] = Field(default=None, foreign_key="channel.id", index=True)
    trend_id: Optional[int] = Field(default=None, foreign_key="trend.id")
    parent_video_id: Optional[int] = None  # quando nasce de um vencedor (escala)
    title: str
    hook: str = ""
    angle: str = ""
    format: str = "short"  # short | long
    pillar: str = ""
    series_key: str = ""  # cluster/série consolidada
    status: str = "backlog"  # backlog | approved | producing | ready | published | discarded
    scores: dict = JSONField({})  # demand, momentum, ctr, rpm, cost, risk, total
    score: float = 0.0
    notes: str = ""
    origin: str = "generated"  # generated | trend | scale | republish | manual
    created_at: datetime = Field(default_factory=now)


class Video(SQLModel, table=True):
    """Um trabalho de produção. Guarda o plano, o guião e os ficheiros gerados."""

    id: Optional[int] = Field(default=None, primary_key=True)
    idea_id: Optional[int] = Field(default=None, foreign_key="idea.id", index=True)
    channel_id: Optional[int] = Field(default=None, foreign_key="channel.id", index=True)
    format: str = "short"
    mode: str = ""  # ver services/production/planner.py MODES
    status: str = "planned"  # planned | scripting | rendering | ready | failed | published
    plan: dict = JSONField({})  # decisão do planner (custos, ROI, justificação)
    script: dict = JSONField({})  # guião estruturado
    packaging: dict = JSONField({})  # títulos, thumbnail, descrição, tags
    compliance: dict = JSONField({})
    source: dict = JSONField({})  # p/ recortes: url, licença, segmentos
    output_path: str = ""
    thumbnail_path: str = ""
    duration_s: float = 0.0
    cost_usd: float = 0.0
    log: list = JSONField([])
    created_at: datetime = Field(default_factory=now)


class Publication(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    video_id: int = Field(foreign_key="video.id", index=True)
    channel_id: Optional[int] = Field(default=None, foreign_key="channel.id")
    platform: str = "youtube"  # youtube | youtube_shorts | tiktok
    external_id: str = ""
    url: str = ""
    title: str = ""
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    status: str = "scheduled"  # scheduled | published | exported | failed
    attempt: int = 1  # >1 = republicação
    verdict: str = ""  # scale | repackage | rehook | kill | hold | hidden_gem
    diagnosis: dict = JSONField({})


class MetricSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    publication_id: int = Field(foreign_key="publication.id", index=True)
    captured_at: datetime = Field(default_factory=now)
    age_hours: float = 0.0
    views: int = 0
    likes: int = 0
    comments: int = 0
    impressions: int = 0
    ctr: float = 0.0  # %
    avg_view_pct: float = 0.0  # % retenção média
    avg_view_s: float = 0.0
    subs_gained: int = 0
    revenue_usd: float = 0.0


class LedgerEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    at: datetime = Field(default_factory=now, index=True)
    kind: str = "cost"  # cost | revenue
    category: str = ""  # llm | tts | image | video_ai | stock | revenue_ads | ...
    amount_usd: float = 0.0
    channel_id: Optional[int] = None
    video_id: Optional[int] = None
    memo: str = ""


class AppState(SQLModel, table=True):
    """Chave/valor para definições editáveis na UI (sobrepõem o .env)."""

    key: str = Field(primary_key=True)
    value: dict = JSONField({})


class JobRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = ""
    started_at: datetime = Field(default_factory=now)
    finished_at: Optional[datetime] = None
    status: str = "running"  # running | ok | error
    summary: dict = JSONField({})
