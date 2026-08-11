"""Formats and casual variants (RULE 8 multiplayer, RULE 9 casual variants).

Until this module existed the engine hard-coded one set of "how a game
starts" numbers — Commander's 40 life (RULE 903.7) — everywhere a game was
built, with `starting_life`/`starting_hand` passed around as bare ints. A
`GameFormat` collects those numbers *and* the variant rules that come with
them into one named, serializable record, so a caller picks a format instead
of remembering a combination.

What a variant actually adds is engine behaviour, and each one here is
built:

* **Planechase** (RULE 901) — a shared planar deck, the planar die and the
  chaos/planeswalk abilities of the face-up plane (`game/variants.py`).
* **Archenemy** (RULE 904) — a per-player scheme deck, set in motion at the
  start of the archenemy's precombat main phase, with ongoing schemes
  staying face up until abandoned.
* **Vanguard** (RULE 902) — an avatar in the command zone whose abilities
  function from there and whose hand-size/life modifiers apply as the game
  starts.

**Not** modeled, and deliberately absent rather than silently degraded: the
*team* variants (RULE 810 Two-Headed Giant, RULE 809 Emperor, RULE 811 Grand
Melee). Those change the turn structure itself — shared turns, a shared
life total, a "defending team" in combat — rather than adding a card pool
alongside it, so they are a turn-loop project, not a format record. See the
`PLR` tickets in `docs/implementation-state/BACKLOG.md`.
"""

from __future__ import annotations

from typing import Any, Optional

#: RULE 901: Planechase — a planar deck, the planar die, chaos abilities.
PLANECHASE = "planechase"
#: RULE 904: Archenemy — one player faces the rest, with a scheme deck.
ARCHENEMY = "archenemy"
#: RULE 902: Vanguard — an avatar card in the command zone.
VANGUARD = "vanguard"

ALL_VARIANTS: frozenset[str] = frozenset({PLANECHASE, ARCHENEMY, VANGUARD})


class GameFormat:
    """One playable format: its starting numbers plus any RULE 9 variants."""

    def __init__(
        self,
        name: str,
        label: str,
        starting_life: int = 20,
        starting_hand: int = 7,
        singleton: bool = False,
        variants: Optional[frozenset[str]] = None,
        archenemy_life: int = 40,
        free_mulligan: bool = False,
    ) -> None:
        self.name = name
        self.label = label
        self.starting_life = starting_life
        self.starting_hand = starting_hand
        #: RULE 903.5b: one copy of each card but basic lands (Commander).
        #: Recorded here so deck validation can read the *format* rather than
        #: assuming Commander, even though today only Commander sets it.
        self.singleton = singleton
        self.variants: frozenset[str] = frozenset(variants or ())
        #: The Commander Rules Committee's "free" first mulligan: a player's
        #: *first* mulligan each game costs no card (draw the full starting
        #: hand again), same as the London style's shuffle-and-redraw, just
        #: without London's "bottom N" penalty on that one attempt. Only
        #: Commander-shaped formats grant it.
        self.free_mulligan = free_mulligan
        #: RULE 904.4: in an Archenemy game the archenemy starts with 40 life
        #: while each other player starts with the format's ordinary total.
        self.archenemy_life = archenemy_life

    def has(self, variant: str) -> bool:
        return variant in self.variants

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "starting_life": self.starting_life,
            "starting_hand": self.starting_hand,
            "singleton": self.singleton,
            "variants": sorted(self.variants),
            "free_mulligan": self.free_mulligan,
        }

    def __repr__(self) -> str:
        return f"GameFormat({self.name!r}, life={self.starting_life}, variants={sorted(self.variants)})"


#: The formats this engine can actually run, keyed by name. Commander is the
#: default everywhere (it is what this app is built around); the rest exist so
#: a game can be *configured* rather than assumed.
FORMATS: dict[str, GameFormat] = {
    fmt.name: fmt
    for fmt in [
        GameFormat(
            "commander", "Commander", starting_life=40, singleton=True, free_mulligan=True
        ),
        GameFormat("constructed", "Constructed"),
        # RULE 806: free-for-all multiplayer — the engine's own N-player mode,
        # already the shape `build_multiplayer_engine` produces.
        GameFormat("free_for_all", "Free-for-All"),
        GameFormat("planechase", "Planechase", variants=frozenset({PLANECHASE})),
        GameFormat("archenemy", "Archenemy", variants=frozenset({ARCHENEMY})),
        GameFormat("vanguard", "Vanguard", variants=frozenset({VANGUARD})),
        # RULE 901.1's own note that Planechase combines freely with other
        # variants — Commander is the combination people actually play.
        GameFormat(
            "planechase_commander",
            "Planechase Commander",
            starting_life=40,
            singleton=True,
            variants=frozenset({PLANECHASE}),
            free_mulligan=True,
        ),
    ]
}

#: What a game is unless told otherwise.
DEFAULT_FORMAT = "commander"


def get_format(name: Optional[str]) -> GameFormat:
    """The named `GameFormat`, or Commander for an unknown/missing name —
    never an error, so an old saved game or a stale client can't wedge a
    session on a format string."""
    return FORMATS.get((name or "").strip().lower(), FORMATS[DEFAULT_FORMAT])
