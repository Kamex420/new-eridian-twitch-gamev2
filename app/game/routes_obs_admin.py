"""Routes: OBS setup and panels, tick, wallet, progress, Rocky, Siro and admin tools.
"""
import random
from datetime import timedelta
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from ..commands import command as colony_command, transaction as game_transaction
from ..db import SessionLocal
from ..models import Identity, Player, WorldClock
from .base import (
    app, AVESTA_DAY_SECONDS, clean, out, OWNER_ONLY_TEXT, platform_response, twitch_owner_ok, valid_admin_key,
    valid_mod_key)
from .rules import EVENTS, SOCIETY_TIERS
from .players import as_utc, player, society, world
from .world import society_tier, world_clock
from .cooldowns_materials import audit_moderator
from .colony_events import cancel_event, maybe_start_auto_event, resolve_expired_event, start_event
from .. import main      # app.main: names from later modules and settings changed at runtime

@app.get("/obs",response_class=HTMLResponse)
def obs_setup(channel:str="new-eridian"):
    """Every OBS panel with its URL, size and a live preview."""
    from .. import stream_overlay
    return HTMLResponse(stream_overlay.setup_page(channel))

@app.get("/obs/{panel}",response_class=HTMLResponse)
def standalone_obs_panel(panel:str,channel:str="new-eridian"):
    valid={"society","today","event","ops","activity","telemetry","signal"}
    panel=(panel or "").lower().strip()
    from .. import stream_overlay
    if panel in stream_overlay.PANELS:
        return HTMLResponse(stream_overlay.page(panel,channel))
    if panel not in valid:
        raise HTTPException(status_code=404,detail="Unknown OBS panel")

    panel_json=stream_overlay.script_json(panel)
    channel_json=stream_overlay.script_json(channel)

    html=r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>New Eridian v2 OBS Panel</title>
<style>
:root{color-scheme:dark;--line:rgba(147,154,255,.36);--line2:rgba(89,218,255,.30);--text:#fffaf0;--muted:#aca9c9;--green:#7ee3b0;--green2:#b8f4d0;--violet:#bd91ff;--cyan:#70ddff;--amber:#ffd27a;--danger:#ff7484;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent;color:var(--text);-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}body{padding:4px}#root{width:100%;height:100%}
.card{width:100%;max-width:100%;overflow:hidden;background:radial-gradient(circle at 90% 0,rgba(125,72,220,.12),transparent 42%),linear-gradient(145deg,rgba(8,13,39,.98),rgba(24,15,54,.96));border:1px solid rgba(147,154,255,.48);border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,.34);padding:18px 20px}
.eyebrow{font-size:12px;font-weight:850;letter-spacing:.14em;text-transform:uppercase;color:var(--green2)}.muted{color:var(--muted)}.small{font-size:12px}
.row{display:flex;align-items:center;justify-content:space-between;gap:10px;min-width:0}.wrap{flex-wrap:wrap}
h1,h2,h3,p{margin:0}h1{font-family:Georgia,"Times New Roman",serif;font-size:31px;line-height:1.05;color:#fff8e8;text-shadow:0 0 3px rgba(255,248,232,.38)}h2{font-size:24px}
.progress{height:8px;margin-top:9px;overflow:hidden;border-radius:999px;background:rgba(255,255,255,.08)}.progress i{display:block;height:100%;width:0;border-radius:999px;background:linear-gradient(90deg,var(--green),var(--violet))}
.chip{padding:5px 9px;border:1px solid var(--line2);border-radius:999px;background:rgba(152,215,155,.08);color:var(--green2);font-size:12px;font-weight:800}
.sep{opacity:.35}.worldline{display:flex;gap:8px;flex-wrap:wrap;margin-top:11px;font-size:13px}.condition{margin-top:13px;padding-top:12px;border-top:1px solid rgba(255,255,255,.09)}.condition strong{font-size:15px}.condition p{margin-top:5px;font-size:12px;color:var(--muted);line-height:1.4}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.module{min-width:0;padding:12px;border:1px solid rgba(255,255,255,.09);background:rgba(7,9,13,.28);border-radius:10px}.module h3{font-size:14px;margin-bottom:5px}.value{font-size:12px;color:var(--muted);line-height:1.4;overflow-wrap:anywhere}.rumor{margin-top:11px;padding-top:10px;border-top:1px solid rgba(255,255,255,.09);font-size:11px;line-height:1.4;color:var(--muted)}
.storypaths{display:flex;flex-direction:column;gap:8px;margin-top:9px}.pathhead{display:flex;justify-content:space-between;gap:8px;font-size:11px}.pathname{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pathmeta{white-space:nowrap;color:var(--muted)}.path.lead .pathname,.path.lead .pathmeta{color:var(--green2)}.pathbar{height:6px;border-radius:99px;background:rgba(255,255,255,.07);overflow:hidden;margin-top:4px}.pathbar i{display:block;height:100%;background:var(--cyan)}.path.lead .pathbar i{background:var(--green2)}
.activity-list{display:flex;flex-direction:column;gap:9px;margin-top:11px}.activity .icon{width:26px;height:26px;display:grid;place-items:center;border-radius:50%;background:rgba(189,145,255,.14);font-size:14px}.activity.fresh{animation:slidein .6s cubic-bezier(.2,1.2,.4,1) both;box-shadow:inset 3px 0 0 var(--green)}@keyframes slidein{from{opacity:0;transform:translateX(-18px)}to{opacity:1;transform:none}}.activity{display:grid;grid-template-columns:26px minmax(0,1fr);gap:10px;min-width:0;padding:9px 10px;border-radius:9px;background:rgba(7,9,13,.30)}.pulse{width:8px;height:8px;border-radius:50%;background:var(--violet);margin-top:5px}.activity:first-child .pulse{background:var(--green)}.top{display:flex;gap:8px;flex-wrap:wrap;min-width:0}.who{font-size:12px;font-weight:850;overflow-wrap:anywhere}.action{font-size:11px;color:var(--cyan);letter-spacing:.07em;text-transform:uppercase;overflow-wrap:anywhere}.age{margin-left:auto;font-size:11px;color:var(--muted);white-space:nowrap}.msg{font-size:12px;color:var(--muted);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stats{display:grid;grid-template-columns:repeat(6,minmax(0,1fr)) 120px 170px;gap:1px;padding:0;overflow:hidden}.stat,.pop,.tier{min-width:0;padding:13px 12px;background:rgba(8,10,14,.28)}.stat small,.pop small,.tier small{display:block;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}.stat strong,.pop strong{display:block;font-size:23px;margin-top:5px}.tier strong{display:block;font-size:18px;color:var(--green2);margin-top:6px}.tiny{font-size:10px;color:var(--muted);margin-top:6px}
.event .eyebrow{color:#ff9aa6}.timer{font-size:23px;font-weight:850}.eventmeta{display:flex;gap:14px;flex-wrap:wrap;margin-top:11px;font-size:12px;color:var(--muted)}.eventmeta b{color:#fff}
.signal{display:inline-flex;align-items:center;gap:8px;padding:10px 12px;border:1px solid rgba(255,255,255,.11);border-radius:9px;background:rgba(12,14,18,.94);font-size:11px;letter-spacing:.10em;text-transform:uppercase;color:var(--muted)}.dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 6px rgba(152,215,155,.48)}.bad .dot{background:var(--danger)}
/* A standalone OBS source should keep its intended card layout even if OBS
   reports a narrow CSS viewport before the source is transformed on canvas. */
body.panel-ops .grid2{grid-template-columns:1fr 1fr!important}
body.panel-today .grid2{grid-template-columns:repeat(3,minmax(0,1fr))!important}
/* OBS can report a narrow CSS viewport even after the source is transformed
   wide on the canvas. The telemetry rail must always remain one horizontal
   row; otherwise OBS stretches a mobile stack and clips everything after Food. */
body.panel-telemetry{padding:0!important}
body.panel-telemetry #root{min-width:0}
body.panel-telemetry .stats{
  width:100%;height:150px;
  grid-template-columns:repeat(6,minmax(0,1fr)) minmax(72px,.75fr) minmax(105px,1.1fr)!important;
  border-radius:12px
}
body.panel-telemetry .stat,
body.panel-telemetry .pop,
body.panel-telemetry .tier{padding:10px 9px}
body.panel-telemetry .tiny{white-space:normal;line-height:1.2}
</style>
</head>
<body class="panel-__BODY_CLASS__">
<div id="root"><section class="card"><div class="eyebrow">New Eridian Signal</div><div class="value" style="margin-top:6px">Connecting to Avesta telemetry…</div></section></div>
<script>
const PANEL=__PANEL__;
const CHANNEL=__CHANNEL__;
const root=document.getElementById('root');
const esc=v=>String(v==null?'':v).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const pct=(v,max)=>Math.max(0,Math.min(100,(Number(v)||0)/Math.max(1,Number(max)||1)*100));
const bar=value=>`<div class="progress"><i style="width:${Math.max(0,Math.min(100,Number(value)||0))}%"></i></div>`;
const fmtTime=n=>{n=Math.max(0,Number(n)||0);return Math.floor(n/60)+':'+String(n%60).padStart(2,'0')};
const ago=iso=>{const sec=Math.max(0,Math.floor((Date.now()-new Date(iso).getTime())/1000));if(sec<10)return 'just now';if(sec<60)return sec+'s ago';if(sec<3600)return Math.floor(sec/60)+'m ago';if(sec<86400)return Math.floor(sec/3600)+'h ago';return Math.floor(sec/86400)+'d ago'};

function plainSentence(msg){
  // The first real sentence of a reply: no emoji, markup, bare stats or ALL-CAPS headers.
  for(let part of String(msg||'').split(/\s*(?:\n| \| | · )\s*/)){
    part=part.replace(/[*_`]/g,'').replace(/^[^A-Za-z0-9(]+/,'').trim();
    if(!part||/^[+\-−\d]/.test(part)||(part===part.toUpperCase()&&!/\d/.test(part)))continue;
    part=part.split(/(?<=[.!?])\s/)[0];return part.length>90?part.slice(0,88)+'…':part}
  return ''}
function concise(msg){
  msg=String(msg||'').replace(/\s+/g,' ').trim();
  const found=[]; const re=/([+-]\d+\s+(?:[A-Za-z][A-Za-z /_-]*?))(?=(?:[,.;]|\/|\s+[+-]\d+|$))/g; let m;
  while((m=re.exec(msg))!==null&&found.length<4){const x=m[1].trim().replace(/\s+/g,' ');if(!found.includes(x))found.push(x)}
  if(found.length)return found.join(' · ');const said=plainSentence(msg);if(/fail|\+0 rewards/i.test(msg))return 'No reward'+(said?' · '+said:'');return said||'Completed successfully';
}
function renderSociety(d){root.innerHTML=`<section class="card"><div class="eyebrow">Society Telemetry</div><div class="row" style="margin-top:5px"><h1>NEW ERIDIAN</h1><span class="chip">${esc(d.tier)}</span></div><div class="worldline"><span>Avesta Day <b>${d.day}</b></span><span class="sep">•</span><span>${esc((d.phase_emoji||'')+' '+(d.phase||''))}</span><span class="sep">•</span><span><b>${d.active_players||0}</b> active</span></div><div class="condition"><strong>${esc(d.condition||'Unknown condition')}</strong><p>${esc(d.condition_text||'')}</p></div><div class="value" style="margin-top:9px;color:#8f86bb;font-family:Georgia,serif">May Rocky's wisdom guide you…</div></section>`}
function renderToday(d){const q=d.directive||{},g=d.engagement||{},a=d.aftermath;const after=a?`<div class="rumor"><b style="color:${Number(a.modifier)>=0?'var(--green2)':'var(--danger)'}">Event aftermath ${Number(a.modifier)>=0?'+':''}${Number(a.modifier)}%</b> · ${esc((a.skills||[]).join(' / '))} · ${fmtTime(a.seconds_remaining)} remaining<br>${esc(a.description||'')}</div>`:'';root.innerHTML=`<section class="card"><div class="eyebrow">✦ Today in New Eridian</div><div class="module" style="margin-top:10px"><div class="row"><h3>${q.complete?'✓ ':''}${esc(q.name||'Daily Directive')}</h3><b class="small" style="color:var(--cyan)">${q.progress||0}/${q.goal||0}</b></div><div class="value">${esc(q.description||'')}</div>${bar(q.percent||0)}<div class="value" style="margin-top:5px">Useful: ${esc((q.skills||[]).join(' · '))} · Reward ${esc(q.reward||'society progress')}</div></div><div class="grid2" style="grid-template-columns:repeat(3,1fr)"><div class="module"><h3>${Number(g.variety_complete||0)}</h3><div class="value">Variety done</div></div><div class="module"><h3>${Number(g.lore_found||0)}/${Number(g.lore_total||0)}</h3><div class="value">Lore found</div></div><div class="module"><h3>${Number(g.fleet_assigned||0)}</h3><div class="value">Fleet assigned</div></div></div><div class="value" style="margin-top:7px">Gear familiarity: ${Number(g.familiar_gear||0)} familiar / ${Number(g.trusted_gear||0)} trusted · ${Number(g.relationship_memories||0)} shared memories</div>${after}</section>`}
function renderEvent(d){const e=d.event;if(!e){root.innerHTML=`<section class="card event"><div class="eyebrow">Live Society Event</div><h2 style="margin-top:6px">No active event</h2><p class="value" style="margin-top:5px">New Eridian is currently stable.</p></section>`;return}root.innerHTML=`<section class="card event"><div class="eyebrow">⚠ Live Society Event</div><div class="row" style="margin-top:5px"><h2>${esc((e.emoji||'🚨')+' '+e.name)}</h2><span class="timer">${fmtTime(e.seconds_remaining)}</span></div>${bar(e.percent)}<div class="eventmeta"><span>Progress <b>${e.progress}/${e.goal}</b></span><span>Primary <b>${esc(e.primary)}</b></span><span>Support <b>${esc(e.support)}</b></span></div></section>`}
function renderOps(d){const p=d.project||{},st=d.story||{},m=d.market||{},tracks=st.tracks||[],total=tracks.reduce((a,x)=>a+(Number(x.value)||0),0),max=Math.max(0,...tracks.map(x=>Number(x.value)||0));const paths=tracks.map(x=>{const value=Number(x.value)||0,share=total?Math.round(value/total*100):0,lead=value===max&&max>0;return `<div class="path${lead?' lead':''}"><div class="pathhead"><span class="pathname">${esc(x.name)}${lead?' · LEADING':''}</span><span class="pathmeta">${value} · ${share}%</span></div><div class="pathbar"><i style="width:${share}%"></i></div></div>`}).join('');root.innerHTML=`<section class="card"><div class="eyebrow">Avesta Operations</div><div class="grid2"><div class="module"><h3>🏗️ Society Project</h3><div class="value">${esc(p.name||'None')} · ${p.progress||0}/${p.goal||0}</div>${bar(p.percent||0)}<div class="value" style="margin-top:5px">${esc((p.skills||[]).join(' · '))}</div></div><div class="module"><h3>📖 Weekly Story · ${Math.round(st.percent||0)}%</h3><div class="value">${esc(st.name||'None')} · ${st.progress||0}/${st.goal||0}</div>${bar(st.percent||0)}<div class="storypaths">${paths}</div></div><div class="module"><h3>💰 Market Signal</h3><div class="value" style="color:var(--amber)">🔥 ${esc(m.primary&&m.primary.name||'None')}${m.primary?' · '+m.primary.price+' SC':''}</div><div class="value">${m.secondary?'↑ '+esc(m.secondary.name)+' · '+m.secondary.price+' SC':''}</div></div><div class="module"><h3>📡 Society Pressure</h3><div class="value">${esc((d.pressure||[]).join(' · ')||'No critical shortages')}</div></div></div><div class="rumor">${d.rumor?'🗣️ '+esc(d.rumor):''}</div></section>`}
const ACT_ICON={relax:'🛋️',sleep:'🛏️',eat:'🍲',games:'🎲',walk:'🌿',hobby:'🎨',meal:'🎃',hi:'👋',hangout:'☕',mentor:'🎓',farm:'🌱',harvest:'🎃',forage:'🍓',water:'💧',scan:'📡',mine:'⛏️',rare:'💎',research:'🔬',cargo:'📦',delivery:'🦆',spaceport:'🚀',explore:'🧭',survey:'🗺️',market:'🪙',repair:'🔧',business:'🏢',make:'🛠️',craft:'🛠️',gather:'🌿',start:'🌱'};
const seenActivity=new Set();
function actIcon(a){a=String(a||'').toLowerCase();for(const k in ACT_ICON)if(a.includes(k))return ACT_ICON[k];return '✦'}
function renderActivity(d){const rows=(d.activity||[]).slice(0,5);const first=!seenActivity.size;root.innerHTML=`<section class="card"><div class="row"><div class="eyebrow">Recent Citizen Activity</div><span class="small muted">${rows.length} latest</span></div><div class="activity-list">${rows.length?rows.map(x=>{const key=x.at+x.name+x.action,fresh=!first&&!seenActivity.has(key);seenActivity.add(key);return `<div class="activity${fresh?' fresh':''}"><span class="icon">${actIcon(x.action)}</span><div style="min-width:0"><div class="top"><span class="who">${esc(x.name)}</span><span class="action">${esc(x.action)}</span><span class="age">${ago(x.at)}</span></div><div class="msg">${esc(concise(x.message))}</div></div></div>`}).join(''):'<div class="value">Waiting for citizen activity…</div>'}</div></section>`}
function renderTelemetry(d){const meta={food:['🌾','Food'],materials:['⛏️','Materials'],development:['⚙️','Development'],knowledge:['🔬','Knowledge'],treasury:['🪙','Treasury'],reputation:['⭐','Reputation']},target=d.tier_target||1;const stats=Object.entries(meta).map(([key,[icon,label]])=>{const value=d.stats&&d.stats[key]||0;return `<div class="stat"><small>${icon} ${label}</small><strong>${Number(value).toLocaleString()}</strong><div class="tiny">${d.next_tier?`${Math.min(value,target)}/${target} to ${esc(d.next_tier)}`:'Maximum tier'}</div>${bar(d.next_tier?pct(value,target):100)}</div>`}).join('');const bonus=Number(d.tier_bonus||0);root.innerHTML=`<section class="card stats">${stats}<div class="pop"><small>👥 Population</small><strong>${Number(d.stats&&d.stats.population||0).toLocaleString()}</strong><div class="tiny">${d.active_players||0} active / 30m</div></div><div class="tier"><small>Society Tier</small><strong>${esc(d.tier||'—')}</strong><div class="tiny">${d.next_tier?'Next: '+esc(d.next_tier)+' · '+d.tier_target+' each':'Regional Hub reached'}<br>Tier bonus: ${bonus?('+'+bonus+' SC on success'):'None'}</div></div></section>`}
function renderSignal(ok=true){root.innerHTML=`<div class="signal${ok?'':' bad'}"><span class="dot"></span>${ok?'LIVE SIGNAL · NEW ERIDIAN':'SIGNAL INTERRUPTED · RETRYING'}</div>`}
function render(d){if(PANEL==='society')renderSociety(d);else if(PANEL==='today')renderToday(d);else if(PANEL==='event')renderEvent(d);else if(PANEL==='ops')renderOps(d);else if(PANEL==='activity')renderActivity(d);else if(PANEL==='telemetry')renderTelemetry(d);else renderSignal(true)}
async function refresh(){try{const response=await fetch('/api/v1/overlay?channel='+encodeURIComponent(CHANNEL),{cache:'no-store'});if(!response.ok)throw new Error('HTTP '+response.status);const data=await response.json();if(!data.ok)throw new Error('No overlay data');render(data)}catch(err){if(PANEL==='signal')renderSignal(false);else root.innerHTML=`<section class="card"><div class="eyebrow" style="color:var(--danger)">Signal Interrupted</div><div class="value" style="margin-top:6px">Retrying New Eridian telemetry…</div></section>`}}
refresh();setInterval(refresh,3500);
</script>
</body></html>"""
    html=(html.replace("__BODY_CLASS__",panel)
              .replace("__PANEL__",panel_json)
              .replace("__CHANNEL__",channel_json))
    return HTMLResponse(stream_overlay.themed(html, fit=True))

@app.get("/api/v1/tick")
@game_transaction
def tick(channel:str):
    with SessionLocal() as db:
        s=society(db,channel);w=world(db,channel);w.heartbeat=main.now();expired=resolve_expired_event(db,s,w)
        if expired:return out(expired)
        started=maybe_start_auto_event(db,w,add_activity=False)
        if started:return out(started)
        db.commit();return out("")


@app.get("/api/v1/wallet")
@game_transaction
def wallet(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        return out(f"🪙 {p.display_name} has {p.sc} SC | ⭐ Contribution {p.contribution}")

@app.get("/api/v1/progress")
@colony_command
def progress(channel:str,provider:str="twitch",viewer:str=""):
    with SessionLocal() as db:
        s=society(db,channel);tier=society_tier(s);core=min(s.food,s.materials,s.development,s.knowledge,s.treasury,s.reputation)
        next_tier=next((x for x in SOCIETY_TIERS if x[1]>core),None)
        target=next_tier[1] if next_tier else SOCIETY_TIERS[-1][1]
        unlock=f"Next: {next_tier[0]} at {target} in every major stat" if next_tier else "Maximum society tier reached"
        stats={"Food":s.food,"Materials":s.materials,"Development":s.development,"Knowledge":s.knowledge,"Treasury":s.treasury,"Reputation":s.reputation};weak=min(stats,key=stats.get)
        if next_tier:
            rows="\n".join(f"• {label}: {value}/{target}" for label,value in stats.items());next_text=f"Next tier: {next_tier[0]}\nRequirement: {target} in every major stat\nCurrent bottleneck: {weak} ({stats[weak]}/{target})"
        else:rows="\n".join(f"• {label}: {value}" for label,value in stats.items());next_text="✅ Maximum society tier reached."
        discord=f"🏗️ New Eridian — Tier Progress\n\n"+(f"{clean(viewer)}, your most useful target is {weak}.\n\n" if viewer else "")+f"Current tier: {tier[0]}\nTier bonus: {('+'+str(tier[2])+' SC on success') if tier[2] else 'None'}\n\n{rows}\n\n{next_text}\n\nUse /guide goal:society for your best matching action."
        twitch=f"🏗️ New Eridian — {tier[0]} | F{s.food} M{s.materials} D{s.development} K{s.knowledge} T{s.treasury} R{s.reputation} | {unlock} | Bottleneck {weak} {stats[weak]} | Tier bonus {tier[2] if tier[2] else 'None'}"
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/rocky")
def rocky(channel:str,uid:str="",name:str="Citizen",provider:str="twitch"):
    sayings=[
        "A strong society grows one harvest at a time.",
        "Never underestimate a farmer.",
        "A delivery duck always remembers.",
        "Respect the Siro, but do not invite it inside.",
        "Development without food is expensive architecture.",
        "Sometimes the rock chooses you.",
        "May Rocky's wisdom guide you."
    ]
    return out(f"🪨 Rocky's Wisdom for {clean(name)}: {random.choice(sayings)}")

@app.get("/api/v1/siro")
@game_transaction
def siro(channel:str):
    with SessionLocal() as db:
        s=society(db,channel);w=world(db,channel);resolve_expired_event(db,s,w)
        if w.active_event=="siro":
            return out(f"☣️ SIRO ALERT | Containment {w.event_progress}/{w.event_goal}. Use !research.")
        return out("☣️ Siro report: levels are manageable. Sensors remain active around New Eridian.")

def _player_summary(db,channel,p):
    ids=db.execute(select(Identity).where(Identity.channel_id==channel,Identity.canonical_uid==p.twitch_uid)).scalars().all()
    kinds=sorted({i.provider for i in ids}) or (["discord"] if p.twitch_uid.startswith("discord:") else ["twitch"])
    xp=sum(getattr(p,f) for f in ("farm_xp","mining_xp","industry_xp","research_xp","delivery_xp","explore_xp","environmental_xp","fabrication_xp","infrastructure_xp","commerce_xp","cooking_xp","medicine_xp","emergency_xp"))
    return {"uid":p.twitch_uid,"name":p.display_name,"accounts":"+".join(kinds),"sc":p.sc,"contribution":p.contribution,"actions":p.actions,"xp":xp,
            "created":as_utc(p.created_at).strftime("%Y-%m-%d"),"last_seen":as_utc(p.last_seen).strftime("%Y-%m-%d %H:%M")}

@app.get("/api/v1/admin/duplicates")
def admin_duplicates(channel:str="",key:str=""):
    """Characters that share a name (ignoring case and [tags]): usually a Twitch and a Discord character never linked."""
    if not valid_admin_key(key):return JSONResponse({"ok":False,"error":"Invalid game-admin key."},status_code=403)
    channel=channel or main.DISCORD_WORLD_ID   # read now: a world merge can change the main world while running
    from ..autonomy import clean_name
    with SessionLocal() as db:
        groups={}
        for p in db.execute(select(Player).where(Player.channel_id==channel)).scalars().all():
            groups.setdefault(clean_name(p.display_name).strip().lower(),[]).append(p)
        dupes=[{"name":ps[0].display_name,"characters":[_player_summary(db,channel,p) for p in sorted(ps,key=lambda x:-x.actions)]} for k,ps in groups.items() if len(ps)>1]
        return JSONResponse({"ok":True,"channel":channel,"duplicates":dupes,
                             "how_to_merge":"/api/v1/admin/merge?channel=CHANNEL&keep=UID&merge=UID&key=KEY (add &confirm=1 to apply)"})

@app.get("/api/v1/admin/merge")
@game_transaction
def admin_merge(keep:str,merge:str,channel:str="",key:str="",confirm:int=0):
    """Merge one character into another with the same code as /link: stats, XP, items, skills, homes, businesses,
    achievements, queues and Seedling life are combined, and both sets of Twitch/Discord IDs point at the kept character.
    Without confirm=1 it only shows what the merged character would look like."""
    if not valid_admin_key(key):return JSONResponse({"ok":False,"error":"Invalid game-admin key."},status_code=403)
    channel=channel or main.DISCORD_WORLD_ID
    me=main
    with SessionLocal() as db:
        try:pair=main.force_merge.load(me,db,channel,keep,merge)    # the preview-and-apply core the owner's /menu Force merge button shares
        except main.force_merge.Refused as e:return JSONResponse({"ok":False,"error":e.error},status_code=e.status)
        if not confirm:
            return JSONResponse({"ok":True,"preview":True,"keep":pair.before[0],"merge":pair.before[1],"after":{**pair.combined,"uid":keep,"name":pair.keep.display_name},
                                 "apply":"repeat this URL with &confirm=1"})
        return JSONResponse({"ok":True,"merged":True,**main.force_merge.apply(me,db,channel,pair,"game admin")})

@app.get("/api/v1/admin/event/{event}/{state}")
@game_transaction
def admin_event(event:str,state:str,channel:str,level:int=0,key:str=""):
    if not valid_mod_key(key):
        return out("⛔ Invalid game-admin key.")
    if not twitch_owner_ok(key,level):
        return out(OWNER_ONLY_TEXT)
    if event not in EVENTS or state not in {"on","off"}:
        return out("⛔ Unknown event.")
    with SessionLocal() as db:
        s=society(db,channel);w=world(db,channel);resolve_expired_event(db,s,w)
        if state=="on":
            if w.active_event:return out("⛔ An event is already active. Stop it before starting another.")
            result=start_event(db,w,event,"StreamElements moderator");audit_moderator(db,channel,"StreamElements level "+str(level),"eventstart",event);return out(result)
        result=cancel_event(db,w,"StreamElements moderator");audit_moderator(db,channel,"StreamElements level "+str(level),"eventstop",event);return out(result)

@app.get("/api/v1/admin/day/next")
@game_transaction
def next_day(channel:str,level:int=0,key:str=""):
    if not twitch_owner_ok(key,level):
        return out(OWNER_ONLY_TEXT)
    with SessionLocal() as db:
        s=society(db,channel);clock=db.execute(select(WorldClock).where(WorldClock.channel_id==channel)).scalar_one_or_none()
        if not clock:clock=WorldClock(channel_id=channel,anchor_at=main.now(),anchor_day=s.day);db.add(clock)
        clock.anchor_at=as_utc(clock.anchor_at)-timedelta(seconds=AVESTA_DAY_SECONDS)
        db.commit();state=world_clock(db,channel,s);audit_moderator(db,channel,"StreamElements level "+str(level),"daynext",f"day {state['day']}")
        return out(f"🌅 Avesta Day {state['day']} begins in New Eridian.")
