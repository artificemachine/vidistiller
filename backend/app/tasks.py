"""
Celery Task Definitions

Defines the Celery application and background tasks for processing
YouTube video transcripts.
"""

import logging
import os
import re
import threading
from math import ceil

from sqlalchemy import text

from celery import Celery
from app.core.config import TRANSCRIPT_CONFIDENCE_CAPTIONS, TRANSCRIPT_CONFIDENCE_WHISPER, get_settings

logger = logging.getLogger(__name__)


def _has_persisted_steps(job) -> bool:
    """Avoid treating test doubles and legacy jobs as the new step workflow."""
    return isinstance(getattr(job, "steps", None), list) and bool(job.steps)


def required_context_tokens_for_transcript(
    transcript_text: str, output_reserve_tokens: int = 4_000
) -> int:
    """Estimate the input context deterministically before task routing."""
    return ceil(len(transcript_text) / 4) + output_reserve_tokens


def _add_log(db, job_id: int, message: str, level: str = "info", step: str | None = None) -> None:
    """Persist a log entry for a job. Commits immediately so the frontend sees it in real-time."""
    try:
        from app.db.models import JobLog, LogLevel
        level_enum = LogLevel(level)
        log_entry = JobLog(job_id=job_id, level=level_enum, message=message[:1024], step=step)
        db.add(log_entry)
        db.commit()
    except Exception as _log_exc:
        logger.debug("Failed to write job log: %s", _log_exc)
        try:
            db.rollback()
        except Exception:
            pass

# ==============================================================================
# CELERY APP
# ==============================================================================

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "tasks",
    broker=redis_url,
    backend=redis_url,
)

# WP2: explicit broker visibility/redelivery semantics. The visibility
# timeout must exceed the longest bounded task (slide detection) so a
# still-running delivery is not redelivered while active; the task-level
# time limits bound the worst case. Late-ack + prefetch 1 and the existing
# claim-step idempotency protections are preserved.
# Must EXCEED the hard task limit (7200) plus grace so an active long
# delivery is never redelivered while running (Review Round 2 P7-NEW-10).
_broker_visibility_seconds = int(os.getenv("CELERY_VISIBILITY_TIMEOUT", "7800"))

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={
        "visibility_timeout": _broker_visibility_seconds,
    },
    # Explicit per-task hard limits (bounded processing, no runaway jobs).
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", "7200")),
    task_soft_time_limit=int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "6600")),
    # WP2: align default CPU concurrency with the two-CPU container quota.
    worker_concurrency=int(os.getenv("CELERY_WORKER_CONCURRENCY", "2")),
)


def _mint_exec_uuid() -> str:
    """Unique per-incarnation execution UUID (fencing, Review Round 1 Finding 5).

    Never use the Celery request.id as a fencing token: it is preserved
    across redelivery, so a stale delivery could otherwise re-validate an
    expired execution. Callers mint one UUID per worker incarnation and
    carry it on claims, heartbeats, releases and completions.
    """
    import uuid as _uuid

    return str(_uuid.uuid4())


def _test_barrier(db, job_id: int, stage: str, claimed: bool) -> None:
    """Deterministic worker-kill barrier for the redelivery test (F12).

    Enabled only when VIDISTILLER_TEST_BARRIER_DIR is set (test env). After
    a step claim, the worker writes a marker file recording the claim and
    blocks until the ``release`` file appears or BARRIER_TIMEOUT (default
    120s) elapses. The test kills the worker while blocked, then starts a
    fresh worker; the redelivered message must NOT re-run the step.
    """
    barrier_dir = os.environ.get("VIDISTILLER_TEST_BARRIER_DIR")
    if not barrier_dir:
        return
    if not claimed:
        # Fenced-out redelivery: never block — it must skip and finish.
        return
    import time as _time
    from pathlib import Path as _Path

    barrier = _Path(barrier_dir)
    marker = barrier / f"claimed-{job_id}-{stage}"
    release = barrier / f"release-{job_id}-{stage}"
    with marker.open("w") as fh:
        fh.write(f"claimed={claimed} at={_time.time()}\n")
    timeout = float(os.environ.get("VIDISTILLER_TEST_BARRIER_TIMEOUT", "120"))
    deadline = _time.time() + timeout
    while not release.exists():
        if _time.time() > deadline:
            logger.warning("test barrier timed out for job %s stage %s", job_id, stage)
            return
        _time.sleep(0.2)


def _finish_admission_for_job(db, job_id: int, *, failed: bool = False) -> bool:
    """Release admission counters exactly once for a terminal job (WP2).

    P27-NEW-63: errors PROPAGATE (no swallow/rollback inside) so callers
    never acknowledge a terminal state or revoke workers without a durable
    DB fence. Returns True when this call performed the release.
    """
    from app.services.admission import finish_job_admission

    return finish_job_admission(db, job_id, failed=failed)


def _mark_stage_delivered(db, job_id: int, stage: str) -> None:
    """Mark the newest outbox row for (job, stage) delivered (WP2).

    ``transcribe`` (canonical step name) and ``transcript`` (outbox/task
    name) are the same stage (P14-NEW-32).
    """
    try:
        from app.db.models import TaskOutbox
        from app.services.admission import mark_outbox_delivered

        stage_aliases = {stage}
        if stage in ("transcribe", "transcript"):
            stage_aliases = {"transcribe", "transcript"}
        row = (
            db.query(TaskOutbox)
            .filter(
                TaskOutbox.job_id == job_id,
                TaskOutbox.stage.in_(tuple(stage_aliases)),
                TaskOutbox.state.in_(("pending", "published", "publishing")),
            )
            .order_by(TaskOutbox.id.desc())
            .first()
        )
        if row is not None:
            mark_outbox_delivered(db, row.id)
    except Exception as exc:
        logger.debug("outbox delivered mark failed for job %s: %s", job_id, exc)
        db.rollback()


def _lease_slot_for_job(db, job, exec_uuid: str, telemetry_snapshot=None):
    """Acquire a sidecar slot for a job under its fencing token (WP2).

    ``telemetry_snapshot`` is the precomputed result of
    prefetch_sidecar_telemetry() taken by the caller BEFORE any DB write
    (WP3-hotfix: lock-held code must never initiate Redis I/O itself).
    """
    from app.services.lease import acquire_slot

    preference = getattr(job, "sidecar_preference", None)
    if preference and preference != "auto":
        return acquire_slot(
            db, job,
            exec_uuid=exec_uuid,
            preferred_sidecar=preference,
            telemetry_snapshot=telemetry_snapshot,
        )
    return acquire_slot(
        db, job, exec_uuid=exec_uuid, telemetry_snapshot=telemetry_snapshot
    )


def _resolve_provider_for_slot(db, slot, telemetry_snapshot=None):
    """Build the LLM provider bound to the LEASED sidecar (Review Round 2 F6).

    Uses the registry endpoint of the leased sidecar plus the model the
    sidecar ACTUALLY serves (live telemetry). There is deliberately NO
    declared-model fallback: if live telemetry is absent or serves nothing,
    the caller treats it as no capacity (fail closed — Review Round 2
    N3/N8).
    """
    from app.services.llm_providers import build_provider
    from app.services.sidecar import (
        get_sidecar,
        prefetch_sidecar_telemetry,
    )

    # WP3-hotfix: consume the caller's precomputed telemetry snapshot (taken
    # BEFORE any DB write). If none was supplied (standalone callers/tests),
    # prefetch here — but note lock-held production paths always pass one so
    # no network I/O occurs under a DB transaction/row lock (Review Round 2
    # F7 invariant). The snapshot (not a read-through getter) is what binds
    # the provider to the leased sidecar's live served model across the
    # process boundary.
    telemetry_snapshot = (
        telemetry_snapshot if telemetry_snapshot is not None
        else prefetch_sidecar_telemetry(db)
    )

    sidecar = get_sidecar(db, slot.sidecar_id)
    if sidecar is None:
        logger.warning("leased sidecar %s missing from registry", slot.sidecar_id)
        return None, None
    telemetry = telemetry_snapshot.get(slot.sidecar_id)
    if telemetry is None or not telemetry.healthy or telemetry.stale:
        logger.warning(
            "leased sidecar %s has no fresh healthy telemetry; treating as no capacity",
            slot.sidecar_id,
        )
        return None, None
    served = telemetry.served_models or []
    if not served:
        logger.warning("leased sidecar %s serves no model; treating as no capacity", slot.sidecar_id)
        return None, None
    model = served[0]
    try:
        provider = build_provider(
            "vllm",
            api_key=None,
            ollama_base_url=sidecar.base_url,
        )
    except Exception as exc:
        logger.warning("could not build provider for leased sidecar %s: %s", slot.sidecar_id, exc)
        return None, None
    return provider, model


def _release_slot_if_held(db, slot, exec_uuid: str) -> None:
    """Release a held slot exactly once (idempotent under fencing triple)."""
    if slot is None:
        return
    try:
        from app.services.lease import release_slot

        release_slot(db, slot.id, exec_uuid, slot.generation)
    except Exception as exc:
        logger.warning("slot release failed for slot %s: %s", slot.id, exc)
        db.rollback()


class SidecarCapacityExhausted(Exception):
    """Raised when no sidecar slot is available for external LLM work.

    The task catches this, records a visible queue reason on the admission
    row, and retries with a bounded countdown instead of overcommitting the
    GPU or failing ambiguously (Review Round 2 F3/F6).
    """


def _delete_document_durably(db, doc_id: int) -> bool:
    """Delete a document in its own committed transaction (P11-NEW-25).

    The document was already committed by save_document; deleting in a fresh
    committed transaction guarantees the stale artifact cannot survive a
    rollback of the surrounding scope.
    """
    try:
        db.execute(text("DELETE FROM documents WHERE id = :doc_id"), {"doc_id": doc_id})
        db.commit()
        return True
    except Exception as exc:
        logger.warning("durable document delete failed for doc %s: %s", doc_id, exc)
        db.rollback()
        return False


def _fail_summarize_owned(
    db, job_id: int, task_id: str, generation: int | None, reason: str,
    step_token: str | None = None, step_claimed: bool = False,
) -> bool:
    """Fail the summarize stage only when this delivery still owns it
    (P23-NEW-55): the conditional update requires the task id, the expected
    status and (when known) the generation, so a stale worker (superseded by
    a newer force) can never clobber the newer delivery's state. Returns
    True when the write applied.

    P24-NEW-59: the JobStep claim token is the per-incarnation exec_uuid,
    never the Celery task id — pass ``step_token`` (exec_uuid) and only fail
    the step when this delivery actually claimed it; otherwise the step
    stays PENDING, which is retryable.
    """
    try:
        if generation is not None:
            res = db.execute(
                text(
                    "UPDATE processing_jobs SET summarize_status = 'failed', "
                    "celery_task_id = NULL "
                    "WHERE id = :job_id AND celery_task_id = :task_id "
                    "AND summarize_status = 'processing' "
                    "AND force_generation = :gen"
                ),
                {"job_id": job_id, "task_id": task_id, "gen": generation},
            )
        else:
            res = db.execute(
                text(
                    "UPDATE processing_jobs SET summarize_status = 'failed', "
                    "celery_task_id = NULL "
                    "WHERE id = :job_id AND celery_task_id = :task_id "
                    "AND summarize_status = 'processing'"
                ),
                {"job_id": job_id, "task_id": task_id},
            )
        if res.rowcount == 1:
            if step_claimed and step_token:
                from app.services.job_steps import fail_step

                fail_step(db, job_id, "summarize", step_token, reason)
            db.commit()
            return True
        db.rollback()
        return False
    except Exception as exc:
        logger.warning("owned summarize fail failed for job %s: %s", job_id, exc)
        db.rollback()
        return False


def _force_generation_still_valid(db, job_id: int, force_generation: int) -> bool:
    """Revalidate a force generation under the job-row lock (P9-NEW-14).

    Called immediately before destructive/final writes so a newer force
    request (which bumps the generation with UPDATE...RETURNING and the
    row lock) fences this delivery out before it deletes or replaces the
    summary document.
    """
    try:
        if db.bind.dialect.name == "postgresql":
            db.execute(
                text(
                    "SELECT id FROM processing_jobs WHERE id = :job_id FOR UPDATE"
                ),
                {"job_id": job_id},
            )
        row = db.execute(
            text("SELECT force_generation FROM processing_jobs WHERE id = :job_id"),
            {"job_id": job_id},
        ).first()
        return row is not None and int(row[0]) == force_generation
    except Exception:
        db.rollback()
        return False


def _release_summarize_claim(db, job_id: int, exec_uuid: str) -> None:
    try:
        from app.services.job_steps import fail_step

        fail_step(db, job_id, "summarize", exec_uuid, "queued on capacity")
        db.commit()
    except Exception as exc:
        logger.warning("summarize claim release on capacity failed: %s", exc)
        db.rollback()


def _record_capacity_queue_reason(db, job) -> None:
    """Record the visible queue reason on the admission row (Review Round 2 F6)."""
    try:
        if db.bind.dialect.name == "postgresql":
            db.execute(
                text(
                    "UPDATE job_admissions SET queue_reason = :reason, "
                    "updated_at = now() WHERE job_id = :job_id AND state = 'admitted'"
                ),
                {
                    "reason": "no sidecar slot available (queued on capacity)",
                    "job_id": job.id,
                },
            )
        else:
            db.execute(
                text(
                    "UPDATE job_admissions SET queue_reason = :reason "
                    "WHERE job_id = :job_id AND state = 'admitted'"
                ),
                {
                    "reason": "no sidecar slot available (queued on capacity)",
                    "job_id": job.id,
                },
            )
        db.commit()
    except Exception as exc:
        logger.warning("could not record capacity queue reason for job %s: %s", job.id, exc)
        db.rollback()


def _terminalize_capacity_exhausted(db, job_id: int) -> str:
    """Terminalize a job whose capacity retries are exhausted (NEW-6).

    Returns a tri-state disposition (P11-NEW-21):
    - "done"       — this call terminalized the job (or its stage).
    - "owned"      — another incarnation owns a running step; callers must
                     perform NO mutation (P8-NEW-11).
    - "completed"  — the conversion is already COMPLETED (summarize-only
                     context); callers fail just the summarize stage.
    - "already"    — job already terminal; nothing to do.

    Celery retries are finite; after the last capacity retry the job must not
    stay admitted/processing with counters held forever.
    """
    try:
        from app.db.models import JobStep, JobStepStatus, ProcessingJob, ProcessingStatus

        # P10-NEW-18: acquire the JOB-row lock FIRST, then inspect claims and
        # terminalize, so our claim inspection happens under a fresh
        # post-lock snapshot that cannot race a concurrently committing
        # claim. The conditional NOT EXISTS UPDATE below remains as the
        # atomic fail gate.
        job_status_observed = None
        if db.bind.dialect.name == "postgresql":
            job_row = db.execute(
                text(
                    "SELECT status FROM processing_jobs WHERE id = :job_id FOR UPDATE"
                ),
                {"job_id": job_id},
            ).first()
            if job_row is None:
                return "already"
            job_status_observed = job_row[0]
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if job is None:
            return "already"
        if job_status_observed is None:
            job_status_observed = job.status.value
        # Guard FIRST (P11-NEW-21): any step running under a claim we do NOT
        # own means another incarnation is actively processing — never
        # terminalize, regardless of job status (a completed conversion can
        # still have an active summarize step).
        running_steps = (
            db.query(JobStep)
            .filter(JobStep.job_id == job_id, JobStep.status == JobStepStatus.RUNNING)
            .all()
        )
        for step in running_steps:
            if step.claim_token is not None:
                logger.warning(
                    "capacity exhaustion for job %s skipped: step %s is owned by another incarnation",
                    job_id, step.name,
                )
                return "owned"
        # THEN terminal-state disposition (dialect-safe: derived from the
        # loaded ORM row on SQLite, from the locked row on PostgreSQL).
        if job_status_observed == "completed":
            return "completed"  # summarize-only context (P11-NEW-21)
        if job_status_observed not in ("pending", "processing"):
            return "already"  # terminal (failed/cancelled) or gone
        if job.status in (
            ProcessingStatus.PENDING, ProcessingStatus.PROCESSING,
        ):
            # Atomic against a concurrent claim (P9-NEW-17): the job-fail is
            # a single conditional UPDATE that re-checks, in the same
            # statement, that no running claim exists. If another incarnation
            # claims between our read above and this UPDATE, the NOT EXISTS
            # fails, rowcount is 0, and we skip without failing the job.
            if db.bind.dialect.name == "postgresql":
                result = db.execute(
                    text(
                        "UPDATE processing_jobs SET status = 'failed', "
                        "error_message = 'No sidecar capacity available after retries', "
                        "celery_task_id = NULL, slide_status = CASE "
                        "WHEN processing_mode = 'slide_aware' THEN 'failed' "
                        "ELSE slide_status END, updated_at = now() "
                        "WHERE id = :job_id AND status IN ('pending', 'processing') "
                        "AND NOT EXISTS (SELECT 1 FROM job_steps js "
                        "WHERE js.job_id = processing_jobs.id "
                        "AND js.status = 'running' AND js.claim_token IS NOT NULL)"
                    ),
                    {"job_id": job_id},
                )
            else:
                result = db.execute(
                    text(
                        "UPDATE processing_jobs SET status = 'failed', "
                        "error_message = 'No sidecar capacity available after retries', "
                        "celery_task_id = NULL "
                        "WHERE id = :job_id AND status IN ('pending', 'processing') "
                        "AND NOT EXISTS (SELECT 1 FROM job_steps js "
                        "WHERE js.job_id = processing_jobs.id "
                        "AND js.status = 'running' AND js.claim_token IS NOT NULL)"
                    ),
                    {"job_id": job_id},
                )
            if result.rowcount != 1:
                # A claim won the race (or the job is no longer active).
                db.rollback()
                logger.warning(
                    "capacity exhaustion terminalize for job %s skipped: concurrent claim or non-active job",
                    job_id,
                )
                return "owned"
            _finish_admission_for_job(db, job_id, failed=True)
        db.commit()
        return "done"
    except Exception as exc:
        logger.warning("capacity-exhausted terminalize failed for job %s: %s", job_id, exc)
        db.rollback()
        return "owned"  # conservative: do not mutate on error


# ==============================================================================
# TRANSCRIPT TASK HELPERS
# ==============================================================================

def _fetch_platform_captions(
    db, job_id: int, video_service, video_url: str, language: str = "en"
) -> tuple[str | None, str]:
    """
    Fetch captions using the appropriate provider for the detected platform.

    For YouTube: uses YouTubeCaptionProvider (native API with timestamps).
    For all other sources: uses YtdlpCaptionProvider (subtitle download).
    Returns (text, detected_language) or (None, "en") when unavailable.

    ``language`` is the preferred caption language (ISO 639-1). It matters for
    auto-dubbed videos, which expose a caption track per dub language; without
    it the provider could return a dub instead of the original.
    """
    from app.core.source_type import SourceType
    from app.services.caption_providers import YouTubeCaptionProvider, YtdlpCaptionProvider

    source_type, source_id = video_service.resolve(video_url)

    if source_type == SourceType.YOUTUBE:
        _add_log(db, job_id, "Fetching YouTube native captions...", "info", "youtube_captions")
        provider = YouTubeCaptionProvider()
        step = "youtube_captions"
    else:
        _add_log(db, job_id, f"Fetching subtitles via yt-dlp ({source_type.value})...", "info", "yt_dlp_captions")
        provider = YtdlpCaptionProvider()
        step = "yt_dlp_captions"

    text, lang = provider.fetch(video_url, source_id, language)

    if text:
        _add_log(db, job_id, f"Captions retrieved ({len(text)} chars, lang={lang})", "info", step)
        return text, lang

    # For YouTube, also try yt-dlp as a secondary fallback before Whisper
    if source_type == SourceType.YOUTUBE:
        _add_log(db, job_id, "YouTube native captions unavailable, trying yt-dlp...", "warning", "yt_dlp_captions")
        text, lang = YtdlpCaptionProvider().fetch(video_url, source_id, language)
        if text:
            _add_log(db, job_id, f"yt-dlp captions retrieved ({len(text)} chars)", "info", "yt_dlp_captions")
            return text, lang

    _add_log(db, job_id, "No captions available, will use Whisper", "warning", step)
    return None, "en"


def _transcribe_audio(db, job_id: int, job, video_service, video_url: str) -> tuple[str, str]:
    """
    Download audio and transcribe via Ollama Whisper.

    Returns (transcript_text, detected_language) on success.
    Raises on failure WITHOUT setting the job status: the outer task's
    exception handler owns terminalization, which happens only at true
    retry exhaustion (P22-NEW-51 / P23-NEW-57). Marking FAILED here would
    make the authorized final retry skip at the entry guard.
    """
    from app.db.models import ProcessingStatus

    _add_log(db, job_id, "Falling back to Ollama Whisper transcription...", "info", "whisper")
    try:
        from app.services.transcript import TranscriptService

        logger.info("No captions available, falling back to Ollama Whisper...")
        audio_path, _ = video_service.download_audio(video_url)
        ts = TranscriptService()
        result = ts.transcribe_audio(audio_path)
        transcript_text = result.get("full_text", "")
        detected_language = result.get("language", "en")
        _add_log(db, job_id, f"Ollama transcription complete ({len(transcript_text)} chars)", "info", "whisper")
        logger.info(f"Ollama transcription complete ({len(transcript_text)} chars)")
        return transcript_text, detected_language
    except Exception as e:
        _add_log(db, job_id, f"Ollama transcription failed: {e}", "error", "whisper")
        logger.error(f"Ollama transcription failed: {e}")
        # P22-NEW-51: do NOT mark the job FAILED here — the outer exception
        # handler owns terminalization (only at true exhaustion, via a
        # conditional UPDATE). Marking FAILED on every audio failure would
        # make the authorized final retry skip at the entry guard.
        raise


def _embed_chapters(transcript_text: str, chapters: list) -> str:
    """
    Inject YouTube chapter headers as markdown into the transcript.

    Returns the enriched transcript text.
    """
    lines = transcript_text.split("\n")
    enriched_lines = []
    ch_idx = 0
    for line in lines:
        ts_match = re.match(r"\[(\d{2}):(\d{2}):(\d{2})\]", line)
        if ts_match:
            line_seconds = int(ts_match[1]) * 3600 + int(ts_match[2]) * 60 + int(ts_match[3])
            while ch_idx < len(chapters) and chapters[ch_idx]["start_time"] <= line_seconds:
                ch = chapters[ch_idx]
                h = int(ch["start_time"] // 3600)
                m = int((ch["start_time"] % 3600) // 60)
                s = int(ch["start_time"] % 60)
                enriched_lines.append(f"## [{h:02d}:{m:02d}:{s:02d}] {ch['title']}")
                ch_idx += 1
        enriched_lines.append(line)
    while ch_idx < len(chapters):
        ch = chapters[ch_idx]
        h = int(ch["start_time"] // 3600)
        m = int((ch["start_time"] % 3600) // 60)
        s = int(ch["start_time"] % 60)
        enriched_lines.append(f"## [{h:02d}:{m:02d}:{s:02d}] {ch['title']}")
        ch_idx += 1
    return "\n".join(enriched_lines)


def _save_video_record(db, job_id: int, job, video_url: str, metadata: dict) -> None:
    """
    Persist a Video record so the title appears in Recent Conversions.

    composite unique(video_id, job_id) means each job always gets its own row.
    """
    from app.db.models import Video

    if not metadata.get("video_id"):
        return

    try:
        video_record = Video(
            job_id=job.id,
            url=video_url,
            source_type=metadata.get("source_type"),
            video_id=metadata["video_id"],
            title=metadata.get("title", "Unknown"),
            description=metadata.get("description"),
            duration=metadata.get("duration"),
            thumbnail_url=metadata.get("thumbnail_url"),
            channel_name=metadata.get("channel"),
            view_count=metadata.get("view_count"),
        )
        db.add(video_record)
        db.flush()
        _add_log(db, job_id, f"Video record saved: {metadata.get('title', '')}", "info", "save_video")
    except Exception as e:
        db.rollback()
        logger.warning(f"Could not persist Video record: {e}")


def _save_transcript_and_segments(
    db, job_id: int, job, transcript_text: str, source: str, detected_language: str
):
    """
    Persist the Transcript row and its TranscriptSegments to the database.

    Returns the created Transcript object.
    """
    from app.db.models import Transcript, TranscriptSegment

    transcript = Transcript(
        job_id=job.id,
        full_text=transcript_text,
        language=detected_language,
        source=source,
        confidence_score=TRANSCRIPT_CONFIDENCE_CAPTIONS if source in ("youtube_captions", "yt_dlp_captions") else TRANSCRIPT_CONFIDENCE_WHISPER,
    )
    db.add(transcript)
    db.flush()
    _add_log(db, job_id, f"Transcript saved (source: {source}, language: {detected_language})", "info", "save_transcript")

    _add_log(db, job_id, "Segmenting transcript...", "info", "segmentation")
    try:
        from app.services.transcript import TranscriptService
        ts = TranscriptService()
        segments = ts.segment_transcript(transcript_text)
        for seg in segments:
            segment = TranscriptSegment(
                transcript_id=transcript.id,
                text=seg["text"],
                start_time=seg["start_time"],
                end_time=seg["end_time"],
                speaker=seg.get("speaker"),
                confidence_score=seg.get("confidence_score", 0.95),
                sequence=seg["sequence"],
            )
            db.add(segment)
    except Exception as e:
        _add_log(db, job_id, f"Segmentation failed (non-fatal): {e}", "warning", "segmentation")
        logger.warning(f"Segmentation failed (non-fatal): {e}")

    return transcript


# ==============================================================================
# TRANSCRIPT TASK
# ==============================================================================

@celery_app.task(bind=True, name="process_video_download", max_retries=2)
def process_video_download(self, job_id: int):
    """Retry only the durable video-download stage without re-transcribing."""
    from pathlib import Path

    from app.db.models import ProcessingJob, ProcessingMode, ProcessingStatus
    from app.db.session import SessionLocal
    from app.services.job_steps import claim_step, complete_step, fail_step
    from app.services.video import VideoService

    exec_uuid = _mint_exec_uuid()
    db = SessionLocal()
    try:
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if job is None or not job.video_url:
            return {"job_id": job_id, "status": "skipped"}
        # Terminal guard (Review Round 2 NEW-9/P9-NEW-16): never resurrect
        # cancelled or failed jobs via redriven download work. COMPLETED jobs
        # are allowed through: the restore-drill flow deliberately retries a
        # failed download step on a completed job to resume its pending
        # dependent step (see the dependent-step re-dispatch below).
        if job.status in (ProcessingStatus.CANCELLED, ProcessingStatus.FAILED):
            return {"job_id": job_id, "status": "skipped", "reason": "job is terminal"}
        claimed = claim_step(db, job.id, "download", exec_uuid)
        if claimed is None:
            return {"job_id": job_id, "status": "skipped"}
        # P10-NEW-20: commit the claim promptly so the job-row lock is not
        # held across the network/file work below (which would block
        # cancellation and terminalization for the download duration).
        db.commit()
        data_dir = get_settings().storage.data_dir or str(
            Path(__file__).resolve().parent.parent / "data"
        )
        output_path = str(Path(data_dir) / "videos" / job.job_id)
        try:
            video_path, _ = VideoService().download_video(
                job.video_url, output_path=output_path, quality="720p"
            )
        except Exception as exc:
            fail_step(db, job.id, "download", exec_uuid, str(exc))
            db.commit()
            raise self.retry(exc=exc, countdown=30)
        job.video_file_path = video_path
        # P11-NEW-23: the claim was committed before the slow network/file
        # work; revalidate the job's terminal state under a fresh lock so a
        # concurrent cancellation cannot be resurrected by this worker.
        # P12-NEW-27: the dependent dispatch is gated on the download step
        # completion actually succeeding under our claim token.
        if db.bind.dialect.name == "postgresql":
            job_row = db.execute(
                text(
                    "SELECT status FROM processing_jobs WHERE id = :job_id FOR UPDATE"
                ),
                {"job_id": job_id},
            ).first()
            if job_row is None or job_row[0] in ("cancelled", "failed"):
                fail_step(db, job.id, "download", exec_uuid, "job terminalized during download")
                db.commit()
                return {"job_id": job_id, "status": "skipped", "reason": "job is terminal"}
        step_done = complete_step(db, job.id, "download", exec_uuid, {"path": Path(video_path).name})
        if not step_done:
            # We lost the download claim (reaped or taken over): never
            # mutate job state or dispatch dependent work on a claim we do
            # not own (P12-NEW-27).
            db.rollback()
            return {"job_id": job_id, "status": "skipped", "reason": "download claim lost"}
        dependent_step = (
            "slides"
            if job.processing_mode == ProcessingMode.SLIDE_AWARE.value
            else "snapshots"
        )
        pending_dependent_step = next(
            (step for step in job.steps if step.name == dependent_step and step.status.value == "pending"),
            None,
        )
        if pending_dependent_step is not None:
            # A download may be retried after the transcript task has already
            # completed the job. Restore processing state before the dependent
            # task runs; slide processing rejects completed jobs as stale work.
            job.status = ProcessingStatus.PROCESSING
            job.celery_task_id = None
        db.commit()
        if pending_dependent_step is not None:
            if dependent_step == "slides":
                process_slides.delay(job.id)
            else:
                process_snapshots.delay(job.id)
            return {"job_id": job_id, "status": "dependent_step_queued", "step": dependent_step}
        return {"job_id": job_id, "status": "completed"}
    finally:
        db.close()

@celery_app.task(bind=True, name="process_transcript", max_retries=2)
def process_transcript(self, job_id: int):
    """
    Process a YouTube video transcript.

    Strategy: Try YouTube captions first (fast, no Ollama needed).
    If unavailable, fall back to downloading audio and using Ollama Whisper.

    Args:
        job_id: Database ID of the ProcessingJob
    """
    from app.db.session import SessionLocal
    from app.db.models import ProcessingJob, ProcessingMode, ProcessingStatus
    from app.services.job_steps import claim_step, complete_step, fail_step
    from app.services.video import VideoService

    # Per-incarnation execution UUID (Review Round 2 F1): step claims are
    # keyed on THIS token, never on the Celery request.id — a redelivered
    # message retains request.id but gets a fresh exec_uuid, so it cannot
    # re-claim a step the previous incarnation still owns.
    exec_uuid = _mint_exec_uuid()
    # P28-NEW-66: initialize exception-handler state BEFORE the main try —
    # an early final-attempt failure must not hit UnboundLocalError in the
    # exhaustion handler (which would prevent terminalization).
    transcribe_claim = None
    db = SessionLocal()
    try:
        # 1. Load job
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found")
            return {"error": f"Job {job_id} not found"}

        # Idempotency guard. task_acks_late=True means a worker killed after
        # finishing but before acking gets the same job redelivered. Reprocessing
        # a completed job would overwrite its transcript and re-run the LLM, so
        # skip anything already in a terminal state. FAILED is also terminal
        # for redeliveries past max_retries (P9-NEW-16): a retried attempt
        # (retries < max) may proceed — the retry path below re-enters
        # PROCESSING — but a redelivery after final exhaustion must not
        # resurrect an unadmitted job.
        if job.status in (ProcessingStatus.COMPLETED, ProcessingStatus.CANCELLED):
            logger.info(
                "Job %s already %s; skipping duplicate delivery", job_id, job.status.value
            )
            return {"job_id": job_id, "status": job.status.value, "skipped": True}
        if (
            job.status == ProcessingStatus.FAILED
            and self.request.retries >= self.max_retries
        ):
            # P22-NEW-51/P25-NEW-60: distinguish an AUTHORIZED final retry
            # (admission positively ADMITTED) from a terminal redelivery
            # (admission released, queued, or absent). Only positively
            # admitted retries run — the exhaustion handler then releases
            # admission.
            from app.db.models import AdmissionState, JobAdmission

            admission = db.get(JobAdmission, job.id)
            admission_held = (
                admission is not None
                and admission.state == AdmissionState.ADMITTED
            )
            if not admission_held:
                logger.info(
                    "Job %s failed after max retries; skipping late redelivery", job_id
                )
                return {"job_id": job_id, "status": "failed", "skipped": True}

        # Staleness guard against redelivered executions while a delivery is
        # still actively running: video download + Whisper fallback
        # transcription can legitimately run past Redis' default broker
        # visibility timeout on slow hardware, so a still-running delivery
        # can get redelivered and picked up by another worker before it
        # finishes. Without this, every redelivery unconditionally
        # overwrites celery_task_id and restarts the whole pipeline from
        # scratch -- the exact bug found live in process_slides on
        # 2026-08-12 (see incident_log.md), which had no such guard either.
        # The exec_uuid claims below additionally fence the step level.
        if job.celery_task_id and job.celery_task_id != self.request.id:
            logger.info(
                "Job %s already processing under task %s, skipping duplicate delivery %s",
                job_id, job.celery_task_id, self.request.id,
            )
            return {"job_id": job_id, "status": "skipped", "reason": "another delivery is active"}

        video_url = job.video_url
        if not video_url:
            _add_log(db, job_id, "No video URL provided", "error", "init")
            job.status = ProcessingStatus.FAILED
            job.error_message = "No video URL provided"
            _finish_admission_for_job(db, job_id, failed=True)
            db.commit()
            return {"error": "No video URL"}

        # 2. Set status to PROCESSING, store Celery task ID for cancellation
        # P20-NEW-42: a conditional UPDATE — if a cancellation/force won the
        # job-row lock first (status now CANCELLED/FAILED), this worker's
        # stale write must not resurrect the job or install an uncaptured
        # task id; it skips instead. FAILED is allowed for authorized retries
        # whenever admission is STILL HELD (P24-NEW-58): the entry guard
        # already rejected terminal redeliveries whose admission was
        # released, so a failed job reaching this update is an authorized
        # retry — including the final attempt at retries == max_retries.
        # P22-NEW-53: exclusive task-ID claim — the predicate requires an
        # empty/self-owned id so two deliveries cannot both install.
        claimed_start = db.execute(
            text(
                "UPDATE processing_jobs SET status = 'processing', "
                "celery_task_id = :task_id "
                "WHERE id = :job_id AND (celery_task_id IS NULL "
                "OR celery_task_id = :task_id) "
                "AND (status IN ('pending', 'processing') "
                "OR (status = 'failed' AND EXISTS (SELECT 1 FROM job_admissions ja "
                "WHERE ja.job_id = processing_jobs.id "
                "AND ja.state = 'admitted')))"
            ),
            {
                "job_id": job_id,
                "task_id": self.request.id,
            },
        )
        if claimed_start.rowcount != 1:
            db.rollback()
            return {"job_id": job_id, "status": "skipped", "reason": "job is terminal or claimed"}
        # P22-NEW-52: reflect the raw install in the ORM so later clears are
        # not no-ops (expire_on_commit=False keeps the stale value otherwise).
        db.refresh(job, ["celery_task_id", "status"])
        db.commit()
        _add_log(db, job_id, f"Job started: {video_url}", "info", "init")
        logger.info(f"Processing transcript for job {job_id}: {video_url}")
        _mark_stage_delivered(db, job_id, "transcript")

        video_service = VideoService()
        steps_enabled = bool(job.steps)
        if _has_persisted_steps(job):
            from app.services.job_steps import claim_step

            transcribe_claim = (
                claim_step(db, job.id, "transcribe", exec_uuid)
                if steps_enabled
                else None
            )
            if steps_enabled and transcribe_claim is None:
                return {"job_id": job_id, "status": "skipped", "reason": "transcribe step is not retryable"}
            # Durable claim: commit so a worker kill leaves a RUNNING claim
            # that fences the redelivery (Review Round 2 F12).
            db.commit()

        # Fault-injection barrier (tests only): when VIDISTILLER_TEST_BARRIER
        # is set, the worker records the claim and blocks until the barrier
        # file appears or the timeout elapses. Lets the redelivery test kill
        # the worker mid-execution deterministically (Review Round 2 F12).
        _test_barrier(db, job_id, "transcribe", transcribe_claim is not None)

        # 3. Try platform-native captions first, then yt-dlp subtitles
        transcript_text = None
        source = "yt_dlp_captions"
        detected_language = "en"

        preferred_language = job.caption_language or "en"
        transcript_text, detected_language = _fetch_platform_captions(
            db, job_id, video_service, video_url, preferred_language
        )

        # Determine the source label based on what was resolved
        if transcript_text:
            from app.core.source_type import SourceType
            source_type, _ = video_service.resolve(video_url)
            source = "youtube_captions" if source_type == SourceType.YOUTUBE else "yt_dlp_captions"

        # 4. Fallback: download audio and transcribe via Ollama
        if not transcript_text:
            source = "whisper_local"
            transcript_text, detected_language = _transcribe_audio(db, job_id, job, video_service, video_url)

        if not transcript_text or not transcript_text.strip():
            _add_log(db, job_id, "No transcript could be generated", "error", "save_transcript")
            job.status = ProcessingStatus.FAILED
            job.error_message = "No transcript could be generated"
            if transcribe_claim:
                fail_step(db, job.id, "transcribe", exec_uuid, "No transcript could be generated")
            _finish_admission_for_job(db, job_id, failed=True)
            db.commit()
            return {"error": "Empty transcript"}

        # 5. Embed chapters as markdown headers (sourced from yt-dlp for any platform)
        metadata = {}
        try:
            metadata = video_service.get_video_metadata(video_url)
            chapters = sorted(metadata.get("chapters", []), key=lambda c: c["start_time"])
        except Exception:
            chapters = []

        if chapters:
            transcript_text = _embed_chapters(transcript_text, chapters)
            _add_log(db, job_id, f"Injected {len(chapters)} chapter headers", "info", "chapters")

        # 5b. Persist Video record so title appears in Recent Conversions
        _save_video_record(db, job_id, job, video_url, metadata)

        # 6. Save transcript to DB and segment it
        _save_transcript_and_segments(db, job_id, job, transcript_text, source, detected_language)
        if transcribe_claim:
            complete_step(
                db,
                job.id,
                "transcribe",
                exec_uuid,
                {"source": source, "language": detected_language, "characters": len(transcript_text)},
            )

        # 7. Download video for snapshot capture (non-fatal)
        download_claim = (
            claim_step(db, job.id, "download", exec_uuid)
            if steps_enabled
            else None
        )
        if download_claim:
            # P10-NEW-20: commit the claim so the job lock is not held
            # across the download network/file work.
            db.commit()
        if not steps_enabled or download_claim:
            _add_log(db, job_id, "Downloading video for snapshots...", "info", "video_download")
            try:
                from pathlib import Path as _Path
                _data_dir = get_settings().storage.data_dir or str(_Path(__file__).resolve().parent.parent / "data")
                videos_dir = str(_Path(_data_dir) / "videos" / job.job_id)
                video_path, _ = video_service.download_video(
                    video_url, output_path=videos_dir, quality="720p",
                )
                job.video_file_path = video_path
                if download_claim:
                    # P11-NEW-23: revalidate terminal state after the slow
                    # download before completing the step or dispatching.
                    # P12-NEW-27: gate on the step completion result — a
                    # lost claim must never dispatch dependent work.
                    download_lost = False
                    if db.bind.dialect.name == "postgresql":
                        job_row = db.execute(
                            text(
                                "SELECT status FROM processing_jobs WHERE id = :job_id FOR UPDATE"
                            ),
                            {"job_id": job_id},
                        ).first()
                        if job_row is None or job_row[0] in ("cancelled", "failed"):
                            fail_step(db, job.id, "download", exec_uuid, "job terminalized during download")
                            db.commit()
                            return {"status": "skipped", "reason": "job is terminal"}
                    if not complete_step(db, job.id, "download", exec_uuid, {"path": _Path(video_path).name}):
                        download_lost = True
                    if download_lost:
                        db.rollback()
                        _add_log(db, job_id, "Download claim lost; not dispatching dependent work", "warning", "video_download")
                        return {"status": "skipped", "reason": "download claim lost"}
                logger.info(f"Video downloaded for job {job_id}: {video_path}")
            except Exception as e:
                if download_claim:
                    fail_step(db, job.id, "download", exec_uuid, str(e))
                _add_log(db, job_id, f"Video download failed (non-fatal): {e}", "warning", "video_download")
                logger.warning(f"Video download failed (non-fatal): {e}")

        # 9. If slide_aware mode and video downloaded, dispatch slide processing
        if job.processing_mode == ProcessingMode.SLIDE_AWARE.value and job.video_file_path:
            _add_log(db, job_id, "Dispatching slide detection pipeline...", "info", "slide_dispatch")
            job.celery_task_id = None
            db.commit()
            process_slides.delay(job_id)
            logger.info(f"Job {job_id}: transcript done, slide detection dispatched")
            return {"status": "slide_processing", "source": source, "length": len(transcript_text)}

        if steps_enabled and job.video_file_path:
            snapshot_step = next(step for step in job.steps if step.name == "snapshots")
            if snapshot_step.status.value == "pending":
                _add_log(db, job_id, "Dispatching snapshot extraction...", "info", "snapshot_dispatch")
                job.celery_task_id = None
                db.commit()
                process_snapshots.delay(job_id)
                return {"status": "snapshot_processing", "source": source, "length": len(transcript_text)}

        # 10. Mark job as completed, clear Celery task ID. Terminal state and
        # admission release commit together (Review Round 2 N5). Guarded: a
        # cancellation that committed while the transcript/download work ran
        # must not be overwritten (P11-NEW-23).
        if db.bind.dialect.name == "postgresql":
            job_row = db.execute(
                text(
                    "SELECT status FROM processing_jobs WHERE id = :job_id FOR UPDATE"
                ),
                {"job_id": job_id},
            ).first()
            if job_row is not None and job_row[0] in ("cancelled", "failed"):
                db.rollback()
                return {"job_id": job_id, "status": "skipped", "reason": "job is terminal"}
        job.status = ProcessingStatus.COMPLETED
        job.celery_task_id = None
        _finish_admission_for_job(db, job_id)
        db.commit()
        _add_log(db, job_id, "Job completed successfully", "info", "complete")

        logger.info(f"Job {job_id} completed: transcript saved ({len(transcript_text)} chars, source={source})")
        return {"status": "completed", "source": source, "length": len(transcript_text)}

    except Exception as e:
        db.rollback()
        _add_log(db, job_id, f"Job failed unexpectedly: {e}", "error", "fatal")
        logger.error(f"Job {job_id} failed unexpectedly: {e}")
        # P21-NEW-46/P21-NEW-49: intermediate retries must NOT set FAILED —
        # the retried incarnation needs to re-enter processing (the start
        # update accepts pending/processing), and a concurrent cancellation
        # must never be overwritten with FAILED. Only final exhaustion
        # terminalizes, and only via a conditional update.
        exhausted = self.request.retries >= self.max_retries
        if not exhausted:
            # Intermediate retry: release the claim, then retry (P22-NEW-51).
            try:
                if transcribe_claim is not None:
                    from app.services.job_steps import fail_step

                    fail_step(db, job.id, "transcribe", exec_uuid, f"retrying: {str(e)[:300]}")
                    db.commit()
            except Exception:
                db.rollback()
            db.commit()
            raise self.retry(exc=e, countdown=30)

        # P27-NEW-62: FINAL exhaustion — the job FAILED write, the step
        # failure, the admission transition and the counter decrement commit
        # in ONE transaction, so a crash can never strand FAILED+ADMITTED
        # (which the redelivery guard would treat as an authorized retry).
        try:
            job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            if job is not None:
                db.execute(
                    text(
                        "UPDATE processing_jobs SET status = 'failed', "
                        "error_message = :msg "
                        "WHERE id = :job_id AND status IN ('pending', 'processing')"
                    ),
                    {"job_id": job_id, "msg": f"Unexpected error: {str(e)[:500]}"},
                )
                if transcribe_claim is not None:
                    from app.services.job_steps import fail_step

                    fail_step(db, job.id, "transcribe", exec_uuid, f"exhausted: {str(e)[:300]}")
                _finish_admission_for_job(db, job_id, failed=True)
                db.commit()
        except Exception as exc:
            db.rollback()
            logger.error("final exhaustion terminalization failed for job %s: %s", job_id, exc)
            # Do NOT retry past the limit; surface the failure.
            raise self.retry(exc=e, countdown=30)
        raise self.retry(exc=e, countdown=30)
    finally:
        db.close()


# ==============================================================================
# HELPERS
# ==============================================================================

def _is_cancelled(db, job_id: int) -> bool:
    """Check if a summarization has been cancelled (fresh DB read)."""
    from app.db.models import ProcessingJob
    db.expire_all()
    job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
    if not job:
        return True
    return job.summarize_status != "processing"


def _is_slide_cancelled(db, job_id: int) -> bool:
    """Check if a slide processing task has been cancelled (fresh DB read).

    Returns True only when the job status is CANCELLED — the signal set by
    the cancel API route. FAILED is a genuine pipeline error and must NOT
    trigger the cancel path.
    """
    from app.db.models import ProcessingJob, ProcessingStatus
    db.expire_all()
    job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
    if not job:
        return True
    return job.status == ProcessingStatus.CANCELLED


# ==============================================================================
# FLEET RESOLVER — find which VM has a given model loaded
# ==============================================================================

from app.services.llm_resolution import FLEET_VMS as _FLEET_VMS  # noqa: E402


def _resolve_fleet_url(model_name: str) -> str | None:
    """
    Query all vLLM fleet VMs to find which one has *model_name* loaded.

    Thin wrapper over the shared resolver (app.services.llm_resolution) so
    jobs and diagnostics use one code path. Returns the vLLM URL of the
    first match, or None if no VM has it.
    """
    from app.services.llm_resolution import resolve_fleet_url

    url, _label = resolve_fleet_url(model_name)
    return url


def _resolve_job_llm_config(db, job, task, required_context_tokens: int = 0):
    """Resolve one job owner's model against a task-specific contract."""
    from app.db.models import User
    from app.services.llm_resolution import resolve_task_llm

    owner = db.query(User).filter(User.id == job.user_id).first() if job.user_id else None
    return resolve_task_llm(owner, task, required_context_tokens)


def _resolve_job_llm(db, job, task=None, required_context_tokens: int = 0):
    """
    Resolve the LLM provider + model for a job's owner (fleet-aware).

    Mirrors the resolution summarization uses so background tasks share one code
    path: honour the owner's configured provider/model, default to the vLLM fleet,
    and pick the VM that actually has the model loaded.

    Returns:
        (provider, model_name) — provider is an LLMProvider, or (None, None) if
        a provider could not be built.
    """
    from app.services.llm_providers import build_provider
    from app.services.llm_fleet import LLMTask

    resolved = _resolve_job_llm_config(
        db,
        job,
        task or LLMTask.SLIDE_CLASSIFICATION,
        required_context_tokens,
    )

    try:
        provider = build_provider(
            resolved.provider_name,
            api_key=resolved.api_key,
            ollama_base_url=resolved.base_url or "http://localhost:11434",
        )
    except Exception as e:
        logger.warning(f"Could not build LLM provider for job {job.id}: {e}")
        return None, None

    return provider, resolved.model


# ==============================================================================
# SUMMARIZE TRANSCRIPT TASK
# ==============================================================================

@celery_app.task(bind=True, name="summarize_transcript", max_retries=3)
def summarize_transcript_task(self, job_id: int, force: bool = False, force_generation: int | None = None):
    """
    Summarize a job's transcript in the background via LLM.

    Args:
        job_id: Database ID of the ProcessingJob
        force: If true, delete existing summary before regenerating
        force_generation: Monotonic generation minted by the force route;
            the takeover only applies when it still matches, so concurrent
            force requests cannot clobber each other (Review Round 2 NEW-7).
    """
    from pathlib import Path
    from app.db.session import SessionLocal
    from app.db.models import ProcessingJob, Document
    from app.services.llm import LLMService, CancelledException

    exec_uuid = _mint_exec_uuid()
    db = SessionLocal()
    summarize_claimed = False
    slot = None
    heartbeat_stop = None
    heartbeat_thread = None
    try:
        from app.db.models import User
        from app.core.crypto import decrypt_field

        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if not job:
            logger.error(f"Summarize: Job {job_id} not found")
            return {"error": f"Job {job_id} not found"}

        # Staleness guard against concurrent deliveries: Celery can hold two
        # executions of the same task (or a fresh task and a redelivered one)
        # for the same job — long runs exceed Redis' visibility timeout, and
        # force=true revokes + re-dispatches. If another delivery already
        # claimed this job (different request id) or finished it, this
        # delivery must not start a second generation or clobber the status.
        # force=true bypasses the claim check: the route revoked the previous
        # task and cleared celery_task_id, so this delivery is the authorized
        # one even if a stale id lingers in the row.
        if not force and job.celery_task_id and job.celery_task_id != self.request.id:
            logger.info(
                "Summarize: job %s already processing under task %s, skipping duplicate delivery %s",
                job_id, job.celery_task_id, self.request.id,
            )
            return {"status": "skipped", "reason": "another delivery is active"}
        if job.summarize_status == "completed" and not force:
            logger.info("Summarize: job %s already completed, skipping", job_id)
            return {"status": "skipped", "reason": "already completed"}
        # P13-NEW-29: a reaped/forced delivery must not resurrect a cancelled
        # summarization (user cancel sets summarize_status='failed' and clears
        # the task id). Forced work only proceeds from a 'processing' state.
        if force and job.summarize_status == "failed":
            logger.info(
                "Summarize: job %s summarization was cancelled (status=failed); skipping forced recovery",
                job_id,
            )
            return {"status": "skipped", "reason": "summarization cancelled"}
        if job.summarize_status not in (None, "processing", "failed") and not force:
            logger.info("Summarize: job %s summarize_status=%s; skipping", job_id, job.summarize_status)
            return {"status": "skipped", "reason": f"summarize_status={job.summarize_status}"}

        # Force-generation fence (Review Round 2 NEW-7/P8-NEW-12): for a
        # forced delivery, the generation check is ATOMIC with the state
        # mutation — we take the job-row FOR UPDATE lock (the force route
        # mints generations with UPDATE...RETURNING, which also locks the
        # row), so a newer force mint can neither slip between the check and
        # the commit nor run concurrently with it. On PostgreSQL this
        # serializes; on SQLite the writer lock provides the same effect.
        if force_generation is not None:
            if db.bind.dialect.name == "postgresql":
                db.execute(
                    text(
                        "SELECT id FROM processing_jobs WHERE id = :job_id FOR UPDATE"
                    ),
                    {"job_id": job_id},
                )
            db.refresh(job, ["force_generation", "summarize_status"])
            if (job.force_generation or 0) != force_generation:
                logger.info(
                    "Summarize: job %s force generation %s is stale (current %s); skipping",
                    job_id, force_generation, job.force_generation,
                )
                return {"status": "skipped", "reason": "superseded by a newer force request"}
            # P14-NEW-31: re-check the authorized status UNDER the lock — a
            # cancellation that committed between our earlier read and this
            # lock must not be overwritten by forced recovery.
            if job.summarize_status == "failed":
                logger.info(
                    "Summarize: job %s summarization cancelled before forced start; skipping",
                    job_id,
                )
                return {"status": "skipped", "reason": "summarization cancelled"}

        # Store Celery task ID for cancellation. P20-NEW-42/P21-NEW-47:
        # conditional UPDATE fenced on the generation observed at startup
        # for ALL workers (not only force): if a force minted a newer
        # generation while this worker waited, its install affects zero rows
        # and it skips. Dialect-safe rowcount check (P21-NEW-50).
        observed_gen = getattr(job, "force_generation", 0) or 0
        # P22-NEW-53: exclusive task-ID claim — empty/self-owned id required.
        installed = db.execute(
            text(
                "UPDATE processing_jobs SET celery_task_id = :task_id, "
                "summarize_status = 'processing' "
                "WHERE id = :job_id AND (celery_task_id IS NULL "
                "OR celery_task_id = :task_id) "
                "AND summarize_status IN ('processing', 'pending') "
                "AND force_generation = :gen"
            ),
            {"job_id": job_id, "task_id": self.request.id, "gen": observed_gen},
        )
        if installed.rowcount != 1:
            db.rollback()
            return {"status": "skipped", "reason": "job superseded or terminal"}
        # P22-NEW-52: reflect the raw install in the ORM.
        db.refresh(job, ["celery_task_id", "summarize_status"])
        db.commit()
        _add_log(db, job_id, "Starting LLM summarization...", "info", "summarize")
        # WP3-hotfix: prefetch the telemetry snapshot BEFORE the outbox
        # delivered-UPDATE below — the snapshot is then passed through
        # acquire_slot/_resolve_provider_for_slot so no Redis I/O occurs
        # while the outbox row (or any later row) is locked.
        from app.services.sidecar import prefetch_sidecar_telemetry

        telemetry_snapshot = prefetch_sidecar_telemetry(db)
        _mark_stage_delivered(db, job_id, "summarize")

        # WP2/WP3 (Review Round 2 F3/F6/N3): summarization performs external
        # LLM work and therefore REQUIRES a sidecar slot lease under this
        # incarnation's exec_uuid. No slot -> visible capacity reason and a
        # bounded retry, never unleased sidecar work.
        slot = _lease_slot_for_job(db, job, exec_uuid, telemetry_snapshot)
        if slot is None:
            _record_capacity_queue_reason(db, job)
            logger.info(
                "Summarize: job %s has no sidecar slot; retrying on capacity", job_id
            )
            raise SidecarCapacityExhausted(job_id)
        _add_log(
            db, job_id,
            f"Acquired sidecar slot {slot.sidecar_id}#{slot.slot_index} (gen {slot.generation})",
            "info", "summarize_lease",
        )

        lease_lost = threading.Event()
        heartbeat_stop = threading.Event()

        def _heartbeat_loop() -> None:
            from app.db.session import SessionLocal as _SL
            from app.services.lease import heartbeat_slot

            interval = get_settings().admission.heartbeat_interval_seconds
            while not heartbeat_stop.wait(interval):
                try:
                    hb_db = _SL()
                    try:
                        ok = heartbeat_slot(
                            hb_db, slot.id, exec_uuid, slot.generation
                        )
                        hb_db.commit()
                        if not ok:
                            logger.error(
                                "Slot %s heartbeat rejected (stale fence); stopping further sidecar work",
                                slot.id,
                            )
                            lease_lost.set()
                            heartbeat_stop.set()
                    finally:
                        hb_db.close()
                except Exception as exc:
                    logger.warning("slot heartbeat failed: %s", exc)

        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop, name=f"summ-hb-{job_id}", daemon=True
        )
        heartbeat_thread.start()

        # Step claim comes AFTER the lease so a no-capacity retry never holds
        # a claim owned by a dead incarnation (Review Round 2 F1/N1). For
        # force deliveries, revalidate the generation under the job lock at
        # the claim point too (P9-NEW-14) — a newer force minted during the
        # lease wait must fence this delivery out.
        if _has_persisted_steps(job):
            from app.services.job_steps import claim_step

            if force_generation is not None:
                if not _force_generation_still_valid(db, job.id, force_generation):
                    _release_slot_if_held(db, slot, exec_uuid)
                    db.commit()
                    return {"status": "skipped", "reason": "superseded by a newer force request"}

            summarize_claimed = claim_step(
                db, job.id, "summarize", exec_uuid
            ) is not None
            if not summarize_claimed and not force:
                # Lost the claim to another incarnation; release the lease.
                _release_slot_if_held(db, slot, exec_uuid)
                db.commit()
                return {"status": "skipped", "reason": "summarize step is not retryable"}
            if not summarize_claimed and force:
                # Force takeover: the route fenced and revoked the previous
                # task before dispatching, so taking over the RUNNING claim
                # is authorized (Review Round 2 N1). Rowcount-checked so a
                # concurrent claimer cannot be clobbered; accepts both a
                # RUNNING step and a COMPLETED step (force regeneration).
                # When a force_generation was minted, it must still match the
                # job's current generation (Review Round 2 NEW-7) — a newer
                # concurrent force bumps it and fences this takeover out.
                gen_guard = ""
                gen_params: dict = {"token": exec_uuid, "job_id": job.id}
                if force_generation is not None:
                    # The generation lives on processing_jobs, not job_steps
                    # (Review Round 2 NEW-7): use a correlated subquery.
                    gen_guard = (
                        "AND EXISTS (SELECT 1 FROM processing_jobs pj "
                        "WHERE pj.id = job_steps.job_id "
                        "AND pj.force_generation = :gen)"
                    )
                    gen_params["gen"] = force_generation
                if db.bind.dialect.name == "postgresql":
                    taken = db.execute(
                        text(
                            "UPDATE job_steps SET status = 'running', claim_token = :token, "
                            "started_at = now(), attempt = attempt + 1, finished_at = NULL, "
                            "error_message = NULL "
                            "WHERE job_id = :job_id AND name = 'summarize' "
                            "AND status IN ('running', 'completed') " + gen_guard
                        ),
                        gen_params,
                    )
                else:
                    from datetime import UTC, datetime as _dt

                    gen_params["now"] = _dt.now(UTC).replace(tzinfo=None)
                    taken = db.execute(
                        text(
                            "UPDATE job_steps SET status = 'running', claim_token = :token, "
                            "started_at = :now, attempt = attempt + 1, finished_at = NULL, "
                            "error_message = NULL "
                            "WHERE job_id = :job_id AND name = 'summarize' "
                            "AND status IN ('running', 'completed') " + gen_guard
                        ),
                        gen_params,
                    )
                db.commit()
                summarize_claimed = taken.rowcount == 1
                if not summarize_claimed:
                    # Zero-row takeover: another incarnation owns the step or
                    # it is missing. Do NOT proceed without the claim — abort
                    # and release the slot (Review Round 2 N3).
                    logger.warning(
                        "Summarize: force takeover of step for job %s affected 0 rows; aborting",
                        job.id,
                    )
                    raise SidecarCapacityExhausted(job_id)
            else:
                # P10-NEW-20: commit the claim promptly so the job-row lock
                # is NOT held across the LLM call (which would block
                # cancellation, force minting and terminalization for the
                # whole request). Generation/terminal state is revalidated
                # before the final writes.
                db.commit()

        # Read the owner preference only for language selection. The concrete
        # endpoint is resolved after the transcript length is known so context
        # is a hard routing filter.
        owner = db.query(User).filter(User.id == job.user_id).first() if job.user_id else None

        if not job.transcripts:
            # P23-NEW-55/P24-NEW-59: fail only if this delivery still owns
            # the stage; the step claim token is the exec_uuid and only
            # applies when claimed (pre-claim exits leave it PENDING).
            _fail_summarize_owned(
                db, job.id, self.request.id, force_generation,
                "No transcript available",
                step_token=exec_uuid, step_claimed=summarize_claimed,
            )
            _add_log(db, job_id, "No transcript available for summarization", "error", "summarize")
            return {"error": "No transcript"}

        transcript_text = job.transcripts[0].full_text
        detected_lang = job.transcripts[0].language or "en"
        # Use user's preferred summary output language, fall back to transcript language
        language = (owner.summary_language if owner and owner.summary_language else None) or detected_lang
        title = job.videos[0].title if job.videos else "Video Summary"

        from app.services.llm_fleet import LLMTask
        from app.services.llm_providers import build_provider

        # WP3 (Review Round 2 F6/N3): bind EVERY provider built here to the
        # LEASED sidecar's registry endpoint + live served model. The slot's
        # sidecar is the capacity we hold; there is no generic fallback.
        from app.services.sidecar import get_sidecar

        leased_sidecar = get_sidecar(db, slot.sidecar_id)
        if leased_sidecar is None:  # registry row removed mid-flight: abort
            logger.error("Summarize: leased sidecar %s missing from registry", slot.sidecar_id)
            _release_summarize_claim(db, job_id, exec_uuid)
            raise SidecarCapacityExhausted(job_id)
        provider, _model = _resolve_provider_for_slot(db, slot, telemetry_snapshot)
        if provider is None:
            logger.error(
                "Summarize: could not build provider for leased sidecar %s", slot.sidecar_id
            )
            # Release the claim we took so the capacity retry can reclaim it
            # (Review Round 2 N6).
            _release_summarize_claim(db, job_id, exec_uuid)
            raise SidecarCapacityExhausted(job_id)
        provider_name = "vllm"
        _resolved_model = _model
        ollama_url = leased_sidecar.base_url
        api_key = None

        # Build snapshot image URLs
        _data_dir = get_settings().storage.data_dir or str(Path(__file__).resolve().parent.parent / "data")
        snapshots_base = Path(_data_dir) / "snapshots"
        snapshot_dicts = []
        for snap in sorted(job.snapshots, key=lambda s: s.timestamp):
            image_url = ""
            try:
                relative = Path(snap.file_path).relative_to(snapshots_base)
                image_url = f"/static/snapshots/{relative}"
            except (ValueError, TypeError):
                pass
            snapshot_dicts.append({
                "timestamp": snap.timestamp,
                "image_url": image_url,
                "file_path": snap.file_path,
            })

        if not snapshot_dicts and job.slides:
            slides_base = Path(_data_dir) / "slides"
            for slide in sorted(job.slides, key=lambda s: s.start_timestamp):
                image_url = ""
                try:
                    if slide.final_frame_path:
                        relative = Path(slide.final_frame_path).relative_to(slides_base)
                        image_url = f"/static/slides/{relative}"
                except (ValueError, TypeError):
                    pass
                if image_url:
                    snapshot_dicts.append({
                        "timestamp": slide.start_timestamp,
                        "image_url": image_url,
                        "file_path": slide.final_frame_path,
                    })


        # Delete old summary if force re-generating. Revalidate the force
        # generation under the job-row lock BEFORE the destructive write
        # (P9-NEW-14): a newer force mints a fresh generation and fences this
        # delivery out.
        if force_generation is not None:
            if not _force_generation_still_valid(db, job.id, force_generation):
                logger.info(
                    "Summarize: job %s force generation superseded before document replacement; aborting",
                    job_id,
                )
                _release_summarize_claim(db, job_id, exec_uuid)
                return {"status": "skipped", "reason": "superseded by a newer force request"}
        if force:
            db.query(Document).filter(
                Document.job_id == job.id, Document.format == "summary"
            ).delete()
            db.commit()

        vision_provider = None
        vision_model = None
        if snapshot_dicts:
            try:
                # WP3 (Review Round 2 N3): vision work also runs on the
                # leased sidecar — no separate unleased lane.
                vision_provider = provider
                vision_model = _resolved_model
            except Exception as exc:
                _add_log(
                    db,
                    job_id,
                    f"No compatible vision model; snapshot descriptions skipped: {exc}",
                    "warning",
                    "summarize",
                )

        # Generate summary via LLM with explicit text and vision routes, all
        # bound to the LEASED sidecar (Review Round 2 N3).
        llm = LLMService(
            provider_name=provider_name,
            model_name=_resolved_model,
            api_key=api_key,
            ollama_base_url=ollama_url,
            vision_provider=vision_provider,
            vision_model=vision_model,
            use_default_vision_provider=not bool(snapshot_dicts),
        )
        summary_content = llm.summarize_transcript_sections(
            transcript_text, snapshot_dicts, language=language,
            title=title, video_url=job.video_url,
            source_type=job.source_type or "",
            cancel_check=lambda: _is_cancelled(db, job_id) or lease_lost.is_set(),
        )

        # Persist document. For force deliveries, revalidate the generation
        # once more under the job lock before the final write (P9-NEW-14):
        # a newer force that minted during the LLM call must win.
        if force_generation is not None:
            if not _force_generation_still_valid(db, job.id, force_generation):
                logger.info(
                    "Summarize: job %s force generation superseded before final save; aborting",
                    job_id,
                )
                _release_summarize_claim(db, job_id, exec_uuid)
                return {"status": "skipped", "reason": "superseded by a newer force request"}
        doc = llm.save_document(db, job.id, title, summary_content, "summary")

        # P10-NEW-19: the generation fence must cover the FINAL status and
        # step writes, not just the document insert. save_document commits
        # internally (releasing the job lock), so revalidate once more under
        # a fresh lock before marking summarization completed; if a newer
        # force minted during the save, delete the just-written document and
        # let the newer delivery win.
        if force_generation is not None:
            if not _force_generation_still_valid(db, job.id, force_generation):
                logger.info(
                    "Summarize: job %s force generation superseded after document save; discarding",
                    job_id,
                )
                cleanup_ok = True
                try:
                    db.query(Document).filter(Document.id == doc.id).delete()
                    db.commit()
                except Exception:
                    db.rollback()
                    cleanup_ok = False
                _release_summarize_claim(db, job_id, exec_uuid)
                if not cleanup_ok:
                    # P11-NEW-25: do not acknowledge a superseded document we
                    # could not durably remove — surface the failure instead.
                    return {"error": "superseded document cleanup failed"}
                return {"status": "skipped", "reason": "superseded by a newer force request"}

        # Mark summarization as completed. Fenced final write (P11-NEW-22):
        # revalidate under the job lock that (a) the generation still matches
        # for force deliveries, (b) summarize_status is still 'processing'
        # (a cancellation or newer force must not be overwritten), and (c)
        # the step completion actually succeeded under our claim token.
        final_ok = True
        try:
            if db.bind.dialect.name == "postgresql":
                db.execute(
                    text(
                        "SELECT id FROM processing_jobs WHERE id = :job_id FOR UPDATE"
                    ),
                    {"job_id": job_id},
                )
            row = db.execute(
                text(
                    "SELECT force_generation, summarize_status FROM processing_jobs "
                    "WHERE id = :job_id"
                ),
                {"job_id": job_id},
            ).first()
            if row is None:
                final_ok = False
            else:
                current_gen, current_status = int(row[0]), row[1]
                # P22-NEW-54: generation fencing applies to EVERY worker that
                # carries a generation (non-force deliveries too) — a worker
                # that observed generation G must not complete after G+1.
                if force_generation is not None and current_gen != force_generation:
                    final_ok = False
                if current_status != "processing":
                    final_ok = False
        except Exception:
            db.rollback()
            final_ok = False

        if not final_ok:
            # A newer force/cancellation won while the LLM ran: discard the
            # document and release the claim rather than overwriting state.
            # The document delete is DURABLE (P11-NEW-25): save_document
            # already committed it, so a rollback here would silently keep
            # the stale document — delete in its own committed transaction
            # and surface failure rather than acknowledging stale work.
            cleanup_ok = _delete_document_durably(db, doc.id)
            _release_summarize_claim(db, job_id, exec_uuid)
            if not cleanup_ok:
                return {"error": "stale document cleanup failed"}
            return {"status": "skipped", "reason": "superseded before completion"}

        job.summarize_status = "completed"
        job.celery_task_id = None
        if summarize_claimed:
            from app.services.job_steps import complete_step
            step_done = complete_step(
                db, job.id, "summarize", exec_uuid,
                {"document_id": doc.id, "characters": len(summary_content)},
            )
            if not step_done:
                # We lost the step claim (another incarnation took over):
                # do not mark the job completed on our behalf. Durable
                # delete of the just-committed document (P11-NEW-22).
                db.rollback()
                cleanup_ok = _delete_document_durably(db, doc.id)
                _release_summarize_claim(db, job_id, exec_uuid)
                if not cleanup_ok:
                    return {"error": "stale document cleanup failed"}
                return {"status": "skipped", "reason": "summarize claim lost before completion"}
        db.commit()
        _add_log(db, job_id, "Summarization completed", "info", "summarize")

        return {"status": "completed", "document_id": doc.id}

    except CancelledException:
        logger.info(f"Summarize task cancelled for job {job_id}")
        _add_log(db, job_id, "Summarization cancelled by user", "warning", "summarize")
        # P23-NEW-55/P24-NEW-59: fail only if this delivery still owns the
        # stage; the step claim token is the exec_uuid.
        _fail_summarize_owned(
            db, job_id, self.request.id, force_generation, "Cancelled",
            step_token=exec_uuid, step_claimed=summarize_claimed,
        )
        return {"status": "cancelled"}

    except SidecarCapacityExhausted:
        logger.info("Summarize: job %s queued on sidecar capacity", job_id)
        if self.request.retries >= self.max_retries:
            # Retries exhausted: stage-aware terminalization (Review Round 2
            # NEW-6 / P11-NEW-21). The helper returns a tri-state:
            #   done      -> whole job failed + admission released
            #   completed -> conversion already COMPLETED: fail only the
            #                summarize stage (this delivery's own stage)
            #   owned     -> another incarnation owns a running step: no
            #                mutation at all (P8-NEW-11)
            #   already   -> job already terminal: nothing to do
            disposition = _terminalize_capacity_exhausted(db, job_id)
            if disposition == "owned":
                return {"status": "skipped", "reason": "another incarnation owns this job"}
            if disposition == "already":
                return {"status": "skipped", "reason": "job already terminal"}
            if disposition == "completed":
                # Summarize-only context on a completed conversion: fail the
                # summarize stage under the ownership fence (P23-NEW-55) so a
                # concurrent cancellation or newer force is not clobbered.
                _fail_summarize_owned(
                    db, job_id, self.request.id, force_generation,
                    "No sidecar capacity available after retries",
                    step_token=exec_uuid, step_claimed=summarize_claimed,
                )
            return {"error": "No sidecar capacity available after retries"}
        raise self.retry(exc=SidecarCapacityExhausted(str(job_id)), countdown=60)

    except Exception as e:
        db.rollback()
        logger.error(f"Summarize task failed for job {job_id}: {e}")
        _add_log(db, job_id, f"Summarization failed: {e}", "error", "summarize")
        try:
            job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            # A concurrent delivery of the same task (Celery redelivery after
            # a long run exceeds Redis' visibility timeout) may have already
            # saved a valid document and marked the job completed. Do not
            # overwrite that success with a failure — the document is the
            # source of truth.
            already_done = False
            if job:
                already_done = (
                    job.summarize_status == "completed"
                    or db.query(Document)
                    .filter(Document.job_id == job.id, Document.format == "summary")
                    .first()
                    is not None
                )
            if not already_done:
                # P23-NEW-55/P24-NEW-59: fail only if this delivery still
                # owns the stage (generation + task id + status fenced); the
                # step claim token is the exec_uuid.
                _fail_summarize_owned(
                    db, job_id, self.request.id, force_generation, str(e),
                    step_token=exec_uuid, step_claimed=summarize_claimed,
                )
        except Exception:
            pass
        return {"error": str(e)}

    finally:
        if heartbeat_thread is not None:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=5)
        if slot is not None:
            try:
                _release_slot_if_held(db, slot, exec_uuid)
                db.commit()
            except Exception as exc:
                logger.warning("summarize slot release failed: %s", exc)
                db.rollback()
        db.close()


# ==============================================================================
# SLIDE DETECTION TASK
# ==============================================================================

@celery_app.task(bind=True, name="process_snapshots", max_retries=1)
def process_snapshots(self, job_id: int):
    """Extract snapshots under the snapshots step's independent claim token."""
    from pathlib import Path

    from app.db.models import ProcessingJob, ProcessingMode, ProcessingStatus
    from app.db.session import SessionLocal
    from app.services.job_steps import claim_step, complete_step, fail_step
    from app.services.snapshot import SnapshotService

    exec_uuid = _mint_exec_uuid()
    db = SessionLocal()
    try:
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if job is None:
            return {"error": f"Job {job_id} not found"}
        # Terminal guard (Review Round 2 NEW-9): a job terminalized between
        # dispatch and execution must not be resurrected by redriven work.
        if job.status in (ProcessingStatus.COMPLETED, ProcessingStatus.CANCELLED, ProcessingStatus.FAILED):
            return {"status": "skipped", "reason": "job is terminal"}
        claimed = claim_step(db, job.id, "snapshots", exec_uuid)
        if claimed is None:
            return {"status": "skipped", "reason": "step is not retryable"}
        if not job.video_file_path or not Path(job.video_file_path).is_file():
            fail_step(db, job.id, "snapshots", exec_uuid, "No downloaded video is available")
            # Terminal-without-result: mark the job failed and release the
            # admission in the same commit (Review Round 2 N5).
            job.status = ProcessingStatus.FAILED
            job.error_message = "No downloaded video is available for snapshots"
            _finish_admission_for_job(db, job_id, failed=True)
            db.commit()
            return {"error": "No downloaded video is available"}

        _data_dir = get_settings().storage.data_dir or str(
            Path(__file__).resolve().parent.parent / "data"
        )
        _mark_stage_delivered(db, job_id, "snapshots")

        def _progress(percent: int) -> None:
            try:
                from app.services.job_steps import set_step_progress

                set_step_progress(db, job.id, "snapshots", claimed.claim_token, percent)
                db.commit()
            except Exception:
                db.rollback()

        frames = SnapshotService().extract_frames(
            job.video_file_path,
            output_dir=str(Path(_data_dir) / "snapshots" / job.job_id),
            progress_cb=lambda done, total: _progress(5 + int(done / max(total, 1) * 80)),
        )
        _progress(90)
        snapshots = SnapshotService().save_snapshots(db, job.id, frames)
        # P20-NEW-43/P21-NEW-48: gate the finalizer on fresh job status under
        # the JOB row lock FIRST (job->step order, matching claim_step), then
        # complete the step; a cancelled/failed job is never resurrected and
        # a lost claim never writes terminal state.
        terminal_ok = True
        if db.bind.dialect.name == "postgresql":
            fresh = db.execute(
                text(
                    "SELECT status FROM processing_jobs WHERE id = :job_id FOR UPDATE"
                ),
                {"job_id": job_id},
            ).first()
        else:
            fresh = db.execute(
                text("SELECT status FROM processing_jobs WHERE id = :job_id"),
                {"job_id": job_id},
            ).first()
        if fresh is not None and fresh[0] in ("cancelled", "failed"):
            terminal_ok = False
        step_done = complete_step(
            db,
            job.id,
            "snapshots",
            exec_uuid,
            {"count": len(snapshots), "frames_analyzed": len(frames)},
        )
        if terminal_ok and job.processing_mode != ProcessingMode.SLIDE_AWARE.value:
            job.status = ProcessingStatus.COMPLETED
            _finish_admission_for_job(db, job_id)
        if not step_done or not terminal_ok:
            # Lost claim or terminalized job: no terminal write.
            db.rollback()
            return {"status": "skipped", "reason": "snapshot finalize superseded"}
        db.commit()  # step + terminal state + admission release in one commit
        return {"status": "completed", "count": len(snapshots)}
    except Exception as exc:
        db.rollback()
        try:
            fail_step(db, job_id, "snapshots", exec_uuid, str(exc))
            # Terminal failure with a conditional write (P21-NEW-49): a
            # cancellation committed during extraction must not be
            # overwritten with FAILED.
            job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            if job and job.processing_mode != ProcessingMode.SLIDE_AWARE.value:
                db.execute(
                    text(
                        "UPDATE processing_jobs SET status = 'failed', "
                        "error_message = :msg "
                        "WHERE id = :job_id AND status IN ('pending', 'processing')"
                    ),
                    {"job_id": job_id, "msg": f"Snapshot extraction failed: {str(exc)[:500]}"},
                )
                _finish_admission_for_job(db, job_id, failed=True)
            db.commit()
        except Exception:
            db.rollback()
        logger.exception("Snapshot task failed for job %s", job_id)
        return {"error": str(exc)}
    finally:
        db.close()

@celery_app.task(bind=True, name="process_slides", max_retries=1)
def process_slides(self, job_id: int):
    """
    Process slide detection for a presentation-style video.

    This task is dispatched by process_transcript when processing_mode == 'slide_aware'
    and a video file has been downloaded.

    Args:
        job_id: Database ID of the ProcessingJob
    """
    from app.db.session import SessionLocal
    from app.db.models import ProcessingJob, ProcessingMode, ProcessingStatus
    from app.services.slide_detection import SlideDetectionService
    from app.services.llm import CancelledException

    db = SessionLocal()
    slide_claimed = False
    slot = None
    exec_uuid = None
    heartbeat_stop = None
    heartbeat_thread = None
    try:
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if not job:
            logger.error(f"Slide task: Job {job_id} not found")
            return {"error": f"Job {job_id} not found"}

        # Per-incarnation execution UUID (Review Round 2 F1): the step claim,
        # the sidecar lease and all completion/release calls share it. A
        # redelivered message (same request.id) gets a fresh exec_uuid and
        # therefore cannot re-claim the step or the lease.
        exec_uuid = _mint_exec_uuid()
        slot = None
        heartbeat_stop = threading.Event()
        heartbeat_thread = None

        # Staleness guard against redelivered executions: slide detection
        # legitimately runs 30-45+ min (SSIM scan + LLM classification),
        # longer than Redis' default broker visibility timeout, so a still-
        # running delivery gets redelivered and a fresh worker picks it up
        # before the first one finishes. Without this guard that repeats
        # every ~60 min forever, each cycle restarting the whole pipeline
        # from scratch (see incident_log.md 2026-08-12: a job looped 7
        # cycles over 7 hours and starved the worker queue for every other
        # job). Mirrors summarize_transcript_task's guard.
        if job.celery_task_id and job.celery_task_id != self.request.id:
            logger.info(
                "Slide task: job %s already processing under task %s, skipping duplicate delivery %s",
                job_id, job.celery_task_id, self.request.id,
            )
            return {"status": "skipped", "reason": "another delivery is active"}
        if job.status in (ProcessingStatus.COMPLETED, ProcessingStatus.CANCELLED, ProcessingStatus.FAILED):
            logger.info(f"Slide task: job {job_id} already terminal ({job.status.value}), skipping")
            return {"status": "skipped", "reason": "job is terminal"}

        if job.processing_mode != ProcessingMode.SLIDE_AWARE.value:
            logger.warning(f"Slide task: Job {job_id} is not in slide_aware mode")
            return {"error": "Not in slide_aware mode"}

        if not job.video_file_path:
            logger.error(f"Slide task: Job {job_id} has no video file")
            _add_log(db, job_id, "No video file for slide detection", "error", "slide_detect")
            # P20-NEW-44: gate the early terminal write on fresh job status
            # under the job-row lock — a concurrent cancellation/failure must
            # never be overwritten with COMPLETED.
            if db.bind.dialect.name == "postgresql":
                fresh = db.execute(
                    text(
                        "SELECT status FROM processing_jobs WHERE id = :job_id FOR UPDATE"
                    ),
                    {"job_id": job_id},
                ).first()
            else:
                fresh = db.execute(
                    text("SELECT status FROM processing_jobs WHERE id = :job_id"),
                    {"job_id": job_id},
                ).first()
            if fresh is not None and fresh[0] in ("cancelled", "failed"):
                db.rollback()
                return {"status": "skipped", "reason": "job is terminal"}
            job.status = ProcessingStatus.COMPLETED
            job.slide_status = "skipped"
            _finish_admission_for_job(db, job_id)
            db.commit()  # terminal + admission release in one commit (N5)
            return {"error": "No video file"}

        # WP2/WP3 (Review Round 2 F1/F3): external sidecar work REQUIRES a
        # slot lease acquired by THIS incarnation under its exec_uuid, and
        # the step claim comes AFTER the lease so a no-capacity retry never
        # leaves a RUNNING claim owned by a dead incarnation. No slot -> the
        # job waits visibly (admission reason recorded) and the task retries
        # with a bounded countdown; it never runs unleased.
        # WP3-hotfix: prefetch the telemetry snapshot BEFORE any DB write
        # below (job-row update / step claim / outbox delivered) and pass it
        # through acquire_slot and provider resolution, so no Redis I/O
        # occurs while DB row locks are held.
        from app.services.sidecar import prefetch_sidecar_telemetry

        telemetry_snapshot = prefetch_sidecar_telemetry(db)
        slot = _lease_slot_for_job(db, job, exec_uuid, telemetry_snapshot)
        if slot is None:
            _record_capacity_queue_reason(db, job)
            logger.info(
                "Slide task: job %s has no sidecar slot; retrying on capacity", job_id
            )
            raise SidecarCapacityExhausted(job_id)

        if _has_persisted_steps(job):
            from app.services.job_steps import claim_step

            slide_claimed = claim_step(db, job.id, "slides", exec_uuid) is not None
            if not slide_claimed:
                # Lost the claim to another incarnation; release the lease
                # we just took so capacity is not held pointlessly.
                _release_slot_if_held(db, slot, exec_uuid)
                db.commit()
                return {"status": "skipped", "reason": "slides step is not retryable"}

        # Mark as processing and store Celery task ID for cancellation
        job.status = ProcessingStatus.PROCESSING
        job.celery_task_id = self.request.id
        db.commit()
        _add_log(db, job_id, "Starting slide detection pipeline...", "info", "slide_detect")
        _mark_stage_delivered(db, job_id, "slides")

        _add_log(
            db, job_id,
            f"Acquired sidecar slot {slot.sidecar_id}#{slot.slot_index} (gen {slot.generation})",
            "info", "slide_lease",
        )

        def cancel_check() -> bool:
            return _is_slide_cancelled(db, job_id) or lease_lost.is_set()

        # Bind the LLM provider to the LEASED sidecar (registry endpoint +
        # live served model), not the generic fleet resolver — the selected
        # registry sidecar is the one the lease authorizes (Review Round 2 F6).
        provider, llm_model = _resolve_provider_for_slot(db, slot, telemetry_snapshot)
        if provider is None:
            _add_log(db, job_id, "No LLM provider available; slide disambiguation will be skipped", "warning", "slide_detect")

        def _heartbeat_loop() -> None:
            from app.db.session import SessionLocal as _SL
            from app.services.lease import heartbeat_slot

            interval = get_settings().admission.heartbeat_interval_seconds
            while not heartbeat_stop.wait(interval):
                try:
                    hb_db = _SL()
                    try:
                        ok = heartbeat_slot(
                            hb_db, slot.id, exec_uuid, slot.generation
                        )
                        hb_db.commit()
                        if not ok:
                            logger.error(
                                "Slot %s heartbeat rejected (stale fence); stopping further sidecar work",
                                slot.id,
                            )
                            lease_lost.set()
                    finally:
                        hb_db.close()
                except Exception as exc:
                    logger.warning("slot heartbeat failed: %s", exc)

        lease_lost = threading.Event()
        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop, name=f"lease-hb-{job_id}", daemon=True
        )
        heartbeat_thread.start()

        def _finish(slide_status: str) -> str:
            """Mark the job COMPLETED with the given slide_status and clear
            the task ID. Returns 'done' | 'terminal' | 'claim-lost' so stale
            workers do not report/log success (P20-NEW-45).

            P19-NEW-41: gated on FRESH job status under the job-row lock and
            on the step completion result — a cancelled/failed job is never
            resurrected to COMPLETED, and a lost claim never writes terminal
            state. Slides are optional: when the job was cancelled, leave the
            cancellation intact and only fail the slides step.
            """
            if db.bind.dialect.name == "postgresql":
                fresh = db.execute(
                    text(
                        "SELECT status FROM processing_jobs WHERE id = :job_id FOR UPDATE"
                    ),
                    {"job_id": job_id},
                ).first()
            else:
                fresh = db.execute(
                    text("SELECT status FROM processing_jobs WHERE id = :job_id"),
                    {"job_id": job_id},
                ).first()
            if fresh is None:
                return "terminal"
            fresh_status = fresh[0]
            if fresh_status in ("cancelled", "failed"):
                # Never overwrite a terminal decision; just mark the step.
                j = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
                if j is not None and slide_claimed:
                    from app.services.job_steps import fail_step

                    fail_step(db, j.id, "slides", exec_uuid, slide_status or "skipped")
                db.commit()
                return "terminal"
            j = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            if j:
                j.status = ProcessingStatus.COMPLETED
                j.slide_status = slide_status
                j.celery_task_id = None
                step_ok = True
                if slide_claimed:
                    from app.services.job_steps import complete_step, fail_step
                    if slide_status == "completed":
                        step_ok = complete_step(db, j.id, "slides", exec_uuid)
                    else:
                        step_ok = fail_step(db, j.id, "slides", exec_uuid, slide_status)
                if not step_ok:
                    # Lost the step claim: do not write terminal job state on
                    # a claim we do not own (P19-NEW-41).
                    db.rollback()
                    return "claim-lost"
                _finish_admission_for_job(db, j.id)
                db.commit()
            return "done"

        service = SlideDetectionService()
        service.run_full_pipeline(db, job, cancel_check, provider=provider, model=llm_model)

        disposition = _finish("completed")
        if disposition in ("terminal", "claim-lost"):
            return {"status": "skipped", "reason": disposition}
        _add_log(db, job_id, "Job completed successfully (with slides)", "info", "complete")
        logger.info(f"Slide detection completed for job {job_id}")

        return {"status": "completed"}

    except SidecarCapacityExhausted:
        # No slot available: the job stays admitted (counters held), the
        # admission row shows the capacity reason, and the task retries with
        # a bounded countdown — never overcommitting, never failing the job
        # ambiguously (Review Round 2 F3/F6). On exhaustion, terminalize and
        # release admission (Review Round 2 NEW-6).
        logger.info("Slide task: job %s queued on sidecar capacity", job_id)
        if self.request.retries >= self.max_retries:
            # On exhaustion, terminalize and release admission. "owned"
            # (another incarnation holds a running step) means this is a
            # duplicate redelivery — skip without mutation.
            disposition = _terminalize_capacity_exhausted(db, job_id)
            if disposition == "owned":
                return {"status": "skipped", "reason": "another incarnation owns this job"}
            return {"error": "No sidecar capacity available after retries"}
        raise self.retry(exc=SidecarCapacityExhausted(str(job_id)), countdown=60)

    except CancelledException:
        logger.info(f"Slide task cancelled for job {job_id}")
        _add_log(db, job_id, "Slide detection cancelled", "warning", "slide_detect")
        try:
            _finish("skipped")
        except Exception:
            pass
        return {"status": "cancelled"}

    except Exception as e:
        db.rollback()
        logger.error(f"Slide task failed for job {job_id}: {e}")
        _add_log(db, job_id, f"Slide detection failed (non-fatal): {e}", "warning", "slide_detect")
        try:
            _finish("failed")
        except Exception:
            pass
        return {"error": str(e)}

    finally:
        if heartbeat_thread is not None:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=5)
        if slot is not None and exec_uuid is not None:
            try:
                _release_slot_if_held(db, slot, exec_uuid)
                db.commit()
            except Exception as exc:
                logger.warning("slot release in finally failed: %s", exc)
                db.rollback()
        db.close()


@celery_app.task(bind=True, name="import_job_payload_file", max_retries=0)
def import_job_payload_file_task(self, file_path: str, user_id: int):
    """
    Import a JSON (or JSON.GZ) export payload asynchronously.

    Designed for large archives uploaded through /jobs/import-upload so request
    handling stays responsive and memory usage is bounded by worker capacity.
    """
    import gzip
    import json
    from pathlib import Path

    from app.db.session import SessionLocal
    from app.services.job_import import import_job_payload

    db = SessionLocal()
    source_path = Path(file_path)
    try:
        if not source_path.exists():
            return {"error": "Import file not found"}

        if source_path.suffix == ".gz":
            with gzip.open(source_path, "rt", encoding="utf-8") as fh:
                payload = json.load(fh)
        else:
            with source_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)

        imported_job = import_job_payload(db, payload, user_id)
        return {"job_id": imported_job.job_id, "status": "completed"}

    except Exception as e:
        db.rollback()
        logger.error(f"Import task failed for user {user_id}: {e}")
        return {"error": str(e)}
    finally:
        db.close()
        try:
            source_path.unlink(missing_ok=True)
        except Exception:
            pass
