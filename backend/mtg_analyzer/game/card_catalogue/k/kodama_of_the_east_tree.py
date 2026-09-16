from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kodama_of_the_east_tree() -> list[AbilitySpec]:
    """Reach
    Whenever another permanent you control enters, if it wasn't put onto
    the battlefield with this ability, you may put a permanent card with
    equal or lesser mana value from your hand onto the battlefield.
    Partner (You can have two commanders if both have partner.)

    — MEC-43 round 4D. Reach and Partner are plain flag keywords. The
    trigger's own body is the new `PutEqualOrLesserManaValueFromHandEffect`
    — the dynamic-mana-value-cap sibling of `PutFromHandOntoBattlefield
    Effect` (Tooth and Nail), reading the just-entered permanent's own
    mana value fresh off `GameContext.trigger_event` each firing rather
    than a literal the catalogue could bake in. It places its pick via
    the new `"hand_to_battlefield"` `_request_choose_objects` action
    (`RulesEngine._apply_chosen_object`) specifically so the new
    permanent gets `GameObject.entered_via_ability_id` stamped — read
    back by the trigger's own new ``not_entered_via_self`` condition
    (`effect_binder._build_group_ok`) to satisfy the printed "if it
    wasn't put onto the battlefield with this ability" guard (a
    Panharmonicon-shaped self-recursion block: a permanent Kodama itself
    just placed must not re-trigger Kodama).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("put_equal_or_lesser_mv_from_hand", {})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "permanent", "controller": "you",
                    "other": True, "not_entered_via_self": True,
                },
            },
        ),
    ]


register("Kodama of the East Tree", _kodama_of_the_east_tree)
