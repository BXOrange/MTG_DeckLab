"""Real gameplay for the Temur Roar (Tarkir: Dragonstorm Commander) catalogue entries."""

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


def test_stormbreath_dragon_deals_damage_to_each_opponent_equal_to_their_hand():
    engine = _game(3)
    p1, p2, p3 = engine.state.players
    dragon = _card(engine, "Stormbreath Dragon")
    for i in range(3):
        _filler(engine, f"A{i}", "Sorcery", player="p2", zone=Zone.HAND)
    for i in range(5):
        _filler(engine, f"B{i}", "Sorcery", player="p3", zone=Zone.HAND)
    life = (p1.life, p2.life, p3.life)
    engine.state.fire_event(GameEvent(EventType.BECAME_MONSTROUS, controller_id="p1",
                                      instance_id=dragon.instance_id))
    engine.resolve_until_stable()
    assert (p1.life, p2.life, p3.life) == (life[0], life[1] - len(p2.hand), life[2] - len(p3.hand))
    assert (len(p2.hand), len(p3.hand)) == (3, 5) and p2.life == 17 and p3.life == 15


def test_nesting_dragon_makes_an_egg_that_hatches_into_a_pumpable_dragon():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Nesting Dragon")
    land = _filler(engine, "Some Land", "Land")
    _enter(engine, land)
    eggs = [o for o in engine.state.battlefield if o.name == "Dragon Egg"]
    assert len(eggs) == 1
    egg = eggs[0]
    continuous.recompute(engine.state)
    assert (egg.power, egg.toughness) == (0, 2) and combat.has(egg, "defender")
    # RULE 700.4: the egg dying creates the 2/2 flying Dragon with the pump ability.
    engine.rules.destroy(egg)
    engine.resolve_until_stable()
    dragons = [o for o in engine.state.battlefield if o.name == "Dragon" and o.is_token]
    assert len(dragons) == 1
    continuous.recompute(engine.state)
    d = dragons[0]
    assert (d.power, d.toughness) == (2, 2) and combat.has(d, "flying")
    assert d.activated_abilities


def _play_temple(engine, hand=(), battlefield=()):
    p1 = engine.state.player_by_id("p1")
    for i, (type_line, name) in enumerate(hand):
        _filler(engine, name, type_line, zone=Zone.HAND)
    for type_line, name in battlefield:
        _filler(engine, name, type_line)
    temple = _card(engine, "Temple of the Dragon Queen", zone=Zone.HAND)
    engine.state.current_step = "main1"
    engine.play_land(p1, temple)
    if engine.state.pending_choice and engine.state.pending_choice["kind"] == "choose_color":
        engine.rules.resolve_choice("R")  # "As this land enters, choose a color."
    return temple


def test_temple_of_the_dragon_queen_enters_tapped_with_no_dragon_to_reveal_or_control():
    engine = _game()
    temple = _play_temple(engine, hand=[("Creature — Elf", "Elf")])
    assert temple.tapped and engine.state.pending_choice is None


def test_temple_of_the_dragon_queen_asks_to_reveal_a_dragon_from_hand():
    engine = _game()
    temple = _play_temple(engine, hand=[("Creature — Dragon", "Whelp")])
    assert temple.tapped and engine.state.pending_choice["kind"] == "land_tapped_reveal"
    engine.rules.resolve_choice("reveal")
    assert not temple.tapped


def test_temple_of_the_dragon_queen_is_untapped_when_you_control_a_dragon():
    engine = _game()
    temple = _play_temple(engine, battlefield=[("Creature — Dragon", "Whelp")])
    assert not temple.tapped and engine.state.pending_choice is None


@pytest.mark.parametrize("name,types", [("Temple of the Dragon Queen", ["dragon"]), ("Fortified Beachhead", ["soldier"])])
def test_reveal_or_control_lands_are_parsed_as_a_reveal_land_with_a_control_skip(name, types):
    from mtg_analyzer.game import card_registry

    condition = card_registry.land_tap_condition(CardDatabase(DB_PATH).get_card(name))
    assert condition == {"kind": "reveal_types", "types": types, "or_control": True}


@pytest.mark.parametrize("power,draws,damage", [(3, 0, 0), (4, 1, 0), (6, 1, 1)])
def test_eshki_scales_with_the_power_of_each_creature_spell_cast(power, draws, damage):
    engine = _game()
    p1, p2 = engine.state.players
    eshki = _card(engine, "Eshki, Temur's Roar")
    spell = _filler(engine, "Big Guy", "Creature — Beast", power=power, toughness=power, zone=Zone.HAND)
    library = len(p1.library)
    life = p2.life
    _cast(engine, spell, {})
    continuous.recompute(engine.state)
    assert eshki.plus_one_counters == 1
    assert len(p1.library) == library - draws
    assert p2.life == life - (eshki.power if damage else 0)


def test_gadrak_makes_a_treasure_per_nontoken_creature_that_died_this_turn():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Gadrak, the Crown-Scourge")
    dead = [_filler(engine, "Mine", "Creature", player="p1", power=1, toughness=1),
            _filler(engine, "Theirs", "Creature", player="p2", power=1, toughness=1)]
    token = _filler(engine, "Soldier", "Token Creature — Soldier", power=1, toughness=1)
    token.is_token = True
    for obj in (*dead, token):
        engine.rules.destroy(obj)
    engine.resolve_until_stable()
    treasures = lambda: [o for o in engine.state.battlefield if o.name == "Treasure"]
    assert not treasures()
    engine.state.active_player_index = 0
    engine.state.current_step = "end"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id=p1.id, controller_id=p1.id))
    engine.resolve_until_stable()
    assert len(treasures()) == 2  # the token that died doesn't count


def test_gadrak_cannot_attack_without_four_artifacts():
    engine = _game()
    p1, _ = engine.state.players
    gadrak = _card(engine, "Gadrak, the Crown-Scourge")
    gadrak.summoning_sick = False
    engine.state.active_player_index = 0
    for i in range(3):
        _filler(engine, f"Rock{i}", "Artifact")
    continuous.recompute(engine.state)
    assert engine._can_attack(p1, gadrak) is False
    _filler(engine, "Rock3", "Artifact")
    continuous.recompute(engine.state)
    assert engine._can_attack(p1, gadrak) is True


def test_whirlwing_stormbrood_lets_you_flash_in_sorceries_and_dragons_only():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Whirlwing Stormbrood")
    engine.state.current_step = "combat_damage"  # not a main phase
    engine.state.active_player_index = 1
    sorcery = _filler(engine, "Sorcery", "Sorcery", zone=Zone.HAND)
    dragon = _filler(engine, "Whelp", "Creature — Dragon", power=1, toughness=1, zone=Zone.HAND)
    elf = _filler(engine, "Elf", "Creature — Elf", power=1, toughness=1, zone=Zone.HAND)
    assert continuous.has_standing_flash_permission(engine.state, p1, sorcery.card)
    assert continuous.has_standing_flash_permission(engine.state, p1, dragon.card)
    assert not continuous.has_standing_flash_permission(engine.state, p1, elf.card)


def test_dynamic_soar_omen_puts_three_counters_then_shuffles_the_card_into_the_library():
    engine = _game()
    p1, _ = engine.state.players
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    card = _card(engine, "Whirlwing Stormbrood // Dynamic Soar", zone=Zone.HAND)
    p1.mana_pool.add_many({"G": 1, "C": 2})
    engine.state.current_step = "main1"
    engine.cast_spell(p1, card, face="back", targets=[bear], target_groups=None)
    engine.resolve_until_stable()
    assert bear.plus_one_counters == 3
    assert card.zone == Zone.LIBRARY and card in p1.library  # RULE 720.3d, not exiled/graveyard
    assert not card.adventure_castable


def test_hammerhead_tyrant_bounces_only_permanents_up_to_the_cast_spells_mana_value():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Hammerhead Tyrant")
    cheap = _filler(engine, "Cheap", "Artifact", player="p2", mv=2)
    pricey = _filler(engine, "Pricey", "Artifact", player="p2", mv=5)
    land = _filler(engine, "Land", "Land", player="p2")
    spell = _filler(engine, "Three Drop", "Sorcery", mv=3, zone=Zone.HAND)
    p1.mana_pool.add_many({"C": 3})
    engine.state.current_step = "main1"
    engine.cast_spell(p1, spell, targets=None, target_groups=None)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == "trigger_target", (choice, [e.__class__.__name__ for e in engine.state.stack])
    offered = {o.get("instance_id") for o in choice["options"]}
    assert cheap.instance_id in offered and pricey.instance_id not in offered and land.instance_id not in offered
    engine.rules.resolve_choice(str(cheap.instance_id))
    engine.resolve_until_stable()
    assert cheap.zone == Zone.HAND and pricey.zone == Zone.BATTLEFIELD


def test_broodcaller_scourge_puts_a_permanent_up_to_the_damage_dealt_by_dragons_onto_the_battlefield():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Broodcaller Scourge")
    dragon = _filler(engine, "Whelp", "Creature — Dragon", power=3, toughness=3)
    bear = _filler(engine, "Bear", "Creature — Bear", power=9, toughness=9)
    cheap = _filler(engine, "Cheap", "Artifact", mv=3, zone=Zone.HAND)
    pricey = _filler(engine, "Pricey", "Artifact", mv=4, zone=Zone.HAND)

    def hit(*contributors):
        engine.state.fire_event(GameEvent(
            EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER, player_id="p1", target_id="p2", is_player=True,
            contributor_ids=[c.instance_id for c, _ in contributors],
            contributor_amounts=[a for _, a in contributors],
        ))
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()

    hit((bear, 9))  # no Dragon among the contributors — nothing triggers
    assert engine.state.pending_choice is None
    hit((dragon, 3), (bear, 9))  # only the Dragons' 3 damage counts, not the Bear's 9
    choice = engine.state.pending_choice
    assert choice is not None
    offered = {o.get("instance_id") for o in choice["options"]}
    assert cheap.instance_id in offered and pricey.instance_id not in offered
    engine.rules.resolve_choice(str(cheap.instance_id))
    engine.resolve_until_stable()
    assert cheap.zone == Zone.BATTLEFIELD and pricey.zone == Zone.HAND


def test_deceptive_frostkite_copies_only_a_power_four_creature_and_gains_dragon_and_flying():
    engine = _game()
    p1, _ = engine.state.players
    small = _filler(engine, "Small", "Creature — Bear", power=3, toughness=3)
    big = _filler(engine, "Big Bear", "Creature — Bear", power=5, toughness=5)
    theirs = _filler(engine, "Their Giant", "Creature — Giant", player="p2", power=7, toughness=7)
    frostkite = _card(engine, "Deceptive Frostkite", zone=Zone.HAND)
    _cast(engine, frostkite, {"U": 2})
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == "enter_as_copy"
    offered = {o.get("instance_id") for o in choice["options"]}
    assert big.instance_id in offered
    assert small.instance_id not in offered and theirs.instance_id not in offered
    engine.rules.resolve_choice(str(big.instance_id))
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    assert frostkite.zone == Zone.BATTLEFIELD and frostkite.name == "Big Bear"
    assert (frostkite.power, frostkite.toughness) == (5, 5)
    assert continuous.has_subtype(frostkite, "Dragon") and continuous.has_subtype(frostkite, "Bear")
    assert combat.has(frostkite, "flying")


def test_sarkhan_soul_aflame_becomes_a_legendary_copy_of_an_entering_dragon_until_end_of_turn():
    engine = _game()
    p1, _ = engine.state.players
    sarkhan = _card(engine, "Sarkhan, Soul Aflame")
    dragon = _filler(engine, "Big Dragon", "Creature — Dragon", power=5, toughness=5)
    _enter(engine, dragon)
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == "trigger_target", choice  # "you may have ~ become a copy"
    engine.rules.resolve_choice("do")
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    assert sarkhan.name == "Sarkhan, Soul Aflame"
    assert (sarkhan.power, sarkhan.toughness) == (5, 5)
    assert "legendary" in sarkhan.card.type_line.lower() and continuous.has_subtype(sarkhan, "Dragon")
    engine._step_cleanup()  # RULE 514.2 — "until end of turn" ends
    continuous.recompute(engine.state)
    assert sarkhan.name == "Sarkhan, Soul Aflame" and (sarkhan.power, sarkhan.toughness) == (2, 4)
    assert not continuous.has_subtype(sarkhan, "Dragon")


def test_hellkite_courser_borrows_the_commander_with_haste_and_returns_it_at_the_end_step():
    engine = _game()
    p1, _ = engine.state.players
    commander = _filler(engine, "My Commander", "Legendary Creature — Elf", power=3, toughness=3,
                        zone=Zone.COMMAND)
    commander.is_commander = True
    courser = _card(engine, "Hellkite Courser")
    _enter(engine, courser)
    choice = engine.state.pending_choice
    assert choice and commander.instance_id in {o.get("instance_id") for o in choice["options"]}
    engine.rules.resolve_choice(str(commander.instance_id))
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    assert commander.zone == Zone.BATTLEFIELD and combat.has(commander, "haste")
    for _ in range(20):  # the delayed trigger fires as the step loop reaches the next end step (RULE 603.7)
        engine.advance_step()
        if engine.state.current_step == "end":
            break
    engine.resolve_until_stable()
    assert commander.zone == Zone.COMMAND and commander in p1.command


def test_hellkite_courser_with_no_commander_in_the_command_zone_does_nothing():
    engine = _game()
    courser = _card(engine, "Hellkite Courser")
    _enter(engine, courser)
    assert engine.state.pending_choice is None


def test_opportunistic_dragon_steals_a_human_or_artifact_and_strips_it_while_the_dragon_stays():
    engine = _game()
    p1, p2 = engine.state.players
    human = _filler(engine, "Their Human", "Creature — Human Soldier", player="p2", power=2, toughness=2,
                    oracle_text="Flying")
    elf = _filler(engine, "Their Elf", "Creature — Elf", player="p2", power=2, toughness=2)
    rock = _filler(engine, "Their Rock", "Artifact", player="p2")
    dragon = _card(engine, "Opportunistic Dragon")
    _enter(engine, dragon)
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == "trigger_target"
    offered = {o.get("instance_id") for o in choice["options"]}
    assert human.instance_id in offered and rock.instance_id in offered and elf.instance_id not in offered
    engine.rules.resolve_choice(str(human.instance_id))
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    assert human.controller_id == "p1"
    assert combat.has(human, "cant_attack") and combat.has(human, "cant_block")
    engine.rules.destroy(dragon)  # "for as long as ~ remains on the battlefield"
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    assert human.controller_id == "p2" and not combat.has(human, "cant_attack")


def _advance_to(engine, step):
    for _ in range(30):
        if engine.state.current_step == step:
            return
        engine.advance_step()
    raise AssertionError(f"{step} not reached")


def _hellkite_game(players=3):
    engine = _game(players)
    hellkite = _card(engine, "Territorial Hellkite")
    hellkite.summoning_sick = False
    engine.state.active_player_index = 0
    engine.state.current_step = "main1"
    return engine, hellkite


def test_territorial_hellkite_must_attack_a_random_opponent_it_did_not_attack_last_combat():
    engine, hellkite = _hellkite_game()
    p1, p2, p3 = engine.state.players
    hellkite.last_combat_attacked_ids = {"p2"}
    _advance_to(engine, "begin_combat")
    engine.resolve_until_stable()
    assert hellkite.must_attack_player_id == "p3"
    _advance_to(engine, "declare_attackers")
    with pytest.raises(ValueError):  # not declared at all
        engine.advance_step()
    engine.declare_attackers(p1, [{"attacker": hellkite, "defender": {"kind": "player", "id": "p2", "label": "1"}}])
    with pytest.raises(ValueError):  # attacking p2 although p3 was required and attackable
        engine.advance_step()
    hellkite.attacking = False
    hellkite.tapped = False
    engine.declare_attackers(p1, [{"attacker": hellkite, "defender": {"kind": "player", "id": "p3", "label": "2"}}])
    assert hellkite.attacking and engine._defending_player(hellkite.combat_defender).id == "p3"
    engine.advance_step()  # requirement satisfied


def test_territorial_hellkite_taps_when_it_attacked_every_opponent_last_combat():
    engine, hellkite = _hellkite_game(players=2)
    hellkite.last_combat_attacked_ids = {"p2"}
    _advance_to(engine, "begin_combat")
    engine.resolve_until_stable()
    assert hellkite.tapped and hellkite.must_attack_player_id is None


def test_territorial_hellkite_remembers_whom_it_attacked_in_its_last_combat():
    engine, hellkite = _hellkite_game(players=3)
    p1, p2, p3 = engine.state.players
    _advance_to(engine, "begin_combat")
    engine.resolve_until_stable()
    target = hellkite.must_attack_player_id
    assert target in {"p2", "p3"}
    _advance_to(engine, "declare_attackers")
    engine.declare_attackers(p1, [{"attacker": hellkite, "defender": {"kind": "player", "id": target, "label": "x"}}])
    _advance_to(engine, "main2")  # past end of combat
    assert hellkite.last_combat_attacked_ids == {target} and hellkite.must_attack_player_id is None


@pytest.mark.parametrize("type_line,copies", [("Creature — Dragon", 2), ("Creature — Elf", 1)])
def test_reflections_of_littjara_copies_only_spells_of_the_chosen_type(type_line, copies):
    engine = _game()
    p1, _ = engine.state.players
    reflections = _card(engine, "Reflections of Littjara")
    reflections.chosen_type = "Dragon"
    spell = _filler(engine, "Guest", type_line, power=2, toughness=2, zone=Zone.HAND)
    _cast(engine, spell, {})
    guests = [o for o in engine.state.battlefield if o.name == "Guest"]
    assert len(guests) == copies
    assert sum(1 for o in guests if o.is_token) == copies - 1  # the copy is a token (RULE 707.10f)


def _stock_library(engine, player_id, cards):
    player = engine.state.player_by_id(player_id)
    player.library.clear()
    for name, type_line in cards:  # listed top-first
        _filler(engine, name, type_line, player=player_id, power=1 if "Creature" in type_line else None,
                toughness=1 if "Creature" in type_line else None, zone=Zone.LIBRARY)
    player.library.reverse()  # the top of the library is the list end


@pytest.mark.parametrize("votes,creatures,hand_put", [(("wild", "wild"), 2, 0), (("free", "free"), 0, 1), (("wild", "free"), 1, 1)])
def test_selvalas_stampede_scales_each_half_with_its_votes(votes, creatures, hand_put):
    engine = _game()
    p1, _ = engine.state.players
    _stock_library(engine, "p1", [("Land A", "Land"), ("Bear A", "Creature — Bear"), ("Rock", "Artifact"),
                                  ("Bear B", "Creature — Bear"), ("Land B", "Land")])
    card = _card(engine, "Selvala's Stampede", zone=Zone.HAND)
    held = _filler(engine, "Held Artifact", "Artifact", zone=Zone.HAND)
    before = len(p1.library)
    p1.mana_pool.add_many({"G": 2, "C": 4})
    engine.state.current_step = "main1"
    engine.cast_spell(p1, card, targets=None, target_groups=None)
    engine.resolve_until_stable()
    for vote in votes:  # APNAP: p1 votes first, then p2
        choice = engine.state.pending_choice
        assert choice and choice["kind"] == "vote", choice
        engine.rules.resolve_choice({"wild": "0", "free": "1"}[vote])
        engine.resolve_until_stable()
    while engine.state.pending_choice:  # "you may put a permanent card from your hand" — take it
        options = engine.state.pending_choice["options"]
        engine.rules.resolve_choice(str(options[0]["id"]))
        engine.resolve_until_stable()
    bears = [o for o in engine.state.battlefield if o.name.startswith("Bear")]
    assert len(bears) == creatures
    assert (held.zone == Zone.BATTLEFIELD) == bool(hand_put)
    if creatures:
        # only the revealed creatures left the library; everything else (revealed or not) is still in it
        assert len(p1.library) == before - creatures
        assert sum(1 for o in p1.library if o.name.startswith("Bear")) == 2 - creatures
