from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

class RawInstitutionalSignal(BaseModel):
    source_id: str
    source_type: str
    category: str
    sub_category: str
    county: str
    locality: str
    entity_name: str
    project_title: str
    estimated_value_ron: float = 0.0
    published_date: str
    action_deadline: Optional[str] = None
    raw_description: str
    source_url: str
    caen_codes: List[str] = Field(default_factory=list)
    cpv_code: Optional[str] = None
    document_url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
