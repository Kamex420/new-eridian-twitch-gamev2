"""Discord's newer message layout (Components V2) for every message the game sends.

Game replies are still built as embeds or plain text (presentation, message_layout,
ui). Just before a message leaves for Discord, `respond` (interaction answers),
`edit` (deferred replies) and `new_message` (follow-ups and bot posts) rebuild it
as one container:

* the old colour strip becomes the container's accent colour (plain notices get
  the information colour);
* the title is a heading and the intro follows it; each section sits under a divider;
* in lists, each item's name is bold and its details sit in a quote under it;
  legends, how-to-use lines and trailing notes become small grey subtext;
* list items a screen names in `_items` (see ui.message) get their button beside
  them, as many as Discord's 40-component limit allows; the rest keep their
  buttons in the rows below;
* the footer is subtext, and the remaining buttons and menus come last.

Discord cannot mix the two layouts in one message. A message sent in the new
layout must be edited in it, and a message sent in the old layout keeps it, so
an edit always follows the message it changes. DISCORD_COMPONENTS_V2=false sends
new messages in the old layout again; messages already in the new layout keep it.

Nothing here changes game state; it only rearranges text and keeps every button.
"""
import os
import re

FLAG = 1 << 15            # IS_COMPONENTS_V2
EPHEMERAL = 1 << 6
ROW, TEXT, SEPARATOR, CONTAINER = 1, 10, 14, 17
SECTION = 9               # text with a button beside it
NOTICE = 0x5865F2         # the information colour (presentation.COLORS['notice'])
MAX_COMPONENTS = 40       # every nested component counts
MAX_TEXT = 4000           # across all text displays in one message
ENABLED = os.getenv('DISCORD_COMPONENTS_V2', 'true').strip().lower() not in {'0', 'false', 'no', 'off'}

MARKS = '✅❌🔒🔑'
# A status-led list item, optionally numbered: '✅ Name — …' or '` 3` ❌⭐ **Name** ×5 — …'.
ITEM = re.compile(r'^(?:`[^`]*`\s*)?[' + MARKS + ']')
# The key under a list: '✅ ready · ❌ missing items · 🔒 level, tier or workstation lock'.
LEGEND = re.compile(r'^[' + MARKS + r']\s*[\w ,]+?\s+·\s+[' + MARKS + ']')
# A detail line under an item: '╰ uses 2 Lumber' or '**Uses:** Iron Nails 4/1'.
DETAIL = re.compile(r'^(?:╰\s*|\*\*[^*\n]{1,30}:\*\*\s)')
# A 'Label: value' line after presentation bolded its label.
LABELLED = re.compile(r'^\*\*[^*\n]{1,30}:\*\*')
# How-to-use lines about the controls under the card.
HELP = re.compile(r'(?:menu|button|dropdown)s? below|Browsing spends nothing|^Select \w+ to ', re.I)
BLANK = '\u200b'      # zero-width space: Discord's placeholder for an empty embed field


def is_v2(message):
    """True when a Discord message (or message data) uses the new layout."""
    try:
        return bool(int((message or {}).get('flags') or 0) & FLAG)
    except (TypeError, ValueError, AttributeError):
        return False


# ---------------------------------------------------------------- text

def _plain(line):
    return line.replace('**', '')


def _bold_name(line):
    """'✅ Maintenance & Repair — branch Lv 9' -> '✅ **Maintenance & Repair** — branch Lv 9'."""
    if '**' in line or ' — ' not in line:
        return line
    match = re.match(r'^((?:`[^`]*`\s*)?[' + MARKS + r'][^\w\s]*\s*)(.+?)( — .*)$', line)
    if not match or ':' in match[2] or len(match[2]) > 48:
        return line
    return f'{match[1]}**{match[2]}**{match[3]}'


def _label(line):
    """'Uses' for '**Uses:** …', '╰' for '╰ …', else ''."""
    if line.startswith('╰'):
        return '╰'
    match = DETAIL.match(line)
    return match[0].strip('*: ') if match else ''


def _gap(out):
    if out and out[-1]:
        out.append('')


def block(text):
    """One block of card text, made easy to scan (see the module docstring).

    Only lists (two or more ✅/❌/🔒/🔑 items) are regrouped: each item's name in bold,
    its detail lines in a quote under it, rules before the list and notes after it
    as subtext. Elsewhere only legends and how-to-use lines change.
    """
    lines = [x.strip() for x in str(text or '').replace(BLANK, '').split('\n')]
    items = [i for i, x in enumerate(lines) if ITEM.match(x) and not LEGEND.match(x)]
    first, last = (items[0], items[-1]) if len(items) >= 2 else (-1, -1)
    out, under, seen = [], None, set()
    for i, line in enumerate(lines):
        if not line:
            _gap(out)
            under = None
            continue
        if LEGEND.match(line) or HELP.search(line):
            out.append('-# ' + _plain(line))
            under = None
            continue
        if first < 0:
            out.append(line)
            continue
        if i in items:
            if i == first or (out and out[-1].startswith('-# ')):
                _gap(out)
            out.append(_bold_name(line))
            under = i
            continue
        label = _label(line)
        # Details belong to the item above. After the last item, only labels already
        # used as details (or '╰' lines) are details; anything else is a note.
        if under is not None and label and (under != last or label == '╰' or label in seen):
            if under != last:
                seen.add(label)
            out.append('> ' + _plain(re.sub(r'^╰\s*', '', line)))
            continue
        if under is not None or (i > last and out and not out[-1].startswith('-# ')):
            _gap(out)
        under = None
        notes = (i > last and LABELLED.match(line)) or (i < first and len(line) > 100)
        out.append('-# ' + _plain(line) if notes else line)
    while out and not out[-1]:
        out.pop()
    return '\n'.join(out).strip()


def _parts(data):
    """(text blocks, footer, accent colour, whether it is a full information card)."""
    embeds = [e for e in data.get('embeds') or [] if isinstance(e, dict)]
    parts, footer, accent = [], '', None
    content = str(data.get('content') or '').strip()
    if content:
        parts.append(block(content))
    for e in embeds:
        if accent is None and isinstance(e.get('color'), int):
            accent = e['color']
        head = []
        author = str((e.get('author') or {}).get('name') or '').strip()
        if author:
            head.append('-# ' + author)
        title = str(e.get('title') or '').strip()
        if title:
            head.append('### ' + title)
        description = block(e.get('description') or '')
        if description:
            head.append(description)
        if head:
            parts.append('\n'.join(head))
        for field in e.get('fields') or []:
            name = str(field.get('name') or '').replace(BLANK, '').strip()
            value = block(field.get('value') or '')
            text = '\n'.join(x for x in (f'**{name}**' if name else '', value) if x)
            if text:
                parts.append(text)
        footer = str((e.get('footer') or {}).get('text') or '').strip() or footer
    fields = sum(len(e.get('fields') or []) for e in embeds)
    return [p for p in parts if p.strip()], footer, accent, bool(footer) or fields >= 3


def _rows(data):
    return [r for r in data.get('components') or [] if isinstance(r, dict) and r.get('type') == ROW and r.get('components')]


def private(data):
    """Message data without this module's private keys (_items, _replaces)."""
    return {k: v for k, v in data.items() if not str(k).startswith('_')} if isinstance(data, dict) else data


def _count(children):
    total = 1                                  # the container itself
    for child in children:
        total += 1 + len(child.get('components') or []) + (1 if child.get('accessory') else 0)
    return total


def _plan(parts, items):
    """Each text part split into segments around its list items, or None when an item is not found.

    Segments are dicts: kind 'text', 'item' (gets a button beside it, ranked in order)
    or 'compact' (its line is dropped when buttons sit beside the items; its button
    stays in the rows below). Items with 'match' are found in order in the text; items
    with 'line' are new lines added after the first part.
    """
    plan, want, k, rank = [], [i for i in items if i.get('match')], 0, 0
    for text in parts:
        segs, buf = [], []
        lines = text.split('\n')
        j = 0
        while j < len(lines):
            line = lines[j]
            if k < len(want) and want[k]['match'] in line and not line.startswith(('> ', '-# ')):
                if buf:
                    segs.append({'kind': 'text', 'text': '\n'.join(buf)})
                    buf = []
                body = [line]
                j += 1
                while j < len(lines) and lines[j].startswith('> '):
                    body.append(lines[j])
                    j += 1
                item = want[k]
                k += 1
                if item.get('compact'):
                    segs.append({'kind': 'compact', 'text': '\n'.join(body)})
                else:
                    segs.append({'kind': 'item', 'text': '\n'.join(body), 'item': item, 'rank': rank})
                    rank += 1
                continue
            buf.append(line)
            j += 1
        if buf:
            segs.append({'kind': 'text', 'text': '\n'.join(buf)})
        plan.append(segs)
    if k < len(want):
        return None
    for item in items:
        if item.get('line') and not item.get('match'):
            if not plan:
                plan.append([])
            plan[0].append({'kind': 'item', 'text': item['line'], 'item': item, 'rank': rank})
            rank += 1
    return plan


def _repack(rows, gone):
    """Rows without the controls in `gone`. A run of button rows that lost buttons is packed five to
    a row again; runs that lost nothing and rows with a dropdown keep their place and shape."""
    out, run = [], []

    def flush():
        if any(len(kept) < len(r['components']) for r, kept in run):
            loose = [c for _, kept in run for c in kept]
            out.extend(dict(type=ROW, components=loose[i:i + 5]) for i in range(0, len(loose), 5))
        else:
            out.extend(r for r, _ in run)
        run.clear()
    for r in rows:
        kept = [c for c in r['components'] if c.get('custom_id') not in gone]
        if any(c.get('type') != 2 for c in r['components']):
            flush()
            if kept:
                out.append(dict(r, components=kept))
        else:
            run.append((r, kept))
    flush()
    return out[:5]


def _children(plan, footer, rows, divided, k, replaces):
    """The container's children for `plan` with buttons beside its first k items."""
    total = sum(1 for segs in plan for s in segs if s['kind'] == 'item')
    beside = k > 0
    used, blocks = set(), []
    for segs in plan:
        part = []
        for s in segs:
            if s['kind'] == 'item' and s['rank'] < k:
                button = dict(s['item']['button'])
                used.add(button.get('custom_id'))
                part.append({'type': SECTION, 'components': [{'type': TEXT, 'content': s['text'].strip()}], 'accessory': button})
            elif s['kind'] == 'compact' and beside:
                continue
            elif part and part[-1]['type'] == TEXT:
                part[-1]['content'] += '\n' + s['text']
            else:
                part.append({'type': TEXT, 'content': s['text']})
        for c in part:
            if c['type'] == TEXT:
                c['content'] = re.sub(r'\n{3,}', '\n\n', c['content']).strip()
        part = [c for c in part if c['type'] != TEXT or c['content']]
        if part:
            blocks.append(part)
    children = []
    for part in blocks:
        if children:
            if divided:
                children.append({'type': SEPARATOR, 'divider': True, 'spacing': 1})
            elif children[-1]['type'] == TEXT and part[0]['type'] == TEXT:
                children[-1]['content'] += '\n\n' + part[0]['content']
                part = part[1:]
        children += part
    if footer:
        if children and children[-1]['type'] == TEXT:
            children[-1]['content'] += '\n-# ' + footer
        else:
            children.append({'type': TEXT, 'content': '-# ' + footer})
    if not children:
        children.append({'type': TEXT, 'content': 'Done.'})
    gone = used | (replaces if beside and k >= total else set())
    rows = _repack(rows, gone) if gone else rows
    if rows:
        children.append({'type': SEPARATOR, 'divider': divided or beside, 'spacing': 1})
        children += rows
    return children


def convert(data, force=False):
    """The same message in the new layout, or None when it cannot fit Discord's limits.

    Items the message lists (`_items`, see ui.message) get their button beside them,
    as many as fit; controls they make redundant (`_replaces`) go when all of them fit.
    With force (an edit of a message already in the new layout, which cannot go back),
    long text is shortened and buttons dropped instead of giving up.
    """
    if not isinstance(data, dict):
        return None
    if is_v2(data):
        return private(data)
    parts, footer, accent, info = _parts(data)
    if not parts and not footer:
        if not force:
            return None
        parts = ['Done.']
    rows = _rows(data)
    items = [i for i in data.get('_items') or [] if isinstance(i, dict) and (i.get('match') or i.get('line'))
             and (i.get('compact') or isinstance(i.get('button'), dict))]
    replaces = {str(x) for x in data.get('_replaces') or []}
    plain = [[{'kind': 'text', 'text': p}] for p in parts]
    plan = _plan(parts, items) if items else None
    total = sum(1 for segs in plan or [] for s in segs if s['kind'] == 'item')
    added = any(i.get('line') and not i.get('match') for i in items)
    ks = [total] if added else list(range(total, 0, -1))      # new lines are all or nothing
    splits = (True, False) if info and len(parts) > 1 else (False,)
    attempts = [(plan, divided, k, rows) for k in ks if plan for divided in splits]
    attempts += [(plain, divided, 0, rows) for divided in splits]
    if force:
        attempts.append((plain, False, 0, []))
    children = None
    for chosen, divided, k, keep in attempts:
        candidate = _children(chosen, footer, keep, divided, k, replaces)
        if _count(candidate) <= MAX_COMPONENTS:
            children = candidate
            break
    if children is None:
        return None
    texts = [c for c in children if c['type'] == TEXT] + [t for c in children if c['type'] == SECTION for t in c['components']]
    excess = sum(len(c['content']) for c in texts) - MAX_TEXT
    if excess > 0:
        if not force:
            return None
        for c in sorted(texts, key=lambda c: len(c['content']), reverse=True):
            if excess <= 0:
                break
            if len(c['content']) <= 2:
                continue
            cut = min(excess + 1, len(c['content']) - 1)      # keep at least one character
            c['content'] = c['content'][:len(c['content']) - cut].rstrip() + '…'
            excess -= cut - 1
    container = {'type': CONTAINER, 'components': children}
    if accent is None and not data.get('embeds'):
        accent = NOTICE                         # a plain notice gets the information colour
    if accent is not None:
        container['accent_color'] = max(0, min(0xFFFFFF, accent))
    out = {k: v for k, v in private(data).items() if k not in {'content', 'embeds', 'components', 'flags'}}
    out['components'] = [container]
    out['flags'] = FLAG | (int(data.get('flags') or 0) & EPHEMERAL)
    return out


# ---------------------------------------------------------------- where replies leave for Discord

def respond(response, payload=None):
    """An interaction answer in the layout it needs: type 4 sends a new message, type 7 edits one."""
    if not isinstance(response, dict) or response.get('type') not in (4, 7) or not isinstance(response.get('data'), dict):
        return response
    data = response['data']
    if response['type'] == 7:
        if not is_v2((payload or {}).get('message')):
            return dict(response, data=private(data))       # a message in the old layout keeps it
        new = convert(data, force=True)
        new['flags'] = FLAG                     # an edit cannot change who sees the message
        return dict(response, data=new)
    return dict(response, data=new_message(data))


def new_message(data):
    """A new message: in the new layout when it is on (one-line notices too), else as it was."""
    if not isinstance(data, dict):
        return data
    if not ENABLED or not (data.get('embeds') or str(data.get('content') or '').strip()):
        return private(data)
    return convert(data) or private(data)


def edit(data, payload=None):
    """A deferred reply's edit in the new layout, or None to send it in the old one.

    A button's message keeps its layout. The reply that replaces "thinking…" after a
    slash command is new, so it uses the new layout when it is on.
    """
    if not isinstance(data, dict):
        return None
    message = (payload or {}).get('message')
    if message is not None:
        if not is_v2(message):
            return None
        new = convert(data, force=True)
    else:
        new = new_message(data)
        if not is_v2(new):
            return None
    new = dict(new)
    new['flags'] = FLAG                         # Discord needs the flag on the edit itself
    return new


def with_line(data, line):
    """A new-layout message with `line` (a ping, a note) as its first line."""
    for c in data.get('components') or []:
        if c.get('type') == CONTAINER:
            kids = c['components']
            if kids and kids[0].get('type') == TEXT:
                kids[0] = dict(kids[0], content=line + '\n' + kids[0]['content'])
            else:
                kids.insert(0, {'type': TEXT, 'content': line})
            break
    return data


def card(blocks, accent=NOTICE, rows=(), flags=0):
    """A new-layout message from text blocks (one per section, divided) and optional button rows."""
    children = []
    for text in [b for b in blocks if str(b).strip()]:
        if children:
            children.append({'type': SEPARATOR, 'divider': True, 'spacing': 1})
        children.append({'type': TEXT, 'content': str(text).strip()})
    rows = [r for r in rows if r and r.get('components')]
    if rows:
        children.append({'type': SEPARATOR, 'divider': True, 'spacing': 1})
        children += rows
    container = {'type': CONTAINER, 'components': children or [{'type': TEXT, 'content': 'Done.'}]}
    if accent is not None:
        container['accent_color'] = accent
    return {'components': [container], 'flags': FLAG | flags}


def locked(payload=None):
    """True when the message being edited is already in the new layout (it cannot go back)."""
    return is_v2((payload or {}).get('message'))


def without_buttons(data):
    """The same new-layout message with its buttons and menus removed (item buttons too)."""
    out = dict(data)
    tops = []
    for c in data.get('components') or []:
        if c.get('type') == CONTAINER:
            kept = []
            for x in c.get('components') or []:
                if x.get('type') == ROW:
                    continue
                if x.get('type') == SECTION:        # an item: keep its text, drop its button
                    x = dict(x['components'][0])
                if x.get('type') == TEXT and kept and kept[-1].get('type') == TEXT:
                    kept[-1] = dict(kept[-1], content=kept[-1]['content'] + '\n' + x['content'])
                    continue
                kept.append(x)
            while kept and kept[-1].get('type') == SEPARATOR:
                kept.pop()
            c = dict(c, components=kept)
        if c.get('type') != ROW:
            tops.append(c)
    out['components'] = tops
    return out


def text_of(data):
    """Every piece of text in a message, in either layout (for logs and tests)."""
    if not isinstance(data, dict):
        return ''
    out = [str(data.get('content') or '')]
    for e in data.get('embeds') or []:
        out += [str(e.get(k) or '') for k in ('title', 'description')]
        out += [str(f.get('name', '')) + '\n' + str(f.get('value', '')) for f in e.get('fields') or []]
        out.append(str((e.get('footer') or {}).get('text') or ''))

    def walk(components):
        for c in components or []:
            if c.get('type') == TEXT:
                out.append(str(c.get('content') or ''))
            walk(c.get('components'))
    walk(data.get('components'))
    return '\n'.join(x for x in out if x)


def controls(data):
    """Every button and menu in a message, in either layout (rows, items and nested rows)."""
    found = []

    def walk(components):
        for c in components or []:
            if c.get('type') in (2, 3, 5, 6, 7, 8):
                found.append(c)
            if isinstance(c.get('accessory'), dict) and c['accessory'].get('type') == 2:
                found.append(c['accessory'])
            walk(c.get('components'))
    walk((data or {}).get('components'))
    return found
