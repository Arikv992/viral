"""Exercita todos os ramos que consomem saídas do LLM, com um LLM falso que gera dados válidos a partir do schema."""
from pathlib import Path

from fastapi.testclient import TestClient

from app import llm as llm_mod
from app.main import app
from app.models import Trend

SENTENCE = "The ocean hides something nobody expected tonight"


def fake_from_schema(schema: dict, key: str = ""):
    t = schema.get("type")
    if "enum" in schema:
        return schema["enum"][0]
    if t == "object":
        return {k: fake_from_schema(v, k) for k, v in schema["properties"].items()}
    if t == "array":
        n = 12 if key == "scenes" else 3
        return [fake_from_schema(schema["items"], key) for _ in range(n)]
    if t == "string":
        if key in ("palette",):
            return "#112233"
        if key == "handle":
            return "vaultshadow"
        return SENTENCE if key in ("narration", "hook", "title", "name", "titles", "description") else f"{key} texto"
    if t == "integer":
        return 60
    if t == "number":
        return 1.0
    if t == "boolean":
        return False
    return None


def test_llm_branches(monkeypatch):
    calls = []

    def fake_json(self, *, system, prompt, schema, **kw):
        calls.append(kw.get("purpose"))
        assert system.startswith("You are VIRAL-OPS")
        return fake_from_schema(schema)

    monkeypatch.setattr(llm_mod.LLM, "available", property(lambda self: True))
    monkeypatch.setattr(llm_mod.LLM, "json", fake_json)

    with TestClient(app) as c:
        con = c.post("/api/strategy/concepts", json={"count": 2}).json()
        assert con["source"] == "llm"
        names = c.post("/api/strategy/names", json={"niche_key": "dark_history", "check_handles": False}).json()
        assert names[0]["handle"] == "vaultshadow"
        ch = c.post("/api/channels", json={"name": "Nocturne", "niche_key": "dark_history"}).json()
        kit = c.post(f"/api/channels/{ch['id']}/branding", json={}).json()
        assert kit["palette"] == ["#112233"] * 3
        aud = c.post("/api/audience", json={"niche_key": "dark_history", "channel_id": ch["id"], "deep": False}).json()
        assert aud["source"] == "llm"

        from app.services import trends

        t = Trend(topic="Roman Empire", niche_key="dark_history", momentum=60, longevity="wave", opportunity=50)
        trends.enrich([t], "US", "en")
        assert t.analysis["verdict"] == "ride_now"

        ideas = c.post("/api/ideas/generate", json={"channel_id": ch["id"], "count": 3, "fmt": "short"}).json()
        assert ideas, "ideia do LLM deve entrar (as restantes são duplicados e são fundidas)"
        v = c.post("/api/production/produce", json={"idea_id": ideas[0]["id"]}).json()
        video = c.get(f"/api/videos/{v['id']}").json()
        assert video["status"] == "ready", video["log"]
        assert video["script"]["source"] == "llm" and len(video["script"]["scenes"]) == 12
        assert video["packaging"]["source"] == "llm" and video["packaging"]["title"] == SENTENCE
        assert "#shorts" in video["packaging"]["description"]
        assert Path(video["output_path"]).exists()

    for purpose in ("channel_strategy", "channel_names", "branding", "audience", "trend_analysis", "ideas",
                    "script_short", "packaging"):
        assert purpose in calls, purpose
