from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _demonspine_whip() -> list[AbilitySpec]:
    """{X}: Equipped creature gets +X/+0 until end of turn.
    Equip {1}

    — PLAY-ALL Step 2 (Wick Snail Boom). Equip is a printed keyword read from
    the card. The activated pump is the parser's own shape for the fixed
    "{1}{R}: equipped creature gets +1/+0" — `pump` on ``attached_permanent``
    — with the ``"x"`` sentinel `RulesEngine._substitute_x` binds to the
    activation's paid {X} (the same spelling it already parses for "{X}:
    target creature gets +X/+0"); only the equipped-creature + X combination
    was unclaimed.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"power": "x", "toughness": 0, "target_kind": "attached_permanent"})],
            cost={"text": "{X}"},
        ),
    ]


register("Demonspine Whip", _demonspine_whip)
