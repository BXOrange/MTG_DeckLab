from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# "Hobbits" / "Wyleth Equip" saved-deck-priority batch — closing the
# remaining group-attack/group-ETB/conditional-trigger cluster the parser's
# generic grammar doesn't reach yet (RULE 603.3b's "any number of X" is a
# genuine aggregate-once trigger shape, distinct from the per-object group
# condition `effect_binder._build_group_ok` already models; a printed
# "historic"/exact-power-filtered ETB gate; a multi-object sacrifice cost).
# Each entry documents its own specific simplification.
# ---------------------------------------------------------------------------


def _meriadoc_brandybuck() -> list[AbilitySpec]:
    """Whenever one or more Halflings you control attack a player, create
    a Food token.

    Simplified: modeled as "attacks" (any defender), not "attacks a
    player" specifically — the ATTACKS event carries no defender-kind
    payload to filter on. RULE 603.3b's "one or more X" is a genuine
    aggregate-once-per-batch trigger; this engine's group condition instead
    fires once per *qualifying object* (once per attacking Halfling), so
    it's capped at once per turn (`trigger["limit"]`) as the closest
    available approximation — under-fires on a rare second combat the same
    turn, never over-fires on a simultaneous multi-Halfling attack.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={
                "event": EventType.ATTACKS,
                "condition": {
                    "subject": "group", "subtypes": ["halfling"],
                    "controller": "you", "other": False,
                },
                "limit": True,
            },
        ),
    ]


register("Meriadoc Brandybuck", _meriadoc_brandybuck)
