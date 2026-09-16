from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mirage_mirror() -> list[AbilitySpec]:
    """{2}: This artifact becomes a copy of target artifact, creature,
    enchantment, or land until end of turn.

    — Mirage Mirror. ``target_kind="permanent"`` is broader than the
    printed four-type union (no target kind names exactly "artifact,
    creature, enchantment, or land" — it only additionally admits a
    planeswalker), the same simplification tier Clever Impersonator's own
    `enter_as_copy` entry already documents for "any nonland permanent".
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("become_copy_until_eot", {"target_kind": "permanent"})],
            cost={"mana": "{2}"},
        )
    ]


register("Mirage Mirror", _mirage_mirror)
