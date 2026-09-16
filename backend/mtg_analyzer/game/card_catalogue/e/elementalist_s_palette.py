from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _elementalists_palette() -> list[AbilitySpec]:
    """Whenever you cast a spell with {X} in its mana cost, put two charge
    counters on this artifact.
    {T}: Add one mana of any color.
    {T}: Add {C} for each charge counter on this artifact. Spend this mana
    only on costs that contain {X}.

    Only the {X}-cast trigger needs authoring; the two plain mana abilities
    fold in from the parser. Documented simplification: the second mana
    ability's "spend only on {X} costs" restriction is not modeled."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "charge", "count": 2})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_has_x": True,
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_mana", {"colors": ["ANY"]})],
            cost={"text": "{T}"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_mana", {
                "colors": ["C"], "amount_selector": "charge_counters_on_source",
            })],
            cost={"text": "{T}"},
        ),
    ]


register("Elementalist's Palette", _elementalists_palette)
