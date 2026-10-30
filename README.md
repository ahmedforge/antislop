# AntiSlop

A Chrome Manifest V3 extension that filters community-flagged AI-content
channels on YouTube, backed by a community blocklist API.

## Status

Stage 2: local blocklist filtering and popup settings are implemented. The backend
and community blocklist sync are not implemented yet.

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
├── backend/         # Python API, migrations, and tests (future stages)
├── docs/            # Architecture and contributor documentation
├── .gitignore
├── LICENSE
└── README.md
```

A root `docker-compose.yml` will be added in Stage 3.

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

## Architecture and development

Architecture details, contribution instructions, privacy documentation, and
release packaging will be added in the corresponding stages.

## License

[MIT](LICENSE), copyright 2026 ahmedforge.
