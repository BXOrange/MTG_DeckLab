"""Bounded entry choices, MV-only spell triggers and this-turn counter visits."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.game.catalogue.cards.test_star_trek_one_offs_h import _game
from tests.support.star_trek import cast, stock_library, vanilla


def _card(name):
    if name == "Nyota Uhura, Communications":
        return Card(id="uhura", name=name, type_line="Legendary Creature — Human Officer",
                    mana_cost_string="{2}{U}", converted_mana_cost=3, is_creature=True, power=2, toughness=4,
                    oracle_text="Hailing Frequencies — As Nyota Uhura enters, choose a number between 0 and 10.\n"
                    "Open a Channel — Whenever an opponent casts a spell with mana value equal to the chosen number, you draw a card.")
    if name == "La Forge, Thoughtful as Ever":
        return Card(id="la-forge", name=name, type_line="Legendary Creature — Human Artificer",
                    mana_cost_string="{3}{U}", converted_mana_cost=4, is_creature=True, power=2, toughness=4,
                    oracle_text="{T}: For each permanent you control that you've put a counter on this turn, create a 1/1 blue Faerie creature token with flying.")
    if name == "Talion, the Kindly Lord":
        return Card(id="talion", name=name, type_line="Legendary Creature — Faerie Noble",
                    mana_cost_string="{2}{U}{B}", converted_mana_cost=4, is_creature=True, power=3, toughness=4,
                    keywords=["Flying"], oracle_text="Flying\nAs Talion enters, choose a number between 1 and 10.\n"
                    "Whenever an opponent casts a spell with mana value, power, or toughness equal to the chosen number, that player loses 2 life and you draw a card.")
    assert name == "Sanctum Prelate"
    return Card(id="prelate", name=name, type_line="Creature — Human Cleric", is_creature=True,
                power=2, toughness=2, mana_cost_string="{1}{W}{W}", converted_mana_cost=3,
                oracle_text="As this creature enters, choose a number.\nNoncreature spells with mana value equal to the chosen number can't be cast.")


def _put(engine, card, zone=Zone.HAND, player="p1"):
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _uhura(number=3):
    engine, p1, p2 = _game()
    obj = _put(engine, _card("Nyota Uhura, Communications"))
    cast(engine, p1, obj)
    engine.resolve_pending_choice(str(number))
    engine.resolve_until_stable()
    stock_library(engine, "p1", 8)
    return engine, p1, p2, obj


@pytest.mark.parametrize("name", ["Nyota Uhura, Communications", "La Forge, Thoughtful as Ever"])
def test_specs_are_fresh_valid_and_bind(name):
    first, second = specs_for(_card(name)), specs_for(_card(name))
    assert first and first[0] is not second[0] and first[0].effects[0] is not second[0].effects[0]
    for spec in first:
        spec.validate()
    engine, _, _ = _game()
    obj = _put(engine, _card(name), Zone.BATTLEFIELD)
    assert (obj.enter_choice_effects and obj.triggered_abilities) if name.startswith("Nyota") else obj.activated_abilities


@pytest.mark.parametrize("answer,expected", [("0", 0), ("10", 10), ("-1", 0), ("11", 0), ("invalid", 0)])
@pytest.mark.parametrize("clone", [False, True])
def test_uhura_entry_choice_enforces_bounds_before_entry_and_survives_clone(answer, expected, clone):
    engine, p1, _ = _game()
    obj = _put(engine, _card("Nyota Uhura, Communications"))
    cast(engine, p1, obj)
    choice = engine.state.pending_choice
    assert choice["kind"] == "choose_number" and not choice.get("free_text")
    assert [o["id"] for o in choice["options"]] == [str(i) for i in range(11)]
    assert obj not in engine.state.battlefield
    if clone:
        engine = GameEngine(engine.state.clone())
    engine.resolve_pending_choice(answer)
    engine.resolve_until_stable()
    entrant = next(o for o in engine.state.battlefield if o.name == obj.name)
    assert entrant.chosen_number == expected


def test_talion_has_one_to_ten_choice_and_unbounded_prelate_still_accepts_large_number():
    for name, answer, expected in [("Talion, the Kindly Lord", "0", 1), ("Sanctum Prelate", "123", 123)]:
        engine, p1, _ = _game()
        obj = _put(engine, _card(name))
        cast(engine, p1, obj)
        choice = engine.state.pending_choice
        if name.startswith("Talion"):
            assert [o["id"] for o in choice["options"]] == [str(i) for i in range(1, 11)]
        else:
            assert choice.get("free_text") and not choice["options"]
        engine.resolve_pending_choice(answer)
        engine.resolve_until_stable()
        assert obj.chosen_number == expected


@pytest.mark.parametrize("mv,power,toughness,draws", [(3, 1, 1, 1), (7, 3, 1, 0), (7, 1, 3, 0), (7, 1, 1, 0)])
def test_uhura_matches_mana_value_only(mv, power, toughness, draws):
    engine, p1, p2, _ = _uhura()
    engine.state.active_player_index = 1
    spell = _put(engine, Card(id="spell", name="Spell", type_line="Creature — Bear", is_creature=True,
                              mana_cost_string=f"{{{mv}}}", converted_mana_cost=mv, power=power, toughness=toughness), player="p2")
    cast(engine, p2, spell)
    assert len(p1.hand) == draws and p2.life == 20


def test_uhura_zero_choice_and_own_spell_exclusion():
    engine, p1, p2, _ = _uhura(0)
    for player, expected in [("p1", 0), ("p2", 1)]:
        spell = _put(engine, Card(id=player, name=f"Zero {player}", type_line="Instant", is_instant=True,
                                  mana_cost_string="{0}"), player=player)
        cast(engine, engine.state.player_by_id(player), spell)
        assert len(p1.hand) == expected


def test_uhura_uses_stack_mana_value_for_x_and_draws_before_spell_resolves():
    engine, p1, p2, _ = _uhura(3)
    spell = _put(engine, Card(id="x", name="X spell", type_line="Instant", is_instant=True,
                              mana_cost_string="{X}{U}", converted_mana_cost=1), player="p2")
    p2.mana_pool.add_many({"C": 2, "U": 1})
    engine.cast_spell(p2, spell, x=2)
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()
    assert len(p1.hand) == 1 and spell.zone == Zone.STACK
    engine.resolve_until_stable()


@pytest.mark.parametrize("power,toughness", [(3, 1), (1, 3)])
def test_talion_still_matches_power_or_toughness(power, toughness):
    engine, p1, p2 = _game()
    talion = _put(engine, _card("Talion, the Kindly Lord"))
    cast(engine, p1, talion)
    engine.resolve_pending_choice("3")
    engine.resolve_until_stable()
    stock_library(engine, "p1", 2)
    engine.state.active_player_index = 1
    spell = _put(engine, Card(id="spell", name="Spell", type_line="Creature — Bear", is_creature=True,
                              mana_cost_string="{5}", converted_mana_cost=5, power=power, toughness=toughness), player="p2")
    cast(engine, p2, spell)
    assert len(p1.hand) == 1 and p2.life == 18


def _la_forge():
    engine, p1, p2 = _game()
    source = _put(engine, _card("La Forge, Thoughtful as Ever"), Zone.BATTLEFIELD)
    return engine, p1, p2, source


def _activate(engine, player, source):
    engine.activate_ability(player, source)
    engine.resolve_until_stable()
    return [o for o in engine.state.battlefield if o.is_token and o.controller_id == player.id]


def test_la_forge_counts_distinct_current_permanents_not_counters_and_uses_correct_actor():
    engine, p1, p2, source = _la_forge()
    mine = _put(engine, Card(id="rock", name="Rock", type_line="Artifact"), Zone.BATTLEFIELD)
    ignored = _put(engine, Card(id="ignored", name="Ignored", type_line="Artifact"), Zone.BATTLEFIELD)
    opponent = vanilla(engine, "p2")
    for amount, kind in [(2, "charge"), (1, "charge"), (1, "storage")]:
        engine.rules.add_counters(mine, amount, kind=kind, source=source)
    engine.rules.add_counters(source, 1, source=source)
    engine.rules.add_counters(ignored, 1, kind="charge", source=opponent)
    engine.rules.add_counters(opponent, 1, source=source)
    engine.rules.add_player_counters(p1, 1, "energy", source=source)
    tokens = _activate(engine, p1, source)
    assert len(tokens) == 2
    assert all((o.power, o.toughness, o.colors) == (1, 1, {"U"}) and combat.has(o, "flying")
               and o.has_subtype("Faerie") for o in tokens)


def test_la_forge_keeps_history_after_counter_removal_but_excludes_blinked_permanent():
    engine, p1, p2, source = _la_forge()
    retained = vanilla(engine, "p1", "Retained")
    blinked = vanilla(engine, "p1", "Blinked")
    engine.rules.add_counters(retained, 1, source=source)
    engine.rules.add_counters(retained, -1, source=source)
    engine.rules.add_counters(blinked, 1, source=source)
    engine.rules.return_to_hand(blinked)
    cast(engine, p1, blinked)
    assert len(_activate(engine, p1, source)) == 1


def test_la_forge_counts_entry_counters_and_checks_control_at_resolution():
    engine, p1, p2, source = _la_forge()
    entrant = _put(engine, Card(id="entry", name="Counter Entrant", type_line="Creature — Bear", is_creature=True,
                                power=2, toughness=2, oracle_text="This creature enters with two +1/+1 counters on it."))
    cast(engine, p1, entrant)
    assert entrant.plus_one_counters == 2
    gained = vanilla(engine, "p2", "Gained")
    lost = vanilla(engine, "p1", "Lost")
    engine.rules.add_counters(gained, 1, source=source)
    engine.rules.add_counters(lost, 1, source=source)
    engine.activate_ability(p1, source)
    gained.controller_id = "p1"
    lost.controller_id = "p2"
    late = vanilla(engine, "p1", "Late")
    engine.rules.add_counters(late, 1, source=source)
    engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.is_token]) == 3, (
        [(o.name, o.instance_id, o.zone_incarnation) for o in engine.state.battlefield],
        [e.data for e in engine.state.events_this_turn() if e.type == "COUNTER"],
    )


def test_la_forge_does_not_count_counters_placed_in_exile_before_entry():
    engine, p1, _, source = _la_forge()
    obj = _put(engine, Card(id="exiled", name="Exiled Bear", type_line="Creature — Bear", is_creature=True,
                           power=2, toughness=2), Zone.EXILE)
    engine.rules.add_counters(obj, 1, kind="charge", source=source)
    engine.rules.return_from_graveyard(obj, "battlefield")
    engine.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD
    assert not _activate(engine, p1, source)


def test_la_forge_counts_automatic_saga_entry_and_turn_based_lore_placement():
    engine, p1, _, source = _la_forge()
    saga = _put(engine, Card(id="saga", name="History Saga", type_line="Enchantment — Saga",
                             oracle_text="(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)\n"
                             "I, II, III — You gain 1 life."))
    cast(engine, p1, saga)
    assert len(_activate(engine, p1, source)) == 1
    engine.begin_turn()
    engine.state.current_step = "main1"
    engine.state.active_player_index = 0
    engine.rules.advance_sagas(p1)
    engine.resolve_until_stable()
    source.tapped = False
    assert len(_activate(engine, p1, source)) == 2


def test_la_forge_counts_positive_loyalty_activation_cost():
    engine, p1, _, source = _la_forge()
    walker = _put(engine, Card(id="walker", name="History Walker", type_line="Planeswalker — Test",
                              loyalty=2, oracle_text="+1: You gain 1 life."), Zone.BATTLEFIELD)
    engine.activate_ability(p1, walker)
    engine.resolve_until_stable()
    assert walker.counters["loyalty"] == 3
    assert len(_activate(engine, p1, source)) == 1


def test_la_forge_turn_history_and_choice_state_survive_clone_then_reset_next_turn():
    engine, p1, p2, source = _la_forge()
    engine.rules.add_counters(source, 1, source=source)
    engine = GameEngine(engine.state.clone())
    p1 = engine.state.player_by_id("p1")
    source = engine.state.find_object(source.instance_id)
    assert len(_activate(engine, p1, source)) == 1
    engine.begin_turn()
    engine.state.current_step = "main1"
    engine.state.active_player_index = 0
    source.tapped = False
    assert len(_activate(engine, p1, source)) == 1  # only the existing token
