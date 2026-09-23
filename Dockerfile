FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# app/main.py loads these legacy modules through the compatibility package.
COPY db.py models.py needs.py occupations.py competencies.py settlement.py seedlings.py events.py progression.py commands.py migrations.py main.py ./
COPY app ./app

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
