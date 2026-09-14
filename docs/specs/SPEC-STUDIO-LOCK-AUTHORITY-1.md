# SPEC-STUDIO-LOCK-AUTHORITY-1 -- Who may lock the judge, and how it is released

> **apatch artifact:** `spec:SPEC-STUDIO-LOCK-AUTHORITY-1`
> **Anchors:** RFP-020
> **Builds on:** RFP-012 §2, SPEC-STUDIO-SDD-LIFECYCLE-1 R12 and R13, RFP-019 endpoint identity
> **Boundary:** connected work consumes signed named principals. This SPEC connects
> them to the local two-party lock; it does not create accounts or memberships.

## R0 RFP traceability gate (meta)

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| LOCK-1 | R1 | covered |
| LOCK-2 | R2 | covered |
| LOCK-3 | R3 | covered |
| LOCK-4 | R4 | covered |
| LOCK-5 | R5 | covered |
| LOCK-6 | R6 | covered |
| LOCK-7 | R7 | covered |
| LOCK-8 | R8 | covered |
| LOCK-9 | R9 | covered |
| LOCK-10 | R10 | covered |
| LOCK-11 | R11 | covered |

(verify: python3 -m pytest tests/lock_authority/test_lock_traceability.py -q)

## R1 LOCK-1 -- The approver is never a name the caller supplied

Approving a locked judge records an identity the product resolved for itself. A caller
supplied name is refused, including the literal the interface used to send. A workspace
that can name nobody cannot approve at all, because a lock signed by a placeholder reads as
evidence while proving nothing.

(verify: python3 -m pytest tests/lock_authority/test_approver_identity.py -q)

## R2 LOCK-2 -- In OSS the approver is this machine, and the record says so

OSS resolves the approver from the configured local machine identity. The record names
the machine and states whether the name is self-asserted or certified, so nobody later
reads it as a human decision. The approval instant precedes the first source change.

(verify: python3 -m pytest tests/lock_authority/test_solo_lock.py -q)

## R3 LOCK-3 -- Connected work carries both sides

A connected lock records the party who set the task and the party who took it,
both resolved from signed principals. It is established before any source change.
A lock naming only one side, or an unverifiable side, is refused.

(verify: python3 -m pytest tests/lock_authority/test_team_lock.py -q)

## R4 LOCK-4 -- A release is asked for, not taken

Releasing starts as a request that names the side asking and carries their reason. Until
the other side answers, the lock stands and the workspace still refuses work outside it.

(verify: python3 -m pytest tests/lock_authority/test_release_request.py -q)

## R5 LOCK-5 -- A refusal is recorded as fully as a consent

An answer is a consent or a refusal, both carry a reason, and both are kept. A refused
release stays readable afterwards, so a request that was made and denied cannot be mistaken
for a request that was never made.

(verify: python3 -m pytest tests/lock_authority/test_release_answer.py -q)

## R6 LOCK-6 -- In connected work nobody releases alone

The side that answers is the side that did not ask. The party who set the task cannot
release their own lock, and neither can the party who took it. An answer from the asking
side, or from a third party who is not on the lock, is refused.

(verify: python3 -m pytest tests/lock_authority/test_team_release.py -q)

## R7 LOCK-7 -- In OSS a release is honest about being one-sided

OSS has one person, so consent from a second side is impossible and is not simulated. The
release is recorded with its reason and marked as one-sided, and it is distinguishable from
a two-party release rather than borrowing its appearance.

(verify: python3 -m pytest tests/lock_authority/test_solo_release.py -q)

## R8 LOCK-8 -- A release invalidates only what it touches

A granted release goes through the existing amendment path in APatch. Requirements whose
judges change become invalid and must be proven again; every other accepted requirement
stays accepted.

(verify: python3 -m pytest tests/lock_authority/test_release_invalidation.py -q)

## R9 LOCK-9 -- A lock that vanished is broken, not absent

Files can be deleted, and this SPEC does not pretend otherwise. A workspace whose lock is
gone while its release record shows no granted release reports a broken lock, naming what
is missing. It does not report an unlocked workspace, because that is the reading an
attacker and a tired operator would both prefer.

Lock and journal paths reject linked ancestry and linked file entries before
writing. Unsafe state is an explicit storage error, never an unlocked workspace.
The journal retains legitimate lock and release exchanges across process restart.

(verify: python3 -m pytest tests/lock_authority/test_broken_lock.py tests/lock_authority/test_lock_state_containment.py -q)

## R10 LOCK-10 -- The whole exchange is visible where the work is

The requirement screen shows who locked it and when, whether a release was asked for, by
which side, with what reason, and how the other side answered. Nothing in this exchange is
reachable only through the API.

(verify: sh -lc "python3 -m pytest tests/lock_authority/test_lock_view.py -q && npm --prefix frontend run build")

## R11 LOCK-11 -- A team workspace never approves with one name

Approving in the team edition records the lock the team edition requires, or it
records nothing. It never falls back to a lock naming this machine, because a
one-sided lock in a workspace whose whole rule is two sides reads as an
agreement that was never made. Where the second side cannot be named the
approval is refused, the refusal says which side is missing, and no lock and no
frozen contract are left behind.

When connected work is configured, Studio consumes two verified principals bound to
the exact reviewed preparation fingerprint. No browser-supplied principal or scope is
authoritative. Preparation, judge or source drift invalidates the offer. The local
LockAuthority record binds both parties to the frozen contract and envelope. An
interrupted persistence operation is visibly incomplete and cannot dispatch work;
retries do not duplicate consents or release exchanges, and concurrent takers cannot
replace the winner.

The requirement view exposes the lock and release controls permitted by the signed
assignment. Release still needs the other recorded side and retains refusals. A
released, broken or incomplete binding cannot start or retry requirement work. Solo
and unconfigured work retain their local behavior.

(verify: python3 -m pytest tests/lock_authority -q)

## Non-goals

Signing a human approval so that local access cannot forge it. This SPEC makes an approval
attributable and releasable, not unforgeable.

Producing Cowork principals. The requirements consume a verified principal and add no
way to authenticate a person.
