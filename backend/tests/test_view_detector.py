
import pytest
import numpy as np
import cv2
import os
import sys

# Ensure backend folder is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from backend.services.view_detector import ViewDetector

def create_shapes_image(width=1000, height=800):
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:] = (255, 255, 255) # White background
    
    # Draw "Front View" (Top-Left) - Rectangle
    cv2.rectangle(img, (50, 50), (400, 300), (0, 0, 0), 2)
    # Fill clearly to ensure morphological closing picks it up as a block
    cv2.rectangle(img, (60, 60), (390, 290), (0, 0, 0), -1) 
    
    # Draw "Side View" (Top-Right) - Circle
    cv2.circle(img, (700, 200), 100, (0, 0, 0), -1)
    
    return img

def test_detect_views_fallback():
    detector = ViewDetector(model_path="nonexistent_model.pt") # Force fallback
    img = create_shapes_image()
    
    views = detector.detect_views(img)
    
    assert len(views) >= 2
    
    # Verify we found the "Front View" (approx large rect at top-left)
    front_found = False
    side_found = False
    
    for v in views:
        x, y, w, h = v['bbox']
        cx = x + w/2
        cy = y + h/2
        
        if cx < 500 and cy < 400:
            front_found = True
        elif cx > 500 and cy < 400: # Side view circle
            side_found = True
            
        assert "view_id" in v
        assert "spatial_order" in v
        
    assert front_found
    assert side_found

if __name__ == "__main__":
    test_detect_views_fallback()
