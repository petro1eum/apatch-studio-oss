"""Offline synthetic calculation through the real native SDK lifecycle.

This fixed demonstration worker is not an LLM and claims no human/AI split.
It accepts only the already frozen sample calculation and current signed source
references in Studio's ordinary prompt. No acceptance, payment or stop is signed.
"""
import csv
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    if sys.platform != 'linux' or os.getuid() != 1000:
        raise RuntimeError('Only the contained unprivileged demo executor is supported')
    prompt = sys.stdin.read(131073)
    if len(prompt) > 131072:
        raise RuntimeError('Bounded exact prompt required')
    def field(name):
        matches = [line[len(name)+1:] for line in prompt.splitlines() if line.startswith(name+'=')]
        if len(matches) != 1:
            raise RuntimeError('Unique native '+name+' required')
        return matches[0]
    contract = json.loads(field('sdd_contract_json'))
    envelope = json.loads(field('task_envelope_json'))
    artifacts = json.loads(field('source_binding_artifacts_json'))
    actor = field('actor_id')
    root = Path.cwd()
    if (envelope['requirement'] not in {'SPEC-COWORK-DEMO-1#R1','SPEC-COWORK-DEMO-CONTINUATION-1#R1'}
            or envelope['allowed_writes'] != ['result.json']
            or contract != json.loads((root/'.apatch/sdd_verification_contract.json').read_text())
            or (root/'result.json').exists()):
        raise RuntimeError('The unchanged frozen synthetic task and empty result are required')
    private = root/'.apatch/native-worker'
    private.mkdir(mode=0o700,exist_ok=True)
    sys.path.insert(0,'/opt/native-sdk')
    from apatch.mcp import server
    def call(name, **kwargs):
        value = getattr(server, name)(target_dir=str(root), **kwargs)
        # Private retained diagnostics include session capabilities. Never emit them.
        path=private/(name+'.json')
        with path.open('x') as output:json.dump(value,output,default=str)
        path.chmod(0o600)
        if not value.get('ok'):
            raise RuntimeError(name+' refused: '+str(value.get('error_type') or value.get('code') or value.get('error')))
        print(json.dumps({'type':'demo.native_step','step':name,'ok':True}),flush=True)
        return value
    opened=call('apatch_session_start',requirement=envelope['requirement'],
                artifacts=artifacts,sdd_contract=contract,task_envelope=envelope,actor_id=actor)
    session=opened.get('session_capability',opened)
    binding=dict(governed_session_id=session['session_id'],session_token=session['session_token'])
    with (root/'demo/stock.csv').open() as source:rows=list(csv.DictReader(source))
    result={'source':'synthetic-interfera-demo.csv','recommendations':[
        {'sku':row['sku'],'reorder_qty':max(0,int(row['reorder_point'])-int(row['on_hand']))} for row in rows]}
    if envelope['requirement']=='SPEC-COWORK-DEMO-CONTINUATION-1#R1':
        raw=(root/'demo/carried_result.json').read_bytes()
        prior=json.loads(raw)
        stock={r['sku']:int(r['on_hand']) for r in rows}
        with (root/'demo/demand.csv').open() as source:demand={r['sku']:r for r in csv.DictReader(source)}
        plan=[]
        for row in prior['recommendations']:
            sku=row['sku'];daily=int(demand[sku]['daily_demand']);lead=int(demand[sku]['lead_days'])
            coverage=stock[sku]/daily
            plan.append({'sku':sku,'reorder_qty':row['reorder_qty'],'daily_demand':daily,'lead_days':lead,
                'coverage_days':coverage,'latest_order_in_days':max(0,coverage-lead),
                'urgent':coverage<=lead and row['reorder_qty']>0})
        result={'source':'synthetic-continuation-demo','carried_sha256':'sha256:'+hashlib.sha256(raw).hexdigest(),
            'delivery_plan':plan,'total_units_to_order':sum(r['reorder_qty'] for r in prior['recommendations']),
            'assumptions':['Synthetic daily demand and lead times; no real purchases.',
                'Quantities retained from the transferred result; urgency calculated separately.']}
    spec_id=envelope['requirement'].split('#')[0]
    call('apatch_execute_next',spec=spec_id,requirement='R1',
         needles=[dict(action='create',target_file='result.json',content=json.dumps(result,indent=2)+'\n')],**binding)
    # execute_next finalization executes frozen tests, falsification, verify,
    # genuine attestation and session close; it never accepts a customer result.
    value=server.apatch_execute_next(target_dir=str(root),spec=spec_id,requirement='R1',
        finalize=True,completion_summary='Calculated a synthetic procurement result under the exact frozen scope; any transferred quantities retain their source hash.',**binding)
    path=private/'finalization.json';path.write_text(json.dumps(value,default=str));path.chmod(0o600)
    if not value.get('ok'):raise RuntimeError('Native finalization refused: '+str(value.get('error_type') or value.get('error')))
    print(json.dumps({'type':'demo.native_result','status':'attested','synthetic':True}),flush=True)


if __name__=='__main__':main()
