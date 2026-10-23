# APatch Studio OSS

APatch Studio OSS is the local workspace for contract-driven work with AI agents.

Most agent sessions begin as requests in natural language: “read the specification,”
“write the tests,” “do not change them,” “implement the feature.” Studio turns that
fragile conversation into an explicit local contract that connects:

- the human intent and selected scope;
- the exact RFP, SPEC and requirement being executed;
- the agent run and every governed mutation;
- verification results, recovery checkpoints and signed evidence;
- the delivery decision and a factual time draft.

The result is not merely “AI generated code.” It is work whose mandate, changes,
tests and proof remain inspectable after the chat session ends.

Studio is useful without an account, subscription or network connection. When the
owner chooses to connect it to [TrustChain Cowork](https://trust-chain.ai/), the same
local workspace can receive signed assignments, require explicit local acceptance,
bind them to an existing SPEC, run APatch locally and return only authorized,
content-safe evidence. Source code, diffs, prompts, credentials and private keys stay
on the user's machine unless the user separately publishes them through Git.

## Install

APatch Studio OSS requires Python 3.11 or newer.

```bash
python3 -m pip install apatch-studio
apatch-studio serve --workspace /path/to/your/git/repository
```

Studio opens a loopback-only browser interface. Consumer installation does not need
Node.js because the wheel contains the built web client.

For development:

```bash
python3 -m venv .venv
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```

## What is included

- local governed changes and exact SPEC requirement execution;
- Codex and Claude Code runner supervision;
- interruption recovery, retry and rollback;
- local review, delivery packs and owner decisions;
- signed evidence, WorkAssets, Avatar evidence export and factual time drafts;
- an opt-in signed Inbox and APatch governed-work round trip with Cowork;
- workspace, policy and runtime diagnostics.

## What is not included

The public distribution contains no organization control plane, membership or
entitlement service, fleet management, hosted database, cloud source storage or
remote arbitrary-execution endpoint. Those collaboration capabilities belong to
TrustChain Cowork and its hosted services. Their absence never disables local work.

## Documentation

- [Getting started](https://github.com/petro1eum/apatch-studio-oss/blob/main/docs/GETTING-STARTED.md)
- [OSS publication contract](https://github.com/petro1eum/apatch-studio-oss/blob/main/docs/RFP-023-studio-oss-publication.md)
- [Executable publication specification](https://github.com/petro1eum/apatch-studio-oss/blob/main/docs/specs/SPEC-STUDIO-OSS-PUBLICATION-1.md)
- [APatch OSS](https://github.com/petro1eum/apatch-oss)
- [TrustChain](https://trust-chain.ai/)

## Security

Please report security issues privately through the repository's GitHub Security
Advisory flow. Do not open a public issue containing credentials, private keys,
source code or personal data.

## License

MIT. See [LICENSE](https://github.com/petro1eum/apatch-studio-oss/blob/main/LICENSE).

## Service maintenance 0.1.7 (20 October 2026)

Preserves the installed 0.1.6 result-delivery journal and routes, and adds guarded exact-contract import with an explicitly configured public trust document (`--exact-contract-trust-file`). Import never authorizes execution. Without an enrolled server binding and matching public pins, this channel is unavailable. The existing local service uses APatch 0.8.54; this source branch does not claim PyPI publication or a completed production exact-contract scenario.

Packaging now rebuilds the Python package from source even if a cached build copy has a newer timestamp, and removes stale modules from that generated package directory. Focused verification: 45 API/security/result-delivery tests and the actual stale-build regression.


The additive execution source declaration producer in `apatch_studio/execution_source_declarations.py` verifies the workspace's existing signer, native execution receipt, independently signed source receipt and exact shared Change before emitting a separate signed statement. It derives the real 16-hex execution project through the native SDK and keeps it distinct from the ProjectGroup. The canonical portable wire is pinned from avatar-contract5e8a43d under `_contracts/UPSTREAM.json`, preserving the installed Avatar runtime. Nineteen source/crypto/path-boundary tests pass. A real local native run was used to verify its declaration separately; this helper alone is not a Company admission, Tracker receipt, production installation or a browser flow.
