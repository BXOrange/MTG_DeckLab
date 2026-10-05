"""RULE 702.75a: actual land entry, hidden selection, linked cards and viewers."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import ActivatedAbility
from mtg_analyzer.game.static_conditions import condition_holds
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.game_session import _redact_face_down_exile


def _game(count=4, available=6):
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * 8) for i in range(3)],
                                 starting_hand=0, starting_life=20)
    for _ in range(10):
        engine.advance_step()
        if engine.state.current_step == "main1":
            break
    player = engine.state.active_player
    player.library.clear()
    cards = []
    for i in range(available):
        card = Card(id=f"pick{i}", name=f"Pick {i}", type_line="Sorcery", is_sorcery=True)
        obj = GameObject(card, owner_id=player.id, zone=Zone.LIBRARY)
        player.add_to_zone(obj, Zone.LIBRARY)
        cards.append(obj)
    card = Card(id="hideaway", name="Hideaway Land", type_line="Land", is_land=True,
                oracle_text=f"Hideaway {count}\nThis land enters tapped.\n{{T}}: Add {{G}}.",
                keywords=["Hideaway"])
    land = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    bind_from_catalogue(land)
    player.add_to_zone(land, Zone.HAND)
    return engine, player, land, cards


@pytest.mark.parametrize("count", [4, 5])
def test_hideaway_uses_the_printed_count_and_requires_a_card(count):
    engine, player, land, cards = _game(count)
    assert len(land.triggered_abilities) == 1
    engine.play_land(player, land)
    assert land.tapped
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice["player_id"] == player.id
    assert {o["instance_id"] for o in choice["options"]} == {c.instance_id for c in cards[-count:]}
    assert not choice["optional"]
    with pytest.raises(ValueError, match="mandatory"):
        engine.resolve_pending_choice("decline")
    chosen = cards[-2]
    engine.resolve_pending_choice(str(chosen.instance_id))
    engine.resolve_until_stable()
    assert chosen in player.exile and chosen.face_down_in_exile
    assert land.linked_exile_id == chosen.instance_id
    assert chosen.instance_id in land.linked_exile_ids
    assert land.hideaway_exile_ids == {chosen.instance_id}
    rest = set(cards[-count:]) - {chosen}
    assert set(player.library[:len(rest)]) == rest
    assert player.library[len(rest):] == cards[:-count]
    assert not engine.state.pending_choice


@pytest.mark.parametrize("available", [0, 1])
def test_hideaway_short_library_and_forced_single_pick(available):
    engine, player, land, cards = _game(4, available)
    engine.play_land(player, land)
    engine.resolve_until_stable()
    assert not engine.state.pending_choice
    assert len(player.exile) == available
    if cards:
        assert cards[0].face_down_in_exile and land.linked_exile_id == cards[0].instance_id


def _exiled_view(engine, viewer, iid):
    state = engine.state.to_dict()
    _redact_face_down_exile(state, viewer)
    return next(obj for p in state["players"] for obj in p["exile"] if obj["instance_id"] == iid)


def test_activation_captures_links_before_source_leaves_or_gets_new_links():
    engine, player, land, cards = _game()
    engine.play_land(player, land)
    engine.resolve_until_stable()
    chosen = cards[-1]
    engine.resolve_pending_choice(str(chosen.instance_id))
    land.tapped = False
    index = len(land.activated_abilities)
    land.activated_abilities.append(ActivatedAbility([], taps_source=True, source=land))
    engine.activate_ability(player, land, index)
    item = engine.state.stack[-1]
    assert item.trigger_event.get("hideaway_exile_ids") == [chosen.instance_id]
    engine.rules.return_to_hand(land)
    assert not land.hideaway_exile_ids
    land.hideaway_exile_ids.add(cards[-2].instance_id)
    assert item.trigger_event.get("hideaway_exile_ids") == [chosen.instance_id]


def test_hideaway_damage_condition_counts_one_opponent_and_current_turn():
    engine, player, _, _ = _game(available=8)
    state = engine.state
    p2, p3 = state.player_by_id("p2"), state.player_by_id("p3")
    condition = {"kind": "opponent_was_dealt_damage_this_turn", "min": 7}
    holds = lambda: condition_holds(condition, state, controller_id=player.id)
    engine.rules.deal_damage(player, 7)
    engine.rules.deal_damage(p2, 4, combat=True)
    engine.rules.deal_damage(p3, 3)
    assert not holds()  # Own damage and separate opponents cannot be combined.
    engine.rules.lose_life(p2, 7, cause="effect")
    assert not holds()
    engine.rules.deal_damage(p2, 3)
    assert holds()  # Combat and noncombat damage to the same opponent combine.
    engine.rules.gain_life(p2, 10)
    assert holds()
    engine.begin_turn()
    assert not holds()


def test_hideaway_damage_condition_includes_infect_without_life_loss():
    engine, player, _, _ = _game()
    opponent = engine.state.player_by_id("p2")
    source = GameObject(Card(id="infect", name="Infect creature", type_line="Creature",
                             is_creature=True, power=7, toughness=7, keywords=["Infect"]),
                        owner_id=player.id, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(source)
    engine.state.battlefield.append(source)
    old_life = opponent.life
    engine.rules.deal_damage(opponent, 7, source=source, combat=True)
    assert opponent.life == old_life
    assert condition_holds({"kind": "opponent_was_dealt_damage_this_turn", "min": 7},
                           engine.state, controller_id=player.id)


def test_hideaway_viewers_follow_control_and_keep_permission_after_source_leaves():
    engine, player, land, cards = _game()
    engine.play_land(player, land)
    engine.resolve_until_stable()
    chosen = cards[-1]
    engine.resolve_pending_choice(str(chosen.instance_id))
    engine.resolve_until_stable()
    assert _exiled_view(engine, "p1", chosen.instance_id)["name"] == chosen.name
    assert _exiled_view(engine, "p2", chosen.instance_id)["name"] != chosen.name
    land.controller_id = "p2"
    engine.recompute_continuous_effects()
    assert _exiled_view(engine, "p2", chosen.instance_id)["name"] == chosen.name
    land.controller_id = "p1"
    engine.recompute_continuous_effects()
    engine.rules.return_to_hand(land)
    for viewer in ("p1", "p2"):
        assert _exiled_view(engine, viewer, chosen.instance_id)["name"] == chosen.name
    for viewer in ("p3", None):
        assert _exiled_view(engine, viewer, chosen.instance_id)["name"] != chosen.name


def test_hideaway_source_removed_during_choice_does_not_link_a_new_incarnation():
    engine, player, land, cards = _game()
    engine.play_land(player, land)
    engine.resolve_until_stable()
    engine.rules.return_to_hand(land)
    chosen = cards[-1]
    engine.resolve_pending_choice(str(chosen.instance_id))
    engine.resolve_until_stable()
    assert chosen in player.exile and chosen.face_down_in_exile
    assert not land.hideaway_exile_ids
    land.controller_id = "p2"
    engine.state.add_to_battlefield(land)
    engine.recompute_continuous_effects()
    assert _exiled_view(engine, "p2", chosen.instance_id)["name"] != chosen.name


def test_two_copies_of_hideaway_link_both_cards_independently():
    engine, player, land, cards = _game()
    # A trigger doubler yields two firings of the same ability.
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine.play_land(player, land)
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,
                                     instance_id=land.instance_id, controller_id=player.id))
    engine.resolve_until_stable()
    first = cards[-1]
    engine.resolve_pending_choice(str(first.instance_id))
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    second_id = choice["options"][0]["instance_id"]
    engine.resolve_pending_choice(str(second_id))
    engine.resolve_until_stable()
    assert len(player.exile) == 2
    assert land.hideaway_exile_ids == {first.instance_id, second_id}
    assert set(land.linked_exile_ids) == land.hideaway_exile_ids
