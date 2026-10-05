"""Breena, the Demagogue rewards attacks against opponents."""

from __future__ import annotations

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _breena_card():
    return Card(id="br", name="Breena, the Demagogue",
                type_line="Legendary Creature — Bird Warlock", is_creature=True,
                power=1, toughness=3,
                oracle_text=("Flying\nWhenever a player attacks one of your opponents, "
                             "if that opponent has more life than another of your "
                             "opponents, that attacking player draws a card and you put "
                             "two +1/+1 counters on a creature you control."))


def test_registered_and_binds():
    assert is_registered("Breena, the Demagogue")
    spec = _REGISTRY["breena, the demagogue"]()[0]
    spec.validate()
    assert spec.trigger["defender_is_opponent"] is True
    assert spec.trigger["defending_opponent_leads_an_opponent"] is True
    assert spec.effects[0].params["selector"] == "attacking_player"
    src = GameObject(_breena_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_breena_card())


def _setup(p2_life, p3_life):
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Cara", [])],
        starting_life=20, starting_hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    eng.state.player_by_id("p2").life = p2_life
    eng.state.player_by_id("p3").life = p3_life
    br = GameObject(_breena_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    br.controller_id = "p1"
    br.summoning_sick = False
    eng.state.add_to_battlefield(br)
    bind_from_catalogue(br)
    mine = GameObject(Card(id="m", name="Mine", type_line="Creature — Bear",
                           is_creature=True, power=2, toughness=2),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    mine.controller_id = "p1"
    eng.state.add_to_battlefield(mine)
    # give every player a library so a draw is meaningful
    for pid in ("p1", "p2", "p3"):
        pl = eng.state.player_by_id(pid)
        for i in range(3):
            pl.add_to_zone(GameObject(Card(id=f"{pid}L{i}", name=f"{pid}L{i}",
                                           type_line="Plains", is_land=True),
                                      owner_id=pid, zone=Zone.LIBRARY), Zone.LIBRARY)
    eng.recompute_continuous_effects()
    return eng, mine


def test_fires_when_attacked_opponent_has_more_life_than_another_opponent():
    eng, mine = _setup(p2_life=18, p3_life=10)  # p3 (attacked) has less... attack p2
    p2 = eng.state.player_by_id("p2")
    hand_before = len(p2.hand)
    # p2 attacks p3? No — need the *attacked* opp to lead. p2 attacks... we
    # want defending_player_id = the higher-life opp. Attack p2 (life 18 > p3 10).
    eng.state.fire_event(GameEvent(
        EventType.PLAYER_ATTACKED, attacking_player_id="p3", defending_player_id="p2",
        count=1,
    ))
    eng.resolve_until_stable()
    # "put two +1/+1 counters on a creature you control" is a target choice
    if eng.state.pending_choice and eng.state.pending_choice["kind"] == "trigger_target":
        eng.resolve_pending_choice(str(mine.instance_id))
        eng.resolve_until_stable()
    assert len(eng.state.player_by_id("p3").hand) == 1  # attacking player drew
    assert mine.counters.get("+1/+1") == 2


def test_silent_when_attacked_opponent_does_not_lead():
    eng, mine = _setup(p2_life=8, p3_life=20)
    eng.state.fire_event(GameEvent(
        EventType.PLAYER_ATTACKED, attacking_player_id="p3", defending_player_id="p2",
        count=1,
    ))
    eng.resolve_until_stable()
    assert mine.counters.get("+1/+1") in (None, 0)
