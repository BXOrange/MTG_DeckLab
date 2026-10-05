"""MEC-103 — "sacrifice up to N / any number of `<type>`. When you sacrifice one
or more this way, `<payoff>` [that many]." (RULE 701.21, 603.12.)

`SacrificeChosenThenEffect` picks through the ordinary `choose_objects`
chooser; the count actually sacrificed is bound into the reflexive trigger's
"x" sentinel (`RulesEngine._apply_choose_objects_tail`).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def engine():
    filler = _card("Lightning Bolt")
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler] * 20), ("p2", "Bob", [filler] * 20)], starting_hand=0,
    )
    return eng, eng.state.player_by_id("p1"), eng.state.player_by_id("p2")


def on_battlefield(eng, name, controller="p1"):
    obj = GameObject(_card(name), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def advance_to_main(eng):
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    eng.recompute_continuous_effects()


def pick(eng, *objs):
    for obj in objs:
        eng.resolve_pending_choice(str(obj.instance_id))


def cast_rotbelly(eng, p1):
    rotbelly = GameObject(_card("Ravenous Rotbelly"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(rotbelly)
    p1.hand.append(rotbelly)
    advance_to_main(eng)
    p1.mana_pool.add("B", 1)
    p1.mana_pool.add("C", 4)
    eng.cast_spell(p1, rotbelly, targets=[])
    eng.resolve_until_stable()
    # "you may" — the ETB trigger's own do/decline gate.
    if eng.state.pending_choice and eng.state.pending_choice["kind"] == "trigger_target":
        eng.resolve_pending_choice("do")


def test_rotbelly_opponent_sacrifices_as_many_as_you_sacrificed():
    eng, p1, p2 = engine()
    z1 = on_battlefield(eng, "Walking Corpse")
    z2 = on_battlefield(eng, "Diregraf Ghoul")
    bears = [on_battlefield(eng, "Grizzly Bears", "p2") for _ in range(3)]
    cast_rotbelly(eng, p1)
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_objects" and choice["action"] == "sacrifice"
    assert choice["count"] == 3  # Rotbelly itself is a Zombie on the battlefield too
    pick(eng, z1, z2)
    eng.resolve_pending_choice("decline")  # "up to": stop at two
    eng.resolve_until_stable()
    # The reflexive trigger asks the opponent for exactly two creatures.
    choice = eng.state.pending_choice
    assert choice is not None and choice["player_id"] == "p2" and choice["count"] == 2
    pick(eng, bears[0], bears[1])
    assert z1 not in eng.state.battlefield and z2 not in eng.state.battlefield
    assert [b in eng.state.battlefield for b in bears] == [False, False, True]


def test_rotbelly_declining_everything_does_nothing():
    eng, p1, p2 = engine()
    bear = on_battlefield(eng, "Grizzly Bears", "p2")
    on_battlefield(eng, "Walking Corpse")
    cast_rotbelly(eng, p1)
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert bear in eng.state.battlefield


def test_rotbelly_only_offers_zombies():
    eng, p1, _p2 = engine()
    bear = on_battlefield(eng, "Grizzly Bears")
    zombie = on_battlefield(eng, "Walking Corpse")
    cast_rotbelly(eng, p1)
    offered = {o.get("instance_id") for o in eng.state.pending_choice["options"]}
    assert zombie.instance_id in offered and bear.instance_id not in offered


def test_nyssa_taps_and_draws_that_many():
    eng, p1, p2 = engine()
    nyssa = on_battlefield(eng, "Nyssa of Traken")
    a1 = on_battlefield(eng, "Sol Ring")
    a2 = on_battlefield(eng, "Mind Stone")
    a3 = on_battlefield(eng, "Sol Ring")
    bears = [on_battlefield(eng, "Grizzly Bears", "p2") for _ in range(3)]
    advance_to_main(eng)
    eng.state.current_step = "declare_attackers"
    hand_before = len(p1.hand)
    eng.declare_attackers(p1, [nyssa])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_objects" and choice["count"] == 3
    pick(eng, a1, a2)
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    # "tap up to that many target creatures" — the reflexive trigger asks for targets.
    for _ in range(4):
        choice = eng.state.pending_choice
        if choice is None:
            break
        opts = [o for o in choice["options"] if o["id"] != "decline"]
        eng.resolve_pending_choice(opts[0]["id"])
        eng.resolve_until_stable()
    assert a1 not in eng.state.battlefield and a2 not in eng.state.battlefield
    assert a3 in eng.state.battlefield
    assert len(p1.hand) == hand_before + 2
    assert sum(1 for b in bears if b.tapped) <= 2


def test_radiant_lotus_adds_three_mana_per_artifact_sacrificed():
    eng, p1, _p2 = engine()
    lotus = on_battlefield(eng, "Radiant Lotus")
    a1 = on_battlefield(eng, "Sol Ring")
    a2 = on_battlefield(eng, "Mind Stone")
    advance_to_main(eng)
    eng.activate_ability(p1, lotus, 0, targets=[p1], x=2, tap_choices=[a1.instance_id, a2.instance_id])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "add_mana_any_color" and choice["amount"] == 6
    eng.resolve_pending_choice("G")
    assert p1.mana_pool.total() == 6
    assert a1 not in eng.state.battlefield and a2 not in eng.state.battlefield
