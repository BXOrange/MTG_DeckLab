"""Hand-authored cards of the saved "Oops! All Night's Whispers" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import battlefield_object


def _game(*deck_names):
    cards = [CardDatabase(DB_PATH).get_card(name) for name in deck_names]
    engine = GameEngine.new_game([("p1", "A", cards), ("p2", "B", [])], starting_hand=len(cards), starting_life=20)
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.player_by_id("p1")
    for i in range(4):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"Lib {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    return engine, p1, engine.state.player_by_id("p2")


def _cast_wisps(name, color, keyword):
    engine, p1, p2 = _game(name)
    bear = battlefield_object(engine, "p1", "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2, color_identity={"G"})
    p1.mana_pool.add_many({"B": 1, "R": 1, "U": 1})
    hand_before = len(p1.hand)
    engine.cast_spell(p1, p1.hand[0], targets=[bear])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert len(p1.hand) == hand_before - 1 + 1  # the spell left the hand, "draw a card" refilled it
    assert bear.colors == {color} and combat.has(bear, keyword)  # "becomes <colour>" replaces green

    engine._step_cleanup()
    engine.recompute_continuous_effects()
    assert bear.colors == {"G"} and not combat.has(bear, keyword)  # until end of turn


def test_aphotic_wisps_makes_the_creature_black_with_fear_and_draws():
    _cast_wisps("Aphotic Wisps", "B", "fear")


def test_crimson_wisps_makes_the_creature_red_with_haste_and_draws():
    _cast_wisps("Crimson Wisps", "R", "haste")


def _creature_card(name, owner):
    return GameObject(
        Card(id=name, name=name, type_line="Creature — Beast", is_creature=True, power=2, toughness=2),
        owner_id=owner, zone=Zone.GRAVEYARD,
    )


def test_exhume_lets_each_player_choose_a_creature_from_their_own_graveyard():
    engine, p1, p2 = _game("Exhume")
    mine = [_creature_card("My Beast", "p1"), _creature_card("My Other Beast", "p1")]
    theirs = [_creature_card("Their Beast", "p2"), _creature_card("Their Other Beast", "p2")]
    p1.graveyard.extend(mine)
    p2.graveyard.extend(theirs)
    p1.mana_pool.add_many({"B": 1, "C": 1})
    engine.cast_spell(p1, p1.hand[0])
    engine.resolve_until_stable()

    first = engine.state.pending_choice
    assert first["player_id"] == "p1" and {o["label"] for o in first["options"] if "instance_id" in o} == {"My Beast", "My Other Beast"}
    engine.resolve_pending_choice(next(o["id"] for o in first["options"] if o.get("label") == "My Other Beast"))
    engine.resolve_until_stable()
    second = engine.state.pending_choice
    assert second["player_id"] == "p2" and {o["label"] for o in second["options"] if "instance_id" in o} == {"Their Beast", "Their Other Beast"}
    engine.resolve_pending_choice(next(o["id"] for o in second["options"] if o.get("label") == "Their Beast"))
    engine.resolve_until_stable()

    assert mine[1].zone == Zone.BATTLEFIELD and mine[1].controller_id == "p1" and mine[0].zone == Zone.GRAVEYARD
    assert theirs[0].zone == Zone.BATTLEFIELD and theirs[0].controller_id == "p2" and theirs[1].zone == Zone.GRAVEYARD


def _fill_graveyard(player, n):
    for i in range(n):
        player.graveyard.append(GameObject(Card(id=f"F{i}", name=f"Filler {i}", type_line="Sorcery", is_sorcery=True), owner_id=player.id, zone=Zone.GRAVEYARD))


def test_stitch_together_returns_to_hand_but_to_the_battlefield_with_threshold():
    for fillers, expected in ((4, Zone.HAND), (6, Zone.BATTLEFIELD)):  # 5 cards vs 7 cards in the graveyard with the target
        engine, p1, p2 = _game("Stitch Together")
        target = _creature_card("Fallen Beast", "p1")
        p1.graveyard.append(target)
        _fill_graveyard(p1, fillers)
        p1.mana_pool.add_many({"B": 2})
        engine.cast_spell(p1, p1.hand[0], targets=[target])
        engine.resolve_until_stable()
        assert target.zone == expected, (fillers, target.zone)


def test_ghastly_demise_destroys_a_nonblack_creature_only_while_its_toughness_fits_my_graveyard():
    def cast(graveyard_cards, color):
        engine, p1, p2 = _game("Ghastly Demise")
        victim = battlefield_object(
            engine, "p2", "Victim", "Creature — Beast", is_creature=True, power=2, toughness=3, color_identity={color},
        )
        _fill_graveyard(p1, graveyard_cards)
        p1.mana_pool.add_many({"B": 1})
        engine.cast_spell(p1, p1.hand[0], targets=[victim])
        engine.resolve_until_stable()
        return victim

    assert cast(3, "G").zone != Zone.BATTLEFIELD  # toughness 3 <= 3 cards (+ the resolved spell makes 4 anyway)
    assert cast(1, "G").zone == Zone.BATTLEFIELD  # toughness 3 > 1 card in the graveyard: nothing happens
