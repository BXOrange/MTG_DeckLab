from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _corpse_dance() -> list[AbilitySpec]:
    """Buyback {2} (You may pay an additional {2} as you cast this spell.
    If you do, put this card into your hand as it resolves.)
    Return the top creature card of your graveyard to the battlefield.
    That creature gains haste until end of turn. Exile it at the beginning
    of the next end step.

    — Corpse Dance. Buyback comes from the RULE 702.27 keyword catalogue
    (independent of this registry). ENG-37 B6 split the fused
    `return_top_graveyard_creature_with_haste` into a `seq`:
    `return_from_graveyard` with the new ``positional_top_creature`` flag
    (the graveyard's own insertion order, not a RULE 115 target) plus its
    already-present ``haste`` rider, then — gated on a creature actually
    having been returned (RULE 608.2: "it" needs a referent) — a
    `create_delayed_trigger` for "Exile it at the beginning of the next end
    step." ``capture="previous_or_self"`` bakes in whichever object the
    return just surfaced onto `previous_targets` / `created_objects`, and
    ``scope="any"`` matches "the **next** end step", whoever's turn it is.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "return_from_graveyard", "params": {
                    "positional_top_creature": True, "haste": True,
                }},
                {"type": "if_else", "params": {
                    "condition": {"kind": "is_card_type", "of": "previous_target",
                                  "card_type": "creature"},
                    "then": [{"type": "create_delayed_trigger", "params": {
                        "step": "end", "scope": "any", "capture": "previous_or_self",
                        "effects": [{"type": "exile", "params": {"target_kind": None}}],
                        "description": "Corpse Dance: im nächsten Endsegment exilieren",
                    }}],
                }},
            ]})],
        )
    ]


register("Corpse Dance", _corpse_dance)
