from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _illusionist_s_gambit() -> list[AbilitySpec]:
    """Cast this spell only during the declare blockers step on an opponent's turn.
    Remove all attacking creatures from combat and untap them. After this phase, there is an additional combat
    phase. Each of those creatures attacks that combat if able. They can't attack you or planeswalkers you
    control that combat.

    — Peace Offering deck batch. The timing line is a new ``cast_timing_restriction`` shape
    (``declare_blockers`` on an opponent's turn, read by `GameEngine.can_cast`). The body: `tap` over the
    attacking creatures with ``untap`` and the new ``remove_from_combat`` (RULE 506.4 — and the group is left as
    the referent of "those creatures"); `extra_combat_phase` ("after this phase", queued and drained by the turn
    loop); `pump` giving that referent a temporary ``attacks_if_able`` (a requirement for the additional combat,
    since the declaration of the current one is over); and `prevent_attacking_player_this_turn` in its
    ``reversed`` form, barring the active player from attacking you for the rest of the turn — which is exactly
    "that combat", the only one they can still declare attackers in.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("tap", {
                    "selector": "attacking_creatures", "untap": True, "remove_from_combat": True,
                }),
                EffectSpec("extra_combat_phase", {}),
                EffectSpec("pump", {"previous_subject": True, "keywords": ["attacks_if_able"]}),
                EffectSpec("prevent_attacking_player_this_turn", {"reversed": True}),
            ],
            cast_timing_restriction={"step": "declare_blockers", "opponents_turn": True},
        ),
    ]


register("Illusionist's Gambit", _illusionist_s_gambit)
