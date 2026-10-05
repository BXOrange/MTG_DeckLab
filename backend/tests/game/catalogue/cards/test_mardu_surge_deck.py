"""Real gameplay for the Mardu Surge (Tarkir: Dragonstorm Commander) catalogue entries."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game(players=2):
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * 8) for i in range(players)],
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


def _attack(engine, attackers):
    """Declare ``attackers`` and let combat lock in (the aggregate "whenever you attack" events fire)."""
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    for a in attackers:
        (a["attacker"] if isinstance(a, dict) else a).summoning_sick = False
    first = engine.legal_defenders_for(state.active_player)[0]
    engine.declare_attackers(state.active_player, [
        a if isinstance(a, dict) else {"attacker": a, "defender": first} for a in attackers
    ])
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()


def _named(engine, name, player="p1"):
    return [o for o in engine.state.battlefield if o.name == name and o.controller_id == player]


def test_adeline_makes_a_tapped_attacking_human_per_opponent_and_scales_with_the_board():
    engine = _game(players=3)
    adeline = _card(engine, "Adeline, Resplendent Cathar")
    _filler(engine, "Bear", power=2, toughness=2)
    continuous.recompute(engine.state)
    assert adeline.power == 2  # two creatures
    _attack(engine, [adeline])
    humans = _named(engine, "Human")
    assert len(humans) == 2  # one per opponent, a single trigger
    assert all(h.tapped and h.attacking for h in humans)
    assert {h.combat_defender["id"] for h in humans} == {"p2", "p3"}
    assert combat.has(adeline, "vigilance") and not adeline.tapped


def test_within_range_makes_two_warriors_and_drains_per_attacker():
    engine = _game(players=3)
    p1, p2, p3 = engine.state.players
    rng = _card(engine, "Within Range", zone=Zone.HAND)
    rng.zone = Zone.BATTLEFIELD
    p1.hand[:] = [o for o in p1.hand if o is not rng]
    engine.state.add_to_battlefield(rng)
    _enter(engine, rng)
    warriors = _named(engine, "Warrior")
    assert len(warriors) == 2 and (warriors[0].power, warriors[0].toughness) == (1, 1)
    extra = _filler(engine, "Extra", power=1, toughness=1)
    _attack(engine, [
        {"attacker": warriors[0], "defender": {"kind": "player", "id": "p2", "label": "p2"}},
        {"attacker": warriors[1], "defender": {"kind": "player", "id": "p2", "label": "p2"}},
        {"attacker": extra, "defender": {"kind": "player", "id": "p3", "label": "p3"}},
    ])
    assert (p2.life, p3.life) == (18, 19)


def test_stroke_of_midnight_destroys_and_gives_the_controller_a_human():
    engine = _game()
    p1, p2 = engine.state.players
    target = _filler(engine, "Their Rock", "Artifact", player="p2", mv=2)
    spell = _card(engine, "Stroke of Midnight", zone=Zone.HAND)
    _cast(engine, spell, {"W": 1, "C": 2}, targets=[target])
    assert target in p2.graveyard
    humans = _named(engine, "Human", "p2")
    assert len(humans) == 1 and (humans[0].power, humans[0].toughness) == (1, 1)
    assert not _named(engine, "Human", "p1")


def test_legion_warboss_makes_a_hasty_goblin_that_must_attack():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Legion Warboss")
    engine.state.current_step = "begin_combat"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    goblins = _named(engine, "Goblin")
    assert len(goblins) == 1
    continuous.recompute(engine.state)
    assert combat.has(goblins[0], "haste") and combat.has(goblins[0], "attacks_if_able")


def test_ainok_strike_leader_triggers_for_itself_or_a_commander_only():
    engine = _game(players=3)
    ainok = _card(engine, "Ainok Strike Leader")
    other = _filler(engine, "Other", power=2, toughness=2)
    _attack(engine, [other])
    assert not _named(engine, "Goblin")  # neither the Leader nor a commander attacked
    engine = _game(players=3)
    ainok = _card(engine, "Ainok Strike Leader")
    other = _filler(engine, "Other", power=2, toughness=2)
    other.is_commander = True
    _attack(engine, [other])
    goblins = _named(engine, "Goblin")
    assert len(goblins) == 2 and all(g.tapped and g.attacking for g in goblins)
    engine = _game(players=2)
    ainok = _card(engine, "Ainok Strike Leader")
    _attack(engine, [ainok])
    assert len(_named(engine, "Goblin")) == 1


def test_ainok_sacrifice_makes_only_creature_tokens_indestructible():
    engine = _game()
    p1, _ = engine.state.players
    ainok = _card(engine, "Ainok Strike Leader")
    token = _filler(engine, "Goblin", power=1, toughness=1)
    token.is_token = True
    real = _filler(engine, "Real", power=2, toughness=2)
    engine.activate_ability(p1, ainok, 0)
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    assert ainok in p1.graveyard
    assert combat.has(token, "indestructible") and not combat.has(real, "indestructible")


def test_divine_visitation_turns_creature_tokens_into_angels_but_not_other_tokens():
    engine = _game(players=3)
    p1, _, _ = engine.state.players
    _card(engine, "Divine Visitation")
    adeline = _card(engine, "Adeline, Resplendent Cathar")
    _attack(engine, [adeline])
    angels = _named(engine, "Angel")
    assert len(angels) == 2 and not _named(engine, "Human")
    assert all((a.power, a.toughness) == (4, 4) and a.tapped and a.attacking for a in angels)
    continuous.recompute(engine.state)
    assert combat.has(angels[0], "flying") and combat.has(angels[0], "vigilance")
    from mtg_analyzer.services.token_database import synthesize_token_card

    made = engine.rules.create_token("p1", synthesize_token_card(name="Clue"), 1)
    assert [t.name for t in made] == ["Clue"]  # a noncreature token is left alone
    bears = engine.rules.create_token("p2", synthesize_token_card(name="Bear", power=2, toughness=2), 1)
    assert [t.name for t in bears] == ["Bear"]  # only creature tokens *you* would create are replaced


@pytest.mark.parametrize("attackers,playable", [(2, False), (3, True)])
def test_windbrisk_heights_needs_three_attackers(attackers, playable):
    engine = _game()
    p1, _ = engine.state.players
    heights = _card(engine, "Windbrisk Heights")
    from mtg_analyzer.game.static_conditions import condition_holds

    creatures = [_filler(engine, f"A{i}", power=1, toughness=1) for i in range(attackers)]
    _attack(engine, creatures)
    cond = heights.activated_abilities[0].effects[0].condition
    assert condition_holds(cond, engine.state, heights, "p1") is playable


def test_bone_devourer_enters_with_a_counter_per_creature_that_died_and_cashes_them_in_when_it_dies():
    engine = _game()
    p1, p2 = engine.state.players
    for i, owner in enumerate(("p1", "p2", "p2")):
        victim = _filler(engine, f"Victim{i}", power=1, toughness=1, player=owner)
        engine.rules.destroy(victim)
    engine.resolve_until_stable()
    devourer = _card(engine, "Bone Devourer", zone=Zone.HAND)
    _cast(engine, devourer, {"B": 1, "C": 3})
    assert devourer.zone == Zone.BATTLEFIELD and devourer.counters.get("+1/+1") == 3
    hand, life = len(p1.hand), p1.life
    engine.rules.destroy(devourer)
    engine.resolve_until_stable()
    assert devourer in p1.graveyard
    assert (len(p1.hand), p1.life) == (hand + 3, life - 3)


def test_commander_s_insignia_counts_commander_casts_from_the_command_zone():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Commander's Insignia")
    bear = _filler(engine, "Bear", power=2, toughness=2)
    continuous.recompute(engine.state)
    assert bear.power == 2
    p1.commander_casts[999] = 2
    continuous.recompute(engine.state)
    assert (bear.power, bear.toughness) == (4, 4)


def test_thalisse_makes_a_spirit_per_token_created_this_turn_at_each_end_step():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Thalisse, Reverent Medium")
    from mtg_analyzer.services.token_database import synthesize_token_card

    engine.rules.create_token("p1", synthesize_token_card(name="Clue"), 2)
    engine.rules.create_token("p2", synthesize_token_card(name="Clue"), 5)  # an opponent's tokens don't count
    engine.state.current_step = "end"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    spirits = _named(engine, "Spirit")
    assert len(spirits) == 2 and (spirits[0].power, spirits[0].toughness) == (1, 1)
    continuous.recompute(engine.state)
    assert combat.has(spirits[0], "flying")


@pytest.mark.parametrize("subtype,draws", [("Warrior", 1), ("Elf", 0)])
def test_mindblade_render_triggers_once_per_step_for_damage_dealt_by_a_warrior(subtype, draws):
    engine = _game(players=3)
    p1, p2, p3 = engine.state.players
    _card(engine, "Mindblade Render")
    hits = [
        _filler(engine, f"Hitter{i}", f"Creature — {subtype}", power=2, toughness=2)
        for i in range(2)
    ]
    hand, life = len(p1.hand), p1.life
    _attack(engine, [
        {"attacker": hits[0], "defender": {"kind": "player", "id": "p2", "label": "p2"}},
        {"attacker": hits[1], "defender": {"kind": "player", "id": "p3", "label": "p3"}},
    ])
    engine.state.current_step = "combat_damage"
    engine._step_combat_damage()
    engine.resolve_until_stable()
    assert (p2.life, p3.life) == (18, 18)
    assert len(p1.hand) == hand + draws and p1.life == life - draws  # one trigger though two opponents were hit


def test_eliminate_the_competition_sacrifices_x_creatures_and_destroys_x_creatures():
    engine = _game()
    p1, p2 = engine.state.players
    mine = [_filler(engine, f"Mine{i}", power=1, toughness=1) for i in range(2)]
    theirs = [_filler(engine, f"Theirs{i}", power=1, toughness=1, player="p2") for i in range(3)]
    spell = _card(engine, "Eliminate the Competition", zone=Zone.HAND)
    _cast(engine, spell, {"B": 1, "C": 4})
    for victim in mine:
        engine.resolve_pending_choice(str(victim.instance_id))
    assert all(m in p1.graveyard for m in mine)
    for victim in theirs[:2]:  # X = 2: two destroy picks
        engine.resolve_pending_choice(str(victim.instance_id))
    engine.resolve_until_stable()
    assert [t.zone for t in theirs] == [Zone.GRAVEYARD, Zone.GRAVEYARD, Zone.BATTLEFIELD]
    assert engine.state.pending_choice is None


def test_tempt_with_vengeance_pays_you_x_more_per_accepting_opponent():
    engine = _game(3)
    p1, p2, p3 = engine.state.players
    spell = _card(engine, "Tempt with Vengeance", zone=Zone.HAND)
    _cast(engine, spell, {"R": 1, "C": 3}, x=3)
    assert engine.state.pending_choice["player_id"] == "p2"
    engine.resolve_pending_choice("pay")
    engine.resolve_until_stable()
    assert engine.state.pending_choice["player_id"] == "p3"
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    assert [len(_named(engine, "Elemental", pid)) for pid in ("p1", "p2", "p3")] == [6, 3, 0]
    continuous.recompute(engine.state)
    assert combat.has(_named(engine, "Elemental", "p2")[0], "haste")


def test_infantry_shield_gives_menace_and_mobilizes_for_the_equipped_creatures_power():
    engine = _game()
    p1, p2 = engine.state.players
    shield = _card(engine, "Infantry Shield")
    bear = _filler(engine, "Bear", power=3, toughness=3)
    shield.attached_to = bear.instance_id
    continuous.recompute(engine.state)
    assert combat.has(bear, "menace")
    _attack(engine, [bear])
    warriors = _named(engine, "Warrior")
    assert len(warriors) == 3 and all(w.tapped and w.attacking for w in warriors)
    assert (warriors[0].power, warriors[0].toughness) == (1, 1)
    for _ in range(10):  # the delayed trigger sacrifices exactly those tokens at the next end step
        engine.advance_step()
        engine.resolve_until_stable()
        if engine.state.current_step == "end":
            break
    engine.resolve_until_stable()
    assert not _named(engine, "Warrior") and bear.zone == Zone.BATTLEFIELD


def _kaya(engine):
    kaya = _card(engine, "Kaya, Geist Hunter")
    kaya.counters["loyalty"] = 7
    engine.state.current_step = "main1"
    engine.state.current_phase = "main"
    return kaya


def _loyalty_index(walker, cost):
    return next(i for i, a in enumerate(walker.activated_abilities) if a.cost.loyalty == cost)


def test_kaya_plus_one_grants_deathtouch_and_counters_a_creature_token_only():
    engine = _game()
    p1, _ = engine.state.players
    kaya = _kaya(engine)
    token = _filler(engine, "Soldier", power=1, toughness=1)
    token.is_token = True
    real = _filler(engine, "Real", power=2, toughness=2)
    engine.activate_ability(p1, kaya, _loyalty_index(kaya, 1), targets=[token])
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    assert combat.has(token, "deathtouch") and combat.has(real, "deathtouch")
    assert token.counters.get("+1/+1") == 1 and not real.counters.get("+1/+1")
    from mtg_analyzer.game.targeting import legal_targets

    spec = kaya.activated_abilities[_loyalty_index(kaya, 1)].effects[1].target_spec
    offered = {t.get("instance_id") for t in legal_targets(engine.state, "p1", spec, source=kaya)}
    assert token.instance_id in offered and real.instance_id not in offered


def test_kaya_minus_two_doubles_your_tokens_until_end_of_turn_only():
    engine = _game(3)
    p1, _, _ = engine.state.players
    kaya = _kaya(engine)
    adeline = _card(engine, "Adeline, Resplendent Cathar")
    engine.activate_ability(p1, kaya, _loyalty_index(kaya, -2))
    engine.resolve_until_stable()
    _attack(engine, [adeline])
    assert len(_named(engine, "Human")) == 4  # two opponents' worth, doubled
    from mtg_analyzer.services.token_database import synthesize_token_card

    mine = engine.rules.create_token("p1", synthesize_token_card(name="Bear", power=2, toughness=2), 1)
    theirs = engine.rules.create_token("p2", synthesize_token_card(name="Bear", power=2, toughness=2), 1)
    assert (len(mine), len(theirs)) == (2, 1)  # only tokens created under *your* control
    engine.state.internal_turn.number += 1  # the next turn: the effect has ended
    assert len(engine.rules.create_token("p1", synthesize_token_card(name="Bear", power=2, toughness=2), 1)) == 1
    assert not [e for e in p1.player_effects if getattr(e, "event_type", None) == EventType.CREATE_TOKENS]


def test_kaya_minus_six_exiles_every_graveyard_and_makes_a_spirit_per_card():
    engine = _game()
    p1, p2 = engine.state.players
    kaya = _kaya(engine)
    for i, owner in enumerate(("p1", "p1", "p2", "p2", "p2")):
        _filler(engine, f"Dead{i}", power=1, toughness=1, player=owner, zone=Zone.GRAVEYARD)
    engine.activate_ability(p1, kaya, _loyalty_index(kaya, -6))
    engine.resolve_until_stable()
    assert not p1.graveyard and not p2.graveyard
    spirits = _named(engine, "Spirit")
    assert len(spirits) == 5 and (spirits[0].power, spirits[0].toughness) == (1, 1)
    continuous.recompute(engine.state)
    assert combat.has(spirits[0], "flying")


def _grenzo_hit(engine, mode):
    """Grenzo connects with p2; answer the modal trigger with ``mode`` (and the goad target when asked)."""
    p1, p2 = engine.state.players
    grenzo = _card(engine, "Grenzo, Havoc Raiser")
    theirs = _filler(engine, "Theirs", power=1, toughness=1, player="p2")
    p2.library.clear()
    top = _filler(engine, "Top Card", "Sorcery", player="p2", zone=Zone.LIBRARY, mv=2)
    _attack(engine, [grenzo])
    engine.state.current_step = "combat_damage"
    engine._step_combat_damage()
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "trigger_mode"
    engine.resolve_pending_choice(str(mode))
    engine.resolve_until_stable()
    return grenzo, theirs, top


def test_grenzo_goad_mode_goads_a_creature_the_damaged_player_controls():
    engine = _game()
    _, theirs, _ = _grenzo_hit(engine, 0)
    while engine.state.pending_choice:  # the goad's target pick, if the engine asks
        choice = engine.state.pending_choice
        engine.resolve_pending_choice(choice["options"][0]["id"])
        engine.resolve_until_stable()
    assert combat.is_goaded(theirs)


def test_grenzo_exile_mode_exiles_the_damaged_players_top_card_and_lets_you_cast_it():
    engine = _game()
    p1, p2 = engine.state.players
    _, _, top = _grenzo_hit(engine, 1)
    assert top.zone == Zone.EXILE and top in p2.exile
    assert engine.state.temp_play_permission_player.get(top.instance_id) == "p1"
    assert top.instance_id in engine.state.mana_wildcard_permission


def _neriv_attack(commander_attacks):
    """Neriv with two Goblins and a Spirit token (two token names) attacks; returns (engine, Neriv, exiled cards)."""
    engine = _game()
    p1, _ = engine.state.players
    neriv = _card(engine, "Neriv, Crackling Vanguard")
    for name in ("Goblin", "Goblin", "Spirit"):
        token = _filler(engine, name, power=1, toughness=1)
        token.is_token = True
    commander = _filler(engine, "Commander", power=2, toughness=2)
    commander.is_commander = True
    p1.library.clear()
    library = [_filler(engine, f"Lib{i}", "Basic Land — Forest", zone=Zone.LIBRARY) for i in range(4)]
    _attack(engine, [neriv, commander] if commander_attacks else [neriv])
    return engine, neriv, [c for c in library if c.zone == Zone.EXILE]


def test_neriv_enters_with_two_goblins():
    engine = _game()
    neriv = _card(engine, "Neriv, Crackling Vanguard", zone=Zone.HAND)
    _cast(engine, neriv, {"R": 1, "W": 1, "B": 1, "C": 2})
    assert len(_named(engine, "Goblin")) == 2


def test_neriv_exiles_one_card_per_differently_named_token_and_plays_them_only_after_a_commander_attacked():
    engine, neriv, exiled = _neriv_attack(commander_attacks=True)
    p1, _ = engine.state.players
    assert len(exiled) == 2  # "Goblin" and "Spirit": two names, three tokens
    engine.state.current_step = "main2"
    engine.state.current_phase = "main"
    assert all(engine.can_play_land(p1, card) for card in exiled)


def test_neriv_cards_stay_unplayable_on_a_turn_no_commander_attacked():
    engine, neriv, exiled = _neriv_attack(commander_attacks=False)
    p1, _ = engine.state.players
    assert len(exiled) == 2
    engine.state.current_step = "main2"
    engine.state.current_phase = "main"
    assert not any(engine.can_play_land(p1, card) for card in exiled)


def test_gix_lets_a_damaging_creatures_controller_pay_life_to_draw():
    engine = _game(3)
    p1, p2, p3 = engine.state.players
    _card(engine, "Gix, Yawgmoth Praetor")
    for pl in (p1, p2, p3):
        for i in range(3):
            _filler(engine, f"{pl.id}-lib{i}", "Sorcery", player=pl.id, zone=Zone.LIBRARY)
    # p2's creature hits p3 — an opponent of Gix's controller (p1), though the attacker is p1's opponent too.
    hitter = _filler(engine, "Hitter", power=2, toughness=2, player="p2")
    hand, life = len(p2.hand), p2.life
    engine.rules.deal_damage(p3, 2, source=hitter, combat=True)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice and choice["player_id"] == "p2"  # the damaging creature's controller, not Gix's
    engine.resolve_pending_choice("pay")
    engine.resolve_until_stable()
    assert (len(p2.hand), p2.life) == (hand + 1, life - 1)
    assert len(p1.hand) == 0


def test_gix_ignores_damage_dealt_to_its_controller():
    engine = _game(2)
    p1, p2 = engine.state.players
    _card(engine, "Gix, Yawgmoth Praetor")
    hitter = _filler(engine, "Hitter", power=2, toughness=2, player="p2")
    engine.rules.deal_damage(p1, 2, source=hitter, combat=True)
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None


def test_gix_activation_discards_x_exiles_x_from_an_opponent_and_plays_them_free():
    engine = _game(2)
    p1, p2 = engine.state.players
    gix = _card(engine, "Gix, Yawgmoth Praetor")
    discards = [_filler(engine, f"Discard{i}", "Sorcery", zone=Zone.HAND) for i in range(2)]
    p2.library.clear()
    spell = _filler(engine, "Stolen Spell", "Sorcery", player="p2", zone=Zone.LIBRARY, mv=5)
    land = _filler(engine, "Stolen Forest", "Basic Land — Forest", player="p2", zone=Zone.LIBRARY)
    engine.state.current_step, engine.state.current_phase = "main1", "main"
    p1.mana_pool.add_many({"B": 3, "C": 4})
    engine.activate_ability(p1, gix, 0, targets=[p2], x=2, discard_choices=[d.instance_id for d in discards])
    engine.resolve_until_stable()
    assert all(d in p1.graveyard for d in discards)
    assert spell.zone == Zone.EXILE and land.zone == Zone.EXILE
    assert engine.can_play_land(p1, land)
    assert engine.state.exile_cast_cost_override[spell.instance_id] == "{0}"
    assert engine.can_cast(p1, spell)  # a five-mana sorcery castable with an empty mana pool
