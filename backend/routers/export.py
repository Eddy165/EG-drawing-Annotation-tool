
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import os
from backend.services.report_generator import ReportGenerator
from backend.routers.upload import sessions

router = APIRouter()
generator = ReportGenerator()

class ExportRequest(BaseModel):
    session_id: str
    format: str # "pdf", "xlsx", "json"
    inspector_name: str = "Inspector"
    drawing_name: str = "Drawing"

@router.post("/export")
async def export_report(request: ExportRequest):
    session_id = request.session_id
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session = sessions[session_id]
    balloons = session.get("balloons", [])
    
    # Prepare data structure for generator
    data = {
        "metadata": {
            "drawing_name": request.drawing_name,
            "inspector": request.inspector_name,
            "date": "2023-10-27", # Todo: current date
            "total_balloons": len(balloons)
        },
        "balloons": balloons,
        "notes": [b for b in balloons if b.get("section") == "notes"],
        "bom": [b for b in balloons if b.get("section") == "bom"]
    }
    
    filepath = ""
    if request.format == "json":
        filepath = generator.generate_json(data, f"report_{session_id}")
    elif request.format == "xlsx":
        filepath = generator.generate_xlsx(data, f"report_{session_id}")
    elif request.format == "pdf":
        filepath = generator.generate_pdf(data, f"report_{session_id}")
    else:
        raise HTTPException(status_code=400, detail="Invalid format")
        
    return FileResponse(filepath, filename=os.path.basename(filepath))
