"""Standing "play/cast from the top of your library" permission.

RULE 701 has no native "play from the top of your library" provision — every
real card (Oracle of Mul Daya, Glarb, Calamity's Augur, Future Sight-shaped)
grants it as its own static ability (`TopLibraryPermissionEffect`,
`game/effects.py`), bound onto the granting permanent's own
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

from .effects import TopLibraryPermissionEffect

if TYPE_CHECKING:
    from ..models.card import Card
    from ..models.game_object import GameObject
    from ..models.game_state import GameState
    from ..models.player import Player


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


def may_cast_spell_from_top_of_library(player: "Player", state: "GameState", card: "Card") -> bool:
    """Whether ``card`` — the top card, a non-land spell — is castable from
    there right now. Multiple simultaneous grants OR together: a spell is
    castable if *any* active grant's ``min_mana_value`` gate (or lack of
    one) allows it (RULE 702-style "mana value N or greater", e.g. Glarb),
    never the intersection of every grant's own filter.
    """
    mv = card.converted_mana_cost
    return any(
        g.cast_spells and (g.min_mana_value is None or mv >= g.min_mana_value)
        for g in active_top_library_grants(player, state)
    )
