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

from .notice import FOOTER                     # "… · a fan project by Kamex • …"

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
    state=lines[0].split('—')[-1].strip().title().replace('Error','Stopped')
    icon={'Running':'▶️','Paused':'⏸️','Completed':'✅','Cancelled':'⏹️','Stopped':'⛔'}.get(state,'⏱️')
    card = {'title': f'{icon} Queue {state.lower()}',
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
    if state=='Completed':card['color']=0x57F287
    if state in {'Stopped','Cancelled'}:card['color']=0xED4245
    delivery=next((x for x in lines if 'notification could not be delivered' in x),'')
    if delivery:field('Alert delivery',delivery)
    if 'RETRY STATUS' in lines:field('Retrying',lines[lines.index('RETRY STATUS')+1])
    if 'PAUSE REASON' in lines:
        reason = content.split('PAUSE REASON\n', 1)[1].split('\nNEXT\n', 1)[0].split('\n\nFor ',1)[0]
        if 'WHY\n' in reason:reason=reason.split('WHY\n',1)[1].split('\n\n',1)[0]
        reason=reason.strip()
        field('Result' if state=='Cancelled' else 'Action needed' if state=='Stopped' else 'Paused · action needed', reason)
        if state=='Paused':card['color'] = 0xFEE75C
    forecast = re.search(r'To finish without recovery, start with at least (\d+) Energy, (\d+) Nutrition(?:,| and) (\d+) Social(?: and (\d+) Comfort)?', content)
    current = re.search(r'Current needs: Energy (\d+)/100; Nutrition (\d+)/100; Social (\d+)/100(?:; Comfort (\d+)/100)?', content)
    if forecast and current:
        pairs = zip(('Energy', 'Nutrition', 'Social', 'Comfort'), current.groups(), forecast.groups())
        field('Needs · current / needed to finish', ' · '.join(f'{label} {have}/{need}' for label, have, need in pairs if have is not None and need is not None))
    missing = [x for x in lines if re.search(r'missing [1-9]', x)]
    if missing:
        field('Materials needed', '\n'.join(missing))
    if 'NEXT' in lines:
        field('Next',content.split('\nNEXT\n',1)[-1])
    card['fields'].sort(key=lambda f: 0 if f['name'].startswith('Paused') else 1 if f['name'] == 'Materials needed' else 2)
    return card


def action_card(m, embed, content, command):
    """Action receipts contain changes and immediate blockers, not handbook text."""
    if 'MENU' in content.splitlines()[0] or content.startswith('TASK QUEUE'):return None
    performed=bool(re.search(r'TASK (?:COMPLETE|FAILED)|CRAFTING COMPLETE|GATHERING COMPLETE|MINING FAILED',content))
    performed=performed or bool(re.search(r'^Needs: (?!unchanged)',content,re.M))
    if not performed:return None
    failed='FAILED' in content[:120]
    title=m._discord_action_name(command) if command not in {'make','gather'} else ('Crafting' if command=='make' else 'Gathering')
    title=re.sub(r'^[^\w]+','',title).title().replace(' Shift','')
    performed_name=re.search(r' completes ([^.]+)\.',content)
    if performed_name:title=performed_name[1]
    card={'title':title+' · '+('Failed' if failed else 'Complete'),'color':0xED4245 if failed else 0x57F287,'fields':[]}
    def add(name,value):
        if value:card['fields'].append({'name':name,'value':value,'inline':False})
    resource=re.search(r'^Resources: (.+)$',content,re.M)
    needs=re.search(r'^Needs: (?!unchanged)(.+)$',content,re.M)
    practice=re.search(r'^Aptitude practice: (.+)$',content,re.M)
    def section(name):
        match=re.search(r'(?:^|\n)'+name+r'\n(.*?)(?=\n\n|$)',content,re.S)
        return match[1].strip() if match else ''
    if resource:
        add('Items & currency',resource[1])
    else:
        add('Gained',section('OUTPUT'))
        add('Used',section('USED'))
        change=section('CHANGE')
        if change:add('Changes',change)
    add('Needs',needs[1] if needs else next((x for x in content.splitlines() if re.match(r'^[−-]\d+ Energy',x)),''))
    add('Practice',practice[1] if practice else section('PRACTICE'))
    if failed:
        # Keep the actual failure, injuries and byproducts, not generic retry rules.
        reason=section('WHY') or next((x for x in content.splitlines()[1:] if x.strip() and x not in {'OUTPUT','PRACTICE'}),'')
        reason=reason.split('🧬 Active life modifiers')[0].split('WHY THIS RESULT')[0]
        add('Result',reason)
    recovery=section('⚠️ RECOVERY NEEDED BEFORE MORE WORK')
    if recovery:add('Recovery needed',recovery)
    milestones=[x for x in m._discord_split_result(content) if 'LEVEL UP' in x or x.startswith(('🩹','🔎','🧳','📜','🏆')) or re.search(r'\b(unlocked|completed|started|ended)\b',x,re.I)]
    add('New this action','\n'.join(milestones))
    add('Next step',section('NEXT STEP'))
    card['fields'].sort(key=lambda f:0 if f['name'] in {'Result','Recovery needed'} else 1)
    if not card['fields']:return None
    # Reward/cost receipts keep exact deltas; permanent bonuses and general rules
    # remain in inventory, /me, /guide and recipe previews.
    detail=card['title']+'\n\n'+'\n\n'.join(f['name']+'\n'+f['value'] for f in card['fields'])
    return card,detail


def render(m, embed, content, command=""):
    """Receipts and notices stay small; information shows in full, then Details pages."""
    from . import presentation
    if content.startswith('TASK QUEUE —'):
        return _render_queue(m, content)
    source, shape, overflow = presentation.card(m, content, command)
    if shape == 'info':
        source['footer'] = {'text': FOOTER}
    if not overflow:
        return {'embeds': [source], 'allowed_mentions': {'parse': []}}
    title = source.get('title') or 'New Eridian'
    pages = [source] + [{'title': title[:230] + ' · Details', 'description': part, 'color': source['color'], 'footer': {'text': FOOTER}}
                        for part in chunks(presentation.page_text(m, content))]
    return _store(m, pages)


def _render_queue(m, content):
    source = queue_card(content)
    source['footer'] = {'text': FOOTER}
    if len(content) <= 650 and len(content.splitlines()) <= 12:
        return {'embeds': [source], 'allowed_mentions': {'parse': []}}
    pages = [source]
    for part in chunks(content):
        pages.append({'title': source['title'][:230] + ' · Details', 'description': part,
                      'color': source['color'], 'footer': {'text': FOOTER}})
    return _store(m, pages)


def _store(m, pages):
    token = secrets.token_hex(16)
    with m.SessionLocal() as db:
        db.execute(delete(MessagePages).where(MessagePages.expires_at < m.now()))
        db.add(MessagePages(id=token, pages=json.dumps(pages), expires_at=m.now() + timedelta(hours=24)))
        db.commit()
    return page_data(token, pages, 0)


def page_data(token, pages, index):
    embed = copy.deepcopy(pages[index])
    embed['footer'] = {'text': FOOTER}
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
