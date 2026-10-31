"""Gamble: the discard after the tutor is random (RULE 701.8d), not a player choice."""
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from tests.test_mec118_opponent_choice import _engine, _put, _db_card


def test_gamble_discards_at_random_without_a_choice():
    eng = _engine()
    for name in ('H1', 'H2', 'H3'):
        _put(eng, Card(id=name, name=name, type_line='Sorcery', is_sorcery=True), 'p1', Zone.HAND)
    found = _put(eng, Card(id='F', name='Found', type_line='Sorcery', is_sorcery=True), 'p1', Zone.HAND)
    eng.state.active_player.hand.remove(found)
    found.zone = Zone.LIBRARY
    eng.state.active_player.library.append(found)
    spell = _put(eng, _db_card('Gamble'), 'p1', Zone.HAND)
    player = eng.state.active_player
    player.mana_pool.add_many({c: 5 for c in 'WUBRG'})
    eng.cast_spell(player, spell, targets=[])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice['eligible']
    eng.resolve_pending_choice(choice['eligible'][0]['instance_id'])
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None  # the discard asked nobody
    assert len(player.graveyard) == 2  # Gamble itself + exactly one randomly discarded card
    assert len(player.hand) == 3
