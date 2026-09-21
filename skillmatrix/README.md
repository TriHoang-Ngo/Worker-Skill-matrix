# Worker Skill Matrix — Architecture & Setup

## 1. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | **Python + FastAPI** | Async, auto-generated OpenAPI/Swagger docs (useful for a plant IT team to self-serve integration), first-class Pydantic validation, and pandas/openpyxl/reportlab give CSV/Excel/PDF for free. |
| ORM / DB access | **SQLAlchemy 2.0** | DB-agnostic — ship on SQLite for a pilot, point `DATABASE_URL` at Postgres for the real plant deployment with zero code changes. |
| Database | **SQLite (dev/pilot) → PostgreSQL (production)** | SQLite needs no server, so a line supervisor can pilot this on a single tablet/PC in an afternoon. Postgres is the recommended production target once multiple lines write concurrently. |
| Frontend | **React (no build step, CDN + Babel standalone)** | A single static `index.html` — no npm/webpack pipeline to install or maintain on a plant floor kiosk PC. Swap to a Vite build later without changing any application code if you want a proper CI pipeline. |
| Reports | **openpyxl (Excel), ReportLab (PDF)** | Server-generated, so exports are identical regardless of which browser/tablet requests them. |

This stack was chosen for **rapid deployment**: `pip install -r requirements.txt && uvicorn main:app` gets the API running, and the frontend is one HTML file you can open directly or host on any web server / USB stick for a kiosk PC. If you later need offline-first tablets or a no-code path, Streamlit (internal tool, fast but less tablet-friendly) or AppSheet (fastest, but weakest on the custom bottleneck-detection logic in Step 4) are the fallback options — this build assumes a factory floor with intermittent-but-present network connectivity to a local server.

## 2. Database schema

```
employees
├── employee_id      VARCHAR(20)  PK
├── full_name        VARCHAR(120) NOT NULL
├── department       VARCHAR(80)  NOT NULL   -- production line
├── position          VARCHAR(80)  NOT NULL
├── is_active         BOOLEAN      DEFAULT true   -- soft delete
├── created_at        DATETIME
└── updated_at        DATETIME

skills
├── skill_id          VARCHAR(20)  PK
├── skill_name        VARCHAR(120) NOT NULL UNIQUE
├── skill_category    VARCHAR(60)  NOT NULL   -- Operation / Maintenance / Quality / Safety
├── description       VARCHAR(500)
├── is_critical        BOOLEAN      DEFAULT false  -- feeds bottleneck detection
└── created_at         DATETIME

assessments                                    -- CURRENT level, one row per (employee, skill)
├── id                 INTEGER      PK AUTOINCREMENT
├── employee_id        VARCHAR(20)  FK → employees.employee_id (CASCADE)
├── skill_id           VARCHAR(20)  FK → skills.skill_id (CASCADE)
├── proficiency_level  INTEGER      NOT NULL, CHECK 0–4
├── assessed_by        VARCHAR(120)
├── assessed_at        DATETIME
└── UNIQUE(employee_id, skill_id)

assessment_history                              -- append-only audit trail
├── id                 INTEGER      PK AUTOINCREMENT
├── employee_id        VARCHAR(20)  FK → employees.employee_id (CASCADE)
├── skill_id           VARCHAR(20)  FK → skills.skill_id (CASCADE)
├── proficiency_level  INTEGER      NOT NULL
├── assessed_by        VARCHAR(120)
└── assessed_at         DATETIME
```

Design notes:
- `assessments` holds only the **current** level per worker/skill (uniqueness enforced at the DB level), so the matrix query is a simple join — no aggregation needed on read.
- `assessment_history` is append-only. Every write to `assessments` also inserts a history row, giving you a trend line per worker/skill later without touching the hot-path query.
- `is_critical` on `skills` is what the bottleneck detector uses to separate "critical" alerts (single point of failure on a safety/production-critical skill) from routine "warning" gaps.
- Soft-delete (`is_active`) on employees preserves historical assessments when someone transfers out or leaves, instead of orphaning their skill history.

## 3. Architecture & data flow

```
┌─────────────────────┐        HTTPS/JSON        ┌──────────────────────────┐        SQL        ┌─────────────┐
│   Frontend (React)   │ ───────────────────────▶ │   FastAPI backend         │ ─────────────────▶ │  Database    │
│  - Skill matrix grid │ ◀─────────────────────── │  /api/employees            │ ◀───────────────── │  (SQLite /   │
│  - Gap dashboard     │      REST responses       │  /api/skills                │      ORM rows       │  Postgres)   │
│  - Click-to-edit cell│                           │  /api/assessments           │                     └─────────────┘
│  - CSV/Excel import  │                           │  /api/matrix                │
│    (via file upload) │                           │  /api/search-by-skill       │
└─────────────────────┘                           │  /api/analytics/*           │
                                                    └──────────────────────────┘
```

Flow for the most common action — a supervisor updating a skill level on the shop floor:
1. Supervisor taps a grid cell on a tablet → `MatrixView` opens the level-picker.
2. On save, the frontend calls `PUT /api/assessments` with `{employee_id, skill_id, proficiency_level}`.
3. The backend upserts `assessments` and appends a row to `assessment_history` in the same transaction.
4. The frontend updates its local grid state optimistically (no full page reload).
5. The dashboard's coverage % and bottleneck alerts are computed live from the same `assessments` table on each dashboard load — no separate ETL/cache layer needed at this scale (a few hundred workers × tens of skills).

## 4. Running it locally

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000     # seeds demo data on first run
# API docs: http://localhost:8000/docs

# Frontend
# Just open frontend/index.html in a browser (double-click, or `python3 -m http.server` from that folder).
# It talks to http://localhost:8000 by default; override with:
#   <script>window.SKILL_MATRIX_API_BASE = "http://your-server:8000";</script>
# placed before the app's own <script> tag in index.html.
```

For a real plant deployment: run the backend behind a process manager (systemd/gunicorn+uvicorn workers), point `DATABASE_URL` at Postgres, serve `index.html` from nginx or any static file host on the plant intranet, and restrict CORS `allow_origins` in `main.py` to that intranet's origin.

## 5. Public read access, edit access only for you

The backend now enforces this split:
- **Every `GET` endpoint is public** — the matrix, the dashboard, search, and the PDF/Excel reports. Anyone with the URL can view them, no login.
- **Every `POST`/`PUT`/`DELETE` requires a bearer token** — set once as an `ADMIN_TOKEN` environment variable on your server, checked in `database.py`'s `require_admin` dependency. Without a valid `Authorization: Bearer <token>` header, writes get a `401`. If `ADMIN_TOKEN` isn't set on the server at all, writes fail closed with a `500` rather than silently staying open.

In the frontend, click **"Admin sign-in"** in the top bar and enter that same password once — it's stored in your browser's `localStorage` and sent automatically on every edit from then on. Signing out (or on another device that never signed in) leaves the page fully viewable but blocks any write.

**This is a single shared password, not per-user accounts.** Anyone you give the password to can edit; treat it like you would a Wi-Fi password. If you need multiple editors with individual logins and audit trails down the road, that's a straightforward upgrade from here (real user accounts + JWT), just more than a pilot needs.

## 6. Deploying so the public URL works from anywhere

A `render.yaml` is included for [Render](https://render.com) (generous free tier, simplest path):

1. Push this project to a GitHub repo.
2. In Render: **New → Blueprint**, point it at the repo — it reads `render.yaml` automatically.
3. Render will ask you to set `ADMIN_TOKEN` (pick any password) before deploying. Leave `DATABASE_URL` unset to use SQLite, or paste a Postgres connection string if you've provisioned one (recommended for anything beyond a pilot — Render's free-tier filesystem is not guaranteed to persist across restarts, so SQLite data can be lost).
4. Once deployed you'll get a URL like `https://skillmatrix-api.onrender.com`. That's your public API base.
5. Host `frontend/index.html` anywhere static (Render Static Site, GitHub Pages, Netlify — all free). Before deploying it, set the API base at the top of the file's `<script>`, or add this line right before the app's own `<script>` tag:
   ```html
   <script>window.SKILL_MATRIX_API_BASE = "https://skillmatrix-api.onrender.com";</script>
   ```
6. Open the static page's URL — that's now the one link you share publicly. Sign in with your admin password to edit; everyone else just views.

Fly.io and Railway work the same way (a Python web service + `ADMIN_TOKEN` env var); Render is included here because its free tier needs no credit card to start.
