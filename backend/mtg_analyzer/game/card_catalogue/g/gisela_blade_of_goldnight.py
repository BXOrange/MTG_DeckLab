from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gisela_blade_of_goldnight() -> list[AbilitySpec]:
    """Flying, first strike
    If a source would deal damage to an opponent or a permanent an
    opponent controls, that source deals double that damage to that
    player or permanent instead.
    If a source would deal damage to you or a permanent you control,
    prevent half that damage, rounded up.

    — Flying/first strike are the ordinary keyword fold-in. The two
    replacements are independent and both fire off *any* source
    (unqualified), one already-shipped (`double_damage`, opponent-scoped
    via ``to_opponent_only``), one new (`prevent_damage`'s
    ``recipient_union=["controller", {}]`` — "you or a permanent you
    control", an empty filter dict matching any controlled permanent —
    and ``amount={"half": "up"}``).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_damage", {"to_opponent_only": True})],
        ),
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "recipient_union": ["controller", {}], "amount": {"half": "up"},
            })],
        ),
    ]


register("Gisela, Blade of Goldnight", _gisela_blade_of_goldnight)
