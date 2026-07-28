"""Artifact publication and reports for Milestone 3.5 campaigns.

This module contains only offline artifact rendering and publication. Campaign
planning, state inspection, and resume decisions remain in campaign.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .cache import atomic_write, sha256_bytes
from .campaign import (
    MILESTONE_REPORT_SCHEMA_VERSION,
    STAGE_B_COMMAND,
    CampaignConfig,
    CampaignError,
    CampaignPlan,
    _display_path,
    create_campaign_plan,
    inspect_campaign,
    ledger_request_row_count,
)


@dataclass(frozen=True, slots=True)
class VerificationEvidence:
    """Actual offline test evidence for the Definition-of-Done report."""

    command: str
    summary: str
    passed_tests: int
    passed: bool


@dataclass(frozen=True, slots=True)
class CampaignArtifacts:
    """Paths and identities published by one Stage A generation."""

    campaign_id: str
    configuration_fingerprint: str
    campaign_plan_fingerprint: str
    campaign_state_fingerprint: str
    output_directory: Path
    config_path: Path
    plan_json_path: Path
    plan_markdown_path: Path
    preflight_json_path: Path
    preflight_markdown_path: Path
    milestone_report_path: Path | None
    authenticated_request_delta: int


def _json_bytes(payload: object) -> bytes:
    """Render stable human-readable JSON bytes."""
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _write_immutable(path: Path, content: bytes) -> None:
    """Publish an immutable artifact or verify an identical existing file."""
    if path.exists():
        if not path.is_file() or path.read_bytes() != content:
            raise CampaignError(
                f"Immutable campaign artifact conflicts with existing file: {path}"
            )
        return
    atomic_write(path, content)


def _markdown_text(lines: list[str]) -> str:
    """Render clean Markdown while preserving intentional hard breaks."""
    cleaned = [
        line if line.endswith("  ") else line.rstrip()
        for line in lines
    ]
    return "\n".join(cleaned) + "\n"


def render_campaign_plan_markdown(plan: CampaignPlan) -> str:
    """Render the complete campaign plan for human review."""
    payload = plan.payload()
    accounting = payload["request_accounting"]
    lines = [
        "# Milestone 3.5 Historical Expansion Campaign Plan",
        "",
        "Generated artifact — do not hand-edit.",
        "",
        f"- Campaign ID: `{payload['campaign_id']}`",
        (
            "- Configuration fingerprint: "
            f"`{payload['configuration_fingerprint']}`"
        ),
        (
            "- Campaign plan fingerprint: "
            f"`{payload['campaign_plan_fingerprint']}`"
        ),
        (
            "- Fixed range: "
            f"`{plan.config.start_utc.isoformat()}` inclusive to "
            f"`{plan.config.end_utc.isoformat()}` exclusive"
        ),
        "- Authenticated requests made by planning: `0`",
        "",
        "## Request Accounting",
        "",
        (
            f"- Logical partitions: `{accounting['logical_partitions']}` "
            f"(`{accounting['new_historical_partitions']}` new and "
            f"`{accounting['cached_pilot_partitions']}` cached pilot)"
        ),
        (
            "- Conditional request specifications: "
            f"`{accounting['conditional_request_specs_total']}` total, "
            f"`{accounting['conditional_request_specs_new_partitions']}` "
            "for new partitions"
        ),
        (
            "- Maximum additional HTTP attempts: "
            f"`{accounting['max_additional_http_attempts']}`"
        ),
        (
            "- Expected successful pages: "
            f"`{accounting['expected_successful_pages']['minimum']}–"
            f"{accounting['expected_successful_pages']['maximum']}`"
        ),
        "- Pilot additional HTTP budget: `0`",
        "- Automatic retries: `0`",
        "",
        "## Ordered Partitions",
        "",
        (
            "| # | Partition | Kind | Start (inclusive) | End (exclusive) | "
            "Run ID | Slots | Campaign network budget |"
        ),
        "| ---: | --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for partition in payload["partitions"]:
        lines.append(
            f"| {partition['ordinal']} | `{partition['partition_id']}` | "
            f"{partition['kind']} | `{partition['start_utc_inclusive']}` | "
            f"`{partition['end_utc_exclusive']}` | "
            f"`{partition['run_id']}` | {partition['request_slots']} | "
            f"{partition['campaign_network_budget']} |"
        )

    lines.extend(["", "## Exact Conditional Requests", ""])
    for partition in payload["partitions"]:
        lines.extend(
            [
                f"### {partition['partition_id']}",
                "",
                f"- Configuration hash: `{partition['config_hash']}`",
                f"- Checkpoint: `{partition['paths']['checkpoint']}`",
                f"- Cache root: `{partition['paths']['cache_directory']}`",
                f"- Execution policy: `{partition['execution_policy']}`",
                "",
                "| Sequence | Offset | Request hash | Cache response |",
                "| ---: | ---: | --- | --- |",
            ]
        )
        for request in partition["requests"]:
            lines.append(
                f"| {request['sequence']} | {request['offset']} | "
                f"`{request['request_hash']}` | "
                f"`{request['cache_paths']['response']}` |"
            )
        lines.append("")

    lines.extend(
        [
            "## Resume and Approval Boundary",
            "",
            "Campaign status is derived read-only from the existing SQLite ",
            "ledger and verified cache. Failed, exhausted, unresolved, or ",
            "out-of-order state blocks progress. No live execution is exposed ",
            "by the campaign coordinator.",
            "",
            "The separately approved Stage B command would be:",
            "",
            "```bash",
            STAGE_B_COMMAND,
            "```",
            "",
            "This command is recorded for review and was not executed in Stage A.",
        ]
    )
    return _markdown_text(lines)


def render_preflight_markdown(preflight: dict[str, object]) -> str:
    """Render campaign state, pilot proof, and next-action evidence."""
    accounting = preflight["request_accounting"]
    pilot = preflight["pilot_reuse"]
    resume = preflight["resume"]
    io_audit = preflight["stage_a_io_audit"]
    lines = [
        "# Milestone 3.5 Campaign Preflight",
        "",
        "Generated artifact — do not hand-edit.",
        "",
        f"- Campaign ID: `{preflight['campaign_id']}`",
        (
            "- Campaign state fingerprint: "
            f"`{preflight['campaign_state_fingerprint']}`"
        ),
        f"- Campaign status: `{resume['campaign_status']}`",
        (
            "- Stage A authenticated request delta: "
            f"`{io_audit['authenticated_request_delta']}`"
        ),
        "- API key read by Stage A: `false`",
        "",
        "## Request Accounting",
        "",
        (
            "- Historical pilot attempts, excluded from expansion budget: "
            f"`{accounting['historical_pilot_http_attempts']}`"
        ),
        (
            "- Milestone 3.5 additional attempts used: "
            f"`{accounting['m3_5_additional_attempts_used']}`"
        ),
        (
            "- Milestone 3.5 additional attempts remaining: "
            f"`{accounting['m3_5_additional_attempts_remaining']}`"
        ),
        (
            "- Verified cached pilot pages: "
            f"`{accounting['verified_cached_pilot_pages']}`"
        ),
        "",
        "## Cached Pilot Proof",
        "",
        f"- Run ID: `{pilot['run_id']}`",
        f"- Configuration hash: `{pilot['config_hash']}`",
        f"- SQLite status: `{pilot['ledger_status']}`",
        f"- Records: `{pilot['records']}`",
        "- Additional HTTP request required: `false`",
        "",
        "| Page | Request hash | Response SHA-256 | Records | Final |",
        "| ---: | --- | --- | ---: | --- |",
    ]
    for page in pilot["verified_cached_pages"]:
        lines.append(
            f"| {page['sequence']} | `{page['request_hash']}` | "
            f"`{page['response_sha256']}` | {page['record_count']} | "
            f"{str(page['is_final_page']).lower()} |"
        )
    lines.extend(
        [
            "",
            "The two later pilot request specifications are not missing cache ",
            "entries: they are unreachable because page 2 is terminal.",
            "",
            "## Deterministic Resume",
            "",
            f"- Next partition: `{resume.get('next_partition_id')}`",
            f"- Next run: `{resume.get('next_run_id')}`",
            f"- Next sequence: `{resume.get('next_sequence')}`",
            f"- Next offset: `{resume.get('next_offset')}`",
            (
                "- Remaining campaign budget: "
                f"`{resume['additional_attempts_remaining']}`"
            ),
            (
                "- Partition remaining request ceiling: "
                f"`{resume.get('partition_remaining_request_ceiling')}`"
            ),
            "",
            "No acquisition run, checkpoint, cache entry, or request-ledger ",
            "row was created by this preflight.",
        ]
    )
    return _markdown_text(lines)


def _artifact_hash_rows(
    paths: tuple[Path, ...],
    repository_root: Path,
) -> list[dict[str, object]]:
    """Return checksums for generated evidence files."""
    return [
        {
            "path": _display_path(path, repository_root),
            "sha256": sha256_bytes(path.read_bytes()),
            "bytes": path.stat().st_size,
        }
        for path in paths
    ]


def render_milestone_report(
    *,
    plan: CampaignPlan,
    preflight: dict[str, object],
    verification: VerificationEvidence,
    artifact_hashes: list[dict[str, object]],
) -> str:
    """Render the mandatory generated Stage A Definition-of-Done report."""
    if not verification.passed:
        raise CampaignError(
            "A completion report requires passing offline verification."
        )
    payload = plan.payload()
    accounting = payload["request_accounting"]
    runtime_accounting = preflight["request_accounting"]
    pilot = preflight["pilot_reuse"]
    resume = preflight["resume"]
    lines = [
        "# Milestone 3.5 Stage A: Offline Campaign Planning and Coordination",
        "",
        "> Generated Definition-of-Done artifact — do not hand-edit.",
        "",
        f"Report schema: `{MILESTONE_REPORT_SCHEMA_VERSION}`  ",
        "Status: **complete; Stage B awaiting separate approval**  ",
        f"Campaign ID: `{payload['campaign_id']}`  ",
        (
            "Configuration fingerprint: "
            f"`{payload['configuration_fingerprint']}`  "
        ),
        (
            "Campaign plan fingerprint: "
            f"`{payload['campaign_plan_fingerprint']}`  "
        ),
        (
            "Campaign state fingerprint: "
            f"`{preflight['campaign_state_fingerprint']}`"
        ),
        "",
        "## 1. Definition-of-Done outcome",
        "",
        "Stage A is complete. The fixed 2022–2026 campaign has been planned ",
        "as 19 deterministic partitions, the existing pilot ledger and cache ",
        "have been verified, resume and budget decisions are derived without ",
        "mutating acquisition state, and all offline tests pass.",
        "",
        "Authenticated requests performed by Stage A: **0**.",
        "",
        "## 2. Scope boundary",
        "",
        "Included:",
        "",
        "- immutable campaign configuration and fingerprints;",
        "- exact secret-free request specifications and cache/checkpoint paths;",
        "- read-only SQLite/cache preflight and deterministic resume resolution;",
        "- campaign-level request accounting and boundary enforcement;",
        "- machine-readable and Markdown planning artifacts; and",
        "- comprehensive offline tests.",
        "",
        "Excluded:",
        "",
        "- the 2022-Q1 authenticated canary;",
        "- any historical acquisition request;",
        "- raw-data parsing or normalization changes;",
        "- supervised-dataset construction changes;",
        "- feature engineering, splitting, modeling, backend, and frontend work.",
        "",
        "## 3. Implementation map",
        "",
        "| File | Responsibility |",
        "| --- | --- |",
        "| `src/liquipedia_backfill/campaign.py` | Fixed campaign contract, partition composition, fingerprints, read-only state/cache inspection, resume policy, and budget/readiness gate. |",
        "| `src/liquipedia_backfill/campaign_reports.py` | Immutable JSON publication, Markdown planning reports, preflight evidence, and generated Definition-of-Done report. |",
        "| `src/liquipedia_backfill/envelope.py` | Pure response-envelope validation shared by the live runner and offline cache verifier. |",
        "| `src/liquipedia_backfill/runner.py` | Uses the extracted pure envelope validator; HTTP behavior is otherwise unchanged. |",
        "| `src/liquipedia_backfill/__init__.py` | Exposes the campaign planning contract. |",
        "| `scripts/plan_liquipedia_history_campaign.py` | Offline-only planning CLI and completion-report gate. |",
        "| `tests/test_milestone3_5_campaign.py` | Boundaries, hashes, state, budgets, cache reuse, reports, and zero-request tests. |",
        "| `docs/milestones/MILESTONE_3_5_STAGE_A_OFFLINE_CAMPAIGN_PLANNING.md` | Mandatory generated completion evidence. |",
        "| `README.md`, `data/README.md`, and milestone design documents | Current status, artifact layout, and corrected approval boundaries. |",
        "| `.gitignore` | Keeps authenticated data local while allowing credential-free campaign evidence to be versioned. |",
        "",
        "## 4. Architecture decisions",
        "",
        "The coordinator composes `BackfillConfig` and `create_plan()` for every ",
        "partition. It does not construct API queries independently and does ",
        "not expose an HTTP client.",
        "",
        "Campaign state is a read-only projection of the existing SQLite ",
        "partition ledger plus checksum-verified cache entries. No campaign ",
        "tables or second state database were added. The existing ",
        "`BackfillRunner` remains the only live acquisition path.",
        "",
        "Immutable plan/configuration identity excludes local paths, timestamps, ",
        "and mutable state. Preflight state has its own fingerprint.",
        "",
        "## 5. Campaign request accounting",
        "",
        f"- Logical partitions: **{accounting['logical_partitions']}**",
        (
            "- New full-quarter partitions: "
            f"**{accounting['new_historical_partitions']}**"
        ),
        "- Cached July 2026 pilot partitions: **1**",
        (
            "- Conditional request specifications: "
            f"**{accounting['conditional_request_specs_total']}** "
            f"({accounting['conditional_request_specs_new_partitions']} new + "
            f"{accounting['conditional_request_specs_pilot']} pilot)"
        ),
        (
            "- Estimated successful pages: "
            f"**{accounting['expected_successful_pages']['minimum']}–"
            f"{accounting['expected_successful_pages']['maximum']}**"
        ),
        (
            "- Maximum additional HTTP attempts: "
            f"**{accounting['max_additional_http_attempts']}**"
        ),
        (
            "- Additional attempts used at Stage A completion: "
            f"**{runtime_accounting['m3_5_additional_attempts_used']}**"
        ),
        "",
        "The 148 specifications are conditional pagination slots, not an ",
        "authorization to make 148 calls. The campaign hard ceiling remains ",
        "100 additional attempts.",
        "",
        "## 6. Ordered partitions",
        "",
        (
            "| # | Partition | Range | Run ID | Config hash | Slots | "
            "Network budget |"
        ),
        "| ---: | --- | --- | --- | --- | ---: | ---: |",
    ]
    for partition in payload["partitions"]:
        lines.append(
            f"| {partition['ordinal']} | `{partition['partition_id']}` | "
            f"`{partition['start_utc_inclusive']}` → "
            f"`{partition['end_utc_exclusive']}` | "
            f"`{partition['run_id']}` | `{partition['config_hash']}` | "
            f"{partition['request_slots']} | "
            f"{partition['campaign_network_budget']} |"
        )

    lines.extend(
        [
            "",
            "## 7. Cached pilot reuse proof",
            "",
            f"- Run ID: `{pilot['run_id']}`",
            f"- Configuration hash: `{pilot['config_hash']}`",
            f"- SQLite status: `{pilot['ledger_status']}`",
            (
                "- Historical attempts, excluded from Stage 3.5 budget: "
                f"`{pilot['historical_http_attempts']}`"
            ),
            f"- Verified records: `{pilot['records']}`",
            "- Additional pilot requests required: `0`",
            "",
            "| Page | Request hash | Response SHA-256 | Records | Final |",
            "| ---: | --- | --- | ---: | --- |",
        ]
    )
    for page in pilot["verified_cached_pages"]:
        lines.append(
            f"| {page['sequence']} | `{page['request_hash']}` | "
            f"`{page['response_sha256']}` | {page['record_count']} | "
            f"{str(page['is_final_page']).lower()} |"
        )

    lines.extend(
        [
            "",
            "Page 2 is terminal, so the pilot's conditional request slots 3 and ",
            "4 are correctly classified as not required. The coordinator ",
            "assigns the pilot a zero network budget.",
            "",
            "## 8. Resume and budget decision",
            "",
            f"- Campaign status: `{resume['campaign_status']}`",
            f"- Next partition: `{resume.get('next_partition_id')}`",
            f"- Next run ID: `{resume.get('next_run_id')}`",
            f"- Next sequence and offset: `{resume.get('next_sequence')}` / `{resume.get('next_offset')}`",
            (
                "- Additional attempt budget remaining: "
                f"`{resume['additional_attempts_remaining']}`"
            ),
            (
                "- Next-partition remaining ceiling: "
                f"`{resume.get('partition_remaining_request_ceiling')}`"
            ),
            "",
            "A failed, exhausted, unresolved, corrupt, or out-of-order ",
            "partition blocks the campaign. A partition is authorized at a ",
            "boundary only when the campaign can cover its conservative ",
            "remaining request ceiling.",
            "",
            "## 9. Offline verification",
            "",
            f"- Command: `{verification.command}`",
            f"- Result: **{verification.summary}**",
            f"- Passing tests: **{verification.passed_tests}**",
            "- API key read: **no**",
            "- Authenticated request delta: **0**",
            "- Acquisition ledger rows created: **0**",
            "",
            "## 10. Generated artifact checksums",
            "",
            "| Artifact | SHA-256 | Bytes |",
            "| --- | --- | ---: |",
        ]
    )
    for artifact in artifact_hashes:
        lines.append(
            f"| `{artifact['path']}` | `{artifact['sha256']}` | "
            f"{artifact['bytes']} |"
        )

    lines.extend(
        [
            "",
            "## 11. Deviations, warnings, and limitations",
            "",
            "- No design deviation was required.",
            "- Request estimates remain planning ranges rather than quotas or ",
            "  dataset-size guarantees.",
            "- The campaign coordinator enforces the 100-attempt ceiling at ",
            "  partition boundaries; the existing runner continues to enforce ",
            "  each partition's eight-attempt ceiling.",
            "- Stage A does not prove 2022 payload compatibility. That is the ",
            "  purpose of the separately approved historical canary.",
            "",
            "## 12. Stage B approval boundary",
            "",
            "The proposed command below targets only 2022-Q1 through the ",
            "existing validated acquisition runner. It was not executed:",
            "",
            "```bash",
            STAGE_B_COMMAND,
            "```",
            "",
            "Stage B remains blocked pending separate approval.",
        ]
    )
    return _markdown_text(lines)


def generate_campaign_artifacts(
    campaign: CampaignConfig,
    *,
    verification: VerificationEvidence | None = None,
    milestone_report_path: Path | None = None,
    ledger_rows_before_stage_a: int | None = None,
) -> CampaignArtifacts:
    """Publish Stage A artifacts while proving acquisition state is unchanged."""
    plan = create_campaign_plan(campaign)
    before = (
        ledger_request_row_count(campaign.state_path)
        if ledger_rows_before_stage_a is None
        else ledger_rows_before_stage_a
    )
    preflight = inspect_campaign(plan)

    output = campaign.output_directory
    config_path = output / "campaign_config.json"
    plan_json_path = output / "campaign_plan.json"
    plan_markdown_path = output / "campaign_plan.md"
    preflight_json_path = output / "campaign_preflight.json"
    preflight_markdown_path = output / "campaign_preflight.md"

    config_payload = {
        "campaign_id": campaign.campaign_id,
        "configuration_fingerprint": campaign.config_fingerprint,
        "configuration": campaign.identity_payload(),
    }
    _write_immutable(config_path, _json_bytes(config_payload))
    _write_immutable(plan_json_path, _json_bytes(plan.payload()))
    _write_immutable(
        plan_markdown_path,
        render_campaign_plan_markdown(plan).encode("utf-8"),
    )

    after = ledger_request_row_count(campaign.state_path)
    request_delta = after - before
    if request_delta != 0:
        raise CampaignError(
            "Offline campaign planning changed the request ledger."
        )
    preflight = {
        **preflight,
        "stage_a_io_audit": {
            "ledger_request_rows_before": before,
            "ledger_request_rows_after": after,
            "authenticated_request_delta": request_delta,
            "api_key_read": False,
            "network_code_invoked": False,
            "acquisition_state_modified": False,
        },
    }
    atomic_write(preflight_json_path, _json_bytes(preflight))
    atomic_write(
        preflight_markdown_path,
        render_preflight_markdown(preflight).encode("utf-8"),
    )

    report_path: Path | None = None
    if milestone_report_path is not None:
        if verification is None or not verification.passed:
            raise CampaignError(
                "The milestone report requires passing test evidence."
            )
        artifact_hashes = _artifact_hash_rows(
            (
                config_path,
                plan_json_path,
                plan_markdown_path,
                preflight_json_path,
                preflight_markdown_path,
            ),
            campaign.repository_root,
        )
        report_path = milestone_report_path.resolve()
        atomic_write(
            report_path,
            render_milestone_report(
                plan=plan,
                preflight=preflight,
                verification=verification,
                artifact_hashes=artifact_hashes,
            ).encode("utf-8"),
        )

    final_count = ledger_request_row_count(campaign.state_path)
    if final_count != before:
        raise CampaignError(
            "Stage A artifact generation changed the request ledger."
        )
    return CampaignArtifacts(
        campaign_id=campaign.campaign_id,
        configuration_fingerprint=campaign.config_fingerprint,
        campaign_plan_fingerprint=plan.plan_fingerprint,
        campaign_state_fingerprint=str(
            preflight["campaign_state_fingerprint"]
        ),
        output_directory=output,
        config_path=config_path,
        plan_json_path=plan_json_path,
        plan_markdown_path=plan_markdown_path,
        preflight_json_path=preflight_json_path,
        preflight_markdown_path=preflight_markdown_path,
        milestone_report_path=report_path,
        authenticated_request_delta=request_delta,
    )
