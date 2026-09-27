# Released contract cannot enter test authoring

Observed: 2026-09-16. Consumer: Telegram / SPEC-PERFOBORE-DRIVE-SYNC.

## Reproduction and actual state

1. Freeze an R0 regression-only contract, with no test-authoring writes.
2. Request a release explaining the need to prepare new acceptance tests.
3. The owner grants the release in Studio. The lock view reports `released`.
4. Start a governed test-authoring session through MCP.
5. Core rejects the session: `This workspace requires the frozen SDD contract, task envelope and implementation actor`.
6. Supplying the original envelope permits only its original operations. It does not authorize creating tests.

The observed frozen contract is `sha256:e78aae1649e5208bcabba549eec2da95873ef41798eff0c37b8f3a07435c7af3`.
The original envelope allows only `bot_v1/miniapp/auth.py`, zero inserted/deleted lines, and verification tools. Existing judge assets include the regression tests, specification, RFP, manifest and gate runner.

The owner release was observed through the live API. No agent submitted that decision. Neither the frozen contract nor its envelope was modified to bypass the rejection.

## Missing integration

`LockAuthority.answer_release` records a decision. `amendment_for_release` produces a sealed amendment describing selective invalidation. Neither activates a new authoring capability.

`runtime.session.start_session` requires the workspace's frozen profile and task envelope. `sdd_integrity` has implementation, verifier and authority roles; the inspected runtimes do not provide an admitted authoring role. Existing judge-path protections and functional attestation requirements also prevent using a widened implementation envelope as a substitute.

Inspected runtimes: running MCP 0.8.42 and Studio Core 0.8.45. A Studio-only endpoint cannot repair Core admission.

## Required repair contract

- Prepare an exact scope: new file paths, operations, budgets, preserved judge hashes, original contract hash, release identity and allowed verification commands.
- Have the owner approve the exact scope snapshot. A free-text release reason is not an exact scope approval.
- Admit the immutable grant through Core and MCP without replacing or deleting the frozen workspace profile.
- Keep old judges and application runtime source immutable during preparation.
- Reject stale scopes, reused grants, path traversal, symlinks, pre-existing targets, cross-workspace targets, and caller-selected authority roles.
- Distinguish preparation evidence (collection/syntax and preserved hashes) from functional acceptance. Preparing a test cannot attest a business requirement.
- Freeze the resulting executable business contract separately before implementation.
- Verify the whole path in integration tests, including failures and replay, before enabling it in the consumer.

Suggested first consumer scope: new `bot_v1/tests/drive_sync/__init__.py`, `support.py`, `fake_drive.py`, `test_r01.py`, and `test_r03.py`, plus a separately named preparation candidate. This is a proposal, not an approved grant.

## Activation boundary

The consumer AGENTS.md reserves installation/reload of MCP to the human operator. An implementation patch and its passing tests must be prepared before requesting that activation. Do not disable enforcement or edit frozen profile files as a workaround.

## Delivery status — updated 2026-09-16

The authoring transition is now implemented in Core and Studio source. Core changes were governed and attested under SPEC-SDD-INTEGRITY-1#R12, session `apatch_sess_1789572040292369000_adec0a657f83`, attestation `op_0406`.

The reviewed local package is `/Users/edcher/Documents/Codex/perfobore-authoring-fix-20260916/dist/apatch-0.8.45+authoring.1-py3-none-any.whl`, built from clean OSS commit `7d212e73e021af5ce920888b6f7aaddc333f1620` plus only the signed authoring source changes. SHA256: `7d2f8d1011d2014dc1fdd4e0e23ec6d0aaa787d5b8a7d839e03a2e606f885e47`.

Validation: 54 Core tests on the isolated candidate and 190 Studio/SDD/lock tests against the actual unpacked wheel passed. Cross-layer coverage includes a real signed multi-stage creation/verification/attestation cycle with sandbox enforcement; it explicitly leaves functional acceptance false and the old profile byte-identical. The frontend build passed.

The installed MCP runtime has not been replaced or restarted by the agent. The human activation script is alongside the wheel in `activate.sh`; it checks the package digest and installs it into the two existing Python environments without touching consumer contracts. After activation and MCP reload, the exact preparation scope must be proposed and reviewed in Studio before the agent can author tests.

This first version permits a single complete CREATE plan containing only the exact new approved paths. It does not permit editing pre-existing files. It records preparation evidence, not business acceptance. Perfobore R1–R28 remain unimplemented and unaccepted.
