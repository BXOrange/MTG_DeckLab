from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "three or more cards have been exiled with this artifact".
_CARDS_NEEDED = 3


def _colfenor_s_urn() -> list[AbilitySpec]:
    """Whenever a creature with toughness 4 or greater is put into your graveyard from the battlefield, you may exile it.
    At the beginning of the end step, if three or more cards have been exiled with this artifact, sacrifice it. If you do, return those cards to the battlefield under their owner's control.

    — PLAY-ALL (Abzan Armor). The optional exile tracks linked cards.
    The end-step intervening-if checks three linked cards. The sacrifice
    and return sequence runs only while the trigger's controller can sacrifice
    the Urn; removing it or changing its controller prevents the return.
    """
    gate = {"kind": "control_count", "selector": "exiled_with_count", "min": _CARDS_NEEDED}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "trigger_subject", "trigger_event_key": "__group_subject__", "track_exiled_with": True,
            })],
            trigger={"event": EventType.DIES, "condition": {
                "subject": "group", "controller": "any", "other": False,
                "filter": {"card_type": "creature", "min_toughness": 4}, "owner": "you",
            }},
            optional=True,
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "sacrifice_self", "params": {}},
                {"type": "return_all_exiled_with", "params": {}},
            ]}, condition={"kind": "source_controlled_by_you"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "active_if": dict(gate)},
        ),
    ]


register("Colfenor's Urn", _colfenor_s_urn)
