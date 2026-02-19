
import cv2
import numpy as np
from typing import List, Dict, Any

class BOMDetector:
    def __init__(self, ocr_service):
        self.ocr_service = ocr_service

    def detect_bom(self, image: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detects the Bill of Materials (BOM) table.
        Returns a list of BOM item balloons (one per row).
        """
        # 1. Detect Table Grid (Horizontal and Vertical Lines)
        # This is useful to define the BOM region.
        # As a heuristic, we can also look for BOM headers: "ITEM", "QTY", "DESCRIPTION", "MATERIAL"
        
        text_blocks = self.ocr_service.detect_text(image)
        
        headers = ["ITEM", "NO.", "QTY", "DESCRIPTION", "MATERIAL", "PART NO"]
        found_headers = []
        
        for block in text_blocks:
            if any(h in block["text"].upper() for h in headers):
                found_headers.append(block)
                
        if len(found_headers) < 2:
            return [] # Unlikely to be a BOM without at least 2 headers
            
        # Determine BOM Region Bounding Box
        # Usually BOM is at the bottom right or top right.
        # Let's find the bounding box covering all headers
        xs = [b["bbox"][0] for b in found_headers]
        ys = [b["bbox"][1] for b in found_headers]
        
        # ROI starts around these headers and goes DOWN (or UP if headers are at bottom?)
        # Standard BOM headers are at the top of the list or bottom? 
        # Often headers are at the top of the columns.
        
        # We will look for rows ALIGNED with these headers.
        
        # Simplified logic:
        # 1. Find the "ITEM" or "NO." column header.
        # 2. Look for numbers below it (or above it) that look like item numbers (1, 2, 3...).
        
        item_header = None
        for h in found_headers:
            if "ITEM" in h["text"].upper() or "NO." in h["text"].upper():
                item_header = h
                break
        
        bom_items = []
        
        if item_header:
            ix, iy, iw, ih = item_header["bbox"]
            
            # Search for numbers in the same X column
            col_x_min = ix - 20
            col_x_max = ix + iw + 20
            
            for block in text_blocks:
                bx, by, bw, bh = block["bbox"]
                if col_x_min < bx < col_x_max:
                    # Check if it's a number
                    if block["text"].isdigit():
                        item_no = int(block["text"])
                        # Avoid detecting the header itself if it was "1" or something (unlikely) or valid years
                        if by > iy + 10 or by < iy - 10: # Spatially vertically separated
                            
                            # Determine if this is a row
                            # We want to associate other text in this row (Description, Qty)
                            # For ballooning, we just need the position of the ITEM number.
                            
                            bom_items.append({
                                "bom_id": f"bom_{item_no}",
                                "balloon_no": None,
                                "item_no": str(item_no),
                                "description": "", # formatting complex table data is hard without advanced logic
                                "qty": "",
                                "material": "",
                                "position": [bx, by + bh//2],
                                "bbox": block["bbox"],
                                "section": "bom"
                                # Note: We don't fill Description/Qty fully in this MVP 
                                # unless we do full table structure analysis.
                                # For "Inspector" use, marking the Item No is the key key.
                            })
                            
        # Sort by Item No
        bom_items.sort(key=lambda x: int(x["item_no"]) if x["item_no"].isdigit() else 0)
        
        return bom_items
