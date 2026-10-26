"""Execute actual TypeScript state logic; wiring assertions are text-only."""
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def test_exit_zero_and_foreign_or_empty_evidence_never_mean_tests_passed():
    source=(ROOT/'frontend/src/productLanguage.ts').as_uri()
    script=f'''import {{exactLocalVerificationState as state,changeState}} from {json.dumps(source)};
const proof={{run_id:'current',attestation_count:1,contribution_event_count:1}};
console.log(JSON.stringify([
state('succeeded','current',null),state('succeeded','current',{{...proof,run_id:'old'}}),
state('succeeded','current',{{...proof,attestation_count:0}}),
state('succeeded','current',{{...proof,contribution_event_count:0}}),
state('succeeded','current',proof),state('running','current',proof),state(null,null,null),
changeState({{status:'succeeded',mode:'requirement',plan_handoff:null,contribution:null}})]));'''
    run=subprocess.run(['node','--experimental-strip-types','--input-type=module','-e',script],
        cwd=ROOT,capture_output=True,text=True,check=True)
    assert json.loads(run.stdout)==['finished','finished','finished','finished','verified','running','notRun',
        {'label':'Execution finished','tone':'info'}]


def test_inbox_uses_current_evidence_not_exit_code_and_clears_old_proof():
    source=(ROOT/'frontend/src/ExactContractDeliveryInbox.tsx').read_text()
    assert 't[exactLocalVerificationState(runStatus, delivery?.run_id ?? null, evidence)]' in source
    assert 'runStatus === "succeeded" ? t.verified' not in source
    assert 'result.run_id !== delivery?.run_id' in source
    assert 'setEvidence(null); setPlan(null); setConsent(false); setPublication(null);' in source
    assert 'The agent finished. Prepare signed evidence' in source
    assert 'Агент завершил работу. Подготовьте подписанные доказательства' in source
