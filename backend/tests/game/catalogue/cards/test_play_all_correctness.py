"""Live regressions for the PLAY-ALL card correctness follow-ups."""
import pytest
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import battlefield_object


def _game():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0, starting_life=20)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state.players[0], engine.state.players[1]


def test_magda_creates_only_one_tapped_treasure_for_real_crimes_in_a_turn():
    engine, p1, p2 = _game()
    magda = GameObject(CardDatabase(DB_PATH).get_card("Magda, the Hoardmaster"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(magda)
    engine.state.add_to_battlefield(magda)
    for i in range(2):
        spell = GameObject(Card(id=str(i), name="Ping", type_line="Instant", is_instant=True,
                               oracle_text="Deal 1 damage to target player."), owner_id="p1", zone=Zone.HAND)
        bind_from_catalogue(spell)
        p1.hand.append(spell)
        engine.cast_spell(p1, spell, targets=[p2])
        engine.resolve_until_stable()
    treasures = [o for o in engine.state.battlefield if o.name == "Treasure"]
    assert len(treasures) == 1 and treasures[0].tapped


def test_jaya_requires_my_legendary_creature_or_planeswalker():
    engine, p1, p2 = _game()
    spell = GameObject(CardDatabase(DB_PATH).get_card("Jaya's Immolating Inferno"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    p1.mana_pool.add_many({"R": 5})
    assert not engine.can_cast(p1, spell, targets=[p2], x=1)
    legend = battlefield_object(engine, "p2", "Legend", "Legendary Creature", is_creature=True,
                                is_legendary=True, power=2, toughness=2)
    assert not engine.can_cast(p1, spell, targets=[p2], x=1)
    legend.controller_id = "p1"
    assert engine.can_cast(p1, spell, targets=[p2], x=1)
    engine.cast_spell(p1, spell, targets=[p2], x=1)
    engine.resolve_until_stable()
    assert p2.life == 19


@pytest.mark.parametrize("kind", ["Instant", "Sorcery"])
def test_legendary_spell_gate_applies_without_catalogue_reminder_text(kind):
    engine, p1, p2 = _game()
    spell = GameObject(Card(id=kind, name="Legendary study", type_line=f"Legendary {kind}",
                            is_instant=kind == "Instant", is_sorcery=kind == "Sorcery",
                            oracle_text="Draw a card."), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    assert getattr(spell, "cast_condition", None) is None
    assert not engine.can_cast(p1, spell)
    battlefield_object(engine, "p1", "Legendary rock", "Legendary Artifact", is_legendary=True)
    assert not engine.can_cast(p1, spell)
    battlefield_object(engine, "p1", "Walker", "Legendary Planeswalker", is_legendary=True)
    assert engine.can_cast(p1, spell)


from mtg_analyzer.game import combat
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import activate, answer, attack, card, cast, filler, game, named, pick_label, step


def test_resourceful_defense_moves_a_chosen_subset_of_counter_kinds():
    engine = game()
    defense = card(engine, 'Resourceful Defense')
    src = filler(engine, 'From', power=3, toughness=3)
    dst = filler(engine, 'To', power=3, toughness=3)
    src.add_counters('+1/+1', 3)
    src.add_counters('flying', 1)
    me = engine.state.player_by_id('p1')
    me.mana_pool.add_many({'W': 1, 'C': 4})
    activate(engine, defense, targets=[src, dst])
    engine.resolve_pending_choice(pick_label('+1/+1')(engine.state.pending_choice))
    engine.resolve_pending_choice(pick_label('flying')(engine.state.pending_choice))
    engine.resolve_pending_choice('done')
    assert src.counters == {'+1/+1': 2}
    assert dst.counters == {'+1/+1': 1, 'flying': 1}


def test_rikku_lets_the_controller_choose_which_kind_of_counter_to_move():
    engine = game()
    rikku = card(engine, 'Rikku, Resourceful Guardian')
    src = filler(engine, 'From', player='p2', power=3, toughness=3)
    dst = filler(engine, 'To', power=3, toughness=3)
    src.add_counters('+1/+1', 2)
    src.add_counters('flying', 1)
    engine.state.player_by_id('p1').mana_pool.add_many({'C': 1})
    activate(engine, rikku, targets=[src, dst])
    answer(engine, pick_label('flying'))
    assert src.counters == {'+1/+1': 2} and dst.counters == {'flying': 1}


def test_depthshaker_grants_melee_and_counts_distinct_attacked_opponents():
    engine = game(players=3)
    card(engine, 'Depthshaker Titan')
    first = filler(engine, 'First', type_line='Artifact Creature', power=2, toughness=2)
    second = filler(engine, 'Second', type_line='Artifact Creature', power=2, toughness=2)
    assert combat.has(first, 'melee')
    engine.state.current_phase, engine.state.current_step = 'combat', 'declare_attackers'
    engine.declare_attackers(engine.state.active_player, [
        {'attacker': first, 'defender': {'kind': 'player', 'id': 'p2'}},
        {'attacker': second, 'defender': {'kind': 'player', 'id': 'p3'}},
    ])
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()
    answer(engine)
    assert first.power == second.power == 4


def test_lulu_never_offers_a_creature_attacking_another_player():
    engine = game(players=3)
    lulu = card(engine, 'Lulu, Stern Guardian')
    at_you = filler(engine, 'At You', player='p2', power=2, toughness=2)
    at_them = filler(engine, 'At Them', player='p2', power=2, toughness=2)
    at_you.attacking = at_them.attacking = True
    at_you.combat_defender = {'kind': 'player', 'id': 'p1'}
    at_them.combat_defender = {'kind': 'player', 'id': 'p3'}
    spec = lulu.triggered_abilities[0].effects[0].target_spec
    assert [o['instance_id'] for o in legal_targets(engine.state, 'p1', spec, lulu)] == [at_you.instance_id]


def test_hellkite_attack_offer_honors_the_selected_opponent():
    engine = game(players=3)
    hellkite = card(engine, 'Territorial Hellkite')
    hellkite.must_attack_player_id = 'p3'
    engine.state.current_phase, engine.state.current_step = 'combat', 'declare_attackers'
    offer = next(a for a in engine.legal_actions(engine.state.active_player) if a['type'] == 'attack')
    assert [d['id'] for d in offer['legal_defenders']] == ['p3']


def test_infantry_shield_trigger_is_owned_by_the_creature_and_survives_detachment():
    engine = game()
    shield = card(engine, 'Infantry Shield')
    creature = filler(engine, 'Soldier', power=3, toughness=3)
    shield.attached_to = creature.instance_id
    engine.recompute_continuous_effects()
    engine.state.current_phase, engine.state.current_step = 'combat', 'declare_attackers'
    engine.declare_attackers(engine.state.active_player, [{'attacker': creature, 'defender': {'kind': 'player', 'id': 'p2'}}])
    shield.attached_to = None
    engine.resolve_until_stable()
    assert len(named(engine, 'Warrior')) == 3


def test_chakrams_buff_controlled_commanders_even_if_owned_by_an_opponent():
    engine = game()
    chakrams = card(engine, "Dancer's Chakrams")
    host = filler(engine, 'Host', power=1, toughness=1)
    stolen = filler(engine, 'Stolen Commander', power=2, toughness=2, player='p2')
    stolen.controller_id = 'p1'
    stolen.is_commander = True
    chakrams.attached_to = host.instance_id
    engine.recompute_continuous_effects()
    assert stolen.power == 4 and combat.has(stolen, 'lifelink')


def test_within_range_makes_one_trigger_for_the_completed_attack_declaration():
    engine = game(players=3)
    enchantment = card(engine, 'Within Range')
    first = filler(engine, 'First', power=1, toughness=1)
    second = filler(engine, 'Second', power=1, toughness=1)
    engine.state.current_phase, engine.state.current_step = 'combat', 'declare_attackers'
    engine.declare_attackers(engine.state.active_player, [
        {'attacker': first, 'defender': {'kind': 'player', 'id': 'p2'}},
        {'attacker': second, 'defender': {'kind': 'player', 'id': 'p3'}},
    ])
    engine._fire_player_attacked_events()
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack) == 1 and engine.state.stack[0].source is enchantment
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p2').life == engine.state.player_by_id('p3').life == 19


def test_cait_sith_chooses_the_pump_target_after_scry_and_exile():
    engine = game()
    cait = card(engine, 'Cait Sith, Fortune Teller')
    ally = filler(engine, 'Ally', power=1, toughness=1)
    top = filler(engine, 'Big Card', type_line='Sorcery', mv=4, zone=Zone.LIBRARY)
    from tests.support.deck_batch import stack_library
    stack_library(engine, 'p1', top)
    step(engine, 'begin_combat')
    assert engine.state.pending_choice['kind'] != 'trigger_target'
    engine.resolve_pending_choice('decline')
    assert top.zone == Zone.EXILE and engine.state.pending_choice['kind'] == 'trigger_target'
    answer(engine, pick_label('Ally'))
    assert ally.power == 5


def test_kujata_discard_payoff_is_a_separate_reflexive_trigger():
    engine = game()
    kujata = card(engine, 'Summon: Kujata')
    discard = filler(engine, 'Discard Me', type_line='Sorcery', mv=3, zone=Zone.HAND)
    filler(engine, 'Keep Me', type_line='Sorcery', mv=1, zone=Zone.HAND)
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine.state.fire_event(GameEvent(EventType.SAGA_CHAPTER, instance_id=kujata.instance_id, chapter=3, controller_id='p1'))
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice
    engine.rules.resolve_choice(str(discard.instance_id))
    engine.rules.resume_deferred_effects()
    assert engine.state.player_by_id('p2').life == 20
    engine.rules.put_triggers_on_stack()
    assert engine.state.stack
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p2').life == 17


def test_counter_move_removes_nothing_when_destination_cannot_receive_counters():
    engine = game()
    defense = card(engine, 'Resourceful Defense')
    src = filler(engine, 'From', power=2, toughness=2)
    dst = filler(engine, 'To', power=2, toughness=2)
    src.add_counters('+1/+1', 1)
    from mtg_analyzer.game.effects.core import EffectRegistry
    prohibition = EffectRegistry.create('counter_placement_prohibition', {'affects': 'all_creatures', 'counter_kind': 'all'})
    prohibition.source = defense
    defense.static_effects.append(prohibition)
    engine.recompute_continuous_effects()
    engine.state.player_by_id('p1').mana_pool.add_many({'C': 4, 'W': 1})
    activate(engine, defense, targets=[src, dst])
    engine.resolve_pending_choice('0')
    engine.resolve_pending_choice('done')
    assert src.counters.get('+1/+1') == 1 and not dst.counters


def test_kimahri_keeps_only_ronso_rage_when_copying_again():
    engine = game()
    kimahri = card(engine, 'Kimahri, Valiant Guardian')
    visionary = card(engine, 'Elvish Visionary', player='p2')
    plain = filler(engine, 'Plain', player='p2', power=2, toughness=2)
    step(engine, 'begin_combat')
    answer(engine, pick_label('Elvish Visionary', 'Ja'))
    assert len(kimahri.triggered_abilities) == 2
    step(engine, 'begin_combat')
    answer(engine, pick_label('Plain', 'Ja'))
    assert len(kimahri.triggered_abilities) == 1 and combat.has(kimahri, 'vigilance')
