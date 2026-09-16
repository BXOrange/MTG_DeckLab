from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ruinous_waterbending() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may waterbend {4}.
    All creatures get -2/-2 until end of turn. If this spell's additional
    cost was paid, whenever a creature dies this turn, you gain 1 life.

    — the -2/-2 board sweep parses on its own (`pump` selector
    ``all_creatures``); the paid-branch grant is the new *event-based,
    this-turn* floating triggered ability — `install_temporary_player_
    trigger` with ``duration="this_turn"`` (armed active immediately,
    dropped at the next `TURN_BEGIN`), ``event_player_scope="any"``
    ("whenever **a** creature dies", not "a creature you control") and
    ``recipient="controller"`` ("**you** gain 1 life").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("pump", {"power": -2, "toughness": -2, "selector": "all_creatures"}),
                EffectSpec("install_temporary_player_trigger", {
                    "event_type": "DIES",
                    "duration": "this_turn",
                    "event_player_scope": "any",
                    "recipient": "controller",
                    "effects": [{"type": "gain_life", "params": {"amount": 1}}],
                    "description": "Immer wenn in diesem Zug eine Kreatur stirbt, gewinnst du 1 Leben.",
                }, condition={"additional_cost_paid": True}),
            ],
            additional_cost={"waterbend": 4},
            additional_cost_optional=True,
        ),
    ]


register("Ruinous Waterbending", _ruinous_waterbending)
