"""Entry-copy prerequisites for The Cosplayzer's name exception.

Use Clone's entry shell until the complete Cosplayzer factory is registered.
"""
from mtg_analyzer.game.effects.counters_tokens import EnterAsCopyReplacement
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.deck_batch import card, cast, game


def entering_copy(engine, target, answer=None):
    source = card(engine, 'Clone', zone=Zone.HAND)
    source.enter_as_copy_effects = [EnterAsCopyReplacement(
        target_kind='creature', name_first_letter='Z',
    )]
    cast(engine, source)
    assert engine.state.pending_choice is not None
    engine.resolve_pending_choice(answer or str(target.instance_id))
    engine.resolve_until_stable()
    return source


def test_entry_replaces_first_letter_and_leaves_original_unchanged():
    engine = game(); target = card(engine, 'Grizzly Bears', player='p2')
    source = entering_copy(engine, target)
    assert source.name == 'Zrizzly Bears' and source.power == 2
    assert target.name == 'Grizzly Bears'


def test_declining_copy_does_not_rename_and_zero_toughness_dies():
    engine = game(); target = card(engine, 'Grizzly Bears')
    source = entering_copy(engine, target, 'decline')
    assert source.name == 'Clone' and source.zone == Zone.GRAVEYARD


def test_further_copy_keeps_renamed_name_and_authored_abilities():
    engine = game(); target = card(engine, 'Curie, Emergent Intelligence', player='p2')
    source = entering_copy(engine, target)
    token = engine.rules.copy_permanent(controller_id='p1', source=source, not_legendary=True)[0]
    assert token.name == 'Zurie, Emergent Intelligence'
    assert len(token.activated_abilities) == len(target.activated_abilities) == 1
    assert len(token.triggered_abilities) == len(target.triggered_abilities) == 1
    player = engine.state.players[0]
    before = len(player.hand)
    engine.rules.deal_damage(engine.state.players[1], 1, source=token, combat=True)
    engine.resolve_until_stable()
    assert len(player.hand) == before + 1


def test_serialized_renamed_copy_rebinds_original_authored_abilities():
    engine = game(); target = card(engine, 'Curie, Emergent Intelligence', player='p2')
    source = entering_copy(engine, target)
    restored = GameObject(Card.from_dict(source.card.to_dict()), owner_id='p1')
    bind_from_catalogue(restored)
    assert restored.name == 'Zurie, Emergent Intelligence'
    assert len(restored.activated_abilities) == len(source.activated_abilities) == 1
    assert len(restored.triggered_abilities) == len(source.triggered_abilities) == 1


def test_further_copy_retains_usable_mana_ability():
    engine = game(); target = card(engine, 'Llanowar Elves', player='p2')
    source = entering_copy(engine, target)
    token = engine.rules.copy_permanent(controller_id='p1', source=source)[0]
    token.summoning_sick = False
    player = engine.state.players[0]
    player.mana_pool.empty()
    engine.tap_for_mana(player, token)
    assert token.name == 'Zlanowar Elves' and player.mana_pool.total() == 1
