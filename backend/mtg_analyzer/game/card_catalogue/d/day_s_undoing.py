from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _days_undoing() -> list[AbilitySpec]:
    """Each player shuffles their hand and graveyard into their library,
    then draws seven cards. If it's your turn, end the turn. (Exile all
    spells and abilities from the stack, including this card. Discard
    down to your maximum hand size. Damage wears off, and "this turn"
    and "until end of turn" effects end.)

    — MEC-12 (cEDH M-K). The first sentence is a `seq` of the RULE 701.20
    shuffle (`scope="each_player"`) and a mass `draw`
    (`selector="each_player"`) — ENG-37 B7 retired the fused `wheel` type it
    used to be. "If it's your turn, end the turn" is the
    ``is_your_turn`` `ConditionalEffect` gate wrapping
    `end_the_turn`/`EndTheTurnEffect` (RulesEngine can't reach
    `GameEngine._turn_steps`/`_cursor` directly, so it exiles the stack
    now and queues `GameState.end_turn_requested` for `GameEngine.
    advance_step` to drain — see both docstrings). "Including this card"
    is a trailing self-exile (``target_kind=None``), the same override
    `_apply_stack_item` already gives `ShuffleSelfIntoLibraryEffect` —
    without it this card would go to its owner's graveyard as normal
    resolution, not exile.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("seq", {"effects": [
                    {"type": "shuffle_hand_and_graveyard_into_library",
                     "params": {"scope": "each_player"}},
                    {"type": "draw", "params": {"selector": "each_player", "count": 7}},
                ]}),
                EffectSpec("end_the_turn", {}, condition={"is_your_turn": True}),
                EffectSpec("exile", {"target_kind": None}),
            ],
        ),
    ]


register("Day's Undoing", _days_undoing)
