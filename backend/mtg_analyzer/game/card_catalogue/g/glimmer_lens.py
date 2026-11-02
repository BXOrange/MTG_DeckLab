from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _glimmer_lens() -> list[AbilitySpec]:
    """For Mirrodin! (When this Equipment enters, create a 2/2 red Rebel creature token, then attach this to it.)
    Whenever equipped creature and at least one other creature attack, draw a card.
    Equip {1}{W}

    — Commander Cube singleton batch. The ETB (token, then attach) is the parser's own claim. The attack draw is an
    ATTACKS trigger on the attached creature (`attached_permanent`, the Argentum Armor shape) with the
    `other_attackers_at_least` intervening-if (RULE 603.4, `game/binding/count_predicates.py`). Equip and For Mirrodin!
    are keyword-catalogue abilities, not authored here.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "power": 2, "toughness": 2, "colors": ["R"],
                                         "subtypes": ["Rebel"], "keywords": [], "token_name": "Rebel"}),
             EffectSpec("attach", {"target_kind": "created"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="when ~ enters, create a 2/2 red rebel creature token, then attach this to it.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"},
                     "other_attackers_at_least": 1},
        ),
    ]


register("Glimmer Lens", _glimmer_lens)
