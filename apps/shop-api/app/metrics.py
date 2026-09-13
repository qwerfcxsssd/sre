import threading
from collections.abc import Iterator

from prometheus_client import REGISTRY, Counter, Gauge, Histogram
from prometheus_client.metrics_core import Metric
from prometheus_client.registry import Collector

HTTP_DURATION_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

ORDER_AMOUNT_BUCKETS = (100.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0, 25000.0)

WORKER_DURATION_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2)

HttpKey = tuple[str, str, str, str | None]


class HttpRequestsCollector(Collector):
    """http_requests_total with an optional user_id label.

    A plain Counter has a fixed label set, but the chaos switch `high_cardinality`
    has to add `user_id` to the very same metric family at runtime, so the samples
    are emitted by hand.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[HttpKey, float] = {}

    def inc(self, method: str, route: str, status: str, user_id: str | None = None) -> None:
        with self._lock:
            key: HttpKey = (method, route, status, user_id)
            self._counts[key] = self._counts.get(key, 0.0) + 1.0

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()

    def collect(self) -> Iterator[Metric]:
        metric = Metric("http_requests", "Total HTTP requests handled.", "counter")
        with self._lock:
            snapshot = dict(self._counts)
        for (method, route, status, user_id), value in snapshot.items():
            labels = {"method": method, "route": route, "status": status}
            if user_id is not None:
                labels["user_id"] = user_id
            metric.add_sample("http_requests_total", labels, value)
        yield metric


HTTP_REQUESTS = HttpRequestsCollector()
REGISTRY.register(HTTP_REQUESTS)

HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency.",
    labelnames=("method", "route"),
    buckets=HTTP_DURATION_BUCKETS,
)

HTTP_IN_FLIGHT = Gauge(
    "http_requests_in_flight",
    "HTTP requests currently being served.",
)

ORDERS_CREATED = Counter(
    "app_orders_created_total",
    "Checkout attempts by outcome.",
    labelnames=("result",),
)

ORDER_AMOUNT = Histogram(
    "app_order_amount_rubles",
    "Order total in rubles.",
    buckets=ORDER_AMOUNT_BUCKETS,
)

QUEUE_DEPTH = Gauge(
    "app_queue_depth",
    "Pending jobs in the Redis queue.",
)

WORKER_JOBS = Counter(
    "app_worker_jobs_total",
    "Jobs processed by the background worker, by outcome.",
    labelnames=("result",),
)

WORKER_JOB_DURATION = Histogram(
    "app_worker_job_duration_seconds",
    "Background job processing time.",
    buckets=WORKER_DURATION_BUCKETS,
)

DEPENDENCY_UP = Gauge(
    "app_dependency_up",
    "1 when the dependency answered its probe, 0 otherwise.",
    labelnames=("dependency",),
)

CACHE_OPERATIONS = Counter(
    "app_cache_operations_total",
    "Redis cache operations by outcome.",
    labelnames=("operation", "result"),
)

DB_POOL_CONNECTIONS = Gauge(
    "app_db_pool_connections",
    "SQLAlchemy connection pool occupancy.",
    labelnames=("state",),
)

BUILD_INFO = Gauge(
    "app_build_info",
    "Build metadata, always 1.",
    labelnames=("version", "commit", "python_version"),
)


def set_build_info(version: str, commit: str, python_version: str) -> None:
    BUILD_INFO.labels(version=version, commit=commit, python_version=python_version).set(1)


for _dependency in ("postgres", "redis"):
    DEPENDENCY_UP.labels(dependency=_dependency).set(0)

for _state in ("in_use", "idle"):
    DB_POOL_CONNECTIONS.labels(state=_state).set(0)
