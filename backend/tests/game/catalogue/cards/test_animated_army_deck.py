"""Real gameplay for the Animated Army (Bloomburrow Commander) catalogue entries."""

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


def _filler(engine, name="Filler", type_line="Creature", player="p1", mv=0, power=None, toughness=None, **kw):
    card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                is_creature="Creature" in type_line, is_land="Land" in type_line,
                power=power, toughness=toughness, mana_cost_string="{%d}" % mv if mv else "", **kw)
    obj = GameObject(card, owner_id=player, zone=Zone.BATTLEFIELD)
    obj.controller_id = player
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _treasures(engine, player):
    return [o for o in engine.state.battlefield if o.card.name == "Treasure" and o.controller_id == player]


def test_prosperous_bandit_makes_that_many_tapped_treasures_on_combat_damage():
    engine = _game()
    p1, p2 = engine.state.players
    bandit = _card(engine, "Prosperous Bandit")
    engine.rules.deal_damage(p2, 3, source=bandit, combat=True)
    engine.resolve_until_stable()
    made = _treasures(engine, "p1")
    assert len(made) == 3 and all(t.tapped for t in made)


def test_prosperous_bandit_ignores_noncombat_damage():
    engine = _game()
    p1, p2 = engine.state.players
    bandit = _card(engine, "Prosperous Bandit")
    engine.rules.deal_damage(p2, 3, source=bandit, combat=False)
    engine.resolve_until_stable()
    assert not _treasures(engine, "p1")


@pytest.mark.parametrize("pay_offspring", [False, True])
def test_prosperous_bandit_offspring_makes_a_1_1_token_copy_only_when_paid(pay_offspring):
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    bandit = _card(engine, "Prosperous Bandit", zone=Zone.HAND)
    actions = [a for a in engine.legal_actions(p1) if a.get("instance_id") == bandit.instance_id]
    p1.mana_pool.add_many({"R": 1, "C": 3})
    action = next(a for a in engine.legal_actions(p1) if a.get("instance_id") == bandit.instance_id)
    assert action["has_kicker"] and action["kicker_cost"] == "{1}" and action["kicker_keyword"] == "offspring"
    engine.cast_spell(p1, bandit, kicked=1 if pay_offspring else 0, targets=None, target_groups=None)
    engine.resolve_until_stable()
    copies = [o for o in engine.state.battlefield if o.card.name == "Prosperous Bandit"]
    assert len(copies) == (2 if pay_offspring else 1)
    if pay_offspring:
        token = next(o for o in copies if o is not bandit)
        assert token.is_token and (token.power, token.toughness) == (1, 1)
        assert len([o for o in engine.state.battlefield if o.card.name == "Prosperous Bandit"]) == 2  # no chain


def test_decimate_destroys_one_of_each_of_its_four_targets():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    art = _filler(engine, "Their Artifact", "Artifact", "p2")
    cre = _filler(engine, "Their Creature", "Creature", "p2", power=2, toughness=2)
    ench = _filler(engine, "Their Enchantment", "Enchantment", "p2")
    land = _filler(engine, "Their Land", "Land", "p2")
    bystander = _filler(engine, "Bystander", "Creature", "p2", power=1, toughness=1)
    decimate = _card(engine, "Decimate", zone=Zone.HAND)
    p1.mana_pool.add_many({"R": 1, "G": 1, "C": 2})
    engine.cast_spell(p1, decimate, targets=[art, cre, ench, land], target_groups=[[art], [cre], [ench], [land]])
    engine.resolve_until_stable()
    for victim in (art, cre, ench, land):
        assert victim in p2.graveyard
    assert bystander in engine.state.battlefield


def test_wildsear_gives_enchantments_cast_from_hand_cascade_only():
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    _card(engine, "Wildsear, Scouring Maw")
    p1.library.clear()
    hit = GameObject(Card(id="Hit", name="Hit", type_line="Sorcery", is_sorcery=True,
                          converted_mana_cost=1, mana_cost_string="{1}", oracle_text="Draw a card."),
                     owner_id="p1", zone=Zone.LIBRARY)
    bind_from_catalogue(hit)
    p1.add_to_zone(hit, Zone.LIBRARY)

    def cast(type_line, zone=Zone.HAND):
        card = Card(id="Spell", name="Spell", type_line=type_line, converted_mana_cost=3,
                    is_instant="Instant" in type_line,
                    mana_cost_string="{3}")
        obj = GameObject(card, owner_id="p1", zone=zone)
        bind_from_catalogue(obj)
        p1.add_to_zone(obj, zone)
        p1.mana_pool.add("C", 3)
        engine.cast_spell(p1, obj, targets=None, target_groups=None)
        engine.resolve_until_stable()

    cast("Instant")
    assert hit in p1.library  # an instant gets no cascade
    cast("Enchantment")
    assert hit not in p1.library  # the enchantment cascaded into the library hit


def test_goreclaw_discounts_only_creature_spells_with_power_four_or_more():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Goreclaw, Terror of Qal Sisma")
    engine.state.current_step = "main1"

    def cost_of(type_line, power):
        card = Card(id="S", name="S", type_line=type_line, is_creature="Creature" in type_line,
                    converted_mana_cost=5, mana_cost_string="{5}", power=power,
                    toughness=power)
        obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
        bind_from_catalogue(obj)
        p1.add_to_zone(obj, Zone.HAND)
        return engine.effective_cast_cost(p1, obj).converted_mana_cost

    assert cost_of("Creature", 4) == 3
    assert cost_of("Creature", 3) == 5
    assert cost_of("Artifact", None) == 5


def test_goreclaw_attack_pumps_and_tramples_only_power_four_or_more_creatures():
    engine = _game()
    p1, _ = engine.state.players
    goreclaw = _card(engine, "Goreclaw, Terror of Qal Sisma")
    big = _filler(engine, "Big", power=5, toughness=5)
    small = _filler(engine, "Small", power=2, toughness=2)
    goreclaw.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [goreclaw])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    from mtg_analyzer.game import combat

    assert (goreclaw.power, goreclaw.toughness) == (5, 4)  # printed 4/3, power >= 4 so it pumps itself
    assert (big.power, big.toughness) == (6, 6) and combat.has(big, "trample")
    assert (small.power, small.toughness) == (2, 2) and not combat.has(small, "trample")


def _end_step(engine):
    for _ in range(20):
        engine.advance_step()
        if engine.state.current_step == "end":
            return
    raise AssertionError("end step not reached")


def test_thickest_in_the_thicket_adds_counters_equal_to_the_targets_power():
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    victim = _filler(engine, "Bear", power=3, toughness=3)
    thicket = _card(engine, "Thickest in the Thicket", zone=Zone.HAND)
    p1.mana_pool.add_many({"G": 2, "C": 3})
    engine.cast_spell(p1, thicket, targets=None, target_groups=None)
    engine.resolve_until_stable()
    if engine.state.pending_choice:
        engine.resolve_pending_choice(str(victim.instance_id))
        engine.resolve_until_stable()
    assert victim.plus_one_counters == 3


@pytest.mark.parametrize("opponent_power,draws", [(2, True), (4, False), (3, True)])
def test_thickest_in_the_thicket_draws_only_with_the_greatest_power(opponent_power, draws):
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Thickest in the Thicket")
    _filler(engine, "Mine", power=3, toughness=3)
    _filler(engine, "Theirs", player="p2", power=opponent_power, toughness=2)
    before = len(p1.hand)
    _end_step(engine)
    engine.resolve_until_stable()
    assert (len(p1.hand) - before == 2) == draws


def test_pyreswipe_hawk_attack_pumps_power_by_the_greatest_artifact_mana_value():
    engine = _game()
    p1, _ = engine.state.players
    hawk = _card(engine, "Pyreswipe Hawk")
    hawk.summoning_sick = False
    _filler(engine, "Small Rock", "Artifact", mv=2)
    _filler(engine, "Big Rock", "Artifact", mv=5)
    base = hawk.power
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [hawk])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert hawk.power == base + 5 and hawk.toughness == hawk.card.toughness  # +X/+0 only


def test_pyreswipe_hawk_expend_six_steals_an_artifact_until_the_hawk_leaves():
    engine = _game()
    p1, p2 = engine.state.players
    hawk = _card(engine, "Pyreswipe Hawk")
    rock = _filler(engine, "Their Rock", "Artifact", "p2", mv=3)
    engine.state.current_step = "main1"
    # six mana worth of spells in one turn: the sixth mana spent fires EXPEND 6
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine.state.fire_event(GameEvent(EventType.EXPEND, player_id="p1", amount=6))
    engine.resolve_until_stable()
    if engine.state.pending_choice:
        engine.resolve_pending_choice(str(rock.instance_id))
        engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert rock.controller_id == "p1"
    engine.rules.destroy(hawk)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert rock.controller_id == "p2"


def test_evercoat_ursine_hides_two_cards_then_plays_one_free_on_combat_damage():
    engine = _game()
    p1, p2 = engine.state.players
    p1.library.clear()
    for i in range(8):
        card = Card(id=f"Lib{i}", name="Bolt" if i == 7 else f"Lib {i}", type_line="Instant" if i == 7 else "Land",
                    is_instant=i == 7, is_land=i != 7, converted_mana_cost=1 if i == 7 else 0,
                    mana_cost_string="{R}" if i == 7 else "",
                    oracle_text="Bolt deals 3 damage to any target." if i == 7 else "")
        obj = GameObject(card, owner_id="p1", zone=Zone.LIBRARY)
        bind_from_catalogue(obj)
        p1.add_to_zone(obj, Zone.LIBRARY)
    ursine = _card(engine, "Evercoat Ursine", zone=Zone.HAND)
    assert len([a for a in ursine.triggered_abilities if a.trigger_event == "ENTERS_BATTLEFIELD"]) == 2
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 1, "C": 4})
    engine.cast_spell(p1, ursine, targets=None, target_groups=None)
    engine.resolve_until_stable()
    for _ in range(10):  # two hideaway picks
        choice = engine.state.pending_choice
        if not choice:
            break
        options = [o for o in choice["options"] if str(o.get("id", "")).isdigit()]
        engine.resolve_pending_choice(str(options[0]["id"]))
        engine.resolve_until_stable()
    assert len(ursine.hideaway_exile_ids) == 2
    ursine.summoning_sick = False
    engine.rules.deal_damage(p2, 5, source=ursine, combat=True)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == "play_during_resolution"
    assert set(choice["instance_ids"]) == set(ursine.hideaway_exile_ids)


def test_brightcap_badger_gives_fungi_and_saprolings_a_green_mana_ability_and_makes_saprolings():
    from mtg_analyzer.game.mana_abilities import mana_abilities_for

    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Brightcap Badger")
    saproling = _filler(engine, "Saproling", "Creature — Saproling", power=1, toughness=1)
    fungus = _filler(engine, "Some Fungus", "Creature — Fungus", power=1, toughness=1)
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    engine.recompute_continuous_effects()
    assert mana_abilities_for(saproling) and mana_abilities_for(fungus)
    assert not mana_abilities_for(bear)
    before = sum(o.card.name == "Saproling" for o in engine.state.battlefield)
    _end_step(engine)
    engine.resolve_until_stable()
    assert sum(o.card.name == "Saproling" for o in engine.state.battlefield) == before + 1


def _treasure(engine, player="p1", tapped=False):
    engine.rules._apply_effect_specs([{"type": "create_token", "params": {"token_name": "Treasure", "tapped": tapped}}],
                                     next(o for o in engine.state.battlefield if o.controller_id == player))
    token = [o for o in engine.state.battlefield if o.card.name == "Treasure" and o.controller_id == player][-1]
    return token


def test_alchemists_talent_enters_with_two_tapped_treasures():
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    talent = _card(engine, "Alchemist's Talent", zone=Zone.HAND)
    p1.mana_pool.add_many({"R": 1, "C": 3})
    engine.cast_spell(p1, talent, targets=None, target_groups=None)
    engine.resolve_until_stable()
    made = [o for o in engine.state.battlefield if o.card.name == "Treasure"]
    assert len(made) == 2 and all(t.tapped for t in made)


def test_alchemists_talent_level_two_upgrades_treasures_to_two_mana():
    from mtg_analyzer.game.mana_abilities import mana_abilities_for

    engine = _game()
    talent = _card(engine, "Alchemist's Talent")
    treasure = _treasure(engine)
    engine.recompute_continuous_effects()
    before = sorted(sum(o.values()) for a in mana_abilities_for(treasure) for o in a.options)
    talent.counters["class_level"] = 2
    engine.recompute_continuous_effects()
    after = sorted(sum(o.values()) for a in mana_abilities_for(treasure) for o in a.options)
    assert before and max(before) == 1 and max(after) == 2


def test_alchemists_talent_level_three_damages_by_mana_value_when_a_treasure_paid():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    talent = _card(engine, "Alchemist's Talent")
    talent.counters["class_level"] = 3
    treasure = _treasure(engine)
    card = Card(id="Cheap", name="Cheap", type_line="Sorcery", is_sorcery=True,
                converted_mana_cost=1, mana_cost_string="{1}", oracle_text="Draw a card.")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)
    # pay with the Treasure's own mana ability, as the auto-tapper would
    engine.tap_for_mana(p1, treasure)
    engine.cast_spell(p1, obj, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert p2.life == 19


def test_alchemists_talent_level_three_ignores_spells_not_paid_with_a_treasure():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    talent = _card(engine, "Alchemist's Talent")
    talent.counters["class_level"] = 3
    card = Card(id="Cheap", name="Cheap", type_line="Sorcery", is_sorcery=True,
                converted_mana_cost=1, mana_cost_string="{1}", oracle_text="Draw a card.")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)
    p1.mana_pool.add("R", 1)
    engine.cast_spell(p1, obj, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert p2.life == 20


def test_bello_animates_big_non_equipment_artifacts_and_non_aura_enchantments_on_your_turn():
    from mtg_analyzer.game import combat

    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Bello, Bard of the Brambles")
    big_art = _filler(engine, "Big Artifact", "Artifact", mv=4)
    big_ench = _filler(engine, "Big Enchantment", "Enchantment", mv=5)
    cheap = _filler(engine, "Cheap Artifact", "Artifact", mv=3)
    equip = _filler(engine, "Big Equipment", "Artifact — Equipment", mv=4)
    aura = _filler(engine, "Big Aura", "Enchantment — Aura", mv=4)
    engine.recompute_continuous_effects()
    assert engine.state.active_player.id == "p1"
    for animated in (big_art, big_ench):
        assert animated.is_creature and (animated.power, animated.toughness) == (4, 4)
        assert combat.has(animated, "indestructible") and combat.has(animated, "haste")
        from mtg_analyzer.game import continuous

        assert continuous.has_subtype(animated, "Elemental")
    for plain in (cheap, equip, aura):
        assert not plain.is_creature


def test_bello_does_nothing_on_the_opponents_turn():
    engine = _game()
    _card(engine, "Bello, Bard of the Brambles")
    big_art = _filler(engine, "Big Artifact", "Artifact", mv=4)
    engine.state.active_player_index = 1  # p2's turn
    engine.recompute_continuous_effects()
    assert not big_art.is_creature


def test_bello_animated_artifact_draws_on_combat_damage():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Bello, Bard of the Brambles")
    big_art = _filler(engine, "Big Artifact", "Artifact", mv=4)
    engine.recompute_continuous_effects()
    before = len(p1.hand)
    engine.rules.deal_damage(p2, 4, source=big_art, combat=True)
    engine.resolve_until_stable()
    assert len(p1.hand) == before + 1


def test_grothama_lets_any_attacking_creature_fight_it_optionally():
    engine = _game()
    p1, p2 = engine.state.players
    grothama = _card(engine, "Grothama, All-Devouring", player="p2")
    attacker = _filler(engine, "Attacker", power=3, toughness=3)
    attacker.summoning_sick = False
    engine.recompute_continuous_effects()
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [attacker])
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice, "the optional fight is offered"
    engine.resolve_pending_choice("do")
    engine.resolve_until_stable()
    assert grothama.damage_marked == 3  # the attacker's 3 power
    assert attacker in p1.graveyard  # Grothama's 10 power is lethal to it


def test_grothama_declining_the_fight_changes_nothing():
    engine = _game()
    p1, _ = engine.state.players
    grothama = _card(engine, "Grothama, All-Devouring", player="p2")
    attacker = _filler(engine, "Attacker", power=3, toughness=3)
    attacker.summoning_sick = False
    engine.recompute_continuous_effects()
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [attacker])
    engine.resolve_until_stable()
    if engine.state.pending_choice:
        engine.resolve_pending_choice("decline")
        engine.resolve_until_stable()
    assert grothama.damage_marked == 0 and attacker.damage_marked == 0


def test_grothama_leaving_draws_each_player_cards_equal_to_the_damage_they_dealt_to_it():
    engine = _game()
    p1, p2 = engine.state.players
    grothama = _card(engine, "Grothama, All-Devouring", player="p2")
    mine = _filler(engine, "Mine", power=3, toughness=3)
    theirs = _filler(engine, "Theirs", player="p2", power=2, toughness=2)
    engine.rules.deal_damage(grothama, 3, source=mine)
    engine.rules.deal_damage(grothama, 2, source=theirs)
    before = {p.id: len(p.hand) for p in (p1, p2)}
    engine.rules.destroy(grothama)
    engine.resolve_until_stable()
    assert len(p1.hand) - before["p1"] == 3 and len(p2.hand) - before["p2"] == 2
