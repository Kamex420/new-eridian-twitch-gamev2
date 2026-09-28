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
PANELS = {'alerts', 'ticker', 'leaders', 'working', 'join', 'map', 'narrator'}
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
    leaders = {'contributors': [{'name': p.display_name, 'contribution': p.contribution} for p in players if p.contribution > 0],
               'active_today': [{'name': names.get(u, 'Citizen'), 'actions': n} for u, n in counts]}

    tq = m.task_queue
    queues = list(db.scalars(select(tq.TaskQueue).where(tq.TaskQueue.channel_id.in_(source_ids), tq.TaskQueue.state.in_(tuple(tq.ACTIVE)))
                             .order_by(tq.TaskQueue.next_at).limit(8)))
    who = {}
    if queues:
        for p in db.scalars(select(m.Player).where(m.Player.channel_id.in_(source_ids), m.Player.twitch_uid.in_([q.canonical_uid for q in queues]))):
            who.setdefault(p.twitch_uid, p.display_name)
    choices = tq.choices(m)
    working = [{'name': who.get(q.canonical_uid, 'Citizen'), 'task': choices.get(q.task, q.task.split(':')[-1]), 'done': q.total - q.remaining,
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
  for(const n of (d.narration||[]).slice(0,3))out.push(`📜 <i>${esc(n.text)}</i>`);
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
body{padding:0}.wrap{position:fixed;inset:0}
svg{width:100%;height:100%;display:block}
.district circle.halo{transition:opacity 1s}.district text{font-family:Inter,system-ui,sans-serif}
.token{transition:transform 3s cubic-bezier(.45,.05,.3,1)}.token circle{stroke:#0b0f24;stroke-width:2.5}
.token text{font:800 11px Inter,system-ui,sans-serif;fill:#08101f;text-anchor:middle;dominant-baseline:central}
.token .label{font:700 10.5px Inter,system-ui,sans-serif;fill:#fffaf0;paint-order:stroke;stroke:#060816;stroke-width:3px}
.token.new{animation:arrive 1.2s ease}
@keyframes arrive{0%{opacity:0}100%{opacity:1}}
.hud{position:absolute;left:18px;top:14px;padding:12px 16px;border-radius:14px;background:linear-gradient(145deg,rgba(8,13,39,.92),rgba(24,15,54,.9));border:1px solid var(--edge);max-width:360px}
.hud h1{margin:2px 0 0;font:700 22px Georgia,serif;color:var(--ivory)}.hud p{margin:4px 0 0;font-size:13px;color:var(--muted)}
.bubble{position:absolute;max-width:260px;padding:9px 12px;border-radius:12px;background:rgba(255,250,240,.96);color:#1a1433;font-size:13px;line-height:1.35;
  box-shadow:0 8px 20px rgba(0,0,0,.35);transform:translate(-50%,-100%);opacity:0;transition:opacity .5s,left 0s,top 0s;pointer-events:none}
.bubble.on{opacity:1}.bubble b{display:block;font-size:11px;color:#6b3fd1;letter-spacing:.06em;text-transform:uppercase;margin-bottom:2px}
.bubble:after{content:'';position:absolute;left:50%;bottom:-7px;margin-left:-7px;border:7px solid transparent;border-bottom:0;border-top-color:rgba(255,250,240,.96)}
.particle{position:absolute;border-radius:50%;pointer-events:none;animation:drift linear infinite}
@keyframes drift{from{transform:translate(0,0)}to{transform:translate(var(--dx),var(--dy))}}
""", r"""
<div class="wrap" id="wrap">
<svg id="map" viewBox="0 0 1200 700" preserveAspectRatio="xMidYMid meet">
 <defs>
  <radialGradient id="ground" cx="50%" cy="52%" r="65%"><stop offset="0" stop-color="#1c1840"/><stop offset=".65" stop-color="#0f0f2b"/><stop offset="1" stop-color="#070818" stop-opacity="0"/></radialGradient>
  <filter id="glow"><feGaussianBlur stdDeviation="6"/></filter>
 </defs>
 <rect id="bg" x="0" y="0" width="1200" height="700" rx="26" fill="url(#ground)"/>
 <g id="roads"></g><g id="districts"></g><g id="tokens"></g>
 <rect id="tint" x="0" y="0" width="1200" height="700" rx="26" fill="transparent" style="pointer-events:none;transition:fill 4s"/>
</svg>
<div class="hud"><div class="eyebrow">🗺️ Avesta · live</div><h1>New Eridian</h1><p id="clock">Connecting…</p><p id="count"></p></div>
<div class="bubble" id="bubble"></div>
</div>
<script>
const CX=600,CY=360,RX=410,RY=255;
const ORDER=['spaceport_quarter','market_concourse','industrial_ward','frontier_edge','residential_ring','agricultural_district','research_block'];
const LOOK={commons:['⛲','The Commons','#b8f4d0'],residential_ring:['🏠','Residential Ring','#ffd27a'],agricultural_district:['🌾','Agricultural District','#7ee3b0'],
  industrial_ward:['🏭','Industrial Ward','#ff9a76'],research_block:['🔬','Research Block','#70ddff'],market_concourse:['🪙','Market Concourse','#ffd27a'],
  spaceport_quarter:['🚀','Spaceport Quarter','#bd91ff'],frontier_edge:['🧭','Frontier Edge','#ff9ad5']};
const POS={commons:[CX,CY]};ORDER.forEach((k,i)=>{const a=(-90+i*360/ORDER.length)*Math.PI/180;POS[k]=[CX+RX*Math.cos(a),CY+RY*Math.sin(a)]});
const MOOD={Inspired:'#ffd27a',Content:'#7ee3b0',Tired:'#9aa3c7',Hungry:'#ffb36b',Lonely:'#8fb3ff',Uneasy:'#d6a4ff',Stressed:'#ff9a76',Miserable:'#ff7484'};
const NS='http://www.w3.org/2000/svg',el=(t,a)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e};
if(Q.get('bg')==='0')document.getElementById('bg').setAttribute('fill','transparent');
const roads=document.getElementById('roads'),dist=document.getElementById('districts');
for(const k of ORDER){const [x,y]=POS[k];roads.appendChild(el('path',{d:`M${CX} ${CY} Q ${(CX+x)/2+(y-CY)*.18} ${(CY+y)/2-(x-CX)*.12} ${x} ${y}`,stroke:'rgba(147,154,255,.28)','stroke-width':3,fill:'none','stroke-dasharray':'2 9','stroke-linecap':'round'}))}
for(const k in POS){const [x,y]=POS[k],[icon,name,color]=LOOK[k],r=k==='commons'?70:80,g=el('g',{class:'district'});
  g.appendChild(el('circle',{class:'halo',cx:x,cy:y,r:r+12,fill:color,opacity:.10,filter:'url(#glow)'}));
  g.appendChild(el('circle',{cx:x,cy:y,r:r,fill:'rgba(10,12,34,.82)',stroke:color,'stroke-opacity':.55,'stroke-width':2}));
  const t1=el('text',{x:x,y:y-r+26,'text-anchor':'middle','font-size':22});t1.textContent=icon;g.appendChild(t1);
  const t2=el('text',{x:x,y:y+r+18,'text-anchor':'middle','font-size':13,'font-weight':800,fill:color,'letter-spacing':'.06em'});t2.textContent=name.toUpperCase();g.appendChild(t2);
  dist.appendChild(g)}
const tokens=document.getElementById('tokens'),live={};let latest=[];
// Seedlings in one place stand on a small grid (up to 4 across) so names never collide.
function slot(place,i,n){const [x,y]=POS[place]||POS.commons,cols=Math.min(4,Math.ceil(Math.sqrt(n))),rows=Math.ceil(n/cols),
  r=Math.floor(i/cols),c=i%cols,inRow=Math.min(cols,n-r*cols),sx=n>9?38:48,sy=n>9?34:42;
  return [x+(c-(inRow-1)/2)*sx,y+6+(r-(rows-1)/2)*sy]}
function draw(list){const groups={};for(const s of list)(groups[s.place]=groups[s.place]||[]).push(s);const seen=new Set();
  for(const place in groups)groups[place].sort((a,b)=>a.id<b.id?-1:1).forEach((s,i,all)=>{seen.add(s.id);const [x,y]=slot(place,i,all.length);let g=live[s.id];
    if(!g){g=el('g',{class:'token new'});g.appendChild(el('circle',{r:13}));const t=el('text',{});g.appendChild(t);const l=el('text',{class:'label',y:26});g.appendChild(l);
      const e=el('text',{class:'act',x:14,y:-12,'font-size':13});g.appendChild(e);tokens.appendChild(g);live[s.id]=g;g.style.transform=`translate(${x}px,${y}px)`}
    g.querySelector('circle').setAttribute('fill',MOOD[s.mood]||'#b8f4d0');g.querySelector('text').textContent=(s.name||'?').slice(0,1).toUpperCase();
    g.querySelector('.label').textContent=s.name.length>12?s.name.slice(0,11)+'…':s.name;g.querySelector('.act').textContent=s.emoji||'';
    requestAnimationFrame(()=>g.style.transform=`translate(${x}px,${y}px)`);g.dataset.x=x;g.dataset.y=y});
  for(const id in live)if(!seen.has(id)){live[id].remove();delete live[id]}}
const TINT={Morning:'rgba(255,170,110,.07)',Day:'rgba(0,0,0,0)',Evening:'rgba(255,110,70,.11)',Night:'rgba(8,14,60,.38)'};
function weather(key){document.querySelectorAll('.particle').forEach(p=>p.remove());const look={spore_drift:['rgba(126,227,176,.55)',5,'80px','-40px'],dust_winds:['rgba(214,180,130,.45)',3,'260px','20px']}[key];if(!look)return;
  for(let i=0;i<28;i++){const p=document.createElement('i');p.className='particle';p.style.cssText=`left:${Math.random()*100}%;top:${Math.random()*100}%;width:${look[1]}px;height:${look[1]}px;background:${look[0]};--dx:${look[2]};--dy:${look[3]};animation-duration:${6+Math.random()*8}s;animation-delay:-${Math.random()*8}s`;document.getElementById('wrap').appendChild(p)}}
let lastWeather='';
function bubble(){const pool=latest.filter(s=>s.thought&&live[s.id]);const b=document.getElementById('bubble');if(!pool.length){b.classList.remove('on');return}
  const s=pool[Math.floor(Math.random()*pool.length)],g=live[s.id],svg=document.getElementById('map'),pt=svg.createSVGPoint();pt.x=+g.dataset.x;pt.y=+g.dataset.y-18;
  const sp=pt.matrixTransform(svg.getScreenCTM());b.innerHTML=`<b>${esc(s.mood_emoji)} ${esc(s.name)} · ${esc(s.activity)}</b>💭 ${esc(s.thought)}`;b.style.left=sp.x+'px';b.style.top=sp.y+'px';
  b.classList.add('on');setTimeout(()=>b.classList.remove('on'),5200)}
setInterval(bubble,Number(Q.get('seconds')||7)*1000);
poll(d=>{latest=d.seedlings||[];draw(latest);document.getElementById('clock').textContent=`${d.phase_emoji||''} Day ${d.day} · ${d.phase} · ${d.condition||''}`;
  const busy=latest.filter(s=>/^Working|^Queue/.test(s.activity)).length;document.getElementById('count').textContent=`${latest.length} Seedling${latest.length===1?'':'s'} · ${busy} at work`;
  document.getElementById('tint').setAttribute('fill',TINT[d.phase]||'transparent');const w=(d.condition||'').toLowerCase().includes('siro')?'spore_drift':(d.condition||'').toLowerCase().includes('dust')?'dust_winds':'';
  if(w!==lastWeather){lastWeather=w;weather(w)}},4000);
</script>""")

PAGES['narrator'] = (r"""
body{padding:4px}.card{padding:18px 22px}
.book{font-family:Georgia,"Times New Roman",serif}.lead{margin-top:10px;font-size:22px;line-height:1.4;color:var(--ivory);min-height:62px}
.lead .cursor{display:inline-block;width:2px;height:1em;background:var(--green2);margin-left:2px;vertical-align:-2px;animation:blink 1s infinite}
.meta{margin-top:6px;font:12px Inter,system-ui,sans-serif;color:var(--muted)}
.past{margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,.09);display:flex;flex-direction:column;gap:6px}
.past div{font-size:14px;line-height:1.35;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.past div:nth-child(2){opacity:.75}.past div:nth-child(3){opacity:.5}
@keyframes blink{50%{opacity:0}}
""", r"""
<section class="card"><div class="eyebrow">📜 Chronicle of New Eridian</div><div class="book"><div class="lead" id="lead">The colony stirs…</div></div><div class="meta" id="meta"></div><div class="past book" id="past"></div></section>
<script>
const LINES=Number(Q.get('lines')||3);let shown=null,typing=null,queue=[];
function type(n){clearInterval(typing);const lead=document.getElementById('lead'),text=`${n.emoji} ${n.text}`;let i=0;
  document.getElementById('meta').textContent=(n.place?n.place+' · ':'')+ago(n.at);
  typing=setInterval(()=>{i+=2;lead.innerHTML=esc(text.slice(0,i))+'<span class="cursor"></span>';if(i>=text.length){clearInterval(typing);lead.innerHTML=esc(text)}},28)}
let rows=[];
function show(){if(!queue.length)return;const n=queue.shift();type(n);shown=n.id;
  const past=rows.filter(r=>r.id<n.id).slice(0,LINES);document.getElementById('past').innerHTML=past.map(r=>`<div>${esc(r.emoji)} ${esc(r.text)}</div>`).join('')}
poll(d=>{rows=d.narration||[];if(!rows.length)return;if(shown===null){queue.push(rows[0]);show();return}
  for(const r of rows.slice().reverse())if(r.id>shown&&!queue.some(q=>q.id===r.id))queue.push(r)},4000);
setInterval(show,Number(Q.get('seconds')||9)*1000);
</script>""")


def page(panel, channel):
    css, body = PAGES[panel]
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>New Eridian · {panel}</title><style>{BASE_CSS}{css}</style></head><body class="panel-{panel}">'
            f'<script>const CHANNEL={json.dumps(channel)};{SHARED_JS}</script>{body}</body></html>')


# Every OBS source, with a sensible Browser Source size.
SOURCES = [('alerts', 'Live alerts', 'Animated pop-up for joins, level ups, achievements, events and milestones. Transparent when idle.', 700, 220,
            '&test=1 shows demo alerts · &sound=1 plays a chime · &seconds=7 · &hide=queue,join'),
           ('ticker', 'News ticker', 'A scrolling crawl: highlights, the event, directive, market, festival and how to join.', 1920, 46, '&speed=80'),
           ('leaders', 'Leaders', 'Top contributors, the most active citizens today and live event leaders.', 620, 330, ''),
           ('working', 'Working now', 'Everyone with a queue running, with live progress bars.', 460, 330, ''),
           ('join', 'How to play', 'Rotating chat commands so new viewers can join. Set DISCORD_INVITE_URL to show your invite.', 520, 220, '&seconds=7'),
           ('map', 'Avesta map', 'Every Seedling on a live map of New Eridian: where they are, what they do and how they feel. &bg=0 for a transparent background.',
            1200, 700, '&bg=0 · &seconds=7 (thought bubbles)'),
           ('narrator', 'Narrator', 'The colony\'s story as it happens, typed out line by line from every Seedling\'s diary.', 620, 260, '&lines=3 · &seconds=9'),
           ('society', 'Society', 'Name, tier, Avesta day and today\'s condition.', 420, 220, ''),
           ('today', 'Today', 'The daily directive and community stats.', 420, 280, ''),
           ('event', 'Event', 'The live society event with its countdown.', 520, 180, ''),
           ('ops', 'Operations', 'Project, weekly story, market and pressure.', 520, 420, ''),
           ('activity', 'Activity', 'The five latest citizen actions.', 520, 360, ''),
           ('telemetry', 'Telemetry rail', 'Six society stats, population and tier in one row.', 1860, 150, ''),
           ('signal', 'Signal', 'A small live/offline indicator.', 320, 60, '')]


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
.head{{display:flex;justify-content:space-between;align-items:baseline;gap:10px}}h2{{margin:0;font-size:19px}}.head span{{color:var(--cyan);font-size:13px;font-weight:700}}
article p{{color:var(--muted);font-size:14px;line-height:1.45;margin:6px 0}}.params{{font-size:12px!important;color:#8f8bb3!important}}
.url{{display:flex;gap:8px;margin-top:10px}}.url input{{flex:1;min-width:0;padding:8px 10px;border-radius:8px;border:1px solid rgba(255,255,255,.14);background:#060816;color:var(--green2);font:13px ui-monospace,monospace}}
.url button{{padding:8px 14px;border-radius:8px;border:0;background:var(--green);color:#07101d;font-weight:800;cursor:pointer}}
.preview{{margin-top:12px;border-radius:10px;overflow:hidden;background:repeating-conic-gradient(#1a1d33 0 25%,#141629 0 50%) 0 0/22px 22px;position:relative}}
.preview iframe{{border:0;transform-origin:0 0;position:absolute;left:0;top:0;pointer-events:none;background:transparent}}
</style></head><body><header><div class="eyebrow">OBS setup</div><h1>New Eridian stream overlay</h1>
<p>Add each panel you want as an OBS <b>Browser Source</b>: paste its URL, set the width and height shown, and leave "Custom CSS" empty. Panels have transparent backgrounds. Changes in the game appear within a few seconds. The full dashboard is still at <code>/overlay?channel={shown}</code> and now includes the live alerts.</p></header>
<main>{''.join(cards)}</main>
<script>for(const i of document.querySelectorAll('input[data-path]'))i.value=location.origin+i.dataset.path;
for(const b of document.querySelectorAll('.url button'))b.onclick=()=>{{const i=b.previousElementSibling;i.select();navigator.clipboard&&navigator.clipboard.writeText(i.value);b.textContent='Copied';setTimeout(()=>b.textContent='Copy',1500)}};</script>
</body></html>'''
