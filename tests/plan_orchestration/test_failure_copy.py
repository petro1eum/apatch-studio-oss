"""Failure states speak product language and name one next step (RFP-016 §7, FAST-8)."""

from __future__ import annotations

import json
from pathlib import Path

from apatch_studio.failure_copy import FAILURE_SCHEMA, explain_failure, known_failure_outcomes

ROOT = Path(__file__).resolve().parents[2]
VIEWS = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
TYPES = (ROOT / "frontend/src/types.ts").read_text(encoding="utf-8")
CSS = (ROOT / "frontend/src/outside-in.css").read_text(encoding="utf-8")
VOCABULARY = json.loads((ROOT / "frontend/src/vocabulary.contract.json").read_text(encoding="utf-8"))
FIELDS = ("headline", "explanation", "next_step")


def test_every_known_failure_outcome_explains_what_happened_and_what_to_do() -> None:
    for outcome in known_failure_outcomes():
        failure = explain_failure(outcome, "failed", timeout_seconds=300, inspection_limit=8)
        assert failure is not None, outcome
        assert failure["schema"] == FAILURE_SCHEMA
        assert failure["outcome"] == outcome
        assert failure["retryable"] is True
        for field in FIELDS:
            assert failure[field].strip(), (outcome, field)
        assert failure["next_step"] != failure["headline"]


def test_failure_copy_uses_product_language_only() -> None:
    texts = []
    for outcome in known_failure_outcomes() + ("something_new", None):
        for status in ("failed", "cancelled", "interrupted"):
            failure = explain_failure(outcome, status, timeout_seconds=300, inspection_limit=8)
            texts.extend(failure[field] for field in FIELDS)
    for text in texts:
        lowered = text.lower()
        for term in VOCABULARY["forbidden_primary_terms"]:
            assert term not in lowered, (term, text)
        for jargon in ("contract", "authoriz", "governed", "attributable", "budget", "lineage", "SPEC", "RFP"):
            assert jargon.lower() not in lowered, (jargon, text)


def test_plan_limits_are_named_in_the_explanation() -> None:
    timeout = explain_failure("plan_timeout", "failed", timeout_seconds=300, inspection_limit=8)
    assert "300-second" in timeout["explanation"]
    exploring = explain_failure("plan_discovery_budget_exceeded", "failed", timeout_seconds=300, inspection_limit=8)
    assert "8 checks" in exploring["explanation"]


def test_finished_and_running_changes_carry_no_failure_block() -> None:
    for status in ("queued", "running", "succeeded"):
        assert explain_failure("plan_ready", status, timeout_seconds=300, inspection_limit=8) is None


def test_interrupted_and_unknown_outcomes_still_get_a_next_step() -> None:
    interrupted = explain_failure(None, "interrupted", timeout_seconds=300, inspection_limit=8)
    assert interrupted["headline"] == "Interrupted"
    unknown = explain_failure("never_seen_before", "failed", timeout_seconds=300, inspection_limit=8)
    assert unknown["next_step"].startswith("Retry")


def test_failed_card_shows_what_happened_and_what_to_do() -> None:
    assert "failure: RunFailure | null;" in TYPES
    assert "export interface RunFailure" in TYPES
    assert 'aria-label="What happened"' in VIEWS
    for expression in ("run.failure.headline", "run.failure.explanation", "run.failure.next_step"):
        assert "{" + expression + "}" in VIEWS
    assert "What to do" in VIEWS
    assert ".oi-run-failure" in CSS
