"""RULE 114.2/114.4 — one emblem carries all its quoted abilities."""
import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause, _emblem_ability_spec
from tests.support.game import creature, make_engine, obj_on_battlefield


def test_two_quotes_create_one_emblem_with_both_live_statics():
    engine = make_engine([], [])
    own = obj_on_battlefield(engine.state, engine, creature())
    enemy = obj_on_battlefield(engine.state, engine, creature('Enemy'), 'p2')
    specs = match_clause('you get an emblem with "creatures you control get +1/+1" '
                         'and "creatures you control have flying"')
    assert len(specs) == 1
    context = GameContext(engine.state, engine.rules)
    for effect in build_effects(specs):
        effect.apply(context)
    engine.recompute_continuous_effects()
    assert len(engine.state.players[0].emblems) == 1
    assert own.power == 3 and 'flying' in own.granted_keywords
    assert enemy.power == 2 and 'flying' not in enemy.granted_keywords


def test_each_opponent_gets_their_own_emblem_excluding_lost_players():
    engine = make_engine([], [])
    specs = match_clause('each opponent gets an emblem with "at the beginning of your upkeep, '
                         'this emblem deals 1 damage to you"')
    assert specs[0].params['each_opponent']
    for effect in build_effects(specs):
        effect.apply(GameContext(engine.state, engine.rules))
    assert not engine.state.players[0].emblems
    assert len(engine.state.players[1].emblems) == 1
    engine.state.players[1].has_lost = True
    for effect in build_effects(specs):
        effect.apply(GameContext(engine.state, engine.rules))
    assert len(engine.state.players[1].emblems) == 1


@pytest.mark.parametrize('body', [
    "at the beginning of your opponent's upkeep, draw a card",
    "your opponents can't cast noncreature spells",
    "creatures your opponents control don't untap during their controllers' untap steps",
])
def test_apostrophes_are_preserved_when_parsing_nested_abilities(body, monkeypatch):
    from mtg_analyzer.parser.oracle.catalogue import clause_hooks
    original = clause_hooks._segment_line  # the registered segmenter entry point (PAR-172)
    observed = []
    def spy(text, **kwargs):
        observed.append(text)
        return original(text, **kwargs)
    monkeypatch.setattr(clause_hooks, '_segment_line', spy)
    _emblem_ability_spec(body)
    assert observed[0] == body


def test_unsupported_second_ability_fails_closed():
    assert match_clause('you get an emblem with "creatures you control get +1/+1" '
                        'and "do something impossible"') is None


def test_nested_granted_ability_keeps_internal_contractions():
    body = "mountains you control have '{t}: ~ deals 1 damage to any target.'"
    assert _emblem_ability_spec(body) is not None


def test_fixed_base_emblem_keeps_counters_and_only_changes_own_creatures():
    engine = make_engine([], [])
    own = obj_on_battlefield(engine.state, engine, creature())
    enemy = obj_on_battlefield(engine.state, engine, creature('Enemy'), 'p2')
    own.add_counters('+1/+1', 2)
    ability = _emblem_ability_spec('creatures you control have base power and toughness 9/9')
    engine.rules.create_emblem(engine.state.players[0], ability)
    engine.recompute_continuous_effects()
    assert (own.power, own.toughness) == (11, 11)
    assert (enemy.power, enemy.toughness) == (2, 2)


def test_dynamic_token_count_reads_board_when_resolving():
    engine = make_engine([], [])
    body = ('at the beginning of your end step, create x 2/2 black zombie creature tokens, '
            'where x is 2 plus the number of zombies you control')
    ability = _emblem_ability_spec(body)
    own = obj_on_battlefield(engine.state, engine,
                             creature('Zombie', type_line='Creature — Zombie'))
    obj_on_battlefield(engine.state, engine,
                       creature('Enemy Zombie', type_line='Creature — Zombie'), 'p2')
    from mtg_analyzer.parser.oracle.spec import EffectSpec
    effects = build_effects([EffectSpec.from_dict(e) for e in ability['effects']])
    for effect in effects:
        effect.apply(GameContext(engine.state, engine.rules))
    tokens = [obj for obj in engine.state.battlefield if obj.is_token]
    assert len(tokens) == 3
    assert all(obj.controller_id == own.controller_id and obj.power == 2 for obj in tokens)


@pytest.mark.parametrize('phrase,expected', [
    ('a permanent card', {'type': ['creature', 'artifact', 'enchantment', 'land', 'planeswalker', 'battle']}),
    ('a blue or black creature card', {'type': 'creature', 'color': ['U', 'B']}),
])
def test_search_composes_type_and_color_or_filters(phrase, expected):
    specs = match_clause(f'search your library for {phrase}, put it onto the battlefield, then shuffle')
    assert specs[0].params['criteria'] == expected


def test_jaya_color_applies_to_both_spell_types_and_copies_twice():
    body = ('whenever you cast a red instant or sorcery spell, copy it twice. '
            'you may choose new targets for the copies.')
    ability = _emblem_ability_spec(body)
    assert ability['trigger']['spell_filter'] == {
        'card_type_any': ['instant', 'sorcery'], 'color': 'R'}
    assert ability['effects'][0]['params']['count'] == 2


def test_unknown_token_group_and_unknown_search_adjective_fail_closed():
    assert match_clause('create x 2/2 black zombie creature tokens, where x is 2 plus '
                        'the number of mysterious things') is None
    assert match_clause('search your library for a purple permanent card, '
                        'put it onto the battlefield, then shuffle') is None
