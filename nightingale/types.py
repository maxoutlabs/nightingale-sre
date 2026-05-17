"""
Nightingale Data Types
Production-grade Pydantic models for the full pipeline.
"""
from typing import List, Dict, Optional, Any, Literal
from pydantic import BaseModel, Field, field_validator
from enum import Enum
from datetime import datetime
import hashlib
import json

# ── Enums ─────────────────────────────────────────────────────────────────────

class IncidentType(str, Enum):
    PIPELINE_FAILURE = "pipeline_failure"
    TEST_FAILURE = "test_failure"
    LINT_FAILURE = "lint_failure"
    BUILD_FAILURE = "build_failure"

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class DecisionType(str, Enum):
    RESOLVE = "resolve"
    ESCALATE = "escalate"
    ABORT = "abort"

class IncidentStatus(str, Enum):
    DETECTED = "detected"
    DIAGNOSING = "diagnosing"
    FIX_GENERATED = "fix_generated"
    SANDBOXING = "sandboxing"
    RESOLVED = "resolved"
    ESCALATED = "escalated"

# ── Core Pipeline Models ───────────────────────────────────────────────────────

class PipelineStep(BaseModel):
    name: str
    status: str
    logs: Optional[str] = None
    duration_ms: Optional[int] = None

class IncidentEvent(BaseModel):
    id: str
    type: IncidentType
    timestamp: datetime = Field(default_factory=datetime.now)
    repository_path: str
    commit_sha: str
    branch: str
    failed_steps: List[PipelineStep]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    workflow_file: Optional[str] = None

class FileDiff(BaseModel):
    file_path: str
    change_type: Literal["modify", "add", "delete"]
    diff_content: str

    def content_hash(self) -> str:
        return hashlib.sha256(self.diff_content.encode()).hexdigest()[:16]

# ── AI Response Schema (OpenAI Structured Outputs) ───────────────────────────

class FileChange(BaseModel):
    """Typed file change entry — compatible with OpenAI structured outputs."""
    file_path: str
    change_type: Literal["modify", "add", "delete"]
    content: str

class AIFixResponse(BaseModel):
    """
    Schema for AI fix responses.
    Used with OpenAI beta.chat.completions.parse() for guaranteed structure.
    Replaces the old GeminiFixResponse.
    """
    root_cause: str = Field(..., description="Root cause analysis of the failure")
    rationale: str = Field(..., description="Explanation of the proposed fix")
    files_to_change: List[FileChange] = Field(..., description="Files to modify")
    verification_commands: List[str] = Field(..., description="Commands to verify the fix")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Self-assessed confidence 0-1")
    risk_assessment: str = Field(..., description="Risk level: low, medium, high, or critical")

# Legacy alias for backward compatibility
GeminiFixResponse = AIFixResponse

# ── Reasoning Trace ───────────────────────────────────────────────────────────

class ReasoningStep(BaseModel):
    step_number: int
    action: str
    input_summary: str
    output_summary: str
    timestamp: datetime = Field(default_factory=datetime.now)
    duration_ms: int = 0
    tokens_used: int = 0

class ReasoningTrace(BaseModel):
    incident_id: str
    attempt_number: int
    steps: List[ReasoningStep] = Field(default_factory=list)
    total_tokens: int = 0
    total_duration_ms: int = 0
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    def add_step(self, action: str, input_summary: str, output_summary: str,
                 duration_ms: int = 0, tokens_used: int = 0):
        self.steps.append(ReasoningStep(
            step_number=len(self.steps) + 1,
            action=action,
            input_summary=input_summary[:500],
            output_summary=output_summary[:500],
            duration_ms=duration_ms,
            tokens_used=tokens_used,
        ))
        self.total_tokens += tokens_used
        self.total_duration_ms += duration_ms

# ── Attempt Tracking ──────────────────────────────────────────────────────────

class VerificationResult(BaseModel):
    success: bool
    input_hash: str
    output_log: str
    duration_ms: int
    tests_passed: int = 0
    tests_failed: int = 0
    tests_total: int = 0
    exit_code: int = 0

    @property
    def pass_ratio(self) -> float:
        if self.tests_total == 0:
            return 1.0 if self.success else 0.0
        return self.tests_passed / self.tests_total

class FixPlan(BaseModel):
    rationale: str
    root_cause: str = ""
    files_to_change: List[FileDiff]
    verification_steps: List[str]
    confidence_score: float = 0.0
    risk_level: RiskLevel = RiskLevel.MEDIUM
    attempt_number: int = 1
    previous_failure_context: Optional[str] = None

    def content_hash(self) -> str:
        content = json.dumps([f.model_dump() for f in self.files_to_change], sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

class AttemptRecord(BaseModel):
    attempt_number: int
    fix_plan: Optional["FixPlan"] = None
    verification_result: Optional[VerificationResult] = None
    reasoning_trace: Optional[ReasoningTrace] = None
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None

# ── Confidence Scoring ────────────────────────────────────────────────────────

class ConfidenceFactors(BaseModel):
    test_pass_ratio: float = Field(ge=0.0, le=1.0, default=0.0)
    inverse_blast_radius: float = Field(ge=0.0, le=1.0, default=1.0)
    attempt_penalty: float = Field(ge=0.0, le=1.0, default=1.0)
    risk_modifier: float = Field(ge=0.0, le=1.0, default=0.5)
    self_consistency_score: float = Field(ge=0.0, le=1.0, default=0.5)

    def weighted_score(self) -> float:
        return (
            0.35 * self.test_pass_ratio
            + 0.25 * self.inverse_blast_radius
            + 0.15 * self.attempt_penalty
            + 0.15 * self.risk_modifier
            + 0.10 * self.self_consistency_score
        )

# ── Metrics ───────────────────────────────────────────────────────────────────

class MetricsData(BaseModel):
    incident_id: str
    total_attempts: int = 0
    total_api_calls: int = 0
    total_tokens_used: int = 0
    total_duration_ms: int = 0
    final_decision: Optional[DecisionType] = None
    final_confidence: float = 0.0
    files_modified: int = 0
    sandbox_runs: int = 0
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

# ── Report ────────────────────────────────────────────────────────────────────

class IncidentReport(BaseModel):
    incident_id: str
    decision: DecisionType
    confidence: float
    confidence_factors: ConfidenceFactors
    attempts: List[AttemptRecord]
    metrics: MetricsData
    final_plan: Optional[FixPlan] = None
    final_verification: Optional[VerificationResult] = None
    report_text: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    pr_url: Optional[str] = None
    status: IncidentStatus = IncidentStatus.DETECTED

# ── Dashboard Types ───────────────────────────────────────────────────────────

class DashboardIncident(BaseModel):
    """Lightweight incident summary for dashboard list view."""
    id: str
    timestamp: str
    repo: str
    failure_type: str
    status: str
    attempts: int = 0
    confidence: float = 0.0
    outcome: str = "pending"
    time_to_resolution_ms: int = 0
    root_cause: str = ""
    fix_summary: str = ""
    pr_url: str = ""

class DashboardMetrics(BaseModel):
    """Aggregated metrics for the dashboard header."""
    total_incidents: int = 0
    auto_resolved: int = 0
    escalated: int = 0
    avg_confidence: float = 0.0
    avg_resolution_ms: int = 0
    success_rate: float = 0.0

# Update forward references
AttemptRecord.model_rebuild()
