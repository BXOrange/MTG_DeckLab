from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _empowered_autogenerator() -> list[AbilitySpec]:
    """This artifact enters tapped.
    {T}: Put a charge counter on this artifact. Add X mana of any one color,
    where X is the number of charge counters on this artifact.

    — PLAY-ALL Step 2 (Counter Intelligence). Enters-tapped is oracle-derived.
    The ability is Astral Cornucopia's `add_mana` (``ANY`` colour, amount =
    ``charge_counters_on_source``) preceded by the counter. It must be a
    resolving effect, not a mana ability: RULE 605.1a would allow it, but the
    counter is placed first so X already includes it, which only holds when
    the two clauses run in order. **Simplification:** it uses the stack like
    any activated ability (a real mana ability would not), same as Cornucopia's
    own pool-adding effect.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"count": 1, "kind": "charge"}),
                EffectSpec("add_mana", {"colors": ["ANY"], "amount_selector": "charge_counters_on_source"}),
            ],
            cost={"text": "{T}"},
        ),
    ]


register("Empowered Autogenerator", _empowered_autogenerator)
