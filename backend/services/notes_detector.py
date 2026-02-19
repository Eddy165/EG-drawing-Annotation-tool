
import re
from typing import List, Dict, Any, Tuple
import numpy as np

class NotesDetector:
    def __init__(self, ocr_service):
        self.ocr_service = ocr_service

    def detect_notes(self, image: np.ndarray) -> List[Dict[str, Any]]:
        """
        Detects the notes section and extracts individual notes.
        Returns a list of note balloons.
        """
        # 1. Detect Text
        text_blocks = self.ocr_service.detect_text(image)
        
        # 2. Find "NOTES" Header
        notes_header = None
        for block in text_blocks:
            text = block["text"].upper()
            if "NOTE" in text and len(text) < 20: # "NOTES", "GENERAL NOTES", "NOTE:"
                notes_header = block
                break
        
        if not notes_header:
            return []
            
        # 3. Define region of interest (ROI) for notes
        # Usually below or near the header. 
        # For simplicity, we look for text blocks that are spatially close and aligned.
        # Or just look for numbered lines anywhere in the drawing if they are clustered?
        # Let's assume notes are in a column below the header.
        
        hx, hy, hw, hh = notes_header["bbox"]
        search_area_y_min = hy + hh
        
        # Filter blocks that are likely notes (below header, similar X align)
        # and match regex for numbered list items "1.", "2)", "1 -"
        
        note_pattern = re.compile(r'^(\d+)[\.\)\-]')
        
        notes = []
        for block in text_blocks:
            bx, by, bw, bh = block["bbox"]
            text = block["text"].strip()
            
            # Check spatial relationship: Below header?
            if by > search_area_y_min:
                # Check for numbered start
                match = note_pattern.search(text)
                if match:
                    note_num = int(match.group(1))
                    
                    notes.append({
                        "note_id": f"note_{len(notes)+1}",
                        "balloon_no": None, # Assigned later by traversal
                        "text": text,
                        "position": [bx, by + bh//2], # Place balloon at start of line
                        "bbox": block["bbox"],
                        "section": "notes"
                    })
                    
        # Sort notes by Y position to ensure order
        notes.sort(key=lambda n: n["bbox"][1])
        
        return notes
