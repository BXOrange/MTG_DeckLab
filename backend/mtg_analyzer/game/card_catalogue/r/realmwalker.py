from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _realmwalker() -> list[AbilitySpec]:
    """Changeling (This card is every creature type.)
    As this creature enters, choose a creature type.
    You may look at the top card of your library any time.
    You may cast creature spells of the chosen type from the top of your
    library.

    — Eliferate deck batch. Changeling (keyword) and the ETB type choice
    (`choose_creature_type_on_enter`) already parse on their own —
    reproduced here verbatim, since whole-card hand-authoring replaces the
    parser's own output wholesale (`specs_for`'s registry-wins precedence).
    The standing permission is `top_library_permission`'s new
    `chosen_type_creature_only` flag — the same `Oracle of Mul Daya`/
    `Glarb, Calamity's Augur` family, narrowed by `GameObject.chosen_type`
    read live (`game/top_library.py`) instead of a fixed mana-value/
    noncreature gate.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_creature_type_on_enter", {})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {
                "look": True, "cast_spells": True, "chosen_type_creature_only": True,
            })],
        ),
    ]


register("Realmwalker", _realmwalker)
