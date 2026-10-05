from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _icy_blast() -> list[AbilitySpec]:
    """Tap X target creatures.
    Ferocious — If you control a creature with power 4 or greater, those
    creatures don't untap during their controllers' next untap steps.

    — PLAY-ALL Step 2 (Hydranten). The tap clause is the parser's own claim,
    reproduced verbatim (X targets via ``count_selector="source_x_paid"``).
    The ferocious half is `skip_next_untap` over ``previous_subject`` — "those
    creatures" are every target the tap clause just had, the `[tap,
    skip_next_untap]` pair the tempo family already uses — gated by an
    effect-level ``condition`` — the flat key ``controls_creature_power_at_least``
    (`effect_conditions`' translator, which expands it to a `control_count` with
    ``min_power`` *and* ``min: 1``; a hand-written `control_count` without that
    ``min`` is always true), checked as the spell resolves (RULE 608.2c), not
    at cast.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("tap", {
                    "target_kind": "creature", "count": 10, "count_selector": "source_x_paid",
                    "optional": True, "untap": False,
                }),
                EffectSpec(
                    "skip_next_untap", {"previous_subject": True},
                    condition={"controls_creature_power_at_least": 4},
                ),
            ],
        )
    ]


register("Icy Blast", _icy_blast)
