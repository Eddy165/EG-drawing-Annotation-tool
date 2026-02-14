"""
QGraphicsScene and graphics items for the drawing canvas.
Image loaded once as QPixmap; scene redraws from stored objects only.
"""
from PyQt6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QGraphicsItem
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPen, QBrush, QColor, QPainter

from state import state


# Balloon colors per type
COLOR_DIMENSION = QColor("#1abc9c")   # Teal
COLOR_NOTE = QColor("#e67e22")        # Orange
COLOR_BOM = QColor("#27ae60")         # Green
RADIUS = 15
LEADER_OFFSET = 30


class BalloonGraphicsItem(QGraphicsItem):
    """Single balloon: dashed leader line + circle + number."""
    def __init__(self, balloon_data: dict, parent=None):
        super().__init__(parent)
        self.balloon_data = balloon_data
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    def boundingRect(self) -> QRectF:
        x, y = self.balloon_data["x"], self.balloon_data["y"]
        cx, cy = x - LEADER_OFFSET, y - LEADER_OFFSET
        r = RADIUS + 2
        return QRectF(min(x, cx - r), min(y, cy - r), max(LEADER_OFFSET + r, r * 2), max(LEADER_OFFSET + r, r * 2))

    def paint(self, painter: QPainter, option, widget=None) -> None:
        x = self.balloon_data["x"]
        y = self.balloon_data["y"]
        cx = x - LEADER_OFFSET
        cy = y - LEADER_OFFSET
        num = self.balloon_data["number"]
        t = self.balloon_data.get("type", "dimension")
        if t == "dimension":
            color = COLOR_DIMENSION
        elif t == "note":
            color = COLOR_NOTE
        else:
            color = COLOR_BOM

        pen = QPen(color, 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(int(x), int(y), int(cx), int(cy))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QPointF(cx, cy), RADIUS, RADIUS)

        painter.setPen(QColor("white"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawText(QRectF(cx - RADIUS, cy - RADIUS, RADIUS * 2, RADIUS * 2),
                         Qt.AlignmentFlag.AlignCenter, str(num))


class AnnotationScene(QGraphicsScene):
    """Scene holding image pixmap and balloon items. No annotation before image load."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._balloon_items: list[BalloonGraphicsItem] = []

    def set_image(self, pixmap) -> None:
        """Load image once; clear existing image and balloons from scene."""
        if self._pixmap_item is not None:
            self.removeItem(self._pixmap_item)
            self._pixmap_item = None
        for item in self._balloon_items:
            self.removeItem(item)
        self._balloon_items.clear()

        if pixmap is None:
            return
        self._pixmap_item = QGraphicsPixmapItem(pixmap)
        self._pixmap_item.setZValue(-1)
        self.addItem(self._pixmap_item)
        self.setSceneRect(self._pixmap_item.boundingRect())

    def sync_balloons(self) -> None:
        """Rebuild balloon graphics items from state.balloons."""
        for item in self._balloon_items:
            self.removeItem(item)
        self._balloon_items.clear()
        for b in state["balloons"]:
            item = BalloonGraphicsItem(b)
            self._balloon_items.append(item)
            self.addItem(item)
        self.update()
