"""ENG-35 — the general continuation: ask a player, then resume.

Design: [docs/concepts/14_PARSER_GRAMMAR_DESIGN.md] stage S1. `14_` §3 named
this the parser's disease one layer down: the parser enumerates clause
combinations because it cannot compose; the engine enumerated *choice*
interactions because it had no way to suspend and resume. **97 of
`RulesEngine`'s 254 public methods (38%) were `request_*`/`resolve_*_choice`
pairs** — one hand-written syscall pair per blocking question, dispatched by
a 368-line ``if kind == …`` cascade in `GameEngine.resolve_pending_choice`.

Reading those 68 resolvers shows they were never 68 different things. Every
one opened with the identical preamble::

    choice = self.state.pending_choice
    if not choice or choice.get("kind") != "<kind>":
        raise ValueError("no pending <x> choice to resolve")
    self.state.pending_choice = None

and the *answer normalization* for each was split across two files — the
dispatcher decided what a decline meant (``None if declined else str(answer)``)
while the resolver decided what an invalid answer meant ("default to the
first option"). Two halves of one rule, a file apart, written out 68 times.

This module is the missing primitive. A choice kind registers **one
handler**; `RulesEngine.resolve_choice` claims the pending choice, coerces
the answer, and calls it. The cascade is gone, the preamble is gone, and
answer handling has one home.

What this is *not*
------------------
It is deliberately **not** a new resumption mechanism, per this repo's own
rule about citing an existing primitive rather than proposing one. Two
already exist and both are untouched:

* `RulesEngine.enqueue_reflexive_trigger` (`game/rules/misc_mixin.py`) —
  MEC-69's "…**when you do**, `<targeted payoff>`". A trigger on the stack
  *is* a resumable continuation with correct RULE 115 target selection, and
  it stays the way a handler runs a payoff that needs targets.
* `GameState.deferred_effects` — RULE 608.2 suspension of the *rest of a
  resolution* while a choice is open, drained by
  `RulesEngine.resume_deferred_effects`.

Those answer "how does the game resume". This module answers "how does an
*answer* find its handler", which is the part that was written out by hand.

Registration
------------
Handlers stay methods on the subsystem mixin that owns them
(`search_mixin`, `triggers_mixin`, …) — ENG-20/21 split those on purpose and
hauling 3,400 lines into one module would undo it. The decorator records the
unbound function, and because every mixin is imported when `rules_engine`
is, the registry is complete by the time anything can ask it a question.

`tests/test_continuations.py` asserts the registry is **total**: every choice
kind the engine can open has a handler. That test would have caught a bug
this refactor found — ``"scroll_rack"`` (MEC-43 round 4F) opened a real
`pending_choice` that `resolve_pending_choice` had no branch for, so the
answer fell through to the search resolver and raised. Scroll Rack was
unanswerable in a live game; only a test calling the private resolver
directly hid it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

#: How a handler reads the raw answer that arrived from the client.
#:
#: The wire answer is always the chosen option's ``id`` as a string (or
#: ``None`` / ``"decline"`` to decline) — see
#: `GameEngine.resolve_pending_choice`'s own docstring. These modes are the
#: coercions the old dispatcher applied inline, named once instead of 68
#: times.
#:
#: ``ANSWER_INT_REQUIRED`` exists because two choices (`ring_bearer`,
#: `intuition_choose`) coerced with a bare ``int(answer)`` and so *raise* on
#: a decline rather than accepting one. That is correct — neither offers a
#: decline option — and it is preserved rather than quietly softened.
ANSWER_STR = "str"
ANSWER_INT = "int"
ANSWER_INT_REQUIRED = "int_required"
ANSWER_FLAG = "flag"

ANSWER_MODES: frozenset[str] = frozenset(
    {ANSWER_STR, ANSWER_INT, ANSWER_INT_REQUIRED, ANSWER_FLAG}
)

#: The wire value meaning "I decline" (alongside a missing answer).
DECLINE = "decline"


@dataclass(frozen=True)
class ChoiceHandler:
    """One choice kind's continuation: how to read its answer, and who resumes.

    ``func`` is the unbound method ``(rules, choice, answer) -> None``. It is
    handed the *already claimed* choice dict — `RulesEngine.resolve_choice`
    has cleared `GameState.pending_choice` before calling, so a handler that
    re-opens a choice (a multi-pick loop, a two-stage search) simply opens a
    fresh one rather than having to clear the old one first.
    """

    kind: str
    func: Callable[..., None]
    answer: str = ANSWER_STR
    #: `ANSWER_FLAG` only: the option id that means "yes". Every other id,
    #: and a decline, is "no".
    yes: Optional[str] = None
    #: What a decline coerces to. ``None`` for almost everything; two
    #: choices declare a real fallback answer instead, because declining
    #: them is a *choice* rather than an abstention — Tainted Pact's
    #: decline means "take the card" and Sylvan Library's means "put it
    #: back".
    decline: Any = None
    #: The Comprehensive Rules passage the choice comes from, so the
    #: registry is checkable against the rules rather than against a naming
    #: convention.
    rule: str = ""


#: Every registered choice kind. Populated by `@choice` at import time.
CHOICE_HANDLERS: dict[str, ChoiceHandler] = {}


def choice(
    *kinds: str,
    answer: str = ANSWER_STR,
    yes: Optional[str] = None,
    decline: Any = None,
    rule: str = "",
) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """Register the decorated method as the continuation for ``kinds``.

    Several kinds may share one handler where the rules genuinely give them
    the same shape — RULE 601.2b's "choose a creature type / a colour / a
    basic land type / a card name / a number" is one decision with different
    answer spaces, and `scry`/`surveil`/`scroll_rack` are one look-at-the-top
    ordering decision with different destinations.
    """
    if answer not in ANSWER_MODES:
        raise ValueError(f"unknown answer mode {answer!r}")
    if (answer == ANSWER_FLAG) != (yes is not None):
        raise ValueError(
            f"answer={answer!r} and yes={yes!r} disagree: a flag answer needs "
            f"the option id that means yes, and only a flag answer takes one"
        )

    def register(func: Callable[..., None]) -> Callable[..., None]:
        for kind in kinds:
            if kind in CHOICE_HANDLERS:
                raise ValueError(
                    f"choice kind {kind!r} already has a continuation "
                    f"({CHOICE_HANDLERS[kind].func.__qualname__})"
                )
            CHOICE_HANDLERS[kind] = ChoiceHandler(
                kind=kind, func=func, answer=answer, yes=yes,
                decline=decline, rule=rule,
            )
        return func

    return register


def is_decline(raw: Any) -> bool:
    """Whether ``raw`` is the client's way of declining."""
    return raw is None or raw == DECLINE


def coerce_answer(handler: ChoiceHandler, raw: Any) -> Any:
    """The raw wire answer, in the shape ``handler.func`` expects.

    This is the half of answer handling that used to live in
    `GameEngine.resolve_pending_choice`. The *other* half — "an unrecognized
    answer defaults to the first offered option" — stays inside each handler,
    because what a bad answer falls back to is a rules question (mandatory
    picks default, optional ones decline) rather than a transport one.
    """
    if handler.answer == ANSWER_FLAG:
        return raw == handler.yes
    if handler.answer == ANSWER_INT_REQUIRED:
        return int(raw)
    if is_decline(raw):
        return handler.decline
    return int(raw) if handler.answer == ANSWER_INT else str(raw)
