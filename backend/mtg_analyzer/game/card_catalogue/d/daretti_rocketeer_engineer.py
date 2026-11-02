from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _daretti_rocketeer_engineer() -> list[AbilitySpec]:
    "Daretti's power is equal to the greatest mana value among artifacts you control.\nWhenever Daretti enters or attacks, choose target artifact card in your graveyard. You may sacrifice an artifact. If you do, return the chosen card to the battlefield."
    def _reanimate() -> list[EffectSpec]:
        # RULE 601.2c: the artifact card is targeted when the trigger goes on the stack; the sacrifice is the
        # "you may ... if you do" payment (RULE 118.12-style optional cost, `pay_cost_then`), and the return
        # reads that announced target.
        return [EffectSpec('pay_cost_then', {
            "cost": "sacrifice an artifact",
            "effects": [{"type": "return_from_graveyard", "params": {
                "target_kind": "graveyard_artifact", "destination": "battlefield"}}],
        })]

    return [
        AbilitySpec(
            'static',
            [EffectSpec('pt_cda', {"affects": 'self', "power_count": {'zone': 'battlefield', 'of': 'you', 'filter': {'card_type': 'artifact'}, 'aggregate': 'max', 'value': 'mana_value'}})],
            raw_text="~'s power is equal to the greatest mana value among artifacts you control.",
        ),
        AbilitySpec(
            'triggered', _reanimate(),
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='whenever ~ enters, choose target artifact card in your graveyard. you may sacrifice an artifact. if you do, return the chosen card to the battlefield.',
        ),
        AbilitySpec(
            'triggered', _reanimate(),
            trigger={"event": EventType.ATTACKS, "condition": {'subject': 'self'}},
            raw_text='whenever ~ attacks, choose target artifact card in your graveyard. you may sacrifice an artifact. if you do, return the chosen card to the battlefield.',
        ),
    ]


register('Daretti, Rocketeer Engineer', _daretti_rocketeer_engineer)
