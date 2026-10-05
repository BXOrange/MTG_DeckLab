"""PAR-112 — "for each `<objects>`, create a token that's a copy of it", and the phase
trigger's ability-wide intervening-if.

Ocelot Pride: "At the beginning of your end step, if you gained life this turn, create a
1/1 white Cat creature token. Then if you have the city's blessing, for each token you
control that entered this turn, create a token that's a copy of it."

Three pieces: a *leading* "for each `<count phrase>`," iterating objects (the body's "it"
is the loop item — `copy_permanent`'s ``referent: "iteration"``), the count-phrase tail
"that entered this turn", and RULE 603.4 — the leading "if" gates the whole ability, so
with no life gained the copies are not made either.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.count_phrase import parse_count_phrase
from mtg_analyzer.parser.oracle.gate import parse_oracle as _parse
from mtg_analyzer.services.card_database import CardDatabase

pytestmark = pytest.mark.full_cache


def _named(name):
    return CardDatabase(DB_PATH).get_card(name)


def _engine():
    state = GameState(players=[Player(id="p1", name="Alice", life=20),
                               Player(id="p2", name="Bob", life=20)])
    state.current_step = "end"
    return GameEngine(state), state


def _board(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _token(state, name="Soldier", owner="p1", earlier_turn=False):
    card = Card(id=name, name=name, type_line=f"Token Creature — {name}", is_creature=True,
                power=1, toughness=1)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.is_token = True
    state.add_to_battlefield(obj)
    if earlier_turn:
        obj.turn_entered = state.internal_turn.number - 1
    return obj


def _end_step(engine, state):
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
    engine.resolve_until_stable()


def _names(state, owner="p1"):
    return sorted(o.name for o in state.battlefield if o.controller_id == owner and o.is_token)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def test_entered_this_turn_is_a_count_phrase_tail():
    assert parse_count_phrase("token you control that entered this turn") == {
        "zone": "battlefield", "of": "you", "filter": {"token": True, "entered_this_turn": True},
    }


def test_the_leading_if_of_a_multi_sentence_phase_trigger_gates_the_whole_ability():
    [spec] = [s for s in parse_oracle(_named("Ocelot Pride")).specs if s.ability_kind == "triggered"]
    assert spec.trigger["active_if"] == {"kind": "gained_life_this_turn"}
    cat, each = spec.effects
    assert cat.type == "create_token" and cat.condition is None
    assert each.type == "for_each" and each.condition == {"kind": "has_city_blessing"}
    assert each.params["effects"] == [
        {"type": "copy_permanent", "params": {"target_kind": None, "referent": "iteration"}}
    ]


def test_a_one_sentence_phase_body_keeps_its_per_effect_gate():
    result = _parse(Card(id="X", name="X", type_line="Enchantment", oracle_text=(
        "At the beginning of your end step, if you gained life this turn, draw a card.")))
    [spec] = result.specs
    assert "active_if" not in spec.trigger
    assert spec.effects[0].condition == {"kind": "gained_life_this_turn"}


@pytest.mark.parametrize("oracle", [
    # the body targets — `for_each` would override the announced target with the item
    "At the beginning of your end step, for each creature you control, "
    "put a +1/+1 counter on target creature.",
    # a pronoun this family has no iteration reading for
    "At the beginning of your end step, for each creature you control, destroy it.",
    # not a battlefield group
    "At the beginning of your end step, for each creature card in your graveyard, "
    "create a token that's a copy of it.",
])
def test_bodies_the_iteration_cannot_carry_fail_closed(oracle):
    assert not _parse(Card(id="X", name="X", type_line="Enchantment", oracle_text=oracle)).modeled


@pytest.mark.parametrize("name", [
    "Ocelot Pride", "Chief Magistrate of Mercadia", "Renewed Solidarity",
])
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def _ocelot_board(*, gained_life, blessing):
    engine, state = _engine()
    _board(state, _named("Ocelot Pride"))
    _token(state, "Soldier")                     # entered this turn
    _token(state, "Old", earlier_turn=True)      # did not
    you = state.player_by_id("p1")
    you.has_city_blessing = blessing
    if gained_life:
        engine.rules.gain_life(you, 1)
    return engine, state


def test_ocelot_pride_copies_each_token_that_entered_this_turn():
    engine, state = _ocelot_board(gained_life=True, blessing=True)
    _end_step(engine, state)
    # The Cat is made first, so it entered this turn too (RULE 608.2 order).
    assert _names(state) == ["Cat", "Cat", "Old", "Soldier", "Soldier"]


def test_without_the_citys_blessing_only_the_cat_is_made():
    engine, state = _ocelot_board(gained_life=True, blessing=False)
    _end_step(engine, state)
    assert _names(state) == ["Cat", "Old", "Soldier"]


def test_without_life_gained_the_whole_ability_does_nothing():
    engine, state = _ocelot_board(gained_life=False, blessing=True)
    _end_step(engine, state)
    assert _names(state) == ["Old", "Soldier"]


def test_a_false_intervening_if_also_skips_the_second_sentence():
    # Before the fix the gate sat on the Cat alone and "then draw a card" always ran
    # (Wary Zone Guard's perpetual +1/+1 was ungated the same way).
    oracle = ("At the beginning of your end step, if you gained life this turn, "
              "create a 1/1 white Cat creature token. Then draw a card.")
    for gained, drawn in ((False, 0), (True, 1)):
        engine, state = _engine()
        _board(state, Card(id="Gate", name="Gate", type_line="Enchantment", oracle_text=oracle))
        you = state.player_by_id("p1")
        you.library.append(GameObject(Card(id="L", name="L", type_line="Instant"),
                                      owner_id="p1", zone=Zone.LIBRARY))
        if gained:
            engine.rules.gain_life(you, 1)
        _end_step(engine, state)
        assert len(you.hand) == drawn


def test_chief_magistrate_copies_every_creature_token_while_monarch():
    engine, state = _engine()
    state.current_step = "upkeep"
    _board(state, _named("Chief Magistrate of Mercadia"))
    _token(state, "Old", earlier_turn=True)
    state.monarch_id = "p1"
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="upkeep"))
    engine.resolve_until_stable()
    assert _names(state) == ["Goblin", "Goblin", "Old", "Old"]
