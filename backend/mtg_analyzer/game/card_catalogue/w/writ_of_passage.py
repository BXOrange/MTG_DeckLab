# save as: /Users/berndzacharias/Desktop/MTG_Deck_Analyzer/.claude/worktrees/agent-a4fa0133717909b9f/backend/mtg_analyzer/game/card_catalogue/w/writ_of_passage.py
# (one file per card, in the folder named after its lowercased first letter —
#  see game/card_catalogue/__init__.py and docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md)
# ALSO add to /Users/berndzacharias/Desktop/MTG_Deck_Analyzer/.claude/worktrees/agent-a4fa0133717909b9f/backend/mtg_analyzer/game/card_catalogue/w/__init__.py:
#     from . import writ_of_passage  # noqa: F401

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

# "Whenever enchanted creature attacks, if its power is 2 or less, it can't be blocked this turn."
# RULE 603.4: the intervening-if is checked when the attack trigger would trigger (trigger-time `active_if` gate;
# not re-checked on resolution); it reads the *enchanted creature's* derived power
# (`of="attached"`), not the Aura's. RULE 303.4 / 301.5: the trigger subject and the effect's
# "it" both follow `attached_to`, so no RULE 115 target is chosen. RULE 509.1b: the effect sets
# `temp_unblockable`, which `can_block` reads and cleanup clears (RULE 514.2).
WRIT_MAX_POWER = 2  # printed "power is 2 or less"


def _writ_of_passage() -> list[AbilitySpec]:
    "Enchant creature\nWhenever enchanted creature attacks, if its power is 2 or less, it can't be blocked this turn.\nForecast — {1}{U}, Reveal this card from your hand: Target creature with power 2 or less can't be blocked this turn. (Activate only during your upkeep and only once each turn.)"
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("unblockable", {"target_kind": "attached_permanent"})],
            trigger={
                "event": EventType.ATTACKS,
                "condition": {"subject": "attached_permanent"},
                "active_if": {"kind": "power", "of": "attached", "max": WRIT_MAX_POWER},
            },
            raw_text="whenever enchanted creature attacks, if its power is 2 or less, it can't be blocked this turn.",
        ),
        AbilitySpec(
            'activated',
            [EffectSpec('unblockable', {"target_kind": 'creature', "creature_filter": {'max_power': WRIT_MAX_POWER}}), EffectSpec('from_hand_marker', {}), EffectSpec('activation_condition_marker', {"condition": {'kind': 'your_upkeep'}}), EffectSpec('once_per_turn_marker', {})],
            cost={"text": '{1}{u}'},
            raw_text="forecast — {1}{u}, reveal this card from your hand: target creature with power 2 or less can't be blocked this turn.",
        ),
    ]


register('Writ of Passage', _writ_of_passage)
