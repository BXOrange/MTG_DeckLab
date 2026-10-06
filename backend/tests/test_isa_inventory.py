"""ENG-34 — the atom inventory is complete, consistent, and CR-grounded.

`game/isa.py` is pure data, so nothing here exercises behaviour. What it
guards is that the data stays *true*: the whole point of the inventory is to
be wrong loudly. Adding an effect type without classifying it, proposing a
composition operator with no fusions behind it, or pointing a classification
at an instruction that does not exist all fail here rather than rotting into
a stale document.

The corpus check (`13_` §5.6(b), ENG-34's exit criterion) runs against the
list frozen in `isa.TOP_CORPUS_OPERATIONS`; re-derive that with
`scripts/isa_report.py --corpus` after a coverage run.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from mtg_analyzer.game import isa
from mtg_analyzer.game.effects import EffectRegistry

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class TestTotality:
    """Every registered type is classified, and nothing classified is stale."""

    def test_every_registered_effect_type_is_classified(self) -> None:
        unclassified = sorted(set(EffectRegistry._factories) - set(isa.EFFECT_TYPES))
        assert not unclassified, (
            f"{len(unclassified)} effect type(s) registered without an ENG-34 "
            f"classification: {unclassified}. Add each to exactly one table in "
            f"game/isa.py — deciding whether a new type is an instruction, a "
            f"fusion, an alias or a continuation is the point of the "
            f"inventory, and 13_'s standing gate is that the enumerated row "
            f"count must not grow unexamined."
        )

    def test_no_classification_names_a_dead_effect_type(self) -> None:
        stale = sorted(set(isa.EFFECT_TYPES) - set(EffectRegistry._factories))
        assert not stale, (
            f"game/isa.py classifies {len(stale)} type(s) that are no longer "
            f"registered: {stale}"
        )

    def test_a_type_is_classified_exactly_once(self) -> None:
        # `_build_effect_types` raises on a duplicate, so importing the module
        # at all proves this. Asserting it explicitly keeps the guarantee
        # visible when someone reorganises the tables.
        assert len(isa.EFFECT_TYPES) == len(set(isa.EFFECT_TYPES))
        assert len(isa.EFFECT_TYPES) == len(EffectRegistry._factories)


class TestInstructionSet:
    """The ISA itself: CR-grounded names, real frames."""

    def test_every_instruction_declares_a_non_empty_frame(self) -> None:
        frameless = sorted(n for n, i in isa.INSTRUCTIONS.items() if not i.frame)
        assert not frameless, (
            f"instructions without an argument frame: {frameless}. A frame is "
            f"axis 2 of the factoring (14_ §2); an instruction without one is "
            f"the opaque row the inventory exists to replace."
        )

    def test_every_frame_role_is_in_the_shared_vocabulary(self) -> None:
        for name, instruction in isa.INSTRUCTIONS.items():
            unknown = [r for r in instruction.frame if r not in isa.ROLES]
            assert not unknown, f"{name} declares unknown role(s) {unknown}"

    def test_a_frame_does_not_repeat_a_role(self) -> None:
        for name, instruction in isa.INSTRUCTIONS.items():
            assert len(set(instruction.frame)) == len(instruction.frame), (
                f"{name}'s frame repeats a role: {instruction.frame}"
            )

    def test_every_instruction_cites_a_comprehensive_rules_passage(self) -> None:
        # The ISA is derived from the CR rather than from this engine's own
        # method list — that is what makes the CR-versus-engine diff (the
        # systematically-generated MEC backlog, 14_ §7) meaningful.
        bad = sorted(
            n for n, i in isa.INSTRUCTIONS.items()
            if not re.fullmatch(r"\d{3}(?:\.\d+[a-z]?)?", i.rule)
        )
        assert not bad, f"instructions with a malformed RULE citation: {bad}"

    def test_the_701_keyword_actions_are_all_present(self) -> None:
        # RULE 701.2-701.70 is the spine of the ISA. Read off the CR text
        # itself so a rules update that adds a keyword action shows up here
        # rather than being silently missing.
        cr = BACKEND_ROOT.parent / "docs" / "Reference" / "MagicCompRules 20260807.txt"
        if not cr.exists():  # pragma: no cover - the CR text ships with the repo
            pytest.skip("Comprehensive Rules text not present")
        # 701.1 is prose introducing the section, not an action; every
        # later subrule heads one keyword action. "Tap and Untap" is a
        # single heading for two instructions, which is why the ISA lists
        # them separately against the same rule number.
        numbers = [
            n for n in re.findall(
                r"^701\.(\d+)\. \S",
                cr.read_text(encoding="utf-8", errors="replace"),
                re.M,
            )
            if n != "1"
        ]
        assert len(numbers) >= 69, (
            f"only {len(numbers)} RULE 701 keyword-action headings found — "
            f"has the CR text moved?"
        )
        by_rule = {i.rule for i in isa.INSTRUCTIONS.values()}
        missing = [f"701.{n}" for n in numbers if f"701.{n}" not in by_rule]
        assert not missing, (
            f"RULE 701 keyword actions with no ISA instruction: {missing}. "
            f"14_ §7: this diff is the systematically-generated MEC backlog."
        )


class TestClassifications:
    """Each label's own invariants."""

    def test_instructions_and_aliases_name_a_real_instruction(self) -> None:
        for name, entry in isa.EFFECT_TYPES.items():
            if entry.classification in (
                isa.Classification.INSTRUCTION, isa.Classification.ALIAS
            ):
                assert entry.instruction in isa.INSTRUCTIONS, (
                    f"{name} is classified {entry.classification.value} against "
                    f"unknown instruction {entry.instruction!r}"
                )

    def test_a_fusion_welds_real_instructions_and_names_an_operator(self) -> None:
        for name, entry in isa.EFFECT_TYPES.items():
            if entry.classification is not isa.Classification.FUSION:
                continue
            assert entry.parts, f"{name} is a fusion of nothing"
            unknown = [p for p in entry.parts if p not in isa.INSTRUCTIONS]
            assert not unknown, f"{name} welds unknown instruction(s) {unknown}"
            assert entry.operator in isa.OPERATORS, (
                f"{name} names unknown composition operator {entry.operator!r}"
            )

    def test_only_instructions_and_aliases_carry_an_instruction(self) -> None:
        for name, entry in isa.EFFECT_TYPES.items():
            if entry.classification in (
                isa.Classification.INSTRUCTION, isa.Classification.ALIAS
            ):
                continue
            assert entry.instruction is None, (
                f"{name} is {entry.classification.value} but names instruction "
                f"{entry.instruction!r}"
            )

    def test_only_fusions_and_compositions_name_an_operator(self) -> None:
        # A fusion names the operator that *retires* it; a composition node
        # names the operator it *is* (ENG-37). Nothing else may claim one, and
        # only a fusion welds `parts`.
        for name, entry in isa.EFFECT_TYPES.items():
            if entry.classification is isa.Classification.FUSION:
                continue
            assert not entry.parts, f"{name}"
            if entry.classification is isa.Classification.COMPOSITION:
                assert entry.operator in isa.OPERATORS, f"{name}"
            else:
                assert entry.operator is None, f"{name}"

    def test_every_operator_has_exactly_one_composition_type(self) -> None:
        # The five nodes are axis 3 itself: an operator with no node cannot
        # retire the fusions that name it, and two nodes for one operator
        # would mean the axis had grown a second spelling.
        by_operator: dict[str, list[str]] = {op: [] for op in isa.OPERATORS}
        for name, entry in isa.EFFECT_TYPES.items():
            if entry.classification is isa.Classification.COMPOSITION:
                by_operator[str(entry.operator)].append(name)
        assert all(len(names) == 1 for names in by_operator.values()), by_operator

    def test_out_of_stream_labels_stay_out_of_the_isa(self) -> None:
        # 14_ §1.1: a RULE 613 static is a continuously re-derived constraint
        # and a RULE 614 replacement is event middleware. Neither is ever
        # executed as an instruction, so neither may claim one — getting this
        # wrong is what would put ~4,000 lines of grammar in the wrong layer.
        for name, entry in isa.EFFECT_TYPES.items():
            if entry.classification in (
                isa.Classification.STATIC, isa.Classification.REPLACEMENT
            ):
                assert entry.instruction is None and not entry.parts, (
                    f"{name} is {entry.classification.value} but claims "
                    f"instruction-stream structure"
                )


class TestOperatorsAreJustified:
    """The shipped composition vocabulary has one registered node per operator."""

    @pytest.mark.parametrize("operator", isa.OPERATORS)
    def test_operator_retires_at_least_one_fusion(self, operator: str) -> None:
        # `_FUSION_TYPES` is now empty — ENG-37 fully retired every fusion — so an
        # operator's justification is that it is a real, registered composition
        # primitive (`game/effects/composition.py`) rather than a speculative one
        # with no fusions left to justify it against.
        assert operator in isa.types_classified(isa.Classification.COMPOSITION)

    def test_every_fusion_is_claimed_by_exactly_one_operator(self) -> None:
        assert not isa.types_classified(isa.Classification.FUSION)


class TestCorpusExitCriterion:
    """ENG-34's exit: the top-50 corpus operations are all framed instructions.

    This is `14_`'s cheap-exit checkpoint made executable — the design says
    the whole programme should be abandoned here if operand frames do not
    canonicalize.
    """

    def test_frozen_top_operations_are_the_measured_fifty(self) -> None:
        assert len(isa.TOP_CORPUS_OPERATIONS) == 50
        assert len(set(isa.TOP_CORPUS_OPERATIONS)) == 50

    @pytest.mark.parametrize("operation", isa.TOP_CORPUS_OPERATIONS)
    def test_top_corpus_operation_has_a_framed_instruction(
        self, operation: str
    ) -> None:
        instruction = isa.INSTRUCTIONS.get(operation)
        assert instruction is not None, (
            f"corpus operation {operation!r} has no ISA instruction — either "
            f"add one or, per 14_'s checkpoint, the atom layer does not "
            f"canonicalize and S3/S4 lose their footing."
        )
        assert instruction.frame, f"{operation!r} has an instruction but no frame"


class TestBacklogSizes:
    """The counts the downstream tickets are judged on, pinned.

    Not a coverage metric — `14_` §6 is explicit that S0/S1 should move
    coverage by zero. These are the numbers ENG-35 and ENG-37 shrink, so
    they are asserted as *upper* bounds: the inventory getting smaller is
    progress and must not fail the suite, the enumeration growing must.
    """

    def test_continuation_backlog_does_not_grow(self) -> None:
        # ENG-35 retires these onto one continuation primitive. Bumped 74 -> 81:
        # not new work, but 7 pre-existing registered types (Avacyn's chosen-colour
        # prevention, Garnet's Saga-counter choice, Ancient Brass Dragon's any-number
        # graveyard return, …) that had never been classified at all, found while
        # closing the `test_every_registered_effect_type_is_classified` gap. MEC-106
        # adds Gift's permanent-ETB continuation (`gift_give`), hence 81 -> 82.
        # MEC-108 adds the enter-choice `choose_enter_counter` ("enters with your
        # choice of a flying counter or …", an `enter_choice_effects` sibling), 82 -> 83.
        n = len(isa.types_classified(isa.Classification.CONTINUATION))
        # Squirreled Away adds five resolution adapters (83 -> 88): conditional
        # death copies, mill/recover/bonus, graveyard-paid repetition and
        # sacrifice-or-discard. They delegate to existing replacement and
        # choose_objects/optional frames; no new answer protocol is introduced.
        # PLAY-ALL adds the pre-entry player choice and Victimize's
        # sacrifice/target linkage; both reuse existing answer protocols.
        # Multi-player discard-or-sacrifice collects choices before moving cards.
        # Hideaway adds one reviewed adapter to the shared immediate-play
        # frame: it preserves linked identities and ordinary cast choices
        # under RULE 607.3/608.2g (tests/test_hideaway_lands.py).
        # Disorienting Choice (Jump Scare!) adds one: a three-stage choose/exile/search continuation over the
        # same `choose_objects` frames (`ChoosePlayerObjectsEffect`'s idiom), 92 -> 93.
        # Abzan Armor adds two more over the same frames: `choose_number_then` (a resolution-time "choose a number",
        # Expel the Interlopers) and `slaughter_the_strong` (a per-player power-budget partition), 93 -> 95.
        # Miracle Worker adds two over the same chooser frames: `aminatous_augury` (exile eight, an optional land, a
        # free cast per nonland card type) and `sacrifice_shared_type_to_return` (Victimize's sacrifice/return linkage
        # for Spirit-Sister's Call), 95 -> 97.
        # Death Toll adds one: `exile_selected_then_return_one` (Winter, Cynical Opportunist — judge a selected graveyard
        # set, exile it, then choose the permanent card that returns with a finality counter), 97 -> 98.
        # Sans Soleil adds three reviewed adapters over existing suspension/entry
        # frames: sacrifice-source/rider, revealed-creature recipients, and
        # hand exile with turn-scoped play/draw plus delayed return. Scry/draw
        # and Tezzeret's counter/animation sequences remain composed atoms.
        # A generic revealed-pile split/take adapter adds one reviewed continuation:
        # it retains library identities and lets distinct players divide and take piles.
        # Multiverse Reforged adds three reviewed player-choice adapters over the existing choice frames:
        # `choose_card_type_on_enter` (the card-type sibling of the creature-type/colour enter choices, Serra's
        # Emissary), `choose_hand_card_to_library_bottom` (a `choose_objects` hand pick, Jace's +1) and
        # `owner_puts_on_top_or_bottom` (the target's owner chooses the library end, Plan for All Outcomes), 102 -> 105.
        # Turtle Power adds two reviewed adapters over existing choose_objects frames:
        # mill/recover-to-battlefield and optional host sacrifice/draw with saved power.
        assert n <= 107, f"continuation types grew to {n}"

    def test_fusion_backlog_does_not_grow(self) -> None:
        # ENG-37 deletes these outright.
        n = len(isa.types_classified(isa.Classification.FUSION))
        assert n == 0, f"ENG-37 leaves fusion types behind: {n}"

    def test_one_card_special_residue_does_not_grow(self) -> None:
        # 57 -> 58: PAR-135's `action_stamp`, the record half of "Do this only once each turn." It is engine
        # bookkeeping (no Comprehensive Rules action decomposes into it), so it is the honest residue rather
        # than an `INSTRUCTIONS` entry — examined, not a stray.
        n = len(isa.types_classified(isa.Classification.SPECIAL))
        # Living Death tracks its exile batch across three simultaneous actions.
        # Shorikai Vehicles adds two bookkeeping types: `crewed_event` (RULE 702.122e's "becomes crewed" event) and
        # `transfer_exiled_with_to_created` (Mechtitan Core's exiled-with link), 59 -> 61. Endless Punishment adds
        # `exile_self_with_counters` (Suspended Sentence's "Exile ~ with three time counters on it"), 61 -> 62.
        # Revival Trance adds the reviewed cross-zone artifact-only copy adapter
        # for Espers to Magicite. Its documented automatic selection remains a
        # card-specific limitation; the copy itself uses Card.as_copy's type mask.
        assert n <= 63, f"one-card specials grew to {n}"
