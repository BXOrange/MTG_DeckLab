"""Tests for RULE 701.16 regeneration (Batch 10 of the M1 parser/engine plan):
the `RegenerateEffect` one-shot, `RulesEngine.regenerate`'s shield mechanism
(a `ReplacementEffect` intercepting the new `EventType.DESTROY` event
`RulesEngine.destroy` now fires), and the RULE 701.16c distinction that
regeneration never saves a permanent from sacrifice or 0 toughness.

Mirrors `test_effect_families_wave3.py`'s two-layer pattern: parser
recognition through `parse_effect_body` directly, then an engine-level test
driving the bound effect through a real `RulesEngine`/`GameEngine`.
"""

from mtg_analyzer.game.effects.core import GameContext, RegenerateEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _bear(name="Bear", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = RulesEngine(state)
    return engine, state, p1, p2


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# PARSER RECOGNITION
# ---------------------------------------------------------------------------


def test_regenerate_target_creature_is_recognized():
    specs = parse_effect_body("regenerate target creature")
    assert specs is not None
    (spec,) = specs
    assert spec.type == "regenerate" and spec.params == {"target_kind": "creature"}


def test_regenerate_self_forms_are_recognized():
    for clause in ("regenerate ~", "regenerate it", "regenerate this creature"):
        specs = parse_effect_body(clause)
        assert specs is not None, clause
        (spec,) = specs
        assert spec.type == "regenerate" and spec.params == {"target_kind": None}


def test_regenerate_subtype_filtered_target_is_recognized():
    # Ezuri, Renegade Leader's "Regenerate another target Elf" — a
    # subtype-filtered target, `_regenerate_another_target`'s own row
    # rather than the shared TARGET grammar (which has no subtype slot).
    # "another" needs no explicit exclusion: the plain "creature" target
    # kind already excludes the ability's own source unconditionally.
    (spec,) = parse_effect_body("regenerate another target elf")
    assert spec.type == "regenerate"
    assert spec.params == {
        "target_kind": "creature",
        "creature_filter": {"subtype": "Elf"},
    }


# ---------------------------------------------------------------------------
# ENGINE: the shield mechanism
# ---------------------------------------------------------------------------


def test_regenerate_shield_absorbs_lethal_damage():
    engine, state, p1, p2 = _rules()
    bear = _bf(state, _bear(toughness=2))
    engine.check_state_based_actions()

    engine.regenerate(bear)
    bear.damage_marked = 2  # lethal
    bear.attacking = True
    engine.check_state_based_actions()  # RULE 704.5g would destroy it

    assert bear.zone == Zone.BATTLEFIELD
    assert bear.damage_marked == 0
    assert bear.tapped is True
    assert bear.attacking is False
    assert bear.replacement_effects == []  # shield consumed


def test_regenerate_shield_is_single_use():
    engine, state, p1, p2 = _rules()
    bear = _bf(state, _bear(toughness=2))
    engine.regenerate(bear)

    bear.damage_marked = 2
    engine.check_state_based_actions()
    assert bear.zone == Zone.BATTLEFIELD  # first lethal hit: regenerated

    bear.damage_marked = 2
    engine.check_state_based_actions()
    assert bear.zone == Zone.GRAVEYARD  # no shield left: destroyed for real


def test_regenerate_shield_deathtouch_lethal_also_absorbed():
    engine, state, p1, p2 = _rules()
    bear = _bf(state, _bear(toughness=4))
    engine.regenerate(bear)
    bear.damage_marked = 1
    bear.dealt_deathtouch_damage = True
    engine.check_state_based_actions()

    assert bear.zone == Zone.BATTLEFIELD
    assert bear.damage_marked == 0
    assert bear.dealt_deathtouch_damage is False


def test_destroy_effect_without_shield_still_moves_to_graveyard():
    engine, state, p1, p2 = _rules()
    bear = _bf(state, _bear())
    engine.destroy(bear)
    assert bear.zone == Zone.GRAVEYARD


def test_multiple_activations_stack_independent_shields():
    # Two shields simultaneously applicable to the same DESTROY event is
    # RULE 616.1e ambiguity — same as any other multi-replacement case in
    # this engine (`test_replacement_ordering.py`) — so it opens an
    # interactive choice rather than resolving synchronously.
    engine, state, p1, p2 = _rules()
    bear = _bf(state, _bear(toughness=2))
    engine.regenerate(bear)
    engine.regenerate(bear)
    assert len(bear.replacement_effects) == 2

    bear.damage_marked = 2
    engine.check_state_based_actions()
    assert state.pending_choice is not None
    engine.resolve_replacement_order_choice(0)

    assert bear.zone == Zone.BATTLEFIELD
    assert len(bear.replacement_effects) == 1  # one shield consumed, one left
    engine.check_state_based_actions()  # damage now clear — nothing left to do
    assert bear.zone == Zone.BATTLEFIELD


def test_regeneration_does_not_apply_to_a_different_permanent():
    engine, state, p1, p2 = _rules()
    shielded = _bf(state, _bear("Shielded", toughness=2))
    other = _bf(state, _bear("Other", toughness=2))
    engine.regenerate(shielded)

    other.damage_marked = 2
    engine.check_state_based_actions()
    assert other.zone == Zone.GRAVEYARD  # its own lethal damage, no shield of its own
    assert shielded.zone == Zone.BATTLEFIELD
    assert len(shielded.replacement_effects) == 1  # untouched


# ---------------------------------------------------------------------------
# RULE 701.16c: regeneration never saves from sacrifice / 0 toughness
# ---------------------------------------------------------------------------


def test_regeneration_does_not_prevent_sacrifice():
    engine, state, p1, p2 = _rules()
    bear = _bf(state, _bear())
    engine.regenerate(bear)

    engine.put_into_graveyard(bear)  # RulesEngine.sacrifice's own choke point
    assert bear.zone == Zone.GRAVEYARD
    assert len(bear.replacement_effects) == 1  # shield untouched, just irrelevant


def test_regeneration_does_not_prevent_sacrifice_effect_family():
    engine, state, p1, p2 = _rules()
    bear = _bf(state, _bear())
    engine.regenerate(bear)

    engine.sacrifice(p1, "creature")
    assert bear.zone == Zone.GRAVEYARD


def test_regeneration_does_not_prevent_zero_toughness_sba():
    engine, state, p1, p2 = _rules()
    bear = _bf(state, _bear(toughness=0))  # already 0 toughness, no damage needed
    engine.regenerate(bear)

    engine.check_state_based_actions()  # RULE 704.5f — not destruction
    assert bear.zone == Zone.GRAVEYARD


def test_game_engine_cost_sacrifice_bypasses_regeneration():
    """`GameEngine`'s cost-payment sacrifice path (`_pay_activation_cost`/
    `_pay_additional_cast_cost`) now calls `put_into_graveyard`, not
    `destroy` — verify that choke point directly."""
    engine = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    bear = GameObject(_bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bear.summoning_sick = False
    engine.state.add_to_battlefield(bear)
    engine.rules.regenerate(bear)

    victim = engine._sacrifice_candidate(engine.state.player_by_id("p1"), bear, "self")
    assert victim is bear
    engine.rules.put_into_graveyard(victim)
    assert bear.zone == Zone.GRAVEYARD


# ---------------------------------------------------------------------------
# RULE 514.2/701.16a: an unused shield expires at cleanup
# ---------------------------------------------------------------------------


def test_unused_shield_expires_at_cleanup():
    engine = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    bear = GameObject(_bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bear.summoning_sick = False
    engine.state.add_to_battlefield(bear)
    engine.rules.regenerate(bear)
    assert len(bear.replacement_effects) == 1

    engine._step_cleanup()
    assert bear.replacement_effects == []


def test_cleanup_does_not_sweep_a_cards_own_bind_time_replacement_effect():
    """Only the `regeneration_shield`-tagged kind is swept — a card's
    ordinary (permanent) replacement effect must survive cleanup."""
    from mtg_analyzer.game.effects.core import ReplacementEffect

    engine = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    bear = GameObject(_bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bear.summoning_sick = False
    engine.state.add_to_battlefield(bear)
    permanent_effect = ReplacementEffect(
        EventType.DAMAGE, lambda e, c: e, description="permanent shield"
    )
    bear.replacement_effects.append(permanent_effect)
    engine.rules.regenerate(bear)
    assert len(bear.replacement_effects) == 2

    engine._step_cleanup()
    assert bear.replacement_effects == [permanent_effect]


# ---------------------------------------------------------------------------
# RegenerateEffect.apply()
# ---------------------------------------------------------------------------


def test_regenerate_effect_self_form_targets_its_own_source():
    engine, state, p1, p2 = _rules()
    bear = _bf(state, _bear(toughness=2))
    ctx = GameContext(state, engine)

    RegenerateEffect(target_kind=None, source=bear).apply(ctx)
    assert len(bear.replacement_effects) == 1


def test_regenerate_effect_targeted_form_uses_the_resolved_target():
    engine, state, p1, p2 = _rules()
    source = _bf(state, _bear("Source"))
    target = _bf(state, _bear("Target", toughness=2), controller="p2")
    ctx = GameContext(state, engine)

    RegenerateEffect(source=source).apply(ctx, targets=[target])
    assert len(target.replacement_effects) == 1
    assert source.replacement_effects == []
