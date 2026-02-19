
import pytest
import numpy as np
import cv2
import os
import sys

# Ensure backend folder is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from backend.services.dimension_detector import DimensionDetector

def create_dimension_image(width=400, height=200):
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:] = (255, 255, 255)
    
    # Draw a line with "arrowheads" (circles for now as simulated arrowheads)
    cv2.line(img, (50, 100), (350, 100), (0, 0, 0), 2)
    cv2.circle(img, (50, 100), 5, (0, 0, 0), -1)
    cv2.circle(img, (350, 100), 5, (0, 0, 0), -1)
    
    # Draw "text" (a rect)
    cv2.rectangle(img, (180, 80), (220, 95), (0, 0, 0), -1)
    
    return img

def test_detect_dimensions_structure():
    detector = DimensionDetector()
    img = create_dimension_image()
    
    # Just verify it runs without error and returns a list (empty or not)
    # Since logic is skeletal, we expect empty or minimal results
    dims = detector.detect_dimensions(img)
    assert isinstance(dims, list)

def test_detect_lines_internal():
    detector = DimensionDetector()
    img = create_dimension_image()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lines = detector._detect_lines(gray)
    assert len(lines) > 0 # Should find the drawn line
