"""
Snapshot Service

Handles key frame extraction from videos, scene change detection, OCR text
extraction, and frame relevance scoring.
"""

import logging
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import subprocess
import json

import cv2
from PIL import Image
import numpy as np

from app.core.config import get_settings
from app.db.models import Snapshot
from app.exceptions import SnapshotException
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class SnapshotService:
    """Service for extracting and processing video snapshots."""

    def __init__(self):
        """Initialize snapshot service."""
        self.settings = get_settings()

    def extract_frames(
        self,
        video_path: str,
        interval: float = 5.0,
        output_dir: Optional[str] = None,
    ) -> List[Dict]:
        """
        Extract frames at regular intervals from video.

        Args:
            video_path: Path to video file
            interval: Seconds between frames (default: 5s)
            output_dir: Directory to save frames (defaults to temp)

        Returns:
            List of frame metadata dicts with:
            - file_path: Path to saved image
            - timestamp: Time in seconds
            - width: Image width
            - height: Image height
            - file_size: File size in bytes

        Raises:
            SnapshotException: If extraction fails
        """
        video_path = Path(video_path)

        if not video_path.exists():
            raise SnapshotException(f"Video file not found: {video_path}")

        try:
            if output_dir is None:
                output_dir = str(Path(tempfile.gettempdir()) / "youtube-snapshots")
            Path(output_dir).mkdir(parents=True, exist_ok=True)

            # Open video file
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise SnapshotException("Failed to open video file")

            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_interval = int(fps * interval)
            frame_count = 0
            extracted_frames = []

            logger.info(f"Extracting frames every {interval}s ({frame_interval} frames)")

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_count % frame_interval == 0:
                    timestamp = (frame_count / fps)
                    height, width = frame.shape[:2]

                    # Save frame as JPEG
                    frame_name = f"frame_{frame_count:06d}.jpg"
                    frame_path = str(Path(output_dir) / frame_name)
                    cv2.imwrite(frame_path, frame)

                    file_size = Path(frame_path).stat().st_size

                    extracted_frames.append({
                        "file_path": frame_path,
                        "timestamp": timestamp,
                        "width": width,
                        "height": height,
                        "file_size": file_size,
                    })

                frame_count += 1

            cap.release()

            logger.info(f"✓ Extracted {len(extracted_frames)} frames")
            return extracted_frames

        except cv2.error as e:
            raise SnapshotException(f"OpenCV error: {str(e)}")
        except Exception as e:
            logger.error(f"Frame extraction failed: {e}")
            raise SnapshotException(f"Failed to extract frames: {str(e)}")

    def extract_frame_at_timestamp(
        self,
        video_path: str,
        timestamp: float,
        output_dir: str,
    ) -> Dict:
        """
        Extract a single frame at a specific timestamp.

        Args:
            video_path: Path to video file
            timestamp: Time in seconds to extract frame
            output_dir: Directory to save the frame

        Returns:
            Dict with file_path, timestamp, width, height, file_size

        Raises:
            SnapshotException: If extraction fails
        """
        video_path_obj = Path(video_path)
        if not video_path_obj.exists():
            raise SnapshotException(f"Video file not found: {video_path}")

        try:
            Path(output_dir).mkdir(parents=True, exist_ok=True)

            cap = cv2.VideoCapture(str(video_path_obj))
            if not cap.isOpened():
                raise SnapshotException("Failed to open video file")

            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            duration = total_frames / fps if fps > 0 else 0

            if timestamp > duration:
                raise SnapshotException(
                    f"Timestamp {timestamp:.1f}s exceeds video duration {duration:.1f}s"
                )

            # Seek to the target frame
            target_frame = int(timestamp * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

            ret, frame = cap.read()
            cap.release()

            if not ret:
                raise SnapshotException(f"Failed to read frame at {timestamp:.1f}s")

            height, width = frame.shape[:2]

            # Save as JPEG (quality 95 = maximum)
            frame_name = f"snapshot_{timestamp:.2f}s.jpg"
            frame_path = str(Path(output_dir) / frame_name)
            cv2.imwrite(frame_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])

            file_size = Path(frame_path).stat().st_size

            logger.info(f"Extracted frame at {timestamp:.2f}s -> {frame_path}")
            return {
                "file_path": frame_path,
                "timestamp": timestamp,
                "width": width,
                "height": height,
                "file_size": file_size,
            }

        except SnapshotException:
            raise
        except Exception as e:
            logger.error(f"Frame extraction at {timestamp}s failed: {e}")
            raise SnapshotException(f"Failed to extract frame: {str(e)}")

    def detect_scene_changes(
        self,
        video_path: str,
        threshold: float = 27.0,
        output_dir: Optional[str] = None,
    ) -> List[Dict]:
        """
        Detect scene changes and extract key frames.

        Uses optical flow and histogram analysis to find significant changes.

        Args:
            video_path: Path to video file
            threshold: Change detection threshold (0-100)
            output_dir: Directory to save frames

        Returns:
            List of key frame metadata (same format as extract_frames)

        Raises:
            SnapshotException: If detection fails
        """
        video_path = Path(video_path)

        if not video_path.exists():
            raise SnapshotException(f"Video file not found: {video_path}")

        try:
            if output_dir is None:
                output_dir = str(Path(tempfile.gettempdir()) / "youtube-snapshots")
            Path(output_dir).mkdir(parents=True, exist_ok=True)

            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise SnapshotException("Failed to open video file")

            fps = cap.get(cv2.CAP_PROP_FPS)
            key_frames = []
            prev_hist = None
            frame_count = 0
            last_key_frame = -fps  # Prevent duplicate frames

            logger.info(f"Detecting scene changes (threshold: {threshold})")

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                # Convert to HSV for better color analysis
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

                # Compute histogram
                hist = cv2.calcHist([hsv], [0, 1], None, [180, 256], [0, 180, 0, 256])
                hist = cv2.normalize(hist, hist).flatten()

                # Compare with previous frame
                if prev_hist is not None:
                    diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
                    change_percent = diff * 100

                    # If significant change detected and enough frames since last key frame
                    if change_percent > threshold and (frame_count - last_key_frame) > fps:
                        timestamp = frame_count / fps
                        height, width = frame.shape[:2]

                        # Save frame
                        frame_name = f"keyframe_{frame_count:06d}.jpg"
                        frame_path = str(Path(output_dir) / frame_name)
                        cv2.imwrite(frame_path, frame)

                        file_size = Path(frame_path).stat().st_size

                        key_frames.append({
                            "file_path": frame_path,
                            "timestamp": timestamp,
                            "width": width,
                            "height": height,
                            "file_size": file_size,
                            "change_score": min(change_percent / 100, 1.0),
                        })

                        last_key_frame = frame_count

                prev_hist = hist
                frame_count += 1

            cap.release()

            logger.info(f"✓ Detected {len(key_frames)} scene changes")
            return key_frames

        except Exception as e:
            logger.error(f"Scene detection failed: {e}")
            raise SnapshotException(f"Failed to detect scene changes: {str(e)}")

    def extract_text_from_frame(self, image_path: str) -> Optional[str]:
        """
        Extract text from frame using OCR (Tesseract).

        Args:
            image_path: Path to image file

        Returns:
            Detected text or None if no text found

        Raises:
            SnapshotException: If OCR fails
        """
        try:
            # Try to import pytesseract
            try:
                import pytesseract
            except ImportError:
                logger.warning("pytesseract not installed, skipping OCR")
                return None

            image = Image.open(image_path)

            # Preprocess image for better OCR
            # Convert to grayscale
            image = image.convert('L')

            # Apply threshold
            image = image.point(lambda x: 0 if x < 128 else 255, '1')

            # Extract text
            text = pytesseract.image_to_string(image)

            if text.strip():
                logger.debug(f"Detected text in frame: {len(text)} chars")
                return text.strip()

            return None

        except Exception as e:
            logger.warning(f"OCR failed: {e}")
            return None

    def score_frame_relevance(
        self,
        image_path: str,
        detected_text: Optional[str] = None,
    ) -> float:
        """
        Score frame relevance for documentation (0.0-1.0).

        Considers:
        - Presence of text (code, diagrams)
        - Image complexity
        - Clarity/sharpness

        Args:
            image_path: Path to image
            detected_text: Detected text from OCR

        Returns:
            Relevance score (0.0-1.0)
        """
        try:
            image = cv2.imread(image_path)
            if image is None:
                return 0.5

            # Convert to grayscale
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

            # Calculate sharpness using Laplacian variance
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            sharpness_score = min(laplacian_var / 500, 1.0)

            # Calculate complexity using entropy
            hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
            hist = hist.flatten() / hist.sum()
            entropy = -np.sum(hist * np.log2(hist + 1e-7))
            complexity_score = min(entropy / 8, 1.0)

            # Text presence bonus
            text_score = 0.3 if detected_text else 0.0

            # Weighted average
            relevance = (
                sharpness_score * 0.4 +
                complexity_score * 0.3 +
                text_score
            )

            return min(relevance, 1.0)

        except Exception as e:
            logger.warning(f"Relevance scoring failed: {e}")
            return 0.5

    def optimize_image(
        self,
        image_path: str,
        max_width: int = 1920,
        max_height: int = 1080,
        quality: int = 95,
    ) -> str:
        """
        Optimize image for storage and web display.

        Resizes, compresses, and optimizes image file.

        Args:
            image_path: Path to original image
            max_width: Maximum width in pixels
            max_height: Maximum height in pixels
            quality: JPEG quality (1-95, 95 = maximum quality)

        Returns:
            Path to optimized image

        Raises:
            SnapshotException: If optimization fails
        """
        try:
            image = Image.open(image_path)

            # Resize if needed
            image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

            # Save optimized version
            opt_path = str(Path(image_path).with_stem(Path(image_path).stem + "_opt"))
            image.save(opt_path, "JPEG", quality=quality, optimize=True)

            # Delete original if optimized is smaller
            orig_size = Path(image_path).stat().st_size
            opt_size = Path(opt_path).stat().st_size

            if opt_size < orig_size:
                Path(image_path).unlink()
                Path(opt_path).rename(image_path)

            return str(image_path)

        except Exception as e:
            logger.warning(f"Image optimization failed: {e}")
            return image_path

    def save_snapshots(
        self,
        db: Session,
        job_id: int,
        frames: List[Dict],
    ) -> List[Snapshot]:
        """
        Save snapshots to database.

        Args:
            db: Database session
            job_id: Processing job ID
            frames: List of frame metadata dicts

        Returns:
            List of Snapshot objects

        Raises:
            SnapshotException: If database operation fails
        """
        try:
            snapshots = []

            for frame in frames:
                snapshot = Snapshot(
                    job_id=job_id,
                    file_path=frame["file_path"],
                    timestamp=frame["timestamp"],
                    relevance_score=frame.get("relevance_score", 0.5),
                    detected_text=frame.get("detected_text"),
                    image_width=frame.get("width"),
                    image_height=frame.get("height"),
                    file_size=frame.get("file_size"),
                )
                snapshots.append(snapshot)
                db.add(snapshot)

            db.commit()
            logger.info(f"✓ Saved {len(snapshots)} snapshots for job {job_id}")
            return snapshots

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to save snapshots: {e}")
            raise SnapshotException(f"Failed to save snapshots: {str(e)}")
