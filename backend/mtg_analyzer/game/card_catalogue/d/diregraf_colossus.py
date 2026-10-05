from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _diregraf_colossus() -> list[AbilitySpec]:
    """This creature enters with a +1/+1 counter on it for each Zombie card in your graveyard.
    Whenever you cast a Zombie spell, create a tapped 2/2 black Zombie creature token.

    — PLAY-ALL Step 2 (Wretched Ranks). The cast trigger is the parser's own claim. The entry counters are Boss's
    Chauffeur's `enters_with_counters_count` static over a structured graveyard count.
    """
    return [
        AbilitySpec("static", [EffectSpec("enters_with_counters_count", {
            "kind": "+1/+1", "base": 0, "count_selector": {
                "zone": "graveyard", "of": "you", "filter": {"subtype": "zombie"}},
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 2, "toughness": 2, "colors": ["B"], "subtypes": ["Zombie"],
                "keywords": [], "token_name": "Zombie", "tapped": True,
            })],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}, "spell_filter": {"subtype": "zombie"}},
        ),
    ]


register("Diregraf Colossus", _diregraf_colossus)
