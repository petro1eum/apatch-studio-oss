"""Private, atomic APatch Studio run journal."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from apatch_studio.operations import ExecutionContext, SddExecutionContext
from apatch_studio.projection import UnsafeProjectionError, assert_projection_safe

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

JOURNAL_SCHEMA = "apatch.studio.run-journal.v1"
RECORD_SCHEMA = "apatch.studio.run-record.v1"
ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "interrupted"}
MAX_JOURNAL_BYTES = 4 * 1024 * 1024

_RECORD_FIELDS = {
    "schema",
    "run_id",
    "request",
    "execution_context",
    "sdd_execution",
    "retry_of",
    "status",
    "phase",
    "created_at",
    "started_at",
    "ended_at",
    "outcome",
    "message",
    "thread_id",
    "event_count",
    "review",
    "timeline",
    "reviewer_note",
    "contribution",
    "plan_handoff",
    "scope",
    "updated_at",
    "planning_last_activity_at",
    "planning_cleanup",
}
_REQUEST_FIELDS = {
    "mode",
    "runner",
    "objective",
    "acceptance_criteria",
    "spec_id",
    "requirement_id",
    "rfp_id",
    "work_asset_id",
    "governed_session_id",
}
_REVIEW_FIELDS = {"schema", "baseline", "result", "delta", "attribution"}
_TIMELINE_FIELDS = {"at", "phase", "message"}
_REVIEWER_NOTE_FIELDS = {"schema", "text", "updated_at"}
_CONTRIBUTION_FIELDS = {"contribution_receipt", "avatar_sync"}
_CONTRIBUTION_RECEIPT_FIELDS = {"status", "code", "event_id"}
_AVATAR_SYNC_FIELDS = {"ok", "status", "retryable", "outbox_preserved", "pending_outbox_items", "complete", "action_required"}
_PLAN_HANDOFF_FIELDS = {"schema", "status", "spec_id", "requirement_ids", "objective", "prepared_at", "package_hash"}
_PLAN_HANDOFF_SPEC = re.compile(r"^SPEC-[A-Z0-9][A-Z0-9-]{1,95}$")
_PLAN_HANDOFF_REQUIREMENT = re.compile(r"^[A-Z][A-Z0-9_-]{0,63}$")
_PLAN_HANDOFF_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCOPE_FIELDS = {
    "schema",
    "status",
    "audit_observed",
    "planned_file_count",
    "logical_areas",
    "blocked_out_of_scope",
    "reverted_out_of_scope",
    "unresolved_out_of_scope",
}
_SCOPE_STATUSES = {"pending", "clean", "protected", "attention"}
_SCOPE_AREAS = {"frontend", "backend", "tests", "docs", "configuration", "other"}
_SNAPSHOT_FIELDS = {
    "schema",
    "captured_at",
    "branch",
    "head",
    "dirty_files",
    "insertions",
    "deletions",
    "attested_requirements",
    "stale_requirements",
    "evidence_events",
    "work_assets",
}
_DELTA_FIELDS = {
    "dirty_files",
    "insertions",
    "deletions",
    "attested_requirements",
    "stale_requirements",
    "evidence_events",
    "work_assets",
    "head_changed",
    "branch_changed",
}


class RunJournalError(RuntimeError):
    """The durable run journal cannot be accepted or updated."""


class RunJournalInUseError(RunJournalError):
    """Another Studio manager owns this workspace journal."""


@dataclass(frozen=True)
class RunJournalLoad:
    records: list[dict[str, Any]]
    status: str = "ready"
    warning: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state_root() -> Path:
    """Return the OS user state location, never a repository-relative path."""

    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "APatch Studio"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "APatch Studio"
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "apatch-studio"


def workspace_identity(workspace: Path) -> str:
    return hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest()[:32]


def _lock(handle: BinaryIO, *, blocking: bool) -> None:
    if fcntl is not None:
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        fcntl.flock(handle.fileno(), operation)
        return
    import msvcrt  # pragma: no cover - Windows fallback

    handle.seek(0)
    if handle.read(1) == b"":
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
    msvcrt.locking(handle.fileno(), mode, 1)


def _unlock(handle: BinaryIO) -> None:
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    import msvcrt  # pragma: no cover - Windows fallback

    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class RunStore:
    """Workspace-scoped durable journal with explicit serialization limits."""

    def __init__(
        self,
        workspace: str | os.PathLike[str],
        *,
        state_root: str | os.PathLike[str] | None = None,
        retention: int = 200,
    ):
        self.workspace = Path(workspace).expanduser().resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"workspace does not exist: {self.workspace}")
        if not 1 <= retention <= 1000:
            raise ValueError("retention must be in 1..1000")
        self.retention = retention
        self.workspace_identity = workspace_identity(self.workspace)
        root = Path(state_root).expanduser().resolve() if state_root else default_state_root()
        self.state_root = root
        self.workspaces_directory = root / "workspaces"
        self.directory = self.workspaces_directory / self.workspace_identity
        try:
            self.directory.relative_to(self.workspace)
        except ValueError:
            pass
        else:
            raise ValueError("run journal must be outside the Git workspace")
        self.journal_path = self.directory / "runs.json"
        self._transaction_path = self.directory / "runs.lock"
        self._instance_path = self.directory / "instance.lock"
        self._instance_handle: BinaryIO | None = None
        self.last_status = "ready"
        self.last_warning: str | None = None

    def acquire_instance(self) -> None:
        if self._instance_handle is not None:
            return
        self._ensure_directory()
        handle = self._instance_path.open("a+b")
        os.chmod(self._instance_path, 0o600)
        try:
            _lock(handle, blocking=False)
        except (BlockingIOError, OSError) as exc:
            handle.close()
            raise RunJournalInUseError(
                "another APatch Studio process owns this workspace journal"
            ) from exc
        self._instance_handle = handle

    def close(self) -> None:
        handle = self._instance_handle
        self._instance_handle = None
        if handle is not None:
            try:
                _unlock(handle)
            finally:
                handle.close()

    def load(self) -> RunJournalLoad:
        with self._transaction():
            return self._load_unlocked(quarantine=True)

    def save(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        accepted = [self._validated_copy(record) for record in records]
        accepted = self._apply_retention(accepted)
        document = {
            "schema": JOURNAL_SCHEMA,
            "workspace_identity": self.workspace_identity,
            "updated_at": _now(),
            "records": accepted,
        }
        try:
            assert_projection_safe(document)
        except UnsafeProjectionError as exc:
            raise RunJournalError(str(exc)) from exc
        payload = json.dumps(
            document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(payload) > MAX_JOURNAL_BYTES:
            raise RunJournalError("run journal exceeds the storage limit")
        with self._transaction():
            self._atomic_write(payload)
        self.last_status = "ready"
        self.last_warning = None
        return accepted

    def _load_unlocked(self, *, quarantine: bool) -> RunJournalLoad:
        if not self.journal_path.exists():
            self.last_status = "ready"
            self.last_warning = None
            return RunJournalLoad([])
        try:
            if self.journal_path.stat().st_size > MAX_JOURNAL_BYTES:
                raise RunJournalError("run journal exceeds the storage limit")
            document = json.loads(self.journal_path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or document.get("schema") != JOURNAL_SCHEMA:
                raise RunJournalError("unsupported run journal schema")
            if document.get("workspace_identity") != self.workspace_identity:
                raise RunJournalError("run journal workspace identity mismatch")
            raw_records = document.get("records")
            if not isinstance(raw_records, list):
                raise RunJournalError("run journal records must be a list")
            records = [self._validated_copy(record) for record in raw_records]
        except (OSError, UnicodeError, json.JSONDecodeError, RunJournalError) as exc:
            if not quarantine:
                raise RunJournalError("invalid run journal") from exc
            self._quarantine()
            self.last_status = "recovered"
            self.last_warning = "invalid_journal_quarantined"
            return RunJournalLoad([], status=self.last_status, warning=self.last_warning)
        self.last_status = "ready"
        self.last_warning = None
        return RunJournalLoad(records)

    def _validated_copy(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise RunJournalError("run record must be an object")
        self._exact_keys(record, _RECORD_FIELDS, "run record")
        if record.get("schema") != RECORD_SCHEMA:
            raise RunJournalError("unsupported run record schema")
        run_id = record.get("run_id")
        if not isinstance(run_id, str) or not run_id.startswith("apr_") or len(run_id) != 36:
            raise RunJournalError("invalid run id")
        request = record.get("request")
        if not isinstance(request, dict):
            raise RunJournalError("run request must be an object")
        self._exact_keys(request, _REQUEST_FIELDS, "run request")
        execution_context = record.get("execution_context")
        if execution_context is not None:
            try:
                ExecutionContext.model_validate(execution_context)
            except ValueError as exc:
                raise RunJournalError("invalid execution context") from exc
        sdd_execution = record.get("sdd_execution")
        if sdd_execution is not None:
            try:
                SddExecutionContext.model_validate(sdd_execution)
            except ValueError as exc:
                raise RunJournalError("invalid SDD execution context") from exc
        if record.get("status") not in ACTIVE_STATUSES | TERMINAL_STATUSES:
            raise RunJournalError("invalid persisted run status")
        planning_last_activity_at = record.get("planning_last_activity_at")
        if planning_last_activity_at is not None and not isinstance(planning_last_activity_at, str):
            raise RunJournalError("invalid planning activity timestamp")
        if record.get("planning_cleanup", "not_needed") not in {
            "not_needed",
            "already_closed",
            "closed",
            "rolled_back",
            "failed",
        }:
            raise RunJournalError("invalid planning cleanup outcome")
        review = record.get("review")
        if review is not None:
            if not isinstance(review, dict):
                raise RunJournalError("run review must be an object")
            self._exact_keys(review, _REVIEW_FIELDS, "run review")
            for name in ("baseline", "result"):
                snapshot = review.get(name)
                if snapshot is not None:
                    if not isinstance(snapshot, dict):
                        raise RunJournalError("review snapshot must be an object")
                    self._exact_keys(snapshot, _SNAPSHOT_FIELDS, "review snapshot")
            delta = review.get("delta")
            if delta is not None:
                if not isinstance(delta, dict):
                    raise RunJournalError("review delta must be an object")
                self._exact_keys(delta, _DELTA_FIELDS, "review delta")
        timeline = record.get("timeline", [])
        if not isinstance(timeline, list) or len(timeline) > 64:
            raise RunJournalError("run timeline must contain at most 64 events")
        for event in timeline:
            if not isinstance(event, dict):
                raise RunJournalError("run timeline event must be an object")
            self._exact_keys(event, _TIMELINE_FIELDS, "run timeline event")
            if not all(isinstance(event.get(key), str) for key in _TIMELINE_FIELDS):
                raise RunJournalError("run timeline event fields must be strings")
            if len(event["phase"]) > 64 or len(event["message"]) > 240:
                raise RunJournalError("run timeline event exceeds storage bounds")
        reviewer_note = record.get("reviewer_note")
        if reviewer_note is not None:
            if not isinstance(reviewer_note, dict):
                raise RunJournalError("reviewer note must be an object")
            self._exact_keys(reviewer_note, _REVIEWER_NOTE_FIELDS, "reviewer note")
            if reviewer_note.get("schema") != "apatch.studio.reviewer-note.v1":
                raise RunJournalError("unsupported reviewer note schema")
            text = reviewer_note.get("text")
            if not isinstance(text, str) or not 3 <= len(text) <= 1000:
                raise RunJournalError("reviewer note must contain 3..1000 characters")
        contribution = record.get("contribution")
        if contribution is not None:
            if not isinstance(contribution, dict):
                raise RunJournalError("run contribution must be an object")
            self._exact_keys(contribution, _CONTRIBUTION_FIELDS, "run contribution")
            receipt = contribution.get("contribution_receipt")
            if receipt is not None:
                if not isinstance(receipt, dict):
                    raise RunJournalError("contribution receipt must be an object")
                self._exact_keys(receipt, _CONTRIBUTION_RECEIPT_FIELDS, "contribution receipt")
            sync = contribution.get("avatar_sync")
            if sync is not None:
                if not isinstance(sync, dict):
                    raise RunJournalError("avatar sync must be an object")
                self._exact_keys(sync, _AVATAR_SYNC_FIELDS, "avatar sync")
        plan_handoff = record.get("plan_handoff")
        if plan_handoff is not None:
            if not isinstance(plan_handoff, dict):
                raise RunJournalError("plan handoff must be an object")
            self._exact_keys(plan_handoff, _PLAN_HANDOFF_FIELDS, "plan handoff")
            if (
                plan_handoff.get("schema") != "apatch.studio.plan-handoff.v1"
                or plan_handoff.get("status") != "review_ready"
                or not isinstance(plan_handoff.get("spec_id"), str)
                or _PLAN_HANDOFF_SPEC.fullmatch(plan_handoff["spec_id"]) is None
                or not isinstance(plan_handoff.get("objective"), str)
                or not 3 <= len(plan_handoff["objective"]) <= 2000
                or not isinstance(plan_handoff.get("prepared_at"), str)
                or not isinstance(plan_handoff.get("package_hash"), str)
                or _PLAN_HANDOFF_HASH.fullmatch(plan_handoff["package_hash"]) is None
            ):
                raise RunJournalError("invalid plan handoff")
            requirement_ids = plan_handoff.get("requirement_ids")
            if (
                not isinstance(requirement_ids, list)
                or not 1 <= len(requirement_ids) <= 256
                or len(set(requirement_ids)) != len(requirement_ids)
                or any(
                    not isinstance(requirement_id, str)
                    or _PLAN_HANDOFF_REQUIREMENT.fullmatch(requirement_id) is None
                    for requirement_id in requirement_ids
                )
            ):
                raise RunJournalError("invalid plan handoff requirements")
        scope = record.get("scope")
        if scope is not None:
            if not isinstance(scope, dict):
                raise RunJournalError("run scope must be an object")
            self._exact_keys(scope, _SCOPE_FIELDS, "run scope")
            if scope.get("schema") != "apatch.studio.scope-outcome.v1":
                raise RunJournalError("unsupported run scope schema")
            if scope.get("status") not in _SCOPE_STATUSES:
                raise RunJournalError("invalid run scope status")
            if not isinstance(scope.get("audit_observed"), bool):
                raise RunJournalError("run scope audit flag must be boolean")
            for field_name in (
                "planned_file_count",
                "blocked_out_of_scope",
                "reverted_out_of_scope",
                "unresolved_out_of_scope",
            ):
                value = scope.get(field_name)
                if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100_000:
                    raise RunJournalError("run scope count is invalid")
            areas = scope.get("logical_areas")
            if not isinstance(areas, list) or len(areas) > len(_SCOPE_AREAS):
                raise RunJournalError("run scope logical areas are invalid")
            if len(set(areas)) != len(areas) or not set(areas).issubset(_SCOPE_AREAS):
                raise RunJournalError("run scope logical areas are invalid")
        try:
            assert_projection_safe(record)
        except UnsafeProjectionError as exc:
            raise RunJournalError(str(exc)) from exc
        try:
            return json.loads(json.dumps(record, ensure_ascii=True))
        except (TypeError, ValueError) as exc:
            raise RunJournalError("run record is not JSON serializable") from exc

    @staticmethod
    def _exact_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
        unknown = set(value) - allowed
        if unknown:
            raise RunJournalError(f"{label} has forbidden fields: {sorted(unknown)}")

    def _apply_retention(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        terminal = [record for record in records if record["status"] in TERMINAL_STATUSES]
        keep_terminal = {record["run_id"] for record in terminal[-self.retention :]}
        return [
            record
            for record in records
            if record["status"] in ACTIVE_STATUSES or record["run_id"] in keep_terminal
        ]

    def _ensure_directory(self) -> None:
        for directory in (self.state_root, self.workspaces_directory, self.directory):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(directory, 0o700)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._ensure_directory()
        handle = self._transaction_path.open("a+b")
        os.chmod(self._transaction_path, 0o600)
        try:
            _lock(handle, blocking=True)
            yield
        finally:
            _unlock(handle)
            handle.close()

    def _atomic_write(self, payload: bytes) -> None:
        self._ensure_directory()
        temporary = self.directory / f".runs.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.journal_path)
            os.chmod(self.journal_path, 0o600)
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def _quarantine(self) -> None:
        if not self.journal_path.exists():
            return
        quarantine = self.directory / f"runs.corrupt.{uuid.uuid4().hex}.json"
        os.replace(self.journal_path, quarantine)
        os.chmod(quarantine, 0o600)
