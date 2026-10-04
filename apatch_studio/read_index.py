"""Disposable, read-only acceleration of canonical APatch ledger projections.

Rows stay in process memory. This index grants no authority, persists no ledger
copy and never participates in source mutation admission.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from apatch import __version__
from apatch.artifact import payload_artifacts
from apatch.artifact_governance import build_doctor_hygiene
from apatch.doctor import build_policy_snapshot
from apatch.mcp_health import build_mcp_health
from apatch.traceability import build_traceability_index, _sort_key
from apatch.trust_identity import anchor_status
from apatch.trustchain_helper import TrustChainHelper


class WorkspaceReadIndex:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self._lock = threading.RLock()
        self._projection = None
        # Published rows and reusable scan results are separate. An invalid
        # object must never promote a partially parsed generation to evidence.
        self._objects: dict[str, tuple[tuple[int, ...], dict[str, Any]]] = {}
        self._parsed: dict[str, tuple[tuple[int, ...], dict[str, Any]]] = {}
        self._invalid: dict[str, tuple[tuple[int, ...], dict[str, str]]] = {}
        self._diagnostic: dict[str, Any] | None = None
        self._fallback: tuple[list[dict[str, Any]], bool] | None = None
        self.generation = 0

    @staticmethod
    def _stamp(path: Path) -> tuple[int, ...]:
        st = path.stat()
        return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)

    def failure_summary(self) -> dict[str, Any] | None:
        """Return a detached safe snapshot without blocking on a running scan."""
        diagnostic = self._diagnostic
        if diagnostic is None:
            return None
        # Explicitly whitelist public fields as well as detaching references.
        return {"code": diagnostic["code"],
                "affected_count": diagnostic["affected_count"],
                "truncated": diagnostic["truncated"],
                "items": [{"object_id": item["object_id"],
                           "digest": item["digest"], "reason": item["reason"]}
                          for item in diagnostic["items"][:16]]}

    def read(self, fallback: Callable | None = None):
        with self._lock:
            ledger_dir = self.root / ".trustchain"
            # Core's constructor installs hooks and creates reversible state.
            # Reuse its pure canonical walker/parser without mutation setup.
            view = SimpleNamespace(trustchain_dir=str(ledger_dir) if ledger_dir.is_dir() else None)
            paths = [Path(p) for p in TrustChainHelper._iter_ledger_json_paths(view)]
            current = {str(path) for path in paths}
            # Evict deleted objects, including failed ones, from scan caches.
            self._parsed = {key: value for key, value in self._parsed.items() if key in current}
            self._invalid = {key: value for key, value in self._invalid.items() if key in current}
            if not paths and not self._objects and fallback is not None:
                self._diagnostic = None
                if self._fallback is None:
                    self._fallback = fallback(str(self.root))
                return self._fallback
            self._fallback = None
            next_objects = {}
            failures = []
            for path in paths:
                key = str(path)
                stamp = self._stamp(path)
                previous = self._parsed.get(key)
                if previous is not None and previous[0] == stamp:
                    next_objects[key] = previous
                    continue
                failed = self._invalid.get(key)
                if failed is not None and failed[0] == stamp:
                    failures.append(failed[1])
                    continue
                self._parsed.pop(key, None)
                self._invalid.pop(key, None)
                raw = path.read_bytes()
                if self._stamp(path) != stamp:
                    raise RuntimeError("ledger_changed_during_read")
                reason = None
                try:
                    data = json.loads(raw)
                except (ValueError, UnicodeError):
                    reason = "invalid_json"
                if reason is None:
                    try:
                        if not isinstance(data, dict):
                            raise ValueError("ledger_object_not_mapping")
                        row = TrustChainHelper._parse_ledger_object(data)
                        row["object_path"] = str(path.relative_to(ledger_dir))
                    except (ValueError, TypeError, KeyError, AttributeError):
                        reason = "invalid_record"
                if reason is not None:
                    object_id = path.stem if re.fullmatch(r"op_[0-9]{1,20}", path.stem) else "unidentified_object"
                    item = {"object_id": object_id,
                            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                            "reason": reason}
                    self._invalid[key] = (stamp, item)
                    failures.append(item)
                    continue
                parsed = (stamp, row)
                self._parsed[key] = parsed
                next_objects[key] = parsed
            if failures:
                items = sorted(failures, key=lambda item: (item["object_id"], item["digest"]))
                self._diagnostic = {"code": "invalid_ledger_objects",
                                    "affected_count": len(items),
                                    "truncated": len(items) > 16,
                                    "items": [dict(item) for item in items[:16]]}
                raise ValueError("ledger_objects_unavailable")
            changed = set(next_objects) != set(self._objects) or any(
                self._objects[key][0] != value[0]
                for key, value in next_objects.items() if key in self._objects
            )
            if changed:
                self.generation += 1
            self._objects = next_objects
            self._diagnostic = None
            return [item[1] for item in self._objects.values()], ledger_dir.is_dir()

    def snapshot(self, fallback: Callable | None = None):
        """Reuse derived membership only while the canonical generation is unchanged."""
        with self._lock:
            entries, active = self.read(fallback=fallback)
            if self._projection is None or self._projection[0] != self.generation:
                trace = build_traceability_index(entries or [])
                groups, global_rows = spec_entry_groups(entries or [], trace)
                self._projection = (self.generation, trace, groups, global_rows)
            _, trace, groups, global_rows = self._projection
            return entries, active, trace, groups, global_rows


def spec_entry_groups(entries, trace_index=None):
    """Keep Core's assigned artifacts and predecessor context, sorted once."""
    index = trace_index if trace_index is not None else build_traceability_index(entries)
    summaries = index.get("op_id_index") or {}
    if not summaries:
        return {}, list(entries)
    groups: dict[str, dict[int, dict[str, Any]]] = {}
    global_rows: dict[int, dict[str, Any]] = {}
    context = None
    for position, row in enumerate(sorted(entries, key=_sort_key)):
        payload = row.get("payload") or {}
        direct = payload_artifacts(payload)
        if direct:
            context = (position, row)
        if row.get("tool_id") == "apatch_sdd_judge_amendment" or payload.get("sdd_evidence"):
            global_rows[position] = row
        summary = summaries.get(str(row.get("id") or row.get("signature"))) or {}
        parents = {
            str(artifact.get("id", "")).split("#", 1)[0]
            for artifact in summary.get("artifacts") or []
            if artifact.get("kind") == "spec"
        }
        for parent in parents:
            bucket = groups.setdefault(parent, {})
            bucket[position] = row
            if not direct and context is not None:
                bucket[context[0]] = context[1]
    result = {}
    for parent, bucket in groups.items():
        merged = {**global_rows, **bucket}
        result[parent] = [merged[p] for p in sorted(merged)]
    return result, [global_rows[p] for p in sorted(global_rows)]


def entries_for_spec(entries, spec_id, trace_index=None):
    groups, global_rows = spec_entry_groups(entries, trace_index)
    return groups.get(spec_id, global_rows)


def runtime_posture(root: Path):
    """Canonical lightweight policy views; full doctor is an explicit action."""
    workspace = str(root)
    posture = build_policy_snapshot(workspace)
    health = build_mcp_health(workspace)
    posture.update({
        "version": __version__,
        "mcp_health": health,
        "writer_protocol": health.get("writer_protocol") or {},
        "trust_anchor": anchor_status(workspace),
        "hygiene": build_doctor_hygiene(workspace),
        "audit_scope": "configuration_only",
    })
    return posture
