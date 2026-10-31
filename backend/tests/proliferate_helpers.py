"""Explicit recipient selection for regressions formerly using auto-all."""
def choose_all_proliferate(engine):
    rules = getattr(engine, 'rules', engine)
    while (rules.state.pending_choice or {}).get('kind') == 'proliferate':
        option = next(o for o in rules.state.pending_choice['options'] if o['id'] != 'decline')
        rules.resolve_choice(option['id'])
        if not rules.state.pending_choice:
            while rules.resume_deferred_effects() and not rules.state.pending_choice:
                pass
