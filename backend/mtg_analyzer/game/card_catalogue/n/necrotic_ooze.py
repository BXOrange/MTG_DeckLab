from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _necrotic_ooze() -> list[AbilitySpec]:
    """As long as this creature is on the battlefield, it has all
    activated abilities of all creature cards in all graveyards.

    — The third ``source_mode`` for `grant_borrowed_activated_ability`
    (MEC-12, alongside MEC-21/MEC-26's ``exiled_with``/``group``/
    ``chosen_permanent``): ``"all_graveyards"`` reads straight off every
    player's live `Player.graveyard` list rather than a single donor or a
    battlefield selector — the "in all graveyards" scope this card is
    actually named for. `continuous._apply_borrowed_activated_abilities`'s
    existing per-(grantee, donor, ability-index) caching, RULE 113.7c
    source-redirect, and creature-only donor filter are all reused as-is;
    "as long as this creature is on the battlefield" needs no `active_if`
    gate — a static ability only ever applies while its own source is on
    the battlefield in the first place (RULE 613.1).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "self",
                "source_mode": "all_graveyards",
            })],
        ),
    ]


register("Necrotic Ooze", _necrotic_ooze)
