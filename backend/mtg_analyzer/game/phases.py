"""Phases & steps as executable sequences (RULE 500, docs/07 PART 1).

docs/07 PART 1 is explicit that phases must NOT be a hardcoded call
sequence, because cards reorder and skip them ("skip your next untap
step"). So a turn is *data*: an ordered list of `GamePhase`s, each an
ordered list of `GameStep`s. The engine walks the list and asks, at each
step, whether an effect skips it — new skip/reorder effects need no new
branches (contrast the "bad approach" in docs/07 PART 1).
"""

from __future__ import annotations

from typing import Any


class GameStep:
    """A single step within a phase (RULE 500.1), identified by name.

    ``gives_priority`` marks steps where players receive priority
    (RULE 500.2) — untap and cleanup normally don't (RULE 502/514).
    """

    def __init__(self, name: str, rule: str = "", gives_priority: bool = True) -> None:
        self.name = name
        self.rule = rule
        self.gives_priority = gives_priority

    def __repr__(self) -> str:
        return f"GameStep({self.name!r})"


class GamePhase:
    """A named, ordered collection of steps (RULE 500)."""

    def __init__(self, name: str, steps: list[GameStep]) -> None:
        self.name = name
        self.steps = steps

    def __repr__(self) -> str:
        return f"GamePhase({self.name!r}, steps={[s.name for s in self.steps]})"


class TurnSequence:
    """The ordered phases of a turn (RULE 500.1), walked by the engine."""

    def __init__(self, phases: list[GamePhase]) -> None:
        self.phases = phases

    def iter_steps(self):
        """Yield ``(phase, step)`` pairs in turn order."""
        for phase in self.phases:
            for step in phase.steps:
                yield phase, step


def default_turn_sequence() -> TurnSequence:
    """Build the standard turn (RULE 500.1, RULE 501-514).

    A fresh instance per call so callers can safely mutate a turn's
    sequence (e.g. add an extra combat phase) without affecting others.
    """
    return TurnSequence(
        [
            GamePhase(
                "beginning",
                [
                    GameStep("untap", rule="502", gives_priority=False),
                    GameStep("upkeep", rule="503"),
                    GameStep("draw", rule="504"),
                ],
            ),
            GamePhase("precombat_main", [GameStep("main1", rule="505")]),
            GamePhase(
                "combat",
                [
                    GameStep("begin_combat", rule="507"),
                    GameStep("declare_attackers", rule="508"),
                    GameStep("declare_blockers", rule="509"),
                    GameStep("combat_damage", rule="510"),
                    GameStep("end_combat", rule="511"),
                ],
            ),
            GamePhase("postcombat_main", [GameStep("main2", rule="505")]),
            GamePhase(
                "ending",
                [
                    GameStep("end", rule="513"),
                    GameStep("cleanup", rule="514", gives_priority=False),
                ],
            ),
        ]
    )


#: A module-level template. The engine calls ``default_turn_sequence()``
#: per turn; this constant is exported mainly for introspection/tests.
DEFAULT_TURN_SEQUENCE: TurnSequence = default_turn_sequence()


def describe_turn_structure() -> dict[str, Any]:
    """Human/debug view of the default structure (RULE 500)."""
    seq = default_turn_sequence()
    return {phase.name: [step.name for step in phase.steps] for phase in seq.phases}
