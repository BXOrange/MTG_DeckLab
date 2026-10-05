from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _archon_of_valors_reach() -> list[AbilitySpec]:
    """Flying, vigilance, trample
    As this creature enters, choose artifact, enchantment, instant,
    sorcery, or planeswalker.
    Players can't cast spells of the chosen type.

    — MEC-43 round 4D. All three keywords are plain flag keywords
    (Scryfall-recognized, no catalogue entries needed). The "choose a
    card type" pick reuses `ChooseNamedModeReplacement` (RULE 601.2b's
    "as ~ enters, choose <Label1> or <Label2>" family, Struggle for
    Project Purity-shaped) rather than a new replacement class: its five
    printed options slug to exactly the ``is_artifact``/``is_enchantment``/
    ``is_instant``/``is_sorcery``/``is_planeswalker`` attribute names a
    `Card` already carries, so `GameObject.chosen_mode` doubles as the
    chosen card type with no new field. `cast_prohibition` gained a
    matching ``type_from_source_mode`` gate reading it back
    (`continuous.cast_prohibited`), unscoped by ``scope`` (the printed
    "**Players** can't…" already binds this card's own controller too,
    the default whenever ``scope`` isn't narrowed to "opponents").
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_named_mode", {
                "options": ["Artifact", "Enchantment", "Instant", "Sorcery", "Planeswalker"],
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {"scope": "all", "type_from_source_mode": True})],
        ),
    ]


register("Archon of Valor's Reach", _archon_of_valors_reach)
