"""Modal spells — "Choose one —" / "Choose one or both —" (RULE 700.2).

Covers the whole pipeline: the `gate.py` block grouper that recognises a
"Choose one —" header plus its "• " mode lines (`parser/oracle/catalogue/
modal.py`), the `AbilitySpec.modes` IR (`parser/oracle/spec.py`), the
binder that turns it into `obj.spell_modes` (`game/effect_binder.py`), and
the engine's per-mode cast offer/commit (`game/game_engine.py`).
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.effect_binder import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec, SpecValidationError
from mtg_analyzer.services.game_session import GameActionError, GameSession, build_goldfish_engine


def creature(name="Bear", power=2, toughness=2, **kw):
    return Card(id=name, name=name, type_line=kw.pop("type_line", "Creature — Bear"),
                is_creature=True, power=power, toughness=toughness, **kw)


def land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def modal_instant(name="Test Charm", oracle="Choose one —\n• Deal 3 damage to any target.\n• Draw 2 cards."):
    return Card(id=name, name=name, type_line="Instant", is_instant=True,
                mana_cost_string="{R}", converted_mana_cost=1, oracle_text=oracle)


def modal_pump_instant(name="Borrowed Test", or_both=True):
    header = "Choose one or both —" if or_both else "Choose one —"
    oracle = (
        f"{header}\n"
        "• Target creature gets +3/+0 until end of turn.\n"
        "• Target creature gains first strike until end of turn."
    )
    return Card(id=name, name=name, type_line="Instant", is_instant=True,
                mana_cost_string="{1}{R}", converted_mana_cost=2, oracle_text=oracle)


def make_engine(p1_library=()):
    return GameEngine.new_game(
        [("p1", "Alice", list(p1_library)), ("p2", "Bob", [])],
        starting_life=20, starting_hand=0,
    )


def _in_hand(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller)
    eng.state.player_by_id(controller).add_to_zone(obj, Zone.HAND)
    return obj


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _ready_main_phase(eng):
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng.state.active_player


# -- Parser (gate.py / catalogue/modal.py) -----------------------------------


def test_modal_spell_parses_as_modeled_with_modes():
    card = modal_instant()
    result = parse_oracle(card)
    assert result.modeled
    assert result.unclaimed == []
    modal_specs = [s for s in result.specs if s.modes is not None]
    assert len(modal_specs) == 1
    spec = modal_specs[0]
    assert spec.ability_kind == "spell_effect"
    assert spec.effects == []  # top-level effects stay empty; modes carry them
    assert spec.modes["or_both"] is False
    assert len(spec.modes["options"]) == 2
    assert spec.modes["options"][0][0].type == "damage"
    assert spec.modes["options"][1][0].type == "draw"
    assert spec.modes["descriptions"] == [
        "deal 3 damage to any target.",
        "draw 2 cards.",
    ]


def test_modal_spell_with_one_unparseable_mode_stays_unmodeled():
    card = modal_instant(
        oracle="Choose one —\n• Deal 3 damage to any target.\n"
        "• Do something no handler recognizes whatsoever."
    )
    result = parse_oracle(card)
    assert not result.modeled
    # Fail-closed: the whole block (header + every bullet) is unclaimed, not
    # just the one bad mode — no half-modal card ever gets modeled.
    assert "choose 1 —" in result.unclaimed
    assert any("do something no handler" in u for u in result.unclaimed)
    assert not any(s.modes is not None for s in result.specs)


def test_choose_one_or_both_sets_or_both_flag():
    card = modal_pump_instant(or_both=True)
    result = parse_oracle(card)
    assert result.modeled
    modal_specs = [s for s in result.specs if s.modes is not None]
    assert len(modal_specs) == 1
    assert modal_specs[0].modes["or_both"] is True


def test_choose_one_or_more_is_not_this_grammar_and_stays_unclaimed():
    # RULE 700.2's "or more"/"choose X" shapes aren't modeled by this block
    # grouper — a different template, left unclaimed (fail-closed).
    card = modal_instant(
        oracle="Choose one or more —\n• Deal 3 damage to any target.\n• Draw 2 cards."
    )
    result = parse_oracle(card)
    assert not result.modeled


def test_modal_block_on_a_permanent_is_out_of_scope_and_unclaimed():
    # Only instants/sorceries are grouped as modal spell blocks (RULE 700.2
    # ETB triggers on a permanent aren't this shape yet).
    card = Card(
        id="Modal Permanent", name="Modal Permanent", type_line="Creature — Bear",
        is_creature=True, power=2, toughness=2,
        oracle_text="When ~ enters, choose one —\n• Deal 3 damage to any target.\n• Draw 2 cards.",
    )
    result = parse_oracle(card)
    assert not result.modeled


# -- AbilitySpec IR (spec.py) -------------------------------------------------


def test_ability_spec_modes_round_trips_through_to_dict_from_dict():
    spec = AbilitySpec(
        "spell_effect",
        effects=[],
        modes={
            "or_both": True,
            "options": [
                [EffectSpec("damage", {"amount": 3, "target_kind": "any"})],
                [EffectSpec("draw", {"count": 2})],
            ],
            "descriptions": ["deal 3 damage", "draw 2"],
        },
        raw_text="choose 1 or both —",
    )
    spec.validate()
    restored = AbilitySpec.from_dict(spec.to_dict())
    restored.validate()
    assert restored.modes["or_both"] is True
    assert [e.type for e in restored.modes["options"][0]] == ["damage"]
    assert [e.type for e in restored.modes["options"][1]] == ["draw"]
    assert restored.modes["descriptions"] == ["deal 3 damage", "draw 2"]


def test_ability_spec_modes_needs_at_least_two_options():
    spec = AbilitySpec(
        "spell_effect", effects=[],
        modes={"or_both": False, "options": [[EffectSpec("draw", {"count": 1})]]},
    )
    with pytest.raises(SpecValidationError):
        spec.validate()


def test_ability_spec_modes_only_supported_on_spell_effect():
    spec = AbilitySpec(
        "triggered", trigger={"event": "ENTERS_BATTLEFIELD"},
        effects=[EffectSpec("draw", {"count": 1})],
        modes={
            "or_both": False,
            "options": [
                [EffectSpec("draw", {"count": 1})],
                [EffectSpec("draw", {"count": 2})],
            ],
        },
    )
    with pytest.raises(SpecValidationError):
        spec.validate()


# -- Binder (effect_binder.py) ------------------------------------------------


def test_binder_attaches_spell_modes_per_option():
    eng = make_engine()
    obj = _in_hand(eng, modal_instant())
    spec = AbilitySpec(
        "spell_effect",
        effects=[],
        modes={
            "or_both": False,
            "options": [
                [EffectSpec("damage", {"amount": 3, "target_kind": "any"})],
                [EffectSpec("draw", {"count": 2})],
            ],
            "descriptions": ["deal 3 damage to any target.", "draw 2 cards."],
        },
        raw_text="choose 1 —",
    )
    attach_to_object(obj, [spec])
    assert len(obj.spell_modes) == 2
    assert obj.spell_modes_or_both is False
    assert obj.spell_modes[0]["description"] == "deal 3 damage to any target."
    assert obj.spell_modes[1]["description"] == "draw 2 cards."
    # Each mode's effects are live GameEffect objects, not specs.
    from mtg_analyzer.game.effects import GameEffect
    assert all(isinstance(e, GameEffect) for e in obj.spell_modes[0]["effects"])
    assert all(isinstance(e, GameEffect) for e in obj.spell_modes[1]["effects"])
    # No top-level spell_effects — nothing resolves until a mode is chosen.
    assert obj.spell_effects == []


def test_binder_via_bind_from_catalogue_end_to_end_from_oracle_text():
    eng = make_engine()
    obj = _in_hand(eng, modal_instant())
    bind_from_catalogue(obj)
    assert len(obj.spell_modes) == 2
    assert obj.spell_modes_or_both is False


# -- Engine: cast flow (game_engine.py) ---------------------------------------


def test_legal_actions_offers_one_cast_action_per_mode():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, modal_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 1})
    actions = [
        a for a in eng.legal_actions(p1)
        if a.get("instance_id") == obj.instance_id
    ]
    assert len(actions) == 2
    modes = {a["mode"] for a in actions}
    assert modes == {0, 1}
    damage_action = next(a for a in actions if a["mode"] == 0)
    draw_action = next(a for a in actions if a["mode"] == 1)
    # Mode 0 ("any target") is never locked — p2 is a legal target even with
    # no creatures on board; mode 1 (draw) needs no target at all.
    assert not damage_action.get("locked")
    assert damage_action["requires_target"] is True
    assert not draw_action.get("requires_target")


def test_cast_without_a_mode_raises():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, modal_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 1})
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj)


def test_cast_with_an_invalid_mode_index_raises():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, modal_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 1})
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj, mode=5)


def test_choosing_the_draw_mode_resolves_as_draw_two_no_target():
    eng = make_engine(p1_library=[land(), land()])
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, modal_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 1})
    hand_before = len(p1.hand) - 1  # excluding the spell itself
    eng.cast_spell(p1, obj, mode=1)
    eng.resolve_until_stable()
    assert len(p1.hand) == hand_before + 2
    assert obj in p1.graveyard
    # The temporary spell_effects swap is cleaned back up afterwards.
    assert obj.spell_effects == []


def test_choosing_the_damage_mode_validates_and_deals_targeted_damage():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    p2 = eng.state.player_by_id("p2")
    obj = _in_hand(eng, modal_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, obj, targets=[p2], mode=0)
    eng.resolve_until_stable()
    assert p2.life == 17


def test_damage_mode_with_no_legal_target_is_rejected():
    # A variant whose damage mode targets a creature specifically, on a
    # board with none — RULE 601.2c must reject casting that mode.
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, modal_instant(
        oracle="Choose one —\n• Deal 3 damage to target creature.\n• Draw 2 cards."
    ))
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 1})
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj, mode=0)
    # The other mode is unaffected.
    eng.cast_spell(p1, obj, mode=1)


def test_or_both_offers_a_combined_both_action():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, modal_pump_instant(or_both=True))
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 1, "C": 1})
    actions = [
        a for a in eng.legal_actions(p1) if a.get("instance_id") == obj.instance_id
    ]
    assert {a.get("mode") for a in actions} == {0, 1, "both"}


def test_choose_one_without_or_both_never_offers_a_both_action():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, modal_pump_instant(or_both=False))
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 1, "C": 1})
    actions = [
        a for a in eng.legal_actions(p1) if a.get("instance_id") == obj.instance_id
    ]
    assert {a.get("mode") for a in actions} == {0, 1}
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj, mode="both")


def test_or_both_mode_resolves_both_effects_in_printed_order():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, modal_pump_instant(or_both=True))
    bind_from_catalogue(obj)
    target = _put(eng, creature("Bear", power=2, toughness=2))
    p1.mana_pool.add_many({"R": 1, "C": 1})
    eng.cast_spell(p1, obj, targets=[target, target], mode="both")
    eng.resolve_until_stable()
    eng.rules.check_state_based_actions()
    # +3/+0 then first strike, both applied.
    assert (target.power, target.toughness) == (5, 2)
    assert combat_has_first_strike(target)


def combat_has_first_strike(obj):
    from mtg_analyzer.game import combat
    return combat.has(obj, "first_strike")


# -- Undo / snapshot survives a modal cast (services/game_session.py) --------


def make_session(library=None, hand=7, with_dummy=False):
    library = library if library is not None else [land()] * 30
    engine = build_goldfish_engine(library, starting_hand=hand, with_dummy=with_dummy)
    return GameSession(engine)


def advance_until(session, *, step, limit=40):
    for _ in range(limit):
        if session.engine.state.current_step == step:
            return
        session.apply_action({"type": "advance_step"})
    raise AssertionError(f"never reached step={step}")


def test_rewind_after_a_modal_cast_restores_hand_and_mana_and_keeps_modes_bound():
    session = make_session(
        library=[land()] * 10 + [modal_instant(), land()], hand=7, with_dummy=True
    )
    advance_until(session, step="main1")
    state = session.engine.state
    p1 = state.active_player
    p2 = state.player_by_id("goldfish")
    p1.mana_pool.add_many({"R": 1})
    spell_obj = next(o for o in p1.hand if o.card.name == "Test Charm")
    assert len(spell_obj.spell_modes) == 2

    hand_before = len(p1.hand)
    session.apply_action(
        {
            "type": "cast_spell",
            "instance_id": spell_obj.instance_id,
            "mode": 0,
            "targets": [{"player_id": p2.id}],
        }
    )
    assert len(session.engine.state.stack) == 1
    assert len(session.engine.state.active_player.hand) == hand_before - 1

    session.rewind(1)
    state = session.engine.state
    p1 = state.active_player
    assert len(state.stack) == 0
    assert len(p1.hand) == hand_before
    restored_obj = next(o for o in p1.hand if o.card.name == "Test Charm")
    # Re-bound the same way after the clone — still castable by mode.
    assert len(restored_obj.spell_modes) == 2
    assert p1.mana_pool.pool.get("R", 0) == 1  # mana refunded too

    # And it can still be cast again post-undo (proves the object, and its
    # binder-time spell_modes, weren't left in some half-swapped state).
    p2 = state.player_by_id("goldfish")
    life_before = p2.life
    view = session.apply_action(
        {
            "type": "cast_spell",
            "instance_id": restored_obj.instance_id,
            "mode": 0,
            "targets": [{"player_id": p2.id}],
        }
    )
    assert len(view["state"]["stack"]) == 1
    session.apply_action({"type": "pass_priority"})
    assert session.engine.state.player_by_id(p2.id).life == life_before - 3


def test_cast_spell_action_rejects_a_missing_mode_via_the_session():
    session = make_session(library=[land()] * 10 + [modal_instant(), land()], hand=7)
    advance_until(session, step="main1")
    state = session.engine.state
    p1 = state.active_player
    p1.mana_pool.add_many({"R": 1})
    spell_obj = next(o for o in p1.hand if o.card.name == "Test Charm")
    hand_before = {o.instance_id for o in p1.hand}
    with pytest.raises(GameActionError):
        session.apply_action({"type": "cast_spell", "instance_id": spell_obj.instance_id})
    # Rejected cleanly — nothing changed (the pre-action snapshot is
    # restored, so this is a *new* clone — compare by instance_id, not
    # object identity).
    restored_hand = {o.instance_id for o in session.engine.state.active_player.hand}
    assert restored_hand == hand_before
    assert spell_obj.instance_id in restored_hand
