from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class RawInstitutionalSignal(BaseModel):
    source_id: str
    source_type: str
    category: str
    county: str
    locality: str
    entity_name: str
    project_title: str
    estimated_value_ron: float = 0.0
    raw_description: str
    publication_date: Optional[str] = None
    action_deadline: Optional[str] = None
    source_url: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
