""""Sacrifice ~ unless you pay `<cost>`." (RULE 701.17 + an "unless" payment)
— the single biggest remaining upkeep-trigger template (Arcades Sabboth,
Breeding Pit, Child of Gaea, Chromium, Kuro; Aura Flux/Coral Net grant it onto
another permanent).

It needed a real **interactive** pay-or-lose-it choice, not just recognition.
Rather than build a second one, this reuses the machinery ward (RULE 702.21)
already had: `RulesEngine._can_pay_player_cost`/`_pay_player_cost` — generalized
out of `resolve_ward_effect` here, since they were never ward-specific — plus
the same `pending_choice` shape. Both are "a rule asks a player for an
arbitrary cost mid-resolution, and something bad happens if they don't", and
`ActivationCost` already covers the whole cost vocabulary these cards print.

The parser deliberately claims a **closed** list of cost shapes rather than
handing free text to `costs.parse_activation_cost`, which returns a *free*
cost for anything it doesn't understand — here that would silently read as
"pay nothing to keep it". Echo/Cumulative Upkeep's self-referential costs,
scaled "for each" costs, "discard a card at random" and multi-permanent
sacrifices all stay unclaimed instead.

Reference: mtg_analyzer/game/{rules_engine,effects}.py,
mtg_analyzer/parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _permanent(name, oracle_text, type_line="Enchantment"):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle_text)


def _creature(name, oracle_text=""):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=2, toughness=2, oracle_text=oracle_text)


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _fire_upkeep(eng):
    from mtg_analyzer.models.events import EventType, GameEvent

    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()


_BREEDING_PIT = "At the beginning of your upkeep, sacrifice this enchantment unless you pay {B}{B}."


# -- parse side ---------------------------------------------------------------


@pytest.mark.parametrize(
    "body,cost",
    [
        ("sacrifice ~ unless you pay {g}{g}", "pay {g}{g}"),
        ("sacrifice ~ unless you pay 1 life", "pay 1 life"),
        ("sacrifice it unless you discard a card", "discard a card"),
        ("sacrifice ~ unless you sacrifice a creature", "sacrifice a creature"),
    ],
)
def test_recognized_cost_shapes(body, cost):
    (spec,) = parse_effect_body(body)
    assert spec.type == "sacrifice_unless_pay"
    assert spec.params == {"cost": cost}


@pytest.mark.parametrize(
    "body",
    [
        # Echo/Cumulative Upkeep's own self-referential reminder costs —
        # neither keyword is modeled at all.
        "sacrifice ~ unless you pay its echo cost",
        "sacrifice ~ unless you pay its upkeep cost for each age counter on it",
        # A *scaled* cost — `parse_activation_cost` would quietly drop the
        # multiplier and read this as a flat {G}.
        "sacrifice ~ unless you pay {g} for each wind counter on it",
        # The engine's `discard` auto-picks and has no random mode.
        "sacrifice it unless you discard a card at random",
        # `ActivationCost.sacrifice` is a single permanent.
        "sacrifice ~ unless you sacrifice 4 creatures",
    ],
)
def test_unmodelable_cost_shapes_stay_unclaimed(body):
    assert parse_effect_body(body) is None


def test_plain_self_sacrifice_is_unaffected():
    # Regression: the new handler sits *before* `sacrifice_self` in the
    # table, so make sure it didn't shadow it.
    (spec,) = parse_effect_body("sacrifice ~")
    assert spec.type == "sacrifice_self"


def test_breeding_pit_is_modeled():
    result = parse_oracle(_permanent("Breeding Pit", _BREEDING_PIT))
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_granted_onto_another_permanent_is_modeled():
    # Coral Net-shaped: the same body inside a quoted Aura grant.
    card = _permanent(
        "Coral Net",
        'Enchant green or white creature\n'
        'Enchanted creature has "At the beginning of your upkeep, sacrifice '
        'this creature unless you discard a card."',
        type_line="Enchantment — Aura",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


# -- engine side --------------------------------------------------------------


def test_paying_keeps_the_permanent_and_spends_the_mana():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    pit = _bf(eng.state, _permanent("Breeding Pit", _BREEDING_PIT))
    p1.mana_pool.add("B", 2)

    _fire_upkeep(eng)
    assert eng.state.pending_choice["kind"] == "sacrifice_unless_pay"
    eng.resolve_pending_choice("pay")

    assert pit in eng.state.battlefield
    assert p1.mana_pool.total() == 0


def test_declining_sacrifices_the_permanent():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    pit = _bf(eng.state, _permanent("Breeding Pit", _BREEDING_PIT))
    p1.mana_pool.add("B", 2)

    _fire_upkeep(eng)
    eng.resolve_pending_choice("decline")

    assert pit not in eng.state.battlefield
    assert pit in p1.graveyard
    assert p1.mana_pool.total() == 2  # declining costs nothing


def test_unaffordable_cost_sacrifices_outright_without_stalling_on_a_choice():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    pit = _bf(eng.state, _permanent("Breeding Pit", _BREEDING_PIT))  # no mana in pool

    _fire_upkeep(eng)
    assert eng.state.pending_choice is None
    assert pit not in eng.state.battlefield
    assert pit in p1.graveyard


def test_life_cost_variant_charges_life():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    obj = _bf(eng.state, _permanent(
        "Life Tax", "At the beginning of your upkeep, sacrifice this enchantment unless you pay 3 life."
    ))

    _fire_upkeep(eng)
    eng.resolve_pending_choice("pay")
    assert obj in eng.state.battlefield
    assert p1.life == 17


def test_paying_is_re_checked_against_the_board_at_answer_time():
    # The offer and the answer are separate round-trips through the session,
    # so a promise to pay that can no longer be honoured must not silently
    # keep the permanent for free.
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    pit = _bf(eng.state, _permanent("Breeding Pit", _BREEDING_PIT))
    p1.mana_pool.add("B", 2)

    _fire_upkeep(eng)
    p1.mana_pool.empty()
    eng.resolve_pending_choice("pay")

    assert pit not in eng.state.battlefield


def test_granted_upkeep_sacrifice_asks_the_hosts_controller():
    from mtg_analyzer.game import continuous

    eng = _engine()
    state = eng.state
    host = _bf(state, _creature("Enchanted Bear"), controller="p2")
    net = _bf(
        state,
        _permanent(
            "Coral Net",
            'Enchant creature\nEnchanted creature has "At the beginning of your '
            'upkeep, sacrifice this creature unless you discard a card."',
            type_line="Enchantment — Aura",
        ),
        controller="p1",
    )
    net.attached_to = host.instance_id
    p2 = state.player_by_id("p2")
    p2.hand.append(GameObject(_creature("Spare Card"), owner_id="p2", zone=Zone.HAND))
    continuous.recompute(state)

    # It's the *enchanted* creature's controller who is asked, on *their*
    # upkeep — the Aura's controller is irrelevant.
    state.active_player_index = 1
    _fire_upkeep(eng)
    choice = state.pending_choice
    assert choice["kind"] == "sacrifice_unless_pay"
    assert choice["player_id"] == "p2"

    eng.resolve_pending_choice("pay")
    assert host in state.battlefield
    assert len(p2.hand) == 0
