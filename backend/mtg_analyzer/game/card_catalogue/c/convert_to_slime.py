from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: RULE 702.150 Delirium — four or more card types among cards in your graveyard.
_DELIRIUM_TYPES = 4


def _convert_to_slime() -> list[AbilitySpec]:
    """Destroy up to one target artifact, up to one target creature, and up to one target enchantment.
    Delirium — Then if there are four or more card types among cards in your graveyard, create an X/X green Ooze creature token, where X is the total mana value of permanents destroyed this way.

    — PLAY-ALL (Death Toll). Decimate's one-`destroy`-per-target shape with each target ``optional`` ("up to one"), then an `if_else`
    on the Delirium condition (a ``control_count`` over the distinct card types in your graveyard) around a `create_token` whose ``pt_amount`` is ``moved_sum`` — the total mana value of what this
    resolution's `destroy` clauses actually put into a graveyard (`GameContext.moved_objects`).
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("destroy", {"target_kind": "artifact", "optional": True}),
            EffectSpec("destroy", {"target_kind": "creature", "optional": True}),
            EffectSpec("destroy", {"target_kind": "enchantment", "optional": True}),
            EffectSpec("if_else", {
                "condition": {"kind": "control_count", "min": _DELIRIUM_TYPES,
                              "selector": {"zone": "graveyard", "of": "you", "distinct": "card_type"}},
                "then": [{"type": "create_token", "params": {
                    "count": 1, "colors": ["G"], "subtypes": ["Ooze"], "token_name": "Ooze",
                    "pt_amount": {"kind": "moved_sum", "characteristic": "mana_value"},
                }}],
            }),
        ]),
    ]


register("Convert to Slime", _convert_to_slime)
