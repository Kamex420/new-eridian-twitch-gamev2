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
        result=m._discord_call_internal(command,uid,name,options,str(payload.get('id') or ''))
        data=m._discord_json_message(result,ephemeral=True,message_type=command)['data']
    except Exception:
        # Never print webhook URLs, credentials, response bodies or SQL parameters.
        logging.getLogger(__name__).error('Deferred Discord command failed: %s',command)
        data={'content':'New Eridian could not finish this request. Check /queue before retrying; your queue may already have started.',
              'allowed_mentions':{'parse':[]}}
    finally:origin.reset(token)
    edit_original(str(payload['application_id']),str(payload['token']),data)
