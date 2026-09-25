"""Compact Discord cards with durable, read-only detail pages.

Pages are snapshots, not commands. Opening one never repeats a reward or starts
work. Random capability IDs are only exposed on the corresponding message;
private messages therefore keep their detail buttons private too.
"""
import copy
import json
import re
import secrets
from datetime import timedelta
from sqlalchemy import Column, String, Text, DateTime, delete
from .db import Base


class MessagePages(Base):
    __tablename__ = 'message_pages_v1'
    id = Column(String(32), primary_key=True)
    pages = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


def chunks(text, limit=850):
    """Bound screen height as well as characters, without dropping any text."""
    current = ''
    for line in text.splitlines():
        while len(line) > limit:
            if current:
                yield current
                current = ''
            yield line[:limit]
            line = line[limit:]
        if current and (len(current) + len(line) + 1 > limit or current.count('\n') >= 11):
            yield current
            current = ''
        current += ('\n' if current else '') + line
    if current:
        yield current


def preview(text, limit):
    part = next(chunks(text, limit - 1), '')
    return part + ('…' if len(part) < len(text) else '')


def clean_name(name):
    return re.sub(r'^[^\w]+', '', name).capitalize()


def queue_card(content):
    lines = content.splitlines()
    card = {'title': 'Queue · ' + lines[0].split('—')[-1].strip().title(),
            'description': lines[1], 'color': 0x5865F2, 'fields': []}
    def field(name, value):
        card['fields'].append({'name': name, 'value': value, 'inline': False})
    completed = re.search(r'Attempts completed: (\d+/\d+); remaining: (\d+)', content)
    results = next((x for x in lines if x.startswith('Succeeded:')), '')
    if completed:
        field('Progress', f'{completed[1]} attempts · {completed[2]} remaining\n' + results.replace('; ', ' · '))
    for heading, label in [('TOTAL ITEMS GAINED', 'Gained'), ('TOTAL ITEMS USED', 'Used')]:
        if heading in lines:
            value = lines[lines.index(heading) + 1]
            if value != 'None':
                field(label, value)
    if 'PAUSE REASON' in lines:
        reason = content.split('PAUSE REASON\n', 1)[1].split('\n\n', 1)[0]
        field('Paused · action needed', reason)
        card['color'] = 0xFEE75C
    forecast = re.search(r'To finish without recovery, start with at least (\d+) Energy, (\d+) Nutrition and (\d+) Social', content)
    current = re.search(r'Current needs: Energy (\d+)/100; Nutrition (\d+)/100; Social (\d+)/100', content)
    if forecast and current:
        field('Needs · current / needed to finish', ' · '.join(f'{label} {have}/{need}' for label, have, need in zip(('Energy', 'Nutrition', 'Social'), current.groups(), forecast.groups())))
    missing = [x for x in lines if re.search(r'missing [1-9]', x)]
    if missing:
        field('Materials needed', '\n'.join(missing))
    if forecast:
        field('Controls', 'Auto checks every 10s; task cooldowns apply.\nOne task, up to 10 attempts · /queue to cancel.')
    card['fields'].sort(key=lambda f: 0 if f['name'].startswith('Paused') else 1 if f['name'] == 'Materials needed' else 2)
    return card


def render(m, embed, content):
    """Use a small overview and preserve the complete response behind Details."""
    source = queue_card(content) if content.startswith('TASK QUEUE —') else copy.deepcopy(embed)
    source['title'] = re.sub(r'^[🟩🟥🟨🟦🟪]\s*', '', source['title'])
    source['footer'] = {'text': 'New Eridian'}
    description = source.get('description', '')
    source['description'] = preview(description, 320)
    fields = source.get('fields', [])
    # Blockers and actual changes precede flavor and calculation explanations.
    priority = ('paused', 'failed', 'needed', 'progress', 'gained', 'output', 'reward', 'used', 'needs', 'need changes', 'cost')
    if not content.startswith('TASK QUEUE —'):
        fields.sort(key=lambda f: next((i for i, word in enumerate(priority) if word in f['name'].lower()), len(priority)))
    kept = []
    budget = 850 - len(source['description'])
    for field in fields:
        value = field['value']
        if value.strip('• \n').lower() == 'none':
            continue
        if len(kept) >= 5 or budget < 80:
            break
        value = preview(value, min(280, budget))
        kept.append({'name': clean_name(field['name']), 'value': value, 'inline': False})
        budget -= len(value)
    source['fields'] = kept
    # Short replies need no navigation. Longer replies retain every original line.
    if len(content) <= 650 and len(content.splitlines()) <= 12:
        if len(description) <= 320 and len(fields) <= 5 and all(len(f['value']) <= 280 for f in fields):
            return {'embeds': [source], 'allowed_mentions': {'parse': []}}
    pages = [source]
    for part in chunks(content):
        pages.append({'title': source['title'][:230] + ' · Details', 'description': part,
                      'color': source['color'], 'footer': {'text': 'New Eridian'}})
    token = secrets.token_hex(16)
    with m.SessionLocal() as db:
        db.execute(delete(MessagePages).where(MessagePages.expires_at < m.now()))
        db.add(MessagePages(id=token, pages=json.dumps(pages), expires_at=m.now() + timedelta(hours=24)))
        db.commit()
    return page_data(token, pages, 0)


def page_data(token, pages, index):
    embed = copy.deepcopy(pages[index])
    embed['footer'] = {'text': f'New Eridian · {"Overview" if index == 0 else "Details " + str(index) + "/" + str(len(pages)-1)}'}
    buttons = []
    if index:
        buttons.append({'type': 2, 'style': 2, 'label': 'Overview', 'custom_id': f'page:{token}:0'})
    if index > 1:
        buttons.append({'type': 2, 'style': 2, 'label': 'Previous', 'custom_id': f'page:{token}:{index-1}'})
    if index < len(pages) - 1:
        buttons.append({'type': 2, 'style': 1, 'label': 'Details' if index == 0 else 'Next', 'custom_id': f'page:{token}:{index+1}'})
    return {'embeds': [embed], 'components': [{'type': 1, 'components': buttons}], 'allowed_mentions': {'parse': []}}


def open_page(m, payload):
    match = re.fullmatch(r'page:([a-f0-9]{32}):(\d{1,5})', str((payload.get('data') or {}).get('custom_id', '')))
    if match:
        with m.SessionLocal() as db:
            row = db.get(MessagePages, match[1])
            if row and m.as_utc(row.expires_at) > m.now():
                pages = json.loads(row.pages)
                index = int(match[2])
                if index < len(pages):
                    data = page_data(match[1], pages, index)
                    # Always private: browsing never changes a shared channel card.
                    if int((payload.get('message') or {}).get('flags', 0)) & 64:
                        return {'type': 7, 'data': data}
                    data['flags'] = 64
                    return {'type': 4, 'data': data}
    return {'type': 4, 'data': {'content': 'This view has expired. Run the command again for current information.', 'flags': 64}}
