
# New Eridian v2 Discord command registration
import os, sys, json, requests

APP_ID = os.getenv("DISCORD_APPLICATION_ID","")
TOKEN = os.getenv("DISCORD_BOT_TOKEN","")
GUILD_ID = os.getenv("DISCORD_GUILD_ID","").strip()

base = f"https://discord.com/api/v10/applications/{APP_ID}"
url = f"{base}/guilds/{GUILD_ID}/commands" if GUILD_ID else f"{base}/commands"

from app.command_catalog import commands

headers = {
    "Authorization": f"Bot {TOKEN}",
    "Content-Type": "application/json"
}

if "--dry-run" in sys.argv:
    print(json.dumps(commands,ensure_ascii=False,indent=2))
    sys.exit(0)
if not APP_ID or not TOKEN:
    sys.exit("Set DISCORD_APPLICATION_ID and DISCORD_BOT_TOKEN before registration.")

r = requests.put(url, headers=headers, json=commands, timeout=30)
print("HTTP", r.status_code)
if not r.ok:
    print(r.text)
    sys.exit(1)

def option_signature(options):
    signatures=[]
    for option in options:
        row={key:option.get(key,False if key in {"required","autocomplete"} else None)
             for key in ("name","type","required","autocomplete","min_value","max_value")}
        row['choices']=[(choice['name'],choice['value']) for choice in option.get('choices',[])]
        signatures.append(row)
    return signatures
registered={row["name"]:row for row in r.json()}
for command in commands:
    actual=registered.get(command['name'])
    if actual is None or option_signature(actual.get('options',[]))!=option_signature(command.get('options',[])):
        sys.exit('Registration verification failed for /'+command['name']+'. Check Discord settings before use.')

print(f"Verified {len(commands)} New Eridian v2 commands with dropdown options.")
if GUILD_ID:
    print("Registered as guild commands for fast testing.")
else:
    print("Registered globally; propagation can take longer.")
