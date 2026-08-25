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
import pytesseract
from PIL import Image
from skimage.metrics import structural_similarity

from app.core.config import get_settings
from app.exceptions import SlideDetectionException
from app.services.llm import CancelledException

logger = logging.getLogger(__name__)


class SlideDetectionService:
    """Service that detects slides in presentation-style videos."""

    # Candidate regions are intentionally asymmetric as well as half-frame:
    # common interview/masterclass layouts reserve roughly 20-30% for a
    # presenter and put the actual deck in the remaining 70-80%.
    _CONTENT_CANDIDATES = (
        ("content_right", (0.22, 0.0, 1.0, 1.0)),
        ("content_left", (0.0, 0.0, 0.78, 1.0)),
        ("content_right", (0.45, 0.0, 1.0, 1.0)),
        ("content_left", (0.0, 0.0, 0.55, 1.0)),
        ("full_frame", (0.0, 0.0, 1.0, 1.0)),
    )

    def __init__(self) -> None:
        self.settings = get_settings()
        self.slide_settings = self.settings.slide_detection

    def _setting(self, name: str, default):
        """Return a concrete slide setting, tolerating legacy test doubles."""
        value = getattr(self.slide_settings, name, default)
        return value if isinstance(value, type(default)) else default

    @staticmethod
    def _crop_normalized(frame: np.ndarray, region) -> np.ndarray:
        """Crop ``frame`` using a normalized ``(x0, y0, x1, y1)`` region."""
        if not region:
            return frame
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = region
        left = max(0, min(w - 1, int(round(float(x0) * w))))
        top = max(0, min(h - 1, int(round(float(y0) * h))))
        right = max(left + 1, min(w, int(round(float(x1) * w))))
        bottom = max(top + 1, min(h, int(round(float(y1) * h))))
        return frame[top:bottom, left:right]

    @staticmethod
    def _resize_max_width(frame: np.ndarray, max_width: int) -> np.ndarray:
        """Reduce a frame before CV work while preserving its aspect ratio."""
        h, w = frame.shape[:2]
        if w <= max_width:
            return frame
        scale = max_width / float(w)
        return cv2.resize(
            frame,
            (max_width, max(1, int(round(h * scale)))),
            interpolation=cv2.INTER_AREA,
        )

    @staticmethod
    def _skin_mask(frame: np.ndarray) -> np.ndarray:
        """Cheap human-motion mask used to keep faces out of SSIM and OCR."""
        if frame.ndim != 3:
            return np.zeros(frame.shape[:2], dtype=np.uint8)
        ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
        cr = ycrcb[:, :, 1]
        cb = ycrcb[:, :, 2]
        mask = (
            (cr >= 133)
            & (cr <= 173)
            & (cb >= 77)
            & (cb <= 127)
        ).astype(np.uint8)
        kernel = np.ones((5, 5), dtype=np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=1)

        # Reject tiny compression speckles. Keep large regions: close-up faces
        # in speaker-only segments are intentionally strong negative evidence.
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        filtered = np.zeros_like(mask)
        minimum = max(8, int(mask.size * 0.001))
        for component in range(1, count):
            area = int(stats[component, cv2.CC_STAT_AREA])
            if area >= minimum:
                filtered[labels == component] = 1
        return filtered

    def _prepare_ocr_frame(self, frame: np.ndarray, region) -> np.ndarray:
        """Crop to slide content and blank residual presenter skin regions."""
        content = self._crop_normalized(frame, region).copy()
        mask = self._skin_mask(content)
        if np.any(mask):
            content[mask > 0] = 255
        return content

    def _slide_region_observation(self, frame: np.ndarray) -> Dict:
        """Locate likely slide content in one sampled frame.

        The score favours structured, sharp, low-skin regions and can return
        ``no_slide``.  This deliberately distinguishes a deck-on-the-right
        frame from a two-presenter split screen without OCR or an LLM call.
        """
        analysis_width = int(self._setting("layout_analysis_width", 320))
        presence_threshold = float(self._setting("slide_presence_score", 0.45))
        best: Optional[Dict] = None

        for layout, region in self._CONTENT_CANDIDATES:
            cropped = self._crop_normalized(frame, region)
            reduced = self._resize_max_width(cropped, analysis_width)
            if reduced.size == 0:
                continue

            gray = cv2.cvtColor(reduced, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 60, 160)
            edge_density = float(np.count_nonzero(edges)) / float(edges.size)
            detail = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            skin_ratio = float(np.count_nonzero(self._skin_mask(reduced))) / float(gray.size)
            area = max(0.0, (region[2] - region[0]) * (region[3] - region[1]))

            # Normalized on real masterclass frames: slides exhibit dense text/
            # line structure and little skin; speaker-only panels have lower
            # edge/detail scores and a much larger skin fraction.
            score = (
                0.45 * min(edge_density / 0.08, 1.0)
                + 0.25 * min(detail / 1000.0, 1.0)
                + 0.15 * area
                - 0.55 * min(skin_ratio / 0.12, 1.0)
            )
            candidate = {
                "layout": layout,
                "region": region,
                "score": max(0.0, min(1.0, score)),
                "slide_present": score >= presence_threshold,
            }
            if best is None or candidate["score"] > best["score"]:
                best = candidate

        if best is None or not best["slide_present"]:
            return {
                "layout": "no_slide",
                "region": None,
                "score": 0.0 if best is None else best["score"],
                "slide_present": False,
            }
        return best

    def _prepare_content_frame(self, frame: np.ndarray, region) -> Tuple[np.ndarray, np.ndarray]:
        """Return reduced grayscale content plus an expanded human/skin mask."""
        cropped = self._crop_normalized(frame, region)
        reduced = self._resize_max_width(
            cropped,
            int(self._setting("scan_max_width", 640)),
        )
        gray = cv2.cvtColor(reduced, cv2.COLOR_BGR2GRAY)
        return gray, self._skin_mask(reduced)

    def _masked_content_ssim(
        self,
        previous: Tuple[np.ndarray, np.ndarray],
        current: Tuple[np.ndarray, np.ndarray],
    ) -> float:
        """Compare content while neutralizing pixels likely to be human motion."""
        prev_gray, prev_skin = previous
        gray, skin = current
        if gray.shape != prev_gray.shape:
            gray = cv2.resize(gray, (prev_gray.shape[1], prev_gray.shape[0]), interpolation=cv2.INTER_AREA)
            skin = cv2.resize(skin, (prev_gray.shape[1], prev_gray.shape[0]), interpolation=cv2.INTER_NEAREST)
        if prev_skin.shape != prev_gray.shape:
            prev_skin = cv2.resize(
                prev_skin,
                (prev_gray.shape[1], prev_gray.shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )
        human = (prev_skin > 0) | (skin > 0)
        if np.any(human):
            prev_gray = prev_gray.copy()
            gray = gray.copy()
            # Identical neutral pixels make skin movement invisible to SSIM.
            prev_gray[human] = 127
            gray[human] = 127
        return self._compute_ssim(prev_gray, gray)

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
        self,
        video_path: str,
        fps: float,
        layout: str,
        *,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Tuple[List[Dict], int]:
        """Scan dynamically selected slide regions at ``fps``.

        Layout is re-evaluated per sampled frame and debounced into temporal
        segments. Speaker-only periods emit ``slide_end``/``slide_start``
        boundaries instead of becoming false slide transitions.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise SlideDetectionException("Cannot open video for SSIM scan")

        video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_skip = max(1, int(video_fps / fps))
        total_frames = max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
        estimated_samples = max(1, (total_frames + frame_skip - 1) // frame_skip)

        transitions: List[Dict] = []
        frame_idx = 0
        frames_sampled = 0
        confirm_samples = int(self._setting("layout_confirm_samples", 2))
        active_observation: Optional[Dict] = None
        pending_key: Optional[str] = None
        pending_count = 0
        pending_since = 0.0
        previous_content: Optional[Tuple[np.ndarray, np.ndarray]] = None

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_skip == 0:
                if cancel_check and cancel_check():
                    from app.services.llm import CancelledException

                    cap.release()
                    raise CancelledException()

                timestamp = frame_idx / video_fps
                observed = self._slide_region_observation(frame)
                observed_key = observed["layout"]

                if active_observation is None:
                    active_observation = observed
                    if observed["slide_present"]:
                        transitions.append({
                            "frame_index": frame_idx,
                            "timestamp": timestamp,
                            "ssim": 1.0,
                            "classification": "slide_start",
                            "layout_type": observed["layout"],
                            "content_region": observed["region"],
                        })
                        previous_content = self._prepare_content_frame(frame, observed["region"])
                elif observed_key != active_observation["layout"]:
                    if pending_key == observed_key:
                        pending_count += 1
                    else:
                        pending_key = observed_key
                        pending_count = 1
                        pending_since = timestamp

                    if pending_count >= confirm_samples:
                        if active_observation["slide_present"]:
                            transitions.append({
                                "frame_index": frame_idx,
                                "timestamp": pending_since,
                                "ssim": 1.0,
                                "classification": "slide_end",
                                "layout_type": active_observation["layout"],
                                "content_region": active_observation["region"],
                            })
                        active_observation = observed
                        previous_content = None
                        if observed["slide_present"]:
                            transitions.append({
                                "frame_index": frame_idx,
                                "timestamp": pending_since,
                                "ssim": 1.0,
                                "classification": "slide_start",
                                "layout_type": observed["layout"],
                                "content_region": observed["region"],
                            })
                            previous_content = self._prepare_content_frame(frame, observed["region"])
                        pending_key = None
                        pending_count = 0
                    # A suspected layout boundary is not a content transition.
                else:
                    pending_key = None
                    pending_count = 0
                    if active_observation["slide_present"]:
                        current_content = self._prepare_content_frame(
                            frame,
                            active_observation["region"],
                        )
                        if previous_content is not None:
                            ssim_val = self._masked_content_ssim(previous_content, current_content)
                            if layout == "pip_speaker":
                                threshold = self.slide_settings.pip_speaker_ssim_threshold
                                ambig_low = self.slide_settings.pip_speaker_ssim_ambiguous_low
                                ambig_high = self.slide_settings.pip_speaker_ssim_ambiguous_high
                            else:
                                threshold = self.slide_settings.ssim_threshold
                                ambig_low = self.slide_settings.ssim_ambiguous_low
                                ambig_high = self.slide_settings.ssim_ambiguous_high

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
                                    "layout_type": active_observation["layout"],
                                    "content_region": active_observation["region"],
                                })
                        previous_content = current_content

                frames_sampled += 1
                if progress_callback:
                    progress_callback(frames_sampled, estimated_samples)

            frame_idx += 1

        cap.release()
        content_transitions = sum(
            1
            for item in transitions
            if item.get("classification") in ("transition", "ambiguous")
        )
        logger.info(
            "Dynamic SSIM scan: %d frames sampled, %d transitions, %d temporal boundaries (initial=%s)",
            frames_sampled,
            content_transitions,
            len(transitions) - content_transitions,
            layout,
        )
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

        WP3: batched by default (bounded structured requests with stable item ids,
        schema validation, retry-only-failed-items, deterministic ordering, and a
        sequential fallback). The batch size is configurable; ``batch_size=1``
        preserves the legacy one-call-per-transition behavior.

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

        batch_size = self.slide_settings.llm_batch_size
        if batch_size <= 1:
            return self._classify_sequential(
                pairs, cancel_check, provider, model
            )
        return self._classify_batched(
            pairs, cancel_check, provider, model, batch_size
        )

    def _classify_sequential(
        self,
        pairs: List[Dict],
        cancel_check: Optional[Callable[[], bool]],
        provider,
        model: Optional[str],
    ) -> List[Dict]:
        """Legacy one-call-per-ambiguous-transition classification (fallback)."""
        model = model or self.slide_settings.llm_model
        timeout = self.slide_settings.llm_timeout
        incremental_threshold = self.slide_settings.incremental_ssim_threshold
        classified = 0

        for pair in pairs:
            if cancel_check and cancel_check():
                raise CancelledException()

            if pair.get("classification") != "ambiguous":
                continue

            if self._apply_fast_path(pair, incremental_threshold):
                classified += 1
                continue

            prompt = self._build_classification_prompt(pair)
            try:
                answer = provider.generate(prompt, model, timeout=timeout, max_tokens=10).strip().upper()
                pair["llm_classification"] = self._parse_answer(answer)
                classified += 1
            except Exception as e:
                logger.warning(f"LLM classification failed: {e}")
                pair["llm_classification"] = "transition"

        logger.info(f"LLM classified {classified} ambiguous transitions (sequential)")
        return pairs

    def _classify_batched(
        self,
        pairs: List[Dict],
        cancel_check: Optional[Callable[[], bool]],
        provider,
        model: Optional[str],
        batch_size: int,
    ) -> List[Dict]:
        """Batched classification with stable ids, schema validation, and fallback.

        Each batch is a single structured request carrying stable item ids
        (``t_<index>``) so results map deterministically back onto the pairs.
        Items whose answer fails schema validation are retried sequentially;
        a whole-batch failure falls back to sequential classification for that
        batch. Bounded concurrency: batches run sequentially by default (the
        sidecar lease authorizes one lane); ``llm_batch_concurrency`` > 1 uses
        a bounded thread pool for deployments with multi-slot leases.
        """
        model = model or self.slide_settings.llm_model
        timeout = self.slide_settings.llm_timeout
        incremental_threshold = self.slide_settings.incremental_ssim_threshold
        concurrency = self.slide_settings.llm_batch_concurrency

        ambiguous = [
            (i, pair)
            for i, pair in enumerate(pairs)
            if pair.get("classification") == "ambiguous"
        ]
        if not ambiguous:
            return pairs

        # Fast-path items never hit the LLM.
        for _, pair in ambiguous:
            if pair.get("ssim", 0) >= incremental_threshold:
                pair["llm_classification"] = "incremental"

        to_classify = [
            (i, pair)
            for i, pair in ambiguous
            if pair.get("llm_classification") is None
        ]
        batches = [
            to_classify[offset : offset + batch_size]
            for offset in range(0, len(to_classify), batch_size)
        ]

        classified = 0

        def classify_batch(batch: List[tuple]) -> int:
            """Return number classified in this batch."""
            if cancel_check and cancel_check():
                raise CancelledException()
            items = [
                {
                    "id": f"t_{i}",
                    "ssim": pair.get("ssim", 0),
                    "ocr_text_before": (pair.get("ocr_text_before") or "")[:500],
                    "ocr_text_after": (pair.get("ocr_text_after") or "")[:500],
                }
                for i, pair in batch
            ]
            prompt = self._build_batch_prompt(items)
            try:
                answer = provider.generate(
                    prompt, model, timeout=timeout, max_tokens=min(4000, 40 + 20 * len(items))
                ).strip()
                results = self._parse_batch_answer(answer)
            except Exception as e:
                logger.warning(f"Batch LLM classification failed ({len(batch)} items): {e}")
                results = {}

            count = 0
            retry_items: List[tuple] = []
            for i, pair in batch:
                item_id = f"t_{i}"
                label = results.get(item_id)
                if label in ("transition", "incremental"):
                    pair["llm_classification"] = label
                    count += 1
                else:
                    retry_items.append((i, pair))

            # Retry only failed items sequentially (schema validation fallback).
            for i, pair in retry_items:
                if cancel_check and cancel_check():
                    raise CancelledException()
                if self._apply_fast_path(pair, incremental_threshold):
                    count += 1
                    continue
                try:
                    answer = provider.generate(
                        self._build_classification_prompt(pair),
                        model,
                        timeout=timeout,
                        max_tokens=10,
                    ).strip().upper()
                    pair["llm_classification"] = self._parse_answer(answer)
                    count += 1
                except Exception as e:
                    logger.warning(f"LLM classification retry failed: {e}")
                    pair["llm_classification"] = "transition"
                    count += 1
            return count

        if concurrency <= 1:
            for batch in batches:
                classified += classify_batch(batch)
        else:
            # Bounded concurrency under the lease: at most ``concurrency``
            # batches in flight (plan §3).
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(classify_batch, batch) for batch in batches]
                for future in futures:
                    try:
                        classified += future.result()
                    except CancelledException:
                        for f in futures:
                            f.cancel()
                        raise

        logger.info(
            f"LLM classified {classified} ambiguous transitions "
            f"(batched, {len(batches)} batches)"
        )
        return pairs

    @staticmethod
    def _apply_fast_path(pair: Dict, incremental_threshold: float) -> bool:
        """High-confidence incremental bypasses the LLM entirely."""
        if pair.get("ssim", 0) >= incremental_threshold:
            pair["llm_classification"] = "incremental"
            return True
        return False

    @staticmethod
    def _build_classification_prompt(pair: Dict) -> str:
        ssim_val = pair.get("ssim", 0)
        text_before = (pair.get("ocr_text_before") or "")[:500]
        text_after = (pair.get("ocr_text_after") or "")[:500]
        return (
            "You are analysing a presentation video. Two consecutive frames have an SSIM "
            f"similarity of {ssim_val:.3f} (1.0 = identical, 0.0 = completely different).\n\n"
            f"OCR text from the BEFORE frame:\n{text_before or '(no text detected)'}\n\n"
            f"OCR text from the AFTER frame:\n{text_after or '(no text detected)'}\n\n"
            "Is this a NEW SLIDE (completely different content) or an INCREMENTAL BUILD "
            "(same slide with added content like bullet points)?\n\n"
            "Respond with exactly one word: TRANSITION or INCREMENTAL"
        )

    @staticmethod
    def _parse_answer(answer: str) -> str:
        return "incremental" if "INCREMENTAL" in answer else "transition"

    @staticmethod
    def _build_batch_prompt(items: List[Dict]) -> str:
        """One structured batch request with stable item ids."""
        lines = []
        for item in items:
            lines.append(
                f"[{item['id']}] ssim={item['ssim']:.3f} | "
                f"before={item['ocr_text_before'] or '(no text)'} | "
                f"after={item['ocr_text_after'] or '(no text)'}"
            )
        return (
            "You are analysing a presentation video. Classify each ambiguous frame pair "
            "below as either TRANSITION (new slide, different content) or INCREMENTAL "
            "(same slide with added content).\n\n"
            + "\n".join(lines)
            + "\n\nRespond with exactly one line per item, in the format "
            "<id>: TRANSITION or <id>: INCREMENTAL, nothing else."
        )

    @classmethod
    def _parse_batch_answer(cls, answer: str) -> Dict[str, str]:
        """Parse the batch response into {item_id: label}.

        Schema validation: only lines matching ``t_<digits>: TRANSITION|INCREMENTAL``
        are accepted; anything else is treated as missing (retried sequentially).
        """
        import re

        pattern = re.compile(r"^(t_\d+)\s*[:\-]\s*(TRANSITION|INCREMENTAL)\b", re.IGNORECASE)
        results: Dict[str, str] = {}
        for line in answer.splitlines():
            line = line.strip()
            if not line:
                continue
            m = pattern.match(line)
            if m:
                results[m.group(1)] = "incremental" if m.group(2).upper() == "INCREMENTAL" else "transition"
        return results

    # ------------------------------------------------------------------
    # Step 4: Slide Grouping
    # ------------------------------------------------------------------

    def slide_grouping(
        self, transitions: List[Dict], video_duration: float, layout: str = "full_frame"
    ) -> List[Dict]:
        """
        Merge incremental builds, enforce minimum duration, and assign slide numbers.

        Returns list of slide dicts:
            {"slide_number": int, "start_timestamp": float, "end_timestamp": float,
             "ssim_transition_score": float, "is_incremental_build": bool,
             "parent_slide_number": Optional[int]}
        """
        if any(
            item.get("classification") in ("slide_start", "slide_end")
            for item in transitions
        ):
            return self._segmented_slide_grouping(transitions, video_duration, layout)

        if layout == "pip_speaker":
            min_duration = self.slide_settings.pip_speaker_min_slide_duration
        else:
            min_duration = self.slide_settings.min_slide_duration

        # Separate real transitions from incremental builds
        real_transitions = []
        incremental_transitions = []
        for t in transitions:
            if self._final_classification(t) == "incremental":
                incremental_transitions.append(t)
            else:
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

        # Attach incremental builds as child slides with parent links
        child_num = len(slides) + 1
        for t in sorted(incremental_transitions, key=lambda x: x["timestamp"]):
            ts = t["timestamp"]
            parent_num = None
            for s in reversed(slides):
                if not s.get("is_incremental_build") and s["start_timestamp"] <= ts:
                    parent_num = s["slide_number"]
                    break
            slides.append({
                "slide_number": child_num,
                "start_timestamp": ts,
                "end_timestamp": video_duration,
                "ssim_transition_score": t.get("ssim", 0.0),
                "is_incremental_build": True,
                "parent_slide_number": parent_num,
            })
            child_num += 1

        non_incr = sum(1 for s in slides if not s["is_incremental_build"])
        logger.info(f"Grouped into {len(slides)} slides ({non_incr} non-incremental, {len(incremental_transitions)} incremental)")
        return slides

    def _segmented_slide_grouping(
        self,
        transitions: List[Dict],
        video_duration: float,
        default_layout: str,
    ) -> List[Dict]:
        """Build slides only inside dynamically detected slide-present segments."""
        segments: List[Dict] = []
        active: Optional[Dict] = None

        for item in sorted(transitions, key=lambda row: row["timestamp"]):
            classification = item.get("classification")
            timestamp = max(0.0, min(video_duration, float(item["timestamp"])))
            if classification == "slide_start":
                if active is not None and timestamp > active["start"]:
                    active["end"] = timestamp
                    segments.append(active)
                active = {
                    "start": timestamp,
                    "end": video_duration,
                    "layout_type": item.get("layout_type") or default_layout,
                    "content_region": item.get("content_region"),
                    "events": [],
                }
            elif classification == "slide_end":
                if active is not None and timestamp > active["start"]:
                    active["end"] = timestamp
                    segments.append(active)
                active = None
            elif active is not None and classification in ("transition", "ambiguous"):
                active["events"].append(item)

        if active is not None and video_duration > active["start"]:
            active["end"] = video_duration
            segments.append(active)

        slides: List[Dict] = []
        incremental_events: List[Tuple[Dict, Dict]] = []
        for segment in segments:
            min_duration = (
                self.slide_settings.pip_speaker_min_slide_duration
                if default_layout == "pip_speaker" or segment["layout_type"] == "pip_speaker"
                else self.slide_settings.min_slide_duration
            )
            real_events: List[Dict] = []
            previous_start = segment["start"]
            for event in sorted(segment["events"], key=lambda row: row["timestamp"]):
                if self._final_classification(event) == "incremental":
                    incremental_events.append((event, segment))
                    continue
                if event["timestamp"] - previous_start < min_duration:
                    continue
                real_events.append(event)
                previous_start = event["timestamp"]

            starts = [segment["start"]] + [float(event["timestamp"]) for event in real_events]
            sources = [None] + real_events
            for index, start in enumerate(starts):
                end = starts[index + 1] if index + 1 < len(starts) else segment["end"]
                if end <= start:
                    continue
                source = sources[index]
                slides.append({
                    "slide_number": 0,
                    "start_timestamp": start,
                    "end_timestamp": end,
                    "ssim_transition_score": source.get("ssim", 0.0) if source else 0.0,
                    "is_incremental_build": False,
                    "parent_slide_number": None,
                    "layout_type": (source or {}).get("layout_type") or segment["layout_type"],
                    "content_region": (source or {}).get("content_region") or segment["content_region"],
                })

        slides.sort(key=lambda row: row["start_timestamp"])
        for index, slide in enumerate(slides, start=1):
            slide["slide_number"] = index

        child_num = len(slides) + 1
        for event, segment in sorted(incremental_events, key=lambda pair: pair[0]["timestamp"]):
            timestamp = float(event["timestamp"])
            parent = next(
                (
                    slide
                    for slide in reversed(slides)
                    if not slide["is_incremental_build"]
                    and slide["start_timestamp"] <= timestamp < slide["end_timestamp"]
                ),
                None,
            )
            if parent is None:
                continue
            slides.append({
                "slide_number": child_num,
                "start_timestamp": timestamp,
                "end_timestamp": parent["end_timestamp"],
                "ssim_transition_score": event.get("ssim", 0.0),
                "is_incremental_build": True,
                "parent_slide_number": parent["slide_number"],
                "layout_type": event.get("layout_type") or segment["layout_type"],
                "content_region": event.get("content_region") or segment["content_region"],
            })
            child_num += 1

        non_incremental = sum(1 for slide in slides if not slide["is_incremental_build"])
        logger.info(
            "Segmented grouping produced %d slides in %d slide-present segments (%d non-incremental)",
            len(slides),
            len(segments),
            non_incremental,
        )
        return slides

    # ------------------------------------------------------------------
    # Step 5: Final State Capture
    # ------------------------------------------------------------------

    def final_state_capture(
        self,
        video_path: str,
        slides: List[Dict],
        output_dir: str,
        frame_ocr_cache: Optional[Dict[int, Optional[str]]] = None,
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
                if frame_ocr_cache is not None and frame_idx in frame_ocr_cache:
                    slide["ocr_text"] = frame_ocr_cache[frame_idx]
                else:
                    ocr_frame = self._prepare_ocr_frame(
                        frame,
                        slide.get("content_region"),
                    )
                    slide["ocr_text"] = self._extract_ocr_text(ocr_frame)

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
        from app.services.job_steps import set_step_progress

        def _progress(percent: int) -> None:
            """Persist monotonic progress on the slides step (WP5)."""
            try:
                claim = next(
                    (s.claim_token for s in job.steps if s.name == "slides" and s.claim_token),
                    None,
                )
                if claim:
                    set_step_progress(db, job.id, "slides", claim, percent)
                    db.commit()
            except Exception:
                db.rollback()

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
        video_duration = self._get_video_duration(cap)
        cap.release()

        # 3. SSIM transition scan
        _add_log("Scanning for slide transitions (SSIM)...", "info", "slide_ssim")
        if cancel_check and cancel_check():
            raise CancelledException()

        scan_progress = {"percent": 0}

        def _scan_progress(done: int, total: int) -> None:
            percent = max(1, min(14, int(done / max(total, 1) * 14)))
            if percent > scan_progress["percent"]:
                scan_progress["percent"] = percent
                _progress(percent)

        transitions, total_frames_sampled = self.ssim_transition_scan(
            video_path,
            self.slide_settings.sampling_fps,
            layout,
            progress_callback=_scan_progress,
            cancel_check=cancel_check,
        )
        _progress(15)
        content_transition_count = sum(
            1
            for item in transitions
            if item.get("classification") in ("transition", "ambiguous")
        )
        boundary_count = len(transitions) - content_transition_count
        _add_log(
            f"Found {content_transition_count} potential transitions across "
            f"{boundary_count} slide-presence boundaries",
            "info",
            "slide_ssim",
        )

        # 4. LLM classification for ambiguous transitions
        ambiguous_count = sum(1 for t in transitions if t.get("classification") == "ambiguous")
        llm_classifications = 0
        frame_ocr_cache: Dict[int, Optional[str]] = {}
        if ambiguous_count > 0:
            _add_log(f"Classifying {ambiguous_count} ambiguous transitions with LLM...", "info", "slide_llm")
            # Get OCR text for ambiguous frames; cache is reused by final_state_capture
            frame_ocr_cache = self._add_ocr_context_to_transitions(video_path, transitions, layout)
            _progress(30)
            transitions = self.llm_ambiguity_classification(
                transitions, cancel_check, provider=provider, model=model
            )
            llm_classifications = ambiguous_count
            _progress(55)

        # 5. Slide grouping
        _add_log("Grouping transitions into slides...", "info", "slide_grouping")
        if cancel_check and cancel_check():
            raise CancelledException()
        slide_dicts = self.slide_grouping(transitions, video_duration, layout)
        _add_log(f"Grouped into {len(slide_dicts)} slides", "info", "slide_grouping")

        # 6. Final state capture + OCR
        _add_log("Capturing final-state frames and running OCR...", "info", "slide_capture")
        if cancel_check and cancel_check():
            raise CancelledException()
        slide_dicts = self.final_state_capture(video_path, slide_dicts, output_dir, frame_ocr_cache=frame_ocr_cache)
        _progress(85)

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
                layout_type=sd.get("layout_type", layout),
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
        observed_layouts = {
            item.get("layout_type")
            for item in transitions
            if item.get("layout_type") and item.get("classification") != "slide_end"
        }
        metadata_layout = (
            next(iter(observed_layouts))
            if len(observed_layouts) == 1
            else "dynamic"
            if observed_layouts
            else layout
        )
        metadata = SlideDetectionMetadata(
            job_id=job.id,
            total_frames_sampled=total_frames_sampled,
            sampling_fps=self.slide_settings.sampling_fps,
            ssim_threshold=self.slide_settings.ssim_threshold,
            ssim_ambiguous_low=self.slide_settings.ssim_ambiguous_low,
            ssim_ambiguous_high=self.slide_settings.ssim_ambiguous_high,
            layout_type_detected=metadata_layout,
            total_slides=len(slide_dicts),
            total_transitions=content_transition_count,
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

    def _get_video_duration(self, cap) -> float:
        """Derive video duration in seconds from an open VideoCapture.

        Falls back to a seek-to-end + POS_MSEC read for containers (VBR,
        streaming) where CAP_PROP_FRAME_COUNT reports 0.
        """
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = cap.get(cv2.CAP_PROP_FPS) or 1.0
        duration = frame_count / fps
        if duration > 0:
            return duration
        cap.set(cv2.CAP_PROP_POS_AVI_RATIO, 1.0)
        duration_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
        return duration_ms / 1000.0

    def _crop_content_region(self, gray: np.ndarray, layout: str) -> np.ndarray:
        """Crop frame to content region based on layout type."""
        h, w = gray.shape[:2]

        if layout == "pip_speaker":
            # Crop out bottom-right 20% where speaker usually is
            return gray[:int(h * 0.8), :int(w * 0.8)]
        elif layout == "content_right":
            return gray[:, int(w * 0.22):]
        elif layout == "content_left":
            return gray[:, :int(w * 0.78)]
        elif layout == "split_panel":
            # Legacy fallback only. Dynamic scans choose content_left or
            # content_right from evidence instead of assuming a side.
            return gray

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
        """Run OCR on a single frame with preprocessing for small text.

        Slides in pip_speaker layouts are small within the frame (frames can
        be 640x360), so raw tesseract output is noisy. Empirically (tested on
        real 640x360 slide frames, 2026-08-08): a 3x INTER_CUBIC upscale of
        the plain grayscale frame beats both adaptive thresholding and
        binarization — compressed-video noise turns any thresholding into
        salt-and-pepper garble, while tesseract handles the upscaled
        grayscale directly. PSM 6 (uniform block) suits slide layouts.
        """
        try:
            if frame.ndim == 3:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                gray = frame

            # Upscale 3x so small slide text becomes readable (no threshold:
            # binarizing compressed video destroys code text)
            h, w = gray.shape[:2]
            gray = cv2.resize(gray, (w * 3, h * 3), interpolation=cv2.INTER_CUBIC)

            pil_img = Image.fromarray(gray)
            text = pytesseract.image_to_string(pil_img, config="--psm 6 --oem 3")
            return text.strip() if text.strip() else None
        except ImportError:
            logger.warning("pytesseract not installed, skipping OCR")
            return None
        except Exception as e:
            logger.warning(f"OCR failed: {e}")
            return None

    def _add_ocr_context_to_transitions(
        self, video_path: str, transitions: List[Dict], layout: str
    ) -> Dict[int, Optional[str]]:
        """Add OCR text context to ambiguous transitions for LLM classification.

        Returns a frame_index → ocr_text cache so final_state_capture can skip
        re-running Tesseract on frames already processed here.
        """
        frame_ocr_cache: Dict[int, Optional[str]] = {}
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return frame_ocr_cache

        video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        for t in transitions:
            if t.get("classification") != "ambiguous":
                continue

            frame_idx = t["frame_index"]
            content_region = t.get("content_region")

            # Get frame before transition (deduplicated via cache)
            before_idx = max(0, frame_idx - int(video_fps / self.slide_settings.sampling_fps))
            if before_idx not in frame_ocr_cache:
                cap.set(cv2.CAP_PROP_POS_FRAMES, before_idx)
                ret, before_frame = cap.read()
                ocr = (
                    self._extract_ocr_text(
                        self._prepare_ocr_frame(before_frame, content_region)
                    )
                    if ret
                    else None
                )
                frame_ocr_cache[before_idx] = ocr
            t["ocr_text_before"] = frame_ocr_cache[before_idx]

            # Get frame at transition (deduplicated via cache)
            if frame_idx not in frame_ocr_cache:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, after_frame = cap.read()
                ocr = (
                    self._extract_ocr_text(
                        self._prepare_ocr_frame(after_frame, content_region)
                    )
                    if ret
                    else None
                )
                frame_ocr_cache[frame_idx] = ocr
            t["ocr_text_after"] = frame_ocr_cache[frame_idx]

        cap.release()
        return frame_ocr_cache

    @staticmethod
    def _final_classification(transition: Dict) -> str:
        """Resolve the final classification for a transition dict (llm_classification wins over classification)."""
        return transition.get("llm_classification", transition.get("classification", "transition"))

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
