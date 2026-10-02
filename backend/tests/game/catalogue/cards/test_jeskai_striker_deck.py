"""The saved "Jeskai Striker" deck (PLAY-ALL Step 2): parser-claimed loots plus hand-authored cards."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _game():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state, engine.state.active_player


def _stock_library(player, n, type_line="Land"):
    for i in range(n):
        player.library.append(GameObject(
            Card(id=f"L{i}", name=f"Library {i}", type_line=type_line, is_land=type_line == "Land"),
            owner_id=player.id, zone=Zone.LIBRARY,
        ))


def _to_hand(player, name, type_line, cost="{U}", cmc=1, **kw) -> GameObject:
    obj = GameObject(
        Card(id=name, name=name, type_line=type_line, mana_cost_string=cost, converted_mana_cost=cmc, **kw),
        owner_id=player.id, zone=Zone.HAND,
    )
    player.hand.append(obj)
    bind_from_catalogue(obj)
    return obj


def _research(engine, player):
    spell = _to_hand(player, "Compulsive Research", "Sorcery", "{2}{U}", 3, is_sorcery=True, oracle_text=(
        "Target player draws three cards. Then that player discards two cards unless they discard a land card."
    ))
    player.mana_pool.add_many({"U": 3})
    engine.cast_spell(player, spell, targets=[player])
    engine.resolve_until_stable()
    return spell


def test_compulsive_research_land_discard_replaces_two_discards():
    engine, state, player = _game()
    _stock_library(player, 3)  # three lands drawn
    _research(engine, player)
    choice = state.pending_choice
    assert choice["action"] == "discard" and choice["count"] == 1
    assert any(o["id"] == "decline" for o in choice["options"])  # "unless" is optional
    engine.resolve_pending_choice(str(choice["options"][0]["instance_id"]))
    engine.resolve_until_stable()
    assert state.pending_choice is None and len(player.hand) == 2


def test_compulsive_research_declining_the_land_discards_two():
    engine, state, player = _game()
    _stock_library(player, 3)
    _research(engine, player)
    engine.resolve_pending_choice("decline")
    assert state.pending_choice["action"] == "discard" and state.pending_choice["count"] == 2
    for _ in range(2):
        engine.resolve_pending_choice(str(state.pending_choice["options"][0]["instance_id"]))
    assert state.pending_choice is None and len(player.hand) == 1


def test_compulsive_research_without_a_land_must_discard_two():
    engine, state, player = _game()
    _stock_library(player, 3, type_line="Creature")
    _research(engine, player)
    assert state.pending_choice["count"] == 2  # no land in hand, so no "unless" offer
    assert not any(o["id"] == "decline" for o in state.pending_choice["options"])


def test_frantic_search_loots_then_untaps_up_to_three_lands():
    engine, state, player = _game()
    _stock_library(player, 2)
    lands = []
    for i in range(4):
        land = GameObject(
            Card(id=f"F{i}", name="Island", type_line="Basic Land — Island", is_land=True),
            owner_id=player.id, zone=Zone.BATTLEFIELD,
        )
        land.controller_id = player.id
        land.tapped = True
        state.add_to_battlefield(land)
        lands.append(land)
    spell = _to_hand(player, "Frantic Search", "Instant", "{2}{U}", 3, is_instant=True, oracle_text=(
        "Draw two cards, then discard two cards. Untap up to three lands."
    ))
    player.mana_pool.add_many({"U": 3})
    engine.cast_spell(player, spell)
    engine.resolve_until_stable()
    # Draw 2 then discard 2: the hand is empty again, so the discard was forced.
    assert len(player.hand) == 0 and len(player.graveyard) == 3  # the 2 looted cards + the spell
    for _ in range(3):
        assert state.pending_choice["action"] == "untap"
        engine.resolve_pending_choice(str(state.pending_choice["options"][0]["instance_id"]))
        engine.resolve_until_stable()
        if state.pending_choice is None:
            break
    assert sum(1 for land in lands if not land.tapped) == 3  # "up to three", not all four


def _creature(state, player, name):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2),
        owner_id=player.id, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = player.id
    state.add_to_battlefield(obj)
    return obj


def _cast_time_wipe(engine, player):
    spell = _to_hand(player, "Time Wipe", "Sorcery", "{2}{W}{W}{U}", 5, is_sorcery=True)
    player.mana_pool.add_many({"W": 2, "U": 1, "R": 2})
    engine.cast_spell(player, spell)
    engine.resolve_until_stable()


def test_time_wipe_saves_the_creature_you_return_and_destroys_the_rest():
    engine, state, player = _game()
    saved = _creature(state, player, "Saved")
    doomed = _creature(state, player, "Doomed")
    foe = _creature(state, state.player_by_id("p2"), "Foe")
    _cast_time_wipe(engine, player)
    assert state.pending_choice["action"] == "return_to_hand"
    engine.resolve_pending_choice(str(saved.instance_id))
    engine.resolve_until_stable()
    assert saved.zone == Zone.HAND
    assert doomed.zone == Zone.GRAVEYARD and foe.zone == Zone.GRAVEYARD


def test_time_wipe_still_wipes_when_you_control_no_creature():
    engine, state, player = _game()
    foe = _creature(state, state.player_by_id("p2"), "Foe")
    _cast_time_wipe(engine, player)
    engine.resolve_until_stable()
    assert state.pending_choice is None and foe.zone == Zone.GRAVEYARD


def test_voracious_bibliophile_draws_one_card_per_target():
    engine, state, player = _game()
    _stock_library(player, 5)
    bibliophile = GameObject(
        Card(id="vb", name="Voracious Bibliophile", type_line="Creature — Dragon", is_creature=True,
             power=2, toughness=4, keywords=["Flying", "Vigilance"]),
        owner_id=player.id, zone=Zone.BATTLEFIELD,
    )
    bibliophile.controller_id = player.id
    bind_from_catalogue(bibliophile)
    state.add_to_battlefield(bibliophile)
    foe = _creature(state, state.player_by_id("p2"), "Foe")
    bolt = _to_hand(player, "Shock", "Instant", "{R}", 1, is_instant=True, oracle_text="Shock deals 2 damage to any target.")
    player.mana_pool.add_many({"R": 1})
    engine.cast_spell(player, bolt, targets=[foe])
    engine.resolve_until_stable()
    assert len(player.hand) == 1  # one target, one card
    untargeted = _to_hand(player, "Divination", "Sorcery", "{2}{U}", 3, is_sorcery=True, oracle_text="Draw two cards.")
    player.mana_pool.add_many({"U": 3})
    before = len(player.hand)
    engine.cast_spell(player, untargeted)
    engine.resolve_until_stable()
    assert len(player.hand) == before - 1 + 2  # the spell's own two cards, no trigger


def _shiko(state, player):
    obj = GameObject(
        Card(id="sn", name="Shiko and Narset, Unified", type_line="Legendary Creature — Human Spirit Dragon",
             is_creature=True, power=4, toughness=4, keywords=["Flying", "Vigilance"]),
        owner_id=player.id, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = player.id
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _spark(player):
    return _to_hand(player, "Spark", "Instant", "{R}", 1, is_instant=True,
                    oracle_text="Spark deals 1 damage to any target.")


def test_shiko_and_narset_copies_the_second_targeted_spell():
    engine, state, player = _game()
    _stock_library(player, 3)
    _shiko(state, player)
    foe = state.player_by_id("p2")
    first, second = _spark(player), _spark(player)
    player.mana_pool.add_many({"R": 2})
    engine.cast_spell(player, first, targets=[foe])
    engine.resolve_until_stable()
    life_after_first = foe.life
    assert len(player.hand) == 1  # the first spell triggers nothing
    engine.cast_spell(player, second, targets=[foe])
    engine.resolve_until_stable()
    assert foe.life == life_after_first - 2  # the spell plus its copy
    assert len(player.hand) == 0  # nothing was drawn: the copy happened


def test_shiko_and_narset_draws_when_the_second_spell_has_no_target():
    engine, state, player = _game()
    _stock_library(player, 3)
    _shiko(state, player)
    first = _spark(player)
    player.mana_pool.add_many({"R": 1, "U": 3})
    engine.cast_spell(player, first, targets=[state.player_by_id("p2")])
    engine.resolve_until_stable()
    divination = _to_hand(player, "Divination", "Sorcery", "{2}{U}", 3, is_sorcery=True, oracle_text="Draw two cards.")
    engine.cast_spell(player, divination)
    engine.resolve_until_stable()
    assert len(player.hand) == 3  # Divination's two plus Shiko's replacement draw


def _training_post(state, player):
    obj = GameObject(
        Card(id="atp", name="Adaptive Training Post", type_line="Artifact", mana_cost_string="{2}{U}",
             converted_mana_cost=3),
        owner_id=player.id, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = player.id
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_adaptive_training_post_stops_charging_at_three_and_copies_the_next_spell():
    engine, state, player = _game()
    post = _training_post(state, player)
    foe = state.player_by_id("p2")
    for _ in range(4):
        spark = _spark(player)
        player.mana_pool.add_many({"R": 1})
        engine.cast_spell(player, spark, targets=[foe])
        engine.resolve_until_stable()
    assert post.counters.get("charge") == 3  # the fourth spell found it already at three

    ability = next(a for a in engine.legal_actions(player)
                   if a["type"] == "activate_ability" and a["instance_id"] == post.instance_id)
    engine.activate_ability(player, post, ability["ability_index"])
    engine.resolve_until_stable()
    assert post.counters.get("charge", 0) == 0
    life_before = foe.life
    spark = _spark(player)
    player.mana_pool.add_many({"R": 1})
    engine.cast_spell(player, spark, targets=[foe])
    engine.resolve_until_stable()
    assert foe.life == life_before - 2  # the spell and its copy
