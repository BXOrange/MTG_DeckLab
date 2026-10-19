"""Existing mass-exile selectors feed one captured return and rider batch."""
import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature
from test_par157_back_selections import _cached


@pytest.mark.parametrize('subject,expected', [
    ('all creatures you control', {'Own', 'Borrowed'}),
    ('all creatures', {'Own', 'Borrowed', 'Enemy'}),
    ('all artifacts you control', {'Artifact'}),
])
@pytest.mark.parametrize('entry', ['', ' with a dream counter on them'])
def test_mass_subject_entry_and_rider_axes_recombine_with_exact_visits_and_clone(subject, expected, entry):
    eng = _engine()
    source = _bf(eng, Card(id='source', name='Source', type_line='Enchantment'))
    own = _bf(eng, _creature('Own'))
    borrowed = _bf(eng, _creature('Borrowed'), 'p2')
    borrowed.controller_id = 'p1'
    enemy = _bf(eng, _creature('Enemy'), 'p2')
    artifact = _bf(eng, Card(id='artifact', name='Artifact', type_line='Artifact'))
    pool = [own, borrowed, enemy, artifact]
    specs = parse_effect_body(f'exile {subject}. at the beginning of your next upkeep, '
        "return those cards to the battlefield tapped under their owners' control" + entry +
        ' and those creatures gain haste until end of turn')
    assert specs and len(specs) == 1 and specs[0].type == 'blink'
    effect = build_effects(specs, source)[0]
    assert not effect.target_specs
    effect.apply(eng.rules.context)
    assert {o.name for o in pool if o.zone == Zone.EXILE} == expected
    later = _bf(eng, _creature('Later'))
    clone = GameEngine(eng.state.clone())
    first = next(o for o in pool if o.name in expected)
    copied = clone.state.find_object(first.instance_id)
    clone.rules.return_to_hand(copied)
    clone.rules.exile(copied)
    clone._fire_delayed_triggers('upkeep')
    clone.resolve_until_stable()
    assert copied.zone == Zone.EXILE
    eng._fire_delayed_triggers('upkeep')
    eng.resolve_until_stable()
    for obj in pool:
        assert obj.zone == Zone.BATTLEFIELD
        if obj.name in expected:
            assert obj.tapped and 'haste' in obj.granted_keywords
            assert obj.counters == ({'dream': 1} if entry else {})
    assert borrowed.controller_id == ('p2' if borrowed.name in expected else 'p1')
    assert not later.tapped and not later.granted_keywords
    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert all('haste' not in obj.granted_keywords for obj in pool)


@pytest.mark.full_cache
@pytest.mark.parametrize('name', ["Legion's Initiative", 'Planar Guide'])
def test_real_mass_return_cards_reuse_the_shared_blink(name):
    eng = _engine()
    card = _cached(name)
    assert parse_oracle(card).modeled
    source = _bf(eng, card)
    visitor = _bf(eng, _creature('Visitor'))
    player = eng.state.player_by_id('p1')
    player.mana_pool.add_many({'C': 3, 'R': 1, 'W': 1})
    eng.activate_ability(player, source, 0)
    eng.resolve_until_stable()
    assert source.zone == visitor.zone == Zone.EXILE
    eng._fire_delayed_triggers('begin_combat' if name == "Legion's Initiative" else 'end')
    eng.resolve_until_stable()
    assert source.zone == Zone.EXILE and visitor.zone == Zone.BATTLEFIELD
    assert ('haste' in visitor.granted_keywords) == (name == "Legion's Initiative")
