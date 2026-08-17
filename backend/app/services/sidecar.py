"""Server-side sidecar registry and load-aware inventory (WP3).

Two layers:

1. **Registry** — trusted operator configuration persisted in the
   ``sidecars`` table. Users may select only a ``registered_id``; the
   endpoint URL is resolved server-side and is never client-supplied
   (Review Round 1 Findings 12-14).
2. **Inventory** — live probes (health, served model, running/waiting
   requests, cache/VRAM where available) plus Vidistiller-reserved slots
   from ``resource_slots``. Telemetry is timestamped; stale telemetry fails
   closed for NEW allocations without disturbing in-flight work.

The model identity used for routing is the one actually served by the live
probe — never the declared model name alone (plan §3).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

import requests
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ResourceSlot, Sidecar, SlotState

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 3
STALE_TELEMETRY_SECONDS = 30

# Redis key prefix for the shared telemetry store (WP3-hotfix). The API
# scheduler publishes snapshots here; EVERY process (API and Celery worker
# alike) reads through the same store into its own process-local cache, so
# worker processes see the same inventory the API probed without ever
# probing sidecars themselves (no sidecar network I/O inside a worker's DB
# transaction, Review Round 2 F7 preserved).
TELEMETRY_REDIS_KEY_PREFIX = "vidistiller:sidecar-telemetry:"

# Background telemetry cache (Review Round 2 F7): the inventory is refreshed
# by the scheduler loop, never probed inside a request transaction.
# WP3-hotfix: this is now a per-process READ-THROUGH cache over the shared
# Redis store — the API scheduler writes it via refresh_telemetry_cache,
# every process (including each Celery worker) lazily re-reads from Redis
# when a local entry is missing or older than LOCAL_TELEMETRY_CACHE_TTL_SECONDS.
_telemetry_cache: dict[str, SidecarTelemetry] = {}
_telemetry_lock = threading.Lock()
_telemetry_loaded_at: float = 0.0
_telemetry_local_ts: dict[str, float] = {}  # monotonic per-entry load time

# Lazily-created shared Redis client (decode_responses=True, bounded timeouts).
_redis_client: Optional[object] = None
_redis_lock = threading.Lock()


def _get_redis() -> object:
    """Return a bounded shared Redis client for the telemetry store."""
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                import redis as _redis

                _redis_client = _redis.from_url(
                    get_settings().cache.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
    return _redis_client


def _telemetry_key(registered_id: str) -> str:
    return f"{TELEMETRY_REDIS_KEY_PREFIX}{registered_id}"


def _telemetry_to_dict(t: SidecarTelemetry) -> dict:
    """Serialize a telemetry row for the shared store (fields only; the
    ``stale``/``available_slots`` properties are recomputed on read).
    ``allow_nan=False`` rejects NaN/Infinity so a malformed float can never
    be published and later evade staleness checks."""
    return {
        "registered_id": t.registered_id,
        "label": t.label,
        "base_url": t.base_url,
        "declared_model": t.declared_model,
        "capabilities": list(t.capabilities or []),
        "healthy": t.healthy,
        "served_models": list(t.served_models or []),
        "running_requests": t.running_requests,
        "waiting_requests": t.waiting_requests,
        "vram_used_mib": t.vram_used_mib,
        "vram_total_mib": t.vram_total_mib,
        "cache_hit_rate": t.cache_hit_rate,
        "reserved_slots": t.reserved_slots,
        "total_slots": t.total_slots,
        "observed_at": t.observed_at,
    }


def _telemetry_from_dict(payload: dict) -> Optional[SidecarTelemetry]:
    """Strictly validate and deserialize a telemetry row from the shared
    store. Returns None on ANY shape/type violation (fail closed): the
    caller treats it as no capacity. Validation is strict — no coercion:
    ``healthy`` must be a real bool, ``served_models`` a list of non-empty
    strings, ``observed_at`` a finite number, and ``registered_id`` must
    match the caller's expectation."""
    if not isinstance(payload, dict):
        return None
    try:
        registered_id = payload.get("registered_id")
        label = payload.get("label")
        base_url = payload.get("base_url")
        healthy = payload.get("healthy")
        served_models = payload.get("served_models")
        observed_at = payload.get("observed_at")
        capabilities = payload.get("capabilities")
        if not isinstance(registered_id, str) or not registered_id:
            return None
        if not isinstance(label, str) or not isinstance(base_url, str):
            return None
        if not isinstance(healthy, bool):  # never coerce "false" strings
            return None
        if not isinstance(served_models, list) or not all(
            isinstance(m, str) and m for m in served_models
        ):
            return None
        if not isinstance(observed_at, (int, float)) or isinstance(observed_at, bool):
            return None
        observed_at = float(observed_at)
        import math

        if not math.isfinite(observed_at):  # NaN/Inf would evade staleness
            return None
        if capabilities is not None and (
            not isinstance(capabilities, list)
            or not all(isinstance(c, str) and c for c in capabilities)
        ):
            return None
        return SidecarTelemetry(
            registered_id=registered_id,
            label=label,
            base_url=base_url,
            declared_model=_strict_optional_str(payload.get("declared_model")),
            capabilities=list(capabilities or []),
            healthy=healthy,
            served_models=list(served_models),
            running_requests=_strict_int(payload.get("running_requests")),
            waiting_requests=_strict_int(payload.get("waiting_requests")),
            vram_used_mib=_strict_int(payload.get("vram_used_mib"), nullable=True),
            vram_total_mib=_strict_int(payload.get("vram_total_mib"), nullable=True),
            cache_hit_rate=_strict_float(payload.get("cache_hit_rate"), nullable=True),
            reserved_slots=_strict_int(payload.get("reserved_slots")),
            total_slots=_strict_int(payload.get("total_slots")),
            observed_at=observed_at,
        )
    except (TypeError, ValueError):
        return None


def _strict_optional_str(value) -> Optional[str]:
    """Accept None or a non-empty string; ANY other type raises so the whole
    row is rejected (no coercion of numbers/bools to strings)."""
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise TypeError(f"expected optional non-empty string, got {type(value).__name__}")
    return value


def _strict_int(value, nullable: bool = False) -> int:
    """Strict int validation: only int (never bool) accepted; None accepted
    only when nullable. Any other type raises so the whole row is rejected."""
    if value is None:
        if nullable:
            return None  # type: ignore[return-value]
        raise TypeError("missing required integer")
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"expected int, got {type(value).__name__}")
    return value


def _strict_float(value, nullable: bool = False) -> Optional[float]:
    if value is None:
        if nullable:
            return None
        raise TypeError("missing required number")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"expected number, got {type(value).__name__}")
    return float(value)


def _publish_telemetry(t: SidecarTelemetry) -> None:
    """Publish one telemetry row to the shared Redis store (best-effort;
    failure must never break the API scheduler sweep). ``allow_nan=False``
    refuses to publish NaN/Infinity (which could otherwise evade staleness
    checks on read)."""
    try:
        ttl = get_settings().admission.telemetry_redis_ttl_seconds
        _get_redis().setex(
            _telemetry_key(t.registered_id),
            ttl,
            json.dumps(_telemetry_to_dict(t), allow_nan=False),
        )
    except Exception as exc:
        logger.warning("telemetry publish failed for %s: %s", t.registered_id, exc)


def _read_telemetry_from_redis(registered_id: str) -> Optional[SidecarTelemetry]:
    """Read one telemetry row from the shared Redis store (bounded, fail
    closed on any error). Returns None when absent/unreadable/unhealthy —
    the caller's eligibility checks apply staleness/no-model rules. The
    payload's registered_id MUST match the key it was read from (a
    mismatched row is malformed and fails closed)."""
    try:
        raw = _get_redis().get(_telemetry_key(registered_id))
        if not raw:
            return None
        payload = json.loads(raw)
        t = _telemetry_from_dict(payload)
        if t is None or t.registered_id != registered_id:
            return None
        return t
    except Exception as exc:
        logger.warning("telemetry read failed for %s: %s", registered_id, exc)
        return None


def prefetch_sidecar_telemetry(db: Session) -> dict[str, Optional[SidecarTelemetry]]:
    """Warm this process's local cache from the shared Redis store for all
    enabled sidecars and RETURN an immutable snapshot of the result.

    Called by capacity-critical paths BEFORE any DB row lock is taken
    (Review Round 2 F7 invariant: no network I/O while holding a DB
    transaction/row lock). Safe in every process: the API scheduler
    refreshes local data directly; workers (and a fresh API after restart)
    fill their local cache here.

    A FRESH local copy is always kept (never clobbered by a Redis miss): in
    the API process the scheduler just wrote it; in tests the fixture
    injected it. Only stale/missing local entries are re-read from Redis,
    and a Redis miss for those evicts them (fail closed).

    The returned snapshot maps every enabled registered id to its telemetry
    or an explicit None (miss) — consumers that hold DB row locks MUST read
    from this snapshot and never call the read-through getter, so no Redis
    I/O can occur under a lock. The dict is a fresh copy (mutating it cannot
    disturb the local cache).
    """
    ids = [rid for (rid,) in db.query(Sidecar.registered_id).filter(Sidecar.enabled.is_(True)).all()]
    if not ids:
        return {}
    now = time.monotonic()
    local_ttl = get_settings().admission.local_telemetry_cache_ttl_seconds
    snapshot: dict[str, Optional[SidecarTelemetry]] = {}
    for rid in ids:
        with _telemetry_lock:
            entry = _telemetry_cache.get(rid)
            loaded = _telemetry_local_ts.get(rid, 0.0)
            fresh_local = entry is not None and (now - loaded) < local_ttl
        if fresh_local:
            snapshot[rid] = entry  # fresh local copy — no Redis round trip
            continue
        t = _read_telemetry_from_redis(rid)
        if t is not None:
            with _telemetry_lock:
                _telemetry_cache[rid] = t
                _telemetry_local_ts[rid] = time.monotonic()
            snapshot[rid] = t
        else:
            # Fail closed for this process: an absent/unreadable shared row
            # must not leave a stale local copy serving as capacity.
            with _telemetry_lock:
                _telemetry_cache.pop(rid, None)
                _telemetry_local_ts.pop(rid, None)
            snapshot[rid] = None
    return dict(snapshot)


def refresh_telemetry_cache(db: Session) -> None:
    """Probe all enabled sidecars and replace the shared cache.

    Called by the periodic scheduler (never inside a request handler). The
    registry/slot reads are committed (transaction closed) BEFORE any
    network probe so no DB connection is held across external I/O
    (Review Round 2 F7). WP3-hotfix: after probing, the fresh snapshot is
    PUBLISHED to the shared Redis store so every process (API and Celery
    workers) reads the same inventory.
    """
    global _telemetry_loaded_at
    settings = get_settings().admission
    rows = db.query(Sidecar).filter(Sidecar.enabled.is_(True)).all()

    reserved_by_sidecar: dict[str, int] = {}
    from app.db.models import SlotState

    for slot in (
        db.query(ResourceSlot)
        .filter(ResourceSlot.state.in_((SlotState.LEASED, SlotState.EXPIRED)))
        .all()
    ):
        reserved_by_sidecar[slot.sidecar_id] = (
            reserved_by_sidecar.get(slot.sidecar_id, 0) + 1
        )
    db.commit()  # end the read transaction before probing

    fresh: dict[str, SidecarTelemetry] = {}
    for sidecar in rows:
        telemetry = _probe_sidecar(sidecar)
        telemetry.reserved_slots = reserved_by_sidecar.get(sidecar.registered_id, 0)
        telemetry.total_slots = settings.slots_per_sidecar
        fresh[sidecar.registered_id] = telemetry
    with _telemetry_lock:
        _telemetry_cache.clear()
        _telemetry_cache.update(fresh)
        _telemetry_loaded_at = time.time()
        now_mono = time.monotonic()
        for rid in fresh:
            _telemetry_local_ts[rid] = now_mono
    # WP3-hotfix: publish the snapshot to the shared store (best-effort).
    for telemetry in fresh.values():
        _publish_telemetry(telemetry)


def get_sidecar_telemetry_status(registered_id: str) -> str:
    """Return the LOCAL cached health status of a sidecar: 'ok' | 'unknown' |
    'unhealthy' | 'stale' | 'no_capacity'.

    Used by admission for the fail-closed preference check. STRICTLY LOCAL
    (never touches Redis): callers must prefetch_sidecar_telemetry() BEFORE
    entering a lock-holding section, then read status here. Unknown means
    the local cache has nothing fresh (scheduler not yet run in this
    process, or prefetch not yet called) — treated as 'ok' for the
    preference gate only if the registry row exists, but the task
    incarnation still requires a live slot lease before external work.
    """
    telemetry = local_sidecar_telemetry(registered_id)
    if telemetry is None:
        return "unknown"
    if not telemetry.healthy:
        return "unhealthy"
    if telemetry.stale:
        return "stale"
    if telemetry.available_slots <= 0:
        return "no_capacity"
    return "ok"


def local_sidecar_telemetry(registered_id: str) -> Optional[SidecarTelemetry]:
    """Strictly local lookup — NEVER touches Redis. Lock-held code paths
    must use this after prefetch_sidecar_telemetry(), never the read-through
    getter, so no network I/O can occur while DB row locks are held."""
    with _telemetry_lock:
        return _telemetry_cache.get(registered_id)


def cached_sidecar_telemetry(registered_id: str) -> Optional[SidecarTelemetry]:
    """Return the telemetry row for a sidecar: fresh process-local copy
    first, then the shared Redis store (WP3-hotfix). Fail closed: returns
    None when the local copy is missing/stale and the shared store has
    nothing readable. Safe to call outside row-lock sections only."""
    local_ttl = get_settings().admission.local_telemetry_cache_ttl_seconds
    now = time.monotonic()
    with _telemetry_lock:
        entry = _telemetry_cache.get(registered_id)
        loaded = _telemetry_local_ts.get(registered_id, 0.0)
        if entry is not None and (now - loaded) < local_ttl:
            return entry
    # Miss or stale local copy -> read through the shared store.
    t = _read_telemetry_from_redis(registered_id)
    if t is not None:
        with _telemetry_lock:
            _telemetry_cache[registered_id] = t
            _telemetry_local_ts[registered_id] = time.monotonic()
        return t
    with _telemetry_lock:
        _telemetry_cache.pop(registered_id, None)
        _telemetry_local_ts.pop(registered_id, None)
    return None


@dataclass
class SidecarTelemetry:
    """One live observation of a registered sidecar."""

    registered_id: str
    label: str
    base_url: str
    declared_model: Optional[str]
    capabilities: list[str]
    healthy: bool
    served_models: list[str] = field(default_factory=list)
    running_requests: int = 0
    waiting_requests: int = 0
    vram_used_mib: Optional[int] = None
    vram_total_mib: Optional[int] = None
    cache_hit_rate: Optional[float] = None
    reserved_slots: int = 0
    total_slots: int = 0
    observed_at: float = field(default_factory=time.time)

    @property
    def stale(self) -> bool:
        return (time.time() - self.observed_at) > STALE_TELEMETRY_SECONDS

    @property
    def available_slots(self) -> int:
        return max(0, self.total_slots - self.reserved_slots)


def registered_sidecar_ids(db: Session) -> list[str]:
    """All enabled registered sidecar ids (for validation)."""
    rows = (
        db.query(Sidecar.registered_id)
        .filter(Sidecar.enabled.is_(True))
        .all()
    )
    return [r[0] for r in rows]


def get_sidecar(db: Session, registered_id: str) -> Optional[Sidecar]:
    return (
        db.query(Sidecar)
        .filter(Sidecar.registered_id == registered_id)
        .first()
    )


def validate_sidecar_preference(db: Session, preference: Optional[str]) -> Optional[str]:
    """Validate a client-supplied sidecar preference.

    Accepts ``None``/``auto`` (returns None → automatic routing) or an exact
    registered id from the server-side registry. Rejects anything that is not
    a registry id — URL-shaped strings are never accepted (SSRF guard,
    Review Round 1 Finding 12). Returns the canonical registered id.
    """
    if preference is None or preference.strip().lower() in ("", "auto"):
        return None
    pref = preference.strip()
    if "://" in pref or "/" in pref or not pref.replace("-", "_").isalnum():
        from app.exceptions import ValidationException
        raise ValidationException(
            "sidecar_preference must be 'auto' or a registered sidecar id"
        )
    sidecar = get_sidecar(db, pref)
    if sidecar is None or not sidecar.enabled:
        from app.exceptions import ValidationException
        raise ValidationException(
            f"sidecar '{pref}' is not a registered sidecar"
        )
    return sidecar.registered_id


def _probe_sidecar(sidecar: Sidecar) -> SidecarTelemetry:
    """Probe one sidecar: health, served model, load, VRAM where available."""
    telemetry = SidecarTelemetry(
        registered_id=sidecar.registered_id,
        label=sidecar.label,
        base_url=sidecar.base_url,
        declared_model=sidecar.declared_model,
        capabilities=list(sidecar.capabilities or []),
        healthy=False,
    )
    parsed = urlparse(sidecar.base_url)

    try:
        # vLLM OpenAI-compatible models endpoint: authoritative served model.
        models_resp = requests.get(
            f"{sidecar.base_url.rstrip('/')}/v1/models",
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        if models_resp.status_code != 200:
            return telemetry
        models_payload = models_resp.json()
        telemetry.served_models = [
            m["id"]
            for m in models_payload.get("data", [])
            if isinstance(m, dict) and isinstance(m.get("id"), str)
        ]
        telemetry.healthy = True
    except Exception as exc:
        logger.warning("sidecar %s models probe failed: %s", sidecar.registered_id, exc)
        return telemetry

    # vllm-manager /status (port 8100) exposes VRAM/load when the sidecar is
    # the manager itself; /metrics (vLLM) exposes running/waiting when direct.
    try:
        status_url = f"{sidecar.base_url.rstrip('/')}/status"
        status_resp = requests.get(status_url, timeout=PROBE_TIMEOUT_SECONDS)
        if status_resp.status_code == 200:
            status = status_resp.json()
            if isinstance(status, dict):
                telemetry.vram_used_mib = status.get("vram_used_mib")
                telemetry.vram_total_mib = status.get("vram_total_mib")
                gpus = status.get("gpus") if isinstance(status.get("gpus"), list) else []
                if gpus:
                    telemetry.vram_used_mib = sum(
                        g.get("vram_used_mib") or 0 for g in gpus if isinstance(g, dict)
                    )
                    telemetry.vram_total_mib = sum(
                        g.get("vram_total_mib") or 0 for g in gpus if isinstance(g, dict)
                    )
    except Exception:
        pass

    try:
        metrics_url = f"{sidecar.base_url.rstrip('/')}/metrics"
        metrics_resp = requests.get(metrics_url, timeout=PROBE_TIMEOUT_SECONDS)
        if metrics_resp.status_code == 200:
            telemetry.running_requests, telemetry.waiting_requests = _parse_vllm_metrics(
                metrics_resp.text
            )
    except Exception:
        pass

    return telemetry


def _parse_vllm_metrics(body: str) -> tuple[int, int]:
    """Parse running/waiting request gauges from vLLM /metrics text."""
    running = 0
    waiting = 0
    for line in body.splitlines():
        if line.startswith("vllm:num_requests_running"):
            running = _first_metric_value(line)
        elif line.startswith("vllm:num_requests_waiting"):
            waiting = _first_metric_value(line)
    return running, waiting


def _first_metric_value(line: str) -> int:
    parts = line.split()
    for part in reversed(parts):
        try:
            return int(float(part))
        except ValueError:
            continue
    return 0


def inventory(db: Session) -> list[SidecarTelemetry]:
    """Live inventory of all enabled sidecars from the shared telemetry
    store (WP3-hotfix: read-through, so this is consistent across API and
    worker processes).

    Request paths call this without probing (Review Round 2 F7): the
    scheduler refreshes the store; stale telemetry fails closed for new
    allocations. Reserved-slot counts are re-read cheaply from the DB here
    (one indexed query, no network).
    """
    settings = get_settings().admission
    rows = db.query(Sidecar).filter(Sidecar.enabled.is_(True)).all()

    reserved_by_sidecar: dict[str, int] = {}
    for slot in (
        db.query(ResourceSlot)
        .filter(
            ResourceSlot.state.in_((SlotState.LEASED, SlotState.EXPIRED)),
        )
        .all()
    ):
        reserved_by_sidecar[slot.sidecar_id] = (
            reserved_by_sidecar.get(slot.sidecar_id, 0) + 1
        )

    result: list[SidecarTelemetry] = []
    for sidecar in rows:
        telemetry = cached_sidecar_telemetry(sidecar.registered_id)
        if telemetry is None:
            telemetry = SidecarTelemetry(
                registered_id=sidecar.registered_id,
                label=sidecar.label,
                base_url=sidecar.base_url,
                declared_model=sidecar.declared_model,
                capabilities=list(sidecar.capabilities or []),
                healthy=False,
                observed_at=0.0,  # never observed -> stale -> fail closed
            )
        telemetry.reserved_slots = reserved_by_sidecar.get(sidecar.registered_id, 0)
        telemetry.total_slots = settings.slots_per_sidecar
        result.append(telemetry)
    return result


def reconcile_slots(db: Session) -> int:
    """Provision ResourceSlot rows for enabled sidecars (Review Round 2 F3).

    Ensures each enabled sidecar has exactly ``SIDECAR_SLOTS`` slot rows.
    Existing rows (including leased/expired) are never deleted or mutated
    here; only missing rows are created. Returns the count created.
    """
    settings = get_settings().admission
    rows = db.query(Sidecar).filter(Sidecar.enabled.is_(True)).all()
    created = 0
    for sidecar in rows:
        existing = (
            db.query(ResourceSlot.slot_index)
            .filter(ResourceSlot.sidecar_id == sidecar.registered_id)
            .all()
        )
        existing_indices = {idx for (idx,) in existing}
        for slot_index in range(settings.slots_per_sidecar):
            if slot_index not in existing_indices:
                db.add(
                    ResourceSlot(
                        sidecar_id=sidecar.registered_id,
                        slot_index=slot_index,
                        enabled=True,
                    )
                )
                created += 1
    if created:
        db.commit()
        logger.info("reconciled %d sidecar slot row(s)", created)
    return created


def routed_sidecar(
    db: Session,
    telemetry_rows: Optional[list[SidecarTelemetry]] = None,
    *,
    preference: Optional[str] = None,
    capabilities: Iterable[str] = ("text",),
) -> Optional[SidecarTelemetry]:
    """Pick a sidecar for a new allocation.

    Rules (WP3): stale telemetry fails closed; declared capability must be
    met by the live probe (served model present + healthy); available slot
    capacity required; a user preference is honored only when the preferred
    sidecar is compatible and has capacity — otherwise the caller decides
    between queueing visibly or explicit fallback.
    """
    rows = telemetry_rows if telemetry_rows is not None else inventory(db)
    cap = set(capabilities)

    candidates = [
        t
        for t in rows
        if t.healthy
        and not t.stale
        and t.available_slots > 0
        and cap.issubset(set(t.capabilities))
        and t.served_models
    ]

    if preference:
        preferred = next((t for t in candidates if t.registered_id == preference), None)
        if preferred is not None:
            return preferred
        return None  # preferred unavailable → caller decides queue vs fallback

    # Deterministic preference: more available capacity, then less load.
    return min(
        candidates,
        key=lambda t: (-t.available_slots, t.running_requests, t.registered_id),
    ) if candidates else None


def load_sidecar_config(path: Optional[str] = None) -> list[dict]:
    """Load the operator-sidecar configuration file.

    The config file is operator-owned and non-secret. Shape:

        {"sidecars": [{"registered_id": "...", "label": "...",
                       "base_url": "...", "capabilities": [...],
                       "declared_model": "..."}]}

    Returns raw dicts; the caller persists them via the seed function.
    """
    # The committed default ships in a public repository, so it deliberately
    # describes placeholder hosts. Real deployments point SIDECAR_CONFIG_PATH at
    # a file kept outside the repo, which is where actual topology belongs.
    candidate = (
        path
        or os.getenv("SIDECAR_CONFIG_PATH")
        or Path(__file__).resolve().parent.parent / "core" / "sidecars.json"
    )
    p = Path(candidate)
    if not p.exists():
        return []
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("sidecar config unreadable: %s", exc)
        return []
    sidecars = payload.get("sidecars") if isinstance(payload, dict) else None
    if not isinstance(sidecars, list):
        return []
    return [s for s in sidecars if isinstance(s, dict)]


def seed_sidecars(db: Session, config_path: Optional[str] = None) -> int:
    """Idempotently seed/refresh the registry from operator configuration."""
    entries = load_sidecar_config(config_path)
    created = 0
    for entry in entries:
        registered_id = entry.get("registered_id")
        if not isinstance(registered_id, str) or not registered_id:
            continue
        existing = get_sidecar(db, registered_id)
        if existing is None:
            db.add(
                Sidecar(
                    registered_id=registered_id,
                    label=str(entry.get("label", registered_id))[:128],
                    base_url=str(entry.get("base_url", "")),
                    capabilities=list(entry.get("capabilities") or []),
                    declared_model=entry.get("declared_model"),
                    enabled=bool(entry.get("enabled", True)),
                )
            )
            created += 1
        else:
            existing.label = str(entry.get("label", existing.label))[:128]
            existing.base_url = str(entry.get("base_url", existing.base_url))
            existing.capabilities = list(entry.get("capabilities") or [])
            existing.declared_model = entry.get("declared_model")
            existing.enabled = bool(entry.get("enabled", True))
    if created or entries:
        db.commit()
    return created
