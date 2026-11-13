"""PAR-273: temporary control, shared riders and exact delayed references."""
import pytest

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.services.game_session import GameSession
from tests.support.star_trek import game, on_battlefield, advance_to
from tests.test_mec118_opponent_choice import _engine, _put, _db_card


NAMES = ['Grilka, Widowed Warrior', 'Worf, Intelligence Contractor', 'The Wrath of Khan']


def cast(eng, player, name):
    source = _put(eng, _db_card(name), player.id, Zone.HAND)
    player.mana_pool.add_many({color: 10 for color in 'WUBRGC'})
    eng.cast_spell(player, source)
    eng.resolve_until_stable()
    return source


def pick(eng, obj):
    choice = eng.state.pending_choice
    assert choice is not None, 'expected a target announcement'
    option = next(o for o in choice['options'] if o.get('instance_id') == obj.instance_id)
    eng.resolve_pending_choice(str(option['id']))
    eng.resolve_until_stable()


@pytest.mark.parametrize('name', NAMES)
def test_real_ticket_cards_fully_modeled(name):
    result = parse_oracle(_db_card(name))
    assert result.modeled, result.unclaimed


def test_grilka_steals_untaps_and_grants_treasure_trigger_until_cleanup():
    eng, player, opponent = game(via_steps=True)
    victim = on_battlefield(eng, opponent.id, 'Grizzly Bears')
    victim.tapped = True
    source = cast(eng, player, NAMES[0])
    if eng.state.pending_choice:
        pick(eng, victim)
    assert victim.controller_id == player.id and not victim.tapped
    assert combat.has(victim, 'haste') and combat.has(victim, 'trample')
    eng.rules.return_to_hand(source)
    advance_to(eng, 'declare_attackers')
    eng.declare_attackers(player, [{'attacker': victim, 'defender': {'kind': 'player', 'id': opponent.id}}])
    eng.resolve_until_stable()
    advance_to(eng, 'combat_damage')
    eng.resolve_until_stable()
    treasures = [o for o in eng.state.battlefield if o.name == 'Treasure']
    assert len(treasures) == 2 and all(o.tapped and o.controller_id == player.id for o in treasures)
    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert victim.controller_id == opponent.id
    assert not combat.has(victim, 'trample') and not combat.has(victim, 'haste')
    assert not victim.granted_triggered_abilities


def test_grilka_noncombat_damage_does_not_create_treasure():
    eng = _engine(3)
    victim = on_battlefield(eng, 'p2', 'Grizzly Bears')
    cast(eng, eng.state.players[0], NAMES[0])
    if eng.state.pending_choice:
        pick(eng, victim)
    eng.rules.deal_damage(eng.state.players[1], 2, source=victim, combat=False)
    eng.resolve_until_stable()
    assert not any(o.name == 'Treasure' for o in eng.state.battlefield)


def test_worf_selects_one_small_creature_per_opponent_and_keeps_original_types():
    eng = _engine(3)
    first = on_battlefield(eng, 'p2', 'Grizzly Bears')
    second = on_battlefield(eng, 'p3', 'Llanowar Elves')
    large = on_battlefield(eng, 'p2', 'Darksteel Colossus')
    own = on_battlefield(eng, 'p1', 'Grizzly Bears')
    first.tapped = second.tapped = True
    cast(eng, eng.state.players[0], NAMES[1])
    choice = eng.state.pending_choice
    assert large.instance_id not in {o.get('instance_id') for o in choice['options']}
    assert own.instance_id not in {o.get('instance_id') for o in choice['options']}
    pick(eng, first)
    assert first.instance_id not in {o.get('instance_id') for o in eng.state.pending_choice['options']}
    pick(eng, second)
    for obj, old_type in ((first, 'bear'), (second, 'elf')):
        assert obj.controller_id == 'p1' and not obj.tapped
        assert combat.has(obj, 'haste')
        assert continuous.has_subtype(obj, 'warrior') and continuous.has_subtype(obj, old_type)
    assert large.controller_id == 'p2' and own.controller_id == 'p1'
    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert first.controller_id == 'p2' and second.controller_id == 'p3'
    assert not continuous.has_subtype(first, 'warrior') and not combat.has(first, 'haste')


def khan_board(victim_name='Colossal Dreadmaw'):
    eng, player, opponent = game(via_steps=True)
    victim = on_battlefield(eng, opponent.id, victim_name)
    source = cast(eng, player, NAMES[2])
    if eng.state.pending_choice:
        pick(eng, victim)
    return eng, player, opponent, source, victim


def test_khan_delays_control_until_combat_and_clone_retains_exact_target():
    eng, player, opponent, source, victim = khan_board()
    assert victim.damage_marked == 4 and victim.controller_id == opponent.id
    assert len(eng.state.delayed_triggers) == 1
    eng.rules.return_to_hand(source)
    restored = GameEngine(eng.state.clone())
    advance_to(restored, 'begin_combat')
    restored.resolve_until_stable()
    actual = restored.state.find_object(victim.instance_id)
    assert actual.controller_id == player.id and combat.has(actual, 'haste')
    assert not restored.state.delayed_triggers
    restored._step_cleanup()
    assert actual.controller_id == opponent.id


@pytest.mark.parametrize('blink', [False, True])
def test_khan_does_not_control_dead_or_returned_target(blink):
    eng, _, opponent, _, victim = khan_board('Colossal Dreadmaw' if blink else 'Grizzly Bears')
    if blink:
        eng.rules.exile(victim)
        eng.rules._put_searched_card(opponent, victim, "battlefield")
    else:
        assert victim.zone == Zone.GRAVEYARD
    advance_to(eng, 'begin_combat')
    eng.resolve_until_stable()
    assert victim.controller_id == opponent.id
    assert victim.zone == (Zone.BATTLEFIELD if blink else Zone.GRAVEYARD)


@pytest.mark.parametrize('body', [
    'gain control of target creature until end of turn. untap it. until end of turn, it gains mystery, haste, and "whenever ~ attacks, draw a card."',
    'gain control of target creature until end of turn. untap it. until end of turn, it gains vigilance and "whenever ~ attacks, draw a card."',
    'gain control of target creature until end of turn. untap it. until end of turn, it becomes a frobnicator in addition to its other types and gains haste',
    'exile a card from their hand',
    'at the beginning of the next combat this turn, gain control of that creature until end of turn. untap it. it gains haste until end of turn',
])
def test_unsupported_or_unbound_riders_fail_closed(body):
    assert parse_effect_body(body) is None


def test_khan_combat_this_turn_expires_when_cast_after_the_last_combat():
    eng, player, opponent = game(via_steps=True, stop_at='main2')
    victim = on_battlefield(eng, opponent.id, 'Colossal Dreadmaw')
    cast(eng, player, NAMES[2])
    if eng.state.pending_choice:
        pick(eng, victim)
    assert eng.state.delayed_triggers
    advance_to(eng, 'upkeep')
    assert eng.state.active_player.id == opponent.id
    assert not eng.state.delayed_triggers
    advance_to(eng, 'begin_combat')
    eng.resolve_until_stable()
    assert victim.controller_id == opponent.id


def test_worf_can_decline_each_opponent_without_granting_anything():
    eng = _engine(3)
    first = on_battlefield(eng, 'p2', 'Grizzly Bears')
    second = on_battlefield(eng, 'p3', 'Llanowar Elves')
    cast(eng, eng.state.players[0], NAMES[1])
    while eng.state.pending_choice:
        assert eng.state.pending_choice['kind'] == 'trigger_target_multi'
        eng.resolve_pending_choice('stop')
        eng.resolve_until_stable()
    assert first.controller_id == 'p2' and second.controller_id == 'p3'
    assert not combat.has(first, 'haste') and not continuous.has_subtype(first, 'warrior')


@pytest.mark.parametrize('pay', [True, False])
def test_khan_second_chapter_optional_exile_then_draw(pay):
    eng, player, _, source, _ = khan_board()
    card = _put(eng, _db_card('Forest'), player.id, Zone.HAND)
    _put(eng, _db_card('Island'), player.id, Zone.HAND)
    before = len(player.hand)
    eng.rules.advance_sagas(player)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'composite_optional'
    eng.resolve_pending_choice('yes' if pay else 'decline')
    eng.resolve_until_stable()
    if pay:
        assert eng.state.pending_choice is not None
        option = next(o for o in eng.state.pending_choice['options'] if o.get('instance_id') == card.instance_id)
        eng.resolve_pending_choice(str(option['id']))
        eng.resolve_until_stable()
        assert card.zone == Zone.EXILE and len(player.hand) == before
    else:
        assert card.zone == Zone.HAND and len(player.hand) == before
    assert source.lore == 2


def test_khan_third_chapter_sacrifices_nontokens_and_saga_completes():
    eng, player, opponent, source, _ = khan_board('Grizzly Bears')
    permanent = on_battlefield(eng, opponent.id, 'Forest')
    token = on_battlefield(eng, opponent.id, 'Llanowar Elves')
    token.is_token = True
    eng.rules.advance_sagas(player)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None  # no hand card: no optional exile or free draw
    eng.rules.advance_sagas(player)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    if eng.state.pending_choice:
        options = eng.state.pending_choice['options']
        assert token.instance_id not in {o.get('instance_id') for o in options}
        option = next(o for o in options if o.get('instance_id') == permanent.instance_id)
        eng.resolve_pending_choice(str(option['id']))
        eng.resolve_until_stable()
    assert permanent.zone == Zone.GRAVEYARD and token.zone == Zone.BATTLEFIELD
    assert source.zone == Zone.GRAVEYARD


def test_khan_optional_hand_pick_survives_clone_and_rewind_before_drawing():
    eng, player, _, _, _ = khan_board()
    card = _put(eng, _db_card('Forest'), player.id, Zone.HAND)
    _put(eng, _db_card('Island'), player.id, Zone.HAND)
    before = len(player.hand)
    eng.rules.advance_sagas(player)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    eng.resolve_pending_choice('yes')
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'choose_objects'
    restored = GameEngine(eng.state.clone())
    session = GameSession(eng)
    session.apply_action({'type': 'choose', 'option_id': str(card.instance_id)}, actor_id=player.id)
    session.rewind()
    for engine in (session.engine, restored):
        engine.resolve_pending_choice(str(card.instance_id))
        engine.resolve_until_stable()
        assert engine.state.find_object(card.instance_id).zone == Zone.EXILE
        assert len(engine.state.player_by_id(player.id).hand) == before


def test_optional_exile_requires_enough_hand_cards_for_the_entire_antecedent():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading

    eng, player, _ = game(via_steps=True)
    _put(eng, _db_card('Forest'), player.id, Zone.HAND)
    source = on_battlefield(eng, player.id, 'Grizzly Bears')
    specs = parse_effect_body('you may exile 2 cards from your hand. if you do, draw a card',
                              reading=ClauseReading(self_subject=True))
    effects = build_effects(specs, source)
    before = len(player.hand)
    effects[0].apply(eng.rules.context)
    assert eng.state.pending_choice is None
    assert len(player.hand) == before and not player.exile


def test_delayed_capture_uses_its_referent_not_other_shared_targets():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading

    eng = _engine(3)
    source = on_battlefield(eng, 'p1', 'Grizzly Bears')
    chosen = on_battlefield(eng, 'p2', 'Grizzly Bears')
    spare = on_battlefield(eng, 'p3', 'Llanowar Elves')
    specs = parse_effect_body('at the beginning of the next combat this turn, gain control of that creature '
                              'until end of turn. untap it. it gains haste until end of turn',
                              reading=ClauseReading(previous_subject=True))
    eng.rules.context.previous_targets = [chosen]
    build_effects(specs, source)[0].apply(eng.rules.context, [chosen, spare])
    eng._fire_delayed_triggers('begin_combat')
    eng.resolve_until_stable()
    assert chosen.controller_id == 'p1' and spare.controller_id == 'p3'


@pytest.mark.parametrize('count', ['a', '2'])
def test_bare_graveyard_exile_retains_the_existing_graveyard_handler(count):
    specs = parse_effect_body(f'exile {count} card' + ('s' if count == '2' else '') + ' from your graveyard')
    assert specs is not None
    assert all(spec.type != 'exile_hand_card' for spec in specs)


@pytest.mark.parametrize('accept', [True, False])
def test_forsaken_city_shared_hand_exile_untaps_only_after_accepted_pick(accept):
    eng, player, _ = game(via_steps=True)
    source = on_battlefield(eng, player.id, 'Forsaken City')
    source.tapped = True
    first = _put(eng, _db_card('Forest'), player.id, Zone.HAND)
    chosen = _put(eng, _db_card('Island'), player.id, Zone.HAND)
    advance_to(eng, 'upkeep')
    eng.advance_step()
    advance_to(eng, 'upkeep')
    eng.resolve_until_stable()
    assert source.tapped
    eng.resolve_pending_choice('do' if accept else 'decline')
    eng.resolve_until_stable()
    if accept:
        assert source.tapped and eng.state.pending_choice['kind'] == 'choose_objects'
        eng.resolve_pending_choice(str(chosen.instance_id))
        eng.resolve_until_stable()
        assert chosen.zone == Zone.EXILE and not source.tapped
        assert first.zone == Zone.HAND
    else:
        assert source.tapped and chosen.zone == Zone.HAND and first.zone == Zone.HAND
