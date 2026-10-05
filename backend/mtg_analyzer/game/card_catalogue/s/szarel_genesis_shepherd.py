from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _szarel_genesis_shepherd() -> list[AbilitySpec]:
    """Flying
    You may play lands from your graveyard.
    Whenever you sacrifice another nontoken permanent during your turn, put a
    number of +1/+1 counters equal to Szarel's power on up to one other target
    creature.

    — PLAY-ALL Step 2 (World Shaper). Flying is the keyword fold-in; the land
    permission is the parser's own `graveyard_cast_permission` (``lands_only``)
    and the trigger head its `SACRIFICE` group (``other``, ``nontoken``,
    ``phase_relation: you``). The body is `add_counters` with a `characteristic`
    (power) amount operand read off the source, on an optional ``creature``
    target (which already excludes the source: "other target creature").
    """
    return [
        AbilitySpec("static", [EffectSpec("graveyard_cast_permission", {"lands_only": True})]),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": {"kind": "characteristic", "of": "source", "characteristic": "power"},
                "kind": "+1/+1", "target_kind": "creature", "optional": True,
            })],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {
                    "subject": "group", "controller": "you", "other": True, "filter": {"nontoken": True},
                },
                "phase_relation": "you",
            },
        ),
    ]


register("Szarel, Genesis Shepherd", _szarel_genesis_shepherd)
