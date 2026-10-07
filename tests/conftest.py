import pytest

from hearth_core.models import ChangeKind, ChangeRecord, ChangeSource, ImpactMatch, ImpactReport, JobSpec, PackageRef


@pytest.fixture
def change_record() -> ChangeRecord:
    return ChangeRecord(
        id="cr_test1",
        provider="stripe",
        package=PackageRef(ecosystem="npm", name="stripe", **{"from": "<17", "to": "17.0.0"}),
        kind=ChangeKind.BREAKING,
        summary="charges.create is removed; use paymentIntents.create",
        source=ChangeSource.MANIFEST,
    )


@pytest.fixture
def job(change_record) -> JobSpec:
    return JobSpec(
        job_id="job_1",
        change_record=change_record,
        impact_report=ImpactReport(
            change_record_id=change_record.id, repository="acme/shop", commit="abc123",
            matches=[ImpactMatch(path="src/pay.ts", line=12, symbol="stripe.charges.create")],
        ),
        validate_commands=["pnpm test"],
        allowed_paths=["src/pay.ts"],
    )
