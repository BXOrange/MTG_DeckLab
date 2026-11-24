"""Hugh's separate additional payments create counterable spell-copy triggers."""
import pytest

from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, named
from tests.support.star_trek import advance_to


def board(spell="Sol Ring"):
    engine = game(players=3, library=30)
    advance_to(engine, "main1")
    hugh = card(engine, "Hugh, First of Many")
    host = card(engine, spell, zone=Zone.HAND)
    return engine, engine.state.players[0], hugh, host


def pay(player, blue=2, generic=5):
    player.mana_pool.add_many({"U": blue, "C": generic})


def test_fresh_specs_and_binding():
    engine, player, hugh, host = board()
    a, b = specs_for(hugh.card), specs_for(hugh.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert hugh.static_effects[0].layer == "grant_replicate"


def test_twice_paid_cost_creates_two_token_copies_without_casting_them():
    engine, player, hugh, host = board()
    pay(player)
    assert engine.effective_cast_cost(player, host, replicate=[2]).resolved_value == 7
    engine.cast_spell(player, host, replicate=[2])
    assert player.mana_pool.total() == 0
    assert host.mana_spent_to_cast == 7
    engine.resolve_until_stable()
    rings = named(engine, "Sol Ring")
    assert len(rings) == 3 and sum(o.is_token for o in rings) == 2
    assert sum(e.type == EventType.SPELL_CAST for e in engine.state.events_this_turn()) == 1


def test_declining_payment_creates_no_trigger_or_copy():
    engine, player, hugh, host = board()
    pay(player, blue=0, generic=1)
    engine.cast_spell(player, host, replicate=[0])
    engine.resolve_until_stable()
    assert named(engine, "Sol Ring") == [host]


@pytest.mark.parametrize("counts", [[-1], [1.5], [True], ["1"], [1, 0], []])
def test_invalid_announcements_fail_without_paying_or_moving(counts):
    engine, player, hugh, host = board()
    pay(player)
    assert not engine.can_cast(player, host, replicate=counts)
    with pytest.raises(ValueError):
        engine.cast_spell(player, host, replicate=counts)
    assert host.zone == Zone.HAND and player.mana_pool.total() == 7
    assert not hasattr(host, "_replicate_cost")


def test_unaffordable_payment_is_illegal_and_preview_leaves_no_announcement():
    engine, player, hugh, host = board()
    pay(player, blue=1, generic=2)
    assert not engine.can_cast(player, host, replicate=[1])
    assert not hasattr(host, "_replicate_cost")
    assert engine.effective_cast_cost(player, host).resolved_value == 1
    with pytest.raises(ValueError):
        engine.cast_spell(player, host, replicate=[1])
    assert host.zone == Zone.HAND and player.mana_pool.total() == 3


def test_nonartifact_does_not_get_replicate():
    engine, player, hugh, host = board("Llanowar Elves")
    pay(player)
    assert not engine.can_cast(player, host, replicate=[1])


def test_opponents_artifact_does_not_get_replicate():
    engine, player, hugh, host = board()
    other = engine.state.players[1]
    engine.state.active_player_index = 1
    artifact = card(engine, "Sol Ring", player=other.id, zone=Zone.HAND)
    pay(other)
    assert not engine.can_cast(other, artifact, replicate=[1])


def test_source_removed_before_cast_does_not_grant_payment():
    engine, player, hugh, host = board()
    engine.rules.exile(hugh)
    pay(player)
    assert not engine.can_cast(player, host, replicate=[1])


def test_paid_trigger_survives_hugh_leaving_and_original_being_countered():
    engine, player, hugh, host = board()
    pay(player)
    engine.cast_spell(player, host, replicate=[2])
    engine.rules.put_triggers_on_stack()
    engine.rules.exile(hugh)
    engine.rules.counter_spell(host)
    engine.resolve_until_stable()
    rings = named(engine, "Sol Ring")
    assert len(rings) == 2 and all(o.is_token for o in rings)
    assert host.zone == Zone.GRAVEYARD


def test_two_hughs_have_separate_payment_counts_and_triggers():
    engine, player, hugh, host = board()
    # Separate controllers would not grant this caster a second instance.
    # Disabling the legend rule lets two actual copies grant independent instances.
    from mtg_analyzer.game.effects.core import StaticAbility
    hugh.static_effects.append(StaticAbility("ignore_legend_rule", affects="you", params={}, source=hugh))
    card(engine, "Hugh, First of Many")
    pay(player, blue=3, generic=7)
    engine.cast_spell(player, host, replicate=[1, 2])
    engine.rules.put_triggers_on_stack()
    triggers = [item for item in engine.state.stack if item.obj is None]
    assert len(triggers) == 2
    engine.resolve_until_stable()
    assert len(named(engine, "Sol Ring")) == 4


def test_undo_clone_retains_paid_trigger_and_recipe():
    engine, player, hugh, host = board()
    pay(player)
    engine.cast_spell(player, host, replicate=[2])
    engine.rules.put_triggers_on_stack()
    clone = GameEngine(engine.state.clone())
    clone.rules.counter_spell(clone.state.find_object(host.instance_id))
    clone.resolve_until_stable()
    assert len(named(clone, "Sol Ring")) == 2
    assert not named(engine, "Sol Ring")


def test_legal_actions_offer_one_payment_field_per_instance():
    engine, player, hugh, host = board()
    pay(player)
    action = next(a for a in engine.legal_actions(player)
                  if a['type'] == 'cast_spell' and a.get('instance_id') == host.instance_id)
    assert action['replicate_costs'] == ['{2}{U}']


def test_free_cast_still_pays_replicate_and_reports_actual_mana_spent():
    engine, player, hugh, host = board()
    engine.state.free_cast_instance_ids.add(host.instance_id)
    pay(player, blue=1, generic=2)
    engine.cast_spell(player, host, free=True, replicate=[1])
    assert host.mana_spent_to_cast == 3 and player.mana_pool.total() == 0
    engine.resolve_until_stable()
    assert len(named(engine, 'Sol Ring')) == 2


def test_free_cast_cannot_ignore_unaffordable_additional_payment():
    engine, player, hugh, host = board()
    engine.state.free_cast_instance_ids.add(host.instance_id)
    assert not engine.can_cast(player, host, free=True, replicate=[1])
    with pytest.raises(ValueError):
        engine.cast_spell(player, host, free=True, replicate=[1])
    assert host.zone == Zone.HAND


def test_reductions_apply_to_total_including_replicate():
    engine, player, hugh, host = board()
    from mtg_analyzer.game.effects.core import StaticAbility
    hugh.static_effects.append(StaticAbility('cost', affects='spells_you_cast',
                                           params={'generic': 5}, source=hugh))
    pay(player, blue=2, generic=0)
    cost = engine.effective_cast_cost(player, host, replicate=[2])
    assert cost.resolved_value == 2
    engine.cast_spell(player, host, replicate=[2])
    engine.resolve_until_stable()
    assert len(named(engine, 'Sol Ring')) == 3


def test_countering_replicate_trigger_prevents_copies_without_countering_original():
    engine, player, hugh, host = board()
    pay(player)
    engine.cast_spell(player, host, replicate=[2])
    engine.rules.put_triggers_on_stack()
    trigger = next(item for item in engine.state.stack if item.obj is None)
    engine.rules.counter_spell(trigger)
    engine.resolve_until_stable()
    assert named(engine, 'Sol Ring') == [host]


def test_session_round_trips_replicate_payment():
    from mtg_analyzer.services.game_session import GameSession
    engine, player, hugh, host = board()
    pay(player)
    session = GameSession(engine, mode='replay', starting_hand=0)
    session.apply_action({'type': 'cast_spell', 'instance_id': host.instance_id, 'replicate': [2]})
    engine.resolve_until_stable()
    assert len(named(engine, 'Sol Ring')) == 3


def test_additional_payment_also_applies_with_an_alternative_cast_cost():
    from mtg_analyzer.game.costs import parse_activation_cost
    engine, player, hugh, host = board()
    host.alt_cast_cost = parse_activation_cost('{2}')
    host.alt_cast_condition = None
    pay(player, blue=1, generic=4)
    engine.cast_spell(player, host, alt_cost=True, replicate=[1])
    assert player.mana_pool.total() == 0 and host.mana_spent_to_cast == 5
    engine.resolve_until_stable()
    assert len(named(engine, 'Sol Ring')) == 2


def test_free_cast_during_resolution_keeps_replicate_payment():
    engine, player, hugh, host = board()
    engine.rules._request_resolution_play(player, [host], zone='hand', free=True, only_spells=True)
    pay(player, blue=1, generic=2)
    engine.play_resolution_card(player, host, replicate=[1])
    engine.resolve_until_stable()
    assert player.mana_pool.total() == 0 and len(named(engine, 'Sol Ring')) == 2


def test_artifact_spell_copies_keep_x_and_enter_with_its_counters():
    engine, player, hugh, host = board('Walking Ballista')
    pay(player, blue=1, generic=6)
    engine.cast_spell(player, host, x=2, replicate=[1])
    engine.resolve_until_stable()
    ballistas = named(engine, 'Walking Ballista')
    assert len(ballistas) == 2
    assert all(o.counters.get('+1/+1') == 2 for o in ballistas)


def test_each_copy_can_choose_new_targets_without_changing_original():
    engine, player, hugh, host = board()
    spell = filler(engine, 'Targeted artifact spell', type_line='Artifact Instant',
                   oracle_text='Target player draws a card.', zone=Zone.HAND, mv=1)
    pay(player)
    before = [len(p.hand) for p in engine.state.players]
    engine.cast_spell(player, spell, targets=[engine.state.players[1]], replicate=[2])
    engine.resolve_until_stable()
    for target in (engine.state.players[2], player):
        choice = engine.state.pending_choice
        assert choice['kind'] == 'copy_targets'
        option = next(o for o in choice['options'] if o.get('player_id') == target.id)
        engine.resolve_pending_choice(str(option['id']))
    engine.resolve_until_stable()
    assert [len(p.hand) for p in engine.state.players] == [before[0], before[1] + 1, before[2] + 1]


def test_removed_static_ability_does_not_grant_replicate():
    engine, player, hugh, host = board()
    hugh._loses_all_abilities = True
    pay(player)
    assert not engine.can_cast(player, host, replicate=[1])


def test_grant_checks_announced_modal_face_and_copies_the_cast_artifact_face():
    engine, player, hugh, host = board('Halvar, God of Battle // Sword of the Realms')
    player.mana_pool.add_many({'W': 2, 'U': 1, 'C': 5})
    assert not engine.can_cast(player, host, replicate=[1])
    assert engine.can_cast(player, host, face='back', replicate=[1])
    engine.cast_spell(player, host, face='back', replicate=[1])
    engine.resolve_until_stable()
    assert len(named(engine, 'Sword of the Realms')) == 2


def test_artifact_cast_can_auto_tap_for_replicate_in_addition_to_printed_cost():
    engine, player, hugh, host = board()
    for _ in range(4):
        card(engine, 'Island')
    engine.cast_spell(player, host, replicate=[1])
    engine.resolve_until_stable()
    assert len(named(engine, 'Sol Ring')) == 2
    assert all(o.tapped for o in named(engine, 'Island'))


def test_later_cast_does_not_inherit_old_replicate_payments():
    engine, player, hugh, host = board()
    pay(player)
    engine.cast_spell(player, host, replicate=[2])
    engine.resolve_until_stable()
    engine.rules.put_into_graveyard(host)
    engine.rules.return_from_graveyard(host, 'hand')
    pay(player, blue=0, generic=1)
    engine.cast_spell(player, host)
    engine.resolve_until_stable()
    assert len(named(engine, 'Sol Ring')) == 3
