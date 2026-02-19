
import pytest
import numpy as np
import cv2
import os
import sys

# Ensure backend folder is in path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from backend.services.preprocessor import Preprocessor
from backend.utils.constants import CANONICAL_LONG_EDGE_PX, PAPER_SIZES_MM

def create_dummy_image(width=1000, height=500, color=(255, 255, 255)):
    # Create a white image
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:] = color
    # Draw a line to test deskew (optional)
    cv2.line(img, (100, 100), (900, 150), (0, 0, 0), 5)
    return img

def test_detect_paper_size():
    # Detect A1-ish large image
    # A1 long edge @ 300 DPI ~ 9933
    large_img = create_dummy_image(width=10000, height=7000)
    assert Preprocessor.detect_paper_size(large_img) == "A1"
    
    # Detect A4-ish
    # A4 long edge @ 300 DPI ~ 3508
    small_img = create_dummy_image(width=3000, height=2000)
    assert Preprocessor.detect_paper_size(small_img) == "A4"

def test_normalise_image():
    # Create large image
    large_img = create_dummy_image(width=5000, height=2500)
    norm_img, scale = Preprocessor.normalise_image(large_img)
    
    h, w = norm_img.shape[:2]
    long_edge = max(w, h)
    
    assert long_edge == CANONICAL_LONG_EDGE_PX
    assert scale < 1.0 # Should have scaled down

    # Create small image
    small_img = create_dummy_image(width=1000, height=500)
    norm_img2, scale2 = Preprocessor.normalise_image(small_img)
    h2, w2 = norm_img2.shape[:2]
    long_edge2 = max(w2, h2)
    
    assert long_edge2 == CANONICAL_LONG_EDGE_PX
    assert scale2 > 1.0 # Should have scaled up

def test_process_pipeline():
    # Create dummy image bytes
    img = create_dummy_image(width=2000, height=1000)
    _, img_encoded = cv2.imencode('.png', img)
    img_bytes = img_encoded.tobytes()
    
    result = Preprocessor.process(img_bytes)
    
    assert "normalised_image" in result
    assert "binary_image" in result
    assert "paper_size" in result
    assert "scale_factor" in result
    
    norm_img = result["normalised_image"]
    h, w = norm_img.shape[:2]
    assert max(w, h) == CANONICAL_LONG_EDGE_PX
    
    print(f"Detected Paper Size: {result['paper_size']}")
