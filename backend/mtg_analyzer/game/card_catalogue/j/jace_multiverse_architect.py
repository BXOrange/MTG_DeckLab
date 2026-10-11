from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jace_multiverse_architect() -> list[AbilitySpec]:
    """At the beginning of combat on each opponent's turn, they may pay {2}. If they don't, creatures they control can't attack
    Jaces you control this turn.
    +1: Draw two cards, then put a card from your hand on the bottom of your library.
    −3: Exile another target planeswalker or creature you control. Reveal cards from the top of your library until you reveal a
    creature or planeswalker card. Put that card onto the battlefield and the rest on the bottom of your library in a random order.
    Jace, Multiverse Architect can be your commander.

    — PLAY-ALL (Multiverse Reforged). The first ability is `each_player_pay_or` with the new ``active_player`` scope (only the
    opponent whose turn it is is asked) over `prevent_attacking_planeswalkers_this_turn` (a ``(they, you, "jace")`` bar that
    `GameEngine.legal_defenders_for` honours). The +1 is `draw` plus `choose_hand_card_to_library_bottom` (a real hand pick). The −3
    is `replace_target_with_revealed` over the new ``another_creature_or_planeswalker_you_control`` target frame. The commander
    clause is the card's own (no engine effect). The opponent may pay using available mana abilities through the shared
    pay-or prompt (RULE 117.12b). Its game-rule restriction includes later Jaces controlled by the ability's controller
    (RULE 611.2c), independently of ownership.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("each_player_pay_or", {
                "cost": "{2}", "scope": "active_player", "effect_targets": "decliner",
                "effects": [{"type": "prevent_attacking_planeswalkers_this_turn", "params": {"subtype": "jace"}}],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "not_you"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 2}), EffectSpec("choose_hand_card_to_library_bottom", {})],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("replace_target_with_revealed", {
                "target_kind": "another_creature_or_planeswalker_you_control", "removal": "exile",
                "revealer": "controller", "criteria": {"type": ["Creature", "Planeswalker"]},
            })],
            cost={"loyalty": -3},
        ),
    ]


register("Jace, Multiverse Architect", _jace_multiverse_architect)
