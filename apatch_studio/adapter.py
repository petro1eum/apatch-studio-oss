"""Bounded APatch governed-runtime read-model adapter used by Studio P0."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from apatch import __version__ as apatch_version
from apatch.artifact_governance import build_doctor_hygiene
from apatch.doctor import run_doctor
from apatch.project_status import _activity_from_index
from apatch.runtime.session import build_session_view
from apatch.spec import _ledger_entries, _load_spec
from apatch.spec_coverage import spec_coverage_from_entries
from apatch.spec_interference import _discover_spec_ids
from apatch.traceability import build_traceability_index
from apatch.work_assets import list_work_assets

from apatch_studio.capabilities import build_runtime_capability_contract
from apatch_studio.endpoint_identity import endpoint_identity_status
from apatch_studio.runtime_requirements import probe_runtime_requirements
from apatch_studio.change_details import project_signed_change_detail
from apatch_studio.change_history import project_signed_changes
from apatch_studio.projection import assert_projection_safe
from apatch_studio.project_documents import ProjectKnowledgeWorkspace


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


_REPOSITORY_COMPONENT = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\\\/]")
_SCP_REMOTE = re.compile(r"^[^/@\\s]+@[^:\\s]+:(?P<path>.+)$")


def _repository_slug(remote: str) -> str | None:
    """Return a credential-free owner/repository label for a network remote."""

    value = remote.strip()
    if not value or value.startswith(("/", "~")) or _WINDOWS_ABSOLUTE.match(value):
        return None
    if "://" in value:
        parsed = urlsplit(value)
        if not parsed.hostname:
            return None
        candidate = parsed.path
    else:
        matched = _SCP_REMOTE.fullmatch(value)
        if matched is None:
            return None
        candidate = matched.group("path")
    parts = [part for part in candidate.strip("/").split("/") if part]
    if len(parts) < 2:
        return None
    parts[-1] = parts[-1][:-4] if parts[-1].endswith(".git") else parts[-1]
    owner, repository = parts[-2:]
    if not all(_REPOSITORY_COMPONENT.fullmatch(part) for part in (owner, repository)):
        return None
    return f"{owner}/{repository}"


def _timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return str(value)


class APatchStudioAdapter:
    def __init__(self, workspace: str | os.PathLike[str], *, cache_ttl: float = 2.0):
        self.root = Path(workspace).expanduser().resolve()
        if not (self.root / ".git").exists():
            raise ValueError(f"workspace is not a git repository: {self.root}")
        self.cache_ttl = cache_ttl
        self._cached_at = 0.0
        self._cached: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self.project_documents = ProjectKnowledgeWorkspace(self.root)

    def _workspace(self) -> dict[str, Any]:
        porcelain = _git(self.root, "status", "--porcelain=v1")
        dirty = [line for line in porcelain.splitlines() if line.strip()]
        return {
            "name": self.root.name,
            "identity": hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()[:16],
            "repository": _repository_slug(
                _git(self.root, "remote", "get-url", "origin")
            ),
            "branch": _git(self.root, "branch", "--show-current") or "detached",
            "upstream": _git(
                self.root,
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{upstream}",
            )
            or None,
            "head": _git(self.root, "rev-parse", "--short=12", "HEAD") or None,
            "operator": _git(self.root, "config", "user.name")[:160] or "Local user",
            "dirty_files": len(dirty),
            "clean": not dirty,
        }

    @staticmethod
    def _specifications(status: dict[str, Any]) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for raw in status.get("specs") or []:
            summary = raw.get("summary") or {}
            requirements = list(raw.get("requirements") or [])
            coverage_status = str(raw.get("coverage_status") or "available")
            stale_ids = [
                str(row.get("id"))
                for row in requirements
                if row.get("state") == "stale" or row.get("stale")
            ]
            pending_ids = [
                str(row.get("id"))
                for row in requirements
                if row.get("state") == "pending"
            ]
            specs.append(
                {
                    "id": raw.get("id"),
                    "title": raw.get("title") or raw.get("id"),
                    "done": coverage_status == "available" and bool(raw.get("done")),
                    "coverage_status": coverage_status,
                    "coverage_error": raw.get("coverage_error"),
                    "total": int(summary.get("total") or 0),
                    "attested": int(summary.get("attested") or 0),
                    "pending": int(summary.get("pending") or 0),
                    "stale": int(summary.get("stale") or 0),
                    "blocked": int(summary.get("blocked") or 0),
                    "percent": float(summary.get("percent_complete") or 0),
                    "stale_ids": stale_ids,
                    "pending_ids": pending_ids,
                }
            )
        specs.sort(
            key=lambda row: (
                row["coverage_status"] == "available",
                -row["stale"],
                -row["blocked"],
                row["done"],
                row["id"] or "",
            )
        )
        return specs[:250]

    @staticmethod
    def _activity(status: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "id": row.get("op_id"),
                "role": row.get("role"),
                "tool": row.get("tool_id"),
                "at": _timestamp(row.get("timestamp")),
                "signed_by": row.get("signed_by"),
                "intent": row.get("intent"),
                "session_id": row.get("governed_session_id"),
            }
            for row in (status.get("activity") or [])[:24]
        ]

    @staticmethod
    def _work_assets(raw: dict[str, Any]) -> dict[str, Any]:
        assets = []
        for asset in raw.get("assets") or []:
            assets.append(
                {
                    "id": asset.get("asset_id"),
                    "title": asset.get("title"),
                    "kind": asset.get("asset_kind"),
                    "lifecycle": asset.get("lifecycle"),
                    "recallable": bool(asset.get("recallable")),
                    "reuse_count": int((asset.get("reuse") or {}).get("count") or 0),
                    "signals": list(asset.get("trigger_signals") or [])[:6],
                    "verification_count": len(asset.get("verification_refs") or []),
                }
            )
        return {
            "count": int(raw.get("asset_count") or len(assets)),
            "lifecycle_counts": dict(raw.get("lifecycle_counts") or {}),
            "items": assets[:24],
        }

    @staticmethod
    def _session(raw: dict[str, Any]) -> dict[str, Any]:
        session = raw.get("session") or {}
        session_id = session.get("session_id")
        if not session_id:
            return {
                "active": False,
                "id": None,
                "intent": None,
                "lifecycle": "idle",
                "phase": "idle",
                "checkpoint": None,
                "risk": "low",
                "next_action": None,
                "started_at": None,
                "ended_at": None,
                "failure": None,
            }
        return {
            "active": not bool(session.get("ended_at")),
            "id": session_id,
            "intent": session.get("intent"),
            "lifecycle": session.get("lifecycle") or "idle",
            "phase": session.get("phase") or "idle",
            "checkpoint": session.get("checkpoint"),
            "risk": session.get("risk_level") or "low",
            "next_action": session.get("next_action"),
            "started_at": session.get("started_at"),
            "ended_at": session.get("ended_at"),
            "failure": session.get("failure"),
        }

    @staticmethod
    def _mcp_profile(doctor: dict[str, Any]) -> str:
        health = doctor.get("mcp_health") or {}
        fingerprint = health.get("stored_mcp_fingerprint") or {}
        catalog = health.get("mcp_tool_catalog") or {}
        catalog_count = int(catalog.get("count") or 0)
        fingerprint_count = int(fingerprint.get("tool_count") or 0)
        if catalog_count > 15 and catalog_count > fingerprint_count:
            return "full"
        return str(fingerprint.get("mcp_profile") or doctor.get("mcp_profile") or "unknown")

    def _canonical_status_snapshot(self, *, include_hygiene: bool = True) -> dict[str, Any]:
        """Compose one file-drift-aware APatch snapshot from one ledger read."""

        entries, ledger_active = _ledger_entries(str(self.root))
        trace_index = build_traceability_index(entries or [])
        specs: list[dict[str, Any]] = []
        errors: list[str] = []

        for spec_id in _discover_spec_ids(str(self.root)):
            try:
                parsed = _load_spec(str(self.root), spec=spec_id)
                coverage = spec_coverage_from_entries(parsed, entries, str(self.root))
                requirements = list(coverage.get("requirements") or [])
                summary = dict(coverage.get("summary") or {})
                summary["blocked"] = sum(
                    1 for row in requirements if row.get("state") == "blocked"
                )
                total = int(summary.get("total") or 0)
                attested = int(summary.get("attested") or 0)
                summary["percent_complete"] = (
                    round(100.0 * attested / total, 1) if total else 0.0
                )
                specs.append(
                    {
                        "id": spec_id,
                        "title": parsed.title,
                        "summary": summary,
                        "requirements": requirements,
                        "done": bool(total) and attested == total,
                        "coverage_status": "available",
                        "coverage_error": None,
                    }
                )
            except (FileNotFoundError, ValueError):
                continue
            except Exception as exc:
                error_type = type(exc).__name__
                errors.append(error_type)
                specs.append(
                    {
                        "id": spec_id,
                        "title": spec_id,
                        "summary": {},
                        "requirements": [],
                        "done": False,
                        "coverage_status": "unavailable",
                        "coverage_error": error_type,
                    }
                )

        summary: dict[str, Any] = {
            "spec_count": len(specs),
            "coverage_status": "unavailable" if errors else "available",
            "coverage_error": errors[0] if errors else None,
        }
        if not errors:
            total = sum(int((row.get("summary") or {}).get("total") or 0) for row in specs)
            attested = sum(int((row.get("summary") or {}).get("attested") or 0) for row in specs)
            summary.update(
                {
                    "total_requirements": total,
                    "attested": attested,
                    "stale_count": sum(
                        int((row.get("summary") or {}).get("stale") or 0)
                        for row in specs
                    ),
                    "percent_complete": (
                        round(100.0 * attested / total, 1) if total else 0.0
                    ),
                }
            )

        return {
            "ledger_active": ledger_active,
            "specs": specs,
            "summary": summary,
            "hygiene": build_doctor_hygiene(str(self.root)) if include_hygiene else {},
            "activity": _activity_from_index(trace_index),
            "changes": project_signed_changes(entries or [], limit=80),
        }

    def _build(self) -> dict[str, Any]:
        with ThreadPoolExecutor(max_workers=2) as executor:
            status_future = executor.submit(
                self._canonical_status_snapshot, include_hygiene=False
            )
            doctor_future = executor.submit(run_doctor, str(self.root))
            status = status_future.result()
            doctor = doctor_future.result()
        session = build_session_view(str(self.root))
        try:
            assets = list_work_assets(str(self.root), limit=24)
            asset_error = None
        except Exception as exc:  # optional projection must degrade independently
            assets = {"asset_count": 0, "lifecycle_counts": {}, "assets": []}
            asset_error = type(exc).__name__

        hygiene = doctor.get("hygiene") or doctor.get("runtime_hygiene") or {}
        writer = doctor.get("writer_protocol") or {}
        catalog = (doctor.get("mcp_health") or {}).get("mcp_tool_catalog") or {}
        projection = {
            "schema": "apatch.studio.workspace-overview.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "workspace": self._workspace(),
            "runtime": {
                "apatch_version": doctor.get("version") or apatch_version,
                "mcp_profile": self._mcp_profile(doctor),
                "tool_count": int(catalog.get("count") or 0),
                "trust_mode": (doctor.get("trustchain") or {}).get("mode"),
                "enforcement": bool((doctor.get("enforcement") or {}).get("active")),
                "trust_anchor": (doctor.get("trust_anchor") or {}).get("level"),
                "writer_protocol": writer.get("protocol"),
                "concurrent_writers": bool(writer.get("disjoint_concurrency")),
                "hygiene": hygiene.get("status") or "unknown",
                "hygiene_issues": [
                    {"type": issue.get("type"), "count": int(issue.get("count") or 0)}
                    for issue in (hygiene.get("issues") or [])[:8]
                ],
                "endpoint_identity": endpoint_identity_status(str(self.root)),
                "requirements": probe_runtime_requirements(
                    version=str(doctor.get("version") or apatch_version),
                ),
                "capability_contract": build_runtime_capability_contract(
                    version=str(doctor.get("version") or apatch_version),
                    profile=self._mcp_profile(doctor),
                    tool_count=int(catalog.get("count") or 0),
                    concurrent_writers=bool(writer.get("disjoint_concurrency")),
                ),
            },
            "summary": dict(status.get("summary") or {}),
            "project_brief": self.project_documents.project_brief(),
            "plans": self.project_documents.catalog(status),
            "session": self._session(session),
            "specifications": self._specifications(status),
            "evidence": self._activity(status),
            "changes": list(status.get("changes") or []),
            "work_assets": self._work_assets(assets),
            "degraded": [
                *(
                    ["spec_coverage"]
                    if (status.get("summary") or {}).get("coverage_status")
                    == "unavailable"
                    else []
                ),
                *(["work_assets"] if asset_error else []),
            ],
        }
        assert_projection_safe(projection)
        return projection

    def overview(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            if not force and self._cached is not None and now - self._cached_at < self.cache_ttl:
                return self._cached
            self._cached = self._build()
            self._cached_at = time.monotonic()
            return self._cached

    def document_catalog(self) -> dict[str, Any]:
        projection = self.project_documents.catalog(self._canonical_status_snapshot())
        assert_projection_safe(projection)
        return projection

    def document_detail(self, document_id: str) -> dict[str, Any]:
        projection = self.project_documents.document(
            document_id,
            self._canonical_status_snapshot(),
        )
        assert_projection_safe(projection)
        return projection

    def change_detail(self, change_id: str) -> dict[str, Any]:
        entries, _ledger_active = _ledger_entries(str(self.root))
        detail = project_signed_change_detail(
            entries or [],
            change_id,
            project=self._workspace(),
        )
        spec_id = detail.get("spec_id")
        requirement_id = detail.get("requirement_id")
        detail["decision_basis"] = (
            self.project_documents.decision_basis(
                str(spec_id),
                str(requirement_id),
                self._canonical_status_snapshot(),
            )
            if spec_id and requirement_id
            else None
        )
        return detail
