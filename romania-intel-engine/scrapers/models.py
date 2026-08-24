from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

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
    action_deadline: Optional[str] = None
    source_url: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
