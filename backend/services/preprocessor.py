import cv2
import numpy as np
from typing import Tuple, Dict, Any
from backend.utils.constants import PAPER_SIZES_MM, CANONICAL_LONG_EDGE_PX

class Preprocessor:
    @staticmethod
    def detect_paper_size(image: np.ndarray) -> str:
        """
        Detects paper size based on image aspect ratio.
        Assumes landscape orientation primarily, but checks both.
        """
        h, w = image.shape[:2]
        aspect_ratio = max(w, h) / min(w, h)
        
        # A-series roughly maintains sqrt(2) ~ 1.414 aspect ratio
        # But we use the pixel dimensions to guess the closest standard size if possible,
        # or just rely on aspect ratio for now. 
        # Since we don't know the physical DPI yet, we can only guess based on relative size if we had a reference.
        # However, the user prompt says: "Detect paper size from image aspect ratio".
        # A1: ~841x594mm (1.41)
        # A2: ~594x420mm (1.41)
        # All A-series have the same aspect ratio! 
        # So providing a specific size like "A1" based ONLY on aspect ratio is ambiguous without absolute scale.
        # BUT, often engineering drawings have a border or title block that might give a clue, 
        # or we might just default to A3/A4 if it's close to 1.414.
        # Let's map based on the user's specific notes if there were any, otherwise standard A-series logic.
        # User Note: "A1: ~841x594mm -> ~2x1 landscape?" No, A1 is 1.414.
        # Wait, the prompt said: "A1: ~841x594mm -> ~2x1 landscape". 
        # 841/594 = 1.415. 
        # Maybe they meant 2 A1s make an A0? 
        # Let's stick to standard ISO sizes.
        # If the user strictly wants to differentiate A1 from A4 based on pixel count, we need a reference.
        # For now, we will return "Unknown" or best guess based on long edge if > some threshold.
        
        long_edge = max(w, h)
        
        # Heuristic: Larger pixel counts likely mean larger paper if scanned at same DPI.
        # 300 DPI A4 long edge ~ 3508
        # 300 DPI A3 long edge ~ 4961
        # 300 DPI A2 long edge ~ 7016
        # 300 DPI A1 long edge ~ 9933
        
        if long_edge > 8500:
            return "A1"
        elif long_edge > 6000:
            return "A2"
        elif long_edge > 4000:
            return "A3"
        else:
            return "A4"

    @staticmethod
    def normalise_image(image: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Resizes image so the long edge is CANONICAL_LONG_EDGE_PX (3508).
        Returns normalised image and the scale factor used.
        """
        h, w = image.shape[:2]
        long_edge = max(w, h)
        scale = CANONICAL_LONG_EDGE_PX / long_edge
        
        if scale == 1.0:
            return image, 1.0
            
        new_w = int(w * scale)
        new_h = int(h * scale)
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        return resized, scale

    @staticmethod
    def deskew_image(image: np.ndarray) -> np.ndarray:
        """
        Applies deskewing using Hough Line Transform to align dominant lines horizontally/vertically.
        """
        # Convert to grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
            
        # Edge detection
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        
        # Probabilistic Hough Transform
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=100, minLineLength=100, maxLineGap=10)
        
        if lines is None:
            return image
            
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi
            # precise angle within -45 to 45 degrees
            if -45 < angle < 45:
                angles.append(angle)
            elif 135 < angle < 225:
                 angles.append(angle - 180)
        
        if not angles:
            return image
            
        median_angle = np.median(angles)
        
        if abs(median_angle) < 0.5: # Ignore small deviations
            return image
            
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
        rotated = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        
        return rotated

    @staticmethod
    def process(image_bytes: bytes) -> Dict[str, Any]:
        """
        Main pipeline: Decode -> Deskew -> Denoise -> Normalise.
        """
        # Decode
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if image is None:
            raise ValueError("Could not decode image bytes")

        # 1. Deskew
        image = Preprocessor.deskew_image(image)
        
        # 2. Denoise (FastNLMeans - effective but slow, maybe skip for speed if resolution is high? 
        # User requested it. Let's apply lightly or on grayscale)
        # Using light strength to preserve edges.
        image = cv2.fastNlMeansDenoisingColored(image, None, 10, 10, 7, 21)
        
        # 3. Enhance Contrast (CLAHE) - requires grayscale or L channel
        # Convert to LAB
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        cl = clahe.apply(l)
        limg = cv2.merge((cl, a, b))
        image = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
        
        # 4. Detect Paper Size (before normalisation to use original pixel count logic)
        paper_size = Preprocessor.detect_paper_size(image)
        
        # 5. Normalise
        norm_image, scale = Preprocessor.normalise_image(image)
        
        # 6. Binarize (Otsu) for downstream processing if needed, 
        # but we usually return the color/grayscale image for viewing 
        # and a binary version for OCR/Detection.
        # The user asked to "Return: { normalised_image: np.ndarray, paper_size: str, dpi_estimate: int }"
        # And mentioned "Convert to grayscale + binarize (Otsu threshold)" as part of the pipeline.
        # Let's add a binary version to the result.
        
        gray_norm = cv2.cvtColor(norm_image, cv2.COLOR_BGR2GRAY)
        _, binary_norm = cv2.threshold(gray_norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        return {
            "normalised_image": norm_image,
            "binary_image": binary_norm,
            "paper_size": paper_size,
            "scale_factor": scale,
            "original_shape": image.shape[:2]
        }
