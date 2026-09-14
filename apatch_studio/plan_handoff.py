"""Fail-closed attribution of APatch SDD preparation output to one Studio run."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apatch_studio.projection import assert_projection_safe
from apatch_studio.sdd_workflow import SddWorkflowError, SddWorkflowFacade

PREPARATION_SCHEMA = "apatch.studio.sdd-preparation.v1"
HANDOFF_SCHEMA = "apatch.studio.plan-handoff.v1"
MAX_PREPARATION_BYTES = 1_048_576
MAX_PREPARATIONS = 512

_SPEC_ID = re.compile(r"^SPEC-[A-Z0-9][A-Z0-9-]{1,95}$")
_REQUIREMENT_ID = re.compile(r"^[A-Z][A-Z0-9_-]{0,63}$")
_PREPARATION_FILE = re.compile(r"^(SPEC-[A-Z0-9][A-Z0-9-]{1,95})\.json$")
_REQUIREMENT_HEADING = re.compile(
    r"^##\s+([A-Z][A-Z0-9_-]{0,63})(?:\s+|$)",
    re.MULTILINE,
)
_REQUIRED_KEYS = {
    "schema",
    "spec_id",
    "objective",
    "prepared_at",
    "source_mutation_count",
    "contract_request",
    "task_envelopes",
}


TASK_ENVELOPE_SCHEMA = "apatch.sdd.task-envelope.v1"
PREPARATION_REQUIRED_KEYS = frozenset(_REQUIRED_KEYS)
_HASH_PLACEHOLDER = "sha256:<64 lowercase hex digits>"
_ACCEPTANCE_PLACEHOLDER = "<RFP acceptance id, for example AC-1>"


def preparation_package_template(
    spec_id: str,
    objective: str,
    *,
    requirement_ids: tuple[str, ...] | list[str] = ("R1",),
    prepared_at: str | None = None,
) -> dict[str, Any]:
    """Return the exact package shape Studio accepts for ``spec_id``.

    Every ``<placeholder>`` must be replaced by the runner and every key must
    stay. The SPEC must carry one ``## Rk`` heading per task envelope and
    nothing else (REC-bf36f1001fd7).
    """

    requirements = tuple(str(item) for item in requirement_ids) or ("R1",)
    test_command = ["python3", "-m", "pytest", "<frozen test file path>", "-q"]
    obligation = {
        "acceptance_id": _ACCEPTANCE_PLACEHOLDER,
        "test_id": "<pytest node id of the frozen test>",
        "oracle": "<independent observable oracle for this acceptance row>",
        "perspectives": ["positive", "negative", "boundary", "regression"],
        "asset_hashes": [_HASH_PLACEHOLDER],
        "command": list(test_command),
        "command_hash": _HASH_PLACEHOLDER,
        "baseline": {"kind": "observed_red", "result_hash": _HASH_PLACEHOLDER},
        "falsification": {
            "kind": "reversible_seed",
            "expected": "red",
            "target_hash": _HASH_PLACEHOLDER,
        },
        "approver": "owner:pending",
        "material": True,
    }
    contract_request = {
        "brief_hash": _HASH_PLACEHOLDER,
        "rfp_hash": _HASH_PLACEHOLDER,
        "spec_hash": _HASH_PLACEHOLDER,
        "plan_hash": _HASH_PLACEHOLDER,
        "baseline_hash": _HASH_PLACEHOLDER,
        "coverage": {"complete": True, "missing": [], "ambiguous": [], "waivers": []},
        "obligations": [obligation],
    }
    envelopes: dict[str, Any] = {}
    for requirement_id in requirements:
        envelopes[requirement_id] = {
            "schema": TASK_ENVELOPE_SCHEMA,
            "requirement": f"{spec_id}#{requirement_id}",
            "baseline_hash": _HASH_PLACEHOLDER,
            "allowed_reads": ["<source glob the implementer may read>"],
            "allowed_writes": ["<exact source file the implementer may change>"],
            "allowed_symbols": [],
            "forbidden_paths": ["docs/RFP-*.md", "docs/specs/**", "tests/**"],
            "tools": ["apatch_session_start", "apatch_execute_next", "apatch_verify_run"],
            "commands": [list(test_command)],
            "network": [],
            "remote": [],
            "services": [],
            "budgets": {"files": 4, "insertions": 400, "deletions": 120, "seconds": 1800},
            "checks": [_ACCEPTANCE_PLACEHOLDER],
            "rollback_owner": "session:self",
            "containment": "mediated_only",
        }
    return {
        "schema": PREPARATION_SCHEMA,
        "spec_id": spec_id,
        "objective": " ".join(str(objective).split()) or "<intended outcome>",
        "prepared_at": prepared_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_mutation_count": 0,
        "contract_request": contract_request,
        "task_envelopes": envelopes,
    }


def render_preparation_template(
    spec_id: str,
    objective: str,
    *,
    requirement_ids: tuple[str, ...] | list[str] = ("R1",),
    prepared_at: str | None = None,
) -> str:
    """Render the template as the exact JSON text a runner may write."""

    package = preparation_package_template(
        spec_id,
        objective,
        requirement_ids=requirement_ids,
        prepared_at=prepared_at,
    )
    return json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True)


class PlanHandoffError(RuntimeError):
    """A runner did not produce one attributable, reviewable plan."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _Candidate:
    fingerprint: str
    package_hash: str | None
    handoff: dict[str, Any] | None
    error: str | None


PlanHandoffSnapshot = dict[str, _Candidate]


def _canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _fingerprint(path: Path, raw: bytes | None = None) -> str:
    metadata = path.lstat()
    content = hashlib.sha256(raw).hexdigest() if raw is not None else "unread"
    return ":".join(
        (
            str(metadata.st_mode),
            str(metadata.st_size),
            str(metadata.st_mtime_ns),
            content,
        )
    )


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not 10 <= len(value) <= 64:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


class PlanHandoffCollector:
    """Snapshot prepared packages and resolve exactly one changed valid package."""

    def __init__(self, workspace: str | Path):
        self.root = Path(workspace).expanduser().resolve()
        self.prepared = self.root / ".apatch" / "sdd" / "prepared"
        self.workflow = SddWorkflowFacade(self.root)

    def capture(self) -> PlanHandoffSnapshot:
        if not self.prepared.exists():
            return {}
        if self.prepared.is_symlink() or not self.prepared.is_dir():
            return {
                "__prepared_directory__": _Candidate(
                    fingerprint="unsafe-directory",
                    package_hash=None,
                    handoff=None,
                    error="contract_preparation_invalid",
                )
            }
        try:
            paths = sorted(
                (path for path in self.prepared.iterdir() if path.name.endswith(".json")),
                key=lambda path: path.name,
            )
        except OSError:
            return {
                "__prepared_directory__": _Candidate(
                    fingerprint="unreadable-directory",
                    package_hash=None,
                    handoff=None,
                    error="contract_preparation_invalid",
                )
            }
        if len(paths) > MAX_PREPARATIONS:
            return {
                "__prepared_overflow__": _Candidate(
                    fingerprint=f"overflow:{len(paths)}",
                    package_hash=None,
                    handoff=None,
                    error="contract_preparation_invalid",
                )
            }
        return {path.name: self._candidate(path) for path in paths}

    def resolve(self, before: PlanHandoffSnapshot) -> dict[str, Any]:
        after = self.capture()
        changed = [
            name
            for name, candidate in after.items()
            if name not in before or before[name].fingerprint != candidate.fingerprint
        ]
        if not changed:
            raise PlanHandoffError(
                "The agent completed without one new reviewable plan.",
                code="contract_preparation_missing",
            )
        if len(changed) != 1:
            raise PlanHandoffError(
                "The agent changed more than one prepared plan; exact attribution is required.",
                code="contract_preparation_ambiguous",
            )
        name = changed[0]
        candidate = after[name]
        if candidate.error or candidate.handoff is None or candidate.package_hash is None:
            raise PlanHandoffError(
                "The prepared plan is invalid or unsafe.",
                code=candidate.error or "contract_preparation_invalid",
            )
        previous = before.get(name)
        if previous is not None and previous.package_hash == candidate.package_hash:
            raise PlanHandoffError(
                "The prepared plan did not contain a new contract revision.",
                code="contract_preparation_stale",
            )
        return dict(candidate.handoff)

    def _candidate(self, path: Path) -> _Candidate:
        try:
            metadata = path.lstat()
        except OSError:
            return _Candidate("unreadable", None, None, "contract_preparation_invalid")
        fallback_fingerprint = _fingerprint(path)
        match = _PREPARATION_FILE.fullmatch(path.name)
        if (
            match is None
            or path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size <= 0
            or metadata.st_size > MAX_PREPARATION_BYTES
        ):
            return _Candidate(
                fallback_fingerprint,
                None,
                None,
                "contract_preparation_invalid",
            )
        try:
            raw = path.read_bytes()
            fingerprint = _fingerprint(path, raw)
            package = json.loads(raw.decode("utf-8"))
            handoff = self._validate(package, filename_spec=match.group(1))
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            SddWorkflowError,
        ):
            return _Candidate(
                fallback_fingerprint,
                None,
                None,
                "contract_preparation_invalid",
            )
        package_hash = _canonical_hash(package)
        handoff["package_hash"] = package_hash
        assert_projection_safe(handoff)
        return _Candidate(fingerprint, package_hash, handoff, None)

    def _validate(self, package: Any, *, filename_spec: str) -> dict[str, Any]:
        if not isinstance(package, dict) or set(package) != _REQUIRED_KEYS:
            raise ValueError("unsupported preparation shape")
        spec_id = package.get("spec_id")
        if (
            package.get("schema") != PREPARATION_SCHEMA
            or not isinstance(spec_id, str)
            or spec_id != filename_spec
            or _SPEC_ID.fullmatch(spec_id) is None
        ):
            raise ValueError("invalid preparation identity")
        if type(package.get("source_mutation_count")) is not int or package["source_mutation_count"] != 0:
            raise ValueError("source changed before owner review")
        objective_value = package.get("objective")
        if not isinstance(objective_value, str):
            raise ValueError("objective must be text")
        objective = " ".join(objective_value.split())
        if not 3 <= len(objective) <= 2000:
            raise ValueError("objective is outside bounds")
        prepared_at = package.get("prepared_at")
        if not _valid_timestamp(prepared_at):
            raise ValueError("invalid preparation time")
        if not isinstance(package.get("contract_request"), dict):
            raise ValueError("contract request is required")
        envelopes = package.get("task_envelopes")
        if not isinstance(envelopes, dict) or not 1 <= len(envelopes) <= 256:
            raise ValueError("task envelopes are required")
        if any(
            not isinstance(requirement_id, str)
            or _REQUIREMENT_ID.fullmatch(requirement_id) is None
            for requirement_id in envelopes
        ):
            raise ValueError("invalid requirement identity")

        spec_path = self.root / "docs" / "specs" / f"{spec_id}.md"
        if spec_path.is_symlink() or not spec_path.is_file():
            raise ValueError("specification document is unavailable")
        if spec_path.stat().st_size > MAX_PREPARATION_BYTES:
            raise ValueError("specification document is oversized")
        spec_text = spec_path.read_text(encoding="utf-8")
        heading_order = [
            match.group(1)
            for match in _REQUIREMENT_HEADING.finditer(spec_text)
            if match.group(1) in envelopes
        ]
        if len(heading_order) != len(envelopes) or set(heading_order) != set(envelopes):
            raise ValueError("prepared requirements do not match the specification")
        for requirement_id in heading_order:
            self.workflow.contract_review(spec_id, requirement_id)

        return {
            "schema": HANDOFF_SCHEMA,
            "status": "review_ready",
            "spec_id": spec_id,
            "requirement_ids": heading_order,
            "objective": objective,
            "prepared_at": prepared_at,
        }
