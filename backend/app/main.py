"""Ponto de entrada: `uvicorn app.main:app` (a partir de backend/)."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import api
from .config import ROOT, get_settings
from .db import init_db
from .services import autopilot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    autopilot.start_scheduler()
    yield
    autopilot.stop_scheduler()


app = FastAPI(title="VIRAL-OPS", version="1.0", lifespan=lifespan)
if os.environ.get("VERCEL"):
    init_db()  # funções serverless podem não correr o lifespan: garantir as tabelas no arranque
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
app.include_router(api)
app.mount("/media", StaticFiles(directory=str(get_settings().media_dir)), name="media")

WEB = ROOT / "web" / "dist"
if WEB.exists():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
else:
    @app.get("/")
    def root():
        return {"app": "VIRAL-OPS", "docs": "/docs", "hint": "cd web && npm install && npm run build"}



