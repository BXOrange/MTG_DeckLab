from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _garnet_princess_of_alexandria() -> list[AbilitySpec]:
    """Lifelink
    Whenever Garnet attacks, you may remove a lore counter from each of any
    number of Sagas you control. Put a +1/+1 counter on Garnet for each
    lore counter removed this way.

    — PAR-67. Lifelink is a plain printed keyword. The attack trigger's
    body is a genuinely new shape (SOLO-blocked, no cluster elsewhere in
    the cache): a *chosen set* of the controller's own Sagas, each losing
    one lore counter, then a payoff scaled by how many were actually
    removed. `RemoveLoreCounterFromChosenSagasThenAddCountersEffect`
    reuses the existing `_request_choose_objects` "strip_all_counters"
    action (every printed Saga carries only lore counters, so stripping
    "all" of a chosen Saga's counters is the same RULE 122 precision
    simplification `RemoveCountersFromAmongThenDrawLoseLifeEffect`,
    Eventide's Shadow, already accepts) restricted to the controller's own
    Sagas, and queues the +1/+1 payoff as a before/after lore-counter-total
    delta the same way that card's own draw/life-loss tail does.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("remove_lore_counter_from_chosen_sagas_then_add_counters", {})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Garnet, Princess of Alexandria", _garnet_princess_of_alexandria)
