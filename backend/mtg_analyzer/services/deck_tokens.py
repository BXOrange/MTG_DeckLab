"""Enumerate the tokens a deck can *produce*, for up-front art preloading.

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md (the token catalogue), CLAUDE.md
("Preload all tokens … available at the start of the match").

Tokens are never named in a decklist — they are created by effects during
play, and their art is otherwise lazy-loaded the first time one hits the
battlefield (a visible "pop-in"). This module walks a deck's cards, finds
every ``create_token`` effect they carry, and resolves each to the token
`Card` definition it would create — **using the exact same resolution path as
`CreateTokenEffect.apply`** (game/effects/core.py), so the preloaded set matches
what actually appears in play:

* a bare *named* token (no inline P/T) → the curated `TokenDatabase`, keeping
  its printed art + abilities (Treasure, Clue, a named creature token);
* an *inline* token (P/T + colours + subtypes from the oracle clause) →
  `synthesize_token_card`, which carries no Scryfall art (the UI falls back to
  a text tile).

The result is a de-duplicated list of token `Card`s; the API layer
(`api/game.py`) turns it into image URLs the goldfish loading screen preloads.
"""

from __future__ import annotations

from typing import Any

from mtg_analyzer.models.cards.card import Card


def producible_tokens(cards: list[Card]) -> list[Card]:
    """The distinct token `Card`s the given deck cards could create.

    De-duplicated by token id, preserving first-seen order. Import the
    engine pieces function-scoped so this stays cheap to import and keeps the
    model→game boundary clean (CLAUDE.md "Model → game import boundary").
    """
    from mtg_analyzer.game.card_registry import specs_for
    from mtg_analyzer.services.token_database import (
        default_token_database,
        synthesize_token_card,
    )

    catalogue = default_token_database()
    seen: dict[str, Card] = {}
    for card in _unique_by_id(cards):
        for params in _create_token_params(card, specs_for):
            if params.get("empower_jace"):
                from mtg_analyzer.services.token_database import jace_token_card
                token = jace_token_card()
            else:
                token = _resolve_token(params, catalogue, synthesize_token_card)
            if token is not None and token.id not in seen:
                seen[token.id] = token
    return list(seen.values())


def _unique_by_id(cards: list[Card]) -> list[Card]:
    """The deck's cards de-duplicated by id (a deck is a flat, multiset list)."""
    seen: dict[str, Card] = {}
    for card in cards:
        seen.setdefault(card.id, card)
    return list(seen.values())


def _create_token_params(card: Card, specs_for: Any) -> list[dict[str, Any]]:
    """Every ``create_token`` effect's params across all of ``card``'s specs."""
    out: list[dict[str, Any]] = []
    try:
        specs = specs_for(card)
    except Exception:
        # Enumeration is best-effort art preloading, never a hard failure:
        # a card whose parse raises simply contributes no tokens.
        return out
    for spec in specs:
        for effect in getattr(spec, "effects", []) or []:
            if getattr(effect, "type", None) == "create_token":
                out.append(dict(getattr(effect, "params", {}) or {}))
            elif getattr(effect, "type", None) == "empower_jace" or _contains_empower(
                getattr(effect, "params", {})
            ):
                out.append({"empower_jace": True})
    return out


def _contains_empower(node: Any) -> bool:
    """Empower inside a bind/branch still produces the same Jace token."""
    if isinstance(node, dict):
        return node.get("type") == "empower_jace" or any(
            _contains_empower(value) for value in node.values()
        )
    if isinstance(node, (list, tuple)):
        return any(_contains_empower(value) for value in node)
    return False


def _resolve_token(
    params: dict[str, Any], catalogue: Any, synthesize: Any
) -> Card | None:
    """Resolve one ``create_token`` params dict to its token `Card` definition.

    Mirrors `CreateTokenEffect.apply`: a bare named token comes from the curated
    catalogue; anything with inline stats (or an uncatalogued name) synthesizes.
    """
    token_name = params.get("token_name")
    power = params.get("power")
    toughness = params.get("toughness")
    # A bare named token (no inline stats) → the curated catalogue.
    if token_name and power is None and toughness is None:
        card = catalogue.get_token(token_name)
        if card is not None:
            return card
    return synthesize(
        token_name or (params.get("subtypes") or ["Token"])[0],
        power=power,
        toughness=toughness,
        colors=params.get("colors"),
        subtypes=params.get("subtypes"),
        keywords=params.get("keywords"),
    )
