from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _orcish_bowmasters() -> list[AbilitySpec]:
    """Flash
    When this creature enters and whenever an opponent draws a card
    except the first one they draw in each of their draw steps, this
    creature deals 1 damage to any target. Then amass Orcs 1.

    — MEC-42. Flash is a plain printed keyword. "Except the first one
    they draw in each of their draw steps" is MEC-32's own `EventType.
    DRAW` ``first_in_draw_step`` flag (`RulesEngine._single_draw`, already
    built for Notion Thief/Chains of Mephistopheles' replacement effects)
    — the first *trigger* consumer of it, via a plain ``filter`` exact-
    match (`{"first_in_draw_step": False}`) rather than a replacement
    condition. Amass (RULE 701.48) had no primitive at all yet — new
    `AmassEffect`. Two `AbilitySpec`s (ETB self, and the opponent-scoped
    DRAW trigger) share the same effect *shape*, each its own fresh
    `EffectSpec` instance, the same split Derevi's own ETB-and-combat-
    damage pair uses right above.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("damage", {"amount": 1, "target_kind": "any"}),
                EffectSpec("amass", {"subtype": "Orc", "count": 1}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("damage", {"amount": 1, "target_kind": "any"}),
                EffectSpec("amass", {"subtype": "Orc", "count": 1}),
            ],
            trigger={
                "event": EventType.DRAW,
                "condition": {"subject": "group", "controller": "not_you"},
                "filter": {"first_in_draw_step": False},
            },
        ),
    ]


register("Orcish Bowmasters", _orcish_bowmasters)
