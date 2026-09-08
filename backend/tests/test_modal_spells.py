"""Modal spells and triggered abilities — "Choose one —" / "Choose one or
both —" (RULE 700.2).

Covers the whole pipeline: the `gate.py` block grouper that recognises a
"Choose one —" header plus its "• " mode lines, bare (a modal spell) or
trigger-wrapped (a permanent's modal triggered ability,
`parser/oracle/catalogue/modal.py`), the `AbilitySpec.modes` IR
(`parser/oracle/spec.py`), the binder that turns it into `obj.spell_modes`
or a `TriggeredAbility.modes` (`game/binding/core.py`), and the engine's
per-mode cast offer/commit for a spell (`game/game_engine.py`) or the
`trigger_mode` interactive choice for a triggered ability
(`game/rules_engine.py`).
"""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.effects.core import TriggeredAbility
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


def test_modal_triggered_ability_on_a_permanent_is_claimed():
    # A permanent's modal ETB trigger ("When ~ enters, choose one — …") is a
    # trigger-wrapped sibling of the bare modal-spell header — claimed as a
    # `triggered` spec carrying `modes`, not `spell_effect`.
    card = Card(
        id="Modal Permanent", name="Modal Permanent", type_line="Creature — Bear",
        is_creature=True, power=2, toughness=2,
        oracle_text="When ~ enters, choose one —\n• Deal 3 damage to any target.\n• Draw 2 cards.",
    )
    result = parse_oracle(card)
    assert result.modeled
    assert result.unclaimed == []
    modal_specs = [s for s in result.specs if s.modes is not None]
    assert len(modal_specs) == 1
    spec = modal_specs[0]
    assert spec.ability_kind == "triggered"
    assert spec.effects == []
    assert spec.trigger == {"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}}
    assert spec.modes["or_both"] is False
    assert len(spec.modes["options"]) == 2
    assert spec.modes["options"][0][0].type == "damage"
    assert spec.modes["options"][1][0].type == "draw"


def test_modal_triggered_ability_with_one_unparseable_mode_stays_unmodeled():
    card = Card(
        id="Modal Permanent Bad", name="Modal Permanent Bad", type_line="Creature — Bear",
        is_creature=True, power=2, toughness=2,
        oracle_text=(
            "When ~ enters, choose one —\n• Deal 3 damage to any target.\n"
            "• Do something no handler recognizes whatsoever."
        ),
    )
    result = parse_oracle(card)
    assert not result.modeled
    assert "when ~ enters, choose 1 —" in result.unclaimed
    assert any("do something no handler" in u for u in result.unclaimed)
    assert not any(s.modes is not None for s in result.specs)


def test_modal_triggered_ability_needs_a_recognized_trigger_event():
    # A trigger wrapper `_trigger_event` doesn't recognize (only enters/dies/
    # attacks/blocks are modeled) leaves the whole block unclaimed rather than
    # guessing a trigger — the ordinary trigger-recognition gate applies to a
    # modal trigger's wrapper exactly like a non-modal one.
    card = Card(
        id="Modal Permanent Unknown Trigger", name="Modal Permanent Unknown Trigger",
        type_line="Creature — Bear", is_creature=True, power=2, toughness=2,
        oracle_text=(
            "When you cast a spell, choose one —\n• Deal 3 damage to any target.\n"
            "• Draw 2 cards."
        ),
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


def test_ability_spec_modes_supported_on_triggered_too():
    spec = AbilitySpec(
        "triggered", trigger={"event": "ENTERS_BATTLEFIELD"},
        effects=[],
        modes={
            "or_both": False,
            "options": [
                [EffectSpec("draw", {"count": 1})],
                [EffectSpec("draw", {"count": 2})],
            ],
            "descriptions": ["draw 1", "draw 2"],
        },
    )
    spec.validate()  # does not raise


def test_ability_spec_modes_supported_on_activated_too():
    # MEC-43 (Umezawa's Jitte): RULE 700.2 modal choice widened from
    # spell/triggered to activated abilities too -- see
    # `effect_binder.bind_ability`'s own NotImplementedError guard for the
    # (still-unsupported) "choose N"/"or both" activated-modal shapes;
    # structural validation here only cares about the ability_kind.
    spec = AbilitySpec(
        "activated", effects=[],
        cost={"text": "{2}"},
        modes={
            "or_both": False,
            "options": [
                [EffectSpec("draw", {"count": 1})],
                [EffectSpec("draw", {"count": 2})],
            ],
        },
    )
    spec.validate()  # does not raise


def test_activated_modal_wider_than_choose_one_fails_at_bind_time():
    # The binder-level guard `test_ability_spec_modes_supported_on_
    # activated_too` references: spec-level validation accepts a "choose
    # 2" activated modal (it's a structurally valid RULE 700.2 block), but
    # `effect_binder.bind_ability` refuses to bind it -- no activated
    # ability in this cache needs more than plain "choose one" yet.
    from mtg_analyzer.game.binding.core import bind_ability

    spec = AbilitySpec(
        "activated", effects=[],
        cost={"text": "{2}"},
        modes={
            "choose": 2,
            "options": [
                [EffectSpec("draw", {"count": 1})],
                [EffectSpec("draw", {"count": 2})],
            ],
        },
    )
    with pytest.raises(NotImplementedError):
        bind_ability(spec, source=None)


# -- Binder (binding/core.py) ------------------------------------------------


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
    from mtg_analyzer.game.effects.core import GameEffect
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


# -- Triggered modal abilities (RULE 700.2 wrapped in RULE 603) --------------


def _modal_etb_trigger(source):
    """A "When ~ enters, choose one —" ability with a no-target mode 0
    (gain 3 life) and a targeted mode 1 (destroy target permanent) —
    mirrors `test_trigger_targeting.py`'s low-level construction pattern,
    exercising `game/rules_engine.py`'s `trigger_mode` choice directly
    rather than round-tripping through oracle text.
    """
    from mtg_analyzer.game.effects.core import DestroyEffect, GainLifeEffect

    return TriggeredAbility(
        trigger_event="ENTERS_BATTLEFIELD",
        effects=[],
        modes=[
            {"effects": [GainLifeEffect(amount=3)], "description": "gain 3 life"},
            {"effects": [DestroyEffect(source=source)], "description": "destroy target permanent"},
        ],
        controller_id=source.controller_id,
        source=source,
        description="modal ETB trigger",
    )


def _modal_etb_trigger_or_both(source):
    """An "or both" (RULE 700.2e) variant with two *untargeted* modes (gain
    life / draw a card) — real "or both" templating always pairs same-shape
    modes (see `modal_pump_instant`'s two same-target spell modes). A
    target+no-target (or two differently-targeted) combination now resolves
    correctly too via `StackItem.target_groups`
    (`test_multi_effect_targeting.py`) — this fixture just isn't the test for
    that; it isolates the "or both" combining mechanism itself."""
    from mtg_analyzer.game.effects.core import DrawCardEffect, GainLifeEffect

    return TriggeredAbility(
        trigger_event="ENTERS_BATTLEFIELD",
        effects=[],
        modes=[
            {"effects": [GainLifeEffect(amount=3)], "description": "gain 3 life"},
            {"effects": [DrawCardEffect(count=1)], "description": "draw a card"},
        ],
        modes_or_both=True,
        controller_id=source.controller_id,
        source=source,
        description="modal ETB trigger (or both)",
    )


def test_modal_trigger_opens_a_trigger_mode_choice_first():
    eng = make_engine()
    eng.begin_turn()
    source = _put(eng, creature("Source"))

    eng.rules.pending_triggers = [(_modal_etb_trigger(source), None)]
    eng.rules.put_triggers_on_stack()

    assert not eng.state.stack  # not placed yet — awaiting the mode
    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_mode"
    assert [o["label"] for o in choice["options"]] == ["gain 3 life", "destroy target permanent"]


def test_choosing_a_no_target_mode_places_and_resolves_immediately():
    eng = make_engine()
    eng.begin_turn()
    p1 = eng.state.player_by_id("p1")
    source = _put(eng, creature("Source"))
    life_before = p1.life

    eng.rules.pending_triggers = [(_modal_etb_trigger(source), None)]
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_trigger_mode_choice("0")

    assert eng.state.pending_choice is None
    assert len(eng.state.stack) == 1
    eng.resolve_until_stable()
    assert p1.life == life_before + 3


def test_choosing_a_targeted_mode_opens_the_target_choice_next():
    eng = make_engine()
    eng.begin_turn()
    source = _put(eng, creature("Source"))
    victim = _put(eng, creature("Victim"))

    eng.rules.pending_triggers = [(_modal_etb_trigger(source), None)]
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_trigger_mode_choice("1")

    assert not eng.state.stack  # still awaiting the target
    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_target"
    victim_option = next(o for o in choice["options"] if o["instance_id"] == victim.instance_id)
    assert source.instance_id not in {o.get("instance_id") for o in choice["options"]}

    eng.rules.resolve_trigger_target_choice(victim_option["id"])
    assert len(eng.state.stack) == 1
    assert eng.state.stack[0].targets == [victim]
    eng.resolve_until_stable()
    assert victim not in eng.state.battlefield
    assert source in eng.state.battlefield


def test_missing_mode_answer_defaults_to_the_first_mode():
    # RULE 700.2's mode choice is mandatory — an unrecognized/declined
    # answer must still resolve, not silently drop the trigger.
    eng = make_engine()
    eng.begin_turn()
    p1 = eng.state.player_by_id("p1")
    source = _put(eng, creature("Source"))
    life_before = p1.life

    eng.rules.pending_triggers = [(_modal_etb_trigger(source), None)]
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_trigger_mode_choice(None)

    eng.resolve_until_stable()
    assert p1.life == life_before + 3  # mode 0, the first option


def test_or_both_offers_a_combined_both_choice():
    eng = make_engine(p1_library=[land(), land()])
    eng.begin_turn()
    p1 = eng.state.player_by_id("p1")
    source = _put(eng, creature("Source"))
    life_before = p1.life
    hand_before = len(p1.hand)

    eng.rules.pending_triggers = [(_modal_etb_trigger_or_both(source), None)]
    eng.rules.put_triggers_on_stack()
    choice = eng.state.pending_choice
    assert {o["id"] for o in choice["options"]} == {"0", "1", "both"}

    eng.rules.resolve_trigger_mode_choice("both")
    # Neither mode needs a target — "both" places and resolves immediately,
    # applying both modes' effects together (RULE 700.2e).
    assert eng.state.pending_choice is None
    assert len(eng.state.stack) == 1
    eng.resolve_until_stable()
    assert p1.life == life_before + 3
    assert len(p1.hand) == hand_before + 1


def test_choosing_one_mode_of_an_or_both_ability_applies_only_that_one():
    eng = make_engine(p1_library=[land(), land()])
    eng.begin_turn()
    p1 = eng.state.player_by_id("p1")
    source = _put(eng, creature("Source"))
    life_before = p1.life
    hand_before = len(p1.hand)

    eng.rules.pending_triggers = [(_modal_etb_trigger_or_both(source), None)]
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_trigger_mode_choice("0")

    eng.resolve_until_stable()
    assert p1.life == life_before + 3
    assert len(p1.hand) == hand_before  # mode 1 (draw) wasn't chosen


def test_modal_triggered_ability_end_to_end_from_oracle_text():
    """The full pipeline: oracle text → gate.py → spec.py → binding/core.py
    → a real firing through the event bus, no low-level construction."""
    eng = make_engine()
    eng.begin_turn()
    p1 = eng.state.player_by_id("p1")
    life_before = p1.life
    card = Card(
        id="Modal ETB Bear", name="Modal ETB Bear", type_line="Creature — Bear",
        is_creature=True, power=2, toughness=2,
        oracle_text="When ~ enters, choose one —\n• You gain 3 life.\n• Draw a card.",
    )
    obj = GameObject(card, owner_id="p1")
    eng.state.player_by_id("p1").add_to_zone(obj, Zone.HAND)
    hand_before = len(p1.hand) - 1  # excluding the creature itself

    # Cast it as a permanent spell: resolves onto the battlefield, fires
    # ENTERS_BATTLEFIELD, and its bound modal trigger should fire.
    p1.mana_pool.add_many({"C": 10})
    bind_from_catalogue(obj)
    eng.state.current_step = "main1"
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_mode"
    eng.rules.resolve_trigger_mode_choice("0")
    eng.resolve_until_stable()
    assert p1.life == life_before + 3
    assert obj in eng.state.battlefield
