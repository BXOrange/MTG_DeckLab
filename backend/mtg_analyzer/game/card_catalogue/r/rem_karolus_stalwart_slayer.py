from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rem_karolus_stalwart_slayer() -> list[AbilitySpec]:
    """Flying, haste
    If a spell would deal damage to you or another permanent you control,
    prevent that damage.
    If a spell would deal damage to an opponent or a permanent an opponent
    controls, it deals that much damage plus 1 instead.

    — Flying/haste are the ordinary keyword fold-in. The prevent half is
    already fully expressible: ``source_filter={"is_spell": True}`` +
    ``recipient_union=["controller", {"exclude_self": True}]`` (Temple
    Altisaur's own "another `<X>` you control" idiom, unfiltered here since
    "another permanent" has no type restriction). The bonus-damage half
    needed one new param on `_additional_damage_replacement` — ``is_spell``,
    mirroring the check its own `_prevent_damage_replacement` sibling
    already had for the exact same event field (MEC-30).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "recipient_union": ["controller", {"exclude_self": True}],
                "amount": "all", "source_filter": {"is_spell": True},
            })],
        ),
        AbilitySpec(
            "replacement",
            [EffectSpec("additional_damage", {
                "amount": 1, "to_opponent_only": True, "is_spell": True,
            })],
        ),
    ]


register("Rem Karolus, Stalwart Slayer", _rem_karolus_stalwart_slayer)
