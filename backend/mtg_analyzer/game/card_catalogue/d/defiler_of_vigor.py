from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: RULE 110.4 — every permanent type; "permanent spell" is a spell of any of these.
_PERMANENT_TYPES = ["creature", "artifact", "enchantment", "land", "planeswalker", "battle"]


def _defiler_of_vigor() -> list[AbilitySpec]:
    """Trample
    As an additional cost to cast green permanent spells, you may pay 2 life.
    Those spells cost {G} less to cast if you paid life this way. This effect
    reduces only the amount of green mana you pay.
    Whenever you cast a green permanent spell, put a +1/+1 counter on each
    creature you control.

    — PLAY-ALL Step 2 (Kodama). Trample is the keyword fold-in. The optional
    life cost uses the `pip_life_option` static. Affordability probes consider
    either payment; casting prompts for the additional life payment before
    paying costs, even when green mana is available. Each paid instance reduces
    only the green mana cost. The trigger's `any_of` permanent-types filter
    prevents green instants and sorceries from receiving counters.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("pip_life_option", {
                "color": "G", "pips": 1, "spell_color": "G", "spell_type": _PERMANENT_TYPES,
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "+1/+1", "selector": "each_creature_you_control", "count": 1})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "you"},
                "spell_filter": {
                    "color": "G",
                    "any_of": [{"card_type": t} for t in _PERMANENT_TYPES],
                },
            },
        ),
    ]


register("Defiler of Vigor", _defiler_of_vigor)
