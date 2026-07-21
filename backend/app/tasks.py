"""
Celery Task Definitions

Defines the Celery application and background tasks for processing
YouTube video transcripts.
"""

import logging
import os
import re

from celery import Celery
from app.core.config import TRANSCRIPT_CONFIDENCE_CAPTIONS, TRANSCRIPT_CONFIDENCE_WHISPER, get_settings

logger = logging.getLogger(__name__)


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

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


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
    Sets job status to FAILED and raises on failure so the caller can propagate.
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
        job.status = ProcessingStatus.FAILED
        job.error_message = f"Transcription failed: {str(e)[:500]}"
        db.commit()
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
    from app.services.video import VideoService

    db = SessionLocal()
    try:
        # 1. Load job
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found")
            return {"error": f"Job {job_id} not found"}

        video_url = job.video_url
        if not video_url:
            _add_log(db, job_id, "No video URL provided", "error", "init")
            job.status = ProcessingStatus.FAILED
            job.error_message = "No video URL provided"
            db.commit()
            return {"error": "No video URL"}

        # 2. Set status to PROCESSING, store Celery task ID for cancellation
        job.status = ProcessingStatus.PROCESSING
        job.celery_task_id = self.request.id
        db.commit()
        _add_log(db, job_id, f"Job started: {video_url}", "info", "init")
        logger.info(f"Processing transcript for job {job_id}: {video_url}")

        video_service = VideoService()

        # 3. Try platform-native captions first, then yt-dlp subtitles
        transcript_text = None
        source = "yt_dlp_captions"
        detected_language = "en"

        transcript_text, detected_language = _fetch_platform_captions(db, job_id, video_service, video_url)

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

        # 7. Download video for snapshot capture (non-fatal)
        _add_log(db, job_id, "Downloading video for snapshots...", "info", "video_download")
        try:
            from pathlib import Path as _Path
            _data_dir = get_settings().storage.data_dir or str(_Path(__file__).resolve().parent.parent / "data")
            videos_dir = str(_Path(_data_dir) / "videos" / job.job_id)
            video_path, _ = video_service.download_video(
                video_url, output_path=videos_dir, quality="720p",
            )
            job.video_file_path = video_path
            logger.info(f"Video downloaded for job {job_id}: {video_path}")
        except Exception as e:
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

        # 10. Mark job as completed, clear Celery task ID
        job.status = ProcessingStatus.COMPLETED
        job.celery_task_id = None
        db.commit()
        _add_log(db, job_id, "Job completed successfully", "info", "complete")

        logger.info(f"Job {job_id} completed: transcript saved ({len(transcript_text)} chars, source={source})")
        return {"status": "completed", "source": source, "length": len(transcript_text)}

    except Exception as e:
        db.rollback()
        _add_log(db, job_id, f"Job failed unexpectedly: {e}", "error", "fatal")
        logger.error(f"Job {job_id} failed unexpectedly: {e}")
        try:
            job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            if job:
                job.status = ProcessingStatus.FAILED
                job.error_message = f"Unexpected error: {str(e)[:500]}"
                db.commit()
        except Exception:
            pass
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

_FLEET_VMS = [
    ("vm913", "VLLM_VM913_URL"),
    ("vm903", "VLLM_VM903_URL"),
    ("vm901", "VLLM_VM901_URL"),
    ("vm2900", "VLLM_VM2900_URL"),
]


def _resolve_fleet_url(model_name: str) -> str | None:
    """
    Query all vLLM fleet VMs to find which one has *model_name* loaded.

    Calls ``GET /v1/models`` directly on each VM's vLLM port (8000).
    Returns the vLLM URL of the first match, or None if no VM has it.
    """
    import requests as _requests

    for _vm_label, _env_var in _FLEET_VMS:
        _vllm_url = os.environ.get(_env_var)
        if not _vllm_url:
            continue
        try:
            _api = _vllm_url.rstrip("/") + "/v1/models"
            _resp = _requests.get(_api, timeout=3)
            if _resp.status_code == 200:
                _models = [m["id"] for m in _resp.json().get("data", [])]
                if model_name in _models:
                    logger.info(
                        "fleet: model %r found on %s (%s)", model_name, _vm_label, _vllm_url
                    )
                    return _vllm_url
        except Exception:
            continue

    logger.warning("fleet: model %r not loaded on any VM", model_name)
    return None


def _resolve_job_llm(db, job):
    """
    Resolve the LLM provider + model for a job's owner (fleet-aware).

    Mirrors the resolution summarization uses so background tasks share one code
    path: honour the owner's configured provider/model, default to the vLLM fleet,
    and pick the VM that actually has the model loaded.

    Returns:
        (provider, model_name) — provider is an LLMProvider, or (None, None) if
        a provider could not be built.
    """
    from app.db.models import User
    from app.core.crypto import decrypt_field
    from app.services.llm_providers import build_provider, DEFAULT_MODELS

    owner = db.query(User).filter(User.id == job.user_id).first() if job.user_id else None
    provider_name = owner.llm_provider if owner and owner.llm_provider else "vllm"
    model_name = owner.llm_model if owner and owner.llm_model else None

    resolved_model = model_name or DEFAULT_MODELS.get(provider_name) or "gemma4-31b"

    fleet_url = _resolve_fleet_url(resolved_model) if provider_name == "vllm" else None
    default_url = fleet_url or os.environ.get("VLLM_VM913_URL") or os.environ.get("OLLAMA_URL")
    base_url = (owner.llm_ollama_url if owner and owner.llm_ollama_url else None) or default_url

    api_key = None
    if owner and owner.llm_api_key_encrypted:
        try:
            api_key = decrypt_field(owner.llm_api_key_encrypted)
        except Exception as e:
            logger.warning(f"Failed to decrypt API key for job {job.id}: {e}")

    try:
        provider = build_provider(
            provider_name,
            api_key=api_key,
            ollama_base_url=base_url or "http://localhost:11434",
        )
    except Exception as e:
        logger.warning(f"Could not build LLM provider for job {job.id}: {e}")
        return None, None

    return provider, resolved_model


# ==============================================================================
# SUMMARIZE TRANSCRIPT TASK
# ==============================================================================

@celery_app.task(bind=True, name="summarize_transcript", max_retries=0)
def summarize_transcript_task(self, job_id: int, force: bool = False):
    """
    Summarize a job's transcript in the background via LLM.

    Args:
        job_id: Database ID of the ProcessingJob
        force: If true, delete existing summary before regenerating
    """
    from pathlib import Path
    from app.db.session import SessionLocal
    from app.db.models import ProcessingJob, Document
    from app.services.llm import LLMService, CancelledException

    db = SessionLocal()
    try:
        from app.db.models import User
        from app.core.crypto import decrypt_field

        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if not job:
            logger.error(f"Summarize: Job {job_id} not found")
            return {"error": f"Job {job_id} not found"}

        # Store Celery task ID for cancellation
        job.celery_task_id = self.request.id
        job.summarize_status = "processing"
        db.commit()
        _add_log(db, job_id, "Starting LLM summarization...", "info", "summarize")

        # Resolve user's LLM provider preferences
        owner = db.query(User).filter(User.id == job.user_id).first() if job.user_id else None
        provider_name = owner.llm_provider if owner and owner.llm_provider else "vllm"
        model_name = owner.llm_model if owner else None

        # Fleet-aware URL: find the VM that actually has the model loaded
        _resolved_model = model_name
        if not _resolved_model and provider_name == "vllm":
            from app.services.llm_providers import DEFAULT_MODELS
            _resolved_model = DEFAULT_MODELS.get("vllm", "qwen3-32b-awq")

        if provider_name == "vllm" and _resolved_model:
            _fleet_url = _resolve_fleet_url(_resolved_model)
        else:
            _fleet_url = None

        _default_url = (
            _fleet_url
            or os.environ.get("VLLM_VM913_URL")
            or os.environ.get("OLLAMA_URL")
        )
        ollama_url = (owner.llm_ollama_url if owner and owner.llm_ollama_url else None) or _default_url
        api_key = None
        if owner and owner.llm_api_key_encrypted:
            try:
                api_key = decrypt_field(owner.llm_api_key_encrypted)
            except Exception as e:
                logger.warning(f"Failed to decrypt API key for job {job_id}: {e}")

        if not job.transcripts:
            job.summarize_status = "failed"
            job.celery_task_id = None
            db.commit()
            _add_log(db, job_id, "No transcript available for summarization", "error", "summarize")
            return {"error": "No transcript"}

        transcript_text = job.transcripts[0].full_text
        detected_lang = job.transcripts[0].language or "en"
        # Use user's preferred summary output language, fall back to transcript language
        language = (owner.summary_language if owner and owner.summary_language else None) or detected_lang
        title = job.videos[0].title if job.videos else "Video Summary"

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


        # Delete old summary if force re-generating
        if force:
            db.query(Document).filter(
                Document.job_id == job.id, Document.format == "summary"
            ).delete()
            db.commit()

        # Generate summary via LLM with user's provider settings and cancellation check
        llm = LLMService(
            provider_name=provider_name,
            model_name=model_name,
            api_key=api_key,
            ollama_base_url=ollama_url,
        )
        summary_content = llm.summarize_transcript_sections(
            transcript_text, snapshot_dicts, language=language,
            title=title, video_url=job.video_url,
            source_type=job.source_type or "",
            cancel_check=lambda: _is_cancelled(db, job_id),
        )

        # Persist document
        doc = llm.save_document(db, job.id, title, summary_content, "summary")

        # Mark summarization as completed
        job.summarize_status = "completed"
        job.celery_task_id = None
        db.commit()
        _add_log(db, job_id, "Summarization completed", "info", "summarize")

        return {"status": "completed", "document_id": doc.id}

    except CancelledException:
        logger.info(f"Summarize task cancelled for job {job_id}")
        _add_log(db, job_id, "Summarization cancelled by user", "warning", "summarize")
        try:
            job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            if job:
                job.summarize_status = "failed"
                job.celery_task_id = None
                db.commit()
        except Exception:
            pass
        return {"status": "cancelled"}

    except Exception as e:
        db.rollback()
        logger.error(f"Summarize task failed for job {job_id}: {e}")
        _add_log(db, job_id, f"Summarization failed: {e}", "error", "summarize")
        try:
            job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            if job:
                job.summarize_status = "failed"
                job.celery_task_id = None
                db.commit()
        except Exception:
            pass
        return {"error": str(e)}

    finally:
        db.close()


# ==============================================================================
# SLIDE DETECTION TASK
# ==============================================================================

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
    try:
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if not job:
            logger.error(f"Slide task: Job {job_id} not found")
            return {"error": f"Job {job_id} not found"}

        if job.processing_mode != ProcessingMode.SLIDE_AWARE.value:
            logger.warning(f"Slide task: Job {job_id} is not in slide_aware mode")
            return {"error": "Not in slide_aware mode"}

        if not job.video_file_path:
            logger.error(f"Slide task: Job {job_id} has no video file")
            _add_log(db, job_id, "No video file for slide detection", "error", "slide_detect")
            job.status = ProcessingStatus.COMPLETED
            job.slide_status = "skipped"
            db.commit()
            return {"error": "No video file"}

        # Mark as processing and store Celery task ID for cancellation
        job.status = ProcessingStatus.PROCESSING
        job.celery_task_id = self.request.id
        db.commit()
        _add_log(db, job_id, "Starting slide detection pipeline...", "info", "slide_detect")

        def cancel_check() -> bool:
            return _is_slide_cancelled(db, job_id)

        provider, llm_model = _resolve_job_llm(db, job)
        if provider is None:
            _add_log(db, job_id, "No LLM provider available; slide disambiguation will be skipped", "warning", "slide_detect")

        def _finish(slide_status: str) -> None:
            """Mark the job COMPLETED with the given slide_status and clear the task ID."""
            j = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            if j:
                j.status = ProcessingStatus.COMPLETED
                j.slide_status = slide_status
                j.celery_task_id = None
                db.commit()

        service = SlideDetectionService()
        service.run_full_pipeline(db, job, cancel_check, provider=provider, model=llm_model)

        _finish("completed")
        _add_log(db, job_id, "Job completed successfully (with slides)", "info", "complete")
        logger.info(f"Slide detection completed for job {job_id}")

        return {"status": "completed"}

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
