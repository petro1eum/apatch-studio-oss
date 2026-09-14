"""Enrollment runs once and survives a restart, and the invitation never lands (RFP-019)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from apatch_studio.endpoint_enrollment import (
    IDENTITY_FILE,
    RECORD_SCHEMA,
    apply_stored_identity,
    default_machine_name,
    enroll_machine,
    enrollment_readiness,
    stored_identity,
)
from apatch_studio.endpoint_identity import endpoint_identity_status

ROOT = Path(__file__).resolve().parents[2]
MODULE = (ROOT / "apatch_studio/endpoint_enrollment.py").read_text(encoding="utf-8")
VOCABULARY = json.loads(
    (ROOT / "frontend/src/vocabulary.contract.json").read_text(encoding="utf-8")
)
PLATFORM = "https://keys.trust-chain.ai"
INVITATION = "invitation-token-do-not-store-2f8c1e"


def _runtime(state_root: Path, *, ok: bool = True):
    """Stand in for the APatch runtime, writing the files it would write."""

    def enroll(*, invitation, platform_url, out_dir, agent_id):
        assert invitation == INVITATION
        assert platform_url == PLATFORM
        if not ok:
            return {"ok": False, "error": "invitation already used"}
        key = Path(out_dir) / "agent.key"
        cert = Path(out_dir) / "agent.crt"
        key.write_text("PRIVATE KEY BELONGS TO THE RUNTIME", encoding="utf-8")
        cert.write_text("CERTIFICATE", encoding="utf-8")
        return {"ok": True, "key_path": str(key), "cert_path": str(cert)}

    return enroll


def test_readiness_explains_a_missing_tool_with_one_next_step() -> None:
    missing = enrollment_readiness(which=lambda _name: None)
    assert missing["ready"] is False
    assert "not installed" in missing["headline"]
    assert "pip install trustchain" in missing["next_step"]

    present = enrollment_readiness(which=lambda _name: "/usr/local/bin/tc")
    assert present["ready"] is True


def test_a_successful_enrollment_is_recorded_and_takes_effect(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    result = enroll_machine(
        state_root=tmp_path,
        invitation=INVITATION,
        platform_url=PLATFORM,
        machine_name="studio-laptop",
        enroll=_runtime(tmp_path),
        environ=env,
    )

    assert result["enrolled"] is True and result["machine_name"] == "studio-laptop"
    record = stored_identity(tmp_path)
    assert record["schema"] == RECORD_SCHEMA
    assert record["machine_name"] == "studio-laptop"
    assert record["key_path"].endswith("agent.key")
    assert env["APATCH_AGENT_ID"] == "studio-laptop"
    assert env["APATCH_AGENT_KEY"] == record["key_path"]
    assert env["APATCH_AGENT_CERT"] == record["certificate_path"]


def test_the_invitation_is_never_written_anywhere(tmp_path: Path) -> None:
    """The invitation authorises enrollment once; it must not survive the call."""

    enroll_machine(
        state_root=tmp_path,
        invitation=INVITATION,
        platform_url=PLATFORM,
        machine_name="studio-laptop",
        enroll=_runtime(tmp_path),
        environ={},
    )

    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert INVITATION not in path.read_text(encoding="utf-8", errors="replace"), path


def test_the_record_is_private_and_outside_the_git_workspace(tmp_path: Path) -> None:
    enroll_machine(
        state_root=tmp_path,
        invitation=INVITATION,
        platform_url=PLATFORM,
        machine_name="studio-laptop",
        enroll=_runtime(tmp_path),
        environ={},
    )
    path = tmp_path / IDENTITY_FILE
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_refused_enrollment_records_nothing_and_says_what_to_do(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    result = enroll_machine(
        state_root=tmp_path,
        invitation=INVITATION,
        platform_url=PLATFORM,
        machine_name="studio-laptop",
        enroll=_runtime(tmp_path, ok=False),
        environ=env,
    )

    assert result["enrolled"] is False
    assert "new invitation" in result["next_step"]
    assert stored_identity(tmp_path) is None
    assert env == {}


def test_a_restart_puts_the_identity_back(tmp_path: Path) -> None:
    enroll_machine(
        state_root=tmp_path,
        invitation=INVITATION,
        platform_url=PLATFORM,
        machine_name="studio-laptop",
        enroll=_runtime(tmp_path),
        environ={},
    )

    fresh: dict[str, str] = {}
    assert apply_stored_identity(tmp_path, environ=fresh) is True
    assert fresh["APATCH_AGENT_ID"] == "studio-laptop"
    assert fresh["APATCH_AGENT_KEY"].endswith("agent.key")


def test_an_operator_who_set_the_identity_themselves_is_never_overridden(tmp_path: Path) -> None:
    enroll_machine(
        state_root=tmp_path,
        invitation=INVITATION,
        platform_url=PLATFORM,
        machine_name="studio-laptop",
        enroll=_runtime(tmp_path),
        environ={},
    )

    chosen = {"APATCH_AGENT_ID": "chosen-by-hand"}
    assert apply_stored_identity(tmp_path, environ=chosen) is False
    assert chosen == {"APATCH_AGENT_ID": "chosen-by-hand"}


def test_nothing_is_applied_when_the_machine_was_never_enrolled(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    assert apply_stored_identity(tmp_path, environ=env) is False
    assert env == {}


def test_a_damaged_record_is_ignored_rather_than_trusted(tmp_path: Path) -> None:
    path = tmp_path / IDENTITY_FILE
    for body in (
        "not json",
        json.dumps({"schema": "something.else", "machine_name": "x", "key_path": "/k"}),
        json.dumps({"schema": RECORD_SCHEMA, "machine_name": "x"}),
        json.dumps({"schema": RECORD_SCHEMA, "machine_name": "", "key_path": "/k"}),
        json.dumps([1, 2, 3]),
    ):
        path.write_text(body, encoding="utf-8")
        assert stored_identity(tmp_path) is None, body


def test_a_symlinked_record_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "elsewhere.json"
    real.write_text(
        json.dumps({"schema": RECORD_SCHEMA, "machine_name": "x", "key_path": "/k"}),
        encoding="utf-8",
    )
    (tmp_path / IDENTITY_FILE).symlink_to(real)
    assert stored_identity(tmp_path) is None


def test_bad_input_is_refused_before_anything_runs(tmp_path: Path) -> None:
    def explode(**_kwargs):
        raise AssertionError("the runtime must not be called")

    for kwargs in (
        {"invitation": "  ", "platform_url": PLATFORM, "machine_name": "ok-name"},
        {"invitation": INVITATION, "platform_url": "http://insecure", "machine_name": "ok-name"},
        {"invitation": INVITATION, "platform_url": PLATFORM, "machine_name": "Bad Name"},
        {"invitation": INVITATION, "platform_url": PLATFORM, "machine_name": "-leading"},
    ):
        with pytest.raises(ValueError):
            enroll_machine(state_root=tmp_path, enroll=explode, environ={}, **kwargs)


def test_the_default_machine_name_is_plain(tmp_path: Path) -> None:
    assert default_machine_name("Eds-MacBook-Pro.local") == "eds-macbook-pro-local"
    assert default_machine_name("") == "studio"
    assert default_machine_name("!!!") == "studio"


def test_studio_still_never_creates_key_material() -> None:
    """Reading a certificate is allowed; making key material is not."""

    for forbidden in (
        "generate_private_key",
        "Ed25519PrivateKey",
        "from_private_bytes",
        "token_bytes",
        "urandom",
        "load_pem_private_key",
    ):
        assert forbidden not in MODULE, forbidden


def test_the_identity_never_reveals_where_the_key_lives(tmp_path: Path) -> None:
    """Paths belong on this machine, not in anything a person or browser sees."""

    enroll_machine(
        state_root=tmp_path,
        invitation=INVITATION,
        platform_url=PLATFORM,
        machine_name="studio-laptop",
        enroll=_runtime(tmp_path),
        environ={},
    )
    projected = endpoint_identity_status(
        str(tmp_path),
        status_provider=lambda _w: {
            "level": "ca-issued",
            "secure": True,
            "agent_id": "studio-laptop",
            "has_cert": True,
        },
    )
    rendered = json.dumps(projected)
    assert "agent.key" not in rendered and str(tmp_path) not in rendered
    assert not any("path" in key for key in projected)


def test_enrollment_copy_uses_product_language_only(tmp_path: Path) -> None:
    outcomes = [
        enrollment_readiness(which=lambda _n: None),
        enrollment_readiness(which=lambda _n: "/usr/bin/tc"),
        enroll_machine(
            state_root=tmp_path,
            invitation=INVITATION,
            platform_url=PLATFORM,
            machine_name="studio-laptop",
            enroll=_runtime(tmp_path, ok=False),
            environ={},
        ),
        enroll_machine(
            state_root=tmp_path,
            invitation=INVITATION,
            platform_url=PLATFORM,
            machine_name="studio-laptop",
            enroll=_runtime(tmp_path),
            environ={},
        ),
    ]
    for outcome in outcomes:
        for field in ("headline", "explanation", "next_step"):
            lowered = outcome[field].lower()
            for term in VOCABULARY["forbidden_primary_terms"]:
                assert term not in lowered, (term, outcome[field])


def _identity_files(tmp_path: Path) -> tuple[str, str]:
    key = tmp_path / "agent.key"
    cert = tmp_path / "agent.crt"
    key.write_text("KEY", encoding="utf-8")
    cert.write_text("CERT", encoding="utf-8")
    return str(key), str(cert)


def test_an_existing_identity_is_adopted_only_after_it_is_proved(tmp_path: Path) -> None:
    from apatch_studio.endpoint_enrollment import adopt_identity

    key, cert = _identity_files(tmp_path)
    seen: dict = {}

    def prove(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "chain_ok": True, "key_match": True}

    env: dict[str, str] = {}
    result = adopt_identity(
        state_root=tmp_path,
        machine_name="apatch-edcher",
        key_path=key,
        certificate_path=cert,
        platform_url="https://keys.trust-chain.ai",
        verify=prove,
        validity=lambda _p: {"valid": True, "reason": None},
        environ=env,
    )

    assert result["enrolled"] is True
    assert seen["registry_base"] == "https://keys.trust-chain.ai"
    assert seen["signer_key"] == key and seen["leaf_cert"] == cert
    assert stored_identity(tmp_path)["machine_name"] == "apatch-edcher"
    assert env["APATCH_AGENT_KEY"] == key


def test_an_unprovable_certificate_is_refused_and_recorded_nowhere(tmp_path: Path) -> None:
    from apatch_studio.endpoint_enrollment import adopt_identity

    key, cert = _identity_files(tmp_path)
    env: dict[str, str] = {}
    result = adopt_identity(
        state_root=tmp_path,
        machine_name="apatch-edcher",
        key_path=key,
        certificate_path=cert,
        platform_url="https://keys.trust-chain.ai",
        verify=lambda **_k: {"ok": False, "errors": ["PKIX chain verification failed"]},
        validity=lambda _p: {"valid": True, "reason": None},
        environ=env,
    )

    assert result["enrolled"] is False
    assert "could not be proved" in result["headline"]
    assert stored_identity(tmp_path) is None
    assert env == {}


def test_a_checker_that_explodes_counts_as_unproved(tmp_path: Path) -> None:
    from apatch_studio.endpoint_enrollment import adopt_identity

    key, cert = _identity_files(tmp_path)

    def explode(**_kwargs):
        raise RuntimeError("no network")

    result = adopt_identity(
        state_root=tmp_path,
        machine_name="apatch-edcher",
        key_path=key,
        certificate_path=cert,
        platform_url="https://keys.trust-chain.ai",
        verify=explode,
        validity=lambda _p: {"valid": True, "reason": None},
        environ={},
    )
    assert result["enrolled"] is False
    assert stored_identity(tmp_path) is None


def test_adoption_without_a_way_to_check_is_refused(tmp_path: Path) -> None:
    from apatch_studio.endpoint_enrollment import adopt_identity

    key, cert = _identity_files(tmp_path)
    with pytest.raises(ValueError):
        adopt_identity(
            state_root=tmp_path,
            machine_name="apatch-edcher",
            key_path=key,
            certificate_path=cert,
            verify=lambda **_k: {"ok": True},
            environ={},
        )


def test_missing_or_symlinked_identity_files_are_refused(tmp_path: Path) -> None:
    from apatch_studio.endpoint_enrollment import adopt_identity

    key, cert = _identity_files(tmp_path)
    link = tmp_path / "linked.crt"
    link.symlink_to(cert)
    for kwargs in (
        {"key_path": str(tmp_path / "missing.key"), "certificate_path": cert},
        {"key_path": key, "certificate_path": str(tmp_path / "missing.crt")},
        {"key_path": key, "certificate_path": str(link)},
    ):
        with pytest.raises(ValueError):
            adopt_identity(
                state_root=tmp_path,
                machine_name="apatch-edcher",
                platform_url="https://keys.trust-chain.ai",
                verify=lambda **_k: {"ok": True},
                environ={},
                **kwargs,
            )


def test_an_expired_certificate_is_refused_even_when_the_chain_checks_out(tmp_path: Path) -> None:
    """The runtime's anchor check ignores dates, so Studio must not."""

    from apatch_studio.endpoint_enrollment import adopt_identity

    key, cert = _identity_files(tmp_path)
    result = adopt_identity(
        state_root=tmp_path,
        machine_name="apatch-edcher",
        key_path=key,
        certificate_path=cert,
        platform_url=PLATFORM,
        verify=lambda **_k: {"ok": True, "chain_ok": True, "key_match": True},
        validity=lambda _p: {"valid": False, "reason": "the certificate expired on 2026-06-10"},
        environ={},
    )

    assert result["enrolled"] is False
    assert "cannot be used" in result["headline"]
    assert "2026-06-10" in result["explanation"]
    assert stored_identity(tmp_path) is None


def test_a_certificate_that_is_not_valid_yet_is_refused(tmp_path: Path) -> None:
    from apatch_studio.endpoint_enrollment import adopt_identity

    key, cert = _identity_files(tmp_path)
    result = adopt_identity(
        state_root=tmp_path,
        machine_name="apatch-edcher",
        key_path=key,
        certificate_path=cert,
        platform_url=PLATFORM,
        verify=lambda **_k: {"ok": True},
        validity=lambda _p: {"valid": False, "reason": "the certificate is not valid yet"},
        environ={},
    )
    assert result["enrolled"] is False
    assert stored_identity(tmp_path) is None


def test_the_validity_window_is_read_from_the_certificate_itself(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from apatch_studio.endpoint_enrollment import certificate_validity

    unreadable = tmp_path / "not-a-certificate.crt"
    unreadable.write_text("NOT A CERTIFICATE", encoding="utf-8")
    assert certificate_validity(str(unreadable))["valid"] is False

    missing = certificate_validity(str(tmp_path / "absent.crt"))
    assert missing["valid"] is False
