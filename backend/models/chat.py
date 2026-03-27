from pydantic import BaseModel, Field
from typing import Optional
import uuid

class ChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: str = Field(..., min_length=1, max_length=1000)

class SessionInfo(BaseModel):
    id: str; title: str; created_at: str; updated_at: str

class MessageInfo(BaseModel):
    id: int; session_id: str; role: str; content: str
    msg_type: str = "text"; metadata: Optional[dict] = None; created_at: str
