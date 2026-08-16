"""Lightweight operational metrics (WP1/WP6).

A dependency-free Prometheus-style text exposition with no new runtime
dependencies. Counters are fed by the DB pool events in ``app.db.session``
and by middleware/route hooks:

- pool: checked-out connections, checkout total, wait now/total, timeouts
- requests: total, in-flight, latency bucket counts, per-path status
- auth: authentication failures (401)
- db: idle-in-transaction guard aborts (from the app guard in session.py)

Thread-safe via a lock; values are ints/float only.
"""

import threading
import time

_lock = threading.Lock()

_metrics: dict = {
    # pool (fed by app.db.session events)
    "pool_checked_out": 0,
    "pool_checkout_total": 0,
    "pool_wait_total": 0,
    "pool_wait_now": 0,
    "pool_timeout_total": 0,
    # requests
    "requests_total": 0,
    "requests_in_flight": 0,
    "requests_5xx_total": 0,
    "requests_4xx_total": 0,
    # latency buckets (seconds): labels are bucket upper bounds
    "latency_bucket_lt_0_05": 0,
    "latency_bucket_lt_0_1": 0,
    "latency_bucket_lt_0_5": 0,
    "latency_bucket_lt_1": 0,
    "latency_bucket_lt_5": 0,
    "latency_bucket_ge_5": 0,
    # auth
    "auth_failures_total": 0,
    # db guard
    "db_idle_in_tx_abort_total": 0,
}

_started = time.monotonic()


def inc(name: str, delta: int = 1) -> None:
    with _lock:
        _metrics.setdefault(name, 0)
        _metrics[name] += delta


def set_gauge(name: str, value) -> None:
    with _lock:
        _metrics[name] = value


def record_latency(seconds: float) -> None:
    with _lock:
        for bound in (0.05, 0.1, 0.5, 1, 5):
            if seconds < bound:
                _metrics[f"latency_bucket_lt_{bound}"] += 1
                break
        else:
            _metrics["latency_bucket_ge_5"] += 1


def snapshot() -> dict:
    with _lock:
        return dict(_metrics)


def uptime_seconds() -> float:
    return time.monotonic() - _started


_METRIC_HELP = {
    "pool_checked_out": "SQLAlchemy pool connections currently checked out",
    "pool_checkout_total": "Total pool checkouts",
    "pool_wait_total": "Total pool wait events (waited for a connection)",
    "pool_wait_now": "Pool connections currently waiting",
    "pool_timeout_total": "Pool checkout timeouts",
    "requests_total": "Total HTTP requests",
    "requests_in_flight": "HTTP requests currently in flight",
    "requests_5xx_total": "HTTP 5xx responses",
    "requests_4xx_total": "HTTP 4xx responses",
    "auth_failures_total": "Authentication failures (401)",
    "db_idle_in_tx_abort_total": "Idle-in-transaction aborts from the app guard",
}


def render_prometheus() -> str:
    """Render the metrics snapshot as Prometheus text exposition format."""
    lines = [f"# HELP vidistiller_uptime_seconds Application uptime",
             "# TYPE vidistiller_uptime_seconds gauge",
             f"vidistiller_uptime_seconds {uptime_seconds():.3f}"]
    for name, value in sorted(snapshot().items()):
        metric = f"vidistiller_{name}"
        if name in _METRIC_HELP:
            lines.append(f"# HELP {metric} {_METRIC_HELP[name]}")
        if name.startswith("pool_") or name == "requests_in_flight":
            lines.append(f"# TYPE {metric} gauge")
        else:
            lines.append(f"# TYPE {metric} counter")
        lines.append(f"{metric} {value}")
    return "\n".join(lines) + "\n"
