# app/main.py, part 13: routes world
# Routes: world status, rumors, collection, traits, districts, shifts, goals, projects, bulletin, meals, mentoring,
# journal, account links, society, events and the leaderboard.
# Runs inside app.main's namespace, after the parts before it (see main.py). Not a module of its own.

@app.get("/api/v1/world")
@colony_command
def world_status(channel:str,uid:str="",name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        s=society(db,channel);clock=world_clock(db,channel,s);proj=current_project(db,channel,clock["day"]);pcfg=project_cfg(proj.project_key)
        storyrow,storycfg=story_state(db,channel,clock)
        rumor=RUMORS[_stable_index(f"{channel}:{clock['day']}:rumor",len(RUMORS))]
        low=shortages(s);shared=colony_state(db,channel)
        short=", ".join(x[0] for x in low) if low else "No core-resource shortages"
        if shared.housing<s.population:short+="; "+housing_status_text(shared,s,provider)
        discord=(f"{clock['phase_emoji']} Avesta Day {clock['day']} — {clock['phase']}\n\n"
                 f"World condition: {clock['condition']}\n{clock['condition_text']}\n\n"
                 f"Society project: {pcfg[1]} {proj.progress}/{proj.goal}\n"
                 f"Society pressure: {short}\n\n"
                 f"Weekly story: {storycfg['name']} {storyrow.track_a+storyrow.track_b+storyrow.track_c}/{storycfg['goal']}\n\n"
                 f"Rumor: {rumor}\n\nDay phases change action bonuses. Night outdoor work can increase Siro exposure.")
        if uid:
            _,pp=player(db,channel,provider,uid,name);discord+=tutorial_advance(db,pp,"world");twitch_note=tutorial_advance(db,pp,"world")
        else:twitch_note=""
        twitch=f"{clock['phase_emoji']} Day {clock['day']} {clock['phase']} | {clock['condition']} | Story {storycfg['name']} {storyrow.track_a+storyrow.track_b+storyrow.track_c}/{storycfg['goal']} | Project {pcfg[1]} {proj.progress}/{proj.goal} | {short} | Rumor: {rumor}"+twitch_note
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/rumor")
@game_transaction
def rumor(channel:str,uid:str="",name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        clock=world_clock(db,channel);base=RUMORS[_stable_index(f"{channel}:{clock['day']}:{clock['phase']}",len(RUMORS))]
        who,job=NPCS[_stable_index(f"{channel}:{clock['day']}:npc",len(NPCS))]
        return out(f"🗣️ {who}, {job}: {base}")

@app.get("/api/v1/collection")
@game_transaction
def collection(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        rows=db.execute(select(CollectionItem).where(CollectionItem.channel_id==channel,CollectionItem.canonical_uid==p.twitch_uid,CollectionItem.qty>0).order_by(CollectionItem.item_name)).scalars().all()
        if not rows:return out("🧳 Collection empty. Explore, work, and watch for unusual encounters.")
        claimed={x.set_key for x in db.execute(select(CollectionSetClaim).where(CollectionSetClaim.channel_id==channel,CollectionSetClaim.canonical_uid==p.twitch_uid)).scalars().all()}
        set_lines=[f"{name}: {'COMPLETE' if key in claimed else str(sum(1 for i in items if i in {r.item_key for r in rows}))+'/'+str(len(items))}" for key,(name,items,_,__,___) in COLLECTION_SETS.items()]
        if provider=="discord":return PlainTextResponse("🧳 Collection\n\n"+"\n".join(f"• {r.item_name} x{r.qty}" for r in rows[:25])+"\n\nSETS\n"+"\n".join("• "+x for x in set_lines))
        return out("🧳 "+p.display_name+" | "+" | ".join(f"{r.item_name} x{r.qty}" for r in rows[:10]))

@app.get("/api/v1/traits")
@game_transaction
def traits(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);items,_=trait_data(db,p)
        return out("🧬 "+p.display_name+" | "+(", ".join(items) if items else "No earned traits yet. Reach 50 XP in an aptitude to begin earning them."))

@app.get("/api/v1/district")
@game_transaction
def district(channel:str,uid:str,name:str="Citizen",district:str="",provider:str="twitch"):
    key=(district or "").lower().strip().replace(" ","_")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);pw=player_world(db,p)
        if not key:return out("🏘️ Districts: "+", ".join(DISTRICTS))
        if key not in DISTRICTS:return out("🏘️ Unknown district. Options: "+", ".join(DISTRICTS))
        pw.district=key;db.commit();journal_add(db,p,f"Moved residence to {DISTRICTS[key]}.")
        return out(f"🏘️ {p.display_name} now lives in the {DISTRICTS[key]}. Matching work receives a small local familiarity bonus.")

@app.get("/api/v1/shift")
@colony_command
def shift(channel:str,uid:str,name:str="Citizen",role:str="",provider:str="twitch"):
    key=(role or "").lower().strip().replace(" ","_")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);clock=world_clock(db,channel);pw=player_world(db,p)
        if not key:return out("🕒 Shift roles: "+", ".join(SHIFT_ROLES))
        if key not in SHIFT_ROLES:return out("🕒 Unknown role. Options: "+", ".join(SHIFT_ROLES))
        pw.shift_role=key;pw.shift_day=clock["day"];db.commit()
        bonus_note="No shift bonus while off duty." if key=="off_duty" else "Matching work gets +2 percentage points to the success chance today."
        return out(f"🕒 {p.display_name} takes {SHIFT_ROLES[key]} for Avesta Day {clock['day']}. {bonus_note}")

@app.get("/api/v1/conditions")
@game_transaction
def conditions(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);pw=player_world(db,p);rows=active_statuses(db,p)
        bits=[f"Siro exposure {pw.siro_exposure}/100"]+[f"{r.effect.replace('_',' ').title()} ({r.modifier:+d}%)" for r in rows]
        return out("🩺 "+p.display_name+" | "+" | ".join(bits))

@app.get("/api/v1/goal")
@game_transaction
def personal_goal(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    # /goal now shows the same Daily Contract as /contracts instead of
    # maintaining a second overlapping daily objective.
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);d=daily(db,p)
        state="COMPLETE" if d.complete else f"{d.progress}/{d.target}"
        cmd=("/" if provider=="discord" else "!")+d.action
        discord=f"🎯 {p.display_name} — Daily Goal\n\nTask: {cmd}\nProgress: {state}\nReward: {d.reward_sc} SC + 1 Contribution"+("\n\n✅ Complete for today." if d.complete else f"\n\nNext: use {cmd}.")
        twitch=f"🎯 Daily Goal | {cmd} {state} | Reward {d.reward_sc} SC +1 Contribution"
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/projectstatus")
@colony_command
def projectstatus(channel:str,provider:str="twitch"):
    with SessionLocal() as db:
        clock=world_clock(db,channel);row=current_project(db,channel,clock["day"]);cfg=project_cfg(row.project_key)
        skills=", ".join(SKILL_LABELS[x] for x in sorted(cfg[3]))
        return out(f"🏗️ {cfg[1]} | {row.progress}/{row.goal} | Useful aptitudes: {skills} | Completed projects: {row.completed}")

@app.get("/api/v1/bulletin")
@game_transaction
def bulletin(channel:str,provider:str="twitch"):
    with SessionLocal() as db:
        clock=world_clock(db,channel);proj=current_project(db,channel,clock["day"]);cfg=project_cfg(proj.project_key)
        directive,dcfg=directive_for(db,channel,clock["day"])
        aftermath=db.execute(select(SocietyAftermath).where(SocietyAftermath.channel_id==channel,SocietyAftermath.expires_at>now()).order_by(SocietyAftermath.expires_at.desc())).scalars().first()
        tasks=[
            f"Daily Directive: {dcfg[1]} {directive.progress}/{directive.goal} — use {', '.join(SKILL_LABELS[x] for x in sorted(dcfg[2]))}",
            f"Society Project: contribute with {', '.join(SKILL_LABELS[x] for x in cfg[3])}",
            f"World Condition: {clock['condition']} — {clock['condition_text']}",
            f"Community: bring a Pumpkin to the shared meal with {'/meal' if provider=='discord' else '!meal'}",
        ]
        if aftermath:tasks.append(f"Event Aftermath: {aftermath.event_name} {aftermath.modifier:+d}% related work until it expires")
        if provider=="discord":return PlainTextResponse("📌 New Eridian Bulletin\n\n"+"\n".join("• "+x for x in tasks))
        return out("📌 "+" | ".join(tasks))

@app.get("/api/v1/meal")
@colony_command
def meal(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);clock=world_clock(db,channel)
        if p.crops<=0:return out(f"🍲 You need 1 Pumpkin to contribute to the community meal. Pumpkins: {material_source('crops',provider)} Nothing spent.")
        row=db.execute(select(CommunityMeal).where(CommunityMeal.channel_id==channel,CommunityMeal.day==clock["day"])).scalar_one_or_none()
        if not row:row=CommunityMeal(channel_id=channel,day=clock["day"],contributions=0,completed=False);db.add(row)
        p.crops-=1;row.contributions+=1;life=life_state(db,p);life.social=clamp100(life.social+10);life.morale=clamp100(life.morale+3);life.nutrition=clamp100(life.nutrition+25)
        msg=f"🍲 {p.display_name} shares 1 Pumpkin. Meal progress {row.contributions}/12. +25 Nutrition/+10 Social/+3 Morale (capped at 100)."
        if row.contributions>=12 and not row.completed:
            row.completed=True;add_status(db,p,"community_fed",45,4,"A completed community meal is helping you feel prepared.");msg+=" 🎉 Community meal complete! You gain Community Fed +4% for 45 min."
        db.commit();journal_add(db,p,f"Contributed to the community meal on Day {clock['day']}.");return out(msg)

@app.get("/api/v1/mentor")
@colony_command
def mentor(channel:str,uid:str,name:str="Citizen",target:str="",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);clock=world_clock(db,channel);pw=player_world(db,p)
        if pw.mentor_day==clock["day"]:return out("🧑‍🏫 You have already mentored someone today.")
        target_p,error=find_player_name(db,channel,target)
        if error:return out("🧑‍🏫 "+error)
        if target_p.twitch_uid==p.twitch_uid:return out("🧑‍🏫 Mentoring yourself is called reading your own notes.")
        fields=[(key,skill_xp(target_p,key)) for key in SKILL_LABELS]
        skill=min(fields,key=lambda x:x[1])[0]
        # A mentor has to be better at the skill than the learner, so a fresh second account cannot hand its main
        # free XP every day.
        if lvl(skill_xp(p,skill))<=lvl(skill_xp(target_p,skill)):
            return out(f"🧑‍🏫 To mentor {target_p.display_name} in {SKILL_LABELS[skill]} you need a higher level than theirs (you Lv.{lvl(skill_xp(p,skill))}, them Lv.{lvl(skill_xp(target_p,skill))}). Nothing changed.")
        mentored_gain=gain_skill(target_p,skill,2);p.contribution+=2;pw.mentor_day=clock["day"];db.commit()
        journal_add(db,p,f"Mentored {target_p.display_name} in {SKILL_LABELS[skill]}.")
        return out(f"🧑‍🏫 {p.display_name} mentors {target_p.display_name}. {target_p.display_name} gains +{mentored_gain} {SKILL_LABELS[skill]} competency XP; mentor gains +2 Contribution.")

@app.get("/api/v1/journal")
@game_transaction
def journal(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        rows=db.execute(select(JournalEntry).where(JournalEntry.channel_id==channel,JournalEntry.canonical_uid==p.twitch_uid).order_by(JournalEntry.created_at.desc()).limit(8)).scalars().all()
        if not rows:return out("📓 Journal is empty. Important discoveries and milestones will appear here.")
        if provider=="discord":return PlainTextResponse("📓 Journal\n\n"+"\n".join("• "+r.entry for r in rows))
        return out("📓 "+" | ".join(r.entry for r in rows[:5]))

@app.get("/api/v1/link/create")
@game_transaction
def link_create(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        c=resolve(db,channel,provider,uid);record_account_name(db,channel,provider,uid,name);code="".join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(6))
        db.add(LinkCode(channel_id=channel,canonical_uid=c,code=code,expires_at=now()+timedelta(minutes=15)));db.commit()
        return out(f"🔗 Link code {code}. In Discord use /link {code} within 15 minutes.")

@app.get("/api/v1/link/claim")
@game_transaction
def link_claim(channel:str,discord_uid:str,name:str="Citizen",code:str=""):
    with SessionLocal() as db:
        record_account_name(db,channel,"discord",discord_uid,name)
        r=db.execute(select(LinkCode).where(LinkCode.channel_id==channel,LinkCode.code==code.upper())).scalar_one_or_none()
        if not r:
            elsewhere=db.execute(select(LinkCode.channel_id).where(LinkCode.code==code.upper())).scalar_one_or_none()
            if elsewhere:
                # The code was made in another world: Twitch's channel ID is not DISCORD_WORLD_ID, so linking can never work.
                RUNTIME_WARNINGS.add(f"A !link code from channel {elsewhere} was used on Discord, whose world is {channel}: Twitch and Discord do not share one world. "
                                     f"Merge them (do not only set DISCORD_WORLD_ID={elsewhere}: that hides every Discord character): open "
                                     f"/api/v1/admin/world-merge?source={channel}&target={elsewhere}&key=<ADMIN_KEY> to preview, then add &confirm=1.")
                return out("⛔ That code is from a different New Eridian world, so it cannot link here. Ask a moderator to check the game's /health page (DISCORD_WORLD_ID).")
        if not r or as_utc(r.expires_at)<now():return out("⛔ Invalid or expired code.")
        discord_link=db.execute(select(AccountLink).where(AccountLink.channel_id==channel,AccountLink.discord_uid==discord_uid)).scalar_one_or_none()
        twitch_link=db.execute(select(AccountLink).where(AccountLink.channel_id==channel,AccountLink.twitch_uid==r.canonical_uid)).scalar_one_or_none()
        if discord_link and discord_link.twitch_uid!=r.canonical_uid:return out("⛔ This Discord account is already permanently linked to another Twitch character.")
        if twitch_link and twitch_link.discord_uid!=discord_uid:return out("⛔ This Twitch character is already permanently linked to another Discord account.")
        x=db.execute(select(Identity).where(Identity.channel_id==channel,Identity.provider=="discord",Identity.provider_uid==discord_uid)).scalar_one_or_none()
        orphan_uid="discord:"+discord_uid
        orphan=db.execute(select(Player).where(Player.channel_id==channel,Player.twitch_uid==orphan_uid)).scalar_one_or_none()
        # Prefer a legacy Discord-only row so accounts linked before v5.1.1 can relink once and recover it.
        source_uid=orphan_uid if orphan else (x.canonical_uid if x else orphan_uid)
        merged=merge_accounts(db,channel,source_uid,r.canonical_uid)
        if x:x.canonical_uid=r.canonical_uid
        else:db.add(Identity(channel_id=channel,provider="discord",provider_uid=discord_uid,canonical_uid=r.canonical_uid))
        if not discord_link and not twitch_link:db.add(AccountLink(channel_id=channel,twitch_uid=r.canonical_uid,discord_uid=discord_uid))
        db.delete(r);db.commit()
        return out("✅ Discord and Twitch linked. Both characters' stats and progress were merged." if merged else "✅ Discord linked to your Twitch New Eridian character.")

@app.get("/api/v1/society")
@colony_command
def soc(channel:str,provider:str="twitch",viewer:str=""):
    with SessionLocal() as db:
        s=society(db,channel);tier=society_tier(s)
        personal=f"{clean(viewer)}, your society currently needs the most help with {min({'Food':s.food,'Materials':s.materials,'Development':s.development,'Knowledge':s.knowledge,'Treasury':s.treasury,'Reputation':s.reputation},key=lambda k:{'Food':s.food,'Materials':s.materials,'Development':s.development,'Knowledge':s.knowledge,'Treasury':s.treasury,'Reputation':s.reputation}[k])}.\n\n" if viewer else ""
        discord=(f"🏙️ {s.name} — Society Status\n\n{personal}🏛️ Tier: {tier[0]}\n👥 Population: {s.population}\n\n"
                 f"📦 CORE RESOURCES\n🌾 Food: {s.food} · ⛏️ Materials: {s.materials}\n🏗️ Development: {s.development} · 🔬 Knowledge: {s.knowledge}\n"
                 f"🪙 Treasury: {s.treasury} · ⭐ Reputation: {s.reputation}\n\n💰 Tier pay bonus: +{tier[2]} SC\nUse /society section:Next Tier Progress to see the next tier.")
        discord+="\n\nSHARED HOUSING\n"+housing_status_text(colony_state(db,channel),s,provider,True)
        twitch=f"🏙️ {s.name} — {tier[0]} | 🌾{s.food} Food · ⛏️{s.materials} Materials · 🏗️{s.development} Development · 🔬{s.knowledge} Knowledge · 🪙{s.treasury} Treasury · ⭐{s.reputation} Reputation · 👥{s.population} | Tier bonus +{tier[2]} SC"
        return platform_response(provider,discord,twitch)

@app.get("/api/v1/event")
@game_transaction
def event(channel:str,provider:str="twitch",viewer:str=""):
    with SessionLocal() as db:
        s=society(db,channel);w=world(db,channel);expired=resolve_expired_event(db,s,w)
        if expired:return out(expired)
        if not w.active_event:return out("🚨 No active live event.")
        cfg=EVENTS[w.active_event];seconds=max(0,int((as_utc(w.event_ends)-now()).total_seconds()));pct=int((w.event_progress/w.event_goal)*100) if w.event_goal else 0;leaders=event_contributors(db,w)
        penalty=stat_changes_text(cfg["penalty"],"−")
        if provider=="discord":
            return PlainTextResponse(f"🚨 {cfg['emoji']} {cfg['name']}\n\n"+(f"{clean(viewer)}, New Eridian needs your response.\n\n" if viewer else "")+f"📊 STATUS\nProgress: {w.event_progress}/{w.event_goal} ({pct}%)\nTime remaining: {seconds//60}:{seconds%60:02d}\n\n🎯 HOW TO HELP\nPrimary: {SKILL_LABELS[cfg['primary']]} — each success adds +1\n  {EVENT_WORK.get(cfg['primary'],'')}\nSupport: {SKILL_LABELS[cfg['support']]} — {w.event_support_successes}/2 toward +1\n  {EVENT_WORK.get(cfg['support'],'')}\nQueues and Seedlings count too.\n\n⚠️ Full failure penalty: {penalty}\n🏅 Leaders: {leader_text(leaders)}\n\nUse /guide goal:event for your personal best available command.")
        primary=SKILL_LABELS.get(cfg["primary"],cfg["primary"].title());support=SKILL_LABELS.get(cfg["support"],cfg["support"].title())
        return out(f"🚨 {cfg['emoji']} {cfg['name']} {pct}% | {w.event_progress}/{w.event_goal} | {seconds//60}:{seconds%60:02d} | Primary {primary} | Support {support} {w.event_support_successes}/2 | Penalty {penalty} | Leaders {leader_text(leaders)}")

@app.get("/api/v1/eventhistory")
@game_transaction
def eventhistory(channel:str,provider:str="twitch"):
    with SessionLocal() as db:
        rows=db.execute(select(EventHistory).where(EventHistory.channel_id==channel).order_by(EventHistory.ended_at.desc()).limit(5)).scalars().all()
        if not rows:return out("📜 No completed event history yet.")
        lines=[f"{r.result.upper()} · {r.event_name} {r.progress}/{r.goal} · {r.participants} participants · started {r.started_by} · ended {r.ended_by}" for r in rows]
        return PlainTextResponse("📜 New Eridian Event History\n"+"\n".join(lines)) if provider=="discord" else out("📜 "+" | ".join(lines[:3]))

@app.get("/api/v1/leaderboard")
@game_transaction
def leaderboard(channel:str,provider:str="twitch",uid:str="",name:str="Citizen"):
    with SessionLocal() as db:
        viewer=None
        if uid:_,viewer=player(db,channel,provider,uid,name)
        all_players=db.execute(select(Player).where(Player.channel_id==channel).order_by(Player.contribution.desc(),Player.id)).scalars().all()
        if not all_players:return out("🏆 No citizens ranked yet.")
        lines=[f"{i}. {p.display_name} — {p.contribution} contribution" for i,p in enumerate(all_players[:10],1)]
        personal=""
        if viewer:
            rank=next((i for i,p in enumerate(all_players,1) if p.twitch_uid==viewer.twitch_uid),len(all_players));personal=f"\n\n{viewer.display_name}, you are ranked #{rank} with {viewer.contribution} Contribution."
        return PlainTextResponse("🏆 New Eridian Contributors\n\n"+"\n".join(lines)+personal) if provider=="discord" else out("🏆 "+" | ".join(lines[:5]))
