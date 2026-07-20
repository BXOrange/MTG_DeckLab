"""Standing "cast [permanent] spells from your graveyard" permission
(Lurrus of the Dream-Den-shaped).

Mirrors `game/top_library.py`'s "scan on demand" shape exactly (read every
active `GraveyardCastPermissionEffect` a player controls straight off the
battlefield, rather than a cached/recomputed field) — the same reasons
apply: the permission disappears the instant its granting permanent leaves
the battlefield, with no separate cleanup step needed.

Unlike Flashback/Escape (`GameEngine._graveyard_cast_keyword`), which are a
closed alt-cost keyword vocabulary printed on the card being cast itself,
this is a permission granted by some *other* permanent, paid at the cast
card's own normal mana cost — the graveyard-zone analogue of
`top_library_permission`'s "cast_spells" grant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .effects import GraveyardCastPermissionEffect

if TYPE_CHECKING:
    from ..models.card import Card
    from ..models.game_state import GameState
    from ..models.player import Player


def _is_permanent_card(card: "Card") -> bool:
    """Whether ``card`` is a permanent card (creature/artifact/enchantment/
    land/planeswalker) — Lurrus's own "a permanent spell" restriction.
    Mirrors `ExileGraveyardCardCounterIfPermanentEffect`'s identical check
    (`game/effects.py`)."""
    return bool(
        card.is_creature or card.is_artifact or card.is_enchantment
        or card.is_land or getattr(card, "is_planeswalker", False)
    )


def active_graveyard_cast_grants(player: "Player", state: "GameState") -> list[GraveyardCastPermissionEffect]:
    """Every currently-active `GraveyardCastPermissionEffect` ``player``
    controls — excluding a ``once_per_turn`` grant whose granting permanent
    has already been used this turn (`GameObject.graveyard_casts_this_turn`,
    reset each untap step)."""
    grants: list[GraveyardCastPermissionEffect] = []
    for obj in state.permanents_controlled_by(player.id):
        for effect in getattr(obj, "static_effects", None) or []:
            if not isinstance(effect, GraveyardCastPermissionEffect):
                continue
            if effect.once_per_turn and getattr(obj, "graveyard_casts_this_turn", 0):
                continue
            grants.append(effect)
    return grants


def graveyard_cast_grant_for(
    player: "Player", state: "GameState", card: "Card"
) -> Optional[GraveyardCastPermissionEffect]:
    """The `GraveyardCastPermissionEffect` that currently allows ``card`` (a
    card sitting in ``player``'s own graveyard) to be cast from there, or
    ``None``. Multiple simultaneous grants OR together — the same
    `top_library.may_cast_spell_from_top_of_library` "loosest filter wins"
    semantics — never the intersection of every grant's own filter.
    """
    if card.is_land:
        return None
    for effect in active_graveyard_cast_grants(player, state):
        if effect.permanent_only and not _is_permanent_card(card):
            continue
        if effect.max_mana_value is not None and card.converted_mana_cost > effect.max_mana_value:
            continue
        return effect
    return None


def may_cast_spell_from_graveyard(player: "Player", state: "GameState", card: "Card") -> bool:
    return graveyard_cast_grant_for(player, state, card) is not None
