"""Commander Spock's revealed visit and Dathon's chosen existing counter kind."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import advance_to, cast, game, stock_library


def _card(name):
    if name == "Commander Spock":
        return Card(id="spock", name=name, type_line="Legendary Creature — Vulcan Human Scientist", is_creature=True,
            is_legendary=True, power=3, toughness=5, mana_cost_string="{2}{G}{W}{U}", converted_mana_cost=5,
            oracle_text="Strange new worlds — Whenever Commander Spock enters or attacks, reveal the top card of your library. You may cast that card without paying its mana cost if that spell's mana value is equal to or less than the number of differently named lands you control. If it's a land card, you may put it onto the battlefield tapped. If that card is still on top of your library, draw a card.")
    assert name == "Dathon, His Heart Open"
    return Card(id="dathon", name=name, type_line="Legendary Creature — Tamarian Officer", is_creature=True,
        is_legendary=True, power=3, toughness=3, mana_cost_string="{G}{U}{R}", converted_mana_cost=3,
        oracle_text="Whenever you cast an enchantment spell, draw a card. If it's a Saga spell, Dathon deals 2 damage to each opponent.\n"
        "{2}: Choose a counter on target enchantment you control. Put another counter of that kind on it. Activate only as a sorcery.")


def _put(engine, card, zone=Zone.BATTLEFIELD, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=zone)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(owner).add_to_zone(obj, zone)
    return obj


def _land(engine, name):
    return _put(engine, Card(id=name, name=name, type_line="Land", is_land=True))


def _spell(name="Find", mv=2):
    return Card(id=name, name=name, type_line="Instant", is_instant=True,
                mana_cost_string=f"{{{mv}}}", converted_mana_cost=mv, oracle_text="You gain 1 life.")


def _spock(top, lands=("Forest", "Forest", "Island")):
    engine, p1, p2 = game()
    for name in lands:
        _land(engine, name)
    stock_library(engine, "p1", 2)
    revealed = _put(engine, top, Zone.LIBRARY)
    source = _put(engine, _card("Commander Spock"), Zone.HAND)
    cast(engine, p1, source)
    return engine, p1, p2, source, revealed


@pytest.mark.parametrize("name", ["Commander Spock", "Dathon, His Heart Open"])
def test_specs_are_fresh_valid_and_bind(name):
    first, second = specs_for(_card(name)), specs_for(_card(name))
    assert first and first[0] is not second[0] and first[0].effects[0] is not second[0].effects[0]
    for spec in first:
        spec.validate()
    engine, _, _ = game()
    source = _put(engine, _card(name))
    assert source.triggered_abilities
    if name.startswith("Dathon"):
        assert source.activated_abilities


@pytest.mark.parametrize("clone", [False, True])
def test_spock_casts_at_equal_mana_value_without_payment_or_extra_draw(clone):
    engine, p1, p2, source, revealed = _spock(_spell())
    assert engine.state.pending_choice["kind"] == "play_during_resolution"
    if clone:
        engine = GameEngine(engine.state.clone())
        p1 = engine.state.player_by_id("p1")
        revealed = engine.state.find_object(revealed.instance_id)
    before = p1.mana_pool.total()
    engine.play_resolution_card(p1, revealed)
    engine.resolve_until_stable()
    assert revealed in p1.graveyard and p1.life == 21 and not p1.hand
    assert p1.mana_pool.total() == before and len(p1.library) == 2


def test_spock_declined_cast_draws_the_revealed_card():
    engine, p1, p2, source, revealed = _spock(_spell())
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert revealed in p1.hand and len(p1.hand) == 1
    assert p1.life == 20


@pytest.mark.parametrize("lands,mv", [(("Forest", "Forest"), 2), ((), 1)])
def test_spock_counts_differently_named_lands_and_draws_an_ineligible_spell(lands, mv):
    engine, p1, p2, source, revealed = _spock(_spell(mv=mv), lands)
    if engine.state.pending_choice:
        assert not any(a["type"] == "cast_spell" for a in engine.resolution_play_actions(p1))
        engine.resolve_pending_choice("decline")
        engine.resolve_until_stable()
    assert revealed in p1.hand


def test_spock_zero_mana_spell_is_castable_without_lands():
    engine, p1, p2, source, revealed = _spock(_spell(mv=0), ())
    engine.play_resolution_card(p1, revealed)
    engine.resolve_until_stable()
    assert revealed in p1.graveyard and not p1.hand and p1.life == 21


@pytest.mark.parametrize("accept", [False, True])
@pytest.mark.parametrize("clone", [False, True])
def test_spock_land_can_enter_tapped_without_a_land_drop_or_be_drawn_instead(accept, clone):
    engine, p1, p2, source, revealed = _spock(Card(id="topland", name="Top land", type_line="Land", is_land=True))
    choice = engine.state.pending_choice
    assert choice["kind"] == "composite_optional", choice
    if clone:
        engine = GameEngine(engine.state.clone())
        p1 = engine.state.player_by_id("p1")
        revealed = engine.state.find_object(revealed.instance_id)
    engine.resolve_pending_choice("yes" if accept else "no")
    engine.resolve_until_stable()
    assert revealed.zone == (Zone.BATTLEFIELD if accept else Zone.HAND)
    if accept:
        assert revealed.tapped and p1.lands_played_this_turn == 0 and not p1.hand


@pytest.mark.parametrize("land_front", [False, True])
def test_spock_caps_the_actual_mdfc_spell_face_and_not_the_front_face(land_front):
    card = Card(id="mdfc", name="Front // Back", layout="modal_dfc",
        type_line="Land" if land_front else "Creature — Giant", is_land=land_front, is_creature=not land_front,
        power=None if land_front else 4, toughness=None if land_front else 4,
        mana_cost_string="" if land_front else "{8}", converted_mana_cost=0 if land_front else 8,
        back_name="Back", back_type_line="Instant", back_mana_cost_string="{1}{G}", back_oracle_text="You gain 1 life.")
    engine, p1, p2, source, revealed = _spock(card)
    actions = engine.resolution_play_actions(p1)
    assert any(a["type"] == "cast_spell" and a.get("face") == "back" for a in actions), actions
    assert not any(a["type"] == "cast_spell" and a.get("face", "front") == "front" for a in actions)
    engine.play_resolution_card(p1, revealed, face="back")
    engine.resolve_until_stable()
    assert revealed in p1.graveyard and p1.life == 21 and not p1.hand


def test_spock_empty_library_neither_opens_a_choice_nor_causes_a_failed_draw():
    engine, p1, p2 = game()
    source = _put(engine, _card("Commander Spock"), Zone.HAND)
    cast(engine, p1, source)
    assert engine.state.pending_choice is None and not p1.has_lost
    assert not p1.attempted_draw_from_empty


def test_spock_attack_trigger_uses_the_same_reveal_and_optional_land_sequence():
    engine, p1, p2 = game(via_steps=True)
    source = _put(engine, _card("Commander Spock"))
    revealed = _put(engine, Card(id="land", name="Attack land", type_line="Land", is_land=True), Zone.LIBRARY)
    advance_to(engine, "declare_attackers")
    engine.declare_attackers(p1, [{"attacker": source, "defender": engine.legal_defenders_for(p1)[0]}])
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "composite_optional"
    engine.resolve_pending_choice("yes")
    engine.resolve_until_stable()
    assert revealed.zone == Zone.BATTLEFIELD and revealed.tapped


def test_spock_does_not_draw_a_new_visit_of_the_same_revealed_card():
    engine, p1, p2, source, revealed = _spock(_spell())
    engine.rules.exile(revealed)
    p1.remove_from_zone(revealed, Zone.EXILE)
    p1.add_to_zone(revealed, Zone.LIBRARY)
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert revealed in p1.library and not p1.hand


@pytest.mark.parametrize("type_line,owner,draws,damage", [
    ("Enchantment", "p1", 1, 0), ("Enchantment — Saga", "p1", 1, 2),
    ("Enchantment — Saga", "p2", 0, 0), ("Instant", "p1", 0, 0),
])
def test_dathon_draws_on_own_enchantment_cast_and_damages_only_for_a_saga(type_line, owner, draws, damage):
    engine, p1, p2 = game()
    source = _put(engine, _card("Dathon, His Heart Open"))
    stock_library(engine, "p1", 3)
    engine.state.active_player_index = 0 if owner == "p1" else 1
    card = Card(id="spell", name="Spell", type_line=type_line, is_instant=type_line == "Instant")
    spell = _put(engine, card, Zone.HAND, owner)
    engine.cast_spell(engine.state.player_by_id(owner), spell)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert len(p1.hand) == draws and p2.life == 20 - damage


def test_dathon_reads_the_cast_snapshot_even_if_the_saga_spell_was_countered():
    engine, p1, p2 = game()
    _put(engine, _card("Dathon, His Heart Open"))
    stock_library(engine, "p1", 2)
    spell = _put(engine, Card(id="saga", name="Saga", type_line="Enchantment — Saga"), Zone.HAND)
    engine.cast_spell(p1, spell)
    engine.rules.put_triggers_on_stack()
    engine.rules.counter_spell(spell)
    engine.resolve_until_stable()
    assert spell in p1.graveyard and p2.life == 18 and len(p1.hand) == 1


@pytest.mark.parametrize("clone", [False, True])
def test_dathon_chooses_one_existing_counter_kind_and_adds_only_one(clone):
    engine, p1, p2 = game()
    source = _put(engine, _card("Dathon, His Heart Open"))
    enchantment = _put(engine, Card(id="enchantment", name="Counter holder", type_line="Enchantment"))
    enchantment.counters.update({"lore": 2, "charge": 4})
    p1.mana_pool.add("C", 2)
    engine.activate_ability(p1, source, targets=[enchantment])
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice["kind"] == "counter_kind" and len(choice["options"]) == 2
    picked = next(o["id"] for o in choice["options"] if o["label"] == "charge")
    if clone:
        engine = GameEngine(engine.state.clone())
        enchantment = engine.state.find_object(enchantment.instance_id)
    engine.resolve_pending_choice(picked)
    engine.resolve_until_stable()
    assert enchantment.counters["charge"] == 5 and enchantment.counters["lore"] == 2


def test_dathon_counterless_enchantment_remains_legal_and_class_level_is_not_a_counter():
    engine, p1, p2 = game()
    source = _put(engine, _card("Dathon, His Heart Open"))
    enchantment = _put(engine, Card(id="class", name="Class", type_line="Enchantment — Class"))
    p1.mana_pool.add("C", 2)
    engine.activate_ability(p1, source, targets=[enchantment])
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and enchantment.counters == {"class_level": 1}


def test_dathon_lore_duplication_triggers_chapters_and_final_saga_sacrifice():
    engine, p1, p2 = game()
    source = _put(engine, _card("Dathon, His Heart Open"))
    saga = _put(engine, Card(id="story", name="Story", type_line="Enchantment — Saga",
        oracle_text="(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)\n"
        "I — You gain 1 life.\nII — You gain 2 life.\nIII — You gain 3 life."))
    engine.resolve_until_stable()
    assert p1.life == 21 and saga.counters["lore"] == 1
    for life in (23, 26):
        p1.mana_pool.add("C", 2)
        engine.activate_ability(p1, source, targets=[saga])
        engine.resolve_until_stable()
        engine.resolve_pending_choice("0")
        engine.resolve_until_stable()
        assert p1.life == life
    assert saga in p1.graveyard and p2.life == 20


def test_dathon_counter_choice_never_applies_to_a_reentered_target_visit():
    engine, p1, p2 = game()
    source = _put(engine, _card("Dathon, His Heart Open"))
    enchantment = _put(engine, Card(id="e", name="Enchantment", type_line="Enchantment"))
    enchantment.counters["charge"] = 1
    p1.mana_pool.add("C", 2)
    engine.activate_ability(p1, source, targets=[enchantment])
    engine.resolve_until_stable()
    engine.rules.return_to_hand(enchantment)
    p1.remove_from_zone(enchantment, Zone.HAND)
    engine.state.add_to_battlefield(enchantment)
    engine.resolve_pending_choice("0")
    engine.resolve_until_stable()
    assert not enchantment.counters


def test_dathon_activation_requires_own_enchantment_and_sorcery_timing():
    engine, p1, p2 = game()
    source = _put(engine, _card("Dathon, His Heart Open"))
    theirs = _put(engine, Card(id="their", name="Theirs", type_line="Enchantment"), owner="p2")
    mine = _put(engine, Card(id="mine", name="Mine", type_line="Enchantment"))
    p1.mana_pool.add("C", 2)
    with pytest.raises(ValueError):
        engine.activate_ability(p1, source, targets=[theirs])
    assert p1.mana_pool.total() == 2
    engine.state.current_step = "upkeep"
    with pytest.raises(ValueError):
        engine.activate_ability(p1, source, targets=[mine])
