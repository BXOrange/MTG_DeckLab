from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-40: cEDH Rocco / cEDH staples remaining gaps (batch 1)
# ---------------------------------------------------------------------------


def _culling_ritual() -> list[AbilitySpec]:
    """Culling Ritual (Sorcery, {2}{B}{G})

    "Destroy each nonland permanent with mana value 2 or less. Add {B} or
    {G} for each permanent destroyed this way."

    The destroy half is a plain parser-claimable mass wipe on its own
    (`_MASS_DESTROY_NOUNS_SINGULAR`'s new "nonland permanent" entry) —
    hand-authored here only because the mana rider needs a same-resolution
    accumulator (`GameContext.permanents_destroyed_this_way`, mirroring the
    existing `life_lost_this_way`) the parser has no vocabulary for yet.

    **Documented simplification**: the real card lets you split the
    produced mana between {B} and {G} independently, mana by mana (RULE
    106.1); `AddManaEffect.any_color_choices` offers one colour choice for
    the *whole* amount instead (see its own docstring for why) — no
    per-unit "how many of each" interactive shape exists yet. Still fully
    usable colored mana, just less flexible than printed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec(
                    "destroy",
                    {"selector": "all_nonland_permanents", "filter": {"max_mana_value": 2}},
                ),
                EffectSpec(
                    "add_mana",
                    {
                        "colors": ["ANY"],
                        "any_color_choices": ["B", "G"],
                        "any_amount_from_context": "permanents_destroyed_this_way",
                    },
                ),
            ],
        ),
    ]


register("Culling Ritual", _culling_ritual)
