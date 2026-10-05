from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _waterbenders_restoration() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, waterbend {X}.
    Exile X target creatures you control. Return those cards to the
    battlefield under their owner's control at the beginning of the next
    end step.

    — a mass delayed-return flicker: `exile` X targets with ``track_exiled_
    with`` + a RULE 603.7 `create_delayed_trigger` at the next end step
    running `return_all_exiled_with` (each card back under its own owner's
    control — the effect's default). The mandatory waterbend {X} announces
    X (v215) and `_substitute_x` resolves the ``"x"`` target count.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile", {
                    "target_kind": "creature_you_control",
                    "count_selector": "source_x_paid",
                    "track_exiled_with": True,
                }),
                # "at the beginning of **the** next end step" (not "your") —
                # scope "any", the very next end step whoever's turn it is.
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "any",
                    "effects": [{"type": "return_all_exiled_with", "params": {}}],
                    "description": "Bringe diese Karten am Anfang des nächsten "
                                   "Endsegments ins Spiel zurück.",
                }),
            ],
            additional_cost={"waterbend": "x"},
        ),
    ]


register("Waterbender's Restoration", _waterbenders_restoration)
