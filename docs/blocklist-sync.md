# Blocklist delta sync (Stage 5)

`GET /v1/blocklist` returns a full snapshot. Only approved channels appear in
`channels`; no reports, install IDs, scores, reasons, or viewing activity are sent.
The request has no channel/video lookup parameter. All browsing lookups remain
local to the extension in Stage 6.

Example shape (timestamps are illustrative):

```json
{
  "full_sync": true,
  "channels": [
    {
      "youtube_channel_id": "UC0000000000000000000000",
      "handle": "@antislop-demo-fixture",
      "updated_at": "2026-10-31T10:00:00.123456Z"
    }
  ],
  "removed_channel_ids": [],
  "next_since": "2026-10-31T10:00:00.123456Z"
}
```

A full snapshot **replaces** the local list. Then request
`GET /v1/blocklist?since=<previous next_since>` for deltas. URL-encode the cursor,
especially timezone offsets containing `+`. Keep the returned timestamp string
verbatim: JavaScript Date serialization can discard microseconds.

For a delta, upsert `channels` by `youtube_channel_id` (replacing the previous
handle, including with null), then delete every ID in `removed_channel_ids`.
Persist the list and `next_since` together only after applying the response.
Removal IDs represent changed non-approved rows, including rows never present in
the client's cache; deleting an absent ID is a no-op. This ensures revoked approval
can stop filtering a wrongly flagged creator. No non-approved handle or moderation
reason is exposed.

The timestamp boundary is inclusive. A row exactly at `since` may be replayed;
upserting/deleting by ID makes retrying the same delta safe. `next_since` is the
latest channel update timestamp, never earlier than the submitted cursor, or the
Unix epoch for an empty initial database. It remains stable without changes.
Naive, malformed, pre-epoch, or future timestamps return `422`.

## ETag and failure behavior

The response's `ETag` hashes the exact deterministic JSON bytes, including its
cursor. `Cache-Control: public, no-cache` permits caching but requires revalidation
before reuse. Store an ETag with its **exact request URL**, not globally; full
snapshots and different `since` values are different representations.

On a repeat request, send `If-None-Match: "the-saved-tag"`. If it matches, the API
returns `304` with no response body. Retain the cached representation and cursor.
A 304 is useful only when the client still has the corresponding cached response.
A changed representation returns `200` with its new body and ETag. Weak validators,
comma-separated validator lists, and the wildcard are supported for GET, following
[RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.2).

ETags save response bandwidth; this version still reads PostgreSQL to calculate
them. They do not bypass the database query. No Redis response cache is added.
Database errors and lock timeouts return `503` with `Retry-After: 5` and a generic
message. The extension should keep its last valid cache and retry later. No database
credentials or SQL exception details appear in the response.

## Snapshot consistency and scope

A short `SHARE` table lock waits for uncommitted channel writes and prevents new
writes during the snapshot. Concurrent sync readers can proceed together. Subsequent
READ COMMITTED queries see the writers that finished before the lock was acquired.
PostgreSQL's [locking rules](https://www.postgresql.org/docs/17/explicit-locking.html)
define these conflicts. Lock waiting is capped at three seconds, SQL statements at
ten seconds, and initial database connections at five seconds.

Migration `0002` extends the timestamp trigger to inserts as well as updates. This
uses actual statement-time clock readings rather than transaction-start time, so
an insert from a transaction started before the last sync cannot be backdated by
the default `now()` value. Tests cover this and a pending writer committing while
a sync request waits.

Trade-off: this simple unpaginated design suits a small v1 community list; a large
list or frequent moderation would need a durable change log and paginated snapshot
protocol to reduce write blocking. Timestamps assume a forward-moving database
clock; after restoring an older database or moving the clock backwards, clients
must obtain a fresh full snapshot. Keep channel rows and change their status;
hard deletion is not supported by this delta protocol because no tombstone remains.
There is no channel deletion endpoint.

## Seed import

From `backend/`, with the migrated database URL configured:

```bash
.venv/bin/python -m app.seed app/seed.demo.json
```

Or with the Compose database running and backend image rebuilt:

```bash
docker compose run --rm --no-deps backend alembic upgrade head
docker compose run --rm --no-deps backend python -m app.seed app/seed.demo.json
```

Expected first run: `Inserted 1 approved channel(s); existing channels left unchanged.`
Expected repeat: `Inserted 0 approved channel(s); existing channels left unchanged.`
The demo file contains a **synthetic fixture**, not an allegation about a real
creator. Nothing is imported automatically. Supply your own JSON array of vetted
channels to the same CLI for real seed data; entries require `youtube_channel_id`
and a review `reason`, and may contain `handle`.

The whole file is validated before writing. Import runs in one transaction, creates
an approval audit action for each newly inserted channel, and never overwrites an
existing row, even if that row has since been rejected. Duplicate IDs within the
file are rejected. This is an explicit operator import, not public moderation API.

## Verification

From the repository root with Compose running:

```bash
curl --fail -i http://127.0.0.1:8000/v1/blocklist
curl --fail -G --data-urlencode 'since=1970-01-01T00:00:00Z' http://127.0.0.1:8000/v1/blocklist
```

Expect `200`, an `ETag` header, and the response shape above. To check `304`, repeat
the identical URL with its exact ETag in `If-None-Match`.

The full PostgreSQL suite from `backend/` is:

```bash
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/TEST_DB .venv/bin/python -m pytest -q
```

Each PostgreSQL test uses its own temporary schema. With no test URL, these tests
explicitly skip; the health and database-unavailable tests still run.
