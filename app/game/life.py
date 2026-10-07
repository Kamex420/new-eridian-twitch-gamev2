"""Needs and life state, quality gear, success modifiers and progress notes.
"""
import random
import re
from sqlalchemy import select
from .. import task_yields
from ..models import DailyVariety, LifeState, PlayerPreference, QualityGear
from .rules import ACTION_SKILLS, HOBBIES, QUALITY_RECIPES, QUALITY_TIERS, SKILL_LABELS
from .players import clamp100, hobby_points
from .. import main      # app.main: names from later modules and settings changed at runtime

from ..needs import (decay as decay_needs, RECOVERY_HELP, TASK_NEED_MINIMUM, COMFORT_SLOW, COMFORT_BLOCK,
    STANDARD_ENERGY, HEAVY_ENERGY, COMFORT_FIXES_DISCORD, COMFORT_FIXES_TWITCH, work_energy, comfort_cost, RELAX_COMFORT,
    cost_text as need_cost_text, duration_text, blocked_needs, finish_forecast)

def life_state(db,p):
    row=db.execute(select(LifeState).where(LifeState.channel_id==p.channel_id,LifeState.canonical_uid==p.twitch_uid)).scalar_one_or_none()
    if not row:
        row=LifeState(channel_id=p.channel_id,canonical_uid=p.twitch_uid,last_decay_at=main.now(),updated_at=main.now())
        db.add(row);db.commit();db.refresh(row)
    if decay_needs(row,main.now()):db.commit()
    return row

def life_label(value,kind):
    if value>=80:return "Excellent"
    if value>=60:return "Good"
    if value>=35:return "Stable"
    if value>=20:return {"energy":"Tired","nutrition":"Hungry","social":"Lonely","comfort":"Uncomfortable","morale":"Low"}.get(kind,"Low")
    return {"energy":"Exhausted","nutrition":"Starving","social":"Isolated","comfort":"Distressed","morale":"Demoralized"}.get(kind,"Critical")

def task_need_gate(db,p,action,provider="twitch",life=None):
    """Return a clear blocking response when core life needs are too low."""
    life=life or life_state(db,p)
    blocked=blocked_needs(life)
    if not blocked:return ""
    if provider=="discord" and action=="gearrepair":shown="/repair target:Personal Quality Gear"
    elif provider=="discord" and action=="make":shown="/make"
    else:shown=main.guide_command(action,"discord") if provider=="discord" and action in ACTION_SKILLS else (("/" if provider=="discord" else "!")+action)
    if provider=="discord":
        lines=[f"• {main.NEED_EMOJI[field]} {label}: {value}/100 — requires {minimum}. Fix it with {main.need_fix(field,provider,db,p)}." for field,label,value,minimum in blocked]
        return (f"⛔ TASK BLOCKED — {p.display_name}, {shown} did not start.\n\n"
                "WHY\n"+"\n".join(lines)+
                "\n\nWHAT HAPPENED\nNo resources were consumed, no rewards were rolled, and no cooldown started.\n\n"
                "Fix every need listed above, then try the task again. Check /me section:Life Needs for your full status.")
    details="; ".join(f"{label} {value}/100 (need {minimum}): {main.need_fix(field,provider,db,p)}" for field,label,value,minimum in blocked)
    return f"⛔ TASK BLOCKED: {shown} did not start. {details}. Nothing was consumed, no rewards were rolled, and no cooldown started."

def hobby_rank(points):
    if points>=100:return ("Enthusiast III",.03)
    if points>=50:return ("Enthusiast II",.02)
    if points>=15:return ("Enthusiast I",.01)
    return ("Beginner",0)

def quality_gear_special(db,p,item_key):
    rows=db.execute(select(QualityGear).where(
        QualityGear.channel_id==p.channel_id,QualityGear.canonical_uid==p.twitch_uid,
        QualityGear.item_key==item_key,QualityGear.qty>0,QualityGear.condition>0
    )).scalars().all()
    if not rows:return 0
    best=max(rows,key=lambda row:QUALITY_TIERS.get(row.quality,QUALITY_TIERS["Standard"])["special"])
    value=QUALITY_TIERS.get(best.quality,QUALITY_TIERS["Standard"])["special"]
    return value if best.condition>=25 else value/2

def quality_roll(fabrication_level,quality_bonus_points=0):
    roll=max(1,random.randint(1,100)-max(0,int(quality_bonus_points)));lvl=max(0,int(fabrication_level))
    if lvl>=30:
        return "Masterwork" if roll<=15 else "Precision" if roll<=65 else "Refined" if roll<=95 else "Standard"
    if lvl>=15:
        return "Masterwork" if roll<=5 else "Precision" if roll<=30 else "Refined" if roll<=80 else "Standard"
    if lvl>=5:
        return "Refined" if roll<=5 else "Standard" if roll<=35 else "Crude"
    return "Standard" if roll>65 else "Crude"

def add_quality_gear(db,p,key,quality):
    recipe=QUALITY_RECIPES[key]
    existing=db.execute(select(QualityGear).where(
        QualityGear.channel_id==p.channel_id,
        QualityGear.canonical_uid==p.twitch_uid,
        QualityGear.item_key==key,
        QualityGear.qty>0
    )).scalars().first()
    if existing:return existing
    row=db.execute(select(QualityGear).where(
        QualityGear.channel_id==p.channel_id,
        QualityGear.canonical_uid==p.twitch_uid,
        QualityGear.item_key==key,
        QualityGear.quality==quality
    )).scalar_one_or_none()
    if row:row.qty+=1;row.condition=max(row.condition,100)
    else:db.add(QualityGear(channel_id=p.channel_id,canonical_uid=p.twitch_uid,item_key=key,item_name=recipe["name"],quality=quality,qty=1,condition=100))
    db.commit()

def quality_gear_modifier(db,p,skill):
    if not skill:return 0,[]
    total=0;notes=[]
    rows=db.execute(select(QualityGear).where(QualityGear.channel_id==p.channel_id,QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0)).scalars().all()
    best={}
    for row in rows:
        recipe=QUALITY_RECIPES.get(row.item_key)
        if not recipe or skill not in recipe["skills"]:continue
        tier=QUALITY_TIERS.get(row.quality,QUALITY_TIERS["Standard"])
        bonus=tier["skill"]*recipe["skills"][skill]
        if row.condition<25:bonus=max(.01,bonus/2)
        if bonus>best.get(row.item_key,(0,None))[0]:best[row.item_key]=(bonus,row)
    for bonus,row in best.values():
        total+=bonus
        notes.append(f"{row.item_name} {row.quality} +{int(bonus*100)}%")
    return min(.08,total),notes

def life_modifiers(db,p,skill):
    life=life_state(db,p);total=0;notes=[]
    if life.energy<15:total-=.12;notes.append("Exhausted -12%")
    elif life.energy<30:total-=.05;notes.append("Tired -5%")
    elif life.energy>=85:total+=.02;notes.append("Well Rested +2%")
    if life.nutrition<20:total-=.08;notes.append("Hungry -8%")
    elif life.nutrition>=85:total+=.02;notes.append("Well Fed +2%")
    if life.morale<20:total-=.07;notes.append("Demoralized -7%")
    elif life.morale>=85:total+=.02;notes.append("Inspired +2%")
    if life.social==0:
        penalty=.15 if skill in {"commerce","logistics"} else .10;total-=penalty;notes.append(f"Severe Isolation -{int(penalty*100)}%")
    elif life.social<20:
        penalty=.10 if skill in {"commerce","logistics"} else .05;total-=penalty;notes.append(f"Social Isolation -{int(penalty*100)}%")
    elif life.social<35 and skill in {"commerce","logistics"}:total-=.05;notes.append("Lonely -5%")
    elif life.social>=80 and skill in {"commerce","logistics"}:total+=.03;notes.append("Connected +3%")
    if life.comfort<COMFORT_SLOW:total-=.10;notes.append(f"Need pressure: poor Comfort -10%; reduced productivity (work stops below {COMFORT_BLOCK})")
    elif life.comfort<35:total-=.04;notes.append("Need pressure: low Comfort -4%")
    elif life.comfort>=85:total+=.01;notes.append("Comfortable +1%")

    # Hobby perks are small and permanent.
    hobby_map={
        "cultivation":["gardening","cooking"],"environmental":["scanning","research"],
        "extraction":["rockwatching","exploration"],"fabrication":["mechanics"],"infrastructure":["mechanics"],
        "research":["research","scanning"],"logistics":["games","trading"],
        "frontier":["exploration","collecting"],"commerce":["trading","games"],
    }
    if skill in hobby_map:
        choices=[(h,hobby_points(db,p,h)) for h in hobby_map[skill]]
        hobby_name,points=max(choices,key=lambda x:x[1]);rank,bonus=hobby_rank(points)
        if bonus:total+=bonus;notes.append(f"{HOBBIES[hobby_name][0]} {rank} +{int(bonus*100)}%")

    gear_bonus,gear_notes=quality_gear_modifier(db,p,skill)
    total+=gear_bonus;notes.extend(gear_notes)
    return max(-.20,min(.12,total)),notes,life

def task_energy(action,mode=""):
    """Energy for one attempt: the heavier of the work type and the chosen method."""
    if action in {"eat","sleep"}:return 0
    return task_yields.energy(action,mode)

def spend_life_for_action(life,action,energy=None):
    """Spend one task's needs. Comfort drains at the same rate as Energy."""
    if action in {"eat","sleep"}:return
    energy=work_energy(action) if energy is None else max(0,int(energy))
    social_action=action in {"market","business","businesscontract","businessinvest","delivery","spaceport"}
    life.energy=clamp100(life.energy-energy)
    life.nutrition=clamp100(life.nutrition-1)
    life.comfort=clamp100(life.comfort-comfort_cost(energy))
    if life.comfort<COMFORT_SLOW:life.morale=clamp100(life.morale-1)
    if social_action:life.social=clamp100(life.social+1)
    life.updated_at=main.now()

def life_modifier_text(provider,notes,chance=None):
    if not notes:return ""
    if provider=="discord":
        suffix=f"\nFinal success chance: {int(chance*100)}%" if chance is not None else ""
        return "\n\n🧬 Active life modifiers\n"+"\n".join("• "+x for x in notes)+suffix
    compact=", ".join(notes[:4])
    suffix=f" | Chance {int(chance*100)}%" if chance is not None else ""
    return f" | Life: {compact}{suffix}"

def concise_action_modifiers(provider,notes,chance,failed=False):
    """Routine results show only actionable penalties; full detail lives in hubs."""
    penalties=[note for note in notes if re.search(r"-\d+%",note)]
    if not failed and not penalties:return ""
    shown=penalties[:4]
    chance_text=f"Final chance: {int(chance*100)}%" if chance is not None else ""
    if provider=="discord":
        rows=[*("• "+note for note in shown)]
        if chance_text:rows.append("• "+chance_text)
        return "\n\nWHY THIS RESULT\n"+"\n".join(rows) if rows else ""
    parts=shown+([chance_text] if chance_text else [])
    return " | "+", ".join(parts) if parts else ""

def failure_fix_text(skill,notes,chance,provider):
    fixes=[];joined=" ".join(notes).lower()
    if any(x in joined for x in ("tired","exhausted")):fixes.append("Recover Energy with /sleep or /relax.")
    if "hungry" in joined:fixes.append("Recover Nutrition with /eat.")
    if any(x in joined for x in ("lonely","isolation")):fixes.append("Recover Social with /games or /social.")
    if "poor comfort" in joined or "low comfort" in joined:fixes.append(f"Recover Comfort with {COMFORT_FIXES_DISCORD if provider=='discord' else COMFORT_FIXES_TWITCH}.")
    if "demoralized" in joined:fixes.append("Use /walk, /hobby, /games, or a crafted life item.")
    if not fixes and skill:
        fixes.append(f"Train {SKILL_LABELS[skill]}, equip matching gear, or choose its Lv.10 specialization.")
    chance_line=f"The success roll missed at a final {int((chance or 0)*100)}% chance; even prepared work is never guaranteed."
    if provider=="discord":return "\n\nHOW TO IMPROVE\n• "+chance_line+"\n"+"\n".join("• "+x for x in fixes[:2])
    return " | "+chance_line+" "+" ".join(fixes[:2])

def important_progress_notes(*notes):
    """Keep alerts and completions in action results; routine meters stay in hubs."""
    kept=[]
    for note in notes:
        if not note:continue
        low=note.lower()
        if any(word in low for word in ("complete", "activated", "unlocked", "event", "encounter", "siro exposure", "broke")):
            kept.append(note)
    return "".join(kept)

def player_preference(db,p):
    row=db.execute(select(PlayerPreference).where(PlayerPreference.channel_id==p.channel_id,PlayerPreference.canonical_uid==p.twitch_uid)).scalar_one_or_none()
    if not row:
        row=PlayerPreference(channel_id=p.channel_id,canonical_uid=p.twitch_uid)
        db.add(row);db.commit();db.refresh(row)
    return row

def daily_variety_note(db,p,skill,clock):
    """Reward three different aptitudes once per Avesta day; never a streak."""
    if not skill:return ""
    row=db.execute(select(DailyVariety).where(DailyVariety.channel_id==p.channel_id,DailyVariety.canonical_uid==p.twitch_uid,DailyVariety.avesta_day==clock["day"])).scalar_one_or_none()
    if not row:
        row=DailyVariety(channel_id=p.channel_id,canonical_uid=p.twitch_uid,avesta_day=clock["day"],skills="",claimed=False);db.add(row)
    if row.claimed:return ""
    skills={x for x in row.skills.split(",") if x};before=len(skills);skills.add(skill);row.skills=",".join(sorted(skills))
    if len(skills)>=3 and not row.claimed:
        row.claimed=True;p.sc+=6;life=life_state(db,p);life.morale=clamp100(life.morale+4);db.commit()
        return " 🌈 Daily Variety complete: 3 aptitudes, +6 SC/+4 Morale."
    db.commit()
    return f" 🌈 Daily Variety {len(skills)}/3 aptitudes." if len(skills)>before else ""
