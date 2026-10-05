"""Real gameplay for the Family Matters (Bloomburrow Commander) catalogue entries."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
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
    from mtg_analyzer.models.game.events import EventType, GameEvent

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


@pytest.mark.parametrize("x,draws", [(2, False), (5, True)])
def test_jacked_rabbit_enters_with_x_counters_and_draws_at_five_or_more(x, draws):
    engine = _game()
    p1, _ = engine.state.players
    rabbit = _card(engine, "Jacked Rabbit", zone=Zone.HAND)
    before = len(p1.hand)
    _cast(engine, rabbit, {"W": 1, "C": 1 + x}, x=x)
    assert rabbit.plus_one_counters == x
    assert (len(p1.hand) - (before - 1) == 1) == draws


def test_jacked_rabbit_attack_makes_rabbits_equal_to_its_power():
    engine = _game()
    p1, _ = engine.state.players
    rabbit = _card(engine, "Jacked Rabbit")
    rabbit.add_counters("+1/+1", 3)
    rabbit.summoning_sick = False
    engine.recompute_continuous_effects()
    power = rabbit.power
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [rabbit])
    engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.card.name == "Rabbit"]) == power


def test_boss_s_chauffeur_enters_with_one_plus_the_other_creatures_and_leaves_citizens():
    engine = _game()
    p1, _ = engine.state.players
    _filler(engine, "A", power=1, toughness=1)
    _filler(engine, "B", power=1, toughness=1)
    chauffeur = _card(engine, "Boss's Chauffeur", zone=Zone.HAND)
    _cast(engine, chauffeur, {"W": 1, "C": 4})
    assert chauffeur.plus_one_counters == 3  # 1 + two other creatures
    _enter(engine, _filler(engine, "Late", power=1, toughness=1))  # alliance
    assert chauffeur.plus_one_counters == 4
    engine.rules.destroy(chauffeur)
    engine.resolve_until_stable()
    citizens = [o for o in engine.state.battlefield if o.card.name == "Citizen"]
    assert len(citizens) == 4


def test_pollywog_prodigy_evolves_and_draws_off_cheap_opposing_noncreature_spells():
    engine = _game()
    p1, p2 = engine.state.players
    pollywog = _card(engine, "Pollywog Prodigy")
    base = pollywog.power
    _enter(engine, _filler(engine, "Small", power=base, toughness=base))  # not greater: no counter
    assert pollywog.plus_one_counters == 0
    _enter(engine, _filler(engine, "Big", power=base + 2, toughness=1))
    assert pollywog.plus_one_counters == 1
    power = pollywog.power
    engine.recompute_continuous_effects()
    before = len(p1.hand)
    engine.state.current_step = "main1"

    def opp_spell(kind, mv):
        card = Card(id=f"S{mv}{kind}", name="Spell", type_line=kind, is_creature="Creature" in kind,
                    is_instant="Instant" in kind, converted_mana_cost=mv, mana_cost_string="{%d}" % mv,
                    power=1 if "Creature" in kind else None, toughness=1 if "Creature" in kind else None,
                    keywords=["Flash"])
        obj = GameObject(card, owner_id="p2", zone=Zone.HAND)
        bind_from_catalogue(obj)
        p2.add_to_zone(obj, Zone.HAND)
        p2.mana_pool.add("C", mv)
        engine.cast_spell(p2, obj, targets=None, target_groups=None)
        engine.resolve_until_stable()

    opp_spell("Instant", power - 1)
    assert len(p1.hand) == before + 1  # mana value below power
    opp_spell("Instant", power)
    opp_spell("Creature", 1)
    assert len(p1.hand) == before + 1  # not below power / not noncreature


def test_rapid_augmenter_gives_haste_to_base_power_one_entrants_and_grows_on_uncast_entries():
    engine = _game()
    augmenter = _card(engine, "Rapid Augmenter")
    one = _filler(engine, "One", power=1, toughness=1)
    _enter(engine, one)
    assert combat.has(one, "haste") or "haste" in one.temp_keywords
    assert augmenter.plus_one_counters == 1  # entered without being cast
    big = _filler(engine, "Big", power=3, toughness=3)
    _enter(engine, big, from_cast=True)
    assert "haste" not in big.temp_keywords and augmenter.plus_one_counters == 1


def test_tetsuko_makes_small_creatures_unblockable():
    engine = _game()
    _card(engine, "Tetsuko Umezawa, Fugitive")
    small_power = _filler(engine, "P1", power=1, toughness=5)
    small_toughness = _filler(engine, "T1", power=5, toughness=1)
    big = _filler(engine, "Big", power=3, toughness=3)
    engine.recompute_continuous_effects()
    assert combat.has(small_power, "cant_be_blocked") and combat.has(small_toughness, "cant_be_blocked")
    assert not combat.has(big, "cant_be_blocked")


def test_cut_a_deal_each_opponent_draws_then_you_draw_per_opponent():
    engine = _game(players=3)
    p1, p2, p3 = engine.state.players
    spell = _card(engine, "Cut a Deal", zone=Zone.HAND)
    before = {p.id: len(p.hand) for p in (p1, p2, p3)}
    _cast(engine, spell, {"W": 1, "C": 2})
    assert len(p2.hand) - before["p2"] == 1 and len(p3.hand) - before["p3"] == 1
    assert len(p1.hand) - (before["p1"] - 1) == 2


def test_stolen_by_the_fae_bounces_a_creature_with_mana_value_x_and_makes_x_faeries():
    engine = _game()
    p1, p2 = engine.state.players
    hit = _filler(engine, "Three Drop", player="p2", mv=3, power=2, toughness=2)
    miss = _filler(engine, "Two Drop", player="p2", mv=2, power=2, toughness=2)
    spell = _card(engine, "Stolen by the Fae", zone=Zone.HAND)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"U": 2, "C": 3})
    engine.cast_spell(p1, spell, x=3, targets=[hit], target_groups=[[hit]])
    engine.resolve_until_stable()
    assert hit in p2.hand and miss in engine.state.battlefield
    faeries = [o for o in engine.state.battlefield if o.card.name == "Faerie" and o.controller_id == "p1"]
    assert len(faeries) == 3 and all(combat.has(f, "flying") for f in faeries)


def test_bident_of_thassa_forces_the_opponents_creatures_to_attack():
    engine = _game()
    p1, p2 = engine.state.players
    bident = _card(engine, "Bident of Thassa")
    theirs = _filler(engine, "Theirs", player="p2", power=2, toughness=2)
    mine = _filler(engine, "Mine", power=2, toughness=2)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"U": 1, "C": 1})
    idx = next(a["ability_index"] for a in engine.legal_actions(p1)
               if a.get("type") == "activate_ability" and a.get("instance_id") == bident.instance_id)
    engine.activate_ability(p1, bident, ability_index=idx)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert combat.has(theirs, "attacks_if_able") and not combat.has(mine, "attacks_if_able")


def test_murmuration_makes_a_storm_crow_for_each_spell_cast_and_pumps_birds():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Murmuration")
    bird = _filler(engine, "Bird", "Creature — Bird", power=1, toughness=1)
    engine.recompute_continuous_effects()
    assert (bird.power, bird.toughness) == (2, 2) and combat.has(bird, "vigilance")
    for i in range(2):
        spell = _filler(engine, f"Spell {i}", "Instant", mv=1, zone=Zone.HAND)
        engine.state.current_step = "main1"
        p1.mana_pool.add("C", 1)
        engine.cast_spell(p1, spell, targets=None, target_groups=None)
        engine.resolve_until_stable()
    for _ in range(20):
        engine.advance_step()
        if engine.state.current_step == "end":
            break
    engine.resolve_until_stable()
    crows = [o for o in engine.state.battlefield if o.card.name == "Storm Crow"]
    assert len(crows) == 2 and all(combat.has(c, "flying") and continuous.has_subtype(c, "Bird") for c in crows)


def test_shield_broker_steals_a_noncommander_until_its_shield_counter_is_spent():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    victim = _filler(engine, "Victim", player="p2", power=3, toughness=3)
    commander = _filler(engine, "Their Commander", player="p2", power=3, toughness=3)
    commander.is_commander = True
    broker = _card(engine, "Shield Broker", zone=Zone.HAND)
    p1.mana_pool.add_many({"U": 2, "C": 3})
    engine.cast_spell(p1, broker, targets=None, target_groups=None)
    engine.resolve_until_stable()
    pending = engine.state.pending_choice
    assert pending
    ids = {str(o.get("instance_id", o.get("id"))) for o in pending["options"]}
    assert str(victim.instance_id) in ids and str(commander.instance_id) not in ids
    engine.resolve_pending_choice(str(victim.instance_id))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert victim.controller_id == "p1" and victim.counters.get("shield") == 1
    victim.counters["shield"] = 0  # the shield was spent
    engine.recompute_continuous_effects()
    assert victim.controller_id == "p2"


def test_echoing_assault_copies_an_attacker_as_a_tapped_attacking_1_1_that_dies_at_end_step():
    engine = _game(players=3)
    p1, p2, p3 = engine.state.players
    _card(engine, "Echoing Assault")
    big = _filler(engine, "Big Attacker", power=5, toughness=5)
    big.summoning_sick = False
    token_attacker = _filler(engine, "Token Attacker", power=2, toughness=2)
    token_attacker.is_token = True
    token_attacker.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.state.current_phase = "combat"
    engine.declare_attackers(p1, [{"attacker": big, "defender": {"kind": "player", "id": "p2", "label": "1"}},
                                  {"attacker": token_attacker, "defender": {"kind": "player", "id": "p3", "label": "2"}}])
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()
    for _ in range(4):  # one trigger per attacked player: pick the nontoken attacker when asked
        choice = engine.state.pending_choice
        if not choice:
            break
        options = {str(o.get("instance_id", o.get("id"))) for o in choice["options"]}
        assert str(token_attacker.instance_id) not in options  # nontoken only
        engine.resolve_pending_choice(str(big.instance_id))
        engine.resolve_until_stable()
    copies = [o for o in engine.state.battlefield if o.card.name == "Big Attacker" and o is not big]
    assert len(copies) == 1
    copy = copies[0]
    assert (copy.power, copy.toughness) == (1, 1) and copy.tapped and copy.attacking
    assert copy.combat_defender["id"] == "p2"  # the player the original attacks
    engine._fire_delayed_triggers("end")  # the next end step's beginning
    engine.resolve_until_stable()
    assert copy not in engine.state.battlefield and big in engine.state.battlefield


def test_junk_winder_taps_and_freezes_an_opposing_nonland_permanent_when_a_token_enters():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Junk Winder")
    rock = _filler(engine, "Their Rock", "Artifact", player="p2", mv=2)
    land = _filler(engine, "Their Land", "Land", player="p2")
    token = _filler(engine, "My Token", power=1, toughness=1)
    token.is_token = True
    _enter(engine, token)
    pending = engine.state.pending_choice
    assert pending
    ids = {str(o.get("instance_id", o.get("id"))) for o in pending["options"]}
    assert str(rock.instance_id) in ids and str(land.instance_id) not in ids
    engine.resolve_pending_choice(str(rock.instance_id))
    engine.resolve_until_stable()
    assert rock.tapped
    engine.state.active_player_index = 1  # p2's untap step: it stays tapped
    engine._step_untap()
    assert rock.tapped
    engine._step_untap()  # only the *next* untap step is skipped
    assert not rock.tapped


def test_junk_winder_costs_one_less_per_token():
    engine = _game()
    p1, _ = engine.state.players
    for i in range(3):
        t = _filler(engine, f"Tok{i}", power=1, toughness=1)
        t.is_token = True
    winder = _card(engine, "Junk Winder", zone=Zone.HAND)
    assert engine.effective_cast_cost(p1, winder).converted_mana_cost == 4


def test_fortune_teller_s_talent_level_two_lets_you_play_from_the_top_only_after_casting_a_spell():
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    talent = _card(engine, "Fortune Teller's Talent")
    p1.library.clear()
    top = _filler(engine, "Top Spell", "Sorcery", mv=1, zone=Zone.LIBRARY)
    p1.mana_pool.add("C", 3)
    assert not engine.can_cast(p1, top)  # level 1 only looks
    talent.counters["class_level"] = 2
    assert not engine.can_cast(p1, top)  # no spell cast yet this turn
    cheap = _filler(engine, "Cheap", "Sorcery", mv=1, zone=Zone.HAND)
    engine.cast_spell(p1, cheap, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert engine.can_cast(p1, top)


def test_fortune_teller_s_talent_level_three_discounts_spells_not_cast_from_hand():
    engine = _game()
    p1, _ = engine.state.players
    talent = _card(engine, "Fortune Teller's Talent")
    talent.counters["class_level"] = 3
    from_gy = _filler(engine, "From Graveyard", "Sorcery", mv=4, zone=Zone.GRAVEYARD)
    from_gy.cast_via_flashback = True
    from_hand = _filler(engine, "From Hand", "Sorcery", mv=4, zone=Zone.HAND)
    from mtg_analyzer.game import continuous as cont

    assert cont.cost_reduction_for(engine.state, p1, obj=from_gy)[0] == 2
    assert cont.cost_reduction_for(engine.state, p1, obj=from_hand)[0] == 0


def test_storm_of_souls_returns_every_creature_as_a_1_1_flying_spirit_and_exiles_itself():
    engine = _game()
    p1, _ = engine.state.players
    bear = _filler(engine, "Big Bear", "Creature — Bear", power=4, toughness=4, zone=Zone.GRAVEYARD)
    elf = _filler(engine, "Old Elf", "Creature — Elf", power=2, toughness=2, zone=Zone.GRAVEYARD)
    relic = _filler(engine, "Relic", "Artifact", mv=1, zone=Zone.GRAVEYARD)
    storm = _card(engine, "Storm of Souls", zone=Zone.HAND)
    _cast(engine, storm, {"W": 2, "C": 4})
    assert bear.zone == Zone.BATTLEFIELD and elf.zone == Zone.BATTLEFIELD
    assert relic.zone == Zone.GRAVEYARD
    engine.recompute_continuous_effects()
    for creature in (bear, elf):
        assert (creature.power, creature.toughness) == (1, 1)
        assert "Spirit" in creature._added_subtypes
        assert "flying" in combat._obj_keywords(creature)
    assert "Bear" in bear.card.type_line and "Elf" in elf.card.type_line  # "in addition to its other types"
    assert storm.zone == Zone.EXILE


def test_zinnia_gets_plus_one_power_per_other_creature_with_base_power_one():
    engine = _game()
    zinnia = _card(engine, "Zinnia, Valley's Voice")
    engine.recompute_continuous_effects()
    assert zinnia.power == 1  # Zinnia's own printed power is 1 and she does not count herself
    _filler(engine, "One A", power=1, toughness=1)
    _filler(engine, "One B", power=1, toughness=3)
    _filler(engine, "Two", power=2, toughness=2)
    _filler(engine, "Theirs", player="p2", power=1, toughness=1)
    engine.recompute_continuous_effects()
    assert zinnia.power == 3
    assert "flying" in combat._obj_keywords(zinnia)


def test_zinnia_grants_offspring_to_creature_spells_and_the_token_copy_is_made():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Zinnia, Valley's Voice")
    bear = _filler(engine, "Grizzly", "Creature — Bear", mv=2, power=2, toughness=2, zone=Zone.HAND)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 4})
    assert engine._kicker_cost(bear) is not None
    assert engine.can_cast(p1, bear, kicked=1)
    engine.cast_spell(p1, bear, targets=None, target_groups=None, kicked=1)
    engine.resolve_until_stable()
    copies = [o for o in engine.state.battlefield if o.name == "Grizzly"]
    assert len(copies) == 2 and sum(1 for o in copies if o.is_token) == 1
    token = next(o for o in copies if o.is_token)
    assert (token.power, token.toughness) == (1, 1)


def test_zinnia_offspring_is_optional_and_noncreature_spells_get_none():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Zinnia, Valley's Voice")
    bear = _filler(engine, "Grizzly", "Creature — Bear", mv=2, power=2, toughness=2, zone=Zone.HAND)
    spell = _filler(engine, "Bolt", "Instant", mv=1, zone=Zone.HAND)
    assert engine._kicker_cost(spell) is None
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 4})
    engine.cast_spell(p1, bear, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert [o for o in engine.state.battlefield if o.name == "Grizzly"] == [bear]
