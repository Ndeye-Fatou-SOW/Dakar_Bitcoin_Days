FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /workspace

COPY backend/requirements.txt backend/requirements-lightning.txt backend/requirements-nostr.txt ./backend/
COPY lightning/pyproject.toml lightning/README.md ./lightning/
COPY lightning/tontine_lightning ./lightning/tontine_lightning
COPY nostr/requirements.txt ./nostr/requirements.txt
COPY nostr/registre_nostr ./nostr/registre_nostr

RUN pip install --no-cache-dir -r backend/requirements.txt -r nostr/requirements.txt ./lightning \
    && useradd --uid 10001 --create-home tontine \
    && mkdir /data \
    && chown tontine:tontine /data

COPY backend/app ./backend/app

ENV PYTHONPATH=/workspace/backend
WORKDIR /workspace/backend
USER tontine

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/openapi.json', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
