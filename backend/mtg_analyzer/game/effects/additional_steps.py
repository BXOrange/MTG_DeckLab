"""State-owned requests to insert steps into the current turn."""
from .core import GameEffect


class AdditionalEndStepEffect(GameEffect):
    """RULE 500.9: insert after the currently resolving end step."""

    def __init__(self, only_first=False, source=None):
        super().__init__(source)
        self.only_first = only_first

    def apply(self, context, targets=None):
        state = context.state
        if state.current_step != 'end':
            return
        if self.only_first and state.end_steps_this_turn != 1:
            return
        state.pending_extra_end_steps += 1


class AdditionalBeginningPhaseEffect(GameEffect):
    """RULE 500.8: "there is an additional beginning phase after this phase" (Cyclonus, Cybertronian Fighter).

    An effect can't reach `GameEngine._turn_steps`, so it queues the request on the state and
    `GameEngine.advance_step` inserts the phase directly after the current one."""

    def apply(self, context, targets=None):
        context.state.pending_extra_beginning_phases += 1
