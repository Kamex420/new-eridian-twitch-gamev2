FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# The compatibility package in app/ loads the legacy modules from the repo root.
# Copy those modules into the image as well as app/.
COPY db.py models.py needs.py occupations.py competencies.py settlement.py seedlings.py events.py progression.py commands.py migrations.py main.py ./
COPY app ./app

CMD ["sh","-c","uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
