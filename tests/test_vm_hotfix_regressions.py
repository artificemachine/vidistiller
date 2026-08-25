"""Regression coverage for reliability fixes recovered from the live VM."""

import inspect
import time
from pathlib import Path
from unittest.mock import patch

from app.core.config import AdmissionSettings, SlideDetectionSettings
from app.db.models import ProcessingJob, ProcessingStatus
from app.services import sidecar as sidecar_mod
from app.services.job_steps import seed_job_steps
from app.services.sidecar import SidecarTelemetry


def _healthy_telemetry(registered_id: str = "primary") -> SidecarTelemetry:
    return SidecarTelemetry(
        registered_id=registered_id,
        label="Primary",
        base_url="http://sidecar.test:8000",
        declared_model="test-model",
        capabilities=["text"],
        healthy=True,
        served_models=["test-model"],
        total_slots=1,
        observed_at=time.time(),
    )


def test_shared_telemetry_defaults_are_bounded():
    admission = AdmissionSettings(_env_file=None)
    slides = SlideDetectionSettings(_env_file=None)

    assert admission.telemetry_redis_ttl_seconds == 120
    assert admission.local_telemetry_cache_ttl_seconds == 5
    assert slides.scan_max_width == 640
    assert slides.layout_confirm_samples == 2


def test_shared_telemetry_deserialization_fails_closed_on_bad_types():
    deserialize = getattr(sidecar_mod, "_telemetry_from_dict")
    payload = sidecar_mod._telemetry_to_dict(_healthy_telemetry())
    assert deserialize(payload) is not None

    payload["healthy"] = "false"
    assert deserialize(payload) is None


def test_cached_telemetry_reads_through_shared_store_when_local_cache_is_empty():
    telemetry = _healthy_telemetry()
    sidecar_mod._telemetry_cache.clear()
    if hasattr(sidecar_mod, "_telemetry_local_ts"):
        sidecar_mod._telemetry_local_ts.clear()

    settings = type("Settings", (), {
        "admission": type("Admission", (), {"local_telemetry_cache_ttl_seconds": 5})()
    })()
    with patch.object(sidecar_mod, "get_settings", return_value=settings), patch.object(
        sidecar_mod, "_read_telemetry_from_redis", return_value=telemetry, create=True
    ) as read_shared:
        result = sidecar_mod.cached_sidecar_telemetry("primary")

    assert result is telemetry
    read_shared.assert_called_once_with("primary")


def test_lease_api_accepts_prefetched_telemetry_snapshot():
    from app.services.lease import acquire_slot

    assert "telemetry_snapshot" in inspect.signature(acquire_slot).parameters


def test_video_download_retries_with_fresh_extractor(tmp_path):
    from app.core.source_type import SourceType
    from app.services import video as video_mod

    instances = []

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
            instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def download(self, urls):
            if len(instances) == 1:
                (tmp_path / "source.mp4.part").write_bytes(b"partial")
                raise RuntimeError("temporary 403")
            (tmp_path / "source.mp4").write_bytes(b"video")

    service = video_mod.VideoService.__new__(video_mod.VideoService)
    with patch.object(
        video_mod.VideoSourceResolver,
        "resolve",
        return_value=(SourceType.YOUTUBE, "source"),
    ), patch.object(video_mod.yt_dlp, "YoutubeDL", FakeYoutubeDL), patch.object(
        video_mod.time, "sleep"
    ) as sleep:
        path, size = service.download_video(
            "https://www.youtube.com/watch?v=source", str(tmp_path), "720p"
        )

    assert Path(path).name == "source.mp4"
    assert size == 5
    assert len(instances) == 2
    assert not (tmp_path / "source.mp4.part").exists()
    sleep.assert_called_once_with(1.0)


def test_download_exhaustion_fails_job_and_unowned_dependent_steps(test_db, test_user):
    job = ProcessingJob(
        job_id="download-exhausted-regression",
        status=ProcessingStatus.PROCESSING,
        video_url="https://example.test/video.mp4",
        user_id=test_user.id,
    )
    test_db.add(job)
    test_db.flush()
    seed_job_steps(test_db, job, extract_snapshots=True)
    test_db.commit()

    from app import tasks

    terminalize = getattr(tasks, "_terminalize_download_exhausted")
    assert terminalize(test_db, job.id, "temporary 403") == "done"
    test_db.refresh(job)

    assert job.status == ProcessingStatus.FAILED
    assert all(
        step.status.value in {"failed", "skipped", "completed"}
        for step in job.steps
    )
