"""WP3 acceptance: sidecar allowlisting/SSRF, inventory, and batched slide
classification quality on a fixed fixture.

SSRF/allowlist tests run on SQLite (authorization decisions). Inventory and
batch tests run against the real Postgres when available (fall back to
SQLite with registry rows seeded in-session where the code path permits).
"""

import pytest
from unittest.mock import MagicMock, patch

from app.core.config import get_settings
from app.services.sidecar import (
    get_sidecar,
    load_sidecar_config,
    registered_sidecar_ids,
    seed_sidecars,
    validate_sidecar_preference,
)
from app.exceptions import ValidationException


# ---------------------------------------------------------------------------
# Allowlisting / SSRF (WP3)
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_registry(test_db):
    """Seed two registered sidecars exactly like operator config would."""
    from app.db.models import Sidecar

    test_db.add_all([
        Sidecar(
            registered_id="primary",
            label="Primary",
            base_url="http://192.0.2.36:8000",
            capabilities=["text"],
            declared_model="qwen3.8-27b",
            enabled=True,
        ),
        Sidecar(
            registered_id="vision",
            label="Vision",
            base_url="http://192.0.2.10:8100",
            capabilities=["vision"],
            declared_model="qwen25-15b",
            enabled=True,
        ),
    ])
    test_db.commit()
    return test_db


def test_validate_accepts_registered_id(test_db, seeded_registry):
    assert validate_sidecar_preference(test_db, "primary") == "primary"
    assert validate_sidecar_preference(test_db, "auto") is None
    assert validate_sidecar_preference(test_db, None) is None
    assert validate_sidecar_preference(test_db, "") is None


def test_validate_rejects_url_shaped_values(test_db, seeded_registry):
    for bad in (
        "http://192.0.2.99:8000",
        "https://evil.example/sidecar",
        "primary/../evil",
        "192.0.2.36:8000",
        "primary?x=1",
    ):
        with pytest.raises(ValidationException):
            validate_sidecar_preference(test_db, bad)


def test_validate_rejects_unregistered_id(test_db, seeded_registry):
    with pytest.raises(ValidationException):
        validate_sidecar_preference(test_db, "not-a-registered-sidecar")


def test_validate_rejects_disabled_sidecar(test_db, seeded_registry):
    from app.db.models import Sidecar

    s = get_sidecar(test_db, "vision")
    s.enabled = False
    test_db.commit()
    with pytest.raises(ValidationException):
        validate_sidecar_preference(test_db, "vision")


def test_registered_ids_only_enabled(test_db, seeded_registry):
    assert set(registered_sidecar_ids(test_db)) == {"primary", "vision"}


def test_seed_sidecars_idempotent_from_config(test_db, tmp_path):
    cfg = tmp_path / "sidecars.json"
    cfg.write_text('{"sidecars": [{"registered_id": "primary", "label": "P", "base_url": "http://x:1", "capabilities": ["text"]}]}')
    assert seed_sidecars(test_db, str(cfg)) == 1
    assert seed_sidecars(test_db, str(cfg)) == 0  # refresh, not duplicate
    assert get_sidecar(test_db, "primary") is not None


# ---------------------------------------------------------------------------
# Batched slide classification quality (WP3)
# ---------------------------------------------------------------------------

class _FakeProvider:
    """Provider that answers batch prompts deterministically: items with the
    substring 'ADDED' are INCREMENTAL, everything else TRANSITION."""

    def __init__(self):
        self.calls = []

    def generate(self, prompt, model, timeout=30, max_tokens=1000):
        self.calls.append(prompt)
        if "Respond with exactly one line" in prompt:
            lines = []
            for line in prompt.splitlines():
                if line.startswith("[t_"):
                    item_id = line.split("]")[0][1:]
                    is_inc = "ADDED" in line
                    lines.append(f"{item_id}: {'INCREMENTAL' if is_inc else 'TRANSITION'}")
            return "\n".join(lines)
        # Single-item fallback prompt.
        return "INCREMENTAL" if "ADDED" in prompt else "TRANSITION"


def _ambiguous_pairs(n: int):
    pairs = []
    for i in range(n):
        before = f"slide {i // 3} content"
        after = before if i % 3 != 2 else f"{before} ADDED point {i}"
        pairs.append({
            "frame_index": 100 + i,
            "timestamp": 10.0 + i,
            "ssim": 0.87 if i % 3 != 2 else 0.99,  # 0.99 hits fast path
            "classification": "ambiguous",
            "ocr_text_before": before,
            "ocr_text_after": after,
        })
    return pairs


def _service_with_batch(batch_size: int):
    from app.services.slide_detection import SlideDetectionService

    svc = SlideDetectionService.__new__(SlideDetectionService)
    svc.slide_settings = MagicMock()
    svc.slide_settings.llm_model = "gemma4-31b-awq"
    svc.slide_settings.llm_timeout = 30
    svc.slide_settings.incremental_ssim_threshold = 0.95
    svc.slide_settings.llm_batch_size = batch_size
    svc.slide_settings.llm_batch_concurrency = 1
    return svc


def test_batched_classification_matches_sequential_on_fixed_fixture():
    """Batch and sequential must agree on every item of the same fixture."""
    sequential = _service_with_batch(1)
    batched = _service_with_batch(4)

    pairs_seq = _ambiguous_pairs(10)
    pairs_batch = _ambiguous_pairs(10)

    provider_seq = _FakeProvider()
    provider_batch = _FakeProvider()

    sequential.llm_ambiguity_classification(
        pairs_seq, provider=provider_seq, model="gemma4-31b-awq"
    )
    batched.llm_ambiguity_classification(
        pairs_batch, provider=provider_batch, model="gemma4-31b-awq"
    )

    for seq, bat in zip(pairs_seq, pairs_batch):
        assert seq["llm_classification"] == bat["llm_classification"], (
            f"item {seq['frame_index']}: {seq['llm_classification']} vs {bat['llm_classification']}"
        )

    # Batching must be strictly fewer LLM calls than sequential.
    assert len(provider_batch.calls) < len(provider_seq.calls)


def test_batched_retry_only_failed_items():
    """Items the batch response misses are retried sequentially; the rest
    are not re-called."""
    from app.services.slide_detection import SlideDetectionService

    svc = _service_with_batch(10)
    pairs = _ambiguous_pairs(5)

    class _DroppingProvider(_FakeProvider):
        def generate(self, prompt, model, timeout=30, max_tokens=1000):
            if "Respond with exactly one line" in prompt:
                # Drop every second item from the batch answer.
                answer = super().generate(prompt, model, timeout, max_tokens)
                lines = answer.splitlines()
                return "\n".join(lines[::2])
            return super().generate(prompt, model, timeout, max_tokens)

    provider = _DroppingProvider()
    svc.llm_ambiguity_classification(pairs, provider=provider, model="m")

    # Every item classified.
    assert all(p.get("llm_classification") in ("transition", "incremental") for p in pairs)
    # Retry calls are single-item prompts. Batch covers items 0,1,3,4 (item 2
    # is the 0.99 fast path); dropping even-indexed answer lines loses t_1 and
    # t_4 -> exactly 2 sequential retries.
    retries = [c for c in provider.calls if "Respond with exactly one line" not in c]
    assert len(retries) == 2


def test_batched_deterministic_ordering():
    """llm_classification keys map back to the right items by stable id."""
    svc = _service_with_batch(100)
    pairs = _ambiguous_pairs(6)
    provider = _FakeProvider()
    svc.llm_ambiguity_classification(pairs, provider=provider, model="m")
    for idx, pair in enumerate(pairs):
        assert pair["frame_index"] == 100 + idx
        assert pair["llm_classification"] in ("transition", "incremental")


def test_batch_provider_failure_falls_back_sequentially():
    """Whole-batch failure degrades to the sequential fallback, not data loss."""
    svc = _service_with_batch(4)
    pairs = _ambiguous_pairs(6)

    class _ExplodingProvider(_FakeProvider):
        def generate(self, prompt, model, timeout=30, max_tokens=1000):
            if "Respond with exactly one line" in prompt:
                raise RuntimeError("fleet unreachable")
            return super().generate(prompt, model, timeout, max_tokens)

    provider = _ExplodingProvider()
    svc.llm_ambiguity_classification(pairs, provider=provider, model="m")
    assert all(p.get("llm_classification") in ("transition", "incremental") for p in pairs)


# ---------------------------------------------------------------------------
# Inventory model identity (WP3)
# ---------------------------------------------------------------------------

def test_inventory_identity_comes_from_live_probe(test_db, seeded_registry):
    """The inventory model list reflects the served model, not the declared
    one; a sidecar whose probe fails is unhealthy (fail closed for new
    allocations). The cache is populated through the scheduler path
    (refresh_telemetry_cache) exactly as production does."""
    from app.services import sidecar as sidecar_mod
    from app.services.sidecar import inventory

    def _fake_probe(sidecar):
        from app.services.sidecar import SidecarTelemetry

        if sidecar.registered_id == "primary":
            return SidecarTelemetry(
                registered_id="primary",
                label=sidecar.label,
                base_url=sidecar.base_url,
                declared_model="qwen3.8-27b",
                capabilities=["text"],
                healthy=True,
                served_models=["qwen3.8-27b"],  # live truth: 3.8, not 3.6
            )
        return SidecarTelemetry(
            registered_id="vision",
            label=sidecar.label,
            base_url=sidecar.base_url,
            declared_model="qwen25-15b",
            capabilities=["vision"],
            healthy=False,  # probe failure
        )

    with patch.object(sidecar_mod, "_probe_sidecar", side_effect=_fake_probe):
        sidecar_mod.refresh_telemetry_cache(test_db)
        telemetry = inventory(test_db)
    by_id = {t.registered_id: t for t in telemetry}
    assert by_id["primary"].served_models == ["qwen3.8-27b"]
    assert by_id["vision"].healthy is False

    # Stale or unhealthy sidecars are not routable for new allocations.
    from app.services.sidecar import routed_sidecar

    chosen = routed_sidecar(test_db, telemetry, capabilities=["text"])
    assert chosen is not None and chosen.registered_id == "primary"
    chosen_vision = routed_sidecar(test_db, telemetry, capabilities=["vision"])
    assert chosen_vision is None  # unhealthy fails closed
