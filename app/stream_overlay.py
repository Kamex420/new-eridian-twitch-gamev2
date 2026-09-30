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
                    'days_to_holiday': f['days_until_holiday'],
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
/* New Eridian as a living isometric town, built for broadcast (960×540 source recommended).
   Districts fill with their own buildings as the society grows; Seedlings walk the streets
   and talk; a camera drifts in on whoever is speaking; sky, weather and holidays show. */
body{padding:0}.wrap{position:fixed;inset:0;overflow:hidden;background:#1d1a24}
svg{position:absolute;inset:0;width:100%;height:100%;display:block}
#world{transition:transform 2.8s cubic-bezier(.45,.05,.3,1)}
.token .shirt{stroke:#0b0f24;stroke-width:2}
.token .ini{font:900 11px Inter,system-ui,sans-serif;fill:#08101f;text-anchor:middle;dominant-baseline:central}
.token .label{font:800 11px Inter,system-ui,sans-serif;fill:#fffaf0;text-anchor:middle;paint-order:stroke;stroke:#060816;stroke-width:3.5px}
.token.walking .leg{animation:step .32s ease-in-out infinite alternate}.token.walking .leg.r{animation-delay:-.32s}
.token.walking .bod{animation:bob .32s ease-in-out infinite alternate}
@keyframes step{to{transform:translateY(-3px)}}@keyframes bob{to{transform:translateY(-1.5px)}}
.bubble{transform-box:fill-box;transform-origin:50% 100%}
@keyframes pop{from{opacity:0;transform:scale(.4)}to{opacity:1;transform:none}}
.bubble text{font:800 12px Inter,system-ui,sans-serif;fill:#171230;dominant-baseline:central}
.more text{font:900 13px Inter,system-ui,sans-serif;fill:#fff;text-anchor:middle;dominant-baseline:central}
.dlabel text{font:900 16px Inter,system-ui,sans-serif;letter-spacing:.05em;dominant-baseline:central;text-anchor:middle}
.dlabel .lvl{font:800 12px Inter,system-ui,sans-serif;fill:#fffaf0;opacity:.85}
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
.head .name{font:700 1.15em Georgia,serif;color:var(--ivory);white-space:nowrap}.head .tier{padding:.12em .55em;border-radius:.5em;background:rgba(126,227,176,.18);border:1px solid rgba(126,227,176,.55);color:var(--green2);font-weight:900;font-size:.8em;white-space:nowrap}
.head .hol{padding:.12em .55em;border-radius:.5em;font-weight:900;font-size:.8em;white-space:nowrap;color:#1a1026;background:var(--hol,#ffd27a)}.head .hol:empty{display:none}
.head .info{margin-left:auto;color:#e6e3fb;font-weight:700;font-size:.8em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* Caption: who and what on the first line, what they say below (wraps to two lines, never spills). */
.cap{position:absolute;left:1.6vw;right:1.6vw;bottom:1.4vh;display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;column-gap:.6em;padding:.3em .8em;border-radius:.6em;
  background:rgba(250,248,240,.95);color:#171230;font-size:clamp(11px,min(2vw,3.6vh),40px);line-height:1.2;box-shadow:0 .3em 1em rgba(0,0,0,.4);z-index:3;transition:opacity .5s;overflow:hidden}
.cap .mood{font-size:1.5em;line-height:1}.cap .text{min-width:0;overflow:hidden}
.cap .top{font-size:.8em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.cap .who{font-weight:900}.cap .what{color:#5b3fd1;font-weight:800}
.cap .said{font-style:italic;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow-wrap:anywhere}
.cap.hide{opacity:0}
.toast{position:absolute;left:50%;top:11vh;transform:translate(-50%,-30%) scale(.9);opacity:0;padding:.35em 1em;border-radius:.6em;z-index:4;white-space:nowrap;max-width:90vw;overflow:hidden;text-overflow:ellipsis;
  font:900 clamp(12px,min(2.6vw,4.6vh),52px) Inter,system-ui,sans-serif;color:#1a1026;background:linear-gradient(90deg,#ffe08a,#ffb86b);box-shadow:0 .3em 1.2em rgba(0,0,0,.45);transition:opacity .5s,transform .5s cubic-bezier(.2,1.3,.4,1)}
.toast.show{opacity:1;transform:translate(-50%,0) scale(1)}
.particle{position:absolute;pointer-events:none;animation:drift linear infinite;z-index:2}
@keyframes drift{from{transform:translate(0,0) rotate(0)}to{transform:translate(var(--dx),var(--dy)) rotate(var(--rot,0deg))}}
.glitch{position:absolute;left:0;right:0;height:2.2vh;background:linear-gradient(90deg,transparent,rgba(112,221,255,.35),transparent);z-index:2;pointer-events:none;animation:glitch .5s steps(3) forwards}
@keyframes glitch{0%{opacity:1;transform:translateX(-4%)}100%{opacity:0;transform:translateX(4%)}}
""", r"""
<div class="wrap" id="wrap">
<svg id="map" viewBox="0 0 960 540" preserveAspectRatio="xMidYMid meet">
 <defs>
  <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop id="sky0" offset="0" stop-color="#2b3350"/><stop id="sky1" offset=".6" stop-color="#4a4636"/><stop id="sky2" offset="1" stop-color="#3a3527"/></linearGradient>
  <radialGradient id="domeg" cx="35%" cy="30%" r="75%"><stop offset="0" stop-color="#ffffff" stop-opacity=".95"/><stop offset=".5" stop-color="#bfe8ff" stop-opacity=".7"/><stop offset="1" stop-color="#5aa6c8" stop-opacity=".55"/></radialGradient>
  <radialGradient id="vignette" cx="50%" cy="50%" r="72%"><stop offset=".62" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".45"/></radialGradient>
  <radialGradient id="glowdot"><stop offset="0" stop-color="#ffd98a" stop-opacity=".75"/><stop offset="1" stop-color="#ffd98a" stop-opacity="0"/></radialGradient>
  <radialGradient id="sung"><stop offset="0" stop-color="#fff6d8"/><stop offset=".35" stop-color="#ffe7a0" stop-opacity=".9"/><stop offset="1" stop-color="#ffcf6b" stop-opacity="0"/></radialGradient>
  <radialGradient id="shadeg"><stop offset="0" stop-color="#000" stop-opacity=".22"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>
  <linearGradient id="aurorag" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#7ee3b0" stop-opacity="0"/><stop offset=".5" stop-color="#7ee3b0" stop-opacity=".45"/><stop offset="1" stop-color="#70ddff" stop-opacity="0"/></linearGradient>
 </defs>
 <rect width="960" height="540" fill="url(#sky)"/><g id="stars"></g><g id="aurora"></g><g id="sun"></g><g id="skyclouds"></g>
 <path id="hills" fill="#39344a" opacity=".85"/><path id="hills2" fill="#2f2b3d" opacity=".95"/>
 <g id="world" style="transform:translate(480px,282px) scale(1.15) translate(-480px,-254px)">
  <g id="ground"></g><g id="city"></g><g id="festive"></g><g id="crowd"></g><g id="shades"></g>
  <rect id="tint" x="-600" y="-400" width="2160" height="1400" fill="transparent" style="pointer-events:none;transition:fill 4s"/>
  <rect id="haze" x="-600" y="-400" width="2160" height="1400" fill="transparent" style="pointer-events:none;transition:fill 4s"/>
  <g id="lights" style="pointer-events:none"></g><g id="labels"></g><g id="tokens"></g>
 </g>
 <rect width="960" height="540" fill="url(#vignette)" style="pointer-events:none"/>
 <g id="fx"></g>
</svg>
<div class="head"><span class="name">🏙️ New Eridian</span><span class="tier" id="tier">—</span><span class="hol" id="hol"></span><span class="info" id="info">Connecting to Avesta…</span></div>
<div class="toast" id="toast"></div>
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
const LOOK={commons:['⛲','Commons','#b8f4d0'],residential_ring:['🏠','Homes','#ffd27a'],agricultural_district:['🌾','Farms','#9be37e'],industrial_ward:['🏭','Industry','#ff9a76'],
  research_block:['🔬','Research','#70ddff'],market_concourse:['🪙','Market','#ffd27a'],spaceport_quarter:['🚀','Spaceport','#bd91ff'],frontier_edge:['🧭','Frontier','#ff9ad5']};
const GROUND={commons:'#b9b1a0',residential_ring:'#7f9a5a',agricultural_district:'#6d8c46',industrial_ward:'#8a8578',research_block:'#9aa3a8',market_concourse:'#b5a88c',spaceport_quarter:'#8e8f93',frontier_edge:'#8b7355',park:'#5f8a45',wild:'#6f6446'};
const MOOD={Inspired:'#ffd27a',Content:'#7ee3b0',Tired:'#9aa3c7',Hungry:'#ffb36b',Lonely:'#8fb3ff',Uneasy:'#d6a4ff',Stressed:'#ff9a76',Miserable:'#ff7484'};
const WEATHER_ICON={clear_skies:'☀️',good_growing:'🌧️',spore_drift:'🍃',dust_winds:'🌪️',busy_spaceport:'🚀',water_watch:'💧',quiet_cycle:'🌙',sensor_noise:'📡'};
const SHOW_NAMES=Q.get('names')==='1',PER_PLACE=Number(Q.get('per')||4),CAMERA=Q.get('camera')!=='0',SECONDS=Number(Q.get('seconds')||7)*1000;
// Holidays: colours, and what the town puts up for each.
const HOLIDAYS={'New Year':['🎆',['#ffd35a','#c9d3ff','#ff5ad1'],'newyear'],"Valentine's Day":['💝',['#ff5a8a','#ffb3c8','#ffffff'],'valentine'],
  'Memorial Day':['🇺🇸',['#d9303a','#ffffff','#2d5bd8'],'flag'],"Father's Day":['👔',['#3f7fd8','#8fd3ff','#ffd35a'],'grill'],'Independence Day':['🇺🇸',['#d9303a','#ffffff','#2d5bd8'],'flag'],
  'Labor Day':['🛠️',['#ffb000','#2d5bd8','#ffffff'],'labor'],'Halloween':['🎃',['#ff7a1a','#8a3ffc','#2b2b2b'],'halloween'],'Thanksgiving':['🦃',['#d9771f','#a8431a','#ffcf5a'],'feast'],
  'Christmas':['🎄',['#e0303a','#2fa84f','#ffd35a'],'christmas']};
function previewHoliday(){const q=(Q.get('holiday')||'').toLowerCase().replace(/[^a-z]/g,'');if(!q)return null;const name=Object.keys(HOLIDAYS).find(n=>n.toLowerCase().replace(/[^a-z]/g,'').startsWith(q));
  return name?{name,emoji:HOLIDAYS[name][0],days_to_holiday:Number(Q.get('days')||0)}:null}
function shade(hex,f){const n=parseInt(hex.slice(1),16),r=n>>16,g=n>>8&255,b=n&255,c=v=>Math.max(0,Math.min(255,Math.round(v*f)));return `rgb(${c(r)},${c(g)},${c(b)})`}
function diamond(i,j,w=1,h=1,inset=0){const a=iso(i+inset,j+inset),b=iso(i+w-inset,j+inset),c=iso(i+w-inset,j+h-inset),d=iso(i+inset,j+h-inset);return [a,b,c,d]}
const pts=p=>p.map(q=>q.join(',')).join(' ');
const up=(p,h)=>p.map(([x,y])=>[x,y-h]);
const vr=rng('lamps');

// ---- building parts (all drawn on a tile at i,j; w×d tiles; height h)
function box(g,i,j,w,d,h,color,opt={}){const [t,r,b,l]=diamond(i,j,w,d,opt.inset??.12),top=up([t,r,b,l],h);
  el('polygon',{points:pts([l,b,top[2],top[3]]),fill:shade(color,.72)},g);el('polygon',{points:pts([b,r,top[1],top[2]]),fill:shade(color,.9)},g);
  if(opt.roof==='pitched'){const apex=[(top[0][0]+top[2][0])/2,(top[0][1]+top[2][1])/2-h*.55-6];const rc=opt.roofColor||'#a8543e';
    el('polygon',{points:pts([top[3],top[0],apex]),fill:shade(rc,1.05)},g);el('polygon',{points:pts([top[0],top[1],apex]),fill:shade(rc,1.15)},g);
    el('polygon',{points:pts([top[3],top[2],apex]),fill:shade(rc,.78)},g);el('polygon',{points:pts([top[2],top[1],apex]),fill:shade(rc,.95)},g)}
  else el('polygon',{points:pts(top),fill:opt.topColor||shade(color,1.12)},g);
  if(opt.windows){const rows=Math.max(1,Math.floor(h/9)),cols=Math.max(1,Math.round(w*2));
    for(let k=0;k<rows;k++)for(let c=0;c<cols;c++){const f=(c+.5)/cols,yy=h-6-k*9;
      const L=[l[0]+(b[0]-l[0])*f,l[1]+(b[1]-l[1])*f-yy],R=[b[0]+(r[0]-b[0])*f,b[1]+(r[1]-b[1])*f-yy];
      el('rect',{class:'win',x:L[0]-1.5,y:L[1]-2,width:3,height:3,fill:'#ffd98a',opacity:0,'data-v':vr().toFixed(3)},g);el('rect',{class:'win',x:R[0]-1.5,y:R[1]-2,width:3,height:3,fill:'#ffd98a',opacity:0,'data-v':vr().toFixed(3)},g)}}
  return top}
function centre(i,j,w=1,d=1){return iso(i+w/2,j+d/2)}
function tree(g,i,j,r){const [x,y]=centre(i+(r()-.5)*.5,j+(r()-.5)*.5);el('ellipse',{cx:x+3,cy:y+2,rx:6,ry:3,fill:'rgba(0,0,0,.25)'},g);
  el('rect',{x:x-1.2,y:y-8,width:2.4,height:8,fill:'#6b4a2e'},g);el('circle',{class:'leaf',cx:x,cy:y-12,r:6+r()*2,fill:r()<.5?'#4f8a3c':'#3f7a34'},g);el('circle',{cx:x-2,cy:y-14,r:3,fill:'#6aa84f',opacity:.7},g)}
const ROOFS=['#a8543e','#3f6fa8','#5a8a4a','#8a5aa8','#b88a3a'];
const BUILD={
 residential_ring(g,i,j,r,n,level){if(n%7===6)return tree(g,i,j,r);
   if(level>=6&&n%5===0)return box(g,i,j,1,1,26+r()*18,'#d9d2c3',{windows:true,topColor:'#9aa0a8'});           // apartments as the district grows
   if(n%6===3){box(g,i,j,1,1,8,'#e6e0d4',{topColor:'#e6e0d4'});const [x,y]=centre(i,j);el('ellipse',{cx:x,cy:y-12,rx:12,ry:9,fill:'url(#domeg)',stroke:'#e8f7ff','stroke-width':.8},g);return}
   box(g,i,j,1,1,9+r()*5,'#e9e2cf',{roof:'pitched',roofColor:ROOFS[Math.floor(r()*ROOFS.length)],windows:true})},
 agricultural_district(g,i,j,r,n){if(n%9===4){box(g,i,j,1,1,11,'#9c3b2e',{roof:'pitched',roofColor:'#6b2a22'});return}
   if(n%9===8){const [x,y]=centre(i,j);el('ellipse',{cx:x,cy:y-6,rx:15,ry:10,fill:'url(#domeg)',stroke:'#dff8ff','stroke-width':.8},g);return}
   const [t,rr,b,l]=diamond(i,j,1,1,.04);el('polygon',{class:'field','data-v':r().toFixed(3),points:pts([t,rr,b,l]),fill:'#7fa543'},g);
   for(let k=1;k<4;k++){const f=k/4;el('line',{class:'stripe',x1:t[0]+(l[0]-t[0])*f,y1:t[1]+(l[1]-t[1])*f,x2:rr[0]+(b[0]-rr[0])*f,y2:rr[1]+(b[1]-rr[1])*f,stroke:'#95bb52','stroke-width':2},g)}},
 industrial_ward(g,i,j,r,n){if(n%5===2){const [x,y]=centre(i,j);el('ellipse',{cx:x,cy:y,rx:11,ry:5.5,fill:'#6d737b'},g);el('rect',{x:x-11,y:y-16,width:22,height:16,fill:'#9aa1a9'},g);el('ellipse',{cx:x,cy:y-16,rx:11,ry:5.5,fill:'#c3c9cf'},g);return}
   const top=box(g,i,j,1,1,14+r()*8,'#8d939b',{windows:true,topColor:'#6f757d'});const cx=top[1][0]-6,cy=top[1][1];
   el('rect',{x:cx-2.5,y:cy-18,width:5,height:18,fill:'#5a5f66'},g);el('rect',{x:cx-2.5,y:cy-18,width:5,height:3,fill:'#c2544a'},g);
   for(let k=0;k<2;k++)el('circle',{class:'smoke',cx:cx,cy:cy-22,r:4,fill:'#d8d3ca','data-v':r().toFixed(3),style:`animation-delay:-${(k*2.2+r()*2).toFixed(1)}s`},g)},
 research_block(g,i,j,r,n){if(n%6===0){box(g,i,j,1,1,8,'#e9eef2');const [x,y]=centre(i,j);el('ellipse',{cx:x,cy:y-12,rx:9,ry:4,fill:'#f5f8fa',stroke:'#9fb3c4','stroke-width':1.2,transform:`rotate(-25 ${x} ${y-12})`},g);el('line',{x1:x,y1:y-12,x2:x+4,y2:y-22,stroke:'#9fb3c4','stroke-width':1.5},g);return}
   if(n%6===3){const [x,y]=centre(i,j);box(g,i,j,1,1,6,'#dfe6ec');el('ellipse',{cx:x,cy:y-12,rx:13,ry:10,fill:'url(#domeg)',stroke:'#eaf8ff','stroke-width':.8},g);return}
   box(g,i,j,1,1,16+r()*14,'#cfdfe9',{windows:true,topColor:'#4f9fc4'})},
 market_concourse(g,i,j,r,n){if(n===0){box(g,i,j,1,1,20,'#e2cfa4',{roof:'pitched',roofColor:'#b8452f',windows:true});return}
   const c=['#e0564f','#f2b441','#4fa3e0','#7ec36b','#b86fd6'][Math.floor(r()*5)],top=box(g,i,j,1,1,6,'#d9cfb8',{topColor:c});
   el('polygon',{points:pts(top),fill:'none',stroke:'#fff','stroke-width':.8,'stroke-dasharray':'3 3'},g)},
 spaceport_quarter(g,i,j,r,n){if(n===0){box(g,i,j,1,1,40,'#c3cad3',{windows:true,topColor:'#5f6b80'});const [x,y]=centre(i,j);el('circle',{class:'beacon',cx:x,cy:y-46,r:3,fill:'#ff5a5a'},g);return}
   if(n===5){const [x,y]=centre(i,j);el('polygon',{points:pts([[x-5,y-4],[x+5,y-4],[x+5,y-40],[x,y-52],[x-5,y-40]]),fill:'#eef1f4',stroke:'#9aa3ad'},g);el('polygon',{points:pts([[x-5,y-4],[x-10,y+2],[x-5,y-16]]),fill:'#c24b3c'},g);el('polygon',{points:pts([[x+5,y-4],[x+10,y+2],[x+5,y-16]]),fill:'#c24b3c'},g);return}
   if(n%3===1){const [t,rr,b,l]=diamond(i,j,1,1,.02);el('polygon',{points:pts([t,rr,b,l]),fill:'#5d6068'},g);const [x,y]=centre(i,j);
     el('ellipse',{cx:x,cy:y,rx:12,ry:6,fill:'none',stroke:'#f6d365','stroke-width':1.6},g);el('text',{x:x,y:y+3,'text-anchor':'middle','font-size':8,'font-weight':900,fill:'#f6d365',transform:`scale(1 .6) translate(0 ${y/0.6-y})`},g).textContent='H';return}
   box(g,i,j,1,1,10+r()*6,'#aab1bb',{windows:true,topColor:r()<.5?'#6f7f99':'#c9774a'})},
 frontier_edge(g,i,j,r,n){const [x,y]=centre(i,j);if(n%4===0){el('polygon',{points:pts([[x-9,y+2],[x,y-26],[x+9,y+2]]),fill:'none',stroke:'#7a5a3a','stroke-width':2.5},g);el('circle',{cx:x,cy:y-24,r:3.5,fill:'#c0a27a'},g);return}
   if(n%4===1){for(let k=0;k<5;k++)el('circle',{cx:x+(r()-.5)*16,cy:y+(r()-.5)*7-3,r:3+r()*3.5,fill:k%2?'#8a8070':'#6f6658'},g);return}
   if(n%4===2){el('polygon',{points:pts([[x-10,y+3],[x,y-12],[x+10,y+3]]),fill:'#d7c7a3',stroke:'#a8946c'},g);el('polygon',{points:pts([[x,y-12],[x+10,y+3],[x+4,y+5]]),fill:'#b9a680'},g);return}
   tree(g,i,j,r)},
 commons(g,i,j,r,n){tree(g,i,j,r)},
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
(function terrain(){const g=document.getElementById('ground');
  const hill=(id,base,amp,seed)=>{const r=rng(seed);let d=`M0 ${base}`;for(let x=0;x<=960;x+=40)d+=` L${x} ${base-amp*r()}`;document.getElementById(id).setAttribute('d',d+' L960 540 L0 540 Z')};hill('hills',160,60,'h1');hill('hills2',205,45,'h2');
  el('polygon',{points:pts(diamond(-1.4,-1.4,N+2.8,N+2.8)),fill:'#5e5638',stroke:'#4a4330','stroke-width':3},g);
  const r=rng('wild');for(let k=0;k<50;k++){const i=-1.2+r()*(N+2.4),j=-1.2+r()*(N+2.4);if(i>-.2&&i<N+.2&&j>-.2&&j<N+.2)continue;const [x,y]=iso(i,j);el('circle',{cx:x,cy:y-3,r:2.5+r()*3.5,fill:r()<.6?'#4f7a3a':'#6e6552'},g)}
  const s=document.getElementById('stars');const sr=rng('stars');for(let k=0;k<70;k++){const x=sr()*960,y=40+sr()*200;el('circle',{class:sr()<.3?'twinkle':'',cx:x,cy:y,r:.6+sr()*1.3,fill:'#fff'},s)}
  const c=document.getElementById('skyclouds');for(let k=0;k<4;k++){const cg=el('g',{class:'cloud',style:`animation-duration:${150+k*40}s;animation-delay:-${k*55}s`},c),y=70+k*28;
    for(const [dx,dy,rx] of [[0,0,34],[26,-8,26],[-24,-4,22],[48,2,20]])el('ellipse',{cx:dx,cy:y+dy,rx,ry:rx*.45,fill:'#fff',opacity:.8},cg)}
  const sh=document.getElementById('shades');for(let k=0;k<3;k++){el('ellipse',{class:'shade',cx:300+k*120,cy:180+k*60,rx:120,ry:55,fill:'url(#shadeg)',style:`animation-duration:${80+k*25}s;animation-delay:-${k*30}s`},sh)}})();

const drawn={},levels={};let night=false,lastTier=-1,first=true;
const LAMPS=[];for(let s=0;s<N;s+=3)for(const k of [6,13]){LAMPS.push([k+.1,s+.1],[s+.1,k+.1])}
function streets(d,tier){const g=document.getElementById('ground');g.querySelectorAll('.street').forEach(e=>e.remove());
  const unlocked=k=>k==='commons'||k==='park'||((d.districts||{})[k]||{}).unlocked;
  for(let i=0;i<N;i++)for(let j=0;j<N;j++){if(!(ROAD.has(i)||ROAD.has(j)))continue;
    const near=Object.entries(CELLS).some(([k,[r,c]])=>{const [a,b]=cellTiles(r,c);return unlocked(k)&&i>=a-1&&i<=a+6&&j>=b-1&&j<=b+6});
    el('polygon',{class:'street',points:pts(diamond(i,j)),fill:near?(tier>=2?'#4a4d55':'#6a6250'):'#7a6c4e',stroke:near?'rgba(255,255,255,.05)':'none'},g)}
  if(tier>=2)for(const k of [6,13])for(let s=0;s<N;s++){if(ROAD.has(s))continue;const a=iso(k+.5,s+.15),b=iso(k+.5,s+.55),c=iso(s+.15,k+.5),e=iso(s+.55,k+.5);
    el('line',{class:'street',x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:'#e9d98a','stroke-width':1.2,opacity:.7},g);el('line',{class:'street',x1:c[0],y1:c[1],x2:e[0],y2:e[1],stroke:'#e9d98a','stroke-width':1.2,opacity:.7},g)}
  for(const [i,j] of LAMPS){const [x,y]=iso(i,j);el('rect',{class:'street',x:x-.8,y:y-9,width:1.6,height:9,fill:'#3a3d44'},g);el('circle',{class:'street win lamp',cx:x,cy:y-10,r:1.8,fill:'#ffe6a3',opacity:0,'data-v':'0'},g)}}
function district(key,info,tier){const [r,c]=CELLS[key],[a,b]=cellTiles(r,c),city=document.getElementById('city');
  let dg=drawn[key];const unlocked=key==='commons'||key==='park'||info.unlocked,level=key==='commons'?2+tier*2:key==='park'?6:(info.level||1);
  if(!dg||dg.unlocked!==unlocked){if(dg){dg.ground.remove();dg.g.remove();if(!first)toast(`🎉 ${LOOK[key]?LOOK[key][1]:'The Park'} is open for building!`,key)}
    dg=drawn[key]={unlocked,count:0,ground:el('g',{},document.getElementById('ground')),g:el('g',{},city)};
    for(let i=a;i<a+6;i++)for(let j=b;j<b+6;j++)el('polygon',{class:'tile',points:pts(diamond(i,j,1,1,.02)),fill:unlocked?shade(GROUND[key],.95+((i+j)%2)*.06):shade(GROUND.wild,.95+((i*j)%3)*.04)},dg.ground);
    if(key==='commons'){const [x,y]=centre(a+2,b+2,2,2);el('ellipse',{cx:x,cy:y,rx:30,ry:15,fill:'#3f7fa0',stroke:'#dfe9ea','stroke-width':3},dg.g);
      el('ellipse',{class:'ripple',cx:x,cy:y,rx:22,ry:11,fill:'none',stroke:'#dff6ff','stroke-width':2},dg.g);el('rect',{x:x-3,y:y-22,width:6,height:22,fill:'#cfc6b2'},dg.g);el('circle',{cx:x,cy:y-26,r:6,fill:'#8e8676'},dg.g)}
    if(key==='park'){const [x,y]=centre(a+1,b+2,3,3);el('ellipse',{cx:x,cy:y,rx:46,ry:22,fill:'#3d7ea0',stroke:'#9fd0e0','stroke-width':2,opacity:.95},dg.ground)}
    if(!unlocked){for(const [di,dj] of [[.5,.5],[5.5,.5],[.5,5.5],[5.5,5.5]]){const [x,y]=iso(a+di,b+dj);el('polygon',{points:pts([[x-3,y],[x,y-12],[x+3,y]]),fill:'#f28b3c'},dg.g)}
      const [x,y]=centre(a+3.5,b+3.5,1,1);el('rect',{x:x-14,y:y-20,width:28,height:14,rx:2,fill:'#d9c9a2',stroke:'#7a6446'},dg.g);el('rect',{x:x-1,y:y-6,width:2,height:8,fill:'#7a6446'},dg.g)}
    // Tile order for new buildings: fixed per district, so growth only ever adds buildings.
    const rr=rng('slots:'+key);dg.slots=[];for(let i=a;i<a+6;i++)for(let j=b;j<b+6;j++){if(key==='commons'&&i>=a+2&&i<a+4&&j>=b+2&&j<b+4)continue;if(key==='park'&&!(i===a||j===b||i===a+5||j===b+5))continue;dg.slots.push([i,j,rr()])}
    if(key!=='commons'&&key!=='park')dg.slots.sort((p,q)=>p[2]-q[2]);}
  if(!first&&unlocked&&levels[key]&&level>levels[key]&&LOOK[key])toast(`🏗️ ${LOOK[key][1]} grew to LV ${level}`,key);
  levels[key]=level;
  const want=!unlocked?0:key==='park'?dg.slots.length:key==='commons'?Math.min(dg.slots.length,4+tier*3):Math.min(dg.slots.length,3+level*3);
  if(want>dg.count){const add=dg.slots.slice(dg.count,want).map((s,n)=>[...s,dg.count+n]),grow=!first;dg.count=want;
    const put=()=>{for(const [i,j,,n] of add){const g=el('g',{class:grow?'rise':'','data-depth':i+j},dg.g);BUILD[key](g,i,j,rng(key+':'+n),n,level)}
      [...dg.g.children].sort((p,q)=>(+p.dataset.depth||0)-(+q.dataset.depth||0)).forEach(e=>dg.g.appendChild(e));litSig=''};
    if(!grow)return put();
    // New buildings: scaffolding and a crane first, then the building rises.
    const sc=add.map(([i,j],n)=>{const g=el('g',{'data-depth':i+j},dg.g);scaffold(g,i,j,n===0);return g});setTimeout(()=>{sc.forEach(g=>g.remove());put()},7000)}}
function labelsFor(d){const labels=document.getElementById('labels');labels.innerHTML='';
  for(const k in LOOK){const info=(d.districts||{})[k]||{unlocked:k==='commons',level:1},[x,y]=labelXY(k),[icon,short,color]=LOOK[k];
    const sub=k==='commons'?'':info.unlocked?`LV ${info.level}`:`AT ${String(info.unlocks_at||'').toUpperCase()}`,lab=el('g',{class:'dlabel'},labels);
    const box_=el('rect',{y:y-12,height:24,rx:12,fill:'rgba(8,13,39,.9)',stroke:color,'stroke-width':2},lab),t=el('text',{y:y+1,fill:color},lab);t.textContent=`${icon} ${short.toUpperCase()}`;
    const s=sub?el('text',{class:'lvl',y:y+1},lab):null;if(s)s.textContent=sub;const tw=t.getComputedTextLength(),sw=s?s.getComputedTextLength()+8:0,w=tw+sw+22;
    box_.setAttribute('x',x-w/2);box_.setAttribute('width',w);t.setAttribute('x',x-w/2+11+tw/2);if(s)s.setAttribute('x',x+w/2-11-sw/2+4)}}
function labelXY(k){const [r,c]=CELLS[k]||CELLS.commons,[a,b]=cellTiles(r,c);return iso(a+1.5,b+1.5)}

// ---- the town reacts to the society: crops, smoke, lit windows and market crowds
let litSig='',crowdSig='';
function liveTown(d){const st=d.stats||{},pop=d.population||0,ds=d.districts||{},here=k=>latest.filter(s=>s.place===k).length;
  const ratio=(st.food||0)/Math.max(1,pop*20),ripe=Math.max(0,Math.min(1,(ratio-.6)/1.6)),dry=ratio<.35,wet=weatherKey==='good_growing';
  document.querySelectorAll('.field').forEach(f=>{const v=+f.dataset.v,c=dry&&!wet?['#a08a52','#b59d62']:v<ripe?['#c9a64a','#dcbc5c']:wet?['#6f9c3a','#86b54a']:['#7fa543','#95bb52'];
    if(f.getAttribute('fill')!==c[0]){f.setAttribute('fill',c[0]);f.parentNode.querySelectorAll('.stripe').forEach(s=>s.setAttribute('stroke',c[1]))}});
  const smokeF=Math.min(1,.15+((ds.industrial_ward||{}).level||1)/16+here('industrial_ward')*.2);
  document.querySelectorAll('.smoke').forEach(s=>{s.style.display=+s.dataset.v<smokeF?'':'none'});
  const litF=night?Math.min(1,.3+pop/50):0,sig=litF+':'+document.querySelectorAll('.win').length;
  if(sig!==litSig){litSig=sig;const lights=document.getElementById('lights');lights.innerHTML='';
    document.querySelectorAll('.win').forEach((w,n)=>{const on=+w.dataset.v<litF;w.setAttribute('opacity',on?.95:0);
      if(on&&n%3===0){const x=+w.getAttribute('x')||+w.getAttribute('cx'),y=+w.getAttribute('y')||+w.getAttribute('cy');el('circle',{cx:x+1.5,cy:y+1.5,r:6,fill:'url(#glowdot)'},lights)}})}
  const market=(ds.market_concourse||{}).unlocked?Math.min(14,2+here('market_concourse')*2+(d.market&&d.market.primary?2:0)+Math.floor(((ds.market_concourse||{}).level||1)/2)):0;
  const party=festival?8:0,csig=market+':'+party;
  if(csig!==crowdSig){crowdSig=csig;const g=document.getElementById('crowd');g.innerHTML='';
    const people=(k,n,seed)=>{const [r,c]=CELLS[k],[a,b]=cellTiles(r,c),rr=rng(seed);for(let q=0;q<n;q++){const [x,y]=iso(a+1+Math.floor(rr()*5)+.02,b+1+Math.floor(rr()*5)+.5+rr()*.3);
      const p=el('g',{class:'shopper',style:`animation-delay:-${(rr()*1.1).toFixed(2)}s`},g);el('rect',{x:x-2.5,y:y-9,width:5,height:7,rx:2,fill:['#e0564f','#4fa3e0','#7ec36b','#f2b441','#b86fd6'][Math.floor(rr()*5)]},p);el('circle',{cx:x,cy:y-11.5,r:2.4,fill:['#f1c9a5','#c68a5a','#8d5a3b'][Math.floor(rr()*3)]},p)}};
    people('market_concourse',market,'shoppers');people('commons',party,'party')}}

// ---- Seedlings: little people who walk the streets between districts and stand under the district name
const tokens=document.getElementById('tokens'),live={};let latest=[];
const SKIN=['#f1c9a5','#e0ac7e','#c68a5a','#8d5a3b','#5e3b26'],HAIR=['#2b1d14','#5a3a22','#b07a3a','#e2c27a','#7a2a1a','#c9c9d6'];
function home(k,i,n){const [x,y]=labelXY(k);return [x+(i-(n-1)/2)*30,y+47]}
function roadFor(r,other){return r===0?6:r===2?13:(other===2?13:6)}
function route(from,to){if(from===to||!CELLS[from]||!CELLS[to])return [];const [ra,ca]=CELLS[from],[rb,cb]=CELLS[to],IA=roadFor(ra,rb),IB=roadFor(rb,ra),ja=ca*7+3,jb=cb*7+3;
  let p;if(IA===IB)p=[[IA+.5,ja],[IA+.5,jb]];else{const J=[6,13].sort((x,y)=>Math.abs(ja-x)+Math.abs(jb-x)-Math.abs(ja-y)-Math.abs(jb-y))[0];p=[[IA+.5,ja],[IA+.5,J+.5],[IB+.5,J+.5],[IB+.5,jb]]}
  return p.map(([i,j])=>iso(i,j))}
function figure(s){const g=el('g',{class:'token'},tokens),r=rng(s.id);el('ellipse',{cx:0,cy:0,rx:8,ry:3,fill:'rgba(0,0,0,.45)'},g);const bod=el('g',{class:'bod'},g);
  el('rect',{class:'leg l',x:-5,y:-9,width:4,height:9,rx:2,fill:'#2b2f45'},bod);el('rect',{class:'leg r',x:1,y:-9,width:4,height:9,rx:2,fill:'#2b2f45'},bod);
  el('rect',{class:'shirt',x:-8.5,y:-25,width:17,height:18,rx:6},bod);el('text',{class:'ini',y:-16},bod);
  el('circle',{cx:0,cy:-31,r:6.5,fill:SKIN[Math.floor(r()*SKIN.length)],stroke:'#0b0f24','stroke-width':1.5},bod);
  el('path',{d:'M-6.5 -32 A6.5 6.5 0 0 1 6.5 -32 Q0 -35 -6.5 -32Z',fill:HAIR[Math.floor(r()*HAIR.length)]},bod);
  el('text',{class:'act',x:10,y:-30,'font-size':11},bod);el('text',{class:'label',y:13},g);return {g,x:0,y:0,path:[],place:null}}
function seedlings(list){const groups={};for(const s of list)(groups[s.place]=groups[s.place]||[]).push(s);const seen=new Set();document.querySelectorAll('.more').forEach(e=>e.remove());
  for(const k in groups){const all=groups[k].sort((a,b)=>a.id<b.id?-1:1),n=Math.min(all.length,PER_PLACE),extra=all.length-n;
    all.forEach((s,i)=>{seen.add(s.id);const [tx,ty]=home(k,Math.min(i,n-1),n);let t=live[s.id];
      if(!t){t=live[s.id]=figure(s);t.id=s.id;t.x=tx;t.y=ty;t.place=k;t.g.setAttribute('transform',`translate(${tx},${ty})`)}
      t.hidden=i>=n;t.s=s;t.g.querySelector('.shirt').setAttribute('fill',MOOD[s.mood]||'#b8f4d0');t.g.querySelector('.ini').textContent=(s.name||'?').slice(0,1).toUpperCase();
      t.g.querySelector('.label').textContent=SHOW_NAMES?(s.name.length>8?s.name.slice(0,7)+'…':s.name):'';t.g.querySelector('.act').textContent=s.emoji||'';
      if(t.place!==k){t.path=[...route(t.place,k),[tx,ty]];t.place=k;t.g.style.display=''}else if(!t.path.length&&(Math.abs(t.x-tx)>1||Math.abs(t.y-ty)>1))t.path=[[tx,ty]];
      else if(t.path.length)t.path[t.path.length-1]=[tx,ty];
      if(!t.path.length)t.g.style.display=t.hidden?'none':''});
    if(extra>0){const [x,y]=home(k,n-1,n),m=el('g',{class:'more'},tokens);el('rect',{x:x+14,y:y-30,width:36,height:22,rx:11,fill:'#6b3fd1',stroke:'#fff','stroke-width':2},m);el('text',{x:x+32,y:y-19},m).textContent='+'+extra}}
  for(const id in live)if(!seen.has(id)){live[id].g.remove();delete live[id]}
  walk()}
let walking=false,lastT=0;
function walk(){if(walking)return;walking=true;lastT=performance.now();requestAnimationFrame(stepAll)}
function stepAll(now){const dt=Math.min(.1,(now-lastT)/1000);lastT=now;let any=false;
  for(const id in live){const t=live[id];if(!t.path.length){t.g.classList.remove('walking');continue}any=true;t.g.classList.add('walking');t.g.style.display='';
    let left=46*dt;while(left>0&&t.path.length){const [px,py]=t.path[0],dx=px-t.x,dy=py-t.y,dist=Math.hypot(dx,dy);if(dist<=left){t.x=px;t.y=py;left-=dist;t.path.shift()}else{t.x+=dx/dist*left;t.y+=dy/dist*left;left=0}}
    t.g.setAttribute('transform',`translate(${t.x.toFixed(1)},${t.y.toFixed(1)})`);if(!t.path.length&&t.hidden&&!t.g.querySelector('.bubble'))t.g.style.display='none'}
  sortTokens();if(any)requestAnimationFrame(stepAll);else walking=false}
// Nearer Seedlings draw in front. Nodes are only moved when the order really changes: moving one restarts its animations.
let sortAt=0,speaking=null;function sortTokens(force){const now=performance.now();if(!force&&now-sortAt<400)return;sortAt=now;
  const want=Object.values(live).sort((a,b)=>(a.id===speaking)-(b.id===speaking)||a.y-b.y).map(t=>t.g),have=[...tokens.children].filter(n=>n.classList.contains('token'));
  if(want.length===have.length&&want.every((g,i)=>g===have[i]))return;want.forEach(g=>tokens.appendChild(g))}
// A speech bubble pops up once over the speaker, stays a few seconds and fades away.
let bubbleTimer=null;
function speak(t,line){document.querySelectorAll('.bubble').forEach(b=>b.remove());clearTimeout(bubbleTimer);if(!t||!line)return;const text=line.length>44?line.slice(0,42)+'…':line;
  const b=el('g',{class:'bubble'},t.g),tx=el('text',{x:0,y:-58},b);tx.textContent=text;const w=tx.getComputedTextLength()+18;tx.setAttribute('x',-w/2+9);
  b.insertBefore(el('rect',{x:-w/2,y:-70,width:w,height:24,rx:9,fill:'#fffdf5',stroke:'#171230','stroke-width':1.6}),tx);b.insertBefore(el('polygon',{points:'-5,-47 5,-47 0,-40',fill:'#fffdf5',stroke:'#171230','stroke-width':1.6}),tx);
  b.insertBefore(el('rect',{x:-6,y:-48,width:12,height:3,fill:'#fffdf5'}),tx);t.g.style.display='';sortTokens(true);
  b.animate([{opacity:0,transform:'scale(.4)'},{opacity:1,transform:'none'}],{duration:350,easing:'cubic-bezier(.2,1.4,.4,1)'});
  bubbleTimer=setTimeout(()=>{b.animate([{opacity:1},{opacity:0}],{duration:500,fill:'forwards'}).onfinish=()=>{b.remove();if(t.hidden&&!t.path.length)t.g.style.display='none'}},Math.min(5500,SECONDS-800))}

// ---- the camera: a wide shot, drifting in on whoever is talking and on new buildings
const world=document.getElementById('world');let lockUntil=0;
function look(x,y,s){if(!CAMERA||x==null){world.style.transform='translate(480px,282px) scale(1.15) translate(-480px,-254px)';return}
  x=Math.max(OX-400+480/s,Math.min(OX+400-480/s,x));y=Math.max(OY-50+222/s,Math.min(OY+390-212/s,y));   // keep the town filling the frame, clear of the bars
  world.style.transform=`translate(480px,268px) scale(${s}) translate(${-x}px,${-y}px)`}
const toasts=[];let toasting=false;
function toast(text,key){toasts.push([text,key]);if(!toasting)nextToast()}
function nextToast(){const t=document.getElementById('toast'),item=toasts.shift();if(!item){toasting=false;return}toasting=true;t.textContent=item[0];t.classList.add('show');
  if(item[1]&&CELLS[item[1]]){const [x,y]=labelXY(item[1]);lockUntil=Date.now()+9000;look(x,y+40,1.8)}
  setTimeout(()=>{t.classList.remove('show');setTimeout(nextToast,600)},6000)}

// ---- sky, weather and holidays
let weatherKey='',festival=null,fxSig='',fireworks=null;
const SKY={Morning:['#f0a77e','#f6d6a8','#c9a27a','#8a6e5a','#6e5848'],Day:['#5f9ed8','#bfe0f4','#d6e6ee','#6d7f5a','#58694a'],Evening:['#3b2b5e','#e0785a','#f2a86a','#4a3550','#3a2a40'],Night:['#060a1f','#18204a','#1d2450','#15182c','#101224']};
function sky(phase,wkey){let [a,b,c,h1,h2]=SKY[phase]||SKY.Day;if(phase!=='Night'&&(wkey==='good_growing'||wkey==='water_watch')){a='#6f7885';b='#aab2bc';c='#bcc3cb'}
  if(phase!=='Night'&&wkey==='dust_winds'){a='#a8835a';b='#dcbb8c';c='#e6c89a'}
  document.getElementById('sky0').setAttribute('stop-color',a);document.getElementById('sky1').setAttribute('stop-color',b);document.getElementById('sky2').setAttribute('stop-color',c);
  document.getElementById('hills').setAttribute('fill',h1);document.getElementById('hills2').setAttribute('fill',h2);
  document.getElementById('stars').style.opacity=phase==='Night'?1:phase==='Evening'?.35:0;
  const sun=document.getElementById('sun');sun.innerHTML='';
  if(phase==='Night'){el('circle',{cx:870,cy:96,r:30,fill:'url(#glowdot)',opacity:.5},sun);el('circle',{cx:870,cy:96,r:16,fill:'#f4f1e0'},sun);el('circle',{cx:876,cy:91,r:13,fill:SKY.Night[0]},sun)}
  else if(wkey!=='good_growing'&&wkey!=='water_watch'){const [x,y,r]=phase==='Morning'?[110,150,26]:phase==='Evening'?[860,168,30]:[860,88,24];el('circle',{cx:x,cy:y,r:r*3,fill:'url(#sung)',opacity:.8},sun);el('circle',{cx:x,cy:y,r,fill:phase==='Evening'?'#ffb070':'#fff3c4'},sun)}
  document.getElementById('skyclouds').style.opacity=phase==='Night'?.15:(wkey==='good_growing'||wkey==='water_watch')?1:.7;
  document.getElementById('shades').style.display=phase==='Night'?'none':'';
  const au=document.getElementById('aurora');au.innerHTML='';if(phase==='Night'&&wkey==='sensor_noise')for(let k=0;k<3;k++)el('path',{d:`M0 ${120+k*18} Q240 ${60+k*25} 480 ${110+k*14} T960 ${90+k*20}`,stroke:'url(#aurorag)','stroke-width':14-k*3,fill:'none',opacity:.8},au);
  document.getElementById('haze').setAttribute('fill',wkey==='dust_winds'?'rgba(214,170,110,.16)':wkey==='water_watch'?'rgba(120,130,150,.10)':'transparent')}
function particles(kind,n,make){for(let k=0;k<n;k++){const p=document.createElement('i');p.className='particle';make(p,k);document.getElementById('wrap').appendChild(p)}}
function effects(phase){const pal=festival&&HOLIDAYS[festival.name]?HOLIDAYS[festival.name][1]:null,dark=phase==='Night'||phase==='Evening';
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
  el('circle',{cx:x,cy:y,r:30,fill:'url(#glowdot)',opacity:.35},b);setTimeout(()=>b.remove(),1600)};pop();fireworks=setInterval(pop,1100)}
// Decorations: bunting along the streets, lanterns or pumpkins by the lamps, and a centrepiece on the square in front of the Commons.
function decorate(g,theme,pal,dark){const r=rng('fest:'+theme);
  for(const k of [6,13])for(let s=0;s+3<N;s+=3)for(const [a,b] of [[[k+.1,s+.1],[k+.1,s+3.1]],[[s+.1,k+.1],[s+3.1,k+.1]]]){const [x1,y1]=iso(...a),[x2,y2]=iso(...b),mx=(x1+x2)/2,my=(y1+y2)/2+5;
    el('path',{d:`M${x1} ${y1-10} Q${mx} ${my-10} ${x2} ${y2-10}`,stroke:'rgba(40,30,30,.6)','stroke-width':.8,fill:'none'},g);
    for(let q=1;q<6;q++){const t=q/6,x=(1-t)*(1-t)*x1+2*(1-t)*t*mx+t*t*x2,y=(1-t)*(1-t)*(y1-10)+2*(1-t)*t*(my-10)+t*t*(y2-10),c=pal[q%pal.length];
      if(dark)el('circle',{cx:x,cy:y+1,r:4,fill:'url(#glowdot)'},g);el(dark?'circle':'polygon',dark?{cx:x,cy:y+1,r:1.8,fill:c}:{points:`${x-2.5},${y} ${x+2.5},${y} ${x},${y+5}`,fill:c},g)}}
  const lamp=(i,j,f)=>{const [x,y]=iso(i,j);f(x,y)};
  if(theme==='halloween'||theme==='feast')for(const [i,j] of LAMPS)lamp(i+.35,j+.35,(x,y)=>pumpkin(g,x,y,5,dark&&theme==='halloween'));
  if(theme==='feast')for(let q=0;q<10;q++){const [x,y]=iso(1+r()*4.5,15+r()*4.5);el('rect',{x:x-6,y:y-6,width:12,height:6,rx:1.5,fill:'#e2c25a',stroke:'#a8862e'},g)}
  const [x,y]=iso(13.5,13.5),c=el('g',{},g);
  if(theme==='christmas'){el('rect',{x:x-3,y:y-8,width:6,height:8,fill:'#6b4a2e'},c);[[34,-8,'#2a7a40'],[27,-24,'#2f8a4a'],[19,-38,'#3aa05a']].forEach(([w,o,f])=>el('polygon',{points:`${x-w},${y+o} ${x+w},${y+o} ${x},${y+o-26}`,fill:f},c));
    for(let q=0;q<14;q++){const t=r(),yy=y-10-t*52,xx=x+(r()-.5)*(34*(1-t)+4)*1.6;if(dark)el('circle',{cx:xx,cy:yy,r:5,fill:'url(#glowdot)'},c);el('circle',{cx:xx,cy:yy,r:2.2,fill:pal[q%3]},c)}
    el('polygon',{points:star(x,y-66,7,3),fill:'#ffd35a',stroke:'#fff3b0'},c);[[-22,'#e0303a'],[18,'#2d5bd8'],[-6,'#ffd35a']].forEach(([dx,f])=>{el('rect',{x:x+dx,y:y-6,width:10,height:8,fill:f},c);el('rect',{x:x+dx+4,y:y-6,width:2,height:8,fill:'#fff'},c)})}
  if(theme==='halloween'){pumpkin(c,x,y,20,dark);pumpkin(c,x-26,y+6,9,dark);pumpkin(c,x+26,y+6,8,dark);el('rect',{x:x+34,y:y-40,width:2,height:40,fill:'#6b4a2e'},c);el('rect',{x:x+26,y:y-32,width:18,height:2,fill:'#6b4a2e'},c);el('circle',{cx:x+35,cy:y-44,r:5,fill:'#e2c27a'},c);el('polygon',{points:`${x+28},${y-47} ${x+42},${y-47} ${x+35},${y-56}`,fill:'#2b2b2b'},c)}
  if(theme==='feast'){box(c,12.6,12.9,1.8,.6,6,'#8a5a32',{topColor:'#f4efe4'});for(let q=0;q<5;q++){const [px,py]=iso(12.8+q*.35,13.2);el('circle',{cx:px,cy:py-7,r:2.5,fill:pal[q%3]},c)}pumpkin(c,x-24,y+8,8,false);pumpkin(c,x+26,y+8,7,false)}
  if(theme==='flag'){el('rect',{x:x-1.5,y:y-70,width:3,height:70,fill:'#d6d6d6'},c);const fx=x+1.5,fy=y-70;for(let q=0;q<7;q++)el('rect',{x:fx,y:fy+q*3.4,width:40,height:3.4,fill:q%2?'#ffffff':'#d9303a'},c);el('rect',{x:fx,y:fy,width:17,height:13.6,fill:'#2d5bd8'},c);
    for(let q=0;q<6;q++)el('circle',{cx:fx+3+(q%3)*5.5,cy:fy+3.5+Math.floor(q/3)*6,r:.9,fill:'#fff'},c)}
  if(theme==='valentine'){el('path',{d:heart(x,y-50,26),fill:'none',stroke:'#ff5a8a','stroke-width':6},c);el('path',{d:heart(x,y-50,26),fill:'none',stroke:'#ffb3c8','stroke-width':2},c);for(let q=0;q<8;q++)el('circle',{cx:x+(r()-.5)*50,cy:y+(r()-.5)*10,r:2.5,fill:q%2?'#ff5a8a':'#e0303a'},c)}
  if(theme==='newyear'){el('rect',{x:x-1.5,y:y-64,width:3,height:64,fill:'#c9d3ff'},c);if(dark)el('circle',{cx:x,cy:y-70,r:18,fill:'url(#glowdot)'},c);el('circle',{cx:x,cy:y-70,r:9,fill:'#dfe6ff',stroke:'#ffd35a','stroke-width':2},c);
    const yr=new Date(Date.now()+(festival.days_to_holiday>0?festival.days_to_holiday:0)*864e5+864e5*2).getFullYear();sign(c,x,y-16,`HAPPY ${yr}!`,'#ffd35a')}
  if(theme==='grill'){box(c,13.2,13.2,.6,.4,7,'#333a44',{topColor:'#555'});el('circle',{class:'smoke',cx:x,cy:y-14,r:4,fill:'#d8d3ca'},c);sign(c,x,y-26,"HAPPY FATHER'S DAY",'#8fd3ff')}
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

// ---- captions: each Seedling in turn, with something new to say
let capIndex=0,capTick=0;const said={};
function caption(){const cap=document.getElementById('cap'),pool=latest.filter(s=>(s.lines&&s.lines.length)||s.thought);if(!pool.length){cap.classList.add('hide');return}
  const s=pool[capIndex++%pool.length],lines=(s.lines&&s.lines.length)?s.lines:[s.thought],idx=said[s.id]||0,line=lines[idx%lines.length],place=(LOOK[s.place]||LOOK.commons);
  cap.classList.add('hide');setTimeout(()=>{cap.innerHTML=`<span class="mood">${esc(s.mood_emoji||'🙂')}</span><div class="text"><div class="top"><span class="who">${esc(s.name)}</span> · <span class="what">${esc(place[0])} ${esc(s.activity)}</span></div>${line?`<div class="said">“${esc(line)}”</div>`:''}</div>`;cap.classList.remove('hide')},450);
  said[s.id]=idx+1;const t=live[s.id];speaking=s.id;speak(t,line);
  if(Date.now()<lockUntil)return;capTick++;
  if(t&&!t.path.length&&capTick%2===1)look(t.x,t.y-24,1.9);else look()}
setInterval(caption,SECONDS);
poll(d=>{try{
  if(Q.get('phase'))d.phase=Q.get('phase');if(Q.get('weather')){d.condition_key=Q.get('weather');d.condition=Q.get('weather').replace(/_/g,' ')}
  festival=previewHoliday()||d.festival||null;night=d.phase==='Night'||d.phase==='Evening';weatherKey=d.condition_key||'';
  const tier=d.tier_index||0;if(!first&&lastTier>=0&&tier>lastTier)toast(`🏙️ New Eridian is now a ${d.tier_name||d.tier}!`);
  if(tier!==lastTier){streets(d,tier);lastTier=tier}for(const k in CELLS)district(k,(d.districts||{})[k]||{},tier);labelsFor(d);
  document.getElementById('tint').setAttribute('fill',{Morning:'rgba(255,170,110,.08)',Day:'rgba(0,0,0,0)',Evening:'rgba(255,110,70,.14)',Night:'rgba(6,12,52,.5)'}[d.phase]||'transparent');
  sky(d.phase,weatherKey);effects(d.phase);glitches(weatherKey==='sensor_noise');shuttles(weatherKey==='busy_spaceport'&&d.phase!=='Night');
  latest=d.seedlings||[];liveTown(d);seedlings(latest);if(first){first=false;caption()}
  document.getElementById('tier').textContent=`${d.tier_name||d.tier||'Outpost'} · ${d.population||0} citizens`;
  const hol=document.getElementById('hol');if(festival&&HOLIDAYS[festival.name]){const n=festival.days_to_holiday;hol.style.setProperty('--hol',HOLIDAYS[festival.name][1][0]);
    const GREET={'Christmas':'Merry Christmas!','Memorial Day':'Memorial Day','Thanksgiving':'Happy Thanksgiving!'};hol.textContent=`${festival.emoji} `+(n===0?(GREET[festival.name]||`Happy ${festival.name}!`):n>0?`${festival.name} in ${n} day${n===1?'':'s'}`:`${festival.name} festival`)}else hol.textContent='';
  const busy=latest.filter(s=>/^Working|^Queue|^Gathering/.test(s.activity)).length;
  document.getElementById('info').textContent=`${d.phase_emoji||''} Day ${d.day} · ${d.phase} · ${WEATHER_ICON[weatherKey]||''} ${d.condition||''}`+(festival?'':` · ${busy} working`);
}catch(e){console.error(e)}},4000);
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
    ('map', 'Avesta map', 'New Eridian as a living town: buildings go up (with scaffolding and a crane) as the society grows, Seedlings walk the streets and talk in speech bubbles, the camera drifts in on whoever is speaking, the sky and weather follow Avesta, and the town decorates itself for holidays. Keep it at least a quarter of the screen.', 960, 540, '&camera=0 fixed wide shot · &names=1 · &per=6 · &seconds=7 · preview: &holiday=christmas &phase=Night &weather=dust_winds'),
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
