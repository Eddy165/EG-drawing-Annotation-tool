
import cv2
import numpy as np
import os
from typing import List, Dict, Any, Tuple
from ultralytics import YOLO

class ViewDetector:
    def __init__(self, model_path: str = "backend/models/yolov8_views.pt"):
        self.model_path = model_path
        self.model = None
        # Load YOLO model if available
        if os.path.exists(model_path):
            try:
                self.model = YOLO(model_path)
            except Exception as e:
                print(f"Warning: Could not load YOLO model: {e}")
        else:
            print(f"Warning: Model not found at {model_path}, using fallback only.")

    def detect_views(self, image: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detects views (Front, Top, Side, Section) in the drawing.
        Returns a list of views with bounding boxes and labels.
        """
        views = []
        
        # 1. Try YOLO detection
        if self.model:
            results = self.model(image)
            for r in results:
                boxes = r.boxes
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = box.conf[0].item()
                    cls = int(box.cls[0].item())
                    label = self.model.names[cls]
                    
                    views.append({
                        "label": label,
                        "bbox": [int(x1), int(y1), int(x2-x1), int(y2-y1)], # x, y, w, h
                        "confidence": conf,
                        "source": "yolo"
                    })
        
        # 2. If no views found or model missing, use Rule-Based Fallback
        if not views:
            views = self._detect_views_fallback(image)
            
        # 3. Sort views spatially (Top-Left to Bottom-Right)
        # We sort by Y primarily (with a threshold) then X
        views = self._sort_views_spatially(views)
        
        # 4. Assign IDs
        for i, view in enumerate(views):
            view["view_id"] = f"view_{i+1}"
            view["spatial_order"] = i + 1
            
        return views

    def _detect_views_fallback(self, image: np.ndarray) -> List[Dict[str, Any]]:
        """
        Rule-based detection using contour analysis.
        Assumes views are large, distinct rectangular regions.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Binarize and invert (contours are white on black)
        _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
        
        # Morphological operations to close gaps between lines in a view
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 20))
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
        
        # Find contours
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        height, width = image.shape[:2]
        total_area = height * width
        min_area = total_area * 0.05 # Minimum 5% of screen
        
        detected_views = []
        
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            
            if area > min_area:
                # Heuristic labelling based on position
                cx, cy = x + w/2, y + h/2
                
                label = "Unknown View"
                
                # Split screen into quadrants for guessing
                if cx < width/2 and cy < height/2:
                    label = "Front View" # Often top-left (First Angle) or Front
                elif cx >= width/2 and cy < height/2:
                    label = "Side View"
                elif cx < width/2 and cy >= height/2:
                    label = "Top View"
                else:
                    label = "Section View"
                    
                detected_views.append({
                    "label": label,
                    "bbox": [x, y, w, h],
                    "confidence": 0.5, # Low confidence for fallback
                    "source": "rule_based"
                })
                
        return detected_views

    def _sort_views_spatially(self, views: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sorts views line-by-line (Top to Bottom, Left to Right).
        """
        # Sort by Y first (with a tolerance/binning), then X
        # Tolerance: if Y diff is small, consider them on same 'row'
        
        # Simple sorting key: (approx_y, x)
        # We can normalize Y to be integer steps of e.g., 10% of image height?
        # Since we don't have image height here easily in this method without passing it,
        # let's just use raw coordinates but be careful.
        # Actually usually engineering drawing views are well separated.
        
        return sorted(views, key=lambda v: (v['bbox'][1] // 100, v['bbox'][0]))

