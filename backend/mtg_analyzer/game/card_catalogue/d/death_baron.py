from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _death_baron() -> list[AbilitySpec]:
    """Skeletons you control and other Zombies you control get +1/+1 and have deathtouch.

    — PLAY-ALL Step 2 (Wretched Ranks). Two statics so "other" applies only to the Zombies: non-Zombie Skeletons
    through a structured selector (``subtype`` + ``without_subtype``), every other Zombie through the usual
    ``exclude_self`` subtype scope. A Zombie Skeleton is in the second group only, so it is buffed once.
    """
    skeletons = {"zone": "battlefield", "of": "you", "filter": {
        "card_type": "creature", "subtype": "skeleton", "without_subtype": "zombie"}}
    zombies = {"affects": "other_creatures_you_control", "subtype": "Zombie"}
    return [
        AbilitySpec("static", [
            EffectSpec("anthem", {"affects": skeletons, "power": 1, "toughness": 1}),
            EffectSpec("grant_keyword", {"affects": skeletons, "keywords": ["deathtouch"]}),
        ]),
        AbilitySpec("static", [
            EffectSpec("anthem", {**zombies, "power": 1, "toughness": 1}),
            EffectSpec("grant_keyword", {**zombies, "keywords": ["deathtouch"]}),
        ]),
    ]


register("Death Baron", _death_baron)
