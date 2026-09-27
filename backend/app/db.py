from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_engine = None


def engine():
    global _engine
    if _engine is None:
        url = get_settings().db_url
        args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=args)
    return _engine


def reset_engine() -> None:
    """Usado nos testes para apontar para outra base de dados."""
    global _engine
    _engine = None


def init_db() -> None:
    from . import models  # noqa: F401  (regista as tabelas)

    SQLModel.metadata.create_all(engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(engine(), expire_on_commit=False) as s:
        yield s


def get_session() -> Iterator[Session]:
    with Session(engine(), expire_on_commit=False) as s:
        yield s


def touch(obj: Any, *fields: str) -> None:
    """Marca colunas JSON como alteradas (mutação in-place não é detetada pelo SQLAlchemy)."""
    for f in fields:
        flag_modified(obj, f)
