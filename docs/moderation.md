# Scoring and moderation (Stage 9)

A report adds evidence to a review queue. It is never an automatic block.

## Scoring

Each newly inserted report recalculates its channel's score as the sum of its
reporters' current installation reputations. New installations start at 1; zero
reputation contributes nothing. Duplicate reports neither add weight nor replace
the original reason. The score saturates at 99,999,999.9999 (the database limit).
A channel row lock serializes concurrent reports and moderation decisions, and
report insertion, scoring, and the status change commit in one transaction.

`REVIEW_THRESHOLD` defaults to 5 (positive, at most four decimal places). An
`unreviewed` channel reaching that score becomes `pending_review`. Existing
`pending_review`, `approved`, and `rejected` decisions are preserved by reports.
Only an admin decision can approve a reported channel. The explicit seed import
remains a separate trusted way to approve an initial list.

Reputation is server-owned: public submissions cannot set it, and this stage does
not introduce automatic reputation rewards or an editing endpoint. Scores use
current reputation at the time of the latest new report, not a weight snapshot.
Out-of-band reputation or threshold changes do not backfill old scores or queues;
operators must plan an explicit recalculation if they change those values.
Recalculating all reports is deliberately simple for v1, but costs more as a
channel's report history grows. A channel's pre-existing score (including a seed
score) is replaced by the report-derived total on its next new report.

## Admin setup and API

Set `ADMIN_API_KEY` to a cryptographically random secret of at least 32 ASCII
characters, without whitespace. Generate one with:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Store it in your local ignored environment file or deployment secret store. For
Compose, use the repository-root `.env`; for direct backend commands, use
`backend/.env`. Restart/recreate the backend after changing it. An empty key
(default) disables all admin routes with 503; incorrect/missing keys return 401.
There is no default usable admin credential. Never include the key in the
extension, a URL, version control, screenshots, or logs. Use HTTPS for remote
administration. The documented local Compose API binds only to loopback.

Every route below requires the `X-Admin-Key` header. The key is compared in
constant time. This is one shared operator credential, not individual admin
accounts: audit records identify the actor as `admin-api`, never the secret.
Admin results use `Cache-Control: no-store`. Public endpoints cannot read evidence.
Use `/docs` and its Authorize control for local manual administration.

| Method and path | Purpose |
| --- | --- |
| GET `/v1/admin/channels` | Review queue; `status` defaults to `pending_review`, also accepts `unreviewed`, `approved`, `rejected` |
| GET `/v1/admin/channels/{channel_id}/reports` | Report reasons and current reporter reputations for review |
| GET `/v1/admin/appeals` | Appeals with reasons; `status` defaults to `open`, also accepts `accepted`, `rejected` |
| POST `/v1/admin/channels/{channel_id}/decision` | `{"action":"approve","reason":"Reviewed evidence"}` or action `reject` |
| POST `/v1/admin/appeals/{appeal_id}/decision` | `{"action":"accept","reason":"Reviewed evidence"}` or action `reject` |

Path IDs are **internal database UUIDs** returned by the admin lists, not the
external YouTube channel IDs used in public submissions. Lists use `limit`
(default 50, maximum 100) and `offset` (default 0), ordered by creation time and
UUID. Offset pagination is for a small interactive queue; changes during paging
can move entries, so refresh the queue before deciding. Reasons are required,
trimmed, and 1–2000 characters. Unknown fields and invalid input return 422;
missing targets return 404.

An admin may approve/reject a channel in any state, allowing corrections and
reconsideration. Repeating the channel's existing decision returns `changed:false`
without another audit record. A later opposite decision intentionally overrides
the previous one. Every actual decision records its reason atomically with the
status update; database errors roll back both and return 503 with Retry-After: 5.

Accepting an open appeal resolves it and changes the channel to `rejected`, which
means excluded from the blocklist. Rejecting an appeal resolves it without changing
the channel's current status, including if another admin already unblocked it.
Repeated identical appeal decisions return `changed:false`; attempting to reverse
a resolved appeal returns 409. A channel can still be reconsidered through its
channel decision endpoint. Other open appeals stay open for explicit review.
Retrying an already accepted appeal does not overturn any later channel decision.
Concurrent opposite appeal decisions have exactly one winner and one audit record.

Only `approved` channels appear in a full blocklist. Approval adds a channel to
the next delta; rejection or an accepted appeal emits a removal. The browser
applies that removal at its next successful sync, not instantly. Offline browsers
keep their previous cache until they reconnect. No browsing data is involved.

## Why this reduces brigading

Deduplication prevents one installation from repeatedly adding weight. Redis
buckets restrict submission bursts by installation and IP. Weighted reports can
reduce the contribution of low-reputation installations. Most importantly, even
many reports only trigger review: moderators must inspect the channel and evidence
before approval. Rejected channels cannot be forced back into review by reports.

These controls do not prove independent reporters or prevent a distributed attack.
Anonymous UUIDs can be fabricated, default reputations are equal, IP limits can be
shared by legitimate users, and admins can make mistakes. Appeals and reversible
filtering remain necessary. Never treat the score alone as proof of AI content.

## Verification

Against disposable PostgreSQL and Redis services, from the repository root:

```bash
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/TEST_DB \
TEST_REDIS_URL=redis://HOST:REDIS_PORT/0 \
backend/.venv/bin/python -m pytest backend/tests -q
```

Tests cover weighted thresholds, duplicate and concurrent reports, protected admin
routes, queue evidence, audited approval, appeal rejection/acceptance, concurrent
appeal decisions, atomic rollback, and blocklist removal deltas. Tests isolate
PostgreSQL schemas and Redis key prefixes. No new migration is needed: Stage 4's
schema already stores scores, reputation, decisions, and appeal resolution.
