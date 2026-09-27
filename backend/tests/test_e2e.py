"""Ciclo completo em modo offline: estratégia -> canal -> marca -> ideias -> produção (render real com ffmpeg)
-> Guardião -> agendamento -> exportação -> métricas -> diagnóstico -> escala -> piloto automático."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.production import media


def test_full_cycle():
    with TestClient(app) as c:
        concepts = c.post("/api/strategy/concepts", json={"language": "en", "budget": 60, "count": 2}).json()
        con = concepts["concepts"][0]
        names = c.post("/api/strategy/names", json={"niche_key": con["niche_key"], "count": 5,
                                                    "check_handles": False}).json()
        ch = c.post("/api/channels", json={"name": names[0]["name"], "niche_key": con["niche_key"], "language": "en",
                                           "target_geos": ["US", "GB"], "strategy": con}).json()
        cid = ch["id"]

        kit = c.post(f"/api/channels/{cid}/branding", json={}).json()
        assert kit["description"] and kit["avatar_url"] and kit["banner_url"]
        from PIL import Image

        assert Image.open(kit["banner_path"]).size == (2560, 1440)
        assert Image.open(kit["avatar_path"]).size == (800, 800)

        aud = c.post("/api/audience", json={"niche_key": con["niche_key"], "channel_id": cid, "deep": False}).json()
        assert aud["economics"]["rpm_long"] > 0 and aud["economics"]["geo_table"]

        gen = c.post("/api/ideas/generate", json={"channel_id": cid, "count": 6, "fmt": "short"}).json()
        assert len(gen) >= 3
        best = max(gen, key=lambda i: i["score"])
        plan = c.post(f"/api/production/plan/{best['id']}").json()
        assert plan["mode"] and plan["options"]

        v = c.post("/api/production/produce", json={"idea_id": best["id"]}).json()
        video = c.get(f"/api/videos/{v['id']}").json()
        assert video["status"] == "ready", video["log"]
        out = Path(video["output_path"])
        assert out.exists() and media.has_audio(out)
        assert 15 <= media.duration(out) <= 70
        assert video["compliance"]["verdict"] in ("publish", "fix_then_publish")
        assert Path(video["thumbnail_path"]).exists()

        pubs = c.post(f"/api/publish/schedule/{cid}", params={"publish_now": True}).json()
        assert len(pubs) == 1
        pub = c.get("/api/publications").json()[0]
        assert pub["status"] == "exported"
        assert (Path(pub["url"]) / "metadata.json").exists()

        plan_pub = c.get(f"/api/publish/plan/{cid}").json()
        assert plan_pub["frequency"]["shorts_per_day"] >= 1 and len(plan_pub["heatmap"]["short"]) == 7

        # métricas: vencedor claro (8× a baseline heurística de 1500 views/semana)
        c.post(f"/api/analytics/metrics/{pub['id']}", json={"views": 25000, "likes": 1200, "comments": 90,
                                                            "avg_view_pct": 88, "ctr": 7.5, "age_hours": 100,
                                                            "revenue_usd": 1.2})
        diag = c.post(f"/api/analytics/diagnose/{cid}").json()
        assert diag["videos"][0]["verdict"] == "scale"
        acted = c.post(f"/api/analytics/act/{cid}").json()
        assert acted["scaled"] == 1 and acted["ideas_created"] >= 1

        pnl = c.get("/api/finance/pnl").json()
        assert pnl["revenue"] == 1.2

        dry = c.post("/api/autopilot/run", json={"dry_run": True}).json()
        assert dry["status"] == "ok"
        dash = c.get("/api/dashboard").json()
        assert dash["channels"] == 1
