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
    """Live inventory of all enabled sidecars with reserved slot counts."""
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
        telemetry = _probe_sidecar(sidecar)
        telemetry.reserved_slots = reserved_by_sidecar.get(sidecar.registered_id, 0)
        telemetry.total_slots = settings.slots_per_sidecar
        result.append(telemetry)
    return result


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
    candidate = path or Path(__file__).resolve().parent.parent / "core" / "sidecars.json"
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
