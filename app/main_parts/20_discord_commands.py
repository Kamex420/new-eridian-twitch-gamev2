# app/main.py, part 20: discord commands
# Discord command schema, legacy routes and copy, JSON messages, autocomplete and option checks.
# Runs inside app.main's namespace, after the parts before it (see main.py). Not a module of its own.

# The published flat option schema is also used to validate requests.
from .command_catalog import commands as DISCORD_COMMAND_CATALOG, legacy_commands as DISCORD_LEGACY_COMMANDS
# Registered commands plus retired ones that grouped commands translate into.
DISCORD_OPTION_SCHEMA = {row["name"]: row.get("options", []) for row in DISCORD_COMMAND_CATALOG+DISCORD_LEGACY_COMMANDS}
DISCORD_REGISTERED = {row["name"] for row in DISCORD_COMMAND_CATALOG}

# Grouped slash commands -> the original command and options they run.
WORK_ROUTES={"farm_tend":("farm",{"action":"tend"}),"farm_harvest":("farm",{"action":"harvest"}),
    "farm_irrigate":("farm",{"action":"irrigate"}),"farm_hydroponics":("farm",{"action":"hydroponics"}),
    "scan":("scan",{}),"rare":("rare",{}),"research":("research",{"operation":"standard"}),
    "field_analysis":("research",{"operation":"field_analysis"}),"cargo":("cargo",{}),
    "delivery":("delivery",{"action":"send"}),"spaceport":("spaceport",{"operation":"standard"}),
    "expedite":("spaceport",{"operation":"expedite"}),"scout":("explore",{"operation":"scout"}),
    "survey":("explore",{"operation":"survey"})}
WORLD_ROUTES={"society":("society",{"section":"overview"}),"society_progress":("society",{"section":"progress"}),
    "leaderboard":("society",{"section":"leaderboard"}),"event":("event",{"section":"status"}),
    "event_history":("event",{"section":"history"}),"holidays":("holiday",{})}

def discord_legacy_route(command,options):
    """Translate /life, /work, /mod and grouped /world and /me sections."""
    options=dict(options or {})
    if command=="life":
        action=str(options.get("action") or "")
        if not action:return "me",{"section":"life"}
        if action=="eat":return "eat",({"food":options["food"]} if options.get("food") else {})
        if action=="hobby":return "hobby",({"hobby":options["hobby"]} if options.get("hobby") else {})
        if action=="meal":return "meal",{"action":"share"}
        return action,{}
    if command=="work":
        return WORK_ROUTES.get(str(options.get("task") or ""),("training",{}))
    if command=="mod":
        action=str(options.get("action") or "modlog")
        if action=="eventstart":return "eventstart",({"event":options["event"]} if options.get("event") else {})
        if action=="challengestart":return "challengestart",({"challenge":options["challenge"]} if options.get("challenge") else {})
        if action=="linklookup":return "linklookup",({"player":options["player"]} if options.get("player") else {})
        return action,{}
    if command=="world" and options.get("section") in WORLD_ROUTES:
        return WORLD_ROUTES[options["section"]]
    if command=="me" and options.get("section") in {"skills","daily","achievements","collection"}:
        return "progress",{"section":options["section"]}
    return command,options

# Retired commands named in game text -> the grouped command players type now.
LEGACY_COPY=[("/farm action:Harvest Pumpkins","/work task:farm_harvest"),("/farm action:Tend Fields","/work task:farm_tend"),
    ("/farm action:Irrigate","/work task:farm_irrigate"),("/farm action:Hydroponics","/work task:farm_hydroponics"),
    ("/explore operation:Advanced Survey","/work task:survey"),("/explore operation:survey","/work task:survey"),
    ("/spaceport operation:expedite","/work task:expedite"),("/research operation:field_analysis","/work task:field_analysis"),
    ("/meal action:share","/life action:meal"),("/delivery action:send","/work task:delivery"),
    ("/society section:leaderboard","/world section:leaderboard"),("/society section:Next Tier Progress","/world section:society_progress"),
    ("/society section:progress","/world section:society_progress"),("/event section:history","/world section:event_history")]
LEGACY_BARE={"relax":"/life action:relax","sleep":"/life action:sleep","eat":"/life action:eat","games":"/life action:games",
    "walk":"/life action:walk","hobby":"/life action:hobby","meal":"/life action:meal","farm":"/work task:farm_tend",
    "scan":"/work task:scan","rare":"/work task:rare","research":"/work task:research","cargo":"/work task:cargo",
    "delivery":"/work task:delivery","spaceport":"/work task:spaceport","explore":"/work task:scout",
    "eventstart":"/mod action:eventstart","eventstop":"/mod action:eventstop","modlog":"/mod action:modlog",
    "linklookup":"/mod action:linklookup","society":"/world section:society","event":"/world section:event",
    "holiday":"/world section:holidays","progress":"/me section:skills"}

_RECIPE_LABELS=None
def recipe_display_labels():
    """Recipe ids (and retired legacy keys) shown as their item names in Discord copy."""
    global _RECIPE_LABELS
    if _RECIPE_LABELS is None:
        labels={e.id:e.name for e in workbench.index(sys.modules[__name__])}
        labels.update({old:labels[rid] for old,rid in item_identity.RETIRED_RECIPES.items() if rid in labels})
        labels.update({name:name for name in set(labels.values())})
        _RECIPE_LABELS=labels
    return _RECIPE_LABELS

def discord_command_copy(content):
    """Render registered command choices as readable menu instructions.

    Only command spans are changed; citizen names, item IDs and prose elsewhere
    retain their original spelling. Running this twice is harmless.
    """
    aliases = dict(DISCORD_ACTION_ROUTES)
    aliases.update({"skills":"/me section:skills", "contracts":"/me section:daily",
        "achievements":"/me section:achievements", "collection":"/me section:collection",
        "life":"/me section:life", "bonuses":"/me section:bonuses", "cooldowns":"/me section:cooldowns",
        "traits":"/me section:traits", "relationships":"/me section:relationships",
        "journal":"/me section:journal", "tutorial":"/me section:tutorial",
        "titles":"/me section:titles", "display":"/me section:display",
        "homeup":"/home action:upgrade", "homeupgrade":"/home action:upgrade",
        "businessstart":"/business action:start", "businesswork":"/business action:work",
        "gear":"/inventory section:gear", "recipes":"/make",
        "marketboard":"/market action:view", "projectstatus":"/world section:project",
        "eventhistory":"/world section:event_history", "leaderboard":"/world section:leaderboard",
        "conditions":"/world section:conditions", "story":"/world section:story",
        "bulletin":"/world section:bulletin", "rumor":"/world section:rumor"})
    text=str(content or "")
    # Match whole commands only; never substrings, URLs, fractions or backticks.
    pattern=r"(?<![\w`:/])/([a-z][a-z0-9_]*)(?![\w`])"
    for old,new in LEGACY_COPY:
        text=re.sub(r"(?<![\w`:/])"+re.escape(old)+r"(?![\w`])",new,text,flags=re.I)
    text=re.sub(r"(?<![\w`:/])/progress section:([A-Za-z_&]+(?: [A-Z][a-z]+)*)",lambda m:"/me section:"+m[1].split()[0].lower(),text)
    def route(m):
        if m[1] in DISCORD_REGISTERED:return m[0]
        found=aliases.get(m[1],m[0])
        name=found[1:].split(" ",1)[0] if found.startswith("/") else ""
        return LEGACY_BARE.get(name,found) if name not in DISCORD_REGISTERED else found
    text=re.sub(pattern,route,text)
    choice_aliases={
        ("home","action","view"):"view",("home","action","upgrade"):"upgrade",
        ("business","action","view"):"view",("business","action","start"):"start",
        ("seedindustries","action","orders"):"orders",("seedindustries","action","fulfill"):"fulfill",
        ("explore","operation","advanced survey"):"survey",("progress","section","skills"):"skills",
    }
    matches=list(re.finditer(pattern,text))
    for match in reversed(matches):
        command=match[1]
        if command not in DISCORD_REGISTERED:continue
        # Option values are confined to this command's sentence/line, before the next command.
        end=next((m.start() for m in matches if m.start()>match.start()),len(text))
        span=text[match.end():end]
        fields={row["name"]:row for row in DISCORD_OPTION_SCHEMA[command]}
        for field,row in fields.items():
            labels={str(c["value"]):c["name"] for c in row.get("choices",[])}
            candidates={key:label for key,label in labels.items()}
            candidates.update({label:label for label in labels.values()})
            for (cmd,opt,alias),value in choice_aliases.items():
                if cmd==command and opt==field and value in labels:candidates[alias]=labels[value]
            if field=="recipe":
                candidates.update(recipe_display_labels())
            if field=="station":
                candidates.update({tag:info["name"] for tag,info in crafting_progression.STATIONS.items()})
                candidates.update({info["name"]:info["name"] for info in crafting_progression.STATIONS.values()})
            # Longest label first, so e.g. Skills & Level Unlocks is not partially consumed.
            known="|".join(re.escape(k) for k in sorted(candidates,key=len,reverse=True))
            value_pattern=("(?:"+known+r")(?![\w])|" if known else "")+r"<[^>\n]+>|[A-Za-z0-9_]+"
            option_pattern=r"\b"+re.escape(field)+r":("+value_pattern+r")"
            def render(m):
                value=m[1]
                label=next((v for k,v in candidates.items() if k.casefold()==value.casefold()),None)
                if label and " · " in label and ("Energy" in label or ": " in label):label=label.split(": ")[0].split(" · ")[0]   # work choices: name only
                if label is None:
                    label=value if value.startswith("<") else value.replace("_"," ").title()
                return field.replace("_"," ").title()+": **"+label+"**"
            span=re.sub(option_pattern,render,span,flags=re.I)
        # The arrow separates the command to type from the dropdowns to choose.
        if re.match(r"\s*[A-Z][A-Za-z ]*: \*\*",span):span=" → "+span.lstrip()
        text=text[:match.start()]+"`/"+command+"`"+span+text[end:]
    return text


def _discord_json_message(content: str, ephemeral: bool = False, message_type: str = ""):
    content=discord_command_copy(content)
    command=(message_type or "").lower()
    status=discord_message_status(content)
    category=discord_message_category(command)
    keys=[f"{command}_{status}",command,status,category,"default"]
    custom=next((DISCORD_EMOJI_MAP[key] for key in keys if key in DISCORD_EMOJI_MAP),"")

    # IMPORTANT: Discord renders this as a true embed because the interaction
    # response uses the "embeds" array instead of plain "content".
    embed=_discord_pretty_embed(content,command,status)

    # Colored badges remain visible even when a mobile client hides embed borders.
    # Scope social color to the actual view, not a mention of "story" in a guide.
    tone=status
    menu=content.startswith(("🍽️ FOOD MENU","🎒 ITEM MENU"))
    first_line=content.splitlines()[0].lower() if content else ""
    if status=="info":
        if menu or command in {"make","guide"}:
            tone="action"
        elif command in {"social","hobby","ducks"} or any(word in first_line for word in ("weekly story","relationships","journal","lore")):
            tone="social"
    embed["color"]=_discord_embed_color(tone)
    badge={"success":"🟩","failure":"🟥","cooldown":"🟨","action":"🟨","social":"🟪","detail":"◻️"}.get(tone,"🟦")
    embed["title"]=_discord_clean_piece(badge+" "+re.sub(r"^[🟩🟥🟨🟦🟪]\s*","",embed.get("title","New Eridian v2")),256)
    for field in embed.get("fields",[]):
        field["inline"]=False
        name=field["name"]
        lower=name.lower()
        if any(word in lower for word in ("failed","danger","blocked","warning","risk")):mark="🟥"
        elif any(word in lower for word in ("reward","next","improve","action","recipe","supplies","cost")):mark="🟨"
        elif any(word in lower for word in ("story","lore","social","fleet","discovery","relationship","journal")):mark="🟪"
        elif any(word in lower for word in ("progress","growth","level","achievement")):mark="🟩"
        elif any(word in lower for word in ("detail","note","modifier")):mark="◻️"
        else:mark="🟦"
        name=re.sub(r"^[^\w]+", "", name)
        field["name"]=_discord_clean_piece(mark+" "+(name.capitalize() if name.isupper() else name),256)

    if custom:
        existing=embed.get("description","")
        embed["description"]=_discord_clean_piece((custom+" "+existing).strip(),1800)

    # Never let readable labels push an otherwise valid message over embed limits.
    # Reserve room for an explicit notice rather than silently dropping text.
    budget=5700-len(embed.get("title",""))-len(embed.get("description",""))-len(embed.get("footer",{}).get("text",""))
    kept=[];omitted=False
    for field in embed.get("fields",[]):
        size=len(field["name"])+len(field["value"])
        if len(kept)>=24 or size>budget:
            omitted=True;break
        kept.append(field);budget-=size
    if omitted:
        kept.append({"name":"More detail", "value":"This view is long. Choose a specific section, crafting category, or handbook topic to see its full details.", "inline":False})
    embed["fields"]=kept
    data=message_layout.render(sys.modules[__name__],embed,content,command)
    if ephemeral:
        data["flags"]=64
    return {"type":4,"data":data}

DISCORD_PERSONAL_DETAIL_COMMANDS=set(ACTION_SKILLS)|{
    "farm","fabricate",
    "businesswork","businesscontract","businessinvest",
    "duo","meal","mentor","sell","gearrepair","use"
}

def _discord_user(payload: dict):
    member = payload.get("member") or {}
    user = member.get("user") or payload.get("user") or {}
    uid = str(user.get("id") or "")
    name = (
        member.get("nick")
        or user.get("global_name")
        or user.get("username")
        or "Citizen"
    )
    return uid, name

DISCORD_HUB_SELECTORS={"seed":"topic","guide":"goal","me":"section","progress":"section",
 "inventory":"section","home":"action","business":"action","make":"category",
 "seedindustries":"action","world":"section","society":"section","event":"section",
 "social":"action","farm":"action","research":"operation","repair":"target",
 "spaceport":"operation","explore":"operation","market":"action"}

def _discord_flat_payload(payload):
    data=dict(payload.get("data") or {})
    options=data.get("options") or []
    branch=next((opt for opt in options if opt.get("type")==1),None)
    if branch:
        selector=DISCORD_HUB_SELECTORS.get(data.get("name"))
        if selector:
            value=branch.get("name","")
            if data.get("name")=="make" and value in {"browse","craft"}:value=""
            data["options"]=[{"name":selector,"value":value}]+list(branch.get("options") or [])
    return {**payload,"data":data}

def _discord_options(payload: dict):
    payload=_discord_flat_payload(payload)
    data = payload.get("data") or {}
    result = {}
    for opt in data.get("options") or []:
        result[opt.get("name")] = opt.get("value")
    return result

def _discord_autocomplete_choices(rows,query=""):
    q=str(query or "").lower().strip()
    choices=[]
    seen=set()
    for label,value in rows:
        label=str(label or "").strip()
        value=str(value or "").strip()
        if not label or not value or value in seen:continue
        if q and q not in label.lower() and q not in value.lower():continue
        choices.append({"name":label[:100],"value":value[:100]})
        seen.add(value)
        if len(choices)>=25:break
    return {"type":8,"data":{"choices":choices}}

def _discord_existing_player(payload):
    uid,name=_discord_user(payload)
    if not uid:return None,None,None
    with SessionLocal() as db:
        ident=db.execute(
            select(Identity).where(
                Identity.channel_id==DISCORD_WORLD_ID,
                Identity.provider=="discord",
                Identity.provider_uid==uid
            )
        ).scalar_one_or_none()
        canonical=ident.canonical_uid if ident else "discord:"+uid
        p=db.execute(
            select(Player).where(
                Player.channel_id==DISCORD_WORLD_ID,
                Player.twitch_uid==canonical
            )
        ).scalar_one_or_none()
        return uid,name,p

def _discord_player_autocomplete(payload,query=""):
    uid,_=_discord_user(payload)
    with SessionLocal() as db:
        identity=db.execute(select(Identity).where(Identity.channel_id==DISCORD_WORLD_ID,Identity.provider=='discord',Identity.provider_uid==uid)).scalar_one_or_none()
        own_uid=identity.canonical_uid if identity else 'discord:'+uid
        # Only the columns the menu needs; duplicates are counted once instead of comparing every pair per keystroke.
        rows=db.execute(
            select(Player.id,Player.twitch_uid,Player.display_name)
            .where(Player.channel_id==DISCORD_WORLD_ID)
            .order_by(Player.display_name)
        ).all()
        from collections import Counter
        names=Counter(r.display_name.casefold() for r in rows)
        data=[]
        for p in rows:
            if uid and p.twitch_uid==own_uid:continue
            if (payload.get('data') or {}).get('name')=='social':
                label=f"{p.display_name} · citizen #{p.id}" if names[p.display_name.casefold()]>1 else p.display_name
                data.append((label,f'citizen:{p.id}'))
            else:data.append((p.display_name,p.display_name))
        return _discord_autocomplete_choices(data,query)

def _discord_title_autocomplete(payload,query=""):
    _,_,p=_discord_existing_player(payload)
    if not p:return {"type":8,"data":{"choices":[]}}
    with SessionLocal() as db:
        rows=db.execute(
            select(PlayerTitle)
            .where(
                PlayerTitle.channel_id==DISCORD_WORLD_ID,
                PlayerTitle.canonical_uid==p.twitch_uid
            )
            .order_by(PlayerTitle.unlocked_at)
        ).scalars().all()
        data=[]
        for row in rows:
            label=TITLE_DEFS.get(row.title_key,row.title_key.replace("_"," ").title())
            if row.equipped:label="⭐ "+label
            data.append((label,row.title_key))
        return _discord_autocomplete_choices(data,query)

def _discord_gear_autocomplete(payload,query=""):
    _,_,p=_discord_existing_player(payload)
    if not p:return {"type":8,"data":{"choices":[]}}
    with SessionLocal() as db:
        rows=db.execute(
            select(QualityGear)
            .where(
                QualityGear.channel_id==DISCORD_WORLD_ID,
                QualityGear.canonical_uid==p.twitch_uid,
                QualityGear.qty>0
            )
            .order_by(QualityGear.item_name)
        ).scalars().all()
        data=[
            (f"{'✅' if p.components>=gear_repair_cost(x.condition) else '❌'} {x.quality} {x.item_name} ×{x.qty} — {x.condition}% · repair {gear_repair_cost(x.condition)} Iron Nails (have {p.components})",f"gear_{x.id}")
            for x in rows if x.condition<100
        ]
        return _discord_autocomplete_choices(data,query)

def _discord_make_autocomplete(payload:dict):
    """Recipes filtered by the chosen category/workstation, easiest first, with status."""
    options=(payload.get("data") or {}).get("options") or []
    values={str(opt.get("name") or ""):opt.get("value") for opt in options}
    focused=next((opt for opt in options if opt.get("focused")),{})
    query=str(focused.get("value") or "")
    category=workbench.normalize_category(values.get("category")) or ""
    _,_,current_player=_discord_existing_player(payload)
    with SessionLocal() as db:
        ctx=workbench.Context(sys.modules[__name__],db,current_player,"discord")
        if focused.get("name")=="station":
            return _discord_autocomplete_choices(workbench.station_rows(ctx,query))
        if focused.get("name")!="recipe":return {"type":8,"data":{"choices":[]}}
        station=workbench.find_station(values.get("station")) or ""
        return _discord_autocomplete_choices(workbench.autocomplete_rows(ctx,category,station,query))

def ore_choice_rows(db,p):
    """Mining dropdown: status, owned, needs per attempt, cooldown and locks."""
    harvesting=lvl(skill_xp(p,"extraction")) if p else 1
    rows=[]
    for key in sorted(task_queue.ores(),key=lambda k:(k in crafting_progression.RARE,seed_content.item_label(k))):
        owned=material_amount(db,p,key) if p else 0
        rare=key in crafting_progression.RARE
        energy=HEAVY_ENERGY if rare else STANDARD_ENERGY
        locked=rare and harvesting<crafting_progression.RARE_LEVEL
        progress=material_amount(db,p,"prospect:"+key) if p and rare else 0
        detail=(f" · 3 steps per ore ({progress}/3) · 20s" if rare else " · 5s")
        lock=" · needs Harvesting Lv3" if locked else ""
        rows.append((workbench.clip(f"{'🔒' if locked else '✅'} {seed_content.item_label(key)} ×{owned} · {energy} Energy, {comfort_cost(energy)} Comfort{detail}{lock}"),key))
    return rows

def queue_choice_rows(db,p,query=""):
    """Queue dropdown: every task with its icon, cost and (for recipes) status."""
    module=sys.modules[__name__];q=str(query or "").casefold().strip()
    ctx=workbench.Context(module,db,p)
    harvesting=lvl(skill_xp(p,"extraction")) if p else 1
    rows=[]
    for key,label in task_queue.choices(module).items():
        if q and q not in (label+" "+key).casefold():continue
        kind,target=key.split(":",1)
        if kind=="make":
            e=workbench.entry(module,target)
            if e is None:continue
            st=ctx.status(e)
            text=f"{st.emoji} Make {e.name} ×{ctx.batch_size(e)} · T{e.tier} {workbench.station_label(e,ctx)}"+("" if st.code=="ready" else f" · {st.short}")
            order=(3,workbench.STATUS_ORDER[st.code],e.sort_key)
        else:
            action,mode=task_yields.split(target) if kind=="work" else ("mine" if kind=="mine" else "gather","")
            energy=task_energy(action,mode) if kind=="work" else (HEAVY_ENERGY if target in crafting_progression.RARE else STANDARD_ENERGY)
            icon={"mine":"⛏️","gather":"🌿","work":"💼"}[kind]
            rare=kind=="mine" and target in crafting_progression.RARE
            locked=rare and harvesting<crafting_progression.RARE_LEVEL
            if locked:icon="🔒"
            text=f"{icon} {label} · {energy} Energy, {comfort_cost(energy)} Comfort/attempt"+(" · needs Harvesting Lv3" if locked else "")
            order=({"mine":0,"gather":1,"work":2}[kind],(2 if locked else 1 if rare else 0),label)
        rows.append((order,workbench.clip(text),key))
    return [(text,key) for _,text,key in sorted(rows,key=lambda r:r[0])]

def training_choice_label(db,p,key,cfg):
    """Training dropdown: status, have/need for each input, output and locks."""
    level=lvl(skill_xp(p,cfg["skill"])) if p else 1
    have={k:(material_amount(db,p,k) if p else 0) for k in cfg["cost"]}
    stock="; ".join(f"{resource_name(k)} {have[k]}/{v}" for k,v in cfg["cost"].items()) or "no items needed"
    output=", ".join(f"{v} {resource_name(k)}" for k,v in cfg["output"].items())
    if level<cfg["unlock"]:emoji,tail="🔒",f" · needs {SKILL_LABELS[cfg['skill']]} Lv{cfg['unlock']}"
    elif any(have[k]<v for k,v in cfg["cost"].items()):emoji,tail="❌",""
    else:emoji,tail="✅",""
    return workbench.clip(f"{emoji} {cfg['label']} — {stock}"+(f" → {output}" if output else "")+tail)

def _discord_autocomplete(payload:dict):
    import sys
    payload=_discord_flat_payload(payload)
    data=payload.get("data") or {}
    command=str(data.get("name") or "").lower()
    options=data.get("options") or []
    focused=next((opt for opt in options if opt.get("focused")),{})
    option=str(focused.get("name") or "").lower()
    query=str(focused.get("value") or "")
    selected=_discord_options(payload)
    if command=='life' and option=='food':command='eat'
    if command=='mod' and option=='player':command='linklookup'
    if command=='mine' and option=='ore':
        _,_,p=_discord_existing_player(payload)
        with SessionLocal() as db:
            return _discord_autocomplete_choices(ore_choice_rows(db,p),query)
    if command=='queue' and option=='task':
        _,_,p=_discord_existing_player(payload)
        with SessionLocal() as db:
            return _discord_autocomplete_choices(queue_choice_rows(db,p,query),"")
    if command=='social' and option=='player' and selected.get('action')=='group_games':return _discord_autocomplete_choices([])
    if command=='me' and option=='title' and selected.get('section') not in {None,'','titles'}:return _discord_autocomplete_choices([])
    if command=='repair' and option=='item' and selected.get('target')=='society':return _discord_autocomplete_choices([])

    if command=='workshop' and option=='station':
        _,_,p=_discord_existing_player(payload)
        with SessionLocal() as db:
            return _discord_autocomplete_choices(workbench.station_rows(workbench.Context(sys.modules[__name__],db,p),query))
    if command in {'catalog','gather'} and option in {'item','resource'}:
        import sys
        _,_,p=_discord_existing_player(payload)
        with SessionLocal() as db:
            return _discord_autocomplete_choices(seed_content.choices(sys.modules[__name__],db,p,gather_only=command=='gather',category=selected.get('category',''),owned=bool(selected.get('owned',False))),query)
    if command=='training' and option=='task':
        hub=selected.get('skill')
        _,_,p=_discord_existing_player(payload)
        rows=[]
        with SessionLocal() as db:
            for key,cfg in SEED_TASKS.items():
                if cfg['hub']!=hub:continue
                rows.append((training_choice_label(db,p,key,cfg),key))
        return _discord_autocomplete_choices(rows,query)
    if command=="eat" and option=="food":
        _,_,p=_discord_existing_player(payload)
        if not p:return _discord_autocomplete_choices([])
        with SessionLocal() as db:
            foods=edible_inventory(db,p)
            rows=[(f"{row['name']} ×{row['qty']} — {row['effect']}",row['key']) for row in foods if row['qty']>0]
            if emergency_food_available(db,p,foods):rows.append(("Emergency Meal — free; restores Nutrition to 40","emergency"))
            return _discord_autocomplete_choices(rows,query)

    if command=="seedindustries" and option=="item":
        values=_discord_options(payload);mode=values.get("action","browse")
        with SessionLocal() as db:
            if mode=="fulfill":
                state=society(db,DISCORD_WORLD_ID);clock=world_clock(db,DISCORD_WORLD_ID)
                rows=[(data["name"],key) for key,data in available_production_orders(DISCORD_WORLD_ID,clock["day"],society_tier_index(state))]
            elif mode in {"buy","sell"}:
                _,_,p=_discord_existing_player(payload)
                stock=seed_content.stock(sys.modules[__name__],db,p)
                def owned(key):return (p.cargo if p else 0) if key=="cargo" else stock.get(key,0)
                rows=[(f"{market_item_label(key)} — {data[mode]} SC each · you have {owned(key)}",key) for key,data in sorted(SEED_INDUSTRIES.items(),key=lambda kv:(-owned(kv[0]) if mode=="sell" else 0,market_item_label(kv[0]))) if data.get(mode,0)>0 and (values.get("category","all")=="all" or data.get("category","legacy")==values["category"]) and (mode=="buy" or owned(key)>0)]
            else:rows=[]
        return _discord_autocomplete_choices(rows,query)

    if command=="use" and option=="item":
        _,_,p=_discord_existing_player(payload)
        if not p:return _discord_autocomplete_choices([])
        with SessionLocal() as db:
            owned=owned_life_items(db,p)
            import sys
            source=seed_content.choices(sys.modules[__name__],db,p,category=selected.get('category',''),owned=True,usable=True)
            effects={"meal_kit":"+75 Nutrition, +5 Morale","recreation_set":"+28 Social, +12 Morale","comfort_pack":"+40 Comfort, +8 Energy"}
            legacy=[] if selected.get('category') else [(f"{QUALITY_RECIPES[key]['name']} ×{sum(row.qty for row in rows)} — consumes 1: {effects[key]} (best quality first)",key) for key,rows in owned.items() if rows]
            return _discord_autocomplete_choices(source+legacy,query)

    if command=="make" and option in {"recipe","station"}:
        return _discord_make_autocomplete(payload)

    if option=="player" and command=="social":
        return _discord_player_autocomplete(payload,query)

    if command=="linklookup" and option=="player":
        if not _discord_is_owner(payload):
            return {"type":8,"data":{"choices":[]}}
        return _discord_player_autocomplete(payload,query)

    if command in {"titles","me"} and option=="title":
        return _discord_title_autocomplete(payload,query)

    if command=="repair" and option=="item":
        return _discord_gear_autocomplete(payload,query)

    return {"type":8,"data":{"choices":[]}}

def _discord_allowed_channel(payload: dict):
    if not DISCORD_GAME_CHANNEL_ID:
        return True
    return str(payload.get("channel_id") or "") == str(DISCORD_GAME_CHANNEL_ID)

def _discord_is_moderator(payload:dict):
    """Moderator tools (events, challenges, live, recap, feed, panels, the moderator log) are the owner's alone:
    server permissions (Administrator, Manage Server, Manage Messages) and DISCORD_MOD_ROLE_IDS roles no longer grant them."""
    return _discord_is_owner(payload)

def _discord_is_owner(payload:dict):
    uid,_=_discord_user(payload)
    return bool(DISCORD_OWNER_USER_IDS) and str(uid) in DISCORD_OWNER_USER_IDS

def _discord_owner_denied(uid,what="moderator tools"):
    """Why a Discord account cannot use an owner-only tool, with the ID to put in DISCORD_OWNER_USER_IDS."""
    return (f"⛔ Only the game owner can use {what}. Detected Discord ID: {uid} | Owner IDs loaded: {len(DISCORD_OWNER_USER_IDS)}. "
            f"If this is you, make sure Railway DISCORD_OWNER_USER_IDS contains this exact numeric ID, then redeploy.")

def _discord_validate_options(command,options):
    options=dict(options or {})
    if command not in DISCORD_OPTION_SCHEMA:return options,""
    schema={field['name']:field for field in DISCORD_OPTION_SCHEMA[command]}
    if command=='seedindustries' and not options.get('action') and (options.get('category') or options.get('page')):options['action']='browse'
    if command=='make' and options.get('category'):
        normalized=workbench.normalize_category(options['category'])
        if normalized is None:return options,"⚠️ Choose a Workbench category from the list. Nothing spent."
        options['category']=normalized
    if command=='me' and not options.get('section'):
        if options.get('title'):options['section']='titles'
        elif options.get('style'):options['section']='display'
    if command=='repair' and options.get('item') and not options.get('target'):options['target']='gear'
    for key,value in options.items():
        if key not in schema:return options,f"⚠️ /{command} does not have an option named {key}. Choose from the current command menu. Nothing spent."
        if value is None or value=='':continue
        field=schema[key]
        if field.get('type')==4:
            if isinstance(value,str) and value.strip().isdigit():value=options[key]=int(value.strip())   # menu dropdowns send text
            if isinstance(value,bool) or not isinstance(value,int) or not field.get('min_value',1)<=value<=field.get('max_value',25):
                return options,f"⚠️ {key.title()} must be a whole number from {field.get('min_value',1)} to {field.get('max_value',25)}. Nothing spent."
        if field.get('choices'):
            match=next((choice for choice in field['choices'] if str(value).lower() in {str(choice['value']).lower(),choice['name'].lower()}),None)
            if not match:return options,f"⚠️ Choose a valid {key} for /{command}: "+', '.join(c['name'] for c in field['choices'])+'. Nothing spent.'
            options[key]=match['value']
        if isinstance(value,str) and field.get('min_length') and not value.strip():return options,f"⚠️ {key.title()} cannot be blank. Nothing spent."
        if isinstance(value,str) and len(value)>field.get('max_length',6000):return options,f"⚠️ {key.title()} is too long. Nothing spent."
    for key,field in schema.items():
        if field.get('required') and not options.get(key):
            return options,f"ℹ️ Choose {key} from /{command}'s options first."
    restrictions={
        'me':('section',{'title':{'titles'},'style':{'display'}}),
        'business':('action',{'name':{'start'}}),
        'repair':('target',{'item':{'gear'}}),
        'market':('action',{}),
        'seedindustries':('action',{'item':{'buy','sell','fulfill','sellall'},'amount':{'buy','sell'},'category':{'browse','buy','sell'},'page':{'browse','starters'}}),
        'inventory':('section',{'search':{None,'','all'},'sort':{None,'','all'},'show':{None,'','all'},'page':{None,'','all'}}),
        'social':('action',{'player':{'hi','hangout','mentor','duo_walk','duo_games','duo_research','duo_delivery','duo_explore'}}),
    }
    if command in restrictions:
        selector,fields=restrictions[command]
        for field,allowed in fields.items():
            if options.get(field) is not None and options.get(field)!='' and options.get(selector) not in allowed:
                return options,f"ℹ️ {field.title()} is used with /{command} {selector}:"+' or '.join(sorted(allowed))+f". Choose that {selector}, or remove {field}. Nothing spent."
    required={
        ('seedindustries','buy'):('item',),
        ('seedindustries','sell'):('item',),('seedindustries','fulfill'):('item',),('seedindustries','sellall'):('item',),

    }
    selector='target' if command=='repair' else 'action'
    needed=list(required.get((command,options.get(selector)),()))
    if command=='social' and options.get('action') not in {None,'','group_games'}:needed.append('player')
    for field in needed:
        if not options.get(field):return options,f"ℹ️ Select {field} to continue with /{command} {selector}:{options.get(selector)}. Nothing spent."
    if command=='make':
        if options.get('action') and not options.get('recipe'):
            return options,"ℹ️ Choose a Recipe first, then Preview, Craft or Queue it. Nothing spent."
        if options.get('count') and options.get('action') not in {'queue','fetch'}:
            return options,"ℹ️ Count is used with Action: Queue batches or Fetch missing. Choose one of those, or remove Count. Nothing spent."
    return options,""
