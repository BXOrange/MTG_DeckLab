"""Saga flavor labels compose with ordinary chapter bodies and return axes."""
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature
from test_par157_back_selections import _cached


@pytest.mark.parametrize('label', ['Jecht Beam', 'Wings of Light', 'Hall of Sorrow', 'Stampede!', 'Future Label'])
def test_chapter_flavor_labels_are_independent_of_card_and_keyword_metadata(label):
    text = f'I, II — {label} — Draw a card.'
    assert normalize(text) == 'i, ii — draw a card.'
    assert parse_oracle(Card(id='saga', name='Saga', type_line='Enchantment — Saga', oracle_text=text)).modeled


@pytest.mark.parametrize('text', [
    'I — Choose one — Draw a card.',
    'I — Destroy All Creatures — Draw a card.',
    'I — Flying — Draw a card.',
    'I — unknown rule — Draw a card.',
    'I — This Saga gains "Landfall — Whenever a land you control enters, draw a card."',
    'I — Target opponent faces a villainous choice — Draw a card.',
])
def test_real_instructions_keywords_and_unknown_lowercase_labels_are_not_stripped(text):
    assert normalize(text) == text.lower().replace('choose one', 'choose 1')


@pytest.mark.parametrize('recipient,expected', [('', 'p1'), (" under its owner's control", 'p2'), (' under your control', 'p1')])
def test_blink_return_recipient_is_an_independent_axis(recipient, expected):
    eng = _engine()
    source = _bf(eng, _creature('Stolen'), 'p2')
    source.controller_id = 'p1'
    incarnation = source.zone_incarnation
    specs = parse_effect_body('exile ~, then return it to the battlefield' + recipient)
    assert specs and specs[0].type == 'blink'
    for effect in build_effects(specs, source):
        effect.apply(eng.rules.context)
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and source.zone_incarnation > incarnation
    assert source.controller_id == expected


@pytest.mark.full_cache
def test_jecht_front_transforms_and_shared_flavor_chapters_draw_then_sacrifice():
    eng = _engine()
    card = _cached("Jecht, Reluctant Guardian // Braska's Final Aeon")
    assert parse_oracle(card).modeled and parse_oracle(card.back_face()).modeled
    source = _bf(eng, card)
    own = eng.state.player_by_id('p1')
    for i in range(3):
        own.library.append(GameObject(card=_creature(f'Draw {i}'), owner_id='p1', controller_id='p1', zone=Zone.LIBRARY))
    eng.rules.deal_damage(eng.state.player_by_id('p2'), 1, source=source, combat=True)
    eng.resolve_until_stable()
    assert eng.state.pending_choice
    eng.resolve_pending_choice('do')
    eng.resolve_until_stable()
    assert source.transformed and source.name == card.back_name
    assert len(own.hand) == 1
    eng.rules.advance_sagas(own)
    eng.resolve_until_stable()
    assert len(own.hand) == 2
    victims = [_bf(eng, _creature(f'Victim {i}'), 'p2') for i in range(2)]
    eng.rules.advance_sagas(own)
    eng.resolve_until_stable()
    assert all(victim.zone == Zone.GRAVEYARD for victim in victims)
    assert source.zone == Zone.GRAVEYARD


@pytest.mark.full_cache
def test_jill_back_taps_opponents_lands_and_returns_front_under_ability_controller():
    eng = _engine()
    card = _cached("Jill, Shiva's Dominant // Shiva, Warden of Ice")
    assert parse_oracle(card).modeled and parse_oracle(card.back_face()).modeled
    source = _bf(eng, card, 'p2')
    eng.resolve_until_stable()
    # Enter on the printed back through the shared transformed-return effect.
    for effect in build_effects(parse_effect_body(
        "exile ~, then return it to the battlefield transformed under its owner's control"), source):
        effect.apply(eng.rules.context)
    eng.resolve_until_stable()
    if eng.state.pending_choice:
        eng.resolve_pending_choice(str(source.instance_id))
        eng.resolve_until_stable()
    source.controller_id = 'p1'
    other = _bf(eng, Card(id='other', name='Other land', type_line='Land', is_land=True), 'p2')
    own = _bf(eng, Card(id='own', name='Own land', type_line='Land', is_land=True))
    player = eng.state.player_by_id('p1')
    for _ in range(2):
        eng.rules.advance_sagas(player)
        eng.resolve_until_stable()
        if eng.state.pending_choice and eng.state.pending_choice['kind'] == 'trigger_target':
            eng.resolve_pending_choice(str(source.instance_id))
            eng.resolve_until_stable()
    assert other.tapped and not own.tapped
    assert source.zone == Zone.BATTLEFIELD and not source.transformed
    assert source.controller_id == 'p1' and source.owner_id == 'p2'


def test_source_pronoun_scope_is_required_for_flicker_capture():
    from mtg_analyzer.parser.oracle.catalogue.flicker_sequences import flicker_sequence_specs
    body = "exile it, then return it to the battlefield transformed under its owner's control"
    assert flicker_sequence_specs(body) is None
    assert flicker_sequence_specs(body, reading=ClauseReading(self_subject=True))[0].params['subject'] == 'source'


@pytest.mark.parametrize('tail', ['under a secret controller', 'and secretly double its power'])
def test_unknown_return_qualifiers_stay_unclaimed(tail):
    assert parse_effect_body('exile ~, then return it to the battlefield ' + tail) is None


@pytest.mark.full_cache
def test_anima_final_chapter_keeps_opponents_as_shared_sacrifice_and_life_subject():
    eng = _engine()
    source = _bf(eng, _cached('Summon: Anima'))
    victim = _bf(eng, _creature('Opponent creature'), 'p2')
    eng.resolve_until_stable()
    player = eng.state.player_by_id('p1')
    for _ in range(3):
        eng.rules.advance_sagas(player)
        eng.resolve_until_stable()
    assert source.zone == victim.zone == Zone.GRAVEYARD
    assert player.life == 17 and eng.state.player_by_id('p2').life == 17


@pytest.mark.parametrize('scope', ['each player', 'each opponent'])
def test_group_subject_survives_known_elided_verbs_and_explicit_you_resets_it(scope):
    eng = _engine()
    source = _bf(eng, Card(id='Source', name='Source', type_line='Enchantment'))
    text = f'{scope} draws a card and loses 2 life and you draw a card and gain 3 life'
    specs = parse_effect_body(text)
    assert specs
    for effect in build_effects(specs, source):
        effect.apply(eng.rules.context)
    eng.resolve_until_stable()
    own, other = eng.state.player_by_id('p1'), eng.state.player_by_id('p2')
    assert own.life == (21 if scope == 'each player' else 23)
    assert other.life == 18
    assert len(own.hand) == (2 if scope == 'each player' else 1)
    assert len(other.hand) == 1
