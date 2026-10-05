from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gratuitous_violence() -> list[AbilitySpec]:
    """If a creature you control would deal damage to a permanent or
    player, it deals double that damage to that permanent or player
    instead.

    — Gratuitous Violence. `double_damage` scoped to ``creature_only`` +
    ``your_sources_only`` — narrower than Furnace of Rath's unscoped
    version (a non-creature source you control, e.g. a burn spell or an
    artifact, is untouched), but *not* combat-restricted despite the name —
    the real printed text has no "combat" qualifier at all, unlike what an
    earlier version of this entry assumed.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_damage", {"creature_only": True, "your_sources_only": True})],
        )
    ]


register("Gratuitous Violence", _gratuitous_violence)
