from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _airtight_alibi() -> list[AbilitySpec]:
    """Flash
    Enchant creature
    When this Aura enters, untap enchanted creature. It gains hexproof
    until end of turn. If it's suspected, it's no longer suspected.
    Enchanted creature gets +2/+2 and can't become suspected.

    — PAR-30 Suspect one-off shapes. Flash / Enchant creature parse off the
    printed text directly. The ETB's three clauses are all shared
    primitives keyed to the Aura's host: `TapEffect` untap
    (``target_kind="attached_permanent"``), `PumpEffect` hexproof-until-EOT
    (the parser's own `pump` shape), and `RemoveSuspectedEffect`'s
    ``attached`` form — RULE 701.60a's reverse already no-ops on a
    non-suspected creature, so "if it's suspected, ..." needs no explicit
    gate. The static is a +2/+2 anthem plus a ``grant_keyword`` slug
    ``"cant_become_suspected"`` the layer engine stamps and
    `RulesEngine.suspect` honours — the only card printing that prohibition,
    so a bespoke keyword rather than a new static kind.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("tap", {"target_kind": "attached_permanent", "untap": True}),
                EffectSpec("pump", {"keywords": ["hexproof"], "target_kind": "attached_permanent"}),
                EffectSpec("remove_suspected", {"attached": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2}),
                EffectSpec("grant_keyword", {
                    "affects": "attached_permanent", "keywords": ["cant_become_suspected"],
                }),
            ],
        ),
    ]


register("Airtight Alibi", _airtight_alibi)
