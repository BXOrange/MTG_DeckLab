from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _prismatic_ward() -> list[AbilitySpec]:
    """Enchant creature
    As this Aura enters, choose a color.
    Prevent all damage that would be dealt to enchanted creature by
    sources of the chosen color.

    — "Enchant creature" repeated per Kithkin Armor's own wholesale-
    replacement caution. The colour pick reuses Story Circle's own
    ``choose_color_on_enter``. The shield is the *standing* ``"prevent_
    damage"`` replacement family (RULE 613/616 — a bare, un-triggered
    imperative on a permanent, not a "the next time" one-shot grant),
    ``to="attached_permanent"`` (Kithkin Armor's own recipient shape)
    narrowed by the new ``source_filter={"color_from_source": True}`` key
    (PAR-78) — the standing-replacement sibling of `combat.
    matches_object_filter`'s identically-named dynamic filter.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "enchant", "quality": "creature"}),
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_color_on_enter", {})],
        ),
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "to": "attached_permanent", "amount": "all",
                "source_filter": {"color_from_source": True},
            })],
        ),
    ]


register("Prismatic Ward", _prismatic_ward)
