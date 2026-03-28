from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class JobRunStatus(str, Enum):
    success = "success"
    failed = "failed"
    cancelled = "cancelled"
    timeout = "timeout"
    running = "running"


class JobScheduleType(str, Enum):
    once = "once"
    interval = "interval"
    daily = "daily"
    weekly = "weekly"
    cron = "cron"


class JobRunRecord(BaseModel):
    """단일 실행 이력 레코드"""
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    run_id: str
    started_at: str
    finished_at: Optional[str] = None
    status: JobRunStatus
    duration_seconds: Optional[float] = None
    summary: Optional[str] = None


class JobInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str
    name: str
    description: str = ""
    prompt: str
    skill_names: List[str] = Field(default_factory=list)
    mcp_server_names: List[str] = Field(default_factory=list)
    schedule_type: JobScheduleType = JobScheduleType.once
    schedule_config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    created_at: str
    updated_at: str
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    last_run_status: Optional[JobRunStatus] = None
    last_run_summary: Optional[str] = None
    run_count: int = 0
    consecutive_failures: int = 0
    run_history: List[JobRunRecord] = Field(default_factory=list)


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    name: str
    description: str = ""
    prompt: str
    skill_names: List[str] = Field(default_factory=list)
    mcp_server_names: List[str] = Field(default_factory=list)
    schedule_type: JobScheduleType = JobScheduleType.once
    schedule_config: Dict[str, Any] = Field(default_factory=dict)


class UpdateJobRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    name: Optional[str] = None
    description: Optional[str] = None
    prompt: Optional[str] = None
    skill_names: Optional[List[str]] = None
    mcp_server_names: Optional[List[str]] = None
    schedule_type: Optional[JobScheduleType] = None
    schedule_config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
