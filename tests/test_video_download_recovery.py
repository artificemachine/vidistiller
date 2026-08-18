"""Regression coverage for transient video-download failures."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.db.models import (
    JobStepStatus,
    ProcessingJob,
    ProcessingMode,
    ProcessingStatus,
    TaskOutbox,
)
from app.exceptions import VideoProcessingException
from app.services.job_steps import claim_step, complete_step, fail_step, seed_job_steps
from app.services.video import VideoService


VIDEO_URL = "https://www.youtube.com/watch?v=JWhICz1QR8M"


def test_video_download_reextracts_after_transient_403(tmp_path):
    attempts = 0

    def download(_urls):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary connection reset")
        (tmp_path / "JWhICz1QR8M.mp4").write_bytes(b"video")

    with patch.object(VideoService, "_init_cache", return_value=None), patch(
        "app.services.video.yt_dlp.YoutubeDL"
    ) as youtube_dl, patch("app.services.video.time.sleep") as sleep:
        youtube_dl.return_value.__enter__.return_value.download.side_effect = download
        path, size = VideoService().download_video(
            VIDEO_URL, output_path=str(tmp_path), quality="720p"
        )

    assert path == str(tmp_path / "JWhICz1QR8M.mp4")
    assert size == 5
    assert youtube_dl.call_count == 2
    sleep.assert_called_once_with(1.0)


def test_video_download_stops_after_bounded_retries(tmp_path):
    with patch.object(VideoService, "_init_cache", return_value=None), patch(
        "app.services.video.yt_dlp.YoutubeDL"
    ) as youtube_dl, patch("app.services.video.time.sleep") as sleep:
        youtube_dl.return_value.__enter__.return_value.download.side_effect = RuntimeError(
            "HTTP Error 403: Forbidden"
        )
        with pytest.raises(VideoProcessingException, match="403"):
            VideoService().download_video(
                VIDEO_URL, output_path=str(tmp_path), quality="720p"
            )

    assert youtube_dl.call_count == 4
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 4.0, 10.0]


def test_youtube_download_uses_mweb_pot_provider_and_ejs(tmp_path):
    with patch.object(VideoService, "_init_cache", return_value=None), patch(
        "app.services.video.yt_dlp.YoutubeDL"
    ) as youtube_dl:
        ydl = youtube_dl.return_value.__enter__.return_value
        ydl.download.side_effect = lambda _urls: (
            tmp_path / "JWhICz1QR8M.mp4"
        ).write_bytes(b"video")
        path, size = VideoService().download_video(
            VIDEO_URL, output_path=str(tmp_path), quality="720p"
        )

    assert path == str(tmp_path / "JWhICz1QR8M.mp4")
    assert size == 5
    options = youtube_dl.call_args.args[0]
    assert options["remote_components"] == ["ejs:github"]
    assert options["extractor_args"]["youtube"]["player_client"] == ["mweb"]
    assert options["extractor_args"]["youtubepot-bgutilhttp"]["base_url"] == [
        "http://tutorial_bgutil_provider:4416"
    ]


def test_capture_reports_retryable_upstream_failure(
    client, test_db, test_user, auth_headers
):
    job = ProcessingJob(
        job_id="capture-download-retry",
        status=ProcessingStatus.COMPLETED,
        video_url=VIDEO_URL,
        video_file_path=None,
        user_id=test_user.id,
    )
    test_db.add(job)
    test_db.commit()

    with patch(
        "app.services.video.VideoService.download_video",
        side_effect=VideoProcessingException("HTTP Error 403: Forbidden"),
    ):
        response = client.post(
            "/api/snapshots/capture",
            json={"job_id": job.job_id, "timestamp": 120.0},
            headers=auth_headers,
        )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert "temporarily unavailable" in response.json()["detail"]


def test_transcript_download_failure_queues_durable_recovery(test_db):
    job = ProcessingJob(
        job_id="download-recovery-queued",
        status=ProcessingStatus.PENDING,
        video_url=VIDEO_URL,
        processing_mode=ProcessingMode.SLIDE_AWARE.value,
    )
    test_db.add(job)
    test_db.flush()
    seed_job_steps(test_db, job, extract_snapshots=True, is_slide_mode=True)
    test_db.commit()
    test_db.close = lambda: None

    with patch("app.db.session.SessionLocal", return_value=test_db), patch(
        "app.tasks._fetch_platform_captions", return_value=("timestamped transcript", "en")
    ), patch("app.services.video.VideoService.get_video_metadata", return_value={}), patch(
        "app.tasks._save_video_record"
    ), patch("app.tasks._save_transcript_and_segments"), patch(
        "app.services.video.VideoService.download_video",
        side_effect=VideoProcessingException("HTTP Error 403: Forbidden"),
    ), patch("app.services.dispatch.publish_outbox", return_value=1):
        from app.tasks import process_transcript

        result = process_transcript.apply(
            kwargs={"job_id": job.id}, task_id="transcript-download-failure"
        ).get()

    test_db.expire_all()
    refreshed = test_db.get(ProcessingJob, job.id)
    steps = {step.name: step for step in refreshed.steps}
    outbox = (
        test_db.query(TaskOutbox)
        .filter(TaskOutbox.job_id == job.id, TaskOutbox.stage == "download")
        .one()
    )

    assert result["status"] == "download_retrying"
    assert refreshed.status == ProcessingStatus.PROCESSING
    assert refreshed.video_file_path is None
    assert steps["transcribe"].status == JobStepStatus.COMPLETED
    assert steps["download"].status == JobStepStatus.FAILED
    assert steps["slides"].status == JobStepStatus.PENDING
    assert outbox.state == "pending"


def test_final_download_exhaustion_fails_job_and_pending_steps(test_db):
    job = ProcessingJob(
        job_id="download-recovery-exhausted",
        status=ProcessingStatus.PROCESSING,
        video_url=VIDEO_URL,
        processing_mode=ProcessingMode.SLIDE_AWARE.value,
    )
    test_db.add(job)
    test_db.flush()
    seed_job_steps(test_db, job, extract_snapshots=True, is_slide_mode=True)
    claim_step(test_db, job.id, "transcribe", "transcriber")
    complete_step(test_db, job.id, "transcribe", "transcriber")
    claim_step(test_db, job.id, "download", "initial-download")
    fail_step(test_db, job.id, "download", "initial-download", "HTTP 403")
    test_db.commit()
    test_db.close = lambda: None

    with patch("app.db.session.SessionLocal", return_value=test_db), patch(
        "app.services.video.VideoService.download_video",
        side_effect=VideoProcessingException("HTTP Error 403: Forbidden"),
    ):
        from app.tasks import process_video_download

        result = process_video_download.apply(
            kwargs={"job_id": job.id},
            task_id="download-final-attempt",
            retries=2,
        ).get()

    test_db.expire_all()
    refreshed = test_db.get(ProcessingJob, job.id)

    assert result["status"] == "failed"
    assert refreshed.status == ProcessingStatus.FAILED
    assert refreshed.slide_status == "failed"
    assert "Video download failed after retries" in refreshed.error_message
    assert all(
        step.status
        in {
            JobStepStatus.COMPLETED,
            JobStepStatus.FAILED,
            JobStepStatus.SKIPPED,
            JobStepStatus.CANCELLED,
        }
        for step in refreshed.steps
    )
