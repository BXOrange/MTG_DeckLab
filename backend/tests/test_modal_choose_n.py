""""Choose two —"/"choose N —" modality (RULE 700.2, N>=2) — the fixed-count
generalization of "choose one —"/"choose one or both —" (`test_modal_
spells.py`). Covers the same pipeline layers that file does: the `gate.py`
block grouper (bare spell header and trigger-wrapped), `AbilitySpec.modes`'s
new `choose` field, the binder (`obj.spell_modes_choose`/`TriggeredAbility.
modes_choose`), the engine's per-combination cast offer (`game_engine.py`'s
`_modal_cast_actions`/`_effects_for_mode`), and the iterative `trigger_mode`
choice (`rules_engine.py`) that picks one mode per round until `choose` are
picked, mirroring the library search's "pick up to N one at a time" pattern.

Real "choose two" cards (Kolaghan's Command, Austere Command, Titan of
Industry) almost always give each mode its own "target ..." clause. Combining
two *differently*-targeted modes now resolves correctly via
`StackItem.target_groups` (`test_multi_effect_targeting.py`'s
`test_modal_two_modes_with_different_targets_combine_via_target_groups`,
and — for a triggered ability's own mode — `_continue_trigger_multi_target`
gathering one target per effect automatically); nothing here needed to
change, since `target_groups` is orthogonal to the choose-N mechanism this
file covers. Engine-level tests here still use non-targeted (or same-target)
modes to isolate the choose-N mechanism itself, exactly like
`test_modal_spells.py` already does for "or both"; the parser-level tests use
real card text to prove recognition, separately from full castability.
"""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import DrawCardEffect, GainLifeEffect, MillEffect, TriggeredAbility
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec, SpecValidationError


def creature(name="Source"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2)


def land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def choose_two_of_four_instant(name="Test Command"):
    # Four untargeted modes (draw / gain life / mill / draw again) so the
    # engine-level tests exercise the choose-N combining logic without
    # tripping the pre-existing shared-targets-list limitation.
    oracle = (
        "Choose two —\n"
        "• Draw a card.\n"
        "• You gain 3 life.\n"
        "• Mill two cards.\n"
        "• Draw a card."
    )
    return Card(id=name, name=name, type_line="Instant", is_instant=True,
                mana_cost_string="{1}{U}", converted_mana_cost=2, oracle_text=oracle)


def repeatable_choose_three_instant(name="Test Confluence"):
    return Card(
        id=name, name=name, type_line="Instant", is_instant=True,
        mana_cost_string="{1}{U}", converted_mana_cost=2,
        oracle_text=(
            "Choose three. You may choose the same mode more than once.\n"
            "• Draw a card.\n"
            "• You gain 3 life.\n"
            "• Mill two cards."
        ),
    )


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("this spell was kicked", {"kind": "kicked"}),
        ("you control a Wizard as you cast this spell", {"kind": "controls_subtype_as_cast", "subtype": "wizard"}),
        ("you control a commander as you cast this spell", {"kind": "controls_commander_as_cast"}),
        ("there are four or more card types among cards in your graveyard", {"kind": "card_types_in_graveyard_at_least", "amount": 4}),
        ("you have exactly 13 life", {"kind": "life_total_exactly", "amount": 13}),
        ("you descended this turn", {"kind": "descended_this_turn"}),
    ],
)
def test_conditional_modal_headers_use_closed_condition_ir(condition, expected):
    card = Card(
        id=f"Conditional {condition}", name="Conditional Modal", type_line="Instant",
        is_instant=True, mana_cost_string="{U}", converted_mana_cost=1,
        oracle_text=(
            f"Choose one. If {condition}, you may choose both instead.\n"
            "• Draw a card.\n• You gain 3 life."
        ),
    )
    parsed = parse_oracle(card)
    assert parsed.coverage == MODELED
    assert parsed.specs[0].modes["override"] == {"condition": expected, "choose": 2}


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


# ---------------------------------------------------------------------------
# Parser (gate.py / catalogue/modal.py / spec.py)
# ---------------------------------------------------------------------------


def test_choose_two_header_is_recognized():
    card = Card(id="T", name="T", type_line="Instant", is_instant=True,
                oracle_text="Choose two —\n• Draw a card.\n• Gain 3 life.\n• Mill two cards.")
    r = parse_oracle(card)
    assert r.coverage == MODELED
    (spec,) = r.specs
    assert spec.modes["choose"] == 2
    assert len(spec.modes["options"]) == 3


def test_choose_three_header_is_recognized():
    card = Card(id="T", name="T", type_line="Instant", is_instant=True,
                oracle_text="Choose three —\n• Draw a card.\n• Gain 3 life.\n"
                            "• Mill two cards.\n• You gain 1 life.")
    r = parse_oracle(card)
    assert r.coverage == MODELED
    (spec,) = r.specs
    assert spec.modes["choose"] == 3


def test_choose_n_exceeding_mode_count_stays_unclaimed():
    # "Choose three —" with only two modes printed is nonsensical — fail
    # closed rather than clamp/guess.
    card = Card(id="T", name="T", type_line="Instant", is_instant=True,
                oracle_text="Choose three —\n• Draw a card.\n• Gain 3 life.")
    r = parse_oracle(card)
    assert r.coverage != MODELED


def test_repeatable_choose_n_header_is_recognized():
    # Fiery Confluence is one of the actual PAR-54 cards; its already-known
    # body handlers prove this closes the header gap rather than only a
    # synthetic spelling.
    card = Card(
        id="Fiery Confluence", name="Fiery Confluence", type_line="Sorcery", is_sorcery=True,
        oracle_text=(
            "Choose three. You may choose the same mode more than once.\n"
            "• Fiery Confluence deals 1 damage to each creature.\n"
            "• Fiery Confluence deals 2 damage to each opponent.\n"
            "• Destroy target artifact."
        ),
    )
    r = parse_oracle(card)
    assert r.coverage == MODELED
    (spec,) = r.specs
    assert spec.modes["choose"] == 3
    assert spec.modes["repeatable"] is True


def test_choose_two_triggered_ability_is_recognized():
    card = Card(id="Permanent", name="Permanent", type_line="Creature — Giant",
                is_creature=True, power=4, toughness=4,
                oracle_text="When this creature enters, choose two —\n"
                            "• Draw a card.\n• Gain 3 life.\n• Mill two cards.")
    r = parse_oracle(card)
    assert r.coverage == MODELED
    (spec,) = r.specs
    assert spec.ability_kind == "triggered"
    assert spec.modes["choose"] == 2


def test_triggered_modal_accepts_any_trigger_segment_line_claims():
    # RULE 603.1 wrapper on a modal block: `_split_triggered_modal_block`
    # recognises the wrapper via `segment_line` (the same grammar an
    # ordinary triggered ability uses), not the narrow generic
    # `_trigger_event`/`_trigger_condition` pair — so a combined-event
    # attack/block trigger and a typed cast-spell trigger both drive it.
    gargaroth = Card(id="G", name="G", type_line="Creature — Beast",
                     is_creature=True, power=6, toughness=6,
                     oracle_text="Whenever this creature attacks or blocks, choose one —\n"
                                 "• Create a 3/3 green Beast creature token.\n"
                                 "• You gain 3 life.\n• Draw a card.")
    r = parse_oracle(gargaroth)
    assert r.coverage == MODELED
    (spec,) = r.specs
    assert spec.ability_kind == "triggered"
    # combined "attacks or blocks" → event list, carried through verbatim
    assert spec.trigger["event"] == ["ATTACKS", "BLOCKS"]
    assert spec.modes["choose"] == 1 and len(spec.modes["options"]) == 3

    # A typed cast-spell trigger — recognised only by `segment_line`'s
    # dedicated `_CAST_SPELL_TRIGGER_*` regexes, never by the old generic
    # `_trigger_event` — now also drives a modal block.
    exemplars = Card(id="E", name="E", type_line="Creature — Human Monk",
                     is_creature=True, power=3, toughness=2,
                     oracle_text="Whenever you cast a noncreature spell, choose one —\n"
                                 "• Tap target creature.\n"
                                 "• You gain 2 life.\n• Draw a card.")
    r2 = parse_oracle(exemplars)
    assert r2.coverage == MODELED
    (spec2,) = r2.specs
    assert spec2.trigger["event"] == "SPELL_CAST"
    assert spec2.trigger.get("spell_exclude_card_types") == ["creature"]


def test_triggered_modal_binds_one_ability_per_event_in_a_list():
    # A combined-event trigger becomes one `TriggeredAbility` per event, the
    # same fan-out the binder does for a plain combined-event triggered
    # ability — proves the full trigger dict (not just event+condition)
    # reaches `effect_binder`'s triggered path.
    card = Card(id="G2", name="G2", type_line="Creature — Beast",
                is_creature=True, power=6, toughness=6,
                oracle_text="Whenever this creature attacks or blocks, choose one —\n"
                            "• You gain 3 life.\n• Draw a card.")
    obj = GameObject(card=card, owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    triggered = [a for a in obj.triggered_abilities if isinstance(a, TriggeredAbility)]
    assert len(triggered) == 2  # one for ATTACKS, one for BLOCKS
    assert all(a.modes and len(a.modes) == 2 for a in triggered)


def test_choose_one_still_defaults_choose_to_one():
    # Backward compatibility: the ordinary "choose one" shape carries no
    # explicit count and must keep defaulting to 1.
    card = Card(id="T", name="T", type_line="Instant", is_instant=True,
                oracle_text="Choose one —\n• Draw a card.\n• Gain 3 life.")
    r = parse_oracle(card)
    assert r.coverage == MODELED
    (spec,) = r.specs
    assert spec.modes["choose"] == 1


def test_real_kolaghan_command_text_parses_fully():
    # Real card text (four differently-targeted modes) — proves parser
    # recognition end to end; full castability of every 2-combination is a
    # separate, pre-existing limitation (see module docstring).
    card = Card(id="Kolaghan's Command", name="Kolaghan's Command", type_line="Instant",
                is_instant=True, mana_cost_string="{1}{B}{R}",
                oracle_text="Choose two —\n"
                            "• Return target creature card from your graveyard to your hand.\n"
                            "• Target player discards a card.\n"
                            "• Destroy target artifact.\n"
                            "• Kolaghan's Command deals 2 damage to any target.")
    r = parse_oracle(card)
    assert r.coverage == MODELED
    (spec,) = r.specs
    assert spec.modes["choose"] == 2
    assert len(spec.modes["options"]) == 4


def test_spec_validation_rejects_choose_out_of_range():
    with pytest.raises(SpecValidationError):
        AbilitySpec(
            "spell_effect", effects=[],
            modes={"choose": 5, "options": [[EffectSpec("draw", {"count": 1})],
                                             [EffectSpec("gain_life", {"amount": 1})]]},
        ).validate()
    with pytest.raises(SpecValidationError):
        AbilitySpec(
            "spell_effect", effects=[],
            modes={"choose": 0, "options": [[EffectSpec("draw", {"count": 1})],
                                             [EffectSpec("gain_life", {"amount": 1})]]},
        ).validate()


# ---------------------------------------------------------------------------
# Engine: modal spell casting (choose two of four)
# ---------------------------------------------------------------------------


def test_legal_actions_offers_one_action_per_combination():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_two_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    actions = [a for a in eng.legal_actions(p1) if a.get("instance_id") == obj.instance_id]
    # C(4, 2) = 6 combinations.
    assert len(actions) == 6
    modes = {tuple(a["mode"]) for a in actions}
    assert modes == {(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)}


def test_cast_with_wrong_length_mode_raises():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_two_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj, mode=[0])  # choose is 2, not 1


def test_cast_with_duplicate_index_raises():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_two_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj, mode=[1, 1])


def test_repeatable_modes_offer_and_resolve_duplicate_selection():
    eng = make_engine(p1_library=[land(), land(), land(), land(), land()])
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, repeatable_choose_three_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})

    actions = [a for a in eng.legal_actions(p1) if a.get("instance_id") == obj.instance_id]
    # Multisets of size 3 from 3 modes: C(3 + 3 - 1, 3) = 10.
    assert len(actions) == 10
    assert any(a["mode"] == [0, 0, 0] for a in actions)

    hand_before = len(p1.hand) - 1
    eng.cast_spell(p1, obj, mode=[0, 0, 0])
    eng.resolve_until_stable()
    assert len(p1.hand) == hand_before + 3


def test_kicked_modal_override_allows_every_mode():
    card = Card(
        id="Kicked Modal", name="Kicked Modal", type_line="Instant", is_instant=True,
        mana_cost_string="{U}", converted_mana_cost=1, keywords=["Kicker"],
        oracle_text=(
            "Kicker {1}\n"
            "Choose one. If this spell was kicked, choose any number instead.\n"
            "• Draw a card.\n• You gain 3 life."
        ),
    )
    eng = make_engine(p1_library=[land(), land()])
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, card)
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    actions = [a for a in eng.legal_actions(p1) if a.get("instance_id") == obj.instance_id]
    assert any(a.get("kicked") == 1 and a.get("mode") == [0, 1] for a in actions)
    life_before = p1.life
    hand_before = len(p1.hand) - 1
    eng.cast_spell(p1, obj, mode=[0, 1], kicked=1)
    eng.resolve_until_stable()
    assert p1.life == life_before + 3
    assert len(p1.hand) == hand_before + 1


def test_cast_time_commander_override_offers_and_resolves_both_modes():
    card = Card(
        id="Commander Modal", name="Commander Modal", type_line="Instant", is_instant=True,
        mana_cost_string="{U}", converted_mana_cost=1,
        oracle_text=(
            "Choose one. If you control a commander as you cast this spell, you may choose both instead.\n"
            "• Draw a card.\n• You gain 3 life."
        ),
    )
    eng = make_engine(p1_library=[land()])
    p1 = _ready_main_phase(eng)
    commander = _put(eng, creature("Commander"))
    commander.is_commander = True
    obj = _in_hand(eng, card)
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1})
    actions = [a for a in eng.legal_actions(p1) if a.get("instance_id") == obj.instance_id]
    assert any(a.get("mode") == [0, 1] for a in actions)
    life_before = p1.life
    eng.cast_spell(p1, obj, mode=[0, 1])
    eng.resolve_until_stable()
    assert p1.life == life_before + 3


def test_cast_with_out_of_range_index_raises():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_two_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj, mode=[0, 9])


def test_bare_int_mode_rejected_when_choose_is_two():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_two_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj, mode=0)  # a bare int no longer suffices


def test_choosing_a_combination_applies_both_modes_in_printed_order():
    eng = make_engine(p1_library=[land(), land(), land(), land()])
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_two_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    life_before = p1.life
    hand_before = len(p1.hand) - 1  # excluding the spell itself
    library_before = len(p1.library)

    eng.cast_spell(p1, obj, mode=[1, 2])  # gain life + mill, in that order
    eng.resolve_until_stable()

    assert p1.life == life_before + 3
    assert len(p1.library) == library_before - 2
    assert len(p1.hand) == hand_before  # the draw modes weren't chosen
    assert obj.spell_effects == []  # temporary swap cleaned up


def test_mode_description_joins_chosen_combination():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_two_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    actions = [a for a in eng.legal_actions(p1) if a.get("instance_id") == obj.instance_id]
    action = next(a for a in actions if tuple(a["mode"]) == (1, 2))
    assert action["mode_description"] == "you gain 3 life. + mill 2 cards."


# ---------------------------------------------------------------------------
# Engine: modal triggered ability, iterative trigger_mode choice
# ---------------------------------------------------------------------------


def _choose_two_etb_trigger(source):
    """A "When ~ enters, choose two —" ability with four untargeted modes —
    exercises the iterative accumulate-then-combine `trigger_mode` choice
    directly, mirroring `test_modal_spells.py`'s `_modal_etb_trigger` low-
    level construction pattern."""
    return TriggeredAbility(
        trigger_event="ENTERS_BATTLEFIELD",
        effects=[],
        modes=[
            {"effects": [DrawCardEffect(count=1)], "description": "draw a card"},
            {"effects": [GainLifeEffect(amount=3)], "description": "gain 3 life"},
            {"effects": [MillEffect(count=2)], "description": "mill two cards"},
            {"effects": [GainLifeEffect(amount=1)], "description": "gain 1 life"},
        ],
        modes_choose=2,
        controller_id=source.controller_id,
        source=source,
        description="modal ETB trigger (choose two)",
    )


def test_first_round_offers_all_four_modes():
    eng = make_engine()
    eng.begin_turn()
    source = _put(eng, creature())
    eng.rules.pending_triggers = [(_choose_two_etb_trigger(source), None)]
    eng.rules.put_triggers_on_stack()

    assert not eng.state.stack  # not placed — awaiting the first pick
    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_mode"
    assert {o["id"] for o in choice["options"]} == {"0", "1", "2", "3"}
    assert choice["chosen"] == []


def test_second_round_excludes_the_first_pick():
    eng = make_engine()
    eng.begin_turn()
    source = _put(eng, creature())
    eng.rules.pending_triggers = [(_choose_two_etb_trigger(source), None)]
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_trigger_mode_choice("1")  # pick "gain 3 life" first

    assert not eng.state.stack  # still one more mode to pick
    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_mode"
    assert {o["id"] for o in choice["options"]} == {"0", "2", "3"}
    assert choice["chosen"] == [1]


def test_picking_two_modes_combines_effects_in_printed_order_not_pick_order():
    eng = make_engine(p1_library=[land(), land(), land()])
    eng.begin_turn()
    p1 = eng.state.player_by_id("p1")
    source = _put(eng, creature())
    life_before = p1.life
    library_before = len(p1.library)

    eng.rules.pending_triggers = [(_choose_two_etb_trigger(source), None)]
    eng.rules.put_triggers_on_stack()
    # Pick mode 2 (mill) first, then mode 1 (gain life) — printed order is
    # 1 then 2, so effects must combine as gain-life-then-mill regardless.
    eng.rules.resolve_trigger_mode_choice("2")
    eng.rules.resolve_trigger_mode_choice("1")

    assert eng.state.pending_choice is None
    assert len(eng.state.stack) == 1
    eng.resolve_until_stable()
    assert p1.life == life_before + 3
    assert len(p1.library) == library_before - 2


def test_missing_answer_during_accumulation_defaults_to_first_available():
    eng = make_engine(p1_library=[land(), land()])
    eng.begin_turn()
    p1 = eng.state.player_by_id("p1")
    source = _put(eng, creature())
    life_before = p1.life

    eng.rules.pending_triggers = [(_choose_two_etb_trigger(source), None)]
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_trigger_mode_choice(None)  # defaults to mode 0 (draw)
    eng.rules.resolve_trigger_mode_choice(None)  # defaults to first available: mode 1

    eng.resolve_until_stable()
    assert p1.life == life_before + 3  # mode 1 (gain 3 life) was included


def test_choose_one_or_both_still_works_after_choose_n_changes():
    # Regression guard: the existing choose-1-of-2 "or both" behaviour
    # (test_modal_spells.py) must be unaffected by generalizing to choose-N.
    from mtg_analyzer.game.effects.core import DestroyEffect

    ability = TriggeredAbility(
        trigger_event="ENTERS_BATTLEFIELD",
        effects=[],
        modes=[
            {"effects": [GainLifeEffect(amount=3)], "description": "gain 3 life"},
            {"effects": [DrawCardEffect(count=1)], "description": "draw a card"},
        ],
        modes_or_both=True,
        modes_choose=1,
        controller_id="p1",
    )
    eng = make_engine(p1_library=[land(), land()])
    eng.begin_turn()
    p1 = eng.state.player_by_id("p1")
    life_before = p1.life
    hand_before = len(p1.hand)

    eng.rules.pending_triggers = [(ability, None)]
    eng.rules.put_triggers_on_stack()
    choice = eng.state.pending_choice
    assert {o["id"] for o in choice["options"]} == {"0", "1", "both"}

    eng.rules.resolve_trigger_mode_choice("both")
    assert eng.state.pending_choice is None
    eng.resolve_until_stable()
    assert p1.life == life_before + 3
    assert len(p1.hand) == hand_before + 1
