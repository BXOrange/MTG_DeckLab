"""ENG-35 — the general continuation primitive.

`14_` §3: the engine enumerated choice interactions because it could not
suspend and resume — 97 of `RulesEngine`'s 254 public methods were
`request_*`/`resolve_*_choice` pairs, dispatched by a 367-line
``if kind == …`` cascade. `game/continuations.py` replaced that with a
registry; `RulesEngine.open_choice`/`resolve_choice` are the two halves.

The load-bearing test here is `TestRegistryTotality`: **a choice may only be
asked if something can answer it.** That invariant is why this refactor
found a real bug — ``"scroll_rack"`` (MEC-43 round 4F) opened a
`pending_choice` the cascade had no branch for, so a live game's answer fell
through to the *search* resolver and raised. The board could reach a state no
input could leave, and only a test calling the private resolver directly kept
it off anyone's radar.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from mtg_analyzer.game import continuations
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

GAME_ROOT = Path(RulesEngine.__module__.replace(".", "/")).parent


def make_engine() -> GameEngine:
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def library(eng: GameEngine, count: int = 6, player_id: str = "p1"):
    player = eng.state.player_by_id(player_id)
    for i in range(count):
        card = Card(id=f"c{i}", name=f"Card {i}", type_line="Creature — Bear",
                    is_creature=True, power=2, toughness=2)
        player.add_to_zone(
            GameObject(card, owner_id=player_id, zone=Zone.LIBRARY), Zone.LIBRARY
        )
    return player


class TestRegistryWellFormedness:
    def test_the_registry_is_not_empty(self) -> None:
        assert len(continuations.CHOICE_HANDLERS) > 60

    @pytest.mark.parametrize("kind", sorted(continuations.CHOICE_HANDLERS))
    def test_handler_declares_a_known_answer_mode(self, kind: str) -> None:
        handler = continuations.CHOICE_HANDLERS[kind]
        assert handler.answer in continuations.ANSWER_MODES

    @pytest.mark.parametrize("kind", sorted(continuations.CHOICE_HANDLERS))
    def test_flag_handlers_declare_their_yes_value(self, kind: str) -> None:
        handler = continuations.CHOICE_HANDLERS[kind]
        assert (handler.answer == continuations.ANSWER_FLAG) == (handler.yes is not None)

    @pytest.mark.parametrize("kind", sorted(continuations.CHOICE_HANDLERS))
    def test_handler_cites_a_comprehensive_rules_passage(self, kind: str) -> None:
        # The registry is checkable against the rules rather than against a
        # naming convention — the same discipline `game/isa.py` applies to
        # the instruction set.
        rule = continuations.CHOICE_HANDLERS[kind].rule
        assert re.fullmatch(r"\d{3}(?:\.\d+[a-z]?)?", rule), (
            f"{kind} cites {rule!r}, which is not a CR passage"
        )

    @pytest.mark.parametrize("kind", sorted(continuations.CHOICE_HANDLERS))
    def test_handler_is_a_private_resume_method(self, kind: str) -> None:
        # The whole point of ENG-35 is that a choice's two halves stop being
        # public API. The public surface is `resolve_choice`, singular.
        name = continuations.CHOICE_HANDLERS[kind].func.__name__
        assert name.startswith("_resume_"), f"{kind} -> {name}"

    def test_registering_a_kind_twice_is_refused(self) -> None:
        existing = next(iter(continuations.CHOICE_HANDLERS))
        with pytest.raises(ValueError, match="already has a continuation"):
            continuations.choice(existing, rule="100")(lambda self, choice, answer: None)

    def test_a_flag_handler_without_a_yes_value_is_refused(self) -> None:
        with pytest.raises(ValueError, match="disagree"):
            continuations.choice(
                "a_kind_that_does_not_exist", answer=continuations.ANSWER_FLAG,
            )(lambda self, choice, answer: None)


class TestRegistryTotality:
    """Every choice kind the engine can open has a handler, and vice versa.

    This is the invariant Scroll Rack violated. It is checked two ways —
    statically against the kinds the source actually constructs, and
    dynamically by `RulesEngine.open_choice` refusing to open an
    unanswerable one.
    """

    @staticmethod
    def _kinds_opened_in_source() -> set[str]:
        """Every ``"kind": "<x>"`` literal inside an `open_choice` call."""
        kinds: set[str] = set()
        for path in Path(GAME_ROOT).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for block in re.findall(r"open_choice\(\{(.*?)\n\s*\}\)", text, re.S):
                found = re.search(r'"kind":\s*"([a-z_]+)"', block)
                if found:
                    kinds.add(found.group(1))
        return kinds

    def test_every_kind_the_source_opens_has_a_handler(self) -> None:
        opened = self._kinds_opened_in_source()
        assert opened, "no open_choice call sites found — has the shape changed?"
        unanswerable = sorted(opened - set(continuations.CHOICE_HANDLERS))
        assert not unanswerable, (
            f"{len(unanswerable)} choice kind(s) can be opened but not "
            f"answered: {unanswerable}. That is the Scroll Rack bug — the "
            f"board reaches a state no input can leave."
        )

    def test_nothing_sets_pending_choice_behind_open_choices_back(self) -> None:
        """The invariant is only worth having if it cannot be bypassed.

        `open_choice` refuses an unanswerable kind, but that check is worth
        nothing if a caller can assign `state.pending_choice` directly — which
        is exactly how Scroll Rack got in. Every construction site in `game/`
        goes through `open_choice`; the single assignment left is the one
        inside `open_choice` itself.
        """
        offenders: list[str] = []
        for path in Path(GAME_ROOT).rglob("*.py"):
            for n, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").split("\n"), 1
            ):
                if re.search(r"pending_choice\s*=\s*(?!None\b)\S", line):
                    # `open_choice`'s own body is the one legitimate writer.
                    if line.strip() == "self.state.pending_choice = choice":
                        continue
                    offenders.append(f"{path.name}:{n}: {line.strip()}")
        assert not offenders, (
            "pending_choice must only be set through `RulesEngine.open_choice`, "
            "which is what makes 'a choice can always be answered' checkable:\n  "
            + "\n  ".join(offenders)
        )

    def test_open_choice_refuses_an_unanswerable_kind(self) -> None:
        eng = make_engine()
        with pytest.raises(ValueError, match="unanswerable choice"):
            eng.rules.open_choice({"kind": "no_such_kind", "player_id": "p1"})
        assert eng.state.pending_choice is None

    def test_resolve_choice_refuses_an_unregistered_kind(self) -> None:
        eng = make_engine()
        # Set it directly, bypassing `open_choice`, to prove the answer side
        # fails closed too rather than guessing (the old cascade sent every
        # unknown kind to the *search* resolver).
        eng.state.pending_choice = {"kind": "no_such_kind", "player_id": "p1"}
        with pytest.raises(ValueError, match="no continuation registered"):
            eng.rules.resolve_choice("whatever")

    def test_resolve_choice_with_nothing_pending_is_an_error(self) -> None:
        eng = make_engine()
        with pytest.raises(ValueError, match="no pending choice"):
            eng.rules.resolve_choice("x")


class TestAnswerCoercion:
    """The half of answer handling that used to be inlined in the cascade."""

    def _handler(self, **kw) -> continuations.ChoiceHandler:
        return continuations.ChoiceHandler(
            kind="k", func=lambda *_: None, **kw
        )

    def test_str_mode_stringifies_and_declines_to_none(self) -> None:
        h = self._handler(answer=continuations.ANSWER_STR)
        assert continuations.coerce_answer(h, 5) == "5"
        assert continuations.coerce_answer(h, None) is None
        assert continuations.coerce_answer(h, "decline") is None

    def test_int_mode_parses_and_declines_to_none(self) -> None:
        h = self._handler(answer=continuations.ANSWER_INT)
        assert continuations.coerce_answer(h, "7") == 7
        assert continuations.coerce_answer(h, None) is None

    def test_a_declared_decline_value_replaces_none(self) -> None:
        # Tainted Pact declines to "take", Sylvan Library to "return":
        # declining those is a *choice*, not an abstention.
        h = self._handler(answer=continuations.ANSWER_STR, decline="take")
        assert continuations.coerce_answer(h, None) == "take"
        assert continuations.coerce_answer(h, "continue") == "continue"

    def test_flag_mode_is_true_only_for_its_yes_value(self) -> None:
        h = self._handler(answer=continuations.ANSWER_FLAG, yes="cast")
        assert continuations.coerce_answer(h, "cast") is True
        assert continuations.coerce_answer(h, "hand") is False
        assert continuations.coerce_answer(h, None) is False

    def test_int_required_mode_raises_on_a_decline(self) -> None:
        # `ring_bearer` / `intuition_choose` never offer a decline, and
        # coerced with a bare int() before ENG-35. Preserved rather than
        # quietly softened.
        h = self._handler(answer=continuations.ANSWER_INT_REQUIRED)
        assert continuations.coerce_answer(h, "3") == 3
        with pytest.raises(TypeError):
            continuations.coerce_answer(h, None)


class TestPublicSurfaceShrank:
    """ENG-35's exit criterion, as a test rather than a claim."""

    @staticmethod
    def _public_methods() -> list[str]:
        return [
            n for n in dir(RulesEngine)
            if not n.startswith("_") and callable(getattr(RulesEngine, n, None))
        ]

    def test_choice_plumbing_is_no_longer_public_api(self) -> None:
        leftovers = sorted(
            n for n in self._public_methods()
            if n != "resolve_choice" and (
                n.startswith("request_")
                or (n.startswith("resolve_") and n.endswith("_choice"))
            )
        )
        assert not leftovers, (
            f"{len(leftovers)} choice-plumbing method(s) are still public: "
            f"{leftovers}. The public surface for choices is `open_choice` "
            f"and `resolve_choice`."
        )

    def test_public_method_count_meets_the_target(self) -> None:
        # 14_ §6's metric for S1: 254 -> <= 170.
        count = len(self._public_methods())
        assert count <= 170, f"RulesEngine still exposes {count} public methods"

    def test_the_dispatcher_is_no_longer_a_cascade(self) -> None:
        source = inspect.getsource(GameEngine.resolve_pending_choice)
        # Strip the docstring first — it *describes* the cascade it replaced,
        # so a naive substring check on the whole source finds its own prose.
        body = source.split('"""')[-1]
        assert "if kind ==" not in body
        assert len(source.split("\n")) < 40


class TestChoicesStillWorkEndToEnd:
    """A couple of real choices driven the way a client drives them."""

    def test_a_dungeon_choice_resolves_through_the_general_path(self) -> None:
        eng = make_engine()
        player = library(eng)
        eng.rules.venture_into_the_dungeon(player)
        assert eng.state.pending_choice["kind"] == "choose_dungeon"
        eng.rules.resolve_choice("Lost Mine of Phandelver")
        assert player.dungeon.name == "Lost Mine of Phandelver"
        assert eng.state.pending_choice is None

    def test_scroll_rack_ordering_is_answerable_at_all(self) -> None:
        """The bug ENG-35 found: this kind had no dispatch branch.

        Before the registry, answering a ``scroll_rack`` choice fell through
        to the *search* resolver and raised ``no pending search choice to
        resolve`` — the prompt was unanswerable through the only entry point
        a client has.
        """
        eng = make_engine()
        player = library(eng, count=3)
        exiled = list(player.library)[:2]
        for obj in exiled:
            player.remove_from_zone(obj, Zone.LIBRARY)
            player.add_to_zone(obj, Zone.EXILE)
        eng.rules.open_scroll_rack_order_choice(
            player, [o.instance_id for o in exiled]
        )
        choice = eng.state.pending_choice
        assert choice is not None and choice["kind"] == "scroll_rack"
        # The client sends the option id as a string, as it does for every
        # other choice — this is the path that used to raise.
        eng.rules.resolve_choice(str(exiled[1].instance_id))
        assert eng.state.pending_choice is None
        assert not player.exile, "the exiled cards go back to the library"
        # `player.library[0]` is the *bottom* (`_finish_look_top` inserts a
        # bottomed card at 0 and appends a topped one), so the card picked
        # first is the topmost.
        assert player.library[-1] is exiled[1]


class TestIterationFrame:
    """ENG-35's structure-aware `deferred_effects` — what ENG-37 blocks on."""

    def test_a_tail_frame_is_still_the_default(self) -> None:
        # An entry with no `kind` key must keep working: that is every
        # existing parking site, and every snapshot taken before ENG-35.
        eng = make_engine()
        eng.state.deferred_effects.append({
            "effects": [], "targets": None, "target_groups": None,
        })
        assert eng.rules.resume_deferred_effects() is True
        assert not eng.state.deferred_effects

    def test_an_iteration_frame_runs_its_body_once_per_item(self) -> None:
        eng = make_engine()
        seen: list[object] = []

        class _Probe:
            target_specs: list = []
            source = None

            def apply(self, context, targets=None):
                seen.append(context.iteration_item)

        eng.rules.defer_iteration([_Probe()], ["a", "b", "c"])
        # One resume per item, the way `resolve_until_stable` drains it.
        while eng.rules.resume_deferred_effects():
            pass
        assert seen == ["a", "b", "c"]

    def test_the_iteration_item_does_not_leak_after_the_loop(self) -> None:
        eng = make_engine()

        class _Probe:
            target_specs: list = []
            source = None

            def apply(self, context, targets=None):
                pass

        eng.rules.defer_iteration([_Probe()], ["only"])
        while eng.rules.resume_deferred_effects():
            pass
        assert eng.rules.context.iteration_item is None

    def test_an_empty_item_list_parks_nothing(self) -> None:
        eng = make_engine()
        eng.rules.defer_iteration([], [])
        assert not eng.state.deferred_effects
