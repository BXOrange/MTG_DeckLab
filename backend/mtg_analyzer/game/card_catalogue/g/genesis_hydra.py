from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: RULE 110.4's nonland permanent types — a "nonland permanent card" is a card of any of these.
_NONLAND_PERMANENT_TYPES = ["creature", "artifact", "enchantment", "planeswalker", "battle"]


def _genesis_hydra() -> list[AbilitySpec]:
    """When you cast this spell, reveal the top X cards of your library. You may
    put a nonland permanent card with mana value X or less from among them onto
    the battlefield. Then shuffle the rest into your library.
    This creature enters with X +1/+1 counters on it.

    — PLAY-ALL Step 2 (Raggadragga / Hydranten). The dig is PAR-144's
    `inspect_top_choose` (the grammar deliberately refuses ``x``, so it is
    authored here): ``count: x`` and a ``max_mana_value: x`` criteria bound to the
    spell's announced X (`_resolved_criteria` reads `x_paid` for the one that
    `_substitute_x` does not reach), ``rest_destination: library_shuffled``. The
    counters come from the oracle text's enters-with-X clause.
    The self-cast trigger functions from the stack and resolves independently
    of the creature spell, retaining the announced X even if it is countered.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("inspect_top_choose", {
                "count": "x", "action": "library_to_battlefield", "optional": True, "max_picks": 1,
                "criteria": {"type": list(_NONLAND_PERMANENT_TYPES), "max_mana_value": "x"},
                "rest_destination": "library_shuffled",
            })],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "self"}},
        ),
    ]


register("Genesis Hydra", _genesis_hydra)
