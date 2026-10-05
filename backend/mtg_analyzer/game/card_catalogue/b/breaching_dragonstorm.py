from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


#: The dig exiles "until you exile a nonland card" — no mana-value bound (any value is below this).
_NO_MANA_VALUE_LIMIT = 1_000_000

#: "…if that spell's mana value is 8 or less."
_CAST_LIMIT = 8


def _breaching_dragonstorm() -> list[AbilitySpec]:
    """When this enchantment enters, exile cards from the top of your library until you exile a nonland
    card. You may cast it without paying its mana cost if that spell's mana value is 8 or less. If you
    don't, put that card into your hand.
    When a Dragon you control enters, return this enchantment to its owner's hand.

    — Reign of Dragons deck batch. The return trigger is the parser's own claim. The ETB is the discover
    machinery (exile to a nonland, cast free *or* take it, the rest to the bottom) with the new
    ``cast_limit``: the mana-value bound on the cast is 8 and no bound on the dig itself, so a hit above
    8 can only go to the hand.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("discover", {"mana_value": _NO_MANA_VALUE_LIMIT, "cast_limit": _CAST_LIMIT})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {"target_kind": None})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": False, "subtypes": ["dragon"], "nontoken": False,
            }},
        ),
    ]


register("Breaching Dragonstorm", _breaching_dragonstorm)
