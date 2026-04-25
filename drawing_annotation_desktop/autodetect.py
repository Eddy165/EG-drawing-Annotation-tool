git # autodetect.py  —  EGDAT V2 Detection Engine
# =============================================
# Full pipeline: zone segmentation, line detection, OCR, balloon placement
# Drop-in replacement for V1 autodetect.py
# All worker-API functions preserved for processing_workers.py compatibility.

import cv2
import numpy as np
import math
import re
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Any, Dict, Callable
from enum import Enum, auto
from pathlib import Path

# ── Tesseract setup ──────────────────────────────────────────────────────────
import pytesseract
_TESS_PATH = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if _TESS_PATH.is_file():
    pytesseract.pytesseract.tesseract_cmd = str(_TESS_PATH)
    TESSERACT_AVAILABLE = True
else:
    TESSERACT_AVAILABLE = False

# ── EasyOCR lazy singleton ────────────────────────────────────────────────────
_easyocr_reader = None
EASYOCR_AVAILABLE = False
try:
    import easyocr as _easyocr_module
    EASYOCR_AVAILABLE = True
except Exception:
    _easyocr_module = None  # type: ignore

def get_easyocr_reader():
    global _easyocr_reader, EASYOCR_AVAILABLE
    if _easyocr_reader is None and EASYOCR_AVAILABLE:
        try:
            _easyocr_reader = _easyocr_module.Reader(['en'], gpu=False, verbose=False)
        except Exception as e:
            logging.warning("EasyOCR init failed: %s", e)
            EASYOCR_AVAILABLE = False
    return _easyocr_reader

# ── scikit-image Sauvola ──────────────────────────────────────────────────────
try:
    from skimage.filters import threshold_sauvola
    SKIMAGE_AVAILABLE = True
except ImportError:
    SKIMAGE_AVAILABLE = False

from PyQt6.QtGui import QImage
from state import state, generate_id, DetectedView, Balloon as BalloonDC

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# ENUMS & DATACLASSES
# ═══════════════════════════════════════════════════════════════════

class PaperSize(Enum):
    A4 = "A4"; A3 = "A3"; A2 = "A2"; A1 = "A1"; UNKNOWN = "UNKNOWN"

class DimensionType(Enum):
    LINEAR_HORIZONTAL = "linear_horizontal"
    LINEAR_VERTICAL   = "linear_vertical"
    ANGULAR           = "angular"
    RADIUS            = "radius"
    DIAMETER          = "diameter"
    ORDINATE          = "ordinate"

class LineOrientation(Enum):
    HORIZONTAL = auto()
    VERTICAL   = auto()
    DIAGONAL   = auto()

@dataclass
class ZoneRect:
    x: int; y: int; w: int; h: int
    @property
    def x2(self): return self.x + self.w
    @property
    def y2(self): return self.y + self.h
    @property
    def area(self): return self.w * self.h
    @property
    def center(self): return (self.x + self.w // 2, self.y + self.h // 2)
    def contains_point(self, px, py) -> bool:
        return self.x <= px <= self.x2 and self.y <= py <= self.y2
    def as_slice(self): return (slice(self.y, self.y2), slice(self.x, self.x2))
    def to_tuple(self): return (self.x, self.y, self.w, self.h)
    def expanded(self, px: int) -> "ZoneRect":
        return ZoneRect(max(0, self.x-px), max(0, self.y-px), self.w+2*px, self.h+2*px)

@dataclass
class SegmentedZones:
    paper_size: PaperSize
    full_image_shape: Tuple[int, int]
    drawing_zone: ZoneRect
    title_block_zone: Optional[ZoneRect]
    notes_zone: Optional[ZoneRect]
    border_zone: Optional[ZoneRect]
    view_zones: List[ZoneRect]
    scale_factor: float
    segmentation_confidence: float
    detection_dpi_estimate: int

@dataclass
class DetectedLine:
    x1: int; y1: int; x2: int; y2: int
    orientation: LineOrientation
    length: float
    angle_deg: float
    has_arrowhead_start: bool = False
    has_arrowhead_end: bool = False
    arrowhead_confidence_start: float = 0.0
    arrowhead_confidence_end: float = 0.0
    @property
    def midpoint(self): return ((self.x1+self.x2)//2, (self.y1+self.y2)//2)
    @property
    def is_dimension_line(self): return self.has_arrowhead_start and self.has_arrowhead_end
    @property
    def is_leader_line(self): return self.has_arrowhead_start != self.has_arrowhead_end

@dataclass
class ExtensionLinePair:
    dim_line: DetectedLine
    ext_line_1: Optional[DetectedLine]
    ext_line_2: Optional[DetectedLine]
    pairing_confidence: float = 0.0

@dataclass
class DetectedDimension:
    dim_type: DimensionType
    line: DetectedLine
    extension_pair: Optional[ExtensionLinePair]
    ocr_value_raw: str
    ocr_value_clean: str
    ocr_confidence: float
    ocr_engine_used: str
    ocr_bbox: Optional[Tuple]
    anchor_point: Tuple[int, int]
    balloon_center: Tuple[int, int]
    detection_confidence: float
    balloon_number: int = 0
    view_id: str = ""

@dataclass
class DetectionResult:
    zones: SegmentedZones
    dimensions: List[DetectedDimension]
    total_lines_detected: int
    total_candidates: int
    total_confirmed: int
    processing_time_ms: float
    debug_images: dict = field(default_factory=dict)

# ═══════════════════════════════════════════════════════════════════
# OCR PATTERNS
# ═══════════════════════════════════════════════════════════════════

DIMENSION_PATTERNS = [
    r'[ØD∅]\s*\d+\.?\d*\s*(?:mm|cm|m)?',
    r'R\s*\d+\.?\d*\s*(?:mm|cm|m)?',
    r'\d+\.?\d*\s*(?:mm|cm|m|in|")',
    r'\d+\.?\d*\s*°',
    r'\d+\.?\d*\s*[+\-±]\s*\d+\.?\d*(?:/[\-]?\d+\.?\d*)?',
    r'\d+\.\d+',
]
COMBINED_PATTERN = re.compile('(' + '|'.join(DIMENSION_PATTERNS) + ')', re.IGNORECASE)

# ═══════════════════════════════════════════════════════════════════
# UTILITY: QPixmap → cv BGR
# ═══════════════════════════════════════════════════════════════════

def qpixmap_to_cv(pixmap) -> np.ndarray:
    """Convert QPixmap to OpenCV BGR numpy array."""
    qimg = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
    W, H = qimg.width(), qimg.height()
    ptr = qimg.bits()
    ptr.setsize(H * W * 4)
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(H, W, 4).copy()
    return arr[:, :, :3]  # drop alpha → BGR

# ═══════════════════════════════════════════════════════════════════
# SECTION 2: PAPER SIZE & SCALE DETECTION
# ═══════════════════════════════════════════════════════════════════

# Reference dims: (short_side, long_side) at 150 dpi
_PAPER_REFS: Dict[PaperSize, Tuple[int, int]] = {
    PaperSize.A4: (1240, 1754),
    PaperSize.A3: (1754, 2480),
    PaperSize.A2: (2480, 3508),
    PaperSize.A1: (3508, 4961),
}
_A4_SHORT = 1240  # baseline

def detect_paper_size_and_scale(image: np.ndarray) -> Tuple[PaperSize, float, int]:
    H, W = image.shape[:2]
    short_s, long_s = min(H, W), max(H, W)
    best_paper, best_err, best_dpi = PaperSize.UNKNOWN, float('inf'), 150
    for paper, (ref_short, ref_long) in _PAPER_REFS.items():
        for dpi_mult in [1.0, 4/3, 2.0, 8/3]:  # 150, 200, 300, 400 dpi
            rs = int(ref_short * dpi_mult)
            rl = int(ref_long * dpi_mult)
            err = abs(short_s - rs) / rs + abs(long_s - rl) / rl
            if err < best_err:
                best_err = err
                best_paper = paper
                best_dpi = int(150 * dpi_mult)
    if best_err > 0.20:
        best_paper = PaperSize.UNKNOWN
    scale_factor = short_s / _A4_SHORT
    return best_paper, scale_factor, best_dpi

# ═══════════════════════════════════════════════════════════════════
# SECTION 3: ADAPTIVE PREPROCESSING
# ═══════════════════════════════════════════════════════════════════

def _odd(n: int) -> int:
    """Return n if odd, else n+1."""
    return n if n % 2 == 1 else n + 1

def preprocess_drawing_image(image: np.ndarray, scale_factor: float) -> dict:
    """Full preprocessing pipeline. Returns dict of images."""
    # Step 1: ensure grayscale
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    elif image.ndim == 2:
        gray = image.copy()
    else:
        gray = image[:, :, 0]

    # Step 2: CLAHE
    tile = max(4, int(8 * scale_factor))
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(tile, tile))
    clahe_img = clahe.apply(gray)

    # Step 3: Sauvola binarization
    if SKIMAGE_AVAILABLE:
        ws = _odd(int(25 * scale_factor))
        thresh = threshold_sauvola(clahe_img, window_size=ws, k=0.15)
        binary = (clahe_img > thresh).astype(np.uint8) * 255
    else:
        _, binary = cv2.threshold(clahe_img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Step 4: noise removal (opening with ellipse kernel)
    k_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k_open, iterations=1)

    # Step 5: Canny edges for Hough
    edges = cv2.Canny(clahe_img, 30, 90, apertureSize=3)

    # Step 6: dilated text binary
    tw = int(8 * scale_factor); th = int(3 * scale_factor)
    k_text = cv2.getStructuringElement(cv2.MORPH_RECT, (max(1,tw), max(1,th)))
    text_binary = cv2.dilate(binary, k_text, iterations=2)

    binary_inv = cv2.bitwise_not(binary)

    return {
        "gray": gray,
        "clahe": clahe_img,
        "binary": binary,
        "edges": edges,
        "text_binary": text_binary,
        "binary_inv": binary_inv,
    }

# ═══════════════════════════════════════════════════════════════════
# SECTION 4: ZONE SEGMENTATION
# ═══════════════════════════════════════════════════════════════════

def _hough_lines(img, threshold, min_len, max_gap):
    lines = cv2.HoughLinesP(img, 1, np.pi/180, threshold,
                             minLineLength=min_len, maxLineGap=max_gap)
    if lines is None:
        return []
    return [tuple(l[0]) for l in lines]

def _detect_border(edges, H, W, scale_factor) -> ZoneRect:
    margin = int(15 * scale_factor)
    thr = int(200 * scale_factor)
    lines = _hough_lines(edges, thr, int(W * 0.6), int(20 * scale_factor))
    top = margin; bottom = H - margin; left = margin; right = W - margin
    found = 0
    for x1, y1, x2, y2 in lines:
        ang = abs(math.degrees(math.atan2(y2-y1, x2-x1)))
        if ang < 10 or ang > 170:  # horizontal
            if y1 < H * 0.15: top = max(top, min(y1, y2)); found += 1
            if y1 > H * 0.85: bottom = min(bottom, max(y1, y2)); found += 1
        elif 80 < ang < 100:  # vertical
            if x1 < W * 0.15: left = max(left, min(x1, x2)); found += 1
            if x1 > W * 0.85: right = min(right, max(x1, x2)); found += 1
    return ZoneRect(left, top, right-left, bottom-top)

def _detect_title_block(binary, H, W, scale_factor) -> Tuple[Optional[ZoneRect], float]:
    sx = int(W * 0.55); sy = int(H * 0.72)
    roi = binary[sy:, sx:]
    rh, rw = roi.shape[:2]
    if rw < 10 or rh < 10:
        return None, 0.0
    thr = int(40 * scale_factor)
    min_len = int(rw * 0.20)
    lines = _hough_lines(roi, thr, min_len, int(5 * scale_factor))
    horiz = [(x1, y1+sy, x2, y2+sy) for x1, y1, x2, y2 in lines
             if abs(math.degrees(math.atan2(y2-y1, x2-x1))) < 3
             and abs(x2-x1) > rw*0.18]
    conf = 0.0
    if not horiz:
        # fallback
        tx = int(W * 0.60)
        return ZoneRect(tx, int(H * 0.72), W-tx, H-int(H*0.72)), 0.2
    conf += 0.4
    title_top = min(y1 for _, y1, _, _ in horiz)
    # find vertical separator
    vlines = [(x1+sx, y1+sy, x2+sx, y2+sy) for x1, y1, x2, y2 in
              _hough_lines(roi, thr, int(rh*0.5), int(5*scale_factor))
              if 80 < abs(math.degrees(math.atan2(y2-y1, x2-x1))) < 100
              and rw*0.1 < x1 < rw*0.8]
    if vlines:
        title_left = min(x1 for x1, _, _, _ in vlines) + sx
        conf += 0.3
    else:
        title_left = int(W * 0.60)
    if title_left > W*0.5 and title_top > H*0.6:
        conf += 0.3
    return ZoneRect(title_left, title_top, W-title_left, H-title_top), conf

def segment_drawing_zones_from_image(
    image: np.ndarray,
    preprocessed: dict,
    paper_size: PaperSize,
    scale_factor: float
) -> SegmentedZones:
    H, W = image.shape[:2]
    edges = preprocessed["edges"]
    text_bin = preprocessed["text_binary"]
    binary_inv = preprocessed["binary_inv"]

    # 4.1 Border
    border = _detect_border(edges, H, W, scale_factor)

    # 4.2 Title block
    tb_zone, tb_conf = _detect_title_block(preprocessed["binary"], H, W, scale_factor)
    seg_conf = tb_conf * 0.5

    # 4.3 Notes zone
    notes_zone = None
    if tb_zone:
        title_top = tb_zone.y
        title_left = tb_zone.x
        bl = border.x; br = title_left - 10
        if br > bl + 20:
            notes_roi = text_bin[title_top:H, bl:br]
            cnts, _ = cv2.findContours(notes_roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            text_cnts = []
            for c in cnts:
                cx2, cy2, cw2, ch2 = cv2.boundingRect(c)
                ar = cw2 / max(ch2, 1)
                if (cv2.contourArea(c) > 50 and 2.0 < ar < 25.0
                        and 6 < ch2 < int(20*scale_factor)):
                    text_cnts.append((cx2+bl, cy2+title_top, cw2, ch2))
            if len(text_cnts) >= 5:
                xs = [t[0] for t in text_cnts]; ys = [t[1] for t in text_cnts]
                xe = [t[0]+t[2] for t in text_cnts]; ye = [t[1]+t[3] for t in text_cnts]
                pad = int(10 * scale_factor)
                notes_zone = ZoneRect(max(0, min(xs)-pad), max(0, min(ys)-pad),
                                      max(xe)-min(xs)+2*pad, max(ye)-min(ys)+2*pad)

    # 4.4 View detection
    dz_x = border.x; dz_y = border.y
    dz_x2 = tb_zone.x if tb_zone else border.x2
    dz_y2 = (tb_zone.y if tb_zone else border.y2)
    dz_w = max(10, dz_x2 - dz_x); dz_h = max(10, dz_y2 - dz_y)

    # Dilate binary_inv in drawing zone to find view clusters
    ks = int(20 * scale_factor)
    k_rect = cv2.getStructuringElement(cv2.MORPH_RECT, (max(1,ks), max(1,ks)))
    roi_binv = binary_inv[dz_y:dz_y+dz_h, dz_x:dz_x+dz_w]
    dilated = cv2.dilate(roi_binv, k_rect, iterations=3)
    cnts, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    dz_area = dz_w * dz_h
    view_zones: List[ZoneRect] = []
    for c in cnts:
        vx, vy, vw, vh = cv2.boundingRect(c)
        a = vw * vh
        ar = vw / max(vh, 1)
        if dz_area*0.03 < a < dz_area*0.95 and 0.15 < ar < 6.5:
            view_zones.append(ZoneRect(vx+dz_x, vy+dz_y, vw, vh))
    # merge IoU > 0.3
    merged: List[ZoneRect] = []
    used = [False] * len(view_zones)
    for i, vA in enumerate(view_zones):
        if used[i]: continue
        rx, ry, rx2, ry2 = vA.x, vA.y, vA.x2, vA.y2
        for j in range(i+1, len(view_zones)):
            if used[j]: continue
            vB = view_zones[j]
            ix = max(0, min(rx2,vB.x2)-max(rx,vB.x))
            iy = max(0, min(ry2,vB.y2)-max(ry,vB.y))
            inter = ix*iy
            union = vA.area + vB.area - inter
            if union > 0 and inter/union > 0.3:
                rx, ry = min(rx,vB.x), min(ry,vB.y)
                rx2, ry2 = max(rx2,vB.x2), max(ry2,vB.y2)
                used[j] = True
        merged.append(ZoneRect(rx, ry, rx2-rx, ry2-ry))
        used[i] = True
    merged.sort(key=lambda z: -z.area)
    view_zones = merged[:6]

    # 4.5 Drawing zone
    drawing_zone = ZoneRect(dz_x, dz_y, dz_w, dz_h)
    total_area = W * H
    if (drawing_zone.area < total_area*0.25 or
            drawing_zone.w < W*0.35 or drawing_zone.h < H*0.35):
        drawing_zone = ZoneRect(int(W*0.05), int(H*0.05), int(W*0.60), int(H*0.70))
        seg_conf = min(seg_conf, 0.3)

    return SegmentedZones(
        paper_size=paper_size,
        full_image_shape=(H, W),
        drawing_zone=drawing_zone,
        title_block_zone=tb_zone,
        notes_zone=notes_zone,
        border_zone=border,
        view_zones=view_zones,
        scale_factor=scale_factor,
        segmentation_confidence=max(0.0, min(1.0, seg_conf)),
        detection_dpi_estimate=150,
    )


# ═══════════════════════════════════════════════════════════════════
# SECTION 5: LINE DETECTION
# ═══════════════════════════════════════════════════════════════════

def _line_orientation(angle_deg: float) -> LineOrientation:
    if angle_deg < 15 or angle_deg > 165:
        return LineOrientation.HORIZONTAL
    if 75 < angle_deg < 105:
        return LineOrientation.VERTICAL
    return LineOrientation.DIAGONAL


def detect_all_lines(preprocessed: dict, drawing_zone: ZoneRect, scale_factor: float) -> List[DetectedLine]:
    edges = preprocessed["edges"]
    dz = drawing_zone
    roi = edges[dz.y:dz.y2, dz.x:dz.x2]
    sf = scale_factor
    results: List[DetectedLine] = []

    passes = [
        dict(threshold=int(25*sf), minLineLength=int(15*sf), maxLineGap=int(4*sf)),
        dict(threshold=int(15*sf), minLineLength=int(8*sf),  maxLineGap=int(8*sf)),
        dict(threshold=int(60*sf), minLineLength=int(80*sf), maxLineGap=int(2*sf)),
    ]
    for p in passes:
        raw = cv2.HoughLinesP(roi, 1, np.pi/180, **p)
        if raw is None:
            continue
        for seg in raw:
            x1, y1, x2, y2 = seg[0]
            x1 += dz.x; x2 += dz.x; y1 += dz.y; y2 += dz.y
            dx = x2-x1; dy = y2-y1
            length = math.hypot(dx, dy)
            if length < 2:
                continue
            angle_deg = math.degrees(math.atan2(abs(dy), abs(dx)))
            orient = _line_orientation(angle_deg)
            results.append(DetectedLine(x1=x1, y1=y1, x2=x2, y2=y2,
                                        orientation=orient, length=length, angle_deg=angle_deg))

    # dedup: merge lines within 5*sf of each other
    tol = int(5 * sf)
    deduped: List[DetectedLine] = []
    used = [False] * len(results)
    for i, a in enumerate(results):
        if used[i]: continue
        best = a
        for j in range(i+1, len(results)):
            if used[j]: continue
            b = results[j]
            if b.orientation != a.orientation: continue
            if (abs(a.x1-b.x1) < tol and abs(a.y1-b.y1) < tol and
                    abs(a.x2-b.x2) < tol and abs(a.y2-b.y2) < tol):
                if b.length > best.length:
                    best = b
                used[j] = True
        # filter border lines
        edge_tol = int(25 * sf)
        if (min(best.x1, best.x2) < dz.x + edge_tol and
                max(best.x1, best.x2) < dz.x + edge_tol):
            continue
        deduped.append(best)
        used[i] = True
    return deduped


def _estimate_line_width(binary_inv: np.ndarray, line: DetectedLine) -> float:
    samples = []
    for t in [0.2, 0.35, 0.5, 0.65, 0.8]:
        mx = int(line.x1 + t*(line.x2-line.x1))
        my = int(line.y1 + t*(line.y2-line.y1))
        dx = line.x2-line.x1; dy = line.y2-line.y1
        length = max(line.length, 1)
        px, py = -dy/length, dx/length  # perpendicular
        count = 0
        for d in range(-5, 6):
            sx = int(mx + d*px); sy = int(my + d*py)
            if 0 <= sy < binary_inv.shape[0] and 0 <= sx < binary_inv.shape[1]:
                if binary_inv[sy, sx] > 127:
                    count += 1
        samples.append(count)
    return sum(samples)/max(len(samples), 1)


def detect_arrowheads(binary_inv: np.ndarray, line: DetectedLine, scale_factor: float) -> Tuple[bool, bool, float, float]:
    ps = int(18 * scale_factor)
    confs = []
    for px, py in [(line.x1, line.y1), (line.x2, line.y2)]:
        xs = max(0, px - ps//2); ys = max(0, py - ps//2)
        xe = min(binary_inv.shape[1], xs+ps); ye = min(binary_inv.shape[0], ys+ps)
        patch = binary_inv[ys:ye, xs:xe]
        conf = 0.0
        if patch.size > 0:
            cnts, _ = cv2.findContours(patch, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in cnts:
                area = cv2.contourArea(c)
                if area < 8: continue
                hull = cv2.convexHull(c)
                hull_area = cv2.contourArea(hull)
                if hull_area < 1: continue
                solidity = area / hull_area
                n_hull = len(hull)
                if solidity < 0.75 and 3 <= n_hull <= 7:
                    conf = max(conf, 1.0 - solidity)
        confs.append(min(1.0, conf))
    thr = 0.45
    return confs[0] >= thr, confs[1] >= thr, confs[0], confs[1]


def classify_dimension_lines(lines: List[DetectedLine], binary_inv: np.ndarray, scale_factor: float) -> List[DetectedLine]:
    sf = scale_factor
    min_len = int(12 * sf); max_len = int(300 * sf)
    for line in lines:
        if not (min_len <= line.length <= max_len):
            continue
        if _estimate_line_width(binary_inv, line) > 3:
            continue
        hs, he, cs, ce = detect_arrowheads(binary_inv, line, sf)
        line.has_arrowhead_start = hs
        line.has_arrowhead_end = he
        line.arrowhead_confidence_start = cs
        line.arrowhead_confidence_end = ce
    return lines


def pair_extension_lines(lines: List[DetectedLine], scale_factor: float) -> List[ExtensionLinePair]:
    tol = int(12 * scale_factor)
    dim_lines = [l for l in lines if l.is_dimension_line]
    ext_candidates = [l for l in lines if not l.has_arrowhead_start and not l.has_arrowhead_end]
    pairs: List[ExtensionLinePair] = []
    for dl in dim_lines:
        e1 = e2 = None
        if dl.orientation == LineOrientation.HORIZONTAL:
            for el in ext_candidates:
                if el.orientation != LineOrientation.VERTICAL: continue
                if el.length < int(10*scale_factor): continue
                ex = min(el.x1, el.x2)
                if abs(ex - dl.x1) < tol and min(el.y1,el.y2) <= dl.y1 <= max(el.y1,el.y2):
                    e1 = el
                elif abs(ex - dl.x2) < tol and min(el.y1,el.y2) <= dl.y2 <= max(el.y1,el.y2):
                    e2 = el
        elif dl.orientation == LineOrientation.VERTICAL:
            for el in ext_candidates:
                if el.orientation != LineOrientation.HORIZONTAL: continue
                if el.length < int(10*scale_factor): continue
                ey = min(el.y1, el.y2)
                if abs(ey - dl.y1) < tol and min(el.x1,el.x2) <= dl.x1 <= max(el.x1,el.x2):
                    e1 = el
                elif abs(ey - dl.y2) < tol and min(el.x1,el.x2) <= dl.x2 <= max(el.x1,el.x2):
                    e2 = el
        found = sum(x is not None for x in [e1, e2])
        conf = {2: 1.0, 1: 0.6, 0: 0.2}[found]
        pairs.append(ExtensionLinePair(dim_line=dl, ext_line_1=e1, ext_line_2=e2, pairing_confidence=conf))
    return pairs


# ═══════════════════════════════════════════════════════════════════
# SECTION 6: OCR PIPELINE
# ═══════════════════════════════════════════════════════════════════

def normalize_dimension_value(raw: str) -> str:
    t = raw.strip()
    t = t.replace('O', '0').replace('l', '1').replace('I', '1').replace('S', '5')
    t = re.sub(r'\s+', '', t)
    t = re.sub(r'r[nm]m?|m[nm]', 'mm', t, flags=re.I)
    t = re.sub(r'[ØD∅]', 'Ø', t)
    return t


def extract_dimension_roi(image_gray: np.ndarray, line: DetectedLine, scale_factor: float) -> Tuple[np.ndarray, Tuple[int,int,int,int]]:
    sf = scale_factor
    H, W = image_gray.shape[:2]
    x1, y1, x2, y2 = line.x1, line.y1, line.x2, line.y2
    bx, by = min(x1,x2), min(y1,y2)
    bx2, by2 = max(x1,x2), max(y1,y2)
    if line.orientation == LineOrientation.HORIZONTAL:
        pad_l = pad_r = int(20*sf); pad_t = int(35*sf); pad_b = int(15*sf)
    elif line.orientation == LineOrientation.VERTICAL:
        pad_l = int(10*sf); pad_r = int(50*sf); pad_t = pad_b = int(15*sf)
    else:
        pad_l = pad_r = pad_t = pad_b = int(40*sf)
    rx = max(0, bx-pad_l); ry = max(0, by-pad_t)
    rx2 = min(W, bx2+pad_r); ry2 = min(H, by2+pad_b)
    roi = image_gray[ry:ry2, rx:rx2].copy()
    if roi.size == 0:
        return np.zeros((10,10), dtype=np.uint8), (rx, ry, 10, 10)
    rh, rw = roi.shape[:2]
    if min(rh, rw) < 30:
        roi = cv2.resize(roi, (rw*2, rh*2), interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4,4))
    roi = clahe.apply(roi)
    roi = cv2.GaussianBlur(roi, (3,3), 0)
    return roi, (rx, ry, rx2-rx, ry2-ry)


def run_ocr_on_roi(roi: np.ndarray, roi_coords: Tuple[int,int,int,int]) -> Tuple[str, float, str]:
    best_val, best_conf, best_eng = "", 0.0, "none"
    # EasyOCR attempt
    reader = get_easyocr_reader()
    if reader is not None:
        try:
            results = reader.readtext(roi, detail=1, paragraph=False)
            for (_, text, conf) in results:
                if conf < 0.35: continue
                matches = COMBINED_PATTERN.findall(text)
                if matches and conf >= 0.55:
                    val = normalize_dimension_value(matches[0])
                    if conf > best_conf:
                        best_val, best_conf, best_eng = val, conf, "easyocr"
        except Exception:
            pass
    # Tesseract fallback
    if best_conf < 0.55 and TESSERACT_AVAILABLE:
        for psm in [7, 6]:
            try:
                cfg = f'--psm {psm} -c tessedit_char_whitelist=0123456789.Rrmm\u00b0\u00b1+/-\u00d8Dcminkgn'
                data = pytesseract.image_to_data(roi, config=cfg, output_type=pytesseract.Output.DICT)
                for i, txt in enumerate(data.get('text', [])):
                    c = int(data['conf'][i])
                    if c < 30 or not txt.strip(): continue
                    matches = COMBINED_PATTERN.findall(txt.strip())
                    if matches:
                        nconf = c / 100.0
                        if nconf > best_conf:
                            best_val = normalize_dimension_value(matches[0])
                            best_conf = nconf
                            best_eng = "tesseract"
            except Exception:
                pass
    return best_val, best_conf, best_eng


# ═══════════════════════════════════════════════════════════════════
# SECTION 7: CONFIDENCE SCORING
# ═══════════════════════════════════════════════════════════════════

def compute_detection_confidence(line: DetectedLine, extension_pair: Optional[ExtensionLinePair],
                                  ocr_value: str, ocr_confidence: float, scale_factor: float) -> float:
    score = 0.0
    cs = line.arrowhead_confidence_start; ce = line.arrowhead_confidence_end
    if cs >= 0.7 and ce >= 0.7:    score += 40
    elif cs >= 0.45 and ce >= 0.45: score += 30
    elif cs >= 0.45 or ce >= 0.45: score += 15
    if extension_pair:
        ep_c = extension_pair.pairing_confidence
        if ep_c >= 0.9:  score += 20
        elif ep_c >= 0.6: score += 15
        elif ep_c >= 0.3: score += 8
    if ocr_value:
        has_unit = bool(re.search(r'mm|cm|in|"', ocr_value, re.I))
        has_sym  = bool(re.search(r'[RØ°]', ocr_value))
        is_num   = bool(re.match(r'^\d+\.?\d*$', ocr_value))
        if has_unit:   score += 30 * ocr_confidence
        elif has_sym:  score += 28 * ocr_confidence
        elif is_num:   score += 20 * ocr_confidence
    sf = scale_factor
    if int(15*sf) < line.length < int(200*sf): score += 5
    if line.orientation in (LineOrientation.HORIZONTAL, LineOrientation.VERTICAL): score += 3
    if extension_pair and extension_pair.ext_line_1 and extension_pair.ext_line_2: score += 2
    return min(100.0, score)


# ═══════════════════════════════════════════════════════════════════
# SECTION 8: BALLOON PLACEMENT
# ═══════════════════════════════════════════════════════════════════

def _clamp(val, lo, hi): return max(lo, min(hi, val))


def compute_balloon_position(dim: DetectedDimension, placed: List[DetectedDimension],
                              drawing_zone: ZoneRect, scale_factor: float, idx: int
                              ) -> Tuple[Tuple[int,int], Tuple[int,int]]:
    sf = scale_factor
    br = int(15 * sf); ll = int(30 * sf)
    anchor = dim.line.midpoint
    ax, ay = anchor
    dz = drawing_zone; dcx, dcy = dz.center

    if dim.line.orientation == LineOrientation.HORIZONTAL:
        bcy = ay - ll - br if ay < dcy else ay + ll + br
        bcx = ax
    elif dim.line.orientation == LineOrientation.VERTICAL:
        bcx = ax - ll - br if ax < dcx else ax + ll + br
        bcy = ay
    else:
        ddx = ax - dcx; ddy = ay - dcy
        n = math.hypot(ddx, ddy) or 1
        bcx = ax + int(ddx/n*(ll+br)); bcy = ay + int(ddy/n*(ll+br))

    # collision resolution
    diam = br * 2
    for attempt in range(8):
        collision = False
        for p in placed:
            dist = math.hypot(bcx - p.balloon_center[0], bcy - p.balloon_center[1])
            if dist < diam * 1.3:
                collision = True; break
        if not collision:
            break
        angle = (attempt * 45) % 360
        od = diam * 1.5 * (1 + attempt * 0.5)
        bcx = ax + int(math.cos(math.radians(angle)) * od)
        bcy = ay + int(math.sin(math.radians(angle)) * od)

    bcx = _clamp(bcx, dz.x + br, dz.x2 - br)
    bcy = _clamp(bcy, dz.y + br, dz.y2 - br)
    return anchor, (bcx, bcy)


def sequence_balloons_by_flow(dims: List[DetectedDimension], drawing_zone: ZoneRect,
                               flow_direction: str) -> List[DetectedDimension]:
    if not dims: return dims
    cx, cy = drawing_zone.center
    start = -math.pi / 2

    def _angle(d):
        ax, ay = d.anchor_point
        a = math.atan2(ay - cy, ax - cx)
        return (a - start) % (2 * math.pi)

    reverse = flow_direction.lower() in ("clockwise", "cw")
    sorted_dims = sorted(dims, key=_angle, reverse=reverse)
    for i, d in enumerate(sorted_dims):
        d.balloon_number = i + 1
    return sorted_dims


# ═══════════════════════════════════════════════════════════════════
# WORKER API FUNCTIONS (called by processing_workers.py)
# ═══════════════════════════════════════════════════════════════════

def preprocess_drawing(state_obj: Any) -> None:
    """
    Worker API (Phase 1): Preprocess cv_image and store results in state.
    Updates: state.preprocessed_image, state.binary_image
    """
    img = state_obj.cv_image
    if img is None:
        raise ValueError("state.cv_image is None — load image first.")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img.copy()
    # Estimate scale from image size
    H, W = gray.shape[:2]
    _, scale_factor, _ = detect_paper_size_and_scale(gray)
    preprocessed = preprocess_drawing_image(gray, scale_factor)
    state_obj.preprocessed_image = preprocessed["clahe"]
    state_obj.binary_image       = preprocessed["binary"]


def detect_zones(state_obj: Any) -> Dict[str, Tuple[int,int,int,int]]:
    """
    Worker API (Phase 1b): Segment drawing into zones, update state.zones.
    Returns dict with keys 'drawing', 'notes', 'bom'.
    """
    gray = state_obj.preprocessed_image
    binary = state_obj.binary_image
    if gray is None or binary is None:
        raise ValueError("Run preprocess_drawing first.")
    H, W = gray.shape[:2]
    paper_size, scale_factor, _ = detect_paper_size_and_scale(gray)
    preprocessed = preprocess_drawing_image(gray, scale_factor)
    zones_obj = segment_drawing_zones_from_image(gray, preprocessed, paper_size, scale_factor)
    dz = zones_obj.drawing_zone
    drawing_rect = dz.to_tuple()
    notes_rect = zones_obj.notes_zone.to_tuple() if zones_obj.notes_zone else (0, int(H*0.75), int(W*0.25), int(H*0.25))
    tb = zones_obj.title_block_zone
    bom_rect = tb.to_tuple() if tb else (int(W*0.70), int(H*0.75), int(W*0.30), int(H*0.25))
    zones = {"drawing": drawing_rect, "notes": notes_rect, "bom": bom_rect}
    state_obj.zones = zones
    return zones


def detect_views(state_obj: Any, progress_callback: Optional[Callable[[str,int],None]] = None) -> List[DetectedView]:
    """
    Worker API (Phase 2): Detect orthographic view regions.
    Populates state.detected_views and returns them.
    """
    gray = state_obj.preprocessed_image
    binary = state_obj.binary_image
    drawing_zone_tuple = state_obj.zones.get("drawing")
    if gray is None or binary is None or not drawing_zone_tuple:
        logger.error("detect_views: missing state data.")
        return []

    if progress_callback: progress_callback("Preprocessing for view detection", 10)
    H, W = gray.shape[:2]
    _, scale_factor, _ = detect_paper_size_and_scale(gray)
    preprocessed = preprocess_drawing_image(gray, scale_factor)
    dz_x, dz_y, dz_w, dz_h = drawing_zone_tuple
    drawing_zone = ZoneRect(dz_x, dz_y, dz_w, dz_h)

    if progress_callback: progress_callback("Morphological view clustering", 30)
    binary_inv = preprocessed["binary_inv"]
    ks = int(20 * scale_factor)
    k_rect = cv2.getStructuringElement(cv2.MORPH_RECT, (max(1,ks), max(1,ks)))
    roi_binv = binary_inv[dz_y:dz_y+dz_h, dz_x:dz_x+dz_w]
    dilated = cv2.dilate(roi_binv, k_rect, iterations=3)
    cnts, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    dz_area = dz_w * dz_h
    candidates = []
    for c in cnts:
        vx, vy, vw, vh = cv2.boundingRect(c)
        a = vw*vh; ar = vw/max(vh,1)
        if dz_area*0.03 < a < dz_area*0.90 and 0.15 < ar < 6.5:
            candidates.append((vx+dz_x, vy+dz_y, vw, vh))

    if progress_callback: progress_callback("OCR label matching", 60)
    # OCR for view labels
    view_labels = ["FRONT VIEW","TOP VIEW","RIGHT SIDE VIEW","LEFT SIDE VIEW","BOTTOM VIEW","DETAIL VIEW"]
    import re as _re
    ocr_matches = []
    reader = get_easyocr_reader()
    if reader:
        try:
            crop_gray = gray[dz_y:dz_y+dz_h, dz_x:dz_x+dz_w]
            ocr_results = reader.readtext(crop_gray, detail=1, paragraph=False)
            KNOWN = _re.compile(r'(FRONT|TOP|SIDE|REAR|BOTTOM|LEFT|RIGHT|SECTION|DETAIL|ISOMETRIC|VIEW)', _re.I)
            for bbox_pts, text, conf in ocr_results:
                if KNOWN.search(text):
                    pts = np.array(bbox_pts)
                    cx2 = float(np.mean(pts[:,0])) + dz_x
                    cy2 = float(np.mean(pts[:,1])) + dz_y
                    ocr_matches.append((cx2, cy2, text.strip().upper(), conf))
        except Exception:
            pass

    if progress_callback: progress_callback("Building DetectedView list", 80)
    # Deduplicate candidates by IoU
    used = [False]*len(candidates)
    merged = []
    for i, ca in enumerate(candidates):
        if used[i]: continue
        rx,ry,rx2,ry2 = ca[0],ca[1],ca[0]+ca[2],ca[1]+ca[3]
        for j in range(i+1,len(candidates)):
            if used[j]: continue
            cb = candidates[j]
            ix = max(0,min(rx2,cb[0]+cb[2])-max(rx,cb[0]))
            iy = max(0,min(ry2,cb[1]+cb[3])-max(ry,cb[1]))
            inter = ix*iy
            union = ca[2]*ca[3]+cb[2]*cb[3]-inter
            if union > 0 and inter/union > 0.40:
                rx,ry = min(rx,cb[0]),min(ry,cb[1])
                rx2,ry2 = max(rx2,cb[0]+cb[2]),max(ry2,cb[1]+cb[3])
                used[j]=True
        merged.append((rx,ry,rx2-rx,ry2-ry))
        used[i]=True

    if not merged:
        merged = [(dz_x, dz_y, dz_w, dz_h)]

    merged.sort(key=lambda b: (b[1]//200, b[0]))
    detected_views: List[DetectedView] = []
    for vid, bbox in enumerate(merged[:6], start=1):
        vx,vy,vw,vh = bbox
        vcx = vx+vw/2; vcy = vy+vh/2
        label = None; conf = 0.5; src = "inferred"
        if ocr_matches:
            dists = [math.hypot(m[0]-vcx, m[1]-vcy) for m in ocr_matches]
            idx = int(np.argmin(dists))
            if dists[idx] < 0.3 * max(vw, vh):
                label = ocr_matches[idx][2]; conf = ocr_matches[idx][3]; src = "ocr"
        if label is None:
            label = view_labels[vid-1] if vid-1 < len(view_labels) else f"VIEW_{vid}"
        detected_views.append(DetectedView(view_id=vid, label=label, bbox=bbox,
                                            confidence=conf, label_source=src))
    if progress_callback: progress_callback("View detection complete", 100)
    state_obj.detected_views = detected_views
    return detected_views


def detect_dimensions_in_view(view: DetectedView, state_obj: Any,
                               image_to_scene: Callable[[int,int],Any]) -> List[Any]:
    """
    Worker API (Phase 5): Detect dimensions in one view, return list of Balloon dataclass objects.
    """
    gray = state_obj.preprocessed_image
    binary = state_obj.binary_image
    if gray is None or binary is None:
        return []

    H, W = gray.shape[:2]
    _, scale_factor, _ = detect_paper_size_and_scale(gray)
    preprocessed = preprocess_drawing_image(gray, scale_factor)
    vx, vy, vw, vh = view.bbox
    drawing_zone = ZoneRect(vx, vy, vw, vh)

    all_lines = detect_all_lines(preprocessed, drawing_zone, scale_factor)
    classified = classify_dimension_lines(all_lines, preprocessed["binary_inv"], scale_factor)
    paired = pair_extension_lines(classified, scale_factor)

    dim_lines = [p.dim_line for p in paired if p.dim_line.is_dimension_line]
    leader_lines = [l for l in classified if l.is_leader_line and l.length > int(20*scale_factor)]
    candidates = dim_lines + leader_lines

    confirmed: List[DetectedDimension] = []
    for line in candidates:
        try:
            roi, roi_coords = extract_dimension_roi(gray, line, scale_factor)
            value, ocr_conf, engine = run_ocr_on_roi(roi, roi_coords)
        except Exception:
            value, ocr_conf, engine = "", 0.0, "none"
        ext_pair = next((p for p in paired if p.dim_line is line), None)
        conf = compute_detection_confidence(line, ext_pair, value, ocr_conf, scale_factor)
        if conf < 50 and not value:
            continue
        if value.upper().startswith('R'):
            dt = DimensionType.RADIUS
        elif 'Ø' in value or value.upper().startswith('D'):
            dt = DimensionType.DIAMETER
        elif '°' in value:
            dt = DimensionType.ANGULAR
        elif line.orientation == LineOrientation.VERTICAL:
            dt = DimensionType.LINEAR_VERTICAL
        else:
            dt = DimensionType.LINEAR_HORIZONTAL
        dim = DetectedDimension(
            dim_type=dt, line=line, extension_pair=ext_pair,
            ocr_value_raw=value, ocr_value_clean=normalize_dimension_value(value),
            ocr_confidence=ocr_conf, ocr_engine_used=engine, ocr_bbox=roi_coords,
            anchor_point=(0,0), balloon_center=(0,0),
            detection_confidence=conf, view_id=str(view.view_id)
        )
        confirmed.append(dim)

    placed: List[DetectedDimension] = []
    for i, dim in enumerate(confirmed):
        anchor, bc = compute_balloon_position(dim, placed, drawing_zone, scale_factor, i)
        dim.anchor_point = anchor; dim.balloon_center = bc
        placed.append(dim)

    sequenced = sequence_balloons_by_flow(placed, drawing_zone,
                                           state_obj.flow_direction or "CW")

    _DT_MAP = {
        DimensionType.LINEAR_HORIZONTAL: "linear_h",
        DimensionType.LINEAR_VERTICAL:   "linear_v",
        DimensionType.ANGULAR:           "angular",
        DimensionType.RADIUS:            "radial",
        DimensionType.DIAMETER:          "circular",
        DimensionType.ORDINATE:          "linear_h",
    }

    balloons = []
    for dim in sequenced:
        pos_scene = image_to_scene(dim.balloon_center[0], dim.balloon_center[1])
        b = BalloonDC(
            balloon_id=generate_id(),
            view_id=view.view_id,
            dim_type=_DT_MAP.get(dim.dim_type, "linear_h"),
            value=dim.ocr_value_clean or "—",
            tolerance="",
            unit="mm",
            confidence=int(dim.detection_confidence),
            position_scene=pos_scene,
            position_image=dim.balloon_center,
            is_flagged=dim.detection_confidence < 50,
            is_manual=False,
            sequence_number=dim.balloon_number,
        )
        balloons.append(b)
    return balloons


def detect_notes(img: Any, gray: np.ndarray, thresh: np.ndarray,
                 zones: dict, start_number: int):
    """Worker API: extract notes-zone text balloons."""
    if not zones.get("notes"):
        return [], start_number
    nx, ny, nw, nh = zones["notes"]
    roi_gray = gray[ny:ny+nh, nx:nx+nw]
    results = []
    reader = get_easyocr_reader()
    if reader:
        try:
            results = reader.readtext(roi_gray)
        except Exception:
            pass
    note_balloons = []
    cur = start_number
    for (bbox, text, prob) in results:
        if re.match(r'^\d+[.\-)]', text.strip()) or prob > 0.5:
            lx = int(bbox[0][0]) + nx; ly = int(bbox[0][1]) + ny
            note_balloons.append({"id": generate_id(), "number": cur, "type": "note",
                                   "text": text, "x": float(lx), "y": float(ly),
                                   "viewId": None, "confidence": int(prob*100), "zoneType": "notes"})
            cur += 1
    return note_balloons, cur


def detect_bom(img: Any, gray: np.ndarray, thresh: np.ndarray,
               zones: dict, start_number: int):
    """Worker API: extract BOM-zone row balloons."""
    if not zones.get("bom"):
        return [], start_number
    bx, by, bw, bh = zones["bom"]
    roi_thresh = thresh[by:by+bh, bx:bx+bw]
    roi_gray   = gray[by:by+bh, bx:bx+bw]
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(1,bw//2), 1))
    hor = cv2.morphologyEx(roi_thresh, cv2.MORPH_OPEN, h_kernel, iterations=2)
    cnts, _ = cv2.findContours(hor, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = sorted(cnts, key=lambda c: cv2.boundingRect(c)[1])
    bom_balloons = []; cur = start_number
    for i in range(len(cnts)-1):
        y1 = cv2.boundingRect(cnts[i])[1]; y2 = cv2.boundingRect(cnts[i+1])[1]
        if y2 - y1 < 10: continue
        row_roi = roi_gray[y1:y2, 0:bw]
        row_text = ""
        if TESSERACT_AVAILABLE:
            try: row_text = pytesseract.image_to_string(row_roi).strip()
            except Exception: pass
        if not row_text: continue
        bom_balloons.append({"id": generate_id(), "number": cur, "type": "bom",
                              "x": float(bx+10), "y": float(by+y1+(y2-y1)/2),
                              "itemNumber": str(i+1), "description": row_text,
                              "quantity": "1", "material": "", "notes": "",
                              "viewId": None, "confidence": 70, "zoneType": "bom"})
        cur += 1
    return bom_balloons, cur


def debug_visualize_all(image: np.ndarray, zones: SegmentedZones, views: List[DetectedView], dims: List[DetectedDimension]) -> np.ndarray:
    """
    Visualization utility for debugging the CV pipeline.
    Draws zones, views, lines, and OCR boxes onto a copy of the image.
    """
    vis = image.copy()
    
    # 1. Draw Zones
    if zones.drawing_zone:
        x, y, w, h = zones.drawing_zone.to_tuple()
        cv2.rectangle(vis, (x, y), (x+w, y+h), (255, 0, 0), 3)
        cv2.putText(vis, "DRAWING ZONE", (x+10, y+30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
        
    if zones.title_block_zone:
        x, y, w, h = zones.title_block_zone.to_tuple()
        cv2.rectangle(vis, (x, y), (x+w, y+h), (0, 0, 255), 3)
        cv2.putText(vis, "TITLE BLOCK", (x+10, y+30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        
    if zones.notes_zone:
        x, y, w, h = zones.notes_zone.to_tuple()
        cv2.rectangle(vis, (x, y), (x+w, y+h), (0, 255, 255), 3)
        cv2.putText(vis, "NOTES", (x+10, y+30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        
    # 2. Draw Views
    for view in views:
        vx, vy, vw, vh = view.bbox
        cv2.rectangle(vis, (vx, vy), (vx+vw, vy+vh), (0, 255, 0), 2)
        cv2.putText(vis, view.label, (vx+10, vy+30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
    # 3. Draw Dimensions and Lines
    for dim in dims:
        # Draw the line
        l = dim.line
        color = (255, 0, 255) if l.orientation == LineOrientation.HORIZONTAL else (255, 255, 0)
        cv2.line(vis, (l.x1, l.y1), (l.x2, l.y2), color, 2)
        
        # Draw extension lines if present
        if dim.extension_pair:
            for ext_l in [dim.extension_pair.ext_line_1, dim.extension_pair.ext_line_2]:
                if ext_l:
                    cv2.line(vis, (ext_l.x1, ext_l.y1), (ext_l.x2, ext_l.y2), (100, 100, 100), 1)
        
        # Draw anchor and balloon center
        ax, ay = dim.anchor_point
        cv2.circle(vis, (int(ax), int(ay)), 4, (0, 0, 255), -1)
        bx, by = dim.balloon_center
        cv2.line(vis, (int(ax), int(ay)), (int(bx), int(by)), (0, 165, 255), 1) # Orange leader to balloon
        cv2.circle(vis, (int(bx), int(by)), 20, (0, 165, 255), 2)
        cv2.putText(vis, str(dim.balloon_number), (int(bx)-10, int(by)+8), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
        
        # Draw OCR text and bounding box if available
        if dim.ocr_bbox:
            ox, oy, ow, oh = dim.ocr_bbox
            cv2.rectangle(vis, (ox, oy), (ox+ow, oy+oh), (128, 0, 128), 1)
            cv2.putText(vis, dim.ocr_value_clean, (ox, oy-5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (128, 0, 128), 1)
            
    return vis# ─────────────────────────────────────────────────────────────────
# LEGACY stub kept for backward compatibility with old imports
# ─────────────────────────────────────────────────────────────────

def autodetect_run(image_data_pixmap, flow_direction: str = "clockwise"):
    """
    Legacy entry point — kept for backward compatibility.
    main_window.py does not call this in V2; workers call the functions above.
    Returns (balloons_list, views_list) as plain dicts for scene compatibility.
    """
    if image_data_pixmap is None:
        return [], []
    try:
        img_bgr = qpixmap_to_cv(image_data_pixmap)
        img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        paper_size, scale_factor, est_dpi = detect_paper_size_and_scale(img_gray)
        preprocessed = preprocess_drawing_image(img_gray, scale_factor)
        try:
            zones_obj = segment_drawing_zones_from_image(img_gray, preprocessed, paper_size, scale_factor)
        except Exception:
            H, W = img_gray.shape[:2]
            zones_obj = SegmentedZones(
                paper_size=PaperSize.UNKNOWN, full_image_shape=(H, W),
                drawing_zone=ZoneRect(int(W*0.03),int(H*0.03),int(W*0.65),int(H*0.72)),
                title_block_zone=None, notes_zone=None, border_zone=None, view_zones=[],
                scale_factor=1.0, segmentation_confidence=0.0, detection_dpi_estimate=150)
        if zones_obj.segmentation_confidence < 0.3:
            H, W = img_gray.shape[:2]
            zones_obj.drawing_zone = ZoneRect(int(W*0.03),int(H*0.03),int(W*0.65),int(H*0.72))
        dz = zones_obj.drawing_zone
        all_lines = detect_all_lines(preprocessed, dz, scale_factor)
        classified = classify_dimension_lines(all_lines, preprocessed["binary_inv"], scale_factor)
        paired = pair_extension_lines(classified, scale_factor)
        dim_lines = [p.dim_line for p in paired if p.dim_line.is_dimension_line]
        leader_lines = [l for l in classified if l.is_leader_line and l.length > int(20*scale_factor)]
        confirmed: List[DetectedDimension] = []
        placed: List[DetectedDimension] = []
        for line in dim_lines + leader_lines:
            try:
                roi, roi_coords = extract_dimension_roi(img_gray, line, scale_factor)
                value, ocr_conf, engine = run_ocr_on_roi(roi, roi_coords)
            except Exception:
                value, ocr_conf, engine = "", 0.0, "none"
            ext_pair = next((p for p in paired if p.dim_line is line), None)
            conf = compute_detection_confidence(line, ext_pair, value, ocr_conf, scale_factor)
            if conf < 50 and not value:
                continue
            if value.upper().startswith('R'):  dt = DimensionType.RADIUS
            elif 'Ø' in value:                 dt = DimensionType.DIAMETER
            elif '°' in value:                 dt = DimensionType.ANGULAR
            elif line.orientation == LineOrientation.VERTICAL: dt = DimensionType.LINEAR_VERTICAL
            else:                              dt = DimensionType.LINEAR_HORIZONTAL
            view_id = "view_0"
            for vi, vz in enumerate(zones_obj.view_zones):
                if vz.contains_point(*line.midpoint):
                    view_id = f"view_{vi}"; break
            dim = DetectedDimension(
                dim_type=dt, line=line, extension_pair=ext_pair,
                ocr_value_raw=value, ocr_value_clean=normalize_dimension_value(value),
                ocr_confidence=ocr_conf, ocr_engine_used=engine, ocr_bbox=roi_coords,
                anchor_point=(0,0), balloon_center=(0,0),
                detection_confidence=conf, view_id=view_id)
            anchor, bc = compute_balloon_position(dim, placed, dz, scale_factor, len(placed))
            dim.anchor_point = anchor; dim.balloon_center = bc
            confirmed.append(dim); placed.append(dim)
        sequenced = sequence_balloons_by_flow(confirmed, dz, flow_direction)
        display_scale = state.get("scale", 1.0)
        _DT_MAP = {
            DimensionType.LINEAR_HORIZONTAL: "linear",
            DimensionType.LINEAR_VERTICAL:   "linear",
            DimensionType.ANGULAR:           "angular",
            DimensionType.RADIUS:            "radius",
            DimensionType.DIAMETER:          "circular",
            DimensionType.ORDINATE:          "linear",
        }
        new_balloons = []
        for dim in sequenced:
            sx = dim.balloon_center[0] * display_scale
            sy = dim.balloon_center[1] * display_scale
            new_balloons.append({
                "id":            generate_id(),
                "number":        dim.balloon_number,
                "type":          "dimension",
                "x":             float(sx),
                "y":             float(sy),
                "viewId":        dim.view_id,
                "dimensionType": _DT_MAP.get(dim.dim_type, "linear"),
                "value":         dim.ocr_value_clean,
                "flowDirection": flow_direction,
            })
        view_names = ["FRONT VIEW","TOP VIEW","RIGHT SIDE VIEW","LEFT SIDE VIEW","BOTTOM VIEW","DETAIL VIEW"]
        new_views = []
        for i, vz in enumerate(zones_obj.view_zones):
            new_views.append({"id": f"view_{i}",
                               "name": view_names[i] if i < len(view_names) else f"VIEW {i+1}",
                               "type": "AUTO"})
        if not new_views:
            new_views.append({"id": "view_0", "name": "MAIN VIEW", "type": "AUTO"})
        return new_balloons, new_views
    except MemoryError:
        logger.error("autodetect_run: MemoryError — image too large")
        return [], []
    except cv2.error as e:
        logger.error("autodetect_run: OpenCV error: %s", e)
        return [], []
    except Exception as e:
        logger.exception("autodetect_run: unexpected error")
        return [], []


# ─────────────────────────────────────────────────────────────────
# LEGACY stubs for old-style imports
# ─────────────────────────────────────────────────────────────────

def preprocess_image(*args, **kwargs):
    raise NotImplementedError("Refactored: use preprocess_drawing(state) instead.")

def segment_zones(*args, **kwargs):
    raise NotImplementedError("Refactored: use detect_zones(state) instead.")

def detect_dimensions(*args, **kwargs):
    raise NotImplementedError("Refactored: use detect_dimensions_in_view(view, state, fn) instead.")

def calculate_iou(boxA, boxB) -> float:
    xA, yA = max(boxA[0], boxB[0]), max(boxA[1], boxB[1])
    xB, yB = min(boxA[0]+boxA[2], boxB[0]+boxB[2]), min(boxA[1]+boxA[3], boxB[1]+boxB[3])
    inter = max(0, xB-xA) * max(0, yB-yA)
    union = boxA[2]*boxA[3] + boxB[2]*boxB[3] - inter
    return inter/union if union > 0 else 0.0

def detect_paper_size(width, height) -> str:
    ratio = max(width,height)/min(width,height)
    if abs(ratio-1.414) < 0.15:
        if width > 7000: return "A1"
        if width > 5000: return "A2"
        if width > 3500: return "A3"
        return "A4"
    return "Custom"

def point_to_line_dist(p, a, b) -> float:
    px,py=p; ax,ay=a; bx,by=b
    lsq=(bx-ax)**2+(by-ay)**2
    if lsq==0: return math.hypot(px-ax,py-ay)
    t=max(0,min(1,((px-ax)*(bx-ax)+(py-ay)*(by-ay))/lsq))
    return math.hypot(px-(ax+t*(bx-ax)), py-(ay+t*(by-ay)))

def sort_balloons(balloons, views, ordering_mode):
    """Legacy sort helper."""
    return balloons
