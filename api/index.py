"""Entrada da função Python no Vercel: expõe a app FastAPI (as rotas /api/* e /media/* são reescritas para aqui)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import app  # noqa: E402,F401
