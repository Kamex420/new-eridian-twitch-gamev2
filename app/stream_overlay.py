"""Stream overlay: the highlights feed, the overlay extras and every OBS page except the older single panels.

The game records notable moments in a small public feed (`stream_highlights_v1`):
a new citizen, a level up, an achievement or trophy, a finished queue, an event,
stream challenge, colony vote or season, a society tier or project milestone.
`/api/v1/overlay` includes the feed and a few summaries; the OBS panels below poll it.

  /obs/hub       one rotating panel with every slide (society, event, challenge, vote, season, news, how to join...)
  /obs/map       the Avesta map: New Eridian as a low-poly diorama where Seedlings walk, talk and the town grows
  /obs/ticker    a TV-style news crawl along the bottom of the stream
  /obs/alerts    animated pop-up for each new highlight (transparent when idle)
  /obs/challenge the live stream challenge as a goal bar (transparent when none is running)
  /obs/leaders   top contributors and today's most active citizens
  /obs/working   citizens with queues running right now, with progress
  /obs/join      how to play from chat, rotating tips (and a Discord invite)
  /obs/narrator  New Eridian News: a typed report for each Seedling step
  /obs           setup page: every panel with its URL, size, options and a live preview

Only public information appears: names, actions and society numbers that the
activity feed already shows. Nothing from a citizen's inventory is exposed.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, Integer, String, DateTime, select, delete, func
from .db import Base

KEEP = 120                      # highlights kept per world
PANELS = {'alerts', 'ticker', 'leaders', 'working', 'join', 'map', 'narrator', 'hub', 'challenge'}
EMOJI = {'join': '🌱', 'level': '⬆️', 'achievement': '🏆', 'queue': '✅', 'event_start': '🚨', 'event_win': '🎉',
         'event_fail': '⌛', 'event_cancel': '🛑', 'tier': '🏛️', 'project': '🏗️', 'story': '📖', 'directive': '📋',
         'trophy': '🏅', 'challenge_start': '⚡', 'challenge_win': '🎉', 'challenge_fail': '⌛', 'vote': '🗳️', 'season': '🏁'}


class StreamHighlight(Base):
    __tablename__ = 'stream_highlights_v1'
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String(64), nullable=False, index=True)
    kind = Column(String(24), nullable=False)
    emoji = Column(String(16), nullable=False, default='✨')
    title = Column(String(160), nullable=False)
    detail = Column(String(240), nullable=False, default='')
    name = Column(String(64), nullable=False, default='')
    created_at = Column(DateTime(timezone=True), nullable=False)


class StreamState(Base):
    """What the overlay saw last, so society milestones are announced once."""
    __tablename__ = 'stream_state_v1'
    channel_id = Column(String(64), primary_key=True)
    tier = Column(String(40), nullable=False, default='')
    project = Column(String(80), nullable=False, default='')
    story = Column(String(80), nullable=False, default='')
    directive = Column(String(80), nullable=False, default='')


def install(m):
    StreamHighlight.__table__.create(m.engine, checkfirst=True)
    StreamState.__table__.create(m.engine, checkfirst=True)


def _now():
    return datetime.now(timezone.utc)


def highlight(db, channel, kind, title, detail='', name='', emoji=''):
    """Record a public moment for the stream. Never raises: gameplay must not depend on it."""
    try:
        with db.begin_nested():
            db.add(StreamHighlight(channel_id=str(channel), kind=kind, emoji=emoji or EMOJI.get(kind, '✨'), title=title[:160],
                                   detail=(detail or '')[:240], name=(name or '')[:64], created_at=_now()))
            db.flush()
            old = list(db.scalars(select(StreamHighlight.id).where(StreamHighlight.channel_id == str(channel))
                                  .order_by(StreamHighlight.id.desc()).offset(KEEP)))
            if old:
                db.execute(delete(StreamHighlight).where(StreamHighlight.id.in_(old)))
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Stream highlight not recorded: %s', kind)


def from_announcement(db, p, message):
    """Level ups and finished queues arrive through progression.announce."""
    text = str(message or '')
    if text.startswith('LEVEL UP'):
        body = text.split(':', 1)[-1].strip()
        body = body.split('—', 1)[-1].strip() if '—' in body else body
        highlight(db, p.channel_id, 'level', f'{p.display_name} levelled up', body, p.display_name)


def queue_finished(m, db, p, queue):
    label = m.task_queue.choices(m).get(queue.task, queue.task.split(':')[-1])
    highlight(db, p.channel_id, 'queue', f'{p.display_name} finished a queue', f'{label} ×{queue.total}', p.display_name)


# ---------------------------------------------------------------- society milestones (seen by the overlay)

def watch(m, db, channel, tier, project, story, directive):
    state = db.get(StreamState, channel)
    if state is None:
        db.add(StreamState(channel_id=channel, tier=tier, project=project.get('key', '') if project.get('completed') else '',
                           story=story.get('key', '') if story.get('resolved') else '',
                           directive=directive.get('key', '') if directive.get('complete') else ''))
        return
    if tier and state.tier and tier != state.tier:
        highlight(db, channel, 'tier', f'New Eridian is now a {tier}!', 'The whole society levelled up. Tier bonuses apply to every success.')
    state.tier = tier or state.tier
    key = project.get('key', '')
    if project.get('completed') and state.project != key:
        highlight(db, channel, 'project', f"Project complete: {project.get('name', 'Society project')}",
                  f"{project.get('goal', 0)} contributions from the community.")
        state.project = key
    key = story.get('key', '')
    if story.get('resolved') and state.story != key:
        highlight(db, channel, 'story', f"Story resolved: {story.get('name', 'Weekly story')}", str(story.get('outcome') or '')[:200])
        state.story = key
    key = f"{directive.get('key', '')}:{directive.get('goal', 0)}"
    if directive.get('complete') and state.directive != key:
        highlight(db, channel, 'directive', f"Daily directive done: {directive.get('name', '')}", str(directive.get('reward') or ''))
        state.directive = key


# ---------------------------------------------------------------- data for /api/v1/overlay

def extra(m, db, source_ids, world):
    since = _now() - timedelta(hours=24)
    rows = list(db.scalars(select(StreamHighlight).where(StreamHighlight.channel_id.in_(source_ids))
                           .order_by(StreamHighlight.id.desc()).limit(20)))
    highlights = [{'id': r.id, 'kind': r.kind, 'emoji': r.emoji, 'title': r.title, 'detail': r.detail, 'name': r.name,
                   'at': m.as_utc(r.created_at).isoformat()} for r in rows]

    players = list(db.scalars(select(m.Player).where(m.Player.channel_id.in_(source_ids)).order_by(m.Player.contribution.desc()).limit(5)))
    names = {}
    counts = db.execute(select(m.ActionLog.canonical_uid, func.count()).where(m.ActionLog.channel_id.in_(source_ids),
                                                                             m.ActionLog.created_at >= since)
                        .group_by(m.ActionLog.canonical_uid).order_by(func.count().desc()).limit(5)).all()
    if counts:
        for p in db.scalars(select(m.Player).where(m.Player.channel_id.in_(source_ids), m.Player.twitch_uid.in_([u for u, _ in counts]))):
            names.setdefault(p.twitch_uid, p.display_name)
    from .autonomy import clean_name
    leaders = {'contributors': [{'name': clean_name(p.display_name), 'contribution': p.contribution} for p in players if p.contribution > 0],
               'active_today': [{'name': clean_name(names.get(u, 'Citizen')), 'actions': n} for u, n in counts]}

    tq = m.task_queue
    queues = list(db.scalars(select(tq.TaskQueue).where(tq.TaskQueue.channel_id.in_(source_ids), tq.TaskQueue.state.in_(tuple(tq.ACTIVE)))
                             .order_by(tq.TaskQueue.next_at).limit(8)))
    who = {}
    if queues:
        for p in db.scalars(select(m.Player).where(m.Player.channel_id.in_(source_ids), m.Player.twitch_uid.in_([q.canonical_uid for q in queues]))):
            who.setdefault(p.twitch_uid, p.display_name)
    choices = tq.choices(m)
    working = [{'name': clean_name(who.get(q.canonical_uid, 'Citizen')), 'task': choices.get(q.task, q.task.split(':')[-1]), 'done': q.total - q.remaining,
                'total': q.total, 'state': q.state} for q in queues]

    from . import seasonal
    festival = None
    active = seasonal.holidays_active_for(_now().date())
    if active:
        f = active[0]
        festival = {'name': f['name'], 'emoji': f['emoji'], 'days_left': (f['end'] - _now().date()).days,
                    'days_to_holiday': f['days_until_holiday'],
                    'foods': [food[0] for food in seasonal.FESTIVAL_FOODS.get(f['name'], [])]}

    join = {'discord': os.getenv('DISCORD_INVITE_URL', '').strip(),
            'tips': [['!start', 'Create your citizen and join New Eridian'], ['!relax', '+25 Energy, +20 Comfort'],
                     ['!gather lumber', 'Collect materials'], ['!make campfire', 'Craft at the Workbench'],
                     ['!craftmax lumber', 'Queue up to 10 gathers and watch them run'], ['!status', 'Needs, queue and your next step'],
                     ['!find <word>', 'Search recipes, items and help'], ['!target <recipe>', 'Pin a goal and track it'],
                     ['!shopping add <recipe>', 'Plan several recipes together: what is missing, buy it all'],
                     ['!keep <item> <n>', 'Selling always leaves you that many'],
                     ['!again', 'Repeat your last action'], ['!seed', 'Every command, by topic']],
            'queue': ['!craftmax lumber', 'to work while you watch']}   # the working panel's hint when no queue runs
    from . import twitch_lite
    if twitch_lite.ENABLED:
        join['tips'], join['queue'] = twitch_lite.join_tips(), ['/queue', 'on Discord to run up to 10 tasks while you watch']
    from . import autonomy
    return {'highlights': highlights, 'leaders': leaders, 'working': working, 'festival': festival, 'join': join,
            **autonomy.overlay_data(m, db, source_ids)}


# ---------------------------------------------------------------- OBS pages

# ---------------------------------------------------------------- one look for every overlay
# Every OBS page shares these fonts and design tokens: Fredoka for headings, Inter for text,
# one set of colours, corner radii, shadows and motion timing.
FONTS_LINK = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
              '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fredoka:wght@500;600;700&family=Inter:wght@500;600;700;800;900&display=swap">')
THEME_CSS = r"""
:root{--font-display:'Fredoka',ui-rounded,'Segoe UI Rounded','Segoe UI',system-ui,sans-serif;--font-body:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif;
  --text:#fffaf0;--muted:#aca9c9;--ivory:#fff8e8;--green:#7ee3b0;--green2:#b8f4d0;--violet:#bd91ff;--cyan:#70ddff;--amber:#ffd27a;--danger:#ff7484;--pink:#ff9ad5;
  --panel:linear-gradient(145deg,rgba(10,14,40,.96),rgba(26,17,56,.94));--edge:rgba(147,154,255,.42);--edge-soft:rgba(255,255,255,.09);
  --radius:16px;--radius-sm:10px;--shadow:0 10px 30px rgba(0,0,0,.42);
  --ease:cubic-bezier(.22,.9,.24,1);--ease-pop:cubic-bezier(.2,1.35,.4,1);--dur:.5s}
body{font-family:var(--font-body)}h1,h2,.display{font-family:var(--font-display);font-weight:600;letter-spacing:.005em}
@keyframes ne-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}@keyframes ne-out{to{opacity:0;transform:translateY(-8px)}}
@keyframes ne-slide-in{from{opacity:0;transform:translateX(5%)}to{opacity:1;transform:none}}@keyframes ne-slide-out{to{opacity:0;transform:translateX(-5%)}}
"""
SERIF = 'Georgia'   # the old heading font, swapped for the display font in older pages
FONT_SWAPS = [(SERIF + ',"Times New Roman",serif', 'var(--font-display)'), (SERIF + ', "Times New Roman", serif', 'var(--font-display)'), (SERIF + ',serif', 'var(--font-display)'),
              ('Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif', 'var(--font-body)'), ('Inter,system-ui,sans-serif', 'var(--font-body)')]


def themed(html, fit=False):
    """Give any overlay page the shared fonts and tokens (used for the older panels served from main)."""
    for old, new in FONT_SWAPS:
        html = html.replace(old, new)
    script = ("<script>setInterval(()=>{const c=document.querySelector('#root>.card,#root>section,body>.card');if(!c)return;c.style.zoom=1;"
           "const h=c.getBoundingClientRect().bottom+6;const z=Math.min(1,innerHeight/h);if(z<.995)c.style.zoom=z.toFixed(3)},1000)</script>")
    html = html.replace('<style>', FONTS_LINK + '<style>' + THEME_CSS, 1)
    return html.replace('</body>', script + '</body>', 1) if fit else html


BASE_CSS = r"""
:root{color-scheme:dark;--card:var(--panel);font-family:var(--font-body)}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent;color:var(--text);-webkit-font-smoothing:antialiased}
.card{max-width:100%;overflow:hidden;min-width:0;background:radial-gradient(circle at 90% 0,rgba(125,72,220,.14),transparent 45%),var(--card);border:1px solid var(--edge);border-radius:var(--radius);box-shadow:var(--shadow);padding:16px 18px}
.eyebrow{font-size:12px;font-weight:850;letter-spacing:.14em;text-transform:uppercase;color:var(--green2)}
.muted{color:var(--muted)}
.bar{height:7px;border-radius:99px;background:rgba(255,255,255,.08);overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--green),var(--violet));transition:width .8s ease}
"""

SHARED_JS = r"""
const Q=new URLSearchParams(location.search);
const esc=v=>String(v==null?'':v).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const ago=iso=>{const s=Math.max(0,Math.floor((Date.now()-new Date(iso).getTime())/1000));return s<10?'just now':s<60?s+'s ago':s<3600?Math.floor(s/60)+'m ago':s<86400?Math.floor(s/3600)+'h ago':Math.floor(s/86400)+'d ago'};
async function poll(render,every){
  const go=async()=>{try{const r=await fetch('/api/v1/overlay?channel='+encodeURIComponent(CHANNEL),{cache:'no-store'});if(!r.ok)throw 0;const d=await r.json();if(d.ok)render(d)}catch(e){}};
  await go();setInterval(go,every||3500);
}
if(Q.get('scale'))document.documentElement.style.zoom=Q.get('scale');
// Card panels shrink to fit their Browser Source when content grows (a live event adds rows), so nothing is cut off.
setInterval(()=>{const c=document.querySelector('body>.card,body>section.card,body>.news');if(!c)return;c.style.zoom=1;const h=c.getBoundingClientRect().height+8,w=c.scrollWidth;
  const z=Math.min(1,(innerHeight)/h);if(z<.995)c.style.zoom=z.toFixed(3)},1000);
"""

PAGES = {}

PAGES['alerts'] = (r"""
.stage{position:fixed;inset:0;display:flex;align-items:flex-start;justify-content:center;padding:14px}
.alert{position:relative;display:grid;grid-template-columns:74px minmax(0,1fr);gap:16px;align-items:center;width:min(620px,100%);padding:16px 22px 16px 16px;border-radius:var(--radius);
  background:radial-gradient(circle at 12% 50%,var(--glow),transparent 55%),linear-gradient(145deg,rgba(8,13,39,.97),rgba(24,15,54,.96));border:1px solid var(--accent);
  box-shadow:0 14px 40px rgba(0,0,0,.5),0 0 34px var(--glow);opacity:0;transform:translateY(-26px) scale(.96)}
.alert.show{animation:enter .6s var(--ease-pop) forwards}.alert.hide{animation:leave .4s var(--ease) forwards}
.alert .icon{width:74px;height:74px;display:grid;place-items:center;font-size:40px;border-radius:50%;background:rgba(255,255,255,.06);border:1px solid var(--accent);animation:pop 1.2s ease .2s}
.alert .kind{font-size:11px;font-weight:850;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
.alert h1{margin:3px 0 0;font-family:var(--font-display);font-size:27px;line-height:1.1;color:var(--ivory);text-shadow:0 0 6px rgba(255,248,232,.25)}
.alert p{margin:6px 0 0;font-size:15px;color:var(--muted);line-height:1.35}
.alert .timer{position:absolute;left:18px;right:18px;bottom:6px;height:3px;border-radius:9px;background:var(--accent);opacity:.55;transform-origin:left;animation:timer linear forwards}
.spark{position:absolute;width:6px;height:6px;border-radius:50%;background:var(--accent);opacity:0;animation:spark 1.1s ease-out forwards}
@keyframes enter{to{opacity:1;transform:none}}@keyframes leave{to{opacity:0;transform:translateY(-18px) scale(.97)}}
@keyframes pop{0%{transform:scale(.6)}45%{transform:scale(1.18)}100%{transform:scale(1)}}@keyframes timer{from{transform:scaleX(1)}to{transform:scaleX(0)}}
@keyframes spark{0%{opacity:1;transform:translate(0,0)}100%{opacity:0;transform:translate(var(--dx),var(--dy))}}
""", r"""
<div class="stage" id="stage"></div>
<script>
const COLORS={join:['#7ee3b0','rgba(126,227,176,.28)','New citizen'],level:['#70ddff','rgba(112,221,255,.28)','Level up'],achievement:['#ffd27a','rgba(255,210,122,.30)','Achievement'],
  queue:['#b8f4d0','rgba(184,244,208,.22)','Queue complete'],event_start:['#ff7484','rgba(255,116,132,.32)','Society event'],event_win:['#ffd27a','rgba(255,210,122,.34)','Event complete'],
  event_fail:['#ff9aa6','rgba(255,154,166,.24)','Event over'],event_cancel:['#aca9c9','rgba(172,169,201,.18)','Event cancelled'],tier:['#bd91ff','rgba(189,145,255,.36)','Society milestone'],
  project:['#bd91ff','rgba(189,145,255,.30)','Project'],story:['#ff9ad5','rgba(255,154,213,.28)','Story'],directive:['#70ddff','rgba(112,221,255,.24)','Daily directive'],
  trophy:['#ffd27a','rgba(255,210,122,.34)','Trophy unlocked'],challenge_start:['#ff7484','rgba(255,116,132,.34)','Stream challenge'],challenge_win:['#7ee3b0','rgba(126,227,176,.34)','Challenge complete'],
  challenge_fail:['#ff9aa6','rgba(255,154,166,.24)','Challenge over'],vote:['#ffd27a','rgba(255,210,122,.28)','Colony vote'],season:['#ff9ad5','rgba(255,154,213,.32)','Season']};
const SHOW=Number(Q.get('seconds')||7)*1000, SKIP=new Set((Q.get('hide')||'').split(',').filter(Boolean));
const stage=document.getElementById('stage');let last=null,queue=[],busy=false,audio=null;
function chime(big){if(!Q.get('sound'))return;try{audio=audio||new AudioContext();const t=audio.currentTime;[0,.12,.24].slice(0,big?3:2).forEach((d,i)=>{const o=audio.createOscillator(),g=audio.createGain();o.type='sine';o.frequency.value=[660,880,1175][i];g.gain.setValueAtTime(.0001,t+d);g.gain.exponentialRampToValueAtTime(.12,t+d+.02);g.gain.exponentialRampToValueAtTime(.0001,t+d+.5);o.connect(g).connect(audio.destination);o.start(t+d);o.stop(t+d+.55)})}catch(e){}}
function show(h){busy=true;const [accent,glow,label]=COLORS[h.kind]||['#b8f4d0','rgba(184,244,208,.2)','Highlight'];
  const el=document.createElement('div');el.className='alert';el.style.setProperty('--accent',accent);el.style.setProperty('--glow',glow);
  el.innerHTML=`<div class="icon">${esc(h.emoji)}</div><div style="min-width:0"><div class="kind">${esc(label)}</div><h1>${esc(h.title)}</h1>${h.detail?`<p>${esc(h.detail)}</p>`:''}</div><div class="timer" style="animation-duration:${SHOW}ms"></div>`;
  stage.innerHTML='';stage.appendChild(el);requestAnimationFrame(()=>el.classList.add('show'));
  const big=['achievement','event_win','tier','project','trophy','challenge_win','season'].includes(h.kind);chime(big);
  if(big)for(let i=0;i<14;i++){const s=document.createElement('i');s.className='spark';const a=Math.random()*Math.PI*2,r=60+Math.random()*90;s.style.left='52px';s.style.top='52px';s.style.setProperty('--dx',Math.cos(a)*r+'px');s.style.setProperty('--dy',Math.sin(a)*r+'px');s.style.animationDelay=(Math.random()*.25)+'s';el.appendChild(s)}
  setTimeout(()=>{el.classList.add('hide');setTimeout(()=>{el.remove();busy=false;next()},480)},SHOW)}
function next(){if(!busy&&queue.length)show(queue.shift())}
const DEMO=[{kind:'join',emoji:'🌱',title:'Kamex arrived in New Eridian',detail:'Type !start in chat to join them.'},{kind:'level',emoji:'⬆️',title:'Kamex levelled up',detail:'Crafting aptitude Lv. 2 → Lv. 3'},
  {kind:'achievement',emoji:'🏆',title:'Astra earned an achievement',detail:'First Masterwork'},{kind:'event_start',emoji:'🚨',title:'Siro Surge has started!',detail:'Research and Engineering help. 10 minutes on the clock.'},
  {kind:'tier',emoji:'🏛️',title:'New Eridian is now a Settlement!',detail:'The whole society levelled up.'},
  {kind:'trophy',emoji:'💎',title:'Astra earned 💎 Ore Hunter',detail:'Find every ore on Avesta'},{kind:'challenge_start',emoji:'🌪️',title:'Dust Storm! Everyone repair the walls before the storm hits',detail:'Goal 24 in 8 minutes. Help with !repair or any crafting.'},
  {kind:'vote',emoji:'🗳️',title:'The colony voted: Clinic Expansion is next!',detail:'🏥 More beds and a pharmacy at the clinic (7 of 12 votes).'}];
if(Q.get('test')){let i=0;const loop=()=>{queue.push(DEMO[i++%DEMO.length]);next()};loop();setInterval(loop,SHOW+1200)}
else poll(d=>{const rows=(d.highlights||[]).slice().reverse();if(last===null){last=rows.length?rows[rows.length-1].id:0;return}
  for(const h of rows)if(h.id>last){last=h.id;if(!SKIP.has(h.kind))queue.push(h)}queue=queue.slice(-6);next()},3000);
</script>""")

PAGES['ticker'] = (r"""
/* A TV-style lower third: a station block on the left, a crawl where every item carries a coloured
   section tag, and the Avesta clock and weather on the right. Sized from the source height. */
body{font-size:clamp(11px,38vh,30px)}
.ticker{position:fixed;inset:0;display:flex;align-items:stretch;overflow:hidden;background:linear-gradient(180deg,rgba(14,18,48,.97),rgba(8,10,30,.97));border-top:.12em solid var(--green);box-shadow:0 -.3em 1em rgba(0,0,0,.35)}
.station{flex:none;display:flex;align-items:center;gap:.5em;padding:0 .9em 0 .7em;background:linear-gradient(90deg,#7ee3b0,#70ddff);color:#07101d;clip-path:polygon(0 0,100% 0,calc(100% - .7em) 100%,0 100%);padding-right:1.4em;z-index:2}
.station .live{display:flex;align-items:center;gap:.3em;padding:.12em .45em;border-radius:.3em;background:#07101d;color:#fff;font:800 .55em var(--font-body);letter-spacing:.14em}
.station .live i{width:.55em;height:.55em;border-radius:50%;background:#ff4d6a;animation:blink 1.6s infinite}
.station .name{font:700 .82em var(--font-display);letter-spacing:.04em;white-space:nowrap}
.lane{position:relative;flex:1;overflow:hidden;mask-image:linear-gradient(90deg,transparent,#000 2%,#000 98%,transparent)}
.track{position:absolute;top:0;left:0;height:100%;display:flex;align-items:center;white-space:nowrap;will-change:transform}
.item{display:inline-flex;align-items:center;gap:.5em;padding:0 1.1em;font-size:.72em;font-weight:600;color:var(--text)}.item b{color:#fff;font-weight:800}.item em{font-style:normal;color:var(--amber);font-weight:800}
.item .tag{padding:.14em .5em;border-radius:.3em;font:800 .72em var(--font-body);letter-spacing:.12em;color:#07101d;background:var(--c,#70ddff)}
.item:after{content:'';width:.4em;height:.4em;margin-left:1.1em;transform:rotate(45deg);background:rgba(255,255,255,.35)}
.clock{flex:none;display:flex;align-items:center;gap:.5em;padding:0 .9em 0 1.3em;background:rgba(255,255,255,.06);clip-path:polygon(.7em 0,100% 0,100% 100%,0 100%);font:700 .7em var(--font-body);white-space:nowrap;z-index:2}
.clock b{font:700 1.15em var(--font-display);color:#fff}
@keyframes blink{50%{opacity:.25}}
""", r"""
<div class="ticker"><div class="station"><span class="live"><i></i>LIVE</span><span class="name">NEW ERIDIAN NEWS</span></div><div class="lane"><div class="track" id="track"></div></div><div class="clock" id="clock"></div></div>
<script>
const SPEED=Number(Q.get('speed')||80);let data=null,running=false;
const TAG={event:['EVENT','#ff7484'],news:['NEWS','#70ddff'],today:['TODAY','#7ee3b0'],market:['MARKET','#ffd27a'],holiday:['HOLIDAY','#ff9ad5'],project:['PROJECT','#bd91ff'],
  work:['AT WORK','#b8f4d0'],report:['REPORT','#70ddff'],rumor:['RUMOR','#aca9c9'],weather:['WEATHER','#9fd0ff'],society:['SOCIETY','#bd91ff'],join:['JOIN','#7ee3b0'],
  challenge:['CHALLENGE','#ff7484'],vote:['VOTE','#ffd27a'],season:['SEASON','#ff9ad5']};
const tag=k=>`<span class="tag" style="--c:${TAG[k][1]}">${TAG[k][0]}</span>`;
function items(d){const out=[];const e=d.event,add=(k,html)=>out.push(tag(k)+html);
  if(e)add('event',`🚨 <b>${esc(e.name)}</b> in progress · ${e.progress}/${e.goal} · ${Math.floor(e.seconds_remaining/60)}m left · <em>${esc(e.primary)}</em> work helps`);
  const c=d.challenge;if(c&&c.state==='active')add('challenge',`${esc(c.emoji)} <b>${esc(c.title)}</b> · ${esc(c.text)} · ${c.progress}/${c.goal} · ${Math.ceil(c.seconds_left/60)}m left · type <em>${esc(c.how)}</em>`);
  else if(c)add('challenge',`${esc(c.emoji)} <b>${esc(c.title)}</b> ${c.state==='won'?'complete! Rewards paid to '+c.participants+' helpers':'ran out of time'}`);
  const v=d.vote;if(v&&v.options)add('vote',`Day ${v.day} vote: ${v.options.map(o=>`<b>${o.n}</b> ${esc(o.emoji)} ${esc(o.name)} <em>${o.votes}</em>`).join(' · ')} · type <b>!vote 1</b>, 2 or 3 · closes in ${esc(v.closes_in)}`);
  if(v&&v.festival)add('vote',`${esc(v.festival.emoji)} <b>${esc(v.festival.name)}</b> today, voted by the colony: ${esc(v.festival.text)}`);
  if(d.condition)add('weather',`${esc(d.condition)} · ${esc(d.condition_text||'')}`);
  for(const h of (d.highlights||[]).slice(0,6))add('news',`${esc(h.emoji)} <b>${esc(h.title)}</b>${h.detail?' · '+esc(h.detail):''} <span class="muted">(${ago(h.at)})</span>`);
  if(d.next_tier)add('society',`<b>${esc(d.tier)}</b> → ${esc(d.next_tier)} · ${Math.round(d.tier_percent||0)}%${d.bottleneck?` · needs more <em>${esc(d.bottleneck.name)}</em>`:''}`);
  const q=d.directive;if(q&&q.name)add('today',`<b>${esc(q.name)}</b> · ${q.progress}/${q.goal}${q.complete?' ✅':''}`);
  const m=d.market;if(m&&m.primary)add('market',`<em>${esc(m.primary.name)}</em> in demand at ${m.primary.price} SC${m.secondary?` · ${esc(m.secondary.name)} ${m.secondary.price} SC`:''}`);
  const f=d.festival;if(f)add('holiday',`${esc(f.emoji)} <b>${esc(f.name)} festival</b> · ${f.days_left} days left · ${esc((f.foods||[]).join(', '))}`);
  const p=d.project;if(p&&p.name)add('project',`🏗️ <b>${esc(p.name)}</b> · ${Math.round(p.percent||0)}%`);
  const w=d.working||[];if(w.length)add('work',`<b>${w.length}</b> citizen${w.length>1?'s':''} working: ${w.slice(0,3).map(x=>esc(x.name)+' ('+esc(x.task)+')').join(', ')}`);
  for(const n of (d.narration||[]).slice(0,3))add('report',`<b>${esc(n.headline||'')}</b> · ${esc((n.text||'').split(' — ').slice(-1)[0])}`);
  if(d.rumor)add('rumor',esc(d.rumor));
  const se=d.season;if(se)add('season',`${esc(se.emoji)} <b>${esc(se.name)}</b> · chapter ${se.chapter}/${se.chapters} · ${se.days_left} days left${(se.top||[]).length?' · leader <b>'+esc(se.top[0].name)+'</b> '+se.top[0].points.toLocaleString():''} · type <b>!season</b>`);
  add('join',`Type <b>!start</b> in chat to join New Eridian${d.join&&d.join.discord?' · Discord: <b>'+esc(d.join.discord.replace(/^https?:\/\//,''))+'</b>':''}`);
  return out}
function clock(d){const h=d.hour==null?null:((d.hour%24)+24)%24,t=h==null?'':`${String(Math.floor(h)).padStart(2,'0')}:${String(Math.floor(h%1*60)).padStart(2,'0')}`;
  document.getElementById('clock').innerHTML=`${esc(d.phase_emoji||'')} <b>${t}</b> DAY ${d.day||'—'}`}
function cycle(){if(!data){setTimeout(cycle,1000);return}running=true;const track=document.getElementById('track'),lane=track.parentElement;
  track.innerHTML=items(data).map(x=>`<span class="item">${x}</span>`).join('');const w=track.scrollWidth,L=lane.clientWidth;
  const dur=(w+L)/SPEED*1000;track.animate([{transform:`translateX(${L}px)`},{transform:`translateX(${-w}px)`}],{duration:dur,easing:'linear'}).onfinish=cycle}
poll(d=>{data=d;clock(d);if(!running)cycle()},5000);
</script>""")

PAGES['leaders'] = (r"""
body{padding:4px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px}
h3{margin:0 0 8px;font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--cyan)}
.row{display:grid;grid-template-columns:30px minmax(0,1fr) auto;gap:8px;align-items:center;padding:7px 9px;border-radius:9px;background:rgba(7,9,13,.3);margin-bottom:6px;font-size:15px;animation:ne-in var(--dur) var(--ease) both}
.rank{font-weight:900;color:var(--muted);text-align:center}.row:nth-child(2) .rank{color:#ffd27a}.row:nth-child(3) .rank{color:#dfe6f3}.row:nth-child(4) .rank{color:#e7a36b}
.name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:750}.num{color:var(--green2);font-weight:800;font-variant-numeric:tabular-nums}
.event{margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,.09)}
@keyframes fade{from{opacity:0;transform:translateX(-8px)}to{opacity:1;transform:none}}
""", r"""
<section class="card"><div class="eyebrow">🏆 New Eridian Leaders</div><div class="grid"><div id="a"></div><div id="b"></div></div><div id="ev"></div></section>
<script>
const medal=i=>['🥇','🥈','🥉'][i]||'#'+(i+1);
const list=(title,rows,val)=>`<h3>${title}</h3>`+(rows.length?rows.map((r,i)=>`<div class="row" style="animation-delay:${i*60}ms"><span class="rank">${medal(i)}</span><span class="name">${esc(r.name)}</span><span class="num">${val(r)}</span></div>`).join(''):'<div class="muted">Waiting for citizens…</div>');
let sig='';poll(d=>{const L=d.leaders||{},s=JSON.stringify([L,d.event&&d.event.leaders]);if(s===sig)return;sig=s;
  document.getElementById('a').innerHTML=list('Top contributors',L.contributors||[],r=>r.contribution.toLocaleString());
  document.getElementById('b').innerHTML=list('Most active · 24h',L.active_today||[],r=>r.actions+' actions');
  const e=d.event;document.getElementById('ev').innerHTML=e&&e.leaders&&e.leaders.length?`<div class="event">${list(esc(e.emoji+' '+e.name)+' leaders',e.leaders,r=>r.primary+' + '+r.support)}</div>`:''},5000);
</script>""")

PAGES['working'] = (r"""
body{padding:4px}.list{display:flex;flex-direction:column;gap:8px;margin-top:11px}
.job{min-width:0;padding:9px 11px;border-radius:10px;background:rgba(7,9,13,.32);animation:ne-in var(--dur) var(--ease) both}
.top{display:flex;gap:8px;align-items:baseline;font-size:14px;min-width:0}.who{flex:none;font-weight:800}.task{color:var(--cyan);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.count{flex:none;margin-left:auto;font-variant-numeric:tabular-nums;color:var(--muted);font-size:13px}.paused .task{color:var(--amber)}.paused .bar i{background:var(--amber)}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
""", r"""
<section class="card"><div style="display:flex;justify-content:space-between"><div class="eyebrow">⏱️ Working right now</div><span class="muted" id="n" style="font-size:12px"></span></div><div class="list" id="list"></div></section>
<script>
let shape='';
poll(d=>{const w=d.working||[],q=(d.join&&d.join.queue)||['!craftmax lumber','to work while you watch'];document.getElementById('n').textContent=w.length?w.length+' queue'+(w.length>1?'s':''):'';
  const next=JSON.stringify([q,w.map(x=>[x.name,x.task,x.total,x.state])]);const list=document.getElementById('list');
  if(next!==shape){shape=next;list.innerHTML=w.length?w.map((x,i)=>`<div class="job ${x.state==='paused'?'paused':''}" style="animation-delay:${i*50}ms"><div class="top"><span class="who">${esc(x.name)}</span><span class="task">${esc(x.task)}${x.state==='paused'?' · paused':''}</span><span class="count"></span></div><div class="bar"><i style="width:0"></i></div></div>`).join('')
    :`<div class="muted" style="font-size:14px">No queues running. ${q[0][0]==='/'?'Use':'Type'} <b style="color:var(--green2)">${esc(q[0])}</b> ${esc(q[1])}.</div>`}
  // Progress updates in place, so bars glide instead of the list redrawing.
  list.querySelectorAll('.job').forEach((el,i)=>{const x=w[i];el.querySelector('.count').textContent=x.done+'/'+x.total;requestAnimationFrame(()=>el.querySelector('.bar i').style.width=(x.total?Math.round(x.done/x.total*100):0)+'%')})},3500);
</script>""")

PAGES['join'] = (r"""
body{padding:4px}.card{display:grid;grid-template-columns:minmax(0,1fr);gap:4px}
h1{margin:2px 0 0;font-family:var(--font-display);font-size:26px;color:var(--ivory)}
.cmd{display:flex;align-items:center;gap:12px;margin-top:8px;min-height:48px;min-width:0}.cmd span{min-width:0}
.cmd code{flex:none;padding:8px 13px;border-radius:10px;background:rgba(126,227,176,.12);border:1px solid rgba(126,227,176,.45);color:var(--green2);font:800 20px ui-monospace,SFMono-Regular,Menlo,monospace}
.cmd span{font-size:16px;color:var(--muted)}.swap{animation:ne-in var(--dur) var(--ease) both}.dots{display:flex;gap:5px;margin-top:10px}.dots i{width:6px;height:6px;border-radius:50%;background:rgba(255,255,255,.18)}.dots i.on{background:var(--green)}
.discord{margin-top:10px;padding-top:9px;border-top:1px solid rgba(255,255,255,.09);font-size:14px;color:var(--muted)}.discord b{color:#aab4ff}
@keyframes swap{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
""", r"""
<section class="card"><div class="eyebrow">🌱 Play from chat</div><h1>Join New Eridian</h1><div id="cmd" class="cmd"></div><div class="dots" id="dots"></div><div id="discord"></div></section>
<script>
let tips=[],i=0;const EVERY=Number(Q.get('seconds')||7)*1000;
function draw(){if(!tips.length)return;const t=tips[i%tips.length];const c=document.getElementById('cmd');c.innerHTML=`<code>${esc(t[0])}</code><span>${esc(t[1])}</span>`;c.classList.remove('swap');void c.offsetWidth;c.classList.add('swap');
  document.getElementById('dots').innerHTML=tips.map((_,k)=>`<i class="${k===i%tips.length?'on':''}"></i>`).join('');i++}
poll(d=>{const j=d.join||{};const first=!tips.length;tips=j.tips||[];document.getElementById('discord').innerHTML=j.discord?`<div class="discord">Crafting, queues, shopping lists, keep levels and quiet hours on Discord: <b>${esc(j.discord.replace(/^https?:\/\//,''))}</b></div>`:'';if(first)draw()},30000);
setInterval(draw,EVERY);
</script>""")


# The map's look: a tidy SEED-style colony as a low-poly diorama. One fixed sun high on the upper left shades every face the same
# way (ground, buildings, trees, the Kernel and the forest horizon). &quality=low keeps one plain shape for each instead of its
# facets, so the page stays light. Kept as its own block so a test can run it with Node.
SEEDLING_SCALE = .72            # Seedling tokens on the full map, relative to their earlier size (the column card keeps 1.0)
LOWPOLY_JS = r"""
// ---- low-poly light: one fixed sun, high on the upper left, shades every face in the town alike
const FACETS=QUALITY!=='low',FINE=QUALITY==='high',U=21;   // U: a tile's side in world units, for slopes
const SUN=(()=>{const v=[-.55,.45,1],m=Math.hypot(...v);return v.map(x=>x/m)})();   // toward the sun, on the world axes +i, +j and up
const FACE={top:[0,0,1],left:[0,1,0],right:[1,0,0]};   // the walls a viewer sees: the left one faces +j, the right one +i
const rgbOf=c=>Array.isArray(c)?c:c[0]==='#'?[1,3,5].map(k=>parseInt(c.slice(k,k+2),16)):c.match(/[\d.]+/g).slice(0,3).map(Number);
const blend=(a,b,t)=>{const x=rgbOf(a),y=rgbOf(b);return x.map((v,k)=>v+(y[k]-v)*t)};
const lum=n=>{n=FACE[n]||n;const m=Math.hypot(n[0],n[1],n[2])||1;return .62+.48*Math.max(0,(n[0]*SUN[0]+n[1]*SUN[1]+n[2]*SUN[2])/m)};
// shade(colour, facing, k): the colour of a face under the sun; facing is 'top', 'left', 'right', a normal [i,j,up] or a plain factor
function shade(c,f,k=1){f=typeof f==='number'?f:lum(f);const v=rgbOf(c).map(x=>Math.max(0,Math.min(255,Math.round(x*f*k))));return `rgb(${v[0]},${v[1]},${v[2]})`}
const cross=(u,w)=>[u[1]*w[2]-u[2]*w[1],u[2]*w[0]-u[0]*w[2],u[0]*w[1]-u[1]*w[0]],dot=(u,w)=>u[0]*w[0]+u[1]*w[1]+u[2]*w[2],minus=(u,w)=>u.map((v,k)=>v-w[k]);
const normal=(a,b,c)=>{const n=cross(minus(b,a),minus(c,a));return n[2]<0?n.map(x=>-x):n};
// A rounded shape's facet that points along a screen direction: un-projected onto the ground, tilted up the higher it sits.
const toward=(ux,uy)=>{const m=Math.hypot(ux,uy)||1;ux/=m;uy/=m;const i=ux/TW+uy/TH,j=uy/TH-ux/TW,h=Math.hypot(i,j)||1;return [i/h,j/h,.8+.6*Math.max(0,-uy)]};
const lift=(i,j,amp)=>rng('v'+Math.round(i*8)+','+Math.round(j*8))()*amp;   // corner heights: never drawn, they only tilt the facets
// A facet is edged in its own colour, so neighbouring facets meet without hairline seams.
const facet=(g,p,fill,a={})=>el('polygon',{points:pts(p),fill,stroke:fill,'stroke-width':.6,'stroke-linejoin':'round',...a},g);
// A patch of ground (one tile, or w×d tiles, inset from its edges) as facets: two triangles, four on high quality, each tilted by
// seeded corner heights and toned between the palette's two colours, so lawns and paving read as faceted, not flat.
function facetTile(g,i,j,pal,o={}){const [c1,c2]=Array.isArray(pal)?pal:[pal,pal],w=o.w||1,d=o.d||1,e=o.inset||0,amp=o.amp??5,r=rng((o.seed||'t')+':'+i+','+j),a={class:o.cls||'tile'};
  const tone=()=>blend(c1,c2,r()),jit=()=>1+(r()-.5)*(o.vary??.06),V=p=>[p[0]*U,p[1]*U,lift(p[0],p[1],amp)],C=[[i+e,j+e],[i+w-e,j+e],[i+w-e,j+d-e],[i+e,j+d-e]];
  if(!FACETS)return [facet(g,C.map(p=>iso(...p)),shade(tone(),'top',jit()),a)];
  const tri=q=>facet(g,q.map(p=>iso(...p)),shade(tone(),normal(...q.map(V)),jit()),a);
  if(FINE){const m=[i+w*(.5+(r()-.5)*.3),j+d*(.5+(r()-.5)*.3)];return C.map((p,k)=>tri([p,C[(k+1)%4],m]))}
  return r()<.5?[tri([C[0],C[1],C[2]]),tri([C[0],C[2],C[3]])]:[tri([C[0],C[1],C[3]]),tri([C[1],C[2],C[3]])]}
// Low-poly trees: tall thin-trunked trees with a crown on top (the colony's own kind), broadleaf trees and conifers.
const PINE=['#3b6044','#446b4a','#33573f'],LEAF=['#4f8a45','#5c9449','#6a9c4c','#477f42'],BARK='#6b5440';
function lowPolyTree(g,x,y,r,kind){const v=r();kind=kind||(v<.5?'tall':v<.85?'broad':'conifer');const k=.9+r()*.25,stem=(kind==='conifer'?4:kind==='tall'?17+r()*9:8)*k;
  el('ellipse',{cx:x+4*k,cy:y+1.2,rx:7*k,ry:2.6*k,fill:'rgba(0,0,0,.22)'},g);el('rect',{x:x-(kind==='tall'?.8:1.1),y:y-stem,width:kind==='tall'?1.6:2.2,height:stem,fill:BARK},g);
  if(kind==='conifer'){const c=PINE[Math.floor(r()*PINE.length)],h=24*k,w=7.5*k,tiers=FACETS?3:1;
    for(let t=0;t<tiers;t++){const yb=y-3*k-t*h*.26,top=tiers===1?y-h:yb-h*.5,ww=w*(1-t*.22),mid=[x+ww*.18,yb+1.2];
      facet(g,[[x-ww,yb],[x,top],mid],shade(c,toward(-1,-.3)));facet(g,[[x,top],[x+ww,yb],mid],shade(c,toward(1,-.3)))}
    return}
  const c=LEAF[Math.floor(r()*LEAF.length)],R=(kind==='tall'?6.2:7)*k,cy=y-stem-R*.75,n=7,P=[...Array(n)].map((_,q)=>{const a=-Math.PI/2+q/n*Math.PI*2,s=R*(.85+r()*.3);return [x+Math.cos(a)*s,cy+Math.sin(a)*s*.92]});
  if(!FACETS)return facet(g,P,shade(c,'top',.95));
  const m=[x-R*.2,cy-R*.25];P.forEach((p,q)=>{const b=P[(q+1)%n];facet(g,[m,p,b],shade(c,toward((p[0]+b[0])/2-x,(p[1]+b[1])/2-cy),1+(r()-.5)*.05))})}
// A rock: a lit top, a left face and a shaded right face (one plain shape on low quality).
function facetRock(g,x,y,s,r,c='#8a8276'){const T=[x+(r()-.5)*s*.4,y-s*(.8+r()*.35)],TL=[x-s*.62,y-s*.55],TR=[x+s*.6,y-s*.6],L=[x-s,y],R=[x+s*(.85+r()*.3),y-s*.05],F=[x+(r()-.5)*s*.3,y+s*.32],M=[x-s*.1,y-s*.35];
  if(!FACETS)return facet(g,[L,TL,T,TR,R,F],shade(c,'left'));
  facet(g,[TL,T,TR,M],shade(c,'top',.98+r()*.06));facet(g,[L,TL,M,F],shade(c,'left'));facet(g,[M,TR,R,F],shade(c,'right'))}
// A shrub: a squat crown, its lit half and its shaded half.
function shrub(g,x,y,s,r,c){const P=[[x-s,y],[x-s*.7,y-s*.8],[x+(r()-.5)*s*.3,y-s*1.15],[x+s*.75,y-s*.75],[x+s,y]],m=[x-s*.1,y-s*.5];
  if(!FACETS)return facet(g,P,shade(c,'left'));facet(g,[P[0],P[1],P[2],m],shade(c,toward(-1,-1)));facet(g,[m,P[2],P[3],P[4],P[0]],shade(c,toward(1,-.2)))}
// Water: a faceted surface (a ring of triangles around a centre fan) in deep and light blues, a few catching the sun, inside a shore rim.
function water(g,x,y,rx,ry,o={}){const r=rng(o.seed||'water'),n=FINE?12:8,deep=o.deep||'#3b6a82',hi=o.hi||'#8ab8c8',rim=o.rim||'#b1a585';
  const ring=(f,j,half)=>[...Array(n)].map((_,k)=>{const a=(k+(half?.5:0))/n*Math.PI*2,q=f*(1+(r()-.5)*j);return [x+Math.cos(a)*rx*q,y+Math.sin(a)*ry*q]});
  facet(g,ring(1.13,.05),shade(rim,'top'),{stroke:shade(rim,'right'),'stroke-width':1.6});   // the shore
  const outer=ring(1,.05);if(!FACETS)return facet(g,outer,shade(deep,'top'));
  const inner=ring(.55,.25,true),c=[x+(r()-.5)*rx*.15,y+(r()-.5)*ry*.15],f=q=>facet(g,q,shade(r()<.22?blend(deep,hi,.45+r()*.4):blend(deep,hi,r()*.2),'top',1+(r()-.5)*.08));
  for(let k=0;k<n;k++){const k1=(k+1)%n;f([outer[k],outer[k1],inner[k]]);f([inner[k],outer[k1],inner[k1]]);f([c,inner[k],inner[k1]])}}
// The town is a diorama: under its two front edges hang faces of topsoil, clay and bedrock, lit on the left and in shade on the right.
const STRATA=[['#4f3f2c',0],['#7a6347',.18],['#7f7d78',.5]];
function slab(g,lo,hi,depth=34){const r=rng('slab'),segs=FACETS?9:1;
  for(const [a,b,side] of [[[lo,hi],[hi,hi],'left'],[[hi,hi],[hi,lo],'right']]){const A=iso(...a),B=iso(...b),P=s=>[A[0]+(B[0]-A[0])*s/segs,A[1]+(B[1]-A[1])*s/segs];
    const cut=[...STRATA.map(x=>x[1]),1].map((t,n)=>[...Array(segs+1)].map(()=>t*depth+(n===0?0:n===STRATA.length?r()*6:(r()-.5)*5)));   // straight along the top, ragged between strata
    STRATA.forEach(([c],n)=>{for(let s=0;s<segs;s++){const p=P(s),q=P(s+1);
      facet(g,[[p[0],p[1]+cut[n][s]],[q[0],q[1]+cut[n][s+1]],[q[0],q[1]+cut[n+1][s+1]],[p[0],p[1]+cut[n+1][s]]],shade(c,side,1+(FACETS?(r()-.5)*.12:0)))}})}}
// The horizon: rows of tall, thin-trunked trees fading into teal mist. Each row is drawn as a few paths (trunks, the lit halves of the
// crowns, their shaded halves), so hundreds of trees cost a handful of shapes. sky() recolours them by the hour from data-l (the row,
// 0 farthest) and data-k (how that part is lit), and the mist bands through the mistg gradient. Low quality: two flat silhouettes.
function forest(far,near){const rows=FACETS?[[far,0,158,44,72,11],[far,1,186,58,92,14],[near,2,216,74,118,18]]:[[far,1,182,54,88,15],[near,2,216,70,112,20]];
  for(const [g,l,base,lo,hi,step] of rows){const r=rng('forest'+l),at=k=>({'data-l':l,'data-k':k});let trunks='',lit='',dark='';
    el('rect',{x:-2000,y:base-.5,width:4960,height:2800,...at(.92)},g);   // the forest floor in front of this row
    for(let x=-460;x<1420;x+=step*(.75+r()*.7)){const h=lo+r()*(hi-lo),R=step*(.42+r()*.28),tx=x+(r()-.5)*4,ty=base-h,tw=Math.max(.6,step*.045);
      const P=[...Array(6)].map((_,q)=>{const a=-Math.PI/2+q/6*Math.PI*2,s=R*(.8+r()*.4);return [tx+Math.cos(a)*s,ty+Math.sin(a)*s*1.15]}),path=q=>'M'+q.map(p=>p[0].toFixed(1)+' '+p[1].toFixed(1)).join('L')+'Z';
      trunks+=path([[tx-tw,base],[tx-tw,ty],[tx+tw,ty],[tx+tw,base]]);
      if(FACETS){lit+=path([P[0],P[5],P[4],P[3]]);dark+=path([P[0],P[1],P[2],P[3]])}else lit+=path(P)}
    el('path',{d:trunks,...at(.72)},g);el('path',{d:lit,...at(FACETS?1+.02*l:1)},g);if(FACETS)el('path',{d:dark,...at(.92-.04*l)},g);
    el('rect',{x:-2000,y:base-hi*.55,width:4960,height:hi*.55+3,fill:'url(#mistg)',class:'mist'},g)}}   // mist lying low between the rows
// ---- the Kernel: the colony's seed pod in the middle of the Commons, where every new Seedling steps out
const VIEW=[.61,.61,.5];   // toward the viewer, on the world axes
// An egg or a pod as facets: n segments around and bands up its height, each lit by the sun. Only the faces turned to the viewer are
// drawn, so a convex shape needs no sorting. Its centre (i,j) is in tiles, R is its widest radius in tiles (at height fraction c), H its
// height, col gives the colour at each height fraction and z0 how high its base sits. Returns its projection, for details drawn on it.
function ovoid(g,i,j,R,H,col,o={}){const n=o.n||(FINE?14:FACETS?10:6),bands=o.bands||(FACETS?[0,.16,.34,.52,.68,.82,.93,1]:[0,.5,1]),c=o.c??.42,z0=o.z0||0,[cx,cy]=iso(i,j);
  const rad=t=>R*Math.sqrt(Math.max(0,1-((t-c)/(t<c?(c||1):1-c))**2)),P=(a,t)=>[rad(t)*Math.cos(a),rad(t)*Math.sin(a),z0+t*H],W=p=>[p[0]*U,p[1]*U,p[2]];
  const S=p=>[cx+(p[0]-p[1])*TW/2,cy+(p[0]+p[1])*TH/2-p[2]],rot=o.rot||0;
  for(let b=0;b<bands.length-1;b++){const t0=bands[b],t1=bands[b+1],tm=(t0+t1)/2;
    for(let k=0;k<n;k++){const a0=rot+k/n*Math.PI*2,a1=a0+Math.PI*2/n,am=(a0+a1)/2,q=[P(a0,t0),P(a1,t0),P(a1,t1),P(a0,t1)],w=q.map(W);
      let nm=cross(minus(w[2],w[0]),minus(w[3],w[1]));if(dot(nm,[Math.cos(am)*U,Math.sin(am)*U,(tm-c)*H*2])<0)nm=nm.map(x=>-x);
      if(dot(nm,VIEW)<=0)continue;facet(g,q.map(S),shade(col(tm),nm),o.cls?{class:o.cls}:{})}}
  return {S,P,rad}}
// A smooth body of revolution (the Kernel and its feet): unlike the faceted town it is drawn as a few gradient-filled outlines.
// Its centre (i,j) is in tiles, R its widest radius in tiles (at height fraction c), H its height; heights below t0 are underground.
function revolve(i,j,R,H,o={}){const c=o.c??.4,t0=o.t0||0,[cx,cy]=iso(i,j),rad=t=>R*Math.sqrt(Math.max(0,1-((t-c)/(t<c?(c||1):1-c))**2));
  const P=(a,t)=>[rad(t)*Math.cos(a),rad(t)*Math.sin(a),(t-t0)*H],S=p=>[cx+(p[0]-p[1])*TW/2,cy+(p[0]+p[1])*TH/2-p[2]];
  const N=(a,t)=>{const d=(rad(Math.min(1,t+.01))-rad(Math.max(0,t-.01)))/.02;return [Math.cos(a),Math.sin(a),-U*d/H]};   // the outward normal
  const shape=(ta,tb,n=FACETS?32:16,m=FACETS?10:5)=>outline([...Array(n)].flatMap((_,k)=>[...Array(m+1)].map((_,q)=>S(P(k/n*Math.PI*2,ta+(tb-ta)*q/m)))));
  return {S,P,rad,N,shape,seen:(a,t)=>dot(N(a,t),VIEW)>0}}
// The convex outline of a set of screen points: the silhouette of a rounded shape.
function outline(p){p=p.slice().sort((a,b)=>a[0]-b[0]||a[1]-b[1]);const x=(o,a,b)=>(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0]),lo=[],hi=[];
  for(const q of p){while(lo.length>1&&x(lo[lo.length-2],lo[lo.length-1],q)<=0)lo.pop();lo.push(q)}
  for(const q of p.reverse()){while(hi.length>1&&x(hi[hi.length-2],hi[hi.length-1],q)<=0)hi.pop();hi.push(q)}
  return lo.slice(0,-1).concat(hi.slice(0,-1))}
const pathOf=p=>'M'+p.map(q=>q[0].toFixed(1)+' '+q[1].toFixed(1)).join('L')+'Z';
// A smooth left-to-right gradient for a rounded surface, its stops taken from shade() round the shape, so it is lit like the town.
function sheen(defs,id,c,up=0){const g=el('linearGradient',{id,x1:0,y1:0,x2:1,y2:0},defs);
  for(const k of [3,2,1,0,-1]){const a=k*Math.PI/4,x=Math.cos(a)-Math.sin(a);el('stop',{offset:((x+Math.SQRT2)/(2*Math.SQRT2)).toFixed(3),'stop-color':shade(c,[Math.cos(a),Math.sin(a),up])},g)}
  return `url(#${id})`}
const KERNEL=[10.15,10.15],KDOOR=iso(10.95,10.95),KRAMP=iso(11.85,11.85);   // its centre (tiles), its doorway and the foot of its ramp (screen)
function kernel(g){const [ki,kj]=KERNEL,R=1.38,H=76,t0=.12,F=Math.PI/4,defs=el('defs',{},g),[cx,cy]=iso(ki,kj),line=(p,a)=>el('polyline',{points:pts(p),fill:'none',...a},g);
  el('ellipse',{cx:cx+10,cy:cy+6,rx:66,ry:27,fill:'rgba(0,0,0,.2)'},g);   // its shadow, away from the sun
  // four rounded feet tucked under the body, at its sides either side of the door and behind
  const foot=FACETS?sheen(defs,'kfootg','#848b8f',.3):shade('#848b8f','left'),shell=FACETS?sheen(defs,'kshellg','#b9bec1',.8):shade('#b9bec1','top');
  for(const a of [F+Math.PI-1.2,F+Math.PI+1.2,F-1.25,F+1.25]){const P=revolve(ki+Math.cos(a)*R*.95,kj+Math.sin(a)*R*.95,.48,26,{c:.42,t0:.06});
    el('path',{class:'kfoot',d:pathOf(P.shape(.06,1)),fill:foot},g);if(FACETS)el('path',{d:pathOf(P.shape(.6,1,16,4)),fill:shell},g)}   // each foot: a darker base under a pale shell
  // the egg: a darker lower body and a paler cap, smooth, lit from the upper left, with a soft highlight on the cap
  const E=revolve(ki,kj,R,H,{c:.4,t0}),seam=.58,ring=.8,run=(t,n=48)=>{const out=[];let cur=[];for(let k=0;k<=n;k++){const a=F-Math.PI+k/n*Math.PI*2;if(E.seen(a,t))cur.push(E.S(E.P(a,t)));else if(cur.length){out.push(cur);cur=[]}}if(cur.length)out.push(cur);return out};
  el('path',{class:'kbody',d:pathOf(E.shape(t0,1)),fill:FACETS?sheen(defs,'kbodyg','#858c90',.1):shade('#858c90','left')},g);
  el('path',{d:pathOf(E.shape(seam,1)),fill:FACETS?sheen(defs,'kcapg','#c2c7c9',.75):shade('#c2c7c9','top')},g);
  for(const p of run(seam))line(p,{stroke:'#6a7175','stroke-width':1});   // the seam between them
  if(FACETS){const hg=el('radialGradient',{id:'khig'},defs);el('stop',{offset:0,'stop-color':'#ffffff','stop-opacity':.45},hg);el('stop',{offset:1,'stop-color':'#ffffff','stop-opacity':0},hg);
    const [hx,hy]=E.S(E.P(F+Math.PI/2+.25,.83));el('ellipse',{cx:hx,cy:hy,rx:16,ry:10,fill:'url(#khig)'},g)}
  // the glowing band round the upper dome: bright where it faces us, hidden behind the dome (brighter at night, pulsing on high quality)
  for(const p of run(ring)){line(p,{class:'kglow',stroke:'#5fe6ff','stroke-width':6,opacity:.35,'stroke-linecap':'round'});line(p,{class:'kring',stroke:'#9ff6ff','stroke-width':2.2,'stroke-linecap':'round'})}
  // the hatch on top: a dark recessed circle in a pale lip, with small cyan lights
  const top=(t,n=24)=>[...Array(n)].map((_,k)=>E.S(E.P(k/n*Math.PI*2,t)));el('path',{d:pathOf(top(.955)),fill:'#a7adb0'},g);el('path',{d:pathOf(top(.975)),fill:'#465054'},g);
  for(let k=0;k<4;k++){const [x,y]=E.S(E.P(k*Math.PI/2,.965));el('circle',{class:'kring',cx:x,cy:y,r:1.1,fill:'#9ff6ff'},g)}
  const [ex,ey]=E.S(E.P(F,t0+.36));el('path',{d:`M${ex} ${ey+3}L${ex} ${ey-1}M${ex} ${ey-1}q-3 -1 -3 -4q3 0 3 4M${ex} ${ey-1}q3 -1 3 -4q-3 0 -3 4`,fill:'#b7bdc0',stroke:'#b7bdc0','stroke-width':.7},g);   // the seed emblem
  // the lit glass doorway between the front feet, and the pale ramp that comes down from it
  const door=[E.P(F-.3,t0+.004),E.P(F+.3,t0+.004),E.P(F+.3,t0+.22),E.P(F,t0+.29),E.P(F-.3,t0+.22)].map(E.S);el('polygon',{class:'kdoor',points:pts(door),fill:'#c3f2fb',stroke:'#5a6266','stroke-width':1.2},g);
  el('ellipse',{class:'kglow',cx:KDOOR[0],cy:KDOOR[1]-8,rx:10,ry:12,fill:'url(#kglowg)',opacity:.5},g);
  const d0=E.rad(t0)+.03,d1=2.25,u=[Math.SQRT1_2,Math.SQRT1_2],wv=[.2,-.2],Q=(d,s,z)=>E.S([u[0]*d+wv[0]*s,u[1]*d+wv[1]*s,z]);
  facet(g,[Q(d0,1,4),Q(d0,-1,4),Q(d1,-1,0),Q(d1,1,0)],shade('#d8dcd8','top'));
  for(const f of FACETS?[.25,.5,.75]:[.5]){const d=d0+(d1-d0)*f,z=4*(1-f);line([Q(d,1,z),Q(d,-1,z)],{stroke:'#aeb4b0','stroke-width':.7})}
  if(FACETS)for(const s of [1,-1])line([Q(d0,s*1.05,10),Q(d1-.1,s*1.05,5)],{stroke:'#eef1ee','stroke-width':.9});   // its handrails
  return E}
// ---- end of the low-poly helpers
"""

PAGES['map'] = (r"""
/* New Eridian as a living SEED-style colony, built for broadcast (960×540 source recommended): lawn plots between pale
   sidewalks, flat-roofed modules, farms of soil beds, a misty forest horizon and the Kernel at the centre, where new Seedlings
   step out. Districts fill with buildings as the society grows; Seedlings walk the streets and talk; a camera drifts in on
   whoever is speaking; sky, weather and holidays show. */
body{padding:0}.wrap{position:fixed;inset:0;overflow:hidden;background:#1d1a24}
svg{position:absolute;inset:0;width:100%;height:100%;display:block}
/* The scenery reaches past the 16:9 frame (overflow visible), so any source shape is filled edge to edge. */
#stage{position:absolute;inset:0;overflow:hidden}#map{overflow:visible}
.vig{position:absolute;inset:0;pointer-events:none;background:radial-gradient(ellipse at 50% 50%,transparent 62%,rgba(0,0,0,.45))}
#world{transition:transform 2.8s cubic-bezier(.45,.05,.3,1)}
.token .shirt{stroke:#0b0f24;stroke-width:2}
/* On the full map tokens are drawn at SEEDLING_SCALE, so the initial and the name are a little larger inside them to read at 1080p.
   The card keeps tokens at their original size, with the original text. */
.token .ini{font:900 12px var(--font-body);fill:#08101f;text-anchor:middle;dominant-baseline:central}
.token .label{font:800 13.5px var(--font-body);fill:#fffaf0;text-anchor:middle;paint-order:stroke;stroke:#060816;stroke-width:4px}
.L-card .token .ini{font-size:11px}.L-card .token .label{font-size:11px;stroke-width:3.5px}
.token.walking .leg{animation:step .32s ease-in-out infinite alternate}.token.walking .leg.r{animation-delay:-.32s}
.token.walking .bod{animation:bob .32s ease-in-out infinite alternate}
.token .arm{transform-box:fill-box;transform-origin:50% 10%}.token.walking .arm.l{animation:swing-l .32s ease-in-out infinite alternate}.token.walking .arm.r{animation:swing-l .32s ease-in-out infinite alternate-reverse}
@keyframes swing-l{from{transform:rotate(22deg)}to{transform:rotate(-22deg)}}.token.waving .arm.r{animation:wave .45s ease-in-out 4 alternate}@keyframes wave{from{transform:rotate(-140deg)}to{transform:rotate(-175deg)}}
.token .eyes{transition:transform .25s}
@keyframes step{to{transform:translateY(-3px)}}@keyframes bob{to{transform:translateY(-1.5px)}}
.bubble .pop{transform-box:fill-box;transform-origin:50% 100%}   /* the outer group scales about the Seedling; only the pop-in uses the bubble's own box */
@keyframes pop{from{opacity:0;transform:scale(.4)}to{opacity:1;transform:none}}
.bubble text{font:800 12px var(--font-body);fill:#171230;dominant-baseline:central}
.more text{font:900 13px var(--font-body);fill:#fff;text-anchor:middle;dominant-baseline:central}
.dlabel{transition:opacity .6s var(--ease)}.dlabel text{font:900 16px var(--font-body);letter-spacing:.05em;dominant-baseline:central;text-anchor:middle}
.dlabel .lvl{font:800 12px var(--font-body);fill:#fffaf0;opacity:.85}
.rise{animation:rise 1.2s cubic-bezier(.2,1.2,.4,1) both;transform-box:fill-box;transform-origin:50% 100%}
@keyframes rise{from{opacity:0;transform:scaleY(.05)}to{opacity:1;transform:none}}
.smoke{animation:smoke 4.5s ease-out infinite;transform-box:fill-box;transform-origin:center}
@keyframes smoke{0%{opacity:.6;transform:translate(0,0) scale(.6)}100%{opacity:0;transform:translate(10px,-30px) scale(2)}}
.ripple{animation:ripple 3s ease-out infinite;transform-box:fill-box;transform-origin:center}@keyframes ripple{0%{opacity:.8;transform:scale(.4)}100%{opacity:0;transform:scale(1.5)}}
.beacon{animation:beacon 1.6s steps(2) infinite}@keyframes beacon{50%{opacity:.15}}
.hook{animation:swing 3s ease-in-out infinite alternate;transform-box:view-box}@keyframes swing{from{transform:translateX(-6px)}to{transform:translateX(6px)}}
.shopper{animation:bob 1.1s ease-in-out infinite alternate}
.cloud{animation:cloud linear infinite}@keyframes cloud{from{transform:translateX(-260px)}to{transform:translateX(1220px)}}
.shade{animation:shade linear infinite}@keyframes shade{from{transform:translate(-520px,-120px)}to{transform:translate(620px,160px)}}
.shuttle{animation:launch 9s ease-in infinite}@keyframes launch{0%,55%{opacity:0;transform:translate(0,0)}60%{opacity:1}100%{opacity:0;transform:translate(260px,-330px)}}
.burst circle{animation:burst 1.5s ease-out forwards}@keyframes burst{from{transform:translate(0,0);opacity:1}to{transform:translate(var(--dx),var(--dy));opacity:0}}
.twinkle{animation:twinkle 2.4s ease-in-out infinite alternate}@keyframes twinkle{to{opacity:.25}}
.head{position:absolute;left:0;right:0;top:0;height:8.5vh;display:flex;align-items:center;gap:1.2vw;padding:0 1.6vw;
  background:linear-gradient(180deg,rgba(6,9,28,.92),rgba(6,9,28,.72));border-bottom:2px solid rgba(147,154,255,.45);font-size:clamp(12px,min(2.2vw,3.9vh),44px);z-index:3}
.head .name{font:700 1.15em var(--font-display);color:var(--ivory);white-space:nowrap}.head .tier{padding:.12em .55em;border-radius:.5em;background:rgba(126,227,176,.18);border:1px solid rgba(126,227,176,.55);color:var(--green2);font-weight:900;font-size:.8em;white-space:nowrap}
.head .hol{padding:.12em .55em;border-radius:.5em;font-weight:900;font-size:.8em;white-space:nowrap;color:#1a1026;background:var(--hol,#ffd27a)}.head .hol:empty{display:none}
.head .info{margin-left:auto;color:#e6e3fb;font-weight:700;font-size:.8em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* Caption: who and what on the first line, what they say below (wraps to two lines, never spills). */
/* The caption and banners sit in the empty corners outside the town, so they never cover buildings. */
.cap{position:absolute;right:1.4vw;width:34vw;bottom:1.4vh;display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;column-gap:.6em;padding:.3em .8em;border-radius:.6em;
  background:rgba(250,248,240,.95);color:#171230;font-size:clamp(10px,min(1.75vw,3.1vh),36px);line-height:1.2;box-shadow:0 .3em 1em rgba(0,0,0,.4);z-index:3;transition:opacity .5s;overflow:hidden}
.cap .mood{font-size:1.5em;line-height:1}.cap .text{min-width:0;overflow:hidden}
.cap .top{font-size:.8em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.cap .who{font-weight:900}.cap .what{color:#5b3fd1;font-weight:800}
.cap .said{font-style:italic;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow-wrap:anywhere}
.cap.hide{opacity:0}
.stats{position:absolute;left:1.2vw;top:10.5vh;width:21vw;padding:.55em .7em .6em;border-radius:.7em;z-index:3;font-size:clamp(9px,min(1.3vw,2.35vh),26px);
  background:linear-gradient(145deg,rgba(10,14,40,.9),rgba(26,17,56,.86));border:1px solid var(--edge);box-shadow:var(--shadow);color:var(--text);transition:opacity .6s var(--ease)}
.stats .tl{display:flex;align-items:baseline;gap:.4em;font:600 1.05em var(--font-display);white-space:nowrap}.stats .tl b{color:var(--green2)}.stats .tl span{margin-left:auto;font:800 .9em var(--font-body);color:var(--amber)}
.stats .meter{height:.42em;border-radius:99px;background:rgba(255,255,255,.1);overflow:hidden}.stats .meter i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--green),var(--violet));transition:width 1s var(--ease)}
.stats .big{height:.55em;margin:.3em 0 .45em}.stats .grid{display:grid;grid-template-columns:1fr 1fr;gap:.28em .7em}
.stats .m{display:grid;grid-template-columns:1.2em 1fr auto;align-items:center;gap:.3em;font-size:.82em}.stats .m em{font-style:normal;font-weight:800;font-variant-numeric:tabular-nums;min-width:2.4em;text-align:right}
.stats .m.low em{color:var(--amber)}.stats .m.low .meter i{background:linear-gradient(90deg,#ffb36b,#ffd27a)}
.stats .next{margin-top:.45em;padding-top:.35em;border-top:1px solid var(--edge-soft);font-size:.8em;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.stats .next b{color:var(--text)}
.stats.hide{opacity:0}
.L-narrow .cap{left:1.4vw;right:1.4vw;width:auto;bottom:1.2vh;font-size:clamp(12px,min(4.2vw,4.4vh),34px)}
.L-narrow .head{height:auto;flex-wrap:wrap;row-gap:.1em;padding:.35em .6em;font-size:clamp(11px,min(4.4vw,4.6vh),36px)}.L-narrow .head .info{margin-left:0;width:100%;font-size:.74em}
/* 'card' layout for a side column (e.g. 340×440): header, town, caption and stats stacked, none on top of another.
   District names become large icon badges and Seedlings are drawn bigger, so they read at column size. */
.L-card .wrap{display:flex;flex-direction:column;border-radius:.9em;border:2px solid var(--edge);background:#1d1a24}
.L-card #stage{position:relative;inset:auto;flex:1 1 0;min-height:0;order:1}
.L-card .head{position:relative;order:0;height:auto;flex:none;flex-wrap:wrap;row-gap:.15em;padding:.35em .6em;gap:.45em;font-size:clamp(11px,4.8vw,34px)}
.L-card .head .info{margin-left:0;width:100%;font-size:.72em}
.L-card .cap{position:relative;order:2;right:auto;bottom:auto;width:auto;margin:.35em .45em 0;font-size:clamp(11px,4.3vw,30px);flex:none}
.L-card .stats{position:relative;order:3;left:auto;top:auto;width:auto;margin:.35em .45em .45em;font-size:clamp(10px,3.9vw,28px);flex:none}
.L-card .toast{left:.5em;right:.5em;max-width:none;text-align:center;font-size:clamp(11px,4.2vw,30px);white-space:normal}
.q-low .smoke,.q-low .shade,.q-low .cloud,.q-low .shopper{display:none}.q-low .ripple,.q-low .beacon,.q-low .hook{animation:none}
.q-high .dlabel{filter:drop-shadow(0 2px 3px rgba(0,0,0,.55))}
/* The Kernel: its ring pulses softly on high quality and flares when a Seedling steps out; --glow (set by the hour) brightens it at night. */
#kernel .kglow{opacity:var(--glow,.4);transition:opacity 2s}.q-high #kernel .kring{animation:kpulse 3.4s ease-in-out infinite}@keyframes kpulse{50%{opacity:.55}}
#kernel.surge .kglow{opacity:1;transition:opacity .3s}#kernel.surge .kring{stroke-width:2.6}
.spawn{transform-box:fill-box;transform-origin:center;animation:spawn 2s ease-out forwards}@keyframes spawn{0%{opacity:0;transform:scale(.3)}20%{opacity:1}100%{opacity:0;transform:scale(2)}}
.q-high .neon{animation:neon 4s steps(1) infinite}@keyframes neon{0%,92%,96%{opacity:1}94%{opacity:.6}}
.shimmer{animation:shimmer 3.2s ease-in-out infinite}@keyframes shimmer{0%,100%{opacity:0;transform:translateX(-4px)}50%{opacity:.85;transform:translateX(4px)}}
.flag{animation:flag 1.4s ease-in-out infinite alternate;transform-box:fill-box;transform-origin:0 50%}@keyframes flag{from{transform:skewY(6deg) scaleX(.92)}to{transform:skewY(-6deg) scaleX(1)}}
.toast{position:absolute;right:1.6vw;top:10.5vh;transform:translateY(-30%) scale(.9);transform-origin:100% 0;opacity:0;padding:.35em .9em;border-radius:.6em;z-index:4;white-space:nowrap;max-width:44vw;overflow:hidden;text-overflow:ellipsis;
  font:900 clamp(11px,min(1.9vw,3.4vh),40px) var(--font-body);color:#1a1026;background:linear-gradient(90deg,#ffe08a,#ffb86b);box-shadow:0 .3em 1.2em rgba(0,0,0,.45);transition:opacity .5s,transform .5s cubic-bezier(.2,1.3,.4,1)}
.toast.show{opacity:1;transform:none}
.head .fest{--hol:#ffd27a}
.particle{position:absolute;pointer-events:none;animation:drift linear infinite;z-index:2}
@keyframes drift{from{transform:translate(0,0) rotate(0)}to{transform:translate(var(--dx),var(--dy)) rotate(var(--rot,0deg))}}
.glitch{position:absolute;left:0;right:0;height:2.2vh;background:linear-gradient(90deg,transparent,rgba(112,221,255,.35),transparent);z-index:2;pointer-events:none;animation:glitch .5s steps(3) forwards}
@keyframes glitch{0%{opacity:1;transform:translateX(-4%)}100%{opacity:0;transform:translateX(4%)}}
""", r"""
<div class="wrap" id="wrap">
<div id="stage"><svg id="map" viewBox="0 0 960 540" preserveAspectRatio="xMidYMid meet">
 <defs>
  <linearGradient id="sky" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="540"><stop id="sky0" offset="0" stop-color="#2b3350"/><stop id="sky1" offset=".6" stop-color="#4a4636"/><stop id="sky2" offset="1" stop-color="#3a3527"/></linearGradient>
  <radialGradient id="domeg" cx="35%" cy="30%" r="75%"><stop offset="0" stop-color="#ffffff" stop-opacity=".95"/><stop offset=".5" stop-color="#bfe8ff" stop-opacity=".7"/><stop offset="1" stop-color="#5aa6c8" stop-opacity=".55"/></radialGradient>
  <radialGradient id="vignette" cx="50%" cy="50%" r="72%"><stop offset=".62" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".45"/></radialGradient>
  <radialGradient id="glowdot"><stop offset="0" stop-color="#ffd98a" stop-opacity=".75"/><stop offset="1" stop-color="#ffd98a" stop-opacity="0"/></radialGradient>
  <radialGradient id="sung"><stop offset="0" stop-color="#fff6d8"/><stop offset=".35" stop-color="#ffe7a0" stop-opacity=".9"/><stop offset="1" stop-color="#ffcf6b" stop-opacity="0"/></radialGradient>
  <radialGradient id="shadeg"><stop offset="0" stop-color="#000" stop-opacity=".22"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>
  <linearGradient id="mistg" x1="0" y1="0" x2="0" y2="1"><stop id="mist0" offset="0" stop-color="#9fd0c4" stop-opacity="0"/><stop id="mist1" offset="1" stop-color="#9fd0c4" stop-opacity=".8"/></linearGradient>
  <radialGradient id="kglowg"><stop offset="0" stop-color="#9ff6ff" stop-opacity=".9"/><stop offset="1" stop-color="#5fe6ff" stop-opacity="0"/></radialGradient>
  <linearGradient id="aurorag" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#7ee3b0" stop-opacity="0"/><stop offset=".5" stop-color="#7ee3b0" stop-opacity=".45"/><stop offset="1" stop-color="#70ddff" stop-opacity="0"/></linearGradient>
 </defs>
 <rect x="-2000" y="-2000" width="4960" height="4540" fill="url(#sky)"/><g id="stars"></g><g id="aurora"></g><g id="sun"></g><g id="skyclouds"></g>
 <g id="hills"></g><g id="hills2"></g>
 <g id="world" style="transform:translate(480px,282px) scale(1.15) translate(-480px,-254px)">
  <g id="ground"></g><path id="shadows" fill="#141428" opacity="0" style="transition:opacity 4s"/><g id="city"></g><g id="festive"></g><g id="civic"></g><g id="crowd"></g><g id="shades"></g>
  <rect id="tint" x="-600" y="-400" width="2160" height="1400" fill="transparent" style="pointer-events:none;transition:fill 4s"/>
  <rect id="haze" x="-600" y="-400" width="2160" height="1400" fill="transparent" style="pointer-events:none;transition:fill 4s"/>
  <g id="lights" style="pointer-events:none"></g><g id="labels"></g><g id="tokens"></g>
 </g>
 <g id="fx"></g>
</svg><div class="vig"></div></div>
<div class="head"><span class="name">🏙️ New Eridian</span><span class="tier" id="tier">—</span><span class="hol" id="hol"></span><span class="hol fest" id="fest"></span><span class="info" id="info">Connecting to Avesta…</span></div>
<div class="toast" id="toast"></div><div class="stats hide" id="stats"></div>
<div class="cap hide" id="cap"></div>
</div>
<script>
const NS='http://www.w3.org/2000/svg',el=(t,a,parent)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(parent)parent.appendChild(e);return e};
function rng(seed){let h=2166136261;for(const c of String(seed))h=Math.imul(h^c.charCodeAt(0),16777619);return()=>{h+=0x6D2B79F5;let t=h;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return((t^t>>>14)>>>0)/4294967296}}
// ---- the isometric grid: 20×20 tiles, three 6×6 blocks per side with two streets between them
const N=20,TW=38,TH=19,OX=480,OY=64;
const iso=(i,j)=>[OX+(i-j)*TW/2,OY+(i+j)*TH/2];
const ROAD=new Set([6,13]);
const CELLS={spaceport_quarter:[0,0],research_block:[0,1],agricultural_district:[0,2],industrial_ward:[1,0],commons:[1,1],market_concourse:[2,1],frontier_edge:[2,0],residential_ring:[2,2],park:[1,2]};
const cellTiles=(r,c)=>[r*7,c*7];   // top-left tile (i,j) of a 6×6 block
const RESERVE=3;   // tiles kept free in every district for landmarks the colony votes to build (the Commons keeps one more for a season monument)
const LOOK={commons:['🌱','The Kernel','#8ff3ff'],residential_ring:['🏠','Homes','#ffd27a'],agricultural_district:['🌾','Farms','#9be37e'],industrial_ward:['🏭','Industry','#ff9a76'],
  research_block:['🔬','Research','#70ddff'],market_concourse:['🪙','Market','#ffd27a'],spaceport_quarter:['🚀','Spaceport','#bd91ff'],frontier_edge:['🧭','Frontier','#ff9ad5']};
// The colony's ground: lawn green everywhere, pale concrete sidewalks and streets, brown soil beds on the farms, rougher meadow
// where a district is not open yet and around the colony's edge. Districts differ by what stands on their plots, not by colour.
const LAWN=['#55893f','#629448'],MEADOW=['#71894a','#7f9152'],RING=['#4c7a3b','#5a8642'],CONCRETE=['#cbcfc8','#c1c6c0'],SOIL='#6a4e36',
  PLOT=['#e48a40','#9270dc'],KERB='rgba(84,92,88,.55)',ROOF=['#7a5638','#94724d','#86603f','#a98a5f'];   // plot lines: orange outside, purple inside
const MOOD={Inspired:'#ffd27a',Content:'#7ee3b0',Tired:'#9aa3c7',Hungry:'#ffb36b',Lonely:'#8fb3ff',Uneasy:'#d6a4ff',Stressed:'#ff9a76',Miserable:'#ff7484'};
const WEATHER_ICON={clear_skies:'☀️',good_growing:'🌧️',spore_drift:'🍃',dust_winds:'🌪️',busy_spaceport:'🚀',water_watch:'💧',quiet_cycle:'🌙',sensor_noise:'📡'};
const wantCard=()=>Q.get('layout')==='card'||(Q.get('layout')!=='wide'&&(innerWidth<560||innerWidth/Math.max(1,innerHeight)<=1.3));
const CARD=wantCard();if(CARD)document.body.classList.add('L-card');
// OBS often opens a Browser Source at its default size and resizes it a moment later: switch layout when that happens.
let relayout=null;addEventListener('resize',()=>{clearTimeout(relayout);relayout=setTimeout(()=>{if(wantCard()!==CARD||(!wantCard()&&(innerWidth<800||innerWidth/Math.max(1,innerHeight)<1.5)!==NARROW))location.reload()},400)});
// A wide layout in a source that is not wide (e.g. 400×400 with &layout=wide): full-width caption, two-line header.
const NARROW=!CARD&&(innerWidth<800||innerWidth/Math.max(1,innerHeight)<1.5);if(NARROW)document.body.classList.add('L-narrow');
let LS=1,TS=1;   // card layout: label and Seedling scale so they stay readable in a small source
const LZ=CARD?1:.78;   // district names are drawn about a fifth smaller on the full map, so they cover less of the town
// Seedlings are smaller on the full map; the column card is already a miniature and keeps their original size.
// The layout is fixed for the page's life (a resize that changes it reloads the page), so TOKEN never changes.
const SEEDLING_SCALE=""" + repr(SEEDLING_SCALE) + r""",TOKEN=CARD?1:SEEDLING_SCALE,TK=()=>TOKEN*TS;   // TK() is the scale tokens end up at, with the card's own TS
const FOCUS=CELLS[Q.get('focus')]?Q.get('focus'):'';   // &focus=commons (or any district): hold the camera close on it, for a preview or a fixed shot
const QUALITY=['low','high'].includes(Q.get('quality'))?Q.get('quality'):'normal';document.body.classList.add('q-'+QUALITY);
const SHOW_NAMES=Q.get('names')==='1',PER_PLACE=Number(Q.get('per')||(Q.get('layout')==='card'||innerWidth<560||innerWidth/Math.max(1,innerHeight)<=1.3?3:4)),CAMERA=Q.get('camera')!=='0',SECONDS=Number(Q.get('seconds')||7)*1000;
// Holidays: colours, and what the town puts up for each.
const HOLIDAYS={'New Year':['🎆',['#ffd35a','#c9d3ff','#ff5ad1'],'newyear'],"Valentine's Day":['💝',['#ff5a8a','#ffb3c8','#ffffff'],'valentine'],
  'Memorial Day':['🇺🇸',['#d9303a','#ffffff','#2d5bd8'],'flag'],"Father's Day":['👔',['#3f7fd8','#8fd3ff','#ffd35a'],'grill'],'Independence Day':['🇺🇸',['#d9303a','#ffffff','#2d5bd8'],'flag'],
  'Labor Day':['🛠️',['#ffb000','#2d5bd8','#ffffff'],'labor'],'Halloween':['🎃',['#ff7a1a','#8a3ffc','#2b2b2b'],'halloween'],'Thanksgiving':['🦃',['#d9771f','#a8431a','#ffcf5a'],'feast'],
  'Christmas':['🎄',['#e0303a','#2fa84f','#ffd35a'],'christmas']};
function previewHoliday(){const q=(Q.get('holiday')||'').toLowerCase().replace(/[^a-z]/g,'');if(!q)return null;const name=Object.keys(HOLIDAYS).find(n=>n.toLowerCase().replace(/[^a-z]/g,'').startsWith(q));
  return name?{name,emoji:HOLIDAYS[name][0],days_to_holiday:Number(Q.get('days')||0)}:null}
function diamond(i,j,w=1,h=1,inset=0){const a=iso(i+inset,j+inset),b=iso(i+w-inset,j+inset),c=iso(i+w-inset,j+h-inset),d=iso(i+inset,j+h-inset);return [a,b,c,d]}
const pts=p=>p.map(q=>q.join(',')).join(' ');
const up=(p,h)=>p.map(([x,y])=>[x,y-h]);
const vr=rng('lamps');
""" + LOWPOLY_JS + r"""

// ---- building parts (all drawn on a tile at i,j; w×d tiles; height h). Everything is a box lit by shade(): left walls in light,
// right walls in shade, with the colony's look: plain pale walls, flat roof slabs, warm window strips.
const CASTERS=[];
function box(g,i,j,w,d,h,color,opt={}){const z=opt.z||0,base=diamond(i,j,w,d,opt.inset??.12),[t,r,b,l]=up(base,z),top=up([t,r,b,l],h);
  if(!z&&!opt.noshadow)CASTERS.push([base,h+(opt.roof==='pitched'?h*.4:0)]);
  el('polygon',{points:pts([l,b,top[2],top[3]]),fill:shade(color,'left')},g);el('polygon',{points:pts([b,r,top[1],top[2]]),fill:shade(color,'right')},g);
  if(opt.roof==='pitched'){const rise=h*.55+6,apex=[(top[0][0]+top[2][0])/2,(top[0][1]+top[2][1])/2-rise],rc=opt.roofColor||'#9a5a44',s=rise/((1-2*(opt.inset??.12))*Math.min(w,d)*U/2);
    // four roof planes, each lit by its own slope: back-left, back-right, then the two in front
    for(const [p,n] of [[[top[3],top[0],apex],[-s,0,1]],[[top[0],top[1],apex],[0,-s,1]],[[top[3],top[2],apex],[0,s,1]],[[top[2],top[1],apex],[s,0,1]]])el('polygon',{points:pts(p),fill:shade(rc,n)},g)}
  else if(!opt.notop)el('polygon',{points:pts(top),fill:opt.topColor?shade(opt.topColor,'top'):shade(color,'top',1.08)},g);
  // windows: a warm strip of glass on each wall per floor (or a pair of panes); cream by day, lit or dark at night (see liveTown)
  if(opt.windows){const pair=opt.windows==='pair',rows=Math.max(1,Math.floor((h-2)/8));
    for(let k=0;k<rows;k++){const lo=3+k*8,hi=lo+3.4;for(const [A,B] of [[l,b],[b,r]])for(const [f0,f1] of pair?[[.14,.42],[.58,.86]]:[[.16,.84]]){
      const P=(f,y)=>[A[0]+(B[0]-A[0])*f,A[1]+(B[1]-A[1])*f-y],q=[P(f0,lo),P(f1,lo),P(f1,hi),P(f0,hi)];
      el('polygon',{class:'win',points:pts(q),fill:'#ecdfac','data-v':vr().toFixed(3),'data-x':((q[0][0]+q[1][0])/2).toFixed(1),'data-y':((q[0][1]+q[2][1])/2).toFixed(1)},g)}}}
  return top}
function centre(i,j,w=1,d=1){return iso(i+w/2,j+d/2)}
function tree(g,i,j,r,kind){const [x,y]=centre(i+(r()-.5)*.5,j+(r()-.5)*.5);lowPolyTree(g,x,y,r,kind)}
// A colony module: pale walls, a flat roof slab that overhangs a little, warm windows; on the roof a garden, a pool or solar panels.
function module_(g,i,j,h,wall,roof,o={}){const w=o.w||1,d=o.d||1,e=o.inset??.16;box(g,i,j,w,d,h,wall,{windows:o.windows??true,inset:e,notop:true});
  const top=box(g,i,j,w,d,2.6,roof,{inset:e-.05,z:h,noshadow:true}),patch=(c,k,ii=i,jj=j,ww=w,dd=d)=>facet(g,up(diamond(ii,jj,ww,dd,e+k),h+2.65),c);
  if(o.garden)patch(shade('#7fb04f','top'),.12);
  if(o.pool)patch('#8fd6e6',.22);
  if(o.solar&&FACETS)for(const f of [0,.5])patch(shade('#3d4c66','top'),.1,i+f*w,j,w*.5,d);
  return top}
// A small white dome hut with a coloured door.
function domeHut(g,i,j,door,c='#eceeed'){const E=ovoid(g,i+.5,j+.5,.34,10,()=>c,{c:0,n:FACETS?8:6,bands:FACETS?[0,.45,.8,1]:[0,1]});
  const F=Math.PI/4;facet(g,[E.P(F-.32,0),E.P(F+.32,0),E.P(F+.32,.5),E.P(F-.32,.5)].map(E.S),door)}
// A long barracks or greenhouse with a rounded roof, lying along i.
function barrack(g,i,j,len,wid,h,c,glass){box(g,i,j,len,wid,h,c,{inset:.06,notop:true,windows:glass?false:'pair'});
  const a=[i+.06,i+len-.06],b0=j+.06,b1=j+wid-.06,seg=FACETS?4:2,arc=k=>{const th=Math.PI*k/seg;return [b0+(b1-b0)*(1-Math.cos(th))/2,h+Math.sin(th)*wid*U*.32]};   // the vault, as strips
  for(let k=0;k<seg;k++){const [j0,z0]=arc(k),[j1,z1]=arc(k+1),n=[0,-(z1-z0)/((j1-j0)*U||1),1],q=[up([iso(a[0],j0)],z0)[0],up([iso(a[1],j0)],z0)[0],up([iso(a[1],j1)],z1)[0],up([iso(a[0],j1)],z1)[0]];
    facet(g,q,shade(glass?'#d5ece8':c,n),glass?{opacity:.92}:{})}
  if(glass)for(const f of [.33,.66]){const x=i+len*f,q=[0,1,2,3,4].map(k=>{const th=Math.PI*k/4;return up([iso(x,b0+(b1-b0)*(1-Math.cos(th))/2)],h+Math.sin(th)*wid*U*.32)[0]});el('polyline',{points:pts(q),fill:'none',stroke:'#f4f7f6','stroke-width':.8},g)}}
// A cylinder (tanks, silos): its lit and shaded halves, a darker foot and a pale lid.
function drum(g,x,y,rx,h,c){el('ellipse',{cx:x,cy:y,rx,ry:rx/2,fill:shade(c,'right',.9)},g);
  if(FACETS){el('rect',{x:x-rx,y:y-h,width:rx,height:h,fill:shade(c,toward(-1,0))},g);el('rect',{x,y:y-h,width:rx,height:h,fill:shade(c,toward(1,0))},g)}
  else el('rect',{x:x-rx,y:y-h,width:2*rx,height:h,fill:shade(c,'left')},g);
  el('ellipse',{cx:x,cy:y-h,rx,ry:rx/2,fill:shade(c,'top',1.12)},g)}
// Crates: a small stack of boxes.
function crates(g,i,j,r){const C=['#a8743f','#c48a4a','#8b6a48','#d08a3a'];box(g,i+.2,j+.25,.32,.32,4,C[Math.floor(r()*4)],{inset:0});box(g,i+.55,j+.2,.28,.3,3.5,C[Math.floor(r()*4)],{inset:0});
  box(g,i+.22,j+.27,.28,.28,3.4,C[Math.floor(r()*4)],{inset:.02,z:4,noshadow:true})}
// A modern street lamp: a slim pole with an angled arm; its head lights up at night.
function streetLamp(g,x,y,h=17,s=1,cls=''){el('polyline',{class:cls,points:pts([[x,y],[x,y-h],[x+4.5*s,y-h-2]]),fill:'none',stroke:'#dfe4e2','stroke-width':1.2,'stroke-linejoin':'round'},g);
  el('circle',{class:(cls+' win lamp').trim(),cx:x+4.5*s,cy:y-h-1.4,r:1.5,fill:'#e3e8e8','data-v':'0'},g)}
// String lights between posts: the bulbs are the dots of one dashed line, so a whole string costs one shape.
function stringLights(g,P,cls='bulbs'){el('path',{d:'M'+P.map(p=>p[0].toFixed(1)+' '+(p[1]-12).toFixed(1)).join('L'),fill:'none',stroke:'#5b4a38','stroke-width':.5,class:cls+'-wire'},g);
  for(const p of P)el('line',{x1:p[0],y1:p[1],x2:p[0],y2:p[1]-13,stroke:'#7a6248','stroke-width':1},g);
  el('path',{class:cls,d:P.slice(1).map((p,k)=>{const q=P[k],mx=(p[0]+q[0])/2,my=(p[1]+q[1])/2-9;return `M${q[0]} ${q[1]-12}Q${mx} ${my} ${p[0]} ${p[1]-12}`}).join(''),fill:'none',stroke:'#f6ecc8','stroke-width':2,'stroke-linecap':'round','stroke-dasharray':'.1 3.4'},g)}
// A parasol: a pole and a striped canopy.
function parasol(g,x,y,c1='#f2c632',c2='#f7f5ec',h=11,rx=7){el('line',{x1:x,y1:y,x2:x,y2:y-h,stroke:'#d8dcd8','stroke-width':1},g);el('ellipse',{cx:x,cy:y-h,rx,ry:rx*.42,fill:c2},g);
  el('path',{d:[0,2,4,6].map(k=>{const a0=k/8*Math.PI*2,a1=(k+1)/8*Math.PI*2;return `M${x} ${y-h-2}L${x+Math.cos(a0)*rx} ${y-h+Math.sin(a0)*rx*.42}L${x+Math.cos(a1)*rx} ${y-h+Math.sin(a1)*rx*.42}Z`}).join(''),fill:c1},g)}
// A glowing purple neon panel on a building's left wall.
function neon(g,i,j,h,inset=.16){const [t,r,b,l]=diamond(i,j,1,1,inset),P=(f,y)=>[l[0]+(b[0]-l[0])*f,l[1]+(b[1]-l[1])*f-y],q=[P(.22,h*.45),P(.62,h*.45),P(.62,h*.9),P(.22,h*.9)];
  el('polygon',{class:'neon',points:pts(q),fill:'#b06cf0',stroke:'#e6c8ff','stroke-width':.8},g);if(FACETS)el('polygon',{class:'neon',points:pts(q),fill:'none',stroke:'#c78bff','stroke-width':4,opacity:.3},g)}
const BUILD={
 residential_ring(g,i,j,r,n,level){if(n%7===6)return tree(g,i,j,r);
   if(level>=6&&n%5===0)return module_(g,i,j,20+r()*5,'#d9dcd8',ROOF[Math.floor(r()*ROOF.length)],{garden:true,pool:r()<.4});   // two-storey modules as the district grows
   if(n%6===3)return domeHut(g,i,j,['#e07a3a','#4f8fd8','#d8b23c','#7ec36b'][Math.floor(r()*4)]);
   module_(g,i,j,9+r()*4,['#dcdfdc','#cfd4d2','#e4e3dc'][Math.floor(r()*3)],ROOF[Math.floor(r()*ROOF.length)],{garden:r()<.2,windows:r()<.5?'pair':true})},
 agricultural_district(g,i,j,r,n){if(n%9===4)return barrack(g,i,j+.18,1,.64,8,'#efe6d4');
   if(n%9===8)return barrack(g,i,j+.18,1,.64,7,'#d6ece8',true);
   if(n===2){const [x,y]=centre(i,j);return water(g,x,y,12,6,{seed:'farmpond',rim:'#8a7a5a'})}
   if(n%9===6)return crates(g,i,j,r);
   // a soil plot: a grid of brown beds, each with a row of crops (leafy greens, or vegetables that turn orange as they ripen)
   const v=r().toFixed(3),veg=r()<.4?'1':'0',beds=FACETS?[[0,0],[.5,0],[0,.5],[.5,.5]]:[[0,0]],s=FACETS?.5:1;
   for(const [di,dj] of beds){const [t,rr,b,l]=diamond(i+di,j+dj,s,s,FACETS?.045:.07);facet(g,[t,rr,b,l],shade(SOIL,'top',.94+r()*.12));
     for(const f of FACETS?[.5]:[.33,.66])el('line',{class:'crop','data-v':v,'data-veg':veg,x1:t[0]+(l[0]-t[0])*f,y1:t[1]+(l[1]-t[1])*f,x2:rr[0]+(b[0]-rr[0])*f,y2:rr[1]+(b[1]-rr[1])*f,stroke:'#6aa547','stroke-width':2.4,'stroke-linecap':'round','stroke-dasharray':'.1 2.8'},g)}},
 industrial_ward(g,i,j,r,n){if(n%5===2){const [x,y]=centre(i,j);drum(g,x-3,y+1,7,13,'#a7adb2');return drum(g,x+5,y-2,5,9,'#9aa1a6')}
   const h=13+r()*7,top=module_(g,i,j,h,['#aab0b3','#9ea5a9','#b6babb'][Math.floor(r()*3)],r()<.5?'#7c8387':'#94724d',{solar:r()<.45,windows:'pair',inset:.1});const cx=top[1][0]-6,cy=top[1][1];
   if(n%3===0){el('rect',{x:cx-2.5,y:cy-16,width:5,height:16,fill:'#5c6268'},g);el('rect',{x:cx-2.5,y:cy-16,width:5,height:3,fill:'#a8564a'},g);
     for(let k=0;k<2;k++)el('circle',{class:'smoke',cx:cx,cy:cy-20,r:4,fill:'#d8d3ca','data-v':r().toFixed(3),style:`animation-delay:-${(k*2.2+r()*2).toFixed(1)}s`},g)}},
 research_block(g,i,j,r,n){if(n%6===0){box(g,i,j,1,1,8,'#e3e7e8');const [x,y]=centre(i,j);el('ellipse',{cx:x,cy:y-12,rx:9,ry:4,fill:'#f2f4f5',stroke:'#93a6b5','stroke-width':1.2,transform:`rotate(-25 ${x} ${y-12})`},g);el('line',{x1:x,y1:y-12,x2:x+4,y2:y-22,stroke:'#93a6b5','stroke-width':1.5},g);return}
   if(n%6===3){const [x,y]=centre(i,j);box(g,i,j,1,1,6,'#dfe4e6');el('ellipse',{cx:x,cy:y-12,rx:13,ry:10,fill:'url(#domeg)',stroke:'#eaf8ff','stroke-width':.8},g);return}
   const h=16+r()*12;module_(g,i,j,h,'#e8ecec','#b9c0be',{garden:true,pool:r()<.3});if(n%3===1)neon(g,i,j,h)},
 market_concourse(g,i,j,r,n){if(n===0){module_(g,i,j,16,'#e2ddd0','#a9845a',{garden:false});const [x,y]=centre(i,j);flag(g,x,y-24,'#ffd27a');return}
   const c=['#c9614f','#e0a83c','#5a8fbe','#78a35c','#9370c4'][Math.floor(r()*5)],top=box(g,i,j,1,1,5,'#d9d4c6',{topColor:c,inset:.2});
   el('polygon',{points:pts(top),fill:'none',stroke:'#f6f2e8','stroke-width':.8,'stroke-dasharray':'3 3'},g);
   if(n%3===0){const [x,y]=centre(i+.3,j+.35);parasol(g,x,y,c,'#f6f3ea',10,6)}},
 spaceport_quarter(g,i,j,r,n){if(n===0){box(g,i,j,1,1,40,'#dfe3e5',{windows:true,topColor:'#5f6b80'});const [x,y]=centre(i,j);flag(g,x+8,y-44,'#bd91ff');el('circle',{class:'beacon',cx:x,cy:y-46,r:3,fill:'#ff5a5a'},g);return}
   if(n===5){const [x,y]=centre(i,j),hull='#e6e9ec',fin='#b04a3c';   // a rocket on its pad: lit and shaded halves
     if(FACETS){el('polygon',{points:pts([[x-5,y-4],[x,y-4],[x,y-52],[x-5,y-40]]),fill:shade(hull,toward(-1,0))},g);el('polygon',{points:pts([[x,y-4],[x+5,y-4],[x+5,y-40],[x,y-52]]),fill:shade(hull,toward(1,0))},g)}
     else el('polygon',{points:pts([[x-5,y-4],[x+5,y-4],[x+5,y-40],[x,y-52],[x-5,y-40]]),fill:shade(hull,'left'),stroke:'#9aa3ad'},g);
     el('polygon',{points:pts([[x-5,y-4],[x-10,y+2],[x-5,y-16]]),fill:shade(fin,'left')},g);el('polygon',{points:pts([[x+5,y-4],[x+10,y+2],[x+5,y-16]]),fill:shade(fin,'right')},g);return}
   if(n%3===1){const [t,rr,b,l]=diamond(i,j,1,1,.04);el('polygon',{points:pts([t,rr,b,l]),fill:'#9fa5a6'},g);const [x,y]=centre(i,j);
     el('ellipse',{cx:x,cy:y,rx:12,ry:6,fill:'none',stroke:'#e8c766','stroke-width':1.6},g);el('text',{x:x,y:y+3,'text-anchor':'middle','font-size':8,'font-weight':900,fill:'#e8c766',transform:`scale(1 .6) translate(0 ${y/0.6-y})`},g).textContent='H';return}
   module_(g,i,j,10+r()*6,'#c9ced2',r()<.5?'#a98a5f':'#7d8590',{solar:r()<.5,inset:.1})},
 frontier_edge(g,i,j,r,n){const [x,y]=centre(i,j);if(n%4===0){el('polygon',{points:pts([[x-9,y+2],[x,y-26],[x+9,y+2]]),fill:'none',stroke:'#6e5236','stroke-width':2.5},g);el('circle',{cx:x,cy:y-24,r:3.5,fill:'#b39a74'},g);return}
   if(n%4===1)return crates(g,i,j,r);
   if(n%4===2)return domeHut(g,i,j,'#d08a3a','#e4ddcc');
   tree(g,i,j,r,r()<.6?'tall':'conifer')},
 commons(g,i,j,r,n){tree(g,i,j,r,r()<.7?'tall':'broad')},
 park(g,i,j,r,n){tree(g,i,j,r)},
};
// Scaffolding and a crane stand where a new building is about to go up.
function scaffold(g,i,j,crane){const [t,r,b,l]=diamond(i,j,1,1,.15),h=22,c='#d4a24c';
  for(const p of [t,r,b,l])el('line',{x1:p[0],y1:p[1],x2:p[0],y2:p[1]-h,stroke:c,'stroke-width':1.6},g);
  for(const k of [h/2,h])el('polygon',{points:pts(up([t,r,b,l],k)),fill:'none',stroke:c,'stroke-width':1.3},g);
  el('line',{x1:l[0],y1:l[1],x2:b[0],y2:b[1]-h,stroke:c,'stroke-width':1},g);el('line',{x1:b[0],y1:b[1],x2:r[0],y2:r[1]-h,stroke:c,'stroke-width':1},g);
  if(crane){const [x,y]=centre(i,j);el('rect',{x:x+12,y:y-62,width:3,height:62,fill:'#f2b441'},g);el('rect',{x:x-22,y:y-64,width:48,height:3,fill:'#f2b441'},g);
    const hook=el('g',{class:'hook'},g);el('line',{x1:x-14,y1:y-61,x2:x-14,y2:y-36,stroke:'#333','stroke-width':1},hook);el('rect',{x:x-19,y:y-36,width:10,height:6,fill:'#9c3b2e'},hook)}}

// ---- terrain and streets, drawn once
(function terrain(){const g=document.getElementById('ground'),lo=-1.4,hi=N+1.4;
  forest(document.getElementById('hills'),document.getElementById('hills2'));slab(g,lo,hi);
  // the land around the colony: one plain diamond on low quality, otherwise 2×2-tile facets of rougher grass that rise and fall a little
  if(!FACETS)facet(g,diamond(lo,lo,hi-lo,hi-lo),shade(RING[0],'top'));
  else{const E=[lo,...[...Array(N/2+1)].map((_,k)=>k*2),hi];for(let a=0;a<E.length-1;a++)for(let b=0;b<E.length-1;b++)if(!(E[a]>=0&&E[a+1]<=N&&E[b]>=0&&E[b+1]<=N))facetTile(g,E[a],E[b],RING,{w:E[a+1]-E[a],d:E[b+1]-E[b],seed:'ring',amp:8,cls:'ring'})}
  // its edge: shrubs, rocks and the colony's tall trees, kept off the front corner where the Homes stand
  const r=rng('wild');for(let k=0;k<50;k++){const i=-1.2+r()*(N+2.4),j=-1.2+r()*(N+2.4);if(i>-.2&&i<N+.2&&j>-.2&&j<N+.2)continue;const [x,y]=iso(i,j),v=r();
    if(v<.45)shrub(g,x,y-1,3+r()*3,r,v<.25?'#4f7a3a':'#5f8442');else if(v<.62||!FACETS||i+j>2*N-4)facetRock(g,x,y-1,2.5+r()*3,r,'#8a877e');else lowPolyTree(g,x,y,r,r()<.75?'tall':'broad')}
  const s=document.getElementById('stars');const sr=rng('stars');for(let k=0;k<140;k++){const x=-500+sr()*1960,y=-360+sr()*600;el('circle',{class:sr()<.3?'twinkle':'',cx:x,cy:y,r:.6+sr()*1.3,fill:'#fff'},s)}
  const c=document.getElementById('skyclouds');for(let k=0;k<4;k++){const cg=el('g',{class:'cloud',style:`animation-duration:${150+k*40}s;animation-delay:-${k*55}s`},c),y=70+k*28;
    for(const [dx,dy,rx] of [[0,0,34],[26,-8,26],[-24,-4,22],[48,2,20]]){if(!FACETS){el('ellipse',{cx:dx,cy:y+dy,rx,ry:rx*.45,fill:'#fff',opacity:.8},cg);continue}
      // a low-poly puff: a sunlit upper half and a greyer underside
      const P=[...Array(6)].map((_,q)=>[dx+Math.cos(q/6*Math.PI*2+.3)*rx,y+dy+Math.sin(q/6*Math.PI*2+.3)*rx*.45]);
      el('polygon',{points:pts([P[3],P[4],P[5],P[0]]),fill:'#fbfcfd',opacity:.85},cg);el('polygon',{points:pts([P[0],P[1],P[2],P[3]]),fill:'#d9dfe6',opacity:.85},cg)}}
  const sh=document.getElementById('shades');for(let k=0;k<3;k++){el('ellipse',{class:'shade',cx:300+k*120,cy:180+k*60,rx:120,ry:55,fill:'url(#shadeg)',style:`animation-duration:${80+k*25}s;animation-delay:-${k*30}s`},sh)}})();

const drawn={},levels={};let night=false,lastTier=-1,first=true,lastPhase='';
const PHASE_NEWS={Morning:'🌅 Dawn breaks over New Eridian',Day:'☀️ Full daylight on Avesta',Evening:'🌇 The sun is setting',Night:'🌙 Night falls, the lights come on'};
const LAMPS=[];for(let s=0;s<N;s+=3)for(const k of [6,13]){LAMPS.push([k+.1,s+.1],[s+.1,k+.1])}
function streets(d,tier){const g=document.getElementById('ground');g.querySelectorAll('.street').forEach(e=>e.remove());
  const unlocked=k=>k==='commons'||k==='park'||((d.districts||{})[k]||{}).unlocked;
  // the streets are wide pale concrete paths; beside districts not open yet they are older and darker
  for(let i=0;i<N;i++)for(let j=0;j<N;j++){if(!(ROAD.has(i)||ROAD.has(j)))continue;
    const near=Object.entries(CELLS).some(([k,[r,c]])=>{const [a,b]=cellTiles(r,c);return unlocked(k)&&i>=a-1&&i<=a+6&&j>=b-1&&j<=b+6});
    facetTile(g,i,j,near?CONCRETE:['#b2b3a8','#a8aa9f'],{cls:'street',seed:'road',amp:1,vary:.035})}
  // kerbs along both sides of each street, broken at the crossings, so the streets always stand out from the districts
  for(const k of [6,13])for(const e of [k,k+1])for(const [s0,s1] of [[0,6],[7,13],[14,N]])for(const [a,b] of [[iso(e,s0),iso(e,s1)],[iso(s0,e),iso(s1,e)]])
    el('line',{class:'street',x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:KERB,'stroke-width':1.1},g);
  if(tier>=2)for(const k of [6,13])for(let s=0;s<N;s++){if(ROAD.has(s))continue;const a=iso(k+.5,s+.15),b=iso(k+.5,s+.55),c=iso(s+.15,k+.5),e=iso(s+.55,k+.5);   // paving joints along the middle
    el('line',{class:'street',x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:'#e9ece8','stroke-width':1.1,opacity:.8},g);el('line',{class:'street',x1:c[0],y1:c[1],x2:e[0],y2:e[1],stroke:'#e9ece8','stroke-width':1.1,opacity:.8},g)}
  for(const [i,j] of LAMPS){const [x,y]=iso(i,j);streetLamp(g,x,y,15,i<j?-1:1,'street')}}
function flag(g,x,y,color){if(QUALITY!=='high')return;el('rect',{x:x-.6,y:y-14,width:1.2,height:14,fill:'#ddd'},g);el('polygon',{class:'flag',points:`${x+.6},${y-14} ${x+10},${y-11.5} ${x+.6},${y-9}`,fill:color},g)}
// The ground of a district: lawn plots of 2×2 tiles between pale concrete sidewalks, each plot outlined in a thin orange and a thin
// purple line. A district that is not open yet is plain meadow; the Park is all lawn; the Commons is the Kernel's square lawn plaza.
function plots(g,a,b,key){facet(g,diamond(a,b,6,6),shade(CONCRETE[0],'top'),{class:'walk'});
  for(let p=0;p<3;p++)for(let q=0;q<3;q++){const i=a+p*2,j=b+q*2;facetTile(g,i,j,LAWN,{w:2,d:2,inset:.13,seed:key+p+q,amp:3});
    plotLines(g,i,j,2,2,.2)}}
function plotLines(g,i,j,w,d,e){(FACETS?PLOT:PLOT.slice(0,1)).forEach((c,k)=>el('polygon',{class:'plotline',points:pts(diamond(i,j,w,d,e+k*.075)),fill:'none',stroke:c,'stroke-width':1,'stroke-linejoin':'round',opacity:.95},g))}
// The Kernel's plaza: picnic tables with benches, a parasol, planters and lamps around the pod.
function picnic(g,i,j){box(g,i-.45,j-.1,.9,.2,4.2,'#e9ece9',{inset:0});for(const dj of [-.36,.22])box(g,i-.45,j+dj,.9,.14,2.4,'#dde2df',{inset:0,noshadow:true})}
function planter(g,i,j){box(g,i,j,.34,.34,3.2,'#d9dcd6',{inset:0,topColor:'#78a64a'});if(FACETS){const [x,y]=centre(i,j,.34,.34);shrub(g,x,y-3.2,2.4,rng('pl'+i+j),'#6aa547')}}
function plaza(g,back){if(back){const [lx,ly]=iso(7.75,7.75);return streetLamp(g,lx,ly,17,1)}   // the lamp behind the pod, drawn before it
  const [x,y]=iso(11.95,11.05);for(const [i,j] of [[11.6,8.75],[8.75,11.6]])picnic(g,i,j);parasol(g,x,y);
  for(const [i,j] of [[12.15,10.95],[10.95,12.15]])planter(g,i,j);for(const [i,j,s] of [[12.3,8.4,1],[8.4,12.3,-1]]){const [lx,ly]=iso(i,j);streetLamp(g,lx,ly,17,s)}}
// Whether a point lies inside the Kernel's outline on screen: decorations behind it there are hidden by the pod, so they are left out.
const behindKernel=(x,y)=>{const [kx,ky]=iso(...KERNEL);return ((x-kx)/56)**2+((y-ky+36)/48)**2<1&&y<ky-4};
function district(key,info,tier){const [r,c]=CELLS[key],[a,b]=cellTiles(r,c),city=document.getElementById('city');
  let dg=drawn[key];const unlocked=key==='commons'||key==='park'||info.unlocked,level=key==='commons'?2+tier*2:key==='park'?6:(info.level||1);
  if(!dg||dg.unlocked!==unlocked){if(dg){dg.ground.remove();dg.g.remove();if(!first)toast(`🎉 ${LOOK[key]?LOOK[key][1]:'The Park'} is open for building!`,key)}
    const G=document.getElementById('ground');dg=drawn[key]={unlocked,count:0,ground:G.insertBefore(el('g',{}),G.querySelector('.street')),g:el('g',{},city)};   // under the streets, kerbs and lamps
    if(key==='commons'){facet(dg.ground,diamond(a,b,6,6),shade(CONCRETE[0],'top'),{class:'walk'});facetTile(dg.ground,a,b,LAWN,{w:6,d:6,inset:.32,seed:'plaza',amp:2});plotLines(dg.ground,a,b,6,6,.4);
      plaza(el('g',{'data-depth':15.5},dg.g),true);kernel(el('g',{id:'kernel','data-depth':20.3},dg.g));plaza(el('g',{'data-depth':21},dg.g))}
    else if(key==='park'){for(let p=0;p<3;p++)for(let q=0;q<3;q++)facetTile(dg.ground,a+p*2,b+q*2,LAWN,{w:2,d:2,seed:'park'+p+q,amp:4});
      const [x,y]=centre(a+1,b+2,3,3);el('ellipse',{cx:x,cy:y,rx:58,ry:28,fill:'none',stroke:shade(CONCRETE[0],'top'),'stroke-width':5},dg.ground);water(dg.ground,x,y,44,21,{seed:'pond',rim:'#a89c78'});   // a path around the pond
      if(QUALITY==='high')for(let k=0;k<6;k++)el('line',{class:'shimmer',x1:x-30+k*11,y1:y-10+(k%3)*9,x2:x-22+k*11,y2:y-10+(k%3)*9,stroke:'#e8f8ff','stroke-width':1.4,'stroke-linecap':'round',style:`animation-delay:-${k*.55}s`},dg.g)}
    else if(unlocked){plots(dg.ground,a,b,key);
      if(key==='agricultural_district'&&FACETS)stringLights(dg.g,[iso(a+5.9,b+.3),iso(a+5.9,b+2),iso(a+5.9,b+3.9),iso(a+5.9,b+5.7)]);   // string lights along the farm's front path
      if(key==='market_concourse'&&FACETS)stringLights(dg.g,[iso(a+.3,b+5.9),iso(a+2.1,b+5.9),iso(a+3.9,b+5.9),iso(a+5.7,b+5.9)])}
    else for(let p=0;p<2;p++)for(let q=0;q<2;q++)facetTile(dg.ground,a+p*3,b+q*3,MEADOW,{w:3,d:3,seed:key+p+q,amp:5});
    if(!unlocked){for(const [di,dj] of [[.5,.5],[5.5,.5],[.5,5.5],[5.5,5.5]]){const [x,y]=iso(a+di,b+dj);el('polygon',{points:pts([[x-3,y],[x,y-12],[x+3,y]]),fill:'#f28b3c'},dg.g)}
      const [x,y]=centre(a+3.5,b+3.5,1,1);el('rect',{x:x-14,y:y-20,width:28,height:14,rx:2,fill:'#e4e1d6',stroke:'#7d7a70'},dg.g);el('rect',{x:x-1,y:y-6,width:2,height:8,fill:'#7d7a70'},dg.g)}
    // Tile order for new buildings: fixed per district, so growth only ever adds buildings. The Commons keeps its middle for the
    // Kernel, and the front of the plaza (its ramp, tables and the Seedlings who gather there) free.
    const rr=rng('slots:'+key),busy=new Set(['12,10','10,12','12,11','11,12','12,12','12,8','8,12']);dg.slots=[];
    for(let i=a;i<a+6;i++)for(let j=b;j<b+6;j++){if(key==='commons'&&(i>a&&i<a+5&&j>b&&j<b+5||busy.has(i+','+j)))continue;if(key==='park'&&!(i===a||j===b||i===a+5||j===b+5))continue;dg.slots.push([i,j,rr()])}
    if(key!=='commons'&&key!=='park')dg.slots.sort((p,q)=>p[2]-q[2]);}
  if(!first&&unlocked&&levels[key]&&level>levels[key]&&LOOK[key]&&key!=='commons')toast(`🏗️ ${LOOK[key][1]} grew to LV ${level}`,key);
  levels[key]=level;
  const want=!unlocked?0:key==='park'?dg.slots.length:key==='commons'?Math.min(dg.slots.length-RESERVE-1,4+tier*3):Math.min(dg.slots.length-RESERVE,3+level*3);
  if(want>dg.count){const add=dg.slots.slice(dg.count,want).map((s,n)=>[...s,dg.count+n]),grow=!first;dg.count=want;
    const put=()=>{for(const [i,j,,n] of add){const g=el('g',{class:grow?'rise':'','data-depth':i+j},dg.g);BUILD[key](g,i,j,rng(key+':'+n),n,level)}
      [...dg.g.children].sort((p,q)=>(+p.dataset.depth||0)-(+q.dataset.depth||0)).forEach(e=>dg.g.appendChild(e));litSig=''};
    if(!grow)return put();
    // New buildings: scaffolding and a crane first, then the building rises.
    const sc=add.map(([i,j],n)=>{const g=el('g',{'data-depth':i+j},dg.g);scaffold(g,i,j,n===0);return g});setTimeout(()=>{sc.forEach(g=>g.remove());put()},7000)}}
let labelSig='';
function labelsFor(d){const sig=JSON.stringify(Object.entries(d.districts||{}).map(([k,v])=>[k,v.unlocked,v.level,v.unlocks_at]));if(sig===labelSig)return;labelSig=sig;for(const k in rowShift)delete rowShift[k];   // rebuilt only when a district changes
  const labels=document.getElementById('labels');labels.innerHTML='';
  for(const k in LOOK){const info=(d.districts||{})[k]||{unlocked:k==='commons',level:1},[x,y]=labelXY(k),[icon,short,color]=LOOK[k],z=LS*LZ;
    const sub=CARD?'':k==='commons'?'':info.unlocked?`LV ${info.level}`:`AT ${String(info.unlocks_at||'').toUpperCase()}`,lab=el('g',{class:'dlabel'},labels);
    const box_=el('rect',{y:y-12*z,height:24*z,rx:12*z,fill:'rgba(8,13,39,.9)',stroke:color,'stroke-width':Math.max(1.4,2*z)},lab),t=el('text',{y:y+z,fill:color,style:`font-size:${16*z}px`},lab);t.textContent=CARD?icon+(info.unlocked||k==='commons'?'':'🔒'):`${icon} ${short.toUpperCase()}`;
    lab.dataset.key=k;const s=sub?el('text',{class:'lvl',y:y+1,style:`font-size:${12*z}px`},lab):null;if(s)s.textContent=sub;const tw=t.getComputedTextLength(),sw=s?s.getComputedTextLength()+8*z:0,w=tw+sw+22*z;
    box_.setAttribute('x',x-w/2);box_.setAttribute('width',w);t.setAttribute('x',x-w/2+11*z+tw/2);if(s)s.setAttribute('x',x+w/2-11*z-sw/2+4*z)}}
// District names sit near the back of their district. The Kernel's name floats behind the pod so it never covers it, and the
// Kernel's Seedlings gather at the foot of its ramp instead of under the name.
const LABEL_AT={commons:[5,5],research_block:[1.5,10.3],industrial_ward:[10.3,1.5]},ROW_AT={commons:[12.5,12.5]};   // Research and Industry step aside for it
function labelXY(k){if(LABEL_AT[k])return iso(...LABEL_AT[k]);const [r,c]=CELLS[k]||CELLS.commons,[a,b]=cellTiles(r,c);return iso(a+1.5,b+1.5)}

// ---- the town reacts to the society: crops, smoke, lit windows and market crowds
let litSig='',crowdSig='';
function liveTown(d){const st=d.stats||{},pop=d.population||0,ds=d.districts||{},here=k=>latest.filter(s=>s.place===k).length;
  const ratio=(st.food||0)/Math.max(1,pop*20),ripe=Math.max(0,Math.min(1,(ratio-.6)/1.6)),dry=ratio<.35,wet=weatherKey==='good_growing';
  document.querySelectorAll('.crop').forEach(f=>{const v=+f.dataset.v,c=dry&&!wet?'#a5925e':v<ripe?(f.dataset.veg==='1'?'#e4772a':'#d8b44c'):wet?'#4f9a3a':'#6aa547';
    if(f.dataset.c!==c){f.dataset.c=c;f.setAttribute('stroke',c)}});
  const kg=document.getElementById('kernel');if(kg)kg.style.setProperty('--glow',(.4+.6*Math.min(1,darkness*1.4)).toFixed(2));
  document.querySelectorAll('.bulbs').forEach(b=>{b.setAttribute('stroke',darkness>.3?'#ffe28a':'#f6ecc8');b.setAttribute('stroke-width',darkness>.3?2.6:2)});
  const smokeF=Math.min(1,.15+((ds.industrial_ward||{}).level||1)/16+here('industrial_ward')*.2);
  document.querySelectorAll('.smoke').forEach(s=>{s.style.display=+s.dataset.v<smokeF?'':'none'});
  const litF=Math.min(1,.3+pop/50)*Math.max(0,Math.min(1,(darkness-.2)/.4)),sig=litF.toFixed(2)+':'+document.querySelectorAll('.win').length;
  if(sig!==litSig){litSig=sig;const lights=document.getElementById('lights'),dark=darkness>.3;lights.innerHTML='';
    // windows are warm cream by day; after dark the lit ones glow and the rest are dark glass. Lamp heads light up at night.
    document.querySelectorAll('.win').forEach((w,n)=>{const on=+w.dataset.v<litF,lamp=w.classList.contains('lamp');
      w.setAttribute('fill',lamp?(on?'#ffe6a3':'#e3e8e8'):on?'#ffd98a':dark?'#333b49':'#ecdfac');w.setAttribute('opacity',lamp&&!on&&w.tagName==='rect'?0:.95);
      if(on&&QUALITY!=='low'&&(lamp||n%3===0)){const x=+(w.dataset.x||w.getAttribute('cx')||w.getAttribute('x')),y=+(w.dataset.y||w.getAttribute('cy')||w.getAttribute('y'));
        if(QUALITY==='high'&&n%4===0)el('circle',{cx:x,cy:y,r:16,fill:'url(#glowdot)',opacity:.35},lights);if(lamp)el('ellipse',{cx:x,cy:y+15,rx:15,ry:7,fill:'url(#glowdot)',opacity:.8},lights);el('circle',{cx:x+1.5,cy:y+1.5,r:6,fill:'url(#glowdot)'},lights)}})}
  const market=(ds.market_concourse||{}).unlocked?Math.min(14,2+here('market_concourse')*2+(d.market&&d.market.primary?2:0)+Math.floor(((ds.market_concourse||{}).level||1)/2)):0;
  const party=(festival?8:0)+(voteFest?10:0),csig=market+':'+party;
  if(csig!==crowdSig){crowdSig=csig;const g=document.getElementById('crowd');g.innerHTML='';
    const people=(k,n,seed)=>{const [r,c]=CELLS[k],[a,b]=cellTiles(r,c),rr=rng(seed);for(let q=0;q<n;q++){let i,j;do{i=a+1+Math.floor(rr()*5)+.02;j=b+1+Math.floor(rr()*5)+.5+rr()*.3}while(k==='commons'&&Math.hypot(i-KERNEL[0],j-KERNEL[1])<2);const [x,y]=iso(i,j);
      const p=el('g',{class:'shopper',style:`animation-delay:-${(rr()*1.1).toFixed(2)}s`},g);el('rect',{x:x-2.5,y:y-9,width:5,height:7,rx:2,fill:['#e0564f','#4fa3e0','#7ec36b','#f2b441','#b86fd6'][Math.floor(rr()*5)]},p);el('circle',{cx:x,cy:y-11.5,r:2.4,fill:['#f1c9a5','#c68a5a','#8d5a3b'][Math.floor(rr()*3)]},p)}};
    people('market_concourse',market,'shoppers');people('commons',party,'party')}}

// ---- Seedlings: little people who walk the streets between districts and stand under the district name
const tokens=document.getElementById('tokens'),live={};let latest=[];
const SKIN=['#f1c9a5','#e0ac7e','#c68a5a','#8d5a3b','#5e3b26'],HAIR=['#2b1d14','#5a3a22','#b07a3a','#e2c27a','#7a2a1a','#c9c9d6'];
const rowShift={};
function home(k,i,n){const [lx,ly]=labelXY(k),[x,yy]=ROW_AT[k]?iso(...ROW_AT[k]):[lx,ly+12*LS*LZ+48*TK()],key=k+':'+n+':'+LS.toFixed(2)+':'+TS.toFixed(2);
  if(!(key in rowShift)){const half=(n-1)/2*30*TK()+14*TK(),extra=12*TK()+2+34*Math.max(.85,TK()),rects=[...document.querySelectorAll('#labels .dlabel')].filter(g=>g.dataset.key!==k).map(g=>{const r=g.querySelector('rect');return [+r.getAttribute('x'),+r.getAttribute('y'),+r.getAttribute('x')+(+r.getAttribute('width')),+r.getAttribute('y')+(+r.getAttribute('height'))]});
    // overlap area between the row (people, feet and the +N badge) and every other district name; pick the nearest shift with the least
    // The row stays inside its own district: a small sideways nudge or a step down the block, never into a neighbour.
    const cost=(dx,dy)=>rects.reduce((c,[l,t,r,b])=>c+Math.max(0,Math.min(r+4,x+dx+half+extra)-Math.max(l-4,x+dx-half))*Math.max(0,Math.min(b+2,yy+dy+6*TK())-Math.max(t-2,yy+dy-46*TK())),0);
    let best=[0,0],bestC=Infinity;for(const dy of [0,10,20,30])for(let dx=0;dx<=48;dx+=8)for(const d of dx?[-dx,dx]:[0]){const c=cost(d,dy)+Math.abs(d)*.6+dy*.8;if(c<bestC){bestC=c;best=[d,dy]}}rowShift[key]=best}
  const [sx,sy]=rowShift[key];return [x+sx+(i-(n-1)/2)*30*TK(),yy+sy]}
const place_=(x,y)=>`translate(${x.toFixed?x.toFixed(1):x},${y.toFixed?y.toFixed(1):y}) scale(${TK().toFixed(3)})`;
function roadFor(r,other){return r===0?6:r===2?13:(other===2?13:6)}
function route(from,to){if(from===to||!CELLS[from]||!CELLS[to])return [];const [ra,ca]=CELLS[from],[rb,cb]=CELLS[to],IA=roadFor(ra,rb),IB=roadFor(rb,ra),ja=ca*7+3,jb=cb*7+3;
  let p;if(IA===IB)p=[[IA+.5,ja],[IA+.5,jb]];else{const J=[6,13].sort((x,y)=>Math.abs(ja-x)+Math.abs(jb-x)-Math.abs(ja-y)-Math.abs(jb-y))[0];p=[[IA+.5,ja],[IA+.5,J+.5],[IB+.5,J+.5],[IB+.5,jb]]}
  return p.map(([i,j])=>iso(i,j))}
// Each job wears something recognisable: straw hats on farmers, helmets on miners, hard hats on engineers, and so on.
const HAT={farmer:'straw',cultivator:'straw',harvester:'straw',miner:'helmet',technician:'hardhat',engineer:'hardhat',safety_officer:'hardhat',firefighter:'firehat',
  researcher:'goggles',pharmacist:'goggles',medic:'medic',cook:'chef',merchant:'tophat',courier:'cap',explorer:'ranger',processor:'bandana',artisan:'bandana'};
// Cosmetic hats (season rewards, champions, trophies) replace the job hat when a citizen wears one.
const COSMETIC=new Set(['flower','viking','wizard','astronaut','beanie','party','crown','laurel','halo','antlers']);
function cosmetic(g,k){
  if(k==='flower')['#ff7aa8','#ffd35a','#fff','#b58cff','#ff9a5a'].forEach((c,n)=>el('circle',{cx:-6+n*3,cy:-36.5+(n%2),r:2,fill:c,stroke:'#7a3a4a','stroke-width':.4},g));
  if(k==='viking'){el('path',{d:'M-7.5 -33 A7.5 7 0 0 1 7.5 -33Z',fill:'#9aa3ad',stroke:'#4a4f58','stroke-width':.8},g);el('rect',{x:-8.5,y:-34,width:17,height:2,rx:1,fill:'#7a5a3a'},g);
    el('path',{d:'M-7 -36 Q-12 -40 -11 -46 Q-8 -41 -5 -38Z',fill:'#f4ecd8',stroke:'#8a7a5a','stroke-width':.5},g);el('path',{d:'M7 -36 Q12 -40 11 -46 Q8 -41 5 -38Z',fill:'#f4ecd8',stroke:'#8a7a5a','stroke-width':.5},g)}
  if(k==='wizard'){el('polygon',{points:'-8,-34 8,-34 2,-52',fill:'#6b3fd1',stroke:'#2b1a5a','stroke-width':.7},g);el('rect',{x:-9,y:-35,width:18,height:2.2,rx:1,fill:'#4a2aa0'},g);el('circle',{cx:1,cy:-43,r:1.4,fill:'#ffd35a'},g)}
  if(k==='astronaut'){el('circle',{cx:0,cy:-31,r:9.5,fill:'rgba(190,230,255,.28)',stroke:'#eef6ff','stroke-width':1.4},g);el('path',{d:'M-5 -37 A6 6 0 0 1 2 -39',fill:'none',stroke:'#fff','stroke-width':1.2,opacity:.8},g)}
  if(k==='beanie'){el('path',{d:'M-7 -33 A7 7.5 0 0 1 7 -33Z',fill:'#4fa3e0',stroke:'#2a5f8a','stroke-width':.7},g);el('rect',{x:-7.5,y:-34.5,width:15,height:2.6,rx:1.2,fill:'#e8f4ff'},g);el('circle',{cx:0,cy:-41,r:2.3,fill:'#e8f4ff'},g)}
  if(k==='party'){el('polygon',{points:'-5,-35 5,-35 0,-49',fill:'#ff5ad1',stroke:'#8a2a6a','stroke-width':.6},g);el('line',{x1:-3,y1:-39,x2:3,y2:-40,stroke:'#ffd35a','stroke-width':1.2},g);el('line',{x1:-1.5,y1:-44,x2:1.8,y2:-44.5,stroke:'#70ddff','stroke-width':1.2},g);el('circle',{cx:0,cy:-49.5,r:1.8,fill:'#ffd35a'},g)}
  if(k==='crown'){el('polygon',{points:'-7,-35 7,-35 8,-43 4,-39 0,-45 -4,-39 -8,-43',fill:'#ffd35a',stroke:'#a8781a','stroke-width':.8},g);el('circle',{cx:0,cy:-38,r:1.3,fill:'#e0303a'},g)}
  if(k==='laurel'){for(const sd of [-1,1])for(let n=0;n<4;n++)el('ellipse',{cx:sd*(6.5-n*.6),cy:-34.5-n*2.2,rx:2.4,ry:1.1,fill:'#5fae4a',transform:`rotate(${sd*(-35-n*12)} ${sd*(6.5-n*.6)} ${-34.5-n*2.2})`},g)}
  if(k==='halo')el('ellipse',{cx:0,cy:-42,rx:7,ry:2.2,fill:'none',stroke:'#ffe27a','stroke-width':1.8},g);
  if(k==='antlers'){for(const sd of [-1,1]){el('path',{d:`M${sd*4} -36 L${sd*7} -44 M${sd*6} -41 L${sd*10} -43 M${sd*6.5} -43 L${sd*5} -47`,stroke:'#8a5a3a','stroke-width':1.4,'stroke-linecap':'round',fill:'none'},g)}}}
function hat(g,job){g.innerHTML='';if(COSMETIC.has(job))return cosmetic(g,job);const k=HAT[job];if(!k)return;
  if(k==='straw'){el('ellipse',{cx:0,cy:-35,rx:10,ry:2.6,fill:'#e2c27a',stroke:'#a8862e','stroke-width':.8},g);el('path',{d:'M-5 -35 Q0 -43 5 -35Z',fill:'#e8cc86',stroke:'#a8862e','stroke-width':.8},g);el('rect',{x:-5,y:-37,width:10,height:1.6,fill:'#b8452f'},g)}
  if(k==='helmet'||k==='hardhat'||k==='firehat'){const c={helmet:'#f2c230',hardhat:'#f28b3c',firehat:'#d9303a'}[k];el('path',{d:'M-7.5 -33 A7.5 7 0 0 1 7.5 -33Z',fill:c,stroke:'#6b4a1a','stroke-width':.8},g);el('rect',{x:-9,y:-34,width:18,height:2,rx:1,fill:c},g);
    if(k==='helmet'){el('circle',{cx:0,cy:-37,r:1.8,fill:'#fff6c0'},g)}}
  if(k==='goggles'){el('rect',{x:-6.5,y:-33.5,width:13,height:4,rx:2,fill:'#5aa6c8',stroke:'#1a3a4a','stroke-width':.8},g)}
  if(k==='medic'){el('rect',{x:-6,y:-40,width:12,height:5,rx:1.5,fill:'#fff'},g);el('rect',{x:-1,y:-39.5,width:2,height:4,fill:'#e0303a'},g);el('rect',{x:-2,y:-38.5,width:4,height:2,fill:'#e0303a'},g)}
  if(k==='chef'){el('rect',{x:-5,y:-40,width:10,height:6,fill:'#fff',stroke:'#ccc','stroke-width':.6},g);el('circle',{cx:-3,cy:-41,r:3.4,fill:'#fff'},g);el('circle',{cx:3,cy:-41,r:3.4,fill:'#fff'},g);el('circle',{cx:0,cy:-43,r:3.4,fill:'#fff'},g)}
  if(k==='tophat'){el('rect',{x:-9,y:-36,width:18,height:2,rx:1,fill:'#2b2433'},g);el('rect',{x:-5,y:-45,width:10,height:10,fill:'#2b2433'},g);el('rect',{x:-5,y:-38,width:10,height:1.6,fill:'#b8452f'},g)}
  if(k==='cap'){el('path',{d:'M-6.8 -33 A6.8 6.5 0 0 1 6.8 -33Z',fill:'#3f6fa8'},g);el('rect',{x:0,y:-34,width:9,height:2,rx:1,fill:'#2d5b90'},g)}
  if(k==='ranger'){el('ellipse',{cx:0,cy:-35,rx:10,ry:2.4,fill:'#5a7a3a'},g);el('path',{d:'M-5.5 -35 Q0 -42 5.5 -35Z',fill:'#6a8a4a'},g)}
  if(k==='bandana'){el('path',{d:'M-6.8 -33 A6.8 6.5 0 0 1 6.8 -33Z',fill:'#c24b3c'},g);el('polygon',{points:'6,-33 10,-31 7,-29',fill:'#c24b3c'},g)}}
// Players' own choices (/customize): hair styles and accessories. Anything not chosen keeps the random look.
function hairDraw(g,style,c){const ci=(x,y,rr)=>el('circle',{cx:x,cy:y,r:rr,fill:c},g);if(style==='bald')return;
  if(style==='long'){el('rect',{x:-7.6,y:-33,width:3,height:11,rx:1.5,fill:c},g);el('rect',{x:4.6,y:-33,width:3,height:11,rx:1.5,fill:c},g)}
  if(style==='braid')for(let k=0;k<4;k++)ci(6,-28+k*3,1.6);
  if(style==='pigtails'){ci(-8.2,-31,2.6);ci(8.2,-31,2.6)}
  if(style==='curly'){[-5,-2.5,0,2.5,5].forEach((x,i)=>ci(x,-35.2+(i%2)*.9,2.5));return}
  if(style==='spiky'){el('polygon',{points:'-6.5,-32 -5.2,-38.5 -2.6,-34 0,-39.5 2.6,-34 5.2,-38.5 6.5,-32',fill:c},g);return}
  if(style==='mohawk'){el('rect',{x:-1.6,y:-41.5,width:3.2,height:10,rx:1.3,fill:c},g);return}
  el('path',{d:'M-6.5 -32 A6.5 6.5 0 0 1 6.5 -32 Q0 -35 -6.5 -32Z',fill:c},g);if(style==='bun')ci(0,-38.6,3)}
function accessory(bod,eyes,k){const ink='#10131f';
  if(k==='glasses'||k==='sunglasses'){const f=k==='sunglasses'?ink:'rgba(200,230,255,.25)';for(const x of [-2.3,2.3])el('circle',{cx:x,cy:-30.5,r:2,fill:f,stroke:ink,'stroke-width':.8},eyes);el('line',{x1:-.3,y1:-30.5,x2:.3,y2:-30.5,stroke:ink,'stroke-width':.8},eyes)}
  if(k==='scarf'){el('rect',{x:-7,y:-26.5,width:14,height:3.2,rx:1.5,fill:'#e0564f'},bod);el('rect',{x:2.5,y:-24.5,width:3,height:7,rx:1,fill:'#c2443e'},bod)}
  if(k==='bowtie'){el('polygon',{points:'-4.2,-26.5 0,-24.8 -4.2,-23',fill:'#d9303a'},bod);el('polygon',{points:'4.2,-26.5 0,-24.8 4.2,-23',fill:'#d9303a'},bod);el('circle',{cx:0,cy:-24.8,r:1,fill:'#a8202a'},bod)}
  if(k==='flower'){['#ff7aa8','#ffd35a','#ff7aa8','#ffd35a'].forEach((c,n)=>el('circle',{cx:5.6+Math.cos(n*1.57)*1.7,cy:-35.2+Math.sin(n*1.57)*1.7,r:1.4,fill:c},bod));el('circle',{cx:5.6,cy:-35.2,r:.9,fill:'#fff6c0'},bod)}
  if(k==='headphones'){el('path',{d:'M-7 -31.5 A7 7.5 0 0 1 7 -31.5',fill:'none',stroke:'#2b2f45','stroke-width':1.7},bod);for(const x of [-8.6,5.6])el('rect',{x,y:-32.5,width:3,height:5,rx:1.2,fill:'#4f7fe0',stroke:'#2b2f45','stroke-width':.6},bod)}}
function figure(s){const L=s.look||{},g=el('g',{class:'token'},tokens),r=rng(s.id),skin0=SKIN[Math.floor(r()*SKIN.length)],skin=L.skin||skin0;el('ellipse',{cx:0,cy:0,rx:8,ry:3,fill:'rgba(0,0,0,.45)'},g);const bod=el('g',{class:'bod'},g);
  if(L.accessory==='backpack')el('rect',{x:-11,y:-25,width:7,height:13,rx:2.5,fill:'#8a5a3a',stroke:'#0b0f24','stroke-width':1},bod);
  el('rect',{class:'leg l',x:-5,y:-9,width:4,height:9,rx:2,fill:'#2b2f45'},bod);el('rect',{class:'leg r',x:1,y:-9,width:4,height:9,rx:2,fill:'#2b2f45'},bod);
  el('rect',{class:'arm l',x:-11.5,y:-23,width:4,height:12,rx:2,fill:skin,stroke:'#0b0f24','stroke-width':1},bod);el('rect',{class:'arm r',x:7.5,y:-23,width:4,height:12,rx:2,fill:skin,stroke:'#0b0f24','stroke-width':1},bod);
  el('rect',{class:'shirt',x:-8.5,y:-25,width:17,height:18,rx:6},bod);el('text',{class:'ini',y:-16},bod);
  el('circle',{cx:0,cy:-31,r:6.5,fill:skin,stroke:'#0b0f24','stroke-width':1.5},bod);
  const hair0=HAIR[Math.floor(r()*HAIR.length)];hairDraw(bod,L.hair||'short',L.hair_colour||hair0);
  const eyes=el('g',{class:'eyes'},bod);el('circle',{cx:-2.3,cy:-30.5,r:1.05,fill:'#10131f'},eyes);el('circle',{cx:2.3,cy:-30.5,r:1.05,fill:'#10131f'},eyes);
  if(L.accessory&&L.accessory!=='backpack')accessory(bod,eyes,L.accessory);
  const h=el('g',{class:'hat'},bod);hat(h,s.hat||(L.nohat?'':s.job));
  el('text',{class:'act',x:13,y:-20,'font-size':10},bod);el('text',{class:'label',y:13},g);return {g,x:0,y:0,path:[],place:null,job:s.hat||(L.nohat?'':s.job),eyes,face:0,lookSig:JSON.stringify(L)}}
// Which way a Seedling looks: eyes shift toward where it walks, and it shows its back when walking away (up the screen).
function face(t,dx,dy){const away=dy<-Math.abs(dx)*.6,x=Math.abs(dx)<.01?0:Math.sign(dx)*1.8;if(t.face===x+':'+away)return;t.face=x+':'+away;
  t.eyes.setAttribute('transform',`translate(${x},0)`);t.eyes.style.opacity=away?0:1}
// Standing Seedlings are not statues: now and then one waves at a neighbour or looks around.
function idle(){if(QUALITY==='low')return;const standing=Object.values(live).filter(t=>!t.path.length&&t.g.style.display!=='none');if(!standing.length)return;
  const t=standing[Math.floor(Math.random()*standing.length)],friends=standing.filter(o=>o!==t&&o.place===t.place);
  if(friends.length&&Math.random()<.6){t.g.classList.add('waving');setTimeout(()=>t.g.classList.remove('waving'),1800)}
  else{const e=t.eyes;e.animate([{transform:'translate(0,0)'},{transform:'translate(-1.8px,0)'},{transform:'translate(-1.8px,0)'},{transform:'translate(1.8px,0)'},{transform:'translate(1.8px,0)'},{transform:'translate(0,0)'}],{duration:2200,easing:'ease-in-out'})}}
setInterval(idle,2600);
function seedlings(list){const groups={};for(const s of list)(groups[s.place]=groups[s.place]||[]).push(s);const seen=new Set();document.querySelectorAll('.more').forEach(e=>e.remove());
  for(const k in groups){const all=groups[k].sort((a,b)=>(isNew(b)-isNew(a))||(a.id<b.id?-1:1)),n=Math.min(all.length,PER_PLACE),extra=all.length-n;
    all.forEach((s,i)=>{seen.add(s.id);const [tx,ty]=home(k,Math.min(i,n-1),n);let t=live[s.id];
      if(!t){t=live[s.id]=figure(s);t.id=s.id;t.place=k;
        // A Seedling new to this session steps out of the Kernel's door, waits a moment in its glow, then walks down the ramp
        // to its place. Those already here when the page opens are simply placed, so loading never starts a parade.
        if(fromKernel(s.id)){[t.x,t.y]=KDOOR;t.path=[KRAMP,...route('commons',k),[tx,ty]];t.wait=performance.now()+1400;spawnGlow()}else{t.x=tx;t.y=ty}
        t.g.setAttribute('transform',place_(t.x,t.y))}
      else if(t.lookSig!==JSON.stringify(s.look||{})){const old=t;t=live[s.id]=figure(s);Object.assign(t,{id:s.id,x:old.x,y:old.y,place:old.place,path:old.path});   // a new look: redraw in place
        t.g.setAttribute('transform',old.g.getAttribute('transform'));old.g.remove()}
      everSeen.add(s.id);t.hidden=i>=n;t.s=s;const hk=s.hat||(s.look&&s.look.nohat?'':s.job);if(t.job!==hk){t.job=hk;hat(t.g.querySelector('.hat'),hk)}t.g.querySelector('.shirt').setAttribute('fill',(s.look&&s.look.outfit)||MOOD[s.mood]||'#b8f4d0');t.g.querySelector('.ini').textContent=(s.name||'?').slice(0,1).toUpperCase();
      t.g.querySelector('.label').setAttribute('y',13+(i%2)*11);   // neighbours' names alternate height so they never overlap
      t.g.querySelector('.label').textContent=SHOW_NAMES?(s.badge?s.badge+' ':'')+(s.name.length>8?s.name.slice(0,7)+'…':s.name):'';t.g.querySelector('.act').textContent=s.emoji||'';
      if(t.place!==k){t.path=[...route(t.place,k),[tx,ty]];t.place=k;t.g.style.display='';hushBubble(t)}else if(!t.path.length&&(Math.abs(t.x-tx)>1||Math.abs(t.y-ty)>1))t.path=[[tx,ty]];
      else if(t.path.length)t.path[t.path.length-1]=[tx,ty];
      if(!t.path.length)t.g.style.display=t.hidden?'none':''});
    if(extra>0){const [x,y]=home(k,n-1,n),z=TK(),b=Math.max(.85,z),m=el('g',{class:'more',transform:`translate(${(x+12*z+2).toFixed(1)},${(y-17*z).toFixed(1)}) scale(${b.toFixed(3)})`},tokens);
      el('rect',{x:0,y:-11,width:34,height:22,rx:11,fill:'#6b3fd1',stroke:'#fff','stroke-width':2},m);el('text',{x:17,y:0},m).textContent='+'+extra}}
  for(const id in live)if(!seen.has(id)){live[id].g.remove();delete live[id]}
  walk()}
const everSeen=new Set();   // every Seedling this page has shown, so only newcomers step out of the Kernel
const fromKernel=id=>!first&&!everSeen.has(id);   // new during this session: not on the first render, and never shown before
// The Kernel's welcome: a ring of cyan light spreads from its doorway and the pod's own ring flares.
function spawnGlow(){const [x,y]=KDOOR,g=el('g',{class:'spawn'});tokens.insertBefore(g,tokens.firstChild);   // behind every Seedling
  el('circle',{cx:x,cy:y-12,r:22,fill:'url(#kglowg)'},g);el('ellipse',{cx:x,cy:y,rx:16,ry:7,fill:'none',stroke:'#8ff3ff','stroke-width':2},g);
  const k=document.getElementById('kernel');if(k){k.classList.add('surge');setTimeout(()=>k.classList.remove('surge'),1800)}setTimeout(()=>g.remove(),2100)}
let walking=false,lastT=0;
function walk(){if(walking)return;walking=true;lastT=performance.now();requestAnimationFrame(stepAll)}
function stepAll(now){const dt=Math.min(.1,(now-lastT)/1000);lastT=now;let any=false;
  for(const id in live){const t=live[id];if(!t.path.length){if(t.g.classList.contains('walking')){t.g.classList.remove('walking');face(t,0,0)}continue}any=true;t.g.style.display='';
    if(t.wait){if(now<t.wait)continue;t.wait=0}t.g.classList.add('walking');
    let left=46*dt;while(left>0&&t.path.length){const [px,py]=t.path[0],dx=px-t.x,dy=py-t.y,dist=Math.hypot(dx,dy);face(t,dx,dy);if(dist<=left){t.x=px;t.y=py;left-=dist;t.path.shift()}else{t.x+=dx/dist*left;t.y+=dy/dist*left;left=0}}
    t.g.setAttribute('transform',place_(t.x,t.y));if(id===speaking)dropBubbleIfHidden(t);if(!t.path.length&&t.hidden&&!t.g.querySelector('.bubble'))t.g.style.display='none'}
  sortTokens();if(any)requestAnimationFrame(stepAll);else walking=false}
// Nearer Seedlings draw in front. Nodes are only moved when the order really changes: moving one restarts its animations.
let sortAt=0,speaking=null;function sortTokens(force){const now=performance.now();if(!force&&now-sortAt<400)return;sortAt=now;
  const want=Object.values(live).sort((a,b)=>(a.id===speaking)-(b.id===speaking)||a.y-b.y).map(t=>t.g),have=[...tokens.children].filter(n=>n.classList.contains('token'));
  if(want.length===have.length&&want.every((g,i)=>g===have[i]))return;want.forEach(g=>tokens.appendChild(g))}
// A speech bubble pops up once over the speaker, stays a few seconds and fades away.
let bubbleTimer=null;
function speak(t,line){document.querySelectorAll('.bubble').forEach(b=>b.remove());clearTimeout(bubbleTimer);if(!t||!line)return;
  // The whole line, word-wrapped. The bubble tries above the head, higher up, then to either side,
  // and takes the first spot that covers no district name, panel or bar and stays on screen.
  // No bubble for a speaker the camera cannot see (off-frame, or behind a bar or panel); the caption still names them.
  if(CARD||t.path.length||t.hidden)return;const z=TK(),[hx0,hy0]=toScreen(t.x,t.y-30*z),walls0=panels();if(hx0<10||hx0>950||hy0<band[0]||hy0>536||walls0.some(q=>hx0>q.l&&hx0<q.r&&hy0>q.t&&hy0<q.b))return;
  const b=el('g',{class:'bubble'},t.g),pop=el('g',{class:'pop'},b),tx=el('text',{},pop),MAX=200,LH=15,rows=[];let cur='';
  const width=str=>{tx.textContent=str;return tx.getComputedTextLength()};
  for(const word of line.split(/\s+/)){const next=cur?cur+' '+word:word;if(cur&&width(next)>MAX){rows.push(cur);cur=word}else cur=next}if(cur)rows.push(cur);
  const w=Math.max(...rows.map(width))+20,h=rows.length*LH+10,k=Math.min(1,1.25/CAM.s);tx.textContent='';b.setAttribute('transform',`scale(${(k/z).toFixed(3)})`);
  const walls=panels();
  document.querySelectorAll('.dlabel').forEach(g=>{if(g.dataset.hidden)return;const r=g.querySelector('rect');const x=+r.getAttribute('x'),y=+r.getAttribute('y'),[l,tp]=toScreen(x,y),[rr,bt]=toScreen(x+(+r.getAttribute('width')),y+(+r.getAttribute('height')));walls.push({l,t:tp,r:rr,b:bt})});
  const cost=(bx,by)=>{const [l,tp]=toScreen(t.x+bx*k,t.y+by*k),[r,bt]=toScreen(t.x+(bx+w)*k,t.y+(by+h)*k);let c=0;
    for(const q of walls){const ox=Math.min(r,q.r)-Math.max(l,q.l),oy=Math.min(bt,q.b)-Math.max(tp,q.t);if(ox>-3&&oy>-3)c+=6000+Math.max(0,ox)*Math.max(0,oy)*4}
    // it should not sit on other Seedlings either (a lighter penalty: names and panels matter most)
    for(const o of Object.values(live)){if(o===t||o.g.style.display==='none')continue;const [ox,oy]=toScreen(o.x,o.y-20*z),hw=11*CAM.s*z,hh=22*CAM.s*z;
      const ix=Math.min(r,ox+hw)-Math.max(l,ox-hw),iy=Math.min(bt,oy+hh)-Math.max(tp,oy-hh);if(ix>0&&iy>0)c+=1500+ix*iy}
    // the tail must not cross a name or panel either
    const [hx1,hy1]=toScreen(t.x,t.y-38*z),ex=Math.max(l,Math.min(r,hx1)),ey=Math.max(tp,Math.min(bt,hy1));
    const steps=Math.max(3,Math.ceil(Math.hypot(hx1-ex,hy1-ey)/4));for(let i=1;i<steps;i++){const f=i/steps,px=ex+(hx1-ex)*f,py=ey+(hy1-ey)*f;if(walls.some(q=>px>q.l-1&&px<q.r+1&&py>q.t-1&&py<q.b+1)){c+=8000;break}}
    const off=(Math.max(0,4-l)+Math.max(0,r-956))*(bt-tp)*9+(Math.max(0,band[0]+2-tp)+Math.max(0,bt-536))*(r-l)*9;c+=off+(off>0?60000:0);   // off the frame loses to any spot on screen
    const [hx,hy]=toScreen(t.x,t.y-38*z),cx=(l+r)/2,cy=(tp+bt)/2,tail=Math.hypot(cx-hx,cy-hy);return c+tail*2.2+Math.max(0,tail-70)*45+(tail>90?20000:0)};   // long tails cost more than crossing a name, and past 90 units they are ruled out   // strongly prefer short tails   // prefer spots close to the speaker
  // Candidate spots all around the head: above (at several heights), to either side, and below the feet.
  const head=-38*z/k,spots=[];
  for(let lift=0;lift<=100;lift+=10)for(const f of [0,-.25,.25,-.5,.5,-.75,.75])spots.push([-w/2+f*w,head-8-h-lift]);
  for(const dy of [-30,0,30])spots.push([14*z/k,head-h/2+dy],[-14*z/k-w,head-h/2+dy]);
  for(const f of [0,-.4,.4])spots.push([-w/2+f*w,10*z/k]);
  let best=spots[0],bestCost=Infinity;for(const sp of spots){const c=cost(sp[0],sp[1]);if(c<bestCost){best=sp;bestCost=c}}
  const [bx,by]=best;
  rows.forEach((r,k2)=>{const ts=el('tspan',{x:bx+10,y:by+5+LH/2+k2*LH},tx);ts.textContent=r});
  // The tail leaves the bubble at the edge point nearest the speaker's head.
  const H=by>0?[0,-2*z/k]:[0,head],P=[Math.max(bx+10,Math.min(bx+w-10,H[0])),Math.max(by,Math.min(by+h,H[1]))],flat=P[1]===by||P[1]===by+h&&!(P[0]===bx||P[0]===bx+w);
  const side=H[1]>by+h?'b':H[1]<by?'t':H[0]<bx?'l':'r',base=side==='b'||side==='t'?[[P[0]-6,side==='b'?by+h:by],[P[0]+6,side==='b'?by+h:by]]:[[side==='l'?bx:bx+w,P[1]-6],[side==='l'?bx:bx+w,P[1]+6]];
  const tip=[H[0]+(P[0]-H[0])*.12,H[1]+(P[1]-H[1])*.12];
  pop.insertBefore(el('rect',{x:bx,y:by,width:w,height:h,rx:9,fill:'#fffdf5',stroke:'#171230','stroke-width':1.6}),tx);
  pop.insertBefore(el('polygon',{points:pts([base[0],base[1],tip]),fill:'#fffdf5',stroke:'#171230','stroke-width':1.6,'stroke-linejoin':'round'}),tx);
  const seam=side==='b'||side==='t'?{x:P[0]-5,y:(side==='b'?by+h:by)-1.6,width:10,height:3.2}:{x:(side==='l'?bx:bx+w)-1.6,y:P[1]-5,width:3.2,height:10};
  pop.insertBefore(el('rect',{...seam,fill:'#fffdf5'}),tx);
  t.g.style.display='';sortTokens(true);
  pop.animate([{opacity:0,transform:'scale(.4)'},{opacity:1,transform:'none'}],{duration:350,easing:'cubic-bezier(.2,1.4,.4,1)'});
  bubbleTimer=setTimeout(()=>{b.animate([{opacity:1},{opacity:0}],{duration:500,fill:'forwards'}).onfinish=()=>{b.remove();if(t.hidden&&!t.path.length)t.g.style.display='none'}},Math.min(5500,SECONDS-800))}

// A Seedling that sets off walking stops talking: its bubble fades rather than drifting into names or off the frame.
function hushBubble(t){const b=t.g.querySelector('.bubble');if(!b||b.dataset.leaving)return;b.dataset.leaving='1';b.animate([{opacity:1},{opacity:0}],{duration:400,fill:'forwards'}).onfinish=()=>b.remove()}
// A speaker who walks out of the shot (or behind a bar) takes the bubble with them.
function dropBubbleIfHidden(t){const b=t.g.querySelector('.bubble');if(!b||b.dataset.leaving)return;const [x,y]=toScreen(t.x,t.y-30*TK());
  if(x<10||x>950||y<band[0]||y>536||panels().some(q=>x>q.l&&x<q.r&&y>q.t&&y<q.b)){b.dataset.leaving='1';b.animate([{opacity:1},{opacity:0}],{duration:400,fill:'forwards'}).onfinish=()=>b.remove()}}

// ---- the camera: a wide shot, drifting in on whoever is talking and on new buildings
const world=document.getElementById('world'),svgEl=document.getElementById('map');let lockUntil=0;
// DOM element → viewBox units, so HTML bars and SVG shapes can be compared.
function vb(e){const m=svgEl.getScreenCTM(),r=e.getBoundingClientRect();return {l:(r.left-m.e)/m.a,t:(r.top-m.f)/m.d,r:(r.right-m.e)/m.a,b:(r.bottom-m.f)/m.d}}
const BOUNDS={left:OX-N*TW/2-8,right:OX+N*TW/2+8,bottom:OY+N*TH+8,top:OY};
let HOME={x:480,y:254,s:1.1,px:480,py:290},CAM=HOME,band=[50,534];
// The wide shot is sized so every building fits below the header and inside the frame.
function fitHome(){try{const c=document.getElementById('city').getBBox();BOUNDS.top=Math.min(c.height?c.y:OY,OY)-4}catch(e){}
  band=[Math.max(4,vb(document.querySelector('.head')).b+6),NARROW?Math.min(534,vb(document.getElementById('cap')).t-6):534];const s=Math.min(944/(BOUNDS.right-BOUNDS.left),(band[1]-band[0])/(BOUNDS.bottom-BOUNDS.top));
  let next={x:(BOUNDS.left+BOUNDS.right)/2,y:(BOUNDS.top+BOUNDS.bottom)/2,s,px:480,py:(band[0]+band[1])/2};
  if(FOCUS){const [r,c]=CELLS[FOCUS],[a,b]=cellTiles(r,c),[fx,fy]=FOCUS==='commons'?iso(...KERNEL):iso(a+3,b+3);next={x:fx,y:fy-(FOCUS==='commons'?20:8),s:s*(CARD?1.6:2.5),px:480,py:next.py}}   // held on one district
  if(Math.abs(next.s-HOME.s)>.002||Math.abs(next.y-HOME.y)>.5||Math.abs(next.py-HOME.py)>.5){const wasHome=CAM===HOME;HOME=next;if(wasHome)apply(HOME)}
  if(CARD){const ppu=Math.min(svgEl.clientWidth/960,svgEl.clientHeight/540)*HOME.s,ls=Math.min(2.2,Math.max(1,13/(16*ppu))),ts=Math.min(1.8,Math.max(1,21/(38*ppu)));
    if(Math.abs(ls-LS)>.02||Math.abs(ts-TS)>.02){LS=ls;TS=ts;labelSig='';if(lastData){labelsFor(lastData);tidyLabels();seedlings(latest);for(const id in live)live[id].g.setAttribute('transform',place_(live[id].x,live[id].y))}}
    const tt=document.getElementById('toast');tt.style.top=(document.querySelector('.head').offsetHeight+6)+'px'}}
let lastData=null;
function apply(c){CAM=c;world.style.transform=`translate(${c.px}px,${c.py}px) scale(${c.s}) translate(${-c.x}px,${-c.y}px)`;tidyLabels()}
// In a close-up, district names that would be cut by the frame or slide under a bar or panel fade out instead.
function panels(){const out=[vb(document.querySelector('.head')),vb(document.getElementById('cap'))],st=document.getElementById('stats'),tt=document.getElementById('toast');
  if(st&&!st.classList.contains('hide'))out.push(vb(st));if(tt.classList.contains('show'))out.push(vb(tt));return out}
function tidyLabels(){const walls=panels();document.querySelectorAll('.dlabel').forEach(g=>{const r=g.querySelector('rect');if(!r)return;const x=+r.getAttribute('x'),y=+r.getAttribute('y');
  const [l,t]=toScreen(x,y),[rr,b]=toScreen(x+(+r.getAttribute('width')),y+(+r.getAttribute('height')));
  const cut=l<2||rr>958||t<0||b>540||walls.some(q=>Math.min(rr,q.r)-Math.max(l,q.l)>0&&Math.min(b,q.b)-Math.max(t,q.t)>0);
  g.style.opacity=cut?0:1;g.dataset.hidden=cut?'1':''})}
function look(x,y,s){if(!CAMERA||x==null||FOCUS)return apply(HOME);
  const hw=480/s,hh=(band[1]-band[0])/2/s;x=Math.max(BOUNDS.left+hw,Math.min(BOUNDS.right-hw,x));y=Math.max(BOUNDS.top+hh,Math.min(BOUNDS.bottom-hh,y));
  apply({x,y,s,px:480,py:(band[0]+band[1])/2})}
const toScreen=(x,y)=>[CAM.px+(x-CAM.x)*CAM.s,CAM.py+(y-CAM.y)*CAM.s];
const toasts=[];let toasting=false;
function toast(text,key){toasts.push([text,key]);if(!toasting)nextToast()}
function nextToast(){const t=document.getElementById('toast'),item=toasts.shift();if(!item){toasting=false;return}toasting=true;t.textContent=item[0];t.classList.add('show');tidyLabels();
  if(item[1]&&CELLS[item[1]]){const [x,y]=labelXY(item[1]);lockUntil=Date.now()+9000;look(x,y+40,1.8)}
  setTimeout(()=>{t.classList.remove('show');tidyLabels();setTimeout(nextToast,600)},6000)}

// ---- sky, weather and holidays
let weatherKey='',festival=null,fxSig='',fireworks=null;
// ---- time of day: the light follows the Avesta hour (0–24) continuously, not just the four phase names.
// Keys: hour, sky top, sky middle, sky horizon, the mist on the far trees, the near forest, light over the town, darkness 0–1, stars 0–1.
// By day the air is a soft teal; the mist turns gold at dawn, pink at dusk and blue at night.
const LIGHT=[[0,'#1b2150','#3d3a6e','#4a4f78','#25324e','#121a2c','rgba(24,28,88,.40)',.72,.55],
  [2,'#3a4488','#c98a96','#e7b39c','#6a5872','#2e2a3e','rgba(255,140,150,.16)',.32,.12],[4.5,'#6fa2da','#f0d6aa','#f2d2a4','#d9bd8e','#4c5a40','rgba(255,196,130,.10)',.06,0],
  [7,'#5f9fb4','#94c8bf','#a3cfc5','#5f9c8d','#264d3c','rgba(0,0,0,0)',0,0],[13,'#5c9cb2','#92c6bd','#a1cdc3','#5f9c8d','#264d3c','rgba(0,0,0,0)',0,0],
  [15.5,'#6a9ab8','#d6d6aa','#d8cca0','#8fa98a','#2f503c','rgba(255,176,90,.12)',0,0],[17.5,'#4a3f7a','#ef9a74','#f2a98a','#dc9aa6','#4d3f4f','rgba(255,106,58,.22)',.22,.08],
  [19,'#241c4a','#8a4a7a','#b8687a','#7a5a88','#2c2440','rgba(64,40,120,.40)',.6,.45],[21,'#060a1f','#18204a','#1d2450','#1f2b4a','#0e1526','rgba(6,12,52,.54)',1,1],
  [24,'#1b2150','#3d3a6e','#4a4f78','#25324e','#121a2c','rgba(24,28,88,.40)',.72,.55]];
const PREVIEW_HOUR={Morning:3,Day:10.5,Evening:17,Night:22};
const rgba=c=>c[0]==='#'?[parseInt(c.slice(1,3),16),parseInt(c.slice(3,5),16),parseInt(c.slice(5,7),16),1]:c.match(/[\d.]+/g).map(Number);
const mix=(a,b,t)=>{const x=rgba(a),y=rgba(b),v=x.map((n,k)=>n+(y[k]-n)*t);return `rgba(${v[0]|0},${v[1]|0},${v[2]|0},${v[3].toFixed(3)})`};
function lightAt(hour){hour=((hour%24)+24)%24;let k=0;while(k<LIGHT.length-2&&LIGHT[k+1][0]<=hour)k++;const A=LIGHT[k],B=LIGHT[k+1],t=(hour-A[0])/(B[0]-A[0]);
  return {sky:[1,2,3].map(n=>mix(A[n],B[n],t)),hills:[mix(A[4],B[4],t),mix(A[5],B[5],t)],tint:mix(A[6],B[6],t),dark:A[7]+(B[7]-A[7])*t,stars:A[8]+(B[8]-A[8])*t}}
let darkness=0,shadowSig='',horizonSig='';
// The forest horizon takes the light of the hour: the farthest row dissolves into the mist, the nearest stays a deep green, and the
// mist itself is teal by day, gold at dawn, pink at dusk and blue at night. Rain greys it and dust browns it.
function horizon(L,veil){const mist=veil(L.hills[0],['#a9b4b6','#cfae84']),col=[veil(mix(L.hills[0],L.sky[2],.22),['#b4bec0','#d6b88e']),veil(mix(L.hills[0],L.hills[1],.5),['#87918f','#a88d68']),veil(L.hills[1],['#59625f','#7c6748'])],sig=col.join()+mist;
  if(sig===horizonSig)return;horizonSig=sig;
  document.querySelectorAll('#hills [data-l],#hills2 [data-l]').forEach(p=>p.setAttribute('fill',shade(col[+p.dataset.l],+p.dataset.k)));
  for(const id of ['mist0','mist1'])document.getElementById(id).setAttribute('stop-color',mist)}
function sky(hour,wkey){const L=lightAt(hour),grey=wkey==='good_growing'||wkey==='water_watch',dust=wkey==='dust_winds',day=1-L.dark;darkness=L.dark;
  const veil=(c,to)=>grey?mix(c,to[0],.55*day):dust?mix(c,to[1],.5*day):c;   // rain greys the sky and the ranges, dust browns them
  ['sky0','sky1','sky2'].forEach((id,n)=>document.getElementById(id).setAttribute('stop-color',veil(L.sky[n],[['#6f7885','#aab2bc','#bcc3cb'][n],['#a8835a','#dcbb8c','#e6c89a'][n]])));
  horizon(L,veil);
  document.getElementById('stars').style.opacity=L.stars.toFixed(2);document.getElementById('tint').setAttribute('fill',L.tint);
  // The sun rises on the left, crosses the sky and sets on the right; the moon follows at night.
  const sun=document.getElementById('sun');sun.innerHTML='';const h=((hour%24)+24)%24;
  const up_=(h>=1.5&&h<=19.2)?(h-1.5)/17.7:null,moon=(h>=18.6||h<=2.2)?((h-18.6+24)%24)/7.6:null;
  if(up_!=null&&!grey){const x=70+up_*820,y=190-Math.sin(Math.PI*up_)*125,low=Math.sin(Math.PI*up_)<.35,col=low?'#ffab66':'#fff3c4';
    el('circle',{cx:x,cy:y,r:low?90:70,fill:'url(#sung)',opacity:low?.95:.75},sun);el('circle',{cx:x,cy:y,r:low?28:23,fill:col},sun)}
  if(moon!=null){const x=890-moon*820,y=175-Math.sin(Math.PI*moon)*115,o=Math.min(1,L.dark*1.4);el('circle',{cx:x,cy:y,r:34,fill:'url(#glowdot)',opacity:.45*o},sun);
    el('circle',{cx:x,cy:y,r:16,fill:'#f4f1e0',opacity:o},sun);el('circle',{cx:x+6,cy:y-5,r:13,fill:L.sky[0],opacity:o},sun)}
  document.getElementById('skyclouds').style.opacity=(grey?1:.15+.55*day).toFixed(2);
  document.getElementById('shades').style.display=L.dark>.3||grey?'none':'';
  const au=document.getElementById('aurora');au.innerHTML='';if(L.dark>.6&&wkey==='sensor_noise')for(let k=0;k<3;k++)el('path',{d:`M0 ${120+k*18} Q240 ${60+k*25} 480 ${110+k*14} T960 ${90+k*20}`,stroke:'url(#aurorag)','stroke-width':14-k*3,fill:'none',opacity:.8},au);
  document.getElementById('haze').setAttribute('fill',dust?'rgba(214,170,110,.16)':wkey==='water_watch'?'rgba(120,130,150,.10)':`rgba(120,200,190,${(.07*day).toFixed(3)})`);   // a soft teal haze by day
  shadows(up_,grey?0:Math.max(0,1-L.dark*2.2))}
// Buildings cast shadows away from the town's one sun (the upper left), so they agree with the lit faces: long at dawn and dusk, short at noon.
function hull(p){p=p.slice().sort((a,b)=>a[0]-b[0]||a[1]-b[1]);const cross=(o,a,b)=>(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0]),lo=[],hi=[];
  for(const q of p){while(lo.length>1&&cross(lo[lo.length-2],lo[lo.length-1],q)<=0)lo.pop();lo.push(q)}for(const q of p.reverse()){while(hi.length>1&&cross(hi[hi.length-2],hi[hi.length-1],q)<=0)hi.pop();hi.push(q)}
  return lo.slice(0,-1).concat(hi.slice(0,-1))}
function shadows(sunT,strength){const path=document.getElementById('shadows');if(sunT==null||strength<=0||QUALITY==='low'){path.setAttribute('opacity',0);return}
  const sig=sunT.toFixed(2)+':'+CASTERS.length;path.setAttribute('opacity',(.42*strength).toFixed(2));if(sig===shadowSig)return;shadowSig=sig;
  const elev=Math.max(.12,Math.sin(Math.PI*sunT)),len=Math.min(2.6,.6/elev),dx=.95*len,dy=.18*len+.08;   // always away from the sun on the upper left
  path.setAttribute('d',CASTERS.map(([base,h])=>'M'+hull(base.concat(base.map(([x,y])=>[x+dx*h,y+dy*h]))).map(q=>q[0].toFixed(1)+' '+q[1].toFixed(1)).join('L')+'Z').join(''))}
function particles(kind,n,make){if(QUALITY==='low')return;for(let k=0;k<n;k++){const p=document.createElement('i');p.className='particle';make(p,k);document.getElementById('wrap').appendChild(p)}}
function effects(phase){const pal=festival&&HOLIDAYS[festival.name]?HOLIDAYS[festival.name][1]:null,dark=darkness>.3;
  const days=festival?festival.days_to_holiday:99,sig=[weatherKey,festival&&festival.name,dark,Math.abs(days)<=1].join('|');if(sig===fxSig)return;fxSig=sig;
  document.querySelectorAll('.particle').forEach(p=>p.remove());const R=Math.random;
  const fall=(p,color,w,h,sp,dx,extra='')=>{p.style.cssText=`left:${R()*110-5}%;top:-8%;width:${w}px;height:${h}px;background:${color};--dx:${dx}px;--dy:620px;animation-duration:${sp*(0.7+R()*.6)}s;animation-delay:-${R()*sp}s;${extra}`};
  if(weatherKey==='good_growing')particles('rain',70,p=>fall(p,'rgba(200,220,255,.55)',1.5,16,1.1,-60,'border-radius:1px'));
  if(weatherKey==='spore_drift')particles('spore',26,p=>{p.style.cssText=`left:${R()*100}%;top:${R()*100}%;width:6px;height:6px;border-radius:50%;background:rgba(126,227,176,.6);--dx:80px;--dy:-40px;animation-duration:${6+R()*8}s;animation-delay:-${R()*8}s`});
  if(weatherKey==='dust_winds')particles('dust',34,p=>{p.style.cssText=`left:-10%;top:${10+R()*85}%;width:${30+R()*50}px;height:2px;border-radius:2px;background:rgba(222,190,140,.55);--dx:1200px;--dy:${R()*60-30}px;animation-duration:${1.6+R()*1.6}s;animation-delay:-${R()*3}s`});
  if(weatherKey==='quiet_cycle'&&dark)particles('firefly',22,p=>{p.style.cssText=`left:${10+R()*80}%;top:${25+R()*65}%;width:5px;height:5px;border-radius:50%;background:#fff3a0;box-shadow:0 0 8px #ffe66b;--dx:${R()*80-40}px;--dy:${R()*60-30}px;animation-duration:${4+R()*5}s;animation-direction:alternate;animation-delay:-${R()*5}s`});
  const emoji=(list,n,dir)=>particles('emoji',n,p=>{const e=list[Math.floor(R()*list.length)];p.textContent=e;p.style.cssText=`left:${R()*100}%;top:${dir>0?-8:100}%;font-size:${14+R()*12}px;--dx:${R()*160-80}px;--dy:${dir*640}px;--rot:${R()*360}deg;animation-duration:${9+R()*8}s;animation-delay:-${R()*16}s;opacity:.85`});
  const fest=document.getElementById('festive');fest.innerHTML='';fireworksOff();
  if(!festival||!pal)return;const theme=HOLIDAYS[festival.name][2];
  decorate(fest,theme,pal,dark);
  if(theme==='christmas'||theme==='newyear'&&!dark)particles('snow',50,p=>fall(p,'#fff',5,5,11,40,'border-radius:50%;opacity:.85'));
  if(theme==='halloween')emoji(dark?['🦇','🦇','👻']:['🍂','🍁'],dark?10:12,dark?-1:1);
  if(theme==='feast')emoji(['🍂','🍁','🍂'],14,1);
  if(theme==='valentine')emoji(['💗','💕','💖'],14,-1);
  const bigDay=Math.abs(days)<=1||(theme==='newyear'||festival.name==='Independence Day')&&days<=3&&days>=-1;
  if(dark&&(bigDay||theme==='newyear'&&days<=7))fireworksOn(pal)}
function fireworksOff(){if(fireworks){clearInterval(fireworks);fireworks=null}document.getElementById('fx').innerHTML=''}
function fireworksOn(pal){const fx=document.getElementById('fx');const pop=()=>{const x=150+Math.random()*660,y=80+Math.random()*130,c=pal[Math.floor(Math.random()*pal.length)],b=el('g',{class:'burst'},fx);
  for(let k=0;k<16;k++){const a=k/16*Math.PI*2,d=34+Math.random()*16;el('circle',{cx:x,cy:y,r:2.4,fill:c,style:`--dx:${(Math.cos(a)*d).toFixed(1)}px;--dy:${(Math.sin(a)*d+10).toFixed(1)}px`},b)}
  el('circle',{cx:x,cy:y,r:30,fill:'url(#glowdot)',opacity:.35},b);setTimeout(()=>b.remove(),1600)};pop();fireworks=setInterval(pop,QUALITY==='low'?2600:1100)}
// Decorations: bunting along the streets, lanterns or pumpkins by the lamps, and a centrepiece on the crossing beside the Kernel's plaza
// (its own doorstep stays clear for the Seedlings who step out of it).
const FEST_AT=[13.5,6.5];
function decorate(g,theme,pal,dark){const r=rng('fest:'+theme);
  for(const k of [6,13])for(let s=0;s+3<N;s+=3)for(const [a,b] of [[[k+.1,s+.1],[k+.1,s+3.1]],[[s+.1,k+.1],[s+3.1,k+.1]]]){const [x1,y1]=iso(...a),[x2,y2]=iso(...b),mx=(x1+x2)/2,my=(y1+y2)/2+5;if(behindKernel(mx,my-10))continue;
    el('path',{d:`M${x1} ${y1-10} Q${mx} ${my-10} ${x2} ${y2-10}`,stroke:'rgba(40,30,30,.6)','stroke-width':.8,fill:'none'},g);
    for(let q=1;q<6;q++){const t=q/6,x=(1-t)*(1-t)*x1+2*(1-t)*t*mx+t*t*x2,y=(1-t)*(1-t)*(y1-10)+2*(1-t)*t*(my-10)+t*t*(y2-10),c=pal[q%pal.length];
      if(dark)el('circle',{cx:x,cy:y+1,r:4,fill:'url(#glowdot)'},g);el(dark?'circle':'polygon',dark?{cx:x,cy:y+1,r:1.8,fill:c}:{points:`${x-2.5},${y} ${x+2.5},${y} ${x},${y+5}`,fill:c},g)}}
  const lamp=(i,j,f)=>{const [x,y]=iso(i,j);if(!behindKernel(x,y-5))f(x,y)};
  if(theme==='halloween'||theme==='feast')for(const [i,j] of LAMPS)lamp(i+.35,j+.35,(x,y)=>pumpkin(g,x,y,5,dark&&theme==='halloween'));
  if(theme==='feast')for(let q=0;q<10;q++){const [x,y]=iso(1+r()*4.5,15+r()*4.5);el('rect',{x:x-6,y:y-6,width:12,height:6,rx:1.5,fill:'#e2c25a',stroke:'#a8862e'},g)}
  const [si,sj]=FEST_AT,[x,y]=iso(si,sj),c=el('g',{},g);
  if(theme==='christmas'){el('rect',{x:x-3,y:y-8,width:6,height:8,fill:'#6b4a2e'},c);[[34,-8],[27,-24],[19,-38]].forEach(([w,o])=>{const b=y+o,t=b-26,m=[x+w*.15,b+2];facet(c,[[x-w,b],[x,t],m],shade('#2f7a45',toward(-1,-.3)));facet(c,[[x,t],[x+w,b],m],shade('#2f7a45',toward(1,-.3)))});
    for(let q=0;q<14;q++){const t=r(),yy=y-10-t*52,xx=x+(r()-.5)*(34*(1-t)+4)*1.6;if(dark)el('circle',{cx:xx,cy:yy,r:5,fill:'url(#glowdot)'},c);el('circle',{cx:xx,cy:yy,r:2.2,fill:pal[q%3]},c)}
    el('polygon',{points:star(x,y-66,7,3),fill:'#ffd35a',stroke:'#fff3b0'},c);[[-22,'#e0303a'],[18,'#2d5bd8'],[-6,'#ffd35a']].forEach(([dx,f])=>{el('rect',{x:x+dx,y:y-6,width:10,height:8,fill:f},c);el('rect',{x:x+dx+4,y:y-6,width:2,height:8,fill:'#fff'},c)})}
  if(theme==='halloween'){pumpkin(c,x,y,20,dark);pumpkin(c,x-26,y+6,9,dark);pumpkin(c,x+26,y+6,8,dark);el('rect',{x:x+34,y:y-40,width:2,height:40,fill:'#6b4a2e'},c);el('rect',{x:x+26,y:y-32,width:18,height:2,fill:'#6b4a2e'},c);el('circle',{cx:x+35,cy:y-44,r:5,fill:'#e2c27a'},c);el('polygon',{points:`${x+28},${y-47} ${x+42},${y-47} ${x+35},${y-56}`,fill:'#2b2b2b'},c)}
  if(theme==='feast'){box(c,si-.9,sj-.6,1.8,.6,6,'#8a5a32',{topColor:'#f4efe4'});for(let q=0;q<5;q++){const [px,py]=iso(si-.7+q*.35,sj-.3);el('circle',{cx:px,cy:py-7,r:2.5,fill:pal[q%3]},c)}pumpkin(c,x-24,y+8,8,false);pumpkin(c,x+26,y+8,7,false)}
  if(theme==='flag'){el('rect',{x:x-1.5,y:y-70,width:3,height:70,fill:'#d6d6d6'},c);const fx=x+1.5,fy=y-70;for(let q=0;q<7;q++)el('rect',{x:fx,y:fy+q*3.4,width:40,height:3.4,fill:q%2?'#ffffff':'#d9303a'},c);el('rect',{x:fx,y:fy,width:17,height:13.6,fill:'#2d5bd8'},c);
    for(let q=0;q<6;q++)el('circle',{cx:fx+3+(q%3)*5.5,cy:fy+3.5+Math.floor(q/3)*6,r:.9,fill:'#fff'},c)}
  if(theme==='valentine'){el('path',{d:heart(x,y-50,26),fill:'none',stroke:'#ff5a8a','stroke-width':6},c);el('path',{d:heart(x,y-50,26),fill:'none',stroke:'#ffb3c8','stroke-width':2},c);for(let q=0;q<8;q++)el('circle',{cx:x+(r()-.5)*50,cy:y+(r()-.5)*10,r:2.5,fill:q%2?'#ff5a8a':'#e0303a'},c)}
  if(theme==='newyear'){el('rect',{x:x-1.5,y:y-64,width:3,height:64,fill:'#c9d3ff'},c);if(dark)el('circle',{cx:x,cy:y-70,r:18,fill:'url(#glowdot)'},c);el('circle',{cx:x,cy:y-70,r:9,fill:'#dfe6ff',stroke:'#ffd35a','stroke-width':2},c);
    const yr=new Date(Date.now()+(festival.days_to_holiday>0?festival.days_to_holiday:0)*864e5+864e5*2).getFullYear();sign(c,x,y-16,`HAPPY ${yr}!`,'#ffd35a')}
  if(theme==='grill'){box(c,si-.3,sj-.3,.6,.4,7,'#333a44',{topColor:'#555'});el('circle',{class:'smoke',cx:x,cy:y-14,r:4,fill:'#d8d3ca'},c);sign(c,x,y-26,"HAPPY FATHER'S DAY",'#8fd3ff')}
  if(theme==='labor')sign(c,x,y-20,'THANK YOU, WORKERS!','#ffb000')}
function pumpkin(g,x,y,s,lit){el('ellipse',{cx:x,cy:y-s*.55,rx:s,ry:s*.62,fill:'#e8701a',stroke:'#a8480e','stroke-width':Math.max(.6,s/10)},g);el('ellipse',{cx:x,cy:y-s*.55,rx:s*.45,ry:s*.62,fill:'none',stroke:'#c55a12','stroke-width':Math.max(.6,s/12)},g);
  el('rect',{x:x-s*.08,y:y-s*1.35,width:s*.16,height:s*.3,fill:'#4a6a2a'},g);
  if(s>=5){const f=lit?'#ffe46b':'#5a2a08';el('polygon',{points:`${x-s*.45},${y-s*.7} ${x-s*.2},${y-s*.7} ${x-s*.32},${y-s*.9}`,fill:f},g);el('polygon',{points:`${x+s*.2},${y-s*.7} ${x+s*.45},${y-s*.7} ${x+s*.32},${y-s*.9}`,fill:f},g);
    el('path',{d:`M${x-s*.45} ${y-s*.45} Q${x} ${y-s*.1} ${x+s*.45} ${y-s*.45}`,stroke:f,'stroke-width':Math.max(.8,s/7),fill:'none'},g);if(lit)el('circle',{cx:x,cy:y-s*.5,r:s*1.8,fill:'url(#glowdot)',opacity:.6},g)}}
function star(x,y,R,r){let p=[];for(let k=0;k<10;k++){const a=-Math.PI/2+k*Math.PI/5,d=k%2?r:R;p.push(`${x+Math.cos(a)*d},${y+Math.sin(a)*d}`)}return p.join(' ')}
function heart(x,y,s){return `M${x} ${y+s*.9} C${x-s*1.6} ${y} ${x-s*.9} ${y-s*1.1} ${x} ${y-s*.35} C${x+s*.9} ${y-s*1.1} ${x+s*1.6} ${y} ${x} ${y+s*.9}Z`}
function sign(g,x,y,text,color){const t=el('text',{x,y,'text-anchor':'middle','dominant-baseline':'central','font-size':11,'font-weight':900,fill:'#1a1026'},g);t.textContent=text;const w=t.getComputedTextLength()+16;
  g.insertBefore(el('rect',{x:x-w/2,y:y-9,width:w,height:18,rx:4,fill:color,stroke:'#1a1026','stroke-width':1.5}),t)}
let glitchTimer=null;
function glitches(on){if(on&&!glitchTimer)glitchTimer=setInterval(()=>{const b=document.createElement('div');b.className='glitch';b.style.top=(12+Math.random()*70)+'%';document.getElementById('wrap').appendChild(b);setTimeout(()=>b.remove(),600)},5200);
  if(!on&&glitchTimer){clearInterval(glitchTimer);glitchTimer=null}}
let shuttle=null;
function shuttles(on){if(on&&!shuttle){const [x,y]=iso(3,3);shuttle=el('g',{class:'shuttle'},document.getElementById('festive').parentNode);el('polygon',{points:`${x-6},${y-30} ${x+8},${y-38} ${x+4},${y-28}`,fill:'#eef1f4',stroke:'#5f6b80'},shuttle);el('circle',{cx:x-7,cy:y-28,r:3,fill:'#ffb070'},shuttle)}
  if(!on&&shuttle){shuttle.remove();shuttle=null}}

// ---- the colony at a glance: tier progress, the six society stats and what opens next
const STATS=[['🌾','food'],['⛏️','materials'],['⚙️','development'],['🔬','knowledge'],['🪙','treasury'],['⭐','reputation']];
const short=v=>v>=1e6?(v/1e6).toFixed(1)+'M':v>=1e4?Math.round(v/1e3)+'k':v>=1e3?(v/1e3).toFixed(1)+'k':String(Math.round(v));
let statsBuilt=false;
// The society stats live in the Hub; the map shows them only with &stats=1.
function statPanel(d){const box=document.getElementById('stats');if(!box)return;if(Q.get('stats')!=='1'){box.remove();return}const st=d.stats||{},target=d.tier_target||1,low=d.bottleneck&&d.bottleneck.key;
  if(!statsBuilt){statsBuilt=true;box.innerHTML=`<div class="tl"><b id="st-tier"></b><small id="st-next"></small><span id="st-pct"></span></div><div class="meter big"><i id="st-bar"></i></div>
    <div class="grid">${STATS.map(([i,k])=>`<div class="m" id="st-${k}" title="${k}"><span>${i}</span><div class="meter"><i></i></div><em></em></div>`).join('')}</div><div class="next" id="st-open"></div>`}
  document.getElementById('st-tier').textContent=(d.tier_name||d.tier||'Outpost').toUpperCase();document.getElementById('st-next').textContent=d.next_tier?'→ '+d.next_tier:'· top tier';
  document.getElementById('st-pct').textContent=d.next_tier?Math.round(d.tier_percent||0)+'%':'';document.getElementById('st-bar').style.width=(d.next_tier?Math.min(100,d.tier_percent||0):100)+'%';
  for(const [,k] of STATS){const row=document.getElementById('st-'+k),v=st[k]||0;row.classList.toggle('low',k===low&&!!d.next_tier);row.querySelector('i').style.width=Math.min(100,v/target*100)+'%';row.querySelector('em').textContent=short(v)}
  const locked=Object.entries(d.districts||{}).filter(([k,v])=>!v.unlocked&&LOOK[k]);
  document.getElementById('st-open').innerHTML=locked.length?`Next: <b>${esc(LOOK[locked[0][0]][0])} ${esc(LOOK[locked[0][0]][1])}</b> opens at ${esc(locked[0][1].unlocks_at)}`:`All districts open${low&&d.next_tier?` · needs <b>${esc(d.bottleneck.name)}</b>`:''}`;
  box.classList.remove('hide')}

// ---- the colony's own choices: the stream challenge bar, landmarks it voted to build, voted festivals and season decorations
const LM={greenhouse_expansion:['#dff3e6','#3f9a5a'],spaceport_pad:['#c3cad3','#6f5ad1'],research_annex:['#e9eef2','#3f8fc4'],irrigation_grid:['#cfe6f2','#2d7fb0'],
  recreation_hall:['#f2e2c4','#c2544a'],deepway_terminal:['#a9aeb5','#5a5f66'],community_kitchen:['#f4e6cf','#d9771f'],clinic_expansion:['#f6f6f2','#e0303a'],fire_station:['#e8d8c8','#b8302a']};
let voteFest='',decorSig='';const marks={};
function placeFor(p){const info=((lastData&&lastData.districts)||{})[p];return !CELLS[p]||p==='park'?'commons':p==='commons'||!info||info.unlocked?p:'commons'}
function landmark(g,i,j,x){const [wall,roof]=LM[x.key]||['#e9e2cf','#8a5aa8'];module_(g,i,j,20,wall,roof,{garden:true,inset:.1});   // a colony module, roofed in the landmark's colour
  const [cx,cy]=centre(i,j),m=el('g',{},g);el('circle',{cx,cy:cy-38,r:8.5,fill:'#fff8e6',stroke:roof,'stroke-width':2},m);
  el('text',{x:cx,y:cy-37.5,'text-anchor':'middle','dominant-baseline':'central','font-size':10},m).textContent=x.emoji;flag(g,cx+9,cy-24,roof)}
function site(g,i,j,b){scaffold(g,i,j,true);const [cx,cy]=centre(i,j),w=36,h=13,yy=cy+5;el('rect',{x:cx-w/2,y:yy,width:w,height:h,rx:3,fill:'rgba(8,13,39,.92)',stroke:'#f2b441','stroke-width':1},g);
  el('rect',{x:cx-w/2+2,y:yy+h-3.6,width:Math.max(1,(w-4)*Math.min(1,b.percent/100)),height:2,rx:1,fill:'#f2b441'},g);
  el('text',{x:cx,y:yy+4.8,'text-anchor':'middle','dominant-baseline':'central','font-size':7.5,'font-weight':900,fill:'#fff'},g).textContent=`${b.emoji} ${b.percent}%`}
function monument(g,i,j,se){box(g,i,j,1,1,7,'#cfc6b2',{topColor:'#e2dccb'});const [cx,cy]=centre(i,j);
  el('rect',{x:cx-3,y:cy-26,width:6,height:14,rx:2,fill:'#bdb4a0',stroke:'#8e8676'},g);el('circle',{cx,cy:cy-31,r:7.5,fill:se.colour||'#ff9ad5',stroke:'#fff8e6','stroke-width':1.5},g);
  el('text',{x:cx,y:cy-30.5,'text-anchor':'middle','dominant-baseline':'central','font-size':9},g).textContent=se.emoji}
function landmarks(v,se){const want=[],used={};
  for(const x of (v&&v.built)||[]){const place=placeFor(x.place),k=used[place]||0;used[place]=k+1;if(k<RESERVE)want.push([`lm:${x.key}:${place}:${k}`,place,k,x,'built'])}
  const b=v&&v.building;if(b&&b.percent<100){const place=placeFor(b.place),k=used[place]||0;if(k<RESERVE)want.push([`site:${b.key}:${place}:${k}:${b.percent}`,place,k,b,'site'])}
  if(se&&(se.decor||[]).includes('monument'))want.push([`mon:${se.key}`,'commons',RESERVE,se,'monument']);
  const keep=new Set(want.map(w=>w[0]));
  for(const id in marks)if(!keep.has(id)||!marks[id].isConnected){marks[id].remove();delete marks[id]}
  for(const [id,place,k,x,kind] of want){if(marks[id])continue;const dg=drawn[place];if(!dg||!dg.slots||dg.slots.length<=k)continue;const [i,j]=dg.slots[dg.slots.length-1-k];
    const g=el('g',{class:first||kind==='site'?'':'rise','data-depth':i+j},dg.g);marks[id]=g;
    if(kind==='built')landmark(g,i,j,x);else if(kind==='site')site(g,i,j,x);else monument(g,i,j,x);
    [...dg.g.children].sort((p,q)=>(+p.dataset.depth||0)-(+q.dataset.depth||0)).forEach(e=>dg.g.appendChild(e));litSig='';
    if(!first&&kind==='built')toast(`${x.emoji} ${x.name} is built! The colony voted for it.`,place);
    if(!first&&kind==='monument')toast(`${x.emoji} A season monument rises in the Commons!`,'commons')}}
function bunting(g,x1,y1,x2,y2,cols){const n=Math.max(4,Math.round(Math.hypot(x2-x1,y2-y1)/11)),sag=9,P=t=>[x1+(x2-x1)*t,y1+(y2-y1)*t+Math.sin(Math.PI*t)*sag];
  el('path',{d:`M${x1} ${y1} Q${(x1+x2)/2} ${(y1+y2)/2+sag*2} ${x2} ${y2}`,fill:'none',stroke:'#efe6d2','stroke-width':.8},g);
  for(let k=0;k<n;k++){const [xa,ya]=P(k/n),[xb,yb]=P((k+.62)/n);el('polygon',{class:'flag',points:pts([[xa,ya],[xb,yb],[(xa+xb)/2,(ya+yb)/2+6.5]]),fill:cols[k%cols.length]},g)}}
function decorate2(se){const decor=(se&&se.decor)||[],colour=(se&&se.colour)||'#ff9ad5',sig=decor.join(',')+'|'+colour+'|'+voteFest;if(sig===decorSig)return;decorSig=sig;
  const g=document.getElementById('civic');g.innerHTML='';const [cr,cc]=CELLS.commons,[a,b]=cellTiles(cr,cc),[x1,y1]=centre(a+3,b+3);
  const cols=voteFest?['#ffd35a','#ff5a8a','#70ddff','#7ee3b0']:[colour,'#fff8e6'];
  if(decor.includes('banners')||voteFest)for(const k of ['research_block','industrial_ward','market_concourse','park']){const [r,c]=CELLS[k],[a2,b2]=cellTiles(r,c),[x2,y2]=centre(a2+3,b2+3);
    bunting(g,x1,y1-66,x1+(x2-x1)*.62,y1+(y2-y1)*.62-30,cols)}   // from above the Kernel's top
  if(decor.includes('lanterns'))for(const k in LOOK){const [x,y]=labelXY(k);for(const dx of [-46,46]){el('line',{x1:x+dx,y1:y+14,x2:x+dx,y2:y-12,stroke:'#4a3a2e','stroke-width':1.3},g);
    el('rect',{x:x+dx-2.8,y:y-18,width:5.6,height:7,rx:2,fill:'#c2302a',stroke:'#7a1a1a','stroke-width':.6},g);el('rect',{class:'win lamp',x:x+dx-1.4,y:y-16.5,width:2.8,height:4,fill:'#ffd98a',opacity:0,'data-v':'0.05'},g)}}
  litSig=''}
function civic(d){const f=d.vote&&d.vote.festival,chip=document.getElementById('fest');chip.textContent=f?`${f.emoji} ${f.name}`:'';
  const key=f?f.key:'';if(key!==voteFest){if(!first&&f)toast(`${f.emoji} ${f.name} today! The colony voted for it.`,'commons');voteFest=key;crowdSig=''}
  landmarks(d.vote,d.season);decorate2(d.season)}

// ---- new citizens: a welcome banner, the camera finds their Seedling, and it says hello
let lastJoin=null;const newcomers={};   // name -> until when they are shown first in their district
const isNew=s=>(newcomers[(s.name||'').toLowerCase()]||0)>Date.now();
function welcomeNew(d){const joins=(d.highlights||[]).filter(h=>h.kind==='join');const top=joins.length?Math.max(...joins.map(h=>h.id)):0;
  if(lastJoin===null){lastJoin=top;return}   // only people who join while the map is open
  for(const h of joins.filter(h=>h.id>lastJoin).sort((a,b)=>a.id-b.id)){const who=String(h.name||'').replace(/\s*\[.*?\]\s*/g,'').trim();
    newcomers[who.toLowerCase()]=Date.now()+5*60000;seedlings(latest);toast(`🌱 Welcome to New Eridian, ${who}!`);setTimeout(()=>greet(who),2500)}
  lastJoin=Math.max(lastJoin,top)}
function greet(who,tries=0){const s=latest.find(x=>x.name.toLowerCase()===who.toLowerCase());const t=s&&live[s.id];if(!t)return;
  if(t.path.length||t.hidden){if(tries<12)setTimeout(()=>greet(who,tries+1),700);return}   // wait until they reach their spot
  lockUntil=Date.now()+9000;look(t.x,t.y-24*TK(),CARD?2.4:1.9);speaking=s.id;
  setTimeout(()=>speak(t,'Hi everyone! I just moved in. 👋'),1600)}

// ---- captions: each Seedling in turn, with something new to say
let capIndex=0,capTick=0;const said={};
function caption(){const cap=document.getElementById('cap'),pool=latest.filter(s=>(s.lines&&s.lines.length)||s.thought);if(!pool.length){cap.classList.add('hide');return}
  const s=pool[capIndex++%pool.length],lines=(s.lines&&s.lines.length)?s.lines:[s.thought],idx=said[s.id]||0,line=lines[idx%lines.length],place=(LOOK[s.place]||LOOK.commons);
  cap.classList.add('hide');setTimeout(()=>{cap.innerHTML=`<span class="mood">${esc(s.mood_emoji||'🙂')}</span><div class="text"><div class="top"><span class="who">${s.badge?esc(s.badge)+' ':''}${esc(s.name)}</span> · <span class="what">${esc(place[0])} ${esc(s.activity)}</span></div>${line?`<div class="said">“${esc(line)}”</div>`:''}</div>`;cap.classList.remove('hide');tidyLabels()},450);
  said[s.id]=idx+1;const t=live[s.id];speaking=s.id;
  if(Date.now()>=lockUntil){capTick++;const closeUp=CARD?capTick%4!==0:capTick%2===1;   // a small card stays close up, with a look at the whole town every fourth turn
    if(t&&!t.path.length&&closeUp)look(t.x,t.y-24*TK(),CARD?2.4:1.9);else look()}
  speak(t,line)}
setInterval(caption,SECONDS);
poll(d=>{try{
  if(Q.get('phase'))d.phase=Q.get('phase');if(Q.get('weather')){d.condition_key=Q.get('weather');d.condition=Q.get('weather').replace(/_/g,' ')}
  festival=previewHoliday()||d.festival||null;if(!first&&weatherKey&&d.condition_key&&d.condition_key!==weatherKey&&!Q.get('weather'))toast(`${WEATHER_ICON[d.condition_key]||'🌤️'} ${d.condition||'The weather'} rolling in`);weatherKey=d.condition_key||'';
  const hour=Q.get('hour')?Number(Q.get('hour')):Q.get('phase')?PREVIEW_HOUR[d.phase]??12:(d.hour??PREVIEW_HOUR[d.phase]??12);
  if(Q.get('hour')){const h=((hour%24)+24)%24;d.phase=h<6?'Morning':h<15?'Day':h<19?'Evening':'Night';d.phase_emoji={Morning:'🌅',Day:'☀️',Evening:'🌇',Night:'🌙'}[d.phase]}
  if(!first&&lastPhase&&d.phase!==lastPhase&&PHASE_NEWS[d.phase])toast(PHASE_NEWS[d.phase]);lastPhase=d.phase;
  const tier=d.tier_index||0;if(!first&&lastTier>=0&&tier>lastTier)toast(`🏙️ New Eridian is now a ${d.tier_name||d.tier}!`);
  if(tier!==lastTier){streets(d,tier);lastTier=tier}for(const k in CELLS)district(k,(d.districts||{})[k]||{},tier);labelsFor(d);tidyLabels();
  sky(hour,weatherKey);night=darkness>.3;effects(d.phase);glitches(weatherKey==='sensor_noise');shuttles(weatherKey==='busy_spaceport'&&darkness<.6);
  latest=d.seedlings||[];lastData=d;civic(d);liveTown(d);statPanel(d);fitHome();welcomeNew(d);seedlings(latest);if(first){first=false;caption()}
  document.getElementById('tier').textContent=`${d.tier_name||d.tier||'Outpost'} · ${d.population||0} citizens`;
  const hol=document.getElementById('hol');if(festival&&HOLIDAYS[festival.name]){const n=festival.days_to_holiday;hol.style.setProperty('--hol',HOLIDAYS[festival.name][1][0]);
    const GREET={'Christmas':'Merry Christmas!','Memorial Day':'Memorial Day','Thanksgiving':'Happy Thanksgiving!'};hol.textContent=`${festival.emoji} `+(n===0?(GREET[festival.name]||`Happy ${festival.name}!`):n>0?`${festival.name} in ${n} day${n===1?'':'s'}`:`${festival.name} festival`)}else hol.textContent='';
  const busy=latest.filter(s=>/^Working|^Queue|^Gathering/.test(s.activity)).length;
  const hh=Math.floor(((hour%24)+24)%24),mm=Math.floor((hour%1)*60);document.getElementById('info').textContent=`${d.phase_emoji||''} Day ${d.day} · ${String(hh).padStart(2,'0')}:${String(mm).padStart(2,'0')} ${d.phase} · ${WEATHER_ICON[weatherKey]||''} ${d.condition||''}`+(festival||voteFest||CARD?'':` · ${busy} working`);
}catch(e){console.error(e)}},4000);
</script>""")

PAGES['narrator'] = (r"""
body{padding:4px}.news{overflow:hidden;border-radius:var(--radius);border:1px solid var(--edge);background:linear-gradient(145deg,rgba(8,13,39,.97),rgba(24,15,54,.96));box-shadow:0 10px 30px rgba(0,0,0,.4)}
.bar{display:flex;align-items:center;gap:10px;padding:8px 14px;background:linear-gradient(90deg,#b3123a,#e0294f 55%,#7b1f6e);color:#fff}
.bar .live{padding:2px 8px;border-radius:5px;background:#fff;color:#b3123a;font:900 11px var(--font-body);letter-spacing:.12em}
.bar .net{font:900 13px var(--font-body);letter-spacing:.16em}.bar .clock{margin-left:auto;font:700 12px var(--font-body);opacity:.9}
.story{padding:12px 16px 12px}.desk{display:inline-block;padding:2px 8px;border-radius:5px;background:rgba(112,221,255,.14);border:1px solid rgba(112,221,255,.4);color:var(--cyan);font:900 10.5px var(--font-body);letter-spacing:.14em}
.head{margin-top:7px;font:600 23px/1.2 var(--font-display);color:#fff}.body{margin-top:6px;font-size:15px;line-height:1.45;color:#d9d6ef;min-height:44px}
.body .cursor{display:inline-block;width:2px;height:1em;background:var(--green2);margin-left:2px;vertical-align:-2px;animation:blink 1s infinite}
.crawl{display:flex;flex-direction:column;gap:5px;padding:9px 16px 11px;border-top:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.18)}
.crawl div{font-size:13px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.crawl b{color:#fff;font-weight:700}
.swap{animation:ne-in var(--dur) var(--ease) both}@keyframes swap{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}@keyframes blink{50%{opacity:0}}
""", r"""
<div class="news"><div class="bar"><span class="live">● LIVE</span><span class="net">NEW ERIDIAN NEWS</span><span class="clock" id="clock"></span></div>
<div class="story" id="story"><span class="desk">COLONY</span><div class="head">Awaiting the first report from Avesta…</div><div class="body"></div></div><div class="crawl" id="crawl"></div></div>
<script>
const LINES=Number(Q.get('lines')||3);let shown=null,typing=null,queue=[],rows=[];
function show(){if(!queue.length)return;const n=queue.shift();shown=n.id;clearInterval(typing);
  const st=document.getElementById('story');st.innerHTML=`<span class="desk">${esc(n.desk||'COLONY')}</span><div class="head">${esc(n.emoji)} ${esc(n.headline||n.text)}</div><div class="body"></div>`;
  st.classList.remove('swap');void st.offsetWidth;st.classList.add('swap');const body=st.querySelector('.body'),text=n.text;let i=0;
  typing=setInterval(()=>{i+=3;body.innerHTML=esc(text.slice(0,i))+'<span class="cursor"></span>';if(i>=text.length){clearInterval(typing);body.innerHTML=esc(text)+` <span style="color:var(--muted);font-size:12px">· ${ago(n.at)}</span>`}},24);
  document.getElementById('crawl').innerHTML=rows.filter(r=>r.id<n.id).slice(0,LINES).map(r=>`<div>${esc(r.emoji)} <b>${esc(r.headline||'')}</b> — ${esc((r.text||'').split(' — ').slice(-1)[0])}</div>`).join('')}
poll(d=>{rows=d.narration||[];document.getElementById('clock').textContent=`${d.phase_emoji||''} DAY ${d.day||'—'} · ${(d.phase||'').toUpperCase()}`;
  if(!rows.length)return;if(shown===null){queue.push(rows[0]);show();return}
  for(const r of rows.slice().reverse())if(r.id>shown&&!queue.some(q=>q.id===r.id))queue.push(r)},4000);
setInterval(show,Number(Q.get('seconds')||10)*1000);
</script>""")

PAGES['hub'] = (r"""
/* One source instead of many: slides rotate through every overlay panel's information.
   16:9, sized in vw so it reads at any source size (640×360 recommended). */
body{padding:0}.hub{position:fixed;inset:0;display:flex;flex-direction:column;overflow:hidden;border-radius:2.2vw;border:2px solid var(--edge);
  background:radial-gradient(circle at 88% 0,rgba(125,72,220,.18),transparent 45%),linear-gradient(145deg,rgba(8,13,39,.96),rgba(24,15,54,.95));font-size:clamp(12px,3.35vw,64px)}
.top{display:flex;align-items:center;gap:.6em;padding:.55em .9em .4em;border-bottom:1px solid rgba(255,255,255,.08)}
.swap{animation:ne-in var(--dur) var(--ease) both}.top .title{font-weight:900;letter-spacing:.12em;text-transform:uppercase;color:var(--green2);font-size:.9em;white-space:nowrap}
.dots{margin-left:auto;display:flex;gap:.35em}.dots i{width:.5em;height:.5em;border-radius:50%;background:rgba(255,255,255,.2)}.dots i.on{background:var(--green)}.dots i.live{background:var(--danger)}
.body{flex:1;padding:.5em .9em;min-height:0;min-width:0;overflow:hidden;display:flex;flex-direction:column;justify-content:center;gap:.45em}.slide{animation:ne-slide-in .6s var(--ease) both}.slide.out{animation:ne-slide-out .35s var(--ease) both}
@keyframes in{from{opacity:0;transform:translateX(3%)}to{opacity:1;transform:none}}
.timer{height:.28em;background:rgba(255,255,255,.07)}.timer i{display:block;height:100%;background:linear-gradient(90deg,var(--green),var(--violet));transform-origin:left}
h2{margin:0;font:700 1.45em/1.1 var(--font-display);color:var(--ivory)}.sub{color:var(--muted);font-size:.78em;line-height:1.3}
.big{font-size:1.1em;font-weight:800}.row{display:flex;align-items:center;gap:.5em;min-width:0}.row .grow{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar{height:.5em;border-radius:99px;background:rgba(255,255,255,.1);overflow:hidden}.bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--green),var(--violet))}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.35em .7em}.stat{padding:.3em .45em;border-radius:.4em;background:rgba(0,0,0,.22)}.stat b{display:block;font-size:1.05em}.stat small{display:block;color:var(--muted);font-size:.66em;text-transform:uppercase;letter-spacing:.06em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.list{display:flex;flex-direction:column;gap:.3em}.list .row{padding:.22em .45em;border-radius:.4em;background:rgba(0,0,0,.2);font-size:.9em}
.num{color:var(--green2);font-weight:900;font-variant-numeric:tabular-nums;white-space:nowrap}.hot{color:var(--amber)}.red{color:#ff9aa6}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:.6em}.cols h3{margin:0 0 .2em;font-size:.7em;letter-spacing:.1em;text-transform:uppercase;color:var(--cyan)}
/* Layouts by source shape: 'strip' for a wide band (e.g. 1440×120 under a game window), 'tall' for a side column (e.g. 340×440).
   Text is sized from the source so it stays readable; anything that still overflows shrinks to fit. */
.L-tall .hub{border-radius:1.1em;font-size:clamp(12px,min(4.9vw,3.6vh),40px)}.L-tall .grid{grid-template-columns:repeat(2,1fr)}.L-tall .cols{grid-template-columns:1fr}
.L-tall h2{font-size:1.3em}
/* 'compact': a small side-column box (e.g. 340×180): larger type, tighter spacing; slides shrink to fit if needed. */
.L-compact .hub{border-radius:.8em;font-size:clamp(12px,min(4.9vw,9vh),30px)}.L-compact .top{padding:.35em .6em .25em}.L-compact .body{padding:.3em .6em;gap:.3em}
.L-compact h2{font-size:1.2em}.L-compact .grid{gap:.25em .4em}.L-compact .stat{padding:.2em .35em}.L-compact .list{gap:.2em}.L-compact .cols{gap:.4em}
.L-strip .hub{flex-direction:row;border-radius:.9em;font-size:clamp(11px,min(15vh,1.5vw),40px)}
.L-strip .top{flex:none;width:9.5em;flex-direction:column;align-items:flex-start;justify-content:center;gap:.4em;border-bottom:0;border-right:1px solid rgba(255,255,255,.1);padding:.4em .8em}
.L-strip .top .title{font-size:.85em;white-space:normal;line-height:1.15}.L-strip .dots{margin-left:0}
.L-strip .body{flex-direction:row;align-items:center;padding:.35em .9em .5em}.L-strip .timer{position:absolute;left:0;right:0;bottom:0}
.srow{display:flex;align-items:stretch;gap:.7em;width:100%;min-width:0}.scol{display:flex;flex-direction:column;justify-content:center;gap:.18em;min-width:0}
.tile{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center;gap:.15em;padding:.25em .55em;border-radius:.45em;background:rgba(0,0,0,.24)}
.tile small{color:var(--muted);font-size:.62em;font-weight:800;text-transform:uppercase;letter-spacing:.08em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tile b{font-size:1em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tile .sub{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ell{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
/* Every word stays visible: long lines wrap instead of ending in "…", and fit() shrinks the slide until it fits. */
.hub .grow,.hub .ell,.hub .tile b,.hub .tile .sub,.hub .tile small,.hub .sub{white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere}
.hub .row{align-items:center}.hub .num{flex:none}
code{padding:.08em .4em;border-radius:.35em;background:rgba(126,227,176,.14);border:1px solid rgba(126,227,176,.45);color:var(--green2);font:800 .95em ui-monospace,monospace}
.tag{display:inline-block;padding:.05em .45em;border-radius:.35em;background:rgba(112,221,255,.14);color:var(--cyan);font-size:.62em;font-weight:900;letter-spacing:.12em}
""", r"""
<div class="hub"><div class="top"><span class="title" id="title">New Eridian</span><span class="dots" id="dots"></span></div>
<div class="body" id="body"><div class="sub">Connecting to Avesta…</div></div><div class="timer"><i id="timer"></i></div></div>
<script>
const EVERY=Number(Q.get('seconds')||12)*1000,PICK=(Q.get('slides')||'').split(',').filter(Boolean);
const pct=v=>Math.max(0,Math.min(100,Number(v)||0)),bar=v=>`<div class="bar"><i style="width:${pct(v)}%"></i></div>`,n=v=>Number(v||0).toLocaleString();
// Each slide: [key, title, has-content test, render]. Slides with nothing to show are skipped.
const SLIDES=[
 ['society','🏛️ Society',d=>true,d=>{const s=d.stats||{},b=d.bottleneck||{};return `<h2>New Eridian · ${esc(d.tier)}</h2>
   <div class="sub">${esc(d.phase_emoji||'')} Avesta Day ${d.day} · ${esc(d.phase)} · ${d.active_players||0} active · ${n(s.population)} citizens</div>
   <div class="row"><span class="big">${esc(d.condition||'')}</span></div><div class="sub">${esc(d.condition_text||'')}</div>
   ${d.next_tier?`<div class="row"><span class="grow">Next: <b>${esc(d.next_tier)}</b> · weakest: ${esc(b.name||'')} ${n(b.value)}/${n(b.target)}</span><span class="num">${Math.round(d.tier_percent||0)}%</span></div>${bar(d.tier_percent)}`:'<div class="sub">Maximum tier reached.</div>'}`}],
 ['stats','📊 Society stats',d=>d.stats,d=>{const s=d.stats,t=d.tier_target||1,m=[['🌾','Food','food'],['⛏️','Materials','materials'],['⚙️','Development','development'],['🔬','Knowledge','knowledge'],['🪙','Treasury','treasury'],['⭐','Reputation','reputation']];
   return `<div class="grid">${m.map(([i,l,k])=>`<div class="stat"><small>${i} ${l}</small><b>${n(s[k])}</b>${bar(s[k]/t*100)}</div>`).join('')}</div>
   <div class="sub">${d.next_tier?`Each needs ${n(t)} for ${esc(d.next_tier)}.`:'All stats past the top tier.'} Tier bonus: ${d.tier_bonus?'+'+d.tier_bonus+' SC on success':'none yet'}.</div>`}],
 ['today','📋 Today',d=>d.directive&&d.directive.name,d=>{const q=d.directive,a=d.aftermath,f=d.festival;return `<h2>${q.complete?'✅ ':''}${esc(q.name)}</h2><div class="sub">${esc(q.description||'')}</div>
   <div class="row"><span class="grow">Useful: ${esc((q.skills||[]).join(' · '))} · Reward ${esc(q.reward||'')}</span><span class="num">${q.progress}/${q.goal}</span></div>${bar(q.percent)}
   ${a?`<div class="row"><span class="${Number(a.modifier)>=0?'hot':'red'} big">Aftermath ${Number(a.modifier)>=0?'+':''}${a.modifier}%</span><span class="sub grow">${esc(a.event)} · ${esc((a.skills||[]).join(' / '))}</span></div>`:''}
   ${f?`<div class="row"><span class="big">${esc(f.emoji)} ${esc(f.name)} festival</span><span class="sub grow">${f.days_left} days left · ${esc((f.foods||[]).join(', '))}</span></div>`:''}`}],
 ['event','🚨 Live event',d=>d.event,d=>{const e=d.event,t=Math.max(0,e.seconds_remaining|0);return `<h2 class="red">${esc(e.emoji)} ${esc(e.name)}</h2>
   <div class="row"><span class="grow big">${e.progress}/${e.goal} responses</span><span class="num">${Math.floor(t/60)}:${String(t%60).padStart(2,'0')} left</span></div>${bar(e.percent)}
   <div class="sub">Primary: <b>${esc(e.primary)}</b> work · Support: <b>${esc(e.support)}</b> (2 = +1)</div>
   ${(e.leaders||[]).length?`<div class="list">${e.leaders.slice(0,3).map((l,i)=>`<div class="row"><span>${['🥇','🥈','🥉'][i]}</span><span class="grow">${esc(l.name)}</span><span class="num">${l.primary} + ${l.support}</span></div>`).join('')}</div>`:'<div class="sub">No responders yet. Jump in!</div>'}`}],
 ['challenge','⚡ Stream challenge',d=>d.challenge,d=>{const c=d.challenge,t=Math.max(0,c.seconds_left|0),done=c.state!=='active';return `<h2 class="${c.state==='won'?'':'red'}">${esc(c.emoji)} ${esc(c.title)}${c.state==='won'?' · complete!':c.state==='lost'?' · time up':''}</h2>
   <div class="sub">${esc(c.text)}</div><div class="row"><span class="grow big">${c.progress}/${c.goal}</span><span class="num">${done?c.participants+' helped':Math.floor(t/60)+':'+String(t%60).padStart(2,'0')+' left'}</span></div>${bar(c.percent)}
   ${done?'':`<div class="row"><code>${esc(c.how)}</code><span class="sub grow">in chat to help</span></div>`}
   ${(c.top||[]).length?`<div class="list">${c.top.map((x,i)=>`<div class="row"><span>${['🥇','🥈','🥉'][i]}</span><span class="grow">${esc(x.name)}</span><span class="num">${x.amount}</span></div>`).join('')}</div>`:'<div class="sub">Nobody yet. Be the first!</div>'}`}],
 ['vote','🗳️ Colony vote',d=>d.vote&&(d.vote.options||[]).length,d=>{const v=d.vote,tot=Math.max(1,v.total);return `<h2>What next for New Eridian?</h2>
   <div class="list">${v.options.map(o=>`<div><div class="row"><code>!vote ${o.n}</code><span class="grow big">${esc(o.emoji)} ${esc(o.name)}</span><span class="num">${o.votes}</span></div>${bar(o.votes/tot*100)}</div>`).join('')}</div>
   <div class="sub">Closes in ${esc(v.closes_in)}${v.festival?` · today: ${esc(v.festival.emoji)} <b>${esc(v.festival.name)}</b>`:''}${v.next_project?` · next build: <b>${esc(v.next_project)}</b>`:''}</div>`}],
 ['season','🏁 Season',d=>d.season,d=>{const se=d.season;return `<h2>${esc(se.emoji)} ${esc(se.name)}</h2><div class="sub">Season ${se.number} · chapter ${se.chapter}/${se.chapters} · ${se.days_left} days left</div>
   <div class="sub">📖 ${esc(se.story)}</div><div class="row"><span class="grow">🤝 Community ${n(se.total)}${se.total>=se.goal?' · every milestone reached':'/'+n(se.goal)}</span><span class="num">${se.total>=se.goal?'✓':Math.round(se.percent)+'%'}</span></div>${bar(se.percent)}
   ${(se.top||[]).length?`<div class="list">${se.top.slice(0,3).map((x,i)=>`<div class="row"><span>${['🥇','🥈','🥉'][i]}</span><span class="grow">${esc(x.name)}</span><span class="num">${n(x.points)}</span></div>`).join('')}</div>`:'<div class="sub">Type <code>!season</code> to see your points.</div>'}`}],
 ['projects','🏗️ Project & story',d=>d.project&&d.project.name,d=>{const p=d.project,s=d.story||{},tr=s.tracks||[],tot=tr.reduce((a,x)=>a+(x.value||0),0);return `
   <div class="row"><span class="grow big">🏗️ ${esc(p.name)}</span><span class="num">${p.progress}/${p.goal}</span></div>${bar(p.percent)}<div class="sub">Helps: ${esc((p.skills||[]).join(' · '))}</div>
   <div class="row"><span class="grow big">📖 ${esc(s.name||'')}</span><span class="num">${Math.round(s.percent||0)}%</span></div>${bar(s.percent)}
   <div class="sub">${tr.map(x=>`${esc(x.name)} ${tot?Math.round(x.value/tot*100):0}%`).join(' · ')||'No story votes yet.'}</div>`}],
 ['market','💰 Market',d=>d.market&&d.market.primary,d=>{const m=d.market;return `<h2>Today's demand</h2>
   <div class="list"><div class="row"><span>🔥</span><span class="grow big">${esc(m.primary.name)}</span><span class="num hot">${m.primary.price} SC</span></div>
   ${m.secondary?`<div class="row"><span>↑</span><span class="grow big">${esc(m.secondary.name)}</span><span class="num">${m.secondary.price} SC</span></div>`:''}</div>
   <div class="sub">Seed Industries pays extra for these today. ${esc(d.pressure&&d.pressure.length?'Shortages: '+d.pressure.join(', ')+'.':'')}</div>
   ${d.rumor?`<div class="sub">🗣️ ${esc(d.rumor)}</div>`:''}`}],
 ['leaders','🏆 Leaders',d=>d.leaders&&((d.leaders.contributors||[]).length||(d.leaders.active_today||[]).length),d=>{const L=d.leaders,li=(r,v)=>r.slice(0,4).map((x,i)=>`<div class="row"><span>${['🥇','🥈','🥉','4.'][i]}</span><span class="grow">${esc(x.name)}</span><span class="num">${v(x)}</span></div>`).join('')||'<div class="sub">No one yet.</div>';
   return `<div class="cols"><div><h3>Top contributors</h3><div class="list">${li(L.contributors||[],x=>n(x.contribution))}</div></div><div><h3>Most active · 24h</h3><div class="list">${li(L.active_today||[],x=>x.actions)}</div></div></div>`}],
 ['working','⏱️ Working now',d=>(d.working||[]).length,d=>`<div class="list">${d.working.slice(0,4).map(x=>`<div><div class="row"><span class="grow"><b>${esc(x.name)}</b> · ${esc(x.task)}${x.state==='paused'?' <span class="hot">paused</span>':''}</span><span class="num">${x.done}/${x.total}</span></div>${bar(x.total?x.done/x.total*100:0)}</div>`).join('')}</div>${d.working.length>4?`<div class="sub">+${d.working.length-4} more queues running</div>`:''}`],
 ['seedlings','🌱 Seedlings',d=>(d.seedlings||[]).length,d=>{const s=d.seedlings.slice(0,5);return `<div class="list">${s.map(x=>`<div class="row"><span>${esc(x.mood_emoji)}</span><span class="grow"><b>${esc(x.name)}</b> · ${esc(x.activity)} <span class="sub">· ${esc(x.place_name)}</span></span></div>`).join('')}</div>${d.seedlings.length>5?`<div class="sub">${d.seedlings.length} Seedlings out on Avesta</div>`:''}`}],
 ['news','📰 News',d=>(d.narration||[]).length,d=>`<div class="list">${d.narration.slice(0,3).map(x=>`<div><div class="row"><span class="tag">${esc(x.desk||'COLONY')}</span><span class="grow big">${esc(x.emoji)} ${esc(x.headline||'')}</span></div><div class="sub">${esc((x.text||'').split(' — ').slice(-1)[0])}</div></div>`).join('')}</div>`],
 ['join','🌱 Play from chat',d=>d.join,d=>{const t=(d.join.tips||[]).slice(0,4);return `<h2>Join New Eridian</h2><div class="list">${t.map(x=>`<div class="row"><code>${esc(x[0])}</code><span class="grow sub">${esc(x[1])}</span></div>`).join('')}</div>
   ${d.join.discord?`<div class="sub">Crafting, queues, shopping lists, keep levels and quiet hours on Discord: <b>${esc(d.join.discord.replace(/^https?:\/\//,''))}</b></div>`:''}`}],
];
// The same slides laid out in one horizontal band for the 'strip' layout.
const T=(label,value,extra='')=>`<div class="tile"><small>${label}</small><b>${value}</b>${extra}</div>`;
const STRIP={
 society:d=>{const s=d.stats||{},b=d.bottleneck||{};return `<div class="srow"><div class="scol" style="flex:1.3"><h2 class="ell">New Eridian · ${esc(d.tier)}</h2><div class="sub ell">${esc(d.phase_emoji||'')} Day ${d.day} · ${esc(d.phase)} · ${d.active_players||0} active · ${n(s.population)} citizens</div></div>
   <div class="scol" style="flex:1.2"><b class="ell">${esc(d.condition||'')}</b><div class="sub ell">${esc(d.condition_text||'')}</div></div>
   <div class="scol" style="flex:1">${d.next_tier?`<div class="row"><span class="grow">→ <b>${esc(d.next_tier)}</b> · needs ${esc(b.name||'')}</span><span class="num">${Math.round(d.tier_percent||0)}%</span></div>${bar(d.tier_percent)}`:'<b>Top tier reached</b>'}</div></div>`},
 stats:d=>{const s=d.stats,t=d.tier_target||1,m=[['🌾','Food','food'],['⛏️','Materials','materials'],['⚙️','Development','development'],['🔬','Knowledge','knowledge'],['🪙','Treasury','treasury'],['⭐','Reputation','reputation']];
   return `<div class="srow">${m.map(([i,l,k])=>T(`${i} ${l}`,n(s[k]),bar(s[k]/t*100))).join('')}</div>`},
 today:d=>{const q=d.directive,a=d.aftermath,f=d.festival;return `<div class="srow"><div class="scol" style="flex:1.4"><b class="ell">${q.complete?'✅ ':''}📋 ${esc(q.name)}</b><div class="sub ell">${esc(q.description||'')}</div></div>
   <div class="scol" style="flex:1"><div class="row"><span class="grow sub">${esc((q.skills||[]).join(' · '))}</span><span class="num">${q.progress}/${q.goal}</span></div>${bar(q.percent)}</div>
   ${a?T('Aftermath',`<span class="${Number(a.modifier)>=0?'hot':'red'}">${Number(a.modifier)>=0?'+':''}${a.modifier}%</span>`,`<span class="sub">${esc(a.event)}</span>`):''}${f?T(`${esc(f.emoji)} Festival`,esc(f.name),`<span class="sub">${f.days_left} days left</span>`):''}</div>`},
 event:d=>{const e=d.event,t=Math.max(0,e.seconds_remaining|0);return `<div class="srow"><div class="scol" style="flex:1.2"><h2 class="red ell">${esc(e.emoji)} ${esc(e.name)}</h2><div class="sub ell">Primary <b>${esc(e.primary)}</b> · Support <b>${esc(e.support)}</b></div></div>
   <div class="scol" style="flex:1"><div class="row"><span class="grow">${e.progress}/${e.goal}</span><span class="num">${Math.floor(t/60)}:${String(t%60).padStart(2,'0')}</span></div>${bar(e.percent)}</div>
   ${(e.leaders||[]).slice(0,3).map((l,i)=>T(['🥇','🥈','🥉'][i],esc(l.name),`<span class="num">${l.primary} + ${l.support}</span>`)).join('')}</div>`},
 challenge:d=>{const c=d.challenge,t=Math.max(0,c.seconds_left|0),done=c.state!=='active';return `<div class="srow"><div class="scol" style="flex:1.3"><h2 class="${c.state==='won'?'':'red'} ell">${esc(c.emoji)} ${esc(c.title)}${c.state==='won'?' · complete!':c.state==='lost'?' · time up':''}</h2><div class="sub ell">${esc(c.text)}</div></div>
   <div class="scol" style="flex:1"><div class="row"><span class="grow">${c.progress}/${c.goal}</span><span class="num">${done?c.participants+' helped':Math.floor(t/60)+':'+String(t%60).padStart(2,'0')}</span></div>${bar(c.percent)}</div>
   ${done?'':T('Help in chat',`<code>${esc(c.how)}</code>`)}${(c.top||[]).slice(0,2).map((x,i)=>T(['🥇','🥈'][i],esc(x.name),`<span class="num">${x.amount}</span>`)).join('')}</div>`},
 vote:d=>{const v=d.vote,tot=Math.max(1,v.total);return `<div class="srow"><div class="scol" style="flex:.9"><h2 class="ell">🗳️ Colony vote</h2><div class="sub ell">Closes in ${esc(v.closes_in)}</div></div>${v.options.map(o=>T(`!vote ${o.n}`,`${esc(o.emoji)} ${esc(o.name)}`,`<div class="row"><span class="grow">${bar(o.votes/tot*100)}</span><span class="num">${o.votes}</span></div>`)).join('')}</div>`},
 season:d=>{const se=d.season;return `<div class="srow"><div class="scol" style="flex:1.3"><h2 class="ell">${esc(se.emoji)} ${esc(se.name)}</h2><div class="sub ell">Chapter ${se.chapter}/${se.chapters} · ${se.days_left} days left</div></div>
   <div class="scol" style="flex:1"><div class="row"><span class="grow">🤝 ${n(se.total)}${se.total>=se.goal?' · all milestones':'/'+n(se.goal)}</span><span class="num">${se.total>=se.goal?'✓':Math.round(se.percent)+'%'}</span></div>${bar(se.percent)}</div>${(se.top||[]).slice(0,3).map((x,i)=>T(['🥇','🥈','🥉'][i],esc(x.name),`<span class="num">${n(x.points)}</span>`)).join('')}</div>`},
 projects:d=>{const p=d.project,s=d.story||{};return `<div class="srow"><div class="scol" style="flex:1"><div class="row"><b class="grow ell">🏗️ ${esc(p.name)}</b><span class="num">${p.progress}/${p.goal}</span></div>${bar(p.percent)}<div class="sub ell">Helps: ${esc((p.skills||[]).join(' · '))}</div></div>
   <div class="scol" style="flex:1"><div class="row"><b class="grow ell">📖 ${esc(s.name||'')}</b><span class="num">${Math.round(s.percent||0)}%</span></div>${bar(s.percent)}<div class="sub ell">${(s.tracks||[]).map(x=>esc(x.name)).join(' · ')}</div></div></div>`},
 market:d=>{const m=d.market;return `<div class="srow">${T('🔥 Top demand',esc(m.primary.name),`<span class="num hot">${m.primary.price} SC</span>`)}${m.secondary?T('↑ Also wanted',esc(m.secondary.name),`<span class="num">${m.secondary.price} SC</span>`):''}
   ${T('⚠️ Shortages',esc(d.pressure&&d.pressure.length?d.pressure.join(', '):'None'))}${d.rumor?`<div class="scol" style="flex:2"><small class="sub">🗣️ RUMOR</small><div class="sub" style="line-height:1.25">${esc(d.rumor)}</div></div>`:''}</div>`},
 leaders:d=>{const L=d.leaders;return `<div class="srow">${(L.contributors||[]).slice(0,4).map((x,i)=>T(['🥇 Top','🥈 2nd','🥉 3rd','4th'][i],esc(x.name),`<span class="num">${n(x.contribution)}</span>`)).join('')}${(L.active_today||[]).slice(0,1).map(x=>T('⚡ Most active 24h',esc(x.name),`<span class="num">${x.actions} actions</span>`)).join('')}</div>`},
 working:d=>`<div class="srow">${d.working.slice(0,4).map(x=>T(esc(x.name),esc(x.task),bar(x.total?x.done/x.total*100:0))).join('')}${d.working.length>4?`<div class="scol"><span class="sub">+${d.working.length-4} more</span></div>`:''}</div>`,
 seedlings:d=>`<div class="srow">${d.seedlings.slice(0,4).map(x=>T(`${esc(x.mood_emoji)} ${esc(x.place_name)}`,esc(x.name),`<span class="sub">${esc(x.activity)}</span>`)).join('')}</div>`,
 news:d=>`<div class="srow">${d.narration.slice(0,2).map(x=>`<div class="scol" style="flex:1"><div class="row"><span class="tag">${esc(x.desk||'COLONY')}</span><b class="ell">${esc(x.emoji)} ${esc(x.headline||'')}</b></div><div class="sub ell">${esc((x.text||'').split(' — ').slice(-1)[0])}</div></div>`).join('')}</div>`,
 join:d=>`<div class="srow"><div class="scol"><h2 style="white-space:nowrap">Join New Eridian</h2>${d.join.discord?`<div class="sub ell">Discord: <b>${esc(d.join.discord.replace(/^https?:\/\//,''))}</b></div>`:'<div class="sub">Type in chat</div>'}</div>${(d.join.tips||[]).slice(0,4).map(x=>`<div class="tile"><code style="align-self:flex-start">${esc(x[0])}</code><span class="sub">${esc(x[1])}</span></div>`).join('')}</div>`,
};
function layoutOf(){const q=Q.get('layout');if(['strip','tall','wide','compact'].includes(q))return q;const r=innerWidth/Math.max(1,innerHeight);return r>=4?'strip':r<=1.15?'tall':innerWidth<560?'compact':'wide'}
let LAYOUT=layoutOf();document.body.classList.add('L-'+LAYOUT);
addEventListener('resize',()=>{const l=layoutOf();if(l!==LAYOUT){document.body.classList.replace('L-'+LAYOUT,'L-'+l);LAYOUT=l;index--;next()}else fit()});
// Whatever the layout, a slide that is still too big for the source shrinks until it fits.
function fit(){const body=document.getElementById('body'),sl=body.querySelector('.slide');if(!sl)return;
  const cs=getComputedStyle(body),H=body.clientHeight-parseFloat(cs.paddingTop)-parseFloat(cs.paddingBottom),W=body.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);
  const over=()=>sl.scrollHeight>Math.ceil(H)+.5||sl.scrollWidth>Math.ceil(W)+1,room=()=>sl.scrollHeight<H*.8;
  let f=1;sl.style.fontSize='';
  // A roomy box (a tall column) grows the slide to use the space; a tight one shrinks it until nothing overflows.
  if(LAYOUT!=='strip')while(f<1.45&&room()){f+=.05;sl.style.fontSize=f.toFixed(2)+'em';if(over()){f-=.05;sl.style.fontSize=f.toFixed(2)+'em';break}}
  while(f>.5&&over()){f-=.05;sl.style.fontSize=f.toFixed(2)+'em'}
  // Still too much? Drop whole list entries from the end (never cut words) until it fits.
  while(over()){const lists=[...sl.querySelectorAll('.list,.srow')].filter(l=>l.children.length>1);if(!lists.length)break;
    const l=lists.sort((a,b)=>b.children.length-a.children.length)[0];l.lastElementChild.remove()}}
// Shown when none of the chosen slides has anything right now (e.g. &slides=event with no live event).
const QUIET=['quiet','🌱 New Eridian',d=>true,d=>`<h2>All quiet on Avesta</h2><div class="sub">${esc(d.phase_emoji||'')} Day ${d.day} · ${esc(d.phase||'')} · ${esc(d.condition||'')}</div><div class="sub">Nothing to show on this slide right now. Type <code>!start</code> in chat to join New Eridian.</div>`];
const ACTIVE=SLIDES.filter(s=>!PICK.length||PICK.includes(s[0]));
let data=null,index=-1,eventTurn=false;
const hotKey=d=>d.event&&ACTIVE.some(s=>s[0]==='event')?'event':d.challenge&&d.challenge.state==='active'&&ACTIVE.some(s=>s[0]==='challenge')?'challenge':null;
function next(){if(!data)return;let tries=0,slide;
  if(!ACTIVE.some(s=>s[2](data)))return show(QUIET);
  // A live event or stream challenge takes every other slide until it ends.
  const hot=hotKey(data);
  if(hot&&!eventTurn){slide=ACTIVE.find(s=>s[0]===hot);eventTurn=true}
  else{eventTurn=false;do{index=(index+1)%ACTIVE.length;slide=ACTIVE[index];tries++}while((hot&&slide[0]===hot)||(!slide[2](data)&&tries<=ACTIVE.length))}
  show(slide)}
function show(slide){
  const body=document.getElementById('body'),old=body.querySelector('.slide'),html=(LAYOUT==='strip'&&STRIP[slide[0]]?STRIP[slide[0]]:slide[3])(data),title=document.getElementById('title');
  const put=()=>{title.textContent=slide[1];title.classList.remove('swap');void title.offsetWidth;title.classList.add('swap');
    body.innerHTML=`<div class="slide" style="display:flex;flex-direction:column;gap:.45em;width:100%;max-height:100%">${html}</div>`;fit()};
  if(old){old.classList.add('out');setTimeout(put,330)}else put();
  const shown=ACTIVE.filter(s=>s[2](data));if(!shown.includes(slide))shown.push(slide);document.getElementById('dots').innerHTML=shown.map(s=>`<i class="${s===slide?'on':''}${s[0]==='event'||s[0]==='challenge'?' live':''}"></i>`).join('');
  const t=document.getElementById('timer');t.animate([{transform:'scaleX(0)'},{transform:'scaleX(1)'}],{duration:EVERY,easing:'linear'})}
poll(d=>{const first=!data;data=d;if(first){next();setInterval(next,EVERY)}},4000);
</script>""")

PAGES['challenge'] = (r"""
/* The stream challenge as a goal bar: slides in when a challenge starts, counts down, celebrates or
   shrugs at the end, then slides away. Transparent when nothing is running. Sized from the source height. */
body{padding:0;font-size:clamp(11px,24vh,40px)}
.cb{position:fixed;inset:.25em;display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:.7em;padding:.35em .9em .35em .5em;border-radius:.8em;
  background:radial-gradient(circle at 6% 50%,rgba(255,116,132,.28),transparent 45%),linear-gradient(145deg,rgba(40,10,26,.96),rgba(24,15,54,.95));border:.08em solid #ff7484;
  box-shadow:0 .3em 1.2em rgba(0,0,0,.5),0 0 1em rgba(255,116,132,.35);opacity:0;transform:translateY(30%) scale(.97);transition:opacity .5s,transform .6s var(--ease-pop)}
.cb.show{opacity:1;transform:none}.cb.won{border-color:#7ee3b0;background:radial-gradient(circle at 6% 50%,rgba(126,227,176,.3),transparent 45%),linear-gradient(145deg,rgba(8,30,28,.96),rgba(24,15,54,.95))}
.cb.lost{filter:saturate(.5)}
.cb .ic{font-size:1.9em;line-height:1;animation:bob 1.6s ease-in-out infinite alternate}@keyframes bob{to{transform:translateY(-.08em) rotate(-4deg)}}
.cb .mid{min-width:0;display:flex;flex-direction:column;gap:.18em}
.cb .t{display:flex;align-items:baseline;gap:.45em;min-width:0}.cb .t b{font:700 .95em var(--font-display);color:#fff;white-space:nowrap}.cb .t span{font-size:.55em;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cb .meter{position:relative;height:.5em;border-radius:99px;background:rgba(255,255,255,.12);overflow:hidden}.cb .meter i{position:absolute;inset:0 auto 0 0;border-radius:99px;background:linear-gradient(90deg,#ff7484,#ffd27a);transition:width .8s var(--ease)}
.cb.won .meter i{background:linear-gradient(90deg,#7ee3b0,#70ddff)}
.cb .n{display:flex;gap:.8em;font-size:.5em;font-weight:800;color:var(--muted);white-space:nowrap;overflow:hidden}.cb .n b{color:#ffd27a}.cb .n code{color:var(--green2);font-family:ui-monospace,monospace}
.cb .clock{text-align:right;font:700 1em var(--font-display);color:#fff;font-variant-numeric:tabular-nums;white-space:nowrap}.cb .clock small{display:block;font:800 .38em var(--font-body);letter-spacing:.16em;color:#ff9aa6}
.cb.won .clock small{color:var(--green2)}
""", r"""
<div class="cb" id="cb"><div class="ic" id="ic">⚡</div><div class="mid"><div class="t"><b id="tt"></b><span id="tx"></span></div><div class="meter"><i id="bar" style="width:0"></i></div><div class="n" id="nn"></div></div><div class="clock"><span id="ck"></span><small id="st">LIVE</small></div></div>
<script>
const DEMO={id:1,emoji:'🌪️',title:'Dust Storm',text:'Everyone repair the walls before the storm hits',how:'!repair or any crafting',progress:14,goal:24,percent:58,seconds_left:272,state:'active',participants:6,top:[{name:'Kamex',amount:5}]};
let cur=null,at=0;
function draw(){const box=document.getElementById('cb');if(!cur){box.classList.remove('show');return}const c=cur;
  box.className='cb show'+(c.state==='won'?' won':c.state==='lost'?' lost':'');document.getElementById('ic').textContent=c.emoji;document.getElementById('tt').textContent=c.title;
  document.getElementById('tx').textContent=c.state==='won'?'Complete! Rewards paid to every helper':c.state==='lost'?'Time ran out. Thanks for helping!':c.text;
  document.getElementById('bar').style.width=Math.min(100,c.percent||0)+'%';const top=(c.top||[])[0];
  document.getElementById('nn').innerHTML=`<span><b>${c.progress}</b> / ${c.goal}</span>`+(c.state==='active'?`<span>type <code>${esc(c.how)}</code></span>`:`<span>${c.participants} helped</span>`)+(top?`<span>🥇 ${esc(top.name)} ${top.amount}</span>`:'');
  document.getElementById('st').textContent=c.state==='active'?'● LIVE':c.state==='won'?'COMPLETE':'TIME UP';tickClock()}
function tickClock(){if(!cur)return;const left=Math.max(0,(cur.seconds_left||0)-Math.floor((Date.now()-at)/1000));document.getElementById('ck').textContent=cur.state==='active'?`${Math.floor(left/60)}:${String(left%60).padStart(2,'0')}`:cur.state==='won'?'🎉':'⌛'}
setInterval(tickClock,1000);
if(Q.get('test')){cur=DEMO;at=Date.now();draw()}
else poll(d=>{cur=d.challenge||null;at=Date.now();draw()},3000);
</script>""")

def script_json(value):
    """JSON that is safe inside a <script> element: '</script>' in a channel name can no longer end the script early."""
    return json.dumps(value).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def page(panel, channel):
    css, body = PAGES[panel]
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>New Eridian · {panel}</title>{FONTS_LINK}<style>{THEME_CSS}{BASE_CSS}{css}</style></head><body class="panel-{panel}">'
            f'<script>const CHANNEL={script_json(channel)};{SHARED_JS}</script>{body}</body></html>')


# Every OBS source, with a sensible Browser Source size.
SOURCES = [
    ('hub', 'Hub (rotating)', 'Everything in one panel: society, stats, today, the live event, the stream challenge, the colony vote, the season, project and story, market, leaders, working now, Seedlings, news and how to join. Rotates every 12 seconds; a live event or stream challenge shows every other slide. Adapts to any source shape: a side column (340×176 compact, 340×440 tall) or a band under the game (1440×120 strip).', 640, 360, '&seconds=12 · &slides=society,event,news · &layout=compact|tall|strip|wide to force a layout'),
    ('map', 'Avesta map', 'New Eridian as a living SEED-style colony, drawn as a low-poly diorama: lawn plots between pale sidewalks, flat-roofed modules with warm windows, farms of soil beds, and a misty forest on the horizon. The Kernel stands at the centre, and every new citizen\'s Seedling steps out of its door. Buildings go up (with scaffolding and a crane) as the society grows, Seedlings walk the streets and talk in speech bubbles, the camera drifts in on whoever is speaking, the sky and weather follow Avesta, the town decorates itself for holidays, voted festivals and season milestones, and projects the colony votes for are built as landmarks. Keep it at least a quarter of the screen, or use it as a card in a side column (340×250 or taller), where the caption sits below the town.', 960, 540, '&layout=card forces the column card · &quality=high (finer facets, glows, a pulsing Kernel, flags) or low (flat shapes, lighter for slower PCs) · &stats=1 adds the society stat panel · &camera=0 fixed wide shot · &focus=commons holds the camera on the Kernel (or any district) · &names=1 · &per=6 · &seconds=7 · preview: &hour=18 &holiday=christmas &weather=dust_winds'),
    ('ticker', 'News ticker', 'A TV-style lower third: every item has a coloured section tag (Event, Challenge, Vote, Weather, News, Society, Today, Market, Holiday, Project, At work, Report, Rumor, Season, Join) and the Avesta clock sits on the right.', 1920, 56, '&speed=80 · works at any height'),
    ('alerts', 'Live alerts', 'Animated pop-up for joins, level ups, achievements, trophies, finished queues, events, stream challenges, colony votes, seasons and society milestones. Transparent when idle.', 700, 220, '&test=1 shows demo alerts · &sound=1 plays a chime · &seconds=7 · &hide=queue,join'),
    ('challenge', 'Stream challenge bar', 'The live stream challenge as a goal bar: it slides in when a challenge starts ("Dust storm! Everyone repair the walls"), counts down with a shared progress bar and the top helper, celebrates the result, then slides away. Transparent when nothing is running. Challenges only happen while the stream is live.', 900, 110, '&test=1 shows a demo challenge'),
    ('leaders', 'Leaders', 'Top contributors, the most active citizens today and live event leaders.', 620, 330, ''),
    ('working', 'Working now', 'Everyone with a queue running, with live progress bars.', 460, 330, ''),
    ('join', 'How to play', 'Rotating chat commands so new viewers can join, and where to find the full game on Discord. Set DISCORD_INVITE_URL to show your invite.', 520, 220, '&seconds=7'),
    ('narrator', 'News', 'New Eridian News: a live report for every Seedling step, with what they gathered, made, practised, earned or restored.', 640, 300, '&lines=3 · &seconds=10'),
    ('society', 'Society', "Name, tier, Avesta day and today's condition.", 420, 220, ''),
    ('today', 'Today', 'The daily directive and community stats.', 420, 280, ''),
    ('event', 'Event', 'The live society event with its countdown.', 520, 180, ''),
    ('ops', 'Operations', 'Project, weekly story, market and pressure.', 520, 420, ''),
    ('activity', 'Activity', 'The five latest citizen actions.', 520, 360, ''),
    ('telemetry', 'Telemetry rail', 'Six society stats, population and tier in one row.', 1860, 150, ''),
    ('signal', 'Signal', 'A small live/offline indicator.', 320, 60, ''),
]


# Layout choices offered on the setup page (empty value = pick automatically from the size).
# Options offered as controls on the setup page. Each becomes a URL parameter only when it differs from the default.
#   kind: select (choices), number (min, max, step), check (on = value added when ticked, off = value added when unticked),
#   multi (choices joined with commas; nothing ticked = all). 'preview' options are for trying a look before going live.
_HUB_SLIDES = [('society', 'Society'), ('stats', 'Stats'), ('today', 'Today'), ('event', 'Live event'), ('challenge', 'Stream challenge'), ('vote', 'Colony vote'),
               ('season', 'Season'), ('projects', 'Project & story'), ('market', 'Market'),
               ('leaders', 'Leaders'), ('working', 'Working now'), ('seedlings', 'Seedlings'), ('news', 'News'), ('join', 'How to join')]
_ALERT_KINDS = [('join', 'New citizen'), ('level', 'Level up'), ('achievement', 'Achievement'), ('trophy', 'Trophy'), ('queue', 'Queue done'), ('event_start', 'Event start'),
                ('event_win', 'Event won'), ('event_fail', 'Event over'), ('event_cancel', 'Event cancelled'), ('challenge_start', 'Stream challenge'),
                ('challenge_win', 'Challenge won'), ('challenge_fail', 'Challenge over'), ('vote', 'Colony vote'), ('season', 'Season'), ('tier', 'Society tier'),
                ('project', 'Project'), ('story', 'Story'), ('directive', 'Directive')]
_HOLIDAY_PICK = [('', 'Live (automatic)'), ('newyear', 'New Year'), ('valentine', "Valentine's Day"), ('memorial', 'Memorial Day'), ('father', "Father's Day"),
                 ('independence', 'Independence Day'), ('labor', 'Labor Day'), ('halloween', 'Halloween'), ('thanksgiving', 'Thanksgiving'), ('christmas', 'Christmas')]
_WEATHER_PICK = [('', 'Live (automatic)'), ('clear_skies', 'Clear skies'), ('good_growing', 'Rain (good growing)'), ('spore_drift', 'Siro spores'), ('dust_winds', 'Dust winds'),
                 ('busy_spaceport', 'Busy spaceport'), ('water_watch', 'Overcast (water watch)'), ('quiet_cycle', 'Quiet (fireflies)'), ('sensor_noise', 'Sensor noise')]
_FOCUS_PICK = [('', 'The whole town'), ('commons', 'The Kernel'), ('residential_ring', 'Homes'), ('agricultural_district', 'Farms'), ('industrial_ward', 'Industry'),
               ('research_block', 'Research'), ('market_concourse', 'Market'), ('spaceport_quarter', 'Spaceport'), ('frontier_edge', 'Frontier'), ('park', 'Park')]
OPTIONS = {
    'hub': [dict(p='layout', label='Layout', kind='select', choices=[('', 'Automatic'), ('compact', 'Compact (small box)'), ('tall', 'Tall (column)'), ('wide', 'Wide (16:9)'), ('strip', 'Strip (one row)')]),
            dict(p='seconds', label='Seconds per slide', kind='number', default=12, min=4, max=120, step=1),
            dict(p='slides', label='Slides to show (none ticked = all)', kind='multi', choices=_HUB_SLIDES)],
    'map': [dict(p='layout', label='Layout', kind='select', choices=[('', 'Automatic'), ('card', 'Card (side column)'), ('wide', 'Wide (full map)')]),
            dict(p='quality', label='Quality', kind='select', choices=[('', 'Normal'), ('high', 'High (finer facets, glows, flags)'), ('low', 'Low (flat shapes, for slower PCs)')]),
            dict(p='camera', label='Camera close-ups', kind='check', default=True, off='0'),
            dict(p='names', label='Names under Seedlings', kind='check', default=False, on='1'),
            dict(p='stats', label='Society stats panel', kind='check', default=False, on='1'),
            dict(p='per', label='Seedlings per district', kind='number', default=0, min=1, max=10, step=1, blank='Auto'),
            dict(p='seconds', label='Seconds per caption', kind='number', default=7, min=3, max=60, step=1),
            dict(p='hour', label='Preview: time of day (0–24)', kind='number', default='', min=0, max=23.9, step=.5, blank='Live', preview=True),
            dict(p='weather', label='Preview: weather', kind='select', choices=_WEATHER_PICK, preview=True),
            dict(p='holiday', label='Preview: holiday', kind='select', choices=_HOLIDAY_PICK, preview=True),
            dict(p='focus', label='Hold the camera on', kind='select', choices=_FOCUS_PICK)],
    'challenge': [dict(p='test', label='Preview: demo challenge', kind='check', default=False, on='1', preview=True)],
    'ticker': [dict(p='speed', label='Scroll speed (px/s)', kind='number', default=80, min=20, max=400, step=10)],
    'alerts': [dict(p='seconds', label='Seconds on screen', kind='number', default=7, min=3, max=60, step=1),
               dict(p='sound', label='Chime sound', kind='check', default=False, on='1'),
               dict(p='hide', label='Hide these alerts', kind='multi', choices=_ALERT_KINDS),
               dict(p='test', label='Preview: demo alerts', kind='check', default=False, on='1', preview=True)],
    'narrator': [dict(p='lines', label='Older headlines', kind='number', default=3, min=0, max=6, step=1),
                 dict(p='seconds', label='Seconds per story', kind='number', default=10, min=4, max=60, step=1)],
    'join': [dict(p='seconds', label='Seconds per tip', kind='number', default=7, min=3, max=60, step=1)],
}


def _option_controls(key):
    from html import escape
    out = []
    for o in OPTIONS.get(key, []):
        attrs = f'data-p="{o["p"]}" data-kind="{o["kind"]}"' + (f' data-default="{o.get("default", "")}"' if o['kind'] == 'number' else '')
        cls = 'opt' + (' prev' if o.get('preview') else '')
        if o['kind'] == 'select':
            ctl = f'<select {attrs}>' + ''.join(f'<option value="{v}">{escape(t)}</option>' for v, t in o['choices']) + '</select>'
        elif o['kind'] == 'number':
            val = '' if o.get('default') in ('', 0) else o['default']
            ctl = f'<input type="number" {attrs} min="{o["min"]}" max="{o["max"]}" step="{o["step"]}" value="{val}" placeholder="{o.get("blank", "")}">'
        elif o['kind'] == 'check':
            ctl = f'<input type="checkbox" {attrs} data-on="{o.get("on", "")}" data-off="{o.get("off", "")}"{" checked" if o["default"] else ""}>'
            out.append(f'<label class="{cls} chk">{ctl}<span>{escape(o["label"])}</span></label>')
            continue
        else:
            ctl = f'<div class="multi" {attrs}>' + ''.join(f'<label><input type="checkbox" value="{v}"><span>{escape(t)}</span></label>' for v, t in o['choices']) + '</div>'
            out.append(f'<div class="{cls} wide"><span class="lbl">{escape(o["label"])}</span>{ctl}</div>')
            continue
        out.append(f'<label class="{cls}"><span class="lbl">{escape(o["label"])}</span>{ctl}</label>')
    return f'<div class="opts">{"".join(out)}</div>' if out else ''



def setup_page(channel):
    from html import escape
    from urllib.parse import quote
    shown, channel = escape(channel), quote(channel, safe='')
    cards = []
    for key, title, text, w, h, params in SOURCES:
        url = f'/obs/{key}?channel={channel}'
        preview = url + ('&test=1' if key == 'alerts' else '')
        scale = min(1, 560 / w)
        cards.append(f'''<article data-key="{key}" data-w="{w}" data-h="{h}" data-url="{url}" data-preview="{preview}"><div class="head"><h2>{title}</h2><span>Recommended {w} × {h}</span></div><p>{text}</p>
<div class="size"><label>Width <input type="number" min="100" max="3840" step="1" data-k="w" value="{w}"></label><span>×</span><label>Height <input type="number" min="40" max="2160" step="1" data-k="h" value="{h}"></label><button class="reset" type="button">Reset all</button></div>{_option_controls(key)}
<div class="url"><input readonly value=""><button>Copy</button></div><p class="params warnprev" hidden>⚠️ A preview option is set: clear it before using this URL live.</p>
<div class="preview"><iframe loading="lazy"></iframe></div></article>''')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>New Eridian · OBS setup</title>
{FONTS_LINK}<style>{THEME_CSS}{BASE_CSS}
html,body{{overflow:auto;height:auto;background:#0b0d1c}}body{{padding:28px 16px;max-width:1240px;margin:0 auto}}
header h1{{margin:0;font-family:var(--font-display);font-size:34px;color:var(--ivory)}}header p{{color:var(--muted);max-width:760px;line-height:1.5}}
main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,580px),1fr));gap:18px;margin-top:22px}}
article{{padding:16px;border-radius:14px;background:rgba(255,255,255,.035);border:1px solid rgba(147,154,255,.22);min-width:0}}
.head{{display:flex;justify-content:space-between;align-items:baseline;gap:10px}}
.rec{{margin-top:12px;padding:12px 16px;border-radius:12px;background:rgba(126,227,176,.1);border:1px solid rgba(126,227,176,.4);color:#dff7ea;line-height:1.5;max-width:900px}}
h2.sec{{margin:28px 0 0;font:700 20px var(--font-display);color:var(--ivory)}}h2{{margin:0;font-size:19px}}.head span{{color:var(--cyan);font-size:13px;font-weight:700}}
article p{{color:var(--muted);font-size:14px;line-height:1.45;margin:6px 0}}.params{{font-size:12px!important;color:#8f8bb3!important}}
.size{{display:flex;flex-wrap:wrap;align-items:flex-end;gap:8px;margin-top:10px}}.size label{{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--muted);font-weight:700}}
.size input,.size select{{width:96px;padding:7px 8px;border-radius:8px;border:1px solid rgba(255,255,255,.18);background:#060816;color:var(--text);font:600 14px var(--font-body)}}.size select{{width:auto}}
.size>span{{padding-bottom:8px;color:var(--muted)}}.size .reset{{padding:8px 12px;border-radius:8px;border:1px solid rgba(255,255,255,.18);background:transparent;color:var(--text);font-weight:700;cursor:pointer}}
.opts{{display:flex;flex-wrap:wrap;gap:8px 12px;margin-top:10px;padding:10px;border-radius:10px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08)}}
.opt{{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--muted);font-weight:700}}.opt.prev .lbl,.opt.prev.chk span{{color:#ffd27a}}
.opt select,.opt input[type=number]{{padding:6px 8px;border-radius:8px;border:1px solid rgba(255,255,255,.18);background:#060816;color:var(--text);font:600 13px var(--font-body);min-width:92px}}
.opt.chk{{flex-direction:row;align-items:center;gap:6px;align-self:flex-end;padding-bottom:6px;color:var(--text)}}.opt.wide{{flex-basis:100%}}
.multi{{display:flex;flex-wrap:wrap;gap:4px 10px}}.multi label{{display:flex;align-items:center;gap:4px;color:var(--text);font-weight:600}}
.warnprev{{color:#ffd27a!important}}
.url{{display:flex;gap:8px;margin-top:10px}}.url input{{flex:1;min-width:0;padding:8px 10px;border-radius:8px;border:1px solid rgba(255,255,255,.14);background:#060816;color:var(--green2);font:13px ui-monospace,monospace}}
.url button{{padding:8px 14px;border-radius:8px;border:0;background:var(--green);color:#07101d;font-weight:800;cursor:pointer}}
.preview{{margin-top:12px;border-radius:10px;overflow:hidden;background:repeating-conic-gradient(#1a1d33 0 25%,#141629 0 50%) 0 0/22px 22px;position:relative}}
.preview iframe{{border:0;transform-origin:0 0;position:absolute;left:0;top:0;pointer-events:none;background:transparent}}
</style></head><body><header><div class="eyebrow">OBS setup</div><h1>New Eridian stream overlay</h1>
<p>Add each panel you want as an OBS <b>Browser Source</b>: paste its URL, set its width and height, and leave "Custom CSS" empty. Panels have transparent backgrounds. Changes in the game appear within a few seconds.</p>
<div class="rec"><b>Any size you like.</b> Type the width and height of the space you have into a panel's boxes: the preview redraws at exactly that size and the layout adapts (the map and Hub also let you pick a layout). Then type the <b>same numbers</b> into the Browser Source's <b>Width</b> and <b>Height</b> in OBS (right-click the source → Properties), rather than dragging its corners, which only stretches the picture. Your sizes are remembered in this browser.</div>
<div class="rec"><b>Recommended: four sources carry everything.</b> Hub (rotating information), Avesta map, News ticker along the bottom, and Live alerts. The other panels below show one slide of the Hub each, if you prefer fixed panels. The full dashboard is still at <code>/overlay?channel={shown}</code>.</div></header>
<h2 class="sec">Recommended</h2><main>{''.join(cards[:4])}</main>
<h2 class="sec">Individual panels (optional)</h2><main>{''.join(cards[4:])}</main>
<script>
// Every source: type your own width and height (and layout); the preview redraws at that exact size and the URL follows. Saved in this browser.
const load=k=>{{try{{return JSON.parse(localStorage.getItem('ne-obs:'+k)||'{{}}')}}catch(e){{return {{}}}}}},save=(k,v)=>{{try{{localStorage.setItem('ne-obs:'+k,JSON.stringify(v))}}catch(e){{}}}};
for(const a of document.querySelectorAll('article[data-key]')){{
  const key=a.dataset.key,W=a.querySelector('[data-k=w]'),H=a.querySelector('[data-k=h]'),url=a.querySelector('.url input'),frame=a.querySelector('iframe'),box=a.querySelector('.preview'),tag=a.querySelector('.head span'),warn=a.querySelector('.warnprev');
  const opts=[...a.querySelectorAll('[data-p]')],saved=load(key);if(saved.w)W.value=saved.w;if(saved.h)H.value=saved.h;
  const read=el=>el.dataset.kind==='check'?el.checked:el.dataset.kind==='multi'?[...el.querySelectorAll('input:checked')].map(i=>i.value):el.value;
  const write=(el,v)=>{{if(el.dataset.kind==='check')el.checked=!!v;else if(el.dataset.kind==='multi')el.querySelectorAll('input').forEach(i=>i.checked=(v||[]).includes(i.value));else el.value=v}};
  const defaults=Object.fromEntries(opts.map(el=>[el.dataset.p,read(el)]));
  if(saved.opts)for(const el of opts)if(el.dataset.p in saved.opts)write(el,saved.opts[el.dataset.p]);else if(el.dataset.p==='layout'&&saved.layout!=null)write(el,saved.layout);
  // Only options that differ from the default go in the URL.
  const query=()=>{{let q='',prev=false;for(const el of opts){{const v=read(el),k=el.dataset.p;let part='';
      if(el.dataset.kind==='check'){{if(v&&el.dataset.on)part=el.dataset.on;if(!v&&el.dataset.off)part=el.dataset.off}}
      else if(el.dataset.kind==='multi'){{if(v.length)part=v.join(',')}}
      else if(el.dataset.kind==='number'){{if(v!==''&&String(+v)!==String(el.dataset.default))part=String(+v)}}
      else if(v)part=v;
      if(part){{q+='&'+k+'='+encodeURIComponent(part).replace(/%2C/g,',');if(el.closest('.prev'))prev=true}}}}return [q,prev]}};
  let timer=null;
  const draw=()=>{{const w=Math.max(100,Math.min(3840,+W.value||+a.dataset.w)),h=Math.max(40,Math.min(2160,+H.value||+a.dataset.h)),[q,prev]=query();
    url.value=location.origin+a.dataset.url+q;warn.hidden=!prev;
    const scale=Math.min(1,(box.clientWidth||560)/w);box.style.height=Math.round(h*scale)+2+'px';frame.style.width=w+'px';frame.style.height=h+'px';frame.style.transform=`scale(${{scale}})`;
    const src=a.dataset.preview+q.replace(/&test=1/,'');if(frame.dataset.src!==src+w+'x'+h){{frame.dataset.src=src+w+'x'+h;frame.src=src}}
    tag.textContent=(w==+a.dataset.w&&h==+a.dataset.h?'Recommended ':'Your size ')+w+' × '+h;
    save(key,{{w,h,opts:Object.fromEntries(opts.map(el=>[el.dataset.p,read(el)]))}})}};
  for(const i of [W,H,...opts])for(const ev of ['input','change'])i.addEventListener(ev,()=>{{clearTimeout(timer);timer=setTimeout(draw,350)}});
  a.querySelector('.reset').onclick=()=>{{W.value=a.dataset.w;H.value=a.dataset.h;for(const el of opts)write(el,defaults[el.dataset.p]);draw()}};
  draw()}}
addEventListener('resize',()=>document.querySelectorAll('article[data-key] [data-k=w]').forEach(i=>i.dispatchEvent(new Event('input'))));
for(const b of document.querySelectorAll('.url button'))b.onclick=()=>{{const i=b.previousElementSibling;i.select();navigator.clipboard&&navigator.clipboard.writeText(i.value);b.textContent='Copied';setTimeout(()=>b.textContent='Copy',1500)}};</script>
</body></html>'''
