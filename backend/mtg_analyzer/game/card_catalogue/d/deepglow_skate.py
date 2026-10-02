from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: UI cap for "any number of target permanents" (RULE 601.2c) — the same
#: idiom as Fire Covenant's / Display of Power's ``count=10``; far above the
#: size of any real board's counter-bearing permanents.
ANY_NUMBER_TARGET_CAP = 10


def _deepglow_skate() -> list[AbilitySpec]:
    """When this creature enters, double the number of each kind of counter
    on any number of target permanents.

    — PLAY-ALL Step 2 (Counter Intelligence). `double_counters_on_target`
    (Ferrafor's effect, ``kind=None`` = every kind) gained
    ``target_count``/``optional`` and now doubles on *every* chosen target.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("double_counters_on_target", {
                "target_kind": "permanent", "kind": None,
                "target_count": ANY_NUMBER_TARGET_CAP, "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Deepglow Skate", _deepglow_skate)
