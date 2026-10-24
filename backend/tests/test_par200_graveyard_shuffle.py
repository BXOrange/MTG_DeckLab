"""PAR-200: whole-graveyard shuffles retain real player targets and batch moves."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from tests.test_bug4_player_target_recheck import _grant_hexproof

TEXT = 'Target player shuffles their graveyard into their library.'


def engine():
    eng = GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', [])], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = 'main1'
    return eng


def put(eng, name, owner='p1', zone=Zone.HAND, text='', kind='Instant'):
    card = Card(id=name, name=name, type_line=kind, oracle_text=text,
                is_instant=kind == 'Instant', is_sorcery=kind == 'Sorcery')
    obj = GameObject(card, owner_id=owner, zone=zone)
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        eng.state.player_by_id(owner).add_to_zone(obj, zone)
    return obj


def cast(eng, target):
    spell = put(eng, 'Reminisce', text=TEXT, kind='Sorcery')
    eng.cast_spell(eng.state.players[0], spell, targets=[target])
    return spell


def test_parse_target_and_owner_axes_and_reject_modified_shapes():
    assert match_clause(TEXT.lower().rstrip(".")) == [EffectSpec('shuffle_graveyard_into_library', {'target_kind': 'player'})]
    assert match_clause('its owner shuffles their graveyard into their library', reading=ClauseReading(self_subject=True)) == [EffectSpec('shuffle_graveyard_into_library', {'owner_of_source': True})]
    assert match_clause('its owner shuffles their graveyard into their library') is None
    assert match_clause('target player shuffles their graveyard and hand into their library.') is None
    assert match_clause('target player shuffles their graveyard into your library.') is None
    assert match_clause('target player shuffles their graveyard into their library unless they pay 2.') is None
    assert parse_oracle(Card(id='Reminisce', name='Reminisce', type_line='Sorcery', is_sorcery=True, oracle_text=TEXT)).modeled


@pytest.mark.parametrize('target_index', [0, 1])
def test_real_cast_moves_only_target_graveyard_and_shuffles_once(target_index):
    eng = engine(); target = eng.state.players[target_index]
    graves = [put(eng, f'Grave{i}', owner=p.id, zone=Zone.GRAVEYARD) for i, p in enumerate(eng.state.players)]
    hands = [put(eng, f'Hand{i}', owner=p.id) for i, p in enumerate(eng.state.players)]
    spell = cast(eng, target)
    eng.resolve_until_stable()
    assert graves[target_index] in target.library
    assert graves[1-target_index] in eng.state.players[1-target_index].graveyard
    assert all(h in p.hand for h, p in zip(hands, eng.state.players))
    assert spell in eng.state.players[0].graveyard
    assert sum(e.type == EventType.SHUFFLE for e in eng.state.event_log) == 1


def test_empty_graveyard_still_shuffles_and_can_be_targeted():
    eng = engine(); cast(eng, eng.state.players[1]); eng.resolve_until_stable()
    assert sum(e.type == EventType.SHUFFLE for e in eng.state.event_log) == 1


def test_announcement_requires_a_player_and_respects_hexproof():
    eng = engine(); p, q = eng.state.players
    spell = put(eng, 'Reminisce', text=TEXT, kind='Sorcery')
    effect = spell.spell_effects[0]
    assert q.id in {o.get('player_id') for o in legal_targets(eng.state, p.id, effect.target_spec, source=spell)}
    _grant_hexproof(eng, q.id)
    assert q.id not in {o.get('player_id') for o in legal_targets(eng.state, p.id, effect.target_spec, source=spell)}
    eng.state._physical_cast_validation = True
    with pytest.raises(ValueError):
        eng.cast_spell(p, spell, targets=[q])
    with pytest.raises(ValueError):
        eng.cast_spell(p, spell, targets=[spell])


def test_player_becoming_illegal_in_response_does_not_shuffle():
    eng = engine(); q = eng.state.players[1]
    grave = put(eng, 'Grave', q.id, Zone.GRAVEYARD)
    cast(eng, q); _grant_hexproof(eng, q.id); eng.resolve_until_stable()
    assert grave in q.graveyard
    assert not any(e.type == EventType.SHUFFLE for e in eng.state.event_log)


def test_actual_activation_and_cloned_commander_resume_keep_one_departure_batch():
    eng = engine(); p, q = eng.state.players
    source = put(eng, 'Thran Foundry', zone=Zone.BATTLEFIELD, kind='Artifact',
                 text='{1}, {T}, Exile Thran Foundry: ' + TEXT)
    first = put(eng, 'CommanderA', q.id, Zone.GRAVEYARD); first.is_commander = True
    second = put(eng, 'CommanderB', q.id, Zone.GRAVEYARD); second.is_commander = True
    p.mana_pool.add_many({'C': 1})
    eng.activate_ability(p, source, targets=[q]); eng.resolve_until_stable()
    assert source in p.exile
    assert eng.state.pending_choice['player_id'] == q.id
    assert not any(e.type == EventType.CARDS_LEFT_GRAVEYARD for e in eng.state.event_log)
    restored = GameEngine(eng.state.clone())
    restored.resolve_pending_choice('decline'); restored.resolve_pending_choice('command')
    restored.resolve_until_stable()
    rq = restored.state.player_by_id(q.id)
    assert any(o.instance_id == first.instance_id for o in rq.library)
    assert any(o.instance_id == second.instance_id for o in rq.command)
    events = [e for e in restored.state.event_log if e.type == EventType.CARDS_LEFT_GRAVEYARD]
    assert len(events) == 1 and len(events[0].get('cards')) == 2
    assert sum(e.type == EventType.SHUFFLE for e in restored.state.event_log) == 1
    assert not restored.state._batch_hold


def test_clear_the_mind_draws_for_controller_after_opponent_commander_choice():
    eng = engine(); p, q = eng.state.players
    draw = put(eng, 'Draw card', p.id, Zone.LIBRARY)
    commander = put(eng, 'Commander', q.id, Zone.GRAVEYARD); commander.is_commander = True
    spell = put(eng, 'Clear the Mind', text=TEXT + '\nDraw a card.', kind='Sorcery')
    eng.cast_spell(p, spell, targets=[q]); eng.resolve_until_stable()
    assert eng.state.pending_choice['player_id'] == q.id
    assert draw in p.library and not p.hand
    eng.resolve_pending_choice('decline'); eng.resolve_until_stable()
    assert draw in p.hand and not q.hand
    assert commander in q.library and spell in p.graveyard


def test_each_player_wrapper_shuffles_every_graveyard_without_announced_targets():
    eng = engine()
    graves = [put(eng, f'Grave{i}', p.id, Zone.GRAVEYARD) for i, p in enumerate(eng.state.players)]
    spell = put(eng, 'Mnemonic Nexus', text='Each player shuffles their graveyard into their library.')
    eng.cast_spell(eng.state.players[0], spell); eng.resolve_until_stable()
    assert all(grave in p.library for grave, p in zip(graves, eng.state.players))
    assert sum(e.type == EventType.SHUFFLE for e in eng.state.event_log) == 2


def test_primal_command_modal_shuffle_targets_independently_of_life_gain():
    eng = engine(); p, q = eng.state.players
    grave = put(eng, 'Grave', q.id, Zone.GRAVEYARD)
    text = ("Choose two —\n• Target player gains 7 life.\n"
            "• Put target noncreature permanent on top of its owner's library.\n"
            "• Target player shuffles their graveyard into their library.\n"
            "• Search your library for a creature card, reveal it, put it into your hand, then shuffle.")
    spell = put(eng, 'Primal Command', text=text, kind='Sorcery')
    life = p.life
    eng.cast_spell(p, spell, mode=[0, 2], targets=[p, q], target_groups=[[p], [q]])
    eng.resolve_until_stable()
    assert p.life == life + 7 and grave in q.library
