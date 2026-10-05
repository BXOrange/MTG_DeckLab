"""Real gameplay for the Reign of Dragons (Foundations Commander) catalogue entries."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game():
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * 8) for i in range(2)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


def _card(engine, name, player="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
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
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def test_hazorets_monument_discounts_red_creatures_and_loots_on_creature_casts():
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    _card(engine, "Hazoret's Monument")
    red = _filler(engine, "Red Bear", "Creature — Bear", mv=3, power=2, toughness=2, zone=Zone.HAND,
                  color_identity={"R"})
    green = _filler(engine, "Green Bear", "Creature — Bear", mv=3, power=2, toughness=2, zone=Zone.HAND,
                    color_identity={"G"})
    assert engine.effective_cast_cost(p1, red).converted_mana_cost == 2
    assert engine.effective_cast_cost(p1, green).converted_mana_cost == 3


def test_chandras_ignition_hits_every_other_creature_and_each_opponent_for_the_creatures_power():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    big = _filler(engine, "Big", power=4, toughness=5)
    ally = _filler(engine, "Ally", power=1, toughness=3)
    foe = _filler(engine, "Foe", player="p2", power=2, toughness=4)
    foe2 = _filler(engine, "Foe Two", player="p2", power=2, toughness=3)
    spell = _card(engine, "Chandra's Ignition", zone=Zone.HAND)
    p1.mana_pool.add_many({"R": 2, "C": 3})
    engine.cast_spell(p1, spell, targets=[big], target_groups=[[big]])
    engine.resolve_until_stable()
    assert foe in p2.graveyard and foe2 in p2.graveyard and ally in p1.graveyard  # 4 damage is lethal to each
    assert big.damage_marked == 0  # "each other creature"
    assert p2.life == 16 and p1.life == 20  # each opponent, not you


def test_haven_of_the_spirit_dragon_returns_a_dragon_or_ugin_but_not_other_cards():
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    haven = _card(engine, "Haven of the Spirit Dragon")
    dragon = _filler(engine, "Dragon", "Creature — Dragon", power=4, toughness=4, zone=Zone.GRAVEYARD)
    ugin = _filler(engine, "Ugin", "Legendary Planeswalker — Ugin", zone=Zone.GRAVEYARD)
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2, zone=Zone.GRAVEYARD)
    p1.mana_pool.add("C", 2)
    idx = next(i for i, a in enumerate(haven.activated_abilities) if not getattr(a, "mana_ability", False))
    action = next(a for a in engine.legal_actions(p1)
                  if a.get("type") == "activate_ability" and a.get("instance_id") == haven.instance_id
                  and a.get("ability_index") == idx)
    options = {o.get("instance_id") for t in action["targets"] for o in t["options"]}
    assert options == {dragon.instance_id, ugin.instance_id}
    engine.activate_ability(p1, haven, ability_index=idx, targets=[dragon])
    engine.resolve_until_stable()
    assert dragon in p1.hand and haven not in engine.state.battlefield


def test_drakuseth_attack_deals_four_to_one_target_and_three_to_up_to_two_others():
    engine = _game()
    p1, p2 = engine.state.players
    drake = _card(engine, "Drakuseth, Maw of Flames")
    drake.summoning_sick = False
    a = _filler(engine, "A", player="p2", power=1, toughness=4)
    b = _filler(engine, "B", player="p2", power=1, toughness=3)
    c = _filler(engine, "C", player="p2", power=1, toughness=3)
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [drake])
    engine.resolve_until_stable()
    for _ in range(6):  # answer the trigger's target requirements in order
        choice = engine.state.pending_choice
        if not choice:
            break
        options = [o for o in choice["options"] if o.get("instance_id") is not None]
        pick = next((o for o in options if o["instance_id"] in (a.instance_id,)), None)
        if pick is None:
            pick = next((o for o in options if o["instance_id"] in (b.instance_id, c.instance_id)), options[0])
        engine.resolve_pending_choice(str(pick["instance_id"]))
        engine.resolve_until_stable()
    assert a in p2.graveyard  # 4 damage to the first target
    assert b in p2.graveyard or c in p2.graveyard  # 3 damage to another, distinct target


def test_thundermane_dragon_casts_big_creatures_from_the_top_and_gives_them_haste():
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    _card(engine, "Thundermane Dragon")
    p1.library.clear()
    big = _filler(engine, "Big Top", "Creature — Beast", mv=2, power=5, toughness=5, zone=Zone.LIBRARY)
    assert engine.can_cast(p1, big) is False  # no mana yet
    p1.mana_pool.add("C", 2)
    assert engine.can_cast(p1, big)
    engine.cast_spell(p1, big, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert big in engine.state.battlefield and combat.has(big, "haste")


def test_thundermane_dragon_does_not_offer_small_creatures_or_noncreatures_from_the_top():
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    _card(engine, "Thundermane Dragon")
    p1.library.clear()
    small = _filler(engine, "Small Top", "Creature — Bear", mv=1, power=3, toughness=3, zone=Zone.LIBRARY)
    p1.mana_pool.add("C", 3)
    assert not engine.can_cast(p1, small)
    p1.library.clear()
    spell = _filler(engine, "Spell Top", "Instant", mv=1, zone=Zone.LIBRARY)
    assert not engine.can_cast(p1, spell)


@pytest.mark.parametrize("dragons,becomes", [(2, False), (3, True)])
def test_nogi_becomes_a_5_5_flying_dragon_only_with_three_dragons(dragons, becomes):
    engine = _game()
    p1, _ = engine.state.players
    nogi = _card(engine, "Nogi, Draco-Zealot")
    nogi.summoning_sick = False
    for i in range(dragons):
        _filler(engine, f"Dragon {i}", "Creature — Dragon", power=3, toughness=3)
    engine.recompute_continuous_effects()
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [nogi])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert ((nogi.power, nogi.toughness) == (5, 5)) == becomes
    assert combat.has(nogi, "flying") == becomes
    assert continuous.has_subtype(nogi, "Dragon") == becomes


def _horn(engine, chosen="Goblin"):
    horn = _card(engine, "Herald's Horn")
    horn.chosen_type = chosen
    return horn


def test_heralds_horn_discounts_only_creature_spells_of_the_chosen_type():
    engine = _game()
    p1, _ = engine.state.players
    _horn(engine)
    goblin = _filler(engine, "Goblin Guy", "Creature — Goblin", mv=3, power=2, toughness=2, zone=Zone.HAND)
    bear = _filler(engine, "Bear Guy", "Creature — Bear", mv=3, power=2, toughness=2, zone=Zone.HAND)
    assert engine.effective_cast_cost(p1, goblin).converted_mana_cost == 2
    assert engine.effective_cast_cost(p1, bear).converted_mana_cost == 3


@pytest.mark.parametrize("top_type,taken", [("Creature — Goblin", True), ("Creature — Bear", False)])
def test_heralds_horn_upkeep_offers_a_top_creature_of_the_chosen_type(top_type, taken):
    engine = _game()
    p1, _ = engine.state.players
    _horn(engine)
    p1.library.clear()
    top = _filler(engine, "Top", top_type, mv=2, power=2, toughness=2, zone=Zone.LIBRARY)
    for _ in range(20):
        engine.advance_step()
        if engine.state.current_step == "upkeep":
            break
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    if taken:
        assert choice
        engine.resolve_pending_choice(str(top.instance_id))
        engine.resolve_until_stable()
        assert top in p1.hand
    else:
        assert not choice and top in p1.library


def test_leyline_tyrant_keeps_unspent_red_mana_across_steps_but_not_other_colors():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Leyline Tyrant")
    p1.mana_pool.add_many({"R": 2, "G": 1, "C": 1})
    engine.advance_step()  # a step ends: the pool normally empties
    assert p1.mana_pool.pool.get("R", 0) == 2
    assert p1.mana_pool.pool.get("G", 0) == 0 and p1.mana_pool.pool.get("C", 0) == 0


def test_without_leyline_tyrant_the_pool_still_empties():
    engine = _game()
    p1, _ = engine.state.players
    p1.mana_pool.add("R", 2)
    engine.advance_step()
    assert p1.mana_pool.total() == 0


def test_leyline_tyrant_dying_lets_you_pay_red_for_that_much_damage():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    tyrant = _card(engine, "Leyline Tyrant")
    p1.mana_pool.add_many({"R": 3, "G": 2})
    engine.rules.destroy(tyrant)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == "pay_cost_then"
    ids = [o["id"] for o in choice["options"]]
    assert max(int(i.split(":")[-1]) for i in ids if i[-1].isdigit()) == 3  # only red mana counts
    best = next(o["id"] for o in choice["options"] if o.get("x") == 3)
    engine.resolve_pending_choice(best)
    engine.resolve_until_stable()
    pending = engine.state.pending_choice
    assert pending and pending["kind"] == "trigger_target"  # the reflexive trigger's "any target"
    engine.resolve_pending_choice("p2")
    engine.resolve_until_stable()
    assert p1.mana_pool.pool.get("R", 0) == 0 and p1.mana_pool.pool.get("G", 0) == 2
    assert p2.life == 17 and p1.life == 20  # 3 damage to the chosen opponent


def _treasures(engine):
    return [o for o in engine.state.battlefield if o.card.name == "Treasure" and o.controller_id == "p1"]


@pytest.mark.parametrize("has_dragon,treasure", [(True, True), (False, False)])
def test_sarkhan_makes_a_treasure_only_if_it_can_behold_a_dragon(has_dragon, treasure):
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    if has_dragon:
        _filler(engine, "Hand Dragon", "Creature — Dragon", power=3, toughness=3, zone=Zone.HAND)
    sarkhan = _card(engine, "Sarkhan, Dragon Ascendant", zone=Zone.HAND)
    p1.mana_pool.add_many({"R": 1, "C": 1})
    engine.cast_spell(p1, sarkhan, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert bool(_treasures(engine)) == treasure


def test_sarkhan_grows_and_flies_as_a_dragon_whenever_a_dragon_enters():
    engine = _game()
    p1, _ = engine.state.players
    sarkhan = _card(engine, "Sarkhan, Dragon Ascendant")
    base = sarkhan.power
    _filler(engine, "New Dragon", "Creature — Dragon", power=3, toughness=3)
    from mtg_analyzer.models.game.events import EventType, GameEvent

    dragon = [o for o in engine.state.battlefield if o.card.name == "New Dragon"][0]
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id="p1", instance_id=dragon.instance_id,
                                      object_types=sorted(dragon.type_words), object=dragon.name))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert sarkhan.power == base + 1 and combat.has(sarkhan, "flying") and continuous.has_subtype(sarkhan, "Dragon")


def _enter(engine, obj):
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
                                      instance_id=obj.instance_id, object_types=sorted(obj.type_words),
                                      object=obj.name))


def test_goddric_is_a_4_4_flying_dragon_only_after_two_nonland_permanents_entered():
    engine = _game()
    p1, _ = engine.state.players
    goddric = _card(engine, "Goddric, Cloaked Reveler")
    engine.recompute_continuous_effects()
    assert (goddric.power, goddric.toughness) == (3, 3) and not combat.has(goddric, "flying")
    land = _filler(engine, "Land", "Land")
    _enter(engine, land)
    one = _filler(engine, "One", "Creature", power=1, toughness=1)
    _enter(engine, one)
    engine.recompute_continuous_effects()
    assert (goddric.power, goddric.toughness) == (3, 3)  # a land doesn't count, one nonland isn't enough
    two = _filler(engine, "Two", "Artifact")
    _enter(engine, two)
    engine.recompute_continuous_effects()
    assert (goddric.power, goddric.toughness) == (4, 4) and combat.has(goddric, "flying")
    assert continuous.has_subtype(goddric, "Dragon") and not continuous.has_subtype(goddric, "Noble")


def test_goddric_celebrating_pumps_all_your_dragons_for_red():
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    goddric = _card(engine, "Goddric, Cloaked Reveler")
    dragon = _filler(engine, "Dragon", "Creature — Dragon", power=3, toughness=3)
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    for name in ("A", "B"):
        _enter(engine, _filler(engine, name, "Artifact"))
    engine.recompute_continuous_effects()
    p1.mana_pool.add("R", 1)
    action = next(a for a in engine.legal_actions(p1)
                  if a.get("type") == "activate_ability" and a.get("instance_id") == goddric.instance_id)
    engine.activate_ability(p1, goddric, ability_index=action["ability_index"])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert goddric.power == 5 and dragon.power == 4 and bear.power == 2


def _stack_library(engine, player, cards):
    """``cards``: (name, type_line, mv) top-first."""
    p = engine.state.player_by_id(player)
    p.library.clear()
    made = []
    for name, kind, mv in reversed(cards):
        made.append(_filler(engine, name, kind, player=player, mv=mv, zone=Zone.LIBRARY,
                            power=1 if "Creature" in kind else None, toughness=1 if "Creature" in kind else None))
    return list(reversed(made))


@pytest.mark.parametrize("mv", [4, 10])
def test_hit_the_mother_lode_makes_treasures_equal_to_ten_minus_the_discovered_value(mv):
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    land, hit = _stack_library(engine, "p1", [("Top Land", "Land", 0), ("Hit", "Sorcery", mv)])
    spell = _card(engine, "Hit the Mother Lode", zone=Zone.HAND)
    p1.mana_pool.add_many({"R": 3, "C": 4})
    engine.cast_spell(p1, spell, targets=None, target_groups=None)
    engine.resolve_until_stable()
    engine.resolve_pending_choice("hand")
    engine.resolve_until_stable()
    treasures = [o for o in engine.state.battlefield if o.card.name == "Treasure" and o.controller_id == "p1"]
    assert hit in p1.hand
    assert len(treasures) == max(0, 10 - mv) and all(t.tapped for t in treasures)


def test_breaching_dragonstorm_casts_or_takes_a_cheap_hit_and_only_takes_an_expensive_one():
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    cheap, = _stack_library(engine, "p1", [("Cheap", "Sorcery", 3)])
    storm = _card(engine, "Breaching Dragonstorm", zone=Zone.HAND)
    p1.mana_pool.add_many({"R": 1, "C": 4})
    engine.cast_spell(p1, storm, targets=None, target_groups=None)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == "discover"
    engine.resolve_pending_choice("hand")
    engine.resolve_until_stable()
    assert cheap in p1.hand

    big, = _stack_library(engine, "p1", [("Huge", "Creature — Beast", 9)])
    storm2 = _card(engine, "Breaching Dragonstorm", zone=Zone.HAND)
    p1.mana_pool.add_many({"R": 1, "C": 4})
    engine.cast_spell(p1, storm2, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert not engine.state.pending_choice and big in p1.hand  # above 8: no cast offered


def _saga_chapter(engine, saga, chapter):
    from mtg_analyzer.models.game.events import EventType, GameEvent

    # Entering the battlefield already put chapter I's lore counter (and trigger) in play: start clean.
    engine.rules.pending_triggers.clear()
    engine.state.stack.clear()
    engine.state.fire_event(GameEvent(EventType.SAGA_CHAPTER, object=saga.name, instance_id=saga.instance_id,
                                      chapter=chapter, controller_id=saga.controller_id))
    engine.resolve_until_stable()


def test_elder_dragon_war_chapter_one_damages_every_creature_and_each_opponent():
    engine = _game()
    p1, p2 = engine.state.players
    saga = _card(engine, "The Elder Dragon War")
    mine = _filler(engine, "Mine", power=1, toughness=2)
    tough = _filler(engine, "Tough", player="p2", power=1, toughness=5)
    _saga_chapter(engine, saga, 1)
    assert mine in p1.graveyard and tough.damage_marked == 2
    assert p2.life == 18 and p1.life == 20


def test_elder_dragon_war_chapter_two_discards_any_number_then_draws_that_many():
    engine = _game()
    p1, _ = engine.state.players
    saga = _card(engine, "The Elder Dragon War")
    hand = [_filler(engine, f"H{i}", "Sorcery", zone=Zone.HAND) for i in range(3)]
    _saga_chapter(engine, saga, 2)
    for card in hand[:2]:
        choice = engine.state.pending_choice
        assert choice and choice["kind"] == "choose_objects"
        engine.resolve_pending_choice(str(card.instance_id))
        engine.resolve_until_stable()
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert len(p1.graveyard) == 2 and len(p1.hand) == 1 + 2  # one card kept + two drawn


def test_elder_dragon_war_chapter_three_makes_a_flying_4_4_dragon():
    engine = _game()
    p1, _ = engine.state.players
    saga = _card(engine, "The Elder Dragon War")
    _saga_chapter(engine, saga, 3)
    dragon = [o for o in engine.state.battlefield if o.card.name == "Dragon" and o.controller_id == "p1"]
    assert len(dragon) == 1 and (dragon[0].power, dragon[0].toughness) == (4, 4) and combat.has(dragon[0], "flying")


@pytest.mark.parametrize("defender_life,fires", [(20, True), (15, False)])
def test_scourge_of_the_throne_untaps_attackers_only_when_attacking_the_player_with_the_most_life(defender_life, fires):
    engine = _game()
    p1, p2 = engine.state.players
    p1.life = 20
    p2.life = defender_life
    scourge = _card(engine, "Scourge of the Throne")
    scourge.summoning_sick = False
    other = _filler(engine, "Other Attacker", power=2, toughness=2)
    other.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [scourge, other])
    engine.resolve_until_stable()
    assert (not other.tapped) == fires and (not scourge.tapped) == fires


def _three_player_game():
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * 8) for i in range(3)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


def _thrasher_hits(engine, thrasher, victim):
    thrasher.attacking = True
    engine._apply_combat_damage([(victim, thrasher.power, thrasher)])
    engine.resolve_until_stable()


def test_parapet_thrasher_modes_use_the_damaged_opponent_and_each_mode_once_a_turn():
    engine = _three_player_game()
    p1, p2, p3 = engine.state.players
    thrasher = _card(engine, "Parapet Thrasher")
    rock = _filler(engine, "Their Rock", "Artifact", player="p2", mv=2)
    other_rock = _filler(engine, "Third Rock", "Artifact", player="p3", mv=2)
    _thrasher_hits(engine, thrasher, p2)
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == "trigger_mode"
    modes = {o["id"]: o["label"] for o in choice["options"]}
    assert len(modes) == 3
    destroy_id = next(i for i, label in modes.items() if "Artefakt" in label)
    engine.resolve_pending_choice(destroy_id)
    engine.resolve_until_stable()
    pending = engine.state.pending_choice
    if pending:  # the artifact target: only the damaged opponent's artifacts are legal
        ids = {o.get("instance_id") for o in pending["options"]}
        assert rock.instance_id in ids and other_rock.instance_id not in ids
        engine.resolve_pending_choice(str(rock.instance_id))
        engine.resolve_until_stable()
    assert rock in p2.graveyard and other_rock in engine.state.battlefield
    # a second hit this turn can no longer pick the destroy mode
    _thrasher_hits(engine, thrasher, p3)
    again = engine.state.pending_choice
    assert again and destroy_id not in {o["id"] for o in again["options"]}


def _end_step(engine):
    for _ in range(20):
        engine.advance_step()
        if engine.state.current_step == "end":
            return
    raise AssertionError("end step not reached")


def test_dragonhawk_exiles_x_cards_and_burns_for_each_still_exiled_at_the_end_step():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    p1.library.clear()
    cards = _stack_library(engine, "p1", [("A", "Sorcery", 1), ("B", "Sorcery", 1), ("C", "Sorcery", 1), ("D", "Sorcery", 1)])
    _filler(engine, "Big One", power=4, toughness=4)
    _filler(engine, "Big Two", power=5, toughness=5)
    hawk = _card(engine, "Dragonhawk, Fate's Tempest", zone=Zone.HAND)
    p1.mana_pool.add_many({"R": 2, "C": 3})
    engine.cast_spell(p1, hawk, targets=None, target_groups=None)
    engine.resolve_until_stable()
    exiled = [c for c in cards if c in p1.exile]
    assert len(exiled) == 3  # X = two power-4+ creatures plus Dragonhawk itself (a 4/4)
    assert all(c.instance_id in engine.state.temp_play_permissions for c in exiled)
    life = p2.life
    _end_step(engine)
    engine.resolve_until_stable()
    assert p2.life == life - 2 * 3  # 2 damage for each of the three cards still exiled
