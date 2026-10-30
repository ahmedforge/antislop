# AntiSlop

A Chrome Manifest V3 extension that filters community-flagged AI-content
channels on YouTube, backed by a community blocklist API.

## Status

Stage 5: the backend serves approved-channel snapshots/deltas with ETags and an
explicit seed importer. The extension still uses its bundled list until Stage 6.

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
- Engineering: GitHub Actions CI and Prometheus metrics.

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

The bundled `extension/src/blocklist.json` contains **synthetic test entries only**:
`@antislop-demo-fixture` and `UC0000000000000000000000`. These are not community
verdicts about real creators. Regular YouTube browsing may show no filtered cards.
A vetted seed list and backend sync belong to later stages.

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
skipped. There are no content-script network requests or viewing-history logs.

### Automated verification

From `extension/`:

```bash
npm ci
npx playwright install chromium
npm test
```

The tests load the actual extension in isolated Chromium with real Chrome storage,
and intercept YouTube requests to serve controlled fixture HTML. They check default
blur, classic and nested cards, collapse, hide, live on/off, DOM preservation,
individual reveal, delayed links, recycled cards, and settings persistence.
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
.venv/bin/python -m uvicorn app.main:create_app --factory --reload --no-access-log
```

Without a test database, PostgreSQL integration tests explicitly skip; health and
database-unavailable checks still run. The development API listens on
`http://127.0.0.1:8000`; `curl http://127.0.0.1:8000/health` returns `{"status":"ok"}`.
Interactive API documentation is at `/docs`.

Settings are read from environment variables or `backend/.env` when running from
`backend/`. Environment variables take precedence. Supported settings are
`APP_NAME`, `ENVIRONMENT` (`development`, `test`, or `production`), `DATABASE_URL`,
and `REDIS_URL`. Connection URLs are validated but not used to connect yet.
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
check before starting, but does not query either service yet. The SQLAlchemy models and initial Alembic migration are available;
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

## Architecture and development

Architecture details, contribution instructions, privacy documentation, and
release packaging will be added in the corresponding stages.

## License

[MIT](LICENSE), copyright 2026 ahmedforge.
