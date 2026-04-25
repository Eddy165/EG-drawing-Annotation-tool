"""
scene.py  —  QGraphicsScene and graphics items for the drawing canvas.
Image loaded once as QPixmap; scene redraws from stored objects only.

v2 update: sync_balloons now handles both Balloon dataclass objects (from
detect_dimensions_in_view) and legacy dict objects (from detect_notes,
detect_bom, and manual additions).  The _to_display() helper normalises
them into the dict format BalloonGraphicsItem expects.
"""

from PyQt6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QGraphicsItem, QMenu
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPen, QBrush, QColor, QPainter, QFontMetrics, QPixmap

from state import state


# ---------------------------------------------------------------------------
# Colour palette per balloon type
# ---------------------------------------------------------------------------
COLOR_DIMENSION = QColor("#1abc9c")   # Teal
COLOR_NOTE      = QColor("#e67e22")   # Orange
COLOR_BOM       = QColor("#27ae60")   # Green
COLOR_UNCERTAIN = QColor("#e74c3c")   # Red
COLOR_MANUAL    = QColor("#95a5a6")   # Gray

RADIUS = 12
LEADER_OFFSET = 30


# ---------------------------------------------------------------------------
# Normalise balloon to display dict
# ---------------------------------------------------------------------------

def _to_display(b) -> dict:
    """
    Accept either a Balloon dataclass or a legacy dict and return a plain
    dict in the format expected by BalloonGraphicsItem.
    """
    from state import Balloon as BDC
    if isinstance(b, dict):
        return b

    if isinstance(b, BDC):
        val = b.value or ""
        if getattr(b, "tolerance", ""):
            val += f" {b.tolerance}"
        return {
            "id":         str(b.balloon_id),
            "number":     b.sequence_number,
            "type":       b.dim_type or "dimension",
            "x":          float(b.position_image[0]),
            "y":          float(b.position_image[1]),
            "value":      val,
            "confidence": b.confidence,
            "manual":     b.is_manual,
            "flagged":    b.is_flagged,
            "viewId":     b.view_id,
        }

    # Last-resort fallback
    return b


# ---------------------------------------------------------------------------
# Graphics Items
# ---------------------------------------------------------------------------

class BalloonGraphicsItem(QGraphicsItem):
    """Single balloon: dashed leader line + filled circle + sequence number.
    Supports drag-and-drop repositioning of the circle (not the anchor point).
    """

    def __init__(self, balloon_data: dict, sync_callback=None,
                 context_callback=None, parent=None) -> None:
        super().__init__(parent)
        self.balloon_data     = balloon_data
        self.sync_callback    = sync_callback
        self.context_callback = context_callback

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable,           True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable,        True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

        # Circle offset from the anchor point
        self.cx_off = -LEADER_OFFSET
        self.cy_off = -LEADER_OFFSET
        self.auto_offset()

    # ---------------------------------------------------------------- layout
    def auto_offset(self) -> None:
        """Nudge the circle until it doesn't overlap another balloon."""
        if not self.scene():
            return
        for _ in range(5):
            overlap = any(
                item is not self
                and isinstance(item, BalloonGraphicsItem)
                and self.get_circle_rect().intersects(item.get_circle_rect())
                for item in self.scene().items()
            )
            if overlap:
                self.cx_off -= 30
                self.cy_off -= 30
            else:
                break

    def get_circle_rect(self) -> QRectF:
        x, y = self.balloon_data["x"], self.balloon_data["y"]
        return QRectF(
            x + self.cx_off - RADIUS,
            y + self.cy_off - RADIUS,
            RADIUS * 2,
            RADIUS * 2,
        )

    def boundingRect(self) -> QRectF:
        x, y = self.balloon_data["x"], self.balloon_data["y"]
        r    = RADIUS + 10
        rect = QRectF(x, y, 0, 0).united(self.get_circle_rect())
        return rect.adjusted(-r, -r, r, r)

    # ---------------------------------------------------------------- paint
    def paint(self, painter: QPainter, option, widget=None) -> None:
        x  = self.balloon_data["x"]
        y  = self.balloon_data["y"]
        cx = x + self.cx_off
        cy = y + self.cy_off

        num        = self.balloon_data.get("number", 0)
        btype      = self.balloon_data.get("type", "dimension")
        confidence = self.balloon_data.get("confidence", 100)
        is_manual  = self.balloon_data.get("manual",  False)
        is_flagged = self.balloon_data.get("flagged", False)

        # Colour
        if is_flagged or confidence < 50:
            color = COLOR_UNCERTAIN
        elif is_manual:
            color = COLOR_MANUAL
        elif btype == "dimension":
            color = COLOR_DIMENSION
        elif btype in ("note", "notes"):
            color = COLOR_NOTE
        else:
            color = COLOR_BOM

        # Selection glow
        if self.isSelected():
            painter.setPen(QPen(QColor("yellow"), 2, Qt.PenStyle.SolidLine))
            painter.drawRect(self.boundingRect().adjusted(2, 2, -2, -2))

        # Leader line (dashed)
        pen = QPen(color, 2, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(x, y), QPointF(cx, cy))

        # Circle fill
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QPointF(cx, cy), RADIUS, RADIUS)

        # Sequence number
        painter.setPen(QColor("white"))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(cx - RADIUS, cy - RADIUS, RADIUS * 2, RADIUS * 2),
            Qt.AlignmentFlag.AlignCenter,
            str(num),
        )

    # ---------------------------------------------------------------- events
    def itemChange(self, change, value):
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        new_pos = self.pos()
        if new_pos != QPointF(0, 0):
            self.cx_off += new_pos.x()
            self.cy_off += new_pos.y()
            self.setPos(0, 0)
            if self.sync_callback:
                self.sync_callback()

    def contextMenuEvent(self, event) -> None:
        if self.context_callback:
            self.context_callback(self.balloon_data, event.screenPos())


# ---------------------------------------------------------------------------

class ViewBoundaryItem(QGraphicsItem):
    """Soft overlay rectangle for detected zones / views."""

    def __init__(self, view_data: dict, parent=None) -> None:
        super().__init__(parent)
        self.view_data = view_data
        self.setZValue(-0.5)

    def boundingRect(self) -> QRectF:
        v = self.view_data
        return QRectF(v["x"], v["y"], v["w"], v["h"])

    def paint(self, painter: QPainter, option, widget=None) -> None:
        is_zone = self.view_data.get("type") == "ZONE"
        pen_color = QColor(180, 100, 20, 180) if is_zone else QColor(100, 100, 255, 150)
        fill_color = QColor(180, 100, 20, 15) if is_zone else QColor(100, 100, 255, 15)

        painter.setPen(QPen(pen_color, 2, Qt.PenStyle.DashDotLine))
        painter.setBrush(QBrush(fill_color))
        painter.drawRect(self.boundingRect())

        # Label
        painter.setPen(pen_color)
        painter.drawText(
            self.boundingRect().topLeft() + QPointF(5, 15),
            self.view_data.get("name", ""),
        )


# ---------------------------------------------------------------------------

class AnnotationScene(QGraphicsScene):
    """Scene holding the image pixmap, view-boundary overlays, and balloon items."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pixmap_item:   QGraphicsPixmapItem | None = None
        self._balloon_items: list[BalloonGraphicsItem]  = []
        self._view_items:    list[ViewBoundaryItem]     = []
        self.balloon_context_callback = None

    def set_image(self, pixmap: QPixmap) -> None:
        if self._pixmap_item is not None:
            self.removeItem(self._pixmap_item)
            self._pixmap_item = None
        self._clear_dynamic_items()

        if pixmap is None or pixmap.isNull():
            return

        self._pixmap_item = QGraphicsPixmapItem(pixmap)
        self._pixmap_item.setZValue(-1)
        self.addItem(self._pixmap_item)
        self.setSceneRect(self._pixmap_item.boundingRect())

    def _clear_dynamic_items(self) -> None:
        for item in self._balloon_items:
            self.removeItem(item)
        self._balloon_items.clear()
        for item in self._view_items:
            self.removeItem(item)
        self._view_items.clear()

    def sync_balloons(self) -> None:
        """Rebuild all overlay items from state.  Call after any state mutation."""
        self._clear_dynamic_items()

        # View / zone boundary overlays
        for v in state.get("view_boundaries", []):
            if state.view_isolated and v.get("id") != state.view_isolated:
                continue
            v_item = ViewBoundaryItem(v)
            self._view_items.append(v_item)
            self.addItem(v_item)

        # Balloon items — normalise dataclass → dict first
        for raw_b in state.balloons:
            b = _to_display(raw_b)
            if state.view_isolated and b.get("viewId") != state.view_isolated:
                continue
            item = BalloonGraphicsItem(
                b,
                sync_callback=self.update,
                context_callback=self.balloon_context_callback,
            )
            self._balloon_items.append(item)
            self.addItem(item)

        self.update()
