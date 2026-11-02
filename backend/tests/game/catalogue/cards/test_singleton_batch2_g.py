"""Singleton batch 2 (worker G): ten hand-authored cards, each executed in a real engine."""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import is_registered
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models import Card, GameObject, ManaCost, Zone

#: Enough of every colour that mana never decides the outcome of a test.
_POOL_AMOUNT = 30


def _card(name, type_line, text="", cost="{1}", power=None, toughness=None, **flags):
    is_creature = "creature" in type_line.lower()
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=is_creature, is_instant="instant" in type_line.lower(),
        is_sorcery="sorcery" in type_line.lower(),
        power=power if is_creature else None, toughness=toughness if is_creature else None,
        oracle_text=text, is_legendary="legendary" in type_line.lower(), **flags,
    )


def _bear(name="Bear", power=2, toughness=2, type_line="Creature — Bear"):
    return _card(name, type_line, "", "{1}{G}", power, toughness)


def _engine():
    filler = [_bear(f"Filler {i}", 1, 1) for i in range(30)]
    return GameEngine.new_game(
        [("p1", "Alice", list(filler)), ("p2", "Bob", list(filler))], starting_life=20, starting_hand=0,
    )


def _put(engine, card, controller="p1", tapped=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    obj.tapped = tapped
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _to_hand(engine, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    obj.controller_id = controller
    bind_from_catalogue(obj)
    engine.state.player_by_id(controller).hand.append(obj)
    return obj


def _to_graveyard(engine, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.GRAVEYARD)
    obj.controller_id = controller
    engine.state.player_by_id(controller).graveyard.append(obj)
    return obj


def _stack_library(engine, cards, controller="p1"):
    """Replace the top of the library with ``cards`` (first card ends up on top)."""
    library = engine.state.player_by_id(controller).library
    objs = []
    for card in reversed(cards):  # the library's end is its top (`RulesEngine._mill` pops it)
        obj = GameObject(card, owner_id=controller, zone=Zone.LIBRARY)
        obj.controller_id = controller
        objs.append(obj)
    library[-len(objs):] = objs
    return list(reversed(objs))


def _main_phase(engine):
    engine.start()
    while engine.state.current_phase != "precombat_main":
        engine.advance_step()
    player = engine.state.player_by_id("p1")
    for colour in "WUBRGC":
        player.mana_pool.add(colour, _POOL_AMOUNT)
    return player


def _cast(engine, player, obj, **kwargs):
    engine.cast_spell(player, obj, **kwargs)
    engine.resolve_until_stable()


def _answer(engine, option_id=None):
    """Answer the open pending choice (the first option unless ``option_id`` is given), then settle."""
    choice = engine.state.pending_choice
    assert choice is not None, "expected an open choice"
    engine.rules.resolve_choice(str(option_id if option_id is not None else choice["options"][0]["id"]))
    engine.resolve_until_stable()



def _settle(engine, answers=()):
    """Resolve the stack, answering each pending choice from ``answers`` (instance/player ids) in order."""
    engine.resolve_until_stable()
    for answer in answers:
        assert engine.state.pending_choice is not None, "expected an open choice"
        engine.rules.resolve_choice(str(answer))
        engine.resolve_until_stable()


# --- Elenda, Saint of Dusk ------------------------------------------------------------------------------------

_ELENDA_TEXT = (
    "Lifelink, hexproof from instants\nAs long as your life total is greater than your starting life total, Elenda "
    "gets +1/+1 and has menace. Elenda gets an additional +5/+5 as long as your life total is at least 10 greater "
    "than your starting life total."
)


def _elenda(engine, controller="p1"):
    card = _card("Elenda, Saint of Dusk", "Legendary Creature \u2014 Vampire Knight", _ELENDA_TEXT, "{2}{W}{B}", 1, 1,
                 keywords=["Lifelink"])
    return _put(engine, card, controller)


def test_elenda_registered():
    assert is_registered("Elenda, Saint of Dusk")


def test_elenda_grows_with_life_over_starting_total():
    engine = _engine()
    elenda = _elenda(engine)
    engine.recompute_continuous_effects()
    assert (elenda.power, elenda.toughness) == (1, 1)  # exactly at the starting total: not "greater"
    assert "menace" not in elenda.granted_keywords
    engine.state.player_by_id("p1").life = 21
    engine.recompute_continuous_effects()
    assert (elenda.power, elenda.toughness) == (2, 2)
    assert "menace" in elenda.granted_keywords
    engine.state.player_by_id("p1").life = 29  # 9 over: still not the +5/+5 tier
    engine.recompute_continuous_effects()
    assert (elenda.power, elenda.toughness) == (2, 2)
    engine.state.player_by_id("p1").life = 30
    engine.recompute_continuous_effects()
    assert (elenda.power, elenda.toughness) == (7, 7)


def test_elenda_ignores_life_total_of_other_players():
    engine = _engine()
    elenda = _elenda(engine)
    engine.state.player_by_id("p2").life = 40
    engine.recompute_continuous_effects()
    assert (elenda.power, elenda.toughness) == (1, 1)


def test_elenda_hexproof_from_instants_only():
    from mtg_analyzer.game.targeting import _targetable_by

    engine = _engine()
    elenda = _elenda(engine)
    engine.recompute_continuous_effects()

    def _source(type_line, zone, controller="p2"):
        obj = GameObject(_card("Src", type_line, "", "{1}"), owner_id=controller, zone=zone)
        obj.controller_id = controller
        return obj

    assert not _targetable_by(elenda, _source("Instant", Zone.STACK))
    assert _targetable_by(elenda, _source("Sorcery", Zone.STACK))
    assert _targetable_by(elenda, _source("Creature \u2014 Elf", Zone.BATTLEFIELD))
    assert _targetable_by(elenda, _source("Instant", Zone.STACK, controller="p1"))  # its own controller's instant


# --- Custodi Lich ---------------------------------------------------------------------------------------------

_LICH_TEXT = (
    "When this creature enters, you become the monarch.\n"
    "Whenever you become the monarch, target player sacrifices a creature of their choice."
)


def test_custodi_lich_registered():
    assert is_registered("Custodi Lich")


def test_custodi_lich_enters_and_forces_a_sacrifice():
    engine = _engine()
    victim = _put(engine, _bear("Victim"), controller="p2")
    player = _main_phase(engine)
    lich = _to_hand(engine, _card("Custodi Lich", "Creature \u2014 Zombie Cleric", _LICH_TEXT, "{3}{B}{B}", 4, 2))
    _cast(engine, player, lich)
    _settle(engine, ["p2"])
    assert engine.state.monarch_id == "p1"
    assert victim.zone == Zone.GRAVEYARD


def test_custodi_lich_can_target_its_own_controller():
    engine = _engine()
    mine = _put(engine, _bear("Mine"))
    player = _main_phase(engine)
    lich = _to_hand(engine, _card("Custodi Lich", "Creature \u2014 Zombie Cleric", _LICH_TEXT, "{3}{B}{B}", 4, 2))
    _cast(engine, player, lich)
    _settle(engine, ["p1", mine.instance_id])  # target yourself, then choose which creature goes
    assert mine.zone == Zone.GRAVEYARD
    assert lich.zone == Zone.BATTLEFIELD


def test_custodi_lich_triggers_when_taking_the_crown_later_but_not_when_already_monarch():
    engine = _engine()
    lich = _put(engine, _card("Custodi Lich", "Creature \u2014 Zombie Cleric", _LICH_TEXT, "{3}{B}{B}", 4, 2))
    victim = _put(engine, _bear("Victim"), controller="p2")
    engine.state.monarch_id = "p1"
    engine.rules.become_monarch(engine.state.player_by_id("p1"))  # already the monarch: not "becoming"
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and victim.zone == Zone.BATTLEFIELD
    engine.state.monarch_id = "p2"
    engine.rules.become_monarch(engine.state.player_by_id("p1"))  # RULE 725.2: now it changes hands
    _settle(engine, ["p2"])
    assert victim.zone == Zone.GRAVEYARD
    assert lich.zone == Zone.BATTLEFIELD


# --- Daretti, Rocketeer Engineer -------------------------------------------------------------------------------

_DARETTI_TEXT = (
    "Daretti's power is equal to the greatest mana value among artifacts you control.\n"
    "Whenever Daretti enters or attacks, choose target artifact card in your graveyard. You may sacrifice an "
    "artifact. If you do, return the chosen card to the battlefield."
)


def _daretti_card():
    return _card("Daretti, Rocketeer Engineer", "Legendary Creature — Goblin Artificer", _DARETTI_TEXT, "{4}{R}", 0, 5)


def _artifact(name, cost="{3}"):
    return _card(name, "Artifact", "", cost)


def test_daretti_registered():
    assert is_registered("Daretti, Rocketeer Engineer")


def test_daretti_power_is_greatest_artifact_mana_value():
    engine = _engine()
    daretti = _put(engine, _daretti_card())
    _put(engine, _artifact("Two", "{2}"))
    _put(engine, _artifact("Five", "{5}"))
    _put(engine, _artifact("Opposing Seven", "{7}"), controller="p2")
    engine.recompute_continuous_effects()
    assert daretti.power == 5


def test_daretti_enters_sacrifice_an_artifact_to_reanimate_the_target():
    engine = _engine()
    fodder = _put(engine, _artifact("Fodder", "{1}"))
    target = _to_graveyard(engine, _artifact("Big Artifact", "{4}"))
    player = _main_phase(engine)
    _cast(engine, player, _to_hand(engine, _daretti_card()))
    assert engine.state.pending_choice["kind"] == "trigger_target"
    _settle(engine, [target.instance_id, "pay"])
    assert fodder.zone == Zone.GRAVEYARD
    assert target.zone == Zone.BATTLEFIELD


def test_daretti_declining_the_sacrifice_returns_nothing():
    engine = _engine()
    fodder = _put(engine, _artifact("Fodder", "{1}"))
    target = _to_graveyard(engine, _artifact("Big Artifact", "{4}"))
    player = _main_phase(engine)
    _cast(engine, player, _to_hand(engine, _daretti_card()))
    _settle(engine, [target.instance_id, "decline"])
    assert fodder.zone == Zone.BATTLEFIELD
    assert target.zone == Zone.GRAVEYARD


def test_daretti_without_an_artifact_to_sacrifice_returns_nothing():
    engine = _engine()
    target = _to_graveyard(engine, _artifact("Big Artifact", "{4}"))
    player = _main_phase(engine)
    _cast(engine, player, _to_hand(engine, _daretti_card()))
    _settle(engine, [target.instance_id])
    assert target.zone == Zone.GRAVEYARD


def test_daretti_attack_trigger_also_reanimates():
    engine = _engine()
    daretti = _put(engine, _daretti_card())
    fodder = _put(engine, _artifact("Fodder", "{1}"))
    target = _to_graveyard(engine, _artifact("Big Artifact", "{4}"))
    _main_phase(engine)
    while engine.state.current_step != "declare_attackers":
        engine.advance_step()
    engine.declare_attackers(engine.state.player_by_id("p1"), [daretti])
    engine.resolve_until_stable()
    _settle(engine, [target.instance_id, "pay"])
    assert fodder.zone == Zone.GRAVEYARD
    assert target.zone == Zone.BATTLEFIELD


# --- Don & Leo, Problem Solvers ----------------------------------------------------------------------------------

_DON_LEO_TEXT = (
    "Vigilance\nAt the beginning of your end step, exile up to one target artifact you control and up to one "
    "target creature you control. Then return them to the battlefield under their owners' control."
)


def _to_end_step(engine):
    while engine.state.current_step != "end":
        engine.advance_step()


def test_don_and_leo_registered():
    assert is_registered("Don & Leo, Problem Solvers")


def test_don_and_leo_flickers_the_chosen_artifact_and_creature():
    engine = _engine()
    _put(engine, _card("Don & Leo, Problem Solvers", "Legendary Creature — Mutant Ninja Turtle", _DON_LEO_TEXT,
                       "{3}{W}{W}", 4, 6))
    rock = _put(engine, _artifact("Rock", "{2}"))
    rock.counters["charge"] = 3
    bear = _put(engine, _bear("Counter Bear"))
    bear.counters["+1/+1"] = 1
    _main_phase(engine)
    _to_end_step(engine)
    _settle(engine, [rock.instance_id, bear.instance_id])
    names = {o.name: o for o in engine.state.battlefield}
    assert names["Rock"].zone == Zone.BATTLEFIELD and names["Counter Bear"].zone == Zone.BATTLEFIELD
    assert not names["Rock"].counters.get("charge")  # RULE 400.7: a new object, counters gone
    assert not names["Counter Bear"].counters.get("+1/+1")


def test_don_and_leo_can_skip_both_targets():
    engine = _engine()
    _put(engine, _card("Don & Leo, Problem Solvers", "Legendary Creature — Mutant Ninja Turtle", _DON_LEO_TEXT,
                       "{3}{W}{W}", 4, 6))
    bear = _put(engine, _bear("Counter Bear"))
    bear.counters["+1/+1"] = 1
    _main_phase(engine)
    _to_end_step(engine)
    engine.resolve_until_stable()
    assert bear.counters.get("+1/+1") == 1


def test_don_and_leo_returns_a_stolen_creature_to_its_owner():
    engine = _engine()
    _put(engine, _card("Don & Leo, Problem Solvers", "Legendary Creature — Mutant Ninja Turtle", _DON_LEO_TEXT,
                       "{3}{W}{W}", 4, 6))
    stolen = _put(engine, _bear("Stolen Bear"), controller="p2")
    stolen.controller_id = "p1"  # an effect gave p1 control of p2's creature
    _main_phase(engine)
    _to_end_step(engine)
    _settle(engine, [stolen.instance_id])
    back = [o for o in engine.state.battlefield if o.name == "Stolen Bear"]
    assert len(back) == 1 and back[0].controller_id == "p2"  # "under their owners' control"


# --- Edgar's Awakening --------------------------------------------------------------------------------------------

_EDGAR_TEXT = (
    "Return target creature card from your graveyard to the battlefield.\n"
    "When you discard this card, you may pay {B}. When you do, return target creature card from your graveyard "
    "to your hand."
)


def _edgar(engine):
    return _to_hand(engine, _card("Edgar's Awakening", "Sorcery", _EDGAR_TEXT, "{3}{B}{B}"))


def test_edgars_awakening_registered():
    assert is_registered("Edgar's Awakening")


def test_edgars_awakening_cast_reanimates():
    engine = _engine()
    dead = _to_graveyard(engine, _bear("Dead Bear"))
    player = _main_phase(engine)
    _cast(engine, player, _edgar(engine), targets=[dead])
    assert dead.zone == Zone.BATTLEFIELD


def test_edgars_awakening_discard_pay_b_returns_a_creature_to_hand():
    engine = _engine()
    dead = _to_graveyard(engine, _bear("Dead Bear"))
    player = _main_phase(engine)
    player.mana_pool.add("B", 1)
    edgar = _edgar(engine)
    engine.rules.discard_specific(edgar, cause=None)
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "pay_cost_then"
    _settle(engine, ["pay", dead.instance_id])
    assert dead.zone == Zone.HAND
    assert edgar.zone == Zone.GRAVEYARD


def test_edgars_awakening_discard_decline_does_nothing():
    engine = _engine()
    dead = _to_graveyard(engine, _bear("Dead Bear"))
    _main_phase(engine)
    edgar = _edgar(engine)
    engine.rules.discard_specific(edgar, cause=None)
    _settle(engine, ["decline"])
    assert dead.zone == Zone.GRAVEYARD
    assert engine.state.pending_choice is None


def test_edgars_awakening_cast_does_not_fire_the_discard_trigger():
    engine = _engine()
    dead = _to_graveyard(engine, _bear("Dead Bear"))
    player = _main_phase(engine)
    _cast(engine, player, _edgar(engine), targets=[dead])
    assert engine.state.pending_choice is None


def test_don_and_leo_one_permanent_chosen_for_both_targets_is_flickered_once():
    engine = _engine()
    _put(engine, _card("Don & Leo, Problem Solvers", "Legendary Creature — Mutant Ninja Turtle", _DON_LEO_TEXT,
                       "{3}{W}{W}", 4, 6))
    both = _put(engine, _card("Golem", "Artifact Creature — Golem", "", "{3}", 3, 3))
    both.counters["+1/+1"] = 1
    _main_phase(engine)
    _to_end_step(engine)
    _settle(engine, [both.instance_id, both.instance_id])
    golems = [o for o in engine.state.battlefield if o.name == "Golem"]
    assert len(golems) == 1 and not golems[0].counters.get("+1/+1")


# --- Dragon Broodmother -------------------------------------------------------------------------------------------

_BROOD_TEXT = (
    "Flying\nAt the beginning of each upkeep, create a 1/1 red and green Dragon creature token with flying and "
    "devour 2. (As the token enters, you may sacrifice any number of creatures. It enters with twice that many "
    "+1/+1 counters on it.)"
)


def _brood(engine):
    return _put(engine, _card("Dragon Broodmother", "Creature — Dragon", _BROOD_TEXT, "{2}{R}{R}{R}{G}", 4, 4))


def _to_upkeep(engine, player_id="p1"):
    engine.start()
    while not (engine.state.current_step == "upkeep" and engine.state.active_player.id == player_id):
        engine.advance_step()


def _dragons(engine):
    return [o for o in engine.state.battlefield if o.name == "Dragon"]


def test_dragon_broodmother_registered():
    assert is_registered("Dragon Broodmother")


def test_dragon_broodmother_makes_a_plain_dragon_when_nothing_is_devoured():
    engine = _engine()
    _brood(engine)
    _to_upkeep(engine)
    engine.resolve_until_stable()
    # Only the Broodmother can be devoured; decline.
    assert engine.state.pending_choice["kind"] == "choose_objects"
    _settle(engine, ["decline"])
    dragon, = _dragons(engine)
    engine.recompute_continuous_effects()
    assert (dragon.power, dragon.toughness) == (1, 1)
    assert "flying" in combat._obj_keywords(dragon)
    assert dragon.is_token and not dragon.counters.get("+1/+1")


def test_dragon_broodmother_devour_two_counters_per_sacrificed_creature():
    engine = _engine()
    brood = _brood(engine)
    a = _put(engine, _bear("Fodder A"))
    b = _put(engine, _bear("Fodder B"))
    _to_upkeep(engine)
    engine.resolve_until_stable()
    pending = engine.state.pending_choice
    assert pending["kind"] == "choose_objects"
    _settle(engine, [a.instance_id, b.instance_id])
    if engine.state.pending_choice is not None:
        _settle(engine, [engine.state.pending_choice["options"][-1]["id"]])  # stop choosing
    engine.recompute_continuous_effects()
    dragon, = _dragons(engine)
    assert a.zone == Zone.GRAVEYARD and b.zone == Zone.GRAVEYARD and brood.zone == Zone.BATTLEFIELD
    assert dragon.counters.get("+1/+1") == 4  # RULE 702.82a: twice the two sacrificed creatures
    assert (dragon.power, dragon.toughness) == (5, 5)


def test_dragon_broodmother_triggers_on_every_players_upkeep():
    engine = _engine()
    _brood(engine)
    _to_upkeep(engine)
    engine.resolve_until_stable()
    engine.rules.resolve_choice("decline")  # p1's own upkeep: no devour
    engine.resolve_until_stable()
    assert len(_dragons(engine)) == 1
    while not (engine.state.current_step == "upkeep" and engine.state.active_player.id == "p2"):
        engine.advance_step()
    engine.resolve_until_stable()
    pending = engine.state.pending_choice
    assert pending is not None and pending["player_id"] == "p1"  # the Broodmother's controller still chooses
    engine.rules.resolve_choice("decline")
    engine.resolve_until_stable()
    assert len(_dragons(engine)) == 2


# --- Dragonspark Reactor -------------------------------------------------------------------------------------------

_REACTOR_TEXT = (
    "Whenever this artifact or another artifact you control enters, put a charge counter on this artifact.\n"
    "{4}, Sacrifice this artifact: It deals damage equal to the number of charge counters on it to target player "
    "and that much damage to up to one target creature."
)


def _reactor(engine):
    return _put(engine, _card("Dragonspark Reactor", "Artifact", _REACTOR_TEXT, "{1}{R}"))


def test_dragonspark_reactor_registered():
    assert is_registered("Dragonspark Reactor")


def test_dragonspark_reactor_counts_artifacts_entering():
    engine = _engine()
    player = _main_phase(engine)
    reactor = _to_hand(engine, _card("Dragonspark Reactor", "Artifact", _REACTOR_TEXT, "{1}{R}"))
    _cast(engine, player, reactor)
    assert reactor.counters.get("charge") == 1  # itself
    _cast(engine, player, _to_hand(engine, _artifact("Rock", "{1}")))
    assert reactor.counters.get("charge") == 2
    _cast(engine, player, _to_hand(engine, _bear("Not An Artifact")))
    assert reactor.counters.get("charge") == 2
    opposing = _put(engine, _artifact("Their Rock", "{1}"), controller="p2")
    assert opposing.zone == Zone.BATTLEFIELD and reactor.counters.get("charge") == 2


def test_dragonspark_reactor_sacrifice_damages_player_and_creature_by_charge_counters():
    engine = _engine()
    player = _main_phase(engine)
    reactor = _reactor(engine)
    reactor.counters["charge"] = 3
    victim = _put(engine, _bear("Victim", 2, 5), controller="p2")
    opponent = engine.state.player_by_id("p2")
    engine.activate_ability(player, reactor, 0, targets=[opponent, victim])
    engine.resolve_until_stable()
    assert reactor.zone == Zone.GRAVEYARD
    assert opponent.life == 17
    assert victim.damage_marked == 3


def test_dragonspark_reactor_creature_target_is_optional():
    engine = _engine()
    player = _main_phase(engine)
    reactor = _reactor(engine)
    reactor.counters["charge"] = 2
    opponent = engine.state.player_by_id("p2")
    engine.activate_ability(player, reactor, 0, target_groups=[[opponent], []])
    engine.resolve_until_stable()
    assert opponent.life == 18


def test_dragonspark_reactor_with_no_counters_deals_no_damage():
    engine = _engine()
    player = _main_phase(engine)
    reactor = _reactor(engine)
    opponent = engine.state.player_by_id("p2")
    engine.activate_ability(player, reactor, 0, target_groups=[[opponent], []])
    engine.resolve_until_stable()
    assert reactor.zone == Zone.GRAVEYARD and opponent.life == 20


# --- Dark Salvation -----------------------------------------------------------------------------------------------

_SALVATION_TEXT = (
    "Target player creates X 2/2 black Zombie creature tokens, then up to one target creature gets -1/-1 until end "
    "of turn for each Zombie that player controls."
)


def _salvation(engine):
    return _to_hand(engine, _card("Dark Salvation", "Sorcery", _SALVATION_TEXT, "{X}{X}{B}"))


def _zombies(engine, controller):
    return [o for o in engine.state.battlefield if o.name == "Zombie" and o.controller_id == controller]


def test_dark_salvation_registered():
    assert is_registered("Dark Salvation")


def test_dark_salvation_targeted_player_gets_the_zombies_and_the_shrink_counts_them():
    engine = _engine()
    victim = _put(engine, _bear("Big Bear", 4, 4), controller="p2")
    player = _main_phase(engine)
    spell = _salvation(engine)
    engine.cast_spell(player, spell, targets=[engine.state.player_by_id("p2"), victim], x=2)
    engine.resolve_until_stable()
    assert len(_zombies(engine, "p2")) == 2 and not _zombies(engine, "p1")  # RULE 111.2: the targeted player owns them
    engine.recompute_continuous_effects()
    assert (victim.power, victim.toughness) == (2, 2)  # -1/-1 for each of the two Zombies


def test_dark_salvation_counts_zombies_the_targeted_player_already_controls():
    engine = _engine()
    _put(engine, _card("Old Zombie", "Creature — Zombie", "", "{1}", 1, 1), controller="p1")
    victim = _put(engine, _bear("Big Bear", 5, 5), controller="p2")
    player = _main_phase(engine)
    # Targeting yourself: your existing Zombie plus the new X=1 token are both counted.
    engine.cast_spell(player, _salvation(engine), targets=[player, victim], x=1)
    engine.resolve_until_stable()
    assert len(_zombies(engine, "p1")) == 1
    engine.recompute_continuous_effects()
    assert (victim.power, victim.toughness) == (3, 3)


def test_dark_salvation_x_zero_makes_nothing_and_shrinks_nothing():
    engine = _engine()
    victim = _put(engine, _bear("Big Bear", 4, 4), controller="p2")
    player = _main_phase(engine)
    engine.cast_spell(player, _salvation(engine), targets=[engine.state.player_by_id("p2"), victim], x=0)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert not _zombies(engine, "p2") and (victim.power, victim.toughness) == (4, 4)


def test_dark_salvation_creature_target_is_optional_and_shrink_can_kill():
    engine = _engine()
    player = _main_phase(engine)
    engine.cast_spell(player, _salvation(engine), target_groups=[[engine.state.player_by_id("p2")], []], x=3)
    engine.resolve_until_stable()
    assert len(_zombies(engine, "p2")) == 3
    # Now shrink one of the Zombies themselves with a second casting: 2/2s with -N/-N die.
    engine2 = _engine()
    p2_target = _put(engine2, _bear("Small Bear", 2, 2), controller="p2")
    player2 = _main_phase(engine2)
    engine2.cast_spell(player2, _salvation(engine2), targets=[engine2.state.player_by_id("p2"), p2_target], x=2)
    engine2.resolve_until_stable()
    assert p2_target.zone == Zone.GRAVEYARD  # -2/-2 on a 2/2


# --- Echocasting Symposium ----------------------------------------------------------------------------------------

_SYMPOSIUM_TEXT = (
    "Target player creates a token that's a copy of target creature you control.\n"
    "Paradigm (Then exile this spell. After you first resolve a spell with this name, you may cast a copy of it "
    "from exile without paying its mana cost at the beginning of each of your first main phases.)"
)


def _symposium(engine):
    return _to_hand(engine, _card("Echocasting Symposium", "Sorcery — Lesson", _SYMPOSIUM_TEXT, "{4}{U}{U}"))


def _named(engine, name, controller):
    return [o for o in engine.state.battlefield if o.name == name and o.controller_id == controller]


def test_echocasting_symposium_registered():
    assert is_registered("Echocasting Symposium")


def test_echocasting_symposium_target_player_gets_the_copy_token():
    engine = _engine()
    mine = _put(engine, _bear("Mine", 3, 3))
    player = _main_phase(engine)
    spell = _symposium(engine)
    engine.cast_spell(player, spell, targets=[engine.state.player_by_id("p2"), mine])
    engine.resolve_until_stable()
    copies = _named(engine, "Mine", "p2")
    assert len(copies) == 1 and copies[0].is_token  # RULE 707.2: p2 creates and controls the token copy
    assert len(_named(engine, "Mine", "p1")) == 1


def test_echocasting_symposium_is_exiled_with_paradigm_instead_of_going_to_the_graveyard():
    engine = _engine()
    mine = _put(engine, _bear("Mine", 3, 3))
    player = _main_phase(engine)
    spell = _symposium(engine)
    engine.cast_spell(player, spell, targets=[player, mine])
    engine.resolve_until_stable()
    assert spell.zone == Zone.EXILE and spell.paradigm_player_id == "p1"
    assert spell not in player.graveyard


def test_echocasting_symposium_paradigm_offers_a_free_copy_each_first_main_phase():
    engine = _engine()
    mine = _put(engine, _bear("Mine", 3, 3))
    player = _main_phase(engine)
    spell = _symposium(engine)
    engine.cast_spell(player, spell, targets=[player, mine])
    engine.resolve_until_stable()
    assert len(_named(engine, "Mine", "p1")) == 2
    # Next turn of p1 (p2's turn in between): walk to p1's precombat main.
    turn = engine.state.internal_turn.number
    while not (engine.state.internal_turn.number > turn and engine.state.active_player.id == "p1" and engine.state.current_step == "main1"):
        if engine.state.pending_choice is not None:
            engine.rules.resolve_choice("decline")
        else:
            engine.advance_step()
        engine.resolve_until_stable()
    engine.resolve_until_stable()
    choice = engine.state.resolution_play_choice
    assert choice is not None and choice["kind"] == "play_during_resolution"
    assert spell.zone == Zone.EXILE  # the card itself stays in exile; a copy is what gets cast
    copy_obj = next(o for o in player.exile if o is not spell and o.name == "Echocasting Symposium")
    assert copy_obj.is_copy
    # RULE 702.192a: the copy is cast through the open "play during resolution" window, not by a plain cast action.
    engine.play_resolution_card(player, copy_obj, targets=[player, mine])
    engine.resolve_until_stable()
    assert len(_named(engine, "Mine", "p1")) == 3  # the original plus a token from each of the two resolutions
    assert spell.zone == Zone.EXILE  # the exiled card keeps offering copies on later turns
    assert all(o.name != "Echocasting Symposium" for o in player.graveyard)  # a resolved copy ceases to exist
    assert not any(o is not spell and o.name == "Echocasting Symposium" for o in player.exile)


def test_echocasting_symposium_paradigm_does_not_trigger_on_the_opponents_turn_or_without_resolving():
    engine = _engine()
    mine = _put(engine, _bear("Mine", 3, 3))
    _main_phase(engine)
    spell = _symposium(engine)  # never cast: not exiled by Paradigm, so no trigger at all
    spell.zone = Zone.EXILE
    engine.state.player_by_id("p1").hand.remove(spell)
    engine.state.player_by_id("p1").exile.append(spell)
    turn = engine.state.internal_turn.number
    while engine.state.internal_turn.number == turn:
        engine.advance_step()
        engine.resolve_until_stable()
    assert engine.state.resolution_play_choice is None
