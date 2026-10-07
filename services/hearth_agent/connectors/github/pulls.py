"""PR naming and body rendering (TDD §9 "PR format")."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from services.hearth_agent.models import AgentResult, ChangeKind, ChangeRecord, ImpactReport, ValidationResult


@dataclass
class Branding:
    """Provider-branded agent profile (TDD §8). ``None`` provider means the neutral HEARTH app."""

    provider_name: str | None = None
    logo_url: str | None = None


@dataclass
class PullRequestContent:
    branch: str
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    draft: bool = False


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", s.lower()).strip("-")


def branch_name(record: ChangeRecord) -> str:
    """``hearth/<provider>-<to_version>-<short_id>``."""
    to = record.package.to_version or "latest"
    short = hashlib.sha1(record.id.encode()).hexdigest()[:7]
    return f"hearth/{_slug(record.provider)}-{_slug(to)}-{short}"


def _validation_table(baseline: ValidationResult | None, candidate: ValidationResult | None) -> str:
    if not candidate:
        return "_No validation results._"
    base = {c.command: c for c in (baseline.commands if baseline else [])}
    rows = ["| Command | Baseline | Candidate |", "|---|---|---|"]
    for c in candidate.commands:
        b = base.get(c.command)
        mark = lambda code: "✅ pass" if code == 0 else f"❌ exit {code}"  # noqa: E731
        rows.append(f"| `{c.command}` | {mark(b.exit_code) if b else '—'} | {mark(c.exit_code)} |")
    if candidate.flaky:
        rows.append("")
        rows.append("Flaky (excluded from the regression check): " + ", ".join(f"`{t}`" for t in candidate.flaky))
    return "\n".join(rows)


def render_pr(
    record: ChangeRecord,
    impact: ImpactReport,
    result: AgentResult,
    *,
    baseline: ValidationResult | None = None,
    transcript_url: str | None = None,
    branding: Branding | None = None,
    draft: bool = False,
) -> PullRequestContent:
    branding = branding or Branding()
    adoption = record.kind == ChangeKind.FEATURE
    pkg = record.package.name
    to = record.package.to_version
    if adoption:
        title = f"feat(deps): adopt {record.summary[:60]} ({pkg})"
    else:
        title = f"chore(deps): migrate {pkg}{f' to v{to}' if to else ''} ({record.summary[:60]})"
    if branding.provider_name:
        title = f"[{branding.provider_name}] {title}"

    lines: list[str] = []
    if adoption:
        lines += ["> **Optional adoption PR.** This adopts a new provider feature; it is not required.", ""]
    lines += ["## What changed upstream", "", record.summary, ""]
    if record.source_url:
        lines.append(f"Source: {record.source_url}")
    if record.migration_guide:
        lines.append(f"Migration guide: {record.migration_guide}")
    if record.deadline:
        lines.append(f"**Deadline:** {record.deadline.isoformat()}")
    lines += ["", "## Files changed", ""]
    lines += [f"- `{f}`" for f in (result.files_changed or impact.files)]
    lines += ["", "## Validation", "", _validation_table(baseline, result.validation), ""]
    lines += ["## Agent summary", "", result.summary or "_No summary._", ""]
    if result.needs_human_attention:
        lines += ["## Needs human attention", ""] + [f"- {n}" for n in result.needs_human_attention] + [""]
    if transcript_url:
        lines.append(f"[Full run transcript]({transcript_url})")
    lines += ["", "---", "Comment `/hearth revise <instructions>`, `/hearth retry`, `/hearth explain` or `/hearth close`."]
    footer = f"Powered by HEARTH · intelligence: `{result.intelligence}`"
    if branding.provider_name:
        footer = f"{branding.provider_name} update agent · " + footer
    lines.append(footer)

    labels = ["hearth"] + (["hearth:adoption"] if adoption else ["hearth:migration"])
    if branding.provider_name:
        labels.append(f"provider:{_slug(branding.provider_name)}")
    return PullRequestContent(branch_name(record), title[:250], "\n".join(lines), labels, draft)
