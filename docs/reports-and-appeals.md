# Reports and appeals (Stage 7)

A report is an explicit submission about an entire channel, not a video or an ML
detection result. New channels remain `unreviewed`. Reports do not change score,
reputation, status, or the local blocklist. Appeals remain `open` until moderation.
Stage 8 applies shared installation/IP token buckets before writes; scoring and
authenticated admin decisions remain Stage 9. See [rate limits](rate-limits.md).

## API contract

Both `POST /v1/reports` and `POST /v1/appeals` accept exactly:

```json
{
  "install_id": "08aaac7f-906c-4f93-830f-43ff8d2a5dab",
  "channel_id": "UC0000000000000000000000",
  "reason": "Explain the reason for this explicit submission."
}
```

`channel_id` is the external YouTube `UC…` identifier, **not** the database's
internal channel UUID. The API maps it to the internal foreign key. Installation
IDs must be UUID v4. Reasons are trimmed, nonempty, and limited to 2000 characters.
Unknown fields (including video URLs) are rejected with `422`.

New submissions return `201` with `{"id":"<submission UUID>","created":true}`.
Duplicates return `200` with the original ID and `created:false`. The original
reason is preserved. Responses use `Cache-Control: no-store`.

- Reports transactionally create an install and an unreviewed channel if absent,
  then insert the report. Existing moderation and reputation are never overwritten.
- The unique `(install_id, channel_id)` report constraint handles concurrent
  submissions as well as retries. A different install may report the same channel.
- Appeals require an existing approved channel. Unknown channels return `404`;
  non-approved channels return `409`, without creating an install or appeal.
- Migration `0003` adds a partial unique index allowing one **open** appeal per
  installation/channel pair. Resolved history remains, and a later appeal can be
  opened. The schema still permits install-less creator appeals for future flows;
  this extension endpoint requires an installation ID.
- An appeal locks its channel row while checking approval and inserting, so a
  concurrent status change cannot slip between those steps.
- Database failure/timeout returns a generic `503` with `Retry-After: 5`; credentials,
  connection URLs, and SQL details are not returned. Writes are transactional.

No list/read endpoint exposes other users' reports, reasons, or installation IDs.
No admin action is recorded for a public submission because it is not a moderation
decision. The existing tables preserve that distinction.

## Extension behavior

Unhidden cards with a recognized channel link have a **Report as AI** button.
Blurred and collapsed panels have **This is wrong**, which opens an appeal form.
Hide mode remains fully hidden; switch display mode to reach its appeal control.
Use **Show anyway** if you want to reveal the card immediately; submitting an
appeal does not itself reveal or unblock it.

The form displays the target channel and asks for a reason. It explains the exact
data being sent. Opening, cancelling, or viewing a form makes no submission request.
The form captures the selected target, so a recycled card cannot silently change
an already-open form. Controls on the card itself track its current channel.

Stable IDs from the card are preferred. A handle-only card can use a unique ID
mapping from the cached approved blocklist. For an unknown or ambiguous handle,
the user must supply a stable channel ID or an HTTPS YouTube `/channel/UC…` URL.
Handle URLs and video URLs are not accepted as substitutes. Only the extracted ID
is transmitted. This deliberate v1 limitation avoids guessing identities or adding
a background channel-resolution service.

The form sends an extension message to the service worker. The worker validates
the message and its YouTube content-script sender, chooses a fixed report/appeal
endpoint, and builds a body containing only the three API fields. It accepts no
caller-supplied destination URL. Page-script synthetic button clicks cannot open
or submit the form through these handlers.

POST uses no cookies or referrer, rejects redirects, and times out after 15 seconds.
There is no automatic retry or offline submission queue. A request might commit
just before a connection fails, so failure means “could not confirm,” not “definitely
not sent.” The draft stays in the open form for an explicit retry. Deduplication
makes that retry safe. Closing the dialog or reloading the page discards the draft.

## Anonymous installation ID: purpose and limits

The worker generates `crypto.randomUUID()` lazily on the first explicit valid
submission and saves it to `chrome.storage.local` **before** sending. Concurrent
first submissions share initialization, and retries/restarts reuse the saved ID.
It is never put in synced preferences or blocklist GET requests. No ID is created
just for browsing, opening a form, or cancelling.

This is pseudonymous deduplication, not identity verification or authentication.
The backend can associate explicit reports and appeals carrying the same ID.
Reinstalling, clearing storage, or using another browser profile can produce a new
ID; API callers can invent UUIDs. Someone knowing an ID could also reuse it. Do not
interpret one install as one human or claim this prevents brigading. Later rate
limits and moderation reduce abuse; no fingerprints or watch-history telemetry
are introduced here.

## Run and verify

Apply the migration after rebuilding the backend:

```bash
docker compose build backend
docker compose run --rm --no-deps backend alembic upgrade head
docker compose up -d --wait backend
npm --prefix extension run build
```

Reload the unpacked extension and YouTube tabs after rebuilding. See
[extension setup](extension-sync.md) for the initial Compose/database steps.
A new report is not expected to blur its target automatically.

Tests (with a PostgreSQL test URL configured as described in `database.md`):

```bash
cd backend
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/TEST_DB TEST_REDIS_URL=redis://HOST:REDIS_PORT/0 .venv/bin/python -m pytest -q
cd ../extension
npm test
```

Backend tests exercise validation, transaction boundaries, concurrent duplicates,
unchanged moderation, appeal history, and failures. Chromium tests cover explicit
submission controls, cancellation, payload privacy, handle-only input, duplicate
responses, draft retention, uncertain network outcomes, recycled targets, and ID
persistence. All submitted test data is synthetic.
