"""RULE 601.2c/h: choose Kotis's other graveyard cards before paying/casting."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.game_session import GameSession
from tests.game.catalogue.cards.test_sultai_arisen_deck import _kotis_game, _filler


def test_kotis_exiles_selected_three_and_preserves_the_oldest_cards():
    engine, player, kotis, spell, fodder = _kotis_game(5)
    picks = [card.instance_id for card in fodder[2:]]
    engine.cast_spell(player, spell, graveyard_exile_choices=picks)
    assert spell.zone == Zone.STACK
    assert all(card.zone == Zone.EXILE for card in fodder[2:])
    assert all(card.zone == Zone.GRAVEYARD for card in fodder[:2])
    engine.rules.counter_spell(spell)
    assert spell.zone == Zone.GRAVEYARD
    assert all(card.zone == Zone.EXILE for card in fodder[2:])  # Costs stay paid after countering.
    assert kotis.graveyard_casts_this_turn == 1


@pytest.mark.parametrize('bad_kind', ['duplicate', 'spell', 'too_few', 'too_many', 'foreign', 'left_zone'])
def test_invalid_exile_selection_rejects_before_paying_any_cost(bad_kind):
    engine, player, kotis, spell, fodder = _kotis_game(5)
    spell.card.mana_cost_string = '{1}{G}'
    spell.card.mana_cost = {'generic': 1, 'G': 1}
    player.mana_pool.add_many({'C': 1, 'G': 1})
    picks = [card.instance_id for card in fodder[2:]]
    if bad_kind == 'duplicate':
        picks[1] = picks[0]
    elif bad_kind == 'spell':
        picks[0] = spell.instance_id
    elif bad_kind == 'too_few':
        picks.pop()
    elif bad_kind == 'too_many':
        picks.append(fodder[0].instance_id)
    elif bad_kind == 'foreign':
        foreign = _filler(engine, 'Foreign', 'Sorcery', zone=Zone.GRAVEYARD, player='p2')
        picks[0] = foreign.instance_id
    else:
        player.graveyard.remove(fodder[2])
        fodder[2].zone = Zone.EXILE
        player.exile.append(fodder[2])
    before_mana = player.mana_pool.total()
    before_graveyard = list(player.graveyard)
    with pytest.raises(ValueError, match='distinct other cards'):
        engine.cast_spell(player, spell, graveyard_exile_choices=picks)
    assert player.mana_pool.total() == before_mana
    assert player.graveyard == before_graveyard
    assert spell.zone == Zone.GRAVEYARD
    assert kotis.graveyard_casts_this_turn == 0
    assert not engine.state.stack


def test_kotis_offer_exposes_all_eligible_other_cards_as_cost_choices():
    engine, player, kotis, spell, fodder = _kotis_game(5)
    action = next(a for a in engine.legal_actions(player) if a.get('type') == 'cast_spell'
                  and a.get('instance_id') == spell.instance_id)
    cost = action['graveyard_exile_cost']
    assert cost['count'] == 3
    assert {o['instance_id'] for o in cost['options']} == {c.instance_id for c in fodder}
    assert not action.get('requires_target')  # These selections are costs, not targets.


def test_kotis_session_payload_and_rewind_preserve_alternate_selection():
    engine, player, kotis, spell, fodder = _kotis_game(5)
    session = GameSession(engine, mode='replay', require_setup=False)
    session.apply_action({'type': 'cast_spell', 'instance_id': spell.instance_id,
                          'graveyard_exile_choices': [c.instance_id for c in fodder[2:]]})
    assert all(c.zone == Zone.EXILE for c in fodder[2:])
    session.rewind()
    restored = session.engine
    restored_spell = restored.state.find_object(spell.instance_id)
    assert restored_spell.zone == Zone.GRAVEYARD
    session.apply_action({'type': 'cast_spell', 'instance_id': spell.instance_id,
                          'graveyard_exile_choices': [c.instance_id for c in fodder[:3]]})
    assert all(restored.state.find_object(c.instance_id).zone == Zone.EXILE for c in fodder[:3])
    assert all(restored.state.find_object(c.instance_id).zone == Zone.GRAVEYARD for c in fodder[3:])
