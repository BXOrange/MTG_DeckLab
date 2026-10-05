from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# Incubate (RULE 701.53) residue — the three cache singletons the PAR-30
# parser trail left, each blocked on its own bespoke shape rather than on
# incubate grammar (that shipped in v160/v162). Hand-authored per this
# repo's escape valve (docs/Reference/11); the incubate itself is the
# standard `create_token` "Incubator" + `extra_counters` {+1/+1} pattern
# `Glissa, Herald of Predation` established, sized by a count source.
# ---------------------------------------------------------------------------


def _traumatic_revelation() -> list[AbilitySpec]:
    """Target opponent reveals their hand. You may choose a creature or
    battle card from it. If you do, that player discards that card. If you
    don't, incubate 3.

    — the "if you don't, `<effect>`" *else*-branch on an optional
    `reveal_hand_choose_discard` (Thoughtseize's own template) is the only
    new shape: `RevealHandChooseDiscardEffect` gains ``optional`` +
    ``else_specs``, threaded through `_request_choose_objects`' new
    ``else_specs`` (the mirror of its long-standing ``then_specs``), which
    fires when the choice ends with nothing picked — including when the
    revealed hand held no creature or battle card to begin with. "battle"
    joins the effect's own ``card_types`` filter. The else body is the
    plain incubate-3 `create_token`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("reveal_hand_choose_discard", {
                "target_kind": "opponent",
                "card_types": ["creature", "battle"],
                "optional": True,
                "else_specs": [
                    {"type": "create_token", "params": {
                        "token_name": "Incubator",
                        "extra_counters": {"kind": "+1/+1", "count": 3},
                    }},
                ],
            })],
        ),
    ]


register("Traumatic Revelation", _traumatic_revelation)
