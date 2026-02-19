
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import cv2
import os

# Import services
from backend.services.view_detector import ViewDetector
from backend.services.dimension_detector import DimensionDetector
from backend.services.ocr_service import OCRService
from backend.services.traversal_engine import TraversalEngine
from backend.services.notes_detector import NotesDetector
from backend.services.bom_detector import BOMDetector
from backend.routers.upload import sessions, UPLOAD_DIR

router = APIRouter()

# Instantiate services once (lazy loading models)
view_detector = ViewDetector()
dimension_detector = DimensionDetector()
ocr_service = OCRService() # May take time to load first time
traversal_engine = TraversalEngine()
notes_detector = NotesDetector(ocr_service)
bom_detector = BOMDetector(ocr_service)

class DetectViewsRequest(BaseModel):
    session_id: str

class DetectDimensionsRequest(BaseModel):
    session_id: str
    views: List[dict] # Simplified type for now
    direction: str = "CW"

@router.post("/detect/views")
async def detect_views(request: DetectViewsRequest):
    session_id = request.session_id
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
        
    norm_path = sessions[session_id]["normalised_path"]
    image = cv2.imread(norm_path)
    if image is None:
        raise HTTPException(status_code=500, detail="Could not load image")
        
    views = view_detector.detect_views(image)
    return {"views": views}

@router.post("/detect/dimensions")
async def detect_dimensions(request: DetectDimensionsRequest):
    session_id = request.session_id
    views = request.views
    direction = request.direction
    
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
        
    norm_path = sessions[session_id]["normalised_path"]
    image = cv2.imread(norm_path)
    
    # Run OCR on full image once? Or per view?
    # OCR on full A4/A3 image at 300 DPI (3500px) is okay for Paddle.
    # It allows us to match text to views globally or by cropping.
    # Let's run global OCR to capture everything including Notes/BOM.
    
    all_text_blocks = ocr_service.detect_text(image)
    
    # Filter dimensions per view
    dimensions_by_view = {}
    
    for view in views:
        vx, vy, vw, vh = view["bbox"]
        view_id = view["view_id"]
        
        # Crop view context for geometric detection
        # view_img = image[vy:vy+vh, vx:vx+vw]
        # geometric_dims = dimension_detector.detect_dimensions(view_img)
        
        # Filter OCR blocks inside this view
        view_text_blocks = []
        for block in all_text_blocks:
            bx, by, bw, bh = block["bbox"]
            bcx, bcy = bx + bw/2, by + bh/2
            if vx < bcx < vx + vw and vy < bcy < vy + vh:
                view_text_blocks.append(block)
                
        # Extract likely dimensions from text
        ocr_dims = ocr_service.extract_dimensions_from_text(view_text_blocks)
        
        # Merge geometric and OCR dims? 
        # For MVP, rely on OCR dims as "Balloons" are identifying values.
        dimensions_by_view[view_id] = ocr_dims
    
    # Sequence Balloons
    balloons = traversal_engine.sequence_balloons(views, dimensions_by_view, direction)
    
    # Detect Notes
    notes = notes_detector.detect_notes(image)
    # Assign balloon numbers continuing from last
    next_num = len(balloons) + 1
    for note in notes:
        note["balloon_no"] = next_num
        balloons.append(note)
        next_num += 1
        
    # Detect BOM (optional, might duplicate if text blocks reused?)
    # ideally we mask out regions we already processed?
    # For now, just run it.
    bom_items = bom_detector.detect_bom(image)
    for item in bom_items:
        item["balloon_no"] = next_num
        balloons.append(item)
        next_num += 1
        
    sessions[session_id]["balloons"] = balloons
    
    return {"balloons": balloons}
