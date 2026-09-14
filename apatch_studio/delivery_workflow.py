"""Bounded Git delivery workflow for APatch Studio."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from apatch.workflows import verify_notarization_workspace
from pydantic import BaseModel, ConfigDict, Field, model_validator

from apatch_studio.action_facade import StudioWorkflowError
from apatch_studio.projection import assert_projection_safe
from apatch_studio.run_store import default_state_root, workspace_identity

_REQUEST_ID = r"^apsreq_[a-z0-9][a-z0-9_-]{7,95}$"


class DeliveryActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(pattern=_REQUEST_ID)
    action: Literal["commit", "push", "open_pr"]
    confirmed: Literal[True]
    message: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_action_shape(self):
        if self.action == "commit":
            message = " ".join((self.message or "").split())
            if not 3 <= len(message) <= 200:
                raise ValueError("commit requires a message of 3..200 characters")
            object.__setattr__(self, "message", message)
        elif self.message is not None:
            raise ValueError("message is accepted only for commit")
        return self


def _hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class GitDeliveryWorkflow:
    """Expose only commit-staged, push-current and open-current-PR operations."""

    def __init__(
        self,
        workspace: str | os.PathLike[str],
        *,
        state_root: str | os.PathLike[str] | None = None,
        notarization: Callable[..., dict[str, Any]] = verify_notarization_workspace,
        run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
    ):
        self.root = Path(workspace).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError(f"workspace does not exist: {self.root}")
        self._git = which("git")
        self._gh = which("gh")
        self._notarization = notarization
        self._run_command = run_command
        state = Path(state_root).expanduser().resolve() if state_root else default_state_root()
        self._directory = state / "workspaces" / workspace_identity(self.root)
        self._receipts = self._directory / "delivery-receipts.json"
        self._lock = threading.RLock()

    def status(self) -> dict[str, Any]:
        self._require_git()
        branch_result = self._run(["symbolic-ref", "--quiet", "--short", "HEAD"])
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
        staged = self._nul_count(["diff", "--cached", "--name-only", "-z"])
        unstaged = self._nul_count(["diff", "--name-only", "-z"])
        untracked = self._nul_count(["ls-files", "--others", "--exclude-standard", "-z"])

        upstream_result = self._run(["rev-parse", "--verify", "@{upstream}"])
        upstream = upstream_result.returncode == 0
        ahead = 0
        behind = 0
        if upstream:
            counts = self._run(
                ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"]
            )
            if counts.returncode == 0:
                parts = counts.stdout.split()
                if len(parts) == 2:
                    ahead, behind = int(parts[0]), int(parts[1])

        github_origin = False
        origin = self._run(["remote", "get-url", "origin"])
        if origin.returncode == 0:
            value = origin.stdout.strip().lower()
            github_origin = (
                value.startswith("git@github.com:")
                or value.startswith("ssh://git@github.com/")
                or value.startswith("https://github.com/")
            )

        result = {
            "schema": "apatch.studio.delivery-status.v1",
            "branch": branch,
            "detached": branch is None,
            "staged_count": staged,
            "unstaged_count": unstaged,
            "untracked_count": untracked,
            "upstream_configured": upstream,
            "ahead": ahead,
            "behind": behind,
            "can_commit": staged > 0,
            "can_push": bool(branch and upstream and ahead > 0),
            "can_open_pr": bool(branch and upstream and github_origin and self._gh),
            "pr_provider": "github" if github_origin else None,
        }
        assert_projection_safe(result)
        return result

    def act(self, request: DeliveryActionRequest) -> dict[str, Any]:
        request_hash = _hash(request.model_dump(mode="json"))
        with self._lock:
            receipts = self._load_receipts()
            existing = receipts.get(request.request_id)
            if existing is not None:
                if existing.get("request_hash") != request_hash:
                    raise StudioWorkflowError(
                        "request id was already used for another delivery action",
                        code="delivery_idempotency_conflict",
                    )
                return existing

            before = self.status()
            if request.action == "commit":
                result = self._commit(request.message or "", before)
            elif request.action == "push":
                result = self._push(before)
            else:
                result = self._open_pr(before)
            receipt = {
                "schema": "apatch.studio.delivery-receipt.v1",
                "request_id": request.request_id,
                "request_hash": request_hash,
                "action": request.action,
                "status": "complete",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "result": result,
            }
            assert_projection_safe(receipt)
            receipts[request.request_id] = receipt
            self._save_receipts(receipts)
            return receipt

    def _commit(self, message: str, before: dict[str, Any]) -> dict[str, Any]:
        staged_count = int(before["staged_count"])
        if staged_count == 0:
            raise StudioWorkflowError(
                "there are no staged changes to commit",
                code="nothing_staged",
            )
        proof = self._notarization(str(self.root), staged=True)
        if not proof.get("ok") or int(proof.get("checked") or 0) != staged_count:
            raise StudioWorkflowError(
                "all staged files must pass APatch notarization before commit",
                code="staged_notarization_required",
            )
        committed = self._run(["commit", "-m", message])
        if committed.returncode != 0:
            raise StudioWorkflowError(
                "Git could not commit the staged change set",
                code="commit_failed",
            )
        head = self._run(["rev-parse", "HEAD"])
        return {
            "ok": True,
            "committed": True,
            "commit_id": head.stdout.strip() if head.returncode == 0 else None,
            "committed_file_count": staged_count,
            "notarization_checked": int(proof.get("checked") or 0),
            "remaining": self.status(),
        }

    def _push(self, before: dict[str, Any]) -> dict[str, Any]:
        if not before["upstream_configured"]:
            raise StudioWorkflowError(
                "configure an upstream for the current branch before push",
                code="upstream_required",
            )
        if not before["branch"]:
            raise StudioWorkflowError(
                "detached HEAD cannot be pushed by Studio",
                code="detached_head",
            )
        pushed = self._run(["push", "--porcelain"])
        if pushed.returncode != 0:
            raise StudioWorkflowError(
                "Git could not push the current branch",
                code="push_failed",
            )
        return {
            "ok": True,
            "pushed": True,
            "branch": before["branch"],
            "after": self.status(),
        }

    def _open_pr(self, before: dict[str, Any]) -> dict[str, Any]:
        if not before["can_open_pr"] or self._gh is None:
            raise StudioWorkflowError(
                "GitHub CLI, a GitHub origin and an upstream branch are required",
                code="pull_request_unavailable",
            )
        created = self._run_external(
            [self._gh, "pr", "create", "--fill", "--head", str(before["branch"])]
        )
        if created.returncode != 0:
            existing = self._run_external(
                [self._gh, "pr", "view", str(before["branch"]), "--json", "number"]
            )
            if existing.returncode != 0:
                raise StudioWorkflowError(
                    "GitHub could not create or resolve the pull request",
                    code="pull_request_failed",
                )
        return {
            "ok": True,
            "pull_request_recorded": True,
            "branch": before["branch"],
            "provider": "github",
        }

    def _require_git(self) -> None:
        if self._git is None:
            raise StudioWorkflowError("Git is unavailable", code="git_unavailable")

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self._require_git()
        return self._run_external([str(self._git), *args])

    def _run_external(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        return self._run_command(
            argv,
            cwd=str(self.root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
        )

    def _nul_count(self, args: list[str]) -> int:
        result = self._run(args)
        if result.returncode != 0:
            raise StudioWorkflowError(
                "Git status is unavailable",
                code="git_status_unavailable",
            )
        return len([item for item in result.stdout.split("\0") if item])

    def _load_receipts(self) -> dict[str, dict[str, Any]]:
        if not self._receipts.is_file():
            return {}
        try:
            value = json.loads(self._receipts.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StudioWorkflowError(
                "delivery receipt store is unavailable",
                code="delivery_receipt_store_unavailable",
                status_code=503,
            ) from exc
        if not isinstance(value, dict):
            raise StudioWorkflowError(
                "delivery receipt store is invalid",
                code="delivery_receipt_store_invalid",
                status_code=503,
            )
        return {key: item for key, item in value.items() if isinstance(item, dict)}

    def _save_receipts(self, receipts: dict[str, dict[str, Any]]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._directory, 0o700)
        temporary = self._receipts.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                receipts, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(self._receipts)
        os.chmod(self._receipts, 0o600)
