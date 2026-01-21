"""
FastAPI Backend for IIIT University Timetable Extractor
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from dotenv import load_dotenv

from models import (
    SubjectRequest, TimetableRequest, SubjectResponse, 
    TimetableResponse, StatusResponse
)
from core import (
    process_file_data, pre_clean_values, get_groq_mapping,
    extract_timetable, CLASS_TT_PATH, LAB_TT_PATH
)

load_dotenv()

app = FastAPI(title="IIIT Timetable API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount frontend
app.mount("/static", StaticFiles(directory="../frontend"), name="static")

# Session storage (in production, use Redis or similar)
session_data = {
    "subject_mapping": {},
    "use_ai": False
}

@app.get("/")
async def root():
    """Serve frontend"""
    return FileResponse("../frontend/index.html")

@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    """Check if data files are loaded"""
    return StatusResponse(
        class_file_loaded=os.path.exists(CLASS_TT_PATH),
        lab_file_loaded=os.path.exists(LAB_TT_PATH),
        class_file_path=CLASS_TT_PATH,
        lab_file_path=LAB_TT_PATH
    )

@app.post("/api/subjects", response_model=SubjectResponse)
async def get_subjects(request: SubjectRequest):
    """Get available subjects from Class TT"""
    # Process Class Data
    class_data = process_file_data(CLASS_TT_PATH, "Classroom No.")
    
    if not class_data:
        raise HTTPException(status_code=500, detail="Failed to process Class Timetable")
    
    _, _, raw_values = class_data
    sorted_raw = sorted(list(raw_values))
    
    subject_mapping = {}
    
    if request.use_ai:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise HTTPException(status_code=400, detail="Groq API key not configured")
        
        filtered_raw = pre_clean_values(sorted_raw)
        ai_mapping = get_groq_mapping(filtered_raw, api_key, request.model_name)
        
        # AI mapping always returns a dict (either from API or fallback)
        if ai_mapping:
            subject_mapping = ai_mapping
            session_data["use_ai"] = True
        else:
            # Should never happen now, but just in case
            for s in filtered_raw[:50]:
                clean = s.replace("\n", " ").strip()
                subject_mapping[clean] = [s]
    else:
        # Identity mapping
        for s in sorted_raw:
            clean = s.replace("\n", " ").strip()
            subject_mapping[clean] = [s]
        session_data["use_ai"] = False
    
    # Store in session
    session_data["subject_mapping"] = subject_mapping
    
    return SubjectResponse(
        subjects=sorted(list(subject_mapping.keys())),
        mapping=subject_mapping
    )

@app.post("/api/generate", response_model=TimetableResponse)
async def generate_timetable(request: TimetableRequest):
    """Generate timetable with selected subjects"""
    if not session_data.get("subject_mapping"):
        raise HTTPException(status_code=400, detail="Please fetch subjects first")
    
    if not request.selected_subjects:
        raise HTTPException(status_code=400, detail="No subjects selected")
    
    try:
        result = extract_timetable(
            request.selected_subjects,
            session_data["subject_mapping"],
            request.branch,
            request.batch
        )
        
        if result is None:
            return TimetableResponse(
                success=False,
                message="No matching classes found"
            )
        
        return TimetableResponse(
            success=True,
            data=result,
            message=f"Generated timetable with {len(request.selected_subjects)} subjects"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=8001)
