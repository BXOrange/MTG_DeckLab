"""Plumb pays its optional sacrifice at casting and creates real stack copies."""
import pytest

from mtg_analyzer.game.card_registry import is_registered, specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_mardu_surge_deck import _game, _card, _filler


def _setup():
    engine = _game()
    engine.state.current_step = 'main1'
    player = engine.state.player_by_id('p1')
    spell = _card(engine, 'Plumb the Forbidden', zone=Zone.HAND)
    player.mana_pool.add_many({'B': 1, 'C': 1})
    return engine, player, spell


def test_registered_body_and_cost_use_shared_primitives():
    engine, player, spell = _setup()
    assert is_registered(spell.name)
    specs = specs_for(spell.card)
    assert [s.type for s in specs[0].effects] == ['draw', 'lose_life']
    assert specs[0].additional_cost_optional
    assert specs[1].effects[0].type == 'copy_spell'


def test_no_sacrifice_cast_has_only_original_and_base_draw_loss():
    engine, player, spell = _setup()
    engine.cast_spell(player, spell)
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack) == 1
    engine.resolve_until_stable()
    assert len(player.hand) == 1 and player.life == 19


@pytest.mark.parametrize('count', [1, 2, 3])
@pytest.mark.parametrize('tokens', [False, True])
def test_sacrifices_are_paid_before_trigger_and_make_separate_copies(count, tokens):
    engine, player, spell = _setup()
    victims = [_filler(engine, f'Victim {i}', power=1, toughness=1) for i in range(count + 1)]
    for obj in victims:
        obj.is_token = tokens
    engine.cast_spell(player, spell, pay_additional=True,
                      sacrifice_choices=[o.instance_id for o in victims[:count]])
    assert all(o.zone == Zone.GRAVEYARD for o in victims[:count])
    assert victims[-1].zone == Zone.BATTLEFIELD
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack) == 2 and engine.state.stack[-1].kind == 'ability'
    engine.rules.resolve_top_of_stack()
    copies = [i for i in engine.state.stack if i.obj is not None and getattr(i.obj, "is_copy", False)]
    assert len(copies) == count
    assert player.life == 20  # Copies can be answered before they resolve.
    engine.resolve_until_stable()
    assert len(player.hand) == count + 1 and player.life == 19 - count


def test_original_can_be_countered_before_cost_trigger_without_losing_copies():
    engine, player, spell = _setup()
    victim = _filler(engine, 'Victim', power=1, toughness=1)
    engine.cast_spell(player, spell, pay_additional=True, sacrifice_choices=[victim.instance_id])
    engine.rules.put_triggers_on_stack()
    engine.rules.counter_spell(spell)
    engine.resolve_until_stable()
    assert len(player.hand) == 1 and player.life == 19


def test_cost_trigger_can_be_countered_without_refunding_sacrifice():
    engine, player, spell = _setup()
    victim = _filler(engine, 'Victim', power=1, toughness=1)
    engine.cast_spell(player, spell, pay_additional=True, sacrifice_choices=[victim.instance_id])
    engine.rules.put_triggers_on_stack()
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD and len(player.hand) == 1 and player.life == 19


def test_sacrificed_magecraft_creature_never_sees_cast_or_copies():
    engine, player, spell = _setup()
    mage = _card(engine, 'Archmage Emeritus')
    engine.cast_spell(player, spell, pay_additional=True, sacrifice_choices=[mage.instance_id])
    engine.resolve_until_stable()
    assert len(player.hand) == 2 and player.life == 18


def test_surviving_magecraft_sees_each_copy_separately():
    engine, player, spell = _setup()
    _card(engine, 'Archmage Emeritus')
    victims = [_filler(engine, f'Victim{i}', power=1, toughness=1) for i in range(2)]
    engine.cast_spell(player, spell, pay_additional=True,
                      sacrifice_choices=[o.instance_id for o in victims])
    for _ in range(20):
        engine.resolve_until_stable()
        choice = engine.state.pending_choice
        if not choice:
            break
        engine.resolve_pending_choice(choice['options'][0]['id'])
    assert len(player.hand) == 6  # Three Plumb draws and one magecraft trigger per cast/copy.
    assert player.life == 17
