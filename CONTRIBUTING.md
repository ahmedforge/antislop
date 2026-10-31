# Contributing

Use Node.js 22, Python 3.12, and Docker Compose. Follow the [README](README.md)
for installation and [tests and CI](docs/testing-and-ci.md) for exact commands
using isolated PostgreSQL/Redis test services. Never point tests at a shared or
production database. `npm ci` and hash-pinned Python requirements reproduce the
committed dependencies.

## Workflow

1. Create a focused branch (`git switch -c fix/describe-change`).
2. Make the smallest complete change, update its documentation, and add tests
   for changed behavior. Keep generated bundles, credentials, ZIPs, and local
   databases out of commits.
3. Run backend Ruff, mypy, and the complete integration/coverage suite for backend
   changes. Run `npm run build` and `npm test` in `extension/` for extension changes.
   For packaging changes also run `python3 scripts/package_extension.py --local`
   and inspect the ZIP as described in [release preparation](docs/release.md).
4. Open a pull request describing the problem, resulting behavior, verification,
   and any remaining limitation. Use conventional commit subjects such as
   `fix: preserve reveal state on recycled cards`.

## Invariants

- No ML detection or per-video flags. Reports never automatically approve channels.
- Default to Blur. Preserve original YouTube nodes and use reversible CSS for
  Blur, Collapse, and Hide. Keep the Hide warning and reveal/appeal controls.
- Keep all YouTube selectors in `extension/src/selectors.ts`; cover new layouts
  with synthetic browser fixtures. Tests do not guarantee live YouTube compatibility.
- Channel matching stays local. Never add watch-history logging, per-card API
  lookups, or identifying metric labels. Send only explicitly submitted fields.
- Preserve transactional moderation/audit updates, deduplication, delta removal
  notices, and microsecond sync cursors. Add Alembic migrations for schema changes;
  do not edit already-applied migrations.
- Keep admin keys outside the extension and Git. Do not include real reports,
  user data, or credentials in issues, fixtures, screenshots, or test logs.

Update both `extension/manifest.json` and `extension/package.json` versions for
an extension release, then refresh `package-lock.json` with npm. Regenerate
Python lock files using the README commands when changing dependency ranges.
CI checks code; it does not deploy or publish a store listing.
