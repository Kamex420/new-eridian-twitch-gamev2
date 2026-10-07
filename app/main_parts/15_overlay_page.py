# app/main.py, part 15: overlay page
# The stream overlay page (/overlay): one large HTML/JS template.
# Runs inside app.main's namespace, after the parts before it (see main.py). Not a module of its own.

@app.get("/overlay",response_class=HTMLResponse)
def overlay_page(panel:str="",channel:str="new-eridian"):
    # Preserve every previously shared /overlay?channel=...&panel=... URL, but
    # serve the smaller OBS-only document instead of loading the full dashboard.
    # This prevents OBS transforms and Windows display scaling from activating
    # the dashboard's mobile stack inside an individual Browser Source.
    selected=(panel or "").lower().strip()
    if selected in {"society","today","event","ops","activity","telemetry","signal","alerts","ticker","leaders","working","join"}:
        return standalone_obs_panel(selected,channel)
    from . import stream_overlay
    return stream_overlay.themed(r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>New Eridian v2 · Stream Telemetry</title>
<style>
:root{
  color-scheme:dark;
  --bg:rgba(7,10,31,.88);
  --bg2:rgba(15,12,43,.93);
  --line:rgba(147,154,255,.34);
  --line2:rgba(89,218,255,.30);
  --text:#fffaf0;
  --muted:#aca9c9;
  --ivory:#fff8e8;
  --green:#7ee3b0;
  --green2:#b8f4d0;
  --violet:#bd91ff;
  --cyan:#70ddff;
  --amber:#ffd27a;
  --danger:#ff7484;
  --shadow:0 18px 52px rgba(0,0,0,.48),0 0 28px rgba(75,54,183,.12);
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}
*{box-sizing:border-box}
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent;color:var(--text)}
body{padding:26px}
.hidden{display:none!important}

.hud{position:relative;width:100%;height:100%;isolation:isolate}
.hud:before{
  content:"";position:absolute;inset:-26px;z-index:-2;pointer-events:none;opacity:.50;
  background:
    radial-gradient(circle at 5% 8%,rgba(65,143,255,.25) 0 3%,rgba(44,73,189,.14) 8%,transparent 18%),
    radial-gradient(ellipse at 79% 13%,rgba(210,126,255,.18),rgba(100,70,225,.12) 12%,transparent 28%),
    radial-gradient(circle at 18% 42%,rgba(65,166,255,.10) 0 1px,transparent 2px),
    radial-gradient(circle at 67% 33%,rgba(255,247,225,.18) 0 1px,transparent 2px),
    linear-gradient(180deg,rgba(5,7,31,.17),rgba(14,8,47,.05) 55%,rgba(7,10,31,.22));
  background-size:auto,auto,113px 89px,149px 127px,auto;
}
.hud:after{
  content:"";position:absolute;left:-26px;right:-26px;bottom:-26px;height:13%;z-index:-1;pointer-events:none;
  background:linear-gradient(155deg,transparent 0 10%,rgba(12,13,35,.44) 11% 22%,transparent 23%),linear-gradient(25deg,rgba(7,9,25,.55),rgba(30,22,65,.26));
  clip-path:polygon(0 52%,8% 39%,15% 58%,24% 34%,34% 69%,46% 43%,56% 65%,68% 39%,78% 57%,88% 28%,100% 48%,100% 100%,0 100%);
}
.card{
  position:absolute;
  overflow:hidden;
  background:
    radial-gradient(circle at 90% 0,rgba(125,72,220,.13),transparent 42%),
    linear-gradient(145deg,rgba(8,13,39,.94),rgba(24,15,54,.91));
  border:1px solid var(--line);
  border-radius:16px;
  box-shadow:var(--shadow);
  backdrop-filter:blur(12px);
}
.card:before{
  content:"";
  position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(120deg,rgba(255,248,226,.055),transparent 35%);
}
.eyebrow{
  font-size:10px;font-weight:800;letter-spacing:.20em;text-transform:uppercase;
  color:var(--green2);
}
.muted{color:var(--muted)}
.mini{font-size:11px}
.dot{
  display:inline-block;width:7px;height:7px;border-radius:50%;
  background:var(--green);box-shadow:0 0 12px rgba(152,215,155,.7);
  margin-right:7px;vertical-align:1px
}

/* Society command card */
.society{left:0;top:0;width:410px;padding:18px 20px 17px}
.society-title{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin-top:5px}
.society h1{
  font-family:Georgia,"Times New Roman",serif;font-size:31px;line-height:1;margin:0;letter-spacing:.025em;
  color:var(--ivory);text-shadow:0 0 8px rgba(255,248,232,.55),0 0 24px rgba(181,124,255,.32)
}
.tier-chip{
  border:1px solid var(--line2);background:rgba(142,211,150,.08);
  color:var(--green2);font-size:11px;font-weight:800;padding:5px 8px;border-radius:999px
}
.world-line{display:flex;gap:9px;align-items:center;margin-top:10px;color:#d7d5df;font-size:12px;flex-wrap:wrap}
.sep{opacity:.35}
.condition{margin-top:11px;padding-top:10px;border-top:1px solid rgba(255,255,255,.07)}
.condition strong{font-size:13px}
.condition p{margin:3px 0 0;color:var(--muted);font-size:11px;line-height:1.35}
.priority{margin-top:12px}
.row-head{display:flex;justify-content:space-between;gap:12px;align-items:center;font-size:11px}
.row-head strong{font-size:12px}
.progress{
  height:7px;margin-top:7px;background:rgba(255,255,255,.07);
  border-radius:999px;overflow:hidden
}
.progress i{
  display:block;height:100%;width:0;
  background:linear-gradient(90deg,var(--green),var(--violet));
  border-radius:999px;transition:width .55s ease
}

/* Today's goals / v6 engagement systems */
.today{left:0;bottom:122px;width:410px;padding:16px 18px}
.today-grid{display:grid;grid-template-columns:1fr;gap:9px;margin-top:9px}
.today .module{background:rgba(8,11,36,.40);border-color:rgba(130,155,255,.13)}
.directive-title{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.directive-title strong{font-size:12px;color:var(--ivory)}
.directive-title span{font-size:10px;color:var(--cyan);font-weight:800}
.system-pulse{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:9px}
.pulse-stat{padding:7px 8px;border:1px solid rgba(112,221,255,.10);border-radius:8px;background:rgba(4,8,29,.28)}
.pulse-stat b{display:block;font-size:13px;color:var(--ivory)}
.pulse-stat small{display:block;margin-top:2px;color:var(--muted);font-size:8px;text-transform:uppercase;letter-spacing:.08em}
.system-detail{margin-top:7px;color:var(--muted);font-size:9px;line-height:1.3}
.aftermath{margin-top:9px;padding-top:9px;border-top:1px solid rgba(255,255,255,.07);font-size:10px;line-height:1.35;color:var(--muted)}
.aftermath.good b{color:var(--green2)}
.aftermath.bad b{color:#ff9aa6}
.brand-motto{margin-top:10px;color:#8f86bb;font:600 11px/1.2 Georgia,"Times New Roman",serif;letter-spacing:.05em}

/* Center live event */
.event{
  top:0;left:50%;transform:translateX(-50%);
  width:620px;padding:17px 20px 16px;border-color:rgba(255,116,132,.36)
}
.event .eyebrow{color:#ff9aa6}
.event-title{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-top:4px}
.event-title h2{font-size:21px;margin:0}
.timer{font-size:19px;font-weight:850;color:#fff}
.event-meta{display:flex;gap:16px;flex-wrap:wrap;margin-top:10px;font-size:11px;color:#cac8d3}
.event-meta b{color:#fff}
.event .progress i{background:linear-gradient(90deg,var(--danger),var(--amber))}
.leaders{margin-top:9px;font-size:10px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* Operations card */
.ops{right:0;top:0;width:505px;padding:17px 19px}
.ops-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px}
.module{padding:11px 12px;border:1px solid rgba(255,255,255,.07);background:rgba(7,9,13,.22);border-radius:11px}
.module h3{font-size:12px;margin:0 0 4px}
.module .value{font-size:11px;color:var(--muted);line-height:1.35}
.module .pct{font-size:11px;font-weight:800;color:#fff}
.module .progress{height:5px;margin-top:8px}
.story-tracks{
  display:flex;
  flex-direction:column;
  gap:8px;
  margin-top:9px
}
.story-path{min-width:0}
.story-path-head{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:8px;
  margin-bottom:4px;
  font-size:9px;
  line-height:1.2
}
.story-path-name{
  color:#d9d8e2;
  font-weight:750;
  min-width:0;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap
}
.story-path-meta{
  color:var(--muted);
  white-space:nowrap
}
.story-path.leader .story-path-name{color:var(--green2)}
.story-path.leader .story-path-meta{color:var(--green2)}
.story-leader-tag{
  display:inline-block;
  margin-left:5px;
  padding:2px 5px;
  border:1px solid rgba(152,215,155,.30);
  border-radius:999px;
  background:rgba(152,215,155,.08);
  color:var(--green2);
  font-size:7px;
  font-weight:850;
  letter-spacing:.08em;
  vertical-align:1px
}
.story-path-bar{
  height:5px;
  overflow:hidden;
  border-radius:999px;
  background:rgba(255,255,255,.07)
}
.story-path-bar i{
  display:block;
  height:100%;
  width:0;
  border-radius:999px;
  background:var(--cyan);
  transition:width .45s ease
}
.story-path.leader .story-path-bar i{
  background:linear-gradient(90deg,var(--green),var(--green2))
}
.story-summary{
  margin-top:7px;
  font-size:8px;
  color:var(--muted);
  line-height:1.3
}
.market-hot{color:var(--amber)!important}
.rumor{
  margin-top:10px;border-top:1px solid rgba(255,255,255,.07);padding-top:9px;
  font-size:10px;line-height:1.35;color:var(--muted)
}

/* Activity feed */
.activity{
  right:0;bottom:122px;width:505px;padding:15px 17px 14px;
  transition:opacity .25s,transform .25s
}
.activity-head{display:flex;justify-content:space-between;align-items:center}
.activity-list{margin-top:8px;display:flex;flex-direction:column;gap:7px}
.activity-item{
  display:grid;
  grid-template-columns:7px minmax(0,1fr);
  gap:9px;
  align-items:start;
  padding:7px 8px;
  background:rgba(8,10,14,.24);
  border-radius:9px;
  min-width:0;
  overflow:hidden
}
.activity-item:first-child{background:rgba(152,215,155,.07)}
.pulse{width:7px;height:7px;border-radius:50%;background:var(--violet);margin-top:5px}
.activity-item:first-child .pulse{background:var(--green);box-shadow:0 0 9px rgba(152,215,155,.6)}
.activity-copy{
  min-width:0;
  max-width:100%;
  overflow:hidden
}
.activity-top{
  display:flex;
  align-items:baseline;
  flex-wrap:wrap;
  gap:3px 8px;
  min-width:0;
  max-width:100%
}
.activity-who{
  min-width:0;
  max-width:100%;
  font-size:10px;
  font-weight:800;
  color:#fff;
  overflow-wrap:anywhere;
  word-break:break-word
}
.activity-action{
  min-width:0;
  max-width:100%;
  font-size:9px;
  color:var(--cyan);
  text-transform:uppercase;
  letter-spacing:.08em;
  margin-left:0;
  overflow-wrap:anywhere;
  word-break:break-word
}
.activity-age{
  margin-left:auto;font-size:9px;color:var(--muted);white-space:nowrap
}
.activity-msg{
  min-width:0;
  max-width:100%;
  font-size:10px;
  color:var(--muted);
  line-height:1.35;
  margin-top:3px;
  white-space:normal;
  overflow-wrap:anywhere;
  word-break:break-word;
  overflow:hidden;
  white-space:nowrap;
  text-overflow:ellipsis;
  overflow:hidden
}

/* Bottom telemetry rail */
.telemetry{
  left:0;right:0;bottom:0;height:102px;
  display:grid;grid-template-columns:repeat(6,minmax(0,1fr)) 115px 165px;
  gap:1px;padding:0;overflow:hidden
}
.stat,.population,.next{
  position:relative;padding:13px 14px;background:rgba(9,11,15,.24)
}
.stat small,.population small,.next small{
  display:block;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.12em
}
.stat strong,.population strong,.next strong{display:block;font-size:21px;margin-top:5px;line-height:1}
.stat .tiny{font-size:9px;color:var(--muted);margin-top:6px}
.stat .progress{height:4px;margin-top:6px}
.population strong{font-size:24px;color:var(--cyan)}
.next strong{font-size:16px;color:var(--green2);margin-top:7px}
.next .tiny{font-size:9px;color:var(--muted);margin-top:7px;line-height:1.3}

/* Connection state / setup */
.signal{
  position:absolute;left:0;bottom:116px;font-size:9px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--muted);padding:6px 9px;background:rgba(12,14,18,.6);border-radius:8px
}
.signal.bad .dot{background:var(--danger);box-shadow:0 0 10px rgba(255,116,132,.6)}
.setup{
  position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
  width:520px;padding:24px;background:var(--bg2);border:1px solid var(--line);
  border-radius:16px;box-shadow:var(--shadow)
}
.setup h1{font-size:24px;margin:6px 0 12px}
.setup input{
  width:100%;padding:12px 13px;border:1px solid rgba(255,255,255,.12);
  border-radius:9px;background:#11131a;color:white;font-size:15px;outline:none
}
.setup button{
  margin-top:10px;padding:11px 15px;border:0;border-radius:9px;
  background:linear-gradient(90deg,var(--green),var(--violet));color:#14151a;font-weight:850;cursor:pointer
}

@media(max-width:1450px){
  body{padding:18px}
  .society{width:350px}
  .today{width:350px;bottom:108px}
  .ops,.activity{width:430px}
  .event{width:520px}
  .telemetry{grid-template-columns:repeat(6,minmax(0,1fr)) 95px 135px;height:92px}
  .activity{bottom:108px}
  .signal{bottom:102px}
}

/* Layout editor ---------------------------------------------------------- */
.panel-hidden{display:none!important}
.layout-edit .movable{
  cursor:grab;
  outline:1px dashed rgba(152,215,155,.46);
  outline-offset:3px;
}
.layout-edit .movable.dragging{
  cursor:grabbing;
  outline-color:var(--green2);
  box-shadow:0 18px 52px rgba(0,0,0,.5),0 0 0 2px rgba(152,215,155,.12);
  user-select:none;
}
.drag-grip{
  display:none;
  position:absolute;
  right:9px;top:8px;
  z-index:4;
  min-width:30px;height:28px;
  align-items:center;justify-content:center;
  border:1px solid rgba(255,255,255,.12);
  border-radius:7px;
  background:rgba(8,10,14,.72);
  color:var(--muted);
  font-size:15px;
  line-height:1;
  pointer-events:none;
}
.layout-edit .movable .drag-grip{display:flex}

.layout-launch{
  display:none;
  position:absolute;
  right:0;bottom:116px;
  z-index:1000;
  border:1px solid var(--line);
  border-radius:10px;
  background:rgba(18,20,27,.92);
  color:#fff;
  padding:9px 12px;
  font:700 11px/1 system-ui,sans-serif;
  letter-spacing:.04em;
  cursor:pointer;
}
.editor-enabled .layout-launch{display:block}

.layout-panel{
  display:none;
  position:absolute;
  right:0;bottom:164px;
  z-index:1001;
  width:286px;
  padding:14px;
  border:1px solid var(--line);
  border-radius:14px;
  background:rgba(18,20,27,.97);
  box-shadow:var(--shadow);
}
.layout-panel.open{display:block}
.layout-panel h3{margin:0 0 4px;font-size:14px}
.layout-panel p{margin:0 0 11px;color:var(--muted);font-size:10px;line-height:1.35}
.layout-actions{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:10px}
.layout-actions button,.panel-toggle{
  border:1px solid rgba(255,255,255,.11);
  border-radius:8px;
  background:rgba(255,255,255,.055);
  color:#fff;
  min-height:34px;
  padding:7px 9px;
  font:700 10px/1 system-ui,sans-serif;
  cursor:pointer;
}
.layout-actions button:hover,.panel-toggle:hover{background:rgba(255,255,255,.10)}
.panel-toggle-row{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:8px;
  padding:6px 0;
  border-top:1px solid rgba(255,255,255,.06);
}
.panel-toggle-row span{font-size:10px;color:#d8d7df}
.panel-toggle[aria-pressed="true"]{color:var(--green2);border-color:rgba(152,215,155,.35)}
.panel-toggle[aria-pressed="false"]{color:#ff9aa6;border-color:rgba(255,116,132,.28)}
.edit-note{
  margin-top:10px!important;
  padding-top:9px;
  border-top:1px solid rgba(255,255,255,.07);
}

/* When a saved free-position layout is restored, these classes let JS
   override the original anchor rules without fighting right/bottom/transform. */
.free-position{
  right:auto!important;
  bottom:auto!important;
  transform:none!important;
}

/* Editor must remain usable at common OBS canvas sizes. */
@media(max-width:1450px){
  .layout-launch{bottom:102px}
  .layout-panel{bottom:146px}
}


/* Single-panel OBS source mode ------------------------------------------ */
/* Use ?panel=society, ?panel=ops, etc. to make each card its own OBS
   Browser Source so OBS can move/resize every panel independently. */
body.single-panel{
  padding:0!important;
  overflow:hidden!important;
  background:transparent!important;
}
body.single-panel .hud{
  width:100%;
  height:100%;
}
body.single-panel .movable[data-panel]{
  display:none!important;
}
body.single-panel .movable[data-panel].panel-selected{
  display:block!important;
  position:absolute!important;
  left:0!important;
  top:0!important;
  right:auto!important;
  bottom:auto!important;
  transform:none!important;
  margin:0!important;
  max-width:100%!important;
}
body.single-panel .panel-selected.society{width:min(410px,100%)!important}
body.single-panel .panel-selected.today{width:min(410px,100%)!important}
body.single-panel .panel-selected.event{width:min(620px,100%)!important}
body.single-panel .panel-selected.ops{width:min(505px,100%)!important}
body.single-panel .panel-selected.activity{width:min(505px,100%)!important}
body.single-panel .panel-selected.telemetry{
  width:100%!important;
  height:auto!important;
  grid-template-columns:repeat(6,minmax(0,1fr)) 115px 165px!important
}
body.single-panel .panel-selected.signal{
  width:auto!important;
  display:inline-block!important
}
body.single-panel .layout-launch,
body.single-panel .layout-panel{
  display:none!important
}
body.single-panel .drag-grip{display:none!important}

/* Compact individual source variants */
body.single-panel.panel-telemetry .hud{min-height:102px}
body.single-panel.panel-signal .hud{min-height:36px}

/* Mobile dashboard ------------------------------------------------------- */
/* On phones, the overlay becomes a normal stacked dashboard instead of
   shrinking the 16:9 OBS layout. Saved desktop positions are ignored. */
@media(max-width:820px){
  html,body{
    width:100%;
    min-height:100%;
    height:auto;
    overflow-x:hidden;
    overflow-y:auto;
    background:#0c0e12;
  }
  body{
    padding:10px;
  }
  .hud{
    position:relative;
    width:100%;
    height:auto;
    display:flex;
    flex-direction:column;
    gap:10px;
    min-width:0;
  }

  .card,
  .society,
  .today,
  .event,
  .ops,
  .activity,
  .telemetry,
  .signal{
    position:relative!important;
    left:auto!important;
    right:auto!important;
    top:auto!important;
    bottom:auto!important;
    transform:none!important;
    width:100%!important;
    max-width:100%!important;
    height:auto!important;
    min-width:0;
    margin:0;
  }

  .card{
    border-radius:13px;
    box-shadow:0 10px 28px rgba(0,0,0,.32);
  }

  .society{order:1;padding:16px}
  .today{order:2;padding:15px 16px}
  .event{order:3;padding:15px 16px}
  .ops{order:4;padding:15px}
  .activity{order:5;padding:14px}
  .telemetry{
    order:6;
    display:grid;
    grid-template-columns:repeat(2,minmax(0,1fr))!important;
    gap:1px;
    overflow:hidden;
    padding:0;
  }
  .signal{
    order:7;
    display:block;
    padding:8px 10px;
    border:1px solid rgba(255,255,255,.07);
    background:rgba(12,14,18,.78);
    border-radius:9px;
  }

  .society h1{font-size:24px}
  .society-title{align-items:center}
  .tier-chip{font-size:10px}
  .world-line{
    font-size:11px;
    gap:6px;
  }

  .event-title{
    align-items:flex-start;
    gap:10px;
  }
  .event-title h2{
    font-size:18px;
    min-width:0;
    overflow-wrap:anywhere;
  }
  .timer{font-size:16px;white-space:nowrap}
  .event-meta{
    gap:8px 12px;
    font-size:10px;
  }
  .leaders{
    white-space:normal;
    overflow:visible;
    text-overflow:clip;
    line-height:1.4;
  }

  .ops-grid{
    grid-template-columns:1fr;
    gap:8px;
  }
  .module{
    min-width:0;
    padding:10px 11px;
  }
  .story-path-head{
    font-size:10px;
  }
  .story-path-name{
    white-space:normal;
    overflow:visible;
    text-overflow:clip;
  }
  .story-summary{
    font-size:9px;
  }

  .module .value,
  .rumor,
  .condition p,
  .next .tiny{
    white-space:normal;
    overflow:visible;
    text-overflow:clip;
    overflow-wrap:anywhere;
    word-break:normal;
  }

  .activity-msg{
    white-space:normal;
    overflow:hidden;
    text-overflow:clip;
    overflow-wrap:anywhere;
    word-break:break-word;
    display:-webkit-box;
    -webkit-box-orient:vertical;
    -webkit-line-clamp:2;
    line-clamp:2;
  }

  .activity-list{gap:6px}
  .activity-item{
    grid-template-columns:7px minmax(0,1fr);
    padding:8px;
  }
  .activity-action{
    display:block;
    margin:3px 0 0;
  }

  .stat,
  .population,
  .next{
    min-width:0;
    padding:11px 10px;
  }
  .stat strong,
  .population strong{
    font-size:18px;
  }
  .next strong{font-size:14px}
  .stat .tiny,
  .population .tiny,
  .next .tiny{
    font-size:8px;
  }

  /* Layout editing stays available, but mobile uses automatic stacking.
     Visibility toggles still work; free-position dragging is desktop-only. */
  .layout-launch{
    position:relative!important;
    order:8;
    display:none;
    left:auto!important;
    right:auto!important;
    top:auto!important;
    bottom:auto!important;
    width:100%;
    min-height:44px;
    margin:0;
    padding:11px 12px;
  }
  .editor-enabled .layout-launch{display:block}

  .layout-panel{
    position:relative!important;
    order:9;
    left:auto!important;
    right:auto!important;
    top:auto!important;
    bottom:auto!important;
    width:100%;
    max-width:100%;
    margin:0;
    padding:14px;
  }

  .layout-actions{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:8px;
  }
  .layout-actions button,
  .panel-toggle{
    min-height:44px;
    font-size:11px;
  }
  .panel-toggle-row{
    min-height:52px;
  }

  /* Do not show drag handles in auto-stacked mobile mode. */
  .layout-edit .movable{cursor:default;outline:none}
  .layout-edit .movable .drag-grip{display:none}

  .setup{
    position:relative;
    left:auto;
    top:auto;
    transform:none;
    width:100%;
    max-width:100%;
    margin:16px 0;
    padding:18px;
  }
  .setup h1{font-size:21px}
  .setup input,
  .setup button{
    min-height:44px;
    font-size:16px;
  }
}

@media(max-width:460px){
  body{padding:8px}
  .hud{gap:8px}
  .telemetry{
    grid-template-columns:1fr!important;
  }
  .society-title{
    align-items:flex-start;
    flex-direction:column;
    gap:8px;
  }
  .world-line{
    flex-direction:column;
    align-items:flex-start;
  }
  .world-line .sep{display:none}
  .event-title{
    flex-direction:column;
  }
  .layout-actions{
    grid-template-columns:1fr;
  }
}

/* OBS-safe final override for the legacy single-panel telemetry URL.
   Keep it after every mobile rule so transformed Browser Sources cannot turn
   the rail into a clipped one-column stack. */
body.single-panel.panel-telemetry .telemetry.panel-selected{
  width:100%!important;
  height:150px!important;
  display:grid!important;
  grid-template-columns:repeat(6,minmax(0,1fr)) minmax(72px,.75fr) minmax(105px,1.1fr)!important;
}
</style>
</head>
<body>
<main id="hud" class="hud hidden">
  <section class="card society movable" data-panel="society"><span class="drag-grip">⠿</span>
    <div class="eyebrow"><span class="dot"></span>SOCIETY TELEMETRY</div>
    <div class="society-title">
      <h1>NEW ERIDIAN</h1>
      <span id="tier-chip" class="tier-chip">CONNECTING</span>
    </div>
    <div class="world-line">
      <span>Avesta Day <b id="day">—</b></span><span class="sep">•</span>
      <span id="phase">—</span><span class="sep">•</span>
      <span><b id="active-players">0</b> active</span>
    </div>
    <div class="condition">
      <strong id="condition">Waiting for world signal…</strong>
      <p id="condition-text"></p>
    </div>
    <div class="brand-motto">May Rocky's wisdom guide you…</div>
  </section>

  <section class="card today movable" data-panel="today"><span class="drag-grip">⠿</span>
    <div class="eyebrow">✦ TODAY IN NEW ERIDIAN</div>
    <div class="today-grid">
      <div class="module">
        <div class="directive-title">
          <strong id="directive-name">Loading directive…</strong>
          <span id="directive-progress">0/0</span>
        </div>
        <div id="directive-description" class="value"></div>
        <div class="progress"><i id="directive-bar"></i></div>
        <div id="directive-skills" class="value" style="margin-top:6px"></div>
      </div>
    </div>
    <div class="system-pulse">
      <div class="pulse-stat"><b id="variety-count">0</b><small>Variety done</small></div>
      <div class="pulse-stat"><b id="lore-count">0/0</b><small>Lore found</small></div>
      <div class="pulse-stat"><b id="fleet-count">0</b><small>Fleet assigned</small></div>
    </div>
    <div id="system-detail" class="system-detail"></div>
    <div id="aftermath" class="aftermath hidden"></div>
  </section>

  <section id="event" class="card event movable hidden" data-panel="event"><span class="drag-grip">⠿</span>
    <div class="eyebrow">⚠ LIVE SOCIETY EVENT</div>
    <div class="event-title">
      <h2 id="event-name">Event</h2>
      <div id="event-time" class="timer">00:00</div>
    </div>
    <div class="progress"><i id="event-bar"></i></div>
    <div class="event-meta">
      <span>Progress <b id="event-progress">0/0</b></span>
      <span>Primary <b id="event-primary">—</b></span>
      <span>Support <b id="event-support">—</b></span>
    </div>
    <div id="event-leaders" class="leaders"></div>
  </section>

  <section class="card ops movable" data-panel="ops"><span class="drag-grip">⠿</span>
    <div class="eyebrow">AVESTA OPERATIONS</div>
    <div class="ops-grid">
      <div class="module">
        <div class="row-head"><h3>🏗️ Society Project</h3><span id="project-pct" class="pct">0%</span></div>
        <div id="project-name" class="value">Loading…</div>
        <div class="progress"><i id="project-bar"></i></div>
        <div id="project-skills" class="value" style="margin-top:6px"></div>
      </div>
      <div class="module">
        <div class="row-head"><h3>📖 Weekly Story</h3><span id="story-pct" class="pct">0%</span></div>
        <div id="story-name" class="value">Loading…</div>
        <div class="progress"><i id="story-bar"></i></div>
        <div id="story-tracks" class="story-tracks"></div>
        <div id="story-summary" class="story-summary"></div>
      </div>
      <div class="module">
        <h3>💰 Market Signal</h3>
        <div id="market-primary" class="value market-hot">Loading…</div>
        <div id="market-secondary" class="value"></div>
      </div>
      <div class="module">
        <h3>📡 Society Pressure</h3>
        <div id="pressure" class="value">Scanning…</div>
      </div>
    </div>
    <div id="rumor" class="rumor"></div>
  </section>

  <section class="card activity movable" data-panel="activity"><span class="drag-grip">⠿</span>
    <div class="activity-head">
      <div class="eyebrow">RECENT CITIZEN ACTIVITY</div>
      <span id="activity-count" class="mini muted">—</span>
    </div>
    <div id="activity-list" class="activity-list"></div>
  </section>

  <section id="telemetry" class="card telemetry movable" data-panel="telemetry"><span class="drag-grip">⠿</span></section>

  <div id="signal" class="signal movable" data-panel="signal"><span class="drag-grip">⠿</span><span class="dot"></span><span id="signal-text">Connecting to New Eridian…</span></div>

  <button id="layout-launch" class="layout-launch" type="button">⚙ EDIT OVERLAY</button>
  <aside id="layout-panel" class="layout-panel" aria-label="Overlay layout editor">
    <h3>Overlay Layout</h3>
    <p>Unlock the layout, then drag any visible panel. Changes are saved automatically in this browser source.</p>
    <div class="layout-actions">
      <button id="layout-lock" type="button">🔓 Unlock</button>
      <button id="layout-reset" type="button">↺ Reset layout</button>
      <button id="layout-close" type="button">Done</button>
    </div>
    <div id="panel-toggles"></div>
    <p class="edit-note">OBS/Desktop: right-click the Browser Source → <b>Interact</b> to move panels. On mobile the dashboard auto-stacks to fit the screen; visibility toggles still work.</p>
  </aside>
</main>

<section id="setup" class="setup hidden">
  <div class="eyebrow">NEW ERIDIAN v2 · OBS SETUP</div>
  <h1>Connect society telemetry</h1>
  <div class="muted mini">Enter the Twitch channel ID used by the game.</div>
  <input id="channel" placeholder="Example: new-eridian">
  <button id="connect">Open overlay</button>
</section>

<script>
const $=s=>document.querySelector(s);
const params=new URLSearchParams(location.search);
const channel=params.get('channel');
const panelMode=(params.get('panel')||'').toLowerCase().trim();
const VALID_PANELS=new Set(['society','today','event','ops','activity','telemetry','signal']);
const statMeta={
  food:['🌾','Food'],materials:['⛏️','Materials'],development:['⚙️','Development'],
  knowledge:['🔬','Knowledge'],treasury:['🪙','Treasury'],reputation:['⭐','Reputation']
};
let lastStamp='';

function esc(v){
  return String(v==null?'':v).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}
function fmtTime(n){
  n=Math.max(0,Number(n)||0);
  const m=Math.floor(n/60),s=n%60;
  return m+':'+String(s).padStart(2,'0');
}
function pct(v,max){return Math.max(0,Math.min(100,(Number(v)||0)/Math.max(1,Number(max)||1)*100))}
function setBar(id,value){$(id).style.width=Math.max(0,Math.min(100,Number(value)||0))+'%'}
function ago(iso){
  const sec=Math.max(0,Math.floor((Date.now()-new Date(iso).getTime())/1000));
  if(!Number.isFinite(sec))return 'time unavailable';
  if(sec<10)return 'just now';
  if(sec<60)return sec+'s ago';
  if(sec<3600)return Math.floor(sec/60)+'m ago';
  if(sec<86400)return Math.floor(sec/3600)+'h ago';
  return Math.floor(sec/86400)+'d ago';
}

function renderStats(d){
  const target=d.tier_target||1;
  const cards=Object.entries(statMeta).map(([key,[icon,label]])=>{
    const value=d.stats&&d.stats[key]!=null?d.stats[key]:0;
    return `<div class="stat">
      <small>${icon} ${label}</small>
      <strong>${Number(value).toLocaleString()}</strong>
      <div class="tiny">${d.next_tier?`${Math.min(value,target).toLocaleString()} / ${Number(target).toLocaleString()} to ${esc(d.next_tier)}`:'Maximum tier'}</div>
      <div class="progress"><i style="width:${d.next_tier?pct(value,target):100}%"></i></div>
    </div>`;
  }).join('');
  $('#telemetry').innerHTML=cards+
    `<div class="population"><small>👥 Population</small><strong>${Number(d.stats&&d.stats.population||0).toLocaleString()}</strong><div class="tiny muted">${Number(d.active_players||0)} active / 30m</div></div>`+
    `<div class="next"><small>Society Tier</small><strong>${esc(d.tier||'—')}</strong><div class="tiny">${d.next_tier?`Next: ${esc(d.next_tier)}<br>${Number(d.tier_target).toLocaleString()} each`:'Regional Hub reached'}<br>Tier bonus: ${Number(d.tier_bonus||0)?('+'+Number(d.tier_bonus||0)+' SC on success'):'None'}</div></div>`;
}

function plainSentence(msg){
  // The first real sentence of a reply: no emoji, markup, bare stats or ALL-CAPS headers.
  for(let part of String(msg||'').split(/\s*(?:\n| \| | · )\s*/)){
    part=part.replace(/[*_`]/g,'').replace(/^[^A-Za-z0-9(]+/,'').trim();
    if(!part||/^[+\-−\d]/.test(part)||(part===part.toUpperCase()&&!/\d/.test(part)))continue;
    part=part.split(/(?<=[.!?])\s/)[0];return part.length>90?part.slice(0,88)+'…':part}
  return ''}
function conciseActivityMessage(x){
  const msg=String(x&&x.message||'').replace(/\s+/g,' ').trim();
  if(!msg)return 'Action completed';

  // Keep the useful mechanical result and drop long flavor/lore sentences.
  const signed=[];
  const rewardRe=/([+-]\d+\s+(?:[A-Za-z][A-Za-z /_-]*?))(?=(?:[,.;]|\/|\s+[+-]\d+|$))/g;
  let m;
  while((m=rewardRe.exec(msg))!==null && signed.length<4){
    let part=m[1].trim()
      .replace(/\s+/g,' ')
      .replace(/\bXP\b/i,'XP');
    if(!signed.includes(part))signed.push(part);
  }

  // Some action outputs use compact slash-separated rewards.
  if(!signed.length){
    const compact=msg.match(/[+-]\d+\s+[A-Za-z][A-Za-z ]*(?:\s*\/\s*[+-]\d+\s+[A-Za-z][A-Za-z ]*)+/);
    if(compact)return compact[0].replace(/\s*\/\s*/g,' · ');
  }

  if(signed.length)return signed.join(' · ');

  const low=msg.toLowerCase(),said=plainSentence(msg);
  if(low.includes('failed') || low.includes('failure') || low.includes('+0 rewards'))return 'No reward'+(said?' · '+said:'');
  // Otherwise the reply's own first sentence, kept short. Never dump the whole response into the HUD.
  return said||'Completed successfully';
}

function renderActivity(d){
  const rows=d.activity||[];
  $('#activity-count').textContent=rows.length?`${rows.length} latest`:'No activity';
  $('#activity-list').innerHTML=rows.slice(0,3).map((x,i)=>`
    <div class="activity-item">
      <span class="pulse"></span>
      <div class="activity-copy">
        <div class="activity-top">
          <span class="activity-who">${esc(x.name)}</span>
          <span class="activity-action">${esc(x.action)}</span>
          <span class="activity-age">${ago(x.at)}</span>
        </div>
        <div class="activity-msg" title="${esc(x.message)}">${esc(conciseActivityMessage(x))}</div>
      </div>
    </div>`).join('') || `<div class="mini muted">Waiting for citizen activity…</div>`;
}

function renderEvent(d){
  const eventPanel=$('#event');
  eventPanel.dataset.available=d.event?'1':'0';
  if(!d.event){eventPanel.classList.add('hidden');return}
  const e=d.event;
  if(VALID_PANELS.has(panelMode)){
    if(panelMode==='event')eventPanel.classList.remove('hidden');
  }else if(!isPanelUserHidden('event')){
    eventPanel.classList.remove('hidden');
  }
  $('#event-name').textContent=(e.emoji||'🚨')+' '+e.name;
  $('#event-time').textContent=fmtTime(e.seconds_remaining);
  $('#event-progress').textContent=e.progress+'/'+e.goal;
  $('#event-primary').textContent=e.primary;
  $('#event-support').textContent=e.support+' '+e.support_progress+'/2';
  setBar('#event-bar',e.percent);
  const leaders=(e.leaders||[]).map((x,i)=>`${i+1}. ${x.name} · ${x.primary}P/${x.support}S`).join('   ');
  $('#event-leaders').textContent=leaders?('Top responders · '+leaders):'Awaiting first responders…';
}

function renderOps(d){
  const p=d.project||{},st=d.story||{},m=d.market||{};
  $('#project-name').textContent=(p.name||'No active project')+' · '+(p.progress||0)+'/'+(p.goal||0);
  $('#project-pct').textContent=Math.round(p.percent||0)+'%';
  $('#project-skills').textContent=(p.skills||[]).length?'Useful: '+p.skills.join(' · '):'';
  setBar('#project-bar',p.percent||0);

  $('#story-name').textContent=(st.name||'No active story')+' · '+(st.progress||0)+'/'+(st.goal||0);
  $('#story-pct').textContent=Math.round(st.percent||0)+'%';
  setBar('#story-bar',st.percent||0);
  const tracks=st.tracks||[];
  const trackTotal=tracks.reduce((sum,x)=>sum+(Number(x.value)||0),0);
  const maxTrack=Math.max(0,...tracks.map(x=>Number(x.value)||0));
  const leaderCount=tracks.filter(x=>(Number(x.value)||0)===maxTrack && maxTrack>0).length;

  function storyIcon(name){
    const n=String(name||'').toLowerCase();
    if(n.includes('investig')||n.includes('analy')||n.includes('study'))return '🔬';
    if(n.includes('stabil')||n.includes('contain')||n.includes('infrastructure'))return '🏗️';
    if(n.includes('supply')||n.includes('cargo')||n.includes('moving'))return '📦';
    if(n.includes('agriculture')||n.includes('cultivation')||n.includes('growth'))return '🌱';
    if(n.includes('search')||n.includes('route'))return '🧭';
    if(n.includes('trace'))return '📡';
    return '◆';
  }

  $('#story-tracks').innerHTML=tracks.map(x=>{
    const value=Number(x.value)||0;
    const influence=trackTotal?Math.round((value/trackTotal)*100):0;
    const leader=value===maxTrack && maxTrack>0;
    const tag=leader ? `<span class="story-leader-tag">${leaderCount>1?'TIED':'LEADING'}</span>` : '';
    return `<div class="story-path${leader?' leader':''}">
      <div class="story-path-head">
        <span class="story-path-name">${storyIcon(x.name)} ${esc(x.name)}${tag}</span>
        <span class="story-path-meta">${value} pts · ${influence}%</span>
      </div>
      <div class="story-path-bar"><i style="width:${influence}%"></i></div>
    </div>`;
  }).join('');

  if(trackTotal){
    const leaderNames=tracks
      .filter(x=>(Number(x.value)||0)===maxTrack)
      .map(x=>x.name);
    $('#story-summary').textContent=
      (leaderNames.length===1?'Current leading path: ':'Current leaders: ')+leaderNames.join(' / ');
  }else{
    $('#story-summary').textContent='No story influence recorded yet.';
  }

  $('#market-primary').textContent=m.primary?`🔥 ${m.primary.name}: ${m.primary.price} SC`:'No market signal';
  $('#market-secondary').textContent=m.secondary?`↑ ${m.secondary.name}: ${m.secondary.price} SC`:'';
  $('#pressure').textContent=(d.pressure||[]).length?(d.pressure.join(' · ')):'No critical shortages';
  $('#rumor').textContent=d.rumor?('🗣️ '+d.rumor):'';
}

function renderToday(d){
  const q=d.directive||{},g=d.engagement||{},a=d.aftermath;
  $('#directive-name').textContent=(q.complete?'✓ ':'')+(q.name||'Daily Directive');
  $('#directive-progress').textContent=(q.progress||0)+'/'+(q.goal||0);
  $('#directive-description').textContent=q.description||'New Eridian is setting today\'s shared priority.';
  $('#directive-skills').textContent=(q.skills||[]).length
    ? 'Useful: '+q.skills.join(' · ')+' · Reward '+(q.reward||'society progress')
    : '';
  setBar('#directive-bar',q.percent||0);

  $('#variety-count').textContent=Number(g.variety_complete||0).toLocaleString();
  $('#lore-count').textContent=Number(g.lore_found||0)+'/'+Number(g.lore_total||0);
  $('#fleet-count').textContent=Number(g.fleet_assigned||0).toLocaleString();
  $('#system-detail').textContent='Gear familiarity: '+Number(g.familiar_gear||0)+' familiar / '+
    Number(g.trusted_gear||0)+' trusted · '+Number(g.relationship_memories||0)+' shared memories';

  const host=$('#aftermath');
  if(!a){host.className='aftermath hidden';host.textContent='';return}
  host.className='aftermath '+(Number(a.modifier)>=0?'good':'bad');
  const sign=Number(a.modifier)>=0?'+':'';
  host.innerHTML='<b>Event aftermath '+sign+Number(a.modifier)+'%</b> · '+
    esc((a.skills||[]).join(' / '))+' · '+esc(fmtTime(a.seconds_remaining))+' remaining<br>'+esc(a.description||'');
}



function initSinglePanelMode(){
  if(!VALID_PANELS.has(panelMode))return false;
  document.body.classList.add('single-panel','panel-'+panelMode);

  document.querySelectorAll('.movable[data-panel]').forEach(panel=>{
    const selected=panel.dataset.panel===panelMode;
    panel.classList.toggle('panel-selected',selected);
    panel.classList.toggle('panel-hidden',!selected);
    if(selected){
      panel.classList.remove('free-position');
      panel.style.left='';
      panel.style.top='';
    }
  });

  // Event still hides naturally when no live event exists.
  return true;
}

/* -----------------------------------------------------------------------
   Movable / toggleable OBS layout
   Add ?edit=1 to the overlay URL to expose the editor.
   Layout and visibility are persisted in this Browser Source via localStorage.
------------------------------------------------------------------------ */
const LAYOUT_KEY='new-eridian-v2-overlay-layout-v2';
const PANEL_LABELS={
  society:'Society / World',
  today:'Today / New Systems',
  event:'Live Event',
  ops:'Operations',
  activity:'Recent Activity',
  telemetry:'Society Stats',
  signal:'Connection Signal'
};
let layoutState={positions:{},hidden:{},locked:true};
let dragState=null;

function readLayout(){
  try{
    const saved=JSON.parse(localStorage.getItem(LAYOUT_KEY)||'{}');
    if(saved && typeof saved==='object'){
      layoutState.positions=saved.positions&&typeof saved.positions==='object'?saved.positions:{};
      layoutState.hidden=saved.hidden&&typeof saved.hidden==='object'?saved.hidden:{};
      layoutState.locked=saved.locked!==false;
    }
  }catch(e){}
}
function saveLayout(){
  try{localStorage.setItem(LAYOUT_KEY,JSON.stringify(layoutState))}catch(e){}
}
function isPanelUserHidden(id){return !!layoutState.hidden[id]}

function getHudRect(){return $('#hud').getBoundingClientRect()}
function applyPanelPosition(panel,pos){
  if(!pos)return;
  const hud=getHudRect();
  const w=panel.offsetWidth||1,h=panel.offsetHeight||1;
  const maxX=Math.max(0,hud.width-w),maxY=Math.max(0,hud.height-h);
  const x=Math.max(0,Math.min(maxX,(Number(pos.x)||0)*hud.width));
  const y=Math.max(0,Math.min(maxY,(Number(pos.y)||0)*hud.height));
  panel.classList.add('free-position');
  panel.style.left=x+'px';
  panel.style.top=y+'px';
}
function applyLayout(){
  if(VALID_PANELS.has(panelMode))return;
  document.querySelectorAll('.movable[data-panel]').forEach(panel=>{
    const id=panel.dataset.panel;
    panel.classList.toggle('panel-hidden',isPanelUserHidden(id));
    applyPanelPosition(panel,layoutState.positions[id]);
  });
  $('#hud').classList.toggle('layout-edit',!layoutState.locked);
  $('#layout-lock').textContent=layoutState.locked?'🔓 Unlock':'🔒 Lock';
  renderPanelToggles();
}
function capturePanelPosition(panel,left,top){
  const hud=getHudRect();
  layoutState.positions[panel.dataset.panel]={
    x:hud.width?left/hud.width:0,
    y:hud.height?top/hud.height:0
  };
  saveLayout();
}
function renderPanelToggles(){
  const host=$('#panel-toggles');
  if(!host)return;
  host.innerHTML='';
  Object.entries(PANEL_LABELS).forEach(([id,label])=>{
    const row=document.createElement('div');
    row.className='panel-toggle-row';
    const name=document.createElement('span');
    name.textContent=label;
    const btn=document.createElement('button');
    btn.type='button';
    btn.className='panel-toggle';
    const visible=!isPanelUserHidden(id);
    btn.setAttribute('aria-pressed',visible?'true':'false');
    btn.textContent=visible?'Visible':'Hidden';
    btn.addEventListener('click',()=>{
      layoutState.hidden[id]=!layoutState.hidden[id];
      saveLayout();
      applyLayout();
      // If there is no active event, keep its data-driven hidden state too.
      if(id==='event' && $('#event').dataset.available!=='1')$('#event').classList.add('hidden');
    });
    row.append(name,btn);
    host.appendChild(row);
  });
}
function resetLayout(){
  layoutState={positions:{},hidden:{},locked:false};
  saveLayout();
  document.querySelectorAll('.movable[data-panel]').forEach(panel=>{
    panel.classList.remove('free-position','panel-hidden');
    panel.style.left='';
    panel.style.top='';
  });
  applyLayout();
  if($('#event').dataset.available!=='1')$('#event').classList.add('hidden');
}
function beginDrag(e){
  if(window.matchMedia('(max-width:820px)').matches)return;
  if(layoutState.locked)return;
  const panel=e.target.closest('.movable[data-panel]');
  if(!panel || e.button!==0)return;
  if(e.target.closest('button,input,a'))return;
  const hud=getHudRect(),r=panel.getBoundingClientRect();
  dragState={
    panel,
    pointerId:e.pointerId,
    dx:e.clientX-r.left,
    dy:e.clientY-r.top
  };
  panel.classList.add('dragging','free-position');
  panel.style.left=(r.left-hud.left)+'px';
  panel.style.top=(r.top-hud.top)+'px';
  if(panel.setPointerCapture)panel.setPointerCapture(e.pointerId);
  e.preventDefault();
}
function moveDrag(e){
  if(!dragState || e.pointerId!==dragState.pointerId)return;
  const panel=dragState.panel,hud=getHudRect();
  const maxX=Math.max(0,hud.width-panel.offsetWidth);
  const maxY=Math.max(0,hud.height-panel.offsetHeight);
  const left=Math.max(0,Math.min(maxX,e.clientX-hud.left-dragState.dx));
  const top=Math.max(0,Math.min(maxY,e.clientY-hud.top-dragState.dy));
  panel.style.left=left+'px';
  panel.style.top=top+'px';
  capturePanelPosition(panel,left,top);
}
function endDrag(e){
  if(!dragState || e.pointerId!==dragState.pointerId)return;
  dragState.panel.classList.remove('dragging');
  if(dragState.panel.releasePointerCapture)dragState.panel.releasePointerCapture(e.pointerId);
  dragState=null;
}
function initLayoutEditor(){
  if(VALID_PANELS.has(panelMode))return;
  readLayout();
  const editor=params.get('edit')==='1';
  if(editor)$('#hud').classList.add('editor-enabled');

  $('#layout-launch').addEventListener('click',()=>{
    $('#layout-panel').classList.toggle('open');
  });
  $('#layout-close').addEventListener('click',()=>{
    $('#layout-panel').classList.remove('open');
  });
  $('#layout-lock').addEventListener('click',()=>{
    layoutState.locked=!layoutState.locked;
    saveLayout();
    applyLayout();
  });
  $('#layout-reset').addEventListener('click',()=>{
    if(confirm('Reset all panel positions and visibility?'))resetLayout();
  });

  $('#hud').addEventListener('pointerdown',beginDrag);
  $('#hud').addEventListener('pointermove',moveDrag);
  $('#hud').addEventListener('pointerup',endDrag);
  $('#hud').addEventListener('pointercancel',endDrag);

  window.addEventListener('resize',()=>{
    document.querySelectorAll('.movable[data-panel]').forEach(panel=>{
      applyPanelPosition(panel,layoutState.positions[panel.dataset.panel]);
    });
  });

  applyLayout();
}

async function refresh(){
  try{
    const r=await fetch('/api/v1/overlay?channel='+encodeURIComponent(channel),{cache:'no-store'});
    if(!r.ok)throw new Error('HTTP '+r.status);
    const d=await r.json();
    if(!d.ok)throw new Error('Overlay unavailable');

    $('#tier-chip').textContent=d.tier||'—';
    $('#day').textContent=d.day!=null?d.day:'—';
    $('#phase').textContent=(d.phase_emoji||'')+' '+(d.phase||'');
    $('#active-players').textContent=d.active_players!=null?d.active_players:0;
    $('#condition').textContent=d.condition||'Unknown condition';
    $('#condition-text').textContent=d.condition_text||'';
    renderOps(d);
    renderToday(d);
    renderEvent(d);
    renderStats(d);
    renderActivity(d);

    $('#signal').classList.remove('bad');
    $('#signal-text').textContent='LIVE SIGNAL · updated just now';
    lastStamp=d.updated_at||'';
  }catch(e){
    $('#signal').classList.add('bad');
    $('#signal-text').textContent='SIGNAL INTERRUPTED · retrying';
  }
}

if(channel){
  $('#hud').classList.remove('hidden');
  initSinglePanelMode();
  initLayoutEditor();
  refresh();
  setInterval(refresh,3500);
  setInterval(()=>{
    if(lastStamp && !$('#signal').classList.contains('bad'))
      $('#signal-text').textContent='LIVE SIGNAL · '+ago(lastStamp);
  },1000);
}else{
  $('#setup').classList.remove('hidden');
  $('#connect').onclick=()=>{
    const v=$('#channel').value.trim();
    if(v)location.href='/overlay?channel='+encodeURIComponent(v);
  };
  $('#channel').addEventListener('keydown',e=>{
    if(e.key==='Enter')$('#connect').click();
  });
}
</script>
<script>
/* Live highlight alerts float over the top centre of the dashboard (&alerts=0 turns them off). */
(()=>{const q=new URLSearchParams(location.search),c=q.get('channel');if(!c||q.get('alerts')==='0'||q.get('panel'))return;
const f=document.createElement('iframe');f.src='/obs/alerts?channel='+encodeURIComponent(c)+(q.get('sound')?'&sound=1':'');f.title='Live alerts';f.setAttribute('allowtransparency','true');
f.style.cssText='position:fixed;top:18px;left:50%;transform:translateX(-50%);width:680px;max-width:96vw;height:220px;border:0;background:transparent;pointer-events:none;z-index:60';
document.body.appendChild(f)})();
</script>
</body>
</html>""")
