from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nissa_who_shakes_the_world() -> list[AbilitySpec]:
    """Whenever you tap a Forest for mana, add an additional {G}.
    +1: Put three +1/+1 counters on up to one target noncreature land you
    control. Untap it. It becomes a 0/0 Elemental creature with vigilance
    and haste that's still a land.
    −8: You get an emblem with "Lands you control have indestructible."
    Search your library for any number of Forest cards, put them onto the
    battlefield tapped, then shuffle.

    — PLAY-ALL Step 2 (Kodama). The Forest trigger is the parser's own
    claim (Wild Growth's triggered mana ability, ``subtypes: forest``).
    The +1 is three clauses on one optional target: `add_counters` on a
    ``land_you_control`` whose ``creature_filter`` is ``without_card_type:
    creature`` ("noncreature land"), `tap` untap and a permanent
    `grant_until` (no duration -> ``rest_of_game``) over ``previous_subject``
    giving a layer-4 `type_change` (creature, Elemental, 0/0 — the three
    counters make it 3/3) and vigilance + haste. The −8 is the parser's
    emblem (copied: its inner static spec) followed by a ``search`` for Forest
    cards with the shared ``99`` "any number of" sentinel into
    ``battlefield_tapped``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"colors": ["G"]})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "type": "land", "subtypes": ["forest"], "controller": "you"},
                "mana_ability": True,
            },
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {
                    "count": 3, "kind": "+1/+1", "target_kind": "land_you_control",
                    "creature_filter": {"without_card_type": "creature"}, "optional": True,
                }),
                EffectSpec("tap", {"previous_subject": True, "untap": True}),
                EffectSpec("grant_until", {
                    "previous_subject": True,
                    "static": {"type": "type_change", "params": {
                        "add_types": ["creature"], "power": 0, "toughness": 0, "add_subtypes": ["Elemental"],
                    }},
                    "extra_statics": [{"type": "grant_keyword", "params": {"keywords": ["vigilance", "haste"]}}],
                }),
            ],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("create_emblem", {"ability": {
                    "ability_kind": "static",
                    "effects": [{"type": "grant_keyword", "params": {
                        "affects": "lands_you_control", "keywords": ["indestructible"],
                    }}],
                    "trigger": None, "cost": None, "target": None, "keyword": None, "modes": None,
                    "additional_cost": None, "additional_cost_optional": False, "conditional_flash": None,
                    "cast_timing_restriction": None, "cast_condition": None, "flash_extra_cost": None,
                    "free_cast_condition": None, "optional": False,
                    "raw_text": "lands you control have indestructible.",
                    "parser": {"version": "nested", "source": "rule:oracle", "confidence": 1.0},
                }}),
                EffectSpec("search", {"criteria": {"type": "Forest"}, "destination": "battlefield_tapped", "count": 99}),
            ],
            cost={"loyalty": -8},
        ),
    ]


register("Nissa, Who Shakes the World", _nissa_who_shakes_the_world)
