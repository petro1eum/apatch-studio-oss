"""Plain-language explanations for changes that did not finish (RFP-016 §7).

Every explanation says what happened and names one next step in product
language. The vocabulary contract forbids protocol terms here.
"""

from __future__ import annotations

from typing import Any

FAILURE_SCHEMA = "apatch.studio.run-failure.v1"
_TERMINAL_WITHOUT_RESULT = {"failed", "cancelled", "interrupted"}
_NOTHING_CHANGED = " Nothing in the project was changed."


def _plan_explanations(timeout_seconds: float, inspection_limit: int) -> dict[str, tuple[str, str, str]]:
    return {
        "plan_timeout": (
            "Planning ran out of time",
            f"The agent did not finish a reviewable plan within the {int(timeout_seconds)}-second limit." + _NOTHING_CHANGED,
            "Retry with the same request. If it happens again, narrow the request to one outcome.",
        ),
        "plan_discovery_budget_exceeded": (
            "Planning did not get past exploring",
            f"The agent kept reading the project ({inspection_limit} checks) instead of writing the plan." + _NOTHING_CHANGED,
            "Retry. If it repeats, describe the requested outcome more concretely.",
        ),
        "contract_preparation_missing": (
            "No plan was written",
            "The agent finished without leaving a reviewable plan; most often its plan bundle was rejected and not repaired." + _NOTHING_CHANGED,
            "Retry with the same request.",
        ),
        "contract_preparation_invalid": (
            "The plan could not be accepted",
            "The agent wrote a plan that does not match the shape Studio can review, so it was not shown." + _NOTHING_CHANGED,
            "Retry with the same request.",
        ),
        "contract_preparation_ambiguous": (
            "More than one plan was written",
            "The agent changed several plans at once, so Studio cannot tell which one belongs to this request." + _NOTHING_CHANGED,
            "Retry; Studio looks for exactly one new plan.",
        ),
        "contract_preparation_stale": (
            "The plan did not change",
            "The agent left the existing plan as it was, so there is nothing new to review." + _NOTHING_CHANGED,
            "Retry, or open the existing plan from Plans.",
        ),
    }


_RUNNER_EXPLANATIONS: dict[str, tuple[str, str, str]] = {
    "runner_unavailable": (
        "The agent is not installed",
        "Studio could not start the selected agent on this machine.",
        "Install the agent or pick another one in Admin, then retry.",
    ),
    "runner_authentication_required": (
        "The agent needs a sign-in",
        "The selected agent is installed but not signed in, so it could not start.",
        "Sign in to the agent from your terminal, then retry.",
    ),
    "runner_capacity_unavailable": (
        "The agent is busy",
        "The agent's service reported a usage or rate limit.",
        "Wait a few minutes and retry.",
    ),
    "runner_options_incompatible": (
        "The agent version does not match Studio",
        "The installed agent rejected the options Studio uses to run it.",
        "Update APatch Studio or the agent, then retry.",
    ),
    "runner_exit": (
        "The agent stopped early",
        "The agent ended before it finished the work, so Studio received no result.",
        "Retry. If it repeats, run the agent once from a terminal to see its own error.",
    ),
    "manager_error": (
        "Studio could not start the agent",
        "The agent process failed to launch.",
        "Check the runner in Admin, then retry.",
    ),
    "cancelled": (
        "Stopped by you",
        "You stopped this change; unfinished work was discarded.",
        "Start it again when you are ready.",
    ),
}

_DEFAULT = (
    "The change did not finish",
    "The agent stopped without a result.",
    "Retry with the same request.",
)
_INTERRUPTED = (
    "Interrupted",
    "Studio was closed or restarted while this change was running.",
    "Retry to start it again.",
)


def known_failure_outcomes() -> tuple[str, ...]:
    """Outcomes with a dedicated explanation (frozen by tests)."""

    return tuple(_plan_explanations(0, 0)) + tuple(_RUNNER_EXPLANATIONS)


def explain_failure(
    outcome: str | None,
    status: str,
    *,
    timeout_seconds: float,
    inspection_limit: int,
) -> dict[str, Any] | None:
    """Return what happened and what to do next, or ``None`` for a change that is not over without a result."""

    if status not in _TERMINAL_WITHOUT_RESULT:
        return None
    if status == "interrupted":
        headline, explanation, next_step = _INTERRUPTED
    else:
        table = _plan_explanations(timeout_seconds, inspection_limit)
        table.update(_RUNNER_EXPLANATIONS)
        headline, explanation, next_step = table.get(str(outcome or ""), _DEFAULT)
    return {
        "schema": FAILURE_SCHEMA,
        "outcome": outcome,
        "headline": headline,
        "explanation": explanation,
        "next_step": next_step,
        "retryable": True,
    }
