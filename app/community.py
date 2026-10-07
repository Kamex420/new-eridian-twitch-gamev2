"""Community features that tie the colony together: colony votes, stream challenges, seasons, trophies and
the weekly recap. This module wires them into the game:

  * after every command (commands.py): trophies, season points, stream-challenge progress, live detection
  * success chances (main.world_rule_bundle): +5% from a voted festival or the running stream challenge
  * the overlay payload: the challenge goal bar, the vote, the season, built landmarks, hats and badges
  * Twitch endpoints (StreamElements) and Discord commands (/vote, /season, /challenge, /trophies, /mod)
  * one background worker: closes ballots, runs stream challenges, rolls seasons over and posts the recap

The rules of each feature live in votes.py, live_events.py, seasons.py, trophies.py and recap.py.
"""
import logging
from sqlalchemy import select
from . import votes, live_events, seasons, trophies, recap

ENABLED = True       # tests that check exact SC totals switch the whole set off
log = logging.getLogger(__name__)
ROUTES = {}          # the endpoint functions, reused by the Discord commands


def install(m):
    for mod in (seasons, trophies, votes):
        mod.install(m)
    _routes(m)
    try:
        import asyncio
        from discord.ext import tasks
    except Exception:
        return

    @tasks.loop(seconds=20, reconnect=True)
    async def timer():
        try:
            await asyncio.to_thread(tick, m)
        except Exception:
            log.error('Community pass failed; retrying')

    async def start():
        m.app.state.community_worker = timer.start()

    async def stop():
        timer.stop()
    m.app.add_event_handler('startup', start)
    m.app.add_event_handler('shutdown', stop)


def tick(m):
    """Close ballots, run stream challenges, roll the season over and post the Sunday recap."""
    if not ENABLED:
        return
    with m.task_queue.atomic(m, m.DISCORD_WORLD_ID):
        with m.SessionLocal() as db:
            votes.sync(m, db)
            live_events.tick(m, db)
            seasons.current(m, db)
            db.commit()
            try:
                recap.tick(m, db)
            except Exception:
                log.exception('Weekly recap failed; it will try again')
            db.commit()
    # The channel feed talks to Discord over the network, so it runs outside the world lock.
    try:
        from . import activity_feed
        activity_feed.tick(m)
    except Exception:
        log.exception('Activity feed update failed; it will try again')


# ---------------------------------------------------------------- hooks

def after_command(m, db, p, fn_name, params, before, after):
    """Returns (Discord note, short chat note). Never raises."""
    if not ENABLED:
        return '', ''
    from .autonomy import ACTING
    acting = ACTING.get()
    provider = params.get('provider') or 'twitch'
    discord, chat = [], []
    try:
        if provider != 'discord' and not acting:
            live_events.seen_on_twitch(p.twitch_uid)
        if not acting:
            d, c = live_events.from_command(m, db, p, before, after, provider)
            if d:
                discord.append(d)
                chat.append(c)
        try:
            from . import activity_feed
            activity_feed.record(m, db, p, fn_name, params, before, after, acting)
        except Exception:
            log.exception('Activity feed entry not recorded')
        if not acting:
            gift = votes.festival_gift(m, db, p)
            if gift:
                discord.append('🎉 ' + gift)
                chat.append(gift)
        if acting and before and after:      # season points count only the Contribution the Seedling may keep today (autonomy.CONTRIBUTION_CAP)
            from .autonomy import contribution_room
            had, now = before.get('Resources', {}).get('contribution', 0), after.get('Resources', {}).get('contribution', 0)
            room = contribution_room(m, db, p)
            if now - had > room:
                after = {**after, 'Resources': {**after.get('Resources', {}), 'contribution': had + room}}
        note = seasons.from_command(m, db, p, before, after, acting)
        if note:
            discord.append(note)
            chat.append(note.split('!')[0] + '!')
        for note in trophies.from_command(m, db, p, fn_name, before, after):
            discord.append(note)
            chat.append(note.split(' (')[0])
    except Exception:
        log.exception('Community hook failed for one command')
    return '\n'.join(discord), ' | '.join(chat)


def profile_lines(m, db, p):
    if not ENABLED:
        return []
    out = []
    try:
        line = trophies.profile_line(m, db, p)
        if line:
            out.append(line)
        season = seasons.current(m, db)
        rank, row = seasons.rank_of(db, season, p)
        s = seasons.info(season)
        out.append(f"{s['emoji']} Season {s['number']}: {row.points:,} points" + (f' · #{rank}' if rank else '') if row and row.points else
                   f"{s['emoji']} Season {s['number']}: no points yet · /season")
        past = seasons.history_text(m, db, p)
        if past:
            out.append(past)
    except Exception:
        log.exception('Profile community lines failed')
    return out


def success_modifier(m, db, p, skill):
    if not ENABLED or not skill:
        return 0, []
    total, notes = 0, []
    for fn in (votes.success_bonus, live_events.board_bonus):
        try:
            b, n = fn(m, db, skill)
        except Exception:
            b, n = 0, []
        total += b
        notes += n
    try:
        b, n = votes.building_bonus(m, db, p, skill)
    except Exception:
        b, n = 0, []
    return total + b, notes + n


def overlay_data(m, db, seedlings):
    """Extra overlay keys; also adds each Seedling's cosmetic hat and pinned badge."""
    if not ENABLED:
        return {}
    out = {}
    for key, fn in (('vote', votes.overlay), ('season', seasons.overlay)):
        try:
            out[key] = fn(m, db)
        except Exception:
            log.exception('Overlay %s failed', key)
    try:
        out.update(live_events.overlay(m, db))
    except Exception:
        log.exception('Overlay challenge failed')
    try:
        import hashlib
        ids = {}
        for p in db.execute(select(m.Player.channel_id, m.Player.twitch_uid)).all():
            ids[hashlib.sha1(f'{p[0]}:{p[1]}'.encode()).hexdigest()[:10]] = (p[0], p[1])
        keys = {ids[s['id']] for s in seedlings if s.get('id') in ids}
        hats, badges = seasons.worn_hats(db, keys), trophies.badges_for(db, keys)
        for s in seedlings:
            k = ids.get(s.get('id'))
            if k in hats:
                s['hat'] = hats[k]
            if k in badges:
                s['badge'] = badges[k]
    except Exception:
        log.exception('Overlay hats and badges failed')
    return out


# ---------------------------------------------------------------- Twitch endpoints (StreamElements) and HTTP

def _routes(m):
    from fastapi.responses import PlainTextResponse
    app, tx = m.app, m.game_transaction

    def player(db, channel, provider, uid, name):
        return m.player(db, channel, provider, uid, name)[1]

    def reply(provider, text):
        return m.platform_response(provider, text, text.replace('**', '').replace('\n', ' · ') if provider != 'discord' else text)

    @app.get('/api/v1/vote')
    @tx
    def vote(channel: str, uid: str, name: str = 'Citizen', choice: str = '', provider: str = 'twitch'):
        """Today's colony vote; with a choice (1-3 or a name), cast or change your vote."""
        with m.SessionLocal() as db:
            p = player(db, channel, provider, uid, name)
            text = votes.cast(m, db, p, choice, provider) if str(choice or '').strip() else votes.view(m, db, p, provider)
            if str(choice or '').strip():
                got = trophies.check(m, db, p, force=True)
                if got:
                    text += ('\n' + '\n'.join(got)) if provider == 'discord' else ' | ' + ' | '.join(g.split(' (')[0] for g in got)
            db.commit()
            return reply(provider, text)

    @app.get('/api/v1/seasons')
    @tx
    def season(channel: str, uid: str, name: str = 'Citizen', section: str = '', provider: str = 'twitch'):
        """The season: your points and rank (blank), top, rewards, story or hats."""
        section = str(section or '').strip().casefold()
        with m.SessionLocal() as db:
            p = player(db, channel, provider, uid, name)
            if section in {'top', 'leaderboard', 'lb'}:
                text = seasons.top_text(m, db, p, provider)
            elif section in {'rewards', 'reward'}:
                text = seasons.rewards_text(m, db, p, provider)
            elif section == 'story':
                text = seasons.story_text(m, db, provider)
            elif section in {'hats', 'hat'}:
                text = seasons.wear(db, p, '', provider)
            else:
                text = seasons.overview(m, db, p, provider)
            db.commit()
            return reply(provider, text)

    @app.get('/api/v1/hat')
    @tx
    def hat(channel: str, uid: str, name: str = 'Citizen', hat: str = '', provider: str = 'twitch'):
        """Your cosmetic hats; with a name, your Seedling wears it on the stream map (job = the job hat)."""
        with m.SessionLocal() as db:
            p = player(db, channel, provider, uid, name)
            text = seasons.wear(db, p, hat, provider)
            db.commit()
            return reply(provider, text)

    @app.get('/api/v1/challenge')
    @tx
    def challenge(channel: str, uid: str = '', name: str = 'Citizen', provider: str = 'twitch'):
        """The running stream challenge: goal, time left, your share and how to help."""
        with m.SessionLocal() as db:
            p = player(db, channel, provider, uid, name) if uid else None
            text = live_events.view(m, db, p, provider)
            db.commit()
            return reply(provider, text)

    @app.get('/api/v1/trophies')
    @tx
    def trophies_view(channel: str, uid: str, name: str = 'Citizen', group: str = '', provider: str = 'twitch'):
        """Trophies and collections: what you have, what is close, and the badge you show."""
        with m.SessionLocal() as db:
            p = player(db, channel, provider, uid, name)
            text = trophies.view(m, db, p, provider, str(group or '').strip().casefold())
            db.commit()
            return reply(provider, text)

    @app.get('/api/v1/badge')
    @tx
    def badge(channel: str, uid: str, name: str = 'Citizen', badge: str = '', provider: str = 'twitch'):
        """Pin a trophy badge next to your name on the stream map; blank lists yours."""
        with m.SessionLocal() as db:
            p = player(db, channel, provider, uid, name)
            trophies.check(m, db, p, force=True)
            text = trophies.pin(m, db, p, badge, provider)
            db.commit()
            return reply(provider, text)

    @app.get('/api/v1/recap')
    @tx
    def recap_view(channel: str = '', provider: str = 'discord'):
        """This week's recap as text (Twitch: this week's top three)."""
        with m.SessionLocal() as db:
            if provider != 'discord':
                text = recap.chat_line(m, db)
                db.commit()
                return m.out(text)
            _, _, text = recap.build(m, db)
            db.commit()
            return PlainTextResponse(text)

    def mod_ok(key, level):
        # Owner-only: MOD_KEY and the broadcaster's StreamElements level (see main.twitch_owner_ok).
        return m.twitch_owner_ok(key, level)

    @app.get('/api/v1/admin/live')
    @tx
    def admin_live(channel: str = '', state: str = '', level: int = 0, key: str = ''):
        """!live on|off|auto for the channel owner (StreamElements passes the level and the moderator key)."""
        if not mod_ok(key, level):
            return m.out(m.OWNER_ONLY_TEXT)
        with m.SessionLocal() as db:
            text = live_events.set_live(m, db, state, 'StreamElements moderator')
            m.audit_moderator(db, m.DISCORD_WORLD_ID, 'StreamElements level ' + str(level), 'live', state or 'view')
            db.commit()
            return m.out(text)

    @app.get('/api/v1/admin/challenge')
    @tx
    def admin_challenge(channel: str = '', action: str = 'start', event: str = '', level: int = 0, key: str = ''):
        """!challenge start [name] / !challenge stop for the channel owner."""
        if not mod_ok(key, level):
            return m.out(m.OWNER_ONLY_TEXT)
        with m.SessionLocal() as db:
            if str(action).casefold() == 'stop':
                text = live_events.cancel(m, db, 'a moderator')
            else:
                _, text = live_events.start(m, db, str(event or '').strip().casefold().replace(' ', '_'), 'moderator')
            m.audit_moderator(db, m.DISCORD_WORLD_ID, 'StreamElements level ' + str(level), 'challenge', f'{action} {event}'.strip())
            db.commit()
            return m.out(text)

    ROUTES.update(vote=vote, season=season, hat=hat, challenge=challenge, trophies=trophies_view, badge=badge)

    @app.get('/api/v1/admin/recap')
    @tx
    def admin_recap(channel: str = '', action: str = 'preview', level: int = 0, key: str = ''):
        """Preview or post the weekly recap now (channel owner)."""
        if not mod_ok(key, level):
            return m.out(m.OWNER_ONLY_TEXT)
        with m.SessionLocal() as db:
            if action == 'post':
                ok, text = recap.post(m, db, force=True)
            else:
                _, _, text = recap.build(m, db)
            db.commit()
            return PlainTextResponse(text)


# ---------------------------------------------------------------- Discord

DISCORD = {'vote', 'season', 'challenge', 'trophies'}
MOD = {'challengestart', 'challengestop', 'liveon', 'liveoff', 'liveauto', 'recappreview', 'recappost', 'feedhere', 'feedoff'}


def discord(m, command, uid, name, options):
    channel = m.DISCORD_WORLD_ID
    if command == 'vote':
        return ROUTES['vote'](channel, uid, name, str(options.get('choice') or ''), 'discord').body.decode()
    if command == 'season':
        section = str(options.get('section') or '')
        if options.get('hat'):
            return ROUTES['hat'](channel, uid, name, str(options['hat']), 'discord').body.decode()
        return ROUTES['season'](channel, uid, name, section, 'discord').body.decode()
    if command == 'challenge':
        return ROUTES['challenge'](channel, uid, name, 'discord').body.decode()
    if command == 'trophies':
        if options.get('badge'):
            return ROUTES['badge'](channel, uid, name, str(options['badge']), 'discord').body.decode()
        return ROUTES['trophies'](channel, uid, name, str(options.get('group') or ''), 'discord').body.decode()
    actor = f'{name} ({uid})'
    with m.SessionLocal() as db:
        if command == 'challengestart':
            _, text = live_events.start(m, db, str(options.get('challenge') or ''), actor)
        elif command == 'challengestop':
            text = live_events.cancel(m, db, name)
        elif command in {'liveon', 'liveoff', 'liveauto'}:
            text = live_events.set_live(m, db, command[4:], actor)
        elif command == 'feedhere':
            from . import activity_feed
            text = activity_feed.here(m, db, m.task_queue.queue_notifications.origin_channel.get())
        elif command == 'feedoff':
            from . import activity_feed
            text = activity_feed.off(m, db)
        elif command == 'recappost':
            ok, text = recap.post(m, db, force=True)
        else:
            title, sections, _ = recap.build(m, db)
            text = '**' + title + '**\n\n' + '\n\n'.join(f'**{h}**\n{t}' for h, t in sections)
            text = text[:1900] + ('\n…' if len(text) > 1900 else '') + '\n\n(Preview. /mod action:recappost posts it for everyone.)'
        m.audit_moderator(db, channel, actor, command, str(options.get('challenge') or ''))
        db.commit()
        return text
