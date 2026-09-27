"""Exercise the browser validator and both API models against the lock authority."""

import json
from pathlib import Path
import subprocess

import pytest
from pydantic import ValidationError

from apatch_studio.lock_authority import LockAuthorityError, _reason
from apatch_studio.operations import LockReleaseAnswer, LockReleaseRequest

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    ("", False), ("Agreed", False), ("1234567", False), ("12345678", True),
    ("a      b", False), (" \tAgreed\n ", False),
    ("  Agreed,\n because this is needed.  ", True),
    ("😀" * 4, False), ("😀" * 8, True),
    ("a" * 500, True), ("a" * 501, False),
    (" \t" + "a" * 500 + "\n ", True),
    ("valid\x00reason", False), ("valid\x7freason", False),
    ("a\x85\x1c\u3000b", False), ("\ufeff1234567", True),
    ("Согласен с изменением", True),
]


@pytest.fixture(scope="module")
def browser_results(tmp_path_factory):
    output = tmp_path_factory.mktemp("lock-reason-js")
    subprocess.run([
        str(ROOT / "frontend/node_modules/.bin/tsc"),
        str(ROOT / "frontend/src/lockReason.ts"), "--outDir", str(output),
        "--target", "ES2022", "--module", "commonjs", "--skipLibCheck",
    ], check=True, capture_output=True, text=True)
    result = subprocess.run([
        "node", "-e",
        "const {validateLockReason}=require(process.argv[1]);"
        "console.log(JSON.stringify(JSON.parse(process.argv[2]).map(validateLockReason)));",
        str(output / "lockReason.js"), json.dumps([value for value, _ in CASES]),
    ], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("index,case", list(enumerate(CASES)))
def test_browser_api_and_authority_agree(index, case, browser_results):
    value, valid = case
    browser = browser_results[index]
    assert browser["valid"] is valid
    assert browser["normalized"] == " ".join(value.split())
    assert browser["length"] == len(browser["normalized"])
    for model in (LockReleaseRequest, LockReleaseAnswer):
        payload = {"request_id": "apsreq_reason_validation", "reason": value}
        if model is LockReleaseAnswer:
            payload["decision"] = "refuse"
        if valid:
            assert model(**payload).reason == _reason(value) == browser["normalized"]
        else:
            with pytest.raises(ValidationError):
                model(**payload)
            with pytest.raises(LockAuthorityError):
                _reason(value)


def test_short_answer_explains_how_to_enable_actions(browser_results):
    agreed = browser_results[1]
    assert "6/8" in agreed["hint"]
    assert "add at least 2 more" in agreed["hint"]
    assert "Repeated spaces count as one" in agreed["hint"]


@pytest.mark.parametrize("reason", ["", "OK", "Agreed", " \n "])
def test_grant_comment_is_optional_and_may_be_short(reason):
    result = LockReleaseAnswer(request_id="apsreq_optional_comment", decision="grant", reason=reason)
    assert result.reason == " ".join(reason.split())
    assert _reason(reason, optional=True) == result.reason


def test_grant_comment_can_be_omitted():
    assert LockReleaseAnswer(request_id="apsreq_optional_comment", decision="grant").reason == ""


def test_empty_and_short_browser_comments_allow_grant(browser_results):
    assert browser_results[0]["commentValid"] is True
    assert browser_results[1]["commentValid"] is True
    assert browser_results[10]["commentValid"] is False
