from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "three or more cards have been exiled with this artifact".
_CARDS_NEEDED = 3


def _colfenor_s_urn() -> list[AbilitySpec]:
    """Whenever a creature with toughness 4 or greater is put into your graveyard from the battlefield, you may exile it.
    At the beginning of the end step, if three or more cards have been exiled with this artifact, sacrifice it. If you do, return those cards to the battlefield under their owner's control.

    — PLAY-ALL (Abzan Armor). The exile trigger is the parser's plus ``track_exiled_with`` (the Urn remembers each card in
    `GameObject.exiled_with_ids`). The end-step trigger carries its RULE 603.4 intervening-if on the ``exiled_with_count``
    selector (on the trigger, re-checked as it resolves); the body sacrifices the Urn and then returns every tracked card to its
    owner's battlefield (`return_all_exiled_with`, Abdel Adrian's) — "if you do" is the sacrifice, which cannot fail here.
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
            [EffectSpec("sacrifice_self", {}), EffectSpec("return_all_exiled_with", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "active_if": dict(gate)},
        ),
    ]


register("Colfenor's Urn", _colfenor_s_urn)
