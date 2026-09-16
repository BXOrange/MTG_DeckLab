from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _etali_primal_storm() -> list[AbilitySpec]:
    """Whenever Etali attacks, exile the top card of each player's
    library, then you may cast any number of spells from among those
    cards without paying their mana costs.

    — Imodane deck batch. `exile_top_from_each_player_cast_free` — see its
    docstring. **Bug fixed** (checked against Scryfall's own ruling #5,
    "any cards not cast, including land cards, remain in exile," 2026-09-04):
    the effect used to grant every exiled card — lands included — a
    `grant_free_cast_window_from_exile` permission, and that permission is
    generic enough to also satisfy `GameEngine.can_play_land` (it backs
    cards like Ragavan/Light Up the Stage that genuinely *do* let a found
    land be played) — so an exiled land was wrongly playable as a land.
    The effect now skips the free-cast/-play grant for a land card
    entirely while still exiling it (dead forever, per the ruling).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_top_from_each_player_cast_free", {})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Etali, Primal Storm", _etali_primal_storm)
