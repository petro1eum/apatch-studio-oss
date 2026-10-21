"""Bounded, non-executable plan delta validation for native scheme imports."""
import re
from pathlib import PurePosixPath
from .acceptance_profiles import EXTENDED_SCHEMA, validate_environment, validate_inputs
PHASES = ('component', 'integration', 'deployment', 'usage')


def validate_plan_delta(source, plan, envelopes):
    def need(condition):
        if not condition:
            raise ValueError('Invalid or scope-changing acceptance scheme')
    extended=type(plan) is dict and plan.get('schema')==EXTENDED_SCHEMA
    need(type(plan) is dict and set(plan) == set(source) | ({'inputs'} if extended else set()))
    input_ids=set()
    if extended:
        need(set(plan)=={'schema','tenant_id','project_group_id','work_item_id','candidate_paths','fixture_assets','environment','checks','inputs'})
        need(isinstance(plan['tenant_id'],str) and 0<len(plan['tenant_id'])<=128
             and isinstance(plan['project_group_id'],str) and re.fullmatch(r'tcpg_[a-f0-9]{32}',plan['project_group_id'])
             and isinstance(plan['work_item_id'],str) and re.fullmatch(r'tcpwi_[a-f0-9]{32}',plan['work_item_id']))
        validate_environment(plan['environment'])
        input_ids={'input:'+key for key in validate_inputs(plan['inputs'],plan['work_item_id'])}
        def path(value):
            return (isinstance(value,str) and 0<len(value)<=256 and '\\' not in value and not any(ord(c)<32 for c in value)
                    and str(PurePosixPath(value))==value and not PurePosixPath(value).is_absolute()
                    and all(p not in {'.','..'} and not p.startswith('.') for p in PurePosixPath(value).parts))
        candidates=plan['candidate_paths'];fixtures=plan['fixture_assets']
        need(type(candidates) is list and 0<len(candidates)<=128 and all(path(p) for p in candidates) and len(set(candidates))==len(candidates))
        need(type(fixtures) is list and len(fixtures)<=128 and all(type(a) is dict and set(a)=={'path','sha256'} and path(a['path'])
             and isinstance(a['sha256'],str) and re.fullmatch(r'sha256:[a-f0-9]{64}',a['sha256']) for a in fixtures))
        need(len({a['path'] for a in fixtures})==len(fixtures) and not set(candidates)&{a['path'] for a in fixtures})
        need(all(plan[k]==source[k] for k in ('tenant_id','project_group_id','work_item_id','candidate_paths','fixture_assets')))
        need(plan['environment']['image_digest']==source['environment']['image_digest'])
    else:
        need(all(plan[k] == source[k] for k in source if k != 'checks'))
    checks = plan['checks']
    original = {c['check_id']: c for c in source['checks']}
    need(type(checks) is list and len(checks) == len(original)
         and all(type(c) is dict for c in checks) and {c.get('check_id') for c in checks} == set(original))
    need(not extended or 0<len(checks)<=100)
    need(not extended or all(not cid.startswith('input:') for cid in original))
    refs, phases = {}, {}
    def references(c, depth=0, count=None):
        count = count if count is not None else [0]
        count[0] += 1
        need(depth <= 8 and count[0] <= 128)
        if c is None:
            need(depth == 0)
            return set()
        need(type(c) is dict)
        if c.get('kind')=='input':
            need(extended and set(c)=={'kind','input_id'} and 'input:'+str(c['input_id']) in input_ids)
            return {'input:'+c['input_id']}
        if c.get('kind') == 'check':
            need(set(c) == {'kind', 'check_id'} and c['check_id'] in original)
            return {c['check_id']}
        if c.get('kind') == 'if':
            need(set(c) == {'kind', 'condition', 'then', 'otherwise'} and c['condition'] in set(original) | input_ids)
            return {c['condition']} | references(c['then'], depth+1, count) | references(c['otherwise'], depth+1, count)
        need(set(c) == {'kind', 'terms'} and c.get('kind') in {'all_of', 'any_of'}
             and type(c['terms']) is list and 0 < len(c['terms']) <= 32)
        return set().union(*(references(t, depth+1, count) for t in c['terms']))
    for c in checks:
        need(type(c) is dict and set(c) == {'check_id', 'requirement', 'phase', 'requires', 'max_attempts', 'timeout_seconds'})
        need(c['requirement'] == original[c['check_id']]['requirement'] and c['phase'] in PHASES)
        if extended:
            need(isinstance(c['check_id'],str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',c['check_id'])
                 and isinstance(c['requirement'],str) and re.fullmatch(r'SPEC-[A-Z0-9-]+#R[0-9]+',c['requirement']))
        selected = [e for e in envelopes.values() if e['requirement'] == c['requirement']] if envelopes is not None else []
        need(envelopes is None or (len(selected) == 1 and c['check_id'] in selected[0]['checks']))
        need(type(c['max_attempts']) is int and 1 <= c['max_attempts'] <= 10
             and type(c['timeout_seconds']) is int and 1 <= c['timeout_seconds'] <= (min(300, selected[0]['budgets']['seconds']) if envelopes is not None else 300))
        refs[c['check_id']], phases[c['check_id']] = references(c['requires']), PHASES.index(c['phase'])
    phases.update({key:0 for key in input_ids})
    need(all(phases[r] <= phases[c] for c, values in refs.items() for r in values))
    left, done = set(original), set(input_ids)
    while left:
        ready = {c for c in left if refs[c] <= done}
        need(bool(ready))
        left -= ready
        done |= ready
