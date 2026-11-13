"""Real casts and Splice announcements for Fell Beast's Shriek."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game


def _board(players=3, caster="p1"):
    engine = game(players=players)
    engine.state.active_player_index = int(caster[1:]) - 1
    spell = card(engine, "Fell Beast's Shriek", player=caster, zone=Zone.HAND)
    return engine, spell


def _creature(engine, name, player):
    return filler(engine, name, player=player, power=2, toughness=3)


def _answer(engine, obj):
    engine.resolve_pending_choice(str(obj.instance_id))
    engine.resolve_until_stable()


def test_every_opponent_chooses_before_tap_and_goad():
    engine, spell = _board()
    own = _creature(engine, "Own", "p1")
    a = _creature(engine, "First", "p2")
    unused = _creature(engine, "Other", "p2")
    b = _creature(engine, "Second", "p3")
    cast(engine, spell)
    assert engine.state.pending_choice["player_id"] == "p2"
    _answer(engine, a)
    assert engine.state.pending_choice["player_id"] == "p3"
    assert not a.tapped and not a.goaded_by
    _answer(engine, b)
    assert a.tapped and b.tapped
    assert a.goaded_by == b.goaded_by == {"p1"}
    assert not own.tapped and not unused.tapped and not unused.goaded_by
    assert spell.zone == Zone.GRAVEYARD


def test_empty_boards_are_skipped_and_tapped_shrouded_creatures_can_be_chosen():
    engine, spell = _board(players=4)
    a = _creature(engine, "Protected", "p3")
    a.temp_keywords.update({"hexproof", "shroud"})
    engine.rules.set_tapped(a, True)
    engine.recompute_continuous_effects()
    cast(engine, spell)
    pending = engine.state.pending_choice
    assert pending["player_id"] == "p3" and not pending["optional"]
    assert [o["instance_id"] for o in pending["options"]] == [a.instance_id]
    _answer(engine, a)
    assert a.tapped and a.goaded_by == {"p1"}
    assert engine.state.pending_choice is None


def test_choices_follow_apnap_for_a_different_caster():
    engine, spell = _board(players=4, caster="p3")
    creatures = {pid: _creature(engine, pid, pid) for pid in ("p1", "p2", "p4")}
    cast(engine, spell)
    for pid in ("p4", "p1", "p2"):
        assert engine.state.pending_choice["player_id"] == pid
        _answer(engine, creatures[pid])
    assert all(obj.goaded_by == {"p3"} for obj in creatures.values())


def test_invalid_choice_leaves_all_actions_pending():
    engine, spell = _board()
    own = _creature(engine, "Own", "p1")
    a = _creature(engine, "First", "p2")
    cast(engine, spell)
    with pytest.raises(ValueError):
        engine.resolve_pending_choice(str(own.instance_id))
    assert engine.state.pending_choice["player_id"] == "p2"
    assert not a.tapped and not a.goaded_by
    _answer(engine, a)
    assert a.tapped and a.goaded_by == {"p1"}


def test_mid_choice_clone_retains_selected_visits_without_mutating_original():
    engine, spell = _board()
    a = _creature(engine, "First", "p2")
    b = _creature(engine, "Second", "p3")
    cast(engine, spell)
    _answer(engine, a)
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice(str(b.instance_id))
    clone.resolve_until_stable()
    assert clone.state.find_object(a.instance_id).goaded_by == {"p1"}
    assert clone.state.find_object(b.instance_id).tapped
    assert not a.tapped and engine.state.pending_choice is not None


def test_empty_opponents_require_no_choices():
    engine, spell = _board()
    own = _creature(engine, "Own", "p1")
    cast(engine, spell)
    assert engine.state.pending_choice is None and not own.tapped


def _splice_board():
    from tests.support.deck_batch import main_phase
    engine, shriek = _board(players=2)
    player = engine.state.player_by_id("p1")
    host = card(engine, "Opt", zone=Zone.HAND)
    creature = _creature(engine, "Victim", "p2")
    main_phase(engine)
    return engine, player, shriek, host, creature


def test_splice_adds_cost_and_runs_after_host_text_without_casting_shriek():
    from mtg_analyzer.models.game.events import EventType
    engine, player, shriek, host, creature = _splice_board()
    player.mana_pool.add_many({"U": 2, "R": 1, "C": 2})
    assert engine.can_cast(player, host, splice_ids=[shriek.instance_id])
    engine.cast_spell(player, host, splice_ids=[shriek.instance_id])
    assert shriek in player.hand and host.zone == Zone.STACK
    assert player.mana_pool.total() == 0 and host.mana_spent_to_cast == 5
    events = engine.state.events_this_turn()
    assert any(e.type == EventType.REVEAL and e.get("instance_id") == shriek.instance_id for e in events)
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] != "fell_beast_creature"  # Opt scries first.
    from tests.support.deck_batch import answer
    answer(engine, lambda choice: str(creature.instance_id) if choice["kind"] == "fell_beast_creature" else None)
    engine.resolve_until_stable()
    assert creature.tapped and creature.goaded_by == {"p1"}
    assert shriek in player.hand and host.zone == Zone.GRAVEYARD
    assert sum(e.type == EventType.SPELL_CAST for e in engine.state.events_this_turn()) == 1
    assert not hasattr(host, "_splice_effects")


def test_splice_is_not_free_when_only_host_mana_is_available():
    engine, player, shriek, host, creature = _splice_board()
    player.mana_pool.add("U", 1)
    assert engine.can_cast(player, host)
    assert not engine.can_cast(player, host, splice_ids=[shriek.instance_id])
    with pytest.raises(ValueError):
        engine.cast_spell(player, host, splice_ids=[shriek.instance_id])
    assert host in player.hand and shriek in player.hand and not engine.state.stack
    assert not hasattr(host, "_splice_cost")


@pytest.mark.parametrize("invalid", ["duplicate", "self", "creature", "other_hand"])
def test_splice_rejects_illegal_announcements(invalid):
    engine, player, shriek, host, creature = _splice_board()
    player.mana_pool.add_many({"U": 10, "R": 10, "C": 10})
    ids = [shriek.instance_id]
    if invalid == "duplicate":
        ids *= 2
    elif invalid == "self":
        host = shriek
    elif invalid == "creature":
        host = card(engine, "Llanowar Elves", zone=Zone.HAND)
    else:
        player.hand.remove(shriek)
        engine.state.player_by_id("p2").add_to_zone(shriek, Zone.HAND)
    assert not engine.can_cast(player, host, splice_ids=ids)
    with pytest.raises(ValueError):
        engine.cast_spell(player, host, splice_ids=ids)


@pytest.mark.parametrize("explicit", [False, True])
def test_waiving_host_mana_still_pays_splice(explicit):
    from tests.support.deck_batch import answer
    engine, player, shriek, host, creature = _splice_board()
    engine.state.free_cast_instance_ids.add(host.instance_id)
    assert not engine.can_cast(player, host, free=explicit, splice_ids=[shriek.instance_id])
    player.mana_pool.add_many({"U": 1, "R": 1, "C": 2})
    assert engine.can_cast(player, host, free=explicit, splice_ids=[shriek.instance_id])
    engine.cast_spell(player, host, free=explicit, splice_ids=[shriek.instance_id])
    assert host.mana_spent_to_cast == 4 and player.mana_pool.total() == 0
    engine.resolve_until_stable()
    answer(engine, lambda choice: str(creature.instance_id) if choice["kind"] == "fell_beast_creature" else None)
    engine.resolve_until_stable()
    assert creature.goaded_by == {"p1"} and shriek in player.hand


def test_splice_with_nonmana_alternative_keeps_both_costs():
    from mtg_analyzer.game.costs import parse_activation_cost
    engine, player, shriek, host, creature = _splice_board()
    host.alt_cast_cost = parse_activation_cost("Pay 2 life")
    assert not engine.can_cast(player, host, alt_cost=True, splice_ids=[shriek.instance_id])
    player.mana_pool.add_many({"U": 1, "R": 1, "C": 2})
    assert engine.can_cast(player, host, alt_cost=True, splice_ids=[shriek.instance_id])
    engine.cast_spell(player, host, alt_cost=True, splice_ids=[shriek.instance_id])
    assert player.life == 18 and player.mana_pool.total() == 0 and host.mana_spent_to_cast == 4


def test_legal_actions_offer_plain_and_spliced_cast_with_combined_cost():
    engine, player, shriek, host, creature = _splice_board()
    player.mana_pool.add("U", 1)
    offers = [a for a in engine.legal_actions(player) if a.get("instance_id") == host.instance_id]
    assert offers and not any(a.get("splice_ids") for a in offers)
    player.mana_pool.add_many({"U": 1, "R": 1, "C": 2})
    offers = [a for a in engine.legal_actions(player) if a.get("instance_id") == host.instance_id]
    spliced, = [a for a in offers if a.get("splice_ids")]
    assert spliced["splice_ids"] == [shriek.instance_id]
    assert spliced["splice_names"] == ["Fell Beast's Shriek"]
    from mtg_analyzer.models.mana.mana_cost import ManaCost
    assert ManaCost.parse(spliced["cost_label"]).resolved_value == 5
    assert not hasattr(host, "_splice_cost")


def test_copied_spliced_spell_uses_the_copy_controllers_opponents():
    from tests.support.deck_batch import answer
    engine, player, shriek, host, creature = _splice_board()
    own = _creature(engine, "Copy victim", "p1")
    player.mana_pool.add_many({"U": 2, "R": 1, "C": 2})
    engine.cast_spell(player, host, splice_ids=[shriek.instance_id])
    original = engine.state.stack[-1]
    copied, = engine.rules.copy_spell(original, "p2")
    assert len(copied.effects) == len(original.effects)
    assert copied.effects[-1] is not original.effects[-1]
    engine.rules.resolve_top_of_stack()
    while engine.state.pending_choice["kind"] != "fell_beast_creature":
        engine.resolve_pending_choice(str(engine.state.pending_choice["options"][0]["id"]))
    assert engine.state.pending_choice["player_id"] == "p1"
    engine.resolve_pending_choice(str(own.instance_id))
    assert own.goaded_by == {"p2"} and not creature.goaded_by
    assert shriek in player.hand


def test_recasting_host_does_not_keep_the_spliced_text():
    from tests.support.deck_batch import answer
    engine, player, shriek, host, creature = _splice_board()
    player.mana_pool.add_many({"U": 4, "R": 1, "C": 2})
    engine.cast_spell(player, host, splice_ids=[shriek.instance_id])
    engine.resolve_until_stable()
    answer(engine, lambda choice: str(creature.instance_id) if choice["kind"] == "fell_beast_creature" else None)
    engine.resolve_until_stable()
    engine.rules.return_from_graveyard(host, "hand")
    engine.rules.set_tapped(creature, False)
    engine.cast_spell(player, host)
    assert len(engine.state.stack[-1].effects) == 2  # Opt: scry, then draw.
    assert shriek in player.hand


def test_clone_preserves_spliced_stack_text_after_announcement_cleanup():
    from tests.support.deck_batch import answer
    engine, player, shriek, host, creature = _splice_board()
    player.mana_pool.add_many({"U": 2, "R": 1, "C": 2})
    engine.cast_spell(player, host, splice_ids=[shriek.instance_id])
    clone = GameEngine(engine.state.clone())
    clone.resolve_until_stable()
    answer(clone, lambda choice: str(creature.instance_id) if choice["kind"] == "fell_beast_creature" else None)
    clone.resolve_until_stable()
    assert clone.state.find_object(creature.instance_id).goaded_by == {"p1"}
    assert not creature.tapped


def test_multiple_physical_copies_are_revealed_once_each_and_add_independent_text():
    from mtg_analyzer.models.game.events import EventType
    engine, player, shriek, host, creature = _splice_board()
    second = card(engine, "Fell Beast's Shriek", zone=Zone.HAND)
    player.mana_pool.add_many({"U": 3, "R": 2, "C": 4})
    engine.cast_spell(player, host, splice_ids=[shriek.instance_id, second.instance_id])
    item = engine.state.stack[-1]
    assert len(item.effects) == 4 and item.effects[-1] is not item.effects[-2]
    assert player.mana_pool.total() == 0 and host.mana_spent_to_cast == 9
    assert host.name == "Opt" and host.mana_value == 1
    revealed = [e.get("instance_id") for e in engine.state.events_this_turn() if e.type == EventType.REVEAL]
    assert revealed.count(shriek.instance_id) == revealed.count(second.instance_id) == 1
    assert shriek in player.hand and second in player.hand


def test_countering_host_keeps_splice_paid_and_does_not_resolve_the_added_text():
    engine, player, shriek, host, creature = _splice_board()
    player.mana_pool.add_many({"U": 2, "R": 1, "C": 2})
    engine.cast_spell(player, host, splice_ids=[shriek.instance_id])
    engine.rules.counter_spell(host)
    engine.resolve_until_stable()
    assert host.zone == Zone.GRAVEYARD and shriek in player.hand
    assert player.mana_pool.total() == 0 and not creature.goaded_by
    assert engine.state.pending_choice is None


def test_host_with_all_targets_illegal_also_loses_spliced_effect():
    engine, player, shriek, _, creature = _splice_board()
    host = card(engine, "Ghostfire", zone=Zone.HAND)
    survivor = _creature(engine, "Survivor", "p2")
    player.mana_pool.add_many({"U": 1, "R": 2, "C": 4})
    engine.cast_spell(player, host, targets=[creature], splice_ids=[shriek.instance_id])
    engine.rules.put_into_graveyard(creature)
    engine.resolve_until_stable()
    assert host.zone == Zone.GRAVEYARD and not survivor.goaded_by
    assert engine.state.pending_choice is None and shriek in player.hand


def test_catalogue_specs_are_fresh_and_bind_the_complete_card():
    from mtg_analyzer.game.card_registry import specs_for
    engine, shriek = _board()
    a, b = specs_for(shriek.card), specs_for(shriek.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(shriek.spell_effects) == 1
    assert shriek.parametric_keywords["splice"] == {"quality": "instant_or_sorcery", "cost": "{2}{U}{R}"}


def test_paying_life_for_library_host_does_not_waive_splice_mana():
    engine, player, shriek, host, creature = _splice_board()
    card(engine, "Bolas's Citadel")
    player.hand.remove(host)
    player.add_to_zone(host, Zone.LIBRARY)
    assert not engine.can_cast(player, host, splice_ids=[shriek.instance_id])
    player.mana_pool.add_many({"U": 1, "R": 1, "C": 2})
    assert engine.can_cast(player, host, splice_ids=[shriek.instance_id])
    engine.cast_spell(player, host, splice_ids=[shriek.instance_id])
    assert player.life == 19 and host.mana_spent_to_cast == 4
    assert player.mana_pool.total() == 0 and shriek in player.hand
