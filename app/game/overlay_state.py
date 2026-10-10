"""The stream overlay data (/api/v1/overlay).
"""
import os
import re
import time
from datetime import timedelta
from sqlalchemy import select
from ..commands import transaction as game_transaction
from ..db import SessionLocal
from ..settlement import pressures as colony_pressures, state as colony_state
from ..models import (
    ActionLog, DailyVariety, DirectiveParticipant, GearFamiliarity, LoreDiscovery, Player, PlayerPreference,
    RelationshipMemory, Society, SocietyAftermath)
from .base import app
from .rules import EVENTS, LORE_FRAGMENTS, RUMORS, SKILL_LABELS, SOCIETY_TIERS
from .players import as_utc, demand_price, market_demand, resource_name, society, story_state, world
from .world import _stable_index, directive_for, project_cfg, shortages, society_tier, world_clock
from .colony_events import event_contributors, resolve_expired_event
from .. import main      # app.main: names from later modules and settings changed at runtime

OVERLAY_CACHE_SECONDS=float(os.getenv("OVERLAY_CACHE_SECONDS","5"))   # the OBS pages poll every 3-5 seconds
_overlay_cache={};_overlay_lock=__import__("threading").Lock()

@app.get("/api/v1/overlay")
def overlay_state(channel:str):
    """Rich JSON contract for the New Eridian v2 OBS Browser Source.

    Every overlay panel polls this every few seconds. One result is shared for
    OVERLAY_CACHE_SECONDS so a dozen OBS sources cost one computation, and the
    world lock the computation takes is not held on every poll (which slowed
    Discord buttons down)."""
    cached=_overlay_cache.get(channel)
    if cached and time.monotonic()-cached[0]<main.OVERLAY_CACHE_SECONDS:return cached[1]
    from .. import world_guard
    # A channel with no world shows the main world (and shares its cache entry) instead of a cache slot of its own.
    if channel!=main.DISCORD_WORLD_ID and not world_guard.known(channel):channel=main.DISCORD_WORLD_ID
    with _overlay_lock:
        cached=_overlay_cache.get(channel)
        if cached and time.monotonic()-cached[0]<main.OVERLAY_CACHE_SECONDS:return cached[1]
        data=overlay_state_fresh(channel)
        while len(_overlay_cache)>=50:_overlay_cache.pop(min(_overlay_cache,key=lambda k:_overlay_cache[k][0]))   # drop the oldest
        _overlay_cache[channel]=(time.monotonic(),data)
        return data

@game_transaction
def overlay_state_fresh(channel:str):
    """The overlay data, computed now."""
    with SessionLocal() as db:
        source_ids=list(dict.fromkeys([main.DISCORD_WORLD_ID,channel]))

        # New Eridian's shared world is authoritative for Avesta state.
        s=society(db,main.DISCORD_WORLD_ID)
        clock=world_clock(db,main.DISCORD_WORLD_ID,s)
        w=world(db,main.DISCORD_WORLD_ID)
        resolve_expired_event(db,s,w)

        # Combine society telemetry when Twitch and Discord have separate legacy rows.
        sources=[s]
        if channel!=main.DISCORD_WORLD_ID:
            other=db.execute(select(Society).where(Society.channel_id==channel)).scalar_one_or_none()
            if other:
                resolve_expired_event(db,other,world(db,channel))
                sources.append(other)

        stats={field:sum(getattr(source,field) for source in sources)
               for field in ("food","materials","development","knowledge","treasury","reputation","population")}
        total=Society(**stats)
        tier=society_tier(total)
        core_stats={k:stats[k] for k in ("food","materials","development","knowledge","treasury","reputation")}
        core=min(core_stats.values())
        next_tier=next((x for x in SOCIETY_TIERS if x[1]>core),None)
        target=next_tier[1] if next_tier else max(1,SOCIETY_TIERS[-1][1])
        bottleneck_key=min(core_stats,key=core_stats.get)
        bottleneck_labels={
            "food":"Food","materials":"Materials","development":"Development",
            "knowledge":"Knowledge","treasury":"Treasury","reputation":"Reputation"
        }

        # Society project.
        project=main.current_project(db,main.DISCORD_WORLD_ID,clock["day"])
        pcfg=project_cfg(project.project_key)
        project_data={
            "key":project.project_key,
            "name":pcfg[1],
            "progress":project.progress,
            "goal":project.goal,
            "percent":min(100,round((project.progress/max(1,project.goal))*100,1)),
            "skills":[SKILL_LABELS.get(x,x.title()) for x in sorted(pcfg[3])],
            "completed":project.completed,
        }

        # Weekly community story.
        storyrow,storycfg=story_state(db,main.DISCORD_WORLD_ID,clock)
        story_values=[storyrow.track_a,storyrow.track_b,storyrow.track_c]
        story_total=sum(story_values)
        story_tracks=[
            {"name":storycfg["tracks"][i][0],"value":story_values[i]}
            for i in range(3)
        ]
        story_data={
            "key":storycfg["key"],
            "name":storycfg["name"],
            "text":storycfg["text"],
            "progress":story_total,
            "goal":storycfg["goal"],
            "percent":min(100,round((story_total/max(1,storycfg["goal"]))*100,1)),
            "resolved":bool(storyrow.resolved),
            "outcome":storyrow.outcome or "",
            "tracks":story_tracks,
        }

        # Current market demand.
        primary_market,secondary_market=market_demand(main.DISCORD_WORLD_ID,clock["day"])
        market_prices={
            k:demand_price(k,clock["day"])
            for k in market_demand(main.DISCORD_WORLD_ID,clock["day"])
        }
        market_data={
            "primary":{"key":primary_market,"name":resource_name(primary_market),"price":market_prices[primary_market]},
            "secondary":{"key":secondary_market,"name":resource_name(secondary_market),"price":market_prices[secondary_market]},
            "prices":market_prices,
        }

        # Shortage pressure and current rumor.
        pressure=[x[0] for x in shortages(total)]
        rumor=RUMORS[_stable_index(f"{main.DISCORD_WORLD_ID}:{clock['day']}:rumor",len(RUMORS))]

        # Recent activity feed.
        recent=db.execute(
            select(ActionLog)
            .where(ActionLog.channel_id.in_(source_ids))
            .order_by(ActionLog.created_at.desc(),ActionLog.id.desc())
            .limit(5)
        ).scalars().all()
        recent_uids=list({x.canonical_uid for x in recent})
        name_map={}
        if recent_uids:
            players=db.execute(
                select(Player).where(
                    Player.channel_id.in_(source_ids),
                    Player.twitch_uid.in_(recent_uids)
                )
            ).scalars().all()
            for p in players:
                name_map.setdefault(p.twitch_uid,p.display_name)
        activity=[]
        for row in recent:
            message=(row.response or "").replace("\r"," ").replace("\n"," · ").strip()
            message=re.sub(r"\s+"," ",message)
            activity.append({
                "name":name_map.get(row.canonical_uid,"Citizen"),
                "action":row.action.replace("_"," ").title(),
                "message":message[:260],
                "at":as_utc(row.created_at).isoformat(),
            })

        cutoff=main.now()-timedelta(minutes=30)
        active_uids=set(db.execute(
            select(ActionLog.canonical_uid).where(
                ActionLog.channel_id.in_(source_ids),
                ActionLog.created_at>=cutoff
            )
        ).scalars().all())

        event_data=None
        if w.active_event:
            cfg=EVENTS[w.active_event]
            leaders=event_contributors(db,w)
            event_data={
                "key":w.active_event,
                "name":cfg["name"],
                "emoji":cfg["emoji"],
                "action":cfg["action"],
                "progress":w.event_progress,
                "goal":w.event_goal,
                "percent":min(100,round((w.event_progress/max(1,w.event_goal))*100,1)),
                "seconds_remaining":max(0,int((as_utc(w.event_ends)-main.now()).total_seconds())),
                "seconds_total":int(cfg["minutes"])*60,
                "primary":SKILL_LABELS.get(cfg["primary"],cfg["primary"].title()),
                "support":SKILL_LABELS.get(cfg["support"],cfg["support"].title()),
                "support_progress":w.event_support_successes,
                "active_players":w.event_active_players,
                "leaders":[
                    {"name":r.display_name,"primary":r.primary_successes,"support":r.support_successes}
                    for r in leaders[:3]
                ],
            }

        # v6.0+ engagement telemetry. These are deliberately summarized at
        # society level so the stream overlay stays useful without exposing a
        # citizen's private inventory or requiring a viewer identity.
        directive,dcfg=directive_for(db,main.DISCORD_WORLD_ID,clock["day"])
        directive_participants=db.execute(
            select(DirectiveParticipant).where(
                DirectiveParticipant.channel_id.in_(source_ids),
                DirectiveParticipant.avesta_day==clock["day"]
            )
        ).scalars().all()
        directive_data={
            "key":directive.directive_key,
            "name":dcfg[1],
            "description":dcfg[5],
            "progress":directive.progress,
            "goal":directive.goal,
            "percent":min(100,round((directive.progress/max(1,directive.goal))*100,1)),
            "complete":bool(directive.complete),
            "skills":[SKILL_LABELS.get(x,x.title()) for x in sorted(dcfg[2])],
            "reward":f"+{dcfg[4]} {dcfg[3].title()}",
            "participants":len({x.canonical_uid for x in directive_participants}),
        }

        aftermath_rows=db.execute(
            select(SocietyAftermath).where(
                SocietyAftermath.channel_id.in_(source_ids),
                SocietyAftermath.expires_at>main.now()
            ).order_by(SocietyAftermath.expires_at.desc())
        ).scalars().all()
        aftermath_data=None
        if aftermath_rows:
            aftermath=aftermath_rows[0]
            aftermath_data={
                "event":aftermath.event_name,
                "result":aftermath.result,
                "modifier":aftermath.modifier,
                "description":aftermath.description,
                "skills":[SKILL_LABELS.get(x,x.title()) for x in aftermath.skills.split(",") if x],
                "seconds_remaining":max(0,int((as_utc(aftermath.expires_at)-main.now()).total_seconds())),
            }

        variety_rows=db.execute(
            select(DailyVariety).where(
                DailyVariety.channel_id.in_(source_ids),
                DailyVariety.avesta_day==clock["day"]
            )
        ).scalars().all()
        prefs=db.execute(
            select(PlayerPreference).where(PlayerPreference.channel_id.in_(source_ids))
        ).scalars().all()
        familiarity=db.execute(
            select(GearFamiliarity).where(GearFamiliarity.channel_id.in_(source_ids))
        ).scalars().all()
        memories=db.execute(
            select(RelationshipMemory).where(RelationshipMemory.channel_id.in_(source_ids))
        ).scalars().all()
        lore=db.execute(
            select(LoreDiscovery).where(LoreDiscovery.channel_id.in_(source_ids))
        ).scalars().all()
        engagement_data={
            "variety_active":len({x.canonical_uid for x in variety_rows}),
            "variety_complete":len({x.canonical_uid for x in variety_rows if x.claimed}),
            "fleet_assigned":len({x.canonical_uid for x in prefs if x.assigned_duck}),
            "familiar_gear":sum(1 for x in familiarity if x.uses>=10),
            "trusted_gear":sum(1 for x in familiarity if x.uses>=50),
            "relationship_memories":len(memories),
            "lore_found":len({x.lore_key for x in lore}),
            "lore_total":len(LORE_FRAGMENTS),
        }

        from .. import stream_overlay
        stream_overlay.watch(db,main.DISCORD_WORLD_ID,tier[0],project_data,story_data,directive_data)
        stream_extra=stream_overlay.extra(db,source_ids,main.DISCORD_WORLD_ID)
        stream_extra.update(main.community.overlay_data(db,stream_extra.get("seedlings",[])))
        db.commit()
        return {
            **stream_extra,
            "ok":True,
            "game":s.name,
            "tier":tier[0],
            "tier_bonus":tier[2],
            "next_tier":next_tier[0] if next_tier else None,
            "tier_target":target,
            "tier_percent":100 if not next_tier else min(100,round((core/max(1,target))*100,1)),
            "bottleneck":{
                "key":bottleneck_key,
                "name":bottleneck_labels[bottleneck_key],
                "value":core_stats[bottleneck_key],
                "target":target,
                "percent":min(100,round((core_stats[bottleneck_key]/max(1,target))*100,1)),
            },
            "day":clock["day"],
            "phase":clock["phase"],"hour":round(clock["hour"],3),
            "phase_emoji":clock["phase_emoji"],
            "condition":clock["condition"],"condition_key":clock["condition_key"],
            "condition_text":clock["condition_text"],
            "stats":stats,
            "project":project_data,
            "story":story_data,
            "market":market_data,
            "pressure":pressure,
            "rumor":rumor,
            "event":event_data,
            "directive":directive_data,
            "aftermath":aftermath_data,
            "engagement":engagement_data,
            "colony":{source.channel_id:{"water":colony_state(db,source.channel_id).water,"ore":colony_state(db,source.channel_id).ore,"components":colony_state(db,source.channel_id).components,"housing":colony_state(db,source.channel_id).housing,"mood":colony_state(db,source.channel_id).mood,"pressures":colony_pressures(colony_state(db,source.channel_id),source)} for source in sources},
            "activity":activity,
            "active_players":len(active_uids),
            "last_action":activity[0] if activity else None,
            "updated_at":main.now().isoformat(),
            "world_sources":source_ids,
            "primary_world":main.DISCORD_WORLD_ID,
            "overlay_version":"6.4.0",
        }
