from pydantic import BaseModel
from typing import List, Dict, Optional

class SubjectRequest(BaseModel):
    """Request model for subject refinement"""
    use_ai: bool = False
    model_name: str = "openai/gpt-oss-120b"

class TimetableRequest(BaseModel):
    """Request model for timetable generation"""
    selected_subjects: List[str]
    branch: Optional[str] = ""
    batch: Optional[str] = ""  # Deprecated: No longer used for filtering, all batches shown

class SubjectResponse(BaseModel):
    """Response model for available subjects"""
    subjects: List[str]
    mapping: Dict[str, List[str]]

class TimetableResponse(BaseModel):
    """Response model for generated timetable"""
    success: bool
    data: Optional[Dict] = None
    message: str = ""
    
class StatusResponse(BaseModel):
    """Response model for system status"""
    class_file_loaded: bool
    lab_file_loaded: bool
    class_file_path: str
    lab_file_path: str
