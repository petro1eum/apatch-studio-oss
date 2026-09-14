"""Private fixed-purpose local review handoff for APatch Studio."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from apatch_studio.projection import assert_projection_safe
from apatch_studio.run_store import default_state_root, workspace_identity

_MAX_LOCAL_REVIEW_BYTES = 32 * 1024 * 1024
_REQUEST_ID_PATTERN = r"^[a-z0-9][a-z0-9_.:-]{7,95}$"


class ReviewWorkflowError(RuntimeError):
    """A bounded local review operation could not be completed."""

    def __init__(self, message: str, *, code: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class ReviewerNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=3, max_length=1000)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 3:
            raise ValueError("reviewer note is too short")
        return normalized


class LocalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(pattern=_REQUEST_ID_PATTERN)


class LocalReviewHandoff:
    """Materialize tracked changes privately and open them in an allowlisted local viewer."""

    def __init__(
        self,
        workspace: str | os.PathLike[str],
        *,
        state_root: str | os.PathLike[str] | None = None,
        launcher: Callable[[Path], str] | None = None,
        run_command: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    ):
        self.workspace = Path(workspace).expanduser().resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"workspace does not exist: {self.workspace}")
        root = Path(state_root).expanduser().resolve() if state_root else default_state_root()
        self.directory = root / "review-artifacts" / workspace_identity(self.workspace)
        self._launcher = launcher or self._launch_default
        self._run = run_command

    def open(self, run_id: str, request: LocalReviewRequest) -> dict[str, Any]:
        git = shutil.which("git")
        if git is None:
            raise ReviewWorkflowError(
                "Git is unavailable for local review",
                code="git_unavailable",
            )
        result = self._run(
            [git, "diff", "--no-ext-diff", "--no-color", "HEAD", "--"],
            cwd=str(self.workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise ReviewWorkflowError(
                "Git could not prepare the local review",
                code="local_review_unavailable",
            )
        payload = result.stdout
        if not isinstance(payload, bytes):
            payload = str(payload).encode("utf-8", errors="replace")
        return self.open_payload(run_id, payload, request)

    def open_payload(
        self,
        resource_id: str,
        payload: bytes,
        request: LocalReviewRequest,
        *,
        file_count: int | None = None,
    ) -> dict[str, Any]:
        """Open an already-bounded local patch without exposing it over HTTP."""

        if not isinstance(payload, bytes):
            raise ReviewWorkflowError(
                "Local review payload is invalid",
                code="local_review_unavailable",
            )
        if len(payload) > _MAX_LOCAL_REVIEW_BYTES:
            raise ReviewWorkflowError(
                "Local review exceeds the 32 MiB safety limit",
                code="local_review_too_large",
                status_code=413,
            )
        observed_files = sum(
            1 for line in payload.splitlines() if line.startswith(b"diff --git ")
        )
        receipt: dict[str, Any] = {
            "schema": "apatch.studio.local-review-handoff.v1",
            "request_id": request.request_id,
            "run_id": resource_id,
            "status": "empty" if not payload else "opened",
            "artifact_id": None,
            "file_count": max(0, int(file_count)) if file_count is not None else observed_files,
            "byte_count": len(payload),
            "launcher": None,
            "expires_in_sec": 0,
        }
        if not payload:
            assert_projection_safe(receipt)
            return receipt

        self._prepare_directory()
        self._remove_expired()
        artifact_id = "apsrev_" + uuid.uuid4().hex
        artifact = self.directory / f"{artifact_id}.patch"
        descriptor = os.open(artifact, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(artifact, 0o600)
            launcher = self._launcher(artifact)
        except Exception as exc:
            artifact.unlink(missing_ok=True)
            if isinstance(exc, ReviewWorkflowError):
                raise
            raise ReviewWorkflowError(
                "No allowlisted local review viewer is available",
                code="local_viewer_unavailable",
            ) from exc

        receipt.update(
            artifact_id=artifact_id,
            launcher=launcher,
            expires_in_sec=86400,
        )
        assert_projection_safe(receipt)
        return receipt

    def _prepare_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)

    def _remove_expired(self) -> None:
        cutoff = time.time() - 86400
        for candidate in self.directory.glob("apsrev_*.patch"):
            try:
                if candidate.stat().st_mtime < cutoff:
                    candidate.unlink()
            except OSError:
                continue

    @staticmethod
    def _launch_default(artifact: Path) -> str:
        if sys.platform == "darwin":
            argv = ["/usr/bin/open", "-t", str(artifact)]
            label = "system_text_viewer"
        elif os.name == "nt":  # pragma: no cover - Windows runtime
            os.startfile(artifact)  # type: ignore[attr-defined]
            return "system_text_viewer"
        else:
            executable = shutil.which("xdg-open")
            if executable is None:
                raise ReviewWorkflowError(
                    "No allowlisted local review viewer is available",
                    code="local_viewer_unavailable",
                )
            argv = [executable, str(artifact)]
            label = "system_text_viewer"
        subprocess.Popen(
            argv,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return label
