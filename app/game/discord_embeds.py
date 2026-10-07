"""Discord command lists and the classic embed builders.
"""
import re
from .. import notice as fan_notice
from .rules import ACTION_SKILLS

DISCORD_PUBLIC_COMMANDS = {
    "society", "event", "eventstart", "eventstop", "holiday",
    "farm",
    "mine", "rare",
    "research", "scan",
    "repair",
    "cargo", "delivery", "spaceport",
    "explore", "market",
    "eat", "sleep", "social", "walk", "relax", "games", "hobby",
    "district", "shift", "meal", "use", "recover", "life", "work", "eatfull",
}

DISCORD_PRIVATE_COMMANDS = {
    "seed", "guide", "start", "me", "progress", "inventory", "job",
    "home", "business", "make", "seedindustries", "link", "specialize", "modlog", "asklog",
    "world", "linklookup", "ducks", "training", "catalog", "gather", "workshop",
    "status", "settings", "mod", "menu", "guidepanels", "menupanel", "inbox", "queuedetails", "find", "undo", "seedling", "seedlingstep",
    "vote", "season", "challenge", "trophies", "customize",
    "challengestart", "challengestop", "liveon", "liveoff", "liveauto", "recappreview", "recappost"
}

def discord_message_status(content):
    lower=content.lower()
    if content.startswith(("❌","⛔","⚠️","🔒","🛑")) or any(term in lower for term in
        ("+0 rewards", "no task rewards were earned", "empty-handed", "cannot ", "still needed:", "still needs ", "need ore first", "no cargo ready", "you only have", "gear not found")):
        return "failure"
    if content.startswith(("⏱️","⏳")) or re.search(r"(?:is ready|again) in \d+[smh]",lower):return "cooldown"
    if content.startswith("✅") or any(term in lower for term in
        ("task complete", "crafting complete", " completes ", " upgraded to ", " sold ", " bought ")):
        return "success"
    return "info"

def discord_message_category(command):
    groups={
        "handbook":{"seed"},"guide":{"guide"},"character":{"start","me","progress","inventory","job","specialize","link"},
        "life":{"social","relax","walk","games","hobby","world","district","shift","meal","ducks","use"},"business":{"business","seedindustries","market"},
        "society":{"society"},"event":{"event","eventstart","eventstop"},"moderator":{"modlog","asklog","linklookup"},
        "action":set(ACTION_SKILLS)|{"farm","fabricate","eat","sleep"},
    }
    return next((group for group,names in groups.items() if command in names),"default")
def _discord_clean_piece(value,limit=1024):
    text=str(value or "").strip()
    if len(text)<=limit:return text
    return text[:max(0,limit-1)].rstrip()+"…"

def _discord_nonempty_lines(content):
    return [x.strip() for x in str(content or "").replace("\r","").split("\n") if x.strip()]

def _discord_split_result(content):
    """Split older combined action strings on known New Eridian v2 system markers."""
    text=str(content or "").replace("\r","").strip()
    if not text:return []
    markers=[
        " Trade Crate:", " Fleet bond:", " 🦆 Fleet bond:",
        " 📖 ", " 🏗️ ", " 🎯 ", " 🔎 Encounter:",
        " ☣️ Siro exposure", " 🧳 ", " 📓 ",
        " 🧬 Active life modifiers", " 🌅 ", " ☀️ ", " 🌇 ", " 🌙 ",
        " 🩹 ", " ✅ ", " 🎓 ", " 🏆 ", " 🌈 ", " 📣 ", " 🔔 ", " 📜 ", " 🛠️ "
    ]
    text=text.replace(" | ","\n")
    for marker in markers:
        text=text.replace(marker,"\n"+marker.strip())
    text=re.sub(r"\s*(🔎\s*Encounter:|🧳\s*Collected:)",r"\n\1",text)
    return [x.strip() for x in text.split("\n") if x.strip()]

def _discord_embed_color(status):
    if status=="failure":return 0xED4245
    if status=="cooldown":return 0xFEE75C
    if status=="success":return 0x57F287
    if status=="action":return 0xFEE75C
    if status=="social":return 0xEB459E
    if status=="detail":return 0x99AAB5
    return 0x3498DB

def _discord_embed(title,description="",status="info"):
    e={
        "title":_discord_clean_piece(title,256),
        "color":_discord_embed_color(status),
        "fields":[],
        "footer":{"text":fan_notice.FOOTER},
    }
    if description:
        e["description"]=_discord_clean_piece(description,1800)
    return e

def _discord_add_field(embed,name,lines,inline=False):
    if isinstance(lines,str):lines=[lines]
    clean=[]
    for line in lines or []:
        line=str(line or "").strip()
        if not line:continue
        if line.startswith("•"):line=line[1:].strip()
        if line not in clean:clean.append(line)
    if not clean:return
    # Split fields at line boundaries so instructions are not cut at 1024 chars.
    chunks=[];current=""
    for line in clean:
        line="• "+line
        while len(line)>1000:
            if current:chunks.append(current);current=""
            split=line.rfind(" ",0,1000)
            if split<1:split=1000
            chunks.append(line[:split]);line=line[split:].lstrip()
        if current and len(current)+1+len(line)>1000:
            chunks.append(current);current=""
        current=(current+"\n"+line).strip()
    if current:chunks.append(current)
    for i,value in enumerate(chunks):
        embed["fields"].append({"name":_discord_clean_piece(name+(" (continued)" if i else ""),256),
                                "value":value,"inline":False})


def _discord_action_name(command):
    names={
        "fabricate":"FABRICATION SHIFT",
        "farm":"FARMING SHIFT","harvest":"HARVEST","forage":"FORAGING",
        "water":"WATER TREATMENT","scan":"PROCESSING SCAN",
        "mine":"MINING SHIFT","rare":"RARE MATERIAL SEARCH","scavenge":"SCAVENGE RUN",
        "craft":"CRAFTING SHIFT","machine":"MACHINE OPERATION","repair":"REPAIR",
        "project":"PROJECT WORK","work":"WORK SHIFT","research":"RESEARCH",
        "cargo":"CARGO PREP","delivery":"DELIVERY","spaceport":"SPACEPORT SHIFT",
        "explore":"EXPEDITION","survey":"SURVEY","market":"MARKET SHIFT",
        "businesswork":"BUSINESS SHIFT","business":"BUSINESS SHIFT",
        "businesscontract":"BUSINESS CONTRACT","businessinvest":"BUSINESS INVESTMENT",
        "eat":"MEAL","sleep":"REST CYCLE","walk":"WALK","games":"GAMES","relax":"RELAX",
        "hobby":"HOBBY","hi":"GREETING","hangout":"HANGOUT","duo":"DUO ACTIVITY",
        "meal":"COMMUNITY MEAL","mentor":"MENTORING","sell":"MARKET SALE",
        "gearrepair":"GEAR REPAIR","use":"ITEM USED","training":"SKILL TRAINING",
    }
    return names.get(command,(command or "NEW ERIDIAN").replace("_"," ").upper())

def _discord_command_title(command):
    titles={
        "training":"🌱 SKILL TRAINING","holiday":"🎉 HOLIDAY CALENDAR",
        "seed":"📘 NEW ERIDIAN v2 HANDBOOK","guide":"🧭 GUIDE","start":"🌱 CITIZEN READY",
        "me":"👤 CITIZEN PROFILE","skills":"🧬 APTITUDES","inventory":"🎒 INVENTORY",
        "job":"🧰 PROFESSION","contracts":"📋 DAILY CONTRACT","achievements":"🏆 ACHIEVEMENTS",
        "home":"🏠 HABITAT","business":"🏢 BUSINESS","make":"🛠️ FABRICATOR","seedindustries":"🏭 SEED INDUSTRIES",
        "life":"❤️ LIFE STATUS","relationships":"🤝 RELATIONSHIPS","world":"🌎 AVESTA WORLD",
        "rumor":"🗣️ NEW ERIDIAN RUMOR","collection":"🧳 COLLECTION","traits":"🧬 TRAITS",
        "district":"🏘️ DISTRICT","shift":"🕒 SHIFT","conditions":"☣️ CONDITIONS",
        "goal":"🎯 DAILY GOAL","projectstatus":"🏗️ SOCIETY PROJECT","bulletin":"📌 BULLETIN",
        "journal":"📓 JOURNAL","tutorial":"🎓 FIRST DAYS","story":"📖 WEEKLY STORY",
        "titles":"🏷️ TITLES","marketboard":"💰 MARKET DEMAND","ducks":"🦆 DELIVERY FLEET",
        "gear":"⚙️ EQUIPMENT","cooldowns":"⏱️ COOLDOWNS","bonuses":"✨ BONUSES",
        "specialize":"⭐ SPECIALIZATION","status":"🏛️ NEW ERIDIAN","progress":"📈 SOCIETY PROGRESS",
        "society":"🏛️ NEW ERIDIAN SOCIETY","event":"🚨 SOCIETY EVENT",
        "link":"🔗 ACCOUNT LINK","linklookup":"🔐 LINKED ACCOUNT LOOKUP","modlog":"🛡️ MODERATOR LOG","asklog":"❓ UNANSWERED FIND QUESTIONS",
    }
    return titles.get(command,"🌱 NEW ERIDIAN v2")

def _discord_progress_embed(content,status):
    lines=_discord_nonempty_lines(content)
    embed=_discord_embed("📈 SOCIETY PROGRESS","🏗️ New Eridian — Tier Progress",status)
    rewards=[];progress=[];notes=[]
    for line in lines:
        low=line.lower()
        if "new eridian — tier progress" in low:continue
        if "success bonus:" in low:
            rewards.append(line)
        elif line.startswith("• ") and any(k in line for k in ("Food:","Materials:","Development:","Knowledge:","Treasury:","Reputation:")):
            progress.append(line)
        elif line.startswith("Current tier:") or line.startswith("Next tier:") or line.startswith("Requirement:"):
            progress.append(line)
        elif "most useful target" in low or "bottleneck:" in low or line.startswith("Use /guide"):
            notes.append(line)
        elif "maximum society tier" in low:
            progress.append(line)
        else:
            notes.append(line)
    _discord_add_field(embed,"🟨 REWARDS",rewards)
    _discord_add_field(embed,"🟦 PROGRESS",progress)
    _discord_add_field(embed,"⚪ DETAILS",notes)
    return embed

def _discord_world_embed(content,status):
    lines=_discord_nonempty_lines(content)
    first=lines[0] if lines else "Avesta world state"
    embed=_discord_embed("🌎 AVESTA WORLD",first,status)
    condition=[];society=[];story=[];notes=[]
    for line in lines[1:]:
        low=line.lower()
        if line.startswith("World condition:"):
            condition.append(line.replace("World condition:","").strip())
        elif line.startswith("Society project:") or line.startswith("Society pressure:"):
            society.append(line)
        elif line.startswith("Weekly story:"):
            story.append(line.replace("Weekly story:","").strip())
        elif line.startswith("Rumor:"):
            notes.append(line)
        elif "day phases change" in low or "night outdoor" in low:
            notes.append(line)
        elif condition and len(condition)<2:
            condition.append(line)
        else:
            notes.append(line)
    _discord_add_field(embed,"🟦 CONDITION",condition)
    _discord_add_field(embed,"🟦 SOCIETY",society)
    _discord_add_field(embed,"🟪 STORY",story)
    _discord_add_field(embed,"⚪ DETAILS",notes)
    return embed

def _discord_life_embed(content,status):
    lines=_discord_nonempty_lines(content)
    first=lines[0] if lines else "Citizen life status"
    embed=_discord_embed("❤️ LIFE STATUS",first,status)
    needs=[];effects=[];notes=[];mode=""
    for line in lines[1:]:
        if line.upper()=="ACTIVE EFFECTS":
            mode="effects";continue
        if any(line.startswith(x) for x in ("⚡","🍲","🤝","🏠","✨")) and "/100" in line:
            needs.append(line)
        elif line.startswith("Use /"):
            notes.append(line)
        elif mode=="effects":
            effects.append(line)
        else:
            notes.append(line)
    _discord_add_field(embed,"🟦 NEEDS",needs)
    _discord_add_field(embed,"⚪ ACTIVE EFFECTS",effects or ["No active life penalties."])
    _discord_add_field(embed,"⚪ DETAILS",notes)
    return embed

def _discord_event_embed(content,status):
    lines=_discord_nonempty_lines(content)
    first=lines[0] if lines else "Live event"
    if "No active live event" in first:
        return _discord_embed("🚨 LIVE EVENT","No active live event.",status)
    embed=_discord_embed("🚨 LIVE EVENT",first,status)
    event_status=[];help_lines=[];risk=[];notes=[];mode=""
    for line in lines[1:]:
        upper=line.upper()
        if upper=="📊 STATUS":mode="status";continue
        if upper=="🎯 HOW TO HELP":mode="help";continue
        if line.startswith("⚠️") or line.startswith("🏅"):
            risk.append(line);continue
        if line.startswith("Use /guide"):
            notes.append(line);continue
        if "needs your response" in line.lower():
            notes.append(line);continue
        if mode=="status":event_status.append(line)
        elif mode=="help":help_lines.append(line)
        else:notes.append(line)
    _discord_add_field(embed,"🟦 STATUS",event_status)
    _discord_add_field(embed,"🟨 HOW TO HELP",help_lines)
    _discord_add_field(embed,"🟥 RISK & LEADERS",risk)
    _discord_add_field(embed,"⚪ DETAILS",notes)
    return embed

def _discord_status_embed(content,status):
    lines=_discord_nonempty_lines(content)
    first=lines[0] if lines else "New Eridian society status"
    embed=_discord_embed("🏛️ NEW ERIDIAN",first,status)
    overview=[];resources=[];notes=[];mode=""
    for line in lines[1:]:
        if line=="📦 CORE RESOURCES":mode="resources";continue
        if mode=="resources":
            # Core resource lines contain two stats separated by a middle dot.
            resources.extend([x.strip() for x in line.split("·") if x.strip()])
        elif line.startswith("Use /progress"):
            notes.append(line)
        elif "your society currently needs" in line.lower():
            notes.append(line)
        else:
            overview.append(line)
    _discord_add_field(embed,"🟦 OVERVIEW",overview)
    _discord_add_field(embed,"🟨 RESOURCES",resources)
    _discord_add_field(embed,"⚪ DETAILS",notes)
    return embed

def _discord_action_embed(content,command,status):
    pieces=_discord_split_result(content)
    title_prefix="🟩" if status=="success" else "🟥" if status=="failure" else "🟨" if status=="cooldown" else "🟦"
    title=title_prefix+" "+_discord_action_name(command)
    embed=_discord_embed(title,"",status)

    rewards=[];society=[];fleet=[];progress=[];discovery=[];world=[];mods=[];notes=[];risk=[];guidance=[];needs=[]
    modifier_mode=False;section_mode=""
    summary=""
    has_practice=any(x.startswith(("Aptitude practice:","Competency practice:")) for x in pieces)
    if command=="training":
        match=re.search(r" completes ([^\n]+?)\.\s*\+",content)
        if match:embed["title"]=title_prefix+" "+match.group(1)+(" • Complete" if status=="success" else "")

    for i,piece in enumerate(pieces):
        low=piece.lower()
        upper=piece.strip("• ").upper()

        # These are routing markers from the plain-text action response. They
        # should organize the embed, never appear as unexplained Notes.
        if upper in {"✅ TASK COMPLETE","❌ TASK FAILED","RESULT"}:
            continue
        if upper in {"WHY THIS RESULT","🧬 ACTIVE LIFE MODIFIERS"}:
            modifier_mode=True;section_mode="mods";continue
        if upper=="WHY":section_mode="risk";continue
        if upper=="HOW TO IMPROVE":section_mode="guidance";continue
        if upper=="NEXT":section_mode="guidance";continue

        if piece.startswith("Needs:"):needs.append(piece[6:].strip());continue
        if piece.startswith("Resources:"):
            for change in piece[10:].split(","):
                match=re.fullmatch(r"\s*(sc|contribution)\s*([+-]\d+)\s*",change,re.I)
                if match:
                    label="SC" if match[1].lower()=="sc" else "Contribution"
                    value=f"{match[2]} {label}"
                    if value not in rewards:rewards.append(value)
                else:rewards.append(change.strip())
            continue
        if piece.startswith("Settlement:"):
            if not society:society.append(piece[11:].strip())
            continue
        if piece.startswith(("Aptitude practice:","Competency practice:")):
            progress.append(piece.split(":",1)[1].strip());continue
        if piece.startswith("shared ") or piece.startswith("society "):
            society.extend(x.strip().capitalize() for x in piece.split(";") if x.strip());continue
        if "LEVEL UP" in piece:
            progress.append(piece);continue
        if section_mode=="risk":
            risk.append(piece);continue
        if section_mode=="guidance":
            guidance.append(piece);continue

        if "active life modifiers" in low:
            modifier_mode=True
            continue
        if modifier_mode:
            if piece.startswith("•") or "success chance" in low or re.search(r"[+-]\d+%",piece):
                mods.append(piece)
                continue
            modifier_mode=False

        # Break the main success sentence away from inline mechanical rewards.
        if not summary:
            # Example: "🦆 Name completes delivery with Prisma. +1 Logistics XP"
            m=re.match(r"^(.*?\.)\s*(\+\d+(?:\.\d+)? .+ XP(?: and branch XP)?)?$",piece)
            if m:
                summary=m.group(1).strip()
                if m.group(2):
                    xp=m.group(2).strip()
                    if not has_practice:progress.append(xp.replace(" and branch XP",""))
                    if "and branch XP" in xp:
                        amount=xp.split()[0]
                        progress.append(f"{amount} branch XP")
                continue
            summary=piece
            continue

        # Split society line from flavor that may trail after the period.
        if "new eridian gains" in low:
            m=re.match(r"^(.*?New Eridian gains [^.]+\.)(.*)$",piece,re.I)
            if m:
                society.append(m.group(1).strip())
                tail=m.group(2).strip()
                if tail:
                    if any(d.lower() in tail.lower() for d in ("hueburt","colora","prisma","pastelle","asimov")):
                        fleet.append(tail)
                    else:notes.append(tail)
            else:society.append(piece)
            continue

        if "fleet bond:" in low or any(d.lower() in low for d in ("hueburt","colora","prisma","pastelle","asimov")):
            fleet.append(piece);continue
        if piece.startswith("📖") or "story progress" in low or "the signal below" in low:
            progress.append(piece.lstrip("📖 ").strip());continue
        if piece.startswith(("🌈","📣","🔔","🛠️")):
            progress.append(piece.lstrip("🌈📣🔔🛠️ ").strip());continue
        if piece.startswith("📜") or "lore discovered" in low:
            discovery.append(piece.lstrip("📜 ").strip());continue
        if piece.startswith("🏗️") or piece.startswith("🎯") or "daily goal" in low or "project" in low and ("progress" in low or "complete" in low):
            progress.append(piece.lstrip("🏗️🎯 ").strip());continue
        if "encounter:" in low or piece.startswith("🔎") or "collected:" in low or "added to collection" in low or piece.startswith("🧳"):
            discovery.append(piece.replace("🔎 Encounter:","").lstrip("🔎🧳 ").strip());continue
        if piece.startswith(("🌅","☀️","🌇","🌙")) or any(x in low for x in ("dust winds","siro drift","good growing weather","busy spaceport","water watch","sensor noise","quiet cycle","clear avesta skies")):
            world.append(piece);continue
        if piece.startswith("☣️") or piece.startswith("🩹") or "siro exposure" in low:
            world.append(piece);continue
        if "final chance" in low or "final success chance" in low or re.search(r"[+-]\d+%",piece):
            mods.append(piece);continue
        if "trade crate:" in low or piece.startswith("+") or any(k in piece for k in (" XP"," SC","Contribution")):
            rewards.append(piece);continue
        if "+0 rewards" in low:
            rewards.append("No rewards earned.");continue
        notes.append(piece)

    embed["description"]=_discord_clean_piece(summary or "Action processed.",1400)
    _discord_add_field(embed,"🟥 WHY IT FAILED",risk)
    _discord_add_field(embed,"🟨 HOW TO IMPROVE",guidance)
    _discord_add_field(embed,"🟨 REWARDS",rewards,inline=True)
    _discord_add_field(embed,"🟦 NEED CHANGES",needs)
    _discord_add_field(embed,"🟦 SOCIETY",society,inline=True)
    _discord_add_field(embed,"🟪 FLEET",fleet)
    _discord_add_field(embed,"🟦 PROGRESS",progress)
    _discord_add_field(embed,"🟪 DISCOVERY",discovery)
    _discord_add_field(embed,"🟦 WORLD",world,inline=True)
    _discord_add_field(embed,"🟦 SUCCESS CHANCE",mods)
    _discord_add_field(embed,"⚪ DETAILS",notes)
    return embed

def _discord_generic_embed(content,command,status):
    lines=_discord_nonempty_lines(content)
    title=_discord_command_title(command)
    if not lines:
        return _discord_embed(title,"No information available.",status)

    # Keep the first useful line prominent, then compact the rest.
    first=lines[0]
    embed=_discord_embed(title,first,status)
    rest=lines[1:]

    # Preserve simple all-caps/label sections when the endpoint already provides them.
    sections=[];current_name="📌 Details";current=[]
    for line in rest:
        if ((line.isupper() and re.match(r"^[A-Z][A-Z &/—-]*$",line)) or line.endswith(":")) and len(line)<=48 and not re.match(r"^[+−\-]?\d",line):
            if current:sections.append((current_name,current))
            current_name=line.strip(":")
            current=[]
        else:
            current.append(line)
    if current:sections.append((current_name,current))

    if not sections and rest:
        sections=[("📌 Details",rest)]

    for name,vals in sections:
        if not name.startswith(("📌","💰","📊","✨","🏛️","🌎","📖","🏗️","🎯","🦆","🧬","☣️","🧳","🤝","⚙️","🎒","🏆","📋")):
            name="📌 "+name.title()
        _discord_add_field(embed,name,vals)

    return embed

def _discord_pretty_embed(content,command,status):
    if content.startswith(("🍽️ FOOD MENU","🎒 ITEM MENU")):return _discord_generic_embed(content,command,"info")
    action_commands=set(ACTION_SKILLS)|{
        "farm","fabricate",
        "eat","sleep","businesswork","businesscontract","businessinvest",
        "walk","games","relax","hobby","hi","hangout","duo","meal","mentor",
        "sell","gearrepair","use"
    }

    if content.startswith(("✅ TASK COMPLETE","❌ TASK FAILED")):
        return _discord_action_embed(content,command,status)
    if command=="progress":return _discord_progress_embed(content,status)
    if command=="world":return _discord_world_embed(content,status)
    if command=="life":return _discord_life_embed(content,status)
    if command=="event":return _discord_event_embed(content,status)
    if command=="status":return _discord_status_embed(content,status)
    if command in action_commands and not (command in {"business","market"} and status=="info"):
        return _discord_action_embed(content,command,status)
    return _discord_generic_embed(content,command,status)
