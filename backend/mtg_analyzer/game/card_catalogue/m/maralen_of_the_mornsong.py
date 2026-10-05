from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _maralen_of_the_mornsong() -> list[AbilitySpec]:
    """Players can't draw cards.
    At the beginning of each player's draw step, that player loses 3 life,
    searches their library for a card, puts it into their hand, then
    shuffles.

    — MEC-43 round 4F. Both clauses were nearly free once diagnosed
    against Omen Machine (MEC-33), which already built the identical
    "Players can't draw cards. At the beginning of each player's draw
    step, …" template. (1) The flat `draw_limit` static at
    `max_per_turn=0` needs no new code at all — same as Omen Machine's own
    first clause. (2) The replacement action reuses Omen Machine's own
    unscoped `STEP_BEGIN`/"draw" trigger (only the active player ever has
    a draw step, so leaving it unnarrowed by `phase_relation` already
    fires it once per turn, for whoever that is — RULE 500.7). Its body
    needed exactly one new selector: `LoseLifeEffect.selector` gained
    `"active_player"` (mirroring `DealDamageEffect`'s own sentinel of the
    same name); `SearchLibraryEffect` needed nothing new at all — its
    untargeted `player` resolution (`apply`'s ``player = self.player or
    context.active_player``) already defaults to the active player
    whenever no explicit ``player`` is given, exactly what an unscoped
    "that player searches…" clause needs.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("draw_limit", {"max_per_turn": 0})],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {"amount": 3, "selector": "active_player"}),
                EffectSpec("search", {"criteria": "", "destination": "hand", "optional": False}),
            ],
            trigger={"event": "STEP_BEGIN", "filter": {"step": "draw"}},
        ),
    ]


register("Maralen of the Mornsong", _maralen_of_the_mornsong)
