"""Aggregate operational metrics; never label by a user or channel identifier."""
from collections.abc import Iterable
from time import perf_counter

from fastapi import APIRouter, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from prometheus_client.core import GaugeMetricFamily, Metric
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.models import Channel

router = APIRouter(tags=["operations"])
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


class Metrics:
    def __init__(self) -> None:
        # Per-application registry: no duplicate collectors or cross-app test state.
        self.registry = CollectorRegistry()
        self.requests = Counter("antislop_http_requests_total", "Completed HTTP requests.",
                                ["method", "route", "status"], registry=self.registry)
        self.latency = Histogram("antislop_http_request_duration_seconds", "HTTP request duration.",
                                 ["method", "route"], registry=self.registry,
                                 buckets=(.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10))
        self.reports = Counter("antislop_reports_created_total", "New reports committed successfully (excludes duplicates).",
                               registry=self.registry)
        self.syncs = Counter("antislop_blocklist_sync_requests_total", "Blocklist GET requests, including conditional requests.",
                             ["status"], registry=self.registry)
        self.rejections = Counter("antislop_rate_limit_rejections_total", "Submission requests rejected with HTTP 429.",
                                  ["route"], registry=self.registry)
        for status in ("200", "304", "422", "503", "500"):
            self.syncs.labels(status)
        for route in ("/v1/reports", "/v1/appeals"):
            self.rejections.labels(route)


class ApprovedChannelsCollector:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def collect(self) -> Iterable[Metric]:
        try:
            with self.engine.begin() as connection:
                connection.exec_driver_sql("SET LOCAL lock_timeout = '1s'")
                connection.exec_driver_sql("SET LOCAL statement_timeout = '2s'")
                count = connection.scalar(select(func.count()).select_from(Channel).where(Channel.status == "approved"))
        except SQLAlchemyError:
            # Export other metrics even when PostgreSQL is down. Do not report a
            # fake zero or keep a stale approved count when the query fails.
            yield GaugeMetricFamily("antislop_metrics_database_up", "Whether the approved-channel count query succeeded.", value=0)
            return
        yield GaugeMetricFamily("antislop_metrics_database_up", "Whether the approved-channel count query succeeded.", value=1)
        yield GaugeMetricFamily("antislop_approved_channels", "Current approved channels in PostgreSQL.", value=count)


class MetricsMiddleware:
    def __init__(self, app: ASGIApp, metrics: Metrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/metrics":
            await self.app(scope, receive, send)
            return
        started = perf_counter()
        status = 500

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            # Routing has completed. Use templates (including {channel_id}),
            # never raw paths, query strings, headers, request bodies or IPs.
            route = getattr(scope.get("route"), "path", "unmatched")
            method = scope["method"] if scope["method"] in METHODS else "OTHER"
            self.metrics.requests.labels(method, route, str(status)).inc()
            self.metrics.latency.labels(method, route).observe(perf_counter() - started)
            if route == "/v1/reports" and method == "POST" and status == 201:
                self.metrics.reports.inc()
            if route == "/v1/blocklist" and method == "GET":
                self.metrics.syncs.labels(str(status)).inc()
            if route in ("/v1/reports", "/v1/appeals") and status == 429:
                self.metrics.rejections.labels(route).inc()


@router.get("/metrics", include_in_schema=False)
def metrics_endpoint(request: Request) -> Response:
    return Response(generate_latest(request.app.state.metrics.registry),
                    headers={"Content-Type": CONTENT_TYPE_LATEST, "Cache-Control": "no-store"})
