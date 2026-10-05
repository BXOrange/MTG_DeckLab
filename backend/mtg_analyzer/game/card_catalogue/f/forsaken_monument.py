from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _forsaken_monument() -> list[AbilitySpec]:
    """Colorless creatures you control get +2/+2.
    Whenever you tap a permanent for {C}, add an additional {C}.
    Whenever you cast a colorless spell, you gain 2 life.

    — Keen Engineering deck batch. The anthem and the life gain are the parser's own claims. The mana
    line is Crypt Ghast's triggered mana ability (RULE 605.1b) on `TAPPED_FOR_MANA` by you, gated by
    the new ``mana_produced_includes`` ({C} actually in the tap's ``produced`` payload).
    """
    return [
        AbilitySpec("static", [EffectSpec("anthem", {
            "power": 2, "toughness": 2, "affects": "creatures_you_control", "color": ["C"],
        })]),
        AbilitySpec(
            "triggered", [EffectSpec("add_mana", {"colors": ["C"]})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "controller": "you"},
                "mana_produced_includes": "C", "mana_ability": True,
            },
        ),
        AbilitySpec(
            "triggered", [EffectSpec("gain_life", {"amount": 2})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                     "spell_filter": {"colorless": True}},
        ),
    ]


register("Forsaken Monument", _forsaken_monument)
