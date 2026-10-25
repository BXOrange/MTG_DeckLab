"""PAR-192 ordinary effect bodies shared by opening-hand permissions."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.deck_batch import card, cast, enter, filler, game


DEVOURER_DIG = (
    "Look at the top four cards of your library. You may put one of those cards "
    "back on top of your library. Exile the rest."
)


@pytest.mark.parametrize("initial", (12, 26, 40))
def test_providence_normal_spell_sets_its_controllers_life(initial):
    eng = game()
    player = eng.state.player_by_id('p1')
    player.life = initial
    spell = card(eng, 'Providence', zone=Zone.HAND)
    cast(eng, spell)
    assert player.life == 26
    assert eng.state.player_by_id('p2').life == 20


def test_life_setting_preserves_life_change_prohibition():
    eng = game()
    player = eng.state.player_by_id('p1')
    shield = card(eng, "Teferi's Protection", zone=Zone.HAND)
    cast(eng, shield)
    spell = card(eng, 'Providence', zone=Zone.HAND)
    cast(eng, spell)
    assert player.life == 20


@pytest.mark.parametrize('text', (
    'your life total becomes x',
    'your life total becomes 26 for the rest of the game',
    'your life total becomes 26 and draw a card',
))
def test_unsupported_life_setters_are_not_claimed(text):
    assert match_clause(text) is None


def _dig_game(library_size=5):
    eng = game(library=0)
    library = [filler(eng, f'Library {i}', zone=Zone.LIBRARY) for i in range(library_size)]
    spell = filler(eng, 'Inspection', type_line='Sorcery', zone=Zone.HAND, oracle_text=DEVOURER_DIG)
    cast(eng, spell)
    return eng, library


def test_look_choose_top_and_exile_rest_uses_the_bounded_inspected_pool():
    eng, library = _dig_game()
    choice = eng.state.pending_choice
    ids = {option.get('instance_id') for option in choice['options']}
    assert library[0].instance_id not in ids
    assert {obj.instance_id for obj in library[1:]} <= ids
    eng.resolve_pending_choice(str(library[2].instance_id))
    eng.resolve_until_stable()
    player = eng.state.player_by_id('p1')
    assert player.library == [library[0], library[2]]
    assert {obj.instance_id for obj in player.exile} == {obj.instance_id for obj in (library[1], library[3], library[4])}


@pytest.mark.parametrize('size', (1, 3, 5))
def test_declining_to_keep_a_card_exiles_only_the_inspected_cards(size):
    eng, library = _dig_game(size)
    eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    player = eng.state.player_by_id('p1')
    assert player.library == (library[:-4] if size > 4 else [])
    assert {obj.instance_id for obj in player.exile} == {obj.instance_id for obj in library[-4:]}


def test_empty_library_has_no_choice_or_exiles():
    eng, _ = _dig_game(0)
    assert eng.state.pending_choice is None
    assert not eng.state.player_by_id('p1').exile


def test_inspection_choice_survives_clone():
    eng, library = _dig_game()
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice(str(library[2].instance_id))
    clone.resolve_until_stable()
    assert clone.state.player_by_id('p1').library[-1].instance_id == library[2].instance_id
    assert len(clone.state.player_by_id('p1').exile) == 3
    assert len(eng.state.player_by_id('p1').library) == 5
    assert not eng.state.player_by_id('p1').exile


@pytest.mark.parametrize('text', (
    'look at the top 4 cards of your library. you may put 1 of those cards back on top of your library. exile the rest face down',
    'look at the top 4 cards of your library. you may put 1 of those cards back on top of your library. exile the rest until end of turn',
))
def test_unsupported_inspection_exile_riders_remain_unclaimed(text):
    assert parse_effect_body(text) is None


def test_colored_permanent_target_uses_colors_not_identity_and_rechecks():
    eng = game()
    white = filler(eng, 'White enchantment', type_line='Enchantment', color_identity={'W'},
                   mana_cost_string='{W}')
    mixed = filler(eng, 'Mixed artifact', type_line='Artifact', color_identity={'U', 'B'},
                   mana_cost_string='{U}{B}')
    colorless = card(eng, 'Forest')  # Green identity, but no actual color.
    spell = filler(eng, 'Colored exile', type_line='Instant', zone=Zone.HAND,
                   oracle_text="Exile target permanent that's one or more colors.")
    spec = spell.spell_effects[0].target_spec
    offers = {option.get('instance_id') for option in legal_targets(eng.state, 'p1', spec, spell)}
    assert {white.instance_id, mixed.instance_id} <= offers
    assert colorless.instance_id not in offers
    eng.cast_spell(eng.state.player_by_id('p1'), spell, targets=[white])
    white.card.mana_cost_string = ''
    white.card.mana_cost = {}
    eng.recompute_continuous_effects()
    eng.resolve_until_stable()
    assert white.zone == Zone.BATTLEFIELD


def test_colored_permanent_exile_executes_for_noncreatures():
    eng = game()
    victim = filler(eng, 'White enchantment', type_line='Enchantment', color_identity={'W'},
                    mana_cost_string='{W}')
    spell = filler(eng, 'Colored exile', type_line='Instant', zone=Zone.HAND,
                   oracle_text="Exile target permanent that's one or more colors.")
    cast(eng, spell, targets=[victim])
    assert victim.zone == Zone.EXILE


@pytest.mark.parametrize('text', (
    "exile target permanent that's 2 or more colors",
    "exile target permanent that's 1 or more colors until end of turn",
    "exile target white or green permanent that's 1 or more colors",
))
def test_unrepresented_color_count_or_rider_is_not_claimed(text):
    assert match_clause(text) is None


def _library_cards(eng, size=5):
    return [filler(eng, f'Library {i}', zone=Zone.LIBRARY) for i in range(size)]


@pytest.mark.parametrize('name', ('Gurmag Nightwatch', 'Sage of Days'))
@pytest.mark.parametrize('keep', (False, True))
def test_incidental_top_three_keep_and_graveyard_cards(name, keep):
    eng = game(library=0)
    library = _library_cards(eng)
    source = card(eng, name)
    enter(eng, source)
    assert {o.get('instance_id') for o in eng.state.pending_choice['options']} >= {
        obj.instance_id for obj in library[-3:]}
    eng.resolve_pending_choice(str(library[-2].instance_id) if keep else 'decline')
    eng.resolve_until_stable()
    player = eng.state.player_by_id('p1')
    assert player.library == library[:-3] + ([library[-2]] if keep else [])
    expected_graveyard = [obj for obj in library[-3:] if not keep or obj is not library[-2]]
    assert set(obj.instance_id for obj in player.graveyard) == set(obj.instance_id for obj in expected_graveyard)


def test_incidental_raid_inspection_requires_a_prior_attack():
    eng = game(library=0)
    library = _library_cards(eng)
    source = card(eng, 'Gutless Plunderer')
    enter(eng, source)
    assert eng.state.pending_choice is None
    attacker = filler(eng, 'Attacker', power=2, toughness=2)
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(eng.state.player_by_id('p1'), [attacker])
    enter(eng, source)
    assert eng.state.pending_choice is not None
    eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    assert eng.state.player_by_id('p1').library == library[:-3]


def test_incidental_domain_inspection_measures_land_types_and_bottoms_the_rest():
    eng = game(library=0)
    library = _library_cards(eng)
    card(eng, 'Forest')
    card(eng, 'Island')
    source = card(eng, 'Voda Sea Scavenger')
    enter(eng, source)
    offered = {o.get('instance_id') for o in eng.state.pending_choice['options']}
    assert {o.instance_id for o in library[-2:]} <= offered
    assert library[-3].instance_id not in offered
    eng.resolve_pending_choice(str(library[-1].instance_id))
    eng.resolve_until_stable()
    assert eng.state.player_by_id('p1').library == [library[-2], *library[:-2], library[-1]]


def test_prophetic_bolt_keeps_one_and_lets_its_controller_order_each_rest_card():
    eng = game(library=0)
    library = _library_cards(eng)
    spell = card(eng, 'Prophetic Bolt', zone=Zone.HAND)
    cast(eng, spell, targets=[eng.state.player_by_id('p2')])
    assert eng.state.player_by_id('p2').life == 16
    assert eng.state.pending_choice['kind'] == 'look_top_select'
    assert 'decline' not in {o['id'] for o in eng.state.pending_choice['options']}
    eng.resolve_pending_choice(str(library[-1].instance_id))
    assert eng.state.pending_choice['phase'] == 'order'
    # The requested bottom ordering differs from both initial library orders.
    for obj in (library[1], library[3], library[2]):
        eng.resolve_pending_choice(str(obj.instance_id))
    eng.resolve_until_stable()
    player = eng.state.player_by_id('p1')
    assert library[-1] in player.hand
    assert player.library == [library[2], library[3], library[1], library[0]]


def test_unknown_numbered_pick_or_rest_order_stays_unclaimed():
    assert parse_effect_body(
        'look at the top 4 cards of your library. put 1 of those cards into your hand '
        'and the rest on the bottom of your library in an opponent\'s choice of order'
    ) is None
