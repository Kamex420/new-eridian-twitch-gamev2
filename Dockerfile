
# app/main.py loads these legacy modules through the compatibility package.
COPY db.py models.py needs.py occupations.py competencies.py settlement.py seedlings.py events.py progression.py commands.py migrations.py main.py ./
COPY app ./app
COPY register_discord_commands.py ./

CMD ["sh", "-c", "if [ -n \"$DISCORD_APPLICATION_ID\" ] && [ -n \"$DISCORD_BOT_TOKEN\" ]; then python -u register_discord_commands.py || echo \"WARNING: Discord command registration failed; see the error above. Existing slash commands may be outdated.\"; else echo \"WARNING: Discord command registration skipped. Set DISCORD_APPLICATION_ID and DISCORD_BOT_TOKEN to update all slash commands.\"; fi; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
