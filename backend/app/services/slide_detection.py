"""
Slide Detection Service for presentation-style YouTube videos.

Detects slide transitions via SSIM comparison, classifies ambiguous transitions
with the LLM, extracts final-state frames with OCR, and aligns transcript
segments to each slide.
"""

import logging
import os
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from skimage.metrics import structural_similarity

from app.core.config import get_settings
from app.exceptions import SlideDetectionException
from app.services.llm import CancelledException

logger = logging.getLogger(__name__)


class SlideDetectionService:
    """Service that detects slides in presentation-style videos."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.slide_settings = self.settings.slide_detection

    # ------------------------------------------------------------------
    # Step 1: Layout Detection
    # ------------------------------------------------------------------

    def layout_detection(self, video_path: str) -> str:
        """
        Sample frames and classify layout as full_frame, pip_speaker, or split_panel.

        Uses contour analysis on a few evenly-spaced frames to detect large rectangular
        regions that indicate a Picture-in-Picture speaker box or a split panel.

        Returns:
            Layout type string: "full_frame", "pip_speaker", or "split_panel"
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.warning("Could not open video for layout detection; defaulting to full_frame")
            return "full_frame"

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sample_count = min(self.slide_settings.layout_sample_count, max(1, total_frames))
        indices = [int(i * total_frames / sample_count) for i in range(sample_count)]

        pip_votes = 0
        split_votes = 0

        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue

            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for cnt in contours:
                x, y, cw, ch = cv2.boundingRect(cnt)
                area_ratio = (cw * ch) / (w * h)
                aspect = cw / max(ch, 1)

                # Small box in corner → PiP speaker
                if 0.02 < area_ratio < 0.15 and 0.5 < aspect < 2.0:
                    if (x < w * 0.3 or x + cw > w * 0.7) and (y < h * 0.3 or y + ch > h * 0.7):
                        pip_votes += 1

                # Roughly half the frame → split panel
                if 0.35 < area_ratio < 0.55 and 0.3 < aspect < 3.0:
                    split_votes += 1

        cap.release()

        if pip_votes >= sample_count * 0.4:
            return "pip_speaker"
        if split_votes >= sample_count * 0.4:
            return "split_panel"
        return "full_frame"

    # ------------------------------------------------------------------
    # Step 2: SSIM Transition Scan
    # ------------------------------------------------------------------

    def ssim_transition_scan(
        self, video_path: str, fps: float, layout: str
    ) -> Tuple[List[Dict], int]:
        """
        Compare consecutive frames at `fps` rate using SSIM.

        Returns tuple of (transitions, frames_sampled):
            transitions: list of {"frame_index": int, "timestamp": float, "ssim": float, "classification": str}
            frames_sampled: actual number of frames compared
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise SlideDetectionException("Cannot open video for SSIM scan")

        video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_skip = max(1, int(video_fps / fps))

        prev_gray: Optional[np.ndarray] = None
        transitions: List[Dict] = []
        frame_idx = 0
        frames_sampled = 0

        threshold = self.slide_settings.ssim_threshold
        ambig_low = self.slide_settings.ssim_ambiguous_low
        ambig_high = self.slide_settings.ssim_ambiguous_high

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_skip == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                # Optionally crop content region based on layout
                gray = self._crop_content_region(gray, layout)

                if prev_gray is not None:
                    ssim_val = self._compute_ssim(prev_gray, gray)
                    timestamp = frame_idx / video_fps

                    if ssim_val < threshold:
                        classification = "transition"
                    elif ambig_low <= ssim_val <= ambig_high:
                        classification = "ambiguous"
                    else:
                        classification = "same"

                    if classification in ("transition", "ambiguous"):
                        transitions.append({
                            "frame_index": frame_idx,
                            "timestamp": timestamp,
                            "ssim": ssim_val,
                            "classification": classification,
                        })

                prev_gray = gray
                frames_sampled += 1

            frame_idx += 1

        cap.release()
        logger.info(f"SSIM scan: {frames_sampled} frames sampled, {len(transitions)} transitions found")
        return transitions, frames_sampled

    # ------------------------------------------------------------------
    # Step 3: LLM Ambiguity Classification
    # ------------------------------------------------------------------

    def llm_ambiguity_classification(
        self,
        pairs: List[Dict],
        cancel_check: Optional[Callable[[], bool]] = None,
        provider=None,
        model: Optional[str] = None,
    ) -> List[Dict]:
        """
        Classify ambiguous transition pairs as TRANSITION or INCREMENTAL via the LLM.

        Uses a text-based approach (OCR text diff + SSIM value) through the shared
        provider abstraction, so it runs on the same vLLM fleet / provider the rest
        of the app uses. The provider is injected by the caller (the slide task
        resolves the job owner's LLM settings).

        Args:
            pairs: List of dicts with "ssim", "ocr_text_before", "ocr_text_after"
            cancel_check: Optional callable that returns True if task was cancelled
            provider: An LLMProvider instance exposing generate(prompt, model, ...)
            model: Concrete model id to pass to the provider

        Returns:
            Updated pairs with "llm_classification" field added (unchanged when no
            provider is available).
        """
        if provider is None:
            logger.warning(
                "No LLM provider for slide ambiguity classification; leaving pairs unclassified"
            )
            return pairs

        model = model or self.slide_settings.llm_model
        timeout = self.slide_settings.llm_timeout
        classified = 0

        for pair in pairs:
            if cancel_check and cancel_check():
                raise CancelledException()

            if pair.get("classification") != "ambiguous":
                continue

            ssim_val = pair.get("ssim", 0)
            text_before = (pair.get("ocr_text_before") or "")[:500]
            text_after = (pair.get("ocr_text_after") or "")[:500]

            prompt = (
                "You are analysing a presentation video. Two consecutive frames have an SSIM "
                f"similarity of {ssim_val:.3f} (1.0 = identical, 0.0 = completely different).\n\n"
                f"OCR text from the BEFORE frame:\n{text_before or '(no text detected)'}\n\n"
                f"OCR text from the AFTER frame:\n{text_after or '(no text detected)'}\n\n"
                "Is this a NEW SLIDE (completely different content) or an INCREMENTAL BUILD "
                "(same slide with added content like bullet points)?\n\n"
                "Respond with exactly one word: TRANSITION or INCREMENTAL"
            )

            try:
                answer = provider.generate(prompt, model, timeout=timeout, max_tokens=10).strip().upper()
                if "INCREMENTAL" in answer:
                    pair["llm_classification"] = "incremental"
                else:
                    pair["llm_classification"] = "transition"
                classified += 1
            except Exception as e:
                logger.warning(f"LLM classification failed: {e}")
                pair["llm_classification"] = "transition"

        logger.info(f"LLM classified {classified} ambiguous transitions")
        return pairs

    # ------------------------------------------------------------------
    # Step 4: Slide Grouping
    # ------------------------------------------------------------------

    def slide_grouping(
        self, transitions: List[Dict], video_duration: float
    ) -> List[Dict]:
        """
        Merge incremental builds, enforce minimum duration, and assign slide numbers.

        Returns list of slide dicts:
            {"slide_number": int, "start_timestamp": float, "end_timestamp": float,
             "ssim_transition_score": float, "is_incremental_build": bool,
             "parent_slide_number": Optional[int]}
        """
        min_duration = self.slide_settings.min_slide_duration

        # Filter to actual transitions (not incremental builds)
        real_transitions = []
        for t in transitions:
            classification = t.get("llm_classification", t.get("classification", "transition"))
            if classification == "incremental":
                continue
            real_transitions.append(t)

        # Sort by timestamp
        real_transitions.sort(key=lambda x: x["timestamp"])

        # Build slides from transitions
        slides: List[Dict] = []
        prev_end = 0.0
        slide_num = 1

        for t in real_transitions:
            ts = t["timestamp"]

            # Enforce minimum duration — skip transitions too close to previous
            if ts - prev_end < min_duration:
                continue

            # Close previous slide
            if slides:
                slides[-1]["end_timestamp"] = ts

            slides.append({
                "slide_number": slide_num,
                "start_timestamp": ts,
                "end_timestamp": video_duration,  # will be updated by next transition
                "ssim_transition_score": t.get("ssim", 0.0),
                "is_incremental_build": False,
                "parent_slide_number": None,
            })
            prev_end = ts
            slide_num += 1

        # If no transitions detected, create a single slide for the entire video
        if not slides:
            slides.append({
                "slide_number": 1,
                "start_timestamp": 0.0,
                "end_timestamp": video_duration,
                "ssim_transition_score": 0.0,
                "is_incremental_build": False,
                "parent_slide_number": None,
            })

        # Add initial slide if first transition is not at the start
        if slides and slides[0]["start_timestamp"] > min_duration:
            slides.insert(0, {
                "slide_number": 0,
                "start_timestamp": 0.0,
                "end_timestamp": slides[0]["start_timestamp"],
                "ssim_transition_score": 0.0,
                "is_incremental_build": False,
                "parent_slide_number": None,
            })
            # Renumber all slides
            for i, s in enumerate(slides):
                s["slide_number"] = i + 1

        logger.info(f"Grouped into {len(slides)} slides")
        return slides

    # ------------------------------------------------------------------
    # Step 5: Final State Capture
    # ------------------------------------------------------------------

    def final_state_capture(
        self,
        video_path: str,
        slides: List[Dict],
        output_dir: str,
    ) -> List[Dict]:
        """
        Extract frame at end - 0.5s for each slide, save JPEG, run OCR.

        Updates slides in-place with: final_frame_path, ocr_text, image_width,
        image_height, file_size.
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise SlideDetectionException("Cannot open video for frame capture")

        video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        ocr_enabled = self.slide_settings.ocr_enabled

        for slide in slides:
            capture_ts = max(0, slide["end_timestamp"] - 0.5)
            frame_idx = int(capture_ts * video_fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()

            if not ret:
                logger.warning(f"Could not capture frame for slide {slide['slide_number']}")
                continue

            h, w = frame.shape[:2]
            frame_name = f"slide_{slide['slide_number']:03d}.jpg"
            frame_path = str(Path(output_dir) / frame_name)
            cv2.imwrite(frame_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])

            file_size = Path(frame_path).stat().st_size

            slide["final_frame_path"] = frame_path
            slide["image_width"] = w
            slide["image_height"] = h
            slide["file_size"] = file_size

            # OCR
            if ocr_enabled:
                slide["ocr_text"] = self._extract_ocr_text(frame)

        cap.release()
        return slides

    # ------------------------------------------------------------------
    # Step 6: Transcript Alignment
    # ------------------------------------------------------------------

    def transcript_alignment(
        self, slides: List[Dict], segments: list
    ) -> List[Dict]:
        """
        Map TranscriptSegment records to slides by timestamp overlap.

        Args:
            slides: List of slide dicts with start_timestamp/end_timestamp
            segments: List of TranscriptSegment ORM objects (with start_time, end_time, text)

        Returns:
            Updated slides with "transcript_text" populated.
        """
        for slide in slides:
            start = slide["start_timestamp"]
            end = slide["end_timestamp"]
            matching_texts: List[str] = []

            for seg in segments:
                seg_start = seg.start_time
                seg_end = seg.end_time

                # Check overlap
                if seg_end > start and seg_start < end:
                    matching_texts.append(seg.text)

            slide["transcript_text"] = " ".join(matching_texts) if matching_texts else None

        return slides

    # ------------------------------------------------------------------
    # Step 7: Full Pipeline Orchestrator
    # ------------------------------------------------------------------

    def run_full_pipeline(
        self,
        db,
        job,
        cancel_check: Optional[Callable[[], bool]] = None,
        provider=None,
        model: Optional[str] = None,
    ) -> None:
        """
        Orchestrate the full slide detection pipeline.

        Args:
            db: SQLAlchemy session
            job: ProcessingJob ORM instance
            cancel_check: Optional callable returning True if cancelled
            provider: LLMProvider for ambiguous-transition classification (injected
                by the task so it uses the job owner's provider / the vLLM fleet)
            model: Concrete model id passed to the provider
        """
        from app.db.models import Slide, SlideDetectionMetadata

        start_time = time.time()
        video_path = job.video_file_path

        if not video_path or not Path(video_path).exists():
            raise SlideDetectionException("Video file not available for slide detection")

        job_uuid = job.job_id
        data_root = Path(os.environ.get(
            "DATA_DIR",
            Path(__file__).resolve().parent.parent.parent / "data",
        ))
        output_dir = str(data_root / "slides" / job_uuid)

        _add_log = self._make_log_fn(db, job.id)

        # 1. Layout detection
        _add_log("Detecting presentation layout...", "info", "slide_layout")
        if cancel_check and cancel_check():
            raise CancelledException()
        layout = self.layout_detection(video_path)
        _add_log(f"Layout detected: {layout}", "info", "slide_layout")

        # 2. Get video duration
        cap = cv2.VideoCapture(video_path)
        video_duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(cap.get(cv2.CAP_PROP_FPS), 1.0)
        cap.release()

        # 3. SSIM transition scan
        _add_log("Scanning for slide transitions (SSIM)...", "info", "slide_ssim")
        if cancel_check and cancel_check():
            raise CancelledException()
        transitions, total_frames_sampled = self.ssim_transition_scan(
            video_path, self.slide_settings.sampling_fps, layout
        )
        _add_log(f"Found {len(transitions)} potential transitions", "info", "slide_ssim")

        # 4. LLM classification for ambiguous transitions
        ambiguous_count = sum(1 for t in transitions if t.get("classification") == "ambiguous")
        llm_classifications = 0
        if ambiguous_count > 0:
            _add_log(f"Classifying {ambiguous_count} ambiguous transitions with LLM...", "info", "slide_llm")
            # Get OCR text for ambiguous frames to help LLM classify
            self._add_ocr_context_to_transitions(video_path, transitions, layout)
            transitions = self.llm_ambiguity_classification(
                transitions, cancel_check, provider=provider, model=model
            )
            llm_classifications = ambiguous_count

        # 5. Slide grouping
        _add_log("Grouping transitions into slides...", "info", "slide_grouping")
        if cancel_check and cancel_check():
            raise CancelledException()
        slide_dicts = self.slide_grouping(transitions, video_duration)
        _add_log(f"Grouped into {len(slide_dicts)} slides", "info", "slide_grouping")

        # 6. Final state capture + OCR
        _add_log("Capturing final-state frames and running OCR...", "info", "slide_capture")
        if cancel_check and cancel_check():
            raise CancelledException()
        slide_dicts = self.final_state_capture(video_path, slide_dicts, output_dir)

        # 7. Transcript alignment
        segments = []
        if job.transcripts:
            segments = sorted(job.transcripts[0].segments, key=lambda s: s.start_time)
        if segments:
            _add_log("Aligning transcript to slides...", "info", "slide_transcript")
            slide_dicts = self.transcript_alignment(slide_dicts, segments)

        # 8. Persist slides to DB
        _add_log("Saving slides to database...", "info", "slide_save")
        slide_models: Dict[int, Slide] = {}
        for sd in slide_dicts:
            slide = Slide(
                job_id=job.id,
                slide_number=sd["slide_number"],
                start_timestamp=sd["start_timestamp"],
                end_timestamp=sd["end_timestamp"],
                final_frame_path=sd.get("final_frame_path"),
                ocr_text=sd.get("ocr_text"),
                transcript_text=sd.get("transcript_text"),
                layout_type=layout,
                ssim_transition_score=sd.get("ssim_transition_score"),
                is_incremental_build=sd.get("is_incremental_build", False),
                image_width=sd.get("image_width"),
                image_height=sd.get("image_height"),
                file_size=sd.get("file_size"),
            )
            db.add(slide)
            db.flush()
            slide_models[sd["slide_number"]] = slide

        # Set parent relationships for incremental builds
        for sd in slide_dicts:
            parent_num = sd.get("parent_slide_number")
            if parent_num and parent_num in slide_models:
                slide_models[sd["slide_number"]].parent_slide_id = slide_models[parent_num].id

        # 9. Persist metadata
        metadata = SlideDetectionMetadata(
            job_id=job.id,
            total_frames_sampled=total_frames_sampled,
            sampling_fps=self.slide_settings.sampling_fps,
            ssim_threshold=self.slide_settings.ssim_threshold,
            ssim_ambiguous_low=self.slide_settings.ssim_ambiguous_low,
            ssim_ambiguous_high=self.slide_settings.ssim_ambiguous_high,
            layout_type_detected=layout,
            total_slides=len(slide_dicts),
            total_transitions=len(transitions),
            llm_classifications_count=llm_classifications,
            ocr_enabled=self.slide_settings.ocr_enabled,
            processing_time_seconds=time.time() - start_time,
        )
        db.add(metadata)
        db.commit()

        _add_log(
            f"Slide detection complete: {len(slide_dicts)} slides detected in {time.time() - start_time:.1f}s",
            "info",
            "slide_complete",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _crop_content_region(self, gray: np.ndarray, layout: str) -> np.ndarray:
        """Crop frame to content region based on layout type."""
        h, w = gray.shape[:2]

        if layout == "pip_speaker":
            # Crop out bottom-right 20% where speaker usually is
            return gray[:int(h * 0.8), :int(w * 0.8)]
        elif layout == "split_panel":
            # Use left half (usually the slides)
            return gray[:, :int(w * 0.5)]

        return gray

    def _compute_ssim(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """Compute SSIM between two grayscale images, resizing if needed."""
        # Ensure same size
        if img1.shape != img2.shape:
            h = min(img1.shape[0], img2.shape[0])
            w = min(img1.shape[1], img2.shape[1])
            img1 = cv2.resize(img1, (w, h))
            img2 = cv2.resize(img2, (w, h))

        # Minimum window size for SSIM
        min_dim = min(img1.shape[0], img1.shape[1])
        win_size = min(7, min_dim if min_dim % 2 == 1 else min_dim - 1)
        if win_size < 3:
            return 1.0  # Too small to compare meaningfully

        score, _ = structural_similarity(img1, img2, full=True, win_size=win_size)
        return float(score)

    def _extract_ocr_text(self, frame: np.ndarray) -> Optional[str]:
        """Run OCR on a single frame."""
        try:
            import pytesseract
            from PIL import Image

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            text = pytesseract.image_to_string(pil_img)
            return text.strip() if text.strip() else None
        except ImportError:
            logger.warning("pytesseract not installed, skipping OCR")
            return None
        except Exception as e:
            logger.warning(f"OCR failed: {e}")
            return None

    def _add_ocr_context_to_transitions(
        self, video_path: str, transitions: List[Dict], layout: str
    ) -> None:
        """Add OCR text context to ambiguous transitions for LLM classification."""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return

        video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        for t in transitions:
            if t.get("classification") != "ambiguous":
                continue

            frame_idx = t["frame_index"]

            # Get frame before transition
            before_idx = max(0, frame_idx - int(video_fps / self.slide_settings.sampling_fps))
            cap.set(cv2.CAP_PROP_POS_FRAMES, before_idx)
            ret, before_frame = cap.read()
            if ret:
                t["ocr_text_before"] = self._extract_ocr_text(before_frame)

            # Get frame at transition
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, after_frame = cap.read()
            if ret:
                t["ocr_text_after"] = self._extract_ocr_text(after_frame)

        cap.release()

    @staticmethod
    def _make_log_fn(db, job_id: int):
        """Create a log function bound to a job."""
        def _log(message: str, level: str = "info", step: str | None = None) -> None:
            try:
                from app.db.models import JobLog, LogLevel
                level_enum = LogLevel(level)
                log_entry = JobLog(job_id=job_id, level=level_enum, message=message[:1024], step=step)
                db.add(log_entry)
                db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
        return _log
