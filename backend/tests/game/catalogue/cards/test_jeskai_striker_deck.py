"""Real gameplay for the Jeskai Striker (Tarkir: Dragonstorm Commander) catalogue entries."""

import pytest

from mtg_analyzer.config import DB_PATH
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


def _bolt(engine, zone=Zone.GRAVEYARD, player="p1", keywords=None):
    card = Card(id="Bolt", name="Bolt", type_line="Instant", is_instant=True, keywords=keywords or [],
                mana_cost_string="{R}", converted_mana_cost=1,
                oracle_text="Bolt deals 3 damage to any target.")
    obj = GameObject(card, owner_id=player, zone=zone)
    bind_from_catalogue(obj)
    engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def test_lier_gives_graveyard_instants_flashback_at_their_mana_cost():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    bolt = _bolt(engine)
    assert not engine._graveyard_cast_permission(p1, bolt)
    _card(engine, "Lier, Disciple of the Drowned")
    assert engine._graveyard_cast_permission(p1, bolt)
    creature = GameObject(Card(id="Bear", name="Bear", type_line="Creature", is_creature=True,
                               mana_cost_string="{1}{G}", converted_mana_cost=2, power=2, toughness=2),
                          owner_id="p1", zone=Zone.GRAVEYARD)
    engine.state.player_by_id("p1").add_to_zone(creature, Zone.GRAVEYARD)
    assert not engine._graveyard_cast_permission(p1, creature)  # only instants and sorceries


def test_lier_makes_every_spell_uncounterable_for_both_players():
    engine = _game()
    mine, theirs = _bolt(engine, Zone.HAND, "p1"), _bolt(engine, Zone.HAND, "p2")
    assert not engine.rules._is_cant_be_countered(mine)
    assert not engine.rules._is_cant_be_countered(theirs)
    _card(engine, "Lier, Disciple of the Drowned")
    assert engine.rules._is_cant_be_countered(mine)
    assert engine.rules._is_cant_be_countered(theirs)


def _library_card(engine, name, type_line, mv, player="p1", **kw):
    card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                is_land="Land" in type_line, mana_cost_string="{%d}" % mv if mv else "", **kw)
    obj = GameObject(card, owner_id=player, zone=Zone.LIBRARY)
    bind_from_catalogue(obj)
    engine.state.player_by_id(player).add_to_zone(obj, Zone.LIBRARY)
    return obj


def _attack_with_velomachus(engine):
    velo = _card(engine, "Velomachus Lorehold")
    velo.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(engine.state.active_player, [velo])
    engine.resolve_until_stable()
    return velo


@pytest.mark.parametrize("decline", [True, False])
def test_velomachus_offers_only_cheap_instants_and_sorceries_then_bottoms_the_rest(decline):
    engine = _game()
    p1, p2 = engine.state.players
    p1.library.clear()
    deep = _library_card(engine, "Deep", "Creature", 2, is_creature=True, power=1, toughness=1)
    bolt = _library_card(engine, "Cheap Bolt", "Instant", 1, oracle_text="Cheap Bolt deals 3 damage to any target.")
    big = _library_card(engine, "Big Sorcery", "Sorcery", 9)
    land = _library_card(engine, "Top Land", "Land", 0)
    # library top is the end of the list: land, big, bolt, ... then deep stays below the 7 inspected cards
    p1.library.remove(deep)
    p1.library.insert(0, deep)
    p1.library.remove(bolt)
    p1.library.append(bolt)  # topmost
    velo = _attack_with_velomachus(engine)
    assert velo.power >= 5
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == "play_during_resolution"
    assert choice["instance_ids"] == [bolt.instance_id]  # land, 9-drop and the creature are not offered
    if decline:
        engine.resolve_pending_choice("decline")
        engine.resolve_until_stable()
        assert bolt in p1.library
    else:
        engine.play_resolution_card(p1, bolt, targets=[p2])
        engine.resolve_until_stable()
        assert p2.life == 17 and bolt in p1.graveyard
    # everything not cast went back to the library; nothing is left in exile
    assert not p1.exile
    assert big in p1.library and land in p1.library


def test_velomachus_with_nothing_castable_just_bottoms_the_seven():
    engine = _game()
    p1, _ = engine.state.players
    p1.library.clear()
    cards = [_library_card(engine, f"Land {i}", "Land", 0) for i in range(8)]
    _attack_with_velomachus(engine)
    assert not engine.state.pending_choice
    assert len(p1.library) == 8 and not p1.exile


def _stack_bolt(engine):
    """p2 casts a Bolt at p1; it sits on the stack."""
    p2 = engine.state.player_by_id("p2")
    bolt = _bolt(engine, Zone.HAND, "p2")
    p2.mana_pool.add("R", 1)
    engine.cast_spell(p2, bolt, targets=[engine.state.player_by_id("p1")], target_groups=None)
    return bolt


@pytest.mark.parametrize("accept", [True, False])
def test_transcendent_dragon_counters_exiles_and_offers_a_free_cast(accept):
    engine = _game()
    p1, p2 = engine.state.players
    bolt = _stack_bolt(engine)
    dragon = _card(engine, "Transcendent Dragon", zone=Zone.HAND)
    p1.mana_pool.add("U", 6)
    engine.cast_spell(p1, dragon, targets=None, target_groups=None)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    if choice and choice.get("kind") != "play_during_resolution":  # the trigger's own target pick
        engine.resolve_pending_choice(str(bolt.instance_id))
        engine.resolve_until_stable()
        choice = engine.state.pending_choice
    assert bolt in p2.exile and bolt not in p2.graveyard
    assert choice and choice["kind"] == "play_during_resolution" and choice["player_id"] == "p1"
    if accept:
        engine.play_resolution_card(p1, bolt, targets=[p2])
        engine.resolve_until_stable()
        assert p2.life == 17 and bolt not in p2.exile
    else:
        engine.resolve_pending_choice("decline")
        engine.resolve_until_stable()
        assert bolt in p2.exile and p1.life == 20


def test_transcendent_dragon_does_nothing_when_not_cast():
    engine = _game()
    p1, p2 = engine.state.players
    bolt = _stack_bolt(engine)
    dragon = _card(engine, "Transcendent Dragon")  # put onto the battlefield, not cast
    engine.resolve_until_stable()
    assert not engine.state.pending_choice or engine.state.pending_choice.get("kind") != "play_during_resolution"
    assert bolt not in p2.exile


def _creature(engine, player, name="Victim", keywords=None):
    card = Card(id=name, name=name, type_line="Creature", is_creature=True, power=2, toughness=2,
                keywords=keywords or [])
    obj = GameObject(card, owner_id=player, zone=Zone.BATTLEFIELD)
    obj.controller_id = player
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def test_transforming_flourish_destroys_then_its_controller_digs_and_may_cast_free():
    engine = _game()
    p1, p2 = engine.state.players
    victim = _creature(engine, "p2")
    p2.library.clear()
    hit = _library_card(engine, "Their Hit", "Instant", 1, "p2", oracle_text="Draw a card.")
    flourish = _card(engine, "Transforming Flourish", zone=Zone.HAND)
    p1.mana_pool.add("R", 3)
    engine.cast_spell(p1, flourish, targets=[victim], target_groups=None)
    engine.resolve_until_stable()
    if engine.state.pending_choice and engine.state.pending_choice.get("kind") == "composite_optional":
        engine.resolve_pending_choice("no")  # decline the demonstrate copy
        engine.resolve_until_stable()
    assert victim in p2.graveyard
    assert hit.zone == Zone.EXILE and hit in p2.exile
    # the destroyed permanent's controller (not the caster) holds the free-cast window
    assert hit.instance_id in engine.state.free_cast_instance_ids
    assert engine.state.temp_play_permission_player[hit.instance_id] == "p2"


def test_transforming_flourish_digs_nothing_if_nothing_was_destroyed():
    engine = _game()
    p1, p2 = engine.state.players
    p2.library.clear()
    hit = _library_card(engine, "Their Hit", "Instant", 1, "p2")
    victim = _creature(engine, "p2", keywords=["Indestructible"])
    flourish = _card(engine, "Transforming Flourish", zone=Zone.HAND)
    p1.mana_pool.add("R", 3)
    engine.cast_spell(p1, flourish, targets=[victim], target_groups=None)
    engine.resolve_until_stable()
    if engine.state.pending_choice and engine.state.pending_choice.get("kind") == "composite_optional":
        engine.resolve_pending_choice("no")
        engine.resolve_until_stable()
    assert victim in engine.state.battlefield and hit in p2.library


def test_demonstrate_copies_for_the_caster_and_an_opponent_when_accepted():
    engine = _game()
    p1, p2 = engine.state.players
    bolt = _bolt(engine, Zone.HAND, "p1", keywords=["Demonstrate"])
    p1.mana_pool.add("R", 1)
    engine.cast_spell(p1, bolt, targets=[p2], target_groups=None)
    engine.resolve_until_stable()
    assert engine.state.pending_choice and engine.state.pending_choice["kind"] == "composite_optional"
    engine.resolve_pending_choice("yes")
    engine.resolve_until_stable()
    while engine.state.pending_choice and engine.state.pending_choice["kind"] == "copy_targets":
        engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    # original + own copy + the opponent's copy, all aimed at p2 → 3 × 3 damage
    assert p2.life == 11


def test_an_indestructible_permanent_is_not_destroyed_by_a_destroy_effect():
    """RULE 702.12b — `RulesEngine.destroy` itself, not just the lethal-damage SBA, honours it."""
    engine = _game()
    victim = _creature(engine, "p2", keywords=["Indestructible"])
    engine.rules.destroy(victim)
    assert victim in engine.state.battlefield


def test_sublime_epiphany_is_fully_modeled_with_all_five_modes():
    from mtg_analyzer.parser.oracle.gate import parse_oracle

    result = parse_oracle(CardDatabase(DB_PATH).get_card("Sublime Epiphany"))
    assert result.modeled, result.unclaimed
    (spec,) = result.specs
    assert spec.modes["at_least"] and len(spec.modes["options"]) == 5
    assert spec.modes["options"][1][0].type == "counter_ability"


def test_sublime_epiphany_bounce_and_draw_modes_together():
    engine = _game()
    p1, p2 = engine.state.players
    for _ in range(3):
        _library_card(engine, "Filler", "Land", 0)
    epiphany = _card(engine, "Sublime Epiphany", zone=Zone.HAND)
    victim = _creature(engine, "p2")
    p1.mana_pool.add_many({"U": 2, "C": 4})
    hand_before = len(p1.hand)
    engine.cast_spell(p1, epiphany, mode=(2, 4), targets=None,
                      target_groups=[[victim], [p1]])
    engine.resolve_until_stable()
    assert victim in p2.hand and victim not in engine.state.battlefield
    assert len(p1.hand) == hand_before - 1 + 1  # the spell left the hand, one card drawn


def _sorcery_on_stack(engine, mv):
    card = Card(id=f"S{mv}", name="Bolt", type_line="Instant", is_instant=True,
                mana_cost_string="{%d}" % mv, converted_mana_cost=mv,
                oracle_text="Bolt deals 3 damage to any target.")
    obj = GameObject(card, owner_id="p2", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p2 = engine.state.player_by_id("p2")
    p2.add_to_zone(obj, Zone.HAND)
    p2.mana_pool.add("C", mv)
    engine.cast_spell(p2, obj, targets=[engine.state.player_by_id("p1")], target_groups=None)
    return obj


def test_expansion_copies_only_spells_with_mana_value_four_or_less():
    from mtg_analyzer.game.targeting import legal_targets

    engine = _game()
    p1, p2 = engine.state.players
    cheap, pricey = _sorcery_on_stack(engine, 4), _sorcery_on_stack(engine, 5)
    card = _card(engine, "Expansion // Explosion", zone=Zone.HAND)
    (effect,) = card.spell_effects
    spec = effect.target_spec
    found = legal_targets(engine.state, "p1", spec, source=card)
    ids = {t.get("instance_id") for t in found}
    assert cheap.instance_id in ids and pricey.instance_id not in ids, found


def test_expansion_copy_resolves_for_the_caster():
    engine = _game()
    p1, p2 = engine.state.players
    _sorcery_on_stack(engine, 2)
    stack_target = engine.state.stack[-1]
    card = _card(engine, "Expansion // Explosion", zone=Zone.HAND)
    p1.mana_pool.add("R", 2)
    engine.cast_spell(p1, card, targets=[stack_target.obj], target_groups=None)
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "copy_targets"
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert p1.life == 20 - 3 - 3  # the original and the copy both hit p1 (the original's target is kept)


def test_explosion_back_half_deals_x_and_draws_x():
    engine = _game()
    p1, p2 = engine.state.players
    for _ in range(4):
        _library_card(engine, "Filler", "Land", 0)
    card = _card(engine, "Expansion // Explosion", zone=Zone.HAND)
    p1.mana_pool.add_many({"U": 2, "R": 2, "C": 2})
    before = len(p1.hand)
    engine.cast_spell(p1, card, x=2, face="back", targets=None, target_groups=[[p2], [p1]])
    engine.resolve_until_stable()
    assert p2.life == 18 and len(p1.hand) == before - 1 + 2


def _gold(engine, player):
    return [o for o in engine.state.battlefield if o.card.name == "Gold" and o.controller_id == player.id]


def _attack(engine, attacker_player):
    attacker = _creature(engine, attacker_player.id, "Attacker")
    attacker.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(attacker_player, [attacker])
    engine._fire_player_attacked_events()  # fired by the turn loop once declaration locks in
    engine.resolve_until_stable()


def test_curse_of_opulence_gives_gold_to_its_controller_and_the_attacking_opponent():
    engine = _game()
    p1, p2 = engine.state.players  # p1 is active and attacks p2, the enchanted player
    curse = _card(engine, "Curse of Opulence", player="p2")
    curse.attached_to = "p2"
    _attack(engine, p1)
    assert len(_gold(engine, p2)) == 1 and len(_gold(engine, p1)) == 1


def test_curse_of_opulence_controller_attacking_the_cursed_player_gets_one_gold_only():
    engine = _game()
    p1, p2 = engine.state.players
    curse = _card(engine, "Curse of Opulence", player="p1")
    curse.attached_to = "p2"
    _attack(engine, p1)
    assert len(_gold(engine, p1)) == 1 and not _gold(engine, p2)


def test_curse_of_opulence_ignores_attacks_on_other_players():
    engine = _game()
    p1, p2 = engine.state.players
    curse = _card(engine, "Curse of Opulence", player="p2")
    curse.attached_to = "p1"  # enchants the attacker, not the defender
    _attack(engine, p1)
    assert not _gold(engine, p1) and not _gold(engine, p2)


def _spell(engine, name, type_line, mv, player="p1", zone=Zone.HAND):
    card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                is_creature="Creature" in type_line,
                mana_cost_string="{%d}" % mv if mv else "", oracle_text="Draw a card.")
    obj = GameObject(card, owner_id=player, zone=zone)
    bind_from_catalogue(obj)
    engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _baral_cast(engine, first_mv=3, hand=()):
    p1 = engine.state.player_by_id("p1")
    _card(engine, "Baral and Kari Zev")
    engine.state.current_step = "main1"
    for spec in hand:
        _spell(engine, *spec)
    trigger = _spell(engine, "First Spell", "Instant", first_mv)
    p1.mana_pool.add("C", first_mv)
    engine.cast_spell(p1, trigger, targets=None, target_groups=None)
    engine.resolve_until_stable()
    return p1


def test_baral_and_kari_zev_offers_a_cheaper_card_sharing_a_type_else_makes_ragavan():
    engine = _game()
    p1 = _baral_cast(engine, 3, hand=[("Cheap Instant", "Instant", 2), ("Same Value", "Instant", 3),
                                      ("Cheap Creature", "Creature", 1), ("Cheap Sorcery", "Sorcery", 1)])
    choice = engine.state.pending_choice
    assert choice and choice.get("action") == "grant_free_cast"
    offered = {o["label"] if "label" in o else o.get("name") for o in choice["options"] if o.get("id") != "decline"}
    names = {engine.state.find_object(int(o["id"])).name for o in choice["options"] if str(o.get("id", "")).isdigit()}
    # strictly lesser value AND shares a card type (instant/sorcery with the cast Instant... only Instant shares)
    assert names == {"Cheap Instant"}, (names, offered)


def test_baral_and_kari_zev_declining_creates_first_mate_ragavan():
    engine = _game()
    p1 = _baral_cast(engine, 3, hand=[("Cheap Instant", "Instant", 2)])
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    tokens = [o for o in engine.state.battlefield if o.card.name == "First Mate Ragavan"]
    assert len(tokens) == 1 and tokens[0].controller_id == "p1"
    assert (tokens[0].power, tokens[0].toughness) == (2, 1)


def test_baral_and_kari_zev_with_nothing_eligible_makes_the_token_without_asking():
    engine = _game()
    _baral_cast(engine, 1, hand=[("Pricey Instant", "Instant", 4)])
    assert not engine.state.pending_choice
    assert any(o.card.name == "First Mate Ragavan" for o in engine.state.battlefield)


def test_baral_and_kari_zev_only_triggers_on_the_first_instant_or_sorcery_each_turn():
    engine = _game()
    p1 = _baral_cast(engine, 1, hand=[])
    base = sum(o.card.name == "First Mate Ragavan" for o in engine.state.battlefield)
    second = _spell(engine, "Second Spell", "Instant", 1)
    p1.mana_pool.add("C", 1)
    engine.cast_spell(p1, second, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert sum(o.card.name == "First Mate Ragavan" for o in engine.state.battlefield) == base == 1
