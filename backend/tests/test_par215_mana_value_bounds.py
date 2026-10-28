"""PAR-215 axis E: mana-value bounds measured at resolution ("mana value equal to the number of charge counters on ~").

Also pins the mass-group fix found on the way: a bound stated on the singular body ("destroy each X with mana value
3") used to be dropped by the group loop, so the card destroyed every member (RULE 115.1: a loop announces no target).
"""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry.core import register
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from tests.support.deck_batch import activate, card, cast, filler, game


def _parse(text):
    return parse_oracle(Card(id="x", name="Probe Card", type_line="Sorcery", oracle_text=text, is_sorcery=True))


def _cast_text(eng, text, name, x=None):
    c = Card(id=name, name=name, type_line="Sorcery", is_sorcery=True, oracle_text=text, converted_mana_cost=0)
    result = parse_oracle(c)
    assert result.modeled, result.unclaimed
    register(name, lambda: result.specs)
    obj = GameObject(c, owner_id="p1", zone=Zone.HAND)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    eng.state.player_by_id("p1").add_to_zone(obj, Zone.HAND)
    cast(eng, obj, **({"x": x} if x is not None else {}))


def _board(eng):
    return (filler(eng, "Two", player="p2", type_line="Artifact", mv=2),
            filler(eng, "Three", player="p2", type_line="Artifact", mv=3),
            filler(eng, "Zero", player="p2", type_line="Creature", mv=0, power=1, toughness=1))


def test_the_group_loop_keeps_the_literal_mana_value_bound():
    eng = game(library=3)
    two, three, zero = _board(eng)
    _cast_text(eng, "Destroy each nonland permanent with mana value 3.", "Literal Wrath")
    assert (two.zone, three.zone, zero.zone) == (Zone.BATTLEFIELD, Zone.GRAVEYARD, Zone.BATTLEFIELD)


def test_the_group_loop_keeps_an_announced_x_bound():
    eng = game(library=3)
    two, three, zero = _board(eng)
    _cast_text(eng, "Destroy all artifacts and creatures with mana value X or less.", "Rivalry Probe", x=2)
    assert (two.zone, three.zone, zero.zone) == (Zone.GRAVEYARD, Zone.BATTLEFIELD, Zone.GRAVEYARD)


def test_the_group_loop_keeps_the_creature_state_filter():
    eng = game(library=3)
    hurt = filler(eng, "Hurt", player="p2", type_line="Creature", power=2, toughness=9)
    healthy = filler(eng, "Healthy", player="p2", type_line="Creature", power=2, toughness=9)
    eng.rules.deal_damage(hurt, 1, filler(eng, "Pinger", player="p1", power=1, toughness=1))
    _cast_text(eng, "Destroy each creature you don't control that was dealt damage this turn.", "Swift Probe")
    assert (hurt.zone, healthy.zone) == (Zone.GRAVEYARD, Zone.BATTLEFIELD)


@pytest.mark.parametrize("text", [
    "Destroy each nonland permanent with mana value equal to the number of charge counters on ~.",
    "Destroy each creature with mana value less than or equal to the number of age counters on ~.",
])
def test_resolution_time_bound_parses_as_a_measured_amount(text):
    result = _parse(text)
    assert result.modeled, result.unclaimed
    bind = next(e for s in result.specs for e in s.to_dict()["effects"] if e["type"] == "bind")
    assert bind["params"]["amount"]["kind"] in ("counters", "count_selector")


def test_a_targeted_bound_is_not_measured_at_resolution():
    # a target bound is fixed while the target is announced (RULE 601.2c): refuse rather than read it later
    assert not _parse("Destroy target creature with mana value equal to the number of charge counters on ~.").modeled


def test_ratchet_bomb_destroys_only_permanents_with_the_charge_count():
    eng = game(library=3)
    bomb = card(eng, "Ratchet Bomb")
    two, three, zero = _board(eng)
    land = filler(eng, "Land2", player="p2", type_line="Land", mv=2)
    bomb.counters["charge"] = 2
    activate(eng, bomb, index=1)
    assert (two.zone, three.zone, zero.zone, land.zone, bomb.zone) == (
        Zone.GRAVEYARD, Zone.BATTLEFIELD, Zone.BATTLEFIELD, Zone.BATTLEFIELD, Zone.GRAVEYARD)


def test_ratchet_bomb_with_no_counters_hits_the_free_permanents():
    eng = game(library=3)
    bomb = card(eng, "Ratchet Bomb")
    two, three, zero = _board(eng)
    activate(eng, bomb, index=1)
    assert (two.zone, zero.zone) == (Zone.BATTLEFIELD, Zone.GRAVEYARD)


def test_target_bound_by_a_count_of_your_own_permanents_parses_as_a_target_restriction():
    result = _parse("Exile target creature with mana value less than or equal to the number of Plains you control.")
    assert result.modeled, result.unclaimed
    effect = result.specs[0].to_dict()["effects"][0]
    assert effect["type"] == "exile"
    assert effect["params"]["max_mana_value"] == {
        "count_selector": {"zone": "battlefield", "of": "you", "filter": {"subtype": "plains"}}}


def test_a_count_taken_as_the_targets_controller_is_a_per_candidate_bound():
    # Drown in the Loch: each candidate answers to its own controller's graveyard (test_par215_candidate_controller_bounds.py)
    result = _parse("Counter target spell with mana value less than or equal to the number of cards in its "
                    "controller's graveyard.")
    assert result.modeled
    params = result.specs[0].to_dict()["effects"][0]["params"]
    assert params["max_mana_value"] == {"candidate_controller_count": {"zone": "graveyard", "of": "you"}}
    # ... but only for the ceiling and the controller's graveyard; other relative counts stay unclaimed
    assert not _parse("Counter target spell with mana value less than or equal to the number of lands its "
                      "controller controls.").modeled


def test_lay_down_arms_only_exiles_creatures_within_the_plains_count():
    eng = game(library=3)
    for i in range(2):
        filler(eng, f"Plains{i}", player="p1", type_line="Basic Land — Plains")
    big = filler(eng, "Big", player="p2", type_line="Creature", mv=3, power=1, toughness=1)
    with pytest.raises(ValueError, match="no legal target"):
        cast(eng, card(eng, "Lay Down Arms", zone=Zone.HAND), targets=[big])  # MV 3 > 2 Plains: not a legal target
    assert big.zone == Zone.BATTLEFIELD
    small = filler(eng, "Small", player="p2", type_line="Creature", mv=2, power=1, toughness=1)
    cast(eng, card(eng, "Lay Down Arms", zone=Zone.HAND), targets=[small])
    assert small.zone == Zone.EXILE
