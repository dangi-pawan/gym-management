import time
from typing import Any, Awaitable, Callable

from prometheus_client import Counter, Gauge, Histogram


REQUEST_COUNT = Counter(
    "http_requests",
    "Total number of HTTP requests.",
    ("method", "handler", "status_code"),
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "handler"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Number of HTTP requests currently being processed.",
    ("method",),
)


class PrometheusMetricsMiddleware:
    """Collect low-cardinality HTTP metrics for Prometheus."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[Any]],
        send: Callable[..., Awaitable[None]],
    ) -> None:
        if scope["type"] != "http" or scope.get("path", "").startswith("/metrics"):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        status_code = "500"
        started_at = time.perf_counter()

        REQUESTS_IN_PROGRESS.labels(method=method).inc()

        async def send_with_status(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = str(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            route = scope.get("route")
            handler = getattr(route, "path", None) or "unmatched"

            REQUEST_COUNT.labels(
                method=method,
                handler=handler,
                status_code=status_code,
            ).inc()
            REQUEST_LATENCY.labels(
                method=method,
                handler=handler,
            ).observe(time.perf_counter() - started_at)
            REQUESTS_IN_PROGRESS.labels(method=method).dec()
