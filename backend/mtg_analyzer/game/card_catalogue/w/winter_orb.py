from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _winter_orb() -> list[AbilitySpec]:
    """As long as this artifact is untapped, players can't untap more than
    one land during their untap steps.

    — Winter Orb. A static family (`continuous.active_untap_caps`,
    `GameEngine._step_untap`), distinct from `no_untap` (which restricts
    one specific *permanent*, not a global per-player cap) and from
    `enters_tapped_static`'s opponent-scoped board-wide family (this is
    unscoped by ownership). The tapped-state gate is the ordinary RULE
    613.6 ``active_if`` wrapper every other conditional static uses, not a
    hardcoded check — Static Orb/Winter Moon (`parser/oracle/catalogue/
    static_handlers.py`'s ``_UNTAP_CAP_RE``) reuse the same family,
    ``card_type``/``nonbasic`` widening it past lands-only. Auto-picks
    which land(s) stay tapped (the same non-interactive MVP simplification
    `_sacrifice_candidate`'s callers already make elsewhere).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("untap_cap", {"count": 1, "active_if": {"kind": "source_untapped"}})],
        )
    ]


register("Winter Orb", _winter_orb)
