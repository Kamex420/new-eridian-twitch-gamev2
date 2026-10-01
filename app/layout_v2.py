"""Discord's newer message layout (Components V2) for replies.

Game replies are still built as embeds (presentation, message_layout, ui). Just
before a reply leaves for Discord, `respond` (interaction answers), `edit`
(deferred replies) and `new_message` (private follow-ups) rebuild it as one
container:

* the old colour strip becomes the container's accent colour;
* the title is a heading and the intro follows it; each section sits under a divider;
* in lists, each item's name is bold and its details sit in a quote under it;
  legends, how-to-use lines and trailing notes become small grey subtext;
* the footer is subtext, and the buttons and menus come last.

Discord cannot mix the two layouts in one message. A message sent in the new
layout must be edited in it, and a message sent in the old layout keeps it, so
an edit always follows the message it changes. DISCORD_COMPONENTS_V2=false sends
new replies in the old layout again; replies already in the new layout keep it.

Nothing here changes game state; it only rearranges text and keeps every button.
"""
import os
import re

FLAG = 1 << 15            # IS_COMPONENTS_V2
EPHEMERAL = 1 << 6
ROW, TEXT, SEPARATOR, CONTAINER = 1, 10, 14, 17
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
    return [p for p in parts if p.strip()], footer, accent, bool(footer)


def _rows(data):
    return [r for r in data.get('components') or [] if isinstance(r, dict) and r.get('type') == ROW and r.get('components')]


def _count(children):
    total = 1                                  # the container itself
    for child in children:
        total += 1 + (len(child.get('components') or []) if child.get('type') == ROW else 0)
    return total


def _layout(parts, footer, rows, divided):
    """The container's children: text blocks (with dividers on full cards), then buttons."""
    if footer:
        parts = parts[:-1] + [parts[-1] + '\n-# ' + footer] if parts else ['-# ' + footer]
    children = []
    for i, text in enumerate(parts if divided else ['\n\n'.join(parts)]):
        if i:
            children.append({'type': SEPARATOR, 'divider': True, 'spacing': 1})
        children.append({'type': TEXT, 'content': text})
    if rows:
        children.append({'type': SEPARATOR, 'divider': divided, 'spacing': 1})
        children += rows
    return children


def convert(data, force=False):
    """The same message in the new layout, or None when it cannot fit Discord's limits.

    With force (an edit of a message already in the new layout, which cannot go back),
    long text is shortened and buttons dropped instead of giving up.
    """
    if not isinstance(data, dict):
        return None
    if is_v2(data):
        return data
    parts, footer, accent, info = _parts(data)
    if not parts and not footer:
        if not force:
            return None
        parts = ['Done.']
    rows = _rows(data)
    children = None
    for divided, keep_rows in ((info and len(parts) > 1, True), (False, True), (False, False)):
        if not keep_rows and not force:
            break
        candidate = _layout(parts, footer, rows if keep_rows else [], divided)
        if _count(candidate) <= MAX_COMPONENTS:
            children = candidate
            break
    if children is None:
        return None
    texts = [c for c in children if c['type'] == TEXT]
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
    if accent is not None:
        container['accent_color'] = max(0, min(0xFFFFFF, accent))
    out = {k: v for k, v in data.items() if k not in {'content', 'embeds', 'components', 'flags'}}
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
            return response                     # a message in the old layout keeps it
        new = convert(data, force=True)
        new['flags'] = FLAG                     # an edit cannot change who sees the message
        return dict(response, data=new)
    new = new_message(data)
    return response if new is data else dict(response, data=new)


def new_message(data):
    """A new message in the new layout when it is on. Plain one-line notices stay plain text."""
    if not ENABLED or not isinstance(data, dict) or not data.get('embeds'):
        return data
    return convert(data) or data


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
        if new is data:
            return None
    new = dict(new)
    new['flags'] = FLAG                         # Discord needs the flag on the edit itself
    return new


def locked(payload=None):
    """True when the message being edited is already in the new layout (it cannot go back)."""
    return is_v2((payload or {}).get('message'))


def without_buttons(data):
    """The same new-layout message with its buttons and menus removed."""
    out = dict(data)
    containers = []
    for c in data.get('components') or []:
        if c.get('type') == CONTAINER:
            kept = [x for x in c.get('components') or [] if x.get('type') != ROW]
            while kept and kept[-1].get('type') == SEPARATOR:
                kept.pop()
            c = dict(c, components=kept)
        if c.get('type') != ROW:
            containers.append(c)
    out['components'] = containers
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
