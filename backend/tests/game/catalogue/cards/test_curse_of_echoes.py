"""Curse of Echoes: individual choices, copy ownership and stack snapshots."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, RICH
from tests.support.star_trek import advance_to
from tests.support.deck_batch import game


def _board(enchanted='p1', owner='p3'):
    engine = game(players=4, library=30)
    advance_to(engine, 'main1')
    curse = card(engine, 'Curse of Echoes', player=owner)
    curse.attached_to = enchanted
    return engine, curse


def _answer(engine, decisions):
    asked = []
    for _ in range(12):
        choice = engine.state.pending_choice
        if not choice:
            break
        assert choice['kind'] == 'composite_optional'
        asked.append(choice['player_id'])
        engine.resolve_pending_choice('yes' if choice['player_id'] in decisions else 'decline')
        engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    return asked


def test_fresh_specs_and_binding():
    engine, curse = _board()
    a,b = specs_for(curse.card), specs_for(curse.card)
    assert len(a) == 2 and a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(curse.triggered_abilities) == 1


@pytest.mark.parametrize('accept',[set(), {'p2'}, {'p2','p3','p4'}])
def test_each_other_player_controls_their_optional_copy(accept):
    engine, curse = _board()
    spell = card(engine, 'Divination', zone=Zone.HAND)
    cast(engine, spell)
    assert _answer(engine, accept) == ['p2','p3','p4']
    assert [len(p.hand) for p in engine.state.players] == [3]+[2 if p in accept else 0 for p in ('p2','p3','p4')]


@pytest.mark.parametrize('kind',['Creature','Enchantment','Artifact','Planeswalker'])
def test_non_instant_non_sorcery_does_not_trigger(kind):
    engine, curse = _board()
    spell = filler(engine, 'Other spell', type_line=kind, zone=Zone.HAND, power=2 if kind == 'Creature' else None, toughness=2 if kind == 'Creature' else None)
    cast(engine, spell)
    assert engine.state.pending_choice is None


def test_unenchanted_caster_does_not_trigger():
    engine, curse = _board(enchanted='p2')
    cast(engine, card(engine, 'Divination', zone=Zone.HAND))
    assert engine.state.pending_choice is None
    assert len(engine.state.players[0].hand) == 3


def test_choice_survives_clone_and_source_departure():
    engine, curse = _board()
    cast(engine, card(engine, 'Divination', zone=Zone.HAND))
    engine.rules.exile(curse)
    engine = GameEngine(engine.state.clone())
    assert _answer(engine, {'p2','p4'}) == ['p2','p3','p4']
    assert [len(p.hand) for p in engine.state.players] == [3,2,0,2]


def test_original_countered_before_resolution_still_copies_last_known_spell():
    engine, curse = _board()
    spell = card(engine, 'Divination', zone=Zone.HAND)
    player = engine.state.players[0]
    player.mana_pool.add_many(RICH)
    engine.cast_spell(player, spell)
    engine.rules.put_triggers_on_stack()
    engine.rules.counter_spell(spell)
    engine.resolve_until_stable()
    assert _answer(engine, {'p2','p3','p4'}) == ['p2','p3','p4']
    assert [len(p.hand) for p in engine.state.players] == [1,2,2,2]


@pytest.mark.parametrize('retarget',[False, True])
def test_instant_copy_controller_can_keep_or_change_targets(retarget):
    engine, curse = _board()
    spell = card(engine, 'Lightning Bolt', zone=Zone.HAND)
    cast(engine, spell, targets=[engine.state.player_by_id('p4')])
    assert engine.state.pending_choice['player_id'] == 'p2'
    engine.resolve_pending_choice('yes')
    choice = engine.state.pending_choice
    assert choice['kind'] == 'copy_targets' and choice['player_id'] == 'p2'
    if retarget:
        option = next(o for o in choice['options'] if o.get('player_id') == 'p3')
        engine.resolve_pending_choice(option['id'])
    else:
        engine.resolve_pending_choice('decline')
    engine = GameEngine(engine.state.clone())
    assert _answer(engine, set()) == ['p3','p4']
    assert [p.life for p in engine.state.players] == ([20,20,17,17] if retarget else [20,20,20,14])


def test_aura_cast_attaches_to_chosen_player():
    engine = game(players=4)
    advance_to(engine, 'main1')
    curse = card(engine, 'Curse of Echoes', zone=Zone.HAND)
    cast(engine, curse, targets=[engine.state.player_by_id('p2')])
    assert curse.zone == Zone.BATTLEFIELD and curse.attached_to == 'p2'


def test_attachment_is_checked_at_cast_time_not_binding():
    engine, curse = _board(enchanted='p2')
    curse.attached_to = 'p1'
    cast(engine, card(engine, 'Divination', zone=Zone.HAND))
    curse.attached_to = 'p4'
    assert _answer(engine, {'p2','p4'}) == ['p2','p3','p4']
    assert [len(p.hand) for p in engine.state.players] == [3,2,0,2]
