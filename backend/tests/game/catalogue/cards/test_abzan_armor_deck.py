"""Real gameplay for the Abzan Armor (Tarkir: Dragonstorm Commander) catalogue entries."""

import pytest

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
                power=power, toughness=toughness, mana_cost_string="{%d}" % mv if mv else "", **kw)
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _cast(engine, card, pool, targets=None, **kw):
    p = engine.state.player_by_id(card.controller_id)
    engine.state.current_step = "main1"
    p.mana_pool.add_many(pool)
    engine.cast_spell(p, card, targets=targets, target_groups=None, **kw)
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


def _attack(engine, attackers, defender=None):
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    first = defender or engine.legal_defenders_for(state.active_player)[0]
    engine.declare_attackers(state.active_player, [{"attacker": a, "defender": first} for a in attackers])
    engine.resolve_until_stable()


def test_assault_formation_makes_your_creatures_deal_toughness_damage():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Assault Formation")
    wall = _filler(engine, "Stout", "Creature — Wall", power=0, toughness=5, keywords=["Defender"])
    continuous.recompute(engine.state)
    assert combat.combat_restrictions(wall, "damage_uses_toughness")


def test_assault_formation_lets_a_defender_attack_for_g():
    engine = _game()
    p1, p2 = engine.state.players
    formation = _card(engine, "Assault Formation")
    wall = _filler(engine, "Stout", "Creature — Wall", power=0, toughness=5, keywords=["Defender"])
    engine.state.current_step = "main1"
    assert not engine._can_attack(p1, wall, p2)
    p1.mana_pool.add("G", 1)
    _activate(engine, formation, 0, targets=[wall])
    assert engine._can_attack(p1, wall, p2)


def test_baldin_pumps_toughness_by_the_cards_in_your_hand():
    engine = _game()
    p1, _ = engine.state.players
    baldin = _card(engine, "Baldin, Century Herdmaster")
    ally = _filler(engine, "Ally", power=1, toughness=1)
    for i in range(3):
        _filler(engine, f"Card{i}", "Sorcery", zone=Zone.HAND)
    _attack(engine, [baldin])
    _answer(engine, pick=lambda c: str(ally.instance_id) if str(ally.instance_id) in [str(o["id"]) for o in c.get("options", [])] else None)
    continuous.recompute(engine.state)
    assert ally.toughness == 1 + 3 and ally.power == 1


def test_betor_adds_counters_for_life_gained_and_returns_a_creature_for_life_lost():
    engine = _game()
    p1, _ = engine.state.players
    betor = _card(engine, "Betor, Ancestor's Voice")
    ally = _filler(engine, "Ally", power=1, toughness=1)
    fallen = _filler(engine, "Fallen", "Creature — Elf", mv=3, power=2, toughness=2, zone=Zone.GRAVEYARD)
    toobig = _filler(engine, "Too Big", "Creature — Elf", mv=5, power=2, toughness=2, zone=Zone.GRAVEYARD)
    engine.rules.gain_life(p1, 3)
    engine.rules.lose_life(p1, 3)
    engine.resolve_until_stable()
    engine.state.current_step = "end"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    for _ in range(8):
        choice = engine.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice.get("options", [])]
        engine.resolve_pending_choice(next((i for i in (str(ally.instance_id), str(fallen.instance_id)) if i in ids), ids[0] if ids else "decline"))
    assert ally.counters.get("+1/+1") == 3
    assert fallen.zone == Zone.BATTLEFIELD and toobig.zone == Zone.GRAVEYARD


def test_canopy_gargantuan_gives_each_other_creature_counters_equal_to_its_own_toughness():
    engine = _game()
    canopy = _card(engine, "Canopy Gargantuan")
    small = _filler(engine, "Small", power=1, toughness=2)
    big = _filler(engine, "Big", power=1, toughness=5)
    engine.state.current_step = "upkeep"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    assert (small.counters.get("+1/+1"), big.counters.get("+1/+1")) == (2, 5)
    assert not canopy.counters.get("+1/+1")


def test_colfenors_urn_exiles_big_creatures_and_returns_them_on_the_third():
    engine = _game()
    p1, _ = engine.state.players
    urn = _card(engine, "Colfenor's Urn")
    victims = [_filler(engine, f"Big{i}", "Creature — Beast", power=4, toughness=4) for i in range(3)]
    small = _filler(engine, "Small", power=1, toughness=1)
    for victim in victims[:2] + [small]:
        engine.rules.destroy(victim)
        engine.resolve_until_stable()
        _answer(engine, pick=lambda c: next((str(o["id"]) for o in c["options"] if o["id"] != "decline"), "decline"))
    assert len(urn.exiled_with_ids) == 2 and small in p1.graveyard
    engine.state.current_step = "end"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    assert urn.zone == Zone.BATTLEFIELD  # only two so far
    engine.rules.destroy(victims[2])
    engine.resolve_until_stable()
    _answer(engine, pick=lambda c: next((str(o["id"]) for o in c["options"] if o["id"] != "decline"), "decline"))
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    assert urn.zone != Zone.BATTLEFIELD
    assert all(v.zone == Zone.BATTLEFIELD for v in victims)


def test_expel_the_interlopers_destroys_creatures_with_power_at_least_the_chosen_number():
    engine = _game()
    p1, p2 = engine.state.players
    big = _filler(engine, "Big", power=5, toughness=5)
    mid = _filler(engine, "Mid", power=3, toughness=3, player="p2")
    small = _filler(engine, "Small", power=1, toughness=1, player="p2")
    spell = _card(engine, "Expel the Interlopers", zone=Zone.HAND)
    _cast(engine, spell, {"W": 2, "C": 3})
    assert engine.state.pending_choice["kind"] == "choose_number_resolve"
    engine.resolve_pending_choice("3")
    assert big.zone == Zone.GRAVEYARD and mid.zone == Zone.GRAVEYARD
    assert small.zone == Zone.BATTLEFIELD


def test_felothar_lets_creatures_attack_past_defender_and_loots_by_the_sacrificed_creature():
    engine = _game(library=12)
    p1, p2 = engine.state.players
    felothar = _card(engine, "Felothar the Steadfast")
    wall = _filler(engine, "Stout", "Creature — Wall", power=0, toughness=5, keywords=["Defender"])
    victim = _filler(engine, "Victim", power=2, toughness=3)
    continuous.recompute(engine.state)
    engine.state.current_step = "main1"
    assert engine._can_attack(p1, wall, p2)
    for i in range(3):
        _filler(engine, f"Hand{i}", "Sorcery", zone=Zone.HAND)
    hand_before = len(p1.hand)
    p1.mana_pool.add_many({"C": 3})
    engine.activate_ability(p1, felothar, 0, sacrifice_choice=victim.instance_id)
    engine.resolve_until_stable()
    _answer(engine, limit=4)
    assert victim.zone == Zone.GRAVEYARD
    assert len(p1.hand) == hand_before + 3 - 2  # drew toughness (3), discarded power (2)


def test_jaws_of_defeat_drains_by_the_difference_between_power_and_toughness():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Jaws of Defeat")
    mover = _filler(engine, "Lopsided", power=5, toughness=2, zone=Zone.HAND)
    mover.zone = Zone.BATTLEFIELD
    p1.hand[:] = [o for o in p1.hand if o is not mover]
    engine.state.add_to_battlefield(mover)
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id="p1", instance_id=mover.instance_id,
                                      object=mover.name, object_types=sorted(mover.type_words)))
    engine.resolve_until_stable()
    _answer(engine, pick=lambda c: "p2")
    assert p2.life == 20 - 3


def test_reunion_of_the_house_returns_creatures_up_to_total_power_ten_and_exiles_itself():
    engine = _game()
    p1, _ = engine.state.players
    a = _filler(engine, "A", "Creature — Elf", power=6, toughness=1, zone=Zone.GRAVEYARD)
    b = _filler(engine, "B", "Creature — Elf", power=4, toughness=1, zone=Zone.GRAVEYARD)
    c = _filler(engine, "C", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    spell = _card(engine, "Reunion of the House", zone=Zone.HAND)
    _cast(engine, spell, {"W": 2, "C": 5})
    _answer(engine, pick=lambda ch: next((str(o["id"]) for o in ch["options"] if o["id"] == str(a.instance_id)), None))
    _answer(engine, pick=lambda ch: next((str(o["id"]) for o in ch["options"] if o["id"] == str(b.instance_id)), None))
    _answer(engine, pick=lambda ch: "decline")
    assert a.zone == Zone.BATTLEFIELD and b.zone == Zone.BATTLEFIELD
    assert c.zone == Zone.GRAVEYARD  # 6 + 4 + 1 would be 11
    assert spell.zone == Zone.EXILE


def test_sidar_kondo_stops_opponents_creatures_without_flying_or_reach_blocking_small_creatures():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Sidar Kondo of Jamuraa")
    small = _filler(engine, "Small", power=2, toughness=2)
    big = _filler(engine, "Big", power=3, toughness=3)
    plain = _filler(engine, "Plain", power=1, toughness=1, player="p2")
    flyer = _filler(engine, "Flyer", "Creature — Bird", power=1, toughness=1, player="p2", keywords=["Flying"])
    continuous.recompute(engine.state)
    _attack(engine, [small, big])
    assert not engine.can_block(p2, plain, small)
    assert engine.can_block(p2, plain, big)
    assert engine.can_block(p2, flyer, small)


def test_slaughter_the_strong_keeps_creatures_within_the_power_budget():
    engine = _game()
    p1, p2 = engine.state.players
    keep = _filler(engine, "Keep", power=3, toughness=3)
    lose = _filler(engine, "Lose", power=2, toughness=2)
    theirs = _filler(engine, "Theirs", power=1, toughness=1, player="p2")
    spell = _card(engine, "Slaughter the Strong", zone=Zone.HAND)
    _cast(engine, spell, {"W": 2, "C": 1})

    def pick(choice):
        ids = [str(o["id"]) for o in choice["options"]]
        if choice["player_id"] == "p1":
            return str(keep.instance_id) if str(keep.instance_id) in ids else "decline"
        return str(theirs.instance_id) if str(theirs.instance_id) in ids else "decline"

    _answer(engine, pick=pick)
    assert keep.zone == Zone.BATTLEFIELD and theirs.zone == Zone.BATTLEFIELD
    assert lose.zone == Zone.GRAVEYARD


def test_slaughter_the_strong_budget_blocks_a_choice_over_four_power():
    engine = _game()
    p1, _ = engine.state.players
    big = _filler(engine, "Big", power=3, toughness=3)
    other = _filler(engine, "Other", power=2, toughness=2)
    spell = _card(engine, "Slaughter the Strong", zone=Zone.HAND)
    _cast(engine, spell, {"W": 2, "C": 1})
    choice = engine.state.pending_choice
    assert choice["player_id"] == "p1"
    engine.resolve_pending_choice(str(big.instance_id))
    # 3 power kept, so the 2-power creature (total 5) is no longer offered.
    assert engine.state.pending_choice is None
    assert other.zone == Zone.GRAVEYARD and big.zone == Zone.BATTLEFIELD


def test_staff_of_compleation_destroys_a_permanent_you_own_for_life():
    engine = _game()
    p1, _ = engine.state.players
    staff = _card(engine, "Staff of Compleation")
    mine = _filler(engine, "Mine", power=1, toughness=1)
    _activate(engine, staff, 0, targets=[mine])
    assert mine.zone == Zone.GRAVEYARD and p1.life == 19 and staff.tapped


def test_tip_the_scales_shrinks_every_creature_by_the_sacrificed_toughness():
    engine = _game()
    p1, p2 = engine.state.players
    victim = _filler(engine, "Victim", power=1, toughness=2)
    mine = _filler(engine, "Mine", power=4, toughness=4)
    theirs = _filler(engine, "Theirs", power=3, toughness=3, player="p2")
    spell = _card(engine, "Tip the Scales", zone=Zone.HAND)
    _cast(engine, spell, {"B": 1, "C": 2})
    _answer(engine, pick=lambda c: str(victim.instance_id))
    continuous.recompute(engine.state)
    assert victim.zone == Zone.GRAVEYARD
    assert (mine.power, mine.toughness) == (2, 2)
    assert (theirs.power, theirs.toughness) == (1, 1)


def test_towering_titan_enters_with_counters_equal_to_the_total_toughness_of_your_other_creatures():
    engine = _game()
    _filler(engine, "A", power=1, toughness=3)
    _filler(engine, "B", power=1, toughness=4)
    _filler(engine, "Theirs", power=1, toughness=9, player="p2")
    titan = _card(engine, "Towering Titan", zone=Zone.HAND)
    _cast(engine, titan, {"G": 2, "C": 4})
    assert titan.zone == Zone.BATTLEFIELD and titan.counters.get("+1/+1") == 7


def test_towering_titan_sacrifice_ability_gives_every_creature_trample():
    engine = _game()
    p1, _ = engine.state.players
    titan = _card(engine, "Towering Titan")
    wall = _filler(engine, "Stout", "Creature — Wall", power=0, toughness=4, keywords=["Defender"])
    other = _filler(engine, "Other", power=1, toughness=1)
    _activate(engine, titan, 0, sacrifice_choice=wall.instance_id)
    continuous.recompute(engine.state)
    assert wall.zone == Zone.GRAVEYARD and combat.has(other, "trample")


def test_tree_of_redemption_swaps_your_life_with_its_toughness():
    engine = _game()
    p1, _ = engine.state.players
    tree = _card(engine, "Tree of Redemption")
    continuous.recompute(engine.state)
    toughness = int(tree.toughness)
    p1.life = 7
    _activate(engine, tree, 0)
    continuous.recompute(engine.state)
    assert p1.life == toughness and tree.toughness == 7


def test_wakestone_gargoyle_lets_your_defenders_attack_this_turn():
    engine = _game()
    p1, p2 = engine.state.players
    gargoyle = _card(engine, "Wakestone Gargoyle")
    wall = _filler(engine, "Stout", "Creature — Wall", power=1, toughness=4, keywords=["Defender"])
    other_wall = _filler(engine, "Theirs", "Creature — Wall", power=1, toughness=4, player="p2", keywords=["Defender"])
    engine.state.current_step = "main1"
    assert not engine._can_attack(p1, wall, p2)
    p1.mana_pool.add_many({"W": 1, "C": 1})
    _activate(engine, gargoyle, 0)
    assert engine._can_attack(p1, wall, p2) and engine._can_attack(p1, gargoyle, p2)
    assert not combat.combat_restrictions(other_wall, "attacks_as_though_no_defender")


def test_walking_bulwark_gives_a_defender_haste_attack_permission_and_toughness_damage():
    engine = _game()
    p1, p2 = engine.state.players
    bulwark = _card(engine, "Walking Bulwark")
    wall = _filler(engine, "Stout", "Creature — Wall", power=0, toughness=5, keywords=["Defender"])
    wall.summoning_sick = True
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 2})
    _activate(engine, bulwark, 0, targets=[wall])
    continuous.recompute(engine.state)
    assert combat.has_haste(wall)
    assert engine._can_attack(p1, wall, p2)
    assert combat.combat_restrictions(wall, "damage_uses_toughness")


def test_wall_of_limbs_grows_on_life_gain_and_drains_by_its_power():
    engine = _game()
    p1, p2 = engine.state.players
    wall = _card(engine, "Wall of Limbs")
    engine.rules.gain_life(p1, 2)
    engine.rules.gain_life(p1, 2)
    engine.resolve_until_stable()
    assert wall.counters.get("+1/+1") == 2
    continuous.recompute(engine.state)
    power = int(wall.power)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"B": 2, "C": 5})
    engine.activate_ability(p1, wall, 0, targets=[p2])
    engine.resolve_until_stable()
    assert wall.zone == Zone.GRAVEYARD and p2.life == 20 - power


def test_wall_of_reverence_gains_life_equal_to_a_creatures_power_at_your_end_step():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Wall of Reverence")
    strong = _filler(engine, "Strong", power=6, toughness=6)
    engine.state.current_step = "end"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    _answer(engine, pick=lambda c: str(strong.instance_id) if str(strong.instance_id) in [str(o["id"]) for o in c["options"]] else "accept")
    assert p1.life == 26
