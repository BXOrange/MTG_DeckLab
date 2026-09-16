from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _march_of_swirling_mist() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may exile any number
    of blue cards from your hand. This spell costs {2} less to cast for
    each card exiled this way.
    Up to X target creatures phase out. (While they're phased out,
    they're treated as though they don't exist. Each one phases in before
    its controller untaps during their next untap step.)

    — MEC-42. Neither clause had a primitive: the additional cost needed a
    genuine RULE 601.2b "announce a value, adjust cost, then pay it"
    shape (mirroring Kicker's own sequencing exactly, just subtracting
    generic instead of adding it) — new `cast_spell`/`can_cast`/`effective_
    cast_cost` param ``exile_discount``, gated by a new `exile_discount_
    cost` static (`continuous.exile_discount_spec_for`, read straight off
    the spell's own `static_effects` in hand, the same way Delve/
    Affinity's own printed "costs less" static already is) so the
    mechanism stays generic rather than hardcoded to blue/{2}. "Up to X
    target creatures phase out" needed `PhaseOutEffect` widened from a
    single fixed target to a real multi-target count (`TargetSpec.
    count_selector`'s new ``"source_x_paid"`` entry, reading `GameObject.
    x_paid` — the spell's own announced {X} — fresh at target-gathering
    time, the same "read a live count, not a printed one" idiom Goad's
    own count-selector already established for a different source).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("exile_discount_cost", {"color": "U", "generic_per_card": 2})],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("phase_out", {
                "target_kind": "creature", "optional": True, "count_selector": "source_x_paid",
            })],
        ),
    ]


register("March of Swirling Mist", _march_of_swirling_mist)
