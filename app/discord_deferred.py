"""Acknowledge slow queue commands before doing database work.

The initial HTTP response is Discord type 5. A synchronous background task runs
in Starlette's thread pool and edits that original private response. Retrying
message delivery never repeats the game command. Tokens remain request-local.
"""
import contextvars
import logging
import time
import requests

# True while edit_original fills a new deferred message (an answer acknowledged with type 5)
# rather than changing the message a button sits on.
NEW_MESSAGE = contextvars.ContextVar('ne_new_message', default=False)


def edit_original(application_id,token,data):
    """Replace "thinking…" (or a button's message) with the reply, in the layout it needs.

    The reply goes out in Discord's newer layout when layout_v2 says so. If Discord
    refuses it, the old layout is sent instead, unless the message is already in the
    new layout (it cannot go back), in which case the reply is sent without buttons.
    """
    from . import layout_v2,ui
    url=f'https://discord.com/api/v10/webhooks/{application_id}/{token}/messages/@original'
    payload=None if NEW_MESSAGE.get() else ui.INTERACTION.get()
    old=layout_v2.private({k:v for k,v in data.items() if k!='flags'})
    new=layout_v2.edit(data,payload)
    fallbacks=[] if new is None else [layout_v2.without_buttons(new) if layout_v2.locked(payload) else old]
    data=new or old
    attempt=0
    while attempt<3:
        try:
            response=requests.patch(url,json=data,timeout=8)
            if 200<=response.status_code<300:return True
            if response.status_code==429:
                try:delay=max(0.1,min(10,float(response.json().get('retry_after',1))))
                except (ValueError,TypeError):delay=1
            elif response.status_code>=500:delay=1
            else:
                logging.getLogger(__name__).error('Discord deferred response rejected (HTTP %s): %s',response.status_code,response.text[:300])
                if response.status_code==400 and fallbacks:
                    data=fallbacks.pop(0)
                    continue
                if response.status_code==400 and data.get('components') and not layout_v2.is_v2(data):
                    # Never leave the player on "thinking…": send the result without buttons.
                    data={k:v for k,v in data.items() if k!='components'}
                    continue
                return False
        except requests.RequestException:delay=1
        attempt+=1
        if attempt<3:time.sleep(delay)
    logging.getLogger(__name__).error('Discord deferred response delivery failed; gameplay was not retried')
    return False


def finish(m,payload,command,uid,name,options):
    origin=m.task_queue.queue_notifications.origin_channel
    token=origin.set(str(payload.get('channel_id') or ''))
    m.ui.INTERACTION.set(payload)   # lets /menu show moderator tools to moderators
    try:
        options=m.extras.default_options(m,command,options,uid)   # e.g. /make reopens where you left off
        result=m.discord_execution.execute(m,payload,command,uid,name,options)
        try:m.extras.record_discord(m,uid,name,command,options)
        except Exception:logging.getLogger(__name__).error('Recent action not recorded: %s',command)
    except Exception:
        logging.getLogger(__name__).error('Deferred Discord command rolled back: %s',command)
        data={'content':'This request could not be completed. Check /queue for any existing queue before trying again.',
              'allowed_mentions':{'parse':[]}}
    else:
        # Public receipts omit private modifier calculations. No extra unsolicited
        # follow-up: the action has one response, with only relevant changes.
        # Every ticket the reply's buttons need is saved in one transaction.
        with m.ui.ticket_batch(m):
            try:
                # Workbench, mining, gathering and queue replies carry dropdowns and buttons.
                data=m.ui.slash_panel(m,command,uid,name,options,result) or m._discord_json_message(result,message_type=command)['data']
                # Lists such as a skill's tasks get a button beside each item in the newer layout.
                data=m.ui.add_list_items(m,data,uid,command,options,name)
                # Every reply offers the next step as buttons: Again, its menu area, and Menu.
                if command!='menu':
                    try:
                        rows=[r for r in data.get('components') or [] if r.get('components')]
                        if len(rows)<5:data['components']=rows+m.menu.after_rows(m,command,options,uid,5-len(rows))
                    except Exception:
                        logging.getLogger(__name__).error('Menu buttons could not be added: %s',command)
            except Exception:
                logging.getLogger(__name__).error('Saved command result could not be formatted: %s',command)
                data={'content':result[:1800], 'allowed_mentions':{'parse':[]}}
    finally:origin.reset(token)
    edit_original(str(payload['application_id']),str(payload['token']),m.ui.tidy(data))
    # Private notifications: warnings and tips raised by this command, and anything
    # waiting in the player's inbox, shown only to them.
    try:
        m.inbox.after_command(m,uid,name,command,options,locals().get('result',''))
        m.inbox.deliver(m,payload,uid)
    except Exception:
        logging.getLogger(__name__).error('Private notifications could not be delivered: %s',command)


def opens_form(payload):
    """True for a press that opens a pop-up form: Discord only shows a form as the first answer."""
    from . import ui
    custom_id=str((payload.get('data') or {}).get('custom_id') or '')
    return payload.get('type')==3 and ui.handles(custom_id) and custom_id.split('|')[2:3]==['mo']


def can_answer_later(payload):
    return bool(payload.get('application_id') and payload.get('token')) and not opens_form(payload)


def ack(payload):
    """Discord's answer to a press or form before any game work, so no press can time out
    ("This interaction failed" after 3 seconds). A private panel changes in place (type 6);
    a press on a shared message is answered privately under "thinking…" (type 5)."""
    if int((payload.get('message') or {}).get('flags') or 0)&64:
        return {'type':6}
    return {'type':5,'data':{'flags':64}}


def answer_later(m,payload):
    """Work out the answer to an acknowledged press or form (see ack) and deliver it.

    Work a button schedules (an action, private notifications) runs after the answer,
    in order. A failure is reported privately; game state rolls back as usual.
    """
    from . import ui,message_layout
    in_place=ack(payload)['type']==6
    later=[]
    schedule=lambda fn,*args:later.append((fn,args))
    custom_id=str((payload.get('data') or {}).get('custom_id') or '')
    token=NEW_MESSAGE.set(not in_place)        # under "thinking…" every answer is a new message
    try:
        ui.INTERACTION.set(payload)
        try:
            if payload.get('type')==5:
                answer=ui.handle_modal(m,payload,schedule)
            elif ui.handles(custom_id):
                answer=ui.handle_component(m,payload,schedule)
            else:
                answer=message_layout.open_page(m,payload)
                if isinstance(answer.get('data'),dict):        # Details pages end with ◀️ Back and 🏠 Menu too
                    if answer.get('type')==7:
                        ui._left_screen(payload,ui._user(payload)[0])   # Back returns to the screen's first page
                    ui.with_menu(answer['data'],ui._user(payload)[0] or None)
        except Exception:
            logging.getLogger(__name__).exception('Button answer failed: %s',custom_id[:60])
            later.clear()
            answer={'type':4,'data':{'content':'That button could not be completed and nothing was spent. Open /menu again for fresh buttons.',
                                     'flags':64,'allowed_mentions':{'parse':[]}}}
        deliver(payload,answer,in_place)
        for fn,args in later:
            try:fn(*args)
            except Exception:logging.getLogger(__name__).exception('Button follow-up work failed: %s',getattr(fn,'__name__',fn))
    finally:
        NEW_MESSAGE.reset(token)


def deliver(payload,answer,in_place):
    from . import ui
    kind=answer.get('type') if isinstance(answer,dict) else None
    app,tok=str(payload['application_id']),str(payload['token'])
    if kind==9:
        # Only a press can open a form (opens_form); never leave the player waiting.
        answer,kind={'type':4,'data':{'content':'Press the button again to open the form.','flags':64}},4
    if kind not in (4,7):
        return                                  # an action answers by itself (finish_ticket)
    data=ui.tidy(dict(answer.get('data') or {}))
    if kind==4 and in_place:
        follow_up(app,tok,data)                 # a new message below the panel (private if flagged)
    else:
        edit_original(app,tok,data)             # the panel itself, or the "thinking…" message


def follow_up(application_id,token,data):
    """Send a new message after the acknowledgement, in the newer layout with the old one as a fallback."""
    from . import layout_v2
    url=f'https://discord.com/api/v10/webhooks/{application_id}/{token}'
    old=layout_v2.private(data)
    new=layout_v2.new_message(data)
    bodies=[new,old] if layout_v2.is_v2(new) else [old]
    for body in bodies:
        for attempt in range(3):
            try:
                response=requests.post(url,json=body,timeout=8)
            except requests.RequestException:
                time.sleep(1);continue
            if 200<=response.status_code<300:return True
            if response.status_code==429 or response.status_code>=500:
                try:delay=max(0.1,min(10,float(response.json().get('retry_after',1))))
                except (ValueError,TypeError,AttributeError):delay=1
                time.sleep(delay);continue
            logging.getLogger(__name__).error('Discord follow-up rejected (HTTP %s): %s',response.status_code,response.text[:300])
            break
    return False


def defer(response,payload,later):
    """Acknowledge a button or form answer at once and send it right after, like a slash reply.

    Sent this way, an answer Discord refuses in the newer layout falls back to the old one
    (see edit_original) instead of failing the press. `later(fn, *args)` runs fn after the
    acknowledgement. Other responses (pop-up forms, deferrals) are returned unchanged.
    """
    if not isinstance(response,dict) or response.get('type') not in (4,7) or not payload.get('application_id') or not payload.get('token'):
        return response
    later(send_answer,payload,response)
    if response['type']==7:return {'type':6}
    private=int((response.get('data') or {}).get('flags') or 0)&64
    return {'type':5,'data':{'flags':64} if private else {}}


def send_answer(payload,response):
    from . import ui
    ui.INTERACTION.set(payload)
    token=NEW_MESSAGE.set(response.get('type')==4)
    try:
        edit_original(str(payload['application_id']),str(payload['token']),ui.tidy(dict(response.get('data') or {})))
    finally:
        NEW_MESSAGE.reset(token)
