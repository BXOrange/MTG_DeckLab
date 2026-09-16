from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Stensian Sanguinist (attack -> grant deathtouch -> prepared) —
# PAR-60
# ===========================================================================
# Pure reuse: `PLAYER_ATTACKED` + `grant_until` (deathtouch) + a DAMAGE


def _stensian_sanguinist() -> list[AbilitySpec]:
    """Whenever you attack, target creature gains deathtouch until end of
    turn. Whenever that creature deals combat damage to a player this
    combat, this creature becomes prepared.

    Documented simplification: the "that creature" link between the two
    clauses is approximated as "a creature you control" (no linked-target
    delayed-DAMAGE-trigger primitive) — Stensian's own grant-then-connect
    intent is preserved."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_until", {
                "target_kind": "creature", "duration": "end_of_turn",
                "static": {"type": "grant_keyword", "params": {"keywords": ["deathtouch"]}},
            })],
            trigger={"event": EventType.PLAYER_ATTACKED, "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={"event": EventType.DAMAGE,
                     "condition": {"subject": "group", "controller": "you", "type": "creature"},
                     "filter": {"combat": True, "is_player": True}},
        ),
    ]


register("Stensian Sanguinist", _stensian_sanguinist)
register("Stensian Sanguinist // Exsanguinate", _stensian_sanguinist)
