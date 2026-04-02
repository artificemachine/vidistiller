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

def _fetch_youtube_captions(db, job_id: int, yt_service, youtube_url: str) -> tuple[str | None, str]:
    """
    Attempt to retrieve captions via YouTubeTranscriptApi.

    Returns (transcript_text, detected_language) on success,
    or (None, "en") when captions are unavailable.
    """
    def fmt_ts(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"[{h:02d}:{m:02d}:{s:02d}]"

    try:
        video_id = yt_service.extract_video_id(youtube_url)
        from youtube_transcript_api import YouTubeTranscriptApi
        ytt_api = YouTubeTranscriptApi()

        # List available transcripts and pick the best one (keep original language)
        transcript_list = ytt_api.list(video_id)
        transcript_obj = None

        # Pick the first available transcript (prefer manual over generated)
        try:
            transcript_obj = transcript_list.find_manually_created_transcript(
                [t.language_code for t in transcript_list]
            )
        except Exception:
            transcript_obj = next(iter(transcript_list))

        detected_language = transcript_obj.language_code
        _add_log(db, job_id, f"Found {transcript_obj.language} ({detected_language}) captions", "info", "youtube_captions")

        transcript_snippets = transcript_obj.fetch()

        lines = []
        for snippet in transcript_snippets:
            text = snippet.text.replace("\n", " ")
            lines.append(f"{fmt_ts(snippet.start)} {text}")

        captions = "\n".join(lines)

        if captions and len(captions.strip()) > 0:
            _add_log(db, job_id, f"YouTube captions retrieved ({len(captions)} chars)", "info", "youtube_captions")
            logger.info(f"Got YouTube captions for {video_id} ({len(captions)} chars)")
            return captions, detected_language

    except Exception as e:
        _add_log(db, job_id, f"YouTube captions not available: {e}", "warning", "youtube_captions")
        logger.warning(f"YouTube captions failed: {e}")

    return None, "en"


def _fetch_ytdlp_captions(db, job_id: int, yt_service, youtube_url: str) -> str | None:
    """
    Attempt to retrieve captions via yt-dlp subtitle extraction.

    Returns transcript text on success, or None when no captions are found.
    """
    _add_log(db, job_id, "Trying yt-dlp subtitle extraction...", "info", "yt_dlp_captions")
    try:
        ytdlp_captions = yt_service.get_captions_ytdlp(youtube_url)
        if ytdlp_captions and ytdlp_captions.strip():
            _add_log(db, job_id, f"yt-dlp captions retrieved ({len(ytdlp_captions)} chars)", "info", "yt_dlp_captions")
            logger.info(f"Got yt-dlp captions for job {job_id} ({len(ytdlp_captions)} chars)")
            return ytdlp_captions
        else:
            _add_log(db, job_id, "yt-dlp returned no captions", "warning", "yt_dlp_captions")
    except Exception as e:
        _add_log(db, job_id, f"yt-dlp caption extraction failed: {e}", "warning", "yt_dlp_captions")
        logger.warning(f"yt-dlp caption extraction failed: {e}")

    return None


def _transcribe_audio(db, job_id: int, job, yt_service, youtube_url: str) -> tuple[str, str]:
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
        audio_path, _ = yt_service.download_audio(youtube_url)
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


def _save_video_record(db, job_id: int, job, youtube_url: str, metadata: dict) -> None:
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
            url=youtube_url,
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
    from app.services.youtube import YouTubeService

    db = SessionLocal()
    try:
        # 1. Load job
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found")
            return {"error": f"Job {job_id} not found"}

        youtube_url = job.youtube_url
        if not youtube_url:
            _add_log(db, job_id, "No YouTube URL provided", "error", "init")
            job.status = ProcessingStatus.FAILED
            job.error_message = "No YouTube URL provided"
            db.commit()
            return {"error": "No YouTube URL"}

        # 2. Set status to PROCESSING, store Celery task ID for cancellation
        job.status = ProcessingStatus.PROCESSING
        job.celery_task_id = self.request.id
        db.commit()
        _add_log(db, job_id, f"Job started: {youtube_url}", "info", "init")
        logger.info(f"Processing transcript for job {job_id}: {youtube_url}")

        yt_service = YouTubeService()

        # 3. Try YouTube captions first (using youtube_transcript_api v1.x)
        transcript_text = None
        source = "youtube_captions"
        detected_language = "en"

        transcript_text, detected_language = _fetch_youtube_captions(db, job_id, yt_service, youtube_url)

        # 4. Fallback: try yt-dlp subtitle extraction
        if not transcript_text:
            transcript_text = _fetch_ytdlp_captions(db, job_id, yt_service, youtube_url)
            if transcript_text:
                source = "yt_dlp_captions"

        # 5. Fallback: download audio and transcribe via Ollama
        if not transcript_text:
            source = "whisper_local"
            transcript_text, detected_language = _transcribe_audio(db, job_id, job, yt_service, youtube_url)

        if not transcript_text or not transcript_text.strip():
            _add_log(db, job_id, "No transcript could be generated", "error", "save_transcript")
            job.status = ProcessingStatus.FAILED
            job.error_message = "No transcript could be generated"
            db.commit()
            return {"error": "Empty transcript"}

        # 6. Embed YouTube chapters as markdown headers (for all sources)
        metadata = {}
        try:
            metadata = yt_service.get_video_metadata(youtube_url)
            chapters = sorted(metadata.get("chapters", []), key=lambda c: c["start_time"])
        except Exception:
            chapters = []

        if chapters:
            transcript_text = _embed_chapters(transcript_text, chapters)
            _add_log(db, job_id, f"Injected {len(chapters)} chapter headers", "info", "chapters")

        # 6b. Persist Video record so title appears in Recent Conversions
        _save_video_record(db, job_id, job, youtube_url, metadata)

        # 6c. Prepend video title and source URL
        video_title = metadata.get("title", "")
        if video_title:
            transcript_text = f"# {video_title}\n\nSource: {youtube_url}\n\n{transcript_text}"

        # 7. Save transcript to DB and segment it
        _save_transcript_and_segments(db, job_id, job, transcript_text, source, detected_language)

        # 8. Download video for snapshot capture (non-fatal)
        _add_log(db, job_id, "Downloading video for snapshots...", "info", "video_download")
        try:
            from pathlib import Path as _Path
            from app.services.youtube import YouTubeService
            yt_dl = YouTubeService()
            _data_dir = get_settings().storage.data_dir or str(_Path(__file__).resolve().parent.parent / "data")
            videos_dir = str(_Path(_data_dir) / "videos" / job.job_id)
            video_path, _ = yt_dl.download_video(
                youtube_url, output_path=videos_dir, quality="720p",
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
        provider_name = owner.llm_provider if owner and owner.llm_provider else "ollama"
        model_name = owner.llm_model if owner else None
        ollama_url = owner.llm_ollama_url if owner and owner.llm_ollama_url else None
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
        language = job.transcripts[0].language or "en"
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
            title=title, youtube_url=job.youtube_url,
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
            db.commit()
            return {"error": "No video file"}

        # Mark as processing and store Celery task ID for cancellation
        job.status = ProcessingStatus.PROCESSING
        job.celery_task_id = self.request.id
        db.commit()
        _add_log(db, job_id, "Starting slide detection pipeline...", "info", "slide_detect")

        def cancel_check() -> bool:
            db.expire_all()
            j = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            if not j:
                return True
            return j.status == ProcessingStatus.FAILED

        service = SlideDetectionService()
        service.run_full_pipeline(db, job, cancel_check)

        # Mark job as completed
        job.status = ProcessingStatus.COMPLETED
        job.celery_task_id = None
        db.commit()
        _add_log(db, job_id, "Job completed successfully (with slides)", "info", "complete")
        logger.info(f"Slide detection completed for job {job_id}")

        return {"status": "completed"}

    except CancelledException:
        logger.info(f"Slide task cancelled for job {job_id}")
        _add_log(db, job_id, "Slide detection cancelled", "warning", "slide_detect")
        try:
            job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            if job:
                job.status = ProcessingStatus.COMPLETED
                job.celery_task_id = None
                db.commit()
        except Exception:
            pass
        return {"status": "cancelled"}

    except Exception as e:
        db.rollback()
        logger.error(f"Slide task failed for job {job_id}: {e}")
        _add_log(db, job_id, f"Slide detection failed (non-fatal): {e}", "warning", "slide_detect")
        try:
            job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            if job:
                # Mark as completed anyway — slides are optional enrichment
                job.status = ProcessingStatus.COMPLETED
                job.celery_task_id = None
                db.commit()
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
