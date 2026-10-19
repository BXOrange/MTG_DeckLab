"""Permanent exclusions take precedence over ordinary parsing and authoring."""
import pytest
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.cards.support_policy import unsupported_reason
from mtg_analyzer.parser.oracle.gate import parse_oracle, NEVER_SUPPORTED
from mtg_analyzer.game import card_registry
from mtg_analyzer.api.cards import coverage_for
from mtg_analyzer.services.coverage_db import content_hash


def card(text='Draw a card.', **kwargs):
    return Card(id='unsupported', name=kwargs.pop('name', 'Policy integration'),
                type_line='Sorcery', is_sorcery=True, oracle_text=text, **kwargs)


@pytest.mark.parametrize('text,reason', [
    ('Return them in the next game you play.', 'cross_game'),
    ("If you've lost a game this match, you may play lands from your graveyard.", 'cross_game'),
    ('This match is now worth 6 base points instead of 3.', 'cross_game'),
    ('Players play a Magic subgame, using their libraries as their decks.', 'cross_game'),
    ('Restart the game, leaving in exile all non-Aura permanent cards.', 'cross_game'),
    ('Put a sticker on it.', 'stickers'),
    ('Open an Attraction.', 'attractions'),
    ('Assemble a Contraption.', 'contraptions'),
    ('Reveal this card as you draft it.', 'draft_matters'),
    ('Conjure a card named Black Lotus into your hand.', 'alchemy'),
])
def test_policy_precedes_authored_and_parser(text, reason, monkeypatch):
    c = card(text)
    monkeypatch.setitem(card_registry.core._REGISTRY, c.name.lower(), lambda: [])
    result = parse_oracle(c)
    assert result.coverage == NEVER_SUPPORTED
    assert result.unsupported_reason == reason
    assert not result.specs and not result.unclaimed
    assert card_registry.specs_for(c) == []
    assert not card_registry.is_authored_card(c)
    assert coverage_for(c) == dict(modeled=False, unsupported=True,
                                  unsupported_reason=reason, source='policy', unclaimed=[])
    assert c.to_dict()['unsupported'] is True
    assert c.to_dict()['unsupported_reason'] == reason


def test_digital_policy_not_memoized_as_paper():
    paper = card()
    digital = card(digital=True, games=['arena'],
                   legalities=dict.fromkeys(('commander', 'legacy', 'vintage'), 'not_legal'))
    assert parse_oracle(paper).modeled
    assert parse_oracle(digital).never_supported
    assert content_hash(paper) != content_hash(digital)
    assert parse_oracle(paper).modeled


@pytest.mark.parametrize('name,text', [
    ("Silvanus's Invoker", 'Conjure Elemental — {8}: Untap target land you control. It becomes an 8/8 Elemental creature with trample and haste until end of turn.'),
    ('Spellbook', 'You have no maximum hand size.'),
    ('Conjure', 'Conjure deals 3 damage to any target.'),
])
def test_paper_ability_labels_and_names_are_not_digital(name, text):
    c = card(text, name=name)
    assert unsupported_reason(c) is None
    assert not c.to_dict()['unsupported']


def test_missing_back_grammar_remains_ordinary_gap():
    c = card(back_name='Other face', back_oracle_text='An unknown action.')
    assert unsupported_reason(c) is None


def test_cross_game_back_face_is_permanent_exclusion():
    c = card(back_name='Other face', back_oracle_text='Return it in the next game you play.')
    assert parse_oracle(c).unsupported_reason == 'cross_game'


def test_reminder_with_last_game_does_not_assert_cross_game_behavior():
    c = card('Choose a card name. (A name chosen in the last game does not count.)')
    assert unsupported_reason(c) is None


@pytest.mark.parametrize('layout', ['transform', 'modal_dfc', 'split', 'flip'])
@pytest.mark.parametrize('excluded_back', [False, True])
def test_whole_card_exclusion_survives_face_projection_and_roundtrip(layout, excluded_back):
    texts = ['Return it in the next game you play.', '{T}: Draw a card.']
    if excluded_back:
        texts.reverse()
    c = Card(id='whole', name='Front // Back', type_line='Artifact', oracle_text=texts[0],
             layout=layout, back_name='Back', back_type_line='Artifact', back_oracle_text=texts[1])
    faces = [c.flip_face() if layout == 'flip' else c.back_face()]
    for face in faces:
        assert face is not None
        assert face.unsupported_reason == 'cross_game'
        assert card_registry.specs_for(face) == []
        loaded = Card.from_dict(face.to_dict())
        assert parse_oracle(loaded).unsupported_reason == 'cross_game'
        assert card_registry.specs_for(loaded) == []


def test_unrecognized_or_false_support_override_never_bypasses_policy():
    c = card('Return it in the next game you play.')
    data = c.to_dict()
    data['unsupported'] = False
    data['unsupported_reason'] = 'made_up'
    assert Card.from_dict(data).unsupported_reason == 'cross_game'
    ordinary = card().to_dict()
    ordinary['unsupported_reason'] = 'made_up'
    assert Card.from_dict(ordinary).unsupported_reason is None


@pytest.mark.parametrize('excluded_back', [False, True])
def test_whole_room_exclusion_applies_to_both_doors(excluded_back):
    from mtg_analyzer.game import rooms
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    texts = ['Return it in the next game you play.', '{T}: Draw a card.']
    if excluded_back:
        texts.reverse()
    c = Card(id='room', name='Front // Back', type_line='Enchantment — Room',
             oracle_text=texts[0], layout='split', back_name='Back',
             back_type_line='Enchantment — Room', back_oracle_text=texts[1])
    for door in rooms.DOORS:
        face = rooms.door_card(c, door)
        assert face.unsupported_reason == 'cross_game'
        assert not card_registry.specs_for(face)
    obj = GameObject(c, owner_id='p1', zone=Zone.BATTLEFIELD)
    obj.unlocked_doors = set(rooms.DOORS)
    bind_from_catalogue(obj)
    assert not obj.activated_abilities and not obj.triggered_abilities
