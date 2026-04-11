from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel


class ReconciliationStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class MatchStatus(str, Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    PARTIAL = "partial"
    EXCEPTION = "exception"


class ReconciliationJobCreate(BaseModel):
    name: str
    source_file_key: str
    target_file_key: str
    match_columns: List[str]
    tolerance: Optional[float] = 0.0


class ReconciliationJobResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    status: ReconciliationStatus
    source_file_key: str
    target_file_key: str
    match_columns: List[str]
    tolerance: float
    total_rows: Optional[int] = None
    matched_rows: Optional[int] = None
    unmatched_rows: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ReconciliationRow(BaseModel):
    row_index: int
    match_status: MatchStatus
    source_data: Dict[str, Any]
    target_data: Optional[Dict[str, Any]] = None
    discrepancies: Optional[Dict[str, Any]] = None
    match_score: Optional[float] = None
