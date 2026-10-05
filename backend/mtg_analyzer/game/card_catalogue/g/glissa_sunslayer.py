from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _glissa_sunslayer() -> list[AbilitySpec]:
    """First strike, deathtouch
    Whenever Glissa Sunslayer deals combat damage to a player, choose one —
    • You draw a card and lose 1 life.
    • Destroy target enchantment.
    • Remove up to three counters from target permanent.

    — Eliferate deck batch. First strike/deathtouch come from the RULE 702
    keyword catalogue automatically. The modal trigger reuses `Bloodforged
    Battle-Axe`'s own "deals combat damage to a player" trigger shape
    (`filter={"combat": True, "is_player": True}`) plus a `triggered`-kind
    `modes` block — RULE 603.3's own "a triggered ability's mode(s) chosen
    as it's put on the stack" path, already shipped and used by parsed
    modal triggers, just not yet by a hand-authored one. The third mode's
    `remove_counters` with `max_count` is the exact primitive
    `RemoveCountersEffect`'s own docstring already names Glissa Sunslayer
    for — built for this card, never previously wired to it.
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
            modes={
                "options": [
                    [
                        EffectSpec("draw", {"count": 1}),
                        EffectSpec("lose_life", {"amount": 1}),
                    ],
                    [EffectSpec("destroy", {"target_kind": "enchantment"})],
                    [EffectSpec("remove_counters", {"target_kind": "permanent", "max_count": 3})],
                ],
                "descriptions": [
                    "Du ziehst eine Karte und verlierst 1 Leben.",
                    "Zerstöre eine Zielverzauberung.",
                    "Entferne bis zu drei Marken von einer bleibenden Zielkarte.",
                ],
            },
        ),
    ]


register("Glissa Sunslayer", _glissa_sunslayer)
