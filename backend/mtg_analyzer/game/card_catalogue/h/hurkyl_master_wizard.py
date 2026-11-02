from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hurkyl_master_wizard() -> list[AbilitySpec]:
    "At the beginning of your end step, if you've cast a noncreature spell this turn, reveal the top five cards of your library. For each card type among noncreature spells you've cast this turn, you may put a card of that type from among the revealed cards into your hand. Put the rest on the bottom of your library in a random order."
    return [
        AbilitySpec(
            'triggered',
            # RULE 603.4: the intervening "if" is the `active_if` condition (checked on trigger and on resolution).
            # `reveal_top_type_picks` (game/effects/type_picks.py) reveals the top five, asks one optional pick per
            # card type among this turn's noncreature spells, and bottoms the rest in a random order.
            [EffectSpec('reveal_top_type_picks', {"count": 5})],
            trigger={
                "event": EventType.STEP_BEGIN,
                "filter": {"step": "end"},
                "phase_relation": "you",
                "active_if": {"kind": "cast_noncreature_spell_this_turn"},
            },
            raw_text="at the beginning of your end step, if you've cast a noncreature spell this turn, reveal the top 5 cards of your library. for each card type among noncreature spells you've cast this turn, you may put a card of that type from among the revealed cards into your hand. put the rest on the bottom of your library in a random order.",
        ),
    ]


register('Hurkyl, Master Wizard', _hurkyl_master_wizard)
