"""Workbench ordering, dropdown limits and single-use Discord buttons."""
from datetime import timedelta
from test_colony import m, reset, client
from app import ui, workbench as wb, seed_content as s, crafting_progression as cp

W = m.DISCORD_WORLD_ID
LUMBER = s.key('Lumber')
CAMPFIRE = next(e for e in wb.index(m) if e.name == 'Campfire' and cp.SURVIVAL in e.tags)


def citizen(uid='111', lumber=10):
    with m.SessionLocal() as db:
        _, p = m.player(db, W, 'discord', uid, 'Kam')
        p.sc = 1000
        life = m.life_state(db, p)
        for k in ('energy', 'nutrition', 'comfort', 'social', 'morale'):
            setattr(life, k, 100)
        m.material_change(db, p, LUMBER, lumber)
        db.commit()
    return uid


def stock(uid='111'):
    with m.SessionLocal() as db:
        _, p = m.player(db, W, 'discord', uid, 'Kam')
        have = s.stock(m, db, p)
        return have.get(LUMBER, 0), have.get(CAMPFIRE.output, 0), p.actions


def press(custom_id, uid='111', values=None):
    payload = {'type': 3, 'data': {'custom_id': custom_id, 'values': values or []},
               'member': {'user': {'id': uid, 'username': 'Kam'}}, 'message': {'flags': 64}}
    return ui.handle_component(m, payload)


def controls(data):
    for component_row in data.get('components', []):
        for component in component_row['components']:
            yield component


def find(data, prefix):
    return next(c for c in controls(data) if c.get('label', '').startswith(prefix))


def test_every_category_lists_recipes_easiest_first():
    entries = wb.index(m)
    assert len({e.id for e in entries}) == len(entries)
    for key, *_ in wb.CATEGORIES:
        rows = wb.in_category(m, key)
        assert rows, key
        assert [e.sort_key for e in rows] == sorted(e.sort_key for e in rows)
        assert [e.tier for e in rows] == sorted(e.tier for e in rows)
    assert {e.category for e in entries} <= set(wb.CATEGORY_INFO)
    # Old category names still open the matching Workbench category.
    assert wb.normalize_category('basic_components') == 'parts'
    assert wb.normalize_category('raw_materials') == 'materials'


def test_dropdown_labels_fit_discord_limits():
    citizen()
    with m.SessionLocal() as db:
        _, p = m.player(db, W, 'discord', '111', 'Kam')
        ctx = wb.Context(m, db, p)
        rows = []
        for key, *_ in [('',)] + list(wb.CATEGORIES):
            rows += wb.autocomplete_rows(ctx, key)
        rows += m.queue_choice_rows(db, p, '') + m.ore_choice_rows(db, p)
        assert all(len(label) <= 100 and len(str(value)) <= 100 for label, value in rows)
        for key, *_ in wb.CATEGORIES:
            for component in controls({'components': ui.category_components(m, ctx, '111', key, 1)}):
                assert len(component['custom_id']) <= 100
                for option in component.get('options', []):
                    assert len(option['label']) <= 100 and len(option.get('description', '')) <= 100
        # A new citizen sees common ores first and locked rare ores marked.
        mines = [(label, value) for label, value in m.queue_choice_rows(db, p, '') if value.startswith('mine:')]
        rare = [value.split(':')[1] in cp.RARE for _, value in mines]
        assert rare == sorted(rare) and any(rare)
        assert all(label.startswith('🔒') for (label, _), r in zip(mines, rare) if r)


def test_navigation_spends_nothing_and_craft_button_works_once():
    citizen()
    before = stock()
    menu = press(ui.cid('111', 'sc'), values=[CAMPFIRE.category])
    assert menu['type'] == 7 and CAMPFIRE.name in menu['data']['embeds'][0]['description']
    preview = press(ui.cid('111', 'wr', CAMPFIRE.id, CAMPFIRE.category, 1, ''))
    assert stock() == before
    text = preview['data']['embeds'][0]['description']
    assert 'Lumber' in text
    craft = find(preview['data'], 'Craft 1 batch')
    assert not craft.get('disabled')
    first = press(craft['custom_id'])
    assert first['type'] == 7
    lumber, fires, _ = stock()
    assert lumber == before[0] - CAMPFIRE.inputs[LUMBER] and fires > before[1]
    again = press(craft['custom_id'])
    assert again['type'] == 4 and 'already used' in again['data']['content']
    assert stock()[:2] == (lumber, fires)


def test_panel_rejects_other_citizens_and_expired_buttons():
    citizen('111'); citizen('222')
    with m.SessionLocal() as db:
        _, p = m.player(db, W, 'discord', '111', 'Kam')
        buttons = {'components': ui.recipe_components(m, wb.Context(m, db, p), '111', CAMPFIRE)}
    craft = find(buttons, 'Craft 1 batch')['custom_id']
    before = stock('111')
    other = press(craft, uid='222')
    assert 'belongs to another citizen' in other['data']['content'] and other['data']['flags'] == 64
    assert stock('111') == before
    with m.SessionLocal() as db:
        for row in db.query(ui.UiTicket):
            row.expires_at = m.now() - timedelta(seconds=1)
        db.commit()
    assert 'expired' in press(craft)['data']['content']
    assert stock('111') == before


def test_queue_plan_shows_totals_before_one_start():
    citizen()
    task = 'gather:' + LUMBER
    plan = press(ui.cid('111', 'qp', task, 5))
    assert 'Energy' in plan['data']['embeds'][0]['description']
    with m.SessionLocal() as db:
        assert db.query(m.task_queue.TaskQueue).count() == 0
    start = find(plan['data'], 'Start queue ×5')['custom_id']
    assert press(start)['type'] == 7
    assert 'already used' in press(start)['data']['content']
    with m.SessionLocal() as db:
        rows = db.query(m.task_queue.TaskQueue).all()
        assert len(rows) == 1 and rows[0].total == 5


def test_make_slash_panel_offers_categories_and_recipe_buttons():
    citizen()
    home = ui.slash_panel(m, 'make', '111', 'Kam', {}, '🛠️ WORKBENCH\nChoose a category.')
    menu = next(controls(home))
    assert [o['value'] for o in menu['options']] == [key for key, *_ in wb.CATEGORIES]
    recipe = ui.slash_panel(m, 'make', '111', 'Kam', {'recipe': CAMPFIRE.id}, 'CAMPFIRE\npreview')
    labels = [c.get('label', '') for c in controls(recipe)]
    assert any(label.startswith('Craft 1 batch') for label in labels) and 'Queue 5' in labels
    ids = [c['custom_id'] for c in controls(recipe)]
    assert len(ids) == len(set(ids)) and all(len(i) <= 100 for i in ids)


def test_message_never_repeats_a_custom_id():
    same = ui.cid('111', 'wh')
    data = ui.message(m, 'TITLE\nbody', [ui.row(ui.button('A', same), ui.button('B', same))])
    ids = [c['custom_id'] for c in controls(data)]
    assert len(ids) == len(set(ids))


def test_twitch_workbench_pages_fit_one_chat_message():
    with m.SessionLocal() as db:
        _, p = m.player(db, 'chan', 'twitch', 't1', 'Kam')
        ctx = wb.Context(m, db, p, 'twitch')
        home = wb.home_text(ctx)
        assert len(home.encode()) <= 380 and all(key in home for key, *_ in wb.CATEGORIES)
        for key, *_ in wb.CATEGORIES:
            page = 1
            while True:
                text = wb.category_text(ctx, key, page)
                assert len(text.encode()) <= 380 and '!make' in text, text
                if 'last page' in text:
                    break
                page += 1
    # '!make parts 2' opens a page; a recipe name crafts.
    assert m.make_text_arguments('parts 2', '', 1) == ('', 'parts', 2)
    assert m.make_text_arguments('Iron Plate', '', 1) == ('Iron Plate', '', 1)


def test_chat_line_folds_card_sections():
    card = '✅ CRAFTING COMPLETE\n\nOUTPUT\n• Campfire ×1\n\nUSED\n2 Lumber'
    assert m.chat_line(card) == '✅ CRAFTING COMPLETE | Output: Campfire ×1 | Used: 2 Lumber'


def test_retired_recipes_keep_history_and_queues():
    citizen()
    with m.SessionLocal() as db:
        _, p = m.player(db, W, 'discord', '111', 'Kam')
        for old in ('ration', 'sensor', 'crate', 'water_filter', 'component'):
            for _ in range(5):
                m.craft_record(db, p, old)
        db.commit()
        # Batches made with retired legacy recipes still count toward personal tiers.
        assert cp.manufactured_batches(m, db, p) == 25
        # An alternate Iron Nails recipe completes the Component catalog entry.
        alternate = next(e.id for e in wb.index(m) if e.name == 'Iron Nails' and e.id != m.item_identity.RETIRED_RECIPES['component'])
        assert m.parts_crafted({alternate}) == m.parts_crafted(set()) + 1
    q = m.task_queue
    flaxa = m.item_identity.RETIRED_GATHERED['biofiber']
    assert 'make:biofiber' not in q.choices(m) and q.normalize(m, 'make:biofiber') == 'gather:' + flaxa
    # A queue saved with a retired recipe continues with its catalog recipe.
    with m.SessionLocal() as db:
        _, p = m.player(db, W, 'discord', '111', 'Kam')
        db.add(q.TaskQueue(channel_id=W, canonical_uid=p.twitch_uid, task='make:component', total=2, remaining=2,
                           state='running', next_at=m.now() - timedelta(seconds=1)))
        db.commit()
        canonical = p.twitch_uid
    q.run_one(m, W, canonical)
    with m.SessionLocal() as db:
        row = db.query(q.TaskQueue).one()
        assert row.task == 'make:' + m.item_identity.RETIRED_RECIPES['component'] and row.state != 'cancelled'


def test_malformed_controls_answer_instead_of_failing():
    citizen()
    for custom in ('ne|111|wc', 'ne|111|wr', 'ne|111|qp|t|abc', 'ne|111|zz'):
        reply = press(custom)
        assert reply['type'] == 4 and 'no longer available' in reply['data']['content']
    assert press('ne|111|sq|mine:x', values=['ten'])['type'] == 4
