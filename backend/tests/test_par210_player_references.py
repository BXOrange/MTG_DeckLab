"""PAR-210: event-player references name the caster/recipient, never the source's controller."""
from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.game import creature, make_engine

DB = CardDatabase(DB_PATH)


def game():
    eng = make_engine([creature(f'Library {i}') for i in range(12)],
                      [creature(f'Other {i}') for i in range(12)], hand=0)
    eng.begin_turn()
    eng.state.current_step = 'main1'
    return eng


def board(eng, card, owner='p1'):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


@pytest.mark.parametrize('name,loss,gain', [
    ('Soot Imp', 1, 0), ('Curse of Wizardry', 1, 0),
    ('Kambal, Consul of Allocation', 2, 2), ("Yawgmoth's Edict", 1, 1),
])
def test_actual_spell_cast_names_the_caster(name, loss, gain):
    eng = game()
    card = DB.get_card(name)
    assert card is not None and parse_oracle(card).modeled
    source = board(eng, card)
    source.chosen_color = 'W'
    spell = GameObject(Card(id='white-spell', name='White Spell', type_line='Instant',
                            is_instant=True, mana_cost_string='{W}',
                            oracle_text='You gain 1 life.'), owner_id='p2', zone=Zone.HAND)
    bind_from_catalogue(spell)
    payer = eng.state.player_by_id('p2')
    payer.hand.append(spell)
    payer.mana_pool.add('W', 1)
    eng.cast_spell(payer, spell)
    eng.resolve_until_stable()
    assert payer.life == 21 - loss
    assert eng.state.player_by_id('p1').life == 20 + gain


def test_krydle_uses_the_damaged_player_for_loss_and_mill_and_the_controller_for_gain():
    eng = game()
    card = DB.get_card("Krydle of Baldur's Gate")
    assert card is not None and parse_oracle(card).modeled
    krydle = board(eng, card)
    eng.rules.deal_damage(eng.state.player_by_id('p2'), 2, source=krydle, combat=True)
    eng.resolve_until_stable()
    while eng.state.pending_choice:
        choice = eng.state.pending_choice
        ids = [o['id'] for o in choice['options']]
        eng.resolve_pending_choice('keep' if 'keep' in ids else ids[0])
        eng.resolve_until_stable()
    assert eng.state.player_by_id('p2').life == 17
    assert len(eng.state.player_by_id('p2').graveyard) == 1
    assert eng.state.player_by_id('p1').life == 21
    assert not eng.state.player_by_id('p1').graveyard


@pytest.mark.parametrize('text', [
    'That player loses 2 life.',
    'Whenever you cast a spell, that player loses 2 life.',
    'Whenever ~ deals damage to a creature, that player loses 2 life.',
])
def test_absent_or_rival_antecedents_fail_closed(text):
    assert not parse_oracle(creature('Ambiguous', oracle_text=text)).modeled


def test_ashenmoor_liege_retains_the_targeting_spells_controller_as_its_referent():
    eng = game()
    liege = board(eng, DB.get_card('Ashenmoor Liege'))
    spell = GameObject(Card(id='pump', name='Pump', type_line='Instant', is_instant=True,
                            mana_cost_string='{0}', oracle_text='Target creature gets +1/+1 until end of turn.'),
                       owner_id='p2', zone=Zone.HAND)
    bind_from_catalogue(spell)
    eng.state.player_by_id('p2').hand.append(spell)
    eng.cast_spell(eng.state.player_by_id('p2'), spell, targets=[liege])
    eng.resolve_until_stable()
    assert eng.state.player_by_id('p2').life == 16
    assert eng.state.player_by_id('p1').life == 20


def test_poison_counter_body_uses_the_damage_recipient_without_targeting_them():
    eng = game()
    viper = board(eng, DB.get_card('Marsh Viper'))
    eng.rules.deal_damage(eng.state.player_by_id('p2'), 1, source=viper)
    eng.resolve_until_stable()
    assert eng.state.player_by_id('p2').poison == 2
    assert not eng.state.player_by_id('p1').poison


@pytest.mark.parametrize('demon', [False, True])
def test_scroll_of_griselbrand_binds_that_player_to_the_announced_opponent(demon):
    eng = game()
    scroll = board(eng, DB.get_card('Scroll of Griselbrand'))
    assert parse_oracle(scroll.card).modeled
    if demon:
        board(eng, creature('Demon', type_line='Creature — Demon'))
    p1, p2 = eng.state.player_by_id('p1'), eng.state.player_by_id('p2')
    from mtg_analyzer.models.game.game_object import GameObject
    victim = GameObject(creature('Discard'), owner_id='p2', zone=Zone.HAND)
    p2.hand.append(victim)
    p1.mana_pool.add('C', 1)
    eng.activate_ability(p1, scroll, targets=[p2])
    eng.resolve_until_stable()
    while eng.state.pending_choice:
        choice = eng.state.pending_choice
        eng.resolve_pending_choice(next(o['id'] for o in choice['options'] if o['id'] != 'decline'))
        eng.resolve_until_stable()
    assert victim.zone is Zone.GRAVEYARD
    assert p2.life == (17 if demon else 20)
    assert p1.life == 20


def test_aphelia_uses_the_nested_combat_trigger_and_only_matching_contributors():
    eng = game()
    aphelia = board(eng, DB.get_card('Aphelia, Viper Whisperer'))
    assert parse_oracle(aphelia.card).modeled
    p1, p2 = eng.state.player_by_id('p1'), eng.state.player_by_id('p2')
    p1.mana_pool.add_many({'B': 1, 'C': 4})
    eng.activate_ability(p1, aphelia)
    eng.resolve_until_stable()
    first = board(eng, creature('First Snake', type_line='Creature — Snake'))
    second = board(eng, creature('Second Snake', type_line='Creature — Snake'))
    bear = board(eng, creature('Bear'))
    p2.life = 19
    eng._apply_combat_damage([(p2, 1, first), (p2, 1, second)])
    eng.resolve_until_stable()
    assert p2.life == 8  # 19 - 2 = 17; one trigger, rounded-up half = 9
    eng._apply_combat_damage([(p2, 1, bear)])
    eng.resolve_until_stable()
    assert p2.life == 7
