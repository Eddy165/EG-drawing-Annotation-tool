
import pytest
from unittest.mock import MagicMock
import numpy as np
import os
import sys

# Ensure backend folder is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from backend.services.notes_detector import NotesDetector
from backend.services.bom_detector import BOMDetector

class MockOCR:
    def detect_text(self, image):
        return []

def test_notes_detector():
    mock_ocr = MockOCR()
    # Mock return values
    mock_ocr.detect_text = MagicMock(return_value=[
        {"text": "NOTES:", "bbox": [100, 100, 50, 20]},
        {"text": "1. All dimensions in mm", "bbox": [100, 130, 200, 20]},
        {"text": "2. Remove sharp edges", "bbox": [100, 160, 200, 20]},
        {"text": "TITLE BLOCK", "bbox": [500, 500, 100, 50]} # Irrelevant
    ])
    
    detector = NotesDetector(mock_ocr)
    image = np.zeros((1000, 1000, 3), dtype=np.uint8)
    
    notes = detector.detect_notes(image)
    
    assert len(notes) == 2
    assert notes[0]["text"] == "1. All dimensions in mm"
    assert notes[1]["text"] == "2. Remove sharp edges"

def test_bom_detector():
    mock_ocr = MockOCR()
    # Mock return values for BOM
    # Header: ITEM QTY DESC
    # Row 1:  1    2   Bolt
    # Row 2:  2    4   Nut
    mock_ocr.detect_text = MagicMock(return_value=[
        {"text": "ITEM", "bbox": [500, 100, 40, 20]},
        {"text": "QTY", "bbox": [550, 100, 30, 20]},
        {"text": "DESCRIPTION", "bbox": [600, 100, 100, 20]},
        
        {"text": "1", "bbox": [510, 130, 20, 20]}, # Item 1 (aligned x with ITEM)
        {"text": "2", "bbox": [560, 130, 20, 20]}, # Qty (misaligned x with ITEM, aligned with QTY)
        {"text": "Bolt", "bbox": [600, 130, 50, 20]},
        
        {"text": "2", "bbox": [510, 160, 20, 20]}, # Item 2
        {"text": "4", "bbox": [560, 160, 20, 20]},
        {"text": "Nut", "bbox": [600, 160, 50, 20]},
    ])
    
    detector = BOMDetector(mock_ocr)
    image = np.zeros((1000, 1000, 3), dtype=np.uint8)
    
    bom = detector.detect_bom(image)
    
    # Logic should find "1" and "2" under "ITEM" header
    # The "2" under "QTY" should be ignored as an item number because of column alignment?
    # Our simple logic checks x-alignment with ITEM header. 
    # Item header X: [500, 540] (width 40). 
    # Qty "2" bbox: [560, ...] -> 560 is > 540+20. Should be excluded.
    # Item "1" bbox: [510, ...] -> Inside.
    # Item "2" bbox: [510, ...] -> Inside.
    
    assert len(bom) == 2
    assert bom[0]["item_no"] == "1"
    assert bom[1]["item_no"] == "2"
