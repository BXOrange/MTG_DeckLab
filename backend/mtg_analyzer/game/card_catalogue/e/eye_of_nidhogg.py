from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eye_of_nidhogg() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature is a black Dragon with base power and toughness 4/2, has flying and deathtouch, and is goaded. (It attacks each combat if able and attacks a player other than you if able.)
    When Eye of Nidhogg is put into a graveyard from the battlefield, return it to its owner's hand.

    — PLAY-ALL (Scions & Spellcraft). Enchant is a keyword. The static layers: `type_change` ``set_subtypes`` (Dragon replaces its
    creature types), `color_change`, `pt_set` 4/2, `grant_keyword`, and the standing `goaded` static. The return is the
    parser's self-dies `return_to_hand`.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("type_change", {"affects": "attached_permanent", "set_subtypes": ["Dragon"]}),
                EffectSpec("color_change", {"affects": "attached_permanent", "colors": ["B"]}),
                EffectSpec("pt_set", {"affects": "attached_permanent", "power": 4, "toughness": 2}),
                EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["flying", "deathtouch"]}),
                EffectSpec("goaded", {"affects": "attached_permanent"}),
            ],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {"target_kind": None})],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Eye of Nidhogg", _eye_of_nidhogg)
