from pydantic import BaseModel
from typing import Optional, List

class AnchorInfo(BaseModel):
    id: str; name: str; level: int; path: Optional[str] = None

class AncestorOption(BaseModel):
    id: str; name: str; level: int; label: str

class ImportResult(BaseModel):
    success: bool; entity_count: int; message: str
