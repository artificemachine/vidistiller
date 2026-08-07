"""Parity contract between backend and frontend default model tables.

Hardcoded last-resort model defaults live in three places that must agree:
``app.services.llm_providers.DEFAULT_MODELS``, ``app.services.llm_resolution.FALLBACK_MODEL``,
and the frontend's ``DEFAULT_MODELS`` map in ``frontend/app/settings/page.tsx``.
The frontend value is verified by grep at CI time (this test covers the
backend pair, since the frontend default is plain TypeScript with no
runtime test surface today).
"""

from app.services.llm_providers import DEFAULT_MODELS
from app.services.llm_resolution import FALLBACK_MODEL


def test_vllm_default_matches_fallback() -> None:
    """Last-resort vllm default is gemma4-31b everywhere.

    The fleet table in ``backend/app/routes/settings.py`` documents VM913's
    home model as gemma4-31b; the frontend settings map uses the same value.
    Backend ``DEFAULT_MODELS["vllm"]`` must equal the global fallback so
    that fleet-eviction and fleet-down paths converge on the same model.
    """
    assert DEFAULT_MODELS["vllm"] == "gemma4-31b"
    assert FALLBACK_MODEL == "gemma4-31b"
    assert DEFAULT_MODELS["vllm"] == FALLBACK_MODEL