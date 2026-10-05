from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _reflection_of_kiki_jiki() -> list[AbilitySpec]:
    """{1}, {T}: Create a token that's a copy of another target nonlegendary
    creature you control, except it has haste. Sacrifice it at the beginning
    of the next end step.
    """
    return [AbilitySpec("activated", [
        EffectSpec("copy_permanent", {
            "target_kind": "other_creature_you_control", "haste": True,
            "creature_filter": {"nonlegendary": True},
        }),
        EffectSpec("create_delayed_trigger", {
            "step": "end", "scope": "any", "capture": "created_objects",
            "effects": [{"type": "sacrifice_specific", "params": {}}],
        }),
    ], cost={"text": "{1}, {T}"})]


register("Reflection of Kiki-Jiki", _reflection_of_kiki_jiki)
