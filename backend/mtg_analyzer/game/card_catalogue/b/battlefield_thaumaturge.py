from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _battlefield_thaumaturge() -> list[AbilitySpec]:
    """Each instant and sorcery spell you cast costs {1} less to cast for
    each creature it targets.
    Heroic — Whenever you cast a spell that targets this creature, this
    creature gains hexproof until end of turn.

    — PLAY-ALL Step 2 (yshtola). The heroic trigger is the parser's own
    claim, reproduced verbatim (a registered card never falls back to the
    parser). The discount is Killian's `reduce_if_targets` shape plus the new
    ``per_target`` flag (`continuous.cost_reduction_for`), which scales it by
    the number of chosen targets that match instead of applying it once;
    Baral's ``spell_type`` list does the "instant and sorcery" part.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "generic": 1, "spell_type": ["instant", "sorcery"],
                "reduce_if_targets": {"card_type": "creature"}, "per_target": True,
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {"keywords": ["hexproof"]})],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "requires_spell_targets_source": True,
            },
        ),
    ]


register("Battlefield Thaumaturge", _battlefield_thaumaturge)
