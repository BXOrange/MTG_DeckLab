"""PAR-242 -- `enter as a copy of ..., except it has "<ability>"` (RULE 707.9a).

The quoted ability joins the copy's copiable values: it is parsed through the ordinary ability grammar, bound on top of
the copied abilities, and carried to any later copy of the copy (RULE 707.9).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.parser.oracle import parse_oracle

from tests.support.game import creature, make_engine, obj_on_battlefield
from tests.test_enter_as_copy_family import _cast, _named, _prepare


@pytest.mark.parametrize("name", ["Copycrook", "Evil Twin", "Mercurial Pretender"])
def test_claimed_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


@pytest.mark.parametrize(
    "name",
    [
        "Gigantoplasm",  # "{x}: ~ has base power and toughness x/x." is not modelled
        "Progenitor Mimic",  # "if ~ isn't a token, create a token that's a copy of ~" is not modelled
        "Mocking Doppelganger",  # "other creatures with the same name as ~ are goaded" is not modelled
        "Callidus Assassin",  # "destroy up to one other target creature with the same name as ~" is not modelled
    ],
)
def test_unmodelled_bodies_stay_unmodeled(name):
    assert parse_oracle(_named(name)).modeled is False


def _enter_as(name, victim_name="Grizzly Bears"):
    eng, p1, clone = _prepare(name, mana={"U": 4, "B": 4, "C": 6})
    original = obj_on_battlefield(eng.state, eng, creature(name=victim_name, cost="{1}{G}"))
    bind_from_catalogue(original)
    _cast(eng, p1, clone)
    opt = next(o for o in eng.state.pending_choice["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])
    return eng, p1, clone, original


def _board_creature(eng, name):
    owner = eng.state.players[0].id  # the bench engine is single-player; "target creature" has no controller limit
    obj = obj_on_battlefield(eng.state, eng, creature(name=name, cost="{1}{G}"), controller=owner)
    bind_from_catalogue(obj)
    return obj


def test_evil_twin_destroys_a_creature_sharing_the_copied_name():
    eng, p1, twin, _original = _enter_as("Evil Twin")
    assert twin.card.name == "Grizzly Bears"
    twin.summoning_sick = False
    same_name = _board_creature(eng, "Grizzly Bears")
    other_name = _board_creature(eng, "Hill Giant")
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"U": 1, "B": 1})
    assert len(twin.activated_abilities) == 1
    eng.activate_ability(p1, twin, 0, targets=[same_name])
    eng.resolve_until_stable()
    assert same_name not in eng.state.battlefield
    assert twin.tapped
    assert other_name in eng.state.battlefield


def test_evil_twin_cannot_target_a_creature_with_another_name():
    eng, p1, twin, _original = _enter_as("Evil Twin")
    twin.summoning_sick = False
    other_name = _board_creature(eng, "Hill Giant")
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"U": 1, "B": 1})
    try:
        eng.activate_ability(p1, twin, 0, targets=[other_name])
        eng.resolve_until_stable()
    except ValueError:
        pass  # RULE 115.4-style illegal target rejected
    assert other_name in eng.state.battlefield  # a creature with another name is never destroyed


def test_a_copy_of_the_clone_carries_the_granted_ability_too():
    # RULE 707.9: the exception is part of the copiable values, so a second clone copying the first has it as well.
    eng, p1, twin, _original = _enter_as("Evil Twin")
    second = _board_creature(eng, "Placeholder")
    from mtg_analyzer.game import copy_mechanics
    copy_mechanics.become_copy(second, twin)
    assert second.card.name == "Grizzly Bears"
    assert len(second.activated_abilities) == 1


def test_copycrook_gains_its_attack_trigger():
    eng, p1, crook, _original = _enter_as("Copycrook")
    assert crook.card.name == "Grizzly Bears"
    assert len(crook.triggered_abilities) == 1


def test_mercurial_pretender_gains_its_bounce_ability():
    eng, p1, clone, _original = _enter_as("Mercurial Pretender")
    assert clone.card.name == "Grizzly Bears"
    clone.summoning_sick = False
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"U": 2, "C": 2})
    assert len(clone.activated_abilities) == 1
    eng.activate_ability(p1, clone, 0)
    eng.resolve_until_stable()
    assert clone not in eng.state.battlefield
    assert clone in p1.hand


def test_declining_the_copy_leaves_the_card_without_the_grant():
    eng, p1, clone = _prepare("Evil Twin", mana={"U": 4, "B": 4, "C": 6})
    _board_creature(eng, "Grizzly Bears")
    _cast(eng, p1, clone)
    eng.resolve_pending_choice("decline")
    assert clone.card.name == "Evil Twin"
    assert clone.card.granted_ability_lines == ()


def test_copycrook_trigger_fires_on_attack_and_connives():
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.game.game_object import GameObject, Zone

    eng, p1, crook, _original = _enter_as("Copycrook")
    for i in range(3):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"Land{i}", type_line="Land"), owner_id=p1.id, zone=Zone.LIBRARY))
    crook.summoning_sick = False
    hand_before = len(p1.hand)
    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(p1, [crook])
    eng.resolve_until_stable()
    pending = eng.state.pending_choice
    if pending is not None:  # connive asks which card to discard
        eng.resolve_pending_choice(pending["options"][0]["id"])
        eng.resolve_until_stable()
    # Draw one, discard one; a discarded land adds no +1/+1 counter.
    assert len(p1.hand) == hand_before
    assert len(p1.graveyard) == 1
