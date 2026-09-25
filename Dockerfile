FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
CMD ["sh", "-c", "python -m scripts.register_discord_commands || echo 'WARNING: Discord registration failed; inspect the registrar error.'; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
