from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _legion_loyalist() -> list[AbilitySpec]:
    """Haste
    Battalion — Whenever this creature and at least two other creatures
    attack, creatures you control gain first strike and trample until end
    of turn and can't be blocked by creature tokens this turn.

    — Legion Loyalist. Haste comes from the RULE 702 keyword catalogue. The
    head is the parser's own Battalion shape (Boros Elite's
    `attackers_declared`); the body is two existing group primitives that
    both resolve against the same set of creatures: Blossoming Bogbeast's
    keyword-only group `pump`, and `combat_restriction_this_turn`'s
    ``selector`` form carrying a `cant_be_blocked_by` restriction filtered
    to tokens (`combat.matches_object_filter`'s ``token`` key). Both act
    when the trigger resolves (RULE 611.2c: the set is fixed then), so a
    creature that enters afterwards gets neither.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("pump", {
                    "selector": "creatures_you_control", "power": 0, "toughness": 0,
                    "keywords": ["first_strike", "trample"],
                }),
                EffectSpec("combat_restriction_this_turn", {
                    "selector": "creatures_you_control",
                    "restriction": {"kind": "cant_be_blocked_by", "filter": {"token": True}},
                }),
            ],
            trigger={
                "event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"},
                "attackers_declared": {
                    "filter": {"card_type": "creature"}, "min": 2, "other": True,
                    "includes_source": True,
                },
            },
        ),
    ]


register("Legion Loyalist", _legion_loyalist)
