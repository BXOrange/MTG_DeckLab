from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _teferi_master_of_time() -> list[AbilitySpec]:
    """You may activate loyalty abilities of Teferi on any player's turn
    any time you could cast an instant.
    +1: Draw a card, then discard a card.
    −3: Target creature you don't control phases out.
    −10: Take two extra turns after this one.

    — MEC-43. The instant-speed activation clause reuses The Wandering
    Emperor's own `conditional_flash` mechanism (`GameEngine._can_
    activate_loyalty`), just with MEC-44's already-shipped
    ``"unconditional": True`` member (Necromancy's own "as though it had
    flash" with no gate at all) instead of Emperor's own "entered this
    turn" gate — carried on the first loyalty ability below, the same
    "`effect_binder.attach_to_object` scans every spec regardless of
    which one carries it" convention Emperor's own entry documents.
    −3 is `PhaseOutEffect(target_kind="creature_you_dont_control")`
    (already-general). −10 is `TakeExtraTurnEffect` listed twice — it
    has no ``count`` param, so "two" is just two queued turns.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1}), EffectSpec("discard", {"count": 1})],
            cost={"loyalty": 1},
            conditional_flash={"unconditional": True},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("phase_out", {"target_kind": "creature_you_dont_control"})],
            cost={"loyalty": -3},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("take_extra_turn", {}), EffectSpec("take_extra_turn", {})],
            cost={"loyalty": -10},
        ),
    ]


register("Teferi, Master of Time", _teferi_master_of_time)
