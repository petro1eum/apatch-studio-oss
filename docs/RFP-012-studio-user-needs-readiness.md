# RFP-012 -- APatch Studio Next-Generation SDD and Execution Integrity Contract

> **Status:** Owner-approved and frozen for executable specification
> **Owner:** APatch Studio
> **Date:** 2026-09-01
> **Builds on implemented baseline:** Studio RFP-001, RFP-005, RFP-011 and the public APatch runtime
> **Executable contracts:** separate APatch Core integrity SPEC and APatch Studio lifecycle SPEC must be frozen after this RFP review
> **Evidence source:** owner correction that APatch is next-generation SDD, not a generic agent launcher or project dashboard

## 1. Owner correction and decision

### 1.1 APatch is the implemented baseline

APatch already exists, works in real repositories and is the canonical SDD execution runtime. This RFP is not a proposal to create APatch again.

The following capabilities are implemented foundations, not roadmap items:

| Layer | Existing canonical APatch capability |
|---|---|
| Contract authoring | RFP acceptance parsing and lint, deterministic `spec scaffold --from-contract`, RFP-to-SPEC coverage |
| Executable specification | Atomic `Rk` requirements, dependency/status tracking, `execute_next`, whole-`spec_run` and multi-SPEC execution |
| Governed execution | Artifact-anchored intent, exact governed sessions, transactional mutations, checkpoints, recovery and rollback |
| Mutation control | Sandbox enforcement, protected paths, SPEC-owned mutation gate, writer/path leases and interference checks |
| Verification | Native verify, baseline-aware comparison, semantic/architecture/database gates and differential `probe falsify/regress/ratify` |
| Continuing truth | Stale/drift classification, symbol-aware evidence and continuous conformance |
| Evidence | TrustChain-signed mutation and attestation history, artifact coverage, inclusion/transparency evidence and contribution receipts |
| Effort | Deterministic, re-verifiable contribution ledger and timesheet projection |
| Extended execution | Remote fixed-purpose execution and reusable WorkAsset foundations |

Existing commands, schemas, ledgers, recovery semantics and previously attested work remain authoritative. The Core and Studio specifications derived from this RFP may extend them, compose them and make existing optional safeguards mandatory for a risk class. They may not replace them with a second runtime, second state model or parallel evidence chain.

### 1.2 Bounded product decision

The initial RFP-012 revision was wrong because it placed onboarding and a generic task launcher at the center. Those are supporting workflows around the already working APatch runtime.

APatch is next-generation spec-driven development because it already connects executable requirements, governed mutation, verification and signed evidence. The bounded upgrade is to make the entire route from a human assignment to those existing mechanisms explicit and consistently enforced:

```text
Brief / technical assignment (TZ)                         [first-class input delta]
  -> RFP acceptance                                       [implemented]
  -> verification contract frozen before implementation  [integrity hardening]
  -> SPEC / Rk and traceability                           [implemented]
  -> strict task envelope                                 [extends session + sandbox]
  -> governed execution / checkpoint / rollback           [implemented]
  -> falsify / regress / ratify                           [implemented; mandatory by policy]
  -> attestation / conformance / contribution             [implemented; enriched bindings]
  -> causal replay and derived effort                     [implemented data; Studio composition]
```

No later stage may silently redefine an earlier one. In particular, implementation cannot rewrite its own acceptance criteria, verification commands, tests or allowed scope and then attest against the weaker contract.

Studio is the human surface over this existing chain. APatch Core remains the authority for contract hashes, execution admission, mutation, verification, attestation, recovery and effort evidence.
## 2. Solo and team authority models

The execution semantics are identical for solo and team use. Only the human authority that freezes or amends the contract changes.

### 2.1 Solo developer

The same person may author the brief, RFP, SPEC and verification contract. APatch helps structure and challenge them. Before implementation begins, the developer explicitly freezes one revision. From that point the agent cannot modify the approved contract or tests.

The solo workflow is not weaker governance. It is self-authority with temporal separation between contract approval and implementation.

### 2.2 Team contributor

A manager, architect, analyst or customer supplies a technical assignment and may supply an already approved RFP/SPEC. If only the assignment exists, APatch helps produce draft RFP, tests and SPEC, but the designated authority must approve their exact hashes before the developer or agent can mutate source.

The contributor and execution agent cannot widen scope, waive criteria or weaken tests. They can only request a signed amendment with a reason.

### 2.3 Team reviewer and administrator

A reviewer approves the engineering contract or a later amendment and separately decides whether the resulting technical evidence satisfies it. A Cowork administrator may manage membership and shared policy, but cannot rewrite local engineering evidence.

AI agents are execution actors. They never become acceptance authority merely because they authored code or tests.

## 3. Contract compilation

APatch already parses RFP acceptance, scaffolds contract-complete SPEC requirements, checks traceability and executes exact `Rk` units. RFP-012 preserves that implementation and adds the missing pre-execution inputs to the same chain.

1. The input brief/TZ is preserved as a versioned artifact using existing artifact identity and provenance mechanisms.
2. Existing RFP lint continues to enforce stable acceptance rows and explicit waivers.
3. A verification-contract manifest maps every acceptance row to test obligations, independent oracles, exact assets and existing APatch verify/probe commands.
4. Existing SPEC scaffold and coverage remain the only RFP-to-SPEC compilation path; requirements remain atomic and executable.
5. The existing execution plan is extended with the intended read context, write set, symbols, operations, dependencies and side effects for every requirement.
6. Human authority freezes a manifest of the RFP, verification contract, SPEC and plan hashes before the first implementation mutation.

APatch may generate drafts, ask clarifying questions and report ambiguity. It must never silently invent missing product decisions and call them approved.

Any material change after freeze creates a new contract revision, states why the prior revision is insufficient, invalidates exactly the affected existing execution capabilities and requires the appropriate human authority before work resumes.
## 4. Strict task envelope

APatch strict mode already requires governed execution and combines artifact-bound sessions, sandbox policy, protected paths, SPEC-owned mutation admission, leases, checkpoints and rollback. Those mechanisms remain the enforcement substrate.

The bounded gap is that their decisions are not yet derived from one complete, signed capability envelope for one exact `Rk` and contract revision. RFP-012 extends the existing session capability with at least:

- brief, RFP, verification-contract, SPEC, requirement, plan and baseline hashes;
- allowed read roots and dependency-expansion rules;
- allowed write paths, directories, symbols, rename/delete targets and generated outputs;
- explicitly forbidden source, contract, test, policy and credential surfaces;
- allowed mutation types, commands, tools, network access, remote targets and service actions;
- filesystem, process, network, time, token and change-volume budgets;
- exact test/fixture hashes and verification commands;
- required checkpoints, review gates and rollback ownership.

The agent receives only the context and capabilities necessary for the requirement. APatch cannot control private model reasoning, but it can bound supplied context, reads, tool calls and every external effect.

Admission remains atomic. Ambiguous ownership, undeclared paths, missing tests or unresolved dependencies block before mutation. Scope never widens automatically. An attempted out-of-envelope read, write, command, network call or service action is denied and recorded against the exact existing governed session.

Plan adherence becomes a blocking invariant in strict mode rather than a report-only observation. Existing sandbox, lease, rollback and TrustChain behavior perform the enforcement; the task envelope makes their common decision explicit and auditable.
## 5. Pre-implementation verification contract

APatch already runs requirement-owned verification, supports baseline-aware comparison and provides `probe falsify`, `probe regress` and `probe ratify`. RFP-012 does not invent another test runner. It closes two exact gaps: the judging contract can currently be selected or edited too late, and gate-quality probes are not mandatory for every applicable strict attestation.

A green command is not evidence unless the frozen contract proves what the command tests and that it can fail.

Before implementation, every RFP acceptance criterion must have a verification obligation containing:

- stable test IDs and exact RFP/SPEC mapping;
- oracle: the observable state or output that determines success;
- test, fixture, schema and verification-command hashes;
- baseline observation made before implementation;
- required positive, negative, boundary and regression perspectives;
- failure, recovery, security, privacy, integration, concurrency, performance or scale perspectives when claimed by the requirement;
- deterministic environment, seed and dependency pins where applicable;
- a falsification or perturbation plan implemented through the existing probe contract;
- author, approver, freeze time and amendment policy.

Tests may be drafted by an agent during the contract-authoring phase. After freeze, the implementation capability cannot modify the tests, fixtures or verification command it is judged by. In team mode, the designated authority approves them. In solo mode, the human developer approves them before implementation.

For new behavior, the baseline should normally demonstrate the relevant test failing before implementation. For characterization, migration or non-code requirements, the contract records the justified baseline and independent oracle instead.

The following never qualify as sufficient proof:

- `true`, empty commands or a runner that collected no tests;
- all-skipped or all-xfailed results;
- import, build or syntax success used as proof of domain behavior;
- tests that only assert a mock was called or return the value they injected;
- tests written or weakened after seeing the implementation without an approved amendment;
- one happy-path check for a requirement that claims failure handling, security, concurrency, compatibility or scale.

Final verification reuses the existing verifier and probe machinery under a non-mutating capability. Mandatory targeted falsification must make an intentional reversible violation red. Baseline-aware regression must show no new unrelated failures, and ratification must show that the final gate remains green.
## 6. Attestation, causal history and effort

APatch already signs governed intent, sessions, mutations, checkpoints, verification and artifact attestations, and already derives contribution receipts and a re-verifiable timesheet from signed events. RFP-012 preserves those schemas and enriches the attested linkage; it does not introduce another ledger or time database.

For an RFP-012 strict run, the existing attestation additionally binds:

- input/RFP/verification-contract/SPEC/plan hashes;
- requirement and strict task-envelope hash;
- actor and execution identity;
- checkpoints, exact mutation set and adherence result;
- collected, executed, passed, failed, skipped and falsification test results;
- environment and dependency fingerprints required for reproduction;
- existing attestation, conformance, contribution and ledger references;
- session start/end, operation spacing, active-effort estimate and work volume.

The causal view composes facts already held by APatch and must answer: what was requested, who approved it, what the agent was allowed to do, what it actually did, why it was done, which checks judged it, whether those checks can detect failure, and how much governed effort occurred.

The existing timesheet remains a deterministic, re-verifiable projection of signed events. It is not a stopwatch, payroll decision or accepted time. Human acceptance and accepted time remain separate authority decisions.
## 7. Ownership boundaries

| Concern | Authority |
|---|---|
| Contract parsing, hashes, coverage, freeze and amendment invalidation | APatch Core |
| Strict envelope admission and effect enforcement | APatch Core |
| Verification, falsification, attestation, recovery and effort evidence | APatch Core |
| Human authoring, comparison, approval and causal-chain visualization | APatch Studio OSS |
| Team assignment, reviewer authority, signed amendments and shared policy | TrustChain Cowork |
| Business acceptance, payment and accepted time | External authority, never inferred by APatch |

Studio does not duplicate Core state. It renders the exact contract and evidence and sends bounded authoring or decision commands back to the owning authority.

## 8. Product readiness terms

- **Need** is a user outcome, such as reviewing a completed change.
- **Prerequisite** is a condition required before the user can complete that outcome.
- **Capability** is an APatch or Studio mechanism that helps satisfy a need.
- **Workflow** is the complete human path from intent to understandable outcome.
- **Ready** means the workflow can be completed now.
- **Action required** means Studio presents one bounded user action that makes the workflow ready.
- **Unavailable** means the workflow cannot run and Studio states the exact reason without creating misleading work state.

A hidden prerequisite is a product defect. Documentation alone does not satisfy a prerequisite contract.

## 9. Product prerequisite contract

Studio owns detection and explanation of every prerequisite. It may delegate installation or authentication to an external application, but it must verify the result and resume the interrupted workflow.

| Id | Prerequisite | Studio responsibility |
|---|---|---|
| PRE-1 | A readable local project or repository | Add, open, remember and switch projects; show the exact selected project before work starts |
| PRE-2 | A compatible APatch runtime and writer protocol | Detect version and protocol, explain incompatibility and provide one safe repair action |
| PRE-3 | An available authenticated local agent such as Codex or Claude Code | Detect availability separately from authentication and prove a bounded launch before offering execution |
| PRE-4 | Repository-owned project context such as README, RFP and SPEC | Show what is missing and offer a governed path to create or improve it |
| PRE-5 | An executable verification basis | Distinguish verified proof from unverified completion and guide creation of an appropriate check |
| PRE-6 | A local signing and trust identity | Initialize, validate and explain local evidence identity without exposing private material |
| PRE-7 | Remote target and service policy when remote work is requested | Guide fixed-purpose remote setup and validate it without disclosing host topology to the agent |
| PRE-8 | Signed Cowork identity and authority when connected coordination is requested | Guide connection and fail closed without disabling the local workflow |

Every need projection includes edition, prerequisite states, readiness state and exactly one recommended next action.

## 10. Implemented APatch baseline and bounded deltas\n\nAPatch is operational; this is not a greenfield capability inventory. Each row names an implemented mechanism and only the remaining additive integrity or Studio-composition gap.

| User need | Prerequisites | Current APatch capability | Exact gap |
|---|---|---|---|
| Preserve the original assignment | Versioned brief/TZ, author, source and hash | Repository documents and artifact hashes exist | No canonical brief/TZ artifact or end-to-end Studio authoring flow |
| Turn the assignment into an RFP | Clarified outcomes, stable acceptance IDs and human authority | RFP documents, lint and governed document mutation exist | Authoring is document-centric; ambiguity, waivers and approval are not one product workflow |
| Define how success will be judged before coding | Test IDs, independent oracles, fixtures, commands, baseline and approver | SPEC verify commands and probe/falsify/regress/ratify primitives exist | No mandatory frozen pre-implementation verification contract; weak checks can still attest |
| Compile the RFP into executable requirements | Complete RFP coverage, atomic requirements and dependencies | Deterministic RFP-to-SPEC coverage and requirement execution exist | The test contract and exact task envelope are not yet first-class inputs to compilation |
| Keep the agent focused on one requirement | Exact allowed context, write set, tools, effects and budgets | Governed sessions, sandbox globs, protected paths, leases and SPEC-owned mutation gates exist | Strict mode does not yet enforce one complete task envelope across every read, tool, network, remote and service surface |
| Prevent the implementation from changing its own judge | Frozen tests, fixtures, commands and amendment authority | Protected paths can be configured | Tests are commonly writable; no universal contract lock or implementation/verifier role separation |
| Prove the implementation, not merely run a command | Collected tests, meaningful assertions, multiple perspectives, falsification and clean regression | Verification, attestation and optional probe workflows exist | Generic or tautological green gates are warned about but not universally rejected; falsification is not mandatory |
| Explain what was done and why | Linked TZ, RFP, Rk, plan, operation, checkpoint and decision IDs | Signed sessions, mutation events, checkpoints and attestations exist | Studio does not yet present the full causal chain as one understandable change record |
| Prove governed effort | Signed event timeline and deterministic derivation rules | Verifiable timesheet and contribution-receipt foundations exist | Studio projection and quality indicators are incomplete; accepted time remains external by design |
| Let a solo developer govern their own work | Human freeze before implementation and explicit amendment flow | One user can author and execute governed artifacts | Temporal separation between authoring approval and implementation is not enforced as a product contract |
| Let a team execute a manager-approved assignment | Named authority, exact frozen hashes, contributor capability and review decision | Signed-intent and evidence foundations exist | Online assignment-to-contract approval and two-party review remain Cowork integration work |
| Amend the task honestly | New revision, reason, impact set, invalidated capabilities and approval | Stale/conformance mechanisms exist | A signed contract-amendment object does not yet govern all affected tests, plans and sessions |

The implementation base is already substantial and remains in service. RFP-012 closes a bounded composition gap: the assignment, frozen judging contract and complete task envelope must become first-class inputs to the existing governed execution and evidence chain.

## 11. APatch Studio OSS target journeys

### 11.1 From assignment to frozen contract

The user starts with a brief or technical assignment, not with a protocol object. Studio preserves the source and helps the user:

1. clarify outcomes, constraints, exclusions and unresolved decisions;
2. produce an RFP with stable acceptance IDs;
3. define the verification contract, including multiple test perspectives and falsification;
4. compile the RFP into atomic SPEC requirements and a proposed execution plan;
5. inspect allowed and forbidden scope;
6. freeze the exact contract hashes before implementation.

A single "What should become true?" field may start a change only when an approved contract already covers that outcome. Otherwise it opens the contract-authoring flow; it never bypasses it.

### 11.2 Strict implementation

Before the first mutation, Studio shows in human language:

- the exact requirement being implemented;
- files, logical areas and external effects that are allowed;
- contract, test, policy and credential surfaces that are forbidden;
- verification obligations and budgets;
- the human authority and frozen revision.

During execution, the same contour remains visible. Reads, writes, commands, network calls, remote operations and service actions outside it fail closed. The agent may request an amendment, but it cannot grant one to itself.

### 11.3 Independent verification and review

After mutation, APatch changes to a verifier capability. The verifier cannot modify source, frozen tests or contract artifacts. Studio shows:

- tests collected, executed, passed, failed and skipped;
- positive, negative, boundary and regression perspectives;
- risk-specific perspectives required by the RFP;
- the baseline observation;
- targeted falsification and its expected red result;
- final regression and ratification;
- the exact patch and any attempted scope violations.

A green badge is impossible when no meaningful tests ran, all tests were skipped, a required perspective is absent, falsification did not make the gate red, or a frozen test asset drifted.

### 11.4 Honest amendment and recovery

When implementation exposes a defective requirement or test, the user does not edit it in place. Studio creates a proposed amendment that states the reason, changed hashes, affected requirements, invalidated sessions and required approver.

Failures and interruptions remain attached to the exact contract revision. Recovery resumes only compatible work; otherwise APatch requires a reviewed amendment or a new change.

### 11.5 Causal history and effort

One change view answers, in order:

- what the user or manager asked for;
- how that became RFP acceptance and SPEC requirements;
- who froze the contract and when;
- what the agent could and could not do;
- what it actually changed and why;
- how each acceptance criterion was tested;
- whether the tests were shown to detect failure;
- what was attested;
- how governed effort was derived.

The individual developer can verify and export a timesheet draft derived from signed events. Its estimation method and data-quality limitations remain visible.

### 11.6 Existing projects, reuse and remote work

Existing APatch workspaces open without duplicating Core state. Proven WorkAssets may be reused only through a new governed contract. Remote work uses the same strict task envelope and fixed-purpose capabilities; host topology, credentials, arbitrary shell and generic MCP relay remain outside the agent contract.

## 12. Cowork-connected target journeys

Cowork extends the same integrity model; it does not create a weaker or separate execution path.

A manager, architect, analyst or customer can provide a technical assignment, review the generated RFP/SPEC/verification contract, freeze exact hashes and assign the resulting work.

A contributor can inspect the complete contract and execute only its bounded capability. The contributor or agent may propose clarification or amendment but cannot widen scope, modify frozen tests or approve their own request.

A reviewer can compare request, approved scope, exact patch, violations, multi-sided verification, falsification, attestation and effort evidence, then issue a separate signed technical decision.

An administrator can distribute policy and trust roots and observe content-safe connection health. Administration cannot rewrite local evidence or infer business acceptance, accepted time, professional value or status.

## 13. Product boundary

| Need | APatch Studio OSS | TrustChain Cowork connection |
|---|---|---|
| Author brief/TZ, RFP, verification contract and SPEC | Included | Included with team templates and policy |
| Human freeze before implementation | Local owner authority | Named team authority and role separation |
| Strict task envelope and fail-closed effects | Included, identical integrity floor | Included, organization policy may only strengthen it |
| Locked tests and separate verifier capability | Included | Included with independent reviewer or harness requirements |
| Multi-sided verification, falsification and ratification | Included | Included with policy-defined risk profiles |
| Local execution, recovery, rollback and attestation | Included | Included |
| Full causal history and verifiable effort draft | Included | Included with team-safe projections and separate decisions |
| Assignment, membership and reviewer authority | Not required | Included |
| Signed contract amendments and team technical decisions | Local owner decisions | Included |
| Organization policy and reconciliation | Not required | Provided by Cowork |
| Cloud dependency for ordinary local work | None | None for OSS-capable operations |

Cowork may add coordination, policy and authority separation. It must never turn the correctness floor into a hosted-only feature by withholding strict execution or meaningful verification from OSS.

## 14. Priorities

### P0 -- Harden and compose the existing SDD runtime

These are additive deltas over working APatch primitives. Reimplementing an existing command, ledger, session lifecycle, rollback path, probe or timesheet is out of scope.

1. Add a versioned brief/TZ input adapter over existing artifact identity and provenance; do not add a document database.
2. Add a freeze manifest that references existing RFP, SPEC, test, fixture, command and plan hashes.
3. Add a signed amendment record that uses existing stale/conformance invalidation to close affected capabilities.
4. Extend the existing governed-session capability into the complete task envelope for reads, writes, symbols, tools, network, remote/service effects and budgets.
5. Route that envelope through existing mutation, sandbox, watcher, lease, runner, remote and service admission points.
6. Protect frozen tests and contract assets from the implementation capability and reuse existing verification under a separate non-mutating capability.
7. Promote existing baseline and `probe falsify/regress/ratify` primitives into mandatory policy-selected attestation gates.
8. Enrich existing attestation and timesheet references with the frozen contract and envelope hashes.
9. Compose existing facts in Studio for solo/team authoring, freeze, visible scope contour, execution, amendment, proof and causal replay.

### P1 -- Complete the human product shell

1. Project add, recent, open and switch.
2. Guided runtime, agent, trust and remote readiness.
3. Search and navigation across assignments, RFPs, SPECs and results.
4. WorkAsset discovery-to-reuse flow.
5. Content-safe Cowork assignment and review projections.

### P2 -- Scale assurance

1. Policy profiles by risk class and domain.
2. Independent harness and hidden-test integration.
3. Contract-quality and false-gate analytics without source collection.
4. Cross-repository ChangeSet envelopes with explicit partial outcomes.
5. Cowork reconciliation, revocation and long-term evidence retention.

## 15. Release qualification

A release claim requires adversarial observed journeys, not screenshots or a green command.

- A solo user transforms a new TZ into an RFP, frozen verification contract, SPEC, strict envelope, implementation and replayable proof.
- A team authority freezes exact contract hashes; a different contributor executes without being able to widen scope or change the judge.
- The test contract and its protected asset hashes demonstrably predate the first source mutation.
- Attempts to write forbidden source, RFP, SPEC, test, fixture, policy or credential surfaces are denied and recorded without unrelated damage.
- Attempts through every supported mutation, tool, network, remote and service path receive the same envelope decision.
- Verification fails when zero tests are collected, all relevant tests are skipped, required perspectives are absent or frozen assets drift.
- A reversible seeded defect makes the mapped test gate red; restoring the implementation makes it green again.
- Positive, negative, boundary and regression checks run for every behavioral criterion, with additional risk perspectives when claimed.
- A plan mismatch blocks strict attestation rather than becoming a report-only warning.
- An approved amendment invalidates affected capabilities and preserves the superseded contract and reason.
- Causal replay answers what, why, who approved, what was allowed, what occurred, how it was tested and how effort was derived.
- Core and Studio contract fixtures are byte-exact, and desktop/mobile UI tests prove that the scope contour and proof remain understandable.

## 16. Product and integrity measures

APatch records product measures without treating them as acceptance evidence:

- percentage of TZ outcomes mapped to stable RFP acceptance IDs;
- percentage of acceptance IDs with a frozen test contract before mutation;
- percentage of SPEC requirements with complete RFP and test mapping;
- out-of-envelope attempts prevented, classified by effect surface;
- contract amendments requested, approved and rejected;
- verification runs with complete perspective coverage;
- seeded defects detected by targeted falsification;
- false-green incidents and gates rejected for zero collection, skipping or drift;
- attestations with complete causal replay;
- effort drafts successfully re-derived from signed events;
- time from TZ to frozen contract and from frozen contract to proven result.

No metric becomes proof of business acceptance, accepted time, quality, professional status or value.

## Acceptance

This revision establishes the stable `SDD-*` contract.

| Id | Requirement | Level |
|---|---|---|
| SDD-1 | The implemented APatch baseline - RFP lint/scaffold/coverage, SPEC/Rk execution, governed sessions, transactional mutation/rollback, sandbox/leases, verify/probe/conformance, TrustChain evidence and verifiable timesheet - remains canonical and is extended rather than reimplemented or duplicated | MUST |
| SDD-2 | The original brief/TZ is a versioned artifact with author/source provenance, timestamp, hash and revision lineage | MUST |
| SDD-3 | Every promised RFP outcome has a stable acceptance ID and maps completely to atomic SPEC requirements or an explicit approved waiver | MUST |
| SDD-4 | Every acceptance ID maps before implementation to a frozen verification obligation containing stable test IDs, independent oracle, asset/command hashes, baseline, required perspectives, falsification plan and approver | MUST |
| SDD-5 | Behavioral obligations include positive, negative, boundary and regression perspectives, plus failure/recovery/security/privacy/integration/concurrency/performance/scale perspectives whenever the RFP makes those claims | MUST |
| SDD-6 | New behavior normally records a relevant red baseline, and every material gate undergoes a reversible targeted falsification that must make the mapped result red before final ratification | MUST |
| SDD-7 | After contract freeze, the implementation actor cannot modify or replace the approved RFP, SPEC, tests, fixtures, schemas or verification commands; changes require a signed amendment and new hashes | MUST |
| SDD-8 | Strict mode binds one exact requirement to an envelope containing contract/baseline hashes, allowed reads/writes/symbols/effects, forbidden surfaces, tools/commands/network/remote/service permissions, budgets, checks and rollback ownership | MUST |
| SDD-9 | Every supported mutation entrypoint, MCP tool, local runner, sandbox/watcher, network operation, remote worker and service action enforces the same envelope before its first external effect, without automatic widening | MUST |
| SDD-10 | Out-of-envelope effects fail closed, are attributed to the exact actor/session, leave unrelated work untouched and prevent attestation until safely resolved | MUST |
| SDD-11 | Strict-mode plan adherence is blocking: undeclared paths, symbols, operations or effects cannot be reduced to a warning or attested as compliant | MUST |
| SDD-12 | A solo developer can author and refine all contract stages, but a human freeze temporally precedes implementation and the executing agent cannot self-approve amendments or proof | MUST |
| SDD-13 | In team mode, a named authority freezes exact contract hashes and a contributor/agent can only execute the issued capability or request a signed amendment | MUST |
| SDD-14 | Studio shows before and during execution, in human language, the exact task, authority, allowed scope, forbidden scope, checks, budgets, live violations and amendment status | MUST |
| SDD-15 | Verification runs with a non-mutating verifier capability and rejects zero-collected, all-skipped, tautological, drifted or perspective-incomplete gates | MUST |
| SDD-16 | Attestation binds the exact contract/envelope hashes, actor, mutation set, adherence result, collected/executed test results, falsification, environment, checkpoints and ledger references | MUST |
| SDD-17 | One causal replay shows the request, decisions, approved plan, actual operations, reasons, violations, verification and final attestation without requiring raw protocol interpretation | MUST |
| SDD-18 | Governed effort and work volume are deterministically re-derived from signed events with quality limits visible and remain distinct from payroll or accepted time | MUST |
| SDD-19 | Contract drift, stale requirements, source drift and approved amendments invalidate exactly the affected capabilities and attestations while preserving prior evidence and reasons | MUST |
| SDD-20 | Studio OSS and Cowork-connected work share the same strict execution and verification floor; hosted authority and coordination cannot weaken or monopolize correctness | MUST |

## Non-goals

Reimplementing APatch is explicitly out of scope. Existing RFP/SPEC tooling, governed execution, transactions, sandbox, leases, recovery, rollback, verification, probe, conformance, TrustChain evidence, contribution and timesheet mechanisms remain the canonical implementation base.

This RFP does not claim to control an agent's private reasoning. It controls the context and capabilities APatch supplies and every observable external effect APatch authorizes.

It does not create a generic task runner, a second APatch runtime, a second SPEC/evidence database, a project-management suite, payroll system, business-acceptance authority, professional-status inference, cloud source repository, remote shell or generic MCP proxy.

A self-written check is not rejected merely because an agent drafted it. It is rejected as proof when it was not frozen before implementation, lacks an independent oracle or required perspectives, can be weakened by the implementation actor, was never shown to fail, collected nothing meaningful or became green by construction.

No implementation of the bounded RFP-012 deltas may begin until the owner reviews and freezes this acceptance contract. Existing APatch operation, existing Studio functionality and previously attested SPECs continue unchanged. The later Core and Studio SPECs must map only the delta and preserve every `SDD-*` row.
