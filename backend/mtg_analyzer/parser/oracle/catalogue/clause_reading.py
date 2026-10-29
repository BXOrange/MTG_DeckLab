"""The one immutable "reading" a clause is parsed under (PAR-173).

English reuses the same words ("it", "that creature", "they") for different referents depending on what the
surrounding ability has already established. The parser used to thread five booleans (`self_subject`,
`previous_subject`, `group_subject`, `previous_selector`, `attached_subject`) through `match_clause`,
`parse_effect_body` and every helper between them, plus a ContextVar (`_GROUP_CLAUSE`) that a few deep builders
read. `ClauseReading` is that state as one frozen value: derive variants with `but(...)`, hand it to whatever
re-enters the parser, and gate rows on it with `EffectHandler.requires`.

PAR-175 (referents) adds its environment here, as one more field on `ClauseReading` (`referents`: the groups and
objects earlier clauses of the same body produced) -- do not thread a new flag instead. `previous_subject` and
`previous_selector` are *views* of it: construct with either spelling and both agree (`__post_init__`), so every row
that gates on them keeps working while the environment grows richer kinds.

A leaf module: it imports nothing from the parser.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


#: `Referent.kind`: an object an earlier clause *chose* (RULE 601.2c target, a created or copied object, a graveyard
#: card, a countered spell) -- `GameContext.previous_targets` at resolution -- read by "it" / "that creature".
TARGET = "target"
#: A player previously targeted by this sequence; never interchangeable with a permanent's "it".
PLAYER = "player"
#: `Referent.kind`: the group an earlier untargeted mass selector acted on -- `GameContext.previous_selector` -- read
#: by "they" / "those creatures".
SELECTOR = "selector"


#: `Referent.kind`: what the preceding clause *made* (tokens, copies, manifested cards) -- `GameContext.created_objects`
#: -- read by "it" / "they" in "Create a token. It has ...". Always accompanied by `TARGET` (the older view), but
#: unlike it never confused with an earlier clause's pick.
CREATED = "created"


#: `Referent.kind`: the spell the preceding clause countered -- "If that spell is countered this way, ..." names it
#: (RULE 701.5a); the consumer folds into that `counter` spec as its replacement destination.
COUNTERED = "countered"


#: `Referent.kind`: the one card an earlier clause revealed or exiled off a library -- "reveal the top card of your
#: library and put it into your hand. You lose life equal to **its** mana value" (RULE 701.20). Distinct from `TARGET`
#: (nothing was chosen, so no RULE 115 target) and `CREATED` (consumed by token riders); `Referent.noun` names the
#: engine referent that carries it (`REVEALED_CARD` = `GameContext.revealed_card`, `EXILED_CARD` = the card the exile
#: left on `GameContext.created_objects`).
REVEALED = "revealed"
REVEALED_CARD = "revealed"
EXILED_CARD = "created"

# The exact batch a preceding instruction put into exile, for cast/play follow-ups.
EXILE_POOL = "exile_pool"


@dataclass(frozen=True)
class Referent:
    """One thing an earlier clause of the same body produced, which a later clause may name with a pronoun."""

    kind: str
    #: What it is called ("object" until a family needs the printed noun to tell referents apart).
    noun: str = "object"
    #: Whether it is a group (plural pronoun) rather than a single object.
    group: bool = False


TARGET_REFERENT = Referent(TARGET)
SELECTOR_REFERENT = Referent(SELECTOR, group=True)
CREATED_REFERENT = Referent(CREATED)
CREATED_GROUP_REFERENT = Referent(CREATED, group=True)
COUNTERED_REFERENT = Referent(COUNTERED)
REVEALED_REFERENT = Referent(REVEALED, noun=REVEALED_CARD)
EXILED_REFERENT = Referent(REVEALED, noun=EXILED_CARD)


@dataclass(frozen=True)
class ClauseReading:
    #: "it" is the ability's own source (an unsplit self-subject trigger body, `segment_line`).
    self_subject: bool = False
    #: "it"/"that creature" is the creature the *preceding clause of the same body* chose (`GameContext.previous_targets`).
    previous_subject: bool = False
    #: "it"/"that creature" is the object this ability's own RULE 603.1 group-subject trigger condition matched.
    group_subject: bool = False
    #: "they" is the group a mass selector in the preceding clause acted on.
    previous_selector: bool = False
    #: The environment of the sequence being read: what the clauses before this one produced, oldest first. The two
    #: booleans above are derived from it (or it from them); build with whichever is convenient.
    referents: tuple[Referent, ...] = ()
    #: "its" is RULE 303.4/301.5's attached host (the trigger condition is ``{"subject": "attached_permanent"}``).
    attached_subject: bool = False
    #: Whether the clause being read sits under a group trigger *as such* (a group subject with no self/previous
    #: reading). Computed once by `match_clause` (`entered`) and carried unchanged by `but`, so a re-entering builder
    #: sees the reading of the clause that invoked it -- what the removed `_GROUP_CLAUSE` ContextVar carried.
    group_clause: bool = False

    def __post_init__(self) -> None:
        # Frozen, so go through object.__setattr__: the booleans and the environment always agree.
        if self.referents:
            object.__setattr__(self, "previous_subject", any(r.kind == TARGET for r in self.referents))
            object.__setattr__(self, "previous_selector", any(r.kind == SELECTOR for r in self.referents))
        else:
            object.__setattr__(self, "referents", tuple(
                ref for ref, on in ((TARGET_REFERENT, self.previous_subject), (SELECTOR_REFERENT, self.previous_selector)) if on
            ))

    def referents_of(self, *kinds: str) -> tuple[Referent, ...]:
        """The environment narrowed to some kinds (a site that only ever carried the "it" chain keeps only that)."""
        return tuple(r for r in self.referents if r.kind in kinds)

    def but(self, **facts: Any) -> "ClauseReading":
        """This reading with some facts changed (``reading.but(previous_subject=True)``); `group_clause` is kept."""
        if "referents" not in facts and ("previous_subject" in facts or "previous_selector" in facts):
            facts["referents"] = ()  # re-derive the environment from the booleans just changed
        return replace(self, **facts)

    def only(self, **facts: Any) -> "ClauseReading":
        """A reading carrying exactly these facts (every other fact off), keeping `group_clause` -- for a builder that
        re-enters the table (`match_clause_once`) under its own fixed reading."""
        return ClauseReading(group_clause=self.group_clause, **facts)

    def unattached(self) -> "ClauseReading":
        """This reading without the attached-host fact (helpers that never read an Aura/Equipment host)."""
        return self.but(attached_subject=False)

    def entered(self) -> "ClauseReading":
        """The reading `match_clause` works under: `group_clause` recomputed from the five facts."""
        return replace(self, group_clause=self.group_subject and not self.previous_subject and not self.self_subject)

    def satisfies(self, required: "ClauseReading") -> bool:
        """Whether every fact `required` asks for holds here (`EffectHandler.requires`); `group_clause` is not a fact."""
        return (
            (self.self_subject or not required.self_subject)
            and (self.previous_subject or not required.previous_subject)
            and (self.group_subject or not required.group_subject)
            and (self.previous_selector or not required.previous_selector)
            and (self.attached_subject or not required.attached_subject)
            and {r.kind for r in required.referents} <= {r.kind for r in self.referents}
        )


#: No special reading: the only one available to a clause standing alone (a bare pronoun claims nothing).
STANDALONE = ClauseReading()
