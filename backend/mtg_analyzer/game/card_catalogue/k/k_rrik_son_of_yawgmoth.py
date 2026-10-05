from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _krrik_son_of_yawgmoth() -> list[AbilitySpec]:
    """Lifelink
    For each {B} in a cost, you may pay 2 life rather than pay that mana.
    Whenever you cast a black spell, put a +1/+1 counter on K'rrik.

    — MEC-43 round 4F. Lifelink is a plain printed keyword, bound
    independent of catalogue registration (see Tymna the Weaver's own
    docstring for the convention). The alternative-payment clause is a
    genuinely new primitive — broader than every existing wildcard-color
    mechanism (RULE 605.1a's `grant_any_color_for_activation`/
    `GameState.mana_wildcard_permission`, both of which only ever relax
    *which* mana pays a pip): `grant_life_for_mana_pip` is a standing
    permission (`continuous.life_for_mana_pip_color`) consulted at the two
    real cost-payment sites — casting (`game/engine/casting_mixin.py`'s
    `can_cast`, `game/rules/casting_mixin.py`'s actual payment) and
    activating (`game/engine/activation_mixin.py`'s `_can_pay_activation_
    cost`/`_pay_activation_cost`/`_max_x_for_mana`) — threaded into
    `ManaPool.can_pay`/`pay`'s new `extra_life_color` param, which gives a
    plain {B} pip the same life-payment option a printed Phyrexian pip
    already has (`mana_pool.KRRIK_LIFE_PER_BLACK_PIP` — 2 life, same price
    RULE 702.85a already charges). The counter trigger reuses the existing
    `cast_of_color` trigger-condition key (Runaway Steam-Kin's own
    template) with no intervening-if.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_life_for_mana_pip", {"color": "B"})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "+1/+1", "amount": 1, "target_kind": None})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "cast_of_color": "B",
            },
        ),
    ]


register("K'rrik, Son of Yawgmoth", _krrik_son_of_yawgmoth)
