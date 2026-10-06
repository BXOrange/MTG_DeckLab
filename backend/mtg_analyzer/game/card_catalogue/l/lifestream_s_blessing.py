from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


_GREATEST_POWER = "greatest_power_among_creatures_you_control"


def _lifestream_s_blessing() -> list[AbilitySpec]:
    """Draw X cards, where X is the greatest power among creatures you controlled as you cast this spell. If this spell was cast from exile, you gain twice X life.
    Foretell {4}{G} (During your turn, you may pay {2} and exile this card from your hand face down. Cast it on a later turn for its foretell cost.)

    — PLAY-ALL (Limit Break). Foretell is the keyword. A `bind` of the new ``greatest_power_among_creatures_you_control`` selector into `draw` and (behind the ``foretold`` flag, read as
    "cast from exile") `gain_life` of twice that (a ``terms``/``times`` count expression). **Simplification:** X is measured as the spell resolves, not as it was cast.
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
                }, condition={"kind": "flag", "flag": "foretold", "of": "source"}),
            ],
        ),
    ]


register("Lifestream's Blessing", _lifestream_s_blessing)
