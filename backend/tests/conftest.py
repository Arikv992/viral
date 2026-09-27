import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

KEYS = ["ANTHROPIC_API_KEY", "YOUTUBE_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY", "FAL_API_KEY",
        "ELEVENLABS_API_KEY", "GOOGLE_CLIENT_SECRETS", "TIKTOK_CLIENT_KEY"]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Base de dados e media num diretório temporário; sem chaves (modo offline determinístico)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    for k in KEYS:
        monkeypatch.setenv(k, "")
    from app import db, llm
    from app.config import get_settings

    get_settings.cache_clear()
    db.reset_engine()
    llm.reset_llm()
    db.init_db()
    # rede desligada nos testes: fontes externas devolvem vazio
    from app.services import http

    monkeypatch.setattr(http, "get_json", lambda *a, **k: None)
    monkeypatch.setattr(http, "get_text", lambda *a, **k: None)
    for mod in ("app.services.trends", "app.services.youtube_data", "app.services.production.visuals"):
        m = sys.modules.get(mod) or __import__(mod, fromlist=["x"])
        if hasattr(m, "get_json"):
            monkeypatch.setattr(m, "get_json", lambda *a, **k: None)
        if hasattr(m, "get_text"):
            monkeypatch.setattr(m, "get_text", lambda *a, **k: None)
    from app.services.production import tts

    monkeypatch.setattr(tts, "_edge", lambda *a, **k: None)
    monkeypatch.setattr(tts, "_piper", lambda *a, **k: None)
    yield
    get_settings.cache_clear()
    db.reset_engine()
    os.environ.pop("DATA_DIR", None)
