from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _edgar_s_awakening() -> list[AbilitySpec]:
    'Return target creature card from your graveyard to the battlefield.\nWhen you discard this card, you may pay {B}. When you do, return target creature card from your graveyard to your hand.'
    return [
        AbilitySpec(
            'spell_effect',
            [EffectSpec('return_from_graveyard', {"target_kind": 'graveyard_creature', "destination": 'battlefield'})],
            raw_text='return target creature card from your graveyard to the battlefield.',
        ),
        # RULE 603.1/701.8: functions from the graveyard the discard just put it into
        # (`triggers_mixin._collect_discarded_triggers`); RULE 603.12: the "When you do" payoff is a reflexive
        # trigger that announces its target only once {B} is paid.
        AbilitySpec(
            'triggered',
            [EffectSpec('pay_cost_then', {"cost": "{B}", "then_trigger": [
                {"type": "return_from_graveyard", "params": {"target_kind": "graveyard_creature", "destination": "hand"}},
            ]})],
            trigger={"event": EventType.DISCARD_CARD, "condition": {"subject": "self"}},
            raw_text='when you discard this card, you may pay {b}. when you do, return target creature card from your graveyard to your hand.',
        ),
    ]


register("Edgar's Awakening", _edgar_s_awakening)
