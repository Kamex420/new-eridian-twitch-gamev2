"""Level-up lines name the other citizen ("Relationship with blake1215"), never their account id, everywhere they show."""
import json
from datetime import datetime, timezone
from sqlalchemy import select
from test_colony import m, reset
from app import readable_names
from app.stream_overlay import StreamHighlight
from app.activity_feed import FeedState
from app.inbox import InboxItem
from app.models import JournalEntry, SeedlingState, LifeRelationship

FRIEND_ID = '621372225'


def citizens():
    with m.SessionLocal() as db:
        me = m.player(db, 'test', 'twitch', 'u', 'Kamex')[1]
        friend = m.player(db, 'test', 'twitch', FRIEND_ID, 'blake1215')[1]
        a, b = m.relationship_pair(me.twitch_uid, friend.twitch_uid)
        db.add(LifeRelationship(channel_id='test', uid_a=a, uid_b=b, familiarity=9))     # one greeting from level 2
        db.commit()


def stored_text():
    with m.SessionLocal() as db:
        texts = [h.title + ' ' + h.detail for h in db.execute(select(StreamHighlight)).scalars()]
        texts += [j.entry for j in db.execute(select(JournalEntry)).scalars()]
        texts += [s.last_progress for s in db.execute(select(SeedlingState)).scalars()]
        return ' | '.join(texts)


def test_a_relationship_level_up_names_the_other_citizen():
    citizens()
    reply = m.hi('test', 'u', 'Kamex', 'blake1215', 'twitch').body.decode()
    shown = reply + ' ' + stored_text()          # the reply, the activity feed / stream highlight, the journal, the status milestone
    assert 'Relationship with blake1215 Lv. 1 → Lv. 2' in shown
    assert FRIEND_ID not in shown


def test_a_hobby_level_up_uses_the_hobby_name():
    with m.SessionLocal() as db:
        p = m.player(db, 'test', 'twitch', 'u', 'Kamex')[1]
        assert readable_names.labels(db, p, ['Hobby gardening', 'Habitat']) == {'Hobby gardening': 'Gardening hobby'}


def test_lines_stored_before_the_fix_are_rewritten_once():
    citizens()
    old = f'LEVEL UP: Relationship {FRIEND_ID} Lv. 1 → Lv. 2'
    gone = 'LEVEL UP: Relationship discord:555555555555 Lv. 2 → Lv. 3'
    now = datetime.now(timezone.utc)
    with m.SessionLocal() as db:
        db.add(StreamHighlight(channel_id='test', kind='level', emoji='⬆️', title='Kamex levelled up',
                               detail=f'Relationship {FRIEND_ID} Lv. 1 → Lv. 2', name='Kamex', created_at=now))
        db.add(JournalEntry(channel_id='test', canonical_uid='u', entry=old))
        db.add(InboxItem(channel_id='test', canonical_uid='u', kind='milestone', important=1, text=gone, created_at=now, seen=0))
        db.add(FeedState(world='test', channel='', enabled=1, message_id='', lines=json.dumps(
            [f'⬆️ Kamex levelled up — Relationship {FRIEND_ID} Lv. 1 → Lv. 2', '⬆️ Kamex levelled up — Hobby gardening Lv. 1 → Lv. 2']),
            last_highlight=0))
        db.commit()
    assert readable_names.repair() == 4
    with m.SessionLocal() as db:
        assert db.execute(select(StreamHighlight).where(StreamHighlight.kind == 'level')).scalar_one().detail == 'Relationship with blake1215 Lv. 1 → Lv. 2'
        assert db.execute(select(JournalEntry).where(JournalEntry.entry.like('LEVEL UP%'))).scalar_one().entry == 'LEVEL UP: Relationship with blake1215 Lv. 1 → Lv. 2'
        assert db.execute(select(InboxItem)).scalar_one().text == 'LEVEL UP: Relationship with a former citizen Lv. 2 → Lv. 3'
        assert json.loads(db.get(FeedState, 'test').lines) == ['⬆️ Kamex levelled up — Relationship with blake1215 Lv. 1 → Lv. 2',
                                                              '⬆️ Kamex levelled up — Gardening hobby Lv. 1 → Lv. 2']
    assert readable_names.repair() == 0                    # nothing left to fix


def test_ordinary_text_is_left_alone():
    names = {FRIEND_ID: 'blake1215'}
    for text in ('Relationship: Friendly (12)', 'Hobby progress 15 (Novice)', '+1 Games hobby', 'Relationship +3'):
        assert readable_names.readable(text, names) == text
