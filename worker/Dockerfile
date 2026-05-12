# Ecombinat Worker - background job processor.
# Hostowany jako 3-ci Railway service (obok backend + frontend).
# Polluje Job table z Postgres co 5s, wykonuje zadania discovery/research/draft/send.
# Działa 24/7 niezależnie od user'owego browsera.

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
    PYTHONDONTWRITEBYTECODE=1

# Worker nie nasłuchuje na portu - to long-running daemon.
# Railway nadal może go restart'ować przy SIGTERM (worker łapie sygnał i drainuje).
CMD ["python", "-m", "worker.main"]
