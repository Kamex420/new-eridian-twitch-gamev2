"""Stream overlay extras: live highlight alerts, a news ticker, leaders, who is working, and a join card.

The game records notable moments in a small public feed (`stream_highlights_v1`):
a new citizen, a level up, an achievement, a finished queue, an event starting or
ending, a society tier or project milestone. `/api/v1/overlay` includes the feed
and a few summaries; the OBS panels below poll it like the existing panels do.

  /obs/alerts    animated pop-up for each new highlight (transparent when idle)
  /obs/ticker    a scrolling news crawl along the bottom of the stream
  /obs/leaders   top contributors and today's most active citizens
  /obs/working   citizens with queues running right now, with progress
  /obs/join      how to play from chat, rotating tips (and a Discord invite)
  /obs           setup page: every panel with its URL, size and a live preview

Only public information appears: names, actions and society numbers that the
activity feed already shows. Nothing from a citizen's inventory is exposed.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, Integer, String, DateTime, select, delete, func
from .db import Base

KEEP = 120                      # highlights kept per world
PANELS = {'alerts', 'ticker', 'leaders', 'working', 'join', 'map', 'narrator', 'hub'}
EMOJI = {'join': '🌱', 'level': '⬆️', 'achievement': '🏆', 'queue': '✅', 'event_start': '🚨', 'event_win': '🎉',
         'event_fail': '⌛', 'event_cancel': '🛑', 'tier': '🏛️', 'project': '🏗️', 'story': '📖', 'directive': '📋'}


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
                    'foods': [food[0] for food in seasonal.FESTIVAL_FOODS.get(f['name'], [])]}

    join = {'discord': os.getenv('DISCORD_INVITE_URL', '').strip(),
            'tips': [['!start', 'Create your citizen and join New Eridian'], ['!relax', '+25 Energy, +20 Comfort'],
                     ['!gather lumber', 'Collect materials'], ['!make campfire', 'Craft at the Workbench'],
                     ['!craftmax lumber', 'Queue up to 10 gathers and watch them run'], ['!status', 'Needs, queue and your next step'],
                     ['!find <word>', 'Search recipes, items and help'], ['!target <recipe>', 'Pin a goal and track it'],
                     ['!again', 'Repeat your last action'], ['!seed', 'Every command, by topic']]}
    from . import autonomy
    return {'highlights': highlights, 'leaders': leaders, 'working': working, 'festival': festival, 'join': join,
            **autonomy.overlay_data(m, db, source_ids)}


# ---------------------------------------------------------------- OBS pages

BASE_CSS = r"""
:root{color-scheme:dark;--text:#fffaf0;--muted:#aca9c9;--ivory:#fff8e8;--green:#7ee3b0;--green2:#b8f4d0;--violet:#bd91ff;--cyan:#70ddff;--amber:#ffd27a;--danger:#ff7484;--pink:#ff9ad5;
  --card:linear-gradient(145deg,rgba(8,13,39,.97),rgba(24,15,54,.95));--edge:rgba(147,154,255,.45);
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent;color:var(--text);-webkit-font-smoothing:antialiased}
.card{max-width:100%;overflow:hidden;min-width:0;background:radial-gradient(circle at 90% 0,rgba(125,72,220,.14),transparent 45%),var(--card);border:1px solid var(--edge);border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.4);padding:16px 18px}
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
"""

PAGES = {}

PAGES['alerts'] = (r"""
.stage{position:fixed;inset:0;display:flex;align-items:flex-start;justify-content:center;padding:14px}
.alert{position:relative;display:grid;grid-template-columns:74px minmax(0,1fr);gap:16px;align-items:center;width:min(620px,100%);padding:16px 22px 16px 16px;border-radius:18px;
  background:radial-gradient(circle at 12% 50%,var(--glow),transparent 55%),linear-gradient(145deg,rgba(8,13,39,.97),rgba(24,15,54,.96));border:1px solid var(--accent);
  box-shadow:0 14px 40px rgba(0,0,0,.5),0 0 34px var(--glow);opacity:0;transform:translateY(-26px) scale(.96)}
.alert.show{animation:enter .55s cubic-bezier(.2,1.4,.4,1) forwards}.alert.hide{animation:leave .45s ease-in forwards}
.alert .icon{width:74px;height:74px;display:grid;place-items:center;font-size:40px;border-radius:50%;background:rgba(255,255,255,.06);border:1px solid var(--accent);animation:pop 1.2s ease .2s}
.alert .kind{font-size:11px;font-weight:850;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
.alert h1{margin:3px 0 0;font-family:Georgia,"Times New Roman",serif;font-size:27px;line-height:1.1;color:var(--ivory);text-shadow:0 0 6px rgba(255,248,232,.25)}
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
  project:['#bd91ff','rgba(189,145,255,.30)','Project complete'],story:['#ff9ad5','rgba(255,154,213,.28)','Story'],directive:['#70ddff','rgba(112,221,255,.24)','Daily directive']};
const SHOW=Number(Q.get('seconds')||7)*1000, SKIP=new Set((Q.get('hide')||'').split(',').filter(Boolean));
const stage=document.getElementById('stage');let last=null,queue=[],busy=false,audio=null;
function chime(big){if(!Q.get('sound'))return;try{audio=audio||new AudioContext();const t=audio.currentTime;[0,.12,.24].slice(0,big?3:2).forEach((d,i)=>{const o=audio.createOscillator(),g=audio.createGain();o.type='sine';o.frequency.value=[660,880,1175][i];g.gain.setValueAtTime(.0001,t+d);g.gain.exponentialRampToValueAtTime(.12,t+d+.02);g.gain.exponentialRampToValueAtTime(.0001,t+d+.5);o.connect(g).connect(audio.destination);o.start(t+d);o.stop(t+d+.55)})}catch(e){}}
function show(h){busy=true;const [accent,glow,label]=COLORS[h.kind]||['#b8f4d0','rgba(184,244,208,.2)','Highlight'];
  const el=document.createElement('div');el.className='alert';el.style.setProperty('--accent',accent);el.style.setProperty('--glow',glow);
  el.innerHTML=`<div class="icon">${esc(h.emoji)}</div><div style="min-width:0"><div class="kind">${esc(label)}</div><h1>${esc(h.title)}</h1>${h.detail?`<p>${esc(h.detail)}</p>`:''}</div><div class="timer" style="animation-duration:${SHOW}ms"></div>`;
  stage.innerHTML='';stage.appendChild(el);requestAnimationFrame(()=>el.classList.add('show'));
  const big=['achievement','event_win','tier','project'].includes(h.kind);chime(big);
  if(big)for(let i=0;i<14;i++){const s=document.createElement('i');s.className='spark';const a=Math.random()*Math.PI*2,r=60+Math.random()*90;s.style.left='52px';s.style.top='52px';s.style.setProperty('--dx',Math.cos(a)*r+'px');s.style.setProperty('--dy',Math.sin(a)*r+'px');s.style.animationDelay=(Math.random()*.25)+'s';el.appendChild(s)}
  setTimeout(()=>{el.classList.add('hide');setTimeout(()=>{el.remove();busy=false;next()},480)},SHOW)}
function next(){if(!busy&&queue.length)show(queue.shift())}
const DEMO=[{kind:'join',emoji:'🌱',title:'Kamex arrived in New Eridian',detail:'Type !start in chat to join them.'},{kind:'level',emoji:'⬆️',title:'Kamex levelled up',detail:'Crafting aptitude Lv. 2 → Lv. 3'},
  {kind:'achievement',emoji:'🏆',title:'Astra earned an achievement',detail:'First Masterwork'},{kind:'event_start',emoji:'🚨',title:'Siro Surge has started!',detail:'Research and Engineering help. 10 minutes on the clock.'},
  {kind:'tier',emoji:'🏛️',title:'New Eridian is now a Settlement!',detail:'The whole society levelled up.'}];
if(Q.get('test')){let i=0;const loop=()=>{queue.push(DEMO[i++%DEMO.length]);next()};loop();setInterval(loop,SHOW+1200)}
else poll(d=>{const rows=(d.highlights||[]).slice().reverse();if(last===null){last=rows.length?rows[rows.length-1].id:0;return}
  for(const h of rows)if(h.id>last){last=h.id;if(!SKIP.has(h.kind))queue.push(h)}queue=queue.slice(-6);next()},3000);
</script>""")

PAGES['ticker'] = (r"""
.ticker{position:fixed;left:0;right:0;bottom:0;height:46px;display:flex;align-items:center;overflow:hidden;background:linear-gradient(90deg,rgba(8,13,39,.97),rgba(24,15,54,.95));border-top:1px solid var(--edge);border-bottom:1px solid var(--edge)}
.label{flex:none;height:100%;display:flex;align-items:center;gap:8px;padding:0 16px;font-size:13px;font-weight:900;letter-spacing:.14em;text-transform:uppercase;color:#08101f;background:linear-gradient(90deg,var(--green),var(--cyan));box-shadow:6px 0 16px rgba(0,0,0,.4);z-index:2}
.label i{width:8px;height:8px;border-radius:50%;background:#08101f;animation:blink 1.6s infinite}
.lane{position:relative;flex:1;height:100%;overflow:hidden;mask-image:linear-gradient(90deg,transparent,#000 3%,#000 97%,transparent)}
.track{position:absolute;top:0;left:0;height:100%;display:flex;align-items:center;white-space:nowrap;will-change:transform}
.item{display:inline-flex;align-items:center;gap:8px;padding:0 26px;font-size:17px;color:var(--text)}.item b{color:var(--green2)}.item em{font-style:normal;color:var(--amber)}
.item+.item:before{content:'✦';margin-right:26px;color:var(--violet);opacity:.7}
@keyframes blink{50%{opacity:.25}}
""", r"""
<div class="ticker"><div class="label"><i></i>New Eridian</div><div class="lane"><div class="track" id="track"></div></div></div>
<script>
const SPEED=Number(Q.get('speed')||80);let data=null,running=false;
function items(d){const out=[];const e=d.event;
  if(e)out.push(`🚨 <b>${esc(e.name)}</b> in progress · ${e.progress}/${e.goal} · ${Math.floor(e.seconds_remaining/60)}m left · <em>${esc(e.primary)}</em> work helps`);
  for(const h of (d.highlights||[]).slice(0,8))out.push(`${esc(h.emoji)} <b>${esc(h.title)}</b>${h.detail?' · '+esc(h.detail):''} <span class="muted">(${ago(h.at)})</span>`);
  const q=d.directive;if(q&&q.name)out.push(`📋 Today's directive: <b>${esc(q.name)}</b> · ${q.progress}/${q.goal}${q.complete?' ✅':''}`);
  const m=d.market;if(m&&m.primary)out.push(`💰 Market: <em>${esc(m.primary.name)}</em> is in demand at ${m.primary.price} SC`);
  const f=d.festival;if(f)out.push(`${esc(f.emoji)} <b>${esc(f.name)} festival</b> · ${f.days_left} days left · ${esc((f.foods||[]).join(', '))}`);
  const p=d.project;if(p&&p.name)out.push(`🏗️ Project <b>${esc(p.name)}</b> · ${Math.round(p.percent||0)}%`);
  const w=d.working||[];if(w.length)out.push(`⏱️ <b>${w.length}</b> citizen${w.length>1?'s':''} working: ${w.slice(0,3).map(x=>esc(x.name)+' ('+esc(x.task)+')').join(', ')}`);
  for(const n of (d.narration||[]).slice(0,3))out.push(`📰 <b>${esc(n.headline||'')}</b> · ${esc((n.text||'').split(' — ').slice(-1)[0])}`);
  if(d.rumor)out.push(`🗣️ ${esc(d.rumor)}`);
  out.push(`🌱 Type <b>!start</b> in chat to join New Eridian${d.join&&d.join.discord?' · Discord: <b>'+esc(d.join.discord.replace(/^https?:\/\//,''))+'</b>':''}`);
  return out}
function cycle(){if(!data){setTimeout(cycle,1000);return}running=true;const track=document.getElementById('track'),lane=track.parentElement;
  track.innerHTML=items(data).map(x=>`<span class="item">${x}</span>`).join('');const w=track.scrollWidth,L=lane.clientWidth;
  const dur=(w+L)/SPEED*1000;track.animate([{transform:`translateX(${L}px)`},{transform:`translateX(${-w}px)`}],{duration:dur,easing:'linear'}).onfinish=cycle}
poll(d=>{data=d;if(!running)cycle()},5000);
</script>""")

PAGES['leaders'] = (r"""
body{padding:4px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px}
h3{margin:0 0 8px;font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--cyan)}
.row{display:grid;grid-template-columns:30px minmax(0,1fr) auto;gap:8px;align-items:center;padding:7px 9px;border-radius:9px;background:rgba(7,9,13,.3);margin-bottom:6px;font-size:15px;animation:fade .5s ease both}
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
.job{min-width:0;padding:9px 11px;border-radius:10px;background:rgba(7,9,13,.32);animation:fade .5s ease both}
.top{display:flex;gap:8px;align-items:baseline;font-size:14px;min-width:0}.who{flex:none;font-weight:800}.task{color:var(--cyan);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.count{flex:none;margin-left:auto;font-variant-numeric:tabular-nums;color:var(--muted);font-size:13px}.paused .task{color:var(--amber)}.paused .bar i{background:var(--amber)}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
""", r"""
<section class="card"><div style="display:flex;justify-content:space-between"><div class="eyebrow">⏱️ Working right now</div><span class="muted" id="n" style="font-size:12px"></span></div><div class="list" id="list"></div></section>
<script>
let shape='';
poll(d=>{const w=d.working||[];document.getElementById('n').textContent=w.length?w.length+' queue'+(w.length>1?'s':''):'';
  const next=JSON.stringify(w.map(x=>[x.name,x.task,x.total,x.state]));const list=document.getElementById('list');
  if(next!==shape){shape=next;list.innerHTML=w.length?w.map((x,i)=>`<div class="job ${x.state==='paused'?'paused':''}" style="animation-delay:${i*50}ms"><div class="top"><span class="who">${esc(x.name)}</span><span class="task">${esc(x.task)}${x.state==='paused'?' · paused':''}</span><span class="count"></span></div><div class="bar"><i style="width:0"></i></div></div>`).join('')
    :'<div class="muted" style="font-size:14px">No queues running. Type <b style="color:var(--green2)">!craftmax lumber</b> to work while you watch.</div>'}
  // Progress updates in place, so bars glide instead of the list redrawing.
  list.querySelectorAll('.job').forEach((el,i)=>{const x=w[i];el.querySelector('.count').textContent=x.done+'/'+x.total;requestAnimationFrame(()=>el.querySelector('.bar i').style.width=(x.total?Math.round(x.done/x.total*100):0)+'%')})},3500);
</script>""")

PAGES['join'] = (r"""
body{padding:4px}.card{display:grid;grid-template-columns:minmax(0,1fr);gap:4px}
h1{margin:2px 0 0;font-family:Georgia,"Times New Roman",serif;font-size:26px;color:var(--ivory)}
.cmd{display:flex;align-items:center;gap:12px;margin-top:8px;min-height:48px;min-width:0}.cmd span{min-width:0}
.cmd code{flex:none;padding:8px 13px;border-radius:10px;background:rgba(126,227,176,.12);border:1px solid rgba(126,227,176,.45);color:var(--green2);font:800 20px ui-monospace,SFMono-Regular,Menlo,monospace}
.cmd span{font-size:16px;color:var(--muted)}.swap{animation:swap .6s ease both}.dots{display:flex;gap:5px;margin-top:10px}.dots i{width:6px;height:6px;border-radius:50%;background:rgba(255,255,255,.18)}.dots i.on{background:var(--green)}
.discord{margin-top:10px;padding-top:9px;border-top:1px solid rgba(255,255,255,.09);font-size:14px;color:var(--muted)}.discord b{color:#aab4ff}
@keyframes swap{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
""", r"""
<section class="card"><div class="eyebrow">🌱 Play from chat</div><h1>Join New Eridian</h1><div id="cmd" class="cmd"></div><div class="dots" id="dots"></div><div id="discord"></div></section>
<script>
let tips=[],i=0;const EVERY=Number(Q.get('seconds')||7)*1000;
function draw(){if(!tips.length)return;const t=tips[i%tips.length];const c=document.getElementById('cmd');c.innerHTML=`<code>${esc(t[0])}</code><span>${esc(t[1])}</span>`;c.classList.remove('swap');void c.offsetWidth;c.classList.add('swap');
  document.getElementById('dots').innerHTML=tips.map((_,k)=>`<i class="${k===i%tips.length?'on':''}"></i>`).join('');i++}
poll(d=>{const j=d.join||{};const first=!tips.length;tips=j.tips||[];document.getElementById('discord').innerHTML=j.discord?`<div class="discord">Buttons, crafting and more on Discord: <b>${esc(j.discord.replace(/^https?:\/\//,''))}</b></div>`:'';if(first)draw()},30000);
setInterval(draw,EVERY);
</script>""")


PAGES['map'] = (r"""
/* Built for broadcast: a 16:9 source (960×540 recommended). Text, tokens and bars are sized
   relative to the source, so the map stays readable when OBS scales it down into a corner. */
body{padding:0}.wrap{position:fixed;inset:0;overflow:hidden}
svg{position:absolute;inset:0;width:100%;height:100%;display:block}
.token{transition:transform 3s cubic-bezier(.45,.05,.3,1)}.token .dot{stroke:#0b0f24;stroke-width:3}
.token .ini{font:900 17px Inter,system-ui,sans-serif;fill:#08101f;text-anchor:middle;dominant-baseline:central}
.token .label{font:800 15px Inter,system-ui,sans-serif;fill:#fffaf0;text-anchor:middle;paint-order:stroke;stroke:#060816;stroke-width:4px}
.more text{font:900 15px Inter,system-ui,sans-serif;fill:#fff;text-anchor:middle;dominant-baseline:central}
.dlabel text{font:900 20px Inter,system-ui,sans-serif;letter-spacing:.04em;text-anchor:middle;dominant-baseline:central}
.dlabel .lvl{font:800 14px Inter,system-ui,sans-serif;fill:#fffaf0;opacity:.85}
.pop{animation:pop .9s cubic-bezier(.2,1.5,.4,1) both;transform-box:fill-box;transform-origin:center}
@keyframes pop{from{opacity:0;transform:scale(.2)}to{opacity:1;transform:none}}
.smoke{animation:smoke 4s ease-out infinite;transform-box:fill-box;transform-origin:center}
@keyframes smoke{0%{opacity:.55;transform:translate(0,0) scale(.6)}100%{opacity:0;transform:translate(8px,-26px) scale(1.8)}}
.spin{animation:spin 9s linear infinite;transform-box:fill-box;transform-origin:center}@keyframes spin{to{transform:rotate(360deg)}}
.ripple{animation:ripple 3s ease-out infinite;transform-box:fill-box;transform-origin:center}@keyframes ripple{0%{opacity:.8;transform:scale(.4)}100%{opacity:0;transform:scale(1.6)}}
.head{position:absolute;left:0;right:0;top:0;height:8.5vh;display:flex;align-items:center;gap:1.4vw;padding:0 1.6vw;
  background:linear-gradient(180deg,rgba(6,9,28,.92),rgba(6,9,28,.72));border-bottom:2px solid rgba(147,154,255,.45);font-size:clamp(12px,2.2vw,44px);z-index:3}
.head .name{font:700 1.15em Georgia,serif;color:var(--ivory);white-space:nowrap}.head .tier{padding:.12em .55em;border-radius:.5em;background:rgba(126,227,176,.18);border:1px solid rgba(126,227,176,.55);color:var(--green2);font-weight:900;font-size:.8em;white-space:nowrap}
.head .info{margin-left:auto;color:#e6e3fb;font-weight:700;font-size:.82em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cap{position:absolute;left:1.6vw;right:1.6vw;bottom:1.4vh;min-height:9vh;display:flex;align-items:center;gap:.8em;padding:.35em .9em;border-radius:.6em;
  background:rgba(250,248,240,.95);color:#171230;font-size:clamp(12px,2.3vw,46px);box-shadow:0 .3em 1em rgba(0,0,0,.4);z-index:3;transition:opacity .5s}
.cap .who{font-weight:900;white-space:nowrap}.cap .what{color:#5b3fd1;font-weight:800;white-space:nowrap}.cap .said{font-style:italic;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.cap.hide{opacity:0}
.particle{position:absolute;border-radius:50%;pointer-events:none;animation:drift linear infinite;z-index:2}
@keyframes drift{from{transform:translate(0,0)}to{transform:translate(var(--dx),var(--dy))}}
""", r"""
<div class="wrap" id="wrap">
<svg id="map" viewBox="0 0 960 540" preserveAspectRatio="xMidYMid slice">
 <defs>
  <radialGradient id="soil" cx="50%" cy="50%" r="75%"><stop offset="0" stop-color="#5a5238"/><stop offset=".55" stop-color="#433d2b"/><stop offset="1" stop-color="#2a2619"/></radialGradient>
  <filter id="veg" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".009 .012" numOctaves="4" seed="11"/>
   <feColorMatrix type="matrix" values="0 0 0 0 .33  0 0 0 0 .47  0 0 0 0 .27  0 0 0 2.4 -1.25"/></filter>
  <filter id="rock" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".022" numOctaves="3" seed="4"/>
   <feColorMatrix type="matrix" values="0 0 0 0 .22  0 0 0 0 .21  0 0 0 0 .2  0 0 0 2.6 -1.55"/></filter>
  <filter id="shadow" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="2" dy="3" stdDeviation="2" flood-color="#000" flood-opacity=".5"/></filter>
  <filter id="lamp" x="-200%" y="-200%" width="500%" height="500%"><feGaussianBlur stdDeviation="2.4"/></filter>
  <radialGradient id="crater"><stop offset="0" stop-color="#1f1c14" stop-opacity=".75"/><stop offset=".7" stop-color="#2d291d" stop-opacity=".35"/><stop offset="1" stop-color="#7a6f52" stop-opacity=".25"/></radialGradient>
  <radialGradient id="dome"><stop offset="0" stop-color="#ffffff"/><stop offset=".45" stop-color="#cfdbe8"/><stop offset="1" stop-color="#7d8ea3"/></radialGradient>
  <radialGradient id="glass"><stop offset="0" stop-color="#e8fff4" stop-opacity=".9"/><stop offset="1" stop-color="#6fd6a8" stop-opacity=".35"/></radialGradient>
  <radialGradient id="vignette" cx="50%" cy="50%" r="72%"><stop offset=".62" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".55"/></radialGradient>
  <pattern id="crops" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(20)"><rect width="7" height="7" fill="#6f8f3a"/><rect width="3.5" height="7" fill="#86a948"/></pattern>
  <pattern id="wheat" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(-25)"><rect width="7" height="7" fill="#b8963f"/><rect width="3.5" height="7" fill="#cfae52"/></pattern>
 </defs>
 <g id="ground"><rect width="960" height="540" fill="url(#soil)"/><rect width="960" height="540" filter="url(#veg)"/><rect width="960" height="540" filter="url(#rock)"/></g>
 <g id="nature"></g><g id="wall"></g><g id="roads"></g><g id="districts"></g>
 <rect width="960" height="540" fill="url(#vignette)" style="pointer-events:none"/>
 <rect id="tint" width="960" height="540" fill="transparent" style="pointer-events:none;transition:fill 4s"/>
 <g id="lights" style="pointer-events:none"></g><g id="labels"></g><g id="tokens"></g>
</svg>
<div class="head"><span class="name">🗺️ New Eridian</span><span class="tier" id="tier">—</span><span class="info" id="info">Connecting to Avesta…</span></div>
<div class="cap hide" id="cap"></div>
</div>
<script>
const NS='http://www.w3.org/2000/svg',el=(t,a,parent)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(parent)parent.appendChild(e);return e};
function rng(seed){let h=2166136261;for(const c of String(seed))h=Math.imul(h^c.charCodeAt(0),16777619);return()=>{h+=0x6D2B79F5;let t=h;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return((t^t>>>14)>>>0)/4294967296}}
const CX=480,CY=268,K=1.2;   // K: district art scale
const ORDER=['spaceport_quarter','market_concourse','industrial_ward','frontier_edge','residential_ring','agricultural_district','research_block'];
const POS={commons:[CX,CY]};ORDER.forEach((k,i)=>{const a=(-90+i*360/ORDER.length)*Math.PI/180;POS[k]=[CX+338*Math.cos(a),CY+150*Math.sin(a)]});
// Short names read at stream size; the full names are in the news and /seedling.
const LOOK={commons:['⛲','Commons','#b8f4d0'],residential_ring:['🏠','Homes','#ffd27a'],agricultural_district:['🌾','Farms','#9be37e'],industrial_ward:['🏭','Industry','#ff9a76'],
  research_block:['🔬','Research','#70ddff'],market_concourse:['🪙','Market','#ffd27a'],spaceport_quarter:['🚀','Spaceport','#bd91ff'],frontier_edge:['🧭','Frontier','#ff9ad5']};
const MOOD={Inspired:'#ffd27a',Content:'#7ee3b0',Tired:'#9aa3c7',Hungry:'#ffb36b',Lonely:'#8fb3ff',Uneasy:'#d6a4ff',Stressed:'#ff9a76',Miserable:'#ff7484'};
const SHOW_NAMES=Q.get('names')!=='0',PER_PLACE=Number(Q.get('per')||5);
if(Q.get('bg')==='0')document.getElementById('ground').style.display='none';

(function nature(){const g=document.getElementById('nature'),r=rng('avesta');
  const river='M-20 520 C 150 500, 250 545, 380 535 S 600 505, 700 532 S 880 548, 980 515';
  el('path',{d:river,fill:'none',stroke:'#2f5f73','stroke-width':18,'stroke-linecap':'round'},g);el('path',{d:river,fill:'none',stroke:'#6fb3c9','stroke-width':5,opacity:.45},g);
  for(let i=0;i<8;i++){const x=r()*960,y=r()*540;if(Math.hypot((x-CX)/1.9,y-CY)<190)continue;const s=16+r()*34;el('ellipse',{cx:x,cy:y,rx:s,ry:s*.8,fill:'url(#crater)'},g)}
  for(let i=0;i<50;i++){const x=r()*960,y=r()*540;if(Math.hypot((x-CX)/1.9,y-CY)<180)continue;el('circle',{cx:x,cy:y,r:2+r()*4,fill:r()<.5?'#6e6552':'#4c4638',filter:'url(#shadow)'},g)}
  for(let i=0;i<80;i++){const x=r()*960,y=r()*540;if(Math.hypot((x-CX)/1.9,y-CY)<170)continue;el('circle',{cx:x,cy:y,r:3+r()*4,fill:r()<.5?'#4f7a3a':'#3f6a32',opacity:.85},g)}})();

function house(g,x,y,r,night){const w=10+r()*8,h=8+r()*6,b=el('g',{filter:'url(#shadow)'},g);el('rect',{x:x-w/2,y:y-h/2,width:w,height:h,rx:1.5,fill:'#b9b3a3'},b);
  el('rect',{x:x-w/2,y:y-h/2,width:w,height:h*.45,rx:1.5,fill:'#8e8778'},b);el('rect',{class:'win',x:x-1.5,y:y+1,width:3,height:2,fill:'#ffd98a',opacity:night?1:0},b);return b}
const BUILD={
 residential_ring(g,x,y,r,i,night){if(i%3===0){const b=el('g',{filter:'url(#shadow)'},g);el('circle',{cx:x,cy:y,r:8+r()*4,fill:'url(#dome)'},b);el('circle',{class:'win',cx:x+2,cy:y+3,r:1.6,fill:'#ffd98a',opacity:night?1:0},b);return b}return house(g,x,y,r,night)},
 agricultural_district(g,x,y,r,i,night){if(i%4===3){const b=el('g',{filter:'url(#shadow)'},g);el('ellipse',{cx:x,cy:y,rx:12,ry:8,fill:'url(#glass)',stroke:'#d8fff0','stroke-width':1},b);return b}
   const w=20+r()*16,h=12+r()*9,b=el('g',{},g);el('rect',{x:x-w/2,y:y-h/2,width:w,height:h,fill:r()<.5?'url(#crops)':'url(#wheat)',stroke:'#3d4a22','stroke-width':1,transform:`rotate(${(r()-.5)*30} ${x} ${y})`},b);return b},
 industrial_ward(g,x,y,r,i,night){const w=16+r()*14,h=12+r()*8,b=el('g',{filter:'url(#shadow)'},g);el('rect',{x:x-w/2,y:y-h/2,width:w,height:h,fill:'#6f747c'},b);
   el('rect',{x:x-w/2,y:y-h/2,width:w,height:3,fill:'#8c929b'},b);el('rect',{x:x+w/2-5,y:y-h/2-7,width:3.5,height:8,fill:'#555a61'},b);
   el('circle',{class:'smoke',cx:x+w/2-3,cy:y-h/2-9,r:3,fill:'#c9c4bb',style:`animation-delay:-${(r()*4).toFixed(1)}s`},b);
   el('rect',{class:'win',x:x-w/2+3,y:y+1,width:w-6,height:1.8,fill:'#ffc86b',opacity:night?.9:0},b);return b},
 research_block(g,x,y,r,i,night){if(i%4===0){const b=el('g',{filter:'url(#shadow)'},g);el('circle',{cx:x,cy:y,r:7,fill:'#dfe7ee'},b);
   const s=el('g',{class:'spin'},b);el('path',{d:`M${x-9} ${y} A9 9 0 0 1 ${x+9} ${y} Z`,fill:'#f4f8fb',stroke:'#9fb3c4'},s);el('line',{x1:x,y1:y,x2:x,y2:y-10,stroke:'#9fb3c4','stroke-width':1.4},s);return b}
   const b=house(g,x,y,r,night);b.querySelector('rect').setAttribute('fill','#c8d6e3');return b},
 market_concourse(g,x,y,r,i,night){const b=el('g',{filter:'url(#shadow)'},g),c=['#e0564f','#f2b441','#4fa3e0','#7ec36b','#b86fd6'][Math.floor(r()*5)];
   el('rect',{x:x-6,y:y-5,width:12,height:10,fill:'#d9cfb8'},b);el('path',{d:`M${x-8} ${y-5} L${x+8} ${y-5} L${x+6} ${y-9} L${x-6} ${y-9} Z`,fill:c},b);
   el('circle',{class:'win',cx:x,cy:y+2,r:1.4,fill:'#ffd98a',opacity:night?1:0},b);return b},
 spaceport_quarter(g,x,y,r,i,night){if(i%3===0){const b=el('g',{},g);el('circle',{cx:x,cy:y,r:14,fill:'#5d6068',stroke:'#e3e6ea','stroke-width':1.5},b);
   el('text',{x:x,y:y+4,'text-anchor':'middle','font-size':11,'font-weight':900,fill:'#f6d365'},b).textContent='H';
   el('circle',{class:'win',cx:x,cy:y-14,r:1.8,fill:'#ff5a5a',opacity:night?1:.4},b);return b}return house(g,x,y,r,night)},
 frontier_edge(g,x,y,r,i,night){const b=el('g',{filter:'url(#shadow)'},g);if(i%3===0){el('path',{d:`M${x-8} ${y+7} L${x} ${y-11} L${x+8} ${y+7}`,fill:'none',stroke:'#8b6e4e','stroke-width':2.4},b);
   el('circle',{cx:x,cy:y-11,r:2.4,fill:'#c0a27a'},b);return b}if(i%3===1){for(let k=0;k<4;k++)el('circle',{cx:x+(r()-.5)*12,cy:y+(r()-.5)*8,r:2.5+r()*3,fill:'#7d7465'},b);return b}
   el('path',{d:`M${x-7} ${y+5} L${x} ${y-6} L${x+7} ${y+5} Z`,fill:'#d7c7a3'},b);el('circle',{class:'win',cx:x,cy:y+2,r:1.3,fill:'#ffb25b',opacity:night?1:0},b);return b},
 commons(g,x,y,r,i,night){const b=el('g',{},g);el('circle',{cx:x,cy:y,r:5+r()*3,fill:r()<.5?'#5b8a45':'#4e7d3b',filter:'url(#shadow)'},b);return b},
};
// Buildings are drawn at base size around the district centre, then the whole district is scaled by K.
function place(k,i,radius,r){const [cx,cy]=POS[k];if(k==='commons'){const a=i*.9,rr=radius*.8;return [cx+rr*Math.cos(a),cy+rr*Math.sin(a)*.8]}
  const a=i*2.39996+r()*.3,rr=8+Math.sqrt(i+1)*radius/5.2;return [cx+rr*Math.cos(a),cy+rr*Math.sin(a)*.7]}
const drawn={};let night=false;
function districts(d){const g=document.getElementById('districts'),roads=document.getElementById('roads'),wall=document.getElementById('wall'),labels=document.getElementById('labels'),tier=d.tier_index||0;
  wall.innerHTML='';el('ellipse',{cx:CX,cy:CY,rx:250+tier*28,ry:130+tier*14,fill:'rgba(120,112,90,.10)',stroke:'#9b8f73','stroke-width':3+tier,'stroke-dasharray':tier?'':'14 10',opacity:.75},wall);
  roads.innerHTML='';for(const k of ORDER){const [x,y]=POS[k],on=(d.districts||{})[k]&&d.districts[k].unlocked,path=`M${CX} ${CY} Q ${(CX+x)/2+(y-CY)*.16} ${(CY+y)/2-(x-CX)*.1} ${x} ${y}`;
    el('path',{d:path,stroke:on?'#8a8472':'#6d6653','stroke-width':on?9+tier*2:4,fill:'none','stroke-linecap':'round','stroke-dasharray':on?'':'3 9',opacity:on?.95:.7},roads);
    if(on)el('path',{d:path,stroke:'#d8d0b8','stroke-width':1.4,fill:'none','stroke-dasharray':'8 10',opacity:.6},roads)}
  labels.innerHTML='';
  for(const k in POS){const info=(d.districts||{})[k]||{unlocked:k==='commons',level:1,unlocks_at:''},[x,y]=POS[k],[icon,short,color]=LOOK[k];
    const level=info.unlocked?info.level:0,radius=k==='commons'?44+tier*3:34+Math.min(level,12)*3.2;
    let dg=drawn[k];if(!dg||dg.unlocked!==info.unlocked){if(dg)dg.g.remove();
      dg=drawn[k]={g:el('g',{transform:`translate(${x} ${y}) scale(${K}) translate(${-x} ${-y})`},g),count:0,unlocked:info.unlocked};
      dg.base=el('ellipse',{cx:x,cy:y,rx:radius,ry:radius*.7,fill:info.unlocked?(k==='commons'?'#8d8a7c':'rgba(170,160,135,.35)'):'rgba(20,18,12,.25)',stroke:info.unlocked?'rgba(255,255,255,.14)':color,'stroke-width':info.unlocked?1:2.5,'stroke-dasharray':info.unlocked?'':'6 6'},dg.g);
      if(k==='commons'){el('circle',{cx:x,cy:y,r:13,fill:'#3f7fa0',stroke:'#cfe9f2','stroke-width':2},dg.g);el('circle',{class:'ripple',cx:x,cy:y,r:11,fill:'none',stroke:'#dff6ff','stroke-width':2},dg.g)}
      if(!info.unlocked)for(let s=0;s<5;s++){const a=s*1.25;el('path',{d:`M${x+radius*.55*Math.cos(a)} ${y+radius*.4*Math.sin(a)} l4 -10 l4 10 z`,fill:'#f28b3c'},dg.g)}}
    dg.base.setAttribute('rx',radius);dg.base.setAttribute('ry',radius*.7);
    const want=info.unlocked?(k==='commons'?6+tier*3:2+Math.round(level*1.8)):0;
    for(let i=dg.count;i<want;i++){const r=rng(k+':'+i),[bx,by]=place(k,i,radius,r),b=BUILD[k](dg.g,bx,by,r,i,night);if(drawn.ready)b.classList.add('pop')}
    dg.count=Math.max(dg.count,want);
    // Big, short label on a pill at the district's lower edge.
    const text=`${icon} ${short.toUpperCase()}`,sub=info.unlocked?(k==='commons'?'':`LV ${level}`):`AT ${String(info.unlocks_at||'').toUpperCase()}`;
    const ly=y+Math.max(radius*.7*K,36)+8,lab=el('g',{class:'dlabel'},labels),box=el('rect',{y:ly-15,height:30,rx:15,fill:'rgba(8,13,39,.9)',stroke:color,'stroke-width':2},lab);
    const t=el('text',{x:0,y:ly+1,fill:color},lab);t.textContent=text;const s=sub?el('text',{class:'lvl',x:0,y:ly+1},lab):null;if(s)s.textContent=sub;
    // Measure the real text so the pill always fits it.
    const tw=t.getComputedTextLength(),sw=s?s.getComputedTextLength()+10:0,w=tw+sw+28;
    box.setAttribute('x',x-w/2);box.setAttribute('width',w);t.setAttribute('x',x-w/2+14+tw/2);if(s)s.setAttribute('x',x+w/2-14-sw/2+5)}
  drawn.ready=true;document.querySelectorAll('.win').forEach(w=>w.setAttribute('opacity',night?(w.getAttribute('fill')==='#ff5a5a'?1:.95):(w.getAttribute('fill')==='#ff5a5a'?.4:0)));
  const lights=document.getElementById('lights');lights.innerHTML='';
  if(night)document.querySelectorAll('#districts .win').forEach(w=>{const b=w.getBBox(),m=w.parentNode.parentNode.transform.baseVal.consolidate();
    let x=b.x+b.width/2,y=b.y+b.height/2;if(m){const p=m.matrix;[x,y]=[p.a*x+p.c*y+p.e,p.b*x+p.d*y+p.f]}const c=w.getAttribute('fill');
    el('circle',{cx:x,cy:y,r:5,fill:c,opacity:.55,filter:'url(#lamp)'},lights);el('circle',{cx:x,cy:y,r:1.6,fill:c},lights)})}
const tokens=document.getElementById('tokens'),live={};let latest=[];
function slot(k,i,n){const [x,y]=POS[k]||POS.commons,cols=Math.min(3,n),rows=Math.ceil(n/cols),rr=Math.floor(i/cols),c=i%cols,inRow=Math.min(cols,n-rr*cols);
  return [x+(c-(inRow-1)/2)*66,y-16+(rr-(rows-1)/2)*46]}
function seedlings(list){const groups={};for(const s of list)(groups[s.place]=groups[s.place]||[]).push(s);const seen=new Set();
  document.querySelectorAll('.more').forEach(e=>e.remove());
  for(const k in groups){const all=groups[k].sort((a,b)=>a.id<b.id?-1:1),shown=all.slice(0,PER_PLACE),extra=all.length-shown.length;
    shown.forEach((s,i)=>{seen.add(s.id);const [x,y]=slot(k,i,shown.length);let g=live[s.id];
      if(!g){g=el('g',{class:'token'},tokens);el('ellipse',{cx:0,cy:17,rx:13,ry:4.5,fill:'rgba(0,0,0,.5)'},g);el('circle',{class:'dot',r:16},g);el('text',{class:'ini'},g);
        el('text',{class:'label',y:33},g);el('text',{class:'act',x:15,y:-12,'font-size':17},g);live[s.id]=g;g.style.transform=`translate(${x}px,${y}px)`}
      g.querySelector('.dot').setAttribute('fill',MOOD[s.mood]||'#b8f4d0');g.querySelector('.ini').textContent=(s.name||'?').slice(0,1).toUpperCase();
      g.querySelector('.label').textContent=SHOW_NAMES?(s.name.length>8?s.name.slice(0,7)+'…':s.name):'';g.querySelector('.act').textContent=s.emoji||'';
      requestAnimationFrame(()=>g.style.transform=`translate(${x}px,${y}px)`)});
    if(extra>0){const [x,y]=POS[k],m=el('g',{class:'more'},tokens);el('rect',{x:x+96,y:y-40,width:46,height:28,rx:14,fill:'#6b3fd1',stroke:'#fff','stroke-width':2},m);el('text',{x:x+119,y:y-26},m).textContent='+'+extra}}
  for(const id in live)if(!seen.has(id)){live[id].remove();delete live[id]}}
const TINT={Morning:'rgba(255,170,110,.08)',Day:'rgba(0,0,0,0)',Evening:'rgba(255,110,70,.14)',Night:'rgba(6,12,52,.5)'};
let lastWeather='';
function weather(key){document.querySelectorAll('.particle').forEach(p=>p.remove());const look={spore_drift:['rgba(126,227,176,.6)',6,'80px','-40px'],dust_winds:['rgba(214,180,130,.5)',4,'260px','20px']}[key];if(!look)return;
  for(let i=0;i<26;i++){const p=document.createElement('i');p.className='particle';p.style.cssText=`left:${Math.random()*100}%;top:${Math.random()*100}%;width:${look[1]}px;height:${look[1]}px;background:${look[0]};--dx:${look[2]};--dy:${look[3]};animation-duration:${6+Math.random()*8}s;animation-delay:-${Math.random()*8}s`;document.getElementById('wrap').appendChild(p)}}
// One large caption at the bottom instead of small bubbles: who, where, what, and what they think.
let capIndex=0;
function caption(){const cap=document.getElementById('cap'),pool=latest.filter(s=>s.activity);if(!pool.length){cap.classList.add('hide');return}
  const s=pool[capIndex++%pool.length],place=(LOOK[s.place]||LOOK.commons);
  cap.classList.add('hide');setTimeout(()=>{cap.innerHTML=`<span>${esc(s.mood_emoji||'🙂')}</span><span class="who">${esc(s.name)}</span><span class="what">${esc(place[0])} ${esc(s.activity)}</span>${s.thought?`<span class="said">“${esc(s.thought)}”</span>`:''}`;cap.classList.remove('hide')},450)}
setInterval(caption,Number(Q.get('seconds')||7)*1000);
poll(d=>{night=d.phase==='Night'||d.phase==='Evening';districts(d);const first=!latest.length;latest=d.seedlings||[];seedlings(latest);if(first)caption();
  document.getElementById('tier').textContent=`${d.tier_name||d.tier||'Outpost'} · ${d.population||0} citizens`;
  const busy=latest.filter(s=>/^Working|^Queue|^Gathering/.test(s.activity)).length;
  document.getElementById('info').textContent=`${d.phase_emoji||''} Day ${d.day} · ${d.phase} · ${latest.length} out · ${busy} working`;
  document.getElementById('tint').setAttribute('fill',TINT[d.phase]||'transparent');
  const c=(d.condition||'').toLowerCase(),w=c.includes('siro')?'spore_drift':c.includes('dust')?'dust_winds':'';if(w!==lastWeather){lastWeather=w;weather(w)}},4000);
</script>""")

PAGES['narrator'] = (r"""
body{padding:4px}.news{overflow:hidden;border-radius:14px;border:1px solid var(--edge);background:linear-gradient(145deg,rgba(8,13,39,.97),rgba(24,15,54,.96));box-shadow:0 10px 30px rgba(0,0,0,.4)}
.bar{display:flex;align-items:center;gap:10px;padding:8px 14px;background:linear-gradient(90deg,#b3123a,#e0294f 55%,#7b1f6e);color:#fff}
.bar .live{padding:2px 8px;border-radius:5px;background:#fff;color:#b3123a;font:900 11px Inter,system-ui,sans-serif;letter-spacing:.12em}
.bar .net{font:900 13px Inter,system-ui,sans-serif;letter-spacing:.16em}.bar .clock{margin-left:auto;font:700 12px Inter,system-ui,sans-serif;opacity:.9}
.story{padding:12px 16px 12px}.desk{display:inline-block;padding:2px 8px;border-radius:5px;background:rgba(112,221,255,.14);border:1px solid rgba(112,221,255,.4);color:var(--cyan);font:900 10.5px Inter,system-ui,sans-serif;letter-spacing:.14em}
.head{margin-top:7px;font:800 22px/1.2 Inter,system-ui,sans-serif;color:#fff}.body{margin-top:6px;font-size:15px;line-height:1.45;color:#d9d6ef;min-height:44px}
.body .cursor{display:inline-block;width:2px;height:1em;background:var(--green2);margin-left:2px;vertical-align:-2px;animation:blink 1s infinite}
.crawl{display:flex;flex-direction:column;gap:5px;padding:9px 16px 11px;border-top:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.18)}
.crawl div{font-size:13px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.crawl b{color:#fff;font-weight:700}
.swap{animation:swap .5s ease both}@keyframes swap{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}@keyframes blink{50%{opacity:0}}
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
.top .title{font-weight:900;letter-spacing:.12em;text-transform:uppercase;color:var(--green2);font-size:.9em;white-space:nowrap}
.dots{margin-left:auto;display:flex;gap:.35em}.dots i{width:.5em;height:.5em;border-radius:50%;background:rgba(255,255,255,.2)}.dots i.on{background:var(--green)}.dots i.live{background:var(--danger)}
.body{flex:1;padding:.5em .9em;min-height:0;display:flex;flex-direction:column;justify-content:center;gap:.45em}.slide{animation:in .55s ease both}
@keyframes in{from{opacity:0;transform:translateX(3%)}to{opacity:1;transform:none}}
.timer{height:.28em;background:rgba(255,255,255,.07)}.timer i{display:block;height:100%;background:linear-gradient(90deg,var(--green),var(--violet));transform-origin:left}
h2{margin:0;font:700 1.45em/1.1 Georgia,serif;color:var(--ivory)}.sub{color:var(--muted);font-size:.78em;line-height:1.3}
.big{font-size:1.1em;font-weight:800}.row{display:flex;align-items:center;gap:.5em;min-width:0}.row .grow{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar{height:.5em;border-radius:99px;background:rgba(255,255,255,.1);overflow:hidden}.bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--green),var(--violet))}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.35em .7em}.stat{padding:.3em .45em;border-radius:.4em;background:rgba(0,0,0,.22)}.stat b{display:block;font-size:1.05em}.stat small{color:var(--muted);font-size:.66em;text-transform:uppercase;letter-spacing:.06em}
.list{display:flex;flex-direction:column;gap:.3em}.list .row{padding:.22em .45em;border-radius:.4em;background:rgba(0,0,0,.2);font-size:.9em}
.num{color:var(--green2);font-weight:900;font-variant-numeric:tabular-nums;white-space:nowrap}.hot{color:var(--amber)}.red{color:#ff9aa6}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:.6em}.cols h3{margin:0 0 .2em;font-size:.7em;letter-spacing:.1em;text-transform:uppercase;color:var(--cyan)}
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
   ${d.join.discord?`<div class="sub">Buttons, crafting and more on Discord: <b>${esc(d.join.discord.replace(/^https?:\/\//,''))}</b></div>`:''}`}],
];
const ACTIVE=SLIDES.filter(s=>!PICK.length||PICK.includes(s[0]));
let data=null,index=-1,eventTurn=false;
function next(){if(!data)return;let tries=0,slide;
  // A live event takes every other slide until it ends.
  if(data.event&&!eventTurn&&ACTIVE.some(s=>s[0]==='event')){slide=ACTIVE.find(s=>s[0]==='event');eventTurn=true}
  else{eventTurn=false;do{index=(index+1)%ACTIVE.length;slide=ACTIVE[index];tries++}while((slide[0]==='event'&&data.event)||(!slide[2](data)&&tries<=ACTIVE.length))}
  document.getElementById('title').textContent=slide[1];
  const body=document.getElementById('body');body.innerHTML=`<div class="slide" style="display:flex;flex-direction:column;gap:.45em">${slide[3](data)}</div>`;
  const shown=ACTIVE.filter(s=>s[2](data));document.getElementById('dots').innerHTML=shown.map(s=>`<i class="${s===slide?'on':''}${s[0]==='event'?' live':''}"></i>`).join('');
  const t=document.getElementById('timer');t.animate([{transform:'scaleX(0)'},{transform:'scaleX(1)'}],{duration:EVERY,easing:'linear'})}
poll(d=>{const first=!data;data=d;if(first){next();setInterval(next,EVERY)}},4000);
</script>""")

def page(panel, channel):
    css, body = PAGES[panel]
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>New Eridian · {panel}</title><style>{BASE_CSS}{css}</style></head><body class="panel-{panel}">'
            f'<script>const CHANNEL={json.dumps(channel)};{SHARED_JS}</script>{body}</body></html>')


# Every OBS source, with a sensible Browser Source size.
SOURCES = [
    ('hub', 'Hub (rotating)', 'Everything in one panel: society, stats, today, the live event, project and story, market, leaders, working now, Seedlings, news and how to join. Rotates every 12 seconds; a live event shows every other slide.', 640, 360, '&seconds=12 · &slides=society,event,news (pick and order the slides)'),
    ('map', 'Avesta map', 'New Eridian on Avesta, growing with the society, built to read at stream size: big labels, big Seedling tokens and a caption bar. Keep it at least a quarter of the screen.', 960, 540, '&names=0 hides names · &per=5 tokens per place · &seconds=7 caption · &bg=0'),
    ('ticker', 'News ticker', 'A scrolling crawl: highlights, the event, directive, market, festival and how to join.', 1920, 46, '&speed=80'),
    ('alerts', 'Live alerts', 'Animated pop-up for joins, level ups, achievements, events and milestones. Transparent when idle.', 700, 220, '&test=1 shows demo alerts · &sound=1 plays a chime · &seconds=7 · &hide=queue,join'),
    ('leaders', 'Leaders', 'Top contributors, the most active citizens today and live event leaders.', 620, 330, ''),
    ('working', 'Working now', 'Everyone with a queue running, with live progress bars.', 460, 330, ''),
    ('join', 'How to play', 'Rotating chat commands so new viewers can join. Set DISCORD_INVITE_URL to show your invite.', 520, 220, '&seconds=7'),
    ('narrator', 'News', 'New Eridian News: a live report for every Seedling step, with what they gathered, earned or restored.', 640, 300, '&lines=3 · &seconds=10'),
    ('society', 'Society', "Name, tier, Avesta day and today's condition.", 420, 220, ''),
    ('today', 'Today', 'The daily directive and community stats.', 420, 280, ''),
    ('event', 'Event', 'The live society event with its countdown.', 520, 180, ''),
    ('ops', 'Operations', 'Project, weekly story, market and pressure.', 520, 420, ''),
    ('activity', 'Activity', 'The five latest citizen actions.', 520, 360, ''),
    ('telemetry', 'Telemetry rail', 'Six society stats, population and tier in one row.', 1860, 150, ''),
    ('signal', 'Signal', 'A small live/offline indicator.', 320, 60, ''),
]


def setup_page(channel):
    from html import escape
    from urllib.parse import quote
    shown, channel = escape(channel), quote(channel, safe='')
    cards = []
    for key, title, text, w, h, params in SOURCES:
        url = f'/obs/{key}?channel={channel}'
        preview = url + ('&test=1' if key == 'alerts' else '')
        scale = min(1, 560 / w)
        cards.append(f'''<article><div class="head"><h2>{title}</h2><span>{w} × {h}</span></div><p>{text}</p>
<div class="url"><input readonly value="" data-path="{url}"><button>Copy</button></div>{f'<p class="params">Options: {params}</p>' if params else ''}
<div class="preview" style="height:{int(h * scale) + 2}px"><iframe src="{preview}" style="width:{w}px;height:{h}px;transform:scale({scale})"></iframe></div></article>''')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>New Eridian · OBS setup</title>
<style>{BASE_CSS}
html,body{{overflow:auto;height:auto;background:#0b0d1c}}body{{padding:28px 16px;max-width:1240px;margin:0 auto}}
header h1{{margin:0;font-family:Georgia,serif;font-size:34px;color:var(--ivory)}}header p{{color:var(--muted);max-width:760px;line-height:1.5}}
main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,580px),1fr));gap:18px;margin-top:22px}}
article{{padding:16px;border-radius:14px;background:rgba(255,255,255,.035);border:1px solid rgba(147,154,255,.22);min-width:0}}
.head{{display:flex;justify-content:space-between;align-items:baseline;gap:10px}}
.rec{{margin-top:12px;padding:12px 16px;border-radius:12px;background:rgba(126,227,176,.1);border:1px solid rgba(126,227,176,.4);color:#dff7ea;line-height:1.5;max-width:900px}}
h2.sec{{margin:28px 0 0;font:700 20px Georgia,serif;color:var(--ivory)}}h2{{margin:0;font-size:19px}}.head span{{color:var(--cyan);font-size:13px;font-weight:700}}
article p{{color:var(--muted);font-size:14px;line-height:1.45;margin:6px 0}}.params{{font-size:12px!important;color:#8f8bb3!important}}
.url{{display:flex;gap:8px;margin-top:10px}}.url input{{flex:1;min-width:0;padding:8px 10px;border-radius:8px;border:1px solid rgba(255,255,255,.14);background:#060816;color:var(--green2);font:13px ui-monospace,monospace}}
.url button{{padding:8px 14px;border-radius:8px;border:0;background:var(--green);color:#07101d;font-weight:800;cursor:pointer}}
.preview{{margin-top:12px;border-radius:10px;overflow:hidden;background:repeating-conic-gradient(#1a1d33 0 25%,#141629 0 50%) 0 0/22px 22px;position:relative}}
.preview iframe{{border:0;transform-origin:0 0;position:absolute;left:0;top:0;pointer-events:none;background:transparent}}
</style></head><body><header><div class="eyebrow">OBS setup</div><h1>New Eridian stream overlay</h1>
<p>Add each panel you want as an OBS <b>Browser Source</b>: paste its URL, set the width and height shown, and leave "Custom CSS" empty. Panels have transparent backgrounds. Changes in the game appear within a few seconds.</p>
<div class="rec"><b>Recommended: four sources carry everything.</b> Hub (rotating information), Avesta map, News ticker along the bottom, and Live alerts. The other panels below show one slide of the Hub each, if you prefer fixed panels. The full dashboard is still at <code>/overlay?channel={shown}</code>.</div></header>
<h2 class="sec">Recommended</h2><main>{''.join(cards[:4])}</main>
<h2 class="sec">Individual panels (optional)</h2><main>{''.join(cards[4:])}</main>
<script>for(const i of document.querySelectorAll('input[data-path]'))i.value=location.origin+i.dataset.path;
for(const b of document.querySelectorAll('.url button'))b.onclick=()=>{{const i=b.previousElementSibling;i.select();navigator.clipboard&&navigator.clipboard.writeText(i.value);b.textContent='Copied';setTimeout(()=>b.textContent='Copy',1500)}};</script>
</body></html>'''
