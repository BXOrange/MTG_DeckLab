from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _herald_of_war() -> list[AbilitySpec]:
    """Flying
    Whenever this creature attacks, put a +1/+1 counter on it.
    Angel spells and Human spells you cast cost {1} less to cast for each +1/+1 counter on this creature.

    — PLAY-ALL (Calling All Angels). The attack trigger is the parser's. The discount is a `cost_reduction` over
    ``your_spells`` with a ``spell_subtype`` list (Angel or Human) and the per-count ``per`` selector
    ``plus_one_counters_on_source`` (the static's own permanent).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec("static", [EffectSpec("cost_reduction", {
            "affects": "your_spells", "generic": 1, "per": "plus_one_counters_on_source",
            "spell_subtype": ["Angel", "Human"],
        })]),
    ]


register("Herald of War", _herald_of_war)
