"""PAR-29 "Parser-shaped only" residue — RULE 701.10's "exchange control of
X and Y" / "exchange life totals" family, widened from Gilded Drake/Oko's
own two narrow shapes to the three general oracle-text templates real cards
actually print: a mandatory self+target swap (`test_cedh_cube_control_and_
zones.py` already covers Gilded Drake's own *optional* "up to one" form),
two independently-typed explicit targets, and "N target `<same kind>`[
controlled by different players]" off one multi-count `TargetSpec`. Plus
`ExchangeLifeTotalsEffect`'s new self+target mode alongside its original
two-target one.

Parse-level coverage of the new oracle-text rows is in
`test_oracle_pipeline.py`/`parser_probe.py`-verified real cards (Avarice
Totem, Chromeshell Crab, Shifting Borders, Switcheroo, Axis of Mortality —
see docs/implementation-state/Done_Backend.md's PAR-29 entry); this file is
the execute-level half.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import attach_to_object
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec


def _permanent(name, controller, type_line="Artifact", **kw):
    card = Card(id=name, name=name, type_line=type_line,
                is_creature="Creature" in type_line, **kw)
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    return obj


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return engine, state, p1, p2


def _spell(name, effects, target=None):
    card = Card(id=name, name=name, type_line="Sorcery", is_sorcery=True)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, [AbilitySpec(
        ability_kind="spell_effect", effects=effects, target=target, raw_text=name,
    )])
    return obj


# --- exchange_control: self + one mandatory target (Avarice Totem-shaped) --


def test_self_target_mode_swaps_and_requires_a_real_target():
    engine, state, p1, p2 = _rules()
    mine = _permanent("MyArtifact", "p1")
    theirs = _permanent("TheirArtifact", "p2")
    state.add_to_battlefield(mine)
    state.add_to_battlefield(theirs)

    from mtg_analyzer.game.effects import ExchangeControlEffect

    ctx = GameContext(state, engine.rules)
    ExchangeControlEffect(target_kind="nonland_permanent", source=mine).apply(ctx, targets=[theirs])

    assert mine.controller_id == "p2"
    assert theirs.controller_id == "p1"


def test_self_target_mode_is_mandatory_unlike_gilded_drakes_up_to_one():
    # Avarice Totem prints no "up to one" — a real target is required to
    # even activate, unlike Gilded Drake's `optional=True`.
    from mtg_analyzer.game.effects import ExchangeControlEffect

    spec = ExchangeControlEffect(target_kind="nonland_permanent").target_spec
    assert spec.optional is False


# --- exchange_control: two independently-typed explicit targets -----------


def test_two_explicit_targets_mode_swaps_regardless_of_kind_symmetry():
    # Chromeshell Crab: "target creature you control and target creature an
    # opponent controls" — both picked independently, neither is the
    # ability's own source.
    engine, state, p1, p2 = _rules()
    mine = _permanent("MyBear", "p1", type_line="Creature", power=2, toughness=2)
    theirs = _permanent("TheirBear", "p2", type_line="Creature", power=3, toughness=3)
    state.add_to_battlefield(mine)
    state.add_to_battlefield(theirs)

    from mtg_analyzer.game.effects import ExchangeControlEffect

    ctx = GameContext(state, engine.rules)
    effect = ExchangeControlEffect(
        first_target_kind="creature_you_control", target_kind="creature_you_dont_control",
    )
    effect.apply(ctx, targets=[mine, theirs])

    assert mine.controller_id == "p2"
    assert theirs.controller_id == "p1"


# --- exchange_control: "N target <kind>" off one multi-count TargetSpec ---


def test_multi_count_mode_swaps_two_same_kind_targets():
    # Shifting Borders: "exchange control of 2 target lands." — no self
    # involved, both targets drawn from one TargetSpec(count=2).
    engine, state, p1, p2 = _rules()
    a = _permanent("LandA", "p1", type_line="Land")
    b = _permanent("LandB", "p2", type_line="Land")
    state.add_to_battlefield(a)
    state.add_to_battlefield(b)

    from mtg_analyzer.game.effects import ExchangeControlEffect

    ctx = GameContext(state, engine.rules)
    effect = ExchangeControlEffect(target_kind="land", count=2)
    assert effect.target_spec.count == 2
    effect.apply(ctx, targets=[a, b])

    assert a.controller_id == "p2"
    assert b.controller_id == "p1"


def test_multi_count_mode_no_ops_if_both_targets_end_up_same_controller():
    # RULE 701.10c's own "if the permanents don't have different
    # controllers, no exchange happens" — the resolve-time safety net that
    # stands in for `distinct_controllers` not being enforceable across two
    # independent explicit-kind specs (only across rounds of one spec).
    engine, state, p1, _ = _rules()
    a = _permanent("LandA", "p1", type_line="Land")
    b = _permanent("LandB", "p1", type_line="Land")
    state.add_to_battlefield(a)
    state.add_to_battlefield(b)

    from mtg_analyzer.game.effects import ExchangeControlEffect

    ctx = GameContext(state, engine.rules)
    ExchangeControlEffect(target_kind="land", count=2).apply(ctx, targets=[a, b])

    assert a.controller_id == "p1"
    assert b.controller_id == "p1"


def test_end_to_end_real_card_shape_via_the_binder():
    # Switcheroo: "Exchange control of two target creatures."
    engine, state, p1, p2 = _rules()
    mine = _permanent("MyBear", "p1", type_line="Creature", power=2, toughness=2)
    theirs = _permanent("TheirBear", "p2", type_line="Creature", power=2, toughness=2)
    state.add_to_battlefield(mine)
    state.add_to_battlefield(theirs)

    spell = _spell(
        "Switcheroo",
        [EffectSpec("exchange_control", {"target_kind": "creature", "count": 2})],
        target={"kind": "creature", "count": 2},
    )
    p1.hand.append(spell)
    engine.cast_spell(p1, spell, targets=[mine, theirs])
    engine.rules.resolve_top_of_stack()

    assert mine.controller_id == "p2"
    assert theirs.controller_id == "p1"


# --- exchange_life_totals: self + one target (Magus of the Mirror-shaped) -


def test_life_totals_self_target_mode_swaps_life():
    engine, state, p1, p2 = _rules()
    p1.life, p2.life = 20, 12
    source = _permanent("Magus", "p1", type_line="Creature")
    state.add_to_battlefield(source)

    from mtg_analyzer.game.effects import ExchangeLifeTotalsEffect

    ctx = GameContext(state, engine.rules)
    ExchangeLifeTotalsEffect(source=source, target_kind="player").apply(ctx, targets=[p2])

    assert p1.life == 12
    assert p2.life == 20


def test_life_totals_two_target_mode_still_works():
    # Soul Conduit's own original shape, unaffected by the new mode.
    engine, state, p1, p2 = _rules()
    p1.life, p2.life = 20, 7

    from mtg_analyzer.game.effects import ExchangeLifeTotalsEffect

    ctx = GameContext(state, engine.rules)
    ExchangeLifeTotalsEffect().apply(ctx, targets=[p1, p2])

    assert p1.life == 7
    assert p2.life == 20
