"""Performance regression guard for local fleet candidate ranking."""

from time import perf_counter

from app.services.llm_fleet import FleetObservation, rank_candidates


def test_ranking_one_thousand_compatible_models_stays_subsecond():
    candidates = [
        FleetObservation(
            node=f"node-{index}",
            model=f"model-{index}",
            base_url="http://fleet.invalid:8000",
            capabilities=frozenset({"text"}),
            priority=index % 10,
            context_tokens=32_768,
            reliability=0.95,
            declared_latency_ms=100,
            observed_latency_ms=100,
            healthy=True,
        )
        for index in range(1_000)
    ]

    started = perf_counter()
    ranked = rank_candidates(candidates)
    elapsed = perf_counter() - started

    assert len(ranked) == 1_000
    assert elapsed < 1.0
