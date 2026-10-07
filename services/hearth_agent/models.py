"""Records shared across HEARTH (TDD §4, §5, §8).

These mirror the JSON files the Engine API keeps on the space volume and the job spec the harness
reads from ``/job/spec.json``.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChangeKind(StrEnum):
    BREAKING = "breaking"
    DEPRECATION = "deprecation"
    FEATURE = "feature"
    SECURITY = "security"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ChangeSource(StrEnum):
    """Change sources in order of trust (TDD §8)."""

    MANIFEST = "manifest"
    SPEC_DIFF = "spec_diff"
    LLM_EXTRACTION = "llm_extraction"


class PackageRef(BaseModel):
    ecosystem: Literal["npm", "pypi"]
    name: str
    from_version: str | None = Field(default=None, alias="from")
    to_version: str | None = Field(default=None, alias="to")

    model_config = {"populate_by_name": True}


class SymbolChange(BaseModel):
    before: str
    after: str | None = None
    note: str | None = None


class Codemod(BaseModel):
    type: Literal["ast-grep"] = "ast-grep"
    rule: str


class ChangeRecord(BaseModel):
    id: str
    provider: str
    package: PackageRef
    kind: ChangeKind
    severity: Severity = Severity.MEDIUM
    summary: str
    symbols: list[SymbolChange] = Field(default_factory=list)
    migration_notes: str | None = None
    migration_guide: str | None = None
    deadline: date | None = None
    codemod: Codemod | None = None
    test_hints: str | None = None
    source: ChangeSource
    source_url: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review_status: Literal["pending", "approved", "rejected", "auto"] = "auto"


class ImpactMatch(BaseModel):
    path: str
    line: int
    symbol: str
    snippet: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ImpactReport(BaseModel):
    change_record_id: str
    repository: str
    commit: str
    matches: list[ImpactMatch] = Field(default_factory=list)
    scope_status: Literal["in_scope", "out_of_scope", "no_matches"] = "in_scope"

    @property
    def files(self) -> list[str]:
        return sorted({m.path for m in self.matches})


class JobLimits(BaseModel):
    """Per-job budgets (PRD §5, TDD §3 item 5)."""

    max_steps: int = 60
    max_tokens: int = 2_000_000
    wall_clock_seconds: int = 45 * 60
    max_validation_rounds: int = 3


class ValidationCommandResult(BaseModel):
    command: str
    exit_code: int
    duration_seconds: float
    failed_tests: list[str] = Field(default_factory=list)
    log_tail: str = ""


class ValidationResult(BaseModel):
    phase: Literal["baseline", "candidate"]
    passed: bool
    commands: list[ValidationCommandResult] = Field(default_factory=list)
    regressions: list[str] = Field(default_factory=list)
    flaky: list[str] = Field(default_factory=list)


class JobSpec(BaseModel):
    """What one remediation job hands to an intelligence."""

    job_id: str
    intelligence: Literal["claude_code"] = "claude_code"
    model: str | None = None
    change_record: ChangeRecord
    impact_report: ImpactReport
    repo_instructions: str | None = None  # AGENTS.md / CLAUDE.md contents, if any
    validate_commands: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)  # globs; default = impact files + tests
    limits: JobLimits = Field(default_factory=JobLimits)
    revise_instructions: str | None = None  # from `/hearth revise <...>`


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    steps: int = 0
    cost_usd: float | None = None


AgentStatus = Literal["passed", "failed_fix", "budget_exhausted", "policy_violation", "error"]


class AgentResult(BaseModel):
    """Written to ``/workspace/.hearth/result.json`` (TDD §3 item 8)."""

    job_id: str
    intelligence: str
    status: AgentStatus
    summary: str = ""
    files_changed: list[str] = Field(default_factory=list)
    needs_human_attention: list[str] = Field(default_factory=list)
    validation: ValidationResult | None = None
    usage: Usage = Field(default_factory=Usage)
    native_session_id: str | None = None
    finished_at: datetime | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
