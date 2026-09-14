# RFP-020 -- Who may lock the judge, and how it is released

> **Status:** Accepted by the owner on 2026-09-04, and built. Every promise below
> is answered by SPEC-STUDIO-LOCK-AUTHORITY-1, all eleven requirements proven.
> **Owner:** APatch Studio
> **Date:** 2026-09-04
> **Builds on:** RFP-012 §2 (solo and team authority models) and §5 (pre-implementation
> verification contract); signed Cowork work proposals; RFP-019 local identity
> **Evidence source:** the approval button in the requirement plan sends a constant name,
> and the product has no way to release a lock once set

## 1. What is actually true today

Three facts, from the code as it stands.

The approval screen exists. A requirement shows **Approve scope & tests**, and afterwards
reads *Approved by ... / Frozen ...*. Behind it, `frontend/src/api.ts` sends:

```
owner_actor_id: "owner:local",
confirmed: true,
```

That name is a literal in the frontend. Every approval in the product carries the same
name, whoever pressed the button.

`SddWorkflowFacade.freeze_requirement` accepts that name as any text between 3 and 128
characters. There is no account, no key and no signature behind it.

There is no release. `amend_contract` in APatch adds an amendment and invalidates the
requirements an amendment touches, but it does not lift the lock. The only way to lift it
is to delete `.apatch/sdd_verification_contract.json` by hand, outside the product.

So the lock records that somebody pressed a button. It does not record who, and it cannot
be released through the product that set it.

## 2. Decision

Solo work and a signed two-party assignment are not the same situation, and the
product must stop pretending they are.

### 2.1 OSS: one person, separation in time

OSS has one user. There is no second party, and inventing one is theatre. The lock is set
by that person, and the honesty comes from order rather than from headcount: the approval
instant precedes the first source change, and the agent doing the work cannot approve its
own amendment. This is already the intent of RFP-012 §2.1 and requirement R12 of the
lifecycle SPEC. What is missing is only that the recorded name is a constant.

OSS records the configured local machine identity as the approver, including whether
that name is self-asserted or certified, so the record says which machine approved and
when instead of saying `owner:local` forever.

Releasing in OSS is the same person, with a written reason, recorded. No counterparty
exists, so the guarantee is the record, not anyone's consent.

### 2.2 Connected work: the one who sets the task and the one who takes it

A connected task names the party who offers work and the party who accepts it.

The lock is established when the task is taken, before any source work, and it carries both
names: who set it and who took it. Neither name is optional and neither is a constant.

Releasing it is a request from either side to the other, carrying a reason. The other
side answers with consent or with a reasoned refusal. Both answers are recorded. Neither
side can release the lock alone.

## 3. Reused mechanism

Studio already has one LockAuthority journal for attributable locks, requests,
answers and reasons. Connected work supplies verified named parties to that same
mechanism. It does not create a second approval model or copy Cowork's agreement
registry into a local database.

## 4. Identity

Connected work separates named authority, contributor and verifier roles. Two named
parties require the product to verify who is acting.

OSS uses the machine identity enrolled under RFP-019. It answers *which machine*, not
*which person*, and for a single-user edition that is the honest limit; the record must say
so rather than implying a person.

Cowork binds the acting person to a signed principal, and the local lock records both
parties. Where Studio cannot verify the person, the lock is refused rather than recorded
against a placeholder. A lock signed by a constant is worse than no lock, because it reads
as evidence.

## 5. Acceptance

| Id | Requirement | Level |
|---|---|---|
| LOCK-1 | No approval records a name the product did not obtain from an identity it can name; a constant approver is refused | MUST |
| LOCK-2 | In OSS the recorded approver is the configured local machine, its self-asserted or certified status is explicit, and the approval instant precedes the first source change | MUST |
| LOCK-3 | For connected work a lock carries both the party who set the task and the party who took it, and is established before any source change | MUST |
| LOCK-4 | A release request carries a reason, names the side that asked, and takes no effect until the other side answers | MUST |
| LOCK-5 | A refusal is recorded as fully as a consent, with its reason, and stays visible afterwards | MUST |
| LOCK-6 | For connected work no single side can release a lock alone, including the side that set it | MUST |
| LOCK-7 | In OSS a release is recorded with its reason and is distinguishable from a two-party release rather than borrowing its appearance | MUST |
| LOCK-8 | Releasing a lock invalidates only the requirements whose judges change, through the existing amendment path, and leaves the rest accepted | MUST |
| LOCK-9 | A lock that disappeared without a recorded release is reported as broken rather than as absent | MUST |
| LOCK-10 | The release request, the answer and the reason are reachable from the requirement screen, not only through the API | MUST |
| LOCK-11 | In a team workspace an approval never records a lock naming one side; where the two parties cannot both be named the approval is refused and nothing is written | MUST |

## 6. Out of scope

Cryptographic signing of a human approval. Nothing here makes an approval unforgeable by
someone with local access; it makes it attributable and releasable. Signed human approval
needs an identity story Studio does not have yet, and pretending otherwise in this RFP
would repeat the mistake it exists to correct.

User management, invitations and role assignment in Cowork. This RFP consumes signed
principals and creates no accounts.
