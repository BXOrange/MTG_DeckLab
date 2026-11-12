"""Arcavios' searched locations, conditional shuffle, and hand-cast spell copies."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game


NAME = "Invasion of Arcavios"


def _board():
    engine = game()
    player = engine.state.player_by_id("p1")
    library = card(engine, "Lightning Bolt", zone=Zone.LIBRARY)
    graveyard = card(engine, "Divination", zone=Zone.GRAVEYARD)
    outside = card(engine, "Shock", zone=Zone.HAND)
    player.hand.remove(outside)
    outside.zone = None
    player.sideboard.append(outside)
    source = card(engine, NAME, zone=Zone.HAND)
    cast(engine, source)
    return engine, source, player, library, graveyard, outside


def _ids(engine):
    return {o["id"] for o in engine.state.pending_choice["options"]}


def _search_events(engine):
    return [e for e in engine.state.events_this_turn() if e.type == EventType.LIBRARY_SEARCHED]


def test_front_registers_fresh_specs_and_enters_with_seven_defense():
    engine, source, player, library, graveyard, outside = _board()
    first, second = specs_for(source.card), specs_for(source.card)
    assert first is not second and first[0] is not second[0]
    assert source.defense == 7 and source.protector_id == "p2"
    assert len(source.triggered_abilities) == 1
    assert _ids(engine) == {"search:library", "search:graveyard", "search:outside"}
    assert not _search_events(engine)


@pytest.mark.parametrize("place", ["library", "graveyard", "outside"])
def test_fetches_exactly_one_owned_instant_or_sorcery_and_shuffles_only_searched_library(place, monkeypatch):
    engine, source, player, library, graveyard, outside = _board()
    shuffles = []
    monkeypatch.setattr(engine.rules, "shuffle_library", lambda p: shuffles.append(p.id))
    hit = {"library": library, "graveyard": graveyard, "outside": outside}[place]
    engine.resolve_pending_choice(f"search:{place}")
    assert str(hit.instance_id) in _ids(engine)
    engine.resolve_pending_choice(str(hit.instance_id))
    assert hit in player.hand and hit.zone == Zone.HAND
    assert sum(obj in player.hand for obj in (library, graveyard, outside)) == 1
    assert shuffles == (["p1"] if place == "library" else [])
    assert len(_search_events(engine)) == int(place == "library")
    assert any(e.type == EventType.REVEAL and e.get("instance_id") == hit.instance_id
               for e in engine.state.events_this_turn())
    assert outside not in player.sideboard if place == "outside" else outside in player.sideboard


def test_can_search_library_then_graveyard_then_take_outside_card(monkeypatch):
    engine, source, player, library, graveyard, outside = _board()
    shuffles = []
    monkeypatch.setattr(engine.rules, "shuffle_library", lambda p: shuffles.append(p.id))
    for place in ("library", "graveyard", "outside"):
        engine.resolve_pending_choice(f"search:{place}")
    assert {str(o.instance_id) for o in (library, graveyard, outside)} <= _ids(engine)
    engine.resolve_pending_choice(str(outside.instance_id))
    assert outside in player.hand and library in player.library and graveyard in player.graveyard
    assert shuffles == ["p1"] and len(_search_events(engine)) == 1


def test_can_fail_hidden_quality_search_even_with_matching_card(monkeypatch):
    engine, source, player, library, graveyard, outside = _board()
    shuffles = []
    monkeypatch.setattr(engine.rules, "shuffle_library", lambda p: shuffles.append(p.id))
    engine.resolve_pending_choice("search:library")
    engine.resolve_pending_choice("done")
    assert library in player.library and shuffles == ["p1"] and not player.hand


def test_searched_graveyard_match_prevents_failing_to_find():
    engine, source, player, library, graveyard, outside = _board()
    engine.resolve_pending_choice("search:graveyard")
    assert "done" not in _ids(engine)
    with pytest.raises(ValueError):
        engine.resolve_pending_choice("done")
    assert str(graveyard.instance_id) in _ids(engine)
    engine.resolve_pending_choice(str(graveyard.instance_id))
    assert graveyard in player.hand


def test_search_outside_can_find_nothing_without_touching_library():
    engine, source, player, library, graveyard, outside = _board()
    player.sideboard.clear()
    engine.resolve_pending_choice("search:outside")
    engine.resolve_pending_choice("done")
    assert not player.hand and not _search_events(engine)


def test_wrong_card_types_other_owners_and_tokens_are_not_choices():
    engine, source, player, library, graveyard, outside = _board()
    creature = filler(engine, "Creature", zone=Zone.GRAVEYARD)
    foreign = card(engine, "Shock", "p2", Zone.GRAVEYARD)
    player.graveyard.append(foreign)
    token = filler(engine, "Spell token", type_line="Sorcery", zone=Zone.GRAVEYARD)
    token.is_token = True
    engine.resolve_pending_choice("search:graveyard")
    assert all(str(o.instance_id) not in _ids(engine) for o in (creature, foreign, token, library, outside))
    assert str(graveyard.instance_id) in _ids(engine)


def test_selected_locations_survive_clone():
    engine, source, player, library, graveyard, outside = _board()
    engine.resolve_pending_choice("search:library")
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice("search:outside")
    clone.resolve_pending_choice(str(outside.instance_id))
    assert clone.state.find_object(outside.instance_id) in clone.state.player_by_id("p1").hand
    assert outside in player.sideboard and engine.state.pending_choice


def _back_board():
    engine, source, player, library, graveyard, outside = _board()
    engine.resolve_pending_choice("search:outside")
    engine.resolve_pending_choice("done")
    engine.rules.deal_damage(source, source.defense)
    engine.resolve_until_stable()
    assert source.zone == Zone.EXILE
    engine.cast_spell(player, source)
    engine.resolve_until_stable()
    assert source.name == "Invocation of the Founders" and not source.is_creature
    return engine, source, player


def test_back_optionally_copies_hand_spell_without_casting_the_copy():
    engine, source, player = _back_board()
    spell = card(engine, "Divination", zone=Zone.HAND)
    before = len(player.hand)
    cast(engine, spell)
    assert engine.state.pending_choice["kind"] == "trigger_target"
    engine.resolve_pending_choice("do")
    assert len(player.hand) == before - 1 + 4
    casts = [e for e in engine.state.events_this_turn() if e.type == EventType.SPELL_CAST
             and e.get("instance_id") == spell.instance_id]
    assert len(casts) == 1 and not engine.state.pending_choice


def test_back_copy_is_optional():
    engine, source, player = _back_board()
    spell = card(engine, "Divination", zone=Zone.HAND)
    before = len(player.hand)
    cast(engine, spell)
    engine.resolve_pending_choice("decline")
    assert len(player.hand) == before + 1


@pytest.mark.parametrize("from_zone,spell_name,controller", [
    ("graveyard", "Divination", "p1"), ("exile", "Lightning Bolt", "p1"),
    ("hand", "Divination", "p2"), ("hand", "Grizzly Bears", "p1"),
])
def test_back_ignores_nonhand_nonspell_and_opponent_casts(from_zone, spell_name, controller):
    engine, source, player = _back_board()
    spell = card(engine, spell_name, controller, Zone.HAND)
    engine.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id=controller,
        controller_id=controller, instance_id=spell.instance_id, from_zone=from_zone,
        object_types=sorted(spell.type_words), object=spell.name))
    engine.rules.put_triggers_on_stack()
    assert not engine.state.pending_choice and not engine.state.stack


@pytest.mark.parametrize("retarget", [True, False])
def test_back_copy_can_change_or_keep_targets(retarget):
    engine, source, player = _back_board()
    opponent = engine.state.player_by_id("p2")
    spell = card(engine, "Lightning Bolt", zone=Zone.HAND)
    cast(engine, spell, targets=[opponent])
    engine.resolve_pending_choice("do")
    assert engine.state.pending_choice["kind"] == "copy_targets"
    target = next((o["id"] for o in engine.state.pending_choice["options"]
                   if o.get("player_id") == "p1"), None)
    engine.resolve_pending_choice(target if retarget else "decline")
    assert opponent.life == (17 if retarget else 14)
    assert player.life == (17 if retarget else 20)
    assert not engine.state.stack and not engine.state.pending_choice


def test_library_search_prohibition_does_not_prevent_graveyard_search(monkeypatch):
    engine, source, player, library, graveyard, outside = _board()
    # Rebuild the location offer under a library-search prohibition.
    monkeypatch.setattr(engine.rules, "is_search_prohibited_for", lambda p: True)
    engine.resolve_pending_choice("search:outside")
    assert "search:library" not in _ids(engine)
    engine.resolve_pending_choice("search:graveyard")
    engine.resolve_pending_choice(str(graveyard.instance_id))
    assert graveyard in player.hand and not _search_events(engine)


def test_library_search_can_fail_after_source_leaves():
    engine, source, player, library, graveyard, outside = _board()
    engine.resolve_pending_choice("search:library")
    engine.rules.exile(source)
    engine.resolve_pending_choice("done")
    assert source.zone == Zone.EXILE and library in player.library
    assert not engine.state.pending_choice


def test_unoffered_card_and_premature_finish_are_rejected():
    engine, source, player, library, graveyard, outside = _board()
    for answer in ("done", str(library.instance_id), "search:hand"):
        with pytest.raises(ValueError):
            engine.resolve_pending_choice(answer)
        assert _ids(engine) == {"search:library", "search:graveyard", "search:outside"}
    engine.resolve_pending_choice("search:library")
    with pytest.raises(ValueError):
        engine.resolve_pending_choice("search:library")
    assert len(_search_events(engine)) == 1


def test_back_specs_are_fresh_and_bound():
    engine, source, player = _back_board()
    first, second = specs_for(source.card), specs_for(source.card)
    assert first is not second and first[0] is not second[0]
    for spec in first:
        spec.validate()
    assert len(source.triggered_abilities) == 1
    assert not source.activated_abilities
