"""MEC-31 — RULE 702.172a Spree / RULE 702.120 Escalate.

Covers the whole pipeline the same way `test_modal_spells.py` does for RULE
700.2's plain modal blocks: the `gate.py`/`catalogue/modal.py` grammar that
recognises a bare "Spree" header followed by "+ <cost> — <body>" mode lines
(distinct from an ordinary "Choose one/N/or more —" header — every mode
prices *itself* rather than sharing one spell cost), the `AbilitySpec.modes
["mode_costs"]` IR (`parser/oracle/spec.py`), the binder that folds it onto
each `obj.spell_modes[i]["cost"]` (`game/binding/core.py`), and the
engine's own per-combination cost (`GameEngine._modal_extra_cost`, consulted
by `effective_cast_cost`/`can_cast`/`_auto_tap_for_cast_if_needed` and
surfaced by `_modal_cast_actions`/`_cast_action`). Escalate reuses the same
mode-selection machinery with a flat, already-parsed keyword cost instead
of `mode_costs` — no new parser grammar needed for it at all (`gate.py`'s
cost-bearing keyword table already claims "Escalate {N}" as a plain
parametric keyword once its reminder text is stripped).

Return the Favor (`Ojer cEDH`, MEC-31's own named card) is hand-authored in
`ability_catalogue.py` — its "change the target…" mode is the parser's own
already-built `change_target` handler output verbatim, but its "copy
target… spell, activated ability, or triggered ability" mode needs a real
targeted-ability-copy primitive this batch doesn't build (see that entry's
own docstring) — covered here by a dedicated end-to-end test using a
synthetic `Card` under that exact name, the same "no DB needed" style this
whole file uses.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import SpecValidationError


def creature(name="Bear", power=2, toughness=2, **kw):
    return Card(id=name, name=name, type_line=kw.pop("type_line", "Creature — Bear"),
                is_creature=True, power=power, toughness=toughness, **kw)


def spree_instant(name="Test Spree", oracle=None, mana_cost="{R}{R}", cmc=2):
    oracle = oracle or (
        "Spree (Choose one or more additional costs.)\n"
        "+ {1} — Destroy target creature.\n"
        "+ {2} — Destroy target artifact."
    )
    return Card(id=name, name=name, type_line="Instant", is_instant=True,
                mana_cost_string=mana_cost, converted_mana_cost=cmc, oracle_text=oracle)


def escalate_instant(name="Test Escalate", mana_cost="{1}{W}", cmc=2):
    oracle = (
        "Escalate {2}\n"
        "Choose one or more —\n"
        "• Target player gains 4 life.\n"
        "• Target player loses 2 life."
    )
    return Card(id=name, name=name, type_line="Instant", is_instant=True,
                mana_cost_string=mana_cost, converted_mana_cost=cmc, oracle_text=oracle,
                keywords=["Escalate"])


def make_engine(p1_library=()):
    return GameEngine.new_game(
        [("p1", "Alice", list(p1_library)), ("p2", "Bob", [])],
        starting_life=20, starting_hand=0,
    )


def _ready_main_phase(eng):
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng.state.active_player


def _in_hand(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller)
    eng.state.player_by_id(controller).add_to_zone(obj, Zone.HAND)
    return obj


def _put(eng, card, controller="p2"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


# -- Parser (gate.py / catalogue/modal.py) -----------------------------------


def test_spree_card_parses_as_modeled_with_mode_costs():
    card = spree_instant()
    result = parse_oracle(card)
    assert result.modeled
    spec = next(s for s in result.specs if s.modes is not None)
    assert spec.modes["at_least"] is True
    assert spec.modes["choose"] == 1
    assert spec.modes["mode_costs"] == ["{1}", "{2}"]
    assert len(spec.modes["options"]) == 2


def test_spree_with_one_unparseable_mode_stays_unmodeled():
    card = spree_instant(oracle=(
        "Spree (Choose one or more additional costs.)\n"
        "+ {1} — Destroy target creature.\n"
        "+ {2} — This is not a real effect body at all.\n"
    ))
    result = parse_oracle(card)
    assert not result.modeled


def test_escalate_card_parses_as_modeled_via_plain_modal_and_cost_keyword():
    # No new grammar needed at all — "choose one or more —" is the ordinary
    # RULE 700.2 header, and "Escalate {2}" is already a plain cost-bearing
    # keyword line once its reminder text is stripped.
    card = escalate_instant()
    result = parse_oracle(card)
    assert result.modeled
    spec = next(s for s in result.specs if s.modes is not None)
    assert spec.modes["at_least"] is True
    assert spec.modes.get("mode_costs") is None


def test_ability_spec_mode_costs_must_match_options_1to1():
    from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec
    with pytest.raises(SpecValidationError):
        AbilitySpec(
            "spell_effect", [],
            modes={
                "at_least": True, "choose": 1,
                "options": [[EffectSpec("draw", {"count": 1})], [EffectSpec("draw", {"count": 1})]],
                "descriptions": ["a", "b"],
                "mode_costs": ["{1}"],
            },
        ).validate()


def test_ability_spec_mode_costs_requires_choose_one_or_more():
    from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec
    with pytest.raises(SpecValidationError):
        AbilitySpec(
            "spell_effect", [],
            modes={
                "choose": 1,
                "options": [[EffectSpec("draw", {"count": 1})], [EffectSpec("draw", {"count": 1})]],
                "descriptions": ["a", "b"],
                "mode_costs": ["{1}", "{1}"],
            },
        ).validate()


# -- Binder (binding/core.py) ------------------------------------------------


def test_binder_attaches_per_mode_cost_from_mode_costs():
    eng = make_engine()
    obj = _in_hand(eng, spree_instant())
    bind_from_catalogue(obj)
    assert len(obj.spell_modes) == 2
    assert obj.spell_modes[0]["cost"] == "{1}"
    assert obj.spell_modes[1]["cost"] == "{2}"
    assert obj.spell_modes_at_least is True


# -- Engine: cast flow --------------------------------------------------------


def test_legal_actions_offers_one_locked_or_unlocked_action_per_combination():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    bear = _put(eng, creature("Bear"), controller="p2")
    # Mode 1 destroys "target artifact" (RULE 115.1c — artifacts only, not
    # any permanent), so it needs a real artifact on the board to be
    # target-legal; without one its lock reason would be "no valid target",
    # masking the mana-affordability check this test is about.
    _put(eng, Card(id="Sol Ring", name="Sol Ring", type_line="Artifact"),
         controller="p2")
    obj = _in_hand(eng, spree_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 3})  # {R}{R} base + {1} — exactly mode 0 alone
    actions = [a for a in eng.legal_actions(p1) if a.get("instance_id") == obj.instance_id]
    by_mode = {tuple(a["mode"]): a for a in actions}
    assert set(by_mode) == {(0,), (1,), (0, 1)}
    assert by_mode[(0,)]["modal_extra_cost"] == "{1}"
    # Mode 0 alone (destroy target creature — Bear is a legal target) is
    # affordable with exactly {R}{R}{1} in the pool.
    assert not by_mode[(0,)].get("locked")
    # Both modes together cost {R}{R}{1}{2} — one more than the pool holds.
    assert by_mode[(0, 1)]["locked"] is True
    assert by_mode[(0, 1)]["lock_reason"] == "Manakosten nicht bezahlbar"


def test_cast_spree_mode_pays_only_that_modes_extra_cost():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    bear = _put(eng, creature("Bear"), controller="p2")
    obj = _in_hand(eng, spree_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 3})
    eng.cast_spell(p1, obj, targets=[bear], mode=[0])
    assert p1.mana_pool.total() == 0
    eng.resolve_until_stable()
    assert bear not in eng.state.battlefield


def test_cast_both_spree_modes_sums_both_costs():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    bear = _put(eng, creature("Bear"), controller="p2")
    artifact = _put(eng, Card(id="Sol Ring", name="Sol Ring", type_line="Artifact"),
                     controller="p2")
    obj = _in_hand(eng, spree_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 5})  # {R}{R} + {1} + {2} == 5
    eng.cast_spell(p1, obj, targets=[bear, artifact], mode=[0, 1])
    assert p1.mana_pool.total() == 0
    eng.resolve_until_stable()
    assert bear not in eng.state.battlefield
    assert artifact not in eng.state.battlefield


def test_cast_both_spree_modes_fails_short_of_the_combined_cost():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    bear = _put(eng, creature("Bear"), controller="p2")
    artifact = _put(eng, Card(id="Sol Ring", name="Sol Ring", type_line="Artifact"),
                     controller="p2")
    obj = _in_hand(eng, spree_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 4})  # one short of {R}{R}{1}{2} == 5
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj, targets=[bear, artifact], mode=[0, 1])


def test_cast_with_no_mode_chosen_is_illegal():
    # RULE 702.172a: "one or more" — zero is never a legal selection.
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, spree_instant())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 5})
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj, mode=None)


def test_escalate_charges_the_flat_cost_once_per_mode_beyond_the_first():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    p2 = eng.state.player_by_id("p2")
    obj = _in_hand(eng, escalate_instant())
    bind_from_catalogue(obj)
    assert obj.spell_modes[0].get("cost") is None  # Escalate isn't per-mode-priced
    p1.mana_pool.add_many({"W": 1, "C": 3})  # {1}{W} base + one {2} escalate surcharge
    eng.cast_spell(p1, obj, targets=[p1, p2], mode=[0, 1])
    assert p1.mana_pool.total() == 0
    life_before = p1.life
    opp_life_before = p2.life
    eng.resolve_until_stable()
    assert p1.life == life_before + 4
    assert p2.life == opp_life_before - 2


# -- Hand-authored: Return the Favor (ability_catalogue.py) ------------------


def _return_the_favor_card():
    return Card(id="Return the Favor", name="Return the Favor", type_line="Instant",
                is_instant=True, mana_cost_string="{R}{R}", converted_mana_cost=2)


def test_return_the_favor_binds_two_priced_modes():
    eng = make_engine()
    obj = _in_hand(eng, _return_the_favor_card())
    bind_from_catalogue(obj)
    assert len(obj.spell_modes) == 2
    assert obj.spell_modes[0]["cost"] == "{1}"
    assert obj.spell_modes[1]["cost"] == "{1}"
    assert obj.spell_modes_at_least is True


def test_return_the_favor_change_target_mode_retargets_a_spell_on_the_stack():
    # `ChangeTargetEffect` has exactly one `TargetSpec` — the spell/ability
    # being retargeted, per RULE 115.4 — and computes the *new* target
    # itself (auto-applying when there's only one legal alternative, or
    # opening a ``change_target`` `pending_choice` otherwise), the same
    # shape `test_change_target_family.py`'s own end-to-end test uses.
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    bear = _put(eng, creature("Bear", toughness=4), controller="p2")
    other_bear = _put(eng, creature("OtherBear", toughness=4), controller="p2")
    shock = Card(id="Shock", name="Shock", type_line="Instant", is_instant=True,
                 mana_cost_string="{R}", converted_mana_cost=1,
                 oracle_text="~ deals 2 damage to any target.")
    shock_obj = _in_hand(eng, shock)
    bind_from_catalogue(shock_obj)
    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, shock_obj, targets=[bear])

    obj = _in_hand(eng, _return_the_favor_card())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 3})  # {R}{R} + {1} for the change-target mode alone
    eng.cast_spell(p1, obj, targets=[shock_obj], mode=[1])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "change_target"
    pick = next(o for o in choice["options"] if o["label"] == "OtherBear")
    eng.resolve_pending_choice(pick["id"])
    assert eng.state.pending_choice is None
    eng.resolve_until_stable()
    assert bear.damage_marked == 0
    assert other_bear.damage_marked == 2
