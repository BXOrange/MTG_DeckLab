from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Rootha, Mastering the Moment (greatest i/s mv this turn) — PAR-60
# ===========================================================================
# New `GameState.greatest_instant_sorcery_mv_this_turn` tracker (bumped in
# `_track_spell_cast`, reset in `begin_turn`) + the
# ``greatest_instant_sorcery_mv_this_turn`` count_selector + a
# ``cast_instant_or_sorcery_this_turn`` trigger intervening-if predicate.
# The X/X is a `bind` over that count.


def _rootha_mastering_the_moment() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, if you've cast an instant or
    sorcery spell this turn, create an X/X blue and red Elemental creature
    token with flying and haste, where X is the greatest mana value among
    instant and sorcery spells you've cast this turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "x",
                "amount": {"kind": "count_selector", "selector": "greatest_instant_sorcery_mv_this_turn"},
                "effects": [{"type": "create_token", "params": {
                    "count": 1, "colors": ["U", "R"], "subtypes": ["Elemental"],
                    "keywords": ["flying", "haste"], "token_name": "Elemental",
                    "power": "$x", "toughness": "$x",
                }}],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"},
                     "phase_relation": "you",
                     "cast_instant_or_sorcery_this_turn": True},
        ),
    ]


register("Rootha, Mastering the Moment", _rootha_mastering_the_moment)
