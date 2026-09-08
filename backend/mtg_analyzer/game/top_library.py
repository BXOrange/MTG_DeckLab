"""Standing "play/cast from the top of your library" permission.

RULE 701 has no native "play from the top of your library" provision — every
real card (Oracle of Mul Daya, Glarb, Calamity's Augur, Future Sight-shaped)
grants it as its own static ability (`TopLibraryPermissionEffect`,
`game/effects/core.py`), bound onto the granting permanent's own
``obj.static_effects`` like any other ``static`` ability. This module reads
those grants live off the battlefield — mirroring `game/mana_abilities.py`'s
"scan on demand" shape rather than a cached/recomputed derived field, since
it's consulted only at the handful of legal-action decision points below
(`GameEngine.can_play_land`/`can_cast`/`legal_actions`), not every SBA pass.

Reading live also means the permission disappears the instant its granting
permanent leaves the battlefield (or, for an Equipment/Reconfigure-shaped
grant, the instant it's unattached) with no separate cleanup step needed —
the same reason `continuous.recompute` re-derives every layer from scratch
each pass instead of tracking "effects that used to apply".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .effects.core import TopLibraryPermissionEffect

if TYPE_CHECKING:
    from ..models.cards.card import Card
    from ..models.game.game_object import GameObject
    from ..models.game.game_state import GameState
    from ..models.game.player import Player


def active_top_library_grants(player: "Player", state: "GameState") -> list[TopLibraryPermissionEffect]:
    """Every currently-active `TopLibraryPermissionEffect` ``player`` controls.

    An Equipment/Reconfigure-shaped grant (``requires_attached``) only
    counts while its source is actually attached to something — the same
    "as long as attached" gate real cards like this print (e.g. The Reality
    Chip, not yet in the local card cache to hand-author but supported by
    this same mechanism once it is).
    """
    grants: list[TopLibraryPermissionEffect] = []
    for obj in state.permanents_controlled_by(player.id):
        for effect in getattr(obj, "static_effects", None) or []:
            if not isinstance(effect, TopLibraryPermissionEffect):
                continue
            if effect.requires_attached and getattr(obj, "attached_to", None) is None:
                continue
            grants.append(effect)
    return grants


def may_look_at_top_of_library(player: "Player", state: "GameState") -> bool:
    """Whether the top of ``player``'s library should be shown to them at all.

    True for any active grant, regardless of its specific ``look``/
    ``play_lands``/``cast_spells`` split — a permission to play cards from
    the top implies seeing them (no real card grants play rights without
    also granting visibility).
    """
    return bool(active_top_library_grants(player, state))


def may_play_land_from_top_of_library(player: "Player", state: "GameState") -> bool:
    return any(g.play_lands for g in active_top_library_grants(player, state))


def _grant_permits_cast(grant: TopLibraryPermissionEffect, card: "Card") -> bool:
    """Whether a single ``grant`` — already known active — permits casting
    ``card`` from the top: the shared ``cast_spells``/``min_mana_value``/
    ``noncreature_only`` gate every consumer below checks identically."""
    if not grant.cast_spells:
        return False
    if grant.min_mana_value is not None and card.converted_mana_cost < grant.min_mana_value:
        return False
    if grant.noncreature_only and getattr(card, "is_creature", False):
        return False
    if grant.creature_only and not getattr(card, "is_creature", False):
        return False
    if grant.subtypes:
        type_line = (card.type_line or "").lower()
        if not any(s in type_line for s in grant.subtypes):
            return False
    if grant.chosen_type_creature_only:
        # Realmwalker: "creature spells of the chosen type" — the type is
        # only known once its own RULE 601.2b ETB choice has been made, so
        # this reads it live off the granting permanent rather than being a
        # closed-vocabulary flag like `noncreature_only`.
        if not getattr(card, "is_creature", False):
            return False
        wanted = getattr(grant.source, "chosen_type", None)
        if not wanted or wanted.lower() not in (card.type_line or "").lower():
            return False
    return True


def may_cast_spell_from_top_of_library(player: "Player", state: "GameState", card: "Card") -> bool:
    """Whether ``card`` — the top card, a non-land spell — is castable from
    there right now. Multiple simultaneous grants OR together: a spell is
    castable if *any* active grant's ``min_mana_value``/``noncreature_only``
    gate (or lack of one) allows it (RULE 702-style "mana value N or
    greater", e.g. Glarb; "noncreature spells", e.g. Elsha of the Infinite),
    never the intersection of every grant's own filter.
    """
    return any(_grant_permits_cast(g, card) for g in active_top_library_grants(player, state))


def may_cast_flash_from_top_of_library(player: "Player", state: "GameState", card: "Card") -> bool:
    """Whether ``card`` may be cast from the top of the library as though it
    had flash (Elsha of the Infinite's own conditional tail, RULE 702.8b) —
    true when some grant that actually permits casting ``card`` this way
    also carries ``grants_flash``.
    """
    return any(
        g.grants_flash and _grant_permits_cast(g, card)
        for g in active_top_library_grants(player, state)
    )


def top_library_life_payment_required(player: "Player", state: "GameState", card: "Card") -> bool:
    """Whether casting ``card`` from the top of the library this way pays
    life equal to its mana value *instead of* its mana cost (Bolas's
    Citadel's own conditional tail) — a mandatory substitution, not an
    optional alternative, so this is consulted automatically by
    `GameEngine.can_cast`/`_cast_current_face` rather than through a
    caller-supplied flag (unlike Kicker/Buyback/the RULE 601.2f free-cast
    condition, which the caller opts into).
    """
    return any(
        g.life_payment and _grant_permits_cast(g, card)
        for g in active_top_library_grants(player, state)
    )
