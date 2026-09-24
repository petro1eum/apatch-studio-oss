# SPEC-STUDIO-OSS-PUBLICATION-1

> **apatch artifact:** `spec:SPEC-STUDIO-OSS-PUBLICATION-1`

## R1 Clean public source boundary

The public repository starts with a new history, uses the exact TrustChain MIT
license, carries English primary documentation and contains no private control-plane,
fleet, entitlement or Local Team implementation.

(verify: python3 -m pytest tests/oss_publication/test_publication_contract.py::test_clean_public_source_boundary -q)

## R2 Distributable artifact boundary

A newly built wheel and sdist contain only the declared OSS paths, carry the exact
LICENSE bytes, use package-index dependencies only and pass metadata validation.

(verify: python3 -m pytest tests/oss_publication/test_distribution_artifact.py::test_built_artifacts_enforce_the_oss_boundary -q)

## R3 Installed client

An isolated installation of the exact wheel imports the application, exposes only
the OSS CLI and serves the bundled web client without Node or a source checkout.

(verify: python3 -m pytest tests/oss_publication/test_distribution_artifact.py::test_isolated_wheel_serves_the_bundled_client -q)

## R4 Standalone local value

A disposable Git workspace can open the local product and use governed work,
recovery, review, evidence and export surfaces without account, subscription or
Cowork configuration.

(verify: python3 -m pytest tests/actionable/test_disposable_workspace_journey.py tests/first_user/test_first_user_journey.py -q)

## R5 Cowork consent and acknowledgement boundary

A valid signed Cowork assignment remains a proposal after import, an invalid or
replayed envelope fails, and exactly one local run starts only after explicit local
confirmation plus exact acceptance and source-binding acknowledgements.

(verify: python3 -m pytest tests/actionable/test_inbox_workflow.py -q)

## R6 No Pro surface in OSS

The default application returns 404 for organization, fleet and Local Team routes;
the production browser bundle contains no navigation or API call to those surfaces.

(verify: python3 -m pytest tests/oss_publication/test_public_surface.py -q)

## R7 Publication hygiene

Tracked public files contain no credential material, machine-local absolute path,
private repository URL, private Git metadata or generated runtime identity.

(verify: python3 -m pytest tests/oss_publication/test_publication_contract.py::test_publication_hygiene_fails_closed -q)

## R8 Accurate product documentation

README states in English the contract-driven before/after value, standalone local
journey, optional Cowork journey, local-data boundary and explicit exclusions, and
all release-facing links are absolute public URLs.

(verify: python3 -m pytest tests/oss_publication/test_publication_contract.py::test_readme_describes_the_real_product_and_uses_public_links -q)

## R9 Candidate-bound release evidence

A machine-readable release record binds the attested source commit, clean public
candidate commit, wheel and sdist hashes, and every release verification command.
The record version must equal package metadata; placeholder or mutable identifiers
fail the gate. The release gate also exercises real-workspace adapter and API smoke
paths without depending on a checkout directory name or a sibling repository.

(verify: python3 -m pytest tests/oss_publication/test_release_evidence.py tests/test_adapter.py::test_adapter_reads_real_apatch_workspace tests/test_api.py::test_authenticated_real_workspace_smoke -q)

## Traceability

| RFP acceptance | SPEC requirement | Status |
| --- | --- | --- |
| OSSPUB-1 | R1 | covered |
| OSSPUB-2 | R2 | covered |
| OSSPUB-3 | R3 | covered |
| OSSPUB-4 | R4 | covered |
| OSSPUB-5 | R5 | covered |
| OSSPUB-6 | R6 | covered |
| OSSPUB-7 | R7 | covered |
| OSSPUB-8 | R8 | covered |
| OSSPUB-9 | R9 | covered |
