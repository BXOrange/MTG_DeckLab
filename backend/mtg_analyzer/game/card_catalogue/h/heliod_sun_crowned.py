from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _heliod_sun_crowned() -> list[AbilitySpec]:
    """Indestructible
    As long as your devotion to white is less than five, Heliod isn't a
    creature.
    Whenever you gain life, put a +1/+1 counter on target creature or
    enchantment you control.
    {1}{W}: Another target creature gains lifelink until end of turn.

    — MEC-43 round 4D. The devotion-gated "isn't a creature" static is
    already fully `MODELED` by the oracle-text parser (`author_card.py`'s
    own "reuse" output, pasted verbatim below) — the two remaining
    clauses need hand-authoring since registering this card overrides the
    parser fallback entirely rather than merging with it. The life-gain
    trigger reuses `EventType.LIFE_GAINED`'s existing ``{"subject": "you"}``
    condition (Prize Pig/Angel of Vitality-shaped) plus a new
    `targeting.py` kind, ``"creature_or_enchantment_you_control"`` (the
    two-type-union sibling of `creature_you_control`). The lifelink grant
    is `PumpEffect`'s already-general 0/0-pump-plus-keyword shape
    (``target_kind="creature"`` already excludes the ability's own source
    by construction, matching the printed "**another** target creature" —
    no new target kind needed).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {
                "remove_types": ["creature"],
                "active_if": {"kind": "control_count", "selector": "devotion_to_white", "max": 4},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "kind": "+1/+1", "amount": 1,
                "target_kind": "creature_or_enchantment_you_control",
            })],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"keywords": ["lifelink"], "target_kind": "creature"})],
            cost={"text": "{1}{W}"},
        ),
    ]


register("Heliod, Sun-Crowned", _heliod_sun_crowned)
