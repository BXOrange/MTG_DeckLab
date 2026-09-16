from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _magda_the_hoardmaster() -> list[AbilitySpec]:
    """Whenever you commit a crime, create a tapped Treasure token. This
    ability triggers only once each turn. (Targeting opponents, anything
    they control, and/or cards in their graveyards is a crime.)
    Sacrifice three Treasures: Create a 4/4 red Scorpion Dragon creature
    token with flying and haste. Activate only as a sorcery.

    — Imodane deck batch. The sacrifice ability already parses on its
    own — reproduced verbatim. **Documented simplification**: "whenever
    you commit a crime" (RULE 701.53 — targeting an opponent, anything
    they control, or a card in their graveyard) isn't modeled — no
    single event unifies "any targeting effect resolving against
    anything opponent-owned" across every effect family in this engine
    (damage, destroy, exile, counter-removal, graveyard recursion, …), so
    the trigger never fires; the treasure-cost payoff still works once
    Treasures exist from any other source.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 4, "toughness": 4, "colors": ["R"],
                "subtypes": ["Scorpion", "Dragon"], "keywords": ["flying", "haste"],
                "token_name": "Scorpion Dragon",
            }), EffectSpec("sorcery_speed_marker", {})],
            cost={"text": "Sacrifice three Treasures"},
        ),
    ]


register("Magda, the Hoardmaster", _magda_the_hoardmaster)
