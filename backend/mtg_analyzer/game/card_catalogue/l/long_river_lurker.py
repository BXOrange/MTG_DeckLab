from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _long_river_lurker() -> list[AbilitySpec]:
    "Ward {1}\nOther Frogs you control have ward {1}.\nWhen this creature enters, target creature you control can't be blocked this turn. Whenever that creature deals combat damage this turn, you may exile it. If you do, return it to the battlefield under its owner's control."
    # RULE 115.1 / 603.1: the ETB targets one creature you control; `unblockable` (RULE 509.1b) marks it.
    # RULE 603.7a: "Whenever that creature deals combat damage this turn" is a turn-scoped triggered
    # ability created by the resolving ETB; `create_turn_trigger(previous_subject=True)` bakes the chosen
    # creature into the subject condition (`instance_id_override`), so it follows that object and no other.
    # RULE 120.1 / 510.2: the DAMAGE event names the damage source as ``source_id`` (the damaging
    # creature), restricted to combat damage by the ``combat`` filter.
    # RULE 608.2c "you may ... If you do": the trigger is optional, and the blink is the "if you do" body;
    # RULE 400.7: the returned creature is a new object, returned under its owner's control
    # (`under_your_control` False), so it is untapped/unattacking and loses its combat state.
    return [
        AbilitySpec(
            'static',
            [EffectSpec('grant_keyword', {"affects": 'other_creatures_you_control', "subtype": 'Frog', "ward_cost": '{1}'})],
            raw_text='other frogs you control have ward {1}.',
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("unblockable", {"target_kind": "creature_you_control"}),
                EffectSpec("create_turn_trigger", {
                    "trigger": {
                        "event": EventType.DAMAGE,
                        "condition": {"subject": "self"},
                        "filter": {"combat": True},
                    },
                    "effects": [{"type": "blink", "params": {
                        "target_kind": "trigger_subject", "trigger_event_key": "source_id",
                        "under_your_control": False,
                    }}],
                    "optional": True, "previous_subject": True,
                    "description": "whenever that creature deals combat damage this turn, you may exile it. "
                                   "if you do, return it to the battlefield under its owner's control.",
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="when ~ enters, target creature you control can't be blocked this turn. whenever that creature deals combat damage this turn, you may exile it. if you do, return it to the battlefield under its owner's control.",
        ),
    ]


register('Long River Lurker', _long_river_lurker)
