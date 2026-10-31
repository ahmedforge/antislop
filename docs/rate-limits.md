# Submission rate limits (Stage 8)

Validated `POST /v1/reports` and `POST /v1/appeals` requests share two Redis-backed
token buckets: one for the installation UUID and one for the connection's IP.
Both must have a token. This limits an installation across IPs and an IP across
new installation IDs. UUIDs remain pseudonymous identifiers, not authentication.

Token buckets allow a short burst of actions, then refill steadily instead of
resetting at a minute boundary. A bucket with capacity `C` and one token every
`S` seconds refills as:

```text
available = min(C, previous_tokens + elapsed_seconds / S)
allowed if both buckets have at least 1 token
on success: subtract 1 from each
on rejection: leave both stored buckets unchanged
```

One Lua script uses Redis's own time, checks both buckets, and consumes their tokens
atomically. Requests from separate API workers therefore share a consistent budget.
[Redis guarantees atomic script execution](https://redis.io/docs/latest/develop/programmability/eval-intro/).
An insufficient bucket returns the ceiling of its time until the next token; if
both are insufficient, the larger delay becomes `Retry-After`.

## Defaults and configuration

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `RATE_LIMIT_INSTALL_CAPACITY` | 5 | Initial/max burst per installation |
| `RATE_LIMIT_INSTALL_REFILL_SECONDS` | 60 | Seconds to replenish one install token |
| `RATE_LIMIT_IP_CAPACITY` | 20 | Initial/max burst per IP |
| `RATE_LIMIT_IP_REFILL_SECONDS` | 10 | Seconds to replenish one IP token |
| `RATE_LIMIT_NAMESPACE` | `antislop:rate-limit:v1` | Shared Redis key prefix; must match across workers |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL (Compose uses `redis://redis:6379/0`) |

Capacity and refill settings must be positive and bounded; NaN/infinite intervals
are rejected. Compose forwards the four budget variables from the shell/root `.env`.
The standalone API reads these from its environment or `backend/.env`.
Use the same budgets and namespace on every replica. IP limits also affect users
sharing a NAT; defaults are starting values, not a claim of production calibration.

`429` returns a positive integer `Retry-After` in seconds and `Cache-Control: no-store`.
The extension shows the delay and retains the open form's draft. It does not queue
or automatically retry submissions. Another user's requests on a shared IP may
consume a newly available token before the suggested retry.

Once both buckets admit a valid request, its tokens are spent even if it is a
business-level duplicate or a later database write fails. This limits repeated
requests rather than only newly created records. Schema-invalid submissions return
`422` before reaching this dependency; they do not consume tokens.

## Failures, privacy, and deployment scope

Redis connection/command failures return `503` and `Retry-After: 5` **before any
PostgreSQL write**. This fails closed for submissions. Redis socket/connect timeouts
are one second each, with automatic retries disabled so a lost reply does not
silently debit another token. Health and blocklist GET requests do not use this
limiter and remain available while Redis is down. This stage protects validated
submission traffic, not arbitrary invalid bodies, read traffic, or volumetric DDoS.

Bucket keys contain the install UUID or a SHA-256 digest of the normalized IP, with
no channels, reasons, or viewing URLs. The digest is not anonymization: IP values
are guessable. It avoids storing raw IP text, and the data is temporary. Keys expire
after the idle time needed to refill the entire bucket (five minutes per install,
200 seconds per IP with the defaults). Rejections create no new keys or extend
TTL. No IP is added to PostgreSQL or application logs by this limiter.

IPv6 spellings and IPv4-mapped IPv6 addresses are canonicalized. The dependency
uses the ASGI client address and ignores `Forwarded`/`X-Forwarded-For` headers.
The Docker command explicitly disables Uvicorn proxy-header processing. Run the
standalone command with `--no-proxy-headers` too. If deploying behind a reverse
proxy later, configure a specific trusted proxy boundary deliberately; otherwise
all clients may share the proxy's bucket. Never trust arbitrary forwarded headers.

Compose Redis remains ephemeral, so restarting/replacing Redis may reset quotas.
Redis memory eviction would also reset affected quotas; production Redis policy
and durability need deliberate deployment configuration. This does not replace
Stage 9 moderation or prove that one installation equals one person.

## Verification

From `backend/`, with disposable PostgreSQL and Redis URLs:

```bash
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/TEST_DB \
TEST_REDIS_URL=redis://HOST:REDIS_PORT/0 .venv/bin/python -m pytest -q
```

The suite uses random per-test Redis prefixes and PostgreSQL schemas. Cleanup
removes only those test keys/schemas; it never flushes a shared Redis database.
Without the appropriate URLs, integration tests explicitly skip.

Tests cover independent IP/install limits, fractional refill, refill caps, TTLs,
concurrent admission, quota sharing across API instances/routes, forwarded-header
spoofing, Redis failures without writes, and positive retry headers. Browser tests
check the displayed wait time and preservation of the reason through an explicit
retry. Invalid configuration is tested separately.
