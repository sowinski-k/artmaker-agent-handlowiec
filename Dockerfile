# Production Dockerfile dla Artmaker Agent na Railway / Fly / Render / dowolny PaaS.
#
# Multi-stage żeby finalny obraz był mały. Builder kompiluje wheele,
# runtime stage kopiuje tylko zainstalowane paczki.

# ---- Stage 1: build dependencies ----
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps potrzebne do kompilacji niektórych wheels (lxml, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Najpierw same requirements - Docker cache layer reuse przy zmianach w kodzie
COPY requirements.txt .
RUN pip install --user --no-cache-dir --upgrade pip \
    && pip install --user --no-cache-dir -r requirements.txt

# ---- Stage 2: runtime ----
FROM python:3.12-slim

WORKDIR /app

# Bezpieczeństwo: non-root user (Railway tego nie wymaga, ale dobry hygiene)
RUN useradd --create-home --shell /bin/bash --uid 1000 artmaker

# Kopiujemy zainstalowane paczki z buildera
COPY --from=builder --chown=artmaker:artmaker /root/.local /home/artmaker/.local

# Kopiujemy kod (volume Railway zamontuje /app/data później dla SQLite)
COPY --chown=artmaker:artmaker . /app

USER artmaker

# pip --user binaries
ENV PATH=/home/artmaker/.local/bin:$PATH

# Streamlit production tuning
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Default port jeśli platforma nie da $PORT (lokalny test docker run)
ENV PORT=8501

EXPOSE 8501

# Healthcheck - Streamlit ma wbudowany endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{__import__(\"os\").getenv(\"PORT\", \"8501\")}/_stcore/health').read()" || exit 1

# Bind 0.0.0.0 bo container, listen na PORT z env (Railway nadpisuje)
CMD streamlit run gui/app.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.fileWatcherType=none \
    --browser.gatherUsageStats=false
