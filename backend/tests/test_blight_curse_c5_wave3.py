"""Blight Curse batch C5 wave 3 — Painful Truths / Grave Venerations
(hand-authored, `ability_catalogue/entries_017.py`).

* Painful Truths — RULE 702.108a Converge: ``draw`` + ``lose_life`` with
  ``amount_from_count_selector="converge"`` (new `continuous.count_selector`
  entry — ``len(GameObject.colors_spent_to_cast)``).
* Grave Venerations — three clauses; the end-step one carries a
  trigger-level RULE 603.4 intervening-if ``active_if={"kind":
  "is_monarch"}``.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.effect_binder import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


PAINFUL_TRUTHS = Card(
    id="PT", name="Painful Truths", type_line="Sorcery", is_sorcery=True,
    mana_cost_string="{B}{B}{B}", converted_mana_cost=3,
    oracle_text="Converge — You draw X cards and lose X life, where X is the number of "
                "colors of mana spent to cast this spell.",
)
GRAVE_VENERATIONS = Card(
    id="GV", name="Grave Venerations", type_line="Enchantment",
    oracle_text="When this enchantment enters, you become the monarch.\nAt the beginning "
                "of your end step, if you're the monarch, return up to one target creature "
                "card from your graveyard to your hand.\nWhenever a creature you control "
                "dies, each opponent loses 1 life and you gain 1 life.",
)


def test_both_authored():
    assert len(specs_for(PAINFUL_TRUTHS)) == 1
    assert len(specs_for(GRAVE_VENERATIONS)) == 3


def test_painful_truths_converge_draws_and_drains_per_colour_spent():
    eng = _engine()
    p1 = eng.state.players[0]
    for i in range(9):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Plains",
                                          is_land=True), owner_id="p1", zone=Zone.LIBRARY))
    obj = GameObject(PAINFUL_TRUTHS, owner_id="p1", zone=Zone.STACK)
    obj.controller_id = "p1"
    obj.colors_spent_to_cast = frozenset({"B", "G", "R"})
    bind_from_catalogue(obj)

    h0, life0 = len(p1.hand), p1.life
    ctx = GameContext(eng.state, eng.rules)
    for e in build_effects([
        EffectSpec("draw", {"count": 0, "amount_from_count_selector": "converge"}),
        EffectSpec("lose_life", {"amount": 0, "amount_from_count_selector": "converge"}),
    ], obj):
        e.apply(ctx)

    assert len(p1.hand) == h0 + 3
    assert p1.life == life0 - 3


def test_painful_truths_mono_colour_is_x_equals_1():
    eng = _engine()
    p1 = eng.state.players[0]
    p1.library.append(GameObject(Card(id="L", name="L", type_line="Plains", is_land=True),
                                 owner_id="p1", zone=Zone.LIBRARY))
    obj = GameObject(PAINFUL_TRUTHS, owner_id="p1", zone=Zone.STACK)
    obj.controller_id = "p1"
    obj.colors_spent_to_cast = frozenset({"B"})
    bind_from_catalogue(obj)

    ctx = GameContext(eng.state, eng.rules)
    for e in build_effects([
        EffectSpec("draw", {"count": 0, "amount_from_count_selector": "converge"}),
        EffectSpec("lose_life", {"amount": 0, "amount_from_count_selector": "converge"}),
    ], obj):
        e.apply(ctx)
    assert len(p1.hand) == 1 and p1.life == 19


def test_grave_venerations_dies_drain():
    eng = _engine()
    p1, p2 = eng.state.players
    gv = GameObject(GRAVE_VENERATIONS, owner_id="p1", zone=Zone.BATTLEFIELD)
    gv.controller_id = "p1"
    eng.state.add_to_battlefield(gv)
    bind_from_catalogue(gv)
    mine = GameObject(Card(id="M", name="M", type_line="Creature — Rat", is_creature=True,
                           power=1, toughness=1), owner_id="p1", zone=Zone.BATTLEFIELD)
    mine.controller_id = "p1"
    eng.state.add_to_battlefield(mine)
    eng.begin_turn()

    eng.rules.destroy(mine)
    eng.resolve_until_stable()
    assert p1.life == 21 and p2.life == 19


def test_grave_venerations_end_step_return_only_while_monarch():
    eng = _engine()
    p1 = eng.state.players[0]
    gv = GameObject(GRAVE_VENERATIONS, owner_id="p1", zone=Zone.BATTLEFIELD)
    gv.controller_id = "p1"
    eng.state.add_to_battlefield(gv)
    bind_from_catalogue(gv)
    dead = GameObject(Card(id="D", name="Dead", type_line="Creature — Ox", is_creature=True,
                           power=3, toughness=3), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(dead)
    eng.begin_turn()

    # not the monarch → no trigger
    eng.state.monarch_id = None
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1"))
    eng.rules.put_triggers_on_stack()
    assert not eng.state.pending_choice and not eng.state.stack

    # the monarch → the return trigger goes on the stack (targeting the gy card)
    eng.state.monarch_id = "p1"
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1"))
    eng.rules.put_triggers_on_stack()
    pc = eng.state.pending_choice
    assert pc and pc["kind"] == "trigger_target"
