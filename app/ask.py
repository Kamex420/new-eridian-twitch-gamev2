"""Ask Find a question.

Players can type a plain word ("campfire") or a question:

    how do I make Iron Nails?        where do I get Coal?          what is Clay used for?
    how do I level Chemistry?        what does Morale mean?        why can't I craft a Campfire?
    what should I do next?           why can't I work?

No AI runs behind it. Each question shape is recognised by its words, its subject is matched
against the game's own recipes, items, skills and handbook terms (typos, plurals and old item
names included), and the answer is built from the same data the rest of the game uses, with the
player's own bag and levels when they are known. A plain word is still the usual search.

Questions it cannot answer are counted (never who asked) so the game owner can see what players
look for: /mod action:asklog.
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import Column, String, Integer, DateTime, select, delete, func

from .db import Base
from . import workbench as wb, seed_content as s, crafting_progression as cp
from . import runtime
from .models import Player

MAX_QUERY = 100          # the /find option and the menu's text box take up to this many characters
LOG_KEEP = 300           # unanswered questions kept for the owner (the oldest go first)


class FindQuestion(Base):
    """A question Find could not answer, counted per world. Holds no player ids."""
    __tablename__ = 'find_unanswered_v1'
    channel_id = Column(String(64), primary_key=True)
    question = Column(String(MAX_QUERY), primary_key=True)
    times = Column(Integer, nullable=False)
    first_asked = Column(DateTime(timezone=True), nullable=False)
    last_asked = Column(DateTime(timezone=True), nullable=False)


def install(m):
    FindQuestion.__table__.create(runtime.engine, checkfirst=True)


@dataclass
class Answer:
    """intent: next, why, needs, level, make, uses, get, define, money, search, suggest (which one?), unknown.
    actions: what the answer's buttons do (see ui.ask_components)."""
    intent: str
    text: str
    actions: list = field(default_factory=list)
    answered: bool = True


# ---------------------------------------------------------------- reading the question

_ART = r"(?:a |an |the |some |more |my |any )?"
_MAKE = r"(?:make|craft|build|cook|create|brew|bake|forge|assemble|produce)"
_GET = r"(?:get|find|obtain|gather|collect|mine|farm|buy|acquire|source|harvest)"
_LEVEL = (r"(?:level(?: up)?|lvl(?: up)?|train|raise|improve|increase|grind|practi[cs]e|get better at|"
          r"get (?:xp|exp|experience) (?:in|for|on))")

# (intent, patterns). Tried in this order; a pattern whose subject is not found lets the next intent try.
PATTERNS = [
    ('next', [r"^(?:what|wat|wut) (?:should|do|can|shall) i (?:do|try|work on|make|craft)(?: next| now| first| today)?$",
              r"^(?:what(?:s| is)? next|what now|now what|next steps?|what to do(?: next| now)?)$",
              r"^(?:im|i am) (?:stuck|lost|confused|bored|new(?: here)?)$",
              r"^(?:where|how) (?:do|should|can) i (?:start|begin)$",
              r"^(?:help|help me|how do i play|how to play)$"]),
    ('needs', [r"^why (?:cant|cannot|can not|wont) i (?:work|do (?:any )?tasks?|do anything|do work|gather|mine|train|"
               r"craft anything|make anything)$",
               r"^why (?:am i|is my citizen|is my character) (?:blocked|too tired|unable to work)$"]),
    ('why', [rf"^why (?:cant|cannot|can not|wont|doesnt|isnt) (?:i|it) (?:let me )?{_MAKE} {_ART}(?P<s>.+)$",
             rf"^why (?:is|are) {_ART}(?P<s>.+?) (?:locked|greyed out|grayed out|unavailable|not ready|red|disabled|blocked)$",
             rf"^why (?:cant|cannot|can not) i (?:start|use|do) {_ART}(?P<s>.+)$"]),
    ('level', [rf"^how (?:do|can|should|would) i {_LEVEL} {_ART}(?P<s>.+?)(?: skill| level| levels| xp| up)?$",
               rf"^how (?:to|2) {_LEVEL} {_ART}(?P<s>.+?)(?: skill| level| xp| up)?$",
               rf"^(?:where|how) (?:do|can) i (?:get|earn) {_ART}(?P<s>.+?) (?:xp|exp|experience|levels?)$",
               rf"^{_LEVEL} {_ART}(?P<s>.+?)(?: skill| up)?$",
               r"^(?P<s>.+?) (?:xp|leveling|levelling|training)$"]),
    ('make', [rf"^how (?:do|can|would|should|to|2) (?:i |you |we )?{_MAKE} {_ART}(?P<s>.+)$",
              rf"^(?:whats |what is )?(?:the )?recipe (?:for|of) {_ART}(?P<s>.+)$",
              rf"^what (?:do|does) (?:i|it|you) need (?:to {_MAKE}|for) {_ART}(?P<s>.+)$",
              rf"^what (?:goes|is|are) in(?:to)? {_ART}(?P<s>.+)$",
              rf"^(?:how is|how are) {_ART}(?P<s>.+?) (?:made|crafted|built|cooked)$",
              rf"^{_MAKE} {_ART}(?P<s>.+)$",
              r"^(?P<s>.+?) recipe$"]),
    ('uses', [rf"^what (?:is|are|s) {_ART}(?P<s>.+?) (?:used for|good for|useful for|used in|used|for)$",
              rf"^what (?:can|do|should|could) (?:i|you) (?:make|do|craft|build|cook|use) with {_ART}(?P<s>.+)$",
              rf"^what (?:uses|needs|takes|requires|is made (?:from|with)) {_ART}(?P<s>.+)$",
              rf"^(?:uses? (?:of|for)|use for|what to do with) {_ART}(?P<s>.+)$",
              rf"^(?:how (?:do|can) i|how to) use {_ART}(?P<s>.+)$",
              rf"^(?:is|are) {_ART}(?P<s>.+?) (?:useful|worth (?:keeping|anything)|needed|used)$",
              r"^(?P<s>.+?) uses?$"]),
    ('get', [rf"^(?:where|how) (?:do|can|would|should|to|2) (?:i |you |we )?{_GET} {_ART}(?P<s>.+)$",
             rf"^where (?:does|do|is|are|can) {_ART}(?P<s>.+?)(?: come from| found| spawn| drop| located| from| sold)?$",
             rf"^(?:get|obtain|source of|sources of|source for|where) {_ART}(?P<s>.+)$",
             rf"^i (?:need|want) {_ART}(?P<s>.+)$"]),
    ('define', [rf"^what (?:is|are|does|do|s) {_ART}(?P<s>.+?)(?: mean| do| does| stand for| for)?$",
                rf"^(?:define|explain|meaning of|definition of|what does|whats) {_ART}(?P<s>.+?)(?: mean)?$",
                rf"^(?:who|what) (?:is|are) {_ART}(?P<s>.+)$"]),
]
_COMPILED = [(intent, [re.compile(p) for p in patterns]) for intent, patterns in PATTERNS]

_FILLER = re.compile(r"\b(?:please|pls|plz|thanks|thank you|thx|actually|in this game|in new eridian)\b")
_GREETING = re.compile(r"^(?:hey|hi|hello|yo|ok|okay|so|um|uh)\b ?")


def clean(query):
    """Lower case, no punctuation or filler words, single spaces: "How do I make Iron Nails?!" -> "how do i make iron nails"."""
    text = str(query or '').casefold().replace('’', "'").replace('‘', "'").replace('`', "'")
    text = re.sub(r"\b(what|where|who|that|there|how)'s\b", r"\1 is", text)          # what's -> what is
    text = re.sub(r"\b(whats|wheres)\b", lambda x: x.group(1)[:-1] + ' is', text)
    text = text.replace("'", '')                                                    # can't -> cant, rocky's -> rockys
    text = re.sub(r"[^\w&+ -]+", ' ', text).replace(' - ', ' ')
    text = _FILLER.sub(' ', ' '.join(text.split()))
    text = _GREETING.sub('', ' '.join(text.split()))
    return ' '.join(text.split())[:MAX_QUERY]


def parse(query):
    """[(intent, subject)] for every question shape the text fits, most specific first ('' subject: none needed)."""
    text = clean(query)
    found = []
    for intent, patterns in _COMPILED:
        for pattern in patterns:
            hit = pattern.match(text)
            if hit:
                subject = (hit.groupdict().get('s') or '').strip()
                subject = re.sub(r"^(?:a|an|the|some|more|my|any) ", '', subject)
                if (intent, subject) not in found:
                    found.append((intent, subject))
    return found


# ---------------------------------------------------------------- finding the subject

def _norm(text):
    return ' '.join(str(text or '').casefold().replace('_', ' ').replace('&', 'and').split())


def _forms(text):
    """The text, then its singular forms: 'berries' -> 'berry', 'nails' -> 'nail', 'boxes' -> 'box'."""
    text = _norm(text)
    forms = [text]
    if text.endswith('ies') and len(text) > 4:
        forms.append(text[:-3] + 'y')
    if text.endswith('es') and len(text) > 3:
        forms.append(text[:-2])
    if text.endswith('s') and not text.endswith('ss') and len(text) > 2:
        forms.append(text[:-1])
    return list(dict.fromkeys(forms))


def _match(text, names, rank=None):
    """(value or None, suggestion names) over each form of `text` (see qol.match). Suggestions: every name holding
    the words, easiest first by `rank` (name -> sort key), else qol.match's typo guesses."""
    from . import qol
    suggestions = []
    for form in _forms(text):
        value, near = qol.match(form, names)
        if value is not None:
            return value, []
        suggestions += [n for n in near if n not in suggestions]
    if rank is not None:
        words = _forms(text)
        holding = [n for n in names if any(w in n for w in words)]
        if holding:
            suggestions = sorted(holding, key=lambda n: (rank(n), n))
    return None, suggestions[:3]


def _recipe_rank(m):
    order = {}
    for i, e in enumerate(wb.index(m)):          # the index lists recipes easiest first
        order.setdefault(_norm(e.name), i)
    return lambda name: order.get(name, 10 ** 6)


def find_recipe(m, text):
    """(easiest recipe entry with that output name, suggestions)."""
    from . import qol
    names = qol.recipe_names(m)
    name, near = _match(text, names, _recipe_rank(m))
    if name is None:
        key, _ = find_item(text, m)
        if key is not None:
            makers = [e for e in wb.index(m) if e.output == key]
            if makers:
                return makers[0], []
        return None, [names.get(x, x) for x in near]
    return next(e for e in wb.index(m) if e.name == name), []


def find_item(text, m=None):
    """(item key, suggestions): names, plurals, partial names and old names (Crops, Components…)."""
    from . import qol
    for form in _forms(text):
        key = s.find_item(form)
        if key in s.ACTIVE:
            return key, []
    if _norm(text) in {'cargo', 'personal cargo'}:
        return 'cargo', []
    names = qol.item_names()
    rank = None
    if m is not None:                            # gathered items first, then the easiest to craft
        recipes = _recipe_rank(m)
        rank = lambda n: (names[n] not in s.GATHER, recipes(n))
    key, near = _match(text, names, rank)
    return (key, []) if key is not None else (None, [s.ITEMS[names[x]]['name'] for x in near if x in names])


_SKILLS = None


def skills(m):
    """{normalized name: (main, branch or None, label, skill key)} for every skill and branch players can level."""
    from .game.rules import SKILL_LABELS
    from .seed_skills import HUBS as SEED_HUBS, TASKS as SEED_TASKS
    global _SKILLS
    if _SKILLS is None:
        _SKILLS = {}
        for skill_key, (main, branch) in s.SKILLS.items():
            _SKILLS.setdefault(_norm(s.skill_name(skill_key)), (main, branch, s.skill_name(skill_key), skill_key))
        mains = {main: key for key, (main, branch) in s.SKILLS.items() if branch is None}
        for hub, main in SEED_HUBS.items():
            if main in mains:
                value = (main, None, SKILL_LABELS.get(main, main.title()), mains[main])
                _SKILLS.setdefault(_norm(hub), value)
                _SKILLS.setdefault(_norm(SKILL_LABELS.get(main, main)), value)
                _SKILLS.setdefault(_norm(main), value)
        for cfg in SEED_TASKS.values():      # task names that differ from their skill's ('Maintenance & Repair')
            match = [v for v in _SKILLS.values() if v[1] == cfg['branch'] or (v[1] is None and cfg['branch'] is None and v[0] == cfg['skill'])]
            if match:
                _SKILLS.setdefault(_norm(cfg['label']), match[0])
    return _SKILLS


def find_skill(m, text):
    value, near = _match(text, {k: k for k in skills(m)})
    if value is None:
        return None, [skills(m)[n][2] for n in near if n in skills(m)]
    return skills(m)[value], []


# Terms the handbook's Terms page does not define, worded from the rules in the code.
EXTRA_TERMS = {
    'Needs': 'Energy, Nutrition, Social and Comfort. Tasks use them up; eating, resting and spending time with others fill them again. '
             'Work stops while Energy, Nutrition or Social is below 20, or Comfort is below 10.',
    'Energy': 'A need. Work and crafting use it; /relax and /sleep restore it. Work stops below 20.',
    'Nutrition': 'A need. Tasks use it; /eat restores it (raw food a little, prepared meals more). Work stops below 20.',
    'Social': 'A need. /games, /social and hangouts with other citizens restore it. Work stops below 20.',
    'Comfort': 'A need that drains along with Energy. Below 20 it lowers success and Morale; work stops below 10. '
               '/relax, /sleep, or /use a bed, seat, bath or clothing item restores it.',
    'Morale': 'Your spirits. 85 or more gives +2% success (Inspired); below 20 gives −7% (Demoralized). '
              'Prepared meals, /walk, /hobby, /games and hangouts raise it.',
    "Rocky's Favor": '+3 percentage points of success for 10 minutes. Eating a prepared meal grants it, and the time stacks.',
    'Seedling': 'Your citizen on the stream map. It has moods and thoughts, and keeps working, eating and sleeping while you are away. '
                'It helps live events, the Society Directive and the colony\'s weakest stat.',
    'Personal tier': 'Your crafting tier. It rises with the batches you craft from ingredients; higher-tier recipes and workstations need it.',
    'Lucky find': 'Successful tasks sometimes turn up one extra item from the same line of work (more often when a task goes especially well). '
                  'Life and social actions never do.',
    'Goal': 'A recipe you work toward. Its walkthrough lists every step (ingredients, machines and skill levels) with a button for each.',
    'Workstation': 'Where a recipe is crafted. Crafting and owning the matching machine opens its workstation for good.',
    'Machine': 'A crafted item that opens a workstation while you own it, e.g. a Furnace or a Medical Fabricator.',
    'Queue': 'Tasks your citizen works through one after another while you do something else. /queue shows it.',
    'Branch': 'A specialty inside a skill (Chemistry inside Processing, Pharmacy inside Medicine). Its training task levels it.',
}
_TERMS = None


def terms(m):
    """{normalized term: (title, definition)} from the handbook's Terms page plus EXTRA_TERMS."""
    from .game.handbook import SEED_HELP_TOPICS
    global _TERMS
    if _TERMS is None:
        _TERMS = {}
        for line in SEED_HELP_TOPICS.get('terms', '').splitlines():
            head, sep, text = line.partition(' — ')
            if not sep or len(head) > 40:
                continue
            for name in head.split(' / '):
                _TERMS.setdefault(_norm(name), (head.strip(), text.strip()))
        for head, text in EXTRA_TERMS.items():
            _TERMS.setdefault(_norm(head), (head, text))
        _TERMS.setdefault('rockys favor', ("Rocky's Favor", EXTRA_TERMS["Rocky's Favor"]))
        _TERMS.setdefault('rocky favor', ("Rocky's Favor", EXTRA_TERMS["Rocky's Favor"]))
        _TERMS.setdefault('seed coins', _TERMS.get('seed coin', ('SC', '')))
    return _TERMS


def find_term(m, text):
    names = {k: k for k in terms(m)}
    value, near = _match(text, names)
    if value is None:
        return None, [terms(m)[n][0] for n in near if n in terms(m)]
    return terms(m)[value], []


def find_leaf(m, text):
    """A menu button or area whose label is the text ('train skills', 'shopping list')."""
    from . import menu
    q = _norm(text)
    for key, (_, title, _, _) in menu.AREAS.items():
        if key != 'home' and _norm(title) == q:
            return key
    for key, leaf in menu.LEAVES.items():
        if _norm(leaf['label']) == q and key not in menu.OWNER_ONLY and not key.startswith('m_'):
            return key
    return None


# ---------------------------------------------------------------- answers

def _ctx(m, db, p, provider):
    return wb.Context(m, db, p, provider)


def _discord(provider):
    return provider == 'discord'


def _lite(m):
    """Twitch is the lite game (app/twitch_lite.py): crafting, goals and the guide are on Discord."""
    return bool(getattr(getattr(m, 'twitch_lite', None), 'ENABLED', False))


def _goal_id(m, db, p):
    if p is None:
        return None
    from . import extras
    e = extras.goal_entry(m, db, p)
    return e.id if e is not None else None


def _plain_inputs(m, e):
    from .game.players import resource_name
    return ', '.join(f'{resource_name(k)} ×{n}' for k, n in e.inputs.items()) or 'no ingredients'


def answer_make(m, db, p, e, provider):
    ctx = _ctx(m, db, p, provider)
    station = wb.station_label(e, ctx)
    ways = sum(1 for x in wb.index(m) if x.name == e.name)
    st = ctx.status(e) if p is not None else None
    reasons = blockers(m, ctx, e) if st is not None and st.code != 'ready' else []
    if not _discord(provider):
        you = (' You: ✅ ready.' if st.code == 'ready' else f' You: {reasons[0][1]}') if st is not None and (reasons or st.code == 'ready') else ''
        how = (' Craft it on Discord with /make, or set it as your goal there for every step.' if _lite(m)
               else f' !make {e.name} · !target {e.name} walks you through every step.')
        text = f'🛠️ {e.name}: {_plain_inputs(m, e)} at the {station} ({e.skill} Lv{e.level}).' + you + how
        return Answer('make', text)
    lines = [f'🛠️ HOW TO MAKE {e.name.upper()}',
             f"**Needs:** {wb.inputs_text(ctx, e) if p is not None else _plain_inputs(m, e)}",
             f'**Makes:** {ctx.batch_size(e)} per batch at the {station}',
             f'**Skill:** {e.skill} Lv {e.level}' + (f' (you are Lv {ctx.level(e.skill_key)})' if p is not None and e.kind == 'seed' else '')
             + f' · personal Tier {e.tier}']
    if st is not None and st.code == 'ready':
        lines.append('**You:** ✅ Ready to craft.')
    elif reasons:
        lines += ['**Before you can make it:**'] + [f'{emoji} {text}' for emoji, text in reasons]
    if ways > 1:
        lines.append(f'There are {ways} recipes for it; this is the easiest.')
    lines += ['', 'Ready: open the recipe to craft it.' if st is not None and st.code == 'ready'
              else 'Set it as your goal and the walkthrough lists every step, machines and skill levels included.']
    actions = [{'kind': 'recipe', 'entry': e}]
    if _goal_id(m, db, p) != e.id:
        actions.append({'kind': 'goal', 'entry': e})
    return Answer('make', '\n'.join(lines), actions)


def _find_sources(m, key):
    """Lines of work whose lucky finds can turn up this item."""
    from .seed_skills import TASKS as SEED_TASKS
    from . import practice
    labels = {cfg['branch']: cfg['label'] for cfg in SEED_TASKS.values()}
    found = []
    for branch, names in practice.BRANCH.items():
        if any(practice.key(m, n) == key for n in names):
            found.append(labels.get(branch) or branch.replace('_', ' ').title())
    return list(dict.fromkeys(found))


def answer_get(m, db, p, key, provider):
    from .game.cooldowns_materials import material_amount, material_source
    from .game.players import resource_name
    name = resource_name(key)
    source = material_source(key, provider)
    best = s.ACQUISITION.get(key) if key in s.ACTIVE else None
    others = [e for e in wb.index(m) if e.output == key and e.id != best][:3]
    finds = _find_sources(m, key)
    have = material_amount(db, p, key) if p is not None else None
    if not _discord(provider):
        if key in s.GATHER:                        # chat commands take the item's name (!mine: one word only)
            source = source.replace(f'!gather {key}', f'!gather {name}')
            if ' ' not in name:
                source = source.replace(f'!mine {key} ', f'!mine {name} ')
        made = wb.entry(m, best) if best and key not in s.GATHER else None
        if made is not None and _lite(m):          # crafting is on Discord in the lite game
            source = f'crafted on Discord (/make): {_plain_inputs(m, made)} at the {wb.station_label(made)}.'
        text = f'📦 {name}: {source}' + (f' Also: {", ".join(e.name + " recipe" for e in others[:2])}.' if others else '')
        text += (f' Lucky finds: {", ".join(finds[:3])}.' if finds else '') + (f' You have {have}.' if have is not None else '')
        return Answer('get', text)
    lines = [f'📦 WHERE TO GET {name.upper()}', f'**Best way:** {source}']
    if others:
        ctx = _ctx(m, db, p, provider)
        lines.append('**Also made by:** ' + '; '.join(f'{e.name} recipe ({_plain_inputs(m, e)} · {wb.station_label(e, ctx)})' for e in others))
    if finds:
        lines.append('**Lucky finds:** sometimes turns up while doing ' + ', '.join(finds[:5]) + '.')
    if have is not None:
        lines.append(f'**You have:** {have}')
    actions = []
    if key in s.GATHER:
        actions.append({'kind': 'gather', 'item': key})
    elif best:
        e = wb.entry(m, best)
        if e is not None:
            actions += [{'kind': 'recipe', 'entry': e}] + ([{'kind': 'goal', 'entry': e}] if _goal_id(m, db, p) != e.id else [])
    if key in s.ACTIVE:
        actions.append({'kind': 'uses', 'item': key})
    return Answer('get', '\n'.join(lines), actions)


def answer_uses(m, db, p, key, provider):
    from .game.players import resource_name
    from . import qol
    ctx = _ctx(m, db, p, provider)
    name = resource_name(key)
    rows = [e for e in wb.index(m) if key in e.inputs]
    if p is not None:
        rows.sort(key=lambda e: (wb.STATUS_ORDER[ctx.status(e).code], e.sort_key))
    purpose = s.PURPOSE.get(key) or {}
    price = qol.sell_price(m, key)
    use = purpose.get('label') if purpose.get('mode') not in (None, 'ingredient', 'research') else ''
    if not _discord(provider):
        parts = [f'🔍 {name}:']
        if use:
            parts.append(use)
        if rows:
            parts.append(f'ingredient in {len(rows)} recipes: ' + ', '.join(e.name for e in rows[:6]) + ('…' if len(rows) > 6 else '') + '.')
        if not rows and not use:
            parts.append('no recipe uses it yet; analyze it for Research XP' + (f' or sell it for {price} SC.' if price else '.'))
        return Answer('uses', ' '.join(parts))
    lines = [f'🔍 WHAT IS {name.upper()} FOR?']
    if use:
        lines.append(f'**Use:** {use}')
    if rows:
        lines.append(f'**Ingredient in {len(rows)} recipe{"s" if len(rows) != 1 else ""}**' + (', ready ones first:' if p is not None else ':'))
        for e in rows[:8]:
            st = ctx.status(e) if p is not None else None
            lines.append(f"{st.emoji + ' ' if st else '• '}**{e.name}** — needs {e.inputs[key]}" + (f' · {st.short}' if st else ''))
        if len(rows) > 8:
            lines.append(f'…and {len(rows) - 8} more: What uses it? lists them.')
    if not rows and not use:
        lines.append('Nothing is made from it yet. Analyze it for +1 Research XP (/use), or sell it.')
    if price:
        lines.append(f'**Sells for:** {price} SC each at Seed Industries.')
    if p is not None:
        lines.append(f'**You have:** {ctx.have(key)}')
    actions = [{'kind': 'recipe', 'entry': e} for e in rows[:3]]
    if len(rows) > 3:
        actions.append({'kind': 'uses', 'item': key})
    return Answer('uses', '\n'.join(lines), actions)


def _hub(m, main):
    from .seed_skills import HUBS as SEED_HUBS
    return next((h for h, k in SEED_HUBS.items() if k == main), None)


def answer_level(m, db, p, skill, provider):
    from .game.players import resource_name
    from .game.rules import SKILL_LABELS
    from .game.training_and_items import training_tasks
    from .seed_skills import TASKS as SEED_TASKS
    main, branch, label, skill_key = skill
    hub = _hub(m, main)
    main_label = SKILL_LABELS.get(main, main.title())
    ctx = _ctx(m, db, p, provider)
    level = ctx.level(skill_key) if p is not None else None
    if hub is None:
        return Answer('level', f'📈 {label} is practised by its work tasks: {"/work" if _discord(provider) else "!work"} lists them.')
    if p is not None:
        tasks = [t for t in training_tasks(db, p, hub, 'discord' if _discord(provider) else 'twitch')
                 if (t['cfg']['branch'] == branch if branch else True)]
    else:
        tasks = [{'key': k, 'cfg': c, 'status': '', 'head': f"{c['label']} — needs {main_label} Lv{c['unlock']}",
                  'uses': '  Uses: ' + (', '.join(f'{resource_name(x)} ×{n}' for x, n in c['cost'].items()) or 'no items')}
                 for k, c in SEED_TASKS.items() if c['hub'] == hub and (c['branch'] == branch if branch else True)]
    ready = [t for t in tasks if t['status'] == '✅']
    if not _discord(provider):
        shown = '; '.join(f"{t['status'] + ' ' if t['status'] else ''}{t['cfg']['label']}: !training {hub} {t['key']}" for t in (ready or tasks)[:3])
        return Answer('level', f'📈 {label}' + (f' (Lv {level})' if level is not None else '') + f': train it with {shown}.'
                      + (f' It is part of {main_label}.' if branch else ''))
    lines = [f'📈 HOW TO LEVEL {label.upper()}']
    lines.append((f'You are Lv {level}. ' if level is not None else '')
                 + (f'It is a {main_label} specialty: its training task practises it.' if branch
                    else f'Every {main_label} training task practises it' + (', ready ones first:' if p is not None else ':')))
    for t in tasks[:4]:
        lines += [t['head'], t['uses']]
    if len(tasks) > 4:
        lines.append(f'…and {len(tasks) - 4} more on the Train {main_label} screen.')
    if p is not None and not ready and tasks:
        lines.append('Nothing trains it yet: each line says what it still needs. Set a goal that needs this skill and the walkthrough plans it for you.')
    lines.append('Each try costs a little Energy, Nutrition and Comfort; materials are only used on success.')
    actions = [{'kind': 'start', 'hub': hub, 'task': t['key'], 'label': t['cfg']['label']} for t in ready[:2]]
    actions.append({'kind': 'train', 'hub': hub, 'label': main_label})
    return Answer('level', '\n'.join(lines), actions)


def blockers(m, ctx, e):
    """Every reason `e` cannot be crafted right now, not only the first (workbench.Context.status)."""
    from .game.players import resource_name
    from .game.rules import RECIPE_TIERS, SOCIETY_TIERS
    from . import seasonal, extras
    found = []
    if not seasonal.festival_open(e.id):
        found.append(('🎉', seasonal.festival_lock_text(e.id)))
    base = s.base_tier(e.id) if e.kind == 'seed' else cp.STATIONS[e.tags[0]]['tier']
    need = cp.TIERS[base - 1][2]
    if ctx.tier < base:
        found.append(('🔒', f'Needs personal Tier {base}: craft {need - ctx.batches} more batches of anything made from ingredients '
                            f'({ctx.batches}/{need}).'))
    if e.kind == 'seed' and ctx.level(e.skill_key) < e.level:
        found.append(('📈', f'Needs {e.skill} Lv {e.level}; you are Lv {ctx.level(e.skill_key)}. Ask Find: how do I level {e.skill}?'))
    if e.kind == 'seed' and any(k in cp.RARE for k in s.RECIPES[e.id]['outputs']) and not ctx.rare_ok:
        found.append(('⛏️', 'Rare ores need a Small or Frontiers Expedition Mineral Extractor in your bag.'))
    if e.kind == 'legacy':
        society_need = RECIPE_TIERS.get(e.id)
        if society_need and ctx.society_tier < society_need:
            found.append(('🏙️', f'Unlocks when New Eridian reaches {SOCIETY_TIERS[society_need][0]}.'))
        if ctx.owned_unique(e.id):
            found.append(('✅', 'You already own one; bonus equipment is limited to one of each.'))
    if not ctx.usable_tags(e):
        machine_key, machine = extras._machine(m, ctx, e)
        station = cp.STATIONS[e.tags[0]]['name'] if e.tags else 'workstation'
        if machine is not None:
            found.append(('🏭', f'Needs the {station}: craft a {resource_name(machine_key)} to open it for good.'))
        else:
            option = ctx.unlock_option(e)
            found.append(('🏭', f"Needs the {cp.STATIONS[option]['name'] if option else station}"
                                + (f" (unlock it once for {cp.STATIONS[option]['cost']} SC in /workshop)." if option else '.')))
    missing = [(k, n - ctx.have(k)) for k, n in e.inputs.items() if ctx.have(k) < n]
    if missing:
        found.append(('❌', 'Missing: ' + ', '.join(f'{n} {resource_name(k)}' for k, n in missing) + '.'))
    if not found and ctx.status(e).code != 'ready':        # a rule this list does not know yet
        st = ctx.status(e)
        found.append((st.emoji, st.detail))
    return found


def answer_why(m, db, p, e, provider):
    if p is None:
        return Answer('why', f'Start playing first ({"/start" if _discord(provider) else "!start"}), then ask again.')
    ctx = _ctx(m, db, p, provider)
    reasons = blockers(m, ctx, e)
    if not _discord(provider):
        if not reasons:
            return Answer('why', f'✅ Nothing is stopping you: {e.name} is ready.' + (' Craft it on Discord with /make.' if _lite(m) else f' !make {e.name}'))
        plan = ' Set it as your goal on Discord (/make) to plan every step.' if _lite(m) else f' !target {e.name} plans every step.'
        return Answer('why', f'🔒 {e.name}: ' + ' '.join(text for _, text in reasons) + plan)
    if not reasons:
        return Answer('why', f'✅ NOTHING IS STOPPING YOU\n{e.name} is ready to craft at the {wb.station_label(e, ctx)}.',
                      [{'kind': 'recipe', 'entry': e}])
    lines = [f"🔒 WHY CAN'T I MAKE {e.name.upper()}?"] + [f'{emoji} {text}' for emoji, text in reasons]
    lines += ['', 'Set it as your goal: the walkthrough turns each of these into steps, each with its own button.']
    actions = ([{'kind': 'goal', 'entry': e}] if _goal_id(m, db, p) != e.id else [{'kind': 'goalview'}]) + [{'kind': 'recipe', 'entry': e}]
    return Answer('why', '\n'.join(lines), actions)


def answer_needs(m, db, p, provider):
    from .game.life import life_state
    from .game.world import NEED_EMOJI, comfort_status_line, need_fix
    from .needs import blocked_needs
    if p is None:
        return Answer('needs', f'Start playing first ({"/start" if _discord(provider) else "!start"}), then ask again.')
    life = life_state(db, p)
    blocked = blocked_needs(life)
    if blocked:
        lines = [f"{NEED_EMOJI[f]} {label} {value}/100 (needs {minimum}) → {need_fix(f, provider, db, p)}" for f, label, value, minimum in blocked]
        if not _discord(provider):
            return Answer('needs', '⛔ Work is paused: ' + ' | '.join(lines))
        return Answer('needs', '⛔ WHY CAN\'T I WORK?\nA need is too low. Blocked tries spend nothing.\n' + '\n'.join(lines),
                      [{'kind': 'area', 'key': 'life'}, {'kind': 'status'}])
    note = comfort_status_line(life)
    rest = ((note + ' ') if note else '') + ('If a task still will not start, its cooldown or a queue may be running: check '
                                             + ('/status.' if _discord(provider) else '!status.'))
    if not _discord(provider):
        return Answer('needs', '✅ Your needs are fine for work. ' + rest)
    return Answer('needs', '✅ YOUR NEEDS ARE FINE FOR WORK\n' + rest, [{'kind': 'status'}])


def answer_skills(m, db, p, provider):
    """"How do I level up?": every skill, how many of its tasks are ready, and where to train."""
    from .game.training_and_items import training_skill_line, training_skills
    if not _discord(provider):
        return Answer('level', '📈 Every skill has training tasks: !training <skill> lists them (farming, harvesting, engineering, '
                               'processing, crafting, cooking, medicine, emergency). Ask !find how do I level <skill> for one.')
    lines = ['📈 HOW DO I LEVEL UP?', 'Each skill has training tasks; doing one practises the skill (and its specialty).']
    if p is not None:
        lines += ['• ' + training_skill_line(label, level, ready, total) for _, label, level, ready, total in training_skills(db, p)]
    lines.append('Ask about one skill for its tasks and a Start button, e.g. how do I level Chemistry?')
    return Answer('level', '\n'.join(lines), [{'kind': 'leaf', 'key': 'trainskill'}])


def answer_next(m, db, p, provider):
    from . import qol, extras
    if p is None:
        guide = '/guide' if _discord(provider) or _lite(m) else '!guide'     # the lite game's reply filter adds 'on Discord'
        return Answer('next', f'👋 New here? {"/start" if _discord(provider) else "!start"} creates your citizen, then '
                              f'{guide} shows your best next step.')
    goal = extras.goal_entry(m, db, p)
    wording = 'discord' if _discord(provider) or _lite(m) else provider    # lite: crafting is on Discord, so its /commands
    step = extras.next_step(m, db, p, wording)[0] if goal is not None else ''
    tip = qol.next_step(m, db, p, wording)
    if not _discord(provider):
        return Answer('next', ((f'🎯 Goal {goal.name}: {step} ' if step else '') + f'🧭 {tip}').replace('**', ''))
    lines = ['🧭 WHAT SHOULD I DO NEXT?']
    if step:
        lines.append(f'🎯 **Your goal, {goal.name}:** {step}')
    lines.append(f'**Right now:** {tip}')
    lines.append('What next? reads your needs, cooldowns and colony too; or ask Find about anything, e.g. how do I make Campfire?')
    actions = ([{'kind': 'goalview'}] if goal is not None else []) + [{'kind': 'leaf', 'key': 'guide'}]
    return Answer('next', '\n'.join(lines), actions)


MONEY = {'money', 'sc', 'seed coin', 'seed coins', 'coin', 'coins', 'cash', 'currency', 'gold'}


def answer_money(m, provider):
    """"How do I make money?": the ways the handbook names, and the guide that picks one for you."""
    if not _discord(provider):
        return Answer('money', '💰 Seed Coin comes from work (+1 SC when it matches your job), the three daily Production Orders, '
                               'and selling surplus to Seed Industries. ' + ('/guide picks the best way.' if _lite(m)
                                                                            else '!guide shows your best next step.'))
    lines = ['💰 HOW DO I EARN SEED COIN?',
             '• **Work:** tasks pay SC; work that matches your job pays +1 SC more (/job).',
             '• **Production Orders:** three rotating daily Seed Industries contracts, once each per Avesta day.',
             '• **Sell surplus:** Seed Industries buys items at fixed prices (/seedindustries).',
             '• **Specialization:** at Lv 10, matching actions pay +1 SC.',
             'The Earn Seed Coin guide reads your situation and picks the best way right now.']
    return Answer('money', '\n'.join(lines), [{'kind': 'guide', 'goal': 'seed_coin', 'label': 'Earn SC guide'}])


def answer_term(m, term, provider):
    title, text = term
    if not _discord(provider):
        return Answer('define', f'📖 {title}: {text}')
    return Answer('define', f'📖 {title.upper()}\n{text}')


def answer_leaf(m, key, provider):
    from . import menu
    menu = menu
    if key in menu.AREAS:
        _, title, text, _ = menu.AREAS[key]
    else:
        leaf = menu.LEAVES[key]
        title, text = leaf['label'], (leaf.get('hint') or '').capitalize() + '.'
    if not _discord(provider):
        return Answer('define', f'🔘 {title} (Discord /menu): {text}')
    return Answer('define', f'🔘 {title.upper()}\nA button in /menu. {text}', [{'kind': 'leaf', 'key': key}])


def answer_item(m, db, p, key, provider):
    """What an item is: what it does, how to get it, what it is for."""
    from .game.cooldowns_materials import material_amount, material_source
    from .game.players import resource_name
    name = resource_name(key)
    description = s.ITEMS.get(key, {}).get('description', '') if key in s.ACTIVE else ''
    used = len([e for e in wb.index(m) if key in e.inputs])
    purpose = (s.PURPOSE.get(key) or {}).get('label', '')
    if not _discord(provider):
        return Answer('define', f'📦 {name}: ' + (description[:120] + ' ' if description else '') + f'Get it: {material_source(key, provider)}')
    lines = [f'📦 {name.upper()}'] + ([description] if description else [])
    lines += [f'**Get it:** {material_source(key, provider)}']
    if purpose:
        lines.append(f'**Use:** {purpose}')
    elif used:
        lines.append(f'**Use:** ingredient in {used} recipes.')
    if p is not None:
        lines.append(f'**You have:** {material_amount(db, p, key)}')
    return Answer('define', '\n'.join(lines), [{'kind': 'uses', 'item': key}] + ([{'kind': 'gather', 'item': key}] if key in s.GATHER else []))


# ---------------------------------------------------------------- putting it together

def _resolve(m, db, p, intent, subject, provider):
    """(Answer or None, suggestions) for one reading of the question."""
    from .game.players import resource_name
    if intent == 'next':
        return answer_next(m, db, p, provider), []
    if intent == 'needs':
        return answer_needs(m, db, p, provider), []
    if not subject:
        return None, []
    if intent in {'make', 'get'} and _norm(subject) in MONEY:
        return answer_money(m, provider), []
    if intent == 'why':
        if _norm(subject) in {'work', 'do tasks', 'do anything', 'gather', 'mine', 'train'}:
            return answer_needs(m, db, p, provider), []
        e, near = find_recipe(m, subject)
        return (answer_why(m, db, p, e, provider), []) if e else (None, near)
    if intent == 'level':
        if _norm(subject) in {'up', 'skill', 'skills', 'my skills', 'faster', 'quickly', 'quick', 'fast'}:
            return answer_skills(m, db, p, provider), []
        skill, near = find_skill(m, subject)
        return (answer_level(m, db, p, skill, provider), []) if skill else (None, near)
    if intent == 'make':
        e, near = find_recipe(m, subject)
        key = e.output if e is not None else find_item(subject)[0]
        if key in s.GATHER:                        # "how do I make Stone?": it is gathered first, crafted only late
            return answer_get(m, db, p, key, provider), []
        return (answer_make(m, db, p, e, provider), []) if e else (None, near)
    if intent in {'uses', 'get'}:
        key, near = find_item(subject, m)
        if key is None:
            return None, near
        return (answer_uses if intent == 'uses' else answer_get)(m, db, p, key, provider), []
    if intent == 'define':
        term, near_terms = find_term(m, subject)
        if term:
            return answer_term(m, term, provider), []
        skill, _ = find_skill(m, subject)
        if skill and _norm(subject) in skills(m):
            return answer_level(m, db, p, skill, provider), []
        key, near_items = find_item(subject, m)
        if key is not None and _norm(resource_name(key)) in _forms(subject):
            return answer_item(m, db, p, key, provider), []                 # the item's own name
        from . import knowledge
        known = knowledge.search_answer(m, db, p, subject, provider)      # "what is a season?": the handbook's /season
        if known is not None:
            return known, []
        if key is not None:                                                # part of an item's name ("ducks")
            return answer_item(m, db, p, key, provider), []
        leaf = find_leaf(m, subject)
        if leaf:
            return answer_leaf(m, leaf, provider), []
        e, near_recipes = find_recipe(m, subject)
        if e is not None:
            return answer_make(m, db, p, e, provider), []
        return None, list(dict.fromkeys(near_terms + near_items + near_recipes))[:3]
    return None, []


def _suggestions(m, text):
    """Names close to a word nothing matched, from every list Find knows."""
    found = []
    for finder in (lambda t: find_recipe(m, t)[1], lambda t: find_item(t, m)[1], lambda t: find_skill(m, t)[1],
                   lambda t: find_term(m, t)[1]):
        found += [x for x in finder(text) if x not in found]
    return found[:3]


def answer(m, db, p, query, provider='discord'):
    """The Answer to a question or a search word. intent 'search': a plain word (extras.find); 'handbook': what the
    handbook, commands and menu say (knowledge.search); 'topic': a society stat, Contribution, a need, tiers, housing or
    the clinic; 'unknown': nothing matched."""
    from . import extras, knowledge
    text = str(query or '').strip()[:MAX_QUERY]
    readings = parse(text)
    if not readings or readings[0][0] in {'define', 'level'} or any(knowledge.topic_of_subject(sub) for _, sub in readings if sub):
        # "how do I raise Reputation?", "what is Morale?", "reputation": what raises it, not a word search.
        topic = knowledge.topic_answer(m, db, p, text, provider)
        if topic is not None:
            return topic
    near = []
    which = None
    for intent, subject in readings:
        result, close = _resolve(m, db, p, intent, subject, provider)
        if result is not None:
            return result
        if close and which is None:
            which = (intent, subject, list(dict.fromkeys(close)))
        near += [x for x in close if x not in near]
    if readings:
        # Not an item, recipe or skill: a society stat, Contribution or a need ("how do I build reputation?"),
        # else whatever the handbook, the commands and the menu say about it.
        topic = knowledge.topic_answer(m, db, p, text, provider)
        if topic is not None:
            return topic
        known = knowledge.search_answer(m, db, p, text, provider)
        if which is not None:
            intent, subject, close = which
            # "where do I get iron": several items hold the word, so ask which; a loose guess gives way to the handbook.
            if known is None or all(_norm(subject) in _norm(n) for n in close):
                return Answer('suggest', which_text(subject, close, intent, provider),
                              [{'kind': 'suggest', 'name': n, 'intent': intent} for n in close])
        if known is not None:
            return known
        # A question whose subject is a button or handbook topic ("how do I use the shopping list"): the plain search.
        for subject in dict.fromkeys(sub for _, sub in readings if sub):
            found = extras.find(m, subject)
            if not _discord(provider):
                found = {k: v for k, v in found.items() if k != 'menu'}       # chat lists no Discord buttons
            if any(found.values()):
                return Answer('search', extras.find_text(m, subject, provider), [{'kind': 'search', 'query': subject}])
        if not near:
            near = _suggestions(m, readings[0][1]) if readings[0][1] else []
    else:
        term, _ = find_term(m, text)
        if term and _norm(clean(text)) not in terms(m):
            term = None
        found = extras.find(m, text)
        if not _discord(provider):
            found = {k: v for k, v in found.items() if k != 'menu'}
        if any(found.values()):
            reply = extras.find_text(m, text, provider)
            if term:                                   # a handbook word: its meaning first, then the search
                reply = answer_term(m, term, provider).text + ('\n\n' if _discord(provider) else ' | ') + reply
            return Answer('search', reply, [{'kind': 'search', 'query': text}])
        if term or find_term(m, text)[0]:
            return answer_term(m, term or find_term(m, text)[0], provider)
        skill, _ = find_skill(m, text)
        if skill:
            return answer_level(m, db, p, skill, provider)
        known = knowledge.search_answer(m, db, p, text, provider)
        if known is not None:
            return known
        near = _suggestions(m, text)
    intent = readings[0][0] if readings else 'search'
    return Answer('unknown', unknown_text(text, near, provider), [{'kind': 'suggest', 'name': n, 'intent': intent} for n in near], answered=False)


def which_text(subject, near, intent, provider):
    if not _discord(provider):
        return (f'🔎 Which "{subject}"? ' + ', '.join(near) + f'. Ask again with the full name, e.g. !find {suggestion_query(intent, near[0])}')
    return '\n'.join([f'🔎 WHICH ONE DID YOU MEAN?', f'Several things match “{subject}”. Pick one below:'] + [f'• {n}' for n in near])


def unknown_text(text, near, provider):
    if not _discord(provider):
        return (f'🔎 "{text}": I could not answer that.' + (f' Did you mean {", ".join(near)}?' if near else '')
                + ' Try: !find how do I make <item> · where do I get <item> · how do I level <skill>.')
    lines = [f'🔎 "{text.upper()}"', "I couldn't answer that one yet." + (' Did you mean one of these?' if near else '')]
    if near:
        lines += [f'• {n}' for n in near]
    lines += ['', 'Questions Find understands:', '• how do I make Iron Nails?', '• where do I get Coal?', '• what is Clay used for?',
              '• how do I level Chemistry?', '• what does Morale mean?', "• why can't I craft a Campfire?", '• what should I do next?']
    return '\n'.join(lines)


def suggestion_query(intent, name):
    """The question a Did-you-mean button asks again, with the suggested name in it."""
    return {'make': f'how do I make {name}', 'why': f"why can't I make {name}", 'level': f'how do I level {name}', 'raise': f'how do I raise {name}',
            'uses': f'what is {name} used for', 'get': f'where do I get {name}', 'define': f'what is {name}'}.get(intent, name)


def reply(m, db, p, query, provider='discord', channel=None):
    """The answer's text, after counting it for the owner when Find could not answer it."""
    result = answer(m, db, p, query, provider)
    if not result.answered:
        log(m, db, (p.channel_id if p is not None else channel), query)
    return result.text


# ---------------------------------------------------------------- what players could not find

def log(m, db, channel, query):
    """Count a question Find could not answer. Written in the caller's session; the caller commits it."""
    question = clean(query)
    if not channel or not question or len(question) < 2:
        return
    try:
        found = db.get(FindQuestion, (str(channel), question))
        when = runtime.now()
        if found is not None:
            found.times += 1
            found.last_asked = when
            return
        db.add(FindQuestion(channel_id=str(channel), question=question, times=1, first_asked=when, last_asked=when))
        db.flush()
        total = db.execute(select(func.count()).select_from(FindQuestion)).scalar() or 0
        if total > LOG_KEEP:
            oldest = db.execute(select(FindQuestion.channel_id, FindQuestion.question).order_by(FindQuestion.last_asked)
                                .limit(total - LOG_KEEP)).all()
            for c, q in oldest:
                db.execute(delete(FindQuestion).where(FindQuestion.channel_id == c, FindQuestion.question == q))
    except Exception:                       # counting is a nicety; the player's answer never depends on it
        logging.getLogger(__name__).exception('Find could not count an unanswered question')


def log_text(m, db, days=30, limit=25):
    """The owner's view: what Find could not answer lately, most asked first."""
    since = runtime.now() - timedelta(days=days)
    rows = db.execute(select(FindQuestion).where(FindQuestion.last_asked >= since)).scalars().all()
    merged = {}
    for r in rows:
        times, last = merged.get(r.question, (0, None))
        when = r.last_asked if r.last_asked.tzinfo else r.last_asked.replace(tzinfo=runtime.now().tzinfo)
        merged[r.question] = (times + r.times, max(last, when) if last else when)
    if not merged:
        return f'❓ UNANSWERED FIND QUESTIONS\nNothing in the last {days} days: Find answered everything players asked.'
    ordered = sorted(merged.items(), key=lambda kv: (-kv[1][0], -kv[1][1].timestamp()))
    lines = ['❓ UNANSWERED FIND QUESTIONS', f'What players asked Find in the last {days} days that it could not answer, most asked first. '
             'Only the question is kept, never who asked.', '']
    lines += [f'• {times}× “{q}” · last <t:{int(last.timestamp())}:R>' for q, (times, last) in ordered[:limit]]
    if len(ordered) > limit:
        lines.append(f'…and {len(ordered) - limit} more.')
    return '\n'.join(lines)


def existing_player(m, db, channel, provider, uid):
    """The asker's citizen when they have one; Find never creates one."""
    from .game.players import resolve
    if not channel or not uid:
        return None
    canon = resolve(db, channel, provider, uid)
    return db.execute(select(Player).where(Player.channel_id == channel, Player.twitch_uid == canon)).scalar_one_or_none()
