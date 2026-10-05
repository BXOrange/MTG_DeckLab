from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Prismari "Artistry": instant/sorcery cast-matters payoffs
# ===========================================================================
# Engine: `PumpEffect.amount_from_count_selector_axis` now also governs the
# ``amount_from_trigger_event`` path (Renegade Bull's +X/+0).


def _prismari_pianist() -> list[AbilitySpec]:
    """Whenever you cast an instant or sorcery spell, create a 1/1 blue and
    red Elemental creature token. If that spell's mana value is 5 or greater,
    create three of those tokens instead.

    Modeled as two mana-value-gated SPELL_CAST triggers (<=4 -> 1 token,
    >=5 -> 3), exactly one of which fires per cast."""
    def _tok(count):
        return EffectSpec("create_token", {
            "count": count, "token_name": "Elemental", "power": 1, "toughness": 1,
            "colors": ["U", "R"], "subtypes": ["Elemental"],
        })
    base = {"subject": "group", "controller": "you"}
    return [
        AbilitySpec(
            "triggered", [_tok(1)],
            trigger={"event": EventType.SPELL_CAST, "condition": dict(base),
                     "spell_card_types": ["instant", "sorcery"],
                     "spell_mana_value_at_most": 4},
        ),
        AbilitySpec(
            "triggered", [_tok(3)],
            trigger={"event": EventType.SPELL_CAST, "condition": dict(base),
                     "spell_card_types": ["instant", "sorcery"],
                     "spell_mana_value_at_least": 5},
        ),
    ]


register("Prismari Pianist", _prismari_pianist)
