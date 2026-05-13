# Ecombinat Frontend

Next.js 15 App Router + TypeScript. Renderuje landing page (1:1 z `ecombinat.html`)
i dashboard panel (1:1 z `ecombinat-dashboard.html`).

## Local dev

```bash
cd frontend
npm install
BACKEND_URL=http://localhost:8000 npm run dev
```

## Testy

Smoke testy Vitest + @testing-library/react w jsdom. Łapią broken
imports / React render errors / regression na strukturze stron.

```bash
cd frontend
npm test          # one-shot run (CI mode)
npm run test:watch  # watch mode dla developmentu
```

CI: workflow `.github/workflows/frontend-tests.yml` odpala się na każdy
push do `frontend/**` + manual dispatch.

Frontend startuje na `http://localhost:3000`. Wszystkie `/api/*` requesty
przekierowuje na `BACKEND_URL` (FastAPI z `web/main.py`).

Backend startujesz w drugim terminalu:

```bash
APP_PASSWORD=test123 SESSION_SECRET=dev-secret \
  uvicorn web.main:app --host 0.0.0.0 --port 8000
```

## Deploy (Railway)

Patrz `frontend/railway.toml`. **Wymaga utworzenia drugiego service'u** w
tym samym Railway projekcie:

1. Backend service (już istnieje): `web/Dockerfile`, root path `/`
2. Frontend service (nowy): `+ Create → Empty Service` → Settings:
   - Source: same repo, branch: `claude/ai-sales-agent-artmaker-n48yh`
   - Build → Dockerfile Path: `frontend/Dockerfile`
   - Build → Build Context: `frontend`
   - Build → Watch Paths: `frontend/**`
   - Variables: `BACKEND_URL = http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000`
   - Networking → Generate Domain

3. Backend service Variables:
   - `APP_PASSWORD` = twoje hasło dostępu
   - `SESSION_SECRET` = `openssl rand -hex 32`
   - `FRONTEND_ORIGINS` = URL frontend service'u (np. `https://frontend-production-xxx.up.railway.app`)
   - Reszta tak jak była (klucze API, DB)

## Struktura

```
frontend/
├── app/
│   ├── layout.tsx          # root layout (fonts, icons)
│   ├── globals.css         # design tokens (Ecombinat palette)
│   ├── page.tsx            # / - landing (ecombinat.html 1:1)
│   ├── login/page.tsx      # /login - password gate
│   └── (app)/              # auth-gated routes
│       ├── layout.tsx      # sidebar + chrome
│       └── pulpit/page.tsx # /pulpit - dashboard
├── components/             # reusable: Sidebar, Topbar, StatCard, ... (TODO)
├── lib/                    # api fetch helpers (TODO)
├── Dockerfile
├── next.config.js
├── package.json
├── railway.toml
└── tsconfig.json
```

## Co dalej

- **Commit 2**: API endpointy łączące się z prawdziwym Postgres (zamiast mock data)
- **Commit 3**: Forms (Pozyskiwanie, Drafty, edycja) — JS fetch z React state
- **Commit 4**: Clerk multi-tenant auth (gdy zaczynasz sprzedaż)
