"""Acknowledge slow queue commands before doing database work.

The initial HTTP response is Discord type 5. A synchronous background task runs
in Starlette's thread pool and edits that original private response. Retrying
message delivery never repeats the game command. Tokens remain request-local.
"""
import logging
import time
import requests


def edit_original(application_id,token,data):
    url=f'https://discord.com/api/v10/webhooks/{application_id}/{token}/messages/@original'
    data={k:v for k,v in data.items() if k!='flags'}
    for attempt in range(3):
        try:
            response=requests.patch(url,json=data,timeout=8)
            if 200<=response.status_code<300:return True
            if response.status_code==429:
                try:delay=max(0.1,min(10,float(response.json().get('retry_after',1))))
                except (ValueError,TypeError):delay=1
            elif response.status_code>=500:delay=1
            else:
                logging.getLogger(__name__).error('Discord deferred response rejected (HTTP %s)',response.status_code)
                return False
        except requests.RequestException:delay=1
        if attempt<2:time.sleep(delay)
    logging.getLogger(__name__).error('Discord deferred response delivery failed; gameplay was not retried')
    return False


def finish(m,payload,command,uid,name,options):
    origin=m.task_queue.queue_notifications.origin_channel
    token=origin.set(str(payload.get('channel_id') or ''))
    try:
        result=m.discord_execution.execute(m,payload,command,uid,name,options)
    except Exception:
        logging.getLogger(__name__).error('Deferred Discord command rolled back: %s',command)
        data={'content':'This request could not be completed. Check /queue for any existing queue before trying again.',
              'allowed_mentions':{'parse':[]}}
    else:
        # Public receipts omit private modifier calculations. No extra unsolicited
        # follow-up: the action has one response, with only relevant changes.
        try:
            # Workbench, mining, gathering and queue replies carry dropdowns and buttons.
            data=m.ui.slash_panel(m,command,uid,name,options,result) or m._discord_json_message(result,message_type=command)['data']
            # Every reply offers the next step as buttons: Again, its menu area, and Menu.
            if command!='menu':
                try:
                    rows=[r for r in data.get('components') or [] if r.get('components')]
                    if len(rows)<5:data['components']=rows+[m.menu.after_command(m,command,options,uid)]
                except Exception:
                    logging.getLogger(__name__).error('Menu buttons could not be added: %s',command)
        except Exception:
            logging.getLogger(__name__).error('Saved command result could not be formatted: %s',command)
            data={'content':result[:1800], 'allowed_mentions':{'parse':[]}}
    finally:origin.reset(token)
    edit_original(str(payload['application_id']),str(payload['token']),data)
    # Private notifications: warnings and tips raised by this command, and anything
    # waiting in the player's inbox, shown only to them.
    try:
        m.inbox.after_command(m,uid,name,command,options,locals().get('result',''))
        m.inbox.deliver(m,payload,uid)
    except Exception:
        logging.getLogger(__name__).error('Private notifications could not be delivered: %s',command)
