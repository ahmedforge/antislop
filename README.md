# AntiSlop

A Chrome Manifest V3 extension that filters community-flagged AI-content
channels on YouTube, backed by a community blocklist API.

## Status

Stage 1: the extension logs channel identities locally. Filtering and the backend
are not implemented yet.

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

1. Open `chrome://extensions`, enable **Developer mode**, and click **Load unpacked**.
2. Select this repository's `extension/dist` folder.
3. Open or reload YouTube, then open the page's DevTools Console and filter for
   `[AntiSlop]` (enable Info-level messages).
4. Check the home feed, a search results page, and a video's recommendation sidebar.
   Scroll to load more cards and navigate between pages without reloading.
5. Expect an observer startup message and channel objects such as
   `{channelId: null, handle: "@example"}`. Actual values depend on visible cards.
   Repeated mutations of the same card should not repeat its unchanged identity.

Rebuild after source changes, reload the extension on `chrome://extensions`, then
reload the YouTube tab. There is no popup yet, and cards remain unchanged.

The manifest injects the bundled content script at `document_idle`. The script
scans existing cards and uses a MutationObserver for added nodes and changed
channel links. Work is batched per animation frame; a WeakMap remembers each
card's last channel identity while allowing removed cards to be garbage collected.
All YouTube selectors live in `extension/src/selectors.ts`.

Only IDs and handles present in channel links are extracted. Legacy `/user/` and
`/c/` URLs, cards without channel links, and unrecognized layouts are skipped.
Selectors cover classic cards and newer lockups but need live verification against
your YouTube layout. Stage 1 logs stay in page DevTools; nothing is sent to a server.

## Architecture and development

Architecture details, contribution instructions, privacy documentation, and
release packaging will be added in the corresponding stages.

## License

[MIT](LICENSE), copyright 2026 ahmedforge.
