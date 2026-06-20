from pydantic import BaseModel
from typing import Any, Dict, List, Optional

class EmailPayload(BaseModel):
    raw_email: str
    is_sensitive: bool = False

class AgentLogEntry(BaseModel):
    agent: str
    message: str

class ProcessEmailResponse(BaseModel):
    status: str
    result: Dict[str, Any]
    thread_id: str

class ApproveResponse(BaseModel):
    status: str
    result: Dict[str, Any]

class RejectResponse(BaseModel):
    status: str
    message: str
    thread_id: str
