"""Force merge: the owner combines two characters from /menu → Moderator, with the same merge as the admin endpoint."""
import json
from pathlib import Path
import pytest
from sqlalchemy import select
from test_colony import m, reset, client
from test_workbench_ui import press as player_press, controls, W, LUMBER
from test_layout_v2 import assert_valid
from app import ui, menu, force_merge as fm, layout_v2 as v2, task_queue as q

OWNER = '111'
MOD = '222'
PLAYER = '333'
KEY = 'test-admin'


@pytest.fixture(autouse=True)
def owners(monkeypatch):
    monkeypatch.setattr(m, 'DISCORD_OWNER_USER_IDS', {OWNER})
    monkeypatch.setattr(m, 'ADMIN_KEY', KEY)
    ui.HISTORY.clear()


def press(custom_id, uid=OWNER, values=None, permissions=str(0x20), message='M1'):
    payload = {'type': 3, 'data': {'custom_id': custom_id, 'values': values or []},
               'member': {'user': {'id': uid, 'username': 'Kam'}, 'permissions': permissions}, 'message': {'flags': 64, 'id': message}}
    return ui.handle_component(payload)


def text_of(answer):
    return json.dumps(answer['data'] if 'data' in answer else answer, ensure_ascii=False)


def labels(answer):
    return [c.get('label') or c.get('placeholder', '') for c in controls(answer['data'])]


def button(answer, prefix):
    return next(c for c in controls(answer['data']) if (c.get('label') or '').startswith(prefix))


def description(answer):
    """The card's title and text as one string (the formatter turns /commands into `code`)."""
    e = answer['data']['embeds'][0]
    return (e.get('title', '') + '\n' + e.get('description', '')).replace('`', '')


def select_values(answer):
    return [o['value'] for c in controls(answer['data']) if c.get('type') == 3 for o in c['options']]


def citizens():
    """The owner's own citizen exists (they use the menu); characters by name -> Player row id."""
    with m.SessionLocal() as db:
        m.player(db, W, 'discord', OWNER, 'Kam')
        db.commit()


def make_pair(tw='tw-555', dc='9001', names=('Deschroyer', 'deschroyer'), queue=True):
    """A Twitch character and a Discord character that were never linked, with different stats, items, life and a queue."""
    with m.SessionLocal() as db:
        a = m.player(db, W, 'twitch', tw, names[0])[1]
        a.sc, a.contribution, a.actions, a.mining_xp = 300, 40, 25, 70
        m.material_change(db, a, LUMBER, 12)
        la = m.life_state(db, a)
        la.energy, la.gardening = 60, 4
        b = m.player(db, W, 'discord', dc, names[1])[1]
        b.sc, b.contribution, b.actions, b.mining_xp = 120, 15, 9, 30
        m.material_change(db, b, LUMBER, 5)
        lb = m.life_state(db, b)
        lb.energy, lb.gardening = 90, 3
        for p in (a, b):
            for k in ('nutrition', 'comfort', 'social', 'morale'):
                setattr(m.life_state(db, p), k, 100)
        db.commit()
        ids = (a.id, b.id)
    if queue:
        m.queued_tasks(W, dc, names[1], 'start', 'gather:' + LUMBER, '4', 'discord')
    return ids


def snapshot(keep_uid, gone_uid):
    """Everything the merge decides, with names and ids left out so two scenarios can be compared."""
    with m.SessionLocal() as db:
        p = db.query(m.Player).filter_by(channel_id=W, twitch_uid=keep_uid).one()
        stock = dict(m.item_identity.stock(db, p))
        life = m.life_state(db, p)
        row = db.get(q.TaskQueue, (W, keep_uid))
        links = db.query(m.AccountLink).filter_by(channel_id=W, twitch_uid=keep_uid).all()
        return {
            'sc': p.sc, 'contribution': p.contribution, 'actions': p.actions, 'mining_xp': p.mining_xp, 'stock': stock,
            'energy': life.energy, 'gardening': life.gardening,
            'queue': (row.task, row.state, row.total, row.remaining) if row else None,
            'links': len(links), 'providers': sorted(i.provider for i in db.query(m.Identity).filter_by(channel_id=W, canonical_uid=keep_uid)),
            'gone': db.query(m.Player).filter_by(channel_id=W, twitch_uid=gone_uid).count(),
            'players': db.query(m.Player).filter_by(channel_id=W).count(), 'population': m.society(db, W).population,
            'audits': [(a.action) for a in db.query(m.ModeratorAudit).all()],
        }


def database_state():
    """Every character and every table the merge touches, as plain data (the citizens using the menu are left out: pressing a button creates yours)."""
    with m.SessionLocal() as db:
        out = {}
        for model in (m.Player, m.Identity, m.AccountLink, m.ModeratorAudit, m.LifeState, q.TaskQueue, m.ExtraItem):
            rows = (json.dumps({c.name: str(getattr(r, c.name)) for c in model.__table__.columns}, sort_keys=True) for r in db.query(model).all())
            out[model.__tablename__] = sorted(r for r in rows if not any(f'discord:{u}' in r or f'"provider_uid": "{u}"' in r for u in (OWNER, MOD, PLAYER)))
        return out


def preview_of(keep_id, gone_id):
    return press(ui.cid(OWNER, 'xm', keep_id, gone_id))


def confirm_of(answer):
    return button(answer, 'Confirm merge')['custom_id']


# ---------------------------------------------------------------- who can see and use it

def test_owner_sees_and_uses_the_button():
    citizens()
    mod_area = press(ui.cid(OWNER, 'mn', 'mod'))
    assert 'Force merge' in labels(mod_area) and 'Force merge' in description(mod_area)
    first = press(button(mod_area, 'Force merge')['custom_id'])
    assert first['type'] == 7 and 'step 1 of 3' in description(first) and 'Choose a character…' in labels(first)
    assert select_values(first) and 'Back' in labels(first) and 'Menu' in labels(first)


def test_a_moderator_who_is_not_an_owner_and_a_player_cannot():
    citizens()
    a, b = make_pair()
    before = database_state()
    area = press(ui.cid(MOD, 'mn', 'mod'), uid=MOD)
    assert 'Force merge' not in labels(area) and 'Force merge' not in description(area)       # hidden, and it is not listed
    assert 'Account lookup' in labels(area)                                                   # the rest of the area still works
    forged = [ui.cid(MOD, 'xk'), ui.cid(MOD, 'xm', a), ui.cid(MOD, 'xm', a, b), ui.cid(MOD, 'mv', 'm_force'), ui.cid(MOD, 'mk', 'm_force'),
              ui.cid(MOD, 'mp', 'm_force')]
    for uid, permissions in ((MOD, str(0x20)), (PLAYER, '0')):
        for custom_id in forged:
            answer = press(custom_id.replace(f'|{MOD}|', f'|{uid}|'), uid=uid, permissions=permissions, values=[str(b)])
            assert 'Owner access is required for Force merge. Nothing changed.' in text_of(answer), custom_id
            assert not [c for c in controls(answer['data']) if c.get('style') == 4 or (c.get('label') or '').startswith(('Confirm', 'Swap'))]
    assert not [c for c in controls(press(ui.cid(PLAYER, 'mn', 'mod'), uid=PLAYER, permissions='0')['data']) if c.get('label') == 'Force merge']
    assert database_state() == before


def test_a_ticket_is_refused_for_someone_else_and_for_an_owner_who_is_no_longer_one(monkeypatch):
    citizens()
    a, b = make_pair()
    ticket = confirm_of(preview_of(a, b))
    before = database_state()
    assert 'belongs to another citizen' in text_of(press(ticket.replace(f'|{OWNER}|', f'|{MOD}|'), uid=MOD))     # forged owner id in the custom_id
    stolen = press(ticket, uid=MOD)
    assert 'belongs to another citizen' in text_of(stolen)
    with m.SessionLocal() as db:                                           # a non-owner who somehow holds a ticket of their own
        row = db.query(ui.UiTicket).filter_by(owner=OWNER, used_at=None).first()
        mine = ui.issue(MOD, json.loads(row.action))
    refused = press(ui.cid(MOD, 't', mine), uid=MOD)
    assert 'Owner access is required for Force merge. Nothing changed.' in text_of(refused)
    monkeypatch.setattr(m, 'DISCORD_OWNER_USER_IDS', set())               # the owner list changed after the preview
    stale = press(ticket)
    assert 'Owner access is required for Force merge. Nothing changed.' in text_of(stale)
    assert database_state() == before


# ---------------------------------------------------------------- choosing the two characters

def test_the_second_list_leaves_out_the_first_pick():
    citizens()
    a, b = make_pair()
    first = press(ui.cid(OWNER, 'xk'))
    assert str(a) in select_values(first) and str(b) in select_values(first)
    second = press(ui.cid(OWNER, 'xk'), values=[str(a)])
    assert 'step 2 of 3' in description(second) and 'Keeping **Deschroyer**' in description(second) and 'Twitch tw-555' in description(second)
    assert str(a) not in select_values(second) and str(b) in select_values(second)
    assert len(select_values(second)) == len(select_values(first)) - 1
    assert [c for c in controls(second['data']) if c.get('type') == 3][0]['custom_id'] == ui.cid(OWNER, 'xm', a)
    option = next(o for c in controls(second['data']) if c.get('type') == 3 for o in c['options'] if o['value'] == str(b))
    assert option['label'] == 'deschroyer · #%d' % b and option['description'] == 'Discord · 120 SC · 9 actions'
    assert preview_of(a, b)['type'] == 7 and 'Confirm merge' in labels(press(ui.cid(OWNER, 'xm', a), values=[str(b)]))


def test_long_lists_page_and_keep_every_option_valid():
    citizens()
    with m.SessionLocal() as db:
        for i in range(30):
            m.player(db, W, 'discord', f'7{i:03d}', f'Citizen {i:02d}')
        db.commit()
    page1 = press(ui.cid(OWNER, 'xk'))
    options = [o for c in controls(page1['data']) if c.get('type') == 3 for o in c['options']]
    assert len(options) == 24 and options[-1]['value'] == '__page:2' and 'Page 1 of 2' in description(page1)
    page2 = press(ui.cid(OWNER, 'xk'), values=['__page:2'])
    options2 = [o['value'] for c in controls(page2['data']) if c.get('type') == 3 for o in c['options']]
    assert options2[0] == '__page:1' and 'Page 2 of 2' in description(page2) and not set(options2) & {o['value'] for o in options}
    keep = int(options[0]['value'])
    second = press(ui.cid(OWNER, 'xk'), values=[str(keep)])
    assert str(keep) not in select_values(second) and 'Page 1 of 2' in description(second)
    again = press(ui.cid(OWNER, 'xm', keep), values=['__page:2'])
    assert 'Page 2 of 2' in description(again) and assert_valid(v2.convert(again['data']))


def test_the_same_character_twice_is_refused_and_so_is_a_missing_one():
    citizens()
    a, b = make_pair()
    before = database_state()
    for answer in (press(ui.cid(OWNER, 'xm', a, a)), press(ui.cid(OWNER, 'xm', a), values=[str(a)])):
        assert 'are already the same character, so there is nothing to merge. Nothing changed.' in text_of(answer)
        assert not [c for c in controls(answer['data']) if (c.get('label') or '').startswith('Confirm')]
    assert 'That character no longer exists. Choose again. Nothing changed.' in text_of(press(ui.cid(OWNER, 'xm', a, 99999)))
    assert 'That character no longer exists. Choose again. Nothing changed.' in text_of(press(ui.cid(OWNER, 'xm', 99999, a)))
    assert 'That character no longer exists' in text_of(press(ui.cid(OWNER, 'xk'), values=['abc']))
    assert database_state() == before
    # The database cannot hold two rows with one canonical id, so "already the same character" is the same row picked twice, above;
    # the shared core refuses it for the endpoint too.
    with m.SessionLocal() as db, pytest.raises(fm.Refused) as same:
        fm.load(db, W, 'x', 'x')
    assert same.value.status == 400 and same.value.error == 'keep and merge are the same character.'


# ---------------------------------------------------------------- the preview

def test_the_preview_shows_both_characters_and_the_total_and_changes_nothing():
    citizens()
    a, b = make_pair()
    before = database_state()
    answer = preview_of(a, b)
    text = description(answer)
    assert 'Force Merge — Preview' in text and 'This cannot be undone' in text and 'Nothing changes until you press Confirm merge' in text
    assert '**KEEP** — Deschroyer' in text and '**MERGE INTO IT** — deschroyer' in text and '**AFTER THE MERGE** — Deschroyer survives' in text
    assert 'Twitch tw-555' in text and 'Discord 9001' in text
    assert '300 SC · 70 XP · 25 actions · 40 contribution' in text and '120 SC · 30 XP · 9 actions · 15 contribution' in text
    assert '420 SC · 100 XP · 34 actions · 55 contribution' in text
    assert '12 items (1 kind)' in text and '5 items (1 kind)' in text and '17 items (1 kind)' in text
    assert 'queue: none' in text and "deschroyer's running queue moves to Deschroyer" in text and 'Gather Lumber · running' in text
    assert 'Twitch tw-555 and Discord 9001 will all point at Deschroyer. A Twitch + Discord pair becomes a permanent link.' in text
    assert labels(answer) == ['Confirm merge', 'Swap', 'Back', 'Menu']
    assert button(answer, 'Confirm merge')['style'] == 4
    assert database_state() == before                                # the preview wrote nothing (one-time tickets are not game data)


def test_the_preview_says_what_happens_when_both_have_a_running_queue():
    citizens()
    a, b = make_pair()
    m.queued_tasks(W, 'tw-555', 'Deschroyer', 'start', 'gather:' + LUMBER, '3', 'twitch')
    text = description(preview_of(a, b))
    assert "both are running: Deschroyer's continues, deschroyer's remaining attempts are cancelled (finished work is kept)" in text


def test_swap_keeps_the_other_character():
    citizens()
    a, b = make_pair()
    answer = preview_of(a, b)
    swapped = press(button(answer, 'Swap')['custom_id'])
    text = description(swapped)
    assert '**KEEP** — deschroyer' in text and '**MERGE INTO IT** — Deschroyer' in text and '**AFTER THE MERGE** — deschroyer survives' in text
    assert 'Deschroyer is deleted and **deschroyer** survives' not in text and '**Deschroyer** is deleted and **deschroyer** survives' in text
    assert button(swapped, 'Swap')['custom_id'] == ui.cid(OWNER, 'xm', a, b)             # swapping back
    done = press(confirm_of(swapped))
    assert 'Merged **Deschroyer** into **deschroyer**' in description(done)
    with m.SessionLocal() as db:
        assert [p.twitch_uid for p in db.query(m.Player).filter(m.Player.id.in_((a, b)))] == ['discord:9001']


# ---------------------------------------------------------------- confirming

def test_confirm_gives_the_same_result_as_the_admin_endpoint():
    citizens()
    make_pair('tw-A', '9001', ('Alpha', 'alpha'))                       # merged by the endpoint
    a2, b2 = make_pair('tw-B', '9002', ('Beta', 'beta'))                # merged by the button
    done = client.get('/api/v1/admin/merge', params={'channel': W, 'key': KEY, 'keep': 'tw-A', 'merge': 'discord:9001', 'confirm': 1}).json()
    assert done['merged'] and done['character']['sc'] == 420
    audit_endpoint = [(a.moderator, a.detail) for a in m.SessionLocal().query(m.ModeratorAudit)]
    expected = snapshot('tw-A', 'discord:9001')
    answer = press(confirm_of(preview_of(a2, b2)))
    assert answer['type'] == 7
    result = description(answer)
    assert 'Force Merge — Done' in result and 'Merged **beta** into **Beta**' in result and '**Beta** now has' in result
    assert '420 SC · 100 XP · 34 actions · 55 contribution' in result and '17 items (1 kind)' in result and 'Gather Lumber · running' in result
    assert 'Discord 9002 · Twitch tw-B all point at Beta' in result and 'permanently linked' in result
    assert 'Logged in the moderator log as owner 111 via /menu' in result
    got = snapshot('tw-B', 'discord:9002')
    assert got == dict(expected, audits=got['audits'], players=got['players'], population=got['population'])
    assert got['sc'] == 420 and got['stock'] == {LUMBER: 17} and got['gardening'] == 7 and got['energy'] == 90
    assert got['queue'][:2] == (f'gather:{LUMBER}', 'running') and got['links'] == 1 and got['providers'] == ['discord', 'twitch'] and got['gone'] == 0
    assert got['audits'] == ['merge', 'merge']
    with m.SessionLocal() as db:
        audits = [(a.moderator, a.detail) for a in db.query(m.ModeratorAudit).order_by(m.ModeratorAudit.id)]
        assert audits[0] == audit_endpoint[0] == ('game admin', 'alpha (discord:9001) into Alpha (tw-A)')
        assert audits[1] == ('owner 111 via /menu', 'beta (discord:9002) into Beta (tw-B)')
        assert db.query(m.AccountLink).filter_by(channel_id=W, twitch_uid='tw-B', discord_uid='9002').one()
        assert m.player(db, W, 'discord', '9002', 'beta')[1].twitch_uid == 'tw-B'                  # later commands reach the one character
        assert m.player(db, W, 'twitch', 'tw-B', 'Beta')[1].twitch_uid == 'tw-B'
    assert labels(answer)[:2] == ['Moderator', 'Merge another'] and labels(answer)[-2:] == ['Back', 'Menu']


def test_back_after_a_merge_goes_up_to_moderator_not_to_the_stale_preview():
    citizens()
    a, b = make_pair()
    press(ui.cid(OWNER, 'mn', 'mod'))
    press(ui.cid(OWNER, 'xk'))
    press(ui.cid(OWNER, 'xk'), values=[str(a)])
    shown = press(ui.cid(OWNER, 'xm', a), values=[str(b)])
    done = press(confirm_of(shown))
    went = press(button(done, 'Back')['custom_id'])
    assert 'Moderator' in description(went) and 'Force merge' in labels(went)


def test_the_ticket_works_once():
    citizens()
    a, b = make_pair()
    ticket = confirm_of(preview_of(a, b))
    assert 'Force Merge — Done' in description(press(ticket))
    after = snapshot('tw-555', 'discord:9001')
    again = press(ticket)
    assert 'already used, so nothing was repeated' in text_of(again)
    assert snapshot('tw-555', 'discord:9001') == after and after['audits'] == ['merge']


def test_confirm_refuses_when_a_character_vanished_or_changed_after_the_preview():
    citizens()
    a, b = make_pair()
    ticket = confirm_of(preview_of(a, b))
    with m.SessionLocal() as db:                                        # someone linked the Discord character in the meantime
        m.merge_accounts(db, W, 'discord:9001', 'tw-555')
    before = database_state()
    gone = press(ticket)
    assert 'One of the two characters no longer exists (it may already have been merged). Nothing changed.' in description(gone)
    assert database_state() == before
    a2, b2 = make_pair('tw-C', '9003', ('Gamma', 'gamma'), queue=False)
    ticket = confirm_of(preview_of(a2, b2))
    with m.SessionLocal() as db:
        db.get(m.Player, b2).twitch_uid = 'discord:renamed'
        db.commit()
    before = database_state()
    changed = press(ticket)
    assert 'changed since the preview' in description(changed) and 'Nothing changed.' in description(changed)
    assert database_state() == before


def test_a_failure_in_the_middle_of_the_merge_changes_nothing(monkeypatch):
    citizens()
    a, b = make_pair()
    ticket = confirm_of(preview_of(a, b))
    before = database_state()
    real = m.merge_accounts

    def explode(db, channel, source, target):
        real(db, channel, source, target)                                # the merge really ran, then something broke
        raise RuntimeError('boom')
    monkeypatch.setattr(m, 'merge_accounts', explode)
    with pytest.raises(RuntimeError):
        press(ticket)
    assert database_state() == before                                    # rolled back: both characters, items, queue, links, audit
    sent = []                                                            # and through the deferred path the owner is told so
    monkeypatch.setattr(m.discord_deferred, 'edit_original', lambda app, token, data: sent.append(data) or True)
    monkeypatch.setattr(m.inbox, 'deliver', lambda *a, **k: False)
    ticket2 = confirm_of(preview_of(a, b))
    payload = {'application_id': 'app', 'token': 't', 'channel_id': '5', 'member': {'user': {'id': OWNER, 'username': 'Kam'}, 'permissions': str(0x20)}}
    action = json.loads(m.SessionLocal().query(ui.UiTicket).filter_by(id=ticket2.split('|')[-1]).one().action)
    ui.finish_ticket(payload, OWNER, 'Kam', action)
    assert 'nothing was spent' in json.dumps(sent[-1]) and database_state() == before


def test_the_admin_endpoint_answers_exactly_as_before():
    citizens()
    a, b = make_pair(queue=False)
    params = {'channel': W, 'key': KEY, 'keep': 'tw-555', 'merge': 'discord:9001'}
    assert client.get('/api/v1/admin/merge', params=dict(params, key='x')).status_code == 403
    same = client.get('/api/v1/admin/merge', params=dict(params, merge='tw-555'))
    assert same.status_code == 400 and same.json() == {'ok': False, 'error': 'keep and merge are the same character.'}
    missing = client.get('/api/v1/admin/merge', params=dict(params, merge='nobody'))
    assert missing.status_code == 404 and missing.json()['error'].startswith('Both characters must exist in this channel')
    preview = client.get('/api/v1/admin/merge', params=params).json()
    assert list(preview) == ['ok', 'preview', 'keep', 'merge', 'after', 'apply'] and preview['after'] == {
        'sc': 420, 'contribution': 55, 'actions': 34, 'xp': 100, 'uid': 'tw-555', 'name': 'Deschroyer'}
    done = client.get('/api/v1/admin/merge', params=dict(params, confirm=1)).json()
    assert list(done) == ['ok', 'merged', 'character', 'expected'] and done['expected']['sc'] == 420 and done['character']['uid'] == 'tw-555'
    with m.SessionLocal() as db:
        assert [x.moderator for x in db.query(m.ModeratorAudit)] == ['game admin']


# ---------------------------------------------------------------- Discord layout rules

def test_every_screen_has_back_and_menu_and_fits_discords_limits():
    citizens()
    a, b = make_pair()
    answers = [press(ui.cid(OWNER, 'mn', 'mod')), press(ui.cid(OWNER, 'xk')), press(ui.cid(OWNER, 'xk'), values=[str(a)]), preview_of(a, b),
               press(ui.cid(OWNER, 'xm', b, a)), press(ui.cid(OWNER, 'xm', a, a)), press(ui.cid(OWNER, 'xm', a, 99999)),
               press(ui.cid(MOD, 'xk'), uid=MOD), press(confirm_of(preview_of(a, b)))]
    for answer in answers:
        rows = [r for r in answer['data']['components'] if r.get('components')]
        assert len(rows) <= 5 and all(len(r['components']) <= 5 for r in rows)
        ids = [c['custom_id'] for r in rows for c in r['components']]
        assert len(ids) == len(set(ids)) and all(len(i) <= 100 for i in ids)
        assert [c['label'] for c in rows[-1]['components'][-2:]] == ['Back', 'Menu'], text_of(answer)[:200]
        assert sum(i.split('|')[2] == 'bk' for i in ids) == 1
        assert assert_valid(v2.convert(answer['data']))
        assert answer['data']['embeds'][0]['author']['name'].startswith('🏠 Menu › 🛡️ Moderator')


def test_the_slash_command_choices_are_untouched():
    contract = json.loads((Path(__file__).parent / 'contracts' / 'discord_options.json').read_text())
    assert 'forcemerge' not in json.dumps(contract) and 'force' not in json.dumps(contract).lower()
    assert 'm_force' in menu.LEAVES and menu.LEAVES['m_force']['kind'] == 'nav' and menu.LEAVES['m_force']['cmd'] == ''


# ---------------------------------------------------------------- forged numbers

HUGE = '99999999999999999999'


def refused_cleanly(answer):
    assert 'That character no longer exists. Choose again. Nothing changed.' in description(answer) or 'One of the two characters no longer exists' in description(answer)
    rows = [r for r in answer['data']['components'] if r.get('components')]
    assert [c['label'] for c in rows[-1]['components'][-2:]] == ['Back', 'Menu']
    assert not [c for c in controls(answer['data']) if (c.get('label') or '').startswith('Confirm')]
    assert assert_valid(v2.convert(answer['data']))


def test_forged_huge_or_odd_ids_are_refused_before_any_query():
    citizens()
    a, b = make_pair()
    before = database_state()
    for answer in (press(ui.cid(OWNER, 'xm', HUGE, a)), press(ui.cid(OWNER, 'xm', a, HUGE)), press(ui.cid(OWNER, 'xk'), values=[HUGE]),
                   press(ui.cid(OWNER, 'xm', a), values=[HUGE]), press(ui.cid(OWNER, 'xm', HUGE), values=[str(b)]),
                   press(ui.cid(OWNER, 'xm', '2147483648', a)), press(ui.cid(OWNER, 'xm', '²', a)), press(ui.cid(OWNER, 'xm', '0', '-1')),
                   press(ui.cid(OWNER, 'xm', 'abc', 'def')), press(ui.cid(OWNER, 'xk'), values=[''])):
        refused_cleanly(answer)
    # A huge or odd page number just shows a page of the list.
    for values in ([f'__page:{HUGE}'], ['__page:abc'], ['__page:-3'], ['__page:']):
        assert 'step 1 of 3' in description(press(ui.cid(OWNER, 'xk'), values=values))
        assert 'step 2 of 3' in description(press(ui.cid(OWNER, 'xm', a), values=values))
    assert database_state() == before


def test_a_ticket_with_a_huge_id_refuses_and_changes_nothing():
    citizens()
    a, b = make_pair()
    before = database_state()
    for action in ({'keep': int(HUGE), 'merge': b, 'keep_uid': 'tw-555', 'merge_uid': 'discord:9001'},
                   {'keep': a, 'merge': HUGE, 'keep_uid': 'tw-555', 'merge_uid': 'discord:9001'},
                   {'keep': None, 'merge': b}, {}):
        ticket = ui.issue(OWNER, dict(action, do='forcemerge'))
        answer = press(ui.cid(OWNER, 't', ticket))
        assert 'One of the two characters no longer exists' in description(answer) and 'Nothing changed.' in description(answer)
        assert [c['label'] for c in answer['data']['components'][-1]['components'][-2:]] == ['Back', 'Menu']
    assert database_state() == before
