"""PAR-213: bounded inspection sequences execute with exact, resumable pools."""
import pytest

from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import game, filler, answer, card, cast


def run(eng, text, targets=None):
    source = filler(eng, 'Inspection source', type_line='Artifact')
    specs = parse_effect_body(text)
    assert specs is not None
    effects = build_effects(specs, source)
    _apply_effects_partitioned(effects, eng.rules.context, source=source, targets=targets, target_groups=None)
    return source


def test_separate_selections_use_only_remaining_cards():
    eng = game(library=0)
    p = eng.state.player_by_id('p1')
    cards = [filler(eng, str(i), zone=Zone.LIBRARY) for i in range(5)]
    run(eng, 'look at the top 3 cards of your library. put 1 of them into your hand. put 1 of them into your graveyard. put the rest on the bottom of your library')
    assert p.library == cards
    eng.resolve_pending_choice('done')
    assert {o['instance_id'] for o in eng.state.pending_choice['options']} == {o.instance_id for o in cards[2:]}
    eng.resolve_pending_choice(str(cards[4].instance_id))
    eng.resolve_pending_choice(str(cards[3].instance_id))
    assert cards[4] in p.hand and cards[3] in p.graveyard
    assert p.library == [cards[2], cards[0], cards[1]]


def test_optional_selection_decline_keeps_full_rest_pool():
    eng = game(library=0)
    cards = [filler(eng, str(i), zone=Zone.LIBRARY) for i in range(3)]
    run(eng, 'look at the top 3 cards of your library. you may exile a creature card from among them. put the rest into your hand')
    eng.resolve_pending_choice('done')
    eng.resolve_pending_choice('decline')
    assert all(o.zone == Zone.HAND for o in cards)


def test_opponent_chooses_then_you_place_creature():
    eng = game(library=0)
    creature = filler(eng, 'Creature', zone=Zone.LIBRARY, power=3, toughness=3)
    land = filler(eng, 'Land', type_line='Land', zone=Zone.LIBRARY)
    run(eng, 'reveal the top 5 cards of your library. an opponent chooses a creature card from among them. put that card onto the battlefield and the rest into your graveyard')
    eng.resolve_pending_choice('done')
    assert eng.state.pending_choice['player_id'] == 'p2'
    eng.resolve_pending_choice(str(creature.instance_id))
    assert creature.zone == Zone.BATTLEFIELD and land.zone == Zone.GRAVEYARD


@pytest.mark.parametrize('text', [
    'look at the top x cards of your library. exile them',
    'look at the top 3 cards of your library. put a card with mana value equal to your life total from among them into your hand',
    'look at the top 3 cards of your library. put 1 of them into your hand. put the rest on mars',
])
def test_unknown_steps_fail_closed(text):
    assert parse_effect_body(text) is None


@pytest.mark.parametrize('name', ['Animal Magnetism', 'Rousing of Souls', "Selvala's Charge", 'Cutthroat Negotiator', "Selvala's Enforcer", 'Genesis Ultimatum'])
def test_real_cards_parse(name):
    from mtg_analyzer.parser.oracle import parse_oracle
    from tests.test_mec118_opponent_choice import _db_card
    result = parse_oracle(_db_card(name))
    assert result.modeled, result.unclaimed


def test_parley_counts_each_players_revealed_card_before_draw():
    eng = game(players=3, library=0)
    tops = [filler(eng, 'Top' + p, player=p, zone=Zone.LIBRARY,
                   type_line='Land' if p == 'p2' else 'Artifact') for p in ['p1', 'p2', 'p3']]
    spell = card(eng, 'Rousing of Souls', zone=Zone.HAND)
    cast(eng, spell)
    assert eng.state.pending_choice['kind'] == 'inspection'
    assert all(obj.zone == Zone.LIBRARY for obj in tops)
    eng.resolve_pending_choice('done')
    eng.resolve_until_stable()
    tokens = [o for o in eng.state.battlefield if o.is_token]
    assert len(tokens) == 2 and all('flying' in o.granted_keywords | o.intrinsic_keywords for o in tokens)
    assert all(obj.zone == Zone.HAND for obj in tops)


def test_clone_mid_selection_keeps_exact_pool_and_ordering():
    from mtg_analyzer.game.game_engine import GameEngine
    eng = game(library=0)
    cards = [filler(eng, str(i), zone=Zone.LIBRARY) for i in range(4)]
    run(eng, 'look at the top 4 cards of your library. you may exile up to 2 creature cards from among them. put the rest on the bottom of your library in any order')
    eng.resolve_pending_choice('done')
    eng.resolve_pending_choice(str(cards[3].instance_id))
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice('decline')
    assert clone.state.pending_choice['mode'] == 'order'
    clone.resolve_pending_choice(str(cards[1].instance_id))
    clone = GameEngine(clone.state.clone())
    clone.resolve_pending_choice(str(cards[0].instance_id))
    assert clone.state.find_object(cards[3].instance_id).zone == Zone.EXILE
    assert [o.instance_id for o in clone.state.player_by_id('p1').library] == [cards[i].instance_id for i in [2, 0, 1]]
    assert cards[3].zone == Zone.LIBRARY


@pytest.mark.parametrize('reveal', [False, True])
def test_inspection_visibility_is_limited_to_exact_visits(reveal):
    from mtg_analyzer.services.game_session import GameSession
    eng = game(library=0)
    cards = [filler(eng, str(i), zone=Zone.LIBRARY) for i in range(4)]
    run(eng, ('reveal' if reveal else 'look at') + ' the top 3 cards of your library')
    session = GameSession(eng)
    for viewer in ['p1', 'p2']:
        state = session.view(perspective=viewer)['state']
        library = next(p['library'] for p in state['players'] if p['id'] == 'p1')
        assert {o['instance_id'] for o in library} == ({o.instance_id for o in cards[1:]} if reveal or viewer == 'p1' else set())
    observer = session.observer_view()['state']
    assert len(observer['players'][0]['library']) == (3 if reveal else 0)


@pytest.mark.parametrize('land', [False, True])
def test_single_reveal_condition_reads_card_not_source(land):
    eng = game(library=0)
    filler(eng, 'Top', type_line='Land' if land else 'Creature', zone=Zone.LIBRARY)
    source = card(eng, 'Brutal Deceiver')
    from tests.support.deck_batch import activate
    eng.state.player_by_id('p1').mana_pool.add_many({'C': 4})
    activate(eng, source, index=1)
    eng.resolve_pending_choice('done')
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert source.power == (3 if land else 2)
    assert ('first_strike' in source.granted_keywords) == land


def test_multiple_filtered_selections_and_elliptical_disposal():
    eng = game(library=0)
    land = filler(eng, 'Land', type_line='Land', zone=Zone.LIBRARY)
    elf = filler(eng, 'Elf', type_line='Creature — Elf', power=1, toughness=1, zone=Zone.LIBRARY)
    other = filler(eng, 'Other', type_line='Artifact', zone=Zone.LIBRARY)
    spell = card(eng, 'Bounty of Skemfar', zone=Zone.HAND)
    cast(eng, spell)
    eng.resolve_pending_choice('done')
    eng.resolve_pending_choice(str(land.instance_id))
    eng.resolve_pending_choice(str(elf.instance_id))
    assert land.zone == Zone.BATTLEFIELD and land.tapped
    assert elf.zone == Zone.HAND and other.zone == Zone.LIBRARY
    # A second real card uses repeated, elided "put one of them" steps.
    eng = game(library=0)
    cards = [filler(eng, str(i), zone=Zone.LIBRARY) for i in range(3)]
    cast(eng, card(eng, 'Moment of Truth', zone=Zone.HAND))
    eng.resolve_pending_choice('done')
    eng.resolve_pending_choice(str(cards[2].instance_id))
    eng.resolve_pending_choice(str(cards[1].instance_id))
    eng.resolve_pending_choice(str(cards[0].instance_id))
    assert cards[2].zone == Zone.HAND and cards[1].zone == Zone.GRAVEYARD
    assert cards[0].zone == Zone.LIBRARY


def test_random_selection_is_not_a_player_choice():
    eng = game(library=0)
    cards = [filler(eng, str(i), zone=Zone.LIBRARY) for i in range(8)]
    run(eng, 'look at the top 8 cards of your library. exile 4 of them at random, then put the rest on top of your library in any order')
    eng.resolve_pending_choice('done')
    assert sum(o.zone == Zone.EXILE for o in cards) == 4
    assert eng.state.pending_choice['mode'] == 'order'


def test_composed_hand_selection_exile_executes_and_reveals_to_everyone():
    from mtg_analyzer.services.game_session import GameSession
    eng = game(library=0)
    victim = filler(eng, 'Victim', player='p2', type_line='Artifact', zone=Zone.HAND)
    land = filler(eng, 'Land', player='p2', type_line='Land', zone=Zone.HAND)
    run(eng, 'target opponent reveals their hand. you choose a nonland card from it. exile that card',
        targets=[eng.state.player_by_id('p2')])
    assert len(GameSession(eng).observer_view()['state']['players'][1]['hand']) == 2
    if eng.state.pending_choice['kind'] == 'inspection':
        eng.resolve_pending_choice('done')
    assert {o['instance_id'] for o in eng.state.pending_choice['options']} == {victim.instance_id}
    eng.resolve_pending_choice(str(victim.instance_id))
    assert victim.zone == Zone.EXILE and land.zone == Zone.HAND


def test_departed_and_returned_card_does_not_reenter_inspected_pool():
    eng = game(library=0)
    original = filler(eng, 'Original', zone=Zone.LIBRARY)
    run(eng, 'look at the top card of your library. put 1 of them into your hand')
    eng.rules.exile(original)
    owner = eng.state.player_by_id('p1')
    eng.rules._remove_from_current_zone(owner, original)
    owner.add_to_zone(original, Zone.LIBRARY)
    eng.resolve_pending_choice('done')
    assert eng.state.pending_choice is None
    assert original.zone == Zone.LIBRARY


@pytest.mark.parametrize('text', [
    'look at the top 3 cards of your library. exile 1 of them if it is red',
    'look at the top 3 cards of your library. put 1 of them into your hand. it gains flying until end of turn',
    'look at the top 3 cards of your library. reveal a card from among them and put it into your hand. destroy target creature',
])
def test_unknown_riders_and_hidden_targets_fail_closed(text):
    assert parse_effect_body(text) is None


@pytest.mark.parametrize('decline', [False, True])
def test_optional_choice_guards_the_following_action(decline):
    eng = game(library=0)
    selected = filler(eng, 'Selected', zone=Zone.LIBRARY)
    run(eng, 'look at the top card of your library. you may choose a card from among them. if you do, exile that card. put the rest into your hand')
    eng.resolve_pending_choice('done')
    eng.resolve_pending_choice('decline' if decline else str(selected.instance_id))
    assert selected.zone == (Zone.HAND if decline else Zone.EXILE)


def test_entry_choice_suspends_disposal_and_survives_clone():
    from mtg_analyzer.game.game_engine import GameEngine
    eng = game(library=0)
    entering = card(eng, 'Adaptive Automaton', zone=Zone.LIBRARY)
    rest = filler(eng, 'Rest', type_line='Sorcery', zone=Zone.LIBRARY)
    run(eng, 'reveal the top 2 cards of your library. choose all creature cards from among them. put those cards onto the battlefield. put the rest into your graveyard')
    eng.resolve_pending_choice('done')
    assert eng.state.pending_choice is not None
    assert rest.zone == Zone.LIBRARY
    clone = GameEngine(eng.state.clone())
    answer(clone)
    assert clone.state.find_object(entering.instance_id).zone == Zone.BATTLEFIELD
    assert clone.state.find_object(rest.instance_id).zone == Zone.GRAVEYARD


def test_unknown_card_qualities_and_exile_riders_are_not_guessed():
    assert parse_effect_body('look at the top 3 cards of your library. put a mysterious card from among them into your hand') is None
    assert parse_effect_body('look at the top 3 cards of your library. exile 1 of them face down') is None


def test_revealing_a_selection_does_not_reveal_the_other_looked_at_cards():
    from mtg_analyzer.services.game_session import GameSession
    eng = game(library=0)
    chosen = filler(eng, 'Chosen', type_line='Artifact', zone=Zone.LIBRARY)
    other = filler(eng, 'Other', type_line='Land', zone=Zone.LIBRARY)
    run(eng, 'look at the top 2 cards of your library. you may reveal an artifact card from among them and put it into your hand. put the rest into your hand')
    eng.resolve_pending_choice('done')
    eng.resolve_pending_choice(str(chosen.instance_id))
    assert eng.state.pending_choice['mode'] == 'ack'
    public = GameSession(eng).observer_view()['state']['players'][0]['library']
    assert {o['instance_id'] for o in public} == {chosen.instance_id}
    eng.resolve_pending_choice('done')
    assert chosen.zone == Zone.HAND and other.zone == Zone.HAND


def test_suspended_source_effect_does_not_affect_a_returned_source():
    from tests.support.deck_batch import activate
    eng = game(library=0)
    filler(eng, 'Top', type_line='Land', zone=Zone.LIBRARY)
    source = card(eng, 'Brutal Deceiver')
    eng.state.player_by_id('p1').mana_pool.add_many({'C': 4})
    activate(eng, source, index=1)
    eng.rules.exile(source)
    owner = eng.state.player_by_id('p1')
    eng.rules._remove_from_current_zone(owner, source)
    eng.rules._put_searched_card(owner, source, 'battlefield')
    eng.resolve_pending_choice('done')
    eng.recompute_continuous_effects()
    assert source.power == 2 and 'first_strike' not in source.granted_keywords


@pytest.mark.parametrize('top_is_creature', [True, False])
def test_llanowar_empath_it_is_the_revealed_card_not_the_creature(top_is_creature):
    """Scry 2, then reveal: "put it into your hand" moves the revealed creature card, never bounces the source."""
    eng = game(library=0)
    p = eng.state.player_by_id('p1')
    filler(eng, 'Below', type_line='Artifact', zone=Zone.LIBRARY)  # the library's top is its last element
    top = filler(eng, 'Top', type_line='Creature' if top_is_creature else 'Artifact', zone=Zone.LIBRARY)
    empath = card(eng, 'Llanowar Empath', zone=Zone.HAND)
    cast(eng, empath)
    for _ in range(6):  # scry's own prompts: decline = keep everything on top; then acknowledge the reveal
        pending = eng.state.pending_choice
        if not pending:
            break
        eng.resolve_pending_choice('decline' if pending.get('kind') == 'scry' else 'done')
        eng.resolve_until_stable()
    assert empath.zone == Zone.BATTLEFIELD
    assert (top in p.hand) == top_is_creature
    assert (top in p.library) != top_is_creature


@pytest.mark.parametrize('land', [True, False])
def test_harsh_deceiver_condition_gates_the_whole_compound_payoff(land):
    from tests.support.deck_batch import activate
    eng = game(library=0)
    filler(eng, 'Top', type_line='Land' if land else 'Creature', zone=Zone.LIBRARY)
    source = card(eng, 'Harsh Deceiver')
    source.tapped = True
    eng.state.player_by_id('p1').mana_pool.add_many({'C': 4})
    activate(eng, source, index=1)
    eng.resolve_pending_choice('done')
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    base = source.card.power
    assert (not source.tapped) == land
    assert source.power == base + (1 if land else 0)
    assert source.toughness == source.card.toughness + (1 if land else 0)
