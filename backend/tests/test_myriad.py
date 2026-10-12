"""Myriad (RULE 702.116a): "Whenever this creature attacks, for each opponent other than defending player, you
may create a token that's a copy of this creature that's tapped and attacking that player or a planeswalker they
control. Exile the tokens at end of combat." (MEC-114)

Built per declaration (`RulesEngine._check_myriad`, like Dethrone) so a granted instance is seen; the body is a
`for_each` over the other opponents around an `optional` copy + delayed exile.
"""

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def land():
    return Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)


def myriad_card(name="Myriad Bear"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2,
                keywords=["Myriad"])


def plain_card(name="Plain Bear"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2)


def walker(name="Test Walker"):
    return Card(id=name, name=name, type_line="Legendary Planeswalker — Test", loyalty=5)


def make_engine(*ids):
    eng = GameEngine.new_game([(i, i, [land()]) for i in ids], starting_life=20, starting_hand=0)
    eng.start()
    return eng


def put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def advance_to(eng, step):
    for _ in range(50):
        if eng.state.current_step == step:
            return
        eng.advance_step()
    raise AssertionError(f"never reached {step}")


def settle(eng, answers):
    """Drive pending choices to completion; ``answers`` maps a choice kind to ``f(choice) -> answer``."""
    for _ in range(30):
        eng.resolve_until_stable()
        choice = eng.state.pending_choice
        if not choice:
            return
        eng.rules.resolve_choice(answers[choice["kind"]](choice))
    raise AssertionError("choices did not settle")


YES = {"composite_optional": lambda c: "yes", "reselect_attack": lambda c: "decline"}


def tokens(eng, name="Myriad Bear"):
    return [o for o in eng.state.battlefield if o.name == name and o.is_token]


def declare(eng, attacker):
    advance_to(eng, "declare_attackers")
    eng.declare_attackers(eng.state.active_player, [{"attacker": attacker, "defender": {"kind": "player", "id": "p2"}}])
    return "p2"


def test_copies_attack_each_other_opponent_and_are_exiled_at_end_of_combat():
    eng = make_engine("p1", "p2", "p3", "p4")
    attacker = put(eng, myriad_card())
    defending = declare(eng, attacker)
    settle(eng, YES)
    made = tokens(eng)
    assert {c.combat_defender["id"] for c in made} == {"p2", "p3", "p4"} - {defending}
    assert all(c.tapped and c.attacking for c in made)
    # RULE 508.3a: never declared, so no "attacked" bookkeeping / attack trigger for the tokens
    assert all(not c.attacked_this_turn for c in made)
    advance_to(eng, "end_combat")
    eng.advance_step()
    eng.resolve_until_stable()
    assert tokens(eng) == []
    assert attacker in eng.state.battlefield


def test_each_copy_is_optional_per_opponent():
    eng = make_engine("p1", "p2", "p3", "p4")
    attacker = put(eng, myriad_card())
    defending = declare(eng, attacker)
    first = []

    def pick(choice):
        first.append(choice)
        return "yes" if len(first) == 1 else "decline"

    settle(eng, {"composite_optional": pick, "reselect_attack": lambda c: "decline"})
    assert len(first) == 2  # asked once per non-defending opponent
    assert len(tokens(eng)) == 1


def test_declining_every_copy_creates_nothing():
    eng = make_engine("p1", "p2", "p3")
    attacker = put(eng, myriad_card())
    declare(eng, attacker)
    settle(eng, {"composite_optional": lambda c: "decline"})
    assert tokens(eng) == []


def test_two_player_game_myriad_does_nothing():
    eng = make_engine("p1", "p2")
    attacker = put(eng, myriad_card())
    declare(eng, attacker)
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert tokens(eng) == []


def test_copy_may_attack_a_planeswalker_the_player_controls():
    eng = make_engine("p1", "p2", "p3")
    attacker = put(eng, myriad_card())
    victim_walker = put(eng, walker(), controller="p3")
    declare(eng, attacker)  # defending player is p2, so the copy's player is p3
    seen = []

    def reselect(choice):
        seen.append(choice)
        return f"planeswalker:{victim_walker.instance_id}"

    settle(eng, {"composite_optional": lambda c: "yes", "reselect_attack": reselect})
    assert len(seen) == 1
    (copy,) = tokens(eng)
    assert copy.combat_defender["kind"] == "planeswalker"
    assert copy.combat_defender["instance_id"] == victim_walker.instance_id


def test_token_copy_of_a_myriad_creature_does_not_trigger_itself():
    eng = make_engine("p1", "p2", "p3", "p4")
    attacker = put(eng, myriad_card())
    declare(eng, attacker)
    settle(eng, YES)
    assert len(tokens(eng)) == 2  # not 2 + copies-of-copies


def test_granted_myriad_from_a_static_ability():
    eng = make_engine("p1", "p2", "p3")
    from tests.test_myriad import plain_card as _p  # noqa: F401  (keeps the helper import explicit)
    attacker = put(eng, plain_card())
    lord = put(eng, _named("Legion Loyalty"))
    eng.recompute_continuous_effects()
    declare(eng, attacker)
    settle(eng, YES)
    assert len(tokens(eng, "Plain Bear")) == 1


def test_granted_myriad_from_equipment():
    eng = make_engine("p1", "p2", "p3")
    attacker = put(eng, plain_card())
    blade = put(eng, _named("Blade of Selves"))
    blade.attached_to = attacker.instance_id
    attacker.attachments = getattr(attacker, "attachments", []) or []
    eng.recompute_continuous_effects()
    declare(eng, attacker)
    settle(eng, YES)
    assert len(tokens(eng, "Plain Bear")) == 1


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name} not in the card cache")
    return card


def test_until_end_of_turn_grant_via_temp_keywords():
    """Corporeal Projection / Duke Ulder Ravengard grant myriad as a temporary keyword."""
    eng = make_engine("p1", "p2", "p3")
    attacker = put(eng, plain_card())
    attacker.temp_keywords.add("myriad")
    eng.recompute_continuous_effects()
    declare(eng, attacker)
    settle(eng, YES)
    assert len(tokens(eng, "Plain Bear")) == 1
