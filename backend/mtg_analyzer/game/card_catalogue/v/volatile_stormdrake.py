from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _volatile_stormdrake() -> list[AbilitySpec]:
    """Flying, hexproof from activated and triggered abilities

    When this creature enters, exchange control of this creature and
    target creature an opponent controls. If you do, you get {E}{E}{E}{E},
    then sacrifice that creature unless you pay an amount of {E} equal to
    its mana value.

    — Volatile Stormdrake, MEC-43. The Gilded Drake-shaped exchange
    (RULE 701.10) plus an Energy-conditional sacrifice-unless-pay bundled
    into one composite effect (`exchange_control_then_energy_sacrifice`,
    `ExchangeControlThenEnergySacrificeEffect`), since RULE 608.2b's "if
    you do" here gates on whether the exchange itself happened — the same
    "action, if you do, consequence" shape Temur Sabertooth/Akiri's own
    bespoke effects already use rather than a cross-effect signal
    `_apply_effects_partitioned` has no channel for. Flying/hexproof come
    from the RULE 702 keyword catalogue.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exchange_control_then_energy_sacrifice", {
                "target_kind": "creature",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
            },
        ),
    ]


register("Volatile Stormdrake", _volatile_stormdrake)
