"""MEC-175 (RULE 605.1a): the effects a mana ability does besides adding mana.

A mana ability may also gain life, draw, or sacrifice its source (RULE 605.1a); it still resolves immediately and
uses no stack (RULE 605.3b). The one exception is a *delayed* draw ("Draw a card at the beginning of the next turn's
upkeep", Astrolabe): that is a delayed triggered ability (RULE 603.7) and uses the stack when it triggers.
`GameEngine.tap_for_mana` and a copied mana ability's resolution (RULE 707.10) share this one applier.
"""
from __future__ import annotations

from typing import Any

from ..models.game.game_state import DelayedTrigger
from ..parser.oracle.spec import EffectSpec
from . import static_conditions

#: The step a delayed draw waits for (RULE 503, upkeep) and its stack-item label.
DELAYED_DRAW_STEP = "upkeep"
DELAYED_DRAW_DESCRIPTION = "Karte ziehen (nächster Versorgungsschritt)"


def apply_mana_ability_extras(rules: Any, player: Any, source: Any, ability: Any) -> None:
    """Carry out ``ability``'s life / draw / sacrifice riders for ``player`` after the mana is added."""
    state = rules.state
    if ability.gain_life and (
        ability.gain_life_when is None
        or static_conditions.condition_holds(ability.gain_life_when, state, source=source, controller_id=player.id)
    ):
        rules.gain_life(player, ability.gain_life)
    if ability.draw_cards:
        rules.draw(player, ability.draw_cards)
    if ability.delayed_draw_cards:
        _arm_delayed_draw(state, player, source, ability.delayed_draw_cards)
    kind = ability.sacrifice_when_no_counters
    if (
        kind is not None and source in state.battlefield
        and not (source.counters or {}).get(kind, 0)
    ):
        # RULE 701.17a: the source sacrifices itself once its last <kind> counter is gone.
        rules.put_into_graveyard(source)


def _arm_delayed_draw(state: Any, player: Any, source: Any, count: int) -> None:
    from .binding.core import build_effects  # function-scoped: the binder imports the effect modules

    effects = build_effects([EffectSpec("draw", {"count": count})], source)
    state.delayed_triggers.append(DelayedTrigger(
        player.id, DELAYED_DRAW_STEP, effects, scope="any", description=DELAYED_DRAW_DESCRIPTION,
        # RULE 603.7: "the next turn's upkeep" is never the current turn's (an instant-speed activation in this
        # upkeep names the following one).
        min_turn=state.internal_turn.number + 1,
    ))
