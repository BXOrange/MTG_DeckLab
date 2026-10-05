from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: The tokens Fisher's Talent turns into one another — a 1/1 Fish becomes a 3/3 Shark (level 2), which becomes
#: an 8/8 Octopus (level 3). Each is a `create_token`/`substitute_token` definition.
_FISH = {"token_name": "Fish", "power": 1, "toughness": 1, "colors": ["U"], "subtypes": ["Fish"], "keywords": []}
_SHARK = {"token_name": "Shark", "power": 3, "toughness": 3, "colors": ["U"], "subtypes": ["Shark"], "keywords": []}
_OCTOPUS = {
    "token_name": "Octopus", "power": 8, "toughness": 8, "colors": ["U"], "subtypes": ["Octopus"], "keywords": [],
}


def _fisher_s_talent() -> list[AbilitySpec]:
    """(Gain the next level as a sorcery to add its ability.)
    At the beginning of your upkeep, look at the top card of your library. You may reveal it if it's a land card.
    Create a 1/1 blue Fish creature token if you revealed it this way. Then draw a card.
    {G}{U}: Level 2
    If you would create a Fish token, create a 3/3 blue Shark creature token instead.
    {2}{G}{U}: Level 3
    If you would create a Shark token, create an 8/8 blue Octopus creature token instead.

    — Peace Offering deck batch. The level-ups are the parser's own claims. The upkeep trigger is
    `peek_top_land_or_hand` with ``reveal_then``: the top card is shown to its owner, a land may be revealed, and
    the Fish is made only if it was; the draw follows once that choice is answered. The two replacements are the
    new `substitute_token` (gated on the Class level): they chain (RULE 616.1), so at level 3 a Fish becomes a
    Shark and then an Octopus.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("peek_top_land_or_hand", {"reveal_then": [{"type": "create_token", "params": _FISH | {"count": 1}}]}),
                EffectSpec("draw", {"count": 1}),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "activated", [EffectSpec("class_level", {"level": 2})],
            cost={"text": "{g}{u}", "sorcery_speed_only": True, "class_level": 2},
        ),
        AbilitySpec("replacement", [EffectSpec("substitute_token", {
            "from_token": "Fish", "to": _SHARK, "min_level": 2,
        })]),
        AbilitySpec(
            "activated", [EffectSpec("class_level", {"level": 3})],
            cost={"text": "{2}{g}{u}", "sorcery_speed_only": True, "class_level": 3},
        ),
        AbilitySpec("replacement", [EffectSpec("substitute_token", {
            "from_token": "Shark", "to": _OCTOPUS, "min_level": 3,
        })]),
    ]


register("Fisher's Talent", _fisher_s_talent)
