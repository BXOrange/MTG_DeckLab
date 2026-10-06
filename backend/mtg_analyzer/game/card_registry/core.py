"""Card → `AbilitySpec` catalogue: the bind-on-load source of card behaviour.

The engine turns a card's abilities into behaviour by binding `AbilitySpec`s
(the IR, `parser/oracle/spec.py`) onto its `GameObject`. Until the oracle-text
NLP parser (docs/09) exists, those specs come from the **hand-authored,
name-keyed registry here**. `specs_for(card)` is the single entry point the
binder (`effect_binder.bind_from_catalogue`) consults when a game is built.

This is deliberately the seam the future parser plugs into: when it lands,
`specs_for` can fall back to it for any card not in the registry, and nothing
else in the engine has to change. Register a card with `register(name, factory)`
where ``factory`` returns fresh specs each call (specs are mutated when bound —
their effects get a source — so each object must get its own copies).

`enters_tapped(card)`/`land_tap_condition(card)` are a separate, *oracle-derived*
rule (RULE 614.1): they read the printed text (delegating the actual clause
recognition to `parser.oracle.catalogue.lands`, the coverage gate's own
source of truth for these shapes), so every plain tap-land — and the shock/
check/fast/slow/Battlebond-land conditional shapes `GameEngine.play_land`
resolves via `RulesEngine.enter_land_tapped` — works without being registered.
`entry_counters(card)` is the same split for a RULE 614.1-style "enters with
N counters" clause (`parser.oracle.catalogue.counters`), resolved by
`RulesEngine`'s battlefield-entry paths. `kicker_x_mana_restriction(card)`
is the same split again, for Kicker's own ``{X}`` payment restriction
(`parser.oracle.catalogue.kicker_mana`, PAR-7), resolved by
`GameEngine.can_cast`/`cast_spell`. `opening_hand_battlefield_permission
(card)` is the same split for RULE 103.6a's "you may begin the game with
it on the battlefield" pregame permission (`parser.oracle.catalogue.
opening_hand`, PLR-11), resolved by `services/game_session.py`'s
opening-hand handling; `pregame_setup_permission(card)` generalizes it to
that module's conditional/graveyard shapes (Gemstone Caverns/Buried Ogre).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ...models.game.events import EventType
from ..costs import SACRIFICE_COUNT_X
from ...parser.oracle.catalogue.counters import entry_counters as _entry_counters
from ...parser.oracle.catalogue.keywords import parse_keywords
from ...parser.oracle.catalogue.kicker_mana import kicker_x_mana_restriction as _kicker_x_mana_restriction
from ...parser.oracle.catalogue.lands import land_tap_condition as _land_tap_condition
from ...parser.oracle.catalogue.opening_hand import (
    opening_hand_battlefield_permission as _opening_hand_battlefield_permission,
    PregameSetupPermission,
    pregame_setup_permission as _pregame_setup_permission,
)
from ...parser.oracle.gate import parse_oracle
from ...parser.oracle.spec import AbilitySpec, EffectSpec

#: name (lowercased) → factory producing that card's specs, fresh each call.
_REGISTRY: dict[str, Callable[[], list[AbilitySpec]]] = {}


#: Keywords a registered card must *not* get from Scryfall's ``keywords`` array: that array lists a keyword the card only
#: has conditionally ("Celebration — … Goddric is a Dragon with … flying"), which the fold-in would otherwise grant always.
_SUPPRESSED_KEYWORDS: dict[str, frozenset[str]] = {}


def register(
    name: str, factory: Callable[[], list[AbilitySpec]], suppress_keywords: tuple[str, ...] = (),
) -> None:
    """Register a card's ability specs under its (case-insensitive) name.

    ``suppress_keywords`` names keyword slugs the card's own authored specs grant (conditionally) and the keyword
    catalogue's fold-in must therefore skip for this card.
    """
    key = name.strip().lower()
    _REGISTRY[key] = factory
    if suppress_keywords:
        _SUPPRESSED_KEYWORDS[key] = frozenset(suppress_keywords)


def registry_signature() -> str:
    """A short, stable fingerprint of *which* cards are hand-`AUTHORED`.

    A hand-authored catalogue entry makes a card fully playable without any
    `parser/oracle/` change, so it never bumps `PARSER_VERSION`. Anything
    that caches "how many of this deck's cards aren't modeled yet" keyed on
    `PARSER_VERSION` alone (`api/saved_decks.py`'s `Deck.unmodeled_coverage`)
    would therefore keep reporting a card as unmodeled forever after it's
    registered, until the decklist text next changes. Folding this
    signature into that cache key is the missing "reassess" trigger.

    Only the *set of registered names* matters here (adding/removing a card),
    not a factory's internal edits — those are picked up by the engine
    directly, and a coverage count can't see them anyway.
    """
    import hashlib

    joined = "\n".join(sorted(_REGISTRY))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


def is_registered(name: str) -> bool:
    """Whether ``name`` (a card's own ``.name``) has a catalogue entry.

    Mirrors `specs_for`'s own DFC/MDFC/split "//" front-face fallback — a
    card registered under its front face's name alone (Halvar, God of
    Battle // Sword of the Realms is registered as just "Halvar, God of
    Battle") must still report registered when looked up by its full
    combined name, or a caller that only checks this (e.g. `api/cards.py`'s
    coverage badge) wrongly reports a fully-bound card as unmodeled.
    """
    lowered = name.strip().lower()
    if lowered in _REGISTRY:
        return True
    return "//" in lowered and lowered.split("//")[0].strip() in _REGISTRY


def suppressed_keywords_for(card: Any) -> frozenset[str]:
    """The keyword slugs ``card``'s registration says Scryfall's ``keywords`` array must not grant (see ``register``)."""
    return _SUPPRESSED_KEYWORDS.get((getattr(card, "name", "") or "").strip().lower(), frozenset())


def specs_for(card: Any) -> list[AbilitySpec]:
    """The `AbilitySpec`s a card contributes, or ``[]`` if none are known.

    Three sources, in precedence order:

    1. the hand-authored registry (by card name) — trusted wholesale when a
       card is registered;
    2. the RULE 702 **keyword catalogue** parsed off the card's own
       text/keywords (always folded in, since each keyword is safe on its own);
    3. the **oracle-effect parser** (docs/09) for the effect/triggered clauses
       of an *unregistered* card — but only when the parser marks the whole
       card `MODELED` (fail-closed: a half-parsed card contributes no effects).

    Any keyword the registry already authored wins, so it isn't duplicated.
    """
    name = (getattr(card, "name", "") or "").strip().lower()
    factory = _REGISTRY.get(name)
    if getattr(card, "is_split", False) and getattr(card, "back_name", "") and "//" in name:
        # RULE 709.3/709.4: the printed card exposes its front half until a fused face is selected.
        factory = _REGISTRY.get(name.split("//")[0].strip(), factory)
    # A DFC/MDFC/split card's ``name`` is the combined "Front // Back"; a
    # registration keyed on the (castable) front face's own name should still
    # match (e.g. Shatterskull Smashing, whose back is a land). Fall back to
    # the pre-"//" front name — the same slice `Card.fuse_face` reads.
    if factory is None and "//" in name:
        factory = _REGISTRY.get(name.split("//")[0].strip())
    registered = factory is not None
    specs: list[AbilitySpec] = list(factory()) if registered else []

    authored = {
        s.keyword.get("name")
        for s in specs
        if s.ability_kind == "keyword" and s.keyword
    }
    suppressed = _SUPPRESSED_KEYWORDS.get(name, frozenset()) if registered else frozenset()
    for kw_spec in parse_keywords(card):
        if kw_spec.keyword and (kw_spec.keyword.get("name") in authored or kw_spec.keyword.get("name") in suppressed):
            continue
        specs.append(kw_spec)

    # For an unregistered card, add parser-derived effect abilities — but only
    # from a fully MODELED card, so we never resolve half of what a card says.
    if not registered:
        result = parse_oracle(card)
        if result.modeled:
            specs.extend(result.effect_specs)
    return specs


def land_tap_condition(card: Any) -> dict[str, Any]:
    """How ``card``'s RULE 614.1 tapped-entry resolves, read off its text.

    One of:

    - ``{"kind": "never"}`` — no tapped-entry clause (a normal land), or an
      unrecognized conditional shape (fails safe: untapped rather than wrong).
    - ``{"kind": "always"}`` — a plain tap-land, unconditionally tapped.
    - ``{"kind": "pay_life", "amount": N}`` — a shock land: the controller may
      pay ``N`` life to keep it untapped, a genuine choice the caller must
      offer interactively.
    - ``{"kind": "optional_bonus_rad", "amount": N}`` — the mirror image
      (Mariposa Military Base): untapped by default, with the controller
      able to choose tapped instead for ``N`` rad counters.
    - ``{"kind": "unless_types", "types": [...]}`` — a check land: untapped
      iff the controller already controls a land of one of these types.
    - ``{"kind": "unless_count", "cmp": "le" | "ge", "count": N, "basic": bool}``
      — a fast land (``"le"``) or slow land (``"ge"``): untapped iff the
      count of *other* lands (or, when ``basic`` is set, *basic* lands) the
      controller controls compares as stated.
    - ``{"kind": "unless_opponents", "count": N}`` — a Commander
      "Battlebond" land: untapped iff the game has at least ``N`` opponents.
    - ``{"kind": "unless_opponents_count", "cmp": "le" | "ge", "count": N}``
      — the "Turbulent" land cycle: untapped iff the *total* count of lands
      across all opponents compares as stated.

    The conditional shapes are deterministic on game/board state at entry —
    no player decision, unlike the shock land's payment. Delegates to the
    oracle-text front-end's `parser.oracle.catalogue.lands.land_tap_condition`
    (the coverage gate's single source of truth for these clause shapes, so
    the engine can never resolve a shape the gate doesn't also claim, or
    vice versa) — see that module for the full clause-recognition logic.
    """
    return _land_tap_condition(card)


def enters_tapped(card: Any) -> bool:
    """Whether ``card`` unconditionally enters the battlefield tapped
    (RULE 614.1) — a plain tap-land. Conditional tap-lands (shock/check/
    fast/slow lands, see `land_tap_condition`) are *not* "always" and so
    read as ``False`` here; `GameEngine.play_land` resolves those properly."""
    return land_tap_condition(card)["kind"] == "always"


def entry_counters(card: Any) -> Optional[dict[str, Any]]:
    """``card``'s RULE 614.1-style "enters with N counters" clause, or
    ``None`` if it has none. One of:

    - ``{"is_x": True, "counter_type": "+1/+1"}`` — the amount is the
      object's actual paid X (RULE 107.3c: 0 outside a cast-for-X).
    - ``{"is_x": False, "count": N, "counter_type": "ice"}`` — a fixed
      amount.

    Delegates to `parser.oracle.catalogue.counters.entry_counters` (the
    coverage gate's single source of truth for this clause shape), the same
    split `land_tap_condition` uses for tapped-entry.
    """
    return _entry_counters(card)


def opening_hand_battlefield_permission(card: Any) -> bool:
    """Whether ``card`` may begin the game on the battlefield straight from
    a kept opening hand (RULE 103.6a — "If this card is in your opening
    hand, you may begin the game with it on the battlefield.", the Leyline
    cycle). A pregame setup permission, not a static or resolve-time
    effect, so it doesn't go through the `EffectRegistry`/binder pipeline
    at all — `services/game_session.py`'s opening-hand handling in
    `_keep_hand` reads this directly once every seat has kept.

    Delegates to `parser.oracle.catalogue.opening_hand` (the coverage
    gate's single source of truth for this clause shape), the same split
    `land_tap_condition`/`entry_counters` use.
    """
    return _opening_hand_battlefield_permission(card)


def pregame_setup_permission(card: Any) -> Optional[PregameSetupPermission]:
    """``card``'s RULE 103.6 pregame setup permission, generalizing
    `opening_hand_battlefield_permission` above to the two conditional/
    costed shapes it deliberately left unclaimed: Gemstone Caverns'
    "...and you're not the starting player...with a luck counter on it. If
    you do, exile a card from your hand." and Buried Ogre's "...in your
    graveyard. If you do, you lose N life." — or ``None`` if ``card`` has
    no pregame setup permission at all.

    Delegates to `parser.oracle.catalogue.opening_hand` (the coverage
    gate's single source of truth for these clause shapes), the same split
    `land_tap_condition`/`entry_counters` use. `services/game_session.py`'s
    opening-hand handling reads this instead of the plain boolean above so
    it can check a permission's own `PregameSetupPermission.condition`
    against who the starting player is before ever queuing the choice.
    """
    return _pregame_setup_permission(card)


def kicker_x_mana_restriction(card: Any) -> Optional[str]:
    """``card``'s Kicker-own-``{X}`` payment restriction (RULE 605.3a-style,
    PAR-7 — Emblazoned Golem's "Spend only colored mana on X. No more than
    one mana of each color may be spent this way."), or ``None`` for an
    ordinary/no-``{X}`` Kicker cost. ``"distinct_colors"`` is the one
    recognized value today, consulted by `GameEngine.can_cast`/`cast_spell`
    via `models.mana.mana_pool.ManaPool.can_pay_distinct_colors`/
    `pay_distinct_colors`.

    Delegates to `parser.oracle.catalogue.kicker_mana` (the coverage gate's
    single source of truth for this clause shape), the same split
    `entry_counters` above uses.
    """
    return _kicker_x_mana_restriction(card)

