from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _aether_gust() -> list[AbilitySpec]:
    """Choose target spell or permanent that's red or green. Its owner puts it on their choice of the top or bottom of their library.

    — PAR-161. `owner_puts_on_top_or_bottom` (a RULE 401.4 `library_position` choice opened for the target's *owner*) over the
    ``spell_or_permanent`` target kind, narrowed to red-or-green objects on the stack and the battlefield through ``colors``
    (RULE 105; `TargetSpec.colors` is an OR). A spell target leaves the stack via `move_spell_off_stack`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("owner_puts_on_top_or_bottom", {
                "target_kind": "spell_or_permanent", "optional": False, "colors": ["R", "G"],
            })],
        ),
    ]


register("Aether Gust", _aether_gust)
