"""Both paths and the complete Fate Reforged Saga of the Dragon Brothers."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.dragon_brothers import LEGENDS_ELDER_DRAGONS
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game


NAME = "The Battle of Dragon Brothers"


def _board(players=2):
    engine = game(players=players, library=30)
    player = engine.state.player_by_id("p1")
    source = card(engine, NAME, zone=Zone.HAND)
    cast(engine, source)
    if engine.state.pending_choice["kind"] != "dragon_brothers_path":
        engine.resolve_pending_choice("p2")
    return engine, source, player


def _back(path, players=2):
    engine, source, player = _board(players)
    engine.resolve_pending_choice(path)
    engine.rules.deal_damage(source, source.defense)
    engine.resolve_until_stable()
    assert source.zone == Zone.EXILE and source.chosen_mode == path
    engine.cast_spell(player, source)
    engine.resolve_until_stable()
    assert source.name == "Fate Reforged" and source.zone == Zone.BATTLEFIELD
    return engine, source, player


def _chapter(engine, source, number):
    assert number == source.lore + 1
    engine.rules.advance_sagas(engine.state.player_by_id(source.controller_id))
    engine.resolve_until_stable()


def test_front_fresh_specs_and_real_cast_wait_for_bolas_or_ugin():
    engine, source, player = _board()
    assert source.defense == 6 and source.protector_id == "p2"
    assert source.chosen_mode is None
    assert engine.state.pending_choice["kind"] == "dragon_brothers_path"
    assert {o["id"] for o in engine.state.pending_choice["options"]} == {"bolas", "ugin"}
    first, second = specs_for(source.card), specs_for(source.card)
    assert first is not second and first[0] is not second[0]
    for spec in first:
        spec.validate()
    assert len(source.triggered_abilities) == 1 and source.static_effects


def test_bolas_destroys_all_players_creatures_but_not_noncreatures():
    engine, source, player = _board(players=3)
    creatures = [filler(engine, f"Body {i}", player=f"p{i}", power=2, toughness=2) for i in (1, 2, 3)]
    artifact = filler(engine, "Artifact", type_line="Artifact")
    indestructible = card(engine, "Darksteel Myr", "p2")
    engine.resolve_pending_choice("bolas")
    assert all(obj.zone == Zone.GRAVEYARD for obj in creatures)
    assert artifact.zone == Zone.BATTLEFIELD and indestructible.zone == Zone.BATTLEFIELD
    assert source.chosen_mode == "bolas"


def test_ugin_manifests_exact_top_three_cards_without_revealing_them():
    engine, source, player = _board()
    top = list(player.library[-3:])
    remaining = len(player.library)
    engine.resolve_pending_choice("ugin")
    assert len(player.library) == remaining - 3
    assert all(obj.zone == Zone.BATTLEFIELD and obj.face_down for obj in top)
    assert all(obj.power == 2 and obj.toughness == 2 and obj.controller_id == "p1" for obj in top)
    assert not any(e.type == EventType.REVEAL for e in engine.state.events_this_turn())
    assert source.chosen_mode == "ugin"


@pytest.mark.parametrize("size", [0, 1, 2])
def test_ugin_manifests_as_many_as_possible_with_short_library(size):
    engine, source, player = _board()
    player.library[:] = player.library[:size]
    engine.resolve_pending_choice("ugin")
    assert not player.library
    assert len([o for o in engine.state.battlefield if o.face_down]) == size


def test_invalid_path_does_not_destroy_or_manifest_anything():
    engine, source, player = _board()
    with pytest.raises(ValueError):
        engine.resolve_pending_choice("both")
    assert source.chosen_mode is None and engine.state.pending_choice["kind"] == "dragon_brothers_path"


def test_departed_source_still_resolves_the_ugin_branch_for_original_controller():
    engine, source, player = _board()
    engine.rules.exile(source)
    engine.resolve_pending_choice("ugin")
    assert source.zone == Zone.EXILE and source.chosen_mode is None
    assert len([o for o in engine.state.battlefield if o.face_down and o.controller_id == "p1"]) == 3


def test_front_choice_survives_clone():
    engine, source, player = _board()
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice("ugin")
    assert clone.state.find_object(source.instance_id).chosen_mode == "ugin"
    assert source.chosen_mode is None


def test_bolas_chapter_one_discards_all_opponents_hands_and_draws_seven():
    engine, source, player = _board(players=3)
    hands = [card(engine, "Shock", seat, Zone.HAND) for seat in ("p2", "p3")]
    own = card(engine, "Divination", zone=Zone.HAND)
    engine.resolve_pending_choice("bolas")
    engine.rules.deal_damage(source, source.defense)
    engine.resolve_until_stable()
    engine.cast_spell(player, source)
    engine.resolve_until_stable()
    assert source.name == "Fate Reforged" and source.chosen_mode == "bolas" and source.lore == 1
    assert len(player.hand) == 8 and own in player.hand
    assert all(obj.zone == Zone.GRAVEYARD for obj in hands)
    assert not engine.state.pending_choice


def test_ugin_chapter_one_manifests_whole_hand_before_drawing_seven():
    engine, source, player = _board()
    hand = [card(engine, name, zone=Zone.HAND) for name in ("Shock", "Grizzly Bears")]
    opponent_hand = card(engine, "Divination", "p2", Zone.HAND)
    engine.resolve_pending_choice("ugin")
    engine.rules.deal_damage(source, source.defense)
    engine.resolve_until_stable()
    engine.cast_spell(player, source)
    engine.resolve_until_stable()
    assert source.name == "Fate Reforged" and source.chosen_mode == "ugin"
    assert engine.state.pending_choice["kind"] == "choose_objects" and len(player.hand) == 2
    engine.resolve_pending_choice(str(hand[1].instance_id))
    assert hand[1].face_down and hand[0] in player.hand and len(player.hand) == 1
    engine.resolve_pending_choice(str(hand[0].instance_id))
    assert all(obj.face_down and obj.zone == Zone.BATTLEFIELD for obj in hand)
    assert len(player.hand) == 7 and opponent_hand.zone == Zone.HAND
    assert hand[0].is_creature and hand[0].power == 2


@pytest.mark.parametrize("path", ["bolas", "ugin"])
def test_empty_hand_first_chapter_still_draws_seven(path):
    engine, source, player = _back(path)
    assert source.lore == 1 and len(player.hand) == 7
    assert not engine.state.pending_choice


@pytest.mark.parametrize("name", LEGENDS_ELDER_DRAGONS)
def test_chapter_two_creates_a_real_legendary_elder_dragon_copy(name):
    engine, source, player = _back("bolas")
    _chapter(engine, source, 2)
    assert engine.state.pending_choice["kind"] == "dragon_brothers_elder"
    assert {o["id"] for o in engine.state.pending_choice["options"]} == set(LEGENDS_ELDER_DRAGONS)
    engine.resolve_pending_choice(name)
    token, = [o for o in engine.state.battlefield if o.is_token]
    assert token.name == name and token.is_legendary and token.power == 7
    assert token.toughness == (9 if name == "Arcades Sabboth" else 7)
    assert token.controller_id == "p1" and token.has_subtype("Elder") and token.has_subtype("Dragon")
    assert token.triggered_abilities or token.activated_abilities or token.static_effects


def test_chapter_three_returns_front_face_and_makes_a_new_path_choice():
    engine, source, player = _back("bolas")
    _chapter(engine, source, 2)
    engine.resolve_pending_choice("Nicol Bolas")
    old_visit = source.zone_incarnation
    _chapter(engine, source, 3)
    assert source.name.split(" // ")[0] == NAME and source.zone == Zone.BATTLEFIELD
    assert source.zone_incarnation != old_visit and source.chosen_mode is None and source.defense == 6
    assert engine.state.pending_choice["kind"] == "dragon_brothers_path"
    engine.resolve_pending_choice("ugin")
    assert source.chosen_mode == "ugin"
    assert any(o.name == "Nicol Bolas" and o.is_token for o in engine.state.battlefield)


def test_chapter_two_token_choice_survives_clone():
    engine, source, player = _back("ugin")
    _chapter(engine, source, 2)
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice("Chromium")
    assert any(o.is_token and o.name == "Chromium" for o in clone.state.battlefield)
    assert not any(o.is_token for o in engine.state.battlefield)


def _token(name):
    engine, source, player = _back("bolas")
    _chapter(engine, source, 2)
    engine.resolve_pending_choice(name)
    token, = [o for o in engine.state.battlefield if o.is_token]
    return engine, source, player, token


def test_arcades_token_anthem_tracks_untapped_nonattacking_creatures_live():
    engine, source, player, token = _token("Arcades Sabboth")
    ally = filler(engine, "Ally", power=2, toughness=2)
    enemy = filler(engine, "Enemy", "Creature", player="p2", power=2, toughness=2)
    assert ally.toughness == 4 and enemy.toughness == 2 and token.toughness == 9
    ally.tapped = True
    engine.recompute_continuous_effects()
    assert ally.toughness == 2
    ally.tapped, ally.attacking = False, True
    engine.recompute_continuous_effects()
    assert ally.toughness == 2  # An untapped attacker still gets no bonus.
    ally.attacking = False
    engine.recompute_continuous_effects()
    assert ally.toughness == 4
    player.mana_pool.add("W", 1)
    engine.activate_ability(player, token, 0)
    engine.resolve_until_stable()
    assert token.toughness == 10


@pytest.mark.parametrize("combat", [False, True])
def test_nicol_bolas_token_damage_discards_only_damaged_opponents_hand(combat):
    engine, source, player, token = _token("Nicol Bolas")
    opponent = engine.state.player_by_id("p2")
    victims = [card(engine, name, "p2", Zone.HAND) for name in ("Shock", "Divination")]
    own_hand = list(player.hand)
    engine.rules.deal_damage(opponent, 1, token, combat=combat)
    engine.resolve_until_stable()
    assert all(obj.zone == Zone.GRAVEYARD for obj in victims)
    assert player.hand == own_hand
    assert not engine.state.pending_choice


def test_nicol_bolas_token_damage_to_own_player_or_creature_does_not_discard():
    engine, source, player, token = _token("Nicol Bolas")
    enemy = filler(engine, "Enemy", player="p2", power=4, toughness=4)
    own_hand = list(player.hand)
    enemy_hand = card(engine, "Shock", "p2", Zone.HAND)
    engine.rules.deal_damage(player, 1, token)
    engine.rules.deal_damage(enemy, 1, token)
    engine.resolve_until_stable()
    assert player.hand == own_hand and enemy_hand.zone == Zone.HAND


@pytest.mark.parametrize("name,cost", [("Arcades Sabboth", {"G": 1, "W": 1, "U": 1}),
                                      ("Nicol Bolas", {"U": 1, "B": 1, "R": 1})])
@pytest.mark.parametrize("pay", [False, True])
def test_newly_authored_dragon_tokens_keep_their_upkeep_cost(name, cost, pay):
    engine, source, player, token = _token(name)
    player.mana_pool.empty()
    player.mana_pool.add_many(cost)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "sacrifice_unless_pay"
    engine.resolve_pending_choice("pay" if pay else "decline")
    assert (token in engine.state.battlefield) == pay
    assert player.mana_pool.total() == (0 if pay else 3)


def test_other_sagas_chapters_do_not_fire_fate_reforged_abilities():
    engine, source, player = _back("bolas")
    other = filler(engine, "Other Saga", type_line="Enchantment — Saga")
    engine.state.fire_event(GameEvent(EventType.SAGA_CHAPTER, instance_id=other.instance_id,
        chapter=2, controller_id="p1"))
    engine.resolve_until_stable()
    assert not engine.state.pending_choice and not engine.state.stack


def test_ordinary_blink_resets_the_front_faces_old_choice():
    engine, source, player = _board()
    engine.resolve_pending_choice("ugin")
    old_visit = source.zone_incarnation
    engine.rules._apply_effect_specs([{"type": "blink", "params": {"subject": "source"}}], source)
    engine.resolve_until_stable()
    assert source.zone_incarnation != old_visit and source.chosen_mode is None
    assert engine.state.pending_choice["kind"] == "dragon_brothers_path"
    engine.resolve_pending_choice("bolas")
    assert source.chosen_mode == "bolas"


@pytest.mark.parametrize("name", ["Arcades Sabboth", "Nicol Bolas"])
def test_authored_dragon_token_definitions_return_fresh_valid_specs(name):
    engine, source, player, token = _token(name)
    first, second = specs_for(token.card), specs_for(token.card)
    assert first is not second and all(a is not b for a, b in zip(first, second))
    assert len(first) == (4 if name == "Arcades Sabboth" else 3)
    for spec in first:
        spec.validate()


def test_saga_final_chapter_returns_stolen_card_to_its_owner():
    engine, source, player = _back("bolas")
    source.controller_id = "p2"
    opponent = engine.state.player_by_id("p2")
    engine.rules.advance_sagas(opponent)
    engine.resolve_until_stable()
    engine.resolve_pending_choice("Chromium")
    engine.rules.advance_sagas(opponent)
    engine.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and source.controller_id == "p1"
    assert source.name.split(" // ")[0] == NAME and source.chosen_mode is None
    assert engine.state.pending_choice["player_id"] == "p1"
    assert engine.state.pending_choice["kind"] == "dragon_brothers_path"
