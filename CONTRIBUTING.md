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
.venv/bin/python -m pip install -r requirements/source.txt -e ".[dev]"
.venv/bin/python -m pip check
.venv/bin/pytest -q
.venv/bin/python -m build .
.venv/bin/python -m twine check dist/*
```

The source install uses a pinned revision of the public Core repository. Update
that pin when changing the SDK contract. The publish workflow deliberately
resolves the wheel's declared dependencies from the package index, without the
development pin: release the compatible Core to PyPI before publishing Studio.

To exercise the full suite before that Core release, build the paired Core
wheel into an empty temporary directory with `python -m pip wheel --no-deps
-r requirements/source.txt --wheel-dir "$wheelhouse"`, then run
`PIP_FIND_LINKS="$wheelhouse" python -m pytest -q` in the development environment.
This proves staging installation, not index availability. The publish job tests
without that directory and uploads only the two hash-verified assets attached
to the matching GitHub release; it does not rebuild after approval.

The browser API must remain loopback-only and fixed-purpose. Please do not add a
generic shell, filesystem, Git or MCP relay.
