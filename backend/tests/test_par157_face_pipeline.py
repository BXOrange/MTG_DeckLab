"""A returned face uses the ordinary parser and binder, including fail-closed text."""
import pytest

from mtg_analyzer.game.card_registry import is_registered, specs_for
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from test_mec106_gift import _engine, _bf


def _card(body):
    return Card(id='face-pipeline', name='Pipeline Front', type_line='Creature — Human',
                is_creature=True, power=2, toughness=3, layout='transform',
                oracle_text=(body + '\n{1}: Exile Pipeline Front, then return it to the '
                             "battlefield transformed under its owner's control."),
                back_name='Pipeline Back', back_type_line='Creature — Spirit',
                back_power=4, back_toughness=5, back_oracle_text=body)


@pytest.mark.parametrize('body,field,delta', [
    ('{1}: You gain 2 life.', 'life', 2),
    ('{1}: Draw a card.', 'hand', 1),
])
def test_same_ordinary_body_binds_and_executes_on_either_face_and_after_front_return(body, field, delta):
    eng = _engine()
    card = _card(body)
    back = card.back_face()
    assert not is_registered(card.name) and not is_registered(back.name)
    assert parse_oracle(card).modeled and parse_oracle(back).modeled
    front_effects = specs_for(card)[0].effects
    assert [s.to_dict() for s in front_effects] == [s.to_dict() for s in specs_for(back)[0].effects]
    source = _bf(eng, card)
    player = eng.state.player_by_id('p1')

    def value():
        return player.life if field == 'life' else len(player.hand)

    start = value()
    player.mana_pool.add('C', 4)
    eng.activate_ability(player, source, 0)
    eng.resolve_until_stable()
    assert value() == start + delta
    visit = source.zone_incarnation
    eng.activate_ability(player, source, 1)
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and source.zone_incarnation > visit
    assert source.transformed and source.name == back.name
    assert (source.power, source.toughness) == (4, 5)
    assert len(source.activated_abilities) == 1
    eng.activate_ability(player, source, 0)
    eng.resolve_until_stable()
    assert value() == start + 2 * delta
    eng.rules.blink(source)
    eng.resolve_until_stable()
    assert not source.transformed and source.name == card.name
    assert (source.power, source.toughness) == (2, 3)
    assert len(source.activated_abilities) == 2
    eng.activate_ability(player, source, 0)
    eng.resolve_until_stable()
    assert value() == start + 3 * delta


def test_unknown_back_action_does_not_prevent_transformed_entry_or_keep_front_abilities():
    eng = _engine()
    card = _card('{1}: You gain 2 life.')
    card.back_oracle_text = '{1}: Perform an unsupported action.'
    assert parse_oracle(card).modeled
    assert not parse_oracle(card.back_face()).modeled
    assert specs_for(card.back_face()) == []
    source = _bf(eng, card)
    player = eng.state.player_by_id('p1')
    player.mana_pool.add('C', 1)
    eng.activate_ability(player, source, 1)
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and source.transformed
    assert source.name == card.back_name and source.power == 4
    assert not source.activated_abilities
    assert player.life == 20
    eng.rules.blink(source)
    eng.resolve_until_stable()
    assert not source.transformed and len(source.activated_abilities) == 2
