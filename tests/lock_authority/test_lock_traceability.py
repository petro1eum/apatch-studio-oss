"""Every promise in RFP-020 is answered by exactly one requirement of this SPEC.

A contract that quietly loses a line is worse than one that never had it: the
line still reads as agreed, and nothing goes red when it stops being true.
"""

import re
from pathlib import Path

RFP = Path("docs/RFP-020-studio-lock-authority.md")
SPEC = Path("docs/specs/SPEC-STUDIO-LOCK-AUTHORITY-1.md")


def _accepted_ids(text: str) -> list[str]:
    return re.findall(r"^\| (LOCK-\d+) \|", text, re.MULTILINE)


def test_every_accepted_promise_maps_to_one_requirement():
    rfp = RFP.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")

    promises = _accepted_ids(rfp)
    assert promises, "the RFP acceptance table is missing or unreadable"
    assert len(promises) == len(set(promises)), "an acceptance id appears twice"

    for promise in promises:
        rows = re.findall(rf"^\| {promise} \| (R\d+) \| covered \|", spec, re.MULTILINE)
        assert len(rows) == 1, f"{promise} is not mapped exactly once"
        requirement = rows[0]
        assert re.search(rf"^## {requirement} ", spec, re.MULTILINE), (
            f"{promise} maps to {requirement}, which the SPEC does not define"
        )


def test_no_requirement_is_answered_by_a_shared_command():
    """One green command proving several requirements proves none of them."""

    spec = SPEC.read_text(encoding="utf-8")
    commands = re.findall(r"^\(verify: (.+)\)$", spec, re.MULTILINE)
    assert len(commands) == len(set(commands)), "two requirements share one check"
