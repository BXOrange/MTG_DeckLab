"""Announced costs, independently measured player targets and damage payoffs."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.game.events import EventType, GameEvent
from tests.support.deck_batch import RICH, card, filler, game, main_phase, step


@pytest.mark.parametrize("x", [0, 2])
def test_sphinx_pays_announced_energy_before_its_draw_ability_resolves(x):
    engine = game()
    sphinx = card(engine, "Sphinx of the Revelation")
    me = engine.state.player_by_id("p1")
    me.counters["energy"] = 3
    me.mana_pool.add_many({"W": 1, "U": 2})
    main_phase(engine)
    action = next(a for a in engine.legal_actions(me)
                  if a["type"] == "activate_ability" and a.get("instance_id") == sphinx.instance_id)
    assert action["has_x"] and action["max_x"] == 3
    before = len(me.hand)
    engine.activate_ability(me, sphinx, 0, x=x)
    assert me.counters["energy"] == 3 - x and len(me.hand) == before
    assert engine.state.pending_choice is None
    engine.resolve_until_stable()
    assert len(me.hand) == before + x


def test_sphinx_does_not_allow_an_energy_payment_greater_than_available():
    engine = game()
    sphinx = card(engine, "Sphinx of the Revelation")
    me = engine.state.player_by_id("p1")
    me.counters["energy"] = 2
    me.mana_pool.add_many({"W": 1, "U": 2})
    main_phase(engine)
    with pytest.raises(ValueError):
        engine.activate_ability(me, sphinx, 0, x=3)
    assert me.counters["energy"] == 2 and not sphinx.tapped


@pytest.mark.parametrize("targets", [[], [0], [0, 2], [0, 1, 2]])
def test_riverchurn_can_announce_any_number_of_distinct_players(targets):
    engine = game(players=3)
    monument = card(engine, "Riverchurn Monument")
    players = engine.state.players
    players[0].mana_pool.add_many({"C": 1})
    main_phase(engine)
    before = [len(p.library) for p in players]
    engine.activate_ability(players[0], monument, 0, targets=[players[i] for i in targets])
    engine.resolve_until_stable()
    assert [len(p.library) for p in players] == [n - (2 if i in targets else 0) for i, n in enumerate(before)]


def test_riverchurn_exhaust_measures_each_players_graveyard_separately():
    engine = game(players=3)
    monument = card(engine, "Riverchurn Monument")
    players = engine.state.players
    for index, count in enumerate([1, 3, 5]):
        for n in range(count):
            filler(engine, f"Grave {index} {n}", type_line="Instant", player=players[index].id, zone=Zone.GRAVEYARD)
    players[0].mana_pool.add_many({"C": 2, "U": 2})
    main_phase(engine)
    engine.activate_ability(players[0], monument, 1, targets=players)
    engine.resolve_until_stable()
    assert [len(p.library) for p in players] == [9, 7, 5]


def test_barret_announces_a_rebel_target_even_when_no_equipment_is_chosen():
    engine = game()
    card(engine, "Barret, Avalanche Leader")
    rebel = filler(engine, "Rebel", type_line="Creature — Rebel", power=2, toughness=2)
    step(engine, "begin_combat")
    assert engine.state.pending_choice is not None
    # Decline the optional Equipment slot, then select the mandatory Rebel.
    for _ in range(3):
        choice = engine.state.pending_choice
        if choice is None:
            break
        options = choice.get("options", [])
        decline = next((o for o in options if o["id"] == "decline"), None)
        chosen = decline or next(o for o in options if str(o["id"]) == str(rebel.instance_id))
        engine.resolve_pending_choice(str(chosen["id"]))
    assert not engine.state.stack and rebel.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize("marked,expected", [(0, 2), (2, 4)])
def test_cramped_vents_gains_life_from_damage_beyond_remaining_lethal_damage(marked, expected):
    engine = game()
    room = card(engine, "Cramped Vents", zone=Zone.HAND)
    victim = filler(engine, "Victim", player="p2", power=2, toughness=4)
    victim.damage_marked = marked
    me = engine.state.player_by_id("p1")
    me.mana_pool.add_many({"B": 1, "C": 3})
    main_phase(engine)
    engine.cast_spell(me, room)
    engine.resolve_until_stable()
    engine.resolve_pending_choice(str(victim.instance_id))
    assert me.life == 20 + expected and victim.zone == Zone.GRAVEYARD


def test_cramped_vents_gains_no_life_when_its_damage_is_prevented():
    engine = game()
    room = card(engine, "Cramped Vents", zone=Zone.HAND)
    victim = filler(engine, "Shielded", player="p2", power=2, toughness=4)
    victim.counters["shield"] = 1
    me = engine.state.player_by_id("p1")
    me.mana_pool.add_many({"B": 1, "C": 3})
    main_phase(engine)
    engine.cast_spell(me, room)
    engine.resolve_until_stable()
    engine.resolve_pending_choice(str(victim.instance_id))
    assert me.life == 20 and victim.damage_marked == 0


def test_rikku_restricts_only_blockers_controlled_by_the_trigger_controllers_opponents():
    from mtg_analyzer.game import combat
    engine = game(players=3)
    card(engine, "Rikku, Resourceful Guardian")
    recipient = filler(engine, "Recipient", player="p2", power=2, toughness=2)
    mine = filler(engine, "Mine", power=2, toughness=2)
    third = filler(engine, "Third", player="p3", power=2, toughness=2)
    source = filler(engine, "Counter Source", power=2, toughness=2)
    engine.rules.add_counters(recipient, 1, "+1/+1", source=source)
    engine.resolve_until_stable()
    assert combat.blocker_allowed(recipient, mine, engine.state)
    assert not combat.blocker_allowed(recipient, third, engine.state)
    engine._step_cleanup()
    assert combat.blocker_allowed(recipient, third, engine.state)


def test_tip_the_scales_sacrifices_before_a_separate_respondable_shrink_trigger():
    engine = game()
    spell = card(engine, "Tip the Scales", zone=Zone.HAND)
    sacrifice = filler(engine, "Sacrifice", power=1, toughness=3)
    survivor = filler(engine, "Survivor", power=5, toughness=5)
    me = engine.state.player_by_id("p1")
    me.mana_pool.add_many({"C": 2, "B": 1})
    main_phase(engine)
    engine.cast_spell(me, spell)
    engine.resolve_until_stable()
    engine.rules.resolve_choice(str(sacrifice.instance_id))
    assert sacrifice.zone == Zone.GRAVEYARD and survivor.toughness == 5
    engine.rules.put_triggers_on_stack()
    assert engine.state.stack
    # A different toughness after the sacrifice cannot change the captured X.
    sacrifice.card.toughness = 9
    engine.resolve_until_stable()
    assert survivor.toughness == 2


def test_territorial_aetherkite_pays_energy_before_a_separate_damage_trigger():
    engine = game()
    kite = card(engine, "Territorial Aetherkite", zone=Zone.HAND)
    victim = filler(engine, "Victim", power=2, toughness=4)
    me = engine.state.player_by_id("p1")
    me.mana_pool.add_many(RICH)
    main_phase(engine)
    engine.cast_spell(me, kite)
    engine.resolve_until_stable()
    engine.rules.resolve_choice("pay_x:2")
    assert me.counters.get("energy", 0) == 0 and victim.damage_marked == 0
    engine.rules.put_triggers_on_stack()
    assert engine.state.stack
    engine.resolve_until_stable()
    assert victim.damage_marked == 2
