"""PAR-292 M18: a dig whose count is the firing event's quantity ("Whenever this creature deals combat damage to a
player, look at that many cards from the top of your library ...").

Parsed from real oracle wording, then run on a real engine: the number of looked-at cards is the damage dealt (RULE
608.2h), the library below them is untouched (RULE 401.2), and a "that many" with no event amount to read stays
unclaimed rather than reading 0.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle

from tests.support.deck_batch import answer, card, filler, game, stack_library
from tests.test_par157_back_selections import _cached

MANY_CARDS = ["Doomskar Warrior", "Garruk's Harbinger", "Gishath, Sun's Avatar", "Glint Raker", "The Key to the Vault"]


@pytest.mark.parametrize("name", MANY_CARDS)
def test_claimed_cards_are_modeled(name):
    assert parse_oracle(_cached(name)).modeled


def _count_operand(name):
    specs = [e for s in parse_oracle(_cached(name)).specs for e in s.effects if e.type == "inspect_top_choose"]
    assert len(specs) == 1
    return specs[0].params["count"]


@pytest.mark.parametrize("name", MANY_CARDS)
def test_the_count_reads_the_damage_event_not_the_private_sentinel(name):
    assert _count_operand(name) == {"kind": "trigger_event", "field": "amount"}


def _spec_for(text, kind="triggered"):
    from mtg_analyzer.models.cards.card import Card
    return parse_oracle(Card(id="t", name="Probe", type_line="Creature — Test", oracle_text=text,
                             is_creature=True, power=1, toughness=1))


@pytest.mark.parametrize("text", [
    # no event payload names the quantity: a spell has no "that many"
    "Look at that many cards from the top of your library. Put one of them into your hand and the rest into your graveyard.",
    # an attack trigger's quantity is a creature count, not an event payload field this row reads
    "Whenever one or more Birds you control attack, look at that many cards from the top of your library. "
    "Put one of them into your hand and the rest into your graveyard.",
    # a pick the dig grammar does not read
    "Whenever Probe deals combat damage to a player, look at that many cards from the top of your library. "
    "Put one of them into your hand and the rest into the hand of target opponent.",
])
def test_near_misses_stay_unclaimed(text):
    assert not _spec_for(text).modeled


def _hit(eng, source, victim="p2", amount=3):
    eng.state.fire_event(GameEvent(
        EventType.DAMAGE, amount=amount, is_player=True, combat=True, target_id=victim,
        source_id=source.instance_id, source_controller_id=source.controller_id,
    ))
    eng.resolve_until_stable()


def _offered(eng):
    return [o["label"] for o in eng.state.pending_choice["options"] if "instance_id" in o]


def _library_top_down(player):
    return [o.name for o in reversed(player.library)]


def _stocked(*names):
    # every card is a 2/2 so a creature put onto the battlefield survives state-based actions (RULE 704.5f)
    eng = game()
    p1 = eng.state.player_by_id("p1")
    stack_library(eng, "p1", *[filler(eng, n, zone=Zone.LIBRARY, type_line=t, **({'power': 2, 'toughness': 2} if 'Creature' in t else {})) for n, t in names])
    return eng, p1


def test_doomskar_warrior_looks_at_as_many_cards_as_damage_dealt():
    eng, p1 = _stocked(("Deep", "Creature"), ("Bear", "Creature"), ("Plains Card", "Land"), ("Spell", "Sorcery"),
                       ("Grizzly", "Creature"))
    warrior = card(eng, "Doomskar Warrior")
    # top of the library is the last stocked: Grizzly, Spell, Plains Card, Bear, Deep
    _hit(eng, warrior, amount=3)
    # only the three looked-at cards can be offered; the creature or land among them (never Bear below them)
    assert sorted(_offered(eng)) == ["Grizzly", "Plains Card"]
    eng.resolve_pending_choice(str(next(o["id"] for o in eng.state.pending_choice["options"]
                                        if o.get("label") == "Grizzly")))
    eng.resolve_until_stable()
    assert [o.name for o in p1.hand] == ["Grizzly"]
    top = _library_top_down(p1)
    assert top[:2] == ["Bear", "Deep"] and sorted(top[-2:]) == ["Plains Card", "Spell"]  # rest under the untouched cards


def test_more_damage_looks_deeper():
    eng, p1 = _stocked(("Deep", "Creature"), ("Bear", "Creature"), ("Plains Card", "Land"), ("Spell", "Sorcery"),
                       ("Grizzly", "Creature"))
    _hit(eng, card(eng, "Doomskar Warrior"), amount=5)
    assert sorted(_offered(eng)) == ["Bear", "Deep", "Grizzly", "Plains Card"]


def test_gishath_puts_any_number_of_dinosaurs_among_that_many_onto_the_battlefield():
    eng, p1 = _stocked(("Far Raptor", "Creature — Dinosaur"), ("Bear", "Creature — Bear"),
                       ("Raptor B", "Creature — Dinosaur"), ("Raptor A", "Creature — Dinosaur"))
    gishath = card(eng, "Gishath, Sun's Avatar")
    _hit(eng, gishath, amount=3)
    assert sorted(_offered(eng)) == ["Raptor A", "Raptor B"]  # Bear is not a Dinosaur; Far Raptor is beyond 3 cards
    for name in ("Raptor A", "Raptor B"):
        option = next(o for o in eng.state.pending_choice["options"] if o.get("label") == name)
        eng.rules.resolve_choice(option["instance_id"])
        eng.resolve_until_stable()
    names = {o.name for o in eng.state.battlefield if o.controller_id == "p1"}
    assert {"Raptor A", "Raptor B"} <= names and "Far Raptor" not in names
    # the unlooked card is still in the library, in place; the unpicked looked-at Bear went under it (RULE 401.4)
    top = _library_top_down(p1)
    assert top[0] == "Far Raptor" and top[-1] == "Bear"


def _glint(*, accept):
    eng, p1 = _stocked(("Deep", "Creature"), ("Dud", "Creature"), ("Gem", "Artifact"))
    _hit(eng, card(eng, "Glint Raker"), amount=2)
    assert eng.state.pending_choice["kind"] == "trigger_target"  # the printed "you may"
    eng.resolve_pending_choice("do" if accept else "decline")
    eng.resolve_until_stable()
    return eng, p1


def test_glint_raker_reveals_that_many_and_sends_the_rest_to_the_graveyard():
    eng, p1 = _glint(accept=True)
    answer(eng)
    assert [o.name for o in p1.hand] == ["Gem"]
    assert [o.name for o in p1.graveyard] == ["Dud"]  # the second revealed card; Deep (third) is untouched
    assert _library_top_down(p1)[0] == "Deep"


def test_glint_raker_declined_reveals_nothing():
    eng, p1 = _glint(accept=False)
    assert p1.hand == [] and p1.graveyard == [] and _library_top_down(p1)[:3] == ["Gem", "Dud", "Deep"]


def test_a_hit_on_a_creature_does_not_dig():
    eng, p1 = _stocked(("Gem", "Artifact"), ("Dud", "Creature"))
    raker = card(eng, "Glint Raker")
    eng.state.fire_event(GameEvent(EventType.DAMAGE, amount=2, is_player=False, combat=True, target_id="x",
                                   source_id=raker.instance_id, source_controller_id="p1"))
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None and p1.hand == [] and not p1.graveyard
