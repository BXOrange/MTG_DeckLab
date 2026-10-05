"""Real gameplay for the Calling All Angels (Foundations Commander) catalogue entries."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game(players=2, life=20):
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * 8) for i in range(players)],
                                 starting_hand=0, starting_life=life)
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


def _enter(engine, obj, from_cast=False):
    """Announce ``obj`` entering (the fillers are placed without the ENTERS_BATTLEFIELD event)."""
    obj.was_cast = from_cast
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
                                      instance_id=obj.instance_id, object_types=sorted(obj.type_words),
                                      object=obj.name))
    engine.resolve_until_stable()


def _cast(engine, card, pool, targets=None, **kw):
    p1 = engine.state.player_by_id(card.controller_id)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many(pool)
    engine.cast_spell(p1, card, targets=targets, target_groups=None, **kw)
    engine.resolve_until_stable()


def _named(engine, name, player="p1"):
    return [o for o in engine.state.battlefield if o.name == name and o.controller_id == player]


def _attack(engine, attackers):
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    for a in attackers:
        a.summoning_sick = False
    first = engine.legal_defenders_for(state.active_player)[0]
    engine.declare_attackers(state.active_player, [{"attacker": a, "defender": first} for a in attackers])
    engine.resolve_until_stable()


def _commander(engine, name="Their Commander", player="p1"):
    obj = _filler(engine, name, power=1, toughness=1, player=player)
    obj.is_commander = True
    return obj


@pytest.mark.parametrize("has_commander", [True, False])
def test_angelic_field_marshal_needs_your_commander_on_the_battlefield(has_commander):
    engine = _game()
    marshal = _card(engine, "Angelic Field Marshal")
    bear = _filler(engine, "Bear", power=2, toughness=2)
    if has_commander:
        _commander(engine)
    continuous.recompute(engine.state)
    assert combat.has(bear, "vigilance") is has_commander
    base_power, base_toughness = int(marshal.card.power), int(marshal.card.toughness)
    bonus = 2 if has_commander else 0
    assert (marshal.power, marshal.toughness) == (base_power + bonus, base_toughness + bonus)


def test_archangel_of_tithes_taxes_attackers_only_while_untapped():
    engine = _game()
    p1, p2 = engine.state.players
    angel = _card(engine, "Archangel of Tithes", player="p2")
    bear = _filler(engine, "Bear", power=2, toughness=2)
    with pytest.raises(ValueError, match="attack tax"):
        _attack(engine, [bear])
    assert not bear.attacking
    p1.mana_pool.add("C", 1)
    _attack(engine, [bear])
    assert bear.attacking
    assert not p1.mana_pool.pool.get("C")  # the tax was paid from the pool
    # Tapped, the Archangel taxes nothing.
    engine2 = _game()
    _card(engine2, "Archangel of Tithes", player="p2").tapped = True
    free = _filler(engine2, "Bear", power=2, toughness=2)
    _attack(engine2, [free])
    assert free.attacking


def test_archangel_of_tithes_taxes_blockers_while_attacking():
    engine = _game()
    p1, p2 = engine.state.players
    angel = _card(engine, "Archangel of Tithes")
    blocker = _filler(engine, "Blocker", "Creature — Bird", power=1, toughness=3, player="p2", keywords=["Flying"])
    engine.state.current_step = "declare_attackers"
    _attack(engine, [angel])
    engine.state.current_step = "declare_blockers"
    with pytest.raises(ValueError, match="block tax"):
        engine.declare_blockers(p2, [{"blocker": blocker, "attacker": angel}])
    assert blocker.blocking is None
    p2.mana_pool.add("C", 1)
    engine.declare_blockers(p2, [{"blocker": blocker, "attacker": angel}])
    assert blocker.blocking == angel.instance_id


def test_archangel_of_tithes_does_not_tax_blockers_when_not_attacking():
    engine = _game()
    p1, p2 = engine.state.players
    angel = _card(engine, "Archangel of Tithes", player="p2")
    attacker = _filler(engine, "Attacker", power=1, toughness=1)
    p1.mana_pool.add("C", 1)
    _attack(engine, [attacker])
    engine.state.current_step = "declare_blockers"
    engine.declare_blockers(p2, [{"blocker": angel, "attacker": attacker}])
    assert angel.blocking == attacker.instance_id


@pytest.mark.parametrize("subtype,counters", [("Angel", 2), ("Cleric", 0)])
def test_defy_death_reanimates_and_gives_an_angel_two_counters(subtype, counters):
    engine = _game()
    p1, _ = engine.state.players
    target = _filler(engine, "Fallen", f"Creature — {subtype}", power=2, toughness=2, zone=Zone.GRAVEYARD)
    spell = _card(engine, "Defy Death", zone=Zone.HAND)
    _cast(engine, spell, {"W": 2, "C": 3}, targets=[target])
    assert target.zone == Zone.BATTLEFIELD
    assert target.counters.get("+1/+1", 0) == counters


@pytest.mark.parametrize("land,destination", [("Plains", Zone.BATTLEFIELD), ("Forest", Zone.HAND)])
def test_emeria_shepherd_landfall_returns_a_nonland_permanent_card(land, destination):
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Emeria Shepherd")
    target = _filler(engine, "Old Rock", "Artifact", mv=2, zone=Zone.GRAVEYARD)
    land_obj = _filler(engine, land, f"Basic Land — {land}")
    _enter(engine, land_obj)
    state = engine.state
    # An optional, targeted trigger: accept it and pick the card.
    for _ in range(4):
        choice = state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice.get("options", [])]
        pick = str(target.instance_id) if str(target.instance_id) in ids else (ids[0] if ids else "accept")
        engine.resolve_pending_choice(pick)
    assert target.zone == destination


def test_endless_atlas_needs_three_lands_with_the_same_name():
    engine = _game()
    p1, _ = engine.state.players
    atlas = _card(engine, "Endless Atlas")
    for name in ("Forest", "Forest", "Island"):
        _filler(engine, name, f"Basic Land — {name}")
    from mtg_analyzer.game.static_conditions import condition_holds

    cond = atlas.activated_abilities[0].cost.activation_condition
    assert condition_holds(cond, engine.state, atlas, "p1") is False
    _filler(engine, "Forest", "Basic Land — Forest")
    assert condition_holds(cond, engine.state, atlas, "p1") is True


def test_exemplar_of_light_grows_on_life_gain_and_draws_once_per_turn():
    engine = _game()
    p1, _ = engine.state.players
    library = len(p1.library)
    exemplar = _card(engine, "Exemplar of Light")
    engine.rules.gain_life(p1, 1)
    engine.resolve_until_stable()
    assert exemplar.counters.get("+1/+1") == 1
    assert len(p1.library) == library - 1
    engine.rules.gain_life(p1, 1)
    engine.resolve_until_stable()
    assert exemplar.counters.get("+1/+1") == 2
    assert len(p1.library) == library - 1  # the draw triggers once each turn


def test_fateful_absence_destroys_and_gives_its_controller_a_clue():
    engine = _game()
    p1, p2 = engine.state.players
    victim = _filler(engine, "Their Bear", power=2, toughness=2, player="p2")
    spell = _card(engine, "Fateful Absence", zone=Zone.HAND)
    _cast(engine, spell, {"W": 1, "C": 1}, targets=[victim])
    assert victim in p2.graveyard
    assert len(_named(engine, "Clue", "p2")) == 1
    assert not _named(engine, "Clue", "p1")


def test_giada_gives_other_angels_a_counter_per_angel_already_controlled():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Giada, Font of Hope")
    second = _filler(engine, "Second Angel", "Creature — Angel", power=2, toughness=2, zone=Zone.HAND)
    _cast(engine, second, {})
    assert second.zone == Zone.BATTLEFIELD and second.counters.get("+1/+1") == 1
    third = _filler(engine, "Third Angel", "Creature — Angel", power=2, toughness=2, zone=Zone.HAND)
    _cast(engine, third, {})
    assert third.counters.get("+1/+1") == 2
    human = _filler(engine, "Human", "Creature — Human", power=2, toughness=2, zone=Zone.HAND)
    _cast(engine, human, {})
    assert human.counters.get("+1/+1", 0) == 0


def test_herald_of_eternal_dawn_stops_you_losing_and_opponents_winning():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Herald of Eternal Dawn")
    p1.life = 0
    engine.resolve_until_stable()
    assert not p1.has_lost  # 0 life, but it can't lose
    engine.rules._player_loses(p1, "effect")
    assert not p1.has_lost
    # An opponent can't win by an alternative win condition either.
    engine.rules.player_wins(p2)
    assert not p1.has_lost and not engine.state.game_over
    # …but conceding still works (RULE 104.3a).
    engine.rules.concede(p1)
    assert p1.has_lost


def test_herald_of_war_grows_when_attacking_and_discounts_angels_and_humans_per_counter():
    engine = _game()
    p1, _ = engine.state.players
    herald = _card(engine, "Herald of War")
    engine.state.current_step = "main1"
    angel = _filler(engine, "Costly Angel", "Creature — Angel", mv=5, power=3, toughness=3, zone=Zone.HAND)
    elf = _filler(engine, "Costly Elf", "Creature — Elf", mv=5, power=3, toughness=3, zone=Zone.HAND)
    assert continuous.cost_reduction_for(engine.state, p1, angel)[0] == 0
    _attack(engine, [herald])
    assert herald.counters.get("+1/+1") == 1
    assert continuous.cost_reduction_for(engine.state, p1, angel)[0] == 1
    assert continuous.cost_reduction_for(engine.state, p1, elf)[0] == 0
    herald.add_counters("+1/+1", 2)
    human = _filler(engine, "Costly Human", "Creature — Human", mv=5, power=3, toughness=3, zone=Zone.HAND)
    assert continuous.cost_reduction_for(engine.state, p1, human)[0] == 3


def test_linvala_gains_life_and_makes_an_angel_only_when_behind():
    engine = _game()
    p1, p2 = engine.state.players
    p2.life = 30
    for i in range(2):
        _filler(engine, f"Their Bear {i}", power=2, toughness=2, player="p2")
    linvala = _card(engine, "Linvala, the Preserver", zone=Zone.HAND)
    _cast(engine, linvala, {"W": 2, "C": 4})
    assert p1.life == 25
    angels = _named(engine, "Angel")
    assert len(angels) == 1 and (angels[0].power, angels[0].toughness) == (3, 3)


def test_linvala_does_nothing_when_ahead():
    engine = _game()
    p1, p2 = engine.state.players
    p1.life = 30
    linvala = _card(engine, "Linvala, the Preserver", zone=Zone.HAND)
    _cast(engine, linvala, {"W": 2, "C": 4})
    assert p1.life == 30
    assert not _named(engine, "Angel")


def test_metallic_mimic_gives_other_creatures_of_the_chosen_type_a_counter():
    engine = _game()
    p1, _ = engine.state.players
    _filler(engine, "Goblin Pal", "Creature — Goblin", power=1, toughness=1)  # offers "Goblin" as an option
    mimic = _card(engine, "Metallic Mimic", zone=Zone.HAND)
    _cast(engine, mimic, {"C": 2})
    assert engine.state.pending_choice["kind"] == "choose_creature_type"
    engine.resolve_pending_choice("Goblin")
    assert mimic.zone == Zone.BATTLEFIELD and mimic.chosen_type == "Goblin"
    goblin = _filler(engine, "Goblin Guy", "Creature — Goblin", power=1, toughness=1, zone=Zone.HAND)
    _cast(engine, goblin, {})
    assert goblin.counters.get("+1/+1") == 1
    elf = _filler(engine, "Elf Guy", "Creature — Elf", power=1, toughness=1, zone=Zone.HAND)
    _cast(engine, elf, {})
    assert elf.counters.get("+1/+1", 0) == 0


def test_righteous_valkyrie_pumps_the_team_at_seven_over_starting_life():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Righteous Valkyrie")
    bear = _filler(engine, "Bear", power=2, toughness=2)
    p1.life = 26
    continuous.recompute(engine.state)
    assert bear.power == 2
    p1.life = 27
    continuous.recompute(engine.state)
    assert (bear.power, bear.toughness) == (4, 4)


def test_sephara_alternative_cost_pays_w_and_taps_four_flyers():
    engine = _game()
    p1, _ = engine.state.players
    flyers = [_filler(engine, f"Flyer{i}", "Creature — Bird", power=1, toughness=1, keywords=["Flying"])
              for i in range(4)]
    sephara = _card(engine, "Sephara, Sky's Blade", zone=Zone.HAND)
    engine.state.current_step = "main1"
    p1.mana_pool.add("W", 1)
    engine.cast_spell(p1, sephara, targets=None, target_groups=None, alt_cost=True)
    engine.resolve_until_stable()
    assert sephara.zone == Zone.BATTLEFIELD
    assert all(f.tapped for f in flyers)
    continuous.recompute(engine.state)
    assert combat.has(flyers[0], "indestructible")


def test_seraph_of_the_sword_prevents_combat_damage_but_not_other_damage():
    engine = _game()
    seraph = _card(engine, "Seraph of the Sword")
    source = _filler(engine, "Attacker", power=3, toughness=3, player="p2")
    engine.rules.deal_damage(seraph, 3, source=source, combat=True)
    assert seraph.damage_marked == 0
    engine.rules.deal_damage(seraph, 2, source=source, combat=False)
    assert seraph.damage_marked == 2


@pytest.mark.parametrize("turns_taken,castable", [(1, False), (3, False), (4, True)])
def test_serra_avenger_cannot_be_cast_on_your_first_three_turns(turns_taken, castable):
    engine = _game()
    p1, _ = engine.state.players
    avenger = _card(engine, "Serra Avenger", zone=Zone.HAND)
    p1.turns_taken = turns_taken
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"W": 2})
    assert engine.can_cast(p1, avenger) is castable


def test_speaker_of_the_heavens_makes_an_angel_only_at_seven_over_starting_life():
    engine = _game()
    p1, _ = engine.state.players
    speaker = _card(engine, "Speaker of the Heavens")
    engine.state.current_step = "main1"
    ability = speaker.activated_abilities[0]
    p1.life = 26
    assert not engine.can_activate(p1, speaker, ability)
    p1.life = 27
    assert engine.can_activate(p1, speaker, ability)
    engine.activate_ability(p1, speaker, 0)
    engine.resolve_until_stable()
    angels = _named(engine, "Angel")
    assert len(angels) == 1 and (angels[0].power, angels[0].toughness) == (4, 4)


def test_wojek_investigator_investigates_once_per_opponent_with_more_cards():
    engine = _game(players=3)
    p1, p2, p3 = engine.state.players
    _card(engine, "Wojek Investigator")
    for _ in range(3):
        _filler(engine, "Card", "Sorcery", zone=Zone.HAND, player="p2")
    _filler(engine, "Card", "Sorcery", zone=Zone.HAND, player="p3")
    for _ in range(2):
        _filler(engine, "Mine", "Sorcery", zone=Zone.HAND, player="p1")
    engine.state.current_step = "upkeep"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    assert len(_named(engine, "Clue")) == 1  # only p2 has more cards than p1
