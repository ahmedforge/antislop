# Release preparation

The repository produces an MV3 ZIP with `manifest.json` at its root. Packaging
is local; it does not publish to the Chrome Web Store or deploy a public API.
Python 3.12, Node.js 22, and `npm ci` in `extension/` are prerequisites.

## Local package

From the repository root:

```bash
npm --prefix extension ci
python3 scripts/package_extension.py --local
python3 -m zipfile -t dist/antislop-0.1.0-local.zip
python3 -m zipfile -l dist/antislop-0.1.0-local.zip
(cd dist && sha256sum -c antislop-0.1.0-local.zip.sha256)
```

The default origin is `http://127.0.0.1:8000`. The ZIP contains exactly seven
runtime files: manifest, three JavaScript bundles, two stylesheets, and popup HTML.
It excludes source maps, tests, dependencies, configuration secrets, and backend
code. Entries have fixed timestamps/permissions and stable ordering; identical
inputs/toolchain produce identical bytes. The checksum detects accidental changes,
not publisher authenticity. Build output and archives are ignored by Git.

Extract the ZIP into a new folder and select that folder using **Load unpacked**
in Chrome's `chrome://extensions` Developer mode. Chrome cannot load a ZIP directly
through that control. Start the API and apply migrations as in the README.
Check default Blur, mode changes, disable/re-enable, reveal controls, and explicit
submission forms. An empty approved list correctly leaves every card visible;
the synthetic demo seed is not evidence about any real creator.

## Store candidate

Deploy and verify your own HTTPS API first, then replace the example origin:

```bash
ANTISLOP_API_BASE_URL=https://api.example.com python3 scripts/package_extension.py
```

Expected: `dist/antislop-0.1.0.zip` and `.zip.sha256`. Omitting an HTTPS origin
fails before building. `--local` deliberately labels a development archive.
The build validates origin syntax and embeds it in the background worker; packaging
does not prove that the host exists or its API is healthy. Chrome host permissions
are scoped to its scheme and hostname (Chrome match patterns do not restrict ports).
Never configure an admin key in this build.

Before submission, update matching manifest/package versions and lock file, run
the full checks in [testing and CI](testing-and-ci.md), inspect the archive, and
load that exact extracted archive for a smoke test. Prepare store artwork, listing
text, permission explanations, and a public privacy-policy URL that describes the
actual hosted service and operator contact. Store review and publication remain
separate manual steps; this package is not a claim of store approval.

## Hosting boundary

Compose is a local setup with disposable database credentials and loopback ports.
Public hosting needs HTTPS, protected database/Redis access, managed secrets,
backup/restore planning, a real privacy/contact/retention policy, and restricted
admin and monitoring access. Grafana's local anonymous Viewer configuration must
not simply be exposed publicly. Configure trusted-proxy handling deliberately
before relying on per-client IP limits behind a proxy. Keep one API worker per
container with the current metrics implementation. See
[moderation](moderation.md), [rate limits](rate-limits.md), and
[observability](observability.md) for the corresponding operating constraints.
