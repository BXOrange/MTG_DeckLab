"""Permanent product policy is distinct from incomplete rules coverage."""
from types import SimpleNamespace
import pytest
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.cards.support_policy import card_support_policy, unsupported_reason


def card(text='', **kwargs):
    return Card(id='x', name='Policy fixture', type_line=kwargs.pop('type_line', 'Artifact'),
                oracle_text=text, **kwargs)


@pytest.mark.parametrize('text,reason', [
    ('Return them in the next game you play.', 'cross_game'),
    ('You may cast it during another game this match.', 'cross_game'),
    ('Each player in an Un-game who can hear you may bid life.', 'cross_game'),
    ('Put a sticker on it.', 'stickers'),
    ('It has trample as long as you control a stickered permanent.', 'stickers'),
    ('Open an Attraction.', 'attractions'),
    ('Assemble a Contraption.', 'contraptions'),
    ('Reveal this card as you draft it.', 'draft_matters'),
    ('Hidden agenda', 'draft_matters'),
    ('It perpetually gets +1/+1.', 'alchemy'),
    ('Specialize {2}', 'alchemy'),
    ('Conjure a duplicate of it into your hand.', 'alchemy'),
    ('Seek a nonland card.', 'alchemy'),
    ('Draft a card from its spellbook.', 'alchemy'),
])
def test_exclusion_shapes(text, reason):
    result = card_support_policy(card(text))
    assert result.unsupported and result.reason == reason


@pytest.mark.parametrize('type_line,reason', [('Stickers', 'stickers'),
                                              ('Artifact — Attraction', 'attractions'),
                                              ('Artifact — Contraption', 'contraptions')])
def test_empty_text_auxiliary_types(type_line, reason):
    assert unsupported_reason(card(type_line=type_line)) == reason


def test_back_face_is_checked():
    assert unsupported_reason(card(back_name='Other face', back_oracle_text='Specialize {3}')) == 'alchemy'


@pytest.mark.parametrize('text', [
    'You may choose a card you own from outside the game.',
    'Open a sealed booster pack and put a card from it into your hand.',
    'Your team gains 3 life.', 'Draw a card.', '',
])
def test_supported_product_shapes_are_not_claimed_unsupported(text):
    assert not card_support_policy(card(text)).unsupported


def test_vanguard_base_modifiers_preserved():
    assert unsupported_reason(card(type_line='Vanguard', layout='vanguard')) is None


@pytest.mark.parametrize('digital,games,legalities,excluded', [
    (True, ['arena'], {'commander':'not_legal','legacy':'not_legal','vintage':'not_legal'}, True),
    (True, ['mtgo'], {'commander':'legal','legacy':'legal','vintage':'legal'}, False),
    (True, ['arena'], {'commander':'legal','legacy':'legal','vintage':'legal'}, False),
    (True, ['paper','arena'], {'commander':'not_legal','legacy':'not_legal','vintage':'not_legal'}, False),
    (True, ['arena'], {}, False), (None, [], {}, False),
])
def test_printing_evidence_is_conservative(digital, games, legalities, excluded):
    assert card_support_policy(card(digital=digital,games=games,legalities=legalities)).unsupported == excluded


@pytest.mark.parametrize('paper_status', ['legal','banned','restricted'])
def test_paper_status_prevents_digital_print_false_positive(paper_status):
    legalities = dict.fromkeys(('commander','legacy','vintage'), 'not_legal')
    legalities['vintage'] = paper_status
    assert unsupported_reason(card(digital=True,games=['arena'],legalities=legalities)) is None


def test_legacy_cardlike_object_needs_no_metadata():
    assert not card_support_policy(SimpleNamespace(oracle_text='Draw a card.')).unsupported
