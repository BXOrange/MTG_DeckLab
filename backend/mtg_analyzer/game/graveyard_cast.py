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

from ..models.cards import card_query
from .effects.core import GraveyardCastPermissionEffect

if TYPE_CHECKING:
    from ..models.cards.card import Card
    from ..models.game.game_state import GameState
    from ..models.game.player import Player


def _is_permanent_card(card: "Card") -> bool:
    """Whether ``card`` is a permanent card (creature/artifact/enchantment/
    land/planeswalker) — Lurrus's own "a permanent spell" restriction.
    Mirrors `ExileGraveyardCardCounterIfPermanentEffect`'s identical check
    (`game/effects/core.py`)."""
    return bool(
        card.is_creature or card.is_artifact or card.is_enchantment
        or card.is_land or getattr(card, "is_planeswalker", False)
    )


def permanent_types(card: "Card") -> set[str]:
    """The printed permanent types relevant to Muldrotha's separate
    once-per-type permissions. A multi-type card may consume any one still
    unused type when it is cast/played."""
    return {
        kind for kind, present in (
            ("artifact", card.is_artifact), ("creature", card.is_creature),
            ("enchantment", card.is_enchantment), ("land", card.is_land),
            ("planeswalker", getattr(card, "is_planeswalker", False)),
        ) if present
    }


def active_graveyard_cast_grants(player: "Player", state: "GameState") -> list[GraveyardCastPermissionEffect]:
    """Every currently-active `GraveyardCastPermissionEffect` ``player``
    controls — excluding a ``once_per_turn`` grant whose granting permanent
    has already been used this turn (`GameObject.graveyard_casts_this_turn`,
    reset each untap step)."""
    grants: list[GraveyardCastPermissionEffect] = []
    # A turn-scoped grant ("…gains flashback until end of turn", Will of the Jeskai / Past in Flames) is
    # written onto its own *spell*, which has left the stack for the graveyard or exile by the time anything
    # asks — so those zones are scanned too, for turn-scoped grants only.
    on_battlefield = list(state.permanents_controlled_by(player.id))
    off_battlefield = [*player.graveyard, *player.exile]
    for obj in [*on_battlefield, *off_battlefield]:
        for effect in getattr(obj, "static_effects", None) or []:
            if not isinstance(effect, GraveyardCastPermissionEffect):
                continue
            if effect.expires_turn is None and obj in off_battlefield:
                continue
            if effect.once_per_turn and not effect.per_permanent_type and getattr(obj, "graveyard_casts_this_turn", 0):
                continue
            if effect.expires_turn is not None and effect.expires_turn != state.internal_turn.number:
                continue
            if effect.active_if is not None:
                from . import static_conditions  # function-scoped: static_conditions imports effects' siblings

                if not static_conditions.condition_holds(effect.active_if, state, obj, player.id):
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
    # Prefer an unrestricted route when several permissions overlap.
    for effect in sorted(active_graveyard_cast_grants(player, state), key=lambda e: bool(e.sacrifice_type)):
        if effect.sacrifice_type:
            from .engine.activation_mixin import ActivationMixin

            if not any(ActivationMixin._matches_sacrifice_type(o, effect.sacrifice_type)
                       and not o.cant_be_sacrificed_this_turn
                       for o in state.permanents_controlled_by(player.id)):
                continue
        if effect.permanent_only and not _is_permanent_card(card):
            continue
        if effect.instant_sorcery_only and not (card.is_instant or card.is_sorcery):
            continue
        if effect.max_mana_value is not None and card.converted_mana_cost > effect.max_mana_value:
            continue
        if effect.spell_criteria and not card_query.matches(card, effect.spell_criteria):
            continue
        if effect.per_permanent_type and permanent_types(card) <= getattr(effect.source, "graveyard_cast_types_this_turn", set()):
            continue
        return effect
    return None


def may_cast_spell_from_graveyard(player: "Player", state: "GameState", card: "Card") -> bool:
    return graveyard_cast_grant_for(player, state, card) is not None


def graveyard_land_play_grant_for(player: "Player", state: "GameState", card: "Card") -> Optional[GraveyardCastPermissionEffect]:
    if not card.is_land:
        return None
    for effect in active_graveyard_cast_grants(player, state):
        if effect.lands_only:
            return effect
        if effect.plays_lands and (not effect.spell_criteria or card_query.matches(card, effect.spell_criteria)):
            return effect  # Kethis: "you may play this card from your graveyard" for legendary lands
        if not effect.per_permanent_type:
            continue
        if "land" not in getattr(effect.source, "graveyard_cast_types_this_turn", set()):
            return effect
    return None


def has_temporary_graveyard_play_permission(player: "Player", state: "GameState") -> bool:
    """"Until end of turn, you may play lands and cast spells from your
    graveyard." (Yawgmoth's Will-shaped, MEC-12) — a player-scoped, turn-
    stamped grant distinct from every permission above: those are all
    anchored to some *other* permanent's own `static_effects` and read
    `graveyard_cast_grant_for`'s per-card filters (which explicitly exclude
    lands, since no other permission source ever needed to cover them);
    this one covers the caster's *whole* graveyard, lands included, for
    exactly the turn it was granted on.
    """
    return player.graveyard_play_permission_until_turn == state.internal_turn.number
