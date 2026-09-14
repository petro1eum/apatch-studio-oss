from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from apatch_studio.agent_runs import AgentRunManager
from apatch_studio.operations import AgentRunRequest
from apatch_studio.plan_handoff import (
    MAX_PREPARATION_BYTES,
    PlanHandoffCollector,
    PlanHandoffError,
)


def _package(spec_id: str = "SPEC-PLAN-1", requirements: tuple[str, ...] = ("R1",)) -> dict:
    return {
        "schema": "apatch.studio.sdd-preparation.v1",
        "spec_id": spec_id,
        "objective": "Make the exact requested behavior true",
        "prepared_at": "2026-09-02T10:00:00+00:00",
        "source_mutation_count": 0,
        "contract_request": {"obligations": []},
        "task_envelopes": {
            requirement: {"requirement": f"{spec_id}#{requirement}"}
            for requirement in requirements
        },
    }


def _write_package(
    root: Path,
    *,
    spec_id: str = "SPEC-PLAN-1",
    requirements: tuple[str, ...] = ("R1",),
    package: dict | None = None,
) -> Path:
    spec = root / "docs" / "specs" / f"{spec_id}.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    sections = "\n\n".join(
        f"## {requirement} Outcome {requirement}\n\n(verify: python3 -m pytest -q)"
        for requirement in requirements
    )
    spec.write_text(
        f"# {spec_id} — Prepared plan\n\n"
        f"> **apatch artifact:** `spec:{spec_id}`\n\n{sections}\n",
        encoding="utf-8",
    )
    path = root / ".apatch" / "sdd" / "prepared" / f"{spec_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(package or _package(spec_id, requirements), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _code(exc: pytest.ExceptionInfo[PlanHandoffError]) -> str:
    return exc.value.code


def test_valid_new_preparation_is_attributed_to_exact_plan(tmp_path: Path) -> None:
    collector = PlanHandoffCollector(tmp_path)
    before = collector.capture()
    _write_package(tmp_path, requirements=("R2", "R1"))

    handoff = collector.resolve(before)

    assert handoff == {
        "schema": "apatch.studio.plan-handoff.v1",
        "status": "review_ready",
        "spec_id": "SPEC-PLAN-1",
        "requirement_ids": ["R2", "R1"],
        "objective": "Make the exact requested behavior true",
        "prepared_at": "2026-09-02T10:00:00+00:00",
        "package_hash": handoff["package_hash"],
    }
    assert handoff["package_hash"].startswith("sha256:")
    assert len(handoff["package_hash"]) == 71


def test_missing_preparation_fails_closed(tmp_path: Path) -> None:
    collector = PlanHandoffCollector(tmp_path)
    with pytest.raises(PlanHandoffError) as exc:
        collector.resolve(collector.capture())
    assert _code(exc) == "contract_preparation_missing"


def test_malformed_preparation_fails_closed_without_content_leak(tmp_path: Path) -> None:
    collector = PlanHandoffCollector(tmp_path)
    before = collector.capture()
    path = tmp_path / ".apatch" / "sdd" / "prepared" / "SPEC-BROKEN-1.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not-json:/Users/private/project}", encoding="utf-8")

    with pytest.raises(PlanHandoffError) as exc:
        collector.resolve(before)

    assert _code(exc) == "contract_preparation_invalid"
    assert "/Users/private/project" not in str(exc.value)
    assert str(path) not in str(exc.value)


def test_ambiguous_changed_preparations_fail_closed(tmp_path: Path) -> None:
    collector = PlanHandoffCollector(tmp_path)
    before = collector.capture()
    _write_package(tmp_path, spec_id="SPEC-PLAN-A")
    _write_package(tmp_path, spec_id="SPEC-PLAN-B")

    with pytest.raises(PlanHandoffError) as exc:
        collector.resolve(before)

    assert _code(exc) == "contract_preparation_ambiguous"


def test_unsafe_spec_identifier_is_rejected(tmp_path: Path) -> None:
    collector = PlanHandoffCollector(tmp_path)
    before = collector.capture()
    bad = _package()
    bad["spec_id"] = "../SPEC-ESCAPE"
    prepared = tmp_path / ".apatch" / "sdd" / "prepared"
    prepared.mkdir(parents=True)
    (prepared / "SPEC-PLAN-1.json").write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(PlanHandoffError) as exc:
        collector.resolve(before)

    assert _code(exc) == "contract_preparation_invalid"


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_symlink_preparation_is_rejected(tmp_path: Path) -> None:
    collector = PlanHandoffCollector(tmp_path)
    before = collector.capture()
    target = tmp_path / "outside.json"
    target.write_text(json.dumps(_package("SPEC-LINK-1")), encoding="utf-8")
    prepared = tmp_path / ".apatch" / "sdd" / "prepared"
    prepared.mkdir(parents=True)
    (prepared / "SPEC-LINK-1.json").symlink_to(target)

    with pytest.raises(PlanHandoffError) as exc:
        collector.resolve(before)

    assert _code(exc) == "contract_preparation_invalid"


def test_oversized_preparation_is_rejected(tmp_path: Path) -> None:
    collector = PlanHandoffCollector(tmp_path)
    before = collector.capture()
    prepared = tmp_path / ".apatch" / "sdd" / "prepared"
    prepared.mkdir(parents=True)
    (prepared / "SPEC-HUGE-1.json").write_bytes(b"{" + b"x" * MAX_PREPARATION_BYTES + b"}")

    with pytest.raises(PlanHandoffError) as exc:
        collector.resolve(before)

    assert _code(exc) == "contract_preparation_invalid"


def test_invalid_schema_is_rejected(tmp_path: Path) -> None:
    collector = PlanHandoffCollector(tmp_path)
    before = collector.capture()
    bad = _package()
    bad["schema"] = "apatch.studio.sdd-preparation.v0"
    _write_package(tmp_path, package=bad)

    with pytest.raises(PlanHandoffError) as exc:
        collector.resolve(before)

    assert _code(exc) == "contract_preparation_invalid"


def test_stale_rewrite_is_rejected(tmp_path: Path) -> None:
    path = _write_package(tmp_path)
    collector = PlanHandoffCollector(tmp_path)
    before = collector.capture()
    original = path.read_bytes()
    previous = path.stat()
    path.write_bytes(original)
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))

    with pytest.raises(PlanHandoffError) as exc:
        collector.resolve(before)

    assert _code(exc) == "contract_preparation_stale"


class _ExitZeroCatalog:
    def projection(self) -> list[dict[str, object]]:
        return [{"id": "codex", "label": "Test runner", "available": True}]

    def command(self, runner: str, workspace: Path) -> list[str]:
        return [sys.executable, "-c", "import sys; sys.stdin.read()"]


class _FixedCollector:
    def __init__(self, result: dict | PlanHandoffError):
        self.result = result

    def capture(self) -> object:
        return object()

    def resolve(self, before: object) -> dict:
        if isinstance(self.result, PlanHandoffError):
            raise self.result
        return self.result


def _request() -> AgentRunRequest:
    return AgentRunRequest.model_validate({
        "mode": "new_change",
        "runner": "codex",
        "objective": "Prepare an exact implementation plan",
        "acceptance_criteria": ["The owner can review exact scope and checks"],
    })


def test_valid_plan_completion_is_projected_as_plan_ready(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    handoff = {
        "schema": "apatch.studio.plan-handoff.v1",
        "status": "review_ready",
        "spec_id": "SPEC-PLAN-1",
        "requirement_ids": ["R1"],
        "objective": "Prepare an exact implementation plan",
        "prepared_at": "2026-09-02T10:00:00+00:00",
        "package_hash": "sha256:" + "a" * 64,
    }
    manager = AgentRunManager(
        workspace,
        catalog=_ExitZeroCatalog(),
        plan_handoff_collector=_FixedCollector(handoff),
        review_collector=lambda: None,
        state_root=tmp_path / "state",
    )

    completed = manager.wait(manager.start(_request())["run_id"], timeout=3)

    assert completed["status"] == "succeeded"
    assert completed["outcome"] == "plan_ready"
    assert completed["plan_handoff"] == handoff
    assert completed["available_actions"] == ["review_plan"]
    manager.close()


def test_missing_plan_completion_is_a_safe_failure(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = AgentRunManager(
        workspace,
        catalog=_ExitZeroCatalog(),
        plan_handoff_collector=_FixedCollector(
            PlanHandoffError(
                "The agent completed without one reviewable plan.",
                code="contract_preparation_missing",
            )
        ),
        review_collector=lambda: None,
        state_root=tmp_path / "state",
    )

    completed = manager.wait(manager.start(_request())["run_id"], timeout=3)

    assert completed["status"] == "failed"
    assert completed["outcome"] == "contract_preparation_missing"
    assert completed["plan_handoff"] is None
    assert completed["can_retry"] is True
    manager.close()
