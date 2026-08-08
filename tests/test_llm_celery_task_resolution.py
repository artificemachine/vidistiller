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


def test_summarize_task_does_not_mark_failed_when_document_exists() -> None:
    """A failed redelivery must not overwrite a successfully saved summary.

    Celery redelivers long tasks (Redis visibility timeout) so two
    executions of the same task can race on one job row. The exception
    handler must check whether a summary document already exists before
    setting summarize_status=failed — otherwise the second delivery
    clobbers the first one's completed status.
    """
    from app.tasks import summarize_transcript_task

    source = inspect.getsource(summarize_transcript_task)
    assert 'job.summarize_status == "completed"' in source, (
        "The exception handler must not mark the job failed when the "
        "status is already completed (concurrent redelivery raced ahead)."
    )
    assert "Document.format == \"summary\"" in source, (
        "The exception handler must check for an existing summary document "
        "before marking the job failed."
    )
    # Staleness guard at task start: another delivery's request id claims the job.
    assert "job.celery_task_id != self.request.id" in source, (
        "The task must skip when another delivery already claimed the job "
        "(different celery_task_id) — otherwise force-revoked or redelivered "
        "tasks race on the same job row."
    )
    # force=true bypasses the claim check (the route revoked + cleared the id).
    assert "not force and job.celery_task_id" in source, (
        "A force-dispatched task must bypass the staleness claim check — "
        "the route revokes the previous task and clears celery_task_id, so "
        "a stale id must not block a legitimate force re-run."
    )


