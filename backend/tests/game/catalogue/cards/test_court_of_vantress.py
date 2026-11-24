"""Court targets once and retains only its own copiable upkeep ability."""
from mtg_analyzer.game.card_catalogue.c.court_of_vantress import UPKEEP
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, enter, filler, game, named, step


def board(monarch=False):
    engine = game(players=3, library=30)
    source = card(engine, 'Court of Vantress')
    target = card(engine, 'Sol Ring', player='p2')
    engine.state.monarch_id = 'p1' if monarch else 'p2'
    return engine, source, target


def announce(engine, target=None):
    step(engine, 'upkeep')
    assert engine.state.pending_choice['kind'] == 'trigger_target'
    engine.resolve_pending_choice(str(target.instance_id) if target else 'decline')


def accept(engine):
    assert engine.state.pending_choice['kind'] == 'composite_optional'
    engine.resolve_pending_choice('yes')
    engine.resolve_until_stable()


def test_specs_are_fresh_and_both_triggers_bind():
    engine, source, target = board()
    a, b = specs_for(source.card), specs_for(source.card)
    assert len(a) == 2 and a[1] is not b[1]
    assert a[1].effects[0] is not b[1].effects[0]
    assert len(source.triggered_abilities) == 2


def test_entering_becomes_monarch():
    engine, source, target = board()
    enter(engine, source)
    assert engine.state.monarch_id == 'p1'


def test_monarch_option_creates_copy_of_target_without_changing_court():
    engine, source, target = board(monarch=True)
    announce(engine, target); accept(engine)
    tokens = named(engine, 'Sol Ring', 'p1')
    assert len(tokens) == 1 and tokens[0].is_token
    assert source.name == 'Court of Vantress' and target.controller_id == 'p2'


def test_nonmonarch_option_changes_source_and_keeps_only_upkeep():
    engine, source, target = board()
    announce(engine, target); accept(engine)
    assert source.name == 'Sol Ring' and not source.is_token
    assert len(source.triggered_abilities) == 1
    assert source.card.granted_ability_lines == (UPKEEP,)
    assert engine.state.monarch_id == 'p2'
    engine.tap_for_mana(engine.state.players[0], source)
    assert engine.state.players[0].mana_pool.total() == 2


def test_optional_token_creation_can_be_declined():
    engine, source, target = board(monarch=True)
    announce(engine, target)
    engine.resolve_pending_choice('decline')
    assert not named(engine, 'Sol Ring', 'p1') and source.name == 'Court of Vantress'


def test_optional_self_copy_can_be_declined():
    engine, source, target = board()
    announce(engine, target)
    engine.resolve_pending_choice('decline')
    assert source.name == 'Court of Vantress' and len(source.triggered_abilities) == 2


def test_no_target_is_legal_and_produces_no_optional_prompt():
    engine, source, target = board()
    announce(engine)
    assert engine.state.pending_choice is None and source.name == 'Court of Vantress'


def test_targets_include_other_enchantments_and_artifacts_but_not_self_or_vanilla_creature():
    engine, source, target = board()
    enchantment = filler(engine, 'Other enchantment', type_line='Enchantment', player='p2')
    creature = filler(engine, 'Creature', power=2, toughness=2)
    step(engine, 'upkeep')
    ids = {option.get('instance_id') for option in engine.state.pending_choice['options']}
    assert target.instance_id in ids and enchantment.instance_id in ids
    assert source.instance_id not in ids and creature.instance_id not in ids


def test_only_controllers_upkeep_triggers():
    engine, source, target = board()
    step(engine, 'upkeep', player='p2')
    assert engine.state.pending_choice is None


def test_losing_monarchy_after_trigger_uses_nonmonarch_branch():
    engine, source, target = board(monarch=True)
    step(engine, 'upkeep')
    engine.state.monarch_id = 'p2'
    engine.resolve_pending_choice(str(target.instance_id)); accept(engine)
    assert source.name == 'Sol Ring' and not named(engine, 'Sol Ring', 'p1')[0].is_token


def test_gaining_monarchy_after_trigger_uses_token_branch():
    engine, source, target = board()
    step(engine, 'upkeep')
    engine.state.monarch_id = 'p1'
    engine.resolve_pending_choice(str(target.instance_id)); accept(engine)
    assert source.name == 'Court of Vantress' and named(engine, 'Sol Ring', 'p1')[0].is_token


def test_copied_upkeep_triggers_again_and_does_not_accumulate_old_targets_abilities():
    engine, source, target = board()
    announce(engine, target); accept(engine)
    replacement = filler(engine, 'New enchantment', type_line='Enchantment')
    announce(engine, replacement); accept(engine)
    assert source.name == 'New enchantment'
    assert len(source.triggered_abilities) == 1 and not source.activated_abilities
    assert source.card.granted_ability_lines == (UPKEEP,)


def test_copy_of_changed_court_inherits_and_can_use_retained_upkeep():
    engine, source, target = board()
    announce(engine, target); accept(engine)
    clone = engine.rules.copy_permanent('p1', source)[0]
    assert clone.card.granted_ability_lines == (UPKEEP,) and len(clone.triggered_abilities) == 1
    engine.rules.exile(source)
    replacement = filler(engine, 'Next enchantment', type_line='Enchantment')
    announce(engine, replacement); accept(engine)
    assert clone.name == 'Next enchantment' and clone.card.granted_ability_lines == (UPKEEP,)


def test_monarch_trigger_still_makes_token_when_court_left():
    engine, source, target = board(monarch=True)
    step(engine, 'upkeep')
    engine.rules.exile(source)
    engine.resolve_pending_choice(str(target.instance_id)); accept(engine)
    assert len(named(engine, 'Sol Ring', 'p1')) == 1 and source.zone == Zone.EXILE


def test_nonmonarch_trigger_does_not_change_departed_court():
    engine, source, target = board()
    step(engine, 'upkeep')
    engine.rules.exile(source)
    engine.resolve_pending_choice(str(target.instance_id)); accept(engine)
    assert source.name == 'Court of Vantress' and source.zone == Zone.EXILE


def test_blink_does_not_let_old_trigger_change_returned_court():
    engine, source, target = board()
    step(engine, 'upkeep')
    engine.rules.put_into_graveyard(source)
    engine.rules.return_from_graveyard(source, 'battlefield')
    engine.resolve_pending_choice(str(target.instance_id))
    if engine.state.pending_choice:
        accept(engine)
    engine.resolve_until_stable()
    assert source.name == 'Court of Vantress'


def test_clone_of_pending_optional_choice_resolves_independently():
    engine, source, target = board()
    announce(engine, target)
    clone = GameEngine(engine.state.clone())
    accept(clone)
    assert clone.state.find_object(source.instance_id).name == 'Sol Ring'
    assert source.name == 'Court of Vantress' and engine.state.pending_choice is not None


def placed_trigger(engine, target):
    step(engine, 'upkeep')
    engine.rules.resolve_choice(str(target.instance_id))
    assert engine.state.stack and engine.state.pending_choice is None
    return engine.state.stack[-1]


def test_countered_trigger_does_not_offer_copy():
    engine, source, target = board(monarch=True)
    trigger = placed_trigger(engine, target)
    engine.rules.counter_spell(trigger)
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and not named(engine, 'Sol Ring', 'p1')


def test_departed_target_makes_trigger_fizzle_without_prompt():
    engine, source, target = board(monarch=True)
    placed_trigger(engine, target)
    engine.rules.exile(target)
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and not named(engine, 'Sol Ring', 'p1')


def test_target_blink_does_not_make_returned_visit_a_legal_target():
    engine, source, target = board(monarch=True)
    placed_trigger(engine, target)
    engine.rules.put_into_graveyard(target)
    engine.rules.return_from_graveyard(target, 'battlefield')
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and not named(engine, 'Sol Ring', 'p1')


def test_source_blink_after_announcement_cannot_change_returned_visit():
    engine, source, target = board()
    placed_trigger(engine, target)
    engine.rules.put_into_graveyard(source)
    engine.rules.return_from_graveyard(source, 'battlefield')
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()  # the returned Court's ETB
    engine.state.monarch_id = 'p2'
    engine.resolve_until_stable()
    accept(engine)
    assert source.name == 'Court of Vantress'


def test_no_monarch_designation_uses_nonmonarch_branch():
    engine, source, target = board()
    engine.state.monarch_id = None
    announce(engine, target); accept(engine)
    assert source.name == 'Sol Ring' and engine.state.monarch_id is None


def test_original_trigger_controller_creates_token_after_source_changes_control():
    engine, source, target = board(monarch=True)
    placed_trigger(engine, target)
    source.controller_id = 'p2'
    engine.resolve_until_stable(); accept(engine)
    assert len(named(engine, 'Sol Ring', 'p1')) == 1
    assert len(named(engine, 'Sol Ring', 'p2')) == 1


def test_registered_copiable_ability_factory_returns_fresh_specs():
    from mtg_analyzer.game.card_registry.core import granted_line_specs
    engine, source, target = board()
    a = granted_line_specs(target.card, UPKEEP)
    b = granted_line_specs(target.card, UPKEEP)
    assert len(a) == len(b) == 1 and a[0] is not b[0]
    assert a[0].effects[0] is not b[0].effects[0]
