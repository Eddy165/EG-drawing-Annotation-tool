"""
Main window: QGraphicsView + sidebar. All balloon operations and validation.
"""
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QGraphicsView,
    QScrollArea,
    QGroupBox,
    QPushButton,
    QLabel,
    QComboBox,
    QLineEdit,
    QTextEdit,
    QMessageBox,
    QFileDialog,
    QFrame,
    QRadioButton,
    QGridLayout,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QWheelEvent, QPainter

from state import state, generate_id, add_view, remove_view, renumber_all_balloons, get_balloon_count_for_view
from scene import AnnotationScene
from export_utils import export_to_file
from autodetect import autodetect_run


MAX_IMAGE_WIDTH = 900


class DrawingGraphicsView(QGraphicsView):
    """Graphics view with wheel zoom."""
    def wheelEvent(self, event: QWheelEvent):
        if event.angleDelta().y() > 0:
            self.scale(1.15, 1.15)
        else:
            self.scale(1.0 / 1.15, 1.0 / 1.15)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Engineering Drawing Annotation Tool")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)

        # Scene and view (NoDrag so left-click places balloons)
        self.scene = AnnotationScene()
        self.view = DrawingGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.setMinimumWidth(400)

        # Sidebar
        sidebar = QWidget()
        sidebar.setMaximumWidth(380)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)

        # Mode
        mode_group = QGroupBox("Annotation mode")
        mode_layout = QVBoxLayout(mode_group)
        self.mode_dim = QRadioButton("Dimension")
        self.mode_note = QRadioButton("Note")
        self.mode_bom = QRadioButton("BOM")
        self.mode_dim.setChecked(True)
        mode_layout.addWidget(self.mode_dim)
        mode_layout.addWidget(self.mode_note)
        mode_layout.addWidget(self.mode_bom)
        self.mode_dim.toggled.connect(lambda c: c and self._set_mode("dimension"))
        self.mode_note.toggled.connect(lambda c: c and self._set_mode("note"))
        self.mode_bom.toggled.connect(lambda c: c and self._set_mode("bom"))
        sidebar_layout.addWidget(mode_group)

        # Dimension controls
        self.dim_group = QGroupBox("Dimension")
        dim_layout = QGridLayout(self.dim_group)
        dim_layout.addWidget(QLabel("Type:"), 0, 0)
        self.dim_type = QComboBox()
        self.dim_type.addItems(["linear", "angular", "radius", "circular"])
        dim_layout.addWidget(self.dim_type, 0, 1)
        dim_layout.addWidget(QLabel("Flow:"), 1, 0)
        self.flow_dir = QComboBox()
        self.flow_dir.addItems(["clockwise", "anticlockwise"])
        dim_layout.addWidget(self.flow_dir, 1, 1)
        dim_layout.addWidget(QLabel("Value (optional):"), 2, 0)
        self.dim_value = QLineEdit()
        self.dim_value.setPlaceholderText("50mm, 45°, R10, Ø20")
        dim_layout.addWidget(self.dim_value, 2, 1)
        sidebar_layout.addWidget(self.dim_group)

        # Note controls
        self.note_group = QGroupBox("Note")
        note_layout = QVBoxLayout(self.note_group)
        self.note_text = QTextEdit()
        self.note_text.setPlaceholderText("Enter note text (required)")
        self.note_text.setMaximumHeight(80)
        note_layout.addWidget(self.note_text)
        sidebar_layout.addWidget(self.note_group)
        self.note_group.setVisible(False)

        # BOM controls
        self.bom_group = QGroupBox("BOM")
        bom_layout = QGridLayout(self.bom_group)
        bom_layout.addWidget(QLabel("Item #:"), 0, 0)
        self.bom_item = QLineEdit()
        bom_layout.addWidget(self.bom_item, 0, 1)
        bom_layout.addWidget(QLabel("Description:"), 1, 0)
        self.bom_desc = QLineEdit()
        bom_layout.addWidget(self.bom_desc, 1, 1)
        bom_layout.addWidget(QLabel("Quantity:"), 2, 0)
        self.bom_qty = QLineEdit()
        bom_layout.addWidget(self.bom_qty, 2, 1)
        bom_layout.addWidget(QLabel("Material (opt):"), 3, 0)
        self.bom_material = QLineEdit()
        bom_layout.addWidget(self.bom_material, 3, 1)
        bom_layout.addWidget(QLabel("Notes (opt):"), 4, 0)
        self.bom_notes = QLineEdit()
        bom_layout.addWidget(self.bom_notes, 4, 1)
        sidebar_layout.addWidget(self.bom_group)
        self.bom_group.setVisible(False)

        # Drawing meta
        meta_group = QGroupBox("Drawing")
        meta_layout = QGridLayout(meta_group)
        meta_layout.addWidget(QLabel("Name:"), 0, 0)
        self.drawing_name = QLineEdit()
        self.drawing_name.textChanged.connect(lambda t: state["drawing_meta"].__setitem__("name", t))
        meta_layout.addWidget(self.drawing_name, 0, 1)
        meta_layout.addWidget(QLabel("Scale:"), 1, 0)
        self.drawing_scale = QLineEdit()
        self.drawing_scale.setText("1:1")
        self.drawing_scale.textChanged.connect(lambda t: state["drawing_meta"].__setitem__("scale", t or "1:1"))
        meta_layout.addWidget(self.drawing_scale, 1, 1)
        sidebar_layout.addWidget(meta_group)

        # Views
        view_group = QGroupBox("Views")
        view_layout = QVBoxLayout(view_group)
        view_row = QHBoxLayout()
        self.view_type = QComboBox()
        self.view_type.addItems(["TOP", "FRONT", "SIDE", "SECTION", "DETAIL", "ASSEMBLY"])
        self.view_name = QLineEdit()
        self.view_name.setPlaceholderText("View name")
        self.add_view_btn = QPushButton("Add")
        self.add_view_btn.clicked.connect(self._add_view)
        view_row.addWidget(self.view_type)
        view_row.addWidget(self.view_name)
        view_row.addWidget(self.add_view_btn)
        view_layout.addLayout(view_row)
        self.view_list_widget = QWidget()
        self.view_list_layout = QVBoxLayout(self.view_list_widget)
        self.view_list_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.addWidget(self.view_list_widget)
        sidebar_layout.addWidget(view_group)

        # Summary
        summary_group = QGroupBox("Summary")
        summary_layout = QVBoxLayout(summary_group)
        self.lbl_total = QLabel("Total: 0")
        self.lbl_dims = QLabel("Dimensions: 0")
        self.lbl_notes = QLabel("Notes: 0")
        self.lbl_bom = QLabel("BOM: 0")
        summary_layout.addWidget(self.lbl_total)
        summary_layout.addWidget(self.lbl_dims)
        summary_layout.addWidget(self.lbl_notes)
        summary_layout.addWidget(self.lbl_bom)
        sidebar_layout.addWidget(summary_group)

        # Filters
        filter_row = QHBoxLayout()
        self.filter_all = QPushButton("All")
        self.filter_dim = QPushButton("Dimensions")
        self.filter_note = QPushButton("Notes")
        self.filter_bom = QPushButton("BOM")
        for b in (self.filter_all, self.filter_dim, self.filter_note, self.filter_bom):
            b.setCheckable(True)
        self.filter_all.setChecked(True)
        self._filter = "all"
        self.filter_all.clicked.connect(lambda: self._set_filter("all"))
        self.filter_dim.clicked.connect(lambda: self._set_filter("dimension"))
        self.filter_note.clicked.connect(lambda: self._set_filter("note"))
        self.filter_bom.clicked.connect(lambda: self._set_filter("bom"))
        filter_row.addWidget(self.filter_all)
        filter_row.addWidget(self.filter_dim)
        filter_row.addWidget(self.filter_note)
        filter_row.addWidget(self.filter_bom)
        sidebar_layout.addLayout(filter_row)

        # Balloon list
        balloon_list_group = QGroupBox("Balloons")
        self.balloon_list_layout = QVBoxLayout(balloon_list_group)
        self.balloon_list_layout.setContentsMargins(4, 4, 4, 4)
        sidebar_layout.addWidget(balloon_list_group)

        # Scroll for sidebar
        scroll = QScrollArea()
        scroll.setWidget(sidebar)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.view)
        splitter.addWidget(scroll)
        splitter.setSizes([700, 380])
        self.setCentralWidget(splitter)

        # Toolbar
        tb = self.addToolBar("Main")
        self.undo_btn = QPushButton("Undo")
        self.undo_btn.clicked.connect(self._undo)
        self.undo_btn.setEnabled(False)
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.clicked.connect(self._clear_all)
        self.clear_btn.setEnabled(False)
        self.export_btn = QPushButton("Export JSON")
        self.export_btn.clicked.connect(self._export)
        self.export_btn.setEnabled(False)
        tb.addWidget(self.undo_btn)
        tb.addWidget(self.clear_btn)
        tb.addWidget(self.export_btn)

        self._load_btn = QPushButton("Load image (JPG/PNG)")
        self._load_btn.clicked.connect(self._load_image)
        tb.addWidget(self._load_btn)

        self._auto_btn = QPushButton("Auto-Detect")
        self._auto_btn.clicked.connect(self._run_autodetect)
        self._auto_btn.setEnabled(False)
        tb.addWidget(self._auto_btn)

        # Scene click
        self.view.viewport().installEventFilter(self)

        self._refresh_sidebar()

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QMouseEvent
        if obj == self.view.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                pos = self.view.mapToScene(event.pos())
                self._on_scene_click(pos.x(), pos.y())
        return super().eventFilter(obj, event)

    def _set_mode(self, mode: str):
        state["mode"] = mode
        state["dimension_type"] = self.dim_type.currentText()
        state["flow_direction"] = self.flow_dir.currentText()
        self.dim_group.setVisible(mode == "dimension")
        self.note_group.setVisible(mode == "note")
        self.bom_group.setVisible(mode == "bom")

    def _set_filter(self, f: str):
        self._filter = f
        self.filter_all.setChecked(f == "all")
        self.filter_dim.setChecked(f == "dimension")
        self.filter_note.setChecked(f == "note")
        self.filter_bom.setChecked(f == "bom")
        self._refresh_balloon_list()

    def _add_view(self):
        name = self.view_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Please enter a view name.")
            return
        add_view(name, self.view_type.currentText())
        self.view_name.clear()
        self._refresh_view_list()
        self._refresh_sidebar()

    def _load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open drawing", "", "Images (JPG, PNG) (*.jpg *.jpeg *.png)"
        )
        if not path:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.critical(self, "Error", "Could not load image.")
            return
        w, h = pixmap.width(), pixmap.height()
        state["image_width"] = w
        state["image_height"] = h
        scale = min(1.0, MAX_IMAGE_WIDTH / w)
        state["scale"] = scale
        scaled = pixmap.scaled(int(w * scale), int(h * scale), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        state["scene_width"] = scaled.width()
        state["scene_height"] = scaled.height()
        state["image_data"] = scaled
        state["image_loaded"] = True
        state["balloons"] = []
        state["next_balloon_number"] = 1
        state["undo_stack"] = []
        self.scene.set_image(scaled)
        self.undo_btn.setEnabled(False)
        self.clear_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        self._auto_btn.setEnabled(True)
        self._refresh_sidebar()

    def _run_autodetect(self):
        if not state["image_loaded"]:
             return
            
        if QMessageBox.question(
            self, "Auto-Detect",
            "This will clear existing balloons and replace them with auto-detected ones. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
            
        self._push_undo()
        
        # Get flow direction from UI or state
        flow = self.flow_dir.currentText()
        
        try:
            balloons, views = autodetect_run(state["image_data"], flow_direction=flow)
            
            if not balloons:
                QMessageBox.information(self, "Auto-Detect", "No features detected.")
                return
                
            state["balloons"] = balloons
            # Replace views for auto mode
            state["views"] = views
            state["next_balloon_number"] = len(balloons) + 1
            
            # Select first view if available
            if state["views"]:
                state["selected_view_id"] = state["views"][0]["id"]
            else:
                state["selected_view_id"] = None
            
            self.scene.sync_balloons()
            self._refresh_sidebar()
            QMessageBox.information(self, "Auto-Detect", f"Detected {len(state['views'])} views and {len(balloons)} balloons.")
            
        except Exception as e:
            QMessageBox.critical(self, "Auto-Detect Error", str(e))

    def _on_scene_click(self, x: float, y: float):
        if not state["image_loaded"]:
            QMessageBox.warning(self, "Annotation", "Please load an image first.")
            return
        if state["selected_view_id"] is None:
            QMessageBox.warning(self, "Annotation", "Please create and select a view first.")
            return
        mode = state["mode"]
        if mode == "dimension":
            pass  # no required fields
        elif mode == "note":
            if not self.note_text.toPlainText().strip():
                QMessageBox.warning(self, "Validation", "Note text cannot be empty.")
                return
        elif mode == "bom":
            if not self.bom_item.text().strip() or not self.bom_desc.text().strip() or not self.bom_qty.text().strip():
                QMessageBox.warning(self, "Validation", "Item number, description and quantity are required for BOM.")
                return

        # Bounds check
        if x < 0 or y < 0 or x > state["scene_width"] or y > state["scene_height"]:
            return

        self._push_undo()
        balloon = {
            "id": generate_id(),
            "number": state["next_balloon_number"],
            "type": mode,
            "x": x,
            "y": y,
            "viewId": state["selected_view_id"],
        }
        state["next_balloon_number"] += 1
        if mode == "dimension":
            balloon["dimensionType"] = self.dim_type.currentText()
            balloon["flowDirection"] = self.flow_dir.currentText()
            balloon["value"] = self.dim_value.text().strip()
        elif mode == "note":
            balloon["text"] = self.note_text.toPlainText().strip()
        elif mode == "bom":
            balloon["itemNumber"] = self.bom_item.text().strip()
            balloon["description"] = self.bom_desc.text().strip()
            balloon["quantity"] = self.bom_qty.text().strip()
            balloon["material"] = self.bom_material.text().strip()
            balloon["notes"] = self.bom_notes.text().strip()
        state["balloons"].append(balloon)
        self.scene.sync_balloons()
        self._clear_form()
        self._refresh_sidebar()

    def _push_undo(self):
        state["undo_stack"].append([b.copy() for b in state["balloons"]])
        if len(state["undo_stack"]) > 50:
            state["undo_stack"].pop(0)
        self.undo_btn.setEnabled(True)

    def _undo(self):
        if not state["undo_stack"]:
            return
        state["balloons"] = state["undo_stack"].pop()
        state["next_balloon_number"] = len(state["balloons"]) + 1
        self.scene.sync_balloons()
        self.undo_btn.setEnabled(len(state["undo_stack"]) > 0)
        self._refresh_sidebar()

    def _clear_all(self):
        if QMessageBox.question(
            self, "Clear all",
            "Clear all balloons? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self._push_undo()
        state["balloons"] = []
        state["next_balloon_number"] = 1
        self.scene.sync_balloons()
        self._refresh_sidebar()

    def _delete_balloon(self, balloon_id: str):
        if QMessageBox.question(
            self, "Delete balloon",
            "Delete this balloon? All subsequent balloons will be renumbered.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self._push_undo()
        state["balloons"] = [b for b in state["balloons"] if b["id"] != balloon_id]
        renumber_all_balloons()
        self.scene.sync_balloons()
        self._refresh_sidebar()

    def _edit_balloon(self, balloon_id: str):
        b = next((x for x in state["balloons"] if x["id"] == balloon_id), None)
        if not b:
            return
        self._set_mode(b["type"])
        state["selected_view_id"] = b.get("viewId")
        self._refresh_view_list()
        if b["type"] == "dimension":
            self.dim_type.setCurrentText(b.get("dimensionType", "linear"))
            self.flow_dir.setCurrentText(b.get("flowDirection", "clockwise"))
            self.dim_value.setText(b.get("value", ""))
        elif b["type"] == "note":
            self.note_text.setPlainText(b.get("text", ""))
        elif b["type"] == "bom":
            self.bom_item.setText(b.get("itemNumber", ""))
            self.bom_desc.setText(b.get("description", ""))
            self.bom_qty.setText(b.get("quantity", ""))
            self.bom_material.setText(b.get("material", ""))
            self.bom_notes.setText(b.get("notes", ""))
        self._push_undo()
        state["balloons"] = [x for x in state["balloons"] if x["id"] != balloon_id]
        renumber_all_balloons()
        self.scene.sync_balloons()
        self._refresh_sidebar()
        QMessageBox.information(self, "Edit", "Balloon removed. Click on the canvas to place it again with the current values.")

    def _clear_form(self):
        self.dim_value.clear()
        self.note_text.clear()
        self.bom_item.clear()
        self.bom_desc.clear()
        self.bom_qty.clear()
        self.bom_material.clear()
        self.bom_notes.clear()

    def _refresh_view_list(self):
        while self.view_list_layout.count():
            child = self.view_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        for v in state["views"]:
            count = get_balloon_count_for_view(v["id"])
            row = QHBoxLayout()
            lbl = QLabel(f"{v['name']} ({v['type']}) — {count}")
            lbl.setStyleSheet("font-weight: bold;" if v["id"] == state["selected_view_id"] else "")
            btn = QPushButton("Del")
            btn.setFixedWidth(40)
            vid = v["id"]
            btn.clicked.connect(lambda checked, id=vid: self._delete_view(id))
            sel_btn = QPushButton("Select")
            sel_btn.clicked.connect(lambda checked, id=vid: self._select_view(id))
            row.addWidget(lbl, 1)
            row.addWidget(sel_btn)
            row.addWidget(btn)
            w = QWidget()
            w.setLayout(row)
            self.view_list_layout.addWidget(w)

    def _delete_view(self, view_id: int):
        if QMessageBox.question(
            self, "Delete view",
            "Delete this view? Balloons in this view will not be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        remove_view(view_id)
        self._refresh_view_list()
        self._refresh_balloon_list()

    def _select_view(self, view_id: int):
        state["selected_view_id"] = view_id
        self._refresh_view_list()
        self._refresh_sidebar()

    def _refresh_balloon_list(self):
        while self.balloon_list_layout.count():
            child = self.balloon_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        balloons = state["balloons"]
        if self._filter != "all":
            balloons = [b for b in balloons if b.get("type") == self._filter]
        balloons = sorted(balloons, key=lambda b: b["number"])
        for b in balloons:
            row = QHBoxLayout()
            t = b.get("type", "")
            if t == "dimension":
                detail = f"{b.get('dimensionType', '')} — {b.get('value', '')}"
            elif t == "note":
                detail = (b.get("text", "") or "")[:40]
            else:
                detail = f"#{b.get('itemNumber','')} {b.get('description','')} x{b.get('quantity','')}"
            lbl = QLabel(f"#{b['number']} [{t}] {detail}")
            lbl.setWordWrap(True)
            row.addWidget(lbl, 1)
            del_btn = QPushButton("Del")
            del_btn.setFixedWidth(40)
            bid = b["id"]
            del_btn.clicked.connect(lambda checked, id=bid: self._delete_balloon(id))
            edit_btn = QPushButton("Edit")
            edit_btn.clicked.connect(lambda checked, id=bid: self._edit_balloon(id))
            row.addWidget(edit_btn)
            row.addWidget(del_btn)
            w = QWidget()
            w.setLayout(row)
            self.balloon_list_layout.addWidget(w)

    def _refresh_sidebar(self):
        self._refresh_view_list()
        self._refresh_balloon_list()
        n = len(state["balloons"])
        self.lbl_total.setText(f"Total: {n}")
        self.lbl_dims.setText(f"Dimensions: {sum(1 for b in state['balloons'] if b.get('type') == 'dimension')}")
        self.lbl_notes.setText(f"Notes: {sum(1 for b in state['balloons'] if b.get('type') == 'note')}")
        self.lbl_bom.setText(f"BOM: {sum(1 for b in state['balloons'] if b.get('type') == 'bom')}")

    def _export(self):
        if not state["balloons"]:
            QMessageBox.warning(self, "Export", "No balloons to export.")
            return
        ts = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        default_name = f"drawing-annotation-{ts}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export JSON", default_name, "JSON (*.json)"
        )
        if not path:
            return
        try:
            export_to_file(path)
            QMessageBox.information(self, "Export", "Export completed successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Export", f"Export failed: {e}")
