import math

from app.knowledge.geo import effective_rpm_mult
from app.services import compliance, finance, ideas, strategy, timing
from app.services.production import captions, clipper, planner
from app.services.trends import analyze_series, opportunity


def test_series_flash():
    s = [10] * 80 + [12, 15, 400, 900, 700, 420, 260, 170, 110]
    d = analyze_series(s)
    assert d["longevity"] == "flash"
    assert 1 <= d["longevity_days"] <= 21


def test_series_evergreen():
    s = [100 + 10 * math.sin(i / 7) for i in range(120)]
    assert analyze_series(s)["longevity"] == "evergreen"


def test_series_rising_wave_has_momentum():
    s = [20] * 60 + [20 + i * 3 for i in range(40)]
    d = analyze_series(s)
    assert d["momentum"] > 60


def test_seasonal_detected():
    s = [100 + (400 if (i % 365) in range(330, 360) else 0) for i in range(760)]
    assert analyze_series(s)["longevity"] == "seasonal"


def test_opportunity_prefers_high_rpm():
    assert opportunity(70, "wave", 40, "finance_explained") > opportunity(70, "wave", 40, "reddit_stories")


def test_rpm_language_ordering():
    assert effective_rpm_mult("en") > effective_rpm_mult("pt") > 0


def test_rank_niches_and_names():
    ranked = strategy.rank_niches("en", 50)
    assert ranked[0]["score"] >= ranked[-1]["score"]
    names = strategy.generate_names("dark_history", count=8, check_handles=False)
    assert len(names) == 8 and all(n["handle"] and " " not in n["handle"] for n in names)


def test_concepts_heuristic():
    out = strategy.channel_concepts("en", 40, count=3)
    assert out["source"] == "heuristic" and len(out["concepts"]) == 3
    assert len(out["concepts"][0]["first_10_videos"]) == 10


def test_idea_dedupe_tokens():
    a = ideas.tokens("The Hidden Cost of Credit Cards")
    b = ideas.tokens("The hidden cost of credit cards!")
    assert ideas.jaccard(a, b) == 1.0


def test_planner_blocks_unlicensed_clips_and_respects_budget():
    p = planner.plan({"expected_views": 3000, "rpm": 0.08}, "short", "mysteries_unexplained",
                     capabilities={"ai_video": False})
    opts = {o["mode"]: o for o in p["options"]}
    assert opts["clip_commentary"]["blocked"]
    assert opts["ai_video_full"]["blocked"]
    assert p["mode"] not in ("clip_commentary", "ai_video_full")
    assert p["chosen"]["cost"]["total"] < 1.0


def test_planner_long_gets_midroll_duration():
    assert planner.target_duration("long") >= 480
    assert planner.target_duration("long", "history_for_sleep") >= 3600


def test_budget_and_reinvest():
    finance.book_cost("llm", 3.0, "x")
    b = finance.budget_status()
    assert b["spent"] == 3.0 and b["remaining"] == b["budget"] - 3.0


def test_ypp_projection():
    r = finance.ypp_projection(500, 1000, 0, daily_subs=50, daily_hours=100, daily_shorts_views=0)
    assert r["best_path"] == "long" and r["eta_days"] == 30


def test_compliance_words():
    assert "murder" in compliance.scan_words("The Murder nobody solved")
    assert "murder" not in compliance.auto_fix_title("The Murder nobody solved").lower()


def test_clip_heuristics_and_vtt():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nThis is the secret nobody knew\n\n" \
          "00:00:04.000 --> 00:00:08.000\nwhy did 3 million people believe it?\n"
    segs = clipper.parse_vtt(vtt)
    assert len(segs) == 2 and segs[0]["text"].startswith("This is")
    long = [{"start": i * 4.0, "end": i * 4.0 + 4, "text": ("why the secret million " if i % 7 == 0 else "and then ")
             * 3} for i in range(60)]
    clips = clipper.heuristic_clips(long, 3)
    assert len(clips) == 3
    assert all(25 <= c["end"] - c["start"] <= 60 for c in clips)


def test_ass_captions(tmp_path):
    words = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.35} for i, w in enumerate("one two three four".split())]
    p = captions.build_ass(words, "short", tmp_path / "c.ass", [{"text": "Hook", "start": 0, "end": 1}])
    txt = p.read_text()
    assert "Dialogue" in txt and "HOOK" in txt and "\\c&H00D7FF&" in txt


def test_timing_slots_revenue_weighted():
    from app.models import Channel

    ch = Channel(id=999, name="t", language="en", target_geos=["US"])
    w = timing.audience_weights(ch)
    assert max(w, key=w.get) == "US"
    slots = timing.best_slots(ch, "long", 3)
    assert len(slots) == 3
    # longos: um por dia no máximo
    hours = sorted(s["weekday"] * 24 + s["hour_utc"] for s in slots)
    assert all(b - a >= 20 for a, b in zip(hours, hours[1:]))
