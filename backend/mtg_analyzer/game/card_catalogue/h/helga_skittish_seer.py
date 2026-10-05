from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _helga_skittish_seer() -> list[AbilitySpec]:
    """Whenever you cast a creature spell with mana value 4 or greater, you
    draw a card, gain 1 life, and put a +1/+1 counter on Helga.
    {T}: Add X mana of any one color, where X is Helga's power. Spend this
    mana only to cast creature spells with mana value 4 or greater or
    creature spells with {X} in their mana costs.

    — PLAY-ALL Step 2 (SpongeBob). The restricted mana ability is read off
    the oracle text (`mana_abilities_for`). The three-part trigger isn't
    claimed as one sentence, but each part is, on the identical head
    (``SPELL_CAST`` by you, ``spell_filter {card_type: creature,
    min_mana_value: 4}``) — so it is one triggered ability with the three
    effects in order: `draw`, `gain_life`, `add_counters` (on Helga herself,
    the trigger's source).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("gain_life", {"amount": 1}),
                EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"}),
            ],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_filter": {"card_type": "creature", "min_mana_value": 4},
            },
        ),
    ]


register("Helga, Skittish Seer", _helga_skittish_seer)
