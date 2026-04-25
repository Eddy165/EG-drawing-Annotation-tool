"""
processing_workers.py
---------------------
QThread-based async workers for every heavy CV/OCR pipeline stage.
Uses the global `state` singleton from state.py as the shared data bus.

Design rules
------------
- Workers never touch Qt GUI objects (QPixmap, QImage) — the main thread does that in slots.
- Workers emit numpy arrays / plain Python objects through signals.
- Callers must keep a reference to each worker (instance variable) to prevent GC while
  the thread is running.  Call worker.quit() + worker.wait() before discarding the reference.
"""

import math
import logging
import numpy as np

from PyQt6.QtCore import QThread, pyqtSignal, QPointF

from state import state, Balloon as BalloonDC

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper utilities (called from main thread slots)
# ---------------------------------------------------------------------------

def numpy_gray_to_ndarray_copy(gray: np.ndarray) -> np.ndarray:
    """Return a contiguous copy safe to hold across thread boundaries."""
    return np.ascontiguousarray(gray)


# ---------------------------------------------------------------------------
# Worker 1 – Preprocessing + Zone Detection  (Phase 0 → 1)
# ---------------------------------------------------------------------------

class PreprocessingWorker(QThread):
    """
    Runs preprocess_drawing(state) and then detect_zones(state).

    Prerequisites
    -------------
    - state.cv_image must be set (numpy BGR image from qpixmap_to_cv).

    Signals
    -------
    progress(int, str)     — 0-100 percentage + status text
    finished(np.ndarray)   — preprocessed grayscale image (for scene display)
    error(str)             — human-readable error message
    """

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(np.ndarray)
    error    = pyqtSignal(str)

    def run(self) -> None:
        try:
            # Import heavy modules inside run() so the main thread doesn't stall
            from autodetect import preprocess_drawing, detect_zones

            self.progress.emit(10, "Preprocessing: converting to grayscale, CLAHE, Sauvola…")
            preprocess_drawing(state)

            self.progress.emit(55, "Detecting drawing / notes / BOM zones…")
            detect_zones(state)

            self.progress.emit(100, "Preprocessing and zone detection complete.")
            # Emit a copy so the main thread owns the buffer safely
            self.finished.emit(numpy_gray_to_ndarray_copy(state.preprocessed_image))

        except Exception as exc:
            logger.exception("PreprocessingWorker error")
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Worker 2 – View Detection  (Phase 2)
# ---------------------------------------------------------------------------

class ViewDetectionWorker(QThread):
    """
    Runs detect_views(state, progress_callback).
    Populates state.detected_views.

    Signals
    -------
    progress(int, str)
    finished()
    error(str)
    """

    progress = pyqtSignal(int, str)
    finished = pyqtSignal()
    error    = pyqtSignal(str)

    def _cb(self, msg: str, pct: int) -> None:
        self.progress.emit(pct, msg)

    def run(self) -> None:
        try:
            from autodetect import detect_views

            self.progress.emit(5, "Detecting orthographic views via morphological clustering…")
            detect_views(state, progress_callback=self._cb)
            self.progress.emit(100, f"Found {len(state.detected_views)} view(s).")
            self.finished.emit()

        except Exception as exc:
            logger.exception("ViewDetectionWorker error")
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Worker 3 – Dimension / Notes / BOM Extraction  (Phases 5-7)
# ---------------------------------------------------------------------------

class DimensionExtractionWorker(QThread):
    """
    For each confirmed DetectedView, runs detect_dimensions_in_view.
    Then appends note and BOM balloons via detect_notes / detect_bom.
    Finally applies CW / ACW angular sort and assigns sequence numbers.

    Prerequisites
    -------------
    - state.detected_views must be populated (and is_confirmed set on wanted views)
    - state.flow_direction must be "CW" or "ACW"

    Signals
    -------
    progress(int, str)
    finished()
    error(str)
    """

    progress = pyqtSignal(int, str)
    finished = pyqtSignal()
    error    = pyqtSignal(str)

    def run(self) -> None:
        try:
            from autodetect import detect_dimensions_in_view, detect_notes, detect_bom

            # Use confirmed views only; fall back to all if none confirmed
            views = [v for v in state.detected_views if v.is_confirmed] or state.detected_views
            total = max(len(views), 1)
            all_balloons: list = []

            def image_to_scene(x: int, y: int) -> QPointF:
                return QPointF(float(x), float(y))

            for i, view in enumerate(views):
                pct = 5 + int((i / total) * 70)
                self.progress.emit(pct, f"Extracting dimensions: view {i + 1}/{total}…")
                balloons = detect_dimensions_in_view(view, state, image_to_scene)
                all_balloons.extend(balloons)

            # --- Notes extraction (returns old-style dicts) ---
            next_num = len(all_balloons) + 1
            if state.zones.get("notes"):
                self.progress.emit(80, "Extracting general notes…")
                note_b, next_num = detect_notes(
                    state.preprocessed_image,   # img (unused internally)
                    state.preprocessed_image,   # gray
                    state.binary_image,         # thresh
                    state.zones,
                    next_num,
                )
                all_balloons.extend(note_b)

            # --- BOM extraction (returns old-style dicts) ---
            if state.zones.get("bom"):
                self.progress.emit(90, "Extracting BOM rows…")
                bom_b, next_num = detect_bom(
                    state.preprocessed_image,
                    state.preprocessed_image,
                    state.binary_image,
                    state.zones,
                    next_num,
                )
                all_balloons.extend(bom_b)

            # --- Sort and number ---
            _sort_and_number(all_balloons, views, state.flow_direction or "CW")

            state.balloons = all_balloons
            state.next_balloon_number = len(all_balloons) + 1

            self.progress.emit(100, f"Detection complete — {len(all_balloons)} balloon(s).")
            self.finished.emit()

        except Exception as exc:
            logger.exception("DimensionExtractionWorker error")
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Shared sorting helper
# ---------------------------------------------------------------------------

def _sort_and_number(balloons: list, views: list, direction: str) -> None:
    """
    Assign sequence_number (Balloon dataclass) or ["number"] (dict)
    using CW/ACW angular ordering around each view's centroid.
    """
    if not balloons:
        return

    # Build view-id → balloon group map
    view_map: dict = {}
    for v in views:
        vid = v.view_id if hasattr(v, "view_id") else v.get("id", 0)
        view_map[vid] = []

    for b in balloons:
        vid = b.view_id if isinstance(b, BalloonDC) else b.get("viewId")
        if vid in view_map:
            view_map[vid].append(b)

    def _xy(b):
        if isinstance(b, BalloonDC):
            return float(b.position_image[0]), float(b.position_image[1])
        return float(b.get("x", 0)), float(b.get("y", 0))

    seq = 1
    for v in views:
        vid = v.view_id if hasattr(v, "view_id") else v.get("id", 0)
        grp = view_map.get(vid, [])
        if not grp:
            continue

        cx = sum(_xy(b)[0] for b in grp) / len(grp)
        cy = sum(_xy(b)[1] for b in grp) / len(grp)

        def _angle(b):
            x, y = _xy(b)
            a = math.atan2(y - cy, x - cx)
            if a < 0:
                a += 2 * math.pi
            return a

        grp.sort(key=_angle, reverse=(direction.upper() == "ACW"))

        for b in grp:
            if isinstance(b, BalloonDC):
                b.sequence_number = seq
            else:
                b["number"] = seq
            seq += 1
