"""PAR-165 -- "Activate only [during your turn,] before attackers are declared." (RULE 602.5d, 506-508).

Parser side: the three printed forms fold into `ActivationCost` flags.  Engine side: `can_activate` allows the ability
only in the steps before the declare-attackers turn-based action, and honours the turn qualifier.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle

YOU = "{T}: You gain 1 life. Activate only during your turn, before attackers are declared."
OPPONENT = "{T}: You gain 1 life. Activate only during an opponent's turn, before attackers are declared."
ANY_TURN = "{T}: You gain 1 life. Activate only before attackers are declared."
PRE_ATTACK = ("untap", "upkeep", "draw", "main1", "begin_combat")
POST_ATTACK = ("declare_attackers", "declare_blockers", "combat_damage", "end_combat", "main2", "end")


@pytest.mark.parametrize("text", [YOU, OPPONENT, ANY_TURN])
def test_timing_sentence_is_modeled(text):
    card = Card(id="Src", name="Src", type_line="Creature -- Human", is_creature=True, power=1, toughness=1,
                oracle_text=text)
    assert parse_oracle(card).coverage == MODELED


def _setup(text):
    cards = [Card(id=f"B{i}", name=f"B{i}", type_line="Creature", is_creature=True) for i in range(6)]
    eng = GameEngine.new_game([("p1", "A", cards), ("p2", "B", list(cards))], starting_life=20, starting_hand=0)
    eng.begin_turn()
    card = Card(id="Src", name="Src", type_line="Creature -- Human", is_creature=True, power=1, toughness=1,
                oracle_text=text)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    eng.state.add_to_battlefield(obj)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    return eng, obj


def _can(eng, obj, player_id):
    player = next(p for p in eng.state.players if p.id == player_id)
    return eng.can_activate(player, obj, obj.activated_abilities[0])


def test_flags_fold_into_the_cost():
    for text, mine, theirs in ((YOU, True, False), (OPPONENT, False, True), (ANY_TURN, False, False)):
        _, obj = _setup(text)
        cost = obj.activated_abilities[0].cost
        assert cost.before_attackers_declared is True
        assert (cost.only_during_your_turn, cost.only_during_opponents_turn) == (mine, theirs)


@pytest.mark.parametrize("step", PRE_ATTACK)
def test_your_turn_form_allowed_before_attackers(step):
    eng, obj = _setup(YOU)
    eng.state.current_step = step
    assert eng.state.active_player.id == "p1"
    assert _can(eng, obj, "p1") is True


@pytest.mark.parametrize("step", POST_ATTACK)
def test_your_turn_form_refused_from_declare_attackers_on(step):
    eng, obj = _setup(YOU)
    eng.state.current_step = step
    assert _can(eng, obj, "p1") is False


def test_your_turn_form_refused_on_an_opponents_turn():
    eng, obj = _setup(YOU)
    eng.state.current_step = "main1"
    eng.state.active_player_index = 1
    assert _can(eng, obj, "p1") is False


def test_opponent_turn_form():
    eng, obj = _setup(OPPONENT)
    eng.state.current_step = "main1"
    assert _can(eng, obj, "p1") is False  # own turn
    eng.state.active_player_index = 1
    assert _can(eng, obj, "p1") is True
    eng.state.current_step = "declare_attackers"
    assert _can(eng, obj, "p1") is False


def test_unqualified_form_works_on_any_turn_until_attackers():
    eng, obj = _setup(ANY_TURN)
    eng.state.active_player_index = 1
    eng.state.current_step = "begin_combat"
    assert _can(eng, obj, "p1") is True
    eng.state.current_step = "declare_blockers"
    assert _can(eng, obj, "p1") is False


def test_extra_combat_does_not_reopen_the_window():
    """Alaborn Veteran ruling (2013-09-20): with several combat phases, only before the *first* declare-attackers
    step -- a second beginning of combat (or an extra main phase) is already past it."""
    from mtg_analyzer.models.game.events import EventType, GameEvent

    eng, obj = _setup(YOU)
    eng.state.current_step = "begin_combat"
    assert _can(eng, obj, "p1") is True
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="declare_attackers", phase="combat"))
    for step in ("begin_combat", "main1"):
        eng.state.current_step = step
        assert _can(eng, obj, "p1") is False
