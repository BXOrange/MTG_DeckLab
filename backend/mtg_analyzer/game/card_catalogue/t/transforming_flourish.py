from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _transforming_flourish() -> list[AbilitySpec]:
    """Demonstrate (When you cast this spell, you may copy it. If you do, choose an opponent to also
    copy it. Players may choose new targets for their copies.)
    Destroy target artifact or creature you don't control. If that permanent is destroyed this way,
    its controller exiles cards from the top of their library until they exile a nonland card,
    then they may cast that card without paying its mana cost.

    — Jeskai Striker deck batch. Demonstrate is the engine's RULE 702.144a cast trigger
    (`RulesEngine._collect_demonstrate_triggers`, a keyword — nothing to author here). The body is a
    `destroy` followed by a `dig_until` gated on the RULE 608.2 "destroyed this way" tally
    (`permanents_destroyed_this_way`, the Acolyte Hybrid condition) whose ``digger`` is the
    destroyed permanent's controller (``previous_target_controller``); that player also holds the
    free-cast window (``caster="digger"``).
    """
    destroyed = {
        "kind": "amount_compare",
        "left": {"kind": "this_way", "tally": "permanents_destroyed_this_way"},
        "right": {"kind": "fixed", "amount": 1},
        "op": "ge",
    }
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("destroy", {"target_kind": "artifact_or_creature_you_dont_control"}),
            EffectSpec("dig_until", {
                "criteria": {"without_type": "land"},
                "hit_destination": "cast_free_window",
                "rest_destination": "exile",
                "digger": "previous_target_controller",
                "caster": "digger",
            }, condition=destroyed),
        ]),
    ]


register("Transforming Flourish", _transforming_flourish)
