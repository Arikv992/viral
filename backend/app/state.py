"""Definições editáveis em runtime (UI) que sobrepõem o .env."""
from __future__ import annotations

from typing import Any

from .config import get_settings
from .db import session_scope
from .models import AppState

EDITABLE = {
    "monthly_budget_usd": float,
    "reinvest_ratio": float,
    "autopilot_enabled": bool,
    "autopilot_interval_hours": int,
    "auto_publish": bool,
    "max_videos_per_cycle": int,
    "min_idea_score": float,
}

DEFAULTS = {"max_videos_per_cycle": 6, "min_idea_score": 55.0}


def get_state(key: str, default: Any = None) -> Any:
    with session_scope() as s:
        row = s.get(AppState, key)
        return row.value.get("v", default) if row else default


def set_state(key: str, value: Any) -> None:
    with session_scope() as s:
        row = s.get(AppState, key)
        if row:
            row.value = {"v": value}
        else:
            row = AppState(key=key, value={"v": value})
        s.add(row)
        s.commit()


def setting(key: str) -> Any:
    """Valor efetivo: AppState (UI) > .env > DEFAULTS."""
    v = get_state(f"setting:{key}")
    if v is not None:
        return v
    return getattr(get_settings(), key, DEFAULTS.get(key))


def all_settings() -> dict[str, Any]:
    return {k: setting(k) for k in EDITABLE}


def update_settings(values: dict[str, Any]) -> dict[str, Any]:
    for k, v in values.items():
        if k in EDITABLE and v is not None:
            set_state(f"setting:{k}", EDITABLE[k](v))
    return all_settings()
