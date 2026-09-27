"""Render do modo recorte com uma fonte sintética (sem rede): intro com gancho + recorte vertical + legendas."""
from app.db import session_scope
from app.models import Channel, Idea, Video
from app.services.production import media, pipeline


def test_clip_render(tmp_path):
    src = tmp_path / "source.mp4"
    media.run(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=40", "-f", "lavfi", "-i",
               "sine=frequency=330:duration=40", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
               src])
    segs = [{"start": i * 4.0, "end": i * 4.0 + 4, "text": "this is the secret nobody told you about"} for i in range(10)]
    info = {"id": "abc", "title": "Source", "channel": "Creator", "url": "https://youtu.be/abc",
            "license": "Creative Commons Attribution license (reuse allowed)", "is_cc": True, "duration": 40}
    clip = {"start": 5.0, "end": 30.0, "hook_text": "Watch what happens at the end", "headline": "The hidden detail",
            "context": "Why this matters", "why": "forte", "virality": 80}
    with session_scope() as s:
        ch = Channel(name="Clips", niche_key="engineering_disasters", status="active")
        s.add(ch)
        s.commit()
        s.refresh(ch)
        idea = Idea(channel_id=ch.id, title="clip", format="short")
        s.add(idea)
        s.commit()
        s.refresh(idea)
        v = Video(idea_id=idea.id, channel_id=ch.id, format="short", mode="clip_commentary",
                  source={**info, "clips": [clip]})
        s.add(v)
        s.commit()
        s.refresh(v)
    out = pipeline._render_clip(v.id, ch, info, segs, clip, str(src))
    assert out.status == "ready", out.log
    d = media.duration(out.output_path)
    assert 25 <= d <= 32 and media.has_audio(out.output_path)
    assert "Creative Commons" in out.packaging["description"]  # atribuição obrigatória
