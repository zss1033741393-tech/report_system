from pydantic import BaseModel, Field
import uuid

class GenerateRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

class ConfirmRequest(BaseModel):
    session_id: str; selected_node_id: str

class ModifyRequest(BaseModel):
    session_id: str; instruction: str = Field(..., min_length=1, max_length=500)

class KBImportRequest(BaseModel):
    excel_path: str
