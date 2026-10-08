"""The channel activity feed, the Share button and the feed privacy setting."""
from datetime import timedelta
import pytest
from test_colony import m, reset, client
from app import activity_feed as af, community, ui, stream_overlay as so, layout_v2

W = m.DISCORD_WORLD_ID
CHANNEL = '123456789012345678'


class Reply:
    def __init__(self, code, data=None):
        self.status_code, self._data = code, data or {}

    def json(self):
        return self._data


@pytest.fixture
def discord(reset, monkeypatch):
    monkeypatch.setattr(community, 'ENABLED', True)
    monkeypatch.setenv('DISCORD_BOT_TOKEN', 'token')
    monkeypatch.setattr(m, 'DISCORD_GAME_CHANNEL_ID', CHANNEL)
    calls, last = [], {'id': ''}

    def fake(method, url, **kw):
        calls.append((method, url.split('/api/v10')[1], kw.get('json')))
        if method == 'GET':
            return Reply(200, {'last_message_id': last['id']})
        if method == 'POST':
            last['id'] = str(900 + len(calls))
            return Reply(200, {'id': last['id']})
        return Reply(200)
    monkeypatch.setattr('requests.request', fake)
    return calls, last


def gather(uid, name, item='lumber', times=1):
    for _ in range(times):
        with m.SessionLocal() as db:
            db.query(m.Cooldown).delete(); db.commit()
        client.get('/api/v1/seed-supplies', params={'channel': W, 'uid': uid, 'name': name, 'mode': 'gather', 'item': item})


def test_the_feed_posts_what_players_bring_in_then_extends_the_same_message(discord):
    calls, last = discord
    for uid, name in [('a', 'Ann'), ('b', 'Bo')]:
        client.get('/api/v1/start', params={'channel': W, 'uid': uid, 'name': name})
    with m.SessionLocal() as db:
        af.state(db); db.commit()                    # the feed starts from now, not from old history
    gather('a', 'Ann', times=3); gather('b', 'Bo', times=2)
    assert af.tick(force=True)
    method, path, body = calls[-1]
    assert (method, path) == ('POST', f'/channels/{CHANNEL}/messages')
    text = layout_v2.text_of(body)
    assert layout_v2.is_v2(body)                                         # one card in the newer layout
    assert '**Ann** gathered 3 Lumber' in text and '**Bo** gathered 2 Lumber' in text and '<t:' in text
    assert body['allowed_mentions'] == {'parse': []}
    assert [c['custom_id'] for c in layout_v2.controls(body)][0] == ui.cid(ui.PUBLIC, 'mn', 'home')
    # Nobody else talked: the same message grows.
    gather('a', 'Ann', item='stone')
    with m.SessionLocal() as db:
        so.highlight(db, W, 'trophy', 'Ann earned 💎 Ore Hunter', 'Find every ore', 'Ann', emoji='💎'); db.commit()
    assert af.tick(force=True)
    assert [c[0] for c in calls[-2:]] == ['GET', 'PATCH']
    text = layout_v2.text_of(calls[-1][2])
    assert 'Ore Hunter' in text and '**Ann** gathered 3 Lumber' in text and 'Stone' in text
    # Someone posted in between: a new message starts below.
    last['id'] = 'someone-else'
    gather('b', 'Bo')
    assert af.tick(force=True)
    assert [c[0] for c in calls[-2:]] == ['GET', 'POST'] and 'Lumber' in layout_v2.text_of(calls[-1][2])


def test_a_feed_message_from_before_a_restart_is_not_edited(discord, monkeypatch):
    """It may be in the other layout (embeds or the newer one), and Discord cannot switch a message between them."""
    calls, last = discord
    client.get('/api/v1/start', params={'channel': W, 'uid': 'a', 'name': 'Ann'})
    with m.SessionLocal() as db:
        af.state(db); db.commit()
    gather('a', 'Ann')
    assert af.tick(force=True) and calls[-1][0] == 'POST'
    monkeypatch.setattr(af, 'STARTED', af._now() + timedelta(minutes=1))     # the app restarted after that post
    gather('a', 'Ann', item='stone')
    assert af.tick(force=True)
    assert calls[-1][0] == 'POST' and 'PATCH' not in [c[0] for c in calls]


def test_updates_wait_their_turn_but_big_moments_go_out_at_once(discord):
    calls, _ = discord
    client.get('/api/v1/start', params={'channel': W, 'uid': 'a', 'name': 'Ann'})
    with m.SessionLocal() as db:
        af.state(db); db.commit()
    gather('a', 'Ann')
    assert af.tick(force=True)
    sent = len(calls)
    gather('a', 'Ann')
    assert af.tick() is None and len(calls) == sent          # not due yet
    with m.SessionLocal() as db:
        so.highlight(db, W, 'challenge_start', 'Dust Storm! Everyone repair the walls', 'Goal 20 in 8 minutes.', emoji='🌪️'); db.commit()
    assert af.tick()
    assert 'Dust Storm' in layout_v2.text_of(calls[-1][2])


def test_seedlings_are_summed_up_and_hidden_players_stay_out(discord):
    calls, _ = discord
    for uid, name in [('a', 'Ann'), ('b', 'Bo')]:
        client.get('/api/v1/start', params={'channel': W, 'uid': uid, 'name': name})
    with m.SessionLocal() as db:
        af.state(db); db.commit()
    assert 'hidden from the channel feed' in client.get('/api/v1/settings', params={'channel': W, 'uid': 'b', 'name': 'Bo', 'feed': 'off'}).text
    token = m.autonomy.ACTING.set(True)
    try:
        gather('a', 'Ann', times=2)
    finally:
        m.autonomy.ACTING.reset(token)
    gather('b', 'Bo', times=2)
    with m.SessionLocal() as db:
        so.highlight(db, W, 'level', 'Bo levelled up', 'Harvesting Lv. 1 → Lv. 2', 'Bo'); db.commit()
    assert af.tick(force=True)
    text = layout_v2.text_of(calls[-1][2])
    assert '1 Seedling worked on their own and brought in 2 items (Ann)' in text and 'Bo' not in text


def test_no_channel_means_nothing_is_recorded_or_sent(reset, monkeypatch):
    monkeypatch.setattr(community, 'ENABLED', True)
    monkeypatch.setattr(m, 'DISCORD_GAME_CHANNEL_ID', '')
    monkeypatch.delenv('DISCORD_FEED_CHANNEL_ID', raising=False)
    client.get('/api/v1/start', params={'channel': W, 'uid': 'a', 'name': 'Ann'})
    gather('a', 'Ann')
    with m.SessionLocal() as db:
        assert db.query(af.FeedEvent).count() == 0
    assert af.tick(force=True) is None


def test_moderators_move_the_feed_and_switch_it_off(discord):
    token = m.task_queue.queue_notifications.origin_channel.set('555555555555555555')
    try:
        assert 'now posts in this channel' in m._discord_call_internal('mod', '111', 'Mod', {'action': 'feedhere'}, 'i1')
    finally:
        m.task_queue.queue_notifications.origin_channel.reset(token)
    with m.SessionLocal() as db:
        assert af.channel_of(db) == '555555555555555555'
    assert 'feed is off' in m._discord_call_internal('mod', '111', 'Mod', {'action': 'feedoff'}, 'i2')
    with m.SessionLocal() as db:
        assert af.channel_of(db) == ''


def test_share_posts_a_private_card_for_everyone(reset):
    with m.SessionLocal() as db:
        m.player(db, W, 'discord', '111', 'Kamex'); db.commit()
    member = {'member': {'user': {'id': '111', 'username': 'Kamex'}}}
    card = ui.handle_component({'data': {'custom_id': ui.cid('111', 'mv', 'me_overview')}, **member})
    assert card['data']['flags'] == 64                                      # the card itself is private
    ids = [c['custom_id'] for r in card['data']['components'] for c in r['components']]
    share = next(i for i in ids if '|sh|' in i)
    shared = ui.handle_component({'data': {'custom_id': share}, **member})
    assert shared['type'] == 4 and 'flags' not in shared['data']           # the shared copy is public
    assert shared['data']['embeds'][0]['author']['name'] == '📣 Kamex shared their profile'
    other = ui.handle_component({'data': {'custom_id': share}, 'member': {'user': {'id': '222', 'username': 'Bo'}}})
    assert other['data']['flags'] == 64 and 'belongs to another citizen' in other['data']['content']
    assert ui.share_button('111', 'me', {'section': 'life'}) is None       # needs and other private views are not shareable
