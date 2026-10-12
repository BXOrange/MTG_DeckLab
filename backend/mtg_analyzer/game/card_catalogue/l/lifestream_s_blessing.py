from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


_GREATEST_POWER = "greatest_creature_power_as_cast"


def _lifestream_s_blessing() -> list[AbilitySpec]:
    """Draw X cards, where X is the greatest power among creatures you controlled as you cast this spell. If this spell was cast from exile, you gain twice X life.
    Foretell {4}{G} (During your turn, you may pay {2} and exile this card from your hand face down. Cast it on a later turn for its foretell cost.)

    — PLAY-ALL (Limit Break). X reads the greatest creature power stored at
    cast time. This is determined by the spell's text, not an announced X
    choice, so an uncast spell copy has no cast-time reading (RULE 107.2 /
    707.10). The life rider reads actual exile cast origin independently
    of the Foretell alternative cost.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "foretell", "cost": "{4}{G}"}),
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("bind", {
                    "name": "x", "amount": {"kind": "count_selector", "selector": _GREATEST_POWER},
                    "effects": [{"type": "draw", "params": {"count": "$x"}}],
                }),
                EffectSpec("bind", {
                    "name": "y", "amount": {"kind": "count_selector", "selector": {"terms": [_GREATEST_POWER], "times": 2}},
                    "effects": [{"type": "gain_life", "params": {"amount": "$y"}}],
                }, condition={"kind": "flag", "flag": "cast_from_exile", "of": "source"}),
            ],
        ),
    ]


register("Lifestream's Blessing", _lifestream_s_blessing)
