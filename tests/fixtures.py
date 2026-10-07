"""Shared test data."""

from services.hearth_agent.models import (
    ChangeKind,
    ChangeRecord,
    ChangeSource,
    ImpactMatch,
    ImpactReport,
    JobSpec,
    PackageRef,
    ValidationCommandResult,
    ValidationResult,
)


def change_record() -> ChangeRecord:
    return ChangeRecord(
        id="cr_test1",
        provider="stripe",
        package=PackageRef(ecosystem="npm", name="stripe", **{"from": "<17", "to": "17.0.0"}),
        kind=ChangeKind.BREAKING,
        summary="charges.create is removed; use paymentIntents.create",
        source=ChangeSource.MANIFEST,
    )


def job() -> JobSpec:
    cr = change_record()
    return JobSpec(
        job_id="job_1",
        change_record=cr,
        impact_report=ImpactReport(
            change_record_id=cr.id, repository="acme/shop", commit="abc123",
            matches=[ImpactMatch(path="src/pay.ts", line=12, symbol="stripe.charges.create")],
        ),
        validate_commands=["pnpm test"],
        allowed_paths=["src/pay.ts"],
    )


def validation(passed: bool) -> ValidationResult:
    return ValidationResult(
        phase="candidate", passed=passed, regressions=[] if passed else ["test_pay"],
        commands=[ValidationCommandResult(command="pnpm test", exit_code=0 if passed else 1, duration_seconds=1,
                                          log_tail="" if passed else "FAIL test_pay")],
    )
