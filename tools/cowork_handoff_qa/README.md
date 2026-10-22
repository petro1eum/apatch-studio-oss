# One new Linux handoff QA run

Status: the source stop/duplicate/fence/transfer path has now run on the server for one separately agreed QA task; successor execution remains open. This is a deterministic
operator runner for one newly agreed QA task. It uses the existing native
ExactContractManager, full-delivery source acknowledgement, AgentRunManager and
RunStore. The native key remains in its enrolled workspace. The work process runs
only in the admitted Linux/runsc container. It never calls an LLM, produces a
completion attestation, or claims that an older Mac run was contained.

The two small Studio extension points retain the public codex/claude request
schema. They allow a trusted headless request model to survive journal restore and
allow already validated source references to reach a fixed runner without an MCP
configuration. `execution_source_artifacts` and current native guard are unchanged.
A new `apr` is allocated and durably saved by the ordinary manager before waiting
at most 240 seconds for root admission. The adapter revalidates current native
and signed source authority after that wait. Root checks the run and complete
admission hash again before starting its precreated container. No caller supplies
an arbitrary host, shell command, container, signing key or stop observation.

## Local verification

Run with the installed current native SDK, not the older source checkout under
`TASKROOT/apatch` (that checkout lacks the current source-reference resolver):

```sh
cd /Users/edcher/Documents/Codex/2026-10-21/cowork-full-release/studio-residuals
PYTHONPATH=. /Users/edcher/.local/share/apatch/runtimes/0.8.52-studio-0.1.6/bin/python -m pytest -q tools/cowork_handoff_qa/test_qa_handoff.py tools/cowork_handoff_qa/test_qa_native_lifecycle.py tools/cowork_handoff_qa/test_qa_cli_pins.py
PYTHONPATH=. /Users/edcher/.local/share/apatch/runtimes/0.8.52-studio-0.1.6/bin/python -m pytest -q tests/test_agent_runs.py tests/test_work_handoff_stop.py tests/test_exact_source_runner_binding.py tests/test_exact_handoff_renewal.py tests/test_exact_contract_artifacts.py tests/test_cdd_transfer_runtime.py
```

The contour suite uses actual durable journals, a real local child process,
actual Core Change/source receipts with public RFC8032 test key material, the SDK
source/SPEC validator and the actual Platform ACK verifier. Current network
admission, Docker and kernel observations are test doubles. It is not evidence of
server execution. Original stop/fence tests are preserved unchanged.

## Concrete next runtime step (root operator)

1. Review/install the exact five files in `installation.prepared.json` at
   `/opt/trustchain-cowork-handoff-qa`, root-owned and not writable by the performer.
   Preserve the two reused Studio modules byte-for-byte. Create the root-only
   state directory `/var/lib/trustchain-cowork-handoff-qa` mode 0700. Provision a
   distinct raw Ed25519 observer key only after reviewing this package. The CLI
   has no key-generation or arbitrary signing command. Interpreter and
   `cryptography` dependency must also be root controlled. An exact sudo rule may
   permit only the fixed `python3 -I -B .../qa_handoff_cli.py` entry, never an
   arbitrary interpreter, shell, environment or module path.
2. Before allocating the short-lived native run, prepare a pinned Linux Python
   image with `Dockerfile.qa-work` and `qa_handoff_work.py`; the supplied QA_BASE
   must be a reviewed digest. Prepare one empty QA workspace owned UID1000 and a
   persistent dedicated cgroup-v2 slice. Read its actual systemd `ControlGroup`
   and kernel boot ID. Do not infer a cgroup path from a unit name.
3. Through the existing product workflow create a NEW disposable task and
   bilateral exact contract explicitly authorizing this deterministic Linux stop
   scenario. Use a fresh enrolled native QA workspace, normal current consents
   and a current downloaded exact bundle. The contract must admit ordinary
   full-delivery source preparation. This test deliberately stops before
   attestation/delivery. Do not reuse the accepted v6 task or the U16 install task.
4. Start this actual headless session with a PTY and keep it open:

```sh
TASKROOT=/Users/edcher/Documents/Codex/2026-10-21/cowork-full-release
PYTHONPATH="$TASKROOT/studio-residuals" \
  /Users/edcher/.local/share/apatch/runtimes/0.8.52-studio-0.1.6/bin/python -B \
  "$TASKROOT/studio-residuals/tools/cowork_handoff_qa/qa_native_cli.py" \
  --workspace "$TASKROOT/handoff-native-qa-workspace" \
  --state-root "$TASKROOT/handoff-native-qa-state" \
  --trust-file /Users/edcher/.config/apatch-studio/trustchain-production-exact-contract.json \
  --bundle "$TASKROOT/handoff-native-qa-bundle.json" \
  --requirement 'SPEC-COWORK-QA-STOP#R1'
```

The workspace, bundle and requirement above are the new agreed QA inputs, not
already existing production artifacts. `awaiting_root_admission` contains the
actual native `apr`, retained execution scope, canonical binding and workspace
ID. The program does not accept a manually selected `apr`.

5. Within the 240-second wait, root precreates one container using that actual
   run ID: pinned image/argv; `--runtime runsc --network none --read-only`, UID
   `1000:1000`, `--cap-drop ALL --security-opt no-new-privileges`, `--restart no`,
   private PID/IPC/cgroup namespaces, bounded memory/PIDs, the dedicated cgroup
   parent, and exactly one private writable `/workspace` bind. Set labels
   `tc.handoff.run_id=<actual apr>` and `tc.handoff.scope_hash=<canonical scope
   hash>`. Root writes `admission.json` from the actual full Docker inspect,
   native journal/binding, cgroup and boot observations, with argv exactly:

```json
["/usr/local/bin/python", "-I", "-B", "-u", "/opt/cowork-qa/work.py"]
```

The observer public key must differ from the native request key. Pin the prepared
program hash, one canonical binding, one actual native run, exact scope,
workspace, host and finite expiry. See `validate_admission` for the closed schema.
The adapter starts the container only after the real native/source recheck.
The ordinary local command `status` reports the retained native run. On Linux,
root `qa_handoff_cli.py status` is diagnostic only and never claims closure.

6. Root deploys the reviewed existing handoff candidate route/fence service and
   sets `TC_COWORK_QUALIFIED_STOP_OBSERVERS` to the same observer public admission.
   This is a separate product deployment: the currently installed invited release
   intentionally omitted the dormant handoff candidate. Do not patch the live
   database or broaden performer routes. Owner requests handoff on the NEW task.
7. Enter `stop` in the native session. Its existing signed WorkHandoffDelivery
   query obtains the exact current request. The first `stop_pending` output
   exposes `authority_query` with scope and inventory only. Root independently
   verifies that query and retains it as `<tcwh_id>.authority.json` in the root
   state directory (0600). Repeat `stop`. The root CLI compares both exact query
   and server acknowledgement hashes, fences before signalling, drains recursive
   cgroups and attach process group, then signs the measured ACK. The unchanged
   native transport submits it to the existing Platform verifier. No user field
   supplies `stopped`, a process count or a signature.
8. For an ACK retry after server acceptance, retain the fresh native query with
   its now non-null acknowledgement hash. Duplicate ACK bytes remain identical
   and require fresh containment. Verify that relaunch/retry under the old root
   admission is denied. Owner completes handoff using the existing product route;
   the successor gets its own task, agreement, consent and native admission.
   No prior accepted result may be altered.

If the native controller exits, the existing RunStore marks active work
interrupted. Closing SSH is never proof of stop. A new invocation with the same
workspace/state and `--resume-stop <retained tceh_id>` instead of
`--bundle/--requirement` restores only the exact observer and can deliver the stop
through the current signed native query. It never relaunches the container.

A real Linux positive, recursive drain, repeat/denial and successor launch still
must be collected before U15-03 is reported complete. This package alone does not
close U15 or the full release.

## 2026-10-23 actual qualification

The real first image failed before starting the work process because its fixed Python argv was absent. The corrected image retains the exact work bytes and adds the interpreter alias; a real runsc smoke proves Python and required imports before admission. Never reuse/reset that failed root instance. The successful retry used a separate root instance, admission, cgroup and observer key.

A real native retry exposed the need to select the existing exact manager's immutable retry lineage both during dispatch and stop-only restoration. The adapter now uses that resolver. Diagnostic SSH uses DEVNULL so it cannot swallow an interactive native command. The headless `--retry-run` always allocates through the ordinary native manager and retains the original association. `--resume-stop` follows the actual current retry leaf without starting it. 118 current contour/native regression tests pass; existing assertions are preserved.

The actual website transfer request, complete cgroup/attach quiescence, exact duplicate ACK, durable relaunch denial and successor creation are recorded under Platform verification `cowork-native-stop-20261023`. A second consent or a new execution is not inherited by the successor.
