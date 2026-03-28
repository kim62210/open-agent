from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class JobRunRecord(BaseModel):
    """단일 실행 이력 레코드"""
    run_id: str
    started_at: str
    finished_at: Optional[str] = None
    status: str  # "success" | "failed" | "cancelled" | "timeout"
    duration_seconds: Optional[float] = None
    summary: Optional[str] = None


class JobInfo(BaseModel):
    id: str
    name: str
    description: str = ""
    prompt: str
    skill_names: List[str] = []
    mcp_server_names: List[str] = []
    schedule_type: str = "once"  # "once" | "interval" | "daily" | "weekly" | "cron"
    schedule_config: Dict[str, Any] = {}
    enabled: bool = True
    created_at: str
    updated_at: str
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    last_run_status: Optional[str] = None  # "success" | "failed" | "running" | "cancelled" | "timeout"
    last_run_summary: Optional[str] = None
    run_count: int = 0
    consecutive_failures: int = 0
    run_history: List[JobRunRecord] = []  # 최근 N회 이력 (최신이 앞)


class CreateJobRequest(BaseModel):
    name: str
    description: str = ""
    prompt: str
    skill_names: List[str] = []
    mcp_server_names: List[str] = []
    schedule_type: str = "once"
    schedule_config: Dict[str, Any] = {}


class UpdateJobRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    prompt: Optional[str] = None
    skill_names: Optional[List[str]] = None
    mcp_server_names: Optional[List[str]] = None
    schedule_type: Optional[str] = None
    schedule_config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
