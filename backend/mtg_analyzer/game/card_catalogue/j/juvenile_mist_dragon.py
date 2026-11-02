
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _juvenile_mist_dragon() -> list[AbilitySpec]:
    """Flying
    Confounding Clouds — When this creature enters, for each opponent, tap up to one target creature that player
    controls. Each of those creatures doesn't untap during its controller's next untap step.

    RULE 603.2 (ETB trigger) with RULE 115.1 per-opponent targeting: ``per_player="opponents"`` gives one optional
    target round per opponent, each restricted to that opponent's creatures (`TargetSpec.per_player`, the same shape
    Shellshock's "up to one target creature per opponent" uses). The tap is `TapEffect`, and "those creatures don't
    untap" is the existing `skip_next_untap` over ``previous_subject`` (the Icy Blast pair). Flying is a printed
    keyword.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("tap", {
                    "target_kind": "creature_that_player_controls", "per_player": "opponents",
                    "optional": True, "untap": False,
                }),
                EffectSpec("skip_next_untap", {"previous_subject": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Juvenile Mist Dragon", _juvenile_mist_dragon)
