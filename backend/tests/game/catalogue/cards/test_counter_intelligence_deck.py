"""Hand-authored cards of the saved "Counter Intelligence" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import battlefield_object


def _game(*deck_names):
    cards = [CardDatabase(DB_PATH).get_card(name) for name in deck_names]
    engine = GameEngine.new_game([("p1", "A", cards), ("p2", "B", [])], starting_hand=len(cards), starting_life=20)
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.player_by_id("p1")
    for i in range(5):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"Lib {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    return engine, p1


def _dispatch(artifacts):
    engine, p1 = _game("Dispatch")
    for i in range(artifacts):
        battlefield_object(engine, "p1", f"Trinket {i}", "Artifact")
    victim = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    p1.mana_pool.add_many({"W": 1})
    engine.cast_spell(p1, p1.hand[0], targets=[victim])
    engine.resolve_until_stable()
    return engine, victim


def test_dispatch_taps_and_with_metalcraft_exiles_the_creature():
    engine, victim = _dispatch(artifacts=3)
    assert victim.zone == Zone.EXILE

    engine, victim = _dispatch(artifacts=2)
    assert victim in engine.state.battlefield and victim.tapped  # tapped only, no metalcraft


def test_soul_guide_lantern_exiles_only_opponents_graveyards():
    engine, p1 = _game()
    p2 = engine.state.player_by_id("p2")
    lantern = battlefield_object(engine, "p1", "Soul-Guide Lantern", "Artifact")
    bind_from_catalogue(lantern)
    mine = GameObject(Card(id="m", name="Mine", type_line="Instant"), owner_id="p1", zone=Zone.GRAVEYARD)
    theirs = GameObject(Card(id="t", name="Theirs", type_line="Instant"), owner_id="p2", zone=Zone.GRAVEYARD)
    p1.graveyard.append(mine)
    p2.graveyard.append(theirs)
    ability = next(i for i, a in enumerate(lantern.activated_abilities) if a.cost.raw == "{T}, Sacrifice ~")
    engine.activate_ability(p1, lantern, ability)
    engine.resolve_until_stable()
    assert theirs.zone == Zone.EXILE and not p2.graveyard
    assert mine in p1.graveyard
    assert lantern.zone != Zone.BATTLEFIELD  # sacrificed as a cost


def test_threefold_thunderhulk_makes_gnomes_equal_to_power_on_enter_and_attack():
    engine, p1 = _game("Threefold Thunderhulk")
    hulk = p1.hand[0]
    p1.mana_pool.add_many({"C": 8})
    engine.cast_spell(p1, hulk)
    engine.resolve_until_stable()
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert hulk.zone == Zone.BATTLEFIELD and hulk.counters.get("+1/+1") == 3

    def gnomes():
        return [o for o in engine.state.battlefield if o.name == "Gnome"]

    assert len(gnomes()) == hulk.power
    before = len(gnomes())
    hulk.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": hulk, "defender": engine.legal_defenders_for(p1)[0]}])
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert len(gnomes()) == before + hulk.power


def test_darksteel_reactor_wins_when_the_twentieth_charge_counter_lands():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, p1 = _game()
    reactor = battlefield_object(engine, "p1", "Darksteel Reactor", "Artifact")
    bind_from_catalogue(reactor)

    def upkeep():
        engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning", player_id="p1"))
        engine.rules.put_triggers_on_stack()
        while engine.state.pending_choice:  # "you may" — accept
            engine.resolve_pending_choice("do")
        engine.resolve_until_stable()

    reactor.counters["charge"] = 18
    upkeep()
    assert reactor.counters["charge"] == 19 and not engine.state.game_over
    upkeep()
    assert reactor.counters["charge"] == 20
    assert engine.state.game_over and engine.state.winner_id == "p1"


def test_deepglow_skate_doubles_every_counter_kind_on_each_chosen_permanent():
    engine, p1 = _game("Deepglow Skate")
    artifact = battlefield_object(engine, "p1", "Charged Thing", "Artifact")
    bear = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=1, toughness=1)
    untouched = battlefield_object(engine, "p1", "Other Thing", "Artifact")
    artifact.counters["charge"] = 2
    bear.counters.update({"+1/+1": 3, "stun": 1})
    untouched.counters["charge"] = 5
    p1.mana_pool.add_many({"U": 5})
    engine.cast_spell(p1, p1.hand[0])
    engine.resolve_until_stable()
    engine.rules.put_triggers_on_stack()
    for object_id in (str(artifact.instance_id), str(bear.instance_id)):
        assert engine.state.pending_choice["kind"] == "trigger_target_multi"
        engine.resolve_pending_choice(object_id)
    engine.resolve_pending_choice("stop")  # "any number": the player ends the list
    engine.resolve_until_stable()
    assert artifact.counters == {"charge": 4}
    assert bear.counters == {"+1/+1": 6, "stun": 2}  # every kind, opposing permanents included
    assert untouched.counters == {"charge": 5}  # not chosen


def test_empowered_autogenerator_enters_tapped_and_adds_mana_equal_to_its_counters():
    engine, p1 = _game("Empowered Autogenerator")
    gen = p1.hand[0]
    p1.mana_pool.add_many({"C": 4})
    engine.cast_spell(p1, gen)
    engine.resolve_until_stable()
    assert gen.zone == Zone.BATTLEFIELD and gen.tapped  # enters tapped

    def tap_for_mana():
        gen.tapped = False
        p1.mana_pool.set_amount("W", 0)
        engine.activate_ability(p1, gen, 0)
        engine.resolve_until_stable()
        while engine.state.pending_choice:  # "any one color": every mana is the same chosen colour
            engine.resolve_pending_choice("W")
        return p1.mana_pool.to_dict()["W"]

    assert tap_for_mana() == 1 and gen.counters["charge"] == 1
    assert tap_for_mana() == 2 and gen.counters["charge"] == 2


def test_cyberdrive_awakener_animates_noncreature_artifacts_until_end_of_turn():
    engine, p1 = _game("Cyberdrive Awakener")
    rock = battlefield_object(engine, "p1", "Mind Stone", "Artifact")
    golem = battlefield_object(engine, "p1", "Golem", "Artifact Creature — Golem", is_creature=True, power=1, toughness=1)
    theirs = battlefield_object(engine, "p2", "Their Rock", "Artifact")
    awakener = p1.hand[0]
    p1.mana_pool.add_many({"U": 1, "C": 5})
    engine.cast_spell(p1, awakener)
    engine.resolve_until_stable()
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert rock.is_creature and (rock.power, rock.toughness) == (4, 4)
    assert not theirs.is_creature  # only artifacts *you* control
    assert (golem.power, golem.toughness) == (1, 1)  # already a creature: not set to 4/4
    assert "flying" in rock.granted_keywords and "flying" in golem.granted_keywords  # other artifact creatures
    late = battlefield_object(engine, "p1", "Late Rock", "Artifact")
    engine.recompute_continuous_effects()
    assert not late.is_creature  # RULE 611.2c: the group was fixed on resolution

    engine._step_cleanup()
    engine.recompute_continuous_effects()
    assert not rock.is_creature


def _titan_entering(pick_ids):
    engine, p1 = _game("Depthshaker Titan")
    rock = battlefield_object(engine, "p1", "Mind Stone", "Artifact")
    other = battlefield_object(engine, "p1", "Sol Ring", "Artifact")
    theirs = battlefield_object(engine, "p2", "Their Rock", "Artifact")
    p1.mana_pool.add_many({"R": 2, "C": 5})
    engine.cast_spell(p1, p1.hand[0])
    engine.resolve_until_stable()
    engine.rules.put_triggers_on_stack()
    options = {o["label"] for o in engine.state.pending_choice["options"]}
    for name in pick_ids:
        engine.resolve_pending_choice(str({"rock": rock, "other": other}[name].instance_id))
    if engine.state.pending_choice:
        engine.resolve_pending_choice("stop")
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    return engine, p1, rock, other, theirs, options


def test_depthshaker_titan_animates_chosen_artifacts_and_sacrifices_them_at_end_step():
    engine, p1, rock, other, theirs, options = _titan_entering(["rock"])
    assert "Their Rock" not in options  # "you control"
    assert rock.is_creature and (rock.power, rock.toughness) == (3, 3)
    assert not other.is_creature  # not chosen
    titan = next(o for o in engine.state.battlefield if o.name == "Depthshaker Titan")
    assert {"trample", "haste"} <= set(rock.granted_keywords)  # the lord covers every artifact creature
    assert {"trample", "haste"} <= set(titan.granted_keywords)

    engine._fire_delayed_triggers("end")
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert rock.zone == Zone.GRAVEYARD and other.zone == Zone.BATTLEFIELD
    assert titan.zone == Zone.BATTLEFIELD


def test_depthshaker_titan_choosing_nothing_never_sacrifices_itself():
    engine, p1, rock, other, theirs, options = _titan_entering([])
    titan = next(o for o in engine.state.battlefield if o.name == "Depthshaker Titan")
    engine._fire_delayed_triggers("end")
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert titan.zone == Zone.BATTLEFIELD and rock.zone == Zone.BATTLEFIELD


def test_emry_lets_you_cast_only_the_chosen_artifact_card_from_the_graveyard():
    engine, p1 = _game()
    emry = battlefield_object(
        engine, "p1", "Emry, Lurker of the Loch", "Legendary Creature — Merfolk Wizard",
        is_creature=True, power=1, toughness=2,
    )
    bind_from_catalogue(emry)
    emry.summoning_sick = False

    def grave_card(name, type_line, **kw):
        obj = GameObject(
            Card(id=name, name=name, type_line=type_line, mana_cost_string="{1}", converted_mana_cost=1, **kw),
            owner_id="p1", zone=Zone.GRAVEYARD,
        )
        p1.graveyard.append(obj)
        return obj

    rock = grave_card("Grave Rock", "Artifact")
    other_rock = grave_card("Other Rock", "Artifact")
    bear = grave_card("Grave Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)

    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    pool = legal_targets(engine.state, "p1", TargetSpec(kind="graveyard_artifact"), source=emry)
    assert {o["name"] for o in pool} == {"Grave Rock", "Other Rock"}  # artifact cards only
    engine.activate_ability(p1, emry, 0, targets=[rock])
    engine.resolve_until_stable()

    def castable(obj):
        return any(
            a.get("instance_id") == obj.instance_id and a.get("type") == "cast_spell"
            for a in engine.legal_actions(p1)
        )

    p1.mana_pool.add_many({"C": 3})
    assert castable(rock) and not castable(other_rock) and not castable(bear)
    engine.cast_spell(p1, rock)
    engine.resolve_until_stable()
    assert rock.zone == Zone.BATTLEFIELD


def test_mycosynth_gardens_becomes_a_copy_of_a_nontoken_artifact_with_mana_value_x():
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    engine, p1 = _game()
    gardens = battlefield_object(engine, "p1", "The Mycosynth Gardens", "Land — Sphere", is_land=True)
    bind_from_catalogue(gardens)
    gardens.summoning_sick = False
    three = battlefield_object(engine, "p1", "Three Rock", "Artifact", mana_cost_string="{3}", converted_mana_cost=3)
    battlefield_object(engine, "p1", "Two Rock", "Artifact", mana_cost_string="{2}", converted_mana_cost=2)
    battlefield_object(engine, "p2", "Their Three", "Artifact", mana_cost_string="{3}", converted_mana_cost=3)
    token = battlefield_object(engine, "p1", "Gold", "Artifact — Gold", mana_cost_string="", converted_mana_cost=3)
    token.is_token = True

    gardens.x_paid = 3  # the announced X, as `activate_ability` stamps it
    pool = legal_targets(engine.state, "p1", TargetSpec(kind="nontoken_artifact_you_control", exact_mana_value="x"), source=gardens)
    assert {o["name"] for o in pool} == {"Three Rock"}  # MV 3, nontoken, yours

    p1.mana_pool.add_many({"C": 3})
    engine.activate_ability(p1, gardens, 0, targets=[three], x=3)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert gardens.name == "Three Rock" and gardens.card.is_artifact and not gardens.is_land
