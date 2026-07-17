""""Choose one or more —"/"choose N or more —" modality (RULE 700.2,
Farewell-shaped) — the *variable*-count generalization of the fixed "choose
N —" modality (`test_modal_choose_n.py`). ``choose`` becomes a minimum
instead of an exact count, and any number of modes from that minimum up to
every mode may be picked. Covers the same pipeline layers `test_modal_
choose_n.py` does: the `gate.py` block grouper (bare spell header and
trigger-wrapped), `AbilitySpec.modes`'s new `at_least` field (mutually
exclusive with `or_both`), the binder (`obj.spell_modes_at_least`/
`TriggeredAbility.modes_at_least`), the engine's per-combination-size cast
offer (`game_engine.py`'s `_modal_cast_actions`/`_effects_for_mode`), and the
iterative `trigger_mode` choice (`rules_engine.py`) that now offers a "done"
option once the minimum is met instead of forcing every mode to be picked.

Engine-level tests use non-targeted (or same-target) modes to isolate the
mechanism itself, exactly like `test_modal_choose_n.py` already does; the
parser-level tests use real card text (Farewell's modal block) to prove
recognition, separately from full castability.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.effects import DrawCardEffect, GainLifeEffect, MillEffect, TriggeredAbility
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec, SpecValidationError


def creature(name="Source"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2)


def land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def choose_one_or_more_of_four_instant(name="Test Sweep"):
    # Four untargeted modes (draw / gain life / mill / draw again) so the
    # engine-level tests exercise the choose-N-or-more combining logic
    # without tripping the pre-existing shared-targets-list limitation.
    oracle = (
        "Choose one or more —\n"
        "• Draw a card.\n"
        "• You gain 3 life.\n"
        "• Mill two cards.\n"
        "• Draw a card."
    )
    return Card(id=name, name=name, type_line="Instant", is_instant=True,
                mana_cost_string="{1}{U}", converted_mana_cost=2, oracle_text=oracle)


def choose_two_or_more_of_four_instant(name="Test Big Sweep"):
    oracle = (
        "Choose two or more —\n"
        "• Draw a card.\n"
        "• You gain 3 life.\n"
        "• Mill two cards.\n"
        "• Draw a card."
    )
    return Card(id=name, name=name, type_line="Instant", is_instant=True,
                mana_cost_string="{1}{U}", converted_mana_cost=2, oracle_text=oracle)


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


def test_choose_one_or_more_header_is_recognized():
    card = Card(id="T", name="T", type_line="Instant", is_instant=True,
                oracle_text="Choose one or more —\n• Draw a card.\n• Gain 3 life.\n• Mill two cards.")
    r = parse_oracle(card)
    assert r.coverage == MODELED
    (spec,) = r.specs
    assert spec.modes["choose"] == 1
    assert spec.modes["at_least"] is True
    assert spec.modes["or_both"] is False
    assert len(spec.modes["options"]) == 3


def test_choose_two_or_more_header_is_recognized():
    card = Card(id="T", name="T", type_line="Instant", is_instant=True,
                oracle_text="Choose two or more —\n• Draw a card.\n• Gain 3 life.\n"
                            "• Mill two cards.\n• You gain 1 life.")
    r = parse_oracle(card)
    assert r.coverage == MODELED
    (spec,) = r.specs
    assert spec.modes["choose"] == 2
    assert spec.modes["at_least"] is True


def test_ordinary_choose_n_still_defaults_at_least_to_false():
    # Regression guard: the fixed-count "choose two —" shape must not pick
    # up at_least just because the field now exists.
    card = Card(id="T", name="T", type_line="Instant", is_instant=True,
                oracle_text="Choose two —\n• Draw a card.\n• Gain 3 life.\n• Mill two cards.")
    r = parse_oracle(card)
    assert r.coverage == MODELED
    (spec,) = r.specs
    assert spec.modes["at_least"] is False


def test_choose_n_or_more_exceeding_mode_count_stays_unclaimed():
    card = Card(id="T", name="T", type_line="Instant", is_instant=True,
                oracle_text="Choose three or more —\n• Draw a card.\n• Gain 3 life.")
    r = parse_oracle(card)
    assert r.coverage != MODELED


def test_choose_one_or_more_triggered_ability_is_recognized():
    card = Card(id="Permanent", name="Permanent", type_line="Creature — Giant",
                is_creature=True, power=4, toughness=4,
                oracle_text="When this creature enters, choose one or more —\n"
                            "• Draw a card.\n• Gain 3 life.\n• Mill two cards.")
    r = parse_oracle(card)
    assert r.coverage == MODELED
    (spec,) = r.specs
    assert spec.ability_kind == "triggered"
    assert spec.modes["choose"] == 1
    assert spec.modes["at_least"] is True


def test_farewell_shaped_header_is_recognized():
    # Farewell's real header ("Choose one or more —" over four modes) proves
    # this handler's header/block-grouper recognition; its actual mode
    # bodies ("Exile all artifacts.", etc.) are a mass "exile all"/"destroy
    # all" effect shape no existing one-shot handler claims yet — a
    # separate, pre-existing coverage gap unrelated to the choose-N-or-more
    # grammar this test targets — so known-good mode bodies stand in here,
    # same as `test_modal_choose_n.py`'s synthetic combinations.
    card = Card(id="Farewell", name="Farewell", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{4}{W}{W}",
                oracle_text="Choose one or more —\n"
                            "• Draw a card.\n"
                            "• You gain 3 life.\n"
                            "• Mill two cards.\n"
                            "• You gain 1 life.")
    r = parse_oracle(card)
    assert r.coverage == MODELED
    (spec,) = r.specs
    assert spec.modes["choose"] == 1
    assert spec.modes["at_least"] is True
    assert len(spec.modes["options"]) == 4


def test_spec_validation_rejects_or_both_and_at_least_together():
    with pytest.raises(SpecValidationError):
        AbilitySpec(
            "spell_effect", effects=[],
            modes={"or_both": True, "at_least": True, "choose": 1,
                   "options": [[EffectSpec("draw", {"count": 1})],
                               [EffectSpec("gain_life", {"amount": 1})]]},
        ).validate()


def test_spec_validation_rejects_choose_out_of_range_with_at_least():
    with pytest.raises(SpecValidationError):
        AbilitySpec(
            "spell_effect", effects=[],
            modes={"at_least": True, "choose": 5,
                   "options": [[EffectSpec("draw", {"count": 1})],
                               [EffectSpec("gain_life", {"amount": 1})]]},
        ).validate()


# ---------------------------------------------------------------------------
# Engine: modal spell casting (choose one-or-more / two-or-more of four)
# ---------------------------------------------------------------------------


def test_legal_actions_offers_every_combination_size_from_choose_up():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_one_or_more_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    actions = [a for a in eng.legal_actions(p1) if a.get("instance_id") == obj.instance_id]
    # sum_{k=1}^{4} C(4, k) = 4 + 6 + 4 + 1 = 15.
    assert len(actions) == 15
    sizes = sorted(len(a["mode"]) for a in actions)
    assert sizes == [1] * 4 + [2] * 6 + [3] * 4 + [4] * 1
    modes = {tuple(a["mode"]) for a in actions}
    assert (0,) in modes
    assert (0, 1, 2, 3) in modes


def test_legal_actions_respects_a_two_mode_minimum():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_two_or_more_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    actions = [a for a in eng.legal_actions(p1) if a.get("instance_id") == obj.instance_id]
    # sum_{k=2}^{4} C(4, k) = 6 + 4 + 1 = 11 — no single-mode action offered.
    assert len(actions) == 11
    assert all(len(a["mode"]) >= 2 for a in actions)


def test_cast_with_single_mode_succeeds_when_minimum_is_one():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_one_or_more_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    life_before = p1.life

    eng.cast_spell(p1, obj, mode=[1])  # just "gain 3 life"
    eng.resolve_until_stable()

    assert p1.life == life_before + 3


def test_cast_below_minimum_raises():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_two_or_more_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj, mode=[0])  # choose is a minimum of 2


def test_cast_with_duplicate_index_raises():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_one_or_more_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj, mode=[1, 1])


def test_cast_with_out_of_range_index_raises():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_one_or_more_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj, mode=[0, 9])


def test_cast_with_every_mode_selected_applies_them_all():
    # 2 lands drawn (both "draw a card" modes) + 2 milled — needs 4+ library.
    eng = make_engine(p1_library=[land(), land(), land(), land(), land()])
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_one_or_more_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    life_before = p1.life
    hand_before = len(p1.hand) - 1  # excluding the spell itself
    library_before = len(p1.library)

    eng.cast_spell(p1, obj, mode=[0, 1, 2, 3])
    eng.resolve_until_stable()

    assert p1.life == life_before + 3
    assert len(p1.library) == library_before - 4  # 2 drawn + 2 milled
    assert len(p1.hand) == hand_before + 2  # both "draw a card" modes
    assert obj.spell_effects == []  # temporary swap cleaned up


def test_mode_description_joins_chosen_combination():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, choose_one_or_more_of_four_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    actions = [a for a in eng.legal_actions(p1) if a.get("instance_id") == obj.instance_id]
    action = next(a for a in actions if tuple(a["mode"]) == (1, 2))
    assert action["mode_description"] == "you gain 3 life. + mill 2 cards."


# ---------------------------------------------------------------------------
# Engine: modal triggered ability, iterative trigger_mode choice + "done"
# ---------------------------------------------------------------------------


def _choose_one_or_more_etb_trigger(source):
    """A "When ~ enters, choose one or more —" ability with four untargeted
    modes — exercises the iterative accumulate-then-stop `trigger_mode`
    choice, mirroring `test_modal_choose_n.py`'s `_choose_two_etb_trigger`
    construction pattern."""
    return TriggeredAbility(
        trigger_event="ENTERS_BATTLEFIELD",
        effects=[],
        modes=[
            {"effects": [DrawCardEffect(count=1)], "description": "draw a card"},
            {"effects": [GainLifeEffect(amount=3)], "description": "gain 3 life"},
            {"effects": [MillEffect(count=2)], "description": "mill two cards"},
            {"effects": [GainLifeEffect(amount=1)], "description": "gain 1 life"},
        ],
        modes_choose=1,
        modes_at_least=True,
        controller_id=source.controller_id,
        source=source,
        description="modal ETB trigger (choose one or more)",
    )


def _choose_two_or_more_etb_trigger(source):
    ability = _choose_one_or_more_etb_trigger(source)
    ability.modes_choose = 2
    ability.description = "modal ETB trigger (choose two or more)"
    return ability


def test_first_round_does_not_offer_done_before_minimum_is_met():
    eng = make_engine()
    eng.begin_turn()
    source = _put(eng, creature())
    eng.rules.pending_triggers = [(_choose_one_or_more_etb_trigger(source), None)]
    eng.rules.put_triggers_on_stack()

    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_mode"
    assert "done" not in {o["id"] for o in choice["options"]}


def test_second_round_offers_done_once_minimum_of_one_is_met():
    eng = make_engine()
    eng.begin_turn()
    source = _put(eng, creature())
    eng.rules.pending_triggers = [(_choose_one_or_more_etb_trigger(source), None)]
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_trigger_mode_choice("1")  # pick "gain 3 life" first

    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_mode"
    assert {o["id"] for o in choice["options"]} == {"0", "2", "3", "done"}


def test_choosing_done_stops_and_combines_only_the_picked_modes():
    eng = make_engine(p1_library=[land(), land()])
    eng.begin_turn()
    p1 = eng.state.player_by_id("p1")
    source = _put(eng, creature())
    life_before = p1.life
    hand_before = len(p1.hand)

    eng.rules.pending_triggers = [(_choose_one_or_more_etb_trigger(source), None)]
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_trigger_mode_choice("1")  # gain 3 life
    eng.rules.resolve_trigger_mode_choice("done")

    assert eng.state.pending_choice is None
    assert len(eng.state.stack) == 1
    eng.resolve_until_stable()
    assert p1.life == life_before + 3
    assert len(p1.hand) == hand_before  # "draw a card" was never picked


def test_never_choosing_done_runs_through_every_mode():
    # 1 land drawn ("draw a card") + 2 milled — needs 3+ library.
    eng = make_engine(p1_library=[land(), land(), land(), land()])
    eng.begin_turn()
    p1 = eng.state.player_by_id("p1")
    source = _put(eng, creature())
    life_before = p1.life
    library_before = len(p1.library)
    hand_before = len(p1.hand)

    eng.rules.pending_triggers = [(_choose_one_or_more_etb_trigger(source), None)]
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_trigger_mode_choice("1")
    eng.rules.resolve_trigger_mode_choice("2")
    eng.rules.resolve_trigger_mode_choice("0")
    eng.rules.resolve_trigger_mode_choice("3")  # last one — auto-finalizes

    assert eng.state.pending_choice is None
    eng.resolve_until_stable()
    assert p1.life == life_before + 3 + 1
    assert len(p1.library) == library_before - 3  # 1 drawn + 2 milled
    assert len(p1.hand) == hand_before + 1


def test_done_is_deferred_until_a_two_mode_minimum_is_met():
    eng = make_engine()
    eng.begin_turn()
    source = _put(eng, creature())
    eng.rules.pending_triggers = [(_choose_two_or_more_etb_trigger(source), None)]
    eng.rules.put_triggers_on_stack()

    choice = eng.state.pending_choice
    assert "done" not in {o["id"] for o in choice["options"]}  # 0 picked, need 2

    eng.rules.resolve_trigger_mode_choice("0")
    choice = eng.state.pending_choice
    assert "done" not in {o["id"] for o in choice["options"]}  # 1 picked, still need 2

    eng.rules.resolve_trigger_mode_choice("1")
    choice = eng.state.pending_choice
    assert "done" in {o["id"] for o in choice["options"]}  # 2 picked — minimum met
