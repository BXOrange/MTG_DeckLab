"""Real gameplay for the remaining Riveteer Rampage catalogue entries."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import battlefield_object


def _game(seats=2):
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * 8) for i in range(seats)],
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


def _end_step(engine):
    for _ in range(20):
        engine.advance_step()
        if engine.state.current_step == "end":
            return
    raise AssertionError("end step not reached")


def _zone_card(engine, name, type_line, owner, zone):
    creature = "Creature" in type_line
    card = Card(id=name, name=name, type_line=type_line, is_creature=creature,
                power=2 if creature else None, toughness=2 if creature else None)
    obj = GameObject(card, owner_id=owner, zone=zone)
    engine.state.player_by_id(owner).add_to_zone(obj, zone)
    return obj


def test_industrial_advancement_catalogue_returns_fresh_complete_abilities():
    from mtg_analyzer.game.card_registry import specs_for

    card = CardDatabase(DB_PATH).get_card("Industrial Advancement")
    first, second = specs_for(card), specs_for(card)
    assert [spec.ability_kind for spec in first] == ["triggered"]
    assert first[0] is not second[0]
    assert first[0].effects[0].params is not second[0].effects[0].params
    first[0].effects[0].params["then_that_many"]["effects"][0]["params"]["count"] = 99
    assert second[0].effects[0].params["then_that_many"]["effects"][0]["params"]["count"] == "x"
    engine = _game()
    obj = _card(engine, card.name)
    assert len(obj.triggered_abilities) == 1


@pytest.mark.parametrize("sacrifice,pick", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("transformed", [False, True])
def test_industrial_advancement_sacrifices_then_inspects_exact_mana_value(sacrifice, pick, transformed):
    engine = _game()
    p1, p2 = engine.state.players
    advancement = _card(engine, "Industrial Advancement")
    victim = battlefield_object(engine, "p1", "Four Mana Bear", "Creature", is_creature=True,
                                power=2, toughness=2, converted_mana_cost=4,
                                mana_cost_string="{3}{G}", layout="transform",
                                back_name="Back Bear", back_type_line="Creature",
                                back_power=3, back_toughness=3)
    if transformed:
        assert engine.rules.transform_permanent(victim)
        assert victim.card.converted_mana_cost == 0
    enemy = battlefield_object(engine, "p2", "Enemy", "Creature", is_creature=True, power=2, toughness=2)
    for _ in range(10):
        engine.advance_step()
        if engine.state.current_step == "main1":
            break
    p1.library.clear()
    deep = _zone_card(engine, "Deep Creature", "Creature", "p1", Zone.LIBRARY)
    land = _zone_card(engine, "Top Land", "Land", "p1", Zone.LIBRARY)
    spell = _zone_card(engine, "Top Spell", "Sorcery", "p1", Zone.LIBRARY)
    first = _zone_card(engine, "Top Creature A", "Creature", "p1", Zone.LIBRARY)
    second = _zone_card(engine, "Top Creature B", "Creature", "p1", Zone.LIBRARY)
    before = list(p1.library)
    _end_step(engine)
    assert {o["instance_id"] for o in engine.state.pending_choice["options"] if "instance_id" in o} == {victim.instance_id}
    engine.resolve_pending_choice(str(victim.instance_id) if sacrifice else "decline")
    engine.resolve_until_stable()
    if not sacrifice:
        assert victim in engine.state.battlefield and p1.library == before
        assert not engine.state.pending_choice
        return
    assert victim in p1.graveyard
    assert {o["instance_id"] for o in engine.state.pending_choice["options"] if "instance_id" in o} == {first.instance_id, second.instance_id}
    engine.resolve_pending_choice(str(first.instance_id) if pick else "decline")
    engine.resolve_until_stable()
    rest = {land, spell, second} | (set() if pick else {first})
    assert set(p1.library[:len(rest)]) == rest  # unchosen inspected cards moved to bottom
    assert p1.library[-1] is deep  # fifth card was never inspected
    assert (first in engine.state.battlefield) == pick
    assert enemy in engine.state.battlefield and advancement in engine.state.battlefield
    assert not engine.state.pending_choice


def test_industrial_advancement_zero_mana_token_and_opponents_end_step():
    engine = _game()
    advancement = _card(engine, "Industrial Advancement")
    token = battlefield_object(engine, "p1", "Token", "Creature", is_creature=True, power=1, toughness=1)
    token.is_token = True
    _end_step(engine)
    before = list(engine.state.players[0].library)
    engine.resolve_pending_choice(str(token.instance_id))
    engine.resolve_until_stable()
    assert token not in engine.state.battlefield
    assert engine.state.players[0].library == before and not engine.state.pending_choice
    engine.advance_step()
    engine.advance_step()
    assert engine.state.active_player.id == "p2"
    _end_step(engine)
    assert not engine.state.pending_choice and not engine.state.stack
    assert advancement in engine.state.battlefield


@pytest.mark.parametrize("remove_source,decline", [(False, False), (True, False), (False, True)])
def test_grime_gorger_chooses_from_defending_graveyard_and_counts_multitype_cards(remove_source, decline):
    engine = _game(3)
    p1, p2, p3 = engine.state.players
    gorger = _card(engine, "Grime Gorger")
    gorger.summoning_sick = False
    own = _zone_card(engine, "Own Bear", "Creature", "p1", Zone.GRAVEYARD)
    other = _zone_card(engine, "Other Bear", "Creature", "p2", Zone.GRAVEYARD)
    picks = [
        _zone_card(engine, "Artifact Bear", "Artifact Creature", "p3", Zone.GRAVEYARD),
        _zone_card(engine, "Enchantment Bear", "Enchantment Creature", "p3", Zone.GRAVEYARD),
        _zone_card(engine, "Plain Bear", "Creature", "p3", Zone.GRAVEYARD),
    ]
    rejected = _zone_card(engine, "Fourth Bear", "Creature", "p3", Zone.GRAVEYARD)
    for _ in range(10):
        engine.advance_step()
        if engine.state.current_step == "declare_attackers":
            break
    engine.declare_attackers(p1, [{"attacker": gorger, "defender": p3}])
    engine.rules.put_triggers_on_stack()
    if remove_source:
        engine.rules.return_to_hand(gorger)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice["player_id"] == "p1"  # attacker, not defender, chooses
    assert {o["instance_id"] for o in choice["options"] if "instance_id" in o} == {
        o.instance_id for o in picks + [rejected]
    }
    if decline:
        engine.resolve_pending_choice("decline")
        engine.resolve_until_stable()
    else:
        for obj in picks:
            engine.resolve_pending_choice(str(obj.instance_id))
            engine.resolve_until_stable()
            assert obj in p3.exile
    assert not engine.state.pending_choice
    assert own in p1.graveyard and other in p2.graveyard and rejected in p3.graveyard
    assert gorger.counters.get("+1/+1", 0) == (0 if remove_source or decline else 3)
    assert all((obj in p3.graveyard) if decline else (obj in p3.exile) for obj in picks)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("types", [
    ["Artifact Creature", "Artifact", "Creature"],
    ["Kindred Sorcery", "Sorcery", "Sorcery"],
])
def test_atraxa_assigns_multitype_cards_to_distinct_types_and_rejects_an_extra(types, reverse):
    engine = _game()
    p1 = engine.state.players[0]
    p1.library.clear()
    selected = [_zone_card(engine, f"Pick {i}", t, "p1", Zone.LIBRARY) for i, t in enumerate(types)]
    filler = [_zone_card(engine, f"Land {i}", "Land", "p1", Zone.LIBRARY) for i in range(7)]
    atraxa = _card(engine, "Atraxa, Grand Unifier", zone=Zone.HAND)
    for _ in range(10):
        engine.advance_step()
        if engine.state.current_step == "main1":
            break
    p1.mana_pool.add_many({"W": 1, "U": 1, "B": 1, "G": 1, "C": 3})
    engine.cast_spell(p1, atraxa)
    engine.resolve_until_stable()
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    for obj in selected[:2][::-1] if reverse else selected[:2]:
        assert str(obj.instance_id) in {o["id"] for o in engine.state.pending_choice["options"]}
        engine.resolve_pending_choice(str(obj.instance_id))
        engine.resolve_until_stable()
    options = engine.state.pending_choice["options"]
    assert str(selected[2].instance_id) not in {o["id"] for o in options}
    assert {str(o.instance_id) for o in filler} <= {o["id"] for o in options}
    with pytest.raises(ValueError, match="legal choice"):
        engine.resolve_pending_choice(str(selected[2].instance_id))
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert all(obj in p1.hand for obj in selected[:2])
    assert selected[2] in p1.library


@pytest.mark.parametrize("sacrifice", [False, True])
def test_bellowing_mauler_collects_each_players_nontoken_choice_before_sacrifices(sacrifice):
    engine = _game(3)
    p1, p2, p3 = engine.state.players
    mauler = _card(engine, "Bellowing Mauler")
    own = battlefield_object(engine, "p1", "Bear", "Creature", is_creature=True, power=2, toughness=2)
    other = battlefield_object(engine, "p2", "Bear", "Creature", is_creature=True, power=2, toughness=2)
    token = battlefield_object(engine, "p3", "Soldier", "Creature", is_creature=True, power=1, toughness=1)
    token.is_token = True
    _end_step(engine)
    choice = engine.state.pending_choice
    assert choice["player_id"] == "p1"
    assert {o["instance_id"] for o in choice["options"] if "instance_id" in o} == {own.instance_id, mauler.instance_id}
    engine.resolve_pending_choice(str(own.instance_id) if sacrifice else "decline")
    engine.resolve_until_stable()
    assert own in engine.state.battlefield  # choices precede all sacrifices
    assert p1.life == p2.life == p3.life == 20
    assert engine.state.pending_choice["player_id"] == "p2"
    engine.resolve_pending_choice(str(other.instance_id))
    engine.resolve_until_stable()
    assert other in p2.graveyard
    assert p1.life == (20 if sacrifice else 16)
    assert p2.life == 20 and p3.life == 16  # tokens cannot be offered
    assert token in engine.state.battlefield and mauler in engine.state.battlefield
    assert (own in p1.graveyard) == sacrifice


def test_bellowing_mauler_can_be_its_own_sacrifice_and_does_not_trigger_on_opponents_end_step():
    engine = _game()
    mauler = _card(engine, "Bellowing Mauler")
    _end_step(engine)
    engine.resolve_pending_choice(str(mauler.instance_id))
    engine.resolve_until_stable()
    assert mauler.zone == Zone.GRAVEYARD
    assert [p.life for p in engine.state.players] == [20, 16]
    second = _card(engine, "Bellowing Mauler")
    engine.advance_step()  # cleanup
    engine.advance_step()  # next turn's untap
    assert engine.state.active_player.id == "p2"
    _end_step(engine)
    assert not engine.state.pending_choice and not engine.state.stack
    assert second in engine.state.battlefield
    assert [p.life for p in engine.state.players] == [20, 16]


@pytest.mark.parametrize("others,cast_zone", [(4, Zone.HAND), (5, Zone.HAND), (5, Zone.GRAVEYARD)])
def test_deathbringer_regent_cast_provenance_and_five_other_creatures(others, cast_zone):
    from mtg_analyzer.game.effects.core import GraveyardCastPermissionEffect

    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    victims = [battlefield_object(engine, "p2", f"Bear {i}", "Creature", is_creature=True,
                                 power=2, toughness=2) for i in range(others)]
    regent = _card(engine, "Deathbringer Regent", zone=cast_zone)
    if cast_zone == Zone.GRAVEYARD:
        grant = _card(engine, "Sol Ring")
        grant.static_effects.append(GraveyardCastPermissionEffect(source=grant))
    p1.mana_pool.add_many({"B": 2, "C": 5})
    engine.cast_spell(p1, regent)
    engine.resolve_until_stable()
    assert regent in engine.state.battlefield
    assert all((v in p2.graveyard) == (others >= 5 and cast_zone == Zone.HAND) for v in victims)


def test_deathbringer_regent_rechecks_its_creature_count_when_trigger_resolves():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    victims = [battlefield_object(engine, "p2", f"Bear {i}", "Creature", is_creature=True,
                                 power=2, toughness=2) for i in range(5)]
    regent = _card(engine, "Deathbringer Regent", zone=Zone.HAND)
    p1.mana_pool.add_many({"B": 2, "C": 5})
    engine.cast_spell(p1, regent)
    engine.rules.resolve_top_of_stack()  # enters, queues its trigger
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack) == 1
    engine.rules.put_into_graveyard(victims[0])
    engine.resolve_until_stable()
    assert all(v in engine.state.battlefield for v in victims[1:])


def test_deathbringer_regents_trigger_survives_removal_of_the_regent():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    victims = [battlefield_object(engine, "p2", f"Bear {i}", "Creature", is_creature=True,
                                 power=2, toughness=2) for i in range(5)]
    regent = _card(engine, "Deathbringer Regent", zone=Zone.HAND)
    p1.mana_pool.add_many({"B": 2, "C": 5})
    engine.cast_spell(p1, regent)
    engine.rules.resolve_top_of_stack()
    engine.rules.put_triggers_on_stack()
    engine.rules.put_into_graveyard(regent)
    engine.resolve_until_stable()
    assert all(v in p2.graveyard for v in victims)


@pytest.mark.parametrize("accept", [False, True])
def test_first_responder_uses_last_battlefield_power_and_returns_to_the_owner(accept):
    from mtg_analyzer.game.effects.core import GameContext, PumpEffect

    engine = _game()
    p1, p2 = engine.state.players
    responder = _card(engine, "First Responder")
    creature = battlefield_object(engine, "p2", "Borrowed Bear", "Creature", is_creature=True,
                                  power=2, toughness=2)
    creature.controller_id = "p1"
    pump = PumpEffect(4, 4, source=responder, target_kind="creature")
    pump.apply(GameContext(engine.state, engine.rules), targets=[creature])
    engine.recompute_continuous_effects()
    assert creature.power == 6
    _end_step(engine)
    choice = engine.state.pending_choice
    assert {o["instance_id"] for o in choice["options"] if "instance_id" in o} == {creature.instance_id}
    engine.resolve_pending_choice(str(creature.instance_id) if accept else "decline")
    engine.resolve_until_stable()
    assert (creature in p2.hand) == accept
    assert responder.counters.get("+1/+1", 0) == (6 if accept else 0)
    if accept:
        assert creature.temp_power == 0 and creature.power == 2
        assert creature.controller_id == "p2"
        engine.begin_turn()
        engine.state.current_step = "main1"
        engine.cast_spell(p2, creature)
        engine.resolve_until_stable()
        assert (creature.power, creature.toughness) == (2, 2)


def test_first_responder_with_no_other_creature_has_no_choice_or_counter_gain():
    engine = _game()
    responder = _card(engine, "First Responder")
    _end_step(engine)
    assert not engine.state.pending_choice
    assert responder.counters.get("+1/+1", 0) == 0


def test_mitotic_slime_and_each_large_ooze_create_their_own_descendants():
    engine = _game()
    slime = _card(engine, "Mitotic Slime")
    engine.rules.destroy(slime)
    engine.resolve_until_stable()
    oozes = [o for o in engine.state.battlefield if o.is_token and o.name == "Ooze"]
    assert len(oozes) == 2
    assert all((o.power, o.toughness) == (2, 2) and len(o.triggered_abilities) == 1 for o in oozes)
    engine.rules.destroy(oozes[0])
    engine.resolve_until_stable()
    current = [o for o in engine.state.battlefield if o.is_token and o.name == "Ooze"]
    assert sorted(o.power for o in current) == [1, 1, 2]
    engine.rules.destroy(oozes[1])
    engine.resolve_until_stable()
    small = [o for o in engine.state.battlefield if o.is_token and o.name == "Ooze"]
    assert len(small) == 4 and all((o.power, o.toughness) == (1, 1) for o in small)
    assert all(o.controller_id == "p1" and not o.triggered_abilities for o in small)
    engine.rules.destroy(small[0])
    engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.is_token and o.name == "Ooze"]) == 3


# --- Wave of Rats / Mezzio Mugger / Turf War (Blitz batch) -----------------------------------

@pytest.mark.parametrize("dealt_combat_damage", [False, True])
def test_wave_of_rats_returns_only_after_combat_damage_to_a_player(dealt_combat_damage):
    engine = _game()
    p1, p2 = engine.state.players
    rats = _card(engine, "Wave of Rats")
    if dealt_combat_damage:
        engine.rules.deal_damage(p2, 2, source=rats, combat=True)
    engine.rules.destroy(rats)
    engine.resolve_until_stable()
    if dealt_combat_damage:
        assert rats in engine.state.battlefield and rats not in p1.graveyard
    else:
        assert rats in p1.graveyard and rats not in engine.state.battlefield


def test_wave_of_rats_noncombat_damage_does_not_count():
    engine = _game()
    p1, p2 = engine.state.players
    rats = _card(engine, "Wave of Rats")
    engine.rules.deal_damage(p2, 2, source=rats, combat=False)
    engine.rules.destroy(rats)
    engine.resolve_until_stable()
    assert rats in p1.graveyard


def test_mezzio_mugger_exiles_each_players_top_card_playable_with_any_color():
    engine = _game()
    p1, p2 = engine.state.players
    mugger = _card(engine, "Mezzio Mugger")
    mine = _zone_card(engine, "Mine", "Sorcery", "p1", Zone.LIBRARY)
    theirs = _zone_card(engine, "Theirs", "Land", "p2", Zone.LIBRARY)
    mugger.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(engine.state.active_player, [mugger])
    engine.resolve_until_stable()
    assert mine in p1.exile and theirs in p2.exile
    for card in (mine, theirs):
        assert engine.state.temp_play_permission_player[card.instance_id] == "p1"
        assert engine.state.mana_wildcard_permission[card.instance_id] == "color"


def test_turf_war_contested_lands_change_hands_on_combat_damage_and_untap():
    engine = _game()
    p1, p2 = engine.state.players
    war = _card(engine, "Turf War")
    contested = battlefield_object(engine, "p2", "Contested Land", "Land", is_land=True)
    plain = battlefield_object(engine, "p2", "Plain Land", "Land", is_land=True)
    contested.counters["contested"] = 1
    contested.tapped = True
    attacker = battlefield_object(engine, "p1", "Attacker", "Creature", is_creature=True, power=2, toughness=2)
    engine.rules.deal_damage(p2, 2, source=attacker, combat=True)
    engine.resolve_until_stable()
    pending = engine.state.pending_choice
    if pending:  # a single candidate may resolve without a prompt
        engine.resolve_pending_choice(str(contested.instance_id))
        engine.resolve_until_stable()
    assert contested.controller_id == "p1" and not contested.tapped
    assert plain.controller_id == "p2"
    assert war in engine.state.battlefield


def test_turf_war_does_nothing_without_a_contested_land():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Turf War")
    land = battlefield_object(engine, "p2", "Plain Land", "Land", is_land=True)
    attacker = battlefield_object(engine, "p1", "Attacker", "Creature", is_creature=True, power=2, toughness=2)
    engine.rules.deal_damage(p2, 2, source=attacker, combat=True)
    engine.resolve_until_stable()
    assert land.controller_id == "p2" and not engine.state.pending_choice
