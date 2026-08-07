"""Guard rails on dependency versions the CI security gate depends on.

Keeps a test-side floor on packages whose known CVEs only get caught by re-running
pip-audit; if the floor drifts, these tests fail before CI does and the cause is
the dependency resolution rather than a missed advisory.
"""

from importlib import metadata

import pytest


def _parse_version(pkg: str) -> tuple[int, ...]:
    raw = metadata.version(pkg)
    parts: list[int] = []
    for token in raw.split("."):
        digits = ""
        for ch in token:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            parts.append(int(digits))
        else:
            break
    if not parts:
        pytest.skip(f"{pkg} has no parseable version: {raw!r}")
    return tuple(parts)


def test_cryptography_at_least_50() -> None:
    """pip-audit PYSEC-2026-3552 is fixed in cryptography 50.0.0.

    The backend ships `cryptography>=50.0.0` so fresh installs clear the gate
    regardless of cache or resolution timing. This test fails if a future bump
    re-introduces the vulnerable range — the same condition CI's pip-audit
    would flag.
    """
    assert _parse_version("cryptography") >= (50, 0, 0)