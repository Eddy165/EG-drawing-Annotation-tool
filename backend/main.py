
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import os

from backend.routers import upload, detect, export

app = FastAPI(title="EG Drawing Inspector API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all for dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Uploads for static access
os.makedirs("backend/uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="backend/uploads"), name="uploads")

# Include Routers
app.include_router(upload.router, prefix="/api", tags=["Upload"])
app.include_router(detect.router, prefix="/api", tags=["Detect"])
app.include_router(export.router, prefix="/api", tags=["Export"])

@app.get("/")
def read_root():
    return {"message": "EG Drawing Inspector API is running"}

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
