"""The Workbench: every craftable recipe in one place, grouped and ranked.

/make opens the Workbench. Recipes are grouped into categories and listed from
the easiest to the most demanding: the personal tier the whole chain needs,
then the skill level, then how many crafting steps separate it from raw
materials. Catalog (SEED) recipes and the New Eridian equipment that has no
catalog twin share the same list, labels and status rules.

Everything here is read-only. Crafting still runs through the existing game
functions, so stations, tiers, skills, needs, cooldowns and rewards are the
same whether a player uses a slash option, a Workbench button, Twitch or a queue.
"""
import math
from dataclasses import dataclass, field
from . import seed_content as s, crafting_progression as cp, production_balance

# Categories are shared with /catalog and /use (defined with the catalog).
CATEGORIES = s.DISPLAY_CATEGORIES
CATEGORY_INFO = s.DISPLAY_INFO
SEED_TO_WORKBENCH = s.SEED_TO_DISPLAY
CATEGORY_ALIASES = s.DISPLAY_ALIASES
# Personal views listed before the categories: what you can craft right now,
# and the recipes you starred. They are filters over the same recipe index.
VIEWS = (
    ('ready', '✅', 'Ready now', 'Every recipe you can craft right now, favourites first.'),
    ('favorites', '⭐', 'Favourites', 'Your starred recipes (up to 10), in the order you added them.'),
)
VIEW_INFO = {**CATEGORY_INFO, **{key: (emoji, label, text) for key, emoji, label, text in VIEWS}}
VIEW_ALIASES = {'ready': 'ready', 'ready_now': 'ready', 'craftable': 'ready', 'can_craft': 'ready',
                'favorites': 'favorites', 'favourites': 'favorites', 'favs': 'favorites', 'fav': 'favorites',
                'favorite': 'favorites', 'favourite': 'favorites', 'starred': 'favorites', 'stars': 'favorites'}


def normalize_category(value):
    """Category or personal view key, '' for the overview, or None when unknown."""
    key = str(value or '').strip().casefold().replace('-', '_').replace(' ', '_').strip('✅⭐_')
    if key in VIEW_ALIASES:
        return VIEW_ALIASES[key]
    return s.display_category(value)
PAGE_SIZE = 10
CHAT_PAGE_SIZE = 8   # Twitch pages must fit one 380-byte chat message
STATUS_ORDER = {'ready': 0, 'missing': 1, 'station': 2, 'owned': 3, 'locked': 4}


@dataclass(frozen=True)
class Entry:
    id: str
    kind: str            # 'seed' catalog recipe or 'legacy' New Eridian equipment
    name: str
    output: str
    quantity: int
    category: str
    tags: tuple
    tier: int            # personal tier the whole chain needs
    steps: int           # crafting steps from raw materials
    level: int
    skill: str
    skill_key: str
    inputs: dict = field(hash=False, compare=False)

    @property
    def sort_key(self):
        return (self.tier, self.level, self.steps, len(self.inputs), self.name.casefold(), self.id)


_INDEX = None
_BY_ID = None


def _legacy_entries(m):
    rows = []
    for key, cost in m.RECIPES.items():
        rows.append((key, m.resource_name(key), cost, 'equipment'))
    for key, data in m.QUALITY_RECIPES.items():
        rows.append((key, data['name'], data['cost'], 'food' if key == 'meal_kit' else 'equipment'))
    for key, name, cost, category in rows:
        tag = cp.legacy_station(m, key)
        tier = max([cp.STATIONS[tag]['tier']] + [s.ITEM_TIER.get(k, 1) for k in cost])
        steps = 1 + max([s.ITEM_STEPS.get(k, 0) for k in cost], default=0)
        yield Entry(key, 'legacy', name, key, 1, category, (tag,), tier, steps, 1, 'Crafting', '', dict(cost))


def index(m):
    """Every recipe once, easiest first within each category."""
    global _INDEX, _BY_ID
    if _INDEX is None:
        entries = []
        for rid, recipe in s.RECIPES.items():
            output = next(iter(recipe['outputs']))
            tier, steps, level = s.recipe_progress(rid)
            skill_key = recipe['requirement'].get('Skill', 'SK_CRAFTING')
            entries.append(Entry(rid, 'seed', s.item_label(output), output, recipe['outputs'][output],
                                 SEED_TO_WORKBENCH[s.recipe_category(rid)], tuple(cp.tags(rid)), tier, steps,
                                 level, s.skill_name(skill_key), skill_key, dict(recipe['inputs'])))
        entries.extend(_legacy_entries(m))
        _INDEX = sorted(entries, key=lambda e: e.sort_key)
        _BY_ID = {e.id: e for e in _INDEX}
    return _INDEX


def entry(m, key):
    index(m)
    return _BY_ID.get(key)


def in_category(m, category, station=''):
    return [e for e in index(m) if (not category or e.category == category) and (not station or station in e.tags)]


def in_view(ctx, category, station=''):
    """Recipes for a category, or for the Ready now / Favourites views."""
    if category == 'ready':
        favorites = set(ctx.favorites)
        rows = [e for e in index(ctx.m) if (not station or station in e.tags) and ctx.status(e).code == 'ready']
        return sorted(rows, key=lambda e: (e.id not in favorites, e.sort_key))
    if category == 'favorites':
        return [e for e in (entry(ctx.m, i) for i in ctx.favorites) if e is not None and (not station or station in e.tags)]
    return in_category(ctx.m, category, station)


def station_code(tag):
    return sorted(cp.STATIONS).index(tag) if tag in cp.STATIONS else -1


def station_from_code(value):
    try:
        return sorted(cp.STATIONS)[int(value)]
    except (TypeError, ValueError, IndexError):
        return ''


def find_station(value):
    value = str(value or '').strip()
    if not value:
        return ''
    if value.upper() in cp.STATIONS:
        return value.upper()
    matches = [k for k, v in cp.STATIONS.items() if v['name'].casefold() == value.casefold()]
    return matches[0] if len(matches) == 1 else None


@dataclass
class Status:
    code: str       # ready, missing, station, owned, locked
    emoji: str
    short: str      # fits a dropdown label
    detail: str     # full sentence for previews


class Context:
    """One player's crafting situation, loaded once per screen."""

    def __init__(self, m, db, p, provider='discord'):
        self.m, self.db, self.p, self.provider = m, db, p, provider
        self.stock = s.stock(m, db, p) if p is not None else {}
        self.batches = cp.manufactured_batches(m, db, p) if p is not None else 0
        self.tier = max(t for t, _, n in cp.TIERS if self.batches >= n)
        owned_machines = [k for k in s.MACHINE_RECIPES if self.stock.get(k, 0) > 0]
        self.access = {tag for tag in cp.STATIONS if tag == cp.SURVIVAL or self.stock.get(cp.permit_key(tag), 0) > 0
                       or any(tag in s.machine_tags(k) for k in owned_machines)}
        self._levels = {}
        self.society_tier = m.society_tier_index(m.society(db, p.channel_id)) if p is not None else 0
        self.harvesting = m.lvl(m.skill_xp(p, 'extraction')) if p is not None else 1
        self._statuses = {}
        self._unique = None
        self._favorites = None

    @property
    def favorites(self):
        if self._favorites is None:
            from . import qol
            self._favorites = qol.favorite_ids(self.m, self.db, self.p) if self.p is not None else []
        return self._favorites

    def star(self, e):
        return '⭐' if e.id in self.favorites else ''

    def have(self, key):
        key = self.m.item_identity.canonical(key)
        if key in self.m.QUALITY_RECIPES:
            return self.m.equipment_count(self.db, self.p, key) if self.p is not None else 0
        if key == 'cargo':
            return self.p.cargo if self.p is not None else 0
        return self.stock.get(key, 0)

    def level(self, skill_key):
        if skill_key not in self._levels:
            self._levels[skill_key] = s.level_for(self.m, self.db, self.p, skill_key) if self.p is not None else 1
        return self._levels[skill_key]

    def owned_unique(self, key):
        if self.p is None:
            return False
        if self._unique is None:
            self._unique = {k for k in (*self.m.UNIQUE_CORE_ITEMS, *self.m.UNIQUE_QUALITY_ITEMS)
                            if self.m.unique_bonus_owned(self.db, self.p, k)}
        return key in self._unique

    def unlock_option(self, e):
        """Cheapest workstation this recipe could use once it is unlocked."""
        options = [t for t in e.tags if cp.STATIONS[t]['tier'] <= self.tier and t not in self.access]
        return min(options, key=lambda t: (cp.STATIONS[t]['cost'], cp.STATIONS[t]['name'])) if options else None

    def usable_tags(self, e):
        return [t for t in e.tags if cp.STATIONS[t]['tier'] <= self.tier and t in self.access]

    def best_tag(self, e):
        usable = self.usable_tags(e)
        if not usable:
            return None
        if e.kind == 'legacy':
            return usable[0]
        return max(usable, key=lambda t: (sum(production_balance.outputs_at(s, cp, e.id, t).values()), cp.STATIONS[t]['tier'], t))

    def outputs(self, e):
        if e.kind == 'legacy':
            return {e.output: 1}
        tag = self.best_tag(e)
        return production_balance.outputs_at(s, cp, e.id, tag) if tag else dict(s.RECIPES[e.id]['outputs'])

    def batch_size(self, e):
        return self.outputs(e).get(e.output, e.quantity)

    def status(self, e):
        if e.id in self._statuses:
            return self._statuses[e.id]
        result = self._status(e)
        self._statuses[e.id] = result
        return result

    def _status(self, e):
        from . import seasonal
        if not seasonal.festival_open(e.id):
            holiday = seasonal.FESTIVAL_RECIPES[e.id]
            start, _ = seasonal.festival_window(holiday)
            return Status('locked', '🔒', f'{holiday} festival (opens {start.isoformat()})', '🎉 ' + seasonal.festival_lock_text(e.id))
        base_tier = s.base_tier(e.id) if e.kind == 'seed' else cp.STATIONS[e.tags[0]]['tier']
        need = cp.TIERS[base_tier - 1][2]
        if self.tier < base_tier:
            return Status('locked', '🔒', f'Tier {base_tier} ({self.batches}/{need} batches)',
                          f'Needs personal Tier {base_tier}: {need} manufacturing batches (you have {self.batches}).')
        if e.kind == 'seed' and self.level(e.skill_key) < e.level:
            return Status('locked', '🔒', f'{e.skill} Lv{e.level} (you {self.level(e.skill_key)})',
                          f'Needs {e.skill} Lv.{e.level}; you are Lv.{self.level(e.skill_key)}. Train it with lower-level recipes or /training.')
        if e.kind == 'seed' and any(k in cp.RARE for k in s.RECIPES[e.id]['outputs']) and self.harvesting < cp.RARE_LEVEL:
            return Status('locked', '🔒', 'Harvesting Lv3', 'Rare ores need Harvesting Lv.3 (12 XP).')
        if e.kind == 'legacy':
            society_need = self.m.RECIPE_TIERS.get(e.id)
            if society_need and self.society_tier < society_need:
                label = self.m.SOCIETY_TIERS[society_need][0]
                return Status('locked', '🔒', f'Society: {label}', f'Unlocks when New Eridian reaches {label}.')
            if self.owned_unique(e.id):
                return Status('owned', '✅', 'owned (limit 1)', 'You already own one; bonus equipment is limited to one of each.')
        if not self.usable_tags(e):
            cheapest = self.unlock_option(e)
            fee = cp.STATIONS[cheapest]['cost']
            return Status('station', '🔑', f"unlock {cp.STATIONS[cheapest]['name']} {fee} SC",
                          f"Unlock {cp.STATIONS[cheapest]['name']} once for {fee} SC with /workshop, or own the matching machine.")
        missing = [(k, n - self.have(k)) for k, n in e.inputs.items() if self.have(k) < n]
        if missing:
            key, short = missing[0]
            more = f' +{len(missing) - 1} more' if len(missing) > 1 else ''
            return Status('missing', '❌', f'need {short} {self.m.resource_name(key)}{more}',
                          'Missing: ' + ', '.join(f'{n} {self.m.resource_name(k)}' for k, n in missing) + '.')
        return Status('ready', '✅', 'ready', 'Ready to craft.')


def station_label(e, ctx=None):
    tag = (ctx.best_tag(e) if ctx else None) or e.tags[0]
    name = cp.STATIONS[tag]['name']
    others = len(e.tags) - 1
    return name + (f' +{others}' if others > 0 else '')


def inputs_text(ctx, e, multiplier=1):
    if not e.inputs:
        return 'no ingredients (extraction)'
    return ', '.join(f'{ctx.m.resource_name(k)} {ctx.have(k)}/{n * multiplier}' for k, n in e.inputs.items())


def clip(text, limit=100):
    text = str(text)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def choice_label(ctx, e):
    """Dropdown label: status, name, batch, tier/station and the key blocker."""
    st = ctx.status(e)
    head = f'{st.emoji}{ctx.star(e)} {e.name} ×{ctx.batch_size(e)}'
    tail = f' · T{e.tier} {station_label(e, ctx)}'
    reason = '' if st.code == 'ready' else ' · ' + st.short
    return clip(head + tail + reason)


def option_description(ctx, e):
    st = ctx.status(e)
    need = inputs_text(ctx, e)
    text = (st.short[:1].upper() + st.short[1:] if st.code != 'ready' else 'Ready') + ' · ' + need
    return clip(text)


def autocomplete_rows(ctx, category='', station='', query=''):
    q = str(query or '').casefold().strip()
    rows = in_view(ctx, category, station)
    if q:
        rows = [e for e in rows if q in e.name.casefold() or q in e.id.casefold()
                or any(q in cp.STATIONS[t]['name'].casefold() for t in e.tags)]
        # Named searches show what you can make now before locked matches.
        rows = sorted(rows, key=lambda e: (STATUS_ORDER[ctx.status(e).code], e.sort_key))
    return [(choice_label(ctx, e), e.id) for e in rows[:25]]


def resolve(m, db, p, value, category=''):
    """Recipe id, legacy key, retired legacy name or item name -> Entry."""
    value = str(value or '').strip()
    if not value:
        return None
    key = value.casefold().replace(' ', '_')
    if category not in CATEGORY_INFO:
        category = ''   # Ready now / Favourites filter the same recipes
    retired = m.item_identity.RETIRED_RECIPES.get(key)
    for candidate in (value, key, retired):
        found = entry(m, candidate) if candidate else None
        if found:
            return found
    matches = [e for e in index(m) if e.name.casefold() == value.casefold() and (not category or e.category == category)]
    if not matches:
        found = s.find_recipe(value)
        return entry(m, found) if found else None
    if len(matches) == 1 or p is None:
        return matches[0]
    ctx = Context(m, db, p)
    return min(matches, key=lambda e: (STATUS_ORDER[ctx.status(e).code], e.sort_key))


def category_counts(ctx):
    counts = {}
    for e in index(ctx.m):
        total, ready, lowest = counts.get(e.category, (0, 0, 9))
        counts[e.category] = (total + 1, ready + (ctx.status(e).code == 'ready'), min(lowest, e.tier))
    all_ready = sum(ready for _, ready, _ in counts.values())
    counts['ready'] = (all_ready, all_ready, 1)
    favorites = [entry(ctx.m, i) for i in ctx.favorites]
    counts['favorites'] = (len(favorites), sum(ctx.status(e).code == 'ready' for e in favorites), min((e.tier for e in favorites), default=1))
    return counts


def tier_line(ctx):
    name = cp.TIERS[ctx.tier - 1][1]
    if ctx.tier < len(cp.TIERS):
        nxt = cp.TIERS[ctx.tier][2]
        return f'Personal Tier {ctx.tier} {name} · {ctx.batches} manufacturing batches (Tier {ctx.tier + 1} at {nxt})'
    return f'Personal Tier {ctx.tier} {name} · {ctx.batches} manufacturing batches (maximum tier)'


def start_here(ctx, limit=3):
    ready = [e for e in index(ctx.m) if ctx.status(e).code == 'ready' and e.inputs]
    return ready[:limit]


def gather_first(ctx, limit=3):
    """Recipes at an unlocked workstation that only lack gatherable materials."""
    rows = []
    for e in index(ctx.m):
        if ctx.status(e).code != 'missing':
            continue
        missing = [k for k, n in e.inputs.items() if ctx.have(k) < n]
        if all(k in s.GATHER and k not in cp.RARE for k in missing):
            rows.append(e)
        if len(rows) >= limit:
            break
    return rows


def home_text(ctx):
    m = ctx.m
    counts = category_counts(ctx)
    if ctx.provider != 'discord':
        # Category keys are what players type, so they are shown instead of labels.
        # Totals are dropped before the line could exceed one 380-byte chat message.
        views = [f'ready {counts["ready"][0]}'] + ([f'favs {counts["favorites"][0]}'] if counts['favorites'][0] else [])
        for totals in (True, False):
            parts = views + [f"{k} {counts.get(k, (0, 0, 1))[1]}" + (f"/{counts.get(k, (0, 0, 1))[0]}" if totals else '') for k, *_ in CATEGORIES]
            text = (f'🛠️ Workbench T{ctx.tier} ({ctx.batches} batches), ' + ('ready/total' if totals else 'ready now') + ': '
                    + ' · '.join(parts) + ' | !make <category> [page] lists easiest first; !make <recipe> crafts one batch.')
            if len(text.encode()) <= 380:
                return text
        return text
    lines = [f'🛠️ WORKBENCH — {ctx.p.display_name if ctx.p else "Citizen"}', tier_line(ctx),
             f"Workstations unlocked: {len(ctx.access)} of {len(cp.STATIONS)} (Survival Workbench is free). /workshop unlocks more.", '',
             f"✅ Ready now: {counts['ready'][0]} recipes · ⭐ Favourites: {counts['favorites'][1]}/{counts['favorites'][0]} ready", '',
             'CATEGORIES · ready now / recipes · easiest tier']
    for key, emoji, label, text in CATEGORIES:
        total, ready, lowest = counts.get(key, (0, 0, 1))
        lines.append(f'{emoji} {label} — {ready}/{total} ready · from T{lowest}')
    easy = start_here(ctx)
    lines += ['', 'START HERE']
    if easy:
        lines += [f'✅ {e.name} ×{ctx.batch_size(e)} — {station_label(e, ctx)} · uses {inputs_text(ctx, e)}' for e in easy]
    else:
        for e in gather_first(ctx):
            missing = ', '.join(f'{n - ctx.have(k)} {m.resource_name(k)}' for k, n in e.inputs.items() if ctx.have(k) < n)
            lines.append(f'❌ {e.name} at {station_label(e, ctx)} — gather {missing} with /gather or /mine, then craft it.')
        lines.append('The Survival Workbench is free. Unlock more workstations with /workshop (15 SC each at Tier 1); Seed Industries sells starter supplies.')
    lines += ['', 'Pick a category (menu below or /make category:<name>), then a recipe. Every list runs from the easiest recipe to the most complex. '
              'Previews show ingredients you have and need, the workstation, tier, skill and where to get each ingredient.']
    return '\n'.join(lines)


def page_bounds(total, page, size=PAGE_SIZE):
    pages = max(1, math.ceil(total / size))
    page = max(1, min(int(page or 1), pages))
    return page, pages, (page - 1) * size, page * size


def category_text(ctx, category, page=1, station=''):
    m = ctx.m
    emoji, label, description = VIEW_INFO[category]
    rows = in_view(ctx, category, station)
    station_note = f" · {cp.STATIONS[station]['name']} only" if station else ''
    if ctx.provider != 'discord':
        return _chat_category(ctx, category, rows, page, station_note)
    page, pages, start, end = page_bounds(len(rows), page)
    shown = rows[start:end]
    ready = sum(ctx.status(e).code == 'ready' for e in rows)
    lines = [f'{emoji} {label.upper()} · Page {page}/{pages}{station_note}',
             f'{description} {len(rows)} recipes, easiest first · {ready} ready now · {tier_line(ctx)}', '']
    for number, e in enumerate(shown, start + 1):
        st = ctx.status(e)
        lines.append(f'{number}. {st.emoji}{ctx.star(e)} {e.name} ×{ctx.batch_size(e)} — T{e.tier} · {station_label(e, ctx)} · {e.skill} Lv{e.level}')
        lines.append(f'   {inputs_text(ctx, e)}' + ('' if st.code in {'ready', 'missing'} else f' · {st.short}'))
    if not rows:
        lines.append(empty_view_text(category))
    lines += ['', '✅ ready · ❌ missing ingredients · 🔑 workstation to unlock · 🔒 tier, skill or society lock',
              'Choose a recipe in the menu below (or /make recipe:<name>) to see its full preview before crafting.']
    return '\n'.join(lines)


def _chat_category(ctx, category, rows, page, station_note):
    """Twitch: one line per page. A name crafted at several benches is listed
    once with its best status, because '!make <name>' picks that variant."""
    emoji, label, _ = VIEW_INFO[category]
    if not rows:
        return f'{emoji} {label}: {empty_view_text(category, ctx.provider)}'
    best, order = {}, []
    for e in rows:
        name = e.name.casefold()
        if name not in best:
            order.append(name)
            best[name] = e
        elif STATUS_ORDER[ctx.status(e).code] < STATUS_ORDER[ctx.status(best[name]).code]:
            best[name] = e
    unique = [best[name] for name in order]
    page, pages, start, end = page_bounds(len(unique), page, CHAT_PAGE_SIZE)
    shown = unique[start:end]
    more = f'!make {category} {page + 1} next' if page < pages else 'last page'
    # Chat messages are capped at 380 bytes; shed the legend, then tiers, before
    # the command hint would be cut off.
    for legend, tiers in ((True, True), (False, True), (False, False)):
        items = ' · '.join(f"{ctx.status(e).emoji}{e.name}" + (f' T{e.tier}' if tiers else '') for e in shown) or 'no recipes'
        text = (f'{emoji} {label} {page}/{pages}{station_note}: {items}' + (' | ✅ready ❌missing 🔑unlock 🔒locked' if legend else '')
                + f' | !make <recipe name> crafts; {more}.')
        if len(text.encode()) <= 380:
            return text
    while len(text.encode()) > 380 and len(shown) > 1:
        shown = shown[:-1]
        items = ' · '.join(f"{ctx.status(e).emoji}{e.name}" for e in shown)
        text = f'{emoji} {label} {page}/{pages}{station_note}: {items} | !make <recipe name> crafts; {more}.'
    return text


def empty_view_text(category, provider='discord'):
    if category == 'favorites':
        return ('No favourites yet. Open a recipe and press ⭐ Favourite.' if provider == 'discord'
                else 'No favourites yet. !fav <recipe name> stars one.')
    if category == 'ready':
        return ('Nothing is ready yet. Open a ❌ recipe and press 🧺 Fetch missing, or /gather materials.' if provider == 'discord'
                else 'Nothing is ready yet. !fetch <recipe> shows how to get its ingredients.')
    return 'No recipes match this filter.'


def used_for(m, key):
    users = [e.name for e in index(m) if key in e.inputs]
    return users


def preview_text(ctx, e, count=1):
    m = ctx.m
    st = ctx.status(e)
    outputs = ctx.outputs(e)
    tag = ctx.best_tag(e)
    if ctx.provider != 'discord':
        return (f"🛠️ {e.name} ×{ctx.batch_size(e)} | {st.emoji} {st.short} | T{e.tier} {station_label(e, ctx)} · {e.skill} Lv{e.level} | "
                f"Uses {inputs_text(ctx, e)} | !make {e.id} crafts one batch.")
    emoji, label, _ = CATEGORY_INFO[e.category]
    lines = [f'🛠️ {e.name.upper()} — {emoji} {label}',
             f"{st.emoji} {st.detail}", '',
             'OUTPUT PER BATCH']
    lines += [f'• {m.resource_name(k)} ×{n}' for k, n in outputs.items()]
    if e.kind == 'seed':
        options = '; '.join(f"{cp.STATIONS[t]['name']} ×{production_balance.outputs_at(s, cp, e.id, t).get(e.output, e.quantity)}" for t in e.tags)
        lines.append(f'• Batch size by workstation: {options}')
        if ctx.p is not None:
            lines.append('• ' + production_balance.quote(m, ctx.db, ctx.p, e.id))
    else:
        lines.append('• ' + legacy_effect(m, e.id))
    lines += ['', 'REQUIREMENTS']
    base_tier = s.base_tier(e.id) if e.kind == 'seed' else cp.STATIONS[e.tags[0]]['tier']
    tier_ok = ctx.tier >= base_tier
    lines.append(f"{'✅' if tier_ok else '🔒'} Personal tier: Tier {base_tier} {cp.TIERS[base_tier - 1][1]} — you are Tier {ctx.tier} ({ctx.batches} batches)")
    for t in e.tags:
        station = cp.STATIONS[t]
        if t in ctx.access and station['tier'] <= ctx.tier:
            state = '✅ unlocked'
        elif t in ctx.access:
            state = f"🔒 owned; usable at Tier {station['tier']}"
        else:
            state = f"🔑 unlock once for {station['cost']} SC (button below, or /workshop action:Unlock Station station:{t})"
        lines.append(f"{'✅' if state.startswith('✅') else '•'} Workstation: {station['name']} (T{station['tier']}) — {state}")
    if e.kind == 'seed':
        have = ctx.level(e.skill_key)
        lines.append(f"{'✅' if have >= e.level else '🔒'} Skill: {e.skill} Lv.{e.level} — you are Lv.{have}")
    else:
        society_need = m.RECIPE_TIERS.get(e.id)
        if society_need:
            name = m.SOCIETY_TIERS[society_need][0]
            lines.append(f"{'✅' if ctx.society_tier >= society_need else '🔒'} Society tier: {name}")
    lines += ['', 'INGREDIENTS · have / need']
    if not e.inputs:
        lines.append('• None: extraction uses your work cooldown and success roll.')
    for k, n in e.inputs.items():
        have = ctx.have(k)
        mark = '✅' if have >= n * count else '❌'
        line = f'{mark} {m.resource_name(k)} {have}/{n * count}'
        if have < n * count:
            line += f' — get it: {m.material_source(k, ctx.provider)}'
        lines.append(line)
    energy = m.task_energy('rare' if e.kind == 'seed' and any(k in cp.RARE for k in s.RECIPES[e.id]['outputs']) else 'make')
    lines += ['', 'COST PER BATCH', f"{m.need_cost_text(energy)} · 5-second workshop cooldown · ingredients are used only on success"]
    users = used_for(m, e.output)
    if users:
        lines += ['', f'USED IN {len(users)} RECIPES', ', '.join(users[:8]) + (' …' if len(users) > 8 else '')]
    lines += ['', 'Craft one batch now, or queue up to 10 batches with the buttons below '
              f'(or /make recipe:{e.id} action:Craft / action:Queue count:<1–10>).']
    return '\n'.join(line for line in lines if line is not None)


def legacy_effect(m, key):
    if key in m.QUALITY_RECIPES:
        data = m.QUALITY_RECIPES[key]
        skills = ', '.join(m.SKILL_LABELS[k] for k in data['skills']) or 'life recovery'
        return f"Quality gear (rolls Crude→Masterwork): improves {skills}; special: {data['special']}."
    return m.ITEM_EFFECTS.get(key, 'Equipment')


def queue_plan_text(ctx, e, count):
    """Totals for a queue of `count` batches, shown before it starts."""
    m = ctx.m
    lines = [f'⏱️ QUEUE {count} × {e.name.upper()}', f'Output: up to {ctx.batch_size(e) * count} {e.name} ({ctx.batch_size(e)} per successful batch).', '',
             'INGREDIENTS FOR THE WHOLE QUEUE · have / need']
    if not e.inputs:
        lines.append('• None.')
    for k, n in e.inputs.items():
        have = ctx.have(k)
        total = n * count
        lines.append(f"{'✅' if have >= total else '⚠️'} {m.resource_name(k)} {have}/{total}" + ('' if have >= total else f' — enough for {have // n} batch(es); the queue pauses when it runs out'))
    # Same per-attempt cost and pace the queue worker uses (rare outputs are heavier).
    _, energy, interval = m.task_queue.specification(m, 'make:' + e.id)
    need = m.finish_forecast(energy, count)
    life = m.life_state(ctx.db, ctx.p)
    lines += ['', 'NEEDS · now / needed to finish without recovery',
              f"Energy {life.energy}/{need['energy']} · Nutrition {life.nutrition}/{need['nutrition']} · Social {life.social}/{need['social']} · Comfort {life.comfort}/{need['comfort']}",
              f"Each batch costs {m.need_cost_text(energy)}. The queue works one batch every {interval} seconds, pauses if a need or ingredient runs short, and resumes by itself.",
              '', 'Press Start to begin, or go back. Only one queue can run at a time.']
    return '\n'.join(lines)


def guide_lines(m, db, p, provider):
    ctx = Context(m, db, p, provider)
    prefix = '/' if provider == 'discord' else '!'
    easy = start_here(ctx, 2)
    lines = [f"🛠️ Workbench: {tier_line(ctx)}."]
    if easy:
        lines += [f"Ready now: {e.name} ×{ctx.batch_size(e)} at {station_label(e, ctx)} ({prefix}make recipe:{e.id})." if provider == 'discord'
                  else f"Ready now: {e.name} (!make {e.id})." for e in easy]
    else:
        lines.append(f'Gather with {prefix}gather and {prefix}mine, then open {prefix}make: categories list recipes from easiest to hardest.')
    lines.append(f"{prefix}workshop shows station access and tiers; {prefix}catalog explains every ingredient's source.")
    return lines


def next_step(m, db, p, provider):
    ctx = Context(m, db, p, provider)
    easy = start_here(ctx, 1)
    prefix = '/' if provider == 'discord' else '!'
    if easy:
        return f"{prefix}make recipe:{easy[0].id} ({easy[0].name})" if provider == 'discord' else f"!make {easy[0].id}"
    return f'{prefix}gather or {prefix}mine for raw materials, then {prefix}make'


def station_rows(ctx, query=''):
    q = str(query or '').casefold()
    counts = {}
    for e in index(ctx.m):
        for t in e.tags:
            counts[t] = counts.get(t, 0) + 1
    rows = []
    for tag, station in sorted(cp.STATIONS.items(), key=lambda kv: (kv[1]['tier'], kv[1]['name'])):
        if q and q not in station['name'].casefold():
            continue
        if station['tier'] > ctx.tier:
            state = f"🔒 T{station['tier']} ({ctx.batches}/{cp.TIERS[station['tier'] - 1][2]} batches)"
        elif tag in ctx.access:
            state = '✅ ready'
        else:
            state = f"🔑 unlock {station['cost']} SC"
        rows.append((clip(f"{station['name']} · T{station['tier']} · {counts.get(tag, 0)} recipes · {state}"), tag))
    return rows
