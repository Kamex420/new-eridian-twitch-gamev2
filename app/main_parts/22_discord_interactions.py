# app/main.py, part 22: discord interactions
# Discord command dispatch (_discord_call_internal) and the interactions webhook.
# Runs inside app.main's namespace, after the parts before it (see main.py). Not a module of its own.

# Options a screen's own buttons set that are not typed in the slash command: a page of a skill's training tasks.
SCREEN_OPTIONS={'training':{'page'}}

def _discord_call_internal(command: str, uid: str, name: str, options: dict, interaction_id: str):
    command,options=discord_legacy_route(command,options)
    screen={k:v for k,v in options.items() if k in SCREEN_OPTIONS.get(command,())}
    options,error=_discord_validate_options(command,{k:v for k,v in options.items() if k not in screen})
    if error:return error
    options={**options,**screen}
    # Reuse the same game functions the Twitch API uses.
    channel = DISCORD_WORLD_ID
    if command=='use':
        import sys
        with SessionLocal() as db:
            _,p=player(db,channel,'discord',uid,name)
            category=str(options.get('category') or '')
            if not options.get('item'):
                menu=seed_content.use_menu(sys.modules[__name__],db,p,category,int(options.get('page') or 1))
                return menu if category else menu+'\n\n'+item_command_menu('use',uid,name)
            chosen=seed_content.find_item(str(options['item']))
            if category and seed_content.CATEGORY.get(chosen)!=category:return 'ℹ️ That item is not in this category. Nothing spent.'
    if command=='mine' and options.get('action')=='mine' and not options.get('ore'):return 'Choose Ore before selecting Mine. No queue was started.'
    if command=='queue' and options.get('action') in {'start','next'} and not options.get('task'):return 'Choose Task before selecting Start or Queue next. No queue was started.'
    selectors={"eat":"food","use":"item","delivery":"action","meal":"action", "repair":"target",
               "research":"operation","farm":"action","spaceport":"operation","explore":"operation","market":"action","social":"action"}
    if command in selectors and (not options.get(selectors[command]) or
            (command in {"delivery","meal"} and options.get("action")=="view") or
            (command=="repair" and options.get("target")=="gear" and not options.get("item"))):
        return item_command_menu(command,uid,name)
    if command=="eat":
        return action("eat",channel,uid,name,msg="food:"+str(options["food"]),provider="discord").body.decode()
    if command=="recover":
        return recover_needs(channel,uid,name,"discord").body.decode()
    if command in community.DISCORD|community.MOD:
        return community.discord(__import__("sys").modules[__name__],command,uid,name,options)
    if command=="menu":
        return game_menu.home_text(__import__("sys").modules[__name__],uid,name)
    if command=="menupanel":
        target=task_queue.queue_notifications.origin_channel.get() or DISCORD_GAME_CHANNEL_ID
        if ui.post_public_panel(__import__("sys").modules[__name__],target):
            return "🎛️ Posted the game panel in this channel. Anyone can press it to open their own private menu. Pin it so it stays on top."
        return "⚠️ The game panel could not be posted. Check that the bot can send messages here and that DISCORD_BOT_TOKEN is set."
    if command=="guidepanels":
        from . import guide_panels
        target=task_queue.queue_notifications.origin_channel.get() or DISCORD_GAME_CHANNEL_ID
        sent=guide_panels.post(target)
        total=len(guide_panels.PANELS)
        if sent==total:return f"📖 Posted all {total} guide panels in this channel."
        return (f"⚠️ Posted {sent} of {total} guide panels. Check that the bot can send messages here and that DISCORD_BOT_TOKEN is set. "
                "docs/discord-guide-panels.txt has the same panels to paste by hand.")

    if command=='mine':
        return mining(channel,uid,name,str(options.get('ore') or ''),str(options.get('action') or 'view'),int(options.get('count') or 1),'discord').body.decode()
    if command=='queue':
        return queued_tasks(channel,uid,name,str(options.get('action') or 'view'),str(options.get('task') or ''),int(options.get('count') or 1),'discord').body.decode()
    if command=='workshop':
        return workshop(channel,uid,name,str(options.get('action') or 'view'),str(options.get('station') or ''),int(options.get('page') or 1),'discord').body.decode()
    if command in {'catalog','gather'}:
        return seed_supplies(channel,uid,name,command,str(options.get('item') or options.get('resource') or ''),int(options.get('page') or 1),bool(options.get('owned',False)),'discord',str(options.get('category') or '')).body.decode()
    if command == "holiday":
        from .seasonal import holiday_message
        return holiday_message()
    if command == "training":
        try:page=max(1,int(options.get('page') or 1))
        except (TypeError,ValueError):page=1
        return training(channel,uid,name,str(options.get('skill') or ''),str(options.get('task') or ''),'discord',page=page).body.decode()
    if command == "seed":
        return discord_seed_help(str(options.get("topic") or "overview"),name)
    if command == "start":
        return start(channel=channel, uid=uid, name=name, provider="discord").body.decode("utf-8")
    if command == "guide":
        return guide(channel=channel,uid=uid,name=name,goal=str(options.get("goal") or "auto"),provider="discord").body.decode("utf-8")
    if command == "me":
        section=str(options.get("section") or "overview").lower()
        if section=="display":return display_style(channel=channel,uid=uid,name=name,style=str(options.get("style") or ""),provider="discord").body.decode("utf-8")
        if section=="life":return life_status(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="bonuses":return bonuses(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="cooldowns":return cooldowns(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="traits":return traits(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="relationships":return relationships(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="journal":return journal(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="tutorial":return tutorial(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="titles":return titles(channel=channel,uid=uid,name=name,title=str(options.get("title") or ""),provider="discord").body.decode("utf-8")
        return profile(channel=channel, uid=uid, name=name, provider="discord").body.decode("utf-8")
    if command == "progress":
        section=str(options.get("section") or "skills").lower()
        if section=="daily":return contracts(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="achievements":return achievements(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="collection":return collection(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        return skills(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
    if command == "inventory":
        if str(options.get("section") or "all").lower()=="gear":
            return gear(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        return inventory(channel=channel, uid=uid, name=name, provider="discord",search=str(options.get("search") or ""),
                         sort=str(options.get("sort") or ""),show=str(options.get("show") or ""),page=int(options.get("page") or 1)).body.decode("utf-8")
    if command == "status":
        return status_view(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
    if command == "settings":
        return settings(channel=channel,uid=uid,name=name,alerts=str(options.get("alerts") or ""),autorecover=str(options.get("autorecover") or ""),provider="discord",popups=str(options.get("popups") or ""),feed=str(options.get("feed") or "")).body.decode("utf-8")
    if command == "inbox":
        from . import inbox as player_inbox
        with SessionLocal() as db:
            _,p=player(db,channel,"discord",uid,name)
            text=player_inbox.inbox_text(__import__("sys").modules[__name__],db,p)
            player_inbox.mark_all_seen(db,p.channel_id,p.twitch_uid);db.commit()
            return text
    if command == "seedlingstep":
        with SessionLocal() as db:
            _,p=player(db,channel,"discord",uid,name);key=(p.channel_id,p.twitch_uid);db.commit()
        text=autonomy.live_one(__import__("sys").modules[__name__],key[0],key[1],force=True)
        with SessionLocal() as db:
            _,p=player(db,channel,"discord",uid,name)
            view=autonomy.view_text(__import__("sys").modules[__name__],db,p);db.commit()
        return ("🎲 YOUR SEEDLING DECIDED\n"+text+"\n\n" if text else "🎲 Your Seedling is busy with your queue right now.\n\n")+view
    if command == "seedling":
        if options.get("schedule"):seedling_schedule(channel,uid,name,str(options["schedule"]),"discord")
        if options.get("autonomy"):seedling_autonomy(channel,uid,name,str(options["autonomy"]),"discord")
        if str(options.get("section") or "")=="diary":return seedling_diary(channel,uid,name,"discord").body.decode()
        return seedling_view(channel,uid,name,"discord").body.decode()
    if command == "customize":
        from . import looks
        return seedling_looks(channel,uid,name,provider="discord",**{k:str(options.get(k) or "") for k in looks.FIELDS}).body.decode()
    if command == "eatfull":
        return eat_full(channel,uid,name,"discord").body.decode()
    if command == "trick":
        return trick_or_treat(channel,uid,name,"discord").body.decode()
    if command == "undo":
        return undo_sale(channel,uid,name,"discord").body.decode()
    if command == "find":
        query=str(options.get("query") or "").strip()[:ask.MAX_QUERY] or "?"
        module=__import__("sys").modules[__name__]   # this function imports sys locally further down
        with SessionLocal() as db:
            p=ask.existing_player(module,db,channel,"discord",uid)
            text=ask.reply(module,db,p,query,"discord",channel)
            db.commit()
        return text
    if command == "asklog":
        with SessionLocal() as db:
            return ask.log_text(__import__("sys").modules[__name__],db)
    if command == "queuedetails":
        with SessionLocal() as db:
            _,p=player(db,channel,"discord",uid,name)
            return task_queue.status(__import__("sys").modules[__name__],db,p,db.get(task_queue.TaskQueue,(p.channel_id,p.twitch_uid)),detail=True)
    if command == "job":
        return job(channel=channel, uid=uid, name=name, job=str(options.get("job") or ""), provider="discord").body.decode("utf-8")
    if command == "home":
        if str(options.get("action") or "view").lower()=="upgrade":
            return homeup(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        return home(channel=channel, uid=uid, name=name, provider="discord").body.decode("utf-8")
    if command == "business":
        business_action=str(options.get("action") or "view").lower()
        if business_action=="start":
            return business_start(channel=channel,uid=uid,name=name,business_name=str(options.get("name") or "New Venture"),provider="discord").body.decode("utf-8")
        if business_action in {"work","contract","invest"}:
            action_name={"work":"business","contract":"businesscontract","invest":"businessinvest"}[business_action]
            return action(action=action_name,channel=channel,uid=uid,name=name,msg=f"discord-{interaction_id}",provider="discord").body.decode("utf-8")
        return business(channel=channel, uid=uid, name=name, provider="discord").body.decode("utf-8")
    if command == "make":
        # Discord previews a selected recipe first; Craft and Queue are explicit.
        return make(
            channel=channel, uid=uid, name=name,
            recipe=str(options.get("recipe") or ""),
            category=str(options.get("category") or ""),
            page=int(options.get("page") or 1),provider="discord",
            station=str(options.get("station") or ""),
            action=str(options.get("action") or "preview"),
            count=int(options.get("count") or 1)
        ).body.decode("utf-8")
    if command == "seedindustries":
        return seed_industries(
            channel=channel,uid=uid,name=name,
            action=str(options.get("action") or "browse"),
            item_name=str(options.get("item") or ""),
            amount=int(options.get("amount") or 1),provider="discord",page=int(options.get("page") or 1),category=str(options.get("category") or "all")
        ).body.decode("utf-8")
    if command == "farm":
        farm_action=str(options.get("action") or "tend").lower()
        action_name={"tend":"farm","harvest":"harvest","irrigate":"water","hydroponics":"water"}.get(farm_action,"farm")
        marker="mode:hydroponics" if farm_action=="hydroponics" else f"discord-{interaction_id}"
        return action(action=action_name,channel=channel,uid=uid,name=name,msg=marker,provider="discord").body.decode("utf-8")
    if command == "research":
        operation=str(options.get("operation") or "standard").lower();marker="mode:field_analysis" if operation=="field_analysis" else f"discord-{interaction_id}"
        return action(action="research",channel=channel,uid=uid,name=name,msg=marker,provider="discord").body.decode("utf-8")
    if command == "spaceport":
        operation=str(options.get("operation") or "standard").lower();marker="mode:expedite" if operation=="expedite" else f"discord-{interaction_id}"
        return action(action="spaceport",channel=channel,uid=uid,name=name,msg=marker,provider="discord").body.decode("utf-8")
    if command == "explore":
        operation=str(options.get("operation") or "scout").lower();action_name="survey" if operation=="survey" else "explore"
        return action(action=action_name,channel=channel,uid=uid,name=name,msg=f"discord-{interaction_id}",provider="discord").body.decode("utf-8")
    if command == "repair":
        if str(options.get("target") or "society").lower()=="gear":
            return gearrepair(channel=channel,uid=uid,name=name,item=str(options.get("item") or ""),provider="discord").body.decode("utf-8")
        return action(action="repair",channel=channel,uid=uid,name=name,msg=f"discord-{interaction_id}",provider="discord").body.decode("utf-8")
    if command == "market":
        market_action=str(options.get("action") or "view").lower()
        if market_action=="view":return marketboard(channel=channel,provider="discord").body.decode("utf-8")
        if market_action=="sell":return seed_industries(channel,uid,name,"sell",str(options.get("resource") or options.get("item") or ""),int(options.get("amount") or 1),"discord").body.decode("utf-8")
        marker="mode:analyze" if market_action=="analyze" else f"discord-{interaction_id}"
        return action(action="market",channel=channel,uid=uid,name=name,msg=marker,provider="discord").body.decode("utf-8")
    if command == "social":
        if not options.get("action"):
            return "🤝 Choose /social action:Say Hi, Hang Out, Mentor, a Duo activity, or Use Recreation Set. Select player for relationship activities. For free solo Social recovery, use /games (+25 Social)."
        social_action=str(options.get("action") or "hi").lower();target=str(options.get("player") or "")
        if social_action=="hi":return hi(channel=channel,uid=uid,name=name,target=target,provider="discord").body.decode("utf-8")
        if social_action=="hangout":return hangout(channel=channel,uid=uid,name=name,target=target,provider="discord").body.decode("utf-8")
        if social_action=="mentor":return mentor(channel=channel,uid=uid,name=name,target=target,provider="discord").body.decode("utf-8")
        if social_action=="group_games":return use_item(channel=channel,uid=uid,name=name,item="recreation_set",provider="discord").body.decode("utf-8")
        if social_action.startswith("duo_"):
            return duo(channel=channel,uid=uid,name=name,target=target,activity=social_action[5:],provider="discord").body.decode("utf-8")
        return "⛔ Unknown social activity."
    if command == "hi":
        return hi(channel=channel,uid=uid,name=name,target=str(options.get("player") or ""),provider="discord").body.decode("utf-8")
    if command == "hangout":
        return hangout(channel=channel,uid=uid,name=name,target=str(options.get("player") or ""),provider="discord").body.decode("utf-8")
    if command == "relax":
        return relax(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
    if command == "walk":
        return walk(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
    if command == "games":
        return games(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
    if command == "hobby":
        return hobby(channel=channel,uid=uid,name=name,hobby=str(options.get("hobby") or ""),provider="discord").body.decode("utf-8")
    if command == "world":
        section=str(options.get("section") or "overview").lower()
        if section=="conditions":return conditions(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="rumor":return rumor(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
        if section=="bulletin":return bulletin(channel=channel,provider="discord").body.decode("utf-8")
        if section=="story":return story(channel=channel,provider="discord").body.decode("utf-8")
        if section=="project":return projectstatus(channel=channel,provider="discord").body.decode("utf-8")
        if section=="market":return marketboard(channel=channel,provider="discord").body.decode("utf-8")
        return world_status(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
    if command == "district":
        return district(channel=channel,uid=uid,name=name,district=str(options.get("district") or ""),provider="discord").body.decode("utf-8")
    if command == "shift":
        return shift(channel=channel,uid=uid,name=name,role=str(options.get("role") or ""),provider="discord").body.decode("utf-8")
    if command == "meal":
        return meal(channel=channel,uid=uid,name=name,provider="discord").body.decode("utf-8")
    if command == "mentor":
        return mentor(channel=channel,uid=uid,name=name,target=str(options.get("player") or ""),provider="discord").body.decode("utf-8")
    if command == "sell":
        return sell(channel=channel,uid=uid,name=name,resource=str(options.get("resource") or ""),amount=int(options.get("amount") or 1),provider="discord").body.decode("utf-8")
    if command == "duo":
        return duo(channel=channel,uid=uid,name=name,target=str(options.get("player") or ""),activity=str(options.get("activity") or "walk"),provider="discord").body.decode("utf-8")
    if command == "ducks":
        return ducks(channel=channel,uid=uid,name=name,duck=str(options.get("duck") or ""),provider="discord").body.decode("utf-8")
    if command == "gearrepair":
        return gearrepair(channel=channel,uid=uid,name=name,item=str(options.get("item") or ""),provider="discord").body.decode("utf-8")
    if command == "use":
        return use_item(channel=channel,uid=uid,name=name,item=str(options.get("item") or ""),provider="discord").body.decode("utf-8")
    if command == "linklookup":
        with SessionLocal() as db:
            return owner_link_lookup(db,channel,str(options.get("player") or ""))
    if command == "link":
        return link_claim(
            channel=channel,
            discord_uid=uid,
            name=name,
            code=str(options.get("code") or "")
        ).body.decode("utf-8")
    if command == "specialize":
        return specialize(channel=channel,uid=uid,name=name,path=str(options.get("path") or ""),provider="discord").body.decode("utf-8")
    if command == "society":
        section=str(options.get("section") or "overview").lower()
        if section=="progress":return progress(channel=channel,provider="discord",viewer=name).body.decode("utf-8")
        if section=="leaderboard":return leaderboard(channel=channel,provider="discord",uid=uid,name=name).body.decode("utf-8")
        return soc(channel=channel,provider="discord",viewer=name).body.decode("utf-8")
    if command == "event":
        if str(options.get("section") or "status").lower()=="history":
            return eventhistory(channel=channel,provider="discord").body.decode("utf-8")
        return event(channel=channel,provider="discord",viewer=name).body.decode("utf-8")
    if command == "modlog":
        with SessionLocal() as db:
            rows=db.execute(select(ModeratorAudit).where(ModeratorAudit.channel_id==channel).order_by(ModeratorAudit.created_at.desc()).limit(10)).scalars().all()
            return "🛡️ No moderator actions recorded." if not rows else "🛡️ Moderator Log\n"+"\n".join(f"{r.moderator}: {r.action} — {r.detail}" for r in rows)
    if command == "eventstart":
        event_key=str(options.get("event") or "").lower()
        if event_key not in EVENTS:return "⛔ Unknown event."
        with SessionLocal() as db:
            s=society(db,channel);w=world(db,channel);resolve_expired_event(db,s,w)
            if w.active_event:return "⛔ An event is already active. Use /eventstop first."
            actor=f"{name} ({uid})";result=start_event(db,w,event_key,actor);audit_moderator(db,channel,actor,"eventstart",event_key);return result
    if command == "eventstop":
        with SessionLocal() as db:
            actor=f"{name} ({uid})";w=world(db,channel);event_key=w.active_event or "none";result=cancel_event(db,w,actor);audit_moderator(db,channel,actor,"eventstop",event_key);return result

    action_name = {"farm":"farm","fabricate":"machine"}.get(command,command)
    return action(
        action=action_name,
        channel=channel,
        uid=uid,
        name=name,
        msg=f"discord-{interaction_id}",
        provider="discord"
    ).body.decode("utf-8")

def _discord_answer(answer,payload,background_tasks):
    """A button or form answer: acknowledged at once and sent right after (before any popups), in the layout
    its message needs, with the old layout as a fallback (discord_deferred.defer, layout_v2)."""
    from starlette.background import BackgroundTask
    def first(fn,*args):background_tasks.tasks.insert(0,BackgroundTask(fn,*args))
    return layout_v2.respond(discord_deferred.defer(answer,payload,first),payload)

@app.post("/discord/interactions")
async def discord_interactions(request: Request, background_tasks: BackgroundTasks):
    if not DISCORD_PUBLIC_KEY:
        raise HTTPException(status_code=500, detail="DISCORD_PUBLIC_KEY is not configured")

    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")
    body = await request.body()

    try:
        verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        verify_key.verify(timestamp.encode() + body, bytes.fromhex(signature))
    except (BadSignatureError, ValueError):
        raise HTTPException(status_code=401, detail="invalid request signature")

    payload = await request.json()

    # Discord endpoint validation / ping.
    if payload.get("type") == 1:
        return {"type": 1}

    # Discord sends type 4 while a user is opening/searching an autocomplete option.
    if payload.get("type") == 4:
        if not _discord_allowed_channel(payload):
            return {"type":8,"data":{"choices":[]}}
        return _discord_autocomplete(payload)

    if payload.get("type") == 3:
        if not _discord_allowed_channel(payload):
            return layout_v2.respond({"type":4,"data":{"content":"Use the designated game channel.","flags":64}},payload)
        if discord_deferred.can_answer_later(payload):
            # Acknowledge at once and do the work right after: a press never times out.
            background_tasks.add_task(discord_deferred.answer_later,sys.modules[__name__],payload)
            return discord_deferred.ack(payload)
        if ui.handles((payload.get("data") or {}).get("custom_id")):
            answer=await run_in_threadpool(ui.handle_component,sys.modules[__name__],payload,background_tasks.add_task)
        else:
            answer=await run_in_threadpool(message_layout.open_page,sys.modules[__name__],payload)
        return _discord_answer(answer,payload,background_tasks)

    # A submitted pop-up form (search, link code, business name, custom amount).
    if payload.get("type") == 5:
        if not _discord_allowed_channel(payload):
            return layout_v2.respond({"type":4,"data":{"content":"Use the designated game channel.","flags":64}},payload)
        if discord_deferred.can_answer_later(payload):
            background_tasks.add_task(discord_deferred.answer_later,sys.modules[__name__],payload)
            return discord_deferred.ack(payload)
        return _discord_answer(await run_in_threadpool(ui.handle_modal,sys.modules[__name__],payload,background_tasks.add_task),payload,background_tasks)

    # Application command.
    if payload.get("type") != 2:
        return layout_v2.respond(_discord_json_message("Unsupported Discord interaction.", ephemeral=True),payload)

    if not _discord_allowed_channel(payload):
        return layout_v2.respond(_discord_json_message(
            "🌱 New Eridian commands are only available in the designated game channel.",
            ephemeral=True
        ),payload)

    command = ((payload.get("data") or {}).get("name") or "").lower()
    uid, name = _discord_user(payload)
    options = _discord_options(payload)
    command, options = discord_legacy_route(command, options)
    interaction_id = str(payload.get("id") or "")

    if not uid:
        return layout_v2.respond(_discord_json_message("Could not identify your Discord account.", ephemeral=True),payload)

    if command not in (DISCORD_PUBLIC_COMMANDS | DISCORD_PRIVATE_COMMANDS):
        return layout_v2.respond(_discord_json_message("Unknown New Eridian command.", ephemeral=True),payload)

    if command in {"eventstart","eventstop","modlog","asklog","guidepanels","menupanel"}|community.MOD and not _discord_is_moderator(payload):
        return layout_v2.respond(_discord_json_message(_discord_owner_denied(uid), ephemeral=True, message_type="moderator"),payload)

    if command == "linklookup" and not _discord_is_owner(payload):
        return layout_v2.respond(_discord_json_message(
            f"⛔ Owner access is required for linked-account lookup. "
            f"Detected Discord ID: {uid} | Owner IDs loaded: {len(DISCORD_OWNER_USER_IDS)}. "
            f"Make sure Railway DISCORD_OWNER_USER_IDS contains this exact numeric ID, then redeploy.",
            ephemeral=True,
            message_type="moderator"
        ),payload)

    if not payload.get('application_id') or not payload.get('token'):
        return layout_v2.respond(_discord_json_message('Discord response details were missing. Please run the command again.',ephemeral=True),payload)
    background_tasks.add_task(discord_deferred.finish,sys.modules[__name__],payload,command,uid,name,options)
    private=discord_execution.private_response(sys.modules[__name__],command,options)
    return {'type':5,'data':{'flags':64} if private else {}}
