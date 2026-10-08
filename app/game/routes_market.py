"""Routes: market board, selling, workshops, Seed Industries, duo work, ducks, gear and using items.
"""
import math
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from .. import crafting_progression, item_identity, practice, seed_content
from ..commands import command as colony_command, transaction as game_transaction
from ..db import SessionLocal
from ..needs import cost_text as need_cost_text, duration_text, work_energy
from ..models import GearFamiliarity, LifeRelationship, ProductionOrderCompletion, QualityGear
from .base import app, chat_line, out, platform_response
from .rules import (
    DELIVERY_DUCKS, DUCK_PERSONALITY, DUO_ACTIVITIES, LIFE_GEAR, QUALITY_RECIPES, QUALITY_TIERS, SEED_INDUSTRIES)
from .players import (
    clamp100, cost_text, demand_price, duck_bond, duck_rank, lvl, market_demand, player, requirement_text,
    resource_name, sale_price, skill_xp, society)
from .life import life_state, player_preference, spend_life_for_action, task_need_gate
from .world import (
    effective_relationship, find_player_name, gear_familiarity_rank, journal_add, relationship_add,
    relationship_memory, society_tier_index, world_clock)
from .cooldowns_materials import (
    available_production_orders, check_cooldown, material_amount, material_change, material_source, order_completed,
    production_order_numbers)
from .colony_events import work_counts
from .accounts import achieve
from .routes_crafting import craft_missing_materials, task_readiness_warning
from .. import main      # app.main: names from later modules and settings changed at runtime

@app.get("/api/v1/marketboard")
@game_transaction
def marketboard(channel:str,provider:str="twitch"):
    with SessionLocal() as db:
        clock=world_clock(db,main.DISCORD_WORLD_ID);a,b=market_demand(main.DISCORD_WORLD_ID,clock["day"])
        def row(k,tag):
            base=SEED_INDUSTRIES[k]['sell'];now_=demand_price(k,clock["day"])
            return f"{tag} {resource_name(k)}: {now_} SC each (usually {base})"
        text=(f"🏪 MARKET — AVESTA DAY {clock['day']}\nSeed Industries pays extra today for:\n{row(a,'🔥')}\n{row(b,'↑')}\n"
              "Sell anything else at its usual price with /seedindustries action:Sell, or /menu → Bag & Shop.")
        return platform_response(provider,text,f"🏪 Day {clock['day']} demand: 🔥 {row(a,'').strip()} | ↑ {row(b,'').strip()} | !sellall <item> sells at today's price")

@app.get("/api/v1/sell")
@colony_command
def sell(channel:str,uid:str,name:str="Citizen",resource:str="",amount:int=1,provider:str="twitch"):
    """!sell <item> [amount]: sells any item to Seed Industries at today's price (old resource names still work)."""
    if not str(resource or '').strip():return out("🏪 Sell anything Seed Industries buys: !sell <item> [amount], or !sellall <item>. !marketboard shows today's demand.")
    return main.seed_industries(channel,uid,name,'sell',str(resource),max(1,min(25,int(amount or 1))),provider)

@app.get('/api/v1/workshop')
@colony_command
def workshop(channel:str,uid:str,name:str='Citizen',action:str='view',station:str='',page:int=1,provider:str='twitch'):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        result=crafting_progression.workshop(db,p,action,station,page,provider)
        return platform_response(provider,result,result.replace('\n',' | '))

def market_item_label(key):
    return resource_name(key)

@app.get("/api/v1/seedindustries")
@colony_command
def seed_industries(channel:str,uid:str,name:str="Citizen",action:str="browse",item_name:str="",amount:int=1,provider:str="twitch",page:int=1,category:str="all"):
    action=(action or "browse").lower().strip();key=(item_name or "").lower().strip().replace(" ","_");amount=max(1,min(25,int(amount or 1)))
    if action not in {"browse","buy","sell","orders","fulfill","starters","sellall","clearout"}:return out("🏭 Seed Industries actions: browse, buy, sell, sellall, clearout, orders, fulfill, starters.")
    if action=="sellall":return main.sell_all_items(channel,uid,name,item_name,provider)
    if action=="clearout":return main.clearout(channel,uid,name,"",provider)
    if action=='starters':
        result=crafting_progression.starter_routes(page,provider)
        return platform_response(provider,result,result.replace('\n',' | '))
    if category not in {'all','legacy','seed','training','rare'}:return out('Choose a valid market category. Nothing spent.')
    if key not in SEED_INDUSTRIES:
        key=seed_content.find_item(item_name or '')
    key=item_identity.canonical(key)
    if action=='browse':
        rows=sorted((k for k,v in SEED_INDUSTRIES.items() if category=='all' or v.get('category','legacy')==category),key=market_item_label)
        size=8 if provider=='discord' else 3;pages=max(1,math.ceil(len(rows)/size));page=max(1,min(page,pages))
        category_label={'all':'All Supplies','legacy':'General Materials & Parts','seed':'Materials & Crafted Goods','training':'Training Supplies','rare':'Rare Ores'}[category]
        lines=[f'🏭 SEED INDUSTRIES · {category_label} · Page {page}/{pages}', 'Prices per item. Buy supplies or sell your crafted surplus.']
        for k in rows[(page-1)*size:page*size]:
            v=SEED_INDUSTRIES[k];sale=f"sell {v['sell']}" if v['sell'] else 'no buyback'
            purchase=f"buy {v['buy']} SC" if v['buy'] else 'crafted item; sell only'
            lines.append(f"• {market_item_label(k)}: {purchase} · {sale}"+(f' · {k}' if provider!='discord' else ''))
        lines+=['Select Starter Routes for each branch. Buy + Item + Amount (1–25) purchases supplies. Page/Category browse all stock. All catalog items have NPC buyback. Prices are per item; recipe previews show batch sale value. Rare ore purchases need a Mineral Extractor.' if provider=='discord' else '!seedpage <page>; !seedbuy <id> <qty>. Rare ores: need a Mineral Extractor.']
        result='\n'.join(lines)
        return platform_response(provider,result,result.replace('\n',' | '))
    if action in {"orders","fulfill"}:
        with SessionLocal() as db:
            _,p=player(db,channel,provider,uid,name);clock=world_clock(db,channel);tier_index=society_tier_index(society(db,channel));orders=available_production_orders(channel,clock["day"],tier_index)
            if action=="orders":
                rows=[]
                for order_key,data in orders:
                    numbers=production_order_numbers(data);done=order_completed(db,p,clock["day"],order_key);missing=craft_missing_materials(db,p,data["cost"])
                    state="✅ COMPLETED" if done else ("❌ NEED "+", ".join(missing) if missing else "✅ READY TO DELIVER")
                    rows.append(f"• {state} — **{data['name']}** (`{order_key}`)\n  Deliver: {requirement_text(data['cost'])}\n  Reward: {numbers['sc']} SC · {numbers['contribution']} Contribution · {numbers['development']} Development · Crafting/Commerce practice (base 2/1; adjusted by conditions)\n  Purpose: {data['purpose']}")
                discord=(f"🏭 SEED INDUSTRIES — DAY {clock['day']} PRODUCTION ORDERS\n\n"
                         "Three rotating contracts connect gathering, manufacturing, and New Eridian's needs. Each may be completed once per citizen per Avesta day.\n\n"+
                         "\n\n".join(rows)+"\n\nUse /seedindustries action:Fulfill item:<order key>. Buying every input costs more than the order pays; manufacturing creates the profit.")
                twitch=f"🏭 Day {clock['day']} Orders | "+" | ".join(f"{key}: {requirement_text(data['cost'])} → {production_order_numbers(data)['sc']} SC" for key,data in orders)
                return platform_response(provider,discord,twitch)
            match=next(((order_key,data) for order_key,data in orders if order_key==key),None)
            if not match:return out("🏭 That order is not active today. View today's production orders first.")
            order_key,data=match
            if order_completed(db,p,clock["day"],order_key):return out(f"🏭 {data['name']} is already complete for Avesta Day {clock['day']}.")
            missing=craft_missing_materials(db,p,data["cost"])
            if missing:return out(f"🏭 {data['name']} still needs "+", ".join(missing)+(". Use /guide goal:crafting for a production route." if provider=="discord" else ". Use !guide crafting for a production route."))
            for material,qty in data["cost"].items():material_change(db,p,material,-qty)
            numbers=production_order_numbers(data);p.sc+=numbers["sc"];p.contribution+=numbers["contribution"];p.actions+=1;p.successes+=1
            main.gain_skill(p,"fabrication",2);main.gain_skill(p,"commerce",1);society(db,channel).development+=numbers["development"]
            found=practice.find(db,p,"fabrication")
            db.add(ProductionOrderCompletion(channel_id=channel,canonical_uid=p.twitch_uid,avesta_day=clock["day"],order_key=order_key));db.commit()
            journal_add(db,p,f"Completed Seed Industries order: {data['name']}.");milestone=achieve(db,p)
            colony=work_counts(db,p,"commerce",grow=False)
            text=(f"✅ PRODUCTION ORDER COMPLETE — {data['name']}\n\n"
                  f"DELIVERED\n• {cost_text(data['cost'])[1:-1]}\n\n"
                  f"REWARDS\n• +{numbers['sc']} SC · +{numbers['contribution']} Contribution\n"
                  f"• +2 Crafting XP · +1 Commerce XP\n"+(f"• {found}\n" if found else "")+f"• New Eridian +{numbers['development']} Development\n\n"
                  f"WHY IT MATTERED\n• {data['purpose']}\n\n"+(colony+"\n\n" if colony else "")+f"NEXT\n• View the remaining Day {clock['day']} orders or continue your daily contract."+milestone)
            return PlainTextResponse(text) if provider=="discord" else out(chat_line(text))
    if key not in SEED_INDUSTRIES and item_name:
        key,suggestions=main.qol.fuzzy_item(item_name,SEED_INDUSTRIES)
        if key is None:return out("🏭 Seed Industries does not trade that item."+main.qol.did_you_mean(suggestions)+" Browse the market for item names. Nothing spent.")
    if key not in SEED_INDUSTRIES:return out("🏭 Seed Industries trades: "+", ".join(resource_name(k) for k in SEED_INDUSTRIES)+".")
    listing=SEED_INDUSTRIES[key]
    if category!='all' and listing.get('category','legacy')!=category:return out('That item is in another market category. Nothing spent.')
    if action=='buy' and not listing['buy']:return out('Seed Industries buys this crafted item but does not stock it. Use /catalog for its recipe. Nothing spent.')
    if action=='sell' and not listing['sell']:return out('Seed Industries supplies this starter item but does not buy it back. Nothing spent.')
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        if action=="buy":
            if key in crafting_progression.RARE and not crafting_progression.rare_unlocked(db,p):
                return out(crafting_progression.RARE_LOCK)
            total=listing["buy"]*amount
            if p.sc<total:return out(f"🏭 {p.display_name} needs {total} SC to buy {amount} {resource_name(key)}. Current balance: {p.sc} SC.")
            p.sc-=total;material_change(db,p,key,amount);db.commit()
            return out(f"🏭 {p.display_name} bought {amount} {resource_name(key)} from Seed Industries for {total} SC. Balance: {p.sc} SC. Use: {listing['purpose'].rstrip('.')}.")
        owned=material_amount(db,p,key)
        if owned<amount:return out(f"🏭 {p.display_name} only has {owned} {resource_name(key)}.")
        unit=sale_price(key);total=unit*amount;material_change(db,p,key,-amount);p.sc+=total;main.gain_skill(p,"commerce",max(1,amount//3));db.commit()
        demand=" (today's demand price)" if unit>listing["sell"] else ""
        colony=work_counts(db,p,"commerce",grow=False)
        return out(f"🏭 {p.display_name} sold {amount} {resource_name(key)} to Seed Industries for {total} SC{demand}. Balance: {p.sc} SC. +{max(1,amount//3)} Commerce XP."+(" "+colony.split("\n",1)[1].replace("\n"," ") if colony else ""))

@app.get("/api/v1/duo")
@colony_command
def duo(channel:str,uid:str,name:str="Citizen",target:str="",activity:str="walk",provider:str="twitch"):
    act=(activity or "walk").lower().strip();
    if act not in DUO_ACTIVITIES:return out("🤝 Duo activities: walk, games, research, delivery, explore.")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);other,error=find_player_name(db,channel,target)
        if error:return out("🤝 "+error)
        if other.twitch_uid==p.twitch_uid:return out("🤝 Duo activities require another citizen.")
        a,b=sorted((p.twitch_uid,other.twitch_uid))
        rel=db.execute(select(LifeRelationship).where(LifeRelationship.channel_id==channel,LifeRelationship.uid_a==a,LifeRelationship.uid_b==b)).scalar_one_or_none()
        familiarity=effective_relationship(db,rel) if rel else 0;need=DUO_ACTIVITIES[act]
        if familiarity<need:return out(f"🤝 {act.title()} requires a relationship score of {need}. Your current score is {familiarity}.")
        wait=check_cooldown(db,p,"duo_"+act)
        if wait:return out(f"⏱️ Duo {act} is ready in {duration_text(wait)}.")
        lp,lo=life_state(db,p),life_state(db,other);reward=""
        if act=="walk":lp.morale=clamp100(lp.morale+8);lo.morale=clamp100(lo.morale+6);main.gain_skill(p,"frontier",1);reward="+8 Morale; Frontier practice"
        elif act=="games":lp.social=clamp100(lp.social+10);lo.social=clamp100(lo.social+8);reward="+10 Social"
        elif act=="research":main.gain_skill(p,"research",2);main.gain_skill(other,"research",1);society(db,channel).knowledge+=2;reward="Research practice for both; +2 Knowledge"
        elif act=="delivery":
            if p.cargo<=0:return out("📦 You need 1 Cargo for a duo delivery.")
            p.cargo-=1;p.sc+=8;other.sc+=3;main.gain_skill(p,"logistics",2);society(db,channel).reputation+=2;reward="+8 SC; Logistics practice; partner +3 SC"
        elif act=="explore":main.gain_skill(p,"frontier",2);main.gain_skill(other,"frontier",1);reward="Frontier practice for both"
        before_relationship=rel.familiarity if rel else 0
        updated_relationship=relationship_add(db,channel,p.twitch_uid,other.twitch_uid,6);relationship_gain=updated_relationship.familiarity-before_relationship
        memory=relationship_memory(db,channel,p.twitch_uid,other.twitch_uid,"Duo "+act.title());db.commit();
        milestone=f" Shared memory milestone: {memory.interactions} activities together." if memory.interactions in {5,10,25,50} else ""
        return out(f"🤝 {p.display_name} and {other.display_name} complete a duo {act}. {reward}. Relationship +{relationship_gain}.{milestone}")

@app.get("/api/v1/ducks")
@game_transaction
def ducks(channel:str,uid:str,name:str="Citizen",duck:str="",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);pref=player_preference(db,p);wanted=(duck or "").strip().title()
        if wanted:
            if wanted not in DELIVERY_DUCKS:return out("🦆 Choose: "+", ".join(DELIVERY_DUCKS)+".")
            pref.assigned_duck=wanted;db.commit();return out(f"🦆 {wanted} is now {p.display_name}'s preferred delivery partner. Assignment changes flavor and bond focus, not base pay or success chance.")
        parts=[]
        for duck in DELIVERY_DUCKS:
            row=duck_bond(db,p,duck,0);assigned=" ⭐ ASSIGNED" if pref.assigned_duck==duck else "";parts.append(f"{duck}: {duck_rank(row.xp)} ({row.xp} XP){assigned} — {DUCK_PERSONALITY[duck]}")
        footer="\n\nAssigning a duck focuses future Logistics bond gains without changing success chance." if provider=="discord" else " | Assign a preferred duck for future Logistics runs"
        return PlainTextResponse("🦆 Delivery Fleet Bonds\n\n"+"\n".join("• "+x for x in parts)+footer) if provider=="discord" else out("🦆 "+" | ".join(parts)+footer)

@app.get("/api/v1/gear")
@game_transaction
def gear(channel:str,uid:str,name:str="Citizen",provider:str="twitch"):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);rows=db.execute(select(QualityGear).where(QualityGear.channel_id==channel,QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0).order_by(QualityGear.item_name)).scalars().all()
        if not rows:return out("🛠️ No quality gear yet. Craft equipment from All recipes." if provider=="discord" else "🛠️ No quality gear yet. Use /make to browse and craft equipment.")
        def gear_line(x):
            fam=db.execute(select(GearFamiliarity).where(GearFamiliarity.channel_id==channel,GearFamiliarity.canonical_uid==p.twitch_uid,GearFamiliarity.item_key==x.item_key)).scalar_one_or_none();uses=fam.uses if fam else 0;rank,reduction=gear_familiarity_rank(uses)
            return f"{x.quality} {x.item_name} x{x.qty} — {x.condition}% · {rank} familiarity ({uses} uses, -{int(reduction*100)}pp wear)"
        return PlainTextResponse("🛠️ Quality Gear\n\n"+"\n".join("• "+gear_line(x) for x in rows)) if provider=="discord" else out("🛠️ "+" | ".join(gear_line(x) for x in rows[:10]))

def gear_repair_cost(condition):
    """Iron Nails to restore gear: 5 per 20% of missing condition (legacy: 1 Component)."""
    return 0 if condition>=100 else 5*max(1,(100-condition+19)//20)

@app.get("/api/v1/gearrepair")
@colony_command
def gearrepair(channel:str,uid:str,name:str="Citizen",item:str="",provider:str="twitch"):
    key=(item or "").lower().strip().replace(" ","_")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);life=life_state(db,p);blocked=task_need_gate(db,p,"gearrepair",provider,life)
        if blocked:return PlainTextResponse(blocked) if provider=="discord" else out(blocked)
        rows=db.execute(select(QualityGear).where(QualityGear.channel_id==channel,QualityGear.canonical_uid==p.twitch_uid,QualityGear.qty>0)).scalars().all()
        row=next((x for x in rows if f"gear_{x.id}"==key or x.item_key==key or x.item_name.lower()==(item or "").lower()),None)
        if not row:return out("🔧 Gear not found. Use "+("/inventory section:gear" if provider=="discord" else "!gear")+" to see your equipment.")
        if row.condition>=100:return out("🔧 That item is already at full condition. Nothing spent.")
        cost=gear_repair_cost(row.condition)
        if p.components<cost:return out(f"🔧 Repair needs {cost} Iron Nails. You have {p.components}. Iron Nails: {material_source('components',provider)} Nothing spent.")
        p.components-=cost;row.condition=100;spend_life_for_action(life,"repair")
        xp=main.gain_skill(p,"infrastructure",1);main.gain_branch(db,p,"maintenance_repair",xp)
        found=practice.find(db,p,"infrastructure","maintenance_repair");db.commit()
        text=(f"🔧 Repaired {row.quality} {row.item_name} to 100% (-{cost} Iron Nails · {need_cost_text(work_energy('repair'))}). "
              f"+{xp} Engineering and Maintenance & Repair XP."+(f" {found}." if found else "")+task_readiness_warning(life,provider))
        return PlainTextResponse(text) if provider=="discord" else out(text)

@app.get("/api/v1/use")
@colony_command
def use_item(channel:str,uid:str,name:str="Citizen",item:str="",provider:str="twitch"):
    source_item=seed_content.find_item(item or '')
    if source_item in seed_content.ACTIVE:
        if source_item in seed_content.EDIBLE:return main.action('eat',channel,uid,name,msg='food:'+source_item,provider=provider)
        import sys
        with SessionLocal() as db:
            _,p=player(db,channel,provider,uid,name)
            result=seed_content.use(db,p,source_item,provider)
            return platform_response(provider,result,result.replace('\n',' | '))
    key=(item or "").lower().strip().replace(" ","_")
    key=next((k for k in LIFE_GEAR if key in {k,QUALITY_RECIPES[k]["name"].lower().replace(" ","_")}),key)
    if key not in LIFE_GEAR:return out("🎒 Choose an owned item from /use. Crafted life gear: "+", ".join(QUALITY_RECIPES[k]["name"] for k in LIFE_GEAR)+". Nothing spent.")
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name);rows=db.execute(select(QualityGear).where(QualityGear.channel_id==channel,QualityGear.canonical_uid==p.twitch_uid,QualityGear.item_key==key,QualityGear.qty>0)).scalars().all()
        if not rows:return out("🎒 You do not have that life item. Craft it with /make.")
        row=max(rows,key=lambda x:list(QUALITY_TIERS).index(x.quality));tier=QUALITY_TIERS[row.quality];boost=10+int(tier["special"]*100);life=life_state(db,p)
        before={field:getattr(life,field) for field in ("nutrition","energy","social","comfort","morale")}
        if key=="meal_kit":life.nutrition=clamp100(life.nutrition+65+boost);life.morale=clamp100(life.morale+5)
        elif key=="recreation_set":life.social=clamp100(life.social+18+boost);life.morale=clamp100(life.morale+12)
        else:life.comfort=clamp100(life.comfort+30+boost);life.energy=clamp100(life.energy+8)
        changes=" · ".join(f"{field.title()} {before[field]}→{getattr(life,field)}/100" for field in before if before[field]!=getattr(life,field))
        row.qty-=1;db.commit();return out(f"🎒 Used {row.quality} {row.item_name}. {changes or 'Needs already full'}; item consumed.")
