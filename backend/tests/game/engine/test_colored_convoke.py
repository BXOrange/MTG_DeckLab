"""RULE 702.51: creature colors contribute directly to spell payment, never mana."""
import pytest

from tests.test_par23_cost_help_keywords import _bf, _card, _engine, _hand, _main


def _setup(cost, helper_costs, mana=None):
    engine = _engine()
    _main(engine)
    player = engine.state.players[0]
    helpers = [_bf(engine.state, _card(f'Helper {i}', cost=color))
               for i, color in enumerate(helper_costs)]
    spell = _hand(engine.state, _card('Convoke test', cost=cost, keywords=['Convoke'],
                  type_line='Creature — Bear', oracle_text='Convoke', power=2, toughness=2))
    if mana:
        player.mana_pool.add_many(mana)
    return engine, player, helpers, spell


@pytest.mark.parametrize('cost,helpers', [('{G}', ['{G}']), ('{W}{G}', ['{W}{G}', '{G}']),
                                         ('{W/U}', ['{U}']), ('{2/W}', ['{G}', '{G}'])])
def test_colored_and_hybrid_payments_use_a_globally_legal_helper_assignment(cost, helpers):
    engine, player, creatures, spell = _setup(cost, helpers)
    assert engine.can_cast(player, spell, help_pay=True)
    assert not any(creature.tapped for creature in creatures)  # preview is read-only
    engine.cast_spell(player, spell, help_pay=True)
    assert all(creature.tapped for creature in creatures)
    assert set(spell.convoked_by_ids) == {c.instance_id for c in creatures}
    assert spell.mana_spent_to_cast == 0
    assert player.mana_pool.total() == 0


@pytest.mark.parametrize('cost,helpers', [('{G}', ['{R}']), ('{C}', ['{C}'])])
def test_convoke_cannot_pay_an_unmatched_or_specifically_colorless_symbol(cost, helpers):
    engine, player, creatures, spell = _setup(cost, helpers)
    assert not engine.can_cast(player, spell, help_pay=True)
    assert not any(creature.tapped for creature in creatures)


def test_existing_mana_reduces_helper_count_and_only_real_mana_is_recorded():
    engine, player, creatures, spell = _setup('{W}{G}', ['{W}{G}', '{G}'], {'G': 1})
    assert engine.can_cast(player, spell, help_pay=True)
    engine.cast_spell(player, spell, help_pay=True)
    assert [creature.tapped for creature in creatures] == [True, False]
    assert spell.mana_spent_to_cast == 1


def test_summoning_sick_creature_can_convoke_but_tapped_or_opposing_cannot():
    engine, player, creatures, spell = _setup('{G}', ['{G}'])
    creatures[0].summoning_sick = True
    assert engine.can_cast(player, spell, help_pay=True)
    creatures[0].tapped = True
    _bf(engine.state, _card('Opponent helper', cost='{G}'), controller='p2')
    assert not engine.can_cast(player, spell, help_pay=True)
