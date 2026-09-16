from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dark_confidant() -> list[AbilitySpec]:
    """At the beginning of your upkeep, reveal the top card of your
    library and put that card into your hand. You lose life equal to its
    mana value.

    — MEC-12 (cEDH staples 2). ENG-37 B5: `reveal_top` stashes the top card
    as the `revealed` referent, a `bind` measures its mana value, and the
    body puts it into hand + loses that much life. `put_revealed_card` is
    deliberately **not** routed through `DrawCardEffect`/`RulesEngine.draw`
    (RULE 121.4: a card entering hand without the printed word "draw" isn't
    a draw, so it must never trip a draw-replacement/"whenever you draw"
    trigger, or count toward cards drawn this turn — load-bearing for this
    exact cluster, since Alms Collector/Notion Thief/Chains of Mephistopheles
    all key off "would draw a card").
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "reveal_top", "params": {"whose": "you"}},
                {"type": "bind", "params": {
                    "name": "mv",
                    "amount": {"kind": "characteristic", "characteristic": "mana_value",
                               "of": "revealed"},
                    "effects": [
                        {"type": "put_revealed_card", "params": {"destination": "hand"}},
                        {"type": "lose_life", "params": {"amount": "$mv"}},
                    ],
                }},
            ]})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Dark Confidant", _dark_confidant)
