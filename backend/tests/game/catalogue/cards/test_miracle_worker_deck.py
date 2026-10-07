"""Real gameplay for the Miracle Worker (Duskmourn: House of Horror Commander) catalogue entries."""

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous, rooms
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


def _energy(engine, player="p1", amount=None):
    p = engine.state.player_by_id(player)
    if amount is not None:
        engine.rules.add_player_counters(p, amount - p.counters.get("energy", 0), "energy")
    return p.counters.get("energy", 0)


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
    engine.resolve_until_stable()
    for step in ("declare_blockers", "combat_damage"):
        state.current_step = step
    engine._step_combat_damage()
    engine.resolve_until_stable()


def _attack(engine, attackers):
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    first = engine.legal_defenders_for(state.active_player)[0]
    engine.declare_attackers(state.active_player, [{"attacker": a, "defender": first} for a in attackers])
    engine.resolve_until_stable()


def _lib(engine, name, type_line, player="p1", mv=0, **kw):
    """Put a filler card on top of ``player``'s library."""
    return _filler(engine, name, type_line, mv=mv, zone=Zone.LIBRARY, player=player, **kw)


def _resolve_choices(engine, pick=None, limit=8):
    for _ in range(limit):
        choice = engine.state.pending_choice
        if choice is None:
            return
        ids = [str(o["id"]) for o in choice.get("options", [])]
        answer = pick(choice, ids) if pick else None
        engine.resolve_pending_choice(answer if answer is not None else (ids[0] if ids else "decline"))


def test_aminatous_augury_exiles_eight_plays_a_land_and_grants_one_free_cast_per_card_type():
    engine = _game(library=2)
    p1, _ = engine.state.players
    land = _lib(engine, "Island", "Basic Land — Island")
    inst_a = _lib(engine, "Instant A", "Instant", mv=2)
    inst_b = _lib(engine, "Instant B", "Instant", mv=2)
    creature = _lib(engine, "Creature", "Creature — Elf", mv=3, power=2, toughness=2)
    artifact = _lib(engine, "Rock", "Artifact", mv=2)
    sorcery = _lib(engine, "Sorcery", "Sorcery", mv=2)
    for i in range(2):
        _lib(engine, f"Filler{i}", "Sorcery", mv=1)
    spell = _card(engine, "Aminatou's Augury", zone=Zone.HAND)
    _cast(engine, spell, RICH)
    _resolve_choices(engine, pick=lambda c, ids: str(land.instance_id) if str(land.instance_id) in ids else None)
    assert land.zone == Zone.BATTLEFIELD and all(o.zone == Zone.EXILE for o in (inst_a, inst_b, creature, artifact))
    engine.state.current_step = "main1"
    engine.cast_spell(p1, inst_a, targets=None, target_groups=None)  # free: nothing in the pool
    engine.resolve_until_stable()
    assert inst_a.zone == Zone.GRAVEYARD
    assert inst_b.instance_id not in engine.state.free_cast_instance_ids  # the instant slot is spent
    assert creature.instance_id in engine.state.free_cast_instance_ids
    assert artifact.instance_id in engine.state.free_cast_instance_ids and sorcery.instance_id in engine.state.free_cast_instance_ids
    engine.cast_spell(p1, creature, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert creature.zone == Zone.BATTLEFIELD


def test_aminatou_veil_piercer_surveils_and_gives_enchantments_miracle_for_four_less():
    engine = _game(library=6)
    p1, _ = engine.state.players
    _card(engine, "Aminatou, Veil Piercer")
    shrine = _lib(engine, "Big Shrine", "Enchantment", mv=5)
    shrine.card.mana_cost = {"generic": 3, "W": 2}
    engine.rules.draw(p1, 1)
    assert shrine.zone == Zone.HAND and getattr(shrine, "miracle_armed", False)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"W": 1})  # {3}{W}{W} reduced by {4} is {W}{W}... generic can't go below zero: {W}{W}
    actions = engine.legal_actions(p1)
    miracle = [a for a in actions if a.get("type") == "cast_spell" and a.get("instance_id") == shrine.instance_id
               and a.get("alt_cost")]
    assert miracle, "the granted miracle cost is offered"
    p1.mana_pool.add_many({"W": 1})
    engine.cast_spell(p1, shrine, targets=None, target_groups=None, alt_cost=True)
    engine.resolve_until_stable()
    assert shrine.zone == Zone.BATTLEFIELD
    second = _lib(engine, "Another Shrine", "Enchantment", mv=5)
    second.card.mana_cost = {"generic": 3, "W": 2}
    engine.rules.draw(p1, 1)
    assert not getattr(second, "miracle_armed", False)  # only the first card drawn each turn


def test_aminatou_veil_piercer_upkeep_surveil():
    engine = _game(library=6)
    _card(engine, "Aminatou, Veil Piercer")
    _step(engine, "upkeep", "p1")
    choice = engine.state.pending_choice
    assert choice is not None and choice["kind"] in ("surveil", "look_top")


def test_ancient_cellarspawn_discounts_horrors_and_drains_for_cheaper_than_value_casts():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Ancient Cellarspawn")
    horror = _filler(engine, "Horror Spell", "Enchantment Creature — Horror", mv=3, zone=Zone.HAND, power=1, toughness=1)
    horror.card.mana_cost = {"generic": 3}
    cost = engine.effective_cast_cost(p1, horror, 0)
    assert cost.converted_mana_cost == 2
    _cast(engine, horror, {"C": 2})
    _resolve_choices(engine, pick=lambda c, ids: "p2" if "p2" in ids else None)
    assert p2.life == 19  # mana spent 2 < mana value 3: the opponent loses the difference
    plain = _filler(engine, "Plain Spell", "Sorcery", mv=2, zone=Zone.HAND)
    plain.card.mana_cost = {"generic": 2}
    _cast(engine, plain, {"C": 2})
    assert p2.life == 19  # full price: nothing


def test_archetype_of_imagination_gives_you_flying_and_takes_it_from_opponents():
    engine = _game()
    mine = _filler(engine, "Mine", power=1, toughness=1)
    theirs = _filler(engine, "Their Flyer", "Creature — Bird", power=1, toughness=1, player="p2", keywords=["Flying"])
    _card(engine, "Archetype of Imagination")
    continuous.recompute(engine.state)
    assert combat.has(mine, "flying") and not combat.has(theirs, "flying")


def test_arvinox_is_a_creature_only_with_three_borrowed_permanents_and_steals_from_the_bottom():
    engine = _game(library=4)
    p1, p2 = engine.state.players
    arvinox = _card(engine, "Arvinox, the Mind Flail")
    continuous.recompute(engine.state)
    assert not arvinox.is_creature
    for i in range(3):
        stolen = _filler(engine, f"Stolen{i}", power=1, toughness=1)
        stolen.owner_id = "p2"
    continuous.recompute(engine.state)
    assert arvinox.is_creature
    bottom = _filler(engine, "Bottom Permanent", "Artifact", mv=2, zone=Zone.LIBRARY, player="p2")
    p2.library.remove(bottom)
    p2.library.insert(0, bottom)
    _step(engine, "end", "p1")
    assert bottom.zone == Zone.EXILE and bottom.face_down_in_exile
    engine.state.current_step = "main1"
    bottom.card.mana_cost = {"generic": 2}
    p1.mana_pool.add_many({"W": 2})  # any color pays
    engine.cast_spell(p1, bottom, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert bottom.zone == Zone.BATTLEFIELD and bottom.controller_id == "p1"


def test_bottomless_pool_bounces_a_creature_when_it_is_cast():
    engine = _game()
    p1, p2 = engine.state.players
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2, player="p2")
    room = _card(engine, "Bottomless Pool // Locker Room", zone=Zone.HAND)
    _cast(engine, room, RICH)
    _resolve_choices(engine, pick=lambda c, ids: str(bear.instance_id) if str(bear.instance_id) in ids else None)
    assert bear.zone == Zone.HAND and room.zone == Zone.BATTLEFIELD


def test_cramped_vents_deals_six_and_gains_the_excess():
    engine = _game()
    p1, p2 = engine.state.players
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2, player="p2")
    room = _card(engine, "Cramped Vents // Access Maze", zone=Zone.HAND)
    _cast(engine, room, RICH, targets=[bear])
    _resolve_choices(engine, pick=lambda c, ids: str(bear.instance_id) if str(bear.instance_id) in ids else None)
    assert bear.zone == Zone.GRAVEYARD and p1.life == 20 + 4  # 6 damage on a 2-toughness creature: 4 excess


def test_secret_arcade_makes_your_nonland_permanents_enchantments():
    engine = _game()
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    land = _filler(engine, "Forest", "Basic Land — Forest")
    theirs = _filler(engine, "Theirs", "Creature — Bear", power=1, toughness=1, player="p2")
    arcade = _card(engine, "Secret Arcade // Dusty Parlor")
    continuous.recompute(engine.state)
    assert "enchantment" not in bear.type_words  # RULE 709.5: both doors are locked, the Room has no rules text
    rooms.unlock(engine.state, arcade, rooms.LEFT)
    continuous.recompute(engine.state)
    assert bear.card.is_enchantment or "enchantment" in bear.type_words
    assert "enchantment" not in land.type_words and "enchantment" not in theirs.type_words


def test_brainstone_draws_three_and_puts_two_back():
    engine = _game(library=8)
    p1, _ = engine.state.players
    stone = _card(engine, "Brainstone")
    p1.mana_pool.add_many({"C": 2})
    hand = len(p1.hand)
    _activate(engine, stone, 0)
    _resolve_choices(engine, limit=6)
    assert len(p1.hand) == hand + 3 - 2 and stone.zone == Zone.GRAVEYARD


def test_demon_of_fates_design_casts_an_enchantment_for_life_once_per_turn_and_sacrifices_for_power():
    engine = _game()
    p1, _ = engine.state.players
    demon = _card(engine, "Demon of Fate's Design")
    ench_a = _filler(engine, "Ench A", "Enchantment", mv=3, zone=Zone.HAND)
    ench_a.card.mana_cost = {"generic": 3}
    ench_b = _filler(engine, "Ench B", "Enchantment", mv=2, zone=Zone.HAND)
    ench_b.card.mana_cost = {"generic": 2}
    engine.state.current_step = "main1"
    assert engine.can_cast(p1, ench_a, alt_cost=True)
    engine.cast_spell(p1, ench_a, targets=None, target_groups=None, alt_cost=True)
    engine.resolve_until_stable()
    assert ench_a.zone == Zone.BATTLEFIELD and p1.life == 17
    assert not engine.can_cast(p1, ench_b, alt_cost=True)  # once during each of your turns
    p1.mana_pool.add_many({"B": 1, "C": 2})
    _activate(engine, demon, 0, sacrifice_choice=ench_a.instance_id)
    continuous.recompute(engine.state)
    assert ench_a.zone == Zone.GRAVEYARD and demon.power == (demon.card.power or 0) + 3


def test_dream_eater_surveils_four_then_bounces_an_opponents_nonland_permanent():
    engine = _game(library=6)
    p1, p2 = engine.state.players
    rock = _filler(engine, "Their Rock", "Artifact", mv=2, player="p2")
    land = _filler(engine, "Their Land", "Land", player="p2")
    _put_on_battlefield(engine, "Dream Eater")
    for _ in range(12):
        choice = engine.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice.get("options", [])]
        engine.resolve_pending_choice(str(rock.instance_id) if str(rock.instance_id) in ids else "decline" if "decline" in ids else ids[0])
    assert rock.zone == Zone.HAND and land.zone == Zone.BATTLEFIELD


def test_fear_of_sleep_paralysis_stuns_on_enchantments_and_keeps_stunned_creatures_tapped():
    engine = _game()
    p1, p2 = engine.state.players
    victim = _filler(engine, "Victim", power=3, toughness=3, player="p2")
    _put_on_battlefield(engine, "Fear of Sleep Paralysis")
    _resolve_choices(engine, pick=lambda c, ids: str(victim.instance_id) if str(victim.instance_id) in ids else None)
    assert victim.tapped and victim.counters.get("stun") == 1
    other = _filler(engine, "Other Victim", power=1, toughness=1, player="p2")
    shrine = _filler(engine, "Shrine", "Enchantment", zone=Zone.HAND)
    shrine.zone = Zone.BATTLEFIELD
    p1.hand[:] = [o for o in p1.hand if o is not shrine]
    engine.state.add_to_battlefield(shrine)
    _enter(engine, shrine)
    _resolve_choices(engine, pick=lambda c, ids: str(other.instance_id) if str(other.instance_id) in ids else None)
    assert other.tapped and other.counters.get("stun") == 1
    # The lock: an untap that would remove the stun counter changes nothing at all.
    engine.rules.set_tapped(victim, False)
    assert victim.tapped and victim.counters.get("stun") == 1
    own = _filler(engine, "Own Stunned", power=1, toughness=1)
    own.tapped = True
    own.counters["stun"] = 1
    engine.rules.set_tapped(own, False)  # it is the *opponents'* permanents that are locked
    assert own.tapped and not own.counters.get("stun")


def test_hall_of_heliods_generosity_tops_the_library_with_an_enchantment_card():
    engine = _game()
    p1, _ = engine.state.players
    hall = _card(engine, "Hall of Heliod's Generosity")
    ench = _filler(engine, "Old Shrine", "Enchantment", zone=Zone.GRAVEYARD)
    p1.mana_pool.add_many({"W": 1, "C": 1})
    _activate(engine, hall, 0, targets=[ench])
    assert ench.zone == Zone.LIBRARY and p1.library[-1] is ench


def test_nightmare_shepherd_exiles_a_dying_creature_and_copies_it_as_a_one_one_nightmare():
    engine = _game()
    _card(engine, "Nightmare Shepherd")
    bear = _filler(engine, "Grizzly", "Creature — Bear", mv=2, power=4, toughness=4)
    engine.rules.destroy(bear)
    engine.resolve_until_stable()
    _resolve_choices(engine)
    copies = [o for o in engine.state.battlefield if o.name == "Grizzly"]
    continuous.recompute(engine.state)
    assert bear.zone == Zone.EXILE and len(copies) == 1
    copy = copies[0]
    assert copy.is_token and (copy.power, copy.toughness) == (1, 1)
    assert "nightmare" in continuous.derived_subtype_words(copy)


def test_one_with_the_multiverse_lets_one_spell_a_turn_be_cast_free_from_hand_or_the_top():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "One with the Multiverse")
    first = _filler(engine, "First", "Sorcery", mv=4, zone=Zone.HAND)
    second = _filler(engine, "Second", "Sorcery", mv=4, zone=Zone.HAND)
    top = _lib(engine, "Top Spell", "Sorcery", mv=4)
    engine.state.current_step = "main1"
    assert engine.can_cast(p1, first, free=True)
    engine.cast_spell(p1, first, targets=None, target_groups=None, free=True)
    engine.resolve_until_stable()
    assert first.zone == Zone.GRAVEYARD
    assert not engine.can_cast(p1, second, free=True) and not engine.can_cast(p1, top, free=True)
    # ...and it renews on the next turn of yours.
    engine.state.internal_turn.number += 2
    assert engine.can_cast(p1, top, free=True)


def test_phenomenon_investigators_believe_makes_horrors_and_doubt_loots_by_bouncing():
    for mode, expect in (("believe", "horror"), ("doubt", "loot")):
        engine = _game(library=6)
        p1, _ = engine.state.players
        investigators = _card(engine, "Phenomenon Investigators", zone=Zone.HAND)
        _cast(engine, investigators, RICH)
        _resolve_choices(engine, pick=lambda c, ids: next(
            (i for i in ids if i.lower() == mode or mode in str(c["options"][ids.index(i)].get("label", "")).lower()), None))
        assert investigators.chosen_mode == mode, investigators.chosen_mode
        if mode == "believe":
            dying = _filler(engine, "Dying", "Creature — Elf", mv=1, power=1, toughness=1)
            engine.rules.destroy(dying)
            engine.resolve_until_stable()
            horrors = _named(engine, "Horror")
            assert len(horrors) == 1 and horrors[0].card.is_enchantment and horrors[0].is_creature
        else:
            home = _filler(engine, "Bounce Me", "Creature — Elf", mv=1, power=1, toughness=1)
            hand = len(p1.hand)
            _step(engine, "end", "p1")
            _resolve_choices(engine, pick=lambda c, ids: str(home.instance_id) if str(home.instance_id) in ids else None)
            assert home.zone == Zone.HAND and len(p1.hand) == hand + 2  # the bounced card and the draw


def test_spirit_sisters_call_sacrifices_a_matching_permanent_to_reanimate_with_an_exile_clause():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Spirit-Sister's Call")
    fodder = _filler(engine, "Fodder", "Creature — Elf", power=1, toughness=1)
    wrong = _filler(engine, "Wrong Type", "Artifact")
    fallen = _filler(engine, "Fallen Hero", "Creature — Human", mv=3, power=3, toughness=3, zone=Zone.GRAVEYARD)
    _step(engine, "end", "p1")
    seen = []

    def pick(choice, ids):
        seen.append(ids)
        for wanted in (str(fallen.instance_id), str(fodder.instance_id)):
            if wanted in ids:
                return wanted
        return None

    _resolve_choices(engine, pick=pick)
    assert fodder.zone == Zone.GRAVEYARD and wrong.zone == Zone.BATTLEFIELD  # only a creature shares a type
    assert fallen.zone == Zone.BATTLEFIELD
    engine.rules.destroy(fallen)
    engine.resolve_until_stable()
    assert fallen.zone == Zone.EXILE  # "exile it instead of putting it anywhere else"


def test_telling_time_puts_one_in_hand_one_on_top_and_one_on_the_bottom():
    engine = _game(library=0)
    p1, _ = engine.state.players
    cards = [_lib(engine, f"Card{i}", "Sorcery") for i in range(5)]
    bottom_before = p1.library[0]
    top3 = list(reversed(p1.library[-3:]))  # top first
    spell = _filler(engine, "Telling Time", "Instant", zone=Zone.HAND)
    from mtg_analyzer.game.card_registry.core import specs_for
    real = _card(engine, "Telling Time", zone=Zone.HAND)
    _cast(engine, real, RICH)
    # pick the second card for the hand, then the third on top (so the first goes to the bottom)
    _resolve_choices(engine, pick=lambda c, ids: str(top3[1].instance_id) if str(top3[1].instance_id) in ids else (
        str(top3[2].instance_id) if str(top3[2].instance_id) in ids else None), limit=6)
    assert top3[1].zone == Zone.HAND
    assert p1.library[-1] is top3[2] and p1.library[0] is top3[0]


def test_the_eldest_reborn_runs_all_three_chapters():
    engine = _game()
    p1, p2 = engine.state.players
    victim = _filler(engine, "Victim", "Creature — Elf", power=1, toughness=1, player="p2")
    spare = _filler(engine, "Spare Card", "Sorcery", zone=Zone.HAND, player="p2")
    big = _filler(engine, "Big Fallen", "Creature — Giant", mv=6, power=6, toughness=6, zone=Zone.GRAVEYARD, player="p2")
    saga = _card(engine, "The Eldest Reborn")  # entering fires chapter I
    engine.resolve_until_stable()
    _resolve_choices(engine)
    assert victim.zone == Zone.GRAVEYARD
    engine.state.fire_event(GameEvent(EventType.SAGA_CHAPTER, chapter=2, controller_id="p1",
                                      instance_id=saga.instance_id, object=saga.name))
    engine.resolve_until_stable()
    _resolve_choices(engine)
    assert spare.zone == Zone.GRAVEYARD
    engine.state.fire_event(GameEvent(EventType.SAGA_CHAPTER, chapter=3, controller_id="p1",
                                      instance_id=saga.instance_id, object=saga.name))
    engine.resolve_until_stable()
    _resolve_choices(engine, pick=lambda c, ids: str(big.instance_id) if str(big.instance_id) in ids else None)
    assert big.zone == Zone.BATTLEFIELD and big.controller_id == "p1"


def test_the_master_of_keys_grows_by_x_mills_twice_x_and_gives_enchantments_escape():
    engine = _game(library=10)
    p1, _ = engine.state.players
    master = _card(engine, "The Master of Keys", zone=Zone.HAND)
    library = len(p1.library)
    _cast(engine, master, RICH, x=2)
    assert master.counters.get("+1/+1") == 2 and len(p1.library) == library - 4
    shrine = _filler(engine, "Escaping Shrine", "Enchantment", mv=2, zone=Zone.GRAVEYARD)
    shrine.card.mana_cost = {"generic": 2}
    for i in range(3):
        _filler(engine, f"Pile{i}", "Sorcery", zone=Zone.GRAVEYARD)
    sorcery = _filler(engine, "Not An Enchantment", "Sorcery", mv=1, zone=Zone.GRAVEYARD)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 2})
    assert engine._graveyard_cast_keyword(shrine) == "escape"
    assert engine._graveyard_cast_keyword(sorcery) != "escape"


def test_nightmare_shepherd_copies_the_dying_transformed_face():
    engine = _game()
    _card(engine, "Nightmare Shepherd")
    wolf = _card(engine, "Huntmaster of the Fells")
    engine.rules.transform_permanent(wolf)
    assert wolf.name == "Ravager of the Fells"
    engine.rules.destroy(wolf)
    engine.resolve_until_stable()
    _resolve_choices(engine)
    copies = [o for o in engine.state.battlefield if o.is_token and o.name == "Ravager of the Fells"]
    assert len(copies) == 1
    assert (copies[0].power, copies[0].toughness) == (1, 1)
    assert "nightmare" in continuous.derived_subtype_words(copies[0])


def test_nightmare_shepherd_cannot_copy_a_card_already_exiled_in_response():
    engine = _game()
    _card(engine, "Nightmare Shepherd")
    bear = _filler(engine, "Vanished Bear", power=2, toughness=2)
    engine.rules.destroy(bear)
    engine.rules.exile(bear)  # another effect removes the linked graveyard object before resolution
    engine.resolve_until_stable()
    _resolve_choices(engine)
    assert not any(o.is_token and o.name == "Vanished Bear" for o in engine.state.battlefield)
    assert bear.zone == Zone.EXILE


def test_spirit_sisters_call_does_not_return_a_different_graveyard_incarnation():
    engine = _game()
    _card(engine, "Spirit-Sister's Call")
    fodder = _filler(engine, "Fodder", power=2, toughness=2)
    fallen = _filler(engine, "Fallen", power=2, toughness=2, zone=Zone.GRAVEYARD)
    _step(engine, "end", "p1")
    engine.resolve_pending_choice(fallen.instance_id)
    assert engine.state.pending_choice["kind"] == "choose_objects"
    # The continuation must not follow the retained ID through a new zone visit.
    engine.rules.return_from_graveyard(fallen, "battlefield")
    engine.rules.put_into_graveyard(fallen)
    engine.resolve_pending_choice(fodder.instance_id)
    engine.resolve_until_stable()
    assert fallen.zone == Zone.GRAVEYARD
