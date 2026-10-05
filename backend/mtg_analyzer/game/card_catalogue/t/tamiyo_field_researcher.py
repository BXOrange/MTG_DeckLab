from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register
from ...continuous import GRANTOR_SENTINEL

#: The "you may cast spells from your hand without paying their mana costs" emblem ability (RULE 114), in the
#: serialized shape `create_emblem` consumes: a static `free_cast_permission` limited to spells cast from hand.
_FREE_CAST_EMBLEM = {
    "ability_kind": "static",
    "effects": [{"type": "free_cast_permission", "params": {"from_hand": True}}],
    "trigger": None, "cost": None, "target": None, "keyword": None, "modes": None,
    "additional_cost": None, "additional_cost_optional": False, "conditional_flash": None,
    "cast_timing_restriction": None, "cast_condition": None, "flash_extra_cost": None,
    "free_cast_condition": None, "optional": False,
    "raw_text": "you may cast spells from your hand without paying their mana costs.",
    "parser": {"version": "nested", "source": "rule:oracle", "confidence": 1.0},
}


def _tamiyo_field_researcher() -> list[AbilitySpec]:
    """+1: Choose up to two target creatures. Until your next turn, whenever either of those creatures deals
    combat damage, you draw a card.
    −2: Tap up to two target nonland permanents. They don't untap during their controller's next untap step.
    −7: Draw three cards. You get an emblem with "You may cast spells from your hand without paying their mana
    costs."

    — Peace Offering deck batch. The +1 is `grant_until` (duration ``your_next_turn``) of a
    `grant_triggered_ability` on the chosen creatures: a combat-DAMAGE trigger whose body draws for the *grantor's*
    controller (`GRANTOR_SENTINEL` as `draw`'s player — the creature may be an opponent's). The −2 is `tap` over up
    to two nonland permanents plus `skip_next_untap` on them (Junk Winder's pairing). The −7 draws three and
    `create_emblem`s a standing `free_cast_permission` limited to spells cast from hand (``from_hand``).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "static": {"type": "grant_triggered_ability", "params": {
                    "trigger_event": "DAMAGE", "filter": {"combat": True},
                    "grant_effects": [{"type": "draw", "params": {"count": 1, "player": GRANTOR_SENTINEL}}],
                }},
                "duration": "your_next_turn", "target_kind": "creature", "count": 2, "optional": True,
            })],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("tap", {"target_kind": "nonland_permanent", "count": 2, "optional": True}),
                EffectSpec("skip_next_untap", {"previous_subject": True}),
            ],
            cost={"loyalty": -2},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("draw", {"count": 3}),
                EffectSpec("create_emblem", {"ability": _FREE_CAST_EMBLEM}),
            ],
            cost={"loyalty": -7},
        ),
    ]


register("Tamiyo, Field Researcher", _tamiyo_field_researcher)
