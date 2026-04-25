"""
main_window.py  —  EG Drawing Annotation Tool V2
=================================================
Main window: QGraphicsView + 10-page Wizard Sidebar.

Key fixes vs previous version
------------------------------
* Removed all calls to NotImplementedError stubs (preprocess_image, segment_zones,
  detect_dimensions, autodetect_run).  These are now routed through QThread workers
  that call the v2 autodetect API (preprocess_drawing, detect_zones, detect_views,
  detect_dimensions_in_view).
* Added Page 3 (View Confirmation) to the stacked wizard — this matches Phase 3 in state.py.
* Workers are stored as instance attributes (never GC'd while running).
* closeEvent stops all in-flight workers cleanly.
* Balloon display handles both new Balloon dataclass objects and legacy dicts.
"""

import logging
from pathlib import Path

import numpy as np

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QGraphicsView, QScrollArea, QGroupBox, QPushButton, QLabel,
    QComboBox, QLineEdit, QTextEdit, QMessageBox, QFileDialog,
    QFrame, QRadioButton, QGridLayout, QProgressBar, QStackedWidget,
    QMenu, QInputDialog,
)
from PyQt6.QtCore import Qt, QPoint, pyqtSlot
from PyQt6.QtGui import QPixmap, QWheelEvent, QPainter, QAction, QImage

from state import (
    state, generate_id, add_view, remove_view, renumber_all_balloons,
    get_balloon_count_for_view, PHASES, Phase,
    advance_phase, go_back_to_phase,
)
from scene import AnnotationScene
from export_utils import export_json, export_annotated_image, export_pdf_report, export_all
from autodetect import qpixmap_to_cv
from processing_workers import (
    PreprocessingWorker,
    ViewDetectionWorker,
    DimensionExtractionWorker,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gray_ndarray_to_pixmap(gray: np.ndarray) -> QPixmap:
    """Convert a grayscale numpy array → QPixmap.  Must be called from the main thread."""
    h, w = gray.shape
    gray_c = np.ascontiguousarray(gray)
    qimg = QImage(gray_c.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
    return QPixmap.fromImage(qimg)


def _balloon_value(b) -> str:
    """Return a display string regardless of Balloon dataclass or dict."""
    from state import Balloon as BDC
    if isinstance(b, BDC):
        v = b.value or ""
        if b.tolerance:
            v += f" {b.tolerance}"
        return v
    return str(b.get("value", b.get("text", b.get("description", "—"))))


def _balloon_number(b) -> int:
    from state import Balloon as BDC
    if isinstance(b, BDC):
        return b.sequence_number
    return b.get("number", 0)


def _balloon_id(b):
    from state import Balloon as BDC
    if isinstance(b, BDC):
        return b.balloon_id
    return b.get("id")


def _balloon_xy(b):
    from state import Balloon as BDC
    if isinstance(b, BDC):
        return b.position_image
    return b.get("x", 0), b.get("y", 0)


# ---------------------------------------------------------------------------
# Custom QGraphicsView (wheel zoom)
# ---------------------------------------------------------------------------

class DrawingGraphicsView(QGraphicsView):
    """Graphics view with smooth wheel zoom."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):

    # ------------------------------------------------------------------ init
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EG Drawing Annotation Tool V2")
        self.setMinimumSize(1240, 820)

        # Worker references — MUST be kept alive while threads run
        self._preproc_worker: PreprocessingWorker | None = None
        self._view_worker:    ViewDetectionWorker | None = None
        self._dim_worker:     DimensionExtractionWorker | None = None

        # Scene / view
        self.scene = AnnotationScene()
        self.scene.balloon_context_callback = self._show_balloon_context_menu
        self.view = DrawingGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        # Layout
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(len(PHASES) - 1)
        self.progress_bar.setFormat("Phase %v of %m")
        self.progress_bar.setStyleSheet(
            "QProgressBar { border-radius: 4px; background: #e0e0e0; }"
            "QProgressBar::chunk { background: #2980b9; border-radius: 4px; }"
        )
        main_layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("Ready — load a drawing to begin.")
        self.status_label.setStyleSheet("color: #555; padding: 2px 6px;")
        main_layout.addWidget(self.status_label)

        # Content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.view)

        # Wizard sidebar
        self.wizard_panel = QStackedWidget()
        self.wizard_panel.setFixedWidth(390)
        self._setup_wizard_steps()

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidget(self.wizard_panel)
        sidebar_scroll.setWidgetResizable(True)
        splitter.addWidget(sidebar_scroll)
        splitter.setSizes([820, 390])
        main_layout.addWidget(splitter)

        self.view.viewport().installEventFilter(self)
        self._update_ui_state()

    # ---------------------------------------------------------------- wizard
    def _setup_wizard_steps(self) -> None:
        """Build wizard pages 0-9 (one per Phase enum value)."""

        # ── Page 0: Upload ──────────────────────────────────────────────
        p0 = self._create_step_widget("Step 1 · Upload Drawing", page_id=0)
        self.btn_load = QPushButton("Select Drawing (JPG / PNG / TIFF)")
        self.btn_load.setStyleSheet("padding: 6px; font-weight: bold;")
        self.btn_load.clicked.connect(self._load_image)
        self.lbl_paper_size = QLabel("Paper size: not detected")
        self.lbl_paper_size.setStyleSheet("color: #666;")
        p0.layout().insertWidget(1, self.btn_load)
        p0.layout().insertWidget(2, self.lbl_paper_size)
        self.wizard_panel.addWidget(p0)   # index 0

        # ── Page 1: Zone Segmentation ────────────────────────────────────
        p1 = self._create_step_widget("Step 2 · Zone Segmentation", page_id=1)
        self.lbl_zones = QLabel("Zones: Drawing | Notes | BOM")
        self.lbl_zones.setWordWrap(True)
        self.btn_run_zone = QPushButton("Run Zone Detection")
        self.btn_run_zone.clicked.connect(self._run_zone_phase)
        p1.layout().insertWidget(1, self.lbl_zones)
        p1.layout().insertWidget(2, self.btn_run_zone)
        self.wizard_panel.addWidget(p1)   # index 1

        # ── Page 2: View Detection ───────────────────────────────────────
        p2 = self._create_step_widget("Step 3 · View Detection", page_id=2)
        self.btn_run_views = QPushButton("Detect Orthographic Views")
        self.btn_run_views.clicked.connect(self._run_view_phase)
        self.view_list_container = QWidget()
        self.view_list_layout = QVBoxLayout(self.view_list_container)
        self.view_list_layout.setContentsMargins(0, 0, 0, 0)
        p2.layout().insertWidget(1, self.btn_run_views)
        p2.layout().insertWidget(2, self.view_list_container)
        self.wizard_panel.addWidget(p2)   # index 2

        # ── Page 3: View Confirmation (NEW) ──────────────────────────────
        p3 = self._create_step_widget("Step 4 · Confirm Views", page_id=3)
        lbl_hint = QLabel(
            "Review auto-detected views below.\n"
            "Edit labels or remove incorrect entries, then click Confirm."
        )
        lbl_hint.setWordWrap(True)
        lbl_hint.setStyleSheet("color: #444;")
        self.btn_confirm_views = QPushButton("✔  Confirm All Views")
        self.btn_confirm_views.setStyleSheet(
            "QPushButton { background:#27ae60; color:white; font-weight:bold; padding:7px; }"
            "QPushButton:hover { background:#2ecc71; }"
        )
        self.btn_confirm_views.clicked.connect(self._confirm_views)
        self.view_confirm_container = QWidget()
        self.view_confirm_layout = QVBoxLayout(self.view_confirm_container)
        self.view_confirm_layout.setContentsMargins(0, 4, 0, 0)
        p3.layout().insertWidget(1, lbl_hint)
        p3.layout().insertWidget(2, self.btn_confirm_views)
        p3.layout().insertWidget(3, self.view_confirm_container)
        self.wizard_panel.addWidget(p3)   # index 3

        # ── Page 4: Flow Direction ───────────────────────────────────────
        p4 = self._create_step_widget("Step 5 · Flow Direction", page_id=4)
        flow_group = QGroupBox("Balloon Sequence Direction")
        flow_layout = QVBoxLayout(flow_group)
        self.rb_cw  = QRadioButton("Clockwise (CW)")
        self.rb_acw = QRadioButton("Anti-Clockwise (ACW)")
        self.rb_cw.setChecked(True)
        self.rb_cw.toggled.connect(lambda chk: setattr(state, "flow_direction", "CW") if chk else None)
        self.rb_acw.toggled.connect(lambda chk: setattr(state, "flow_direction", "ACW") if chk else None)
        flow_layout.addWidget(self.rb_cw)
        flow_layout.addWidget(self.rb_acw)
        p4.layout().insertWidget(1, flow_group)
        self.wizard_panel.addWidget(p4)   # index 4

        # ── Page 5: Run Detection ────────────────────────────────────────
        p5 = self._create_step_widget("Step 6 · Auto-Balloon", page_id=5)
        self.btn_detect = QPushButton("Run Auto-Ballooning")
        self.btn_detect.setStyleSheet(
            "QPushButton { background:#2980b9; color:white; font-weight:bold; padding:8px; }"
            "QPushButton:hover { background:#3498db; }"
        )
        self.btn_detect.clicked.connect(self._run_detection)
        p5.layout().insertWidget(1, self.btn_detect)
        self.wizard_panel.addWidget(p5)   # index 5

        # ── Pages 6-7: Notes / BOM placeholders ──────────────────────────
        self.wizard_panel.addWidget(
            self._create_step_widget("Step 7 · Notes Detection", page_id=6)
        )   # index 6
        self.wizard_panel.addWidget(
            self._create_step_widget("Step 8 · BOM Detection", page_id=7)
        )   # index 7

        # ── Page 8: Review & Override ────────────────────────────────────
        p8 = self._create_step_widget("Step 9 · Review & Override", page_id=8)
        self.lbl_summary = QLabel("Summary: 0 High · 0 Med · 0 Low confidence")
        self.lbl_summary.setWordWrap(True)
        self.balloon_list_container = QWidget()
        self.balloon_list_layout = QVBoxLayout(self.balloon_list_container)
        self.balloon_list_layout.setContentsMargins(0, 0, 0, 0)
        p8.layout().insertWidget(1, self.lbl_summary)
        p8.layout().insertWidget(2, self.balloon_list_container)
        self.wizard_panel.addWidget(p8)   # index 8

        # ── Page 9: Export ───────────────────────────────────────────────
        p9 = self._create_step_widget("Step 10 · Export Report", page_id=9)
        self.btn_export_all  = QPushButton("Export All (PDF + JSON + Image)")
        self.btn_export_json = QPushButton("Export JSON only")
        self.btn_export_img  = QPushButton("Export Annotated Image")
        self.btn_export_pdf  = QPushButton("Generate PDF Report")
        self.btn_export_all.setStyleSheet(
            "QPushButton { background:#e67e22; color:white; font-weight:bold; padding:8px; }"
        )
        self.btn_export_all.clicked.connect(self._export_all)
        self.btn_export_json.clicked.connect(self._export_json)
        self.btn_export_img.clicked.connect(self._export_image)
        self.btn_export_pdf.clicked.connect(self._export_pdf)
        for btn in (self.btn_export_all, self.btn_export_json,
                    self.btn_export_img, self.btn_export_pdf):
            p9.layout().insertWidget(p9.layout().count() - 2, btn)
        self.wizard_panel.addWidget(p9)   # index 9

    def _create_step_widget(self, title: str, page_id: int) -> QWidget:
        """Generic wizard page with title + Back/Next navigation."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        lbl = QLabel(title)
        lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #2c3e50; padding: 4px 0;")
        layout.addWidget(lbl)

        layout.addStretch()

        nav = QHBoxLayout()
        btn_back = QPushButton("◀  Back")
        btn_next = QPushButton("Next  ▶")
        btn_back.setFixedHeight(30)
        btn_next.setFixedHeight(30)
        btn_back.clicked.connect(self._on_back)
        btn_next.clicked.connect(self._on_next)
        nav.addWidget(btn_back)
        nav.addWidget(btn_next)
        layout.addLayout(nav)

        widget.setProperty("btn_next", btn_next)
        widget.setProperty("btn_back", btn_back)
        return widget

    # --------------------------------------------------------- UI sync
    def _update_ui_state(self) -> None:
        """Sync wizard page, progress bar, and button states to state.current_phase."""
        phase_val = state.current_phase.value
        page_idx  = min(phase_val, self.wizard_panel.count() - 1)
        self.wizard_panel.setCurrentIndex(page_idx)
        self.progress_bar.setValue(phase_val)

        current_widget = self.wizard_panel.currentWidget()
        btn_back = current_widget.property("btn_back")
        btn_next = current_widget.property("btn_next")

        if btn_back:
            btn_back.setEnabled(phase_val > 0)

        # Ask the state's gate whether we can advance
        can_proceed = True
        next_val = phase_val + 1
        if next_val <= 9:
            try:
                next_phase = Phase(next_val)
                can_proceed, _ = state.can_advance_to(next_phase)
            except ValueError:
                can_proceed = True

        if btn_next:
            btn_next.setEnabled(can_proceed)

        # Refresh phase-specific sub-panels
        if phase_val == 2:    # VIEW_DETECT
            self._refresh_view_list()
        elif phase_val == 3:  # VIEW_CONFIRM
            self._refresh_view_confirm_list()
        elif phase_val == 8:  # MANUAL_OVERRIDE
            self._refresh_balloon_list()

    # --------------------------------------------------------- Navigation
    def _on_next(self) -> None:
        if advance_phase():
            self._update_ui_state()

    def _on_back(self) -> None:
        idx = PHASES.index(state.current_phase) - 1
        if idx >= 0 and go_back_to_phase(idx):
            self._update_ui_state()

    # --------------------------------------------------------- Phase 0: Load image
    def _load_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Engineering Drawing", "",
            "Images (*.jpg *.jpeg *.png *.tif *.tiff *.bmp)"
        )
        if not path:
            return

        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.critical(self, "Error", f"Cannot load image:\n{path}")
            return

        state["image_data"]  = pixmap
        state["image_loaded"] = True
        state.cv_image = qpixmap_to_cv(pixmap)

        meta_name = Path(path).stem
        state["drawing_meta"]["name"] = meta_name
        self.scene.set_image(pixmap)

        # Quick paper-size hint from pixel dimensions
        h, w = state.cv_image.shape[:2]
        ratio = max(w, h) / min(w, h)
        hint = "A4" if abs(ratio - 1.414) < 0.15 else "Custom"
        self.lbl_paper_size.setText(f"Detected size: {hint}  ({w} × {h} px)")

        self._set_status("Image loaded. Click 'Next' to proceed to zone detection.")
        self._update_ui_state()

    # --------------------------------------------------------- Phase 1: Zone detection
    def _run_zone_phase(self) -> None:
        if state.cv_image is None:
            QMessageBox.warning(self, "Warning", "Please load a drawing image first.")
            return

        self.btn_run_zone.setEnabled(False)
        self._set_status("Running preprocessing + zone detection…")

        self._preproc_worker = PreprocessingWorker()
        self._preproc_worker.progress.connect(self._on_worker_progress)
        self._preproc_worker.finished.connect(self._on_preprocessing_done)
        self._preproc_worker.error.connect(self._on_worker_error)
        self._preproc_worker.start()

    @pyqtSlot(np.ndarray)
    def _on_preprocessing_done(self, gray_img: np.ndarray) -> None:
        # Convert numpy → pixmap in main thread (Qt-safe)
        pixmap = _gray_ndarray_to_pixmap(gray_img)
        self.scene.set_image(pixmap)

        zones = state.zones
        found = [k for k, v in zones.items() if v]
        self.lbl_zones.setText(f"Zones found: {', '.join(found)}")

        # Build view_boundaries for visual overlay
        boundaries = []
        for zname, bbox in zones.items():
            if bbox:
                x, y, w, h = bbox
                boundaries.append({
                    "id": zname, "name": zname.upper(),
                    "type": "ZONE", "x": x, "y": y, "w": w, "h": h,
                })
        state["view_boundaries"] = boundaries
        self.scene.sync_balloons()

        self.btn_run_zone.setEnabled(True)
        self._set_status(f"Zones detected: {', '.join(found)}. Click 'Next'.")
        self._update_ui_state()

    # --------------------------------------------------------- Phase 2: View detection
    def _run_view_phase(self) -> None:
        if not state.zones:
            QMessageBox.warning(self, "Error", "Run zone detection first.")
            return

        self.btn_run_views.setEnabled(False)
        self._set_status("Detecting orthographic views…")

        self._view_worker = ViewDetectionWorker()
        self._view_worker.progress.connect(self._on_worker_progress)
        self._view_worker.finished.connect(self._on_view_detection_done)
        self._view_worker.error.connect(self._on_worker_error)
        self._view_worker.start()

    @pyqtSlot()
    def _on_view_detection_done(self) -> None:
        views = state.detected_views

        # Update view_boundaries overlay
        boundaries = [b for b in state.get("view_boundaries", [])
                      if b.get("type") == "ZONE"]
        for v in views:
            vx, vy, vw, vh = v.bbox
            boundaries.append({
                "id": str(v.view_id), "name": v.label,
                "type": "VIEW", "x": vx, "y": vy, "w": vw, "h": vh,
            })
        state["view_boundaries"] = boundaries
        self.scene.sync_balloons()

        self._refresh_view_list()
        self.btn_run_views.setEnabled(True)
        self._set_status(f"{len(views)} view(s) detected. Review on the next page.")
        self._update_ui_state()

    def _refresh_view_list(self) -> None:
        """Populate the detected-view summary on page 2."""
        while self.view_list_layout.count():
            item = self.view_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for v in state.detected_views:
            lbl = QLabel(
                f"• <b>{v.label}</b> "
                f"<span style='color:#888;'>(conf {v.confidence:.0%}, "
                f"src: {v.label_source})</span>"
            )
            lbl.setTextFormat(Qt.TextFormat.RichText)
            self.view_list_layout.addWidget(lbl)

    # --------------------------------------------------------- Phase 3: View confirmation
    def _refresh_view_confirm_list(self) -> None:
        """Populate the editable view list on the confirmation page."""
        while self.view_confirm_layout.count():
            item = self.view_confirm_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for v in state.detected_views:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)

            lbl = QLabel(f"<b>{v.label}</b> ({v.confidence:.0%})")
            lbl.setTextFormat(Qt.TextFormat.RichText)

            btn_edit = QPushButton("Edit")
            btn_edit.setFixedWidth(44)
            btn_edit.clicked.connect(lambda _, view=v: self._edit_view_label(view))

            btn_del = QPushButton("✕")
            btn_del.setFixedWidth(28)
            btn_del.setStyleSheet("color: red;")
            btn_del.clicked.connect(lambda _, view=v: self._delete_view(view))

            row_layout.addWidget(lbl, stretch=1)
            row_layout.addWidget(btn_edit)
            row_layout.addWidget(btn_del)
            self.view_confirm_layout.addWidget(row)

    def _edit_view_label(self, view) -> None:
        new_label, ok = QInputDialog.getText(
            self, "Edit View Label", "Label:", text=view.label
        )
        if ok and new_label.strip():
            view.label = new_label.strip().upper()
            view.is_manually_edited = True
            self._refresh_view_confirm_list()

    def _delete_view(self, view) -> None:
        state.detected_views = [v for v in state.detected_views if v.view_id != view.view_id]
        # Also remove overlay boundary
        state["view_boundaries"] = [
            b for b in state.get("view_boundaries", [])
            if str(b.get("id")) != str(view.view_id)
        ]
        self.scene.sync_balloons()
        self._refresh_view_confirm_list()

    def _confirm_views(self) -> None:
        if not state.detected_views:
            QMessageBox.warning(self, "No views", "No views to confirm.")
            return
        for v in state.detected_views:
            v.is_confirmed = True
        state.views_confirmed = True
        self._set_status(f"{len(state.detected_views)} view(s) confirmed. Select flow direction.")
        self._update_ui_state()

    # --------------------------------------------------------- Phase 4: Flow direction
    # (set in _run_detection below)

    # --------------------------------------------------------- Phase 5: Dimension extraction
    def _run_detection(self) -> None:
        if not state.views_confirmed:
            QMessageBox.warning(
                self, "Views not confirmed",
                "Please confirm the detected views on the previous step."
            )
            return

        self.btn_detect.setEnabled(False)
        self._set_status(f"Running auto-ballooning ({state.flow_direction})…")

        self._dim_worker = DimensionExtractionWorker()
        self._dim_worker.progress.connect(self._on_worker_progress)
        self._dim_worker.finished.connect(self._on_detection_done)
        self._dim_worker.error.connect(self._on_worker_error)
        self._dim_worker.start()

    @pyqtSlot()
    def _on_detection_done(self) -> None:
        balloons = state.balloons

        # Confidence summary
        def _conf(b):
            from state import Balloon as BDC
            return b.confidence if isinstance(b, BDC) else b.get("confidence", 0)

        hi = sum(1 for b in balloons if _conf(b) > 80)
        md = sum(1 for b in balloons if 50 <= _conf(b) <= 80)
        lo = sum(1 for b in balloons if _conf(b) < 50)
        self.lbl_summary.setText(
            f"Total: {len(balloons)} — High: {hi} · Med: {md} · Low: {lo}"
        )

        self.scene.sync_balloons()
        self.btn_detect.setEnabled(True)
        self._set_status(f"Detection complete — {len(balloons)} balloon(s). Review in Step 9.")
        self._update_ui_state()

    # --------------------------------------------------------- Phase 8: Review & balloon list
    def _refresh_balloon_list(self) -> None:
        while self.balloon_list_layout.count():
            item = self.balloon_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for b in state.balloons:
            num = _balloon_number(b)
            val = _balloon_value(b)
            btn = QPushButton(f"#{num}  —  {val}")
            btn.setStyleSheet("text-align:left; padding: 3px 6px;")
            btn.clicked.connect(lambda _, bd=b: self._focus_balloon(bd))
            self.balloon_list_layout.addWidget(btn)

    def _focus_balloon(self, b) -> None:
        x, y = _balloon_xy(b)
        self.view.centerOn(float(x), float(y))

    def _show_balloon_context_menu(self, balloon_data: dict, screen_pos) -> None:
        menu = QMenu(self)
        edit_action   = QAction("Edit Value",        self)
        delete_action = QAction("Delete Balloon",    self)
        flag_action   = QAction("Toggle Flag",       self)

        edit_action.triggered.connect(lambda: self._edit_balloon(balloon_data))
        delete_action.triggered.connect(lambda: self._delete_balloon(balloon_data))
        flag_action.triggered.connect(lambda: self._flag_balloon(balloon_data))

        menu.addAction(edit_action)
        menu.addAction(delete_action)
        menu.addAction(flag_action)
        menu.exec(screen_pos)

    def _edit_balloon(self, b) -> None:
        from state import Balloon as BDC
        current = b.value if isinstance(b, BDC) else b.get("value", "")
        new_val, ok = QInputDialog.getText(
            self, "Edit Value", "Value:", QLineEdit.EchoMode.Normal, current
        )
        if ok:
            if isinstance(b, BDC):
                b.value = new_val
            else:
                b["value"] = new_val
            self.scene.sync_balloons()
            self._refresh_balloon_list()

    def _delete_balloon(self, b) -> None:
        bid = _balloon_id(b)
        state.balloons = [
            x for x in state.balloons if _balloon_id(x) != bid
        ]
        renumber_all_balloons()
        self.scene.sync_balloons()
        self._refresh_balloon_list()

    def _flag_balloon(self, b) -> None:
        from state import Balloon as BDC
        if isinstance(b, BDC):
            b.is_flagged = not b.is_flagged
        else:
            b["flagged"] = not b.get("flagged", False)
        self.scene.sync_balloons()

    # --------------------------------------------------------- Phase 9: Export
    def _export_all(self) -> None:
        output_dir = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", str(Path.home() / "Documents")
        )
        if not output_dir:
            return
        try:
            paths = export_all(state, output_dir)
            QMessageBox.information(
                self, "Export Complete",
                "Exported:\n" + "\n".join(paths.values())
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export JSON", "drawing.json", "JSON (*.json)"
        )
        if path:
            try:
                export_json(state, path)
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

    def _export_image(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Image", "drawing_annotated.png", "PNG (*.png)"
        )
        if path:
            try:
                export_annotated_image(state, path)
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

    def _export_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PDF Report", "ctq_report.pdf", "PDF (*.pdf)"
        )
        if path:
            try:
                img_path = path.replace(".pdf", "_annotated.png")
                export_annotated_image(state, img_path)
                export_pdf_report(state, img_path, path)
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

    # --------------------------------------------------------- Manual balloon add
    def eventFilter(self, obj, event) -> bool:
        from PyQt6.QtCore import QEvent
        if (obj == self.view.viewport()
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton):
            if state.current_phase.value == 8:   # MANUAL_OVERRIDE
                pos = self.view.mapToScene(event.pos())
                if not self.scene.itemAt(pos, self.view.transform()):
                    self._on_manual_add(pos.x(), pos.y())
        return super().eventFilter(obj, event)

    def _on_manual_add(self, x: float, y: float) -> None:
        b = {
            "id":     generate_id(),
            "number": state.next_balloon_number,
            "type":   "dimension",
            "x": x, "y": y,
            "manual": True,
            "value":  "Manual",
        }
        state.balloons.append(b)
        state.next_balloon_number += 1
        self.scene.sync_balloons()
        self._refresh_balloon_list()

    # --------------------------------------------------------- Worker shared slots
    @pyqtSlot(int, str)
    def _on_worker_progress(self, pct: int, msg: str) -> None:
        self.progress_bar.setValue(pct)
        self._set_status(msg)

    @pyqtSlot(str)
    def _on_worker_error(self, msg: str) -> None:
        logger.error("Worker error: %s", msg)
        QMessageBox.critical(self, "Processing Error", f"An error occurred:\n\n{msg}")
        self.btn_run_zone.setEnabled(True)
        self.btn_run_views.setEnabled(True)
        self.btn_detect.setEnabled(True)
        self._set_status("Error — see message above.")

    def _set_status(self, msg: str) -> None:
        self.status_label.setText(msg)

    # --------------------------------------------------------- Cleanup
    def _stop_worker(self, worker) -> None:
        if worker is not None and worker.isRunning():
            worker.quit()
            worker.wait(3000)

    def closeEvent(self, event) -> None:
        self._stop_worker(self._preproc_worker)
        self._stop_worker(self._view_worker)
        self._stop_worker(self._dim_worker)
        event.accept()
