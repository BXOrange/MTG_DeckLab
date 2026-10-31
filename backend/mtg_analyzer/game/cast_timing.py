"""Spell-local combat windows (RULE 506.7); permissions never override them."""
from ..models.game.events import EventType

_BEFORE_BLOCKERS = frozenset({'begin_combat', 'declare_attackers'})
_AFTER_BLOCKERS = frozenset({'declare_blockers', 'first_strike_damage', 'combat_damage', 'end_combat'})
_BEFORE_COMBAT = frozenset({'untap', 'upkeep', 'draw', 'main1'})


def combat_cast_window_allows(engine, player, restriction):
    state = engine.state
    if engine._turn_steps and engine._cursor:
        phase, _ = engine._turn_steps[engine._cursor - 1]
        if phase.skipped:
            return False
    if restriction.get('your_turn') and state.active_player is not player:
        return False
    if restriction.get('before_blockers'):
        if restriction.get('first_combat'):
            # RULE 506.7d-e: unqualified "before blockers" refers to the
            # first combat, including its preceding phases; extra combats
            # cannot reopen that window. A skipped first combat closes it
            # at the end of the precombat main phase.
            steps = engine._turn_steps
            if steps and engine._cursor:
                first = next((phase for phase, _ in steps if phase.name == 'combat'), None)
                if first is None:
                    return state.current_step in _BEFORE_COMBAT
                point = next((i for i, (phase, step) in enumerate(steps)
                              if phase is first and (step.name == 'declare_blockers' or first.skipped)), None)
                if point is None:
                    point = next((i for i, (phase, step) in enumerate(steps)
                                  if phase is first and step.name == 'combat_damage'), len(steps))
                return engine._cursor - 1 < point
            return state.current_step in _BEFORE_COMBAT | _BEFORE_BLOCKERS
        if state.current_step not in _BEFORE_BLOCKERS:
            return False
    if restriction.get('after_blockers'):
        if state.current_step not in _AFTER_BLOCKERS:
            return False
        # RULE 506.7f: a skipped declare-blockers step never opens the
        # after-blockers window, even when end of combat still occurs.
        if engine._turn_steps and engine._cursor:
            for event in reversed(state.event_log):
                if event.type == EventType.STEP_BEGIN:
                    if event.get('step') == 'declare_blockers':
                        break
                    if event.get('step') == 'begin_combat':
                        return False
            else:
                return False
    if state.current_step == 'declare_blockers' and not all_blockers_declared(engine):
        return False
    return True


def all_blockers_declared(engine) -> bool:
    """RULE 509.1 / 509.2: every defending player has finished declaring blockers, so the declare blockers
    step's first priority window (and an attacker's "unblocked" status, RULE 509.1h) exists."""
    state = engine.state
    defenders = {defender.id for obj in state.battlefield
                 if getattr(obj, 'attacking', False)
                 and (defender := engine._defending_player(obj.combat_defender)) is not None
                 and not defender.is_dummy}
    return defenders <= state.declared_blockers_this_combat
