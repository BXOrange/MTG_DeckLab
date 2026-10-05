from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _echoing_assault() -> list[AbilitySpec]:
    """Creature tokens you control have menace.
    Whenever you attack a player, choose target nontoken creature that's attacking that player. Create a token
    that's a copy of that creature, except it's 1/1. The token enters tapped and attacking that player.
    Sacrifice it at the beginning of the next end step.

    — Family Matters deck batch. The menace grant is the parser's own claim. The trigger is the per-player
    `PLAYER_ATTACKED` aggregate (one firing per attacked player) whose target is a nontoken attacker aimed at
    *that* player (the new ``attacking_trigger_defender`` creature filter, read off the firing event). The
    body is `copy_permanent` (1/1, tapped, attacking — the copied creature's own defender) and a next-end-step
    `sacrifice_specific` captured on the *created* token (``capture="created_objects"``: the parser's
    ``previous_or_self`` would name the copied original, which is a target of the same resolution).
    """
    return [
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "affects": "creatures_you_control", "tokens": True, "keywords": ["menace"],
        })]),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("copy_permanent", {
                    "target_kind": "creature", "creature_filter": {"attacking_trigger_defender": True, "nontoken": True},
                    "set_power": 1, "set_toughness": 1, "tapped": True, "attacking": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "any", "capture": "created_objects",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                }),
            ],
            trigger={"event": EventType.PLAYER_ATTACKED, "condition": {"subject": "group", "controller": "you"}},
        ),
    ]


register("Echoing Assault", _echoing_assault)
