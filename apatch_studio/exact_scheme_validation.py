"""Bounded, non-executable plan delta validation for native scheme imports."""
PHASES = ('component', 'integration', 'deployment', 'usage')


def validate_plan_delta(source, plan, envelopes):
    def need(condition):
        if not condition:
            raise ValueError('Invalid or scope-changing acceptance scheme')
    need(type(plan) is dict and set(plan) == set(source))
    need(all(plan[k] == source[k] for k in source if k != 'checks'))
    checks = plan['checks']
    original = {c['check_id']: c for c in source['checks']}
    need(type(checks) is list and len(checks) == len(original)
         and {c.get('check_id') for c in checks} == set(original))
    refs, phases = {}, {}
    def references(c, depth=0, count=None):
        count = count if count is not None else [0]
        count[0] += 1
        need(depth <= 8 and count[0] <= 128)
        if c is None:
            need(depth == 0)
            return set()
        need(type(c) is dict)
        if c.get('kind') == 'check':
            need(set(c) == {'kind', 'check_id'} and c['check_id'] in original)
            return {c['check_id']}
        if c.get('kind') == 'if':
            need(set(c) == {'kind', 'condition', 'then', 'otherwise'} and c['condition'] in original)
            return {c['condition']} | references(c['then'], depth+1, count) | references(c['otherwise'], depth+1, count)
        need(set(c) == {'kind', 'terms'} and c.get('kind') in {'all_of', 'any_of'}
             and type(c['terms']) is list and 0 < len(c['terms']) <= 32)
        return set().union(*(references(t, depth+1, count) for t in c['terms']))
    for c in checks:
        need(type(c) is dict and set(c) == {'check_id', 'requirement', 'phase', 'requires', 'max_attempts', 'timeout_seconds'})
        need(c['requirement'] == original[c['check_id']]['requirement'] and c['phase'] in PHASES)
        selected = [e for e in envelopes.values() if e['requirement'] == c['requirement']]
        need(len(selected) == 1 and c['check_id'] in selected[0]['checks'])
        need(type(c['max_attempts']) is int and 1 <= c['max_attempts'] <= 10
             and type(c['timeout_seconds']) is int and 1 <= c['timeout_seconds'] <= min(300, selected[0]['budgets']['seconds']))
        refs[c['check_id']], phases[c['check_id']] = references(c['requires']), PHASES.index(c['phase'])
    need(all(phases[r] <= phases[c] for c, values in refs.items() for r in values))
    left, done = set(original), set()
    while left:
        ready = {c for c in left if refs[c] <= done}
        need(bool(ready))
        left -= ready
        done |= ready
