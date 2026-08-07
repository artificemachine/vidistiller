"""Regression test: the celery summarize task must use the shared
resolve_user_llm helper so fleet-model adoption reaches it.

Background: PR #167 extracted fleet/LLM resolution into
``app.services.llm_resolution`` and made the diagnostics endpoint adopt
the loaded fleet model. But the celery ``summarize_transcript_task`` body
still carried inline resolution logic that bypassed the helper — so the
production summarize call kept requesting a hardcoded model name. This
test pins the task to the shared resolver so the regression cannot recur
silently.
"""

import inspect


def test_summarize_transcript_task_uses_shared_resolver() -> None:
    """The celery task body must call resolve_user_llm.

    Static check rather than a full Celery run — exercises the task source
    enough to catch the regression without dragging in DB/job fixtures.
    """
    from app.tasks import summarize_transcript_task

    source = inspect.getsource(summarize_transcript_task)
    assert "resolve_user_llm" in source, (
        "summarize_transcript_task no longer calls resolve_user_llm — fleet "
        "adoption is bypassed."
    )
    assert "DEFAULT_MODELS.get(\"vllm\", \"qwen3-32b-awq\")" not in source, (
        "summarize_transcript_task still carries the pre-fix inline fallback "
        "to qwen3-32b-awq."
    )
    # The LLMService call must use the resolved model and not the old
    # `model_name` local (which no longer exists in this scope).
    assert "model_name=model_name" not in source, (
        "summarize_transcript_task still passes the stale `model_name` "
        "local into LLMService — must use the resolved model from "
        "resolve_user_llm."
    )
    assert "model_name=_resolved_model" in source, (
        "summarize_transcript_task should pass the resolved model into "
        "LLMService via _resolved_model."
    )


