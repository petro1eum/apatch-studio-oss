"""Every promise in RFP-021 is answered by exactly one requirement of this SPEC.

A contract that quietly loses a line is worse than one that never had it: the
line still reads as agreed, and nothing goes red when it stops being true.
"""

import re
from pathlib import Path

RFP = Path("docs/RFP-021-naming-a-machine-without-an-organization.md")
SPEC = Path("docs/specs/SPEC-STUDIO-LOCAL-IDENTITY-1.md")


def _accepted_ids(text: str) -> list[str]:
    return re.findall(r"^\| (NAME-\d+) \|", text, re.MULTILINE)


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


def test_an_operator_can_name_this_machine_without_writing_python():
    """A capability only reachable from a library is not in the product."""

    cli = Path("apatch_studio/cli.py").read_text(encoding="utf-8")
    assert '"name-this-machine"' in cli, "there is no command that names this machine"
    assert "name_this_machine" in cli


def test_the_command_runs_and_says_what_the_name_is_worth(tmp_path, capsys, monkeypatch):
    """A command that parses but does nothing is not a command."""

    from apatch_studio import cli

    monkeypatch.setattr(cli, "default_state_root", lambda: tmp_path)
    assert cli.name_machine(object()) == 0

    printed = capsys.readouterr().out
    assert "This machine is now called" in printed
    assert "own word" in printed
    assert "proves nothing to anyone else" in printed
    assert (tmp_path / "machine-identity.json").is_file()
