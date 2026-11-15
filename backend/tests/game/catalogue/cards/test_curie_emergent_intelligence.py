"""Curie copies an activation's paid creature and draws from layer-7b base power."""
import pytest
from mtg_analyzer.game.card_catalogue.c.curie_emergent_intelligence import DRAW_LINE
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.effects.core import StaticAbility
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, named
from tests.support.star_trek import advance_to


def board():
    engine = game(players=3, library=40)
    advance_to(engine, 'main1')
    source = card(engine, 'Curie, Emergent Intelligence')
    return engine, source, engine.state.players[0]


def body(engine, name='Paid creature', power=4, player='p1'):
    return filler(engine, name, type_line='Artifact Creature — Robot', power=power,
                  toughness=6, player=player)


def activate(engine, source, target):
    player = engine.state.player_by_id(source.controller_id)
    player.mana_pool.add_many({'U': 1, 'C': 1})
    engine.activate_ability(player, source, 0, tap_choices=[target.instance_id])


def hit(engine, source, amount=1):
    engine.rules.deal_damage(engine.state.players[1], amount, source=source, combat=True)


def set_base(engine, source, power):
    source.static_effects.append(StaticAbility('pt_set', affects='self',
        params={'power': power, 'toughness': 6}, source=source))
    engine.recompute_continuous_effects()


def test_specs_are_fresh_and_both_abilities_bind():
    engine, source, player = board()
    a, b = specs_for(source.card), specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.triggered_abilities) == 1 and len(source.activated_abilities) == 1


def test_combat_damage_to_player_draws_one_for_original_base_power():
    engine, source, player = board(); before = len(player.hand)
    hit(engine, source, amount=3); engine.resolve_until_stable()
    assert len(player.hand) == before + 1


def test_noncombat_damage_does_not_trigger():
    engine, source, player = board(); before = len(player.hand)
    engine.rules.deal_damage(engine.state.players[1], 1, source=source)
    engine.resolve_until_stable()
    assert len(player.hand) == before


def test_combat_damage_to_creature_does_not_trigger():
    engine, source, player = board(); before = len(player.hand)
    target = body(engine, player='p2')
    engine.rules.deal_damage(target, 1, source=source, combat=True)
    engine.resolve_until_stable()
    assert len(player.hand) == before


def test_counters_and_modifiers_do_not_increase_base_power_draw():
    engine, source, player = board(); before = len(player.hand)
    source.add_counters('+1/+1', 3)
    source.static_effects.append(StaticAbility('pt_mod', affects='self',
        params={'power': 5, 'toughness': 5}, source=source))
    engine.recompute_continuous_effects()
    assert source.power == 9 and source.base_power == 1
    hit(engine, source); engine.resolve_until_stable()
    assert len(player.hand) == before + 1


def test_base_power_setting_effect_controls_draw_amount():
    engine, source, player = board(); before = len(player.hand)
    set_base(engine, source, 4)
    source.add_counters('+1/+1', 2); engine.recompute_continuous_effects()
    hit(engine, source); engine.resolve_until_stable()
    assert len(player.hand) == before + 4


def test_base_power_is_measured_at_resolution():
    engine, source, player = board(); before = len(player.hand)
    hit(engine, source)
    set_base(engine, source, 5)
    engine.resolve_until_stable()
    assert len(player.hand) == before + 5


@pytest.mark.parametrize('power', [0, -2])
def test_nonpositive_base_power_draws_no_cards(power):
    engine, source, player = board(); before = len(player.hand)
    set_base(engine, source, power)
    hit(engine, source); engine.resolve_until_stable()
    assert len(player.hand) == before


def test_departed_source_uses_last_known_base_power_instead_of_printed_or_total_power():
    engine, source, player = board(); before = len(player.hand)
    set_base(engine, source, 4)
    source.add_counters('+1/+1', 3); engine.recompute_continuous_effects()
    hit(engine, source)
    engine.rules.put_into_graveyard(source)
    engine.resolve_until_stable()
    assert len(player.hand) == before + 4


def test_activation_exiles_creature_and_pays_mana_before_copy_resolves():
    engine, source, player = board(); target = body(engine)
    activate(engine, source, target)
    assert target.zone == Zone.EXILE and source.name == 'Curie, Emergent Intelligence'
    assert player.mana_pool.total() == 0
    engine.resolve_until_stable()
    assert source.name == target.name and source.power == 4
    assert source.card.granted_ability_lines == (DRAW_LINE,)
    assert len(source.triggered_abilities) == 1 and not source.activated_abilities


def test_copied_creature_draws_its_own_base_power():
    engine, source, player = board(); target = body(engine, power=6)
    activate(engine, source, target); engine.resolve_until_stable()
    before = len(player.hand)
    hit(engine, source); engine.resolve_until_stable()
    assert len(player.hand) == before + 6


def test_cost_selection_excludes_self_tokens_nonartifacts_noncreatures_and_opponents():
    engine, source, player = board(); good = body(engine)
    token = body(engine, 'Token'); token.is_token = True
    other = body(engine, 'Opponent', player='p2')
    creature = filler(engine, 'Not artifact', power=2, toughness=2)
    artifact = card(engine, 'Sol Ring')
    player.mana_pool.add_many({'U': 1, 'C': 1})
    action = next(a for a in engine.legal_actions(player)
                  if a['type'] == 'activate_ability' and a.get('instance_id') == source.instance_id)
    assert [o['instance_id'] for o in action['exile_cost']['options']] == [good.instance_id]
    for invalid in (source, token, other, creature, artifact):
        assert not engine.can_activate(player, source, source.activated_abilities[0], tap_choices=[invalid.instance_id])


def test_no_eligible_creature_or_insufficient_mana_prevents_activation():
    engine, source, player = board()
    player.mana_pool.add_many({'U': 1, 'C': 1})
    assert not engine.can_activate(player, source, source.activated_abilities[0])
    target = body(engine); player.mana_pool.empty()
    assert not engine.can_activate(player, source, source.activated_abilities[0], tap_choices=[target.instance_id])
    assert target.zone == Zone.BATTLEFIELD


def test_cost_is_untargeted_so_hexproof_does_not_prevent_exile_payment():
    engine, source, player = board(); target = body(engine)
    target.temp_keywords.add('shroud')
    activate(engine, source, target); engine.resolve_until_stable()
    assert source.name == target.name and target.zone == Zone.EXILE


def test_countering_activation_keeps_cost_paid_but_does_not_copy():
    engine, source, player = board(); target = body(engine)
    activate(engine, source, target)
    engine.rules.counter_spell(engine.state.stack[-1]); engine.resolve_until_stable()
    assert target.zone == Zone.EXILE and source.name == 'Curie, Emergent Intelligence'


def test_two_stacked_activations_remember_their_separate_exiled_creatures():
    engine, source, player = board(); first = body(engine, 'First', 3); second = body(engine, 'Second', 5)
    activate(engine, source, first); activate(engine, source, second)
    engine.rules.resolve_top_of_stack()
    assert source.name == 'Second' and source.base_power == 5
    engine.rules.resolve_top_of_stack()
    assert source.name == 'First' and source.base_power == 3
    assert source.card.granted_ability_lines == (DRAW_LINE,)


def test_copy_effect_survives_paid_card_moving_again():
    engine, source, player = board(); target = body(engine)
    activate(engine, source, target)
    engine.rules.return_to_hand(target)
    engine.resolve_until_stable()
    assert source.name == target.name and target.zone == Zone.HAND


def test_departed_source_does_not_become_copy_in_graveyard():
    engine, source, player = board(); target = body(engine)
    activate(engine, source, target)
    engine.rules.put_into_graveyard(source); engine.resolve_until_stable()
    assert source.zone == Zone.GRAVEYARD and source.name == 'Curie, Emergent Intelligence'


def test_returned_source_is_not_changed_by_old_activation():
    engine, source, player = board(); target = body(engine)
    activate(engine, source, target)
    engine.rules.put_into_graveyard(source); engine.rules.return_from_graveyard(source, 'battlefield')
    engine.resolve_until_stable()
    assert source.name == 'Curie, Emergent Intelligence'


def test_undo_clone_preserves_activation_payment_snapshot():
    engine, source, player = board(); target = body(engine)
    activate(engine, source, target)
    clone = GameEngine(engine.state.clone()); clone.resolve_until_stable()
    assert clone.state.find_object(source.instance_id).name == target.name
    assert source.name == 'Curie, Emergent Intelligence'


def test_copy_of_changed_curie_inherits_copiable_draw_ability():
    engine, source, player = board(); target = body(engine)
    activate(engine, source, target); engine.resolve_until_stable()
    copy = engine.rules.copy_permanent(player.id, source)[0]
    assert copy.card.granted_ability_lines == (DRAW_LINE,)
    before = len(player.hand)
    hit(engine, copy); engine.resolve_until_stable()
    assert len(player.hand) == before + 4


def test_exiling_creature_that_is_a_copy_captures_copy_before_zone_reset():
    engine, source, player = board(); target = body(engine, 'Original', 2)
    template = body(engine, 'Copied form', 5)
    engine.rules.become_copy(target, template)
    engine.recompute_continuous_effects()
    activate(engine, source, target); engine.resolve_until_stable()
    assert target.name == 'Original' and target.zone == Zone.EXILE
    assert source.name == 'Original' and source.base_power == 2


def test_old_draw_trigger_uses_new_copy_base_power_at_resolution():
    engine, source, player = board(); target = body(engine, power=5)
    before = len(player.hand)
    hit(engine, source); engine.rules.put_triggers_on_stack()
    activate(engine, source, target)
    engine.resolve_until_stable()
    assert source.base_power == 5 and len(player.hand) == before + 5


def test_draw_trigger_uses_old_visit_base_power_after_source_returns():
    engine, source, player = board(); before = len(player.hand)
    from tests.support.deck_batch import cast
    setter = card(engine, 'Water Wings', zone=Zone.HAND)
    cast(engine, setter, targets=[source])
    hit(engine, source); engine.rules.put_triggers_on_stack()
    engine.rules.put_into_graveyard(source); engine.rules.return_from_graveyard(source, 'battlefield')
    engine.resolve_until_stable()
    assert source.base_power == 1 and len(player.hand) == before + 4


def test_copying_another_printed_curie_retains_its_own_abilities_and_adds_draw():
    engine, source, player = board()
    target = card(engine, 'Curie, Emergent Intelligence')
    activate(engine, source, target); engine.resolve_until_stable()
    before = len(player.hand)
    hit(engine, source); engine.resolve_until_stable()
    assert len(source.triggered_abilities) == 2
    assert len(source.activated_abilities) == 1
    assert len(player.hand) == before + 2


def test_payment_ends_temporary_copy_layers_on_exiled_creature():
    engine, source, player = board(); target = body(engine, 'Original', 2)
    template = body(engine, 'Temporary', 5)
    engine.rules.become_copy_until_end_of_turn(target, template)
    engine.recompute_continuous_effects()
    activate(engine, source, target); engine.resolve_until_stable()
    assert source.name == target.name == 'Original'
    assert not target._duration_copy_layers and target._copy_until_eot_base is None
