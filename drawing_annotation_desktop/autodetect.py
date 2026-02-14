import cv2
import numpy as np
import math
from state import generate_id
from PyQt6.QtGui import QImage

def autodetect_run(image_data_pixmap, flow_direction="pid"):
    """
    Run auto-detection on the loaded QPixmap.
    Args:
        image_data_pixmap (QPixmap): The loaded image.
        flow_direction (str): 'clockwise' or 'anticlockwise'.
    Returns:
        tuple: (new_balloons, new_views)
    """
    if image_data_pixmap is None:
        return [], []

    # Convert QPixmap to standard numpy array for OpenCV
    # Save to temp file or convert buffer? 
    # QPixmap -> QImage -> bits -> numpy
    qimg = image_data_pixmap.toImage()
    qimg = qimg.convertToFormat(QImage.Format.Format_RGB32)
    width = qimg.width()
    height = qimg.height()
    
    ptr = qimg.bits()
    ptr.setsize(height * width * 4)
    arr = np.array(ptr).reshape(height, width, 4)  # BGRA
    
    # RGB only
    img = arr[:, :, :3]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 1. Detect Views
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)) # Larger kernel to merge elements
    dilated = cv2.dilate(thresh, kernel, iterations=3)
    
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    view_bboxes = []
    min_area = (width * height) * 0.02 # 2% area threshold
    
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w * h > min_area:
            view_bboxes.append((x, y, w, h))
            
    # Sort views (Top-Left priority)
    # Sort by Y-row (approx), then X
    # We bin Y by 100px to group items in the same "row"
    view_bboxes.sort(key=lambda b: (b[1] // 200, b[0]))
    
    new_views = []
    new_balloons = []
    balloon_counter = 1
    
    # If no views detected, treat whole image as one view
    if not view_bboxes:
        view_bboxes.append((0, 0, width, height))

    for i, (vx, vy, vw, vh) in enumerate(view_bboxes):
        view_id = generate_id()
        view_name = f"View {i+1}"
        new_views.append({"id": view_id, "name": view_name, "type": "AUTO"})
        
        # ROI for features
        roi_gray = gray[vy:vy+vh, vx:vx+vw]
        roi_thresh = thresh[vy:vy+vh, vx:vx+vw]
        
        # Detect candidates (blobs)
        # Use smaller kernel for features
        f_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        f_dilated = cv2.dilate(roi_thresh, f_kernel, iterations=1)
        
        f_contours, _ = cv2.findContours(f_dilated, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        
        candidates = []
        for fc in f_contours:
            fx, fy, fw, fh = cv2.boundingRect(fc)
            area = fw * fh
            # Filter noise and huge things
            if area < 50 or area > (vw * vh * 0.2):
                continue
            
            # Center in global coords
            cx = vx + fx + fw / 2
            cy = vy + fy + fh / 2
            candidates.append((cx, cy))
            
        if not candidates:
            continue
            
        # Sequence candidates
        # "Top-Left most" first
        # We find the top-left-most point to start
        candidates.sort(key=lambda p: p[0] + p[1])
        start_point = candidates[0]
        
        remaining = candidates[1:]
        ordered = [start_point]
        
        current = start_point
        
        # Greedy standard path or Radial?
        # User asked for "Flow detection... Clockwise/Anti-clockwise"
        # Let's do a center-based radial sort for the rest
        
        view_cx = vx + vw / 2
        view_cy = vy + vh / 2
        
        def get_angle(p):
            return math.atan2(p[1] - view_cy, p[0] - view_cx)
            
        # Sort remaining by angle
        remaining.sort(key=get_angle, reverse=(flow_direction == "anticlockwise"))
        
        # If we want literal flow from start point, nearest neighbor might be better?
        # But radial is more predictable "Clockwise".
        ordered.extend(remaining)
        
        # Create Balloons
        for cx, cy in ordered:
             # Dedup: check if close to existing in this view
             if any(abs(cx - b["x"]) < 15 and abs(cy - b["y"]) < 15 for b in new_balloons):
                 continue
                 
             new_balloons.append({
                "id": generate_id(),
                "number": balloon_counter,
                "type": "dimension",
                "x": float(cx),
                "y": float(cy),
                "viewId": view_id,
                "dimensionType": "linear",
                "flowDirection": flow_direction,
                "value": "" # Auto-detected value would require OCR
            })
             balloon_counter += 1
             
    return new_balloons, new_views
