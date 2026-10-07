# app/main.py, part 25: routes extra
# Routes: status, settings, favorites, fetch, sell-all, recover, trick-or-treat, find, again, craft max, targets,
# routines, uses, autosell, keep levels, shopping, Seedlings; then fun systems and seasons.
# Runs inside app.main's namespace, after the parts before it (see main.py). Not a module of its own.

@app.get('/api/v1/status')
@game_transaction
def status_view(channel:str,uid:str,name:str='Citizen',provider:str='twitch'):
    """Needs, queue, cooldowns, ready recipes and the next step in one view."""
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        text=qol.status_text(sys.modules[__name__],db,p,provider);db.commit()
        return platform_response(provider,text,text)


@app.get('/api/v1/settings')
@game_transaction
def settings(channel:str,uid:str,name:str='Citizen',alerts:str='',autorecover:str='',provider:str='twitch',text:str='',popups:str='',feed:str=''):
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        note=''
        if str(feed).lower() in {'on','off'}:
            note=activity_feed.set_hidden(db,p,str(feed).lower()=='off')+'\n\n';db.commit()
        body=qol.settings_text(sys.modules[__name__],db,p,provider,alerts,autorecover,text,popups)
        if provider=='discord':body+='\n'+('🙈 Channel feed: your activity is hidden (/settings feed:on shows it).' if activity_feed.hidden(db,p) else '📣 Channel feed: your gathering, crafting, level ups and trophies show in the channel (/settings feed:off hides them).')
        return platform_response(provider,note+body,note.strip() or body)


@app.get('/api/v1/favorite')
@game_transaction
def favorite(channel:str,uid:str,name:str='Citizen',recipe:str='',provider:str='twitch'):
    """Toggle a favourite recipe; with no recipe, list favourites."""
    module=sys.modules[__name__]
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        if not recipe.strip():return platform_response(provider,*(qol.favorites_text(module,db,p,provider),)*2)
        found=workbench.resolve(module,db,p,recipe);note=''
        if found is None:
            found,note,suggestions=qol.fuzzy_recipe(module,db,p,recipe)
            if found is None:return out('⭐ Unknown recipe.'+qol.did_you_mean(suggestions)+' Nothing changed.')
        text=(note+' ' if note else '')+qol.set_favorite(module,db,p,found.id);db.commit()
        return platform_response(provider,text,text)


def batches_argument(text,batches):
    """'Iron Plate 5' -> ('Iron Plate', 5); an explicit batches value wins."""
    head,_,tail=(text or '').strip().rpartition(' ')
    if tail.isdigit() and head and not batches:return head,int(tail)
    return (text or '').strip(),batches or 1


@app.get('/api/v1/fetch')
@game_transaction
def fetch_ingredients(channel:str,uid:str,name:str='Citizen',recipe:str='',batches:int=0,action:str='plan',provider:str='twitch'):
    """Plan (or start) gathering a recipe's missing ingredients, then crafting it."""
    module=sys.modules[__name__];recipe,batches=batches_argument(recipe,batches);batches=max(1,min(10,batches))
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        found=workbench.resolve(module,db,p,recipe) if recipe else None;note=''
        if found is None:
            found,note,suggestions=qol.fuzzy_recipe(module,db,p,recipe) if recipe else (None,'',[])
            if found is None:return out('🧺 Choose a recipe: !fetch <recipe name> [batches].'+qol.did_you_mean(suggestions)+' Nothing spent.')
        text,start=qol.fetch_plan(workbench.Context(module,db,p,provider),found,batches)
        if note:text=note+' '+text
        if action!='start':return platform_response(provider,text,text)
    if not start:return out(text)
    result=queued_tasks(channel,uid,name,'start',start['task'],start['count'],provider).body.decode()
    if start['then'] and ('RUNNING' in result or 'PAUSED' in result):
        queued_tasks(channel,uid,name,'next',start['then']['task'],start['then']['count'],provider)
        result=f"🧺 Fetching for {found.name}; it is queued to craft next. "+result
    return platform_response(provider,result,result)


@app.get('/api/v1/sellall')
@colony_command
def sell_all_items(channel:str,uid:str,name:str='Citizen',item:str='',provider:str='twitch'):
    key=seed_content.find_item(item or '')
    if key not in SEED_INDUSTRIES:
        key,suggestions=qol.fuzzy_item(item,SEED_INDUSTRIES) if item else (None,[])
        if key is None:return out('🏭 Choose an item Seed Industries buys.'+qol.did_you_mean(suggestions)+' Nothing sold.')
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        return out(qol.sell_all(sys.modules[__name__],db,p,key,provider))


@app.get('/api/v1/clearout')
@colony_command
def clearout(channel:str,uid:str,name:str='Citizen',confirm:str='',provider:str='twitch'):
    """Preview selling surplus materials; confirm=confirm sells them."""
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        text=qol.clearout(sys.modules[__name__],db,p,provider,str(confirm).strip().casefold() in {'confirm','yes','1','true'})
        return platform_response(provider,text,text)


@app.get('/api/v1/recover')
@colony_command
def recover_needs(channel:str,uid:str,name:str='Citizen',provider:str='twitch'):
    """One press: relax, games, cheapest food, comfort items or sleep for every blocking need."""
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        text=qol.recover_text(sys.modules[__name__],db,p,provider);db.commit()
        return platform_response(provider,text,text)



@app.get('/api/v1/trick')
@colony_command
def trick_or_treat(channel:str,uid:str,name:str='Citizen',provider:str='twitch'):
    """Halloween trick-or-treat: a treat or a harmless trick, 5 doors a day while the festival is on (app/halloween.py)."""
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        text=halloween.trick(sys.modules[__name__],db,p,provider)
        db.commit()
    return platform_response(provider,text,text)

@app.get('/api/v1/eatfull')
@colony_command
def eat_full(channel:str,uid:str,name:str='Citizen',provider:str='twitch'):
    """Eat the cheapest everyday food until Nutrition reaches 80 (festival foods and Meal Kits are kept)."""
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        text=extras.eat_full(sys.modules[__name__],db,p,provider);db.commit()
        return platform_response(provider,text,text)


@app.get('/api/v1/undo')
@game_transaction
def undo_sale(channel:str,uid:str,name:str='Citizen',provider:str='twitch'):
    """Take back your last Seed Industries sale within 60 seconds."""
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        text=extras.undo_sale(sys.modules[__name__],db,p);db.commit()
        return platform_response(provider,text,text)


@app.get('/api/v1/find')
def find_anything(query:str='',provider:str='twitch',channel:str='',uid:str='',name:str='Citizen'):
    """Search recipes, items, menu buttons and handbook topics, or answer a question (app/ask.py)."""
    if not query.strip():return out('🔎 Search or ask anything: !find <word or question>, e.g. !find campfire or !find how do I make Iron Nails')
    with SessionLocal() as db:
        p=ask.existing_player(sys.modules[__name__],db,channel,provider,uid)
        text=ask.reply(sys.modules[__name__],db,p,query.strip()[:ask.MAX_QUERY],provider,channel)
        db.commit()
    return platform_response(provider,text,text)


@app.get('/api/v1/again')
@game_transaction
def again(channel:str,uid:str,name:str='Citizen',provider:str='twitch'):
    """Repeat your last Twitch action (a task, craft, gather, food or item)."""
    module=sys.modules[__name__]
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        rows=extras.recent(db,p.channel_id,p.twitch_uid,'twitch',1);db.commit()
    if not rows:return out('🔁 Nothing to repeat yet. Do a task, craft, gather or eat first, then !again repeats it.')
    last=rows[0];fn=globals().get(last.command)
    if last.command not in extras.TWITCH_AGAIN or fn is None:return out('🔁 Your last action cannot be repeated. Nothing spent.')
    options=json.loads(last.options or '{}')
    if last.command=='action' and 'msg' not in options:options['msg']=f'again-{int(now().timestamp())}'
    return fn(channel=channel,uid=uid,name=name,provider=provider,**options)


@app.get('/api/v1/craftmax')
@game_transaction
def craft_max(channel:str,uid:str,name:str='Citizen',recipe:str='',provider:str='twitch'):
    """Queue as many batches (or gathering attempts) as your items and needs allow, up to 10."""
    module=sys.modules[__name__]
    if not recipe.strip():return out('🔁 Queue the most you can: !craftmax <recipe or resource>. Nothing spent.')
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        note='';key=seed_content.find_item(recipe)
        found=None if key in seed_content.GATHER else workbench.resolve(module,db,p,recipe)
        if key in seed_content.GATHER:task=('mine:' if key in task_queue.ores() else 'gather:')+key
        elif found is not None:task='make:'+found.id
        else:
            found,note,suggestions=qol.fuzzy_recipe(module,db,p,recipe)
            if found is None:
                key,_=qol.fuzzy_item(recipe,seed_content.GATHER)
                if key is None:return out('🔁 No recipe or resource called that.'+qol.did_you_mean(suggestions)+' Nothing spent.')
                task=('mine:' if key in task_queue.ores() else 'gather:')+key
            else:task='make:'+found.id
        if task not in task_queue.choices(module):return out('🔁 That cannot be queued. Nothing spent.')
        count,reason=extras.max_attempts(module,db,p,task);db.commit()
    label=task_queue.choices(module)[task]
    if count<=0:return out(f'🔁 You cannot do {label} even once right now: short on {reason}. Nothing spent.')
    result=queued_tasks(channel,uid,name,'start',task,str(count),provider).body.decode()
    prefix=(note+' ' if note else '')+f'🔁 Max ×{count} ({"limited by "+reason if count<10 else "the 10-attempt maximum"}). '
    return platform_response(provider,prefix+result,prefix+result)


@app.get('/api/v1/target')
@game_transaction
def target(channel:str,uid:str,name:str='Citizen',recipe:str='',provider:str='twitch'):
    """Pin a recipe as your goal; blank shows progress, 'clear' removes it."""
    module=sys.modules[__name__]
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        wanted=recipe.strip()
        if wanted.casefold() in {'clear','none','off','remove'}:
            extras.clear_goal(db,p);db.commit()
            return out('🎯 Goal cleared.')
        if wanted:
            found=workbench.resolve(module,db,p,wanted)
            note=''
            if found is None:
                found,note,suggestions=qol.fuzzy_recipe(module,db,p,wanted)
                if found is None:return out('🎯 No recipe called that.'+qol.did_you_mean(suggestions)+' Nothing changed.')
            text,plan=extras.start_goal(module,db,p,found.id,provider)
            text=(note+' ' if note else '')+text;goal=extras.goal_text(module,db,p,provider,plan);db.commit()   # planned once
            return platform_response(provider,text+'\n\n'+goal,text+' '+goal)
        text=extras.goal_text(module,db,p,provider);db.commit()
        return platform_response(provider,text,text)


@app.get('/api/v1/routines')
@game_transaction
def routines_view(channel:str,uid:str,name:str='Citizen',action:str='view',provider:str='twitch'):
    """Your plan and saved routines; action=save saves the current plan, action=clear empties the plan."""
    module=sys.modules[__name__]
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        action=str(action or 'view').casefold()
        if action=='save':text=extras.save_routine(module,db,p)
        elif action=='clear':extras.clear_plan(db,p);text='🗺️ Later plan steps cleared. The running queue carries on.'
        elif provider!='discord':
            saved=extras.routines(db,p)
            steps=extras.current_steps(module,db,p)
            text=('🗺️ Plan: '+(' → '.join(extras.step_label(module,st) for st in steps) or 'nothing')+' | Routines: '+
                  (', '.join(f'{i}. {r.name}' for i,r in enumerate(saved,1)) or 'none')+' | !routine <number> starts one; !routines save saves your plan')
        else:text=extras.plan_text(module,db,p)
        db.commit()
        return platform_response(provider,text,text)


def routine_start(channel:str,uid:str,name:str='Citizen',n:str='',provider:str='twitch'):
    """Start saved routine number n (1–5); 'delete n' removes it."""
    module=sys.modules[__name__]
    words=str(n or '').split()
    remove=bool(words) and words[0].casefold() in {'delete','remove','del'}
    if remove:words=words[1:]
    if not words or not words[0].isdigit():return out('🗺️ Choose a routine number: !routine 1. !routines lists them.')
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        saved=extras.routines(db,p);index=int(words[0])-1
        if not 0<=index<len(saved):return out(f'🗺️ You have {len(saved)} saved routines. !routines lists them.')
        chosen=saved[index].id
        if remove:
            extras.delete_routine(db,p,chosen);db.commit()
            return out(f'🗺️ Routine {index+1} deleted.')
        db.commit()
    text=extras.start_routine(module,channel,uid,name,provider,chosen)
    return platform_response(provider,text,text)


@app.get('/api/v1/uses')
@game_transaction
def item_uses(channel:str,uid:str,name:str='Citizen',item:str='',provider:str='twitch'):
    """Recipes that use an item, ready ones first."""
    module=sys.modules[__name__]
    key=seed_content.find_item(item or '')
    if key not in seed_content.ITEMS:
        key,suggestions=qol.fuzzy_item(item) if item else (None,[])
        if key is None:return out('🔍 Which item? !uses <item name>.'+qol.did_you_mean(suggestions))
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        text,_=extras.uses_text(module,db,p,key,provider);db.commit()
        return platform_response(provider,text,text)


@app.get('/api/v1/autosell')
@game_transaction
def autosell(channel:str,uid:str,name:str='Citizen',item:str='',provider:str='twitch'):
    """Toggle selling an item automatically when a queue finishes; blank lists them."""
    module=sys.modules[__name__]
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        if not item.strip():
            text=extras.autosell_text(module,db,p)
            return platform_response(provider,text,text)
        key=seed_content.find_item(item)
        if key not in SEED_INDUSTRIES:
            key,suggestions=qol.fuzzy_item(item,SEED_INDUSTRIES)
            if key is None:return out('🧹 Choose an item Seed Industries buys.'+qol.did_you_mean(suggestions)+' Nothing changed.')
        text=extras.toggle_autosell(module,db,p,key);db.commit()
        return platform_response(provider,text,text)


@app.get('/api/v1/keep')
@game_transaction
def keep_level(channel:str,uid:str,name:str='Citizen',text:str='',provider:str='twitch'):
    """Keep levels: blank lists them; '<item> <amount>' sets one (0 clears); 'restock' plans the first short item, 'restock go' starts it."""
    text=keep_levels.command(sys.modules[__name__],channel,uid,name,provider,text)
    return platform_response(provider,text,text)


@app.get('/api/v1/shopping')
@game_transaction
def shopping(channel:str,uid:str,name:str='Citizen',text:str='',provider:str='twitch'):
    """Shopping list: blank sums it up; 'add <recipe> [amount]' (0 removes), 'remove <recipe>', 'clear [done]'; 'buy' shows the cost, 'buy confirm' buys every missing material Seed Industries sells."""
    text=shopping_list.command(sys.modules[__name__],channel,uid,name,provider,text)
    return platform_response(provider,text,text)



@app.get('/api/v1/seedling')
@game_transaction
def seedling_view(channel:str,uid:str,name:str='Citizen',provider:str='twitch'):
    """Your Seedling: mood, thought, what it is doing where, its schedule and autonomy."""
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        text=autonomy.view_text(sys.modules[__name__],db,p,provider);db.commit()
    note=first_step_note(channel,uid,name,provider,'seedling')
    if note:text+=('\n\n' if provider=='discord' else ' | ')+note
    return platform_response(provider,text,text)


@app.get('/api/v1/diary')
@game_transaction
def seedling_diary(channel:str,uid:str,name:str='Citizen',provider:str='twitch'):
    """What your Seedling has been doing, newest first."""
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        text=autonomy.diary_text(sys.modules[__name__],db,p,provider);db.commit()
        return platform_response(provider,text,text)


@app.get('/api/v1/schedule')
@game_transaction
def seedling_schedule(channel:str,uid:str,name:str='Citizen',preset:str='',provider:str='twitch'):
    """Pick a daily schedule preset (balanced, workaholic, night_owl, socialite, homebody); blank lists them."""
    key=str(preset or '').strip().casefold().replace(' ','_').replace('-','_')
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        if not key:
            text='🗓️ Schedules: '+' | '.join(f'{k}: {v[1]}' for k,v in autonomy.PRESETS.items())
            return platform_response(provider,text,'🗓️ !schedule '+' | '.join(autonomy.PRESETS))
        text=autonomy.set_preset(db,p,key);db.commit()
        return platform_response(provider,text,text.replace('**',''))


@app.get('/api/v1/autonomy')
@game_transaction
def seedling_autonomy(channel:str,uid:str,name:str='Citizen',state:str='',provider:str='twitch'):
    """Turn your Seedling's autonomy on or off; blank shows it."""
    value=str(state or '').strip().casefold()
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        if value not in {'on','off'}:
            found=autonomy.row(db,p.channel_id,p.twitch_uid,create=True);db.commit()
            text=f"🌱 Autonomy is {'on' if found.enabled else 'off'}. !autonomy on or !autonomy off."
            return platform_response(provider,text,text.replace('**',''))
        text=autonomy.set_enabled(db,p,value=='on');db.commit()
        return platform_response(provider,text,text.replace('**',''))

@app.get('/api/v1/looks')
@game_transaction
def seedling_looks(channel:str,uid:str,name:str='Citizen',skin:str='',hair:str='',hair_colour:str='',outfit:str='',accessory:str='',
                   attitude:str='',catchphrase:str='',headwear:str='',provider:str='twitch'):
    """Your Seedling's looks and personality; any option given changes it ("random" puts one back)."""
    from . import looks
    with SessionLocal() as db:
        _,p=player(db,channel,provider,uid,name)
        changed,problems=looks.change(db,p,skin=skin,hair=hair,hair_colour=hair_colour,outfit=outfit,accessory=accessory,
                                     headwear=headwear,attitude=attitude,catchphrase=catchphrase)
        text=looks.view_text(sys.modules[__name__],db,p,provider,changed,problems);db.commit()
        return platform_response(provider,text,text.replace('**',''))

# Extension registration happens after core routes and models are available.
from .fun_systems import install as install_fun_systems
from .seasonal import install as install_seasonal
install_fun_systems(app)
install_seasonal(app)
