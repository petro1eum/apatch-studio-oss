# Getting started with APatch Studio OSS

APatch Studio OSS is a local browser workspace for contract-driven work with AI
agents. APatch supplies the governed runtime; Studio lets a person prepare, approve,
run, inspect, recover and deliver that work.

## Install

You need Python 3.11 or newer, a local Git repository, and at least one locally
installed agent CLI: Codex or Claude Code.

```bash
python3 -m pip install apatch-studio
apatch-studio serve --workspace /path/to/your/git/repository
```

Studio prints and opens a `127.0.0.1` URL. It does not expose the workspace on the
network. The selected agent CLI may still contact its own configured model provider.

## Your first governed change

1. On **Home**, describe the outcome and a meaningful success check, then choose a
   local agent and select **Prepare plan**.
2. Open the result in **Plans**. Review the exact allowed scope, forbidden areas,
   budgets and tests. Nothing may be implemented before you approve them.
3. Select **Approve scope & tests**. The implementation agent cannot change that
   judge; an amendment needs another explicit decision.
4. Return to **Home**, select the approved requirement and run it. Studio records
   the governed mutations, verification and evidence.
5. Review the local diff and delivery pack. Retry or recover a failed run; commit or
   push only after your explicit confirmation.

## Library and time

**Library** exposes proven reusable methods, verification history, exported evidence
and factual time drafts derived from signed APatch activity. Draft time is not an
invoice, payroll decision or automatic acceptance.

## Optional TrustChain Cowork connection

Start Studio with an execution-intent trust document only when you want to receive
signed Cowork assignments:

```bash
apatch-studio serve --workspace /path/to/repository \
  --execution-intent-trust-file /path/to/public-authority-pins.json
```

An imported assignment remains inert. You must bind it to an existing local SPEC
and confirm it. When Cowork is connected, Studio waits for exact acceptance and
source-binding acknowledgements before starting one local run. A replay cannot start
another run.

Source, diffs, prompts, credentials and private keys remain local. Only separately
authorized, content-safe evidence is eligible to leave the machine.

## Develop from source

```bash
python3 -m venv .venv
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```

Node is needed only to build the UI from source. Published wheels contain the web
client.

## Troubleshooting

- **No agent is available:** install/authenticate Codex or Claude Code and restart.
- **Runtime needs attention:** open **Admin → Runtime** and follow the reported
  update or cleanup step.
- **A plan stops:** open the run card; Studio records the bounded failure and offers
  retry instead of leaving silent partial work.
- **Cowork is unavailable:** local work, review, recovery and export remain usable.
