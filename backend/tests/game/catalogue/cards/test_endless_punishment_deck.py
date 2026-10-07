"""Real gameplay for the Endless Punishment (Duskmourn: House of Horror Commander) catalogue entries."""

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game(players=2, library=10):
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * library) for i in range(players)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


def _card(engine, name, player="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _filler(engine, name="Filler", type_line="Creature", player="p1", mv=0, power=None, toughness=None,
            zone=Zone.BATTLEFIELD, **kw):
    card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                is_creature="Creature" in type_line, is_land="Land" in type_line,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                power=power, toughness=toughness, mana_cost_string="{%d}" % mv if mv else "",
                mana_cost={"generic": mv} if mv else {}, **kw)
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _cast(engine, card, pool, targets=None, groups=None, **kw):
    p = engine.state.player_by_id(card.controller_id)
    engine.state.current_step = "main1"
    p.mana_pool.add_many(pool)
    engine.cast_spell(p, card, targets=targets, target_groups=groups, **kw)
    engine.resolve_until_stable()


def _activate(engine, source, index=0, targets=None, player="p1", **kw):
    p = engine.state.player_by_id(player)
    engine.state.current_step = "main1"
    engine.activate_ability(p, source, index, targets=targets, **kw)
    engine.resolve_until_stable()


def _named(engine, name, player="p1"):
    return [o for o in engine.state.battlefield if o.name == name and o.controller_id == player]


def _answer(engine, pick=None, limit=12):
    """Answer pending choices: ``pick(choice)`` returns an option id (default the first option)."""
    for _ in range(limit):
        choice = engine.state.pending_choice
        if choice is None:
            return
        options = choice.get("options") or []
        answer = pick(choice) if pick is not None else None
        if answer is None:
            answer = str(options[0]["id"]) if options else "decline"
        engine.resolve_pending_choice(answer)


def _enter(engine, obj):
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
                                      instance_id=obj.instance_id, object=obj.name,
                                      object_types=sorted(obj.type_words)))
    engine.resolve_until_stable()


def _step(engine, step, player="p1"):
    engine.state.current_step = step
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step, player_id=player, controller_id=player))
    engine.resolve_until_stable()


def _put_on_battlefield(engine, name, player="p1"):
    """Cast-free entry: the card enters the battlefield and its enters trigger fires."""
    obj = _card(engine, name, player, zone=Zone.HAND)
    p = engine.state.player_by_id(player)
    p.hand[:] = [o for o in p.hand if o is not obj]
    obj.zone = Zone.BATTLEFIELD
    engine.state.add_to_battlefield(obj)
    obj.summoning_sick = False
    _enter(engine, obj)
    return obj


#: A pool that pays for any of the deck's spells — the tests below care what resolves, not how it was paid for.
RICH = {"W": 3, "U": 3, "B": 3, "R": 3, "G": 3, "C": 5}


def _attack_and_damage(engine, attackers):
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    p1 = state.player_by_id("p1")
    first = engine.legal_defenders_for(p1)[0]
    engine.declare_attackers(p1, [{"attacker": a, "defender": first} for a in attackers])
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()
    for step in ("declare_blockers", "combat_damage"):
        state.current_step = step
    engine._step_combat_damage()
    engine.resolve_until_stable()


def _gy(engine, name, player="p1"):
    return _card(engine, name, player, zone=Zone.GRAVEYARD)


def _gy_filler(engine, type_line, name="GY", power=None, toughness=None, player="p1"):
    return _filler(engine, name=name, type_line=type_line, power=power, toughness=toughness, player=player,
                   zone=Zone.GRAVEYARD)


def _walker(engine, name, loyalty, player="p1"):
    pw = _card(engine, name, player)
    pw.counters["loyalty"] = loyalty
    return pw


def _loyalty(engine, pw, cost, player="p1", **kw):
    index = next(i for i, a in enumerate(pw.activated_abilities) if getattr(getattr(a, "cost", None), "loyalty", None) == cost)
    pw.activated_loyalty_this_turn = False
    engine.state.current_step = "main1"
    engine.activate_ability(engine.state.player_by_id(player), pw, index, **kw)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


def _gy_filler(engine, type_line, name="GY", power=None, toughness=None, player="p1", mv=0):
    return _filler(engine, name=name, type_line=type_line, power=power, toughness=toughness, player=player, mv=mv,
                   zone=Zone.GRAVEYARD)


def _declare(engine, attackers, player="p1"):
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    p = state.player_by_id(player)
    first = engine.legal_defenders_for(p)[0]
    engine.declare_attackers(p, [{"attacker": a, "defender": first} for a in attackers])
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()


def test_barbflare_gremlin_doubles_mana_only_while_tapped_and_pings_the_player():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    gremlin = _card(engine, "Barbflare Gremlin")
    forest = _card(engine, "Forest")
    life = p1.life
    engine.tap_for_mana(p1, forest)
    engine.resolve_until_stable()
    assert p1.mana_pool.total() == 1 and p1.life == life  # untapped Gremlin: nothing

    forest2 = _card(engine, "Forest")
    gremlin.tapped = True
    before = p1.mana_pool.total()
    engine.tap_for_mana(p1, forest2)
    engine.resolve_until_stable()
    assert p1.mana_pool.total() == before + 2 and p1.life == life - 1


def test_florian_looks_at_x_cards_exiles_one_to_play_and_buries_the_rest():
    engine = _game(library=0)
    p1, p2 = engine.state.players
    _card(engine, "Florian, Voldaren Scion")
    bolt = _filler(engine, "Bolt", "Instant", mv=1, zone=Zone.LIBRARY)
    others = [_filler(engine, f"Junk{i}", "Sorcery", mv=1, zone=Zone.LIBRARY) for i in range(2)]
    # top of library is the last appended: Junk1, Junk0, Bolt below; X = 3 life lost
    engine.rules.lose_life(p2, 3)
    _step(engine, "main2")
    engine.resolve_pending_choice(str(others[1].instance_id))  # pick the card on top
    exiled = [o for o in p1.exile]
    assert [o.name for o in exiled] == ["Junk1"] and len(p1.library) == 2  # the other two went to the bottom
    assert p1.library[0] in (bolt, others[0]) and p1.library[1] in (bolt, others[0])


def test_florian_does_nothing_when_no_life_was_lost():
    engine = _game(library=5)
    p1 = engine.state.player_by_id("p1")
    _card(engine, "Florian, Voldaren Scion")
    _step(engine, "main2")
    assert not p1.exile and engine.state.pending_choice is None


def test_rakdos_needs_an_opponent_to_have_lost_life_and_discounts_creature_spells_by_that_life():
    engine = _game()
    p1, p2 = engine.state.players
    rakdos = _card(engine, "Rakdos, Lord of Riots", zone=Zone.HAND)
    bear = _filler(engine, "Bear", "Creature — Bear", mv=3, power=2, toughness=2, zone=Zone.HAND)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"B": 2, "R": 2})
    assert not engine.can_cast(p1, rakdos)  # no opponent lost life yet
    engine.rules.lose_life(p2, 2)
    assert engine.can_cast(p1, rakdos)



def test_rakdos_discounts_creature_spells_one_per_life_opponents_lost():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Rakdos, Lord of Riots")
    bear = _filler(engine, "Bear", "Creature — Bear", mv=3, power=2, toughness=2, zone=Zone.HAND)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 1})
    assert not engine.can_cast(p1, bear)
    engine.rules.lose_life(p2, 2)
    assert engine.can_cast(p1, bear)  # {3} − 2 = {1}


def test_theater_of_horrors_exiles_each_upkeep_and_lets_you_cast_from_exile_after_an_opponent_lost_life():
    engine = _game(library=0)
    p1, p2 = engine.state.players
    theater = _card(engine, "Theater of Horrors")
    bolt = _filler(engine, "Bolt", "Instant", mv=1, zone=Zone.LIBRARY)
    _step(engine, "upkeep")
    assert bolt.zone == Zone.EXILE and bolt.instance_id in theater.exiled_with_ids
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 1})
    assert not engine.can_cast(p1, bolt)  # no opponent has lost life yet
    engine.rules.lose_life(p2, 1)
    assert engine.can_cast(p1, bolt)


def test_theater_of_horrors_pings_an_opponent_for_four_mana():
    engine = _game()
    p1, p2 = engine.state.players
    theater = _card(engine, "Theater of Horrors")
    p1.mana_pool.add_many({"R": 1, "C": 3})
    engine.state.current_step = "main1"
    index = next(i for i, a in enumerate(theater.activated_abilities) if str(getattr(a.cost, "mana", "")))
    life = p2.life
    engine.activate_ability(p1, theater, index, targets=[p2])
    engine.resolve_until_stable()
    assert p2.life == life - 1


def test_valgavoth_grows_and_draws_only_on_the_first_life_loss_during_an_opponents_own_turn():
    engine = _game(library=10)
    p1, p2 = engine.state.players
    valgavoth = _card(engine, "Valgavoth, Harrower of Souls")
    # My own turn (p1 active): the opponent losing life does not count.
    engine.rules.lose_life(p2, 1)
    engine.resolve_until_stable()
    assert valgavoth.counters.get("+1/+1", 0) == 0

    engine.state.active_player_index = 1  # an opponent's turn
    engine.rules.lose_life(p2, 1)
    engine.resolve_until_stable()
    assert valgavoth.counters.get("+1/+1") == 1 and len(p1.hand) == 1
    engine.rules.lose_life(p2, 1)  # not the first loss this turn
    engine.resolve_until_stable()
    assert valgavoth.counters.get("+1/+1") == 1 and len(p1.hand) == 1


def test_kederekt_parasite_pings_a_drawing_opponent_only_while_you_control_a_red_permanent():
    engine = _game(library=10)
    p1, p2 = engine.state.players
    _card(engine, "Kederekt Parasite")
    life = p2.life
    engine.rules.draw(p2, 1)
    engine.resolve_until_stable()
    assert p2.life == life and engine.state.pending_choice is None  # no red permanent yet
    _filler(engine, "Red Thing", "Creature — Goblin", power=1, toughness=1, color_identity=["R"])
    engine.rules.draw(p2, 1)
    engine.resolve_until_stable()
    engine.resolve_pending_choice("do")  # "you may have this creature deal 1 damage"
    engine.resolve_until_stable()
    assert p2.life == life - 1


def test_the_lord_of_pain_blocks_opponents_life_gain_and_burns_another_player_for_the_first_spell():
    engine = _game(players=3)
    p1, p2, p3 = engine.state.players
    _card(engine, "The Lord of Pain")
    p2.life = 10
    engine.rules.gain_life(p2, 5)
    assert p2.life == 10  # your opponents can't gain life
    bear = _filler(engine, "Bear", "Creature — Bear", mv=3, power=1, toughness=1, zone=Zone.HAND)
    life = p3.life
    _cast(engine, bear, {"C": 3})
    engine.resolve_pending_choice(str(p3.id)) if engine.state.pending_choice else None
    engine.resolve_until_stable()
    assert p3.life == life - 3 and p1.life == 20  # another player than the caster (p1)


def test_vial_smasher_burns_a_random_opponent_for_the_first_spell_each_turn_only():
    engine = _game(players=3)
    p1, p2, p3 = engine.state.players
    _card(engine, "Vial Smasher the Fierce")
    first = _filler(engine, "First", "Creature — Bear", mv=2, power=1, toughness=1, zone=Zone.HAND)
    second = _filler(engine, "Second", "Creature — Bear", mv=2, power=1, toughness=1, zone=Zone.HAND)
    _cast(engine, first, {"C": 2})
    assert p2.life + p3.life == 40 - 2
    _cast(engine, second, {"C": 2})
    assert p2.life + p3.life == 40 - 2


def test_vial_smasher_may_hit_a_planeswalker_of_the_random_opponent():
    # "…damage equal to that spell's mana value to that player **or a planeswalker that player controls**"
    engine = _game(players=2)
    p1, p2 = engine.state.players
    _card(engine, "Vial Smasher the Fierce")
    jace = _filler(engine, "Jace", "Legendary Planeswalker — Jace", player="p2", loyalty=5)
    spell = _filler(engine, "Three", "Creature — Bear", mv=3, power=1, toughness=1, zone=Zone.HAND)
    _cast(engine, spell, {"C": 3})
    pending = engine.state.pending_choice
    assert pending is not None and pending["kind"] == "damage_recipient"
    assert {o["id"] for o in pending["options"]} == {"player:p2", f"planeswalker:{jace.instance_id}"}
    engine.resolve_pending_choice(f"planeswalker:{jace.instance_id}")
    engine.resolve_until_stable()
    assert jace.loyalty == 2 and p2.life == 20  # RULE 120.3c: loyalty counters, not life


def test_syr_konrad_pings_for_other_deaths_non_battlefield_creature_cards_and_graveyard_exits():
    engine = _game(library=10)
    p1, p2 = engine.state.players
    konrad = _card(engine, "Syr Konrad, the Grim")
    life = p2.life
    victim = _filler(engine, "Victim", "Creature — Bear", power=1, toughness=1)
    engine.state.resync_graveyard_watch()  # a real game tracks every card's zone from the start
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert p2.life == life - 1  # another creature died (a battlefield → graveyard move is not the second head)

    milled = _filler(engine, "Milled", "Creature — Bear", power=1, toughness=1, zone=Zone.LIBRARY)
    engine.rules.mill(p1, 1)
    engine.resolve_until_stable()
    assert milled.zone == Zone.GRAVEYARD and p2.life == life - 2  # a creature card put into a graveyard from the library

    engine.rules.destroy(konrad)  # Syr Konrad himself dying is not "another creature"
    engine.resolve_until_stable()
    assert p2.life == life - 2

    p1.mana_pool.add_many({"B": 1, "C": 1})
    konrad2 = _card(engine, "Syr Konrad, the Grim")
    engine.state.current_step = "main1"
    index = next(i for i, a in enumerate(konrad2.activated_abilities) if str(getattr(a.cost, "mana", "")))
    before = (len(p1.graveyard), len(p2.graveyard))
    engine.activate_ability(p1, konrad2, index)
    engine.resolve_until_stable()
    assert (len(p1.graveyard), len(p2.graveyard)) == (before[0] + 1, before[1] + 1)


def test_mask_of_griselbrand_grants_flying_lifelink_and_pays_life_equal_to_power_to_draw_that_many():
    engine = _game(library=10)
    p1 = engine.state.player_by_id("p1")
    mask = _card(engine, "Mask of Griselbrand")
    bear = _filler(engine, "Bear", "Creature — Bear", power=3, toughness=3)
    mask.attached_to = bear.instance_id
    engine.recompute_continuous_effects()
    assert "flying" in bear.granted_keywords and "lifelink" in bear.granted_keywords
    life = p1.life
    engine.rules.destroy(bear)
    engine.resolve_until_stable()
    engine.resolve_pending_choice("pay")
    engine.resolve_until_stable()
    assert p1.life == life - 3 and len(p1.hand) == 3


def test_massacre_girl_chains_minus_one_minus_one_through_every_death_this_turn():
    engine = _game()
    a = _filler(engine, "A", "Creature — Bear", power=3, toughness=1)  # dies to the first -1/-1
    b = _filler(engine, "B", "Creature — Bear", power=3, toughness=2)  # dies to the second
    c = _filler(engine, "C", "Creature — Bear", power=3, toughness=5)  # survives three shrinks at 2 toughness
    girl = _card(engine, "Massacre Girl", zone=Zone.HAND)
    _cast(engine, girl, {"B": 2, "C": 3})
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert a.zone == Zone.GRAVEYARD and b.zone == Zone.GRAVEYARD
    assert c in engine.state.battlefield and c.toughness == 2  # -1/-1 for the ETB, a, and b
    assert girl in engine.state.battlefield and girl.toughness == 4  # "other than Massacre Girl"


def test_kardur_goads_opposing_creatures_and_drains_when_an_attacker_dies():
    engine = _game()
    p1, p2 = engine.state.players
    theirs = _filler(engine, "Theirs", "Creature — Bear", power=2, toughness=2, player="p2")
    _put_on_battlefield(engine, "Kardur, Doomscourge")
    assert theirs.goaded_by

    attacker = _filler(engine, "Attacker", "Creature — Bear", power=1, toughness=1, player="p2")
    attacker.attacking = True
    life1, life2 = p1.life, p2.life
    engine.rules.destroy(attacker)
    engine.resolve_until_stable()
    assert p1.life == life1 + 1 and p2.life == life2 - 1


def test_mogis_pings_an_opponent_each_upkeep_unless_they_sacrifice_a_creature():
    engine = _game()
    p1, p2 = engine.state.players
    mogis = _card(engine, "Mogis, God of Slaughter")
    engine.recompute_continuous_effects()
    assert not mogis.is_creature  # devotion < 7
    engine.state.active_player_index = 1
    life = p2.life
    _step(engine, "upkeep", player="p2")
    if engine.state.pending_choice:
        engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert p2.life == life - 2

    fodder = _filler(engine, "Fodder", "Creature — Bear", power=1, toughness=1, player="p2")
    _step(engine, "upkeep", player="p2")
    engine.resolve_pending_choice("pay")
    _answer(engine)
    assert p2.life == life - 2 and fodder.zone == Zone.GRAVEYARD  # they sacrificed instead


def test_persistent_constrictor_drains_and_shrinks_a_creature_each_opponent_upkeep():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Persistent Constrictor")
    victim = _filler(engine, "Victim", "Creature — Bear", power=2, toughness=2, player="p2")
    engine.state.active_player_index = 1
    life = p2.life
    _step(engine, "upkeep", player="p2")
    _answer(engine, pick=lambda c: str(victim.instance_id) if any(str(o["id"]) == str(victim.instance_id) for o in c["options"]) else None)
    assert p2.life == life - 1 and victim.counters.get("-1/-1") == 1


def test_star_athlete_makes_the_controller_sacrifice_the_permanent_or_take_five():
    engine = _game()
    p1, p2 = engine.state.players
    athlete = _card(engine, "Star Athlete")
    rock = _filler(engine, "Rock", "Artifact", player="p2")
    life = p2.life
    _declare(engine, [athlete])
    engine.resolve_pending_choice(str(rock.instance_id))  # the attack trigger's target
    assert engine.state.pending_choice["kind"] == "composite_optional" and engine.state.pending_choice["player_id"] == "p2"
    engine.resolve_pending_choice("decline")  # p2 refuses to sacrifice
    engine.resolve_until_stable()
    assert rock.zone == Zone.BATTLEFIELD and p2.life == life - 5

    athlete.attacking = False
    athlete.tapped = False
    _declare(engine, [athlete])
    engine.resolve_pending_choice(str(rock.instance_id))
    engine.resolve_pending_choice("yes")  # this time they sacrifice it
    engine.resolve_until_stable()
    assert rock.zone == Zone.GRAVEYARD and p2.life == life - 5


def test_enchanters_bane_deals_the_enchantments_mana_value_unless_its_controller_sacrifices_it():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Enchanter's Bane")
    aura = _filler(engine, "Big Aura", "Enchantment", mv=4, player="p2")
    life = p2.life
    _step(engine, "end")
    if engine.state.pending_choice["kind"] != "composite_optional":
        engine.resolve_pending_choice(str(aura.instance_id))
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert p2.life == life - 4 and aura.zone == Zone.BATTLEFIELD


def test_grab_the_prize_burns_each_opponent_only_when_the_discarded_card_was_not_a_land():
    engine = _game(library=10)
    p1, p2 = engine.state.players
    spell = _card(engine, "Grab the Prize", zone=Zone.HAND)
    land = _filler(engine, "Island", "Basic Land — Island", zone=Zone.HAND)
    _cast(engine, spell, {"R": 2}, discard_choices=[land.instance_id])
    assert land.zone == Zone.GRAVEYARD and p2.life == 20  # discarded a land: no damage

    spell2 = _card(engine, "Grab the Prize", zone=Zone.HAND)
    junk = _filler(engine, "Junk", "Sorcery", zone=Zone.HAND)
    _cast(engine, spell2, {"R": 2}, discard_choices=[junk.instance_id])
    assert p2.life == 18


def test_fear_of_burning_alive_burns_on_enter_and_hits_a_creature_with_delirium():
    engine = _game()
    p1, p2 = engine.state.players
    fear = _card(engine, "Fear of Burning Alive", zone=Zone.HAND)
    _cast(engine, fear, {"R": 6})
    assert p2.life == 16
    for tl, n in (("Land", "L"), ("Instant", "I"), ("Sorcery", "S"), ("Creature — Elf", "E")):
        _gy_filler(engine, tl, n, power=1 if "Creature" in tl else None, toughness=1 if "Creature" in tl else None)
    victim = _filler(engine, "Victim", "Creature — Bear", power=2, toughness=9, player="p2")
    bolt = _filler(engine, "Source", "Creature — Goblin", power=1, toughness=1)
    engine.rules.deal_damage(p2, 3, source=bolt, combat=False)
    engine.resolve_until_stable()
    _answer(engine)
    assert victim.damage_marked == 3


def test_sadistic_shell_game_has_every_player_pick_a_creature_the_caster_does_not_control():
    engine = _game(players=3)
    p1, p2, p3 = engine.state.players
    mine = _filler(engine, "Mine", "Creature — Bear", power=2, toughness=2)
    a = _filler(engine, "A", "Creature — Bear", power=2, toughness=2, player="p2")
    b = _filler(engine, "B", "Creature — Bear", power=2, toughness=2, player="p3")
    c = _filler(engine, "C", "Creature — Bear", power=2, toughness=2, player="p3")
    spell = _card(engine, "Sadistic Shell Game", zone=Zone.HAND)
    _cast(engine, spell, {"B": 5})
    order = []
    for expected, pick in (("p2", a), ("p3", b), ("p1", c)):  # next opponent first, the caster last
        choice = engine.state.pending_choice
        assert choice and choice["player_id"] == expected
        assert all(str(mine.instance_id) != str(o["id"]) for o in choice["options"])  # never the caster's own creatures
        engine.resolve_pending_choice(str(pick.instance_id))
    engine.resolve_until_stable()
    assert all(o.zone == Zone.GRAVEYARD for o in (a, b, c)) and mine in engine.state.battlefield


def test_spiked_corridor_makes_three_devils_that_ping_any_target_when_they_die():
    engine = _game()
    p1, p2 = engine.state.players
    room = _card(engine, "Spiked Corridor // Torture Pit", zone=Zone.HAND)
    _cast(engine, room, {"R": 4})
    devils = [o for o in engine.state.battlefield if o.name == "Devil" and o.is_token]
    assert len(devils) == 3 and all((d.power, d.toughness) == (1, 1) for d in devils)
    life = p2.life
    engine.rules.destroy(devils[0])
    engine.resolve_until_stable()
    engine.resolve_pending_choice(str(p2.id)) if engine.state.pending_choice else None
    engine.resolve_until_stable()
    assert p2.life == life - 1


def test_suspended_sentence_destroys_drains_and_exiles_itself_with_time_counters_to_come_back():
    engine = _game()
    p1, p2 = engine.state.players
    spell = _card(engine, "Suspended Sentence", zone=Zone.HAND)
    victim = _filler(engine, "Victim", "Creature — Bear", power=2, toughness=2, player="p2")
    life = p2.life
    _cast(engine, spell, {"B": 2, "C": 2}, targets=[victim])
    assert victim.zone == Zone.GRAVEYARD and p2.life == life - 3
    assert spell.zone == Zone.EXILE and spell.counters.get("time") == 3
    # Its own Suspend takes over: each of your upkeeps removes a time counter.
    for expected in (2, 1):
        _step(engine, "upkeep")
        assert spell.counters.get("time") == expected
