# Contributing

APatch Studio OSS welcomes focused bug reports, documentation improvements and
changes that preserve its local-first security boundary.

## Before opening a change

1. Check existing issues and describe the user-visible outcome.
2. For behavior changes, add or amend an RFP acceptance row and map it to one
   executable SPEC requirement.
3. Write a test that observes the behavior and can fail for the intended defect.
4. Keep source code, full diffs, prompts, credentials, private keys and local paths
   out of network-facing projections.

## Verify locally

```bash
python3 -m venv .venv
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
.venv/bin/python -m build .
.venv/bin/python -m twine check dist/*
```

The browser API must remain loopback-only and fixed-purpose. Please do not add a
generic shell, filesystem, Git or MCP relay.
