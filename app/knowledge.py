"""Find's answers about everything that is not an item, a recipe or a skill.

Two parts:

* Topics: the colony's six society stats (Food, Materials, Development, Knowledge, Treasury, Reputation),
  Contribution, the needs (Energy, Nutrition, Social, Comfort, Morale), the society tier, shared housing and
  shared Medicines. Each answer lists what raises it, read from the game's own rules (main.action, the
  training tasks, Society Directives and events), with the colony's current value when the asker plays.

* Search: every other question is matched against the handbook (/seed), the Twitch handbook, the command
  list, the menu's buttons and the guide panels, and the best passages are shown, with a button to the
  handbook page or menu button they came from.
"""
import math
import re

from . import ask

# ---------------------------------------------------------------- topics

SOCIETY = {'food': ('🌾', 'Food'), 'materials': ('⛏️', 'Materials'), 'development': ('🏗️', 'Development'),
           'knowledge': ('🔬', 'Knowledge'), 'treasury': ('🪙', 'Treasury'), 'reputation': ('⭐', 'Reputation')}

# Work that raises each society stat on success (main.action, main.duo and main.work_counts). Each: (what, how much, the Discord
# command, the Twitch action for guide_command; None: done on Discord; '': a mode chat cannot choose, so Discord).
WORK = {
    'food': [('Harvest Pumpkins', '+1, +1–2 more while the colony has shared Water', '/work task:farm_harvest', 'harvest'),
             ('Tend Fields', '+1, +1–2 more while the colony has shared Water', '/work task:farm_tend', 'farm'),
             ('Irrigate', '+1, Hydroponics +2', '/work task:farm_irrigate', 'water'),
             ('Gather wild plants', '+1 a trip', '/gather', 'gather'),
             ('Cook at the Workbench', '+1 a batch', '/make', None)],
    'materials': [('Mining', '+1', '/mine', 'mine'),
                  ('Gather stone, wood, water or ore', '+1 a trip', '/gather', 'gather'),
                  ('Environmental crafting at the Workbench', '+1 a batch', '/make', None)],
    'development': [('Society Infrastructure Repair', '+1', '/repair target:Society Infrastructure', 'repair'),
                    ('Craft parts, tools, furniture or buildings at the Workbench', '+1 a batch', '/make', None),
                    ('Business Investment', '+1 (and +3 Treasury)', '/business action:Invest', None)],
    'knowledge': [('Research', '+1, Field Analysis +2', '/work task:research', 'research'),
                  ('Environmental Scan', '+1', '/work task:scan', 'scan'),
                  ('Frontier Scout', '+1', '/work task:scout', 'explore'),
                  ('Advanced Survey', '+2, needs a Resource Scanner', '/work task:survey', 'survey'),
                  ('Duo research with a friend', '+2', '/social action:Duo Research player:<name>', 'duo_research'),
                  ('Analyze a surplus item', '+1', '/use', None),
                  ('Craft medicine at the Workbench', '+1 a batch', '/make', None)],
    'treasury': [('Spaceport Operations', '+1', '/work task:spaceport', 'spaceport'),
                 ('Expedited Spaceport', '+2 (and +1 Reputation), uses a Power Cell', '/work task:expedite', ''),
                 ('Commerce Work', '+1, Market Analysis +2', '/market action:Commerce Work', 'market'),
                 ('Business Investment', '+3 (and +1 Development)', '/business action:Invest', None)],
    'reputation': [('Delivery', '+1, uses 1 Cargo', '/work task:delivery', 'delivery'),
                   ('Expedited Spaceport', '+1 (and +2 Treasury), uses a Power Cell', '/work task:expedite', ''),
                   ('Business Contract', '+2, needs a business', '/business action:Contract', None),
                   ('Duo delivery with a friend', '+2, uses 1 Cargo', '/social action:Duo Delivery player:<name>', 'duo_delivery')],
}
CONTRIBUTION = [
    ('Any successful job', '+1 each: work tasks, gathering, mining, Workbench crafting and item jobs, '
                           'also when your queue or Seedling does them (more during a Contribution bonus)'),
    ('Helping in an event', 'up to +8 when it ends, by how much you helped; the top helper gets +2 more'),
    ('Finishing a Society Project', '+3 to whoever completes it (/world → Society Project)'),
    ('Finishing the Society Directive', '+2 to whoever completes it (/world → Daily Bulletin)'),
    ('Production Orders', 'Seed Industries\' three daily contracts (/seedindustries)'),
    ('Your Daily Contract', '+1 when done (/me section:daily)'),
    ('Mentoring a newer citizen', '+2 (/social action:Mentor player:<name>)'),
    ('Supplying the clinic', '+1 for each medicine you /use'),
]
NEEDS = {'energy': ('⚡', 'Energy'), 'nutrition': ('🍲', 'Nutrition'), 'social': ('🤝', 'Social'),
         'comfort': ('🏠', 'Comfort'), 'morale': ('✨', 'Morale')}

_ANY = r"(?:^|\b)"
TOPIC_WORDS = [  # (topic, pattern); food and materials also need a colony word, since both are items too
    ('reputation', r'\b(?:reputation|rep)\b'), ('treasury', r'\btreasury\b'), ('knowledge', r'\bknowledge\b'),
    ('development', r'\bdevelopment\b'), ('contribution', r'\bcontributions?\b'),
    ('tier', r'\b(?:society|colony|settlement|town) tiers?\b|\bnext tier\b|\btiers?\b'),
    ('housing', r'\b(?:housing|shared housing|housing spaces?|infrastructure)\b'),
    ('medicines', r'\b(?:shared medicines|medicines stock|clinic)\b'),
    ('energy', r'\b(?:energy|tired|exhausted)\b'), ('nutrition', r'\b(?:nutrition|hunger|hungry|starving)\b'),
    ('comfort', r'\b(?:comfort|uncomfortable)\b'), ('morale', r'\b(?:morale|demoralized|inspired)\b'),
    ('social', r'\b(?:social need|lonely|my social|social is)\b'),
    ('food', r'\b(?:society|colony|settlement|town|shared|stat) food\b|\bfood (?:stat|reserve)\b'),
    ('materials', r'\b(?:society|colony|settlement|town|shared|stat) materials\b|\bmaterials stat\b'),
]
_TOPICS = [(t, re.compile(p)) for t, p in TOPIC_WORDS]
_RAISE = re.compile(r'\b(?:how|what|where|why|ways?|raise|increase|boost|build|grow|improve|earn|gain|get|give|gives|more|up|'
                    r'fill|restore|fix|recover|help|add|farm|grind|low|lower|drop|lost|fast|quick|quickly)\b')


def topic_of(text):
    """The topic a question is about, or None. `text` is ask.clean()'s."""
    words = text.split()
    for topic, pattern in _TOPICS:
        if pattern.search(text) and (len(words) <= 3 or _RAISE.search(text)):
            if topic in NEEDS and re.search(r'\b(?:level|train|skill)\b', text):
                continue
            return topic
    return None


def topic_of_subject(subject):
    """The topic when a question's whole subject names it ("rep", "colony food", "my comfort"), so it wins over items."""
    subject = re.sub(r'^(?:a |an |the |some |more |my |our |any |your )+', '', ask.clean(subject))
    for topic, pattern in _TOPICS:
        if pattern.fullmatch(subject):
            return topic
    return None


def _cmd(m, provider, discord, twitch):
    """The command for a way to raise a stat: Discord's, or a chat !command, or 'on Discord' when chat cannot do it."""
    if ask._discord(provider):
        return discord
    if not twitch or ask._lite(m) and twitch.split('_')[0] not in m.twitch_lite.TWITCH_COMMANDS:
        return 'on Discord'
    return m.guide_command(twitch, 'twitch')


def _society(m, db, p):
    return m.society(db, p.channel_id) if p is not None else None


def _tier_line(m, s, stat=None):
    stats = {k: getattr(s, k) for k in SOCIETY}
    low = min(stats.values())
    nxt = next((t for t in m.SOCIETY_TIERS if t[1] > low), None)
    tier = m.society_tier(s)[0]
    text = f"New Eridian is {'an' if tier[:1].lower() in 'aeiou' else 'a'} {tier}"
    if nxt:
        text += f'; {nxt[0]} needs {nxt[1]} in all six stats'
    if stat is not None and stats[stat] == low:
        text += f'. {SOCIETY[stat][1]} is the lowest, so it holds the next tier back'
    return text + '.'


def answer_society(m, db, p, stat, provider):
    emoji, label = SOCIETY[stat]
    s = _society(m, db, p)
    work = [(what, much, _cmd(m, provider, discord, twitch)) for what, much, discord, twitch in WORK[stat]]
    training = [(c['label'], f"+{c['society'][stat]}", m.guide_command(k, provider)) for k, c in m.SEED_TASKS.items() if c['society'].get(stat)]
    directives = [d[1] for d in m.DIRECTIVES if d[3] == stat]
    amount = max([d[4] for d in m.DIRECTIVES if d[3] == stat], default=8)
    wins = [e['name'] for e in m.EVENTS.values() if e['reward'].get(stat)]
    losses = [e['name'] for e in m.EVENTS.values() if e['penalty'].get(stat)]
    if not ask._discord(provider):
        parts = [f'{emoji} {label}' + (f' (colony {getattr(s, stat)})' if s is not None else '') + ':']
        parts += [f'{what} {much.split(",")[0].split(" (")[0]} ({c})' for what, much, c in work[:4]]
        parts += [f'{n} training {a}' for n, a, _ in training[:2]]
        if directives:
            parts.append(f'{directives[0]} directive +{amount}')
        if wins:
            parts.append('winning events')
        return ask.Answer('topic', _fit(parts[0] + ' ' + ' · '.join(parts[1:])))
    lines = [f'{emoji} HOW TO RAISE {label.upper()}',
             f'{label} is one of New Eridian\'s six society stats. The society tier is set by the lowest of the six.']
    if s is not None:
        lines.append(f'**Now:** {getattr(s, stat)} {label}. ' + _tier_line(m, s, stat))
    lines.append('**Work that adds it** (every success):')
    lines += [f'• **{what}** {much} · {c}' for what, much, c in work]
    if training:
        lines.append('**Training tasks:** ' + ', '.join(f'{n} {a}' for n, a, _ in training[:6]) + ('…' if len(training) > 6 else '') + '.')
    if directives:
        lines.append(f'**Society Directive:** {" or ".join(directives)} adds +{amount} when the colony finishes it, on days it is the directive (Daily Bulletin).')
    if wins:
        lines.append(f'**Events:** winning {", ".join(wins[:4])} adds {label}' + (f'; failing {", ".join(losses[:3])} costs some.' if losses else '.'))
    actions = [{'kind': 'guide', 'goal': 'society', 'label': 'Society guide'}, {'kind': 'leaf', 'key': 'h_society'}]
    return ask.Answer('topic', '\n'.join(lines), actions)


def answer_contribution(m, db, p, provider):
    have = f' You have {p.contribution}.' if p is not None else ''
    if not ask._discord(provider):
        return ask.Answer('topic', _fit(f'🏅 Contribution is your service score for the leaderboard.{have} Earn it: every successful task +1, '
                                        'events (up to +8), Society Projects +3, the Society Directive +2, Production Orders, '
                                        'the daily contract +1, mentoring +2, clinic supplies +1. !leaderboard'))
    lines = ['🏅 HOW TO EARN CONTRIBUTION', 'Contribution is your personal service score: it ranks the leaderboard and '
             'counts toward season points.' + have]
    lines += [f'• **{what}:** {how}' for what, how in CONTRIBUTION]
    return ask.Answer('topic', '\n'.join(lines), [{'kind': 'leaf', 'key': 'h_society'}, {'kind': 'guide', 'goal': 'society', 'label': 'Society guide'}])


def answer_need(m, db, p, need, provider):
    emoji, label = NEEDS[need]
    life = m.life_state(db, p) if p is not None else None
    now = f' You have {getattr(life, need)}/100.' if life is not None else ''
    rule = ask.EXTRA_TERMS[label]               # what it is and what it does, worded from the game's rules
    fix = m.need_fix(need, provider, db, p) if p is not None else m.need_fix(need, provider)
    if not ask._discord(provider):
        return ask.Answer('topic', _fit(f'{emoji} {label}:{now} {rule} Raise it: {fix}. All needs recharge +1 per 15 min up to 60.'))
    lines = [f'{emoji} HOW TO RAISE {label.upper()}', rule + now, f'**Raise it:** {fix}.',
             'All needs also recharge by 1 every 15 real minutes, up to 60, even while you are away.']
    return ask.Answer('topic', '\n'.join(lines), [{'kind': 'area', 'key': 'life'}, {'kind': 'status'}])


def answer_tier(m, db, p, provider):
    s = _society(m, db, p)
    low_stat = min(SOCIETY, key=lambda k: getattr(s, k)) if s is not None else None
    if not ask._discord(provider):
        text = '🏙️ The society tier rises when all six stats (Food, Materials, Development, Knowledge, Treasury, Reputation) reach the next level.'
        if s is not None:
            text += ' ' + _tier_line(m, s) + f' Lowest: {SOCIETY[low_stat][1]} {getattr(s, low_stat)}.'
        return ask.Answer('topic', _fit(text + ' Your own crafting tier rises with crafted batches.'))
    lines = ['🏙️ HOW DO SOCIETY TIERS WORK?',
             'The colony\'s tier is set by the **lowest** of its six stats: Food, Materials, Development, Knowledge, Treasury '
             'and Reputation. Higher tiers add SC pay and unlock recipes.']
    actions = [{'kind': 'guide', 'goal': 'society', 'label': 'Society guide'}]
    if s is not None:
        lines.append('**Now:** ' + _tier_line(m, s) + f' Lowest: **{SOCIETY[low_stat][1]} {getattr(s, low_stat)}**.')
        lines.append(f'Raise {SOCIETY[low_stat][1]} first: ask Find “how do I raise {SOCIETY[low_stat][1]}?”.')
        actions.insert(0, {'kind': 'suggest', 'name': SOCIETY[low_stat][1], 'intent': 'raise'})
    lines.append('Your **personal tier** is different: it rises with the batches you craft and opens harder recipes.')
    return ask.Answer('topic', '\n'.join(lines), actions)


def answer_housing(m, db, p, provider):
    tasks = [(c['label'], m.guide_command(k, provider)) for k, c in m.SEED_TASKS.items() if c['shared'].get('infrastructure')]
    repair = _cmd(m, provider, '/repair target:Society Infrastructure', 'repair')
    if not ask._discord(provider):
        return ask.Answer('topic', _fit('🏘️ Shared housing: every 5 shared Infrastructure adds 1 space; fewer spaces than citizens gives −3% success. '
                                        'Add Infrastructure with ' + ', '.join(c for _, c in tasks) + f', or {repair} while the colony has Components.'))
    lines = ['🏘️ HOW TO ADD SHARED HOUSING', 'Every 5 shared Infrastructure adds 1 housing space for the colony. With fewer spaces than '
             'citizens, everyone gets −3 percentage points of task success. Your own Habitat upgrades do not add shared housing.',
             '**Add Infrastructure:**'] + [f'• **{n}** +1 · {c}' for n, c in tasks] + \
            [f'• **Society Infrastructure Repair** +1–2 while the colony has shared Components (mining and crafting supply them) · {repair}']
    return ask.Answer('topic', '\n'.join(lines), [{'kind': 'leaf', 'key': 'h_society'}])


def answer_medicines(m, db, p, provider):
    tasks = [(c['label'], c['shared']['medicines']) for k, c in m.SEED_TASKS.items() if c['shared'].get('medicines')]
    text = ('Shared Medicines stock the colony clinic. Supply it by using a medicine from your bag (/use), +1 Contribution each, '
            'or with medical training: ' + ', '.join(f'{n} +{a}' for n, a in tasks[:5]) + ('…' if len(tasks) > 5 else '') + '.')
    if not ask._discord(provider):
        return ask.Answer('topic', _fit('🩺 ' + text))
    return ask.Answer('topic', '🩺 HOW TO STOCK THE CLINIC\n' + text, [{'kind': 'train', 'hub': 'medicine', 'label': 'Medicine'}])


def topic_answer(m, db, p, text, provider):
    topic = topic_of(ask.clean(text))
    if topic is None:
        return None
    if topic in SOCIETY:
        return answer_society(m, db, p, topic, provider)
    if topic in NEEDS:
        return answer_need(m, db, p, topic, provider)
    return {'contribution': answer_contribution, 'tier': answer_tier, 'housing': answer_housing,
            'medicines': answer_medicines}[topic](m, db, p, provider)


def _fit(text, limit=380):
    if len(text.encode()) <= limit:
        return text
    while len(text.encode()) > limit - 1:
        text = text[:text.rstrip().rfind(' ')] if ' ' in text else text[:-1]
    return text.rstrip(' ,·;:') + '…'


# ---------------------------------------------------------------- search over everything the game explains

STOP = set('''how do does did i im you we can could should would to the a an is are am was be what whats where when why which who whom my me
of for in on at it its and or if get got make there any some way ways best tell about game new eridian please this that these
those with without from into out by as so just really much many also than then thing things stuff find know use using possible
need want wanna gonna yes no not dont doesnt cant cannot'''.split())
SYNONYMS = {'made': ['kamex', 'creator'], 'creator': ['kamex'], 'author': ['kamex'], 'developer': ['kamex', 'klang'],'money': ['sc', 'coin'], 'cash': ['sc', 'coin'], 'coin': ['sc'], 'gold': ['sc'], 'rep': ['reputation'],
            'friend': ['relationship', 'social'], 'friendship': ['relationship'], 'xp': ['practice', 'level'],
            'exp': ['xp', 'practice'], 'experience': ['xp', 'practice'], 'house': ['home', 'habitat'], 'housing': ['housing', 'habitat'],
            'profession': ['job', 'occupation'], 'occupation': ['job'], 'quest': ['contract', 'directive'], 'buff': ['bonus'],
            'boost': ['bonus'], 'shop': ['seedindustries', 'market'], 'store': ['seedindustries', 'market'], 'buy': ['seedindustries'],
            'sell': ['seedindustries', 'sell'], 'company': ['business'], 'hat': ['season'], 'badge': ['trophies'], 'cooldown': ['cooldown'],
            'timer': ['cooldown'], 'link': ['link'], 'twitch': ['twitch', 'link'], 'pet': ['duck', 'fleet'], 'duck': ['fleet', 'duck']}


def stem(word):
    w = word.casefold().strip("'’")
    if len(w) > 4 and w.endswith('ies'):
        return w[:-3] + 'y'
    if len(w) > 4 and w.endswith(('ches', 'shes', 'xes', 'sses')):
        return w[:-2]
    if len(w) > 3 and w.endswith('s') and not w.endswith(('ss', 'us', 'is')):
        w = w[:-1]
    if len(w) > 5 and w.endswith('ing'):
        w = w[:-3]
    elif len(w) > 4 and w.endswith('ed'):
        w = w[:-2]
    return w


# Everyday verbs say little about what is asked ("change my job", "start a business"): the noun decides.
GENERIC = {stem(w) for w in '''change start begin unlock open see check show give take put go set turn work level more fast quick
quickly better first next help raise increase improve'''.split()}


def tokens(text):
    text = str(text).casefold().replace('_', ' ').replace("'", '').replace('’', '')      # rocky's -> rockys
    return [stem(w) for w in re.findall(r'[a-z0-9]+', text) if w not in STOP and len(w) > 1]


class Passage:
    __slots__ = ('head', 'body', 'source', 'action', 'head_t', 'body_t')

    def __init__(self, head, body, source, action=None):
        self.head, self.body, self.source, self.action = head.strip(), body.strip(), source, action
        self.head_t, self.body_t = set(tokens(head)), set(tokens(body))


_INDEX = {}
TOPIC_NAMES = {'start': 'Start here', 'character': 'Character', 'property': 'Home & crafting', 'life': 'Life', 'production': 'Work',
               'operations': 'Logistics', 'society': 'Society', 'other': 'Other', 'terms': 'Terms', 'about': 'About'}


def _handbook(m):
    found = []
    for topic, text in m.SEED_HELP_TOPICS.items():
        if topic == 'moderator':
            continue
        heading, block = '', []
        action = {'kind': 'leaf', 'key': 'h_' + topic}
        source = f'Handbook · {TOPIC_NAMES.get(topic, topic)}'

        def flush():
            if block:
                found.append(Passage(heading, ' '.join(block), source, action))
                block.clear()
        for line in text.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            if line.isupper() and len(line) < 60:      # a heading: the lines under it are one passage ("Event Rules")
                flush()
                heading = line.title()
                continue
            head, sep, body = line.partition(' — ')
            if sep and len(head) <= 60:
                flush()
                found.append(Passage(head, body, source, action))
            else:
                block.append(line)
        flush()
    return found


def _twitch_handbook():
    from . import twitch_help
    found = []
    for topic, text in twitch_help.TOPICS.items():
        if topic == 'moderator':
            continue
        for sentence in re.split(r'(?<=[.!?])\s+(?=[!A-Z])', text):
            head, sep, body = sentence.partition(': ')
            if sep and len(head) <= 60:
                found.append(Passage(head, body, f'Handbook · {TOPIC_NAMES.get(topic, topic)}'))
            elif sentence.strip():
                found.append(Passage('', sentence, f'Handbook · {TOPIC_NAMES.get(topic, topic)}'))
    return found


def _commands():
    from .command_catalog import commands
    found = []
    for c in commands:
        if c.get('name') in {'mod', 'eventstart', 'eventstop', 'modlog', 'linklookup'}:
            continue
        found.append(Passage('/' + c['name'], c.get('description', ''), 'Command'))
    return found


def _menu(m):
    found = []
    menu = m.menu
    for key, (_, title, text, _) in menu.AREAS.items():
        if key not in {'home', 'mod'} and key not in getattr(menu, 'MOD_AREAS', set()):
            found.append(Passage(title, text, 'Menu', {'kind': 'area', 'key': key}))
    for key, leaf in menu.LEAVES.items():
        if key.startswith('m_') or key in menu.OWNER_ONLY or not leaf.get('hint') or menu.PARENT.get(key) == 'mod':
            continue
        found.append(Passage(leaf['label'], leaf['hint'], 'Menu', {'kind': 'leaf', 'key': key}))
    return found


def _panels():
    from . import guide_panels
    found = []
    for panel in guide_panels.PANELS:
        for heading, rows in panel[2]:
            if callable(rows):
                continue
            for row in rows:
                if isinstance(row, tuple) and len(row) == 2:
                    found.append(Passage(row[0], row[1], 'Guide'))
    return found


def index(m, provider):
    key = 'twitch' if not ask._discord(provider) else 'discord'
    if key not in _INDEX:
        passages = []
        for build in ((_twitch_handbook,) if key == 'twitch' else ()) + ((lambda: _handbook(m)),) + \
                     ((_commands, (lambda: _menu(m)), _panels) if key == 'discord' else ()):
            try:
                passages += build()
            except Exception:                  # one source failing never breaks Find
                import logging
                logging.getLogger(__name__).exception('Find could not index a help source')
        terms = [Passage(title, text, 'Handbook · Terms', {'kind': 'leaf', 'key': 'h_terms'}) for title, text in ask.EXTRA_TERMS.items()]
        passages += terms
        from . import seasons
        wear = '/season section:hats' if key == 'discord' else '!hat <name>'
        passages.append(Passage('Holiday hats', "Craft every festival food and keepsake of a holiday (a Jack-o'-lantern Mask makes your Seedling a pumpkin head) to win its Feast trophy and its hat: "
                                + ', '.join(f'{seasons.HATS[h][1]} ({holiday})' for holiday, h in seasons.HOLIDAY_HATS.items())
                                + f'. Wear one with {wear}; your Seedling shows it on the stream map.', 'Handbook · Terms',
                                {'kind': 'leaf', 'key': 'c_hats'}))
        seen, unique = set(), []
        for p_ in passages:
            sig = (p_.head.casefold(), p_.body.casefold())
            if p_.body and sig not in seen:
                seen.add(sig)
                unique.append(p_)
        df = {}
        for p_ in unique:
            for t in p_.head_t | p_.body_t:
                df[t] = df.get(t, 0) + 1
        n = len(unique)
        idf = {t: math.log(1 + n / c) for t, c in df.items()}
        _INDEX[key] = (unique, idf)
    return _INDEX[key]


def query_terms(text):
    found = []
    for t in tokens(ask.clean(text)):
        for x in [t] + [stem(s) for s in SYNONYMS.get(t, [])]:
            if x not in found:
                found.append(x)
    return found


# Explanations first; a menu button's short hint is better as a button than as the answer.
WEIGHT = {'Handbook': 1.25, 'Guide': 0.85, 'Command': 0.7, 'Menu': 0.5}


def search(m, text, provider='discord', limit=3):
    """[(score, passage)] best first: passages that hold most of the question's meaningful words (or their synonyms)."""
    passages, idf = index(m, provider)
    words = tokens(ask.clean(text))
    if not words:
        return []
    rare = max(idf.values(), default=1)

    def weight(w):                             # a word the game never uses weighs most, so it must be matched
        return idf.get(w, rare) * (0.35 if w in GENERIC else 1)
    stands_for = {}
    for w in words:
        stands_for.setdefault(w, w)
        for s_ in SYNONYMS.get(w, []):
            stands_for.setdefault(stem(s_), w)
    core = [w for w in dict.fromkeys(words) if w not in GENERIC] or list(dict.fromkeys(words))
    wanted = sum(weight(w) for w in core)        # how well a passage answers: the question's nouns, not its verbs
    exact = ' '.join(core)
    scored = []
    for p_ in passages:
        score, covered = 0.0, set()
        for t, w in stands_for.items():
            if t in p_.head_t:
                score += weight(t) * 1.6
            elif t in p_.body_t:
                score += weight(t)
            else:
                continue
            covered.add(w)
        coverage = sum(weight(w) for w in covered if w in core) / wanted
        if score and coverage >= 0.5:
            if ' '.join(tokens(p_.head)) == exact:   # the passage is about exactly this ("/season" for "what is a season")
                score *= 1.3
            scored.append((round(coverage, 2), score * WEIGHT.get(p_.source.split(' ·')[0], 1) / (1 + len(p_.body) / 500), p_))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    best, shown = [], set()
    top = scored[0][0] if scored else 0
    for coverage, score, p_ in scored:
        if coverage < top - 0.15 or p_.body in shown:
            continue
        shown.add(p_.body)
        best.append((score, p_))
        if len(best) == limit:
            break
    return best


def search_answer(m, db, p, text, provider):
    found = search(m, text, provider, limit=6)
    if not found:
        return None
    hits = [h for h in found if h[1].source != 'Menu'][:3] or found[:3]
    menu_hits = [h for h in found if h[1].source == 'Menu']
    if not ask._discord(provider):
        return ask.Answer('handbook', _fit('📖 ' + ' | '.join((f'{h.head}: ' if h.head else '') + h.body for _, h in hits[:2])))
    lines = ['📖 WHAT THE GAME SAYS', f'About “{text.strip()[:ask.MAX_QUERY]}”:']
    for _, h in hits:
        lines.append((f'**{h.head}** — ' if h.head else '• ') + h.body + f' *({h.source})*')
    actions, seen = [], set()
    for _, h in menu_hits[:2] + hits:                  # the matching menu buttons first, then the handbook pages
        if h.action and (h.action['kind'], h.action['key']) not in seen:
            seen.add((h.action['kind'], h.action['key']))
            actions.append(h.action)
    return ask.Answer('handbook', '\n'.join(lines), actions[:3])
