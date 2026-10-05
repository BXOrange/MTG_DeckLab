from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fortune_teller_s_talent() -> list[AbilitySpec]:
    """(Gain the next level as a sorcery to add its ability.)
    You may look at the top card of your library any time.
    {3}{U}: Level 2
    As long as you've cast a spell this turn, you may play cards from the top of your library.
    {2}{U}: Level 3
    Spells you cast from anywhere other than your hand cost {2} less to cast.

    — Family Matters deck batch. Level 1 and the level-ups are the parser's own claims. Level 2 is a
    `top_library_permission` (lands and spells) behind two gates — the class level and the new
    ``cast_spell_this_turn`` condition; level 3 is Advanced Reconstruction's level-3 `cost_reduction`
    (``not_from_hand``, generic 2).
    """
    return [
        AbilitySpec("static", [EffectSpec("top_library_permission", {"look": True})]),
        AbilitySpec(
            "activated", [EffectSpec("class_level", {"level": 2})],
            cost={"text": "{3}{u}", "sorcery_speed_only": True, "class_level": 2},
        ),
        AbilitySpec("static", [EffectSpec("top_library_permission", {
            "play_lands": True, "cast_spells": True, "min_level": 2, "level_counter": "class_level",
            "active_if": {"kind": "cast_spell_this_turn"},
        })]),
        AbilitySpec(
            "activated", [EffectSpec("class_level", {"level": 3})],
            cost={"text": "{2}{u}", "sorcery_speed_only": True, "class_level": 3},
        ),
        AbilitySpec("static", [EffectSpec("cost_reduction", {
            "affects": "your_spells", "generic": 2, "not_from_hand": True,
            "min_level": 3, "level_counter": "class_level",
        })]),
    ]


register("Fortune Teller's Talent", _fortune_teller_s_talent)
