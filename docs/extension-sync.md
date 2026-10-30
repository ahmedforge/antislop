# Extension blocklist sync (Stage 6)

The Manifest V3 background service worker fetches `/v1/blocklist` on installation,
browser startup, and an hourly Chrome alarm. It checks for missing alarms each time
it starts. Existing alarm deadlines are preserved, and overlapping events share
one in-flight sync. Chrome can delay alarms while the device sleeps; this is a
best-effort hourly schedule, not a real-time moderation push.

The content script never calls the backend. It reads a locally cached list, builds
sets of channel IDs and handles, and filters YouTube cards locally. A known channel
ID takes precedence over a handle because handles can be reassigned. All YouTube
CSS selectors remain in `extension/src/selectors.ts`.

## Cache and failure behavior

One versioned `blocklistCache` object in `chrome.storage.local` holds the channels,
source endpoint, cursor, last successful sync time, and an ETag tied to its exact
request URL. Display mode and on/off remain separately in `chrome.storage.sync`.

- First successful sync replaces the cache with a full snapshot.
- Later requests send only `since=<previous next_since>`. The timestamp string is
  preserved verbatim, including its microseconds.
- Delta entries replace earlier entries with the same channel ID; removals delete
  that ID. Rebuilding lookup sets also removes outdated handles.
- ETags are sent only when the saved request URL matches. A valid `304` preserves
  the list and cursor. An unsolicited `304` is rejected.
- A `422` cursor rejection triggers one unconditional full-snapshot request. The
  old list remains active until the replacement is validated and saved.
- The list, cursor and validator are saved together in one storage-key update.
  Content scripts listen for that change and reapply the current display mode to
  existing cards without a reload.
- Network failures, non-success HTTP responses, malformed/inconsistent data, and
  storage errors do not intentionally clear or advance the last cache. Retry occurs
  at the next hourly alarm or browser startup; there is no rapid retry loop.
- Each fetch has a 15-second timeout. The v1 response size guard is 5 MiB of text
  code units; Chrome's storage quota can impose a tighter effective limit. A list
  that cannot be saved leaves the previously persisted cache intact.
- With no valid cached list, cards stay visible and Blur remains the default mode.
  There is no hardcoded fallback or automatic seed import.

Only the API origin is granted host permission. Fetch uses `credentials: omit`,
`referrerPolicy: no-referrer`, and rejects redirects. Requests include no browsing
URLs, video IDs, channel lookups, or installation IDs. The server naturally sees
network metadata such as the connection's source IP, but no viewing activity.
Diagnostic failures log a generic message without identities or response bodies.

Turning filtering off affects display, not the background sync schedule. Cache
updates preserve display preferences. Per-card “Show anyway” remains local to that
card; it is not sent to the backend.

## Local backend and extension

The default build uses `http://127.0.0.1:8000`, matching Compose. From the repo root:

```bash
docker compose up -d --wait postgres redis
docker compose build backend
docker compose run --rm --no-deps backend alembic upgrade head
# Optional synthetic development fixture, not a real community allegation:
docker compose run --rm --no-deps backend python -m app.seed app/seed.demo.json
docker compose up -d --wait backend
npm --prefix extension ci
npm --prefix extension run build
```

Load `extension/dist` in Chrome's unpacked-extension UI and reload YouTube tabs.
The popup and display controls are unchanged. The synthetic fixture will not
normally match real YouTube cards. A real vetted list must be explicitly supplied
to the seed importer; this stage does not invent one.

To target a deployed backend, build with its HTTPS origin:

```bash
ANTISLOP_API_BASE_URL=https://your-api.example npm --prefix extension run build
```

The build sets both the compiled endpoint and generated manifest host permission.
Only origin URLs are accepted: no credentials, query, fragment, or path prefix.
HTTP is allowed only for `localhost` or `127.0.0.1` development. Changing the API
origin requires rebuilding/reloading the extension; cache from another source is
not reused. Chrome host match patterns apply across ports on that host, although
the service worker fetches only the configured endpoint and port.

## Automated verification

From `extension/`:

```bash
npm ci
npx playwright install chromium
npm test
```

Tests build a separate ignored `dist-test` extension using
`http://127.0.0.1:18076`. They do not overwrite the normal `dist` build or call the
user's API. Keep test port 18076 available. Controlled YouTube HTML is served through
browser request interception, and a local HTTP fixture implements full/delta/ETag
responses for the real installed service worker.

The suite exercises the existing three display modes, first/full sync, precise
cursors, handle replacement, stable-ID precedence, removal replay, ETags/304,
backend/offline failures, malformed data, recovery from cursor rejection, and an
actual browser restart with cached filtering and alarm recovery. These are behavior
tests; they do not prove compatibility with every live YouTube DOM variant.

Chrome references:
[service-worker alarms](https://developer.chrome.com/docs/extensions/get-started/tutorial/service-worker-events),
[cross-origin requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests).
