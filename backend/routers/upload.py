
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import shutil
import os
import uuid
import cv2
import numpy as np
from backend.services.preprocessor import Preprocessor

router = APIRouter()

UPLOAD_DIR = "backend/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# In-memory session store for MVP (use Redis in prod)
# session_id -> { "image_path": ..., "preprocessed": ..., "metadata": ... }
sessions = {}

@router.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")
    
    session_id = str(uuid.uuid4())
    file_ext = os.path.splitext(file.filename)[1]
    file_path = os.path.join(UPLOAD_DIR, f"{session_id}{file_ext}")
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Run Preprocessor
    try:
        with open(file_path, "rb") as f:
            image_bytes = f.read()
            processed_data = Preprocessor.process(image_bytes)
            
        # Save normalised image for frontend display
        norm_path = os.path.join(UPLOAD_DIR, f"{session_id}_norm.png")
        cv2.imwrite(norm_path, processed_data["normalised_image"])
        
        # Store in session
        sessions[session_id] = {
            "original_path": file_path,
            "normalised_path": norm_path,
            "paper_size": processed_data["paper_size"],
            "scale_factor": processed_data["scale_factor"],
            "original_shape": processed_data["original_shape"]
        }
        
        h, w = processed_data["normalised_image"].shape[:2]
        
        return {
            "session_id": session_id,
            "image_url": f"/uploads/{session_id}_norm.png", # served via static files
            "paper_size": processed_data["paper_size"],
            "width_px": w,
            "height_px": h
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
