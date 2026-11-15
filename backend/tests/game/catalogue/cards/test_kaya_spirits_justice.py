"""Kaya's mixed-origin exile trigger, resolution-time choices and loyalty abilities."""
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, named
from tests.support.star_trek import advance_to


def board():
    engine = game(players=3, library=40); advance_to(engine, 'main1')
    kaya = card(engine, "Kaya, Spirits' Justice")
    token = filler(engine, 'Token', type_line='Artifact — Treasure'); token.is_token = True
    return engine, kaya, token, engine.state.players[0]


def pick_target(engine, token):
    choice = engine.state.pending_choice
    if choice and choice['kind'] == 'trigger_target':
        engine.resolve_pending_choice(str(token.instance_id))


def test_fresh_specs_and_all_four_abilities_bind():
    engine, kaya, token, player = board(); a, b = specs_for(kaya.card), specs_for(kaya.card)
    assert len(a) == 4 and a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(kaya.triggered_abilities) == 1 and len(kaya.activated_abilities) == 3


def test_own_creature_exile_offers_card_and_changes_target_token_until_cleanup():
    engine, kaya, token, player = board(); creature = card(engine, 'Grizzly Bears')
    engine.rules.exile(creature); engine.resolve_until_stable(); pick_target(engine, token)
    assert engine.state.pending_choice is not None
    engine.resolve_pending_choice(str(creature.instance_id)); engine.resolve_until_stable()
    assert token.name == 'Grizzly Bears' and token.is_token and combat.has(token, 'flying')
    engine._step_cleanup()
    assert token.name == 'Token' and not token.is_creature


def test_own_graveyard_creature_card_exile_qualifies():
    engine, kaya, token, player = board(); creature = card(engine, 'Grizzly Bears', zone=Zone.GRAVEYARD)
    engine.rules.exile(creature); engine.resolve_until_stable(); pick_target(engine, token)
    assert engine.state.pending_choice is not None
    engine.resolve_pending_choice(str(creature.instance_id)); engine.resolve_until_stable()
    assert token.name == creature.name


def test_plus_one_creates_white_black_flying_spirit_and_pays_loyalty():
    engine, kaya, token, player = board()
    engine.activate_ability(player, kaya, 1); engine.resolve_until_stable()
    spirit = named(engine, 'Spirit')[0]
    assert spirit.power == spirit.toughness == 1 and combat.has(spirit, 'flying')
    assert spirit.colors == {'W', 'B'} and kaya.counters['loyalty'] == 4


def exile_batch(engine, objects):
    with engine.state.simultaneous():
        for obj in objects:
            engine.rules.exile(obj)


def resolve_copy(engine, token, creature):
    engine.resolve_until_stable(); pick_target(engine, token)
    engine.resolve_pending_choice(str(creature.instance_id)); engine.resolve_until_stable()


def test_mixed_battlefield_and_graveyard_exiles_make_one_trigger_and_one_pool():
    engine, kaya, token, player = board()
    live = card(engine, 'Grizzly Bears'); dead = card(engine, 'Llanowar Elves', zone=Zone.GRAVEYARD)
    exile_batch(engine, [live, dead])
    assert len(engine.rules.pending_triggers) == 1
    engine.resolve_until_stable(); pick_target(engine, token)
    ids = {o.get('instance_id') for o in engine.state.pending_choice['options']}
    assert {live.instance_id, dead.instance_id}.issubset(ids)
    engine.resolve_pending_choice(str(dead.instance_id)); engine.resolve_until_stable()
    assert token.name == 'Llanowar Elves'


def test_separate_exile_events_make_separate_triggers():
    engine, kaya, token, player = board()
    first = card(engine, 'Grizzly Bears'); second = card(engine, 'Llanowar Elves', zone=Zone.GRAVEYARD)
    engine.rules.exile(first); engine.rules.exile(second)
    assert len(engine.rules.pending_triggers) == 2


def test_opponents_creature_and_graveyard_card_do_not_qualify():
    engine, kaya, token, player = board()
    live = card(engine, 'Grizzly Bears', player='p2')
    dead = card(engine, 'Llanowar Elves', player='p2', zone=Zone.GRAVEYARD)
    exile_batch(engine, [live, dead]); engine.resolve_until_stable()
    assert engine.state.pending_choice is None and token.name == 'Token'


def test_own_card_controlled_by_opponent_on_battlefield_does_not_qualify():
    engine, kaya, token, player = board(); creature = card(engine, 'Grizzly Bears')
    creature.controller_id = 'p2'
    engine.rules.exile(creature); engine.resolve_until_stable()
    assert engine.state.pending_choice is None and token.name == 'Token'


def test_opponents_card_controlled_by_you_on_battlefield_qualifies():
    engine, kaya, token, player = board(); creature = card(engine, 'Grizzly Bears', player='p2')
    creature.controller_id = 'p1'
    engine.rules.exile(creature); resolve_copy(engine, token, creature)
    assert token.name == 'Grizzly Bears' and creature.owner_id == 'p2'


def test_exile_from_own_hand_or_library_does_not_qualify():
    engine, kaya, token, player = board()
    hand = card(engine, 'Grizzly Bears', zone=Zone.HAND)
    library = card(engine, 'Llanowar Elves', zone=Zone.LIBRARY)
    exile_batch(engine, [hand, library]); engine.resolve_until_stable()
    assert engine.state.pending_choice is None and token.name == 'Token'


def test_noncreature_graveyard_card_does_not_trigger():
    engine, kaya, token, player = board(); land = card(engine, 'Forest', zone=Zone.GRAVEYARD)
    engine.rules.exile(land); engine.resolve_until_stable()
    assert engine.state.pending_choice is None


def test_exiled_creature_token_triggers_but_cannot_be_chosen_as_a_creature_card():
    engine, kaya, token, player = board()
    creature = filler(engine, 'Exiled token', power=2, toughness=2); creature.is_token = True
    engine.rules.exile(creature)
    assert len(engine.rules.pending_triggers) == 1
    engine.resolve_until_stable(); pick_target(engine, token)
    assert engine.state.pending_choice is None and token.name == 'Token'


def test_optional_card_choice_can_be_declined():
    engine, kaya, token, player = board(); creature = card(engine, 'Grizzly Bears')
    engine.rules.exile(creature); engine.resolve_until_stable(); pick_target(engine, token)
    engine.resolve_pending_choice('decline')
    assert token.name == 'Token'


def test_card_that_left_exile_before_resolution_cannot_be_chosen():
    engine, kaya, token, player = board(); creature = card(engine, 'Grizzly Bears')
    engine.rules.exile(creature); engine.rules.return_to_hand(creature)
    engine.resolve_until_stable(); pick_target(engine, token)
    assert engine.state.pending_choice is None and token.name == 'Token'


def test_new_exile_visit_is_not_in_old_trigger_pool():
    engine, kaya, token, player = board(); creature = card(engine, 'Grizzly Bears')
    engine.rules.exile(creature); engine.rules.return_to_hand(creature); engine.rules.exile(creature)
    engine.resolve_until_stable(); pick_target(engine, token)
    assert engine.state.pending_choice is None and token.name == 'Token'


def test_no_owned_token_means_trigger_cannot_be_placed():
    engine, kaya, token, player = board(); token.controller_id = 'p2'
    creature = card(engine, 'Grizzly Bears'); engine.rules.exile(creature); engine.resolve_until_stable()
    assert not engine.state.stack and engine.state.pending_choice is None


def test_target_token_announced_before_card_choice():
    engine, kaya, token, player = board()
    other = filler(engine, 'Other token', power=1, toughness=1); other.is_token = True
    creature = card(engine, 'Grizzly Bears'); engine.rules.exile(creature); engine.resolve_until_stable()
    assert engine.state.pending_choice['kind'] == 'trigger_target'
    ids = {o.get('instance_id') for o in engine.state.pending_choice['options']}
    assert token.instance_id in ids and other.instance_id in ids and creature.instance_id not in ids
    engine.resolve_pending_choice(str(other.instance_id))
    engine.resolve_pending_choice(str(creature.instance_id)); engine.resolve_until_stable()
    assert other.name == 'Grizzly Bears' and token.name == 'Token'


def test_kaya_departure_does_not_remove_already_triggered_ability():
    engine, kaya, token, player = board(); creature = card(engine, 'Grizzly Bears')
    engine.rules.exile(creature); engine.rules.exile(kaya)
    resolve_copy(engine, token, creature)
    assert token.name == 'Grizzly Bears'


def test_simultaneously_exiled_kaya_still_sees_creature_departure():
    engine, kaya, token, player = board(); creature = card(engine, 'Grizzly Bears')
    exile_batch(engine, [kaya, creature])
    resolve_copy(engine, token, creature)
    assert token.name == 'Grizzly Bears'


def test_undo_preserves_card_choice_and_fixed_target():
    engine, kaya, token, player = board(); creature = card(engine, 'Grizzly Bears')
    engine.rules.exile(creature); engine.resolve_until_stable(); pick_target(engine, token)
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice(str(creature.instance_id)); clone.resolve_until_stable()
    assert clone.state.find_object(token.instance_id).name == 'Grizzly Bears'
    assert token.name == 'Token' and engine.state.pending_choice is not None


def test_minus_two_exiles_required_own_and_one_per_other_player():
    engine, kaya, token, player = board()
    own = card(engine, 'Grizzly Bears'); a = card(engine, 'Grizzly Bears', player='p2')
    b = card(engine, 'Grizzly Bears', player='p3'); extra = card(engine, 'Llanowar Elves', player='p2')
    engine.activate_ability(player, kaya, 2, targets=[own, a, b]); engine.resolve_until_stable()
    assert all(o.zone == Zone.EXILE for o in (own, a, b)) and extra.zone == Zone.BATTLEFIELD
    assert kaya.counters['loyalty'] == 1
    pick_target(engine, token); engine.resolve_pending_choice(str(own.instance_id)); engine.resolve_until_stable()
    assert token.name == 'Grizzly Bears'


def test_minus_two_can_decline_every_other_players_target():
    engine, kaya, token, player = board(); own = card(engine, 'Grizzly Bears')
    other = card(engine, 'Grizzly Bears', player='p2')
    engine.activate_ability(player, kaya, 2, target_groups=[[own], []]); engine.resolve_until_stable()
    assert own.zone == Zone.EXILE and other.zone == Zone.BATTLEFIELD


def finish_surveil(engine):
    while engine.state.pending_choice and engine.state.pending_choice['kind'] == 'surveil':
        engine.resolve_pending_choice('decline')


def test_plus_two_has_no_targets_and_chooses_from_any_graveyard_after_surveil():
    engine, kaya, token, player = board()
    own = card(engine, 'Forest', zone=Zone.GRAVEYARD)
    other = card(engine, 'Island', player='p2', zone=Zone.GRAVEYARD)
    assert not kaya.activated_abilities[0].target_specs
    engine.activate_ability(player, kaya, 0); engine.resolve_until_stable()
    assert kaya.counters['loyalty'] == 5 and engine.state.pending_choice['kind'] == 'surveil'
    finish_surveil(engine)
    choice = engine.state.pending_choice
    assert choice['kind'] == 'choose_objects'
    assert {o.get('instance_id') for o in choice['options']} == {own.instance_id, other.instance_id}
    engine.resolve_pending_choice(str(other.instance_id)); engine.resolve_until_stable()
    assert other.zone == Zone.EXILE and own.zone == Zone.GRAVEYARD


def test_plus_two_can_exile_a_card_just_put_into_graveyard_by_surveil():
    engine, kaya, token, player = board()
    creature = card(engine, 'Grizzly Bears', zone=Zone.LIBRARY)
    land = card(engine, 'Forest', zone=Zone.GRAVEYARD)
    engine.activate_ability(player, kaya, 0); engine.resolve_until_stable()
    engine.resolve_pending_choice(str(creature.instance_id)); finish_surveil(engine)
    assert creature.zone == Zone.GRAVEYARD
    engine.resolve_pending_choice(str(creature.instance_id)); engine.resolve_until_stable()
    pick_target(engine, token); engine.resolve_pending_choice(str(creature.instance_id)); engine.resolve_until_stable()
    assert creature.zone == Zone.EXILE and token.name == 'Grizzly Bears'


def test_loyalty_ability_still_limited_to_one_activation_per_turn():
    engine, kaya, token, player = board()
    engine.activate_ability(player, kaya, 1); engine.resolve_until_stable()
    assert not any(engine.can_activate(player, kaya, ability) for ability in kaya.activated_abilities)


def test_plus_two_with_no_graveyard_cards_can_finish_without_exiling():
    engine, kaya, token, player = board()
    engine.activate_ability(player, kaya, 0); engine.resolve_until_stable(); finish_surveil(engine)
    assert engine.state.pending_choice is None and kaya.counters['loyalty'] == 5


def test_minus_two_requires_an_own_creature_even_if_other_players_have_creatures():
    import pytest
    engine, kaya, token, player = board(); other = card(engine, 'Grizzly Bears', player='p2')
    with pytest.raises(ValueError):
        engine.activate_ability(player, kaya, 2, targets=[other])
    assert kaya.counters['loyalty'] == 3 and other.zone == Zone.BATTLEFIELD


def test_trigger_can_be_countered_before_card_choice():
    engine, kaya, token, player = board(); creature = card(engine, 'Grizzly Bears')
    engine.rules.exile(creature); engine.rules.put_triggers_on_stack()
    if engine.state.pending_choice:
        engine.rules.resolve_choice(str(token.instance_id))
    engine.rules.counter_spell(engine.state.stack[-1]); engine.resolve_until_stable()
    assert engine.state.pending_choice is None and token.name == 'Token'


def test_target_token_leaving_before_trigger_resolution_fizzles():
    engine, kaya, token, player = board(); creature = card(engine, 'Grizzly Bears')
    engine.rules.exile(creature); engine.rules.put_triggers_on_stack()
    if engine.state.pending_choice:
        engine.rules.resolve_choice(str(token.instance_id))
    engine.rules.exile(token); engine.resolve_until_stable()
    assert engine.state.pending_choice is None


def test_counters_remain_when_artifact_token_becomes_creature_copy():
    engine, kaya, token, player = board(); creature = card(engine, 'Grizzly Bears')
    token.add_counters('+1/+1', 2)
    engine.rules.exile(creature); resolve_copy(engine, token, creature)
    assert token.power == token.toughness == 4 and token.plus_one_counters == 2
    engine._step_cleanup()
    assert token.name == 'Token' and token.plus_one_counters == 2


def test_transformed_land_creature_triggers_but_is_not_a_creature_card_in_exile():
    engine, kaya, token, player = board()
    land = card(engine, 'Westvale Abbey // Ormendahl, Profane Prince')
    engine.rules.transform_permanent(land); engine.recompute_continuous_effects()
    assert land.is_creature
    engine.rules.exile(land)
    assert len(engine.rules.pending_triggers) == 1
    engine.resolve_until_stable(); pick_target(engine, token)
    assert engine.state.pending_choice is None and token.name == 'Token'
    assert land.name.split(' // ')[0] == 'Westvale Abbey' and not land.card.is_creature


def test_real_cast_enters_with_printed_loyalty_and_plus_one_works():
    from tests.support.deck_batch import cast
    engine = game(players=3, library=40); advance_to(engine, 'main1')
    kaya = card(engine, "Kaya, Spirits' Justice", zone=Zone.HAND)
    cast(engine, kaya)
    assert kaya.counters['loyalty'] == kaya.card.loyalty == 3
    engine.activate_ability(engine.state.players[0], kaya, 1); engine.resolve_until_stable()
    assert kaya.counters['loyalty'] == 4 and len(named(engine, 'Spirit')) == 1
