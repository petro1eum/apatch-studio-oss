# RFP-021 -- Naming a machine when there is no organization to name it

> **Status:** Accepted by the owner on 2026-09-04, and built. Every promise
> below is answered by SPEC-STUDIO-LOCAL-IDENTITY-1, all five requirements proven.
> **Owner:** APatch Studio
> **Date:** 2026-09-04
> **Builds on:** RFP-019 (machine identity), RFP-020 §2.1 and §4 (who may approve in OSS)
> **Evidence source:** with RFP-020 in place, this workspace can approve nothing,
> because the only identity it accepts is one an organization has issued and no
> organization is running yet

## 1. What is actually true today

RFP-020 made the approver a name the product resolves rather than a name the
caller sends. In the single-user edition it resolves that name from the machine
identity enrolled under RFP-019.

Enrolling under RFP-019 means contacting a TrustChain Platform with an
invitation. That platform is not running. This machine therefore has no name at
all, and the two places a name could come from agree:

- Studio's enrolment record is absent.
- The runtime's trust anchor reports `level: ephemeral`, `agent_id: null`, a
  self-signed development key.

So every approval in this workspace is refused, and with it every frozen
contract and every profile lock that would hold one. The rule is correct and
the product is unusable, which means the rule is incomplete rather than wrong.

## 2. Decision

A machine may name itself, and the record says that is what happened.

Naming is not enrolling. An enrolled machine carries a certificate an
organization issued, and anyone holding that certificate can confirm which
machine produced a record. A self-named machine carries a name it chose from
itself, and confirms nothing to anybody outside it. Both are usable as an
approver; only one is evidence to a stranger.

The whole value of the distinction is that it is never blurred. A self-asserted
name that is displayed, recorded or reported as a certified one is worse than
no name at all, because it invites a reader to believe something nobody
checked.

The name is still not something a caller supplies. It is resolved from the
machine, in one place, once, and the identity report stops having two states
when the truth has three.

## 3. Out of scope

Making a self-named machine trustworthy to anyone else. Nothing here issues,
signs or verifies anything. The name is attributable within this workspace and
worthless outside it, and the product must keep saying so.

Replacing enrolment. When an organization is available, enrolment is still the
way to get an identity a stranger can check, and a certified identity always
outranks a self-asserted one.

## 4. Acceptance

| Id | Requirement | Level |
|---|---|---|
| NAME-1 | This machine can be given a name without any organization, network call or invitation, and the name is resolved from the machine rather than supplied by whoever asked | MUST |
| NAME-2 | A self-asserted identity is recorded as self-asserted, and is never reported, displayed or projected as one an organization certified | MUST |
| NAME-3 | A certified identity always outranks a self-asserted one, and naming this machine locally never overwrites or downgrades an enrolment it already has | MUST |
| NAME-4 | A lock approved by a self-named machine says on the record and on the screen that nobody outside this machine vouched for the name | MUST |
