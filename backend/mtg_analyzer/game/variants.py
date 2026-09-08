"""The RULE 9 casual variants' command-zone card pools: Planechase's planar
deck (RULE 901), Archenemy's scheme decks (RULE 904) and Vanguard's avatars
(RULE 902).

All three share one shape, and it is the shape dungeons (RULE 309) already
established in this engine: cards that **begin outside the game**, never
belong to a deck, live in the command zone, and whose abilities function
from there. What they add on top of a dungeon is that each one *is* a real
card with real oracle text — so unlike a dungeon's rooms they are ordinary
`GameObject`s in `Zone.COMMAND`, bound through `effect_binder.
bind_from_catalogue` exactly like a permanent, and picked up by the same
static-ability and triggered-ability scans that already read a player's
emblems.

This module only builds the pools (shuffled decks of the right kind of card
from `services/variant_card_database.py`) and answers "which object is
currently face up". Everything that *happens* — rolling the planar die,
planeswalking, setting a scheme in motion — is `RulesEngine`, so it goes
through the ordinary event/trigger machinery.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any, Optional

from ..models.game_object import GameObject, Zone
from ..services.variant_card_database import card_for, default_variant_card_database

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models.game_state import GameState
    from ..models.player import Player

#: RULE 901.6: the planar die's six faces — one chaos, one planeswalk, four
#: blank. Rolled as a list so `RulesEngine.random_choice` can pick from it
#: with the session's own seeded RNG (and so a test can assert the spread).
PLANAR_DIE_FACES: tuple[str, ...] = (
    "chaos", "planeswalk", "blank", "blank", "blank", "blank",
)

#: RULE 901.15: a planar deck has at least 10 plane cards; RULE 904.5: a
#: scheme deck at least 20. Used when building a random pool from the
#: catalogue, which is what a player without a curated deck of their own gets.
DEFAULT_PLANAR_DECK_SIZE = 10
DEFAULT_SCHEME_DECK_SIZE = 20


def _objects_of_kind(
    kind: str, owner_id: str, count: Optional[int] = None, rng: Optional[random.Random] = None
) -> list[GameObject]:
    """``count`` freshly-built command-zone objects of one catalogue kind."""
    from .binding.core import bind_from_catalogue  # function-scoped: avoid a cycle

    entries = default_variant_card_database().of_kind(kind)
    if not entries:
        return []
    picker = rng or random
    chosen = picker.sample(entries, min(count or len(entries), len(entries)))
    built: list[GameObject] = []
    for entry in chosen:
        obj = GameObject(card_for(entry), owner_id=owner_id, zone=Zone.COMMAND)
        bind_from_catalogue(obj)
        built.append(obj)
    return built


#: RULE 901.15: a planar deck may hold at most two **phenomenon** cards.
MAX_PHENOMENA = 2


def is_phenomenon(obj: GameObject) -> bool:
    """RULE 901.17: a phenomenon rather than a plane — same `planar` Scryfall
    layout and the same planar deck, but its own type line, its own "when you
    encounter" trigger, and RULE 901.18's "planeswalk again afterward"."""
    return (obj.card.type_line or "").strip().lower().startswith("phenomenon")


def build_planar_deck(
    owner_id: str, size: int = DEFAULT_PLANAR_DECK_SIZE, rng: Optional[random.Random] = None
) -> list[GameObject]:
    """A shuffled planar deck (RULE 901.15), holding at most `MAX_PHENOMENA`
    phenomenon cards and starting on a plane rather than a phenomenon (RULE
    901.9 turns the top card face up as the game begins, and a phenomenon
    there would immediately planeswalk the table off it).

    The **last** entry is the top of the deck, the same "top of a library is
    the end of the list" convention `Player.library` uses — so the same
    mental model applies everywhere.

    Built by dealing off a shuffle of the *whole* pool and skipping any
    phenomenon past the `MAX_PHENOMENA`th, rather than by sampling exactly
    ``size`` cards and then discarding the excess phenomena — that older
    shape had nothing to replace what it discarded, so roughly 6% of decks
    came back **short** of ``size`` (which is what made a Planechase test
    fail intermittently). Dealing keeps the phenomenon count random up to
    the cap, which sampling-then-discarding also did and a
    take-the-cap-every-time fix would not."""
    picker = rng or random
    pool = _objects_of_kind("plane", owner_id, None, rng)
    picker.shuffle(pool)
    deck: list[GameObject] = []
    phenomena = 0
    for obj in pool:
        if len(deck) >= size:
            break
        if is_phenomenon(obj):
            if phenomena >= MAX_PHENOMENA:
                continue
            phenomena += 1
        deck.append(obj)
    picker.shuffle(deck)
    if deck and is_phenomenon(deck[-1]):
        # Keep a plane on top for the opening face-up card (RULE 901.9).
        first_plane = next((i for i, obj in enumerate(deck) if not is_phenomenon(obj)), None)
        if first_plane is not None:
            deck[-1], deck[first_plane] = deck[first_plane], deck[-1]
    return deck


def build_scheme_deck(
    owner_id: str, size: int = DEFAULT_SCHEME_DECK_SIZE, rng: Optional[random.Random] = None
) -> list[GameObject]:
    """A shuffled scheme deck for the archenemy (RULE 904.5), same ordering
    convention as `build_planar_deck`."""
    return _objects_of_kind("scheme", owner_id, size, rng)


def build_vanguard(owner_id: str, name: Optional[str] = None) -> Optional[GameObject]:
    """One Vanguard avatar (RULE 902.2) — the named one, or a random one."""
    db = default_variant_card_database()
    entry = db.get(name) if name else None
    if entry is None:
        entries = db.of_kind("vanguard")
        if not entries:
            return None
        entry = random.choice(entries)
    from .binding.core import bind_from_catalogue  # function-scoped: avoid a cycle

    obj = GameObject(card_for(entry), owner_id=owner_id, zone=Zone.COMMAND)
    bind_from_catalogue(obj)
    return obj


def vanguard_modifiers(name: str) -> tuple[int, int]:
    """A Vanguard avatar's ``(hand_modifier, life_modifier)`` (RULE 902.3/
    902.4) — ``(0, 0)`` for an unknown avatar."""
    entry = default_variant_card_database().get(name)
    if entry is None:
        return (0, 0)
    return (int(entry.get("hand_modifier") or 0), int(entry.get("life_modifier") or 0))


def active_plane(state: "GameState") -> Optional[GameObject]:
    """The face-up plane (RULE 901.7) — the top card of the planar deck — or
    ``None`` when this isn't a Planechase game."""
    return state.planar_deck[-1] if state.planar_deck else None


def command_zone_ability_sources(state: "GameState") -> list[Any]:
    """Every variant object whose abilities currently *function* (RULE 901.7,
    902.4, 904.9) — the face-up plane, each player's face-up ongoing schemes,
    and each player's Vanguard avatar.

    Read by `game/continuous.py`'s static-ability scan and
    `RulesEngine._collect_triggers`, alongside `Player.emblems`. A scheme
    that has been set in motion but *isn't* ongoing is deliberately absent:
    its one triggered ability has already fired, and RULE 904.10 sends it
    back to the bottom of its deck.
    """
    sources: list[Any] = []
    plane = active_plane(state)
    if plane is not None:
        sources.append(plane)
    for player in state.players:
        sources.extend(player.ongoing_schemes)
        if player.vanguard is not None:
            sources.append(player.vanguard)
    return sources
