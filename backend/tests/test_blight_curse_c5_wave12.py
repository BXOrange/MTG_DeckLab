"""Blight Curse batch C5 wave 12 — Cathartic Pyre
(hand-authored, `ability_catalogue/entries_017.py`).

Modal instant, "choose one —":
* mode 1 — ``damage`` 3 to ``creature_or_planeswalker`` (ordinary).
* mode 2 — `discard` with ``count_max=2`` + ``then_draw_discarded`` (ENG-37
  B7 retired the fused `discard_up_to_then_draw_that_many` type): an
  ``optional`` capped-at-N interactive discard, then draw exactly the
  number actually discarded (via `DiscardCardsDiscardedDeltaDrawEffect`
  reading the `cards_discarded_this_turn` delta).
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec


CATHARTIC_PYRE = Card(
    id="CPY", name="Cathartic Pyre", type_line="Instant", is_instant=True,
    mana_cost_string="{1}{R}", converted_mana_cost=2,
    oracle_text="Choose one —\n• Cathartic Pyre deals 3 damage to target creature or "
                "planeswalker.\n• Discard up to two cards, then draw that many cards.",
)


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _stock(eng, pid, hand=0, library=0):
    pl = next(p for p in eng.state.players if p.id == pid)
    for i in range(hand):
        pl.hand.append(GameObject(Card(id=f"H{pid}{i}", name=f"H{pid}{i}", type_line="Forest",
                                       is_land=True), owner_id=pid, zone=Zone.HAND))
    for i in range(library):
        pl.library.append(GameObject(Card(id=f"L{pid}{i}", name=f"L{pid}{i}", type_line="Island",
                                          is_land=True), owner_id=pid, zone=Zone.LIBRARY))
    return pl


def _source(eng):
    src = GameObject(CATHARTIC_PYRE, owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_from_catalogue(src)
    return src


def test_cathartic_pyre_authored_modal():
    specs = specs_for(CATHARTIC_PYRE)
    assert len(specs) == 1 and specs[0].modes["choose"] == 1
    opt_types = [e.type for opt in specs[0].modes["options"] for e in opt]
    assert opt_types == ["damage", "discard"]


def test_mode2_discard_two_then_draw_two():
    eng = _engine()
    p1 = _stock(eng, "p1", hand=3, library=5)
    src = _source(eng)
    eng.begin_turn()

    eff = build_effects([EffectSpec("discard", {"count_max": 2, "then_draw_discarded": True})], src)[0]
    eff.apply(GameContext(eng.state, eng.rules), targets=None)

    # pick two of the three (count_max == 2), then the then_specs draw fires
    for _ in range(2):
        pc = eng.state.pending_choice
        assert pc and pc["kind"] == "choose_objects"
        eng.rules.resolve_choice(pc["options"][0]["instance_id"])
    eng.resolve_until_stable()

    assert len(p1.graveyard) == 2
    assert len(p1.hand) == 3          # discarded 2, drew 2
    assert len(p1.library) == 3       # 5 - 2 drawn


def test_mode2_decline_after_one_draws_one():
    eng = _engine()
    p1 = _stock(eng, "p1", hand=3, library=5)
    src = _source(eng)
    eng.begin_turn()

    eff = build_effects([EffectSpec("discard", {"count_max": 2, "then_draw_discarded": True})], src)[0]
    eff.apply(GameContext(eng.state, eng.rules), targets=None)

    pc = eng.state.pending_choice
    eng.rules.resolve_choice(pc["options"][0]["instance_id"])   # discard 1
    eng.rules.resolve_choice(None)                              # decline the rest
    eng.resolve_until_stable()

    assert len(p1.graveyard) == 1
    assert len(p1.hand) == 3          # -1 discard, +1 draw
    assert len(p1.library) == 4       # 5 - 1 drawn


def test_mode2_empty_hand_is_a_noop():
    eng = _engine()
    p1 = _stock(eng, "p1", hand=0, library=5)
    src = _source(eng)
    eng.begin_turn()

    eff = build_effects([EffectSpec("discard", {"count_max": 2, "then_draw_discarded": True})], src)[0]
    eff.apply(GameContext(eng.state, eng.rules), targets=None)

    assert eng.state.pending_choice is None
    assert len(p1.library) == 5 and not p1.hand


def test_the_fused_type_is_retired():
    from mtg_analyzer.game import isa
    from mtg_analyzer.game.effects import EffectRegistry

    assert not EffectRegistry.is_registered("discard_up_to_then_draw_that_many")
    assert "discard_up_to_then_draw_that_many" not in isa.EFFECT_TYPES
    # folded into `discard` params
    eff = build_effects(
        [EffectSpec("discard", {"count_max": 2, "then_draw_discarded": True})], None
    )[0]
    assert eff.count_max == 2 and eff.then_draw_discarded is True


def test_mode1_damage_targets_creature_or_planeswalker():
    eng = _engine()
    src = _source(eng)
    eff = build_effects(
        [EffectSpec("damage", {"amount": 3, "target_kind": "creature_or_planeswalker"})], src
    )[0]
    assert eff.target_spec.kind == "creature_or_planeswalker"
    assert eff.amount == 3
