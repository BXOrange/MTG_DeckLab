from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _twinflame() -> list[AbilitySpec]:
    """Strive — This spell costs {2}{R} more to cast for each target
    beyond the first.
    Choose any number of target creatures you control. For each of them,
    create a token that's a copy of that creature, except it has haste.
    Exile those tokens at the beginning of the next end step.

    — Strive itself is an already-shipped primitive (`AbilitySpec.
    strive_cost`, `GameEngine`'s per-extra-target cost scaling); the real
    gap was `CopyPermanentEffect` only ever copying its *first* target,
    even when RULE 115.1a's own "any number of target creatures" widens
    the target count past one (MEC-12). Widened with a genuinely new
    ``target_count``/``target_count_max``/``target_optional`` param triple
    (deliberately distinct from the existing ``count``, which still means
    "N copies of the (one) target" — Rite of Replication-shaped, and could
    combine with this on some future card): when the target spec's own
    ``effective_count != 1``, `apply()` now makes one token copy *per*
    chosen target instead of ``count`` copies of just the first, mirroring
    the established `PumpEffect`/`AddCountersEffect` "each of up to N gets
    the full amount" idiom. "Any number of" reuses the parser's own
    ``_ANY_NUMBER_TARGET_CAP`` (10) sentinel. The delayed exile needed one
    small new primitive: `ExileSpecificEffect`, the plural sibling of
    `SacrificeSpecificEffect` (Kiki-Jiki-shaped) — the existing
    `CreateDelayedTriggerEffect`'s ``capture="created_objects"`` branch
    already special-cased any inner effect exposing a plain ``.objects``
    list, but `ExileEffect` only ever carries one ``.target``, silently
    dropping every token past the first for a multi-target source like
    this one.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("copy_permanent", {
                    "target_kind": "creature_you_control", "target_count": 10,
                    "target_optional": True, "haste": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [{"type": "exile_specific", "params": {}}],
                }),
            ],
            strive_cost="{2}{R}",
        ),
    ]


register("Twinflame", _twinflame)
