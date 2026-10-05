from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jodah_the_unifier() -> list[AbilitySpec]:
    """Legendary creatures you control get +X/+X, where X is the number of
    legendary creatures you control.
    Whenever you cast a legendary spell from your hand, exile cards from
    the top of your library until you exile a legendary nonland card with
    lesser mana value. You may cast that card without paying its mana
    cost. Put the rest on the bottom of your library in a random order.

    — MEC-43 round 4D. The anthem needs no new primitive at all:
    `"anthem"`'s existing ``power_count``/``toughness_count`` params
    (Blackblade Reforged/Nettlecyst-shaped per-unit multipliers) already
    fall through to the ordinary controller-scoped `count_selector`
    vocabulary, which already has a ``"legendary_creatures_you_control"``
    entry (built for Eiganjo, Seat of the Empire's Channel discount) — so
    both the anthem's scope and its own magnitude read the same live
    count, correctly counting Jodah himself. The cast trigger is the new
    `LegendarySpellFreeDigEffect`, riding `RulesEngine.dig_until` (the
    cascade/Possibility Storm-shaped generalized dig) with a criteria
    dict built fresh each firing from the *casting* `SPELL_CAST` event's
    own ``mana_value`` — mirrors Sram, Senior Edificer's own "whenever
    you cast a `<X>` spell" trigger shape (`spell_card_types`, `condition:
    {"controller": "you"}`) plus the `Possibility Storm`-established
    ``filter: {"from_hand": True}`` for "from your hand".
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "legendary_creatures_you_control",
                # ``power``/``toughness`` are the *per-unit* amount when a
                # ``_count`` selector is also set (`continuous.
                # _apply_layer_7_pt`'s own ``pt_mod`` sublayer: "power ...
                # multiplied by that count instead of added as a flat
                # delta") -- 1 per legendary creature, matching the printed
                # "+X/+X, where X is the number of...".
                "power": 1, "toughness": 1,
                "power_count": "legendary_creatures_you_control",
                "toughness_count": "legendary_creatures_you_control",
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("legendary_spell_free_dig", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["legendary"],
                "filter": {"from_hand": True},
            },
        ),
    ]


register("Jodah, the Unifier", _jodah_the_unifier)
