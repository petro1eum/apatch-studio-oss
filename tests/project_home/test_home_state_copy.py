"""'Needs attention' always names a cause and one next step (RFP-009 amendment, RFP-015)."""

from __future__ import annotations

import json
from pathlib import Path

from apatch_studio.change_feed import _current_state

ROOT = Path(__file__).resolve().parents[2]
SHELL = (ROOT / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")
VIEWS = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
TYPES = (ROOT / "frontend/src/types.ts").read_text(encoding="utf-8")
LANGUAGE = (ROOT / "frontend/src/productLanguage.ts").read_text(encoding="utf-8")
VOCABULARY = json.loads((ROOT / "frontend/src/vocabulary.contract.json").read_text(encoding="utf-8"))


def _run(status: str, **extra: object) -> dict:
    return {"kind": "studio_run", "run": {"status": status, "can_retry": status in {"failed", "cancelled", "interrupted"}, **extra}}


def test_every_home_state_carries_a_cause_and_one_next_step() -> None:
    cases = {
        "working": [_run("running"), _run("failed")],
        "attention": [_run("failed"), _run("failed"), _run("succeeded")],
        "review": [_run("succeeded")],
        "ready": [_run("succeeded", reviewer_note={"text": "Accepted"})],
    }
    for expected, items in cases.items():
        state = _current_state(items)
        assert state["id"] == expected
        assert state["detail"].strip() and state["next_step"].strip(), expected
        assert set(state) == {"id", "label", "tone", "detail", "next_step"}


def test_attention_state_counts_the_unfinished_changes() -> None:
    assert _current_state([_run("failed")])["detail"] == "1 change did not finish"
    assert _current_state([_run("failed"), _run("interrupted")])["detail"] == "2 changes did not finish"
    assert "Retry" in _current_state([_run("failed")])["next_step"]


def test_home_state_copy_uses_product_language_only() -> None:
    for items in ([_run("running")], [_run("failed")], [_run("succeeded")], []):
        state = _current_state(items)
        for text in (state["detail"], state["next_step"]):
            lowered = text.lower()
            for term in VOCABULARY["forbidden_primary_terms"]:
                assert term not in lowered, (term, text)


def test_home_and_runtime_card_render_the_cause_and_the_next_step() -> None:
    assert "detail: string;" in TYPES and "next_step: string;" in TYPES
    assert "{home.state.detail}" in VIEWS and "{home.state.next_step}" in VIEWS
    assert "export function runtimeAttention" in LANGUAGE
    assert "{runtimeAttention(data.runtime)}" in SHELL
    assert "Open Admin to run safe cleanup" in SHELL
    assert 'onClick={() => navigate("admin", "runtime")}' in SHELL
    for forbidden in VOCABULARY["forbidden_primary_terms"]:
        assert forbidden not in LANGUAGE[LANGUAGE.index("export function runtimeAttention"):].lower()
