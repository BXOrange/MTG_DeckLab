from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sword_of_once_and_future() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2 and has protection from blue and
    from black.
    Whenever equipped creature deals combat damage to a player, surveil
    2. Then you may cast an instant or sorcery spell with mana value 2 or
    less from your graveyard without paying its mana cost. If that spell
    would be put into your graveyard, exile it instead.
    Equip {2}

    — Imodane deck batch. The anthem+protection grant and Equip already
    parse on their own — reproduced verbatim. **Documented
    simplification**: only "surveil 2" is modeled — the trailing "cast an
    instant or sorcery spell with mana value 2 or less from your
    graveyard without paying its mana cost" needs a chooser over
    graveyard cards matching a filter, cast *for free*; the shipped
    graveyard-cast machinery covers either half alone (`dig_until`'s
    ``cast_free_window`` operates on the *library*, not the graveyard;
    `GraveyardCastPermissionEffect`'s graveyard permission is always at
    normal mana cost, never free) but not their combination, so building
    that chooser is disproportionate to this one card.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2}),
                EffectSpec("grant_protection_static", {
                    "affects": "attached_permanent", "protections": ["blue", "black"],
                }),
            ],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("surveil", {"count": 2})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "attached_permanent"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Sword of Once and Future", _sword_of_once_and_future)
