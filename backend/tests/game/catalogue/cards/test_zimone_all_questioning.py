"""Zimone, All-Questioning tracks lands and investigates."""

from __future__ import annotations

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.effects.core import _is_prime
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests import turn_history_events as history


def test_is_prime():
    primes = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31}
    for n in range(0, 33):
        assert _is_prime(n) == (n in primes)


def _zimone_card():
    return Card(id="zi", name="Zimone, All-Questioning",
                type_line="Legendary Creature — Human Wizard", is_creature=True,
                power=1, toughness=1,
                oracle_text=("At the beginning of your end step, if a land entered the "
                             "battlefield under your control this turn and you control a "
                             "prime number of lands, create Primo, the Indivisible, a "
                             "legendary 0/0 green and blue Fractal creature token, then "
                             "put that many +1/+1 counters on it."))


def test_registered_and_binds():
    assert is_registered("Zimone, All-Questioning")
    spec = _REGISTRY["zimone, all-questioning"]()[0]
    spec.validate()
    assert spec.effects[0].type == "zimone_all_questioning_end_step"
    src = GameObject(_zimone_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_zimone_card())


def _mk_lands(eng, pid, n):
    for i in range(n):
        o = GameObject(Card(id=f"{pid}land{i}", name=f"{pid}Forest{i}",
                            type_line="Basic Land — Forest", is_land=True),
                       owner_id=pid, zone=Zone.BATTLEFIELD)
        o.controller_id = pid
        eng.state.add_to_battlefield(o)


def test_makes_primo_when_prime_land_count_and_land_entered():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    zim = GameObject(_zimone_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    zim.controller_id = "p1"
    eng.state.add_to_battlefield(zim)
    bind_from_catalogue(zim)
    _mk_lands(eng, "p1", 4)  # after the 5th (added below) -> 5 lands = prime

    # a land "enters" this turn (bumps the tracker)
    land5 = GameObject(Card(id="p1land5", name="p1Forest5",
                            type_line="Basic Land — Forest", is_land=True),
                       owner_id="p1", zone=Zone.LIBRARY)
    land5.controller_id = "p1"
    eng.state.player_by_id("p1").add_to_zone(land5, Zone.LIBRARY)
    eng.state.add_to_battlefield(land5)
    history.entered(eng.state, land5)  # what the engine's entry paths fire

    eng.rules._apply_effect_specs(
        [{"type": "zimone_all_questioning_end_step", "params": {}}], zim,
    )
    eng.resolve_until_stable()
    primos = [o for o in eng.state.battlefield if o.card.name == "Primo, the Indivisible"]
    assert len(primos) == 1
    assert primos[0].counters.get("+1/+1") == 5


def test_no_primo_when_land_count_not_prime():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    zim = GameObject(_zimone_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    zim.controller_id = "p1"
    eng.state.add_to_battlefield(zim)
    bind_from_catalogue(zim)
    _mk_lands(eng, "p1", 3)
    land4 = GameObject(Card(id="p1land4", name="p1Forest4",
                            type_line="Basic Land — Forest", is_land=True),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
    land4.controller_id = "p1"
    eng.state.add_to_battlefield(land4)  # 4 lands -> not prime
    eng.rules._apply_effect_specs(
        [{"type": "zimone_all_questioning_end_step", "params": {}}], zim,
    )
    eng.resolve_until_stable()
    assert not [o for o in eng.state.battlefield if o.card.name == "Primo, the Indivisible"]


def test_no_primo_when_no_land_entered_this_turn():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    zim = GameObject(_zimone_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    zim.controller_id = "p1"
    eng.state.add_to_battlefield(zim)
    bind_from_catalogue(zim)
    _mk_lands(eng, "p1", 5)  # prime, but none "entered" this turn per the tracker
    eng.rules._apply_effect_specs(
        [{"type": "zimone_all_questioning_end_step", "params": {}}], zim,
    )
    eng.resolve_until_stable()
    assert not [o for o in eng.state.battlefield if o.card.name == "Primo, the Indivisible"]
