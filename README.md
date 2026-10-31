# AntiSlop

A Chrome Manifest V3 extension that filters community-flagged AI-content
channels on YouTube, backed by a community blocklist API.

## Status

Stage 10: GitHub Actions checks backend lint, types, PostgreSQL/Redis tests,
coverage, and the extension build/browser tests on pushes and pull requests.
Filtering uses a local synced cache; reports do not automatically block channels.

## Product principles

- Community reports and a seed list identify channels; no ML detection.
- Version 1 flags entire channels, not individual videos.
- BLUR is always the default, with the label “Flagged as AI content by the community”
  and a “Show anyway” button.
- COLLAPSE shows a thin “Hidden: AI channel” bar with a “Show” button.
- HIDE uses a CSS class with `display: none`; its popup warning explains that
  wrongly flagged channels can be hidden silently.
- Filtering uses reversible CSS classes, never DOM node removal.
- Blocklist deltas sync to the browser; channel lookups happen locally.
  The backend must never receive or log viewing activity. Reports contain only
  what a user explicitly reports.
- Wrongly flagged creators have an appeals path.
- All YouTube CSS selectors belong in one configuration file.

## Repository layout

```text
antislop/
├── extension/       # TypeScript Chrome MV3 extension
├── backend/         # FastAPI app, database models, migrations, and tests
├── docs/            # Architecture and contributor documentation
├── docker-compose.yml # Local API, PostgreSQL, and Redis
├── .gitignore
├── LICENSE
└── README.md
```

## Planned stack

- Extension: TypeScript, Manifest V3, esbuild, no UI framework.
- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Redis, pytest.
- Engineering: GitHub Actions CI; Prometheus metrics planned for Stage 11.

## Setup

Requires Node.js 22 and npm.

```bash
cd extension
npm ci
npm run build
```

Expected: TypeScript exits successfully and the build prints
`Built extension/dist — ready to load unpacked.`

Load `extension/dist` as an unpacked extension from `chrome://extensions` with
Developer mode enabled, then reload YouTube. Open the AntiSlop toolbar popup to
choose Blur (default), Collapse, or Hide and to enable or disable filtering.
Settings are saved in `chrome.storage.sync` and apply to open tabs without reload.
Hide mode displays a warning about silently hiding wrongly flagged channels.

The extension syncs from `http://127.0.0.1:8000` by default and filters against its
local cache. A fresh install keeps cards visible until its first successful sync.
Failures preserve the last valid list. The backend's optional demo seed contains
synthetic entries only; no real creators are flagged automatically. See
[extension sync setup and behavior](docs/extension-sync.md) for backend startup,
API-origin configuration, caching, and offline behavior.

Filtering uses reversible CSS classes. Blur and Collapse offer per-card reveal
buttons; Hide uses `display: none`. Original YouTube nodes are never removed or
wrapped. Blurred/hidden children are inert to prevent keyboard interaction; their
previous inert state is restored when revealed or filtering is disabled. Reveal
choices last for that card and channel in the current page, and reset if its
channel identity changes or the page reloads.

The observer scans only changed subtrees during normal browsing and batches card
updates per animation frame. A WeakMap stores card identity, reveal state, and
existing controls to avoid duplicate UI while supporting reused cards. Settings
changes rescan current cards. All YouTube selectors are in `extension/src/selectors.ts`.
Legacy `/user/` and `/c/` links and cards without recognizable channel links are
skipped. There are no content-script network requests or viewing-history logs. Background
requests contain only sync cursors and conditional ETags; no viewed channels or videos.

### Automated verification

From `extension/`:

```bash
npm ci
npx playwright install chromium
npm test
```

The tests build a separate `dist-test` extension and load it in isolated Chromium
with real Chrome storage/alarms. A local API fixture uses port 18076, and intercepted
YouTube requests serve controlled fixture HTML. They check default
blur, classic and nested cards, collapse, hide, live on/off, DOM preservation,
individual reveal, delayed links, recycled cards, settings persistence, delta sync,
removals, ETags, offline recovery, and browser restart.
This verifies extension behavior, not compatibility with every live YouTube layout.
Rebuild and reload the unpacked extension after source changes.

## Backend development

Python 3.12 is required. From the repository root:

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-dev.txt
cd backend
cp .env.example .env
.venv/bin/python -m pytest -q
.venv/bin/python -m uvicorn app.main:create_app --factory --reload --no-access-log --no-proxy-headers
```

Without a test database, PostgreSQL integration tests explicitly skip; health and
other non-integration checks still run. Submission integration tests also require
`TEST_REDIS_URL`; see [rate-limit verification](docs/rate-limits.md). The development API listens on
`http://127.0.0.1:8000`; `curl http://127.0.0.1:8000/health` returns `{"status":"ok"}`.
Interactive API documentation is at `/docs`.

Settings are read from environment variables or `backend/.env` when running from
`backend/`. Environment variables take precedence. Supported settings are
`APP_NAME`, `ENVIRONMENT` (`development`, `test`, or `production`), `DATABASE_URL`,
`REDIS_URL`, rate-limit settings, `REVIEW_THRESHOLD`, and `ADMIN_API_KEY`.
Connection URLs are validated; database and Redis connections are opened on demand.
The `/health` endpoint is a liveness check, not database/cache readiness.
Request access logging is disabled in the documented launch commands and image.

### Local containers

From the repository root:

```bash
docker compose up --build -d --wait
docker compose ps
curl --fail http://127.0.0.1:8000/health
docker compose exec postgres pg_isready -U antislop -d antislop
docker compose exec redis redis-cli ping
docker compose down
```

Expected: all three services healthy, `{"status":"ok"}`, PostgreSQL
`accepting connections`, and Redis `PONG`. Set `API_PORT=8001` before the Compose
command if port 8000 is occupied. Only the API port is published, on loopback;
PostgreSQL and Redis are available on the internal Compose network.

Compose is a local-development configuration with explicitly disposable database
credentials. PostgreSQL data persists in a named volume across `down`/`up`.
Redis is ephemeral at this stage. The API waits for each dependency's own health
check before starting. The SQLAlchemy models and Alembic migrations are available;
the blocklist endpoint uses them. Apply migrations explicitly before serving blocklist requests:

```bash
docker compose run --rm --no-deps backend alembic upgrade head
docker compose run --rm --no-deps backend alembic check
```

Run these while PostgreSQL is up. See [database design and migration instructions](docs/database.md)
for table/index rationale, constraints, rollback behavior, and PostgreSQL integration tests.

`requirements.in` and `requirements-dev.in` declare dependency ranges; the matching
`.txt` files pin all resolved packages and hashes. To intentionally refresh them
with uv, run from the repository root:

```bash
uv pip compile backend/requirements.in --generate-hashes -o backend/requirements.txt
uv pip compile backend/requirements-dev.in --generate-hashes -o backend/requirements-dev.txt
```

See [blocklist sync and seed import](docs/blocklist-sync.md) for the Stage 5 API
contract, ETags, removal notices, seed commands, and concurrency trade-offs.

See [reports and appeals](docs/reports-and-appeals.md) for explicit submission
behavior, stable-channel-ID requirements, deduplication, and anonymous install-ID limits.

See [rate limits](docs/rate-limits.md) for token-bucket settings, retry semantics,
Redis failure behavior, and proxy/IP considerations.

See [scoring and moderation](docs/moderation.md) for admin setup, review queues,
reputation scoring, appeal decisions, and brigading limitations.

See [tests and CI](docs/testing-and-ci.md) for the local verification commands,
coverage gate, isolated database setup, and GitHub workflow details.

## Architecture and development

Architecture details, contribution instructions, privacy documentation, and
release packaging will be added in the corresponding stages.

## License

[MIT](LICENSE), copyright 2026 ahmedforge.
