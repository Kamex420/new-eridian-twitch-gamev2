"""How every Discord reply looks: small receipts for tasks, full cards for information.

Game handlers return plain text. This module turns that text into one of three
card shapes, so every command reads the same way:

* receipt — a task was performed (work, crafting, gathering, eating, relaxing…).
  A short card: what you got, what it cost, practice, and at most a few lines
  for anything that needs attention (a failure reason, a level up, a warning).
* notice  — a one- or two-line answer (a cooldown, a refusal, a confirmation).
  Just the sentence, coloured by outcome.
* info    — views and menus. A clean title, an intro and titled sections with
  their complete text; very long views continue on Details pages.

Nothing here changes game state; it only arranges text that already exists.
"""
import re

EMBED_TOTAL = 5800
OVERVIEW_CHARS = 2500   # information beyond this continues on Details pages
OVERVIEW_LINES = 40
DESCRIPTION_LIMIT = 4000
FIELD_LIMIT = 1024
KEEP_UPPER = {'SC', 'XP', 'NPC', 'UTC', 'OBS', 'ID', 'II', 'III', 'IV', 'V', 'AM', 'PM', 'DM', 'OK', 'QA', 'NE', 'HP'}
SMALL_WORDS = {'a', 'an', 'and', 'as', 'at', 'by', 'for', 'from', 'in', 'of', 'on', 'or', 'the', 'to', 'with', 'per', 'vs'}
NEED_ICONS = {'energy': '⚡', 'nutrition': '🍲', 'social': '💬', 'comfort': '🛋️', 'morale': '✨'}
COLORS = {'success': 0x57F287, 'failure': 0xED4245, 'cooldown': 0xFEE75C, 'info': 0x5865F2, 'notice': 0x5865F2}
PERFORMED = re.compile(r'TASK (?:COMPLETE|FAILED)|CRAFTING COMPLETE|GATHERING COMPLETE|MINING FAILED|PRODUCTION ORDER COMPLETE')
LEADING_SYMBOLS = re.compile(r'^[^\w(]+')


# ---------------------------------------------------------------- words

def title_case(text):
    """'✅ CRAFTING COMPLETE — Kam' -> '✅ Crafting Complete — Kam'; mixed-case words are kept."""
    words = str(text).split(' ')
    out = []
    for i, word in enumerate(words):
        core = re.sub(r'[^A-Za-z]', '', word)
        if len(core) > 1 and core.isupper() and core not in KEEP_UPPER:
            lowered = word.lower()
            if i and lowered in SMALL_WORDS:
                word = lowered
            else:
                word = re.sub(r'[a-z]', lambda m: m[0].upper(), lowered, count=1)
        out.append(word)
    return ' '.join(out)


def is_header(line):
    """An ALL-CAPS section label such as 'OUTPUT', '📦 KEY RESOURCES' or 'INGREDIENTS · have / need'."""
    text = line.strip().split(' · ')[0].strip()
    if len(line.strip()) > 60 or not re.search(r'[A-Z]{3,}', text):
        return False
    if not text or len(text) > 48 or text.endswith((':', '.')) or re.match(r'^[•\-–+−\d]', text):
        return False
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def header_name(line):
    head, _, tail = line.strip().partition(' · ')
    name = title_case(head).rstrip(':')
    return f'{name} · {tail}' if tail else name


# ---------------------------------------------------------------- change lines

def _signed(value):
    value = value.strip()
    return value.replace('-', '−', 1) if value.startswith('-') else value


def needs_line(text):
    """'comfort -2, energy -2, nutrition -1' -> '⚡ −2 Energy · 🍲 −1 Nutrition · 🛋️ −2 Comfort'."""
    found = dict(re.findall(r'([a-z]+) ([+\-−]\d+)', text.lower()))
    order = ['energy', 'nutrition', 'social', 'comfort', 'morale']
    return ' · '.join(f'{NEED_ICONS[k]} {_signed(found[k])} {k.title()}' for k in order if k in found)


def resources_line(text):
    """'Lumber -2, SC +3, Campfire +1' -> gains first, then what was used."""
    gains, used = [], []
    for name, value in re.findall(r'([^,]+?) ([+\-−]\d+)(?:,|$)', text):
        name = name.strip()
        amount = int(value.replace('−', '-'))
        label = {'SC': '🪙 SC', 'Contribution': '⭐ Contribution'}.get(name, name)
        (gains if amount > 0 else used).append((abs(amount), label))
    # Items first; coins and Contribution after them.
    gains.sort(key=lambda row: row[1].startswith(('🪙', '⭐')))
    parts = [f'**+{n}** {label}' for n, label in gains] + [f'−{n} {label}' for n, label in used]
    return ' · '.join(parts)


SKILL_NAMES = ()


def practice_line(text):
    """'Kam Farming +1.00 (1 XP banked); …' -> '📈 Farming +1 XP' (the citizen's name is dropped)."""
    parts = []
    for chunk in text.split(';'):
        match = re.search(r'^(.*) \+([\d.]+)(?: \((\d+) XP banked\))?\s*$', chunk.strip())
        if not match:
            continue
        who, practice, banked = match.groups()
        skill = next((name for name in sorted(SKILL_NAMES, key=len, reverse=True) if who.endswith(name)), who.split(' ')[-1])
        parts.append(f'{skill} +{banked} XP' if banked and banked != '0' else f'{skill} +{float(practice):.2f}')
    return '📈 ' + ' · '.join(parts) if parts else ''


def settlement_line(text):
    pairs = re.findall(r'([a-z_]+) ([+\-−]\d+)', text)
    return '🏘️ Society ' + ' · '.join(f'{k.replace("_", " ").title()} {_signed(v)}' for k, v in pairs) if pairs else ''


CHANGE_LINES = (('Needs:', needs_line), ('Resources:', resources_line),
                ('Aptitude practice:', practice_line), ('Settlement:', settlement_line))


def change_line(line):
    """Format a wrapper change line, '' to drop it, or None when it is not one."""
    for prefix, fn in CHANGE_LINES:
        if line.startswith(prefix):
            body = line[len(prefix):].strip()
            return '' if body in {'unchanged', ''} else fn(body)
    if line.startswith('Aptitudes:'):
        return '📈 ' + line.split(':', 1)[1].strip()
    return None


# ---------------------------------------------------------------- parsing

def lines_of(content):
    return [line.rstrip() for line in str(content or '').replace('\r', '').split('\n')]


def sections(content):
    """(title, intro lines, [(header, lines)]) with blank lines removed."""
    rows = [x.strip() for x in lines_of(content)]
    rows = [x for x in rows if x]
    notes = [x for x in rows if is_note(x)]
    rows = [x for x in rows if not is_note(x)] or notes
    if not rows:
        return '', [], []
    title, rest = rows[0], rows[1:] + ['🎉 **' + x + '**' for x in notes if x not in rows]
    intro, parts, current = [], [], None
    for line in rest:
        if is_header(line) and current is not None and not current[1]:
            # 'TASK READINESS' then '✅ READY FOR WORK': the second is the answer.
            current[1].append('**' + header_name(line) + '**')
        elif is_header(line):
            current = (header_name(line), [])
            parts.append(current)
        elif current is None:
            intro.append(line)
        else:
            current[1].append(line)
    # A caps line with nothing under it is a status line, not a section.
    merged = []
    for name, body in parts:
        if not body:
            (merged[-1][1] if merged else intro).append(f'**{name}**')
        else:
            merged.append((name, body))
    return title, intro, merged


LABEL = re.compile(r'^((?:[^\w\s`*]+\s)?)([A-Z][\w\' &/()-]{1,26}):\s+(?=\S)')


def is_note(line):
    """Progress notices the command wrapper puts before a reply."""
    return line.startswith(('LEVEL UP:', 'Latest LEVEL UP'))


def bullet(line):
    """Tidy one information line: dash bullets become dots, 'Label: value' gets a bold label."""
    if line.startswith(('- ', '* ')):
        line = '• ' + line[2:]
    prefix = '• ' if line.startswith('• ') else ''
    rest = line[len(prefix):]
    if '`' not in rest.split(':', 1)[0] and '**' not in rest.split(':', 1)[0]:
        rest = LABEL.sub(lambda m: f'{m[1]}**{m[2]}:** ', rest, count=1)
    return prefix + rest


# ---------------------------------------------------------------- shapes

def kind(content):
    text = str(content or '').strip()
    rows = [x for x in lines_of(text) if x.strip()]
    if PERFORMED.search(text[:200]):
        return 'receipt'
    # A one-line action (relax, eat, games…) plus its change lines is a receipt;
    # a longer report that happens to change needs (e.g. Recover) stays a full card.
    body = [x for x in rows if change_line(x.strip()) is None and not is_note(x.strip())]
    changed = any(re.match(r'^(?:Needs: (?!unchanged)|Resources: )', x) for x in rows)
    if changed and len(body) <= 2:
        return 'receipt'
    if len(rows) <= 2 and len(text) <= 320 and not (len(rows) == 2 and is_header(rows[0].strip().split(' — ')[0])):
        return 'notice'
    return 'info'


def notice(m, content, status):
    parts = []
    for line in (x.strip() for x in lines_of(content)):
        formatted = change_line(line) if line else ''
        if line and formatted is None:
            parts.append(line)
        elif formatted:
            parts.append(formatted)
    text = '\n'.join(parts)
    return {'description': text[:DESCRIPTION_LIMIT] or '​', 'color': COLORS.get(status, COLORS['info'])}


def _section(content, name):
    match = re.search(r'(?:^|\n)' + re.escape(name) + r'\n(.*?)(?=\n\s*\n|$)', content, re.S)
    return match[1].strip() if match else ''


ACTION_TITLES = {'relax': 'Relaxed', 'sleep': 'Slept', 'eat': 'Meal', 'games': 'Games', 'walk': 'Walk', 'hobby': 'Hobby practice',
                 'meal': 'Community meal', 'hi': 'Said hi', 'hangout': 'Hung out', 'duo': 'Duo activity', 'mentor': 'Mentored',
                 'farm': 'Farming', 'harvest': 'Harvest', 'forage': 'Forage', 'water': 'Irrigation', 'scan': 'Scan',
                 'mine': 'Mining', 'rare': 'Prospecting', 'research': 'Research', 'cargo': 'Cargo prepared', 'delivery': 'Delivery',
                 'spaceport': 'Spaceport shift', 'explore': 'Expedition', 'survey': 'Survey', 'market': 'Market work',
                 'repair': 'Repair', 'build': 'Build', 'project': 'Project work', 'craft': 'Crafting', 'work': 'Work shift',
                 'machine': 'Machine run', 'business': 'Business shift', 'businesscontract': 'Business contract',
                 'businessinvest': 'Business investment', 'use': 'Item used', 'gearrepair': 'Gear repaired', 'recover': 'Recovered'}
OUTPUT_ITEM = re.compile(r'(?:OUTPUT\s*(?:\|\s*)?•?|Output:)\s*([^×·|\n]+?)\s*×')


def _receipt_title(m, content, command, failed):
    name = re.search(r' completes ([^.]+)\.', content)
    if name:
        label = name[1]
    elif 'CRAFTING COMPLETE' in content or 'PRODUCTION ORDER' in content:
        made = OUTPUT_ITEM.search(content)
        label = ('Crafted ' + made[1].strip()) if made else 'Crafting'
        if 'PRODUCTION ORDER' in content:
            label = 'Production order delivered'
    elif 'GATHERING COMPLETE' in content:
        got = OUTPUT_ITEM.search(content)
        label = ('Gathered ' + got[1].strip()) if got else 'Gathering'
    elif 'MINING FAILED' in content:
        label = 'Mining'
    elif command in ACTION_TITLES:
        label = ACTION_TITLES[command]
    else:
        return ''   # plain one-line trades keep their own sentence instead of a title
    return ('❌ ' + label + ' failed') if failed else ('✅ ' + label)


def receipt(m, content, command, status):
    """A short card for a performed task."""
    rows = [x.strip() for x in lines_of(content) if x.strip()]
    failed = bool(re.search(r'FAILED', content[:160])) or status == 'failure'
    if failed and not _section(content, 'WHY'):
        # Chat-style failures explain themselves in their first sentence.
        opening = re.sub(r'^[^\w]+', '', rows[0] if rows else '').split('. ')[0].split(' | ')[0]
        content = content + '\n\nWHY\n' + opening.rstrip('.') + '.'
    lines, extra = [], []
    changes = {}
    for line in rows:
        formatted = change_line(line)
        if formatted is not None:
            if formatted:
                changes.setdefault(line.split(':', 1)[0], formatted)
    # Items: prefer the measured change line; otherwise the OUTPUT/USED sections.
    items = changes.get('Resources')
    if not items:
        output = [x.lstrip('• ').strip() for x in _section(content, 'OUTPUT').splitlines() if x.strip()]
        used = [x.lstrip('• ').strip() for x in _section(content, 'USED').splitlines() if x.strip() and 'No ingredients' not in x]
        items = ' · '.join([f'**{x}**' for x in output] + [f'−{x}' if not x.startswith(('−', '-')) else x for x in used])
    # A short, story-like first sentence keeps some flavour (relax, games, eat…).
    body_rows = [x for x in rows if change_line(x) is None and not is_note(x)]
    first = body_rows[0] if body_rows else ''
    title = _receipt_title(m, content, command, failed)
    flavour = ''
    if first and not title:
        flavour = first.split(' | ')[0]          # a trade or unlock: its own sentence is the message
    elif first and not PERFORMED.search(first) and not first.startswith(('✅', '❌', '⚙️', '🛠️')):
        sentence = first.split('. ')[0].rstrip('.')
        if len(sentence) <= 90 and not re.search(r'[+−]\d', sentence) and ' completes ' not in sentence:
            flavour = '*' + re.sub(r'^[^\w]+\s*', '', sentence) + '.*'
    if flavour:
        lines.append(flavour)
    if items:
        lines.append(items)
    if changes.get('Needs'):
        lines.append(changes['Needs'])
    practice = changes.get('Aptitude practice') or changes.get('Aptitudes')
    if practice:
        lines.append(practice)
    if failed:
        why = _section(content, 'WHY') or next((x for x in rows[1:] if not x.isupper() and change_line(x) is None and not x.startswith('•')), '')
        why = why.split('🧬 Active life modifiers')[0].split('WHY THIS RESULT')[0].strip()
        if why:
            lines.insert(0, '> ' + why.splitlines()[0][:180])
    recovery = _section(content, '⚠️ RECOVERY NEEDED BEFORE MORE WORK')
    if recovery:
        extra.append('⚠️ ' + ' '.join(recovery.splitlines())[:200])
    for x in m._discord_split_result(content):
        if 'LEVEL UP' in x or x.startswith(('🏆', '🩹', '🔎', '🧳', '📜', '🎉')):
            extra.append('**' + x.strip('* ')[:200] + '**' if 'LEVEL UP' in x or x.startswith('🏆') else x[:200])
    step = _section(content, 'NEXT STEP')
    if step:
        extra.append('💡 ' + re.sub(r'^[^\w`]+\s*', '', step.splitlines()[0])[:200])
    body = lines + list(dict.fromkeys(extra))[:4]
    color = COLORS['failure'] if failed else COLORS['success']
    card = {'description': '\n'.join(body)[:DESCRIPTION_LIMIT] or '​', 'color': color}
    if title:
        card['title'] = title[:256]
    return card


def info(m, content, status, command=''):
    """A full card: title, intro and sections. Returns (embed, overflow pages text)."""
    title, intro, parts = sections(content)
    intro_lines, change_rows = [], []
    for line in intro:
        formatted = change_line(line)
        if formatted is None:
            intro_lines.append(bullet(line))
        elif formatted:
            change_rows.append(formatted)
    fields = []
    for name, body in parts:
        values = []
        for line in body:
            formatted = change_line(line)
            if formatted is None:
                values.append(bullet(line))
            elif formatted:
                change_rows.append(formatted)
        if values:
            fields.append((name, values))
    if change_rows:
        fields.append(('Changes', change_rows))
    title = title_case(title)
    if len(title) > 70:
        # Keep titles short; the rest of a long first line leads the description.
        cut = next((title.index(sep) for sep in (' — ', ': ', '. ', ', ') if sep in title[8:70]), None)
        if cut is not None:
            head, tail = title[:cut], title[cut:].lstrip(' —:.,')
            title, intro_lines = head, [tail] + intro_lines
    embed = {'title': title[:256], 'color': COLORS.get(status, COLORS['info']), 'fields': []}
    overflow = False
    kept, size = [], 0
    for line in intro_lines:
        if len(kept) >= OVERVIEW_LINES or size + len(line) > OVERVIEW_CHARS:
            overflow = True
            break
        kept.append(line)
        size += len(line) + 1
    description = '\n'.join(kept)
    if description:
        embed['description'] = description
    budget = min(EMBED_TOTAL - len(embed['title']), OVERVIEW_CHARS) - len(description)
    lines_left = OVERVIEW_LINES - len(kept)
    if overflow:
        return embed, True
    for name, values in fields:
        chunks, current = [], ''
        for value in values:
            candidate = (current + '\n' + value) if current else value
            if len(candidate) > FIELD_LIMIT:
                if current:
                    chunks.append(current)
                current = value[:FIELD_LIMIT]
            else:
                current = candidate
        if current:
            chunks.append(current)
        for i, chunk in enumerate(chunks):
            label = name if i == 0 else name + ' (cont.)'
            if len(embed['fields']) >= 24 or len(chunk) + len(label) > budget or chunk.count('\n') + 1 > lines_left:
                overflow = True
                break
            embed['fields'].append({'name': label[:256], 'value': chunk, 'inline': False})
            budget -= len(chunk) + len(label)
            lines_left -= chunk.count('\n') + 2
        if overflow:
            break
    return embed, overflow


def card(m, content, command=''):
    """(embed, shape, overflow) for any reply text."""
    content = m.discord_command_copy(content)
    status = m.discord_message_status(content)
    shape = kind(content)
    if shape == 'receipt':
        return receipt(m, content, command, status), shape, len(content) > 900
    if shape == 'notice':
        return notice(m, content, status), shape, False
    embed, overflow = info(m, content, status, command)
    return embed, shape, overflow


def page_text(m, content):
    """Full text for Details pages: bold section titles and tidy change lines."""
    out = []
    for raw in lines_of(m.discord_command_copy(content)):
        line = raw.strip()
        if not line:
            out.append('')
            continue
        formatted = change_line(line)
        if formatted is not None:
            if formatted:
                out.append(formatted)
            continue
        out.append('**' + header_name(line) + '**' if is_header(line) else bullet(line))
    text = '\n'.join(out)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


# ---------------------------------------------------------------- Twitch chat

CHAT_LIMIT = 380


def plain(text):
    return re.sub(r'\*\*|`|(?<!\w)\*|\*(?!\w)|^> ', '', text)


def fit(text, limit=CHAT_LIMIT):
    """StreamElements limits bytes, not characters."""
    data = text.encode()
    if len(data) <= limit:
        return text
    return data[:limit - 3].decode('utf-8', errors='ignore').rstrip(' |·,') + '…'


def chat_fold(text):
    """One chat line: headers fold into their first line, empty pieces and noise disappear."""
    parts, header = [], ''
    for raw in re.split(r'\n| \| ', str(text or '')):
        line = raw.strip()
        if line.startswith('• '):
            line = line[2:].strip()
        if not line:
            continue
        formatted = change_line(line)
        if formatted is not None:
            if formatted:
                parts.append(plain(formatted))
            continue
        if is_header(line) and len(line) <= 32:
            if header:
                parts.append(header)     # a heading with nothing under it is itself the news
            header = line if not parts else header_name(line)
            continue
        parts.append(f'{header}: {line}' if header else line)
        header = ''
    if header:
        parts.append(header)
    return ' | '.join(parts)


def chat_receipt(m, text, command=''):
    card = receipt(m, text, command, m.discord_message_status(text))
    lines = [card.get('title', '')] + [x for x in card['description'].split('\n') if x.strip() and x != '\u200b']
    lines = [plain(x).strip() for x in lines]
    return ' · '.join(x for x in lines if x)


def chat(m, text, command=''):
    text = str(text or '')
    line = chat_receipt(m, text, command) if kind(text) == 'receipt' else chat_fold(text)
    return fit(line)
