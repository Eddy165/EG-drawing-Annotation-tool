
from paddleocr import PaddleOCR
import numpy as np
import logging
from typing import List, Dict, Any, Tuple

# Suppress Paddle warnings
logging.getLogger("ppocr").setLevel(logging.ERROR)

class OCRService:
    def __init__(self, use_gpu: bool = False, lang: str = 'en'):
        """
        Initialize PaddleOCR.
        """
        try:
            self.ocr = PaddleOCR(use_angle_cls=True, lang=lang, use_gpu=use_gpu, show_log=False)
        except Exception as e:
            print(f"Failed to initialize PaddleOCR: {e}")
            self.ocr = None

    def detect_text(self, image: np.ndarray) -> List[Dict[str, Any]]:
        """
        Runs OCR on the given image.
        Returns a list of detected text blocks with bounding boxes and confidence.
        """
        if self.ocr is None:
            return []

        try:
            result = self.ocr.ocr(image, cls=True)
            
            detected_texts = []
            if result and result[0]:
                for line in result[0]:
                    # line structure: [ [[x1,y1],[x2,y2],[x3,y3],[x4,y4]], (text, confidence) ]
                    coords = line[0]
                    text, conf = line[1]
                    
                    # Calculate bounding box [x, y, w, h] from 4 points
                    xs = [pt[0] for pt in coords]
                    ys = [pt[1] for pt in coords]
                    x_min, x_max = min(xs), max(xs)
                    y_min, y_max = min(ys), max(ys)
                    
                    detected_texts.append({
                        "text": text,
                        "confidence": float(conf),
                        "bbox": [int(x_min), int(y_min), int(x_max - x_min), int(y_max - y_min)],
                        "polygon": coords
                    })
                    
            return detected_texts
            
        except Exception as e:
            print(f"Error during OCR detection: {e}")
            return []

    def extract_dimensions_from_text(self, text_blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filters and parses text blocks that look like dimensions.
        """
        dimensions = []
        for block in text_blocks:
            text = block["text"].strip()
            # Simple heuristic: contains digits
            if any(char.isdigit() for char in text):
                # Further classification logic (Diameter, Radius, Angular, Linear)
                dim_type = "linear"
                if "R" in text or "r" in text:
                    dim_type = "radius"
                elif "DIA" in text or "Ø" in text or "⌀" in text:
                    dim_type = "diameter"
                elif "°" in text:
                    dim_type = "angular"
                
                dimensions.append({
                    "dim_id": f"dim_{len(dimensions)}", 
                    "value": text,
                    "type": dim_type,
                    "bbox": block["bbox"],
                    "confidence": block["confidence"]
                })
        return dimensions
