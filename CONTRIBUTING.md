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

## Check a release candidate without GitHub Actions

Keep the commit in `release/candidate.json` in the release branch's history.
Use a merge that preserves it; squashing or rebasing it requires qualifying a
new candidate. The two archives in `release/publication.json` are the upload
inputs, not a request to rebuild them from the tip of the branch.

Run this from the checkout, with `archives` set to the directory containing
only those reviewed files. Do not point pip at the development wheelhouse:

```bash
wheel="$(python3 tools/verify_release_archives.py "$archives" --tag v0.1.7)" || exit 1
env_dir="$(mktemp -d)"
python3 -m venv "$env_dir" &&
  PIP_CONFIG_FILE=/dev/null "$env_dir/bin/python" -m pip --isolated --no-cache-dir install \
    --index-url https://pypi.org/simple --only-binary=apatch "$wheel" &&
  "$env_dir/bin/python" -m pip check &&
  "$env_dir/bin/python" -I tools/check_installed_studio.py
```

For 0.1.7 the package dependency floor is 0.8.54; the receipt-based Inbox
was qualified with the exact 0.8.55 Core recorded in `release/publication.json`.
An index-resolution failure blocks a tag and upload; a successful staging
install is not a substitute. After publication compare **both** SHA-256
digests with the [versioned PyPI record](https://pypi.org/pypi/apatch-studio/0.1.7/json)
and repeat the clean install using `apatch-studio==0.1.7` from the index.

The browser API must remain loopback-only and fixed-purpose. Please do not add a
generic shell, filesystem, Git or MCP relay.
