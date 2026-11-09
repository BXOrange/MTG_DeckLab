"""PAR-251: "creature or Vehicle card" graveyard filter -- parse and execute (RULE 301.7: a Vehicle card is an
artifact card, never a creature card, so the target must accept both words)."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.support.game import creature
from tests.test_par210_object_phrases import cast
from tests.test_par210_player_references import board, game

KIND = 'graveyard_creature_or_vehicle'
BACK_ON_TRACK = ('Return target creature or Vehicle card from your graveyard to the battlefield. Create a 1/1 '
                 'colorless Pilot creature token with "This token saddles Mounts and crews Vehicles as though '
                 'its power were 2 greater."')
OKIBA = ('Return target creature or Vehicle card from your graveyard to the battlefield. Then put two +1/+1 '
         'counters on that permanent if you control an artifact and an enchantment.')
IMPERIAL = ('Whenever this creature attacks, return target creature or Vehicle card with mana value 2 or less '
            'from your graveyard to your hand.')
BROODHEART = ('{2}{B}{G}, {T}, Sacrifice this artifact: Return target creature or Vehicle card from your graveyard '
              'to the battlefield. Activate only as a sorcery.')
FIRE_NATION = ('Whenever one or more creatures you control with counters on them deal combat damage to a player, '
               'put target creature or Vehicle card from that player\'s graveyard onto the battlefield under your '
               'control.')


def _gy(eng, card, pid='p1'):
    obj = GameObject(card, owner_id=pid, zone=Zone.GRAVEYARD)
    eng.state.player_by_id(pid).graveyard.append(obj)
    return obj


def _vehicle(name='Rig', cost=3):
    return Card(id=name, name=name, type_line='Artifact — Vehicle', vehicle_power=3, vehicle_toughness=3,
                oracle_text='Crew 1', mana_cost_string='{%d}' % cost, converted_mana_cost=cost)


def _gadget():
    return Card(id='gadget', name='Gadget', type_line='Artifact', mana_cost_string='{1}')


@pytest.mark.parametrize('name,text', [
    ('Back on Track', BACK_ON_TRACK), ('Okiba Salvage', OKIBA), ('Imperial Recovery Unit', IMPERIAL),
    ('Broodheart Engine', BROODHEART), ('Fire Nation Salvagers', FIRE_NATION),
])
def test_clause_is_modeled(name, text):
    card = Card(id=name, name=name, type_line='Sorcery', is_sorcery=True, oracle_text=text)
    result = parse_oracle(card)
    assert not result.unclaimed, result.unclaimed


def test_target_accepts_creature_and_vehicle_cards_but_not_other_artifacts():
    eng = game()
    bear = _gy(eng, creature('Bear'))
    rig = _gy(eng, _vehicle())
    gadget = _gy(eng, _gadget())
    found = {o['instance_id'] for o in legal_targets(eng.state, 'p1', TargetSpec(kind=KIND))}
    assert found == {bear.instance_id, rig.instance_id}
    assert gadget.instance_id not in found


def test_vehicle_card_returns_to_the_battlefield_and_token_is_a_pilot():
    eng = game()
    rig = _gy(eng, _vehicle())
    cast(eng, BACK_ON_TRACK, [rig])
    assert rig in eng.state.battlefield
    assert any(o.is_token and o.has_subtype('pilot') for o in eng.state.battlefield)


def test_creature_card_returns_to_the_battlefield():
    eng = game()
    bear = _gy(eng, creature('Bear'))
    cast(eng, 'Return target creature or Vehicle card from your graveyard to the battlefield.', [bear])
    assert bear in eng.state.battlefield


@pytest.mark.parametrize('vehicle,artifact,enchantment,counters', [
    (False, True, True, 2), (False, True, False, 0), (False, False, True, 0), (False, False, False, 0),
    # The returned Vehicle is itself an artifact you control when the rider checks (RULE 608.2c, 301.7).
    (True, False, True, 2), (True, False, False, 0),
])
def test_okiba_counters_need_artifact_and_enchantment(vehicle, artifact, enchantment, counters):
    eng = game()
    target = _gy(eng, _vehicle() if vehicle else creature('Bear'))
    if artifact:
        board(eng, _gadget())
    if enchantment:
        board(eng, Card(id='ench', name='Ench', type_line='Enchantment'))
    cast(eng, OKIBA, [target])
    assert target in eng.state.battlefield
    assert target.counters.get('+1/+1', 0) == counters


@pytest.mark.parametrize('cost,returned', [(2, True), (3, False)])
def test_mana_value_cap_for_imperial_recovery_unit(cost, returned):
    eng = game()
    rig = _gy(eng, _vehicle(cost=cost))
    gy_text = ('Return target creature or Vehicle card with mana value 2 or less from your graveyard to your hand.')
    try:
        cast(eng, gy_text, [rig])
    except Exception:
        assert not returned
    hand = eng.state.player_by_id('p1').hand
    assert (rig in hand) == returned


def test_non_vehicle_artifact_is_not_returned():
    eng = game()
    gadget = _gy(eng, _gadget())
    try:
        cast(eng, 'Return target creature or Vehicle card from your graveyard to the battlefield.', [gadget])
    except Exception:
        pass
    assert gadget not in eng.state.battlefield


def test_that_players_graveyard_scope_for_fire_nation_salvagers():
    eng = game()
    rig = _gy(eng, _vehicle(), 'p2')
    kind = 'that_player_graveyard_creature_or_vehicle'
    spec = TargetSpec(kind=kind, scoped_player_id='p2')
    assert {o['instance_id'] for o in legal_targets(eng.state, 'p1', spec)} == {rig.instance_id}
