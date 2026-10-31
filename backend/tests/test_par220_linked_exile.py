"""PAR-220: linked references and exile play permissions, parsed and executed."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.continuous import count_selector
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.linked_exile import linked_cards
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.casting_window import parse_linked_play
from mtg_analyzer.parser.oracle.catalogue.count_phrase import parse_count_phrase
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.game import creature
from tests.test_par210_player_references import game, board
from tests.test_par210_object_phrases import cast
from test_par167_casting_windows import _instant, _in_graveyard
from test_par167_permission_visits import _move


def exile(eng, source, card=None, owner='p1'):
    obj = _in_graveyard(eng, card or _instant(), owner)
    eng.rules.exile(obj)
    eng.state.track_exiled_with(source, obj)
    return obj


def apply(eng, source, text):
    specs = parse_effect_body(text)
    assert specs is not None
    for effect in build_effects(specs, source):
        effect.apply(eng.rules.context)


@pytest.mark.parametrize('restore', [False, True])
def test_linked_count_and_reference_do_not_reacquire_a_new_exile_visit(restore):
    eng = game()
    source = board(eng, creature('Source'))
    card = exile(eng, source)
    selector = parse_count_phrase('cards exiled with it')
    assert count_selector(eng.state, 'p1', selector, source) == 1
    _move(eng, card, Zone.HAND)
    _move(eng, card, Zone.EXILE)
    if restore:
        eng = GameEngine(eng.state.clone())
        source = eng.state.find_object(source.instance_id)
    assert count_selector(eng.state, 'p1', selector, source) == 0
    assert not linked_cards(eng.state, source)


def test_count_filters_and_different_values_use_only_linked_cards():
    eng = game()
    source = board(eng, creature('Source'))
    exile(eng, source, _instant('A', mv=1))
    exile(eng, source, _instant('B', mv=1))
    exile(eng, source, creature('Bear'))
    exile(eng, board(eng, creature('Other source')), _instant('Unrelated', mv=9))
    assert count_selector(eng.state, 'p1', parse_count_phrase('instant cards exiled with ~'), source) == 2
    assert count_selector(eng.state, 'p1', parse_count_phrase('cards exiled with ~ with different mana values'), source) == 2


def test_linked_source_visit_is_not_reused_after_blink():
    eng = game()
    source = board(eng, creature('Source'))
    card = exile(eng, source)
    old_visit = source.zone_incarnation
    eng.rules.exile(source)
    eng.rules.return_from_graveyard(source, 'battlefield')
    assert linked_cards(eng.state, source) == []
    assert linked_cards(eng.state, source, old_visit) == [card]


@pytest.mark.parametrize('free', [False, True])
def test_linked_resolution_offer_charges_only_the_printed_cost_unless_free(free):
    eng = game()
    source = board(eng, creature('Source'))
    card = exile(eng, source, _instant(), owner='p2')
    unrelated = exile(eng, board(eng, creature('Other source')), _instant('Other'))
    apply(eng, source, 'you may cast a spell from among cards exiled with ~'
          + (' without paying its mana cost' if free else '') + '.')
    player = eng.state.player_by_id('p1')
    assert eng.state.pending_choice['kind'] == 'play_during_resolution'
    assert unrelated.instance_id not in [a.get('instance_id') for a in eng.resolution_play_actions(player)]
    if not free:
        with pytest.raises(ValueError):
            eng.play_resolution_card(player, card)
        player.mana_pool.add('C', 1)
    eng.play_resolution_card(player, card)
    eng.resolve_until_stable()
    assert card.zone == Zone.GRAVEYARD and player.mana_pool.total() == 0


def test_declining_resolution_does_not_grant_a_turn_long_permission():
    eng = game()
    source = board(eng, creature('Source'))
    card = exile(eng, source)
    apply(eng, source, 'you may cast a spell from among cards exiled with ~ without paying its mana cost.')
    eng.resolve_pending_choice('decline')
    assert not eng.can_cast(eng.state.player_by_id('p1'), card)


@pytest.mark.parametrize('restore', [False, True])
def test_standing_permission_is_live_and_controller_scoped(restore):
    eng = game()
    source = board(eng, creature('Grantor', oracle_text=(
        '{T}: Exile target card from a graveyard.\nYou may cast spells from among cards exiled with Grantor.')))
    card = exile(eng, source, owner='p2')
    if restore:
        eng = GameEngine(eng.state.clone())
        source, card = eng.state.find_object(source.instance_id), eng.state.find_object(card.instance_id)
    player = eng.state.player_by_id('p1')
    player.mana_pool.add('C', 1)
    assert eng.can_cast(player, card)
    assert not eng.can_cast(eng.state.player_by_id('p2'), card)
    assert any(a.get('instance_id') == card.instance_id for a in eng.legal_actions(player))
    eng.rules.exile(source)
    assert not eng.can_cast(player, card)


def test_linked_window_outlives_source_but_expires_at_cleanup():
    eng = game()
    source = board(eng, creature('Source'))
    card = exile(eng, source)
    apply(eng, source, 'until end of turn, you may cast cards exiled with ~ without paying their mana costs.')
    eng.rules.exile(source)
    player = eng.state.player_by_id('p1')
    assert eng.can_cast(player, card)
    eng._step_cleanup()
    assert not eng.can_cast(player, card)


@pytest.mark.parametrize('body', [
    'Exile target card from a graveyard. You may cast that card this turn without paying its mana cost.',
    'Exile target card from a graveyard. You gain 1 life. You may cast that card this turn without paying its mana cost.',
])
def test_cast_followup_uses_a_proven_exile_antecedent(body):
    eng = game()
    card = _in_graveyard(eng, _instant())
    cast(eng, body, [card])
    player = eng.state.player_by_id('p1')
    eng.cast_spell(player, card)
    eng.resolve_until_stable()
    assert card.zone == Zone.GRAVEYARD


@pytest.mark.parametrize('text', [
    'You may cast that card this turn.',
    'Draw a card. You may cast it without paying its mana cost.',
    'Create a Treasure token. You may cast it without paying its mana cost.',
    'You may cast a spell from among cards exiled with ~ with total mana value X or less without paying its mana cost.',
    'You may cast a spell from among cards exiled with ~ twice this turn.',
    'Exile the top two cards of your library. You may cast that card without paying its mana cost.',
])
def test_unbound_or_unrepresented_references_fail_closed(text):
    assert parse_effect_body(text.lower()) is None


def test_hearse_real_text_binds_count_to_successful_exiles():
    text = ('{T}: Exile up to two target cards from a single graveyard.\n'
            "Unlicensed Hearse's power and toughness are each equal to the number of cards exiled with it.\nCrew 2")
    card = Card(id='hearse', name='Unlicensed Hearse', type_line='Artifact — Vehicle',
                vehicle_power=0, vehicle_toughness=0, keywords=['Crew'], oracle_text=text)
    assert parse_oracle(card).modeled
    eng = game()
    source = board(eng, card)
    victim = _in_graveyard(eng, _instant())
    eng.activate_ability(eng.state.player_by_id('p1'), source, 1, targets=[victim])
    eng.resolve_until_stable()
    pilot = board(eng, creature('Pilot', power=2, toughness=2))
    eng.activate_ability(eng.state.player_by_id('p1'), source, 0, tap_choices=[pilot.instance_id])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (source.power, source.toughness) == (1, 1)
    _move(eng, victim, Zone.HAND)
    eng.recompute_continuous_effects()
    assert (source.power, source.toughness) == (0, 0)


def test_free_standing_linked_cast_uses_free_offer_and_refuses_unrelated_card():
    eng = game()
    source = board(eng, creature('Free grant', oracle_text=(
        '{T}: Exile target card from a graveyard.\n'
        'You may cast spells from among cards exiled with Free grant without paying their mana costs.')))
    card = exile(eng, source, _instant(cost='{5}', mv=5), owner='p2')
    player = eng.state.player_by_id('p1')
    actions = [a for a in eng.legal_actions(player) if a.get('instance_id') == card.instance_id]
    assert actions and any(a.get('free') for a in actions)
    eng.cast_spell(player, card, free=True)
    eng.resolve_until_stable()
    assert card.zone == Zone.GRAVEYARD and player.mana_pool.total() == 0


def test_linked_permission_offers_opponents_land_and_obeys_land_limit():
    eng = game()
    source = board(eng, creature('Land grant', oracle_text=(
        '{T}: Exile target card from a graveyard.\n'
        'You may play lands and cast spells from among cards exiled with Land grant.')))
    card = exile(eng, source, Card(id='island', name='Island', type_line='Basic Land — Island', is_land=True), owner='p2')
    player = eng.state.player_by_id('p1')
    assert eng.can_play_land(player, card)
    assert any(a.get('type') == 'play_land' and a.get('instance_id') == card.instance_id
               for a in eng.legal_actions(player))
    eng.play_land(player, card)
    assert card.zone == Zone.BATTLEFIELD and card.controller_id == player.id
    other = exile(eng, source, Card(id='forest', name='Forest', type_line='Basic Land — Forest', is_land=True))
    assert not eng.can_play_land(player, other)


def test_resolution_offer_survives_sacrificing_the_source_as_cost():
    eng = game()
    source = board(eng, creature('Sacrifice source', oracle_text=(
        '{T}: Exile target card from a graveyard.\n'
        'Sacrifice Sacrifice source: You may cast a spell from among cards exiled with Sacrifice source '
        'without paying its mana cost.')))
    card = exile(eng, source)
    player = eng.state.player_by_id('p1')
    eng.activate_ability(player, source, 1)
    eng.resolve_until_stable()
    assert source.zone == Zone.GRAVEYARD
    eng.play_resolution_card(player, card)
    eng.resolve_until_stable()
    assert card.zone == Zone.GRAVEYARD


def test_migrated_imprint_reader_does_not_copy_a_reexiled_card():
    eng = game()
    source = board(eng, creature('Imprinter'))
    card = _in_graveyard(eng, _instant())
    from mtg_analyzer.game.effects.exile_control import ExileEffect, CopyImprintedCardEffect
    ExileEffect(source=source, remember=True, target_kind='any_graveyard_card').apply(eng.rules.context, [card])
    _move(eng, card, Zone.HAND)
    _move(eng, card, Zone.EXILE)
    CopyImprintedCardEffect(source=source).apply(eng.rules.context)
    assert eng.state.pending_choice is None
    assert len(eng.state.player_by_id('p1').exile) == 1


def test_nightveil_specter_links_the_damaged_players_exiled_card_and_plays_it():
    eng = game()
    source = board(eng, creature('Nightveil Specter', oracle_text=(
        "Flying\nWhenever Nightveil Specter deals combat damage to a player, that player exiles the top card of their library.\n"
        'You may play lands and cast spells from among cards exiled with Nightveil Specter.')))
    player, other = eng.state.player_by_id('p1'), eng.state.player_by_id('p2')
    card = GameObject(_instant(), owner_id='p2', zone=Zone.LIBRARY)
    other.library.append(card)
    eng.rules.deal_damage(other, 1, source=source, combat=True)
    eng.resolve_until_stable()
    assert card.zone == Zone.EXILE and linked_cards(eng.state, source) == [card]
    player.mana_pool.add('C', 1)
    eng.cast_spell(player, card)
    eng.resolve_until_stable()
    assert card.zone == Zone.GRAVEYARD and player.mana_pool.total() == 0


def test_relative_library_exile_requires_a_player_antecedent():
    for text in ['That player exiles the top card of their library.',
                 'Whenever ~ deals damage to a creature, that player exiles the top card of their library.']:
        assert not parse_oracle(creature('Unbound', oracle_text=text)).modeled


def test_fallen_shinobi_free_play_window_includes_lands_and_expires():
    eng = game()
    source = board(eng, creature('Fallen Shinobi', oracle_text=(
        'Whenever Fallen Shinobi deals combat damage to a player, that player exiles the top two cards of their library. '
        'Until end of turn, you may play those cards without paying their mana costs.')))
    player, other = eng.state.player_by_id('p1'), eng.state.player_by_id('p2')
    spell = GameObject(_instant(cost='{5}', mv=5), owner_id='p2', zone=Zone.LIBRARY)
    land = GameObject(Card(id='Land', name='Land', type_line='Land', is_land=True), owner_id='p2', zone=Zone.LIBRARY)
    other.library.extend([spell, land])
    eng.rules.deal_damage(other, 1, source=source, combat=True)
    eng.resolve_until_stable()
    assert eng.can_cast(player, spell) and eng.can_play_land(player, land)
    eng.cast_spell(player, spell)
    eng.resolve_until_stable()
    assert player.mana_pool.total() == 0 and spell.zone == Zone.GRAVEYARD
    eng._step_cleanup()
    assert not eng.can_play_land(player, land)


@pytest.mark.parametrize('destination', ['hand', 'graveyard', 'battlefield'])
@pytest.mark.parametrize('restore', [False, True])
def test_linked_single_card_move_choice_survives_clone(destination, restore):
    eng = game()
    source = board(eng, creature('Source'))
    card = exile(eng, source, creature('Bear'), owner='p2')
    exile(eng, source, creature('Other Bear'))
    text = ('put a creature card exiled with ~ onto the battlefield under your control' if destination == 'battlefield'
            else "put a card exiled with ~ into its owner's " + destination)
    apply(eng, source, text)
    assert eng.state.pending_choice['kind'] == 'choose_objects'
    if restore:
        eng = GameEngine(eng.state.clone())
        source, card = eng.state.find_object(source.instance_id), eng.state.find_object(card.instance_id)
    eng.resolve_pending_choice(str(card.instance_id))
    eng.resolve_until_stable()
    assert card.zone.value == destination
    if destination == 'battlefield':
        assert card.controller_id == 'p1'


def test_linked_return_choice_cannot_take_a_later_exile_visit():
    eng = game()
    source = board(eng, creature('Source'))
    card = exile(eng, source)
    exile(eng, source, _instant("Other"))
    apply(eng, source, "return a card exiled with ~ to its owner's hand")
    _move(eng, card, Zone.HAND)
    _move(eng, card, Zone.EXILE)
    with pytest.raises(ValueError, match='not a legal choice'):
        eng.resolve_pending_choice(str(card.instance_id))
    assert card.zone == Zone.EXILE


def test_profane_procession_tracks_exiles_read_only_from_a_condition():
    card = creature('Source', oracle_text=(
        '{0}: Exile target creature. Then if there are three or more cards exiled with Source, transform it.'))
    specs = parse_oracle(card)
    assert specs.modeled
    assert specs.specs[0].effects[0].params['track_exiled_with'] is True


def test_unimplemented_mana_exile_rider_keeps_forger_fail_closed():
    card = Card(id='foundry', name="Forger's Foundry", type_line='Artifact', oracle_text=(
        "{T}: Add {U}. When you spend this mana to cast an instant or sorcery spell with mana value 3 or less, "
        "you may exile that spell instead of putting it into its owner's graveyard as it resolves.\n"
        '{3}{U}{U}, {T}: You may cast any number of spells from among cards exiled with this artifact '
        'without paying their mana costs. Activate only as a sorcery.'))
    assert not parse_oracle(card).modeled


def test_skipped_conditional_exile_cannot_reuse_an_earlier_batch():
    eng = game()
    player = eng.state.player_by_id('p1')
    card = _in_graveyard(eng, _instant())
    cast(eng, ('Exile target card from a graveyard. Exile the top card of your library if you control an artifact. '
               'You may cast that card this turn without paying its mana cost.'), [card])
    assert card.zone == Zone.EXILE
    assert not eng.can_cast(player, card)


def test_a_failed_leading_condition_does_not_grant_a_window_to_a_previous_batch():
    eng = game()
    source = board(eng, creature('Source'))
    from mtg_analyzer.game.effects.exile_control import ExileTopOfLibraryEffect
    from mtg_analyzer.game.effects.game_status import ConditionalEffect
    first = _instant('First')
    card = GameObject(first, owner_id='p1', zone=Zone.LIBRARY)
    eng.state.player_by_id('p1').library.append(card)
    ExileTopOfLibraryEffect(source=source).apply(eng.rules.context)
    ConditionalEffect({'kind': 'control_count', 'selector': 'artifacts_you_control', 'min': 1},
                      ExileTopOfLibraryEffect(source=source), source=source).apply(eng.rules.context)
    assert eng.rules.context.latest_exiled_visits == []
    apply(eng, source, 'you may cast cards exiled with ~ this turn')
    assert not eng.can_cast(eng.state.player_by_id('p1'), card)


def test_delve_links_cost_exiles_through_cast_and_entry_for_ethereal_forager():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng = game()
    player = eng.state.player_by_id('p1')
    spell = _in_graveyard(eng, _instant())
    for i in range(3):
        _in_graveyard(eng, creature(f'Delve payment {i}'))
    card = creature('Ethereal Forager', power=3, toughness=3, cost='{4}{U}{U}',
                    oracle_text=('Delve\nFlying\nWhenever Ethereal Forager attacks, you may return an instant '
                                 "or sorcery card exiled with Ethereal Forager to its owner's hand."),
                    keywords=['Delve', 'Flying'])
    obj = GameObject(card, owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.hand.append(obj)
    player.mana_pool.add('U', 2)
    eng.cast_spell(player, obj, help_pay=True)
    eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD
    assert spell in linked_cards(eng.state, obj)
    eng.state.fire_event(GameEvent(EventType.ATTACKS, instance_id=obj.instance_id, controller_id=player.id))
    eng.resolve_until_stable()
    if eng.state.pending_choice:
        options = eng.state.pending_choice['options']
        eng.resolve_pending_choice(next(o['id'] for o in options if o['id'] not in ('no', 'decline')))
        eng.resolve_until_stable()
    assert spell.zone == Zone.HAND


def test_nested_static_permission_conditions_are_both_required():
    eng = game()
    source = board(eng, creature('Conditional grant', oracle_text=(
        '{T}: Exile target card from a graveyard.\n'
        'During your turn, as long as you control an artifact, you may cast cards exiled with Conditional grant.')))
    card = exile(eng, source)
    player = eng.state.player_by_id('p1')
    player.mana_pool.add('C', 1)
    assert not eng.can_cast(player, card)
    board(eng, Card(id='artifact', name='Artifact', type_line='Artifact'))
    assert eng.can_cast(player, card)
    eng.state.active_player_index = 1
    assert not eng.can_cast(player, card)


def test_bare_linked_battlefield_return_uses_the_acting_players_control():
    eng = game()
    source = board(eng, creature('Source'))
    card = exile(eng, source, creature('Theirs'), owner='p2')
    apply(eng, source, 'put a creature card exiled with ~ onto the battlefield')
    eng.resolve_until_stable()
    assert card.zone == Zone.BATTLEFIELD and card.controller_id == 'p1'


def test_other_linked_cards_need_a_distinct_exclusion_antecedent():
    assert parse_effect_body('return all other permanent cards exiled with ~ to the battlefield under their owners\' control') is None
