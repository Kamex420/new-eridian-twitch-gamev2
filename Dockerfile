
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY db.py models.py needs.py occupations.py competencies.py settlement.py seedlings.py events.py progression.py commands.py migrations.py main.py ./
COPY app ./app
COPY register_discord_commands.py ./

CMD ["sh", "-c", "python -u register_discord_commands.py || echo 'WARNING: Discord registration failed; check the error above.'; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
