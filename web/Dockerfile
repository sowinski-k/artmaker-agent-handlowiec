# Ecombinat API - FastAPI backend (Python).
# Hostowany jako osobny Railway service. Frontend (Next.js) odwoluje sie
# do niego przez Railway internal networking lub publiczny URL.

FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --user --no-cache-dir --upgrade pip \
    && pip install --user --no-cache-dir -r requirements.txt

FROM python:3.12-slim
WORKDIR /app

RUN useradd --create-home --shell /bin/bash --uid 1000 ecombinat

COPY --from=builder --chown=ecombinat:ecombinat /root/.local /home/ecombinat/.local
COPY --chown=ecombinat:ecombinat . /app

USER ecombinat
ENV PATH=/home/ecombinat/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{__import__(\"os\").getenv(\"PORT\", \"8000\")}/healthz').read()" || exit 1

CMD uvicorn web.main:app --host 0.0.0.0 --port ${PORT}
