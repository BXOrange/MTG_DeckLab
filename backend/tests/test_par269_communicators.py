"""PAR-269: self-copying equipment and host-relative Communicator counts."""
import pytest

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.count_phrase import parse_count_phrase
from mtg_analyzer.parser.oracle.catalogue.characteristic_phrase import parse_qualifier
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import game, on_battlefield, cast, advance_to


@pytest.mark.parametrize('name', ['Combadge', 'Starfleet Communicator'])
def test_real_cards_fully_modeled(name):
    card = get_cached_card(name)
    assert card is not None
    parsed = parse_oracle(card)
    assert parsed.modeled and len(parsed.specs) == 3, parsed.unclaimed


@pytest.mark.parametrize('name', ['Combadge', 'Starfleet Communicator'])
def test_cast_creates_one_spell_copy_then_two_unattached_permanents(name):
    eng, player, _ = game(name)
    source = player.hand[0]
    player.mana_pool.add('C', 10)
    eng.cast_spell(player, source)
    eng.rules.put_triggers_on_stack()
    assert len(eng.state.stack) == 2 and not eng.state.battlefield
    eng.rules.resolve_top_of_stack()
    assert len(eng.state.stack) == 2  # copy above original, no recursive cast trigger
    copy = eng.state.stack[-1].obj
    assert copy.is_copy and copy.is_token and copy.name == name
    restored = GameEngine(eng.state.clone())
    restored.resolve_until_stable()
    objects = [o for o in restored.state.battlefield if o.name == name]
    assert len(objects) == 2 and sum(o.is_token for o in objects) == 1
    assert all(o.attached_to is None for o in objects)
    assert not any(e.type == EventType.CREATE_TOKENS for e in restored.state.event_log)


def equipment(eng, host, name='Combadge', pid='p1'):
    obj = on_battlefield(eng, pid, name)
    assert eng.rules.attach_to_target(obj, host, check_control=False)
    eng.recompute_continuous_effects()
    return obj


def start_attack(eng, player, host):
    advance_to(eng, 'declare_attackers')
    eng.declare_attackers(player, [{'attacker': host, 'defender': {'kind': 'player', 'id': 'p2'}}])
    eng.rules.put_triggers_on_stack()


def hand(eng, name, pid='p1'):
    card = get_cached_card(name)
    assert card is not None
    obj = GameObject(card, pid, Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.player_by_id(pid).add_to_zone(obj, Zone.HAND)
    return obj


def test_equip_original_and_copy_to_different_creatures_unlocks_combadge():
    eng, player, _ = game('Combadge', via_steps=True)
    cast(eng, player, player.hand[0])
    badges = [o for o in eng.state.battlefield if o.name == 'Combadge']
    host = on_battlefield(eng, 'p1', 'Grizzly Bears')
    ally = on_battlefield(eng, 'p1', 'Llanowar Elves')
    for badge, creature in zip(badges, [host, ally]):
        player.mana_pool.add('C', 2)
        eng.activate_ability(player, badge, targets=[creature])
        eng.resolve_until_stable()
    host.summoning_sick = False
    start_attack(eng, player, host)
    assert len(eng.state.stack) == 1
    eng.resolve_until_stable()
    blocker = on_battlefield(eng, 'p2', 'Grizzly Bears')
    assert host.temp_unblockable
    assert not eng.can_block(eng.state.player_by_id("p2"), blocker, host)


def test_combadge_without_other_communicator_bearer_never_triggers():
    eng, player, _ = game(via_steps=True)
    host = on_battlefield(eng, 'p1', 'Grizzly Bears')
    equipment(eng, host)
    equipment(eng, host)  # two attachments on the host still mean no OTHER bearer
    on_battlefield(eng, 'p1', 'Llanowar Elves')
    start_attack(eng, player, host)
    assert not eng.state.stack


def test_combadge_condition_is_event_time_only_and_trigger_survives_detachment():
    eng, player, _ = game(via_steps=True)
    host = on_battlefield(eng, 'p1', 'Grizzly Bears')
    ally = on_battlefield(eng, 'p1', 'Llanowar Elves')
    badge = equipment(eng, host)
    other = equipment(eng, ally)
    start_attack(eng, player, host)
    assert len(eng.state.stack) == 1
    eng.rules.exile(other)
    eng.rules.exile(badge)
    eng.resolve_until_stable()
    blocker = on_battlefield(eng, 'p2', 'Grizzly Bears')
    assert host.temp_unblockable
    assert not eng.can_block(eng.state.player_by_id("p2"), blocker, host)


def test_count_is_distinct_other_creatures_not_attachments_or_attachment_controllers():
    eng, player, _ = game()
    host = on_battlefield(eng, 'p1', 'Grizzly Bears')
    ally = on_battlefield(eng, 'p1', 'Llanowar Elves')
    foreign = on_battlefield(eng, 'p2', 'Grizzly Bears')
    equipment(eng, host)
    equipment(eng, ally)
    equipment(eng, ally, 'Starfleet Communicator', pid='p2')
    equipment(eng, foreign)
    on_battlefield(eng, 'p1', 'Combadge')  # unattached
    selector = parse_count_phrase('other creatures you control with a communicator attached to them')
    assert selector is not None
    assert continuous.count_selector(eng.state, player.id, selector, source=host) == 1


def test_generic_attachment_qualifier_composes_type_and_color():
    assert parse_qualifier('a red aura attached to it') == {'has_attachment': {'color': 'R', 'subtype': 'aura'}}
    assert parse_qualifier('a frobnicator attached to them') is None
    assert parse_count_phrase('creatures you control with a communicator nearby') is None


def starfleet_board(others):
    eng, player, _ = game(via_steps=True)
    host = on_battlefield(eng, 'p1', 'Grizzly Bears')
    equipment(eng, host, 'Starfleet Communicator')
    for _ in range(others):
        ally = on_battlefield(eng, 'p1', 'Llanowar Elves')
        equipment(eng, ally)
    return eng, player, host


def test_zero_other_creatures_draws_and_places_zero_even_with_land_in_hand():
    eng, player, host = starfleet_board(0)
    land = hand(eng, 'Forest')
    before = len(player.hand)
    start_attack(eng, player, host)
    eng.resolve_until_stable()
    assert len(player.hand) == before and land in player.hand
    assert eng.state.pending_choice is None


def test_starfleet_draws_then_places_up_to_x_tapped_lands_and_can_stop_early():
    eng, player, host = starfleet_board(2)
    first = hand(eng, 'Forest')
    second = hand(eng, 'Island')
    before = len(player.hand)
    start_attack(eng, player, host)
    eng.resolve_until_stable()
    assert len(player.hand) == before + 2
    choice = eng.state.pending_choice
    assert choice['kind'] == 'search' and choice['player_id'] == 'p1'
    eng.resolve_pending_choice(str(first.instance_id))
    eng.resolve_until_stable()
    eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    assert first in eng.state.battlefield and first.tapped
    assert second in player.hand


def test_starfleet_can_place_x_lands_and_paused_pick_survives_clone():
    eng, player, host = starfleet_board(2)
    first = hand(eng, 'Forest')
    second = hand(eng, 'Island')
    third = hand(eng, 'Mountain')
    start_attack(eng, player, host)
    eng.resolve_until_stable()
    eng.resolve_pending_choice(str(first.instance_id))
    eng.resolve_until_stable()
    restored = GameEngine(eng.state.clone())
    restored.resolve_pending_choice(str(second.instance_id))
    restored.resolve_until_stable()
    assert restored.state.find_object(first.instance_id).tapped
    assert restored.state.find_object(second.instance_id).zone == Zone.BATTLEFIELD
    assert restored.state.find_object(third.instance_id).zone == Zone.HAND
    assert restored.state.pending_choice is None


def test_unrecognized_while_condition_or_placement_remains_unclaimed():
    from mtg_analyzer.parser.oracle.segmenter import segment_line
    from mtg_analyzer.parser.oracle.spec import ParserProvenance

    assert not segment_line('whenever ~ attacks while you frobnicate, draw a card.',
                            allow_spell_effect=False, provenance=ParserProvenance()).claimed
    assert parse_effect_body('put up to x nonsense cards from your hand onto the battlefield') is None


def test_starfleet_binds_x_once_across_draw_replacement_pause_and_clone():
    eng, player, host = starfleet_board(2)
    first = hand(eng, 'Forest')
    second = hand(eng, 'Island')
    on_battlefield(eng, 'p1', 'Abundance')
    start_attack(eng, player, host)
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'optional_draw_dig'
    restored = GameEngine(eng.state.clone())
    for obj in list(restored.state.battlefield):
        if obj.name == 'Combadge':
            restored.rules.exile(obj)
    restored.resolve_pending_choice('decline')
    restored.resolve_until_stable()
    restored.resolve_pending_choice('decline')
    restored.resolve_until_stable()
    assert restored.state.pending_choice['kind'] == 'search'
    restored.resolve_pending_choice(str(first.instance_id))
    restored.resolve_until_stable()
    restored.resolve_pending_choice(str(second.instance_id))
    restored.resolve_until_stable()
    assert restored.state.find_object(first.instance_id).zone == Zone.BATTLEFIELD
    assert restored.state.find_object(second.instance_id).zone == Zone.BATTLEFIELD


def test_attachment_filter_validation_rejects_nonfilters_and_deep_recursion():
    from mtg_analyzer.parser.oracle.spec import AbilitySpec, SpecValidationError

    with pytest.raises(SpecValidationError):
        AbilitySpec._validate_filter({'has_attachment': 'communicator'})
    value = {}
    for _ in range(AbilitySpec.MAX_SPEC_DEPTH + 2):
        value = {'has_attachment': value}
    with pytest.raises(SpecValidationError):
        AbilitySpec._validate_filter(value)


def test_combadge_equipment_control_does_not_change_who_you_means():
    eng, player, _ = game(via_steps=True)
    host = on_battlefield(eng, 'p1', 'Grizzly Bears')
    ally = on_battlefield(eng, 'p1', 'Llanowar Elves')
    equipment(eng, host, pid='p2')
    equipment(eng, ally, pid='p2')
    start_attack(eng, player, host)
    assert len(eng.state.stack) == 1
    eng.resolve_until_stable()
    assert host.temp_unblockable


def test_arex_draw_then_fixed_land_count_uses_shared_placement():
    eng, player, _ = game('Lt. Arex, Ever-Adapting', via_steps=True)
    on_battlefield(eng, 'p1', 'Forest')
    lands = [hand(eng, name) for name in ('Forest', 'Island', 'Mountain')]
    source = next(o for o in player.hand if o.name == 'Lt. Arex, Ever-Adapting')
    before = len(player.hand)
    cast(eng, player, source)
    assert len(player.hand) == before - 1 + 3
    for land in lands:
        eng.resolve_pending_choice(str(land.instance_id))
        eng.resolve_until_stable()
    assert all(land.zone == Zone.BATTLEFIELD and land.tapped for land in lands)
    assert eng.state.pending_choice is None
