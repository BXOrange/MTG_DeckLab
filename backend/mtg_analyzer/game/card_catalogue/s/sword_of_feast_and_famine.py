from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sword_of_feast_and_famine() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2 and has protection from black and from
    green.
    Whenever equipped creature deals combat damage to a player, that
    player discards a card and you untap all lands you control.
    Equip {2}

    — MEC-43 round 4A. The static half is already fully `MODELED` by the
    oracle-text parser (the anthem + `grant_protection_static` pair every
    other Sword already uses) — reused as-is. Only the trigger needs
    hand-authoring: the "whenever equipped creature deals combat damage to
    a player" shape itself is the parser's own already-shipped
    ``condition={"subject": "attached_permanent"}`` (confirmed by parsing
    that clause alone against a simpler effect), but this card's own effect
    body has two new pieces — `DiscardEffect.player_from_trigger_event`
    ("that player" is the DAMAGE event's own recipient, not a target) and
    `TapEffect`'s ``selector`` whitelist widened with ``"lands_you_control"``
    (`continuous.group_selector_objects` already supports it; only the
    `TapEffect`-side gate was missing it).
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"power": 2, "toughness": 2, "affects": "attached_permanent"}),
                EffectSpec("grant_protection_static", {
                    "affects": "attached_permanent", "protections": ["black", "green"],
                }),
            ],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("discard", {"count": 1, "player_from_trigger_event": True}),
                EffectSpec("tap", {"untap": True, "selector": "lands_you_control"}),
            ],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "attached_permanent"},
                "filter": {"is_player": True, "combat": True},
            },
        ),
    ]


register("Sword of Feast and Famine", _sword_of_feast_and_famine)
