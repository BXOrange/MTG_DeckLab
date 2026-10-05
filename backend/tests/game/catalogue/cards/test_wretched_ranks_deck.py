"""Real gameplay for the Wretched Ranks (Foundations Commander) catalogue entries."""

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


def _enter(engine, obj, from_cast=False):
    """Announce ``obj`` entering (the fillers are placed without the ENTERS_BATTLEFIELD event)."""
    obj.was_cast = from_cast
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
                                      instance_id=obj.instance_id, object_types=sorted(obj.type_words),
                                      object=obj.name))
    engine.resolve_until_stable()


def _cast(engine, card, pool, **kw):
    p1 = engine.state.player_by_id(card.controller_id)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many(pool)
    engine.cast_spell(p1, card, targets=None, target_groups=None, **kw)
    engine.resolve_until_stable()


def _zombies(engine, player="p1"):
    return [o for o in engine.state.battlefield if o.name == "Zombie" and o.controller_id == player]


def test_army_of_the_damned_makes_thirteen_tapped_zombies():
    engine = _game()
    p1, _ = engine.state.players
    spell = _card(engine, "Army of the Damned", zone=Zone.HAND)
    _cast(engine, spell, {"B": 3, "C": 5})
    zombies = _zombies(engine)
    assert len(zombies) == 13 and all(z.tapped for z in zombies) and (zombies[0].power, zombies[0].toughness) == (2, 2)


@pytest.mark.parametrize("type_line,draws", [("Creature — Zombie", 1), ("Creature — Elf", 0)])
def test_cemetery_recruitment_draws_only_for_a_returned_zombie(type_line, draws):
    engine = _game()
    p1, _ = engine.state.players
    dead = _filler(engine, "Dead", type_line, power=1, toughness=1, zone=Zone.GRAVEYARD)
    spell = _card(engine, "Cemetery Recruitment", zone=Zone.HAND)
    hand = len(p1.hand)
    p1.mana_pool.add_many({"B": 1, "C": 1})
    engine.state.current_step = "main1"
    engine.cast_spell(p1, spell, targets=[dead], target_groups=None)
    engine.resolve_until_stable()
    assert dead.zone == Zone.HAND
    assert len(p1.hand) == hand - 1 + 1 + draws  # the spell left, the creature arrived, plus the draw


def test_lord_of_the_undead_buffs_every_other_zombie_and_recurs_zombie_cards():
    engine = _game()
    p1, _ = engine.state.players
    lord = _card(engine, "Lord of the Undead")
    lord.summoning_sick = False
    mine = _filler(engine, "Mine", "Creature — Zombie", power=2, toughness=2)
    theirs = _filler(engine, "Theirs", "Creature — Zombie", player="p2", power=2, toughness=2)
    continuous.recompute(engine.state)
    assert mine.power == 3 and theirs.power == 3 and lord.power == lord.card.power
    dead = _filler(engine, "Dead", "Creature — Zombie", power=1, toughness=1, zone=Zone.GRAVEYARD)
    other = _filler(engine, "Elf", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    from mtg_analyzer.game.targeting import legal_targets

    spec = lord.activated_abilities[0].effects[0].target_spec
    offered = {t.get("instance_id") for t in legal_targets(engine.state, "p1", spec, source=lord)}
    assert dead.instance_id in offered and other.instance_id not in offered


@pytest.mark.parametrize("graveyard,returns", [(3, False), (4, True)])
def test_oversold_cemetery_needs_four_creature_cards_in_the_graveyard(graveyard, returns):
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Oversold Cemetery")
    deads = [_filler(engine, f"D{i}", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD) for i in range(graveyard)]
    engine.state.active_player_index = 0
    engine.state.current_step = "upkeep"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    assert (engine.state.pending_choice is not None) is returns


def test_witch_s_cottage_returns_a_creature_to_the_library_only_when_it_enters_untapped():
    for swamps, untapped in ((0, False), (3, True)):
        engine = _game()
        p1, _ = engine.state.players
        for i in range(swamps):
            _filler(engine, f"Swamp{i}", "Basic Land — Swamp")
        dead = _filler(engine, "Dead", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
        cottage = _card(engine, "Witch's Cottage", zone=Zone.HAND)
        engine.state.current_step = "main1"
        engine.play_land(p1, cottage)
        engine.resolve_until_stable()
        assert cottage.tapped is (not untapped)
        assert (engine.state.pending_choice is not None) is untapped


def test_endless_ranks_makes_half_your_zombies_rounded_down():
    engine = _game()
    _card(engine, "Endless Ranks of the Dead")
    for i in range(5):
        _filler(engine, f"Z{i}", "Creature — Zombie", power=1, toughness=1)
    engine.state.active_player_index = 0
    engine.state.current_step = "upkeep"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    assert len(_zombies(engine)) == 2


def test_death_baron_buffs_skeletons_and_other_zombies_once_each():
    engine = _game()
    baron = _card(engine, "Death Baron")
    skeleton = _filler(engine, "Bones", "Creature — Skeleton", power=1, toughness=1)
    zombie = _filler(engine, "Zed", "Creature — Zombie", power=2, toughness=2)
    both = _filler(engine, "Both", "Creature — Zombie Skeleton", power=2, toughness=2)
    elf = _filler(engine, "Elf", "Creature — Elf", power=2, toughness=2)
    theirs = _filler(engine, "Theirs", "Creature — Zombie", player="p2", power=2, toughness=2)
    continuous.recompute(engine.state)
    assert (skeleton.power, skeleton.toughness) == (2, 2) and combat.has(skeleton, "deathtouch")
    assert (zombie.power, zombie.toughness) == (3, 3) and combat.has(zombie, "deathtouch")
    assert (both.power, both.toughness) == (3, 3)  # once, not twice
    assert baron.power == baron.card.power and not combat.has(baron, "deathtouch")  # "other" Zombies
    assert elf.power == 2 and theirs.power == 2


def test_mutilate_shrinks_every_creature_by_your_swamp_count_until_end_of_turn():
    engine = _game()
    p1, _ = engine.state.players
    for i in range(2):
        _filler(engine, f"Swamp{i}", "Basic Land — Swamp")
    mine = _filler(engine, "Mine", "Creature — Elf", power=3, toughness=3)
    theirs = _filler(engine, "Theirs", "Creature — Elf", player="p2", power=2, toughness=2)
    spell = _card(engine, "Mutilate", zone=Zone.HAND)
    _cast(engine, spell, {"B": 2, "C": 2})
    continuous.recompute(engine.state)
    assert (mine.power, mine.toughness) == (1, 1)
    assert theirs.zone == Zone.GRAVEYARD  # 2/2 with -2/-2


def test_noxious_ghoul_shrinks_non_zombies_when_any_zombie_enters():
    engine = _game()
    ghoul = _card(engine, "Noxious Ghoul")
    elf = _filler(engine, "Elf", "Creature — Elf", power=3, toughness=3)
    zombie = _filler(engine, "Zed", "Creature — Zombie", power=3, toughness=3)
    _enter(engine, ghoul)
    continuous.recompute(engine.state)
    assert (elf.power, elf.toughness) == (2, 2) and (zombie.power, zombie.toughness) == (3, 3)
    theirs = _filler(engine, "Their Zombie", "Creature — Zombie", player="p2", power=2, toughness=2)
    _enter(engine, theirs)
    continuous.recompute(engine.state)
    assert (elf.power, elf.toughness) == (1, 1)  # another Zombie entering (any controller) triggers again


def test_diregraf_colossus_enters_with_a_counter_per_zombie_card_in_the_graveyard_and_makes_tokens():
    engine = _game()
    p1, _ = engine.state.players
    for i in range(3):
        _filler(engine, f"Z{i}", "Creature — Zombie", power=1, toughness=1, zone=Zone.GRAVEYARD)
    _filler(engine, "Elf", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    colossus = _card(engine, "Diregraf Colossus", zone=Zone.HAND)
    _cast(engine, colossus, {"B": 1, "C": 2})
    assert colossus.plus_one_counters == 3
    zombie_spell = _filler(engine, "Zed Spell", "Creature — Zombie", power=1, toughness=1, zone=Zone.HAND)
    _cast(engine, zombie_spell, {})
    assert len(_zombies(engine)) == 1 and _zombies(engine)[0].tapped


def test_josu_vess_makes_eight_menace_zombie_knights_only_when_kicked():
    for kicked in (0, 1):
        engine = _game()
        josu = _card(engine, "Josu Vess, Lich Knight")
        josu.kicker_count = kicked
        _enter(engine, josu)
        knights = [o for o in engine.state.battlefield if o.name == "Zombie Knight"]
        assert len(knights) == (8 if kicked else 0)
        if kicked:
            continuous.recompute(engine.state)
            assert all(combat.has(k, "menace") and (k.power, k.toughness) == (2, 2) for k in knights)


def test_kalitas_exiles_opponents_nontoken_creatures_that_die_and_makes_you_a_zombie():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Kalitas, Traitor of Ghet")
    theirs = _filler(engine, "Theirs", "Creature — Elf", player="p2", power=1, toughness=1)
    token = _filler(engine, "Their Token", "Token Creature — Elf", player="p2", power=1, toughness=1)
    token.is_token = True
    mine = _filler(engine, "Mine", "Creature — Elf", power=1, toughness=1)
    for victim in (theirs, token, mine):
        engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert theirs.zone == Zone.EXILE and theirs not in p2.graveyard
    assert mine.zone == Zone.GRAVEYARD  # your own creatures die normally
    assert len(_zombies(engine)) == 1  # one, for the nontoken only (the token just ceased to exist)


def _razorlash_game(nonbasic_lands, mana):
    engine = _game()
    p1, _ = engine.state.players
    razor = _card(engine, "Razorlash Transmogrant", zone=Zone.GRAVEYARD)
    for i in range(nonbasic_lands):
        _filler(engine, f"Odd Land {i}", "Land", player="p2")
    engine.state.current_step = "main1"
    p1.mana_pool.add_many(mana)
    return engine, p1, razor


def test_razorlash_transmogrant_costs_four_less_only_against_four_nonbasic_lands():
    engine, p1, razor = _razorlash_game(3, {"B": 2})
    assert not engine.can_activate(p1, razor, razor.activated_abilities[0])  # {4}{B}{B} against three nonbasics
    engine, p1, razor = _razorlash_game(4, {"B": 2})
    assert engine.can_activate(p1, razor, razor.activated_abilities[0])  # {B}{B} against four
    engine.activate_ability(p1, razor, 0)
    engine.resolve_until_stable()
    assert razor.zone == Zone.BATTLEFIELD and razor.plus_one_counters == 1
    engine, p1, razor = _razorlash_game(0, {"B": 2, "C": 4})
    assert engine.can_activate(p1, razor, razor.activated_abilities[0])  # full price


def test_syphon_flesh_makes_a_zombie_per_creature_the_opponents_sacrificed():
    engine = _game(3)
    p1, p2, p3 = engine.state.players
    _filler(engine, "A", "Creature — Elf", player="p2", power=1, toughness=1)
    _filler(engine, "B", "Creature — Elf", player="p3", power=1, toughness=1)
    spell = _card(engine, "Syphon Flesh", zone=Zone.HAND)
    _cast(engine, spell, {"B": 3, "C": 4})
    while engine.state.pending_choice:
        choice = engine.state.pending_choice
        engine.rules.resolve_choice(str(choice["options"][0]["id"]))
        engine.resolve_until_stable()
    assert len(_zombies(engine)) == 2


def test_undead_butler_mills_then_trades_itself_for_a_creature_card():
    engine = _game()
    p1, _ = engine.state.players
    butler = _card(engine, "Undead Butler")
    library = len(p1.library)
    _enter(engine, butler)
    assert len(p1.library) == library - 3
    dead = _filler(engine, "Dead", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    engine.rules.destroy(butler)
    engine.resolve_until_stable()
    for _ in range(4):
        choice = engine.state.pending_choice
        if not choice:
            break
        pick = next((o for o in choice["options"] if o.get("instance_id") == dead.instance_id), choice["options"][0])
        engine.rules.resolve_choice(str(pick["id"]))
        engine.resolve_until_stable()
    assert butler.zone == Zone.EXILE and dead.zone == Zone.HAND


def test_zul_ashur_lets_you_cast_a_zombie_from_the_graveyard_this_turn():
    engine = _game()
    p1, _ = engine.state.players
    zul = _card(engine, "Zul Ashur, Lich Lord")
    zul.summoning_sick = False
    zombie = _filler(engine, "Zed", "Creature — Zombie", power=1, toughness=1, zone=Zone.GRAVEYARD)
    elf = _filler(engine, "Elf", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    engine.state.current_step = "main1"
    engine.activate_ability(p1, zul, 0, targets=[zombie])
    engine.resolve_until_stable()
    assert engine.state.temp_graveyard_cast_permissions.get(zombie.instance_id) == "p1"
    assert elf.instance_id not in engine.state.temp_graveyard_cast_permissions
