from pathlib import Path


MAIN = Path(__file__).resolve().parent / "app" / "main.py"


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label}, found {count}")
    return text.replace(old, new, 1)


def main():
    source = MAIN.read_text(encoding="utf-8")
    original = source

    # Make the decay policy explicit and give Comfort a faster, but bounded,
    # decay rate. Existing last_decay_at timestamps remain compatible.
    source = replace_once(
        source,
        'def life_state(db,p):\n',
        '''LIFE_DECAY_INTERVAL_SECONDS=14400  # four real hours\nLIFE_DECAY_RATES={\n    "energy":1,\n    "nutrition":1,\n    "social":1,\n    "comfort":2,  # habitat comfort deteriorates faster than physical reserves\n    "morale":1,\n}\nLIFE_DECAY_MAX_STEPS=6\n\ndef life_state(db,p):\n''',
        "life_state declaration",
    )
    source = replace_once(
        source,
        '''    # Slow, forgiving decay: one point per four real hours, capped at six points per return.\n    last=as_utc(row.last_decay_at) or now()\n    elapsed=max(0,int((now()-last).total_seconds()//14400))\n    steps=min(6,elapsed)\n    if steps:\n        row.energy=clamp100(row.energy-steps)\n        row.nutrition=clamp100(row.nutrition-steps)\n        row.social=clamp100(row.social-steps)\n        row.comfort=clamp100(row.comfort-steps)\n        row.morale=clamp100(row.morale-steps)\n        row.last_decay_at=last+timedelta(seconds=elapsed*14400);row.updated_at=now();db.commit()\n''',
        '''    # Needs decay in real time. Comfort decays twice as quickly because\n    # habitat upkeep and environmental stress are persistent pressures. The\n    # per-return cap prevents a long absence from creating an impossible\n    # recovery wall.\n    last=as_utc(row.last_decay_at) or now()\n    elapsed=max(0,int((now()-last).total_seconds()//LIFE_DECAY_INTERVAL_SECONDS))\n    steps=min(LIFE_DECAY_MAX_STEPS,elapsed)\n    if steps:\n        for field,rate in LIFE_DECAY_RATES.items():\n            setattr(row,field,clamp100(getattr(row,field)-steps*rate))\n        row.last_decay_at=last+timedelta(seconds=elapsed*LIFE_DECAY_INTERVAL_SECONDS);row.updated_at=now();db.commit()\n''',
        "life decay implementation",
    )

    # Capture level transitions at the single XP entry point so every XP path\n    # (work, crafting, orders, selling, mentoring, etc.) can report them.\n    source = replace_once(
        source,
        '''def gain_skill(p,skill,amount=1):\n    field={\n        "cultivation":"farm_xp","environmental":"environmental_xp",\n        "extraction":"mining_xp","fabrication":"fabrication_xp",\n        "infrastructure":"infrastructure_xp","research":"research_xp",\n        "logistics":"delivery_xp","frontier":"explore_xp","commerce":"commerce_xp",\n    }[skill]\n    setattr(p,field,getattr(p,field)+amount)\n    if skill in {"fabrication","infrastructure"}:p.industry_xp+=amount\n''',
        '''def gain_skill(p,skill,amount=1):\n    field={\n        "cultivation":"farm_xp","environmental":"environmental_xp",\n        "extraction":"mining_xp","fabrication":"fabrication_xp",\n        "infrastructure":"infrastructure_xp","research":"research_xp",\n        "logistics":"delivery_xp","frontier":"explore_xp","commerce":"commerce_xp",\n    }[skill]\n    old_xp=getattr(p,field)\n    old_level=lvl(old_xp)\n    new_xp=old_xp+max(0,int(amount))\n    setattr(p,field,new_xp)\n    if skill in {"fabrication","infrastructure"}:p.industry_xp+=max(0,int(amount))\n    new_level=lvl(new_xp)\n    if new_level>old_level:\n        pending=getattr(p,"_level_up_notes",[])\n        pending.append((skill,old_level,new_level))\n        p._level_up_notes=pending\n    return new_level\n\ndef take_level_up_notes(p,provider="twitch"):\n    notes=getattr(p,"_level_up_notes",[])\n    if not notes:return ""\n    p._level_up_notes=[]\n    labels=[]\n    for skill,old_level,new_level in notes:\n        label=SKILL_LABELS.get(skill,skill.replace("_"," ").title())\n        labels.append(f"{label} Lv. {old_level} → Lv. {new_level}")\n    if provider=="discord":\n        return "\\n\\n🎉 LEVEL UP!\\n"+"\\n".join("• "+x for x in labels)+"\\nYour aptitude is stronger. Success chances and specialist rewards may improve."\n    return " 🎉 LEVEL UP: "+"; ".join(labels)+". Success chances and specialist rewards may improve."\n''',
        "gain_skill implementation",
    )

    # Action results are the common path for work and include all its XP gains.
    source = replace_once(
        source,
        '        message=base+determination_note+lore+exceptional+modifier_note+task_readiness_warning(life,provider)+(" "+auto if auto else "")\n',
        '        message=base+take_level_up_notes(p,provider)+determination_note+lore+exceptional+modifier_note+task_readiness_warning(life,provider)+(" "+auto if auto else "")\n',
        "action result assembly",
    )

    # Cover the standalone XP-producing endpoints that do not use action().
    source = replace_once(
        source,
        '                   f"\\n• New Eridian +{rewards[\'development\']} Development"\n                   +updates+task_readiness_warning(life,provider))\n',
        '                   f"\\n• New Eridian +{rewards[\'development\']} Development"\n                   +take_level_up_notes(p,provider)+updates+task_readiness_warning(life,provider))\n',
        "quality crafting result assembly",
    )
    source = replace_once(
        source,
        '              f"\\n• New Eridian +{rewards[\'development\']} Development"\n              +updates+task_readiness_warning(life,provider))\n',
        '              f"\\n• New Eridian +{rewards[\'development\']} Development"\n              +take_level_up_notes(p,provider)+updates+task_readiness_warning(life,provider))\n',
        "core crafting result assembly",
    )
    source = replace_once(
        source,
        '                   f"\\n• New Eridian +{numbers[\'development\']} Development\\n\\nWHY IT MATTERED\\n• {data[\'purpose\']}\\n\\nNEXT\\n• View the remaining Day {clock[\'day\']} orders or continue your daily contract."+milestone)\n',
        '                   f"\\n• New Eridian +{numbers[\'development\']} Development\\n\\nWHY IT MATTERED\\n• {data[\'purpose\']}\\n\\nNEXT\\n• View the remaining Day {clock[\'day\']} orders or continue your daily contract."+take_level_up_notes(p,provider)+milestone)\n',
        "production order result assembly",
    )
    source = replace_once(
        source,
        '        return out(f"🧑‍🏫 {p.display_name} mentors {target_p.display_name}. {target_p.display_name} gains +2 {SKILL_LABELS[skill]} XP; mentor gains +2 Contribution.")\n',
        '        return out(f"🧑‍🏫 {p.display_name} mentors {target_p.display_name}. {target_p.display_name} gains +2 {SKILL_LABELS[skill]} XP; mentor gains +2 Contribution."+take_level_up_notes(target_p,provider))\n',
        "mentoring result assembly",
    )

    # Keep the player-facing rules synchronized with the actual mechanics.
    source = source.replace(
        "Needs decay by 1 per four real hours, with at most 6 points",
        "Energy, Nutrition, Social, and Morale decay by 1 per four real hours; Comfort decays by 2, with at most 6 time-steps",
    )
    source = source.replace(
        "Needs decay by 1 per four real hours, with at most 6 points[...]
",
        "Needs decay by 1 per four real hours, with at most 6 points[...]
",
    )

    if source == original:
        raise RuntimeError("No changes were made")
    MAIN.write_text(source, encoding="utf-8")
    print(f"Updated {MAIN} with balanced life decay and level-up notifications.")


if __name__ == "__main__":
    main()
