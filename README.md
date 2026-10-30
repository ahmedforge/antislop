# AntiSlop

A Chrome Manifest V3 extension that filters community-flagged AI-content
channels on YouTube, backed by a community blocklist API.

## Status

Stage 0: repository layout only. No extension or backend is implemented yet.

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
├── extension/       # TypeScript Chrome MV3 extension (future stages)
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

There are no dependencies to install or applications to run at Stage 0.
Build and development commands will be added with their implementations.

## Architecture and development

Architecture details, contribution instructions, privacy documentation, and
release packaging will be added in the corresponding stages.

## License

[MIT](LICENSE), copyright 2026 ahmedforge.
