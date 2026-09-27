from datetime import timedelta

from app.db import session_scope
from app.models import Channel, Idea, Publication, Video, now
from app.services import publisher


def test_republish_is_spaced_and_counted():
    with session_scope() as s:
        ch = Channel(name="R", niche_key="dark_history", status="active", oauth_token={"tiktok": {"access_token": "x"}})
        s.add(ch)
        s.commit()
        s.refresh(ch)
        old_idea = Idea(channel_id=ch.id, title="Original", format="short", status="published")
        s.add(old_idea)
        s.commit()
        s.refresh(old_idea)
        old = Video(idea_id=old_idea.id, channel_id=ch.id, format="short", status="published")
        s.add(old)
        s.commit()
        s.refresh(old)
        s.add(Publication(video_id=old.id, channel_id=ch.id, status="published", published_at=now() - timedelta(days=2)))
        idea = Idea(channel_id=ch.id, title="Original v2", format="short", origin="republish",
                    parent_video_id=old.id, status="ready")
        s.add(idea)
        s.commit()
        s.refresh(idea)
        s.add(Video(idea_id=idea.id, channel_id=ch.id, format="short", status="ready", packaging={"title": "v2"}))
        s.commit()
    created = publisher.schedule_channel(ch.id, publish_now=False)
    assert len(created) == 1
    p = created[0]
    assert p.attempt == 2
    assert p.scheduled_at >= now() + timedelta(days=4)  # >= 7 dias após a original (publicada há 2)
    with session_scope() as s:
        from sqlmodel import select

        tiktok = s.exec(select(Publication).where(Publication.platform == "tiktok")).all()
    assert len(tiktok) == 1
