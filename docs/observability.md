# Observability (Stage 11)

Prometheus scrapes `GET /metrics` every 15 seconds. Grafana reads Prometheus and
loads the repository's **AntiSlop Overview** dashboard automatically. No external
monitoring account or manual dashboard import is required.

## Start and open

From the repository root, with the existing local environment settings:

```bash
docker compose up --build -d --wait
docker compose exec -T backend alembic upgrade head
curl --fail http://127.0.0.1:8000/metrics
```

Open:

- Grafana: <http://127.0.0.1:3000/d/antislop-overview/antislop-overview>
- Prometheus target status: <http://127.0.0.1:9090/targets>
- API metrics: <http://127.0.0.1:8000/metrics>

Grafana is configured as a **local read-only viewer**, with no login form or
initial admin account. Its dashboard and data source are provisioned from files.
Change dashboard JSON in `monitoring/grafana/dashboards/antislop.json`; Grafana
checks for updates every 30 seconds. All published ports bind to loopback.
`GRAFANA_PORT`, `PROMETHEUS_PORT`, and `API_PORT` can override the host ports.
Prometheus talks to `backend:8000`, and Grafana to `prometheus:9090`, inside Compose.

Allow at least two scrapes before rate charts populate. Empty traffic produces
zero counters; latency has no samples until requests arrive. You can exercise
read-only traffic with `curl http://127.0.0.1:8000/v1/blocklist`. Health checks and
metrics scrapes are excluded from the dashboard's latency chart. The metrics
endpoint itself is excluded from all HTTP instrumentation.

## Metrics and their meaning

| Metric | Meaning |
| --- | --- |
| `antislop_http_requests_total{method,route,status}` | Completed HTTP requests, including handled errors and unexpected failures |
| `antislop_http_request_duration_seconds{method,route}` | Histogram of elapsed request time through the application, including response sending |
| `antislop_reports_created_total` | Successfully created reports (201), excluding duplicate retries (200), invalid input, and failed writes |
| `antislop_blocklist_sync_requests_total{status}` | Blocklist GET requests, including conditional 304 responses and errors |
| `antislop_rate_limit_rejections_total{route}` | Reports/appeals rejected with 429; Redis outages returning 503 are not rate-limit rejections |
| `antislop_approved_channels` | Current PostgreSQL count of approved channels, refreshed on every scrape |
| `antislop_metrics_database_up` | 1 when the approved-count query succeeds, otherwise 0 |
| `up{job="antislop-api"}` | Prometheus's own signal that the scrape succeeded |

Request routes are templates, such as `/v1/admin/channels/{channel_id}/decision`.
Unknown paths share the label `unmatched`; unfamiliar HTTP methods share `OTHER`.
Neither request bodies nor query strings, identifiers, IP addresses, API keys,
reasons, or watched content become metric labels. No browsing events are added.

The approved-count query has a 1-second lock timeout and 2-second statement
timeout. Database connection/pool waits can still delay a scrape; Prometheus stops
waiting after its 10-second scrape timeout. If the count query fails, the metrics
endpoint still exports in-memory metrics and `antislop_metrics_database_up 0`, but
**omits the approved count**. It never substitutes a misleading zero or stale
cached count. The dashboard shows that count as unavailable. A successful scrape
therefore does not prove the database is healthy; inspect both health panels.

The report counter is operational telemetry, not an accounting ledger: process
crashes between commit and response instrumentation can lose an observation.
The database remains the source of truth. Counters reset when the API process
restarts; Prometheus `rate()` handles those resets. Rates are smoothed over
Grafana's selected interval and multiplied by 60 for a per-minute display.
The latency panel computes p95 from histogram buckets; it is an estimate.

## Storage and deployment limits

Prometheus keeps data in `prometheus_data`, with retention capped at 7 days or
1 GB of retained blocks, whichever is reached first. WAL/head data can add disk
usage beyond that block limit. Grafana uses `grafana_data`. Ordinary
`docker compose down` retains volumes; `down -v` destroys them **and the application
database volume**, so do not use it to clear monitoring history casually.

The metrics registry belongs to one application process. The supplied Dockerfile
runs a single Uvicorn worker. Do not add multiple workers behind this scrape
endpoint: each process would expose a different counter set. For scaling, run
one worker per separately scraped instance and aggregate rates across instances;
use `max`, not `sum`, for identical database-wide approved counts. A multiprocess
collector setup would require a separate design.

This Compose setup is for local development. `/metrics`, Prometheus, and the
anonymous Grafana viewer have no remote authentication. Keep them private; a
remote deployment needs restricted networking and an authenticated access layer.
Grafana analytics/update checks are disabled. No alerts or cloud exporter are
introduced in this stage.

## Verify

The regular backend CI suite includes real-database tests for metric counts,
conditional syncs, duplicates, 429s, database/Redis failures, approved-state
changes, missing counts, route-label privacy, application-registry isolation, and
unexpected 500 responses. See [testing and CI](testing-and-ci.md).

Validate the Prometheus configuration using its packaged tool:

```bash
docker compose run --rm --no-deps --entrypoint promtool prometheus \
  check config /etc/prometheus/prometheus.yml
```

In Prometheus, `up{job="antislop-api"}` should return 1. Grafana's data source and
seven panels should load without setup. New-report rates remain zero until real
users explicitly submit reports; this setup does not create fake reports in your
application database to populate charts.

Implementation references: [Python custom collectors](https://prometheus.github.io/client_python/collector/custom/),
[Prometheus configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/),
and [Grafana file provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/).
