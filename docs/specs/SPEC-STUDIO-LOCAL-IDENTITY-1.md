# SPEC-STUDIO-LOCAL-IDENTITY-1 -- Naming a machine when there is no organization

> **apatch artifact:** `spec:SPEC-STUDIO-LOCAL-IDENTITY-1`
> **Anchors:** RFP-021
> **Builds on:** RFP-019 machine identity, SPEC-STUDIO-LOCK-AUTHORITY-1 R1 and R2
> **Boundary:** Nothing here issues, signs or verifies anything. A self-asserted
> name is attributable inside this workspace and worthless outside it, and every
> requirement below exists to keep the product saying so.
> **Consequence:** naming a machine is what makes approving possible where no
> organization exists, so a workspace can hold a frozen contract and a profile
> lock again without any approval being recorded against a constant.

## R0 RFP traceability gate (meta)

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| NAME-1 | R1 | covered |
| NAME-2 | R2 | covered |
| NAME-3 | R3 | covered |
| NAME-4 | R4 | covered |

(verify: python3 -m pytest tests/local_identity/test_local_identity_traceability.py -q)

## R1 NAME-1 -- This machine can name itself, offline

Naming this machine needs no organization, no invitation and no network call.
The name is resolved from the machine, and a name the caller passes in is
refused exactly as it is on the approval path, because a caller that can choose
the name can choose to be another machine.

(verify: python3 -m pytest tests/local_identity/test_self_naming.py -q)

## R2 NAME-2 -- Self-asserted is never dressed as certified

The record says which of the two it is. The identity report has three states,
not two: certified by an organization, named by this machine, and nothing at
all. A self-asserted identity never reaches a reader wearing the words that
belong to a certified one.

(verify: python3 -m pytest tests/local_identity/test_states_are_distinct.py -q)

## R3 NAME-3 -- A certificate outranks a self-asserted name

Naming this machine locally never overwrites or downgrades an identity an
organization issued. Where both exist the certified one is used, and asking to
name a machine that is already enrolled is refused rather than silently
demoting it.

(verify: python3 -m pytest tests/local_identity/test_certified_outranks.py -q)

## R4 NAME-4 -- A lock says whose word the name is on

A lock approved by a self-named machine records that nobody outside this machine
vouched for the name, and the requirement screen says so beside the approver.
A reader must not have to know how this workspace was set up to know what the
approval is worth.

(verify: sh -lc "python3 -m pytest tests/local_identity/test_lock_says_self_asserted.py -q && npm --prefix frontend run build")

## Non-goals

Making a self-named machine mean anything to anyone else. No key is created, no
certificate is issued and no signature is checked here.

Replacing enrolment. When an organization exists, enrolment remains the only way
to get a name a stranger can verify.
