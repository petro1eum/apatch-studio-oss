"""Who may lock a judge, and how a lock is released.

Approving a locked judge is the one moment where a person, or at minimum a
named machine, takes responsibility for a boundary that an agent will then be
held to. Until now the interface sent the same literal name for every approval,
so the record said a decision had been taken without saying by whom.

The rule here is narrow and absolute: the party recorded as acting is resolved
by this module, never accepted from the caller. A workspace that can name
nobody cannot approve at all. A lock signed by a placeholder is worse than an
absent lock, because it reads as evidence.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from apatch_studio.endpoint_enrollment import stored_identity
from apatch_studio.state_io import StateDirectory, canonical_directory, check_target, read_json

PARTY_SCHEMA = "apatch.studio.lock-party.v1"
LOCK_SCHEMA = "apatch.studio.lock.v1"
RELEASE_SCHEMA = "apatch.studio.lock-release.v1"
VIEW_SCHEMA = "apatch.studio.lock-view.v1"

# A reason short enough to be a shrug is not a reason. The floor is low enough
# not to be bureaucracy and high enough that "ok" does not pass for one.
MIN_REASON = 8
MAX_REASON = 500

_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# The literal the interface used to send for every approval, whoever pressed
# the button, plus the shapes a well-meaning caller reaches for next. Refused
# by name so that putting one back cannot pass unnoticed.
PLACEHOLDER_NAMES = frozenset(
    {"owner", "owner:local", "local", "local owner", "user", "unknown", "anonymous"}
)


class LockAuthorityError(PermissionError):
    """Nobody this workspace can name is available to act."""


def _instant(clock: Callable[[], datetime] | None = None) -> str:
    moment = clock() if clock else datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _reference(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_REF.fullmatch(text):
        raise LockAuthorityError(f"{label} is not a plain reference")
    return text


def _reason(value: Any) -> str:
    """Why this is being asked, in words somebody else can weigh."""

    text = " ".join(str(value or "").split())
    if not MIN_REASON <= len(text) <= MAX_REASON:
        raise LockAuthorityError(
            f"a reason of {MIN_REASON} to {MAX_REASON} characters is required; "
            "the other side has to be able to weigh it"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise LockAuthorityError("a reason must be plain text")
    return text


def _same_party(left: Any, right: Any) -> bool:
    if not (isinstance(left, dict) and isinstance(right, dict)):
        return False
    if left.get("kind") != right.get("kind"):
        return False
    if left.get("kind") == "person":
        return left.get("membership_id") == right.get("membership_id")
    return left.get("id") == right.get("id")


def approver_for(
    state_root: str | os.PathLike[str], *, principal: Any = None
) -> dict[str, Any]:
    """The party this workspace may record as approving.

    Connected work passes a verified person. Solo work passes nobody and gets the
    configured machine. Neither is read from the request, because a caller that can choose
    the name on a record can choose to be someone else.
    """

    if principal is not None:
        return _person(principal)
    machine = stored_identity(state_root)
    if machine is None:
        raise LockAuthorityError(
            "This machine has no enrolled identity, so nothing here can be recorded "
            "as approving. Enrol it first, then approve."
        )
    name = str(machine.get("machine_name") or "")
    if not name or name.strip().lower() in PLACEHOLDER_NAMES:
        raise LockAuthorityError(
            "The enrolled identity does not name this machine, so an approval "
            "recorded against it would say nothing."
        )
    # A machine that named itself is a usable approver and evidence to nobody
    # outside this workspace. The record carries which it was, because a reader
    # should not have to know how the workspace was set up to know what the
    # approval is worth.
    return {
        "schema": PARTY_SCHEMA,
        "kind": "machine",
        "id": name,
        "is_person": False,
        "certified": machine.get("certified") is True,
    }


def _person(principal: Any) -> dict[str, Any]:
    """A verified connected person. A bare name is not one, however plausible."""

    subject = getattr(principal, "subject", None)
    membership = getattr(principal, "membership_id", None)
    tenant = getattr(principal, "tenant_id", None)
    if not all(isinstance(item, str) and item for item in (subject, membership, tenant)):
        raise LockAuthorityError(
            "A signed-in person is required. A name on its own is not a person, "
            "and recording it would only look like one."
        )
    if subject.strip().lower() in PLACEHOLDER_NAMES:
        raise LockAuthorityError(
            f"{subject!r} is a placeholder, not somebody who can be held to a decision."
        )
    return {
        "schema": PARTY_SCHEMA,
        "kind": "person",
        "id": subject,
        "membership_id": membership,
        "tenant_id": tenant,
        "is_person": True,
        "certified": True,
    }


class LockAuthority:
    """The locks this workspace holds, and who is behind each one."""

    def __init__(
        self,
        state_root: str | os.PathLike[str],
        *,
        identity_root: str | os.PathLike[str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # Locks belong to a workspace; the identity behind them belongs to the
        # machine, and enrolling writes it to the user's own state location.
        # Reading it from the workspace tells an enrolled machine that it can
        # name nobody, which is the opposite of what enrolling it was for.
        selected_root = Path(state_root).expanduser().absolute()
        # The caller may select a workspace alias; its fixed state-directory
        # child must remain unresolved so a planted .apatch link is rejected.
        self.root = canonical_directory(selected_root.parent) / selected_root.name
        self.identity_root = (
            Path(identity_root).expanduser().resolve()
            if identity_root is not None
            else self.root
        )
        self.clock = clock

    def _path(self, spec_id: str, requirement_id: str) -> Path:
        return (
            self.root
            / "locks"
            / _reference(spec_id, "spec id")
            / f"{_reference(requirement_id, 'requirement id')}.json"
        )

    def read(self, spec_id: str, requirement_id: str) -> dict[str, Any] | None:
        path = self._path(spec_id, requirement_id)
        try:
            record = read_json(path)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise LockAuthorityError("the local lock store is unavailable") from exc
        if not isinstance(record, dict) or record.get("schema") != LOCK_SCHEMA:
            return None
        return record

    def _journal_path(self) -> Path:
        return self.root / "locks" / "journal.jsonl"

    def _write(self, record: dict[str, Any]) -> dict[str, Any]:
        path = self._path(record["spec_id"], record["requirement_id"])
        from apatch_studio.sdd_workflow import _atomic_json

        # The journal is what survives someone deleting the lock. Without it a
        # removed lock and a lock that never existed look identical, and that is
        # the reading both an attacker and a tired operator would prefer.
        release = record.get("release")
        journal = self._journal_path()
        try:
            check_target(journal)
            _atomic_json(path, record)
            with StateDirectory(journal.parent, create=True) as directory:
                directory.append_bytes(journal.name, (json.dumps(
                    {
                        "at": _instant(self.clock),
                        "spec_id": record["spec_id"],
                        "requirement_id": record["requirement_id"],
                        "release_state": (release or {}).get("state"),
                    },
                    ensure_ascii=False,
                ) + "\n").encode("utf-8"))
        except OSError as exc:
            raise LockAuthorityError("the local lock store is unavailable") from exc
        return dict(record)

    def _journal_for(self, spec_id: str, requirement_id: str) -> list[dict[str, Any]]:
        journal = self._journal_path()
        try:
            with StateDirectory(journal.parent) as directory:
                content = directory.read_bytes(journal.name).decode("utf-8")
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError) as exc:
            raise LockAuthorityError("the local lock journal is unavailable") from exc
        entries: list[dict[str, Any]] = []
        for line in content.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(entry, dict)
                and entry.get("spec_id") == spec_id
                and entry.get("requirement_id") == requirement_id
            ):
                entries.append(entry)
        return entries

    def status(self, spec_id: str, requirement_id: str) -> dict[str, Any]:
        """What this requirement's boundary is doing, in words a person can act on.

        A lock whose file has gone while nothing granted its release is reported
        as broken rather than absent. Files can be deleted, and this does not
        pretend otherwise; it refuses to read a deletion as permission.
        """

        record = self.read(spec_id, requirement_id)
        history = self._journal_for(spec_id, requirement_id)
        if record is None:
            if not history:
                return {
                    "state": "unlocked",
                    "headline": "This requirement has no agreed boundary yet",
                    "parties": [],
                }
            if history[-1].get("release_state") == "granted":
                return {
                    "state": "released",
                    "headline": "The boundary was lifted by agreement",
                    "parties": [],
                }
            return {
                "state": "broken",
                "headline": "This lock is missing and nothing released it",
                "explanation": (
                    "A boundary was agreed here and its record is gone, with no "
                    "granted release to explain the absence. Treat this workspace "
                    "as unsafe to work in until somebody accounts for it."
                ),
                "missing": str(
                    self._path(spec_id, requirement_id).relative_to(self.root)
                ),
                "parties": [],
            }
        release = record.get("release")
        state = (release or {}).get("state")
        if state == "awaiting_answer":
            headline = "A release was asked for and is waiting for an answer"
            reported = "awaiting_answer"
        elif state == "granted":
            headline = "The boundary was lifted by agreement"
            reported = "released"
        else:
            headline = "This boundary is agreed and holds"
            reported = "locked"
        return {
            "state": reported,
            "headline": headline,
            "parties": list(record["parties"]),
            "locked_at": record["locked_at"],
            "approved_by_a_person": record["approved_by_a_person"],
        }

    def lock_solo(
        self,
        spec_id: str,
        requirement_id: str,
        *,
        source_changed_at: str | None = None,
    ) -> dict[str, Any]:
        """OSS: this machine approves the boundary, before any source work.

        There is one user, so there is no second side and none is invented. The
        guarantee is order rather than headcount, and the record says plainly
        that a machine approved so nobody later reads it as a person's decision.
        """

        if source_changed_at:
            raise LockAuthorityError(
                "Source work on this requirement already began, so approving its "
                "boundary now would approve what was already written."
            )
        if self.read(spec_id, requirement_id) is not None:
            raise LockAuthorityError(
                "This requirement is already locked. Ask for a release instead."
            )
        approver = approver_for(self.identity_root)
        return self._write(
            {
                "schema": LOCK_SCHEMA,
                "spec_id": _reference(spec_id, "spec id"),
                "requirement_id": _reference(requirement_id, "requirement id"),
                "edition": "oss",
                "parties": [{"role": "approver", **approver}],
                "approved_by_a_person": False,
                "locked_at": _instant(self.clock),
                "release": None,
            }
        )

    @staticmethod
    def _release_retry(record, request_id, person, reason, decision=None):
        if request_id is None:
            return False
        _reference(request_id, "request id")
        release = record.get("release") or {}
        for exchange in [release, *release.get("history", [])]:
            item = exchange if decision is None else (exchange.get("answer") or {})
            if item.get("request_id") != request_id:
                continue
            actor = item.get("asked_by") if decision is None else item.get("by")
            if (not _same_party(person, actor or {}) or item.get("reason") != _reason(reason)
                    or (decision is not None and item.get("decision") != decision)):
                raise LockAuthorityError("A release request identifier cannot be reused with different details.")
            return True
        return False

    def request_release(
        self,
        spec_id: str,
        requirement_id: str,
        *,
        asked_by: Any = None,
        reason: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Ask for the lock to be lifted. Asking is not lifting.

        Until the other side answers, the boundary stands exactly as it did.
        A request that quietly took effect would make the second side
        decorative, which is the failure this whole mechanism exists to avoid.
        """

        record = self.read(spec_id, requirement_id)
        if record is None:
            raise LockAuthorityError("there is no lock here to release")
        asker = approver_for(self.identity_root, principal=asked_by)
        if self._release_retry(record, request_id, asker, reason):
            return dict(record)
        release = record.get("release")
        if isinstance(release, dict) and release.get("state") == "awaiting_answer":
            raise LockAuthorityError(
                "a release is already waiting for an answer; answer that one first"
            )
        if not any(_same_party(asker, party) for party in record["parties"]):
            raise LockAuthorityError(
                "only a side of this lock may ask for it to be lifted"
            )
        history = list((release or {}).get("history") or [])
        if isinstance(release, dict) and release.get("state") in ("granted", "refused"):
            history.append({k: v for k, v in release.items() if k != "history"})
        # A single-party lock has nobody to consent, and saying so on the record
        # is the whole point: a one-sided release must not later be read as an
        # agreement between two people who never spoke.
        two_sided = len(record["parties"]) > 1
        record["release"] = {
            "schema": RELEASE_SCHEMA,
            **({"request_id": request_id} if request_id is not None else {}),
            "state": "awaiting_answer",
            "asked_by": asker,
            "asked_at": _instant(self.clock),
            "reason": _reason(reason),
            "answer": None,
            "two_sided": two_sided,
            "one_sided": not two_sided,
            "history": history,
        }
        return self._write(record)

    def answer_release(
        self,
        spec_id: str,
        requirement_id: str,
        *,
        answered_by: Any = None,
        decision: str,
        reason: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Consent or refuse, and say why either way.

        A refusal is kept as fully as a consent. If refusals were dropped, a
        request that was made and denied would be indistinguishable from one
        nobody ever made, and the argument would have to be had again with no
        record of how it went last time.
        """

        if decision not in ("grant", "refuse"):
            raise LockAuthorityError("an answer is either grant or refuse")
        record = self.read(spec_id, requirement_id)
        if record is None:
            raise LockAuthorityError("there is no lock here to answer about")
        answerer = approver_for(self.identity_root, principal=answered_by)
        if self._release_retry(record, request_id, answerer, reason, decision):
            return dict(record)
        release = record.get("release")
        if not isinstance(release, dict) or release.get("state") != "awaiting_answer":
            raise LockAuthorityError("nothing here is waiting for an answer")
        if not any(_same_party(answerer, party) for party in record["parties"]):
            raise LockAuthorityError(
                "only a side of this lock may answer a release request"
            )
        if len(record["parties"]) > 1 and _same_party(answerer, release["asked_by"]):
            raise LockAuthorityError(
                "the side that asked cannot also answer. Two sides agreed this "
                "boundary, so one side alone cannot undo it, including the side "
                "that set it."
            )
        release["state"] = "granted" if decision == "grant" else "refused"
        release["answer"] = {
            **({"request_id": request_id} if request_id is not None else {}),
            "by": answerer,
            "decision": decision,
            "reason": _reason(reason),
            "at": _instant(self.clock),
        }
        record["release"] = release
        return self._write(record)

    def view(self, spec_id: str, requirement_id: str) -> dict[str, Any]:
        """The whole exchange in words, for the screen where the work happens.

        Everything a person needs to judge the boundary should be readable
        beside the requirement: who agreed it, whether anyone asked to lift it,
        on what grounds, and what the other side said. An exchange only visible
        through the API is an exchange most people will never see.
        """

        status = self.status(spec_id, requirement_id)
        exchanges = []
        for item in self.exchanges(spec_id, requirement_id):
            answer = item.get("answer") or {}
            exchanges.append(
                {
                    "asked_by": (item.get("asked_by") or {}).get("id"),
                    "asked_at": item.get("asked_at"),
                    "reason": item.get("reason"),
                    "one_sided": bool(item.get("one_sided")),
                    "answered_by": answer.get("by", {}).get("id"),
                    "answered_at": answer.get("at"),
                    "answer": answer.get("decision"),
                    "answer_reason": answer.get("reason"),
                    "outcome": item.get("state"),
                }
            )
        return {
            "schema": VIEW_SCHEMA,
            "spec_id": spec_id,
            "requirement_id": requirement_id,
            "state": status["state"],
            "headline": status["headline"],
            "explanation": status.get("explanation"),
            "agreed_by": [
                {
                    "role": party.get("role"),
                    "name": party.get("id"),
                    "is_person": bool(party.get("is_person")),
                    "self_asserted": party.get("certified") is not True,
                }
                for party in status.get("parties") or []
            ],
            "agreed_at": status.get("locked_at"),
            "approved_by_a_person": status.get("approved_by_a_person", False),
            "exchanges": exchanges,
        }

    def amendment_for_release(
        self,
        spec_id: str,
        requirement_id: str,
        *,
        contract: Any,
        changed_acceptance_ids: Any,
        affected_requirements: Any,
        all_requirements: Any,
    ) -> dict[str, Any]:
        """Turn a granted release into an amendment that touches only what moved.

        A release is not a reset. Work already proven against judges nobody
        changed stays proven, or every small correction would cost the whole
        history and people would stop asking for corrections.
        """

        from apatch.sdd_integrity import amend_contract

        record = self.read(spec_id, requirement_id)
        if record is None:
            raise LockAuthorityError("there is no lock here to amend")
        release = record.get("release")
        if not isinstance(release, dict) or release.get("state") != "granted":
            raise LockAuthorityError(
                "only a granted release amends the contract; asking is not consent"
            )
        affected = [str(item) for item in (affected_requirements or [])]
        if not affected:
            raise LockAuthorityError(
                "a release that invalidates nothing does not need an amendment"
            )
        answer = release["answer"]
        return amend_contract(
            contract,
            reason=answer["reason"],
            authority={"actor_id": answer["by"]["id"], "role": "authority"},
            changed_acceptance_ids=[str(item) for item in changed_acceptance_ids or []],
            affected_requirements=affected,
            all_requirements=[str(item) for item in all_requirements or []],
        )

    def exchanges(self, spec_id: str, requirement_id: str) -> list[dict[str, Any]]:
        """Every release ever asked for here, answered or still waiting."""

        record = self.read(spec_id, requirement_id)
        if record is None:
            return []
        release = record.get("release")
        if not isinstance(release, dict):
            return []
        past = list(release.get("history") or [])
        return past + [{k: v for k, v in release.items() if k != "history"}]

    def is_locked(self, spec_id: str, requirement_id: str) -> bool:
        """Whether work outside this boundary is still refused."""

        record = self.read(spec_id, requirement_id)
        if record is None:
            return False
        release = record.get("release")
        if not isinstance(release, dict):
            return True
        return release.get("state") != "granted"

    def lock_team(
        self,
        spec_id: str,
        requirement_id: str,
        *,
        set_by: Any,
        taken_by: Any,
        source_changed_at: str | None = None,
        approval_binding: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Connected work is locked when accepted and carries both sides.

        The manager who set the work and the person who took it are both on the
        record, because a boundary agreed by one side is not an agreement. Both
        are resolved from the tenant's own principals; a name is not a party.
        """

        if source_changed_at:
            raise LockAuthorityError(
                "Source work on this requirement already began, so agreeing its "
                "boundary now would agree to what was already written."
            )
        if self.read(spec_id, requirement_id) is not None:
            raise LockAuthorityError(
                "This requirement is already locked. Ask for a release instead."
            )
        if approval_binding is not None:
            basic_keys = {"offer_id", "snapshot", "contract_hash", "envelope_hash"}
            change_keys = {
                "change_envelope_id", "change_envelope_hash", "policy_hash"
            }
            if (
                set(approval_binding) not in (basic_keys, basic_keys | change_keys)
                or not re.fullmatch(
                    r"apsofr_[0-9a-f]{32}", approval_binding.get("offer_id", "")
                )
                or any(
                    not re.fullmatch(
                        r"sha256:[0-9a-f]{64}", approval_binding.get(key, "")
                    )
                    for key in (
                        "snapshot", "contract_hash", "envelope_hash",
                        *(
                            ("change_envelope_hash", "policy_hash")
                            if change_keys.issubset(approval_binding)
                            else ()
                        ),
                    )
                )
                or (
                    change_keys.issubset(approval_binding)
                    and not re.fullmatch(
                        r"apschg_[0-9a-f]{32}",
                        approval_binding.get("change_envelope_id", ""),
                    )
                )
            ):
                raise LockAuthorityError(
                    "A team agreement must bind exact offer, contract, "
                    "envelope and optional connected-change hashes."
                )
        setter = approver_for(self.identity_root, principal=set_by)
        taker = approver_for(self.identity_root, principal=taken_by)
        if not (setter["is_person"] and taker["is_person"]):
            raise LockAuthorityError(
                "Both sides of a team lock are people; a machine cannot take a task "
                "from a manager on its own behalf."
            )
        if setter["tenant_id"] != taker["tenant_id"]:
            raise LockAuthorityError(
                "The two sides belong to different organizations, so neither can "
                "hold the other to this boundary."
            )
        if setter["membership_id"] == taker["membership_id"]:
            raise LockAuthorityError(
                "One person cannot be both sides of a team lock. Use the single-user "
                "edition, which records honestly that one side agreed."
            )
        return self._write(
            {
                "schema": LOCK_SCHEMA,
                "spec_id": _reference(spec_id, "spec id"),
                "requirement_id": _reference(requirement_id, "requirement id"),
                "edition": "cowork",
                **({"approval_binding": dict(approval_binding)} if approval_binding is not None else {}),
                "parties": [
                    {"role": "set_by", **setter},
                    {"role": "taken_by", **taker},
                ],
                "approved_by_a_person": True,
                "locked_at": _instant(self.clock),
                "release": None,
            }
        )
