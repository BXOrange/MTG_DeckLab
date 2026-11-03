"""Gameplay regressions for singleton payments and source-bound transformations."""
import pytest
import json
import sqlite3

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import DEFAULT_DB_PATH
from tests.support.catalogue import two_player_game, battlefield_object


def card(engine, name, zone=Zone.BATTLEFIELD, owner="p1"):
    with sqlite3.connect(f"file:{DEFAULT_DB_PATH.as_posix()}?mode=ro", uri=True) as db:
        row = db.execute("SELECT data FROM cards WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    obj = GameObject(Card.from_dict(json.loads(row[0])), owner_id=owner, zone=zone)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(owner).add_to_zone(obj, zone)
    return obj


def library(engine, player="p1"):
    p = engine.state.player_by_id(player)
    for i in range(5):
        p.add_to_zone(GameObject(Card(id=str(i), name=f"Draw {i}", type_line="Land", is_land=True), owner_id=player, zone=Zone.LIBRARY), Zone.LIBRARY)


@pytest.mark.parametrize("name", ["Dusk Mangler", "Highway Robbery", "Havengul Lich", "Jinnie Fay, Jetmir's Second", "Kitesail Larcenist"])
def test_registry_fresh_and_bound(name):
    engine, _ = two_player_game()
    obj = card(engine, name)
    a, b = specs_for(obj.card), specs_for(obj.card)
    assert a and a[0] is not b[0]
    assert getattr(obj, "spell_effects", []) or obj.activated_abilities or obj.triggered_abilities or obj.replacement_effects


@pytest.mark.parametrize("branch", ["0", "1", "decline"])
def test_highway_payment_and_decline(branch):
    engine, p1 = two_player_game()
    library(engine)
    spell = card(engine, "Highway Robbery", Zone.HAND)
    fodder = card(engine, "Forest", Zone.HAND)
    land = card(engine, "Forest")
    engine.state.current_phase, engine.state.current_step = "main1", "main1"
    p1.mana_pool.add("R", 2)
    assert engine.cast_spell(p1, spell)
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "alternative_payment"
    engine.resolve_pending_choice(branch)
    engine.resolve_until_stable()
    assert len(p1.hand) == (1 if branch == "decline" else 2 if branch == "0" else 3)
    assert (land.zone == Zone.GRAVEYARD) == (branch == "1")
    assert (fodder.zone == Zone.GRAVEYARD) == (branch == "0")


def test_highway_only_payable_options_and_nested_land_choice():
    engine, p1 = two_player_game()
    library(engine)
    spell = card(engine, "Highway Robbery", Zone.GRAVEYARD)
    lands = [card(engine, "Forest"), card(engine, "Forest")]
    spell.spell_effects[0].apply(engine.rules.context)
    choice = engine.state.pending_choice
    assert [o["id"] for o in choice["options"]] == ["1", "decline"]
    engine.resolve_pending_choice("1")
    assert len(p1.hand) == 0  # the payoff waits for the actual sacrifice
    choice = engine.state.pending_choice
    assert choice
    engine.resolve_pending_choice(str(lands[1].instance_id))
    engine.resolve_until_stable()
    assert lands[1].zone == Zone.GRAVEYARD and len(p1.hand) == 2


@pytest.mark.parametrize("option,name,power,toughness,keyword", [
    (0, "Cat", 2, 2, "haste"), (1, "Dog", 3, 1, "vigilance"),
    (2, "Treasure", None, None, None),
])
def test_jinnie_optional_token_substitution(option, name, power, toughness, keyword):
    engine, _ = two_player_game()
    card(engine, "Jinnie Fay, Jetmir's Second")
    token = Card(id="treasure", name="Treasure", type_line="Artifact — Treasure")
    engine.rules.create_token("p1", token, 2)
    assert engine.state.pending_choice["kind"] == "replacement_order"
    engine.resolve_pending_choice(str(option))
    engine.recompute_continuous_effects()
    tokens = [o for o in engine.state.permanents() if o.is_token]
    assert len(tokens) == 2 and {o.name for o in tokens} == {name}
    if keyword:
        from mtg_analyzer.game.combat import has
        assert all(o.power == power and o.toughness == toughness and has(o, keyword) for o in tokens)
        assert all(o.colors == {"G"} and not o.is_artifact for o in tokens)


def test_jinnie_doubler_and_opponent():
    engine, _ = two_player_game()
    card(engine, "Jinnie Fay, Jetmir's Second")
    card(engine, "Parallel Lives")
    token = Card(id="treasure", name="Treasure", type_line="Artifact — Treasure")
    engine.rules.create_token("p1", token, 2)
    # First choose the doubling replacement, then choose the Dog alternative.
    choice = engine.state.pending_choice
    pick = next(o["id"] for o in choice["options"] if "Jinnie Fay" not in o["label"])
    engine.resolve_pending_choice(pick)
    choice = engine.state.pending_choice
    engine.resolve_pending_choice(next(o["id"] for o in choice["options"] if o["label"] == "Jinnie Fay: Dog"))
    assert len([o for o in engine.state.permanents() if o.is_token and o.name == "Dog"]) == 4
    engine.rules.create_token("p2", token, 1)
    assert engine.state.pending_choice is None
    assert len([o for o in engine.state.permanents() if o.is_token and o.controller_id == "p2"]) == 1


def test_kitesail_transform_and_source_departure():
    engine, _ = two_player_game()
    source = card(engine, "Kitesail Larcenist")
    target = battlefield_object(engine, "p2", "Victim", "Enchantment Creature — Elf", power=3, toughness=4,
                                is_creature=True, oracle_text="Flying")
    bind_from_catalogue(target)
    effect = source.triggered_abilities[0].effects[0]
    assert effect.target_spec.per_player == "players" and effect.target_spec.optional
    effect.apply(engine.rules.context, [target])
    engine.recompute_continuous_effects()
    assert target.is_artifact and not target.is_creature and target.loses_all_abilities
    from mtg_analyzer.game import continuous
    assert continuous.has_subtype(target, "Treasure") and not continuous.has_subtype(target, "Elf")
    from mtg_analyzer.game.mana_abilities import mana_abilities_for
    mana = mana_abilities_for(target)
    assert len(mana) == 1 and mana[0].cost.sacrifice == "self"
    engine.rules.put_into_graveyard(source)
    engine.recompute_continuous_effects()
    assert target.is_creature and not target.is_artifact and not target.loses_all_abilities
    assert continuous.has_subtype(target, "Elf")


def test_kitesail_source_already_gone_does_not_transform():
    engine, _ = two_player_game()
    source = card(engine, "Kitesail Larcenist")
    target = card(engine, "Llanowar Elves", owner="p2")
    effect = source.triggered_abilities[0].effects[0]
    engine.rules.put_into_graveyard(source)
    effect.apply(engine.rules.context, [target])
    engine.recompute_continuous_effects()
    assert target.is_creature and not target.is_artifact


def test_kitesail_announces_only_other_targets_once_per_player():
    from mtg_analyzer.game.targeting import legal_targets
    engine, _ = two_player_game()
    source = card(engine, "Kitesail Larcenist")
    own = card(engine, "Llanowar Elves")
    other = card(engine, "Llanowar Elves", owner="p2")
    spec = source.triggered_abilities[0].effects[0].target_spec
    candidates = {o["instance_id"] for o in legal_targets(engine.state, "p1", spec, source=source)}
    assert source.instance_id not in candidates and own.instance_id in candidates and other.instance_id in candidates


def test_havengul_cast_permission_and_delayed_borrow():
    engine, p1 = two_player_game()
    lich = card(engine, "Havengul Lich")
    creature = card(engine, "Prodigal Pyromancer", Zone.GRAVEYARD, owner="p2")
    engine.state.current_phase, engine.state.current_step = "main1", "main1"
    p1.mana_pool.add("R", 4)
    engine.activate_ability(p1, lich, 0, targets=[creature])
    engine.resolve_until_stable()
    assert not lich.temp_granted_activated_abilities
    assert engine.state.temp_graveyard_cast_permissions[creature.instance_id] == "p1"
    assert engine.cast_spell(p1, creature)
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack) == 2
    engine.rules.resolve_top_of_stack()
    assert len(lich.temp_granted_activated_abilities) == 1
    assert lich.temp_granted_activated_abilities[0].effects[0].source is lich


def test_havengul_later_graveyard_visit_does_not_trigger():
    engine, _ = two_player_game()
    lich = card(engine, "Havengul Lich")
    creature = card(engine, "Prodigal Pyromancer", Zone.GRAVEYARD)
    lich.activated_abilities[0].effects[0].apply(engine.rules.context, [creature])
    entry = engine.state.turn_scoped_triggers[-1]
    from mtg_analyzer.models.game.events import GameEvent, EventType
    event = GameEvent(EventType.SPELL_CAST, instance_id=creature.instance_id, player_id="p1",
                      from_zone="graveyard", from_zone_incarnation=creature.zone_incarnation + 2)
    assert not entry.ability.check_trigger(event, engine.rules.context)


def test_havengul_borrows_mana_ability_and_expires_at_cleanup():
    from mtg_analyzer.game.mana_abilities import mana_abilities_for
    from mtg_analyzer.game import durations
    engine, p1 = two_player_game()
    lich = card(engine, "Havengul Lich")
    creature = card(engine, "Llanowar Elves", Zone.GRAVEYARD)
    engine.state.current_phase, engine.state.current_step = "main1", "main1"
    p1.mana_pool.add("G", 3)
    engine.activate_ability(p1, lich, 0, targets=[creature])
    engine.resolve_until_stable()
    engine.cast_spell(p1, creature)
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()
    engine.recompute_continuous_effects()
    assert mana_abilities_for(lich, engine.state)[0].options == [{"G": 1}]
    durations.sweep(engine.state, "cleanup")
    engine.recompute_continuous_effects()
    assert mana_abilities_for(lich, engine.state) == []


def test_havengul_removed_source_cannot_receive_abilities():
    engine, p1 = two_player_game()
    lich = card(engine, "Havengul Lich")
    creature = card(engine, "Prodigal Pyromancer", Zone.GRAVEYARD)
    lich.activated_abilities[0].effects[0].apply(engine.rules.context, [creature])
    engine.rules.put_into_graveyard(lich)
    engine.state.current_phase, engine.state.current_step = "main1", "main1"
    p1.mana_pool.add("R", 3)
    engine.cast_spell(p1, creature)
    engine.resolve_until_stable()
    assert lich.temp_granted_activated_abilities == []


@pytest.mark.parametrize("branch", ["0", "1", "2"])
def test_dusk_mangler_three_additional_costs_and_etb(branch):
    engine, p1 = two_player_game()
    p2 = engine.state.players[1]
    spell = card(engine, "Dusk Mangler", Zone.HAND)
    own = card(engine, "Llanowar Elves")
    hand = card(engine, "Forest", Zone.HAND)
    victim = card(engine, "Llanowar Elves", owner="p2")
    opponent_hand = card(engine, "Forest", Zone.HAND, owner="p2")
    engine.state.current_phase, engine.state.current_step = "main1", "main1"
    p1.mana_pool.add("B", 7)
    engine.cast_spell(p1, spell)
    assert engine.state.pending_choice["kind"] == "cast_cost_alternative"
    assert [o["id"] for o in engine.state.pending_choice["options"]] == ["0", "1", "2"]
    assert spell.zone == Zone.HAND and p1.mana_pool.total() == 7
    engine.resolve_pending_choice(branch)
    engine.resolve_until_stable()
    assert spell.zone == Zone.BATTLEFIELD
    assert (own.zone == Zone.GRAVEYARD) == (branch == "0")
    assert (hand.zone == Zone.GRAVEYARD) == (branch == "1")
    assert p1.life == (16 if branch == "2" else 20)
    assert victim.zone == Zone.GRAVEYARD and opponent_hand.zone == Zone.GRAVEYARD and p2.life == 16


def test_dusk_mangler_unpayable_branches_and_no_free_cast_escape():
    engine, p1 = two_player_game()
    spell = card(engine, "Dusk Mangler", Zone.HAND)
    engine.state.current_phase, engine.state.current_step = "main1", "main1"
    p1.life = 3
    assert not engine.can_cast(p1, spell, free=True)
    p1.life = 4
    engine.cast_spell(p1, spell, free=True)
    assert [o["id"] for o in engine.state.pending_choice["options"]] == ["2"]


def test_dusk_mangler_cost_choice_survives_clone_and_chooses_discard():
    from mtg_analyzer.game.game_engine import GameEngine
    engine, p1 = two_player_game()
    spell = card(engine, "Dusk Mangler", Zone.HAND)
    a = card(engine, "Forest", Zone.HAND)
    b = card(engine, "Mountain", Zone.HAND)
    engine.state.current_phase, engine.state.current_step = "main1", "main1"
    p1.mana_pool.add("B", 7)
    engine.cast_spell(p1, spell)
    restored = GameEngine(engine.state.clone())
    restored.resolve_pending_choice("1")
    assert restored.state.pending_choice["kind"] == "cast_cost_object"
    restored.resolve_pending_choice(str(b.instance_id))
    restored.resolve_until_stable()
    assert restored.state.find_object(b.instance_id).zone == Zone.GRAVEYARD
    assert restored.state.find_object(a.instance_id).zone == Zone.HAND
    assert b.zone == Zone.HAND  # the live game and its clone stay independent


def test_jinnie_pending_replacement_clone_keeps_token_riders_and_following_clause():
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.game.effects.counters_tokens import CreateTokenEffect
    from mtg_analyzer.game.combat import has
    engine, p1 = two_player_game()
    card(engine, "Jinnie Fay, Jetmir's Second")
    engine.state.current_phase, engine.state.current_step = "combat", "declare_attackers"
    spell = GameObject(Card(id="rider-test", name="Token rider test", type_line="Instant", is_instant=True),
                       owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    create = CreateTokenEffect(count=2, token_name="Bird", power=1, toughness=1, colors=["U"],
        subtypes=["Bird"], keywords=["flying"], token_dies_gain_life=1,
        tapped=True, attacking=True, extra_counters={"kind": "+1/+1", "count": 1}, source=spell)
    following = EffectRegistry.create("grant_until", {"previous_subject": True, "target_kind": None,
        "static": {"type": "grant_keyword", "params": {"keywords": ["menace"]}}})
    following.source = spell
    spell.spell_effects = [create, following]
    engine.rules.cast_spell(p1, spell)
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice["kind"] == "replacement_order"
    restored = GameEngine(engine.state.clone())
    restored.resolve_pending_choice("0")
    restored.resolve_until_stable()
    restored.recompute_continuous_effects()
    tokens = [o for o in restored.state.permanents() if o.is_token]
    assert len(tokens) == 2
    assert all(t.name == "Cat" and t.tapped and t.attacking for t in tokens)
    assert all(t.counters["+1/+1"] == 1 and has(t, "haste") and has(t, "menace") for t in tokens)
    assert all(not has(t, "flying") and not t.triggered_abilities for t in tokens)
    assert not any(o.is_token for o in engine.state.permanents())
    assert restored.state.find_object(spell.instance_id).zone == Zone.GRAVEYARD
