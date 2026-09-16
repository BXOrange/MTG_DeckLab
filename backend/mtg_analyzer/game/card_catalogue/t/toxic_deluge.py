from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _toxic_deluge() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, pay X life.
    All creatures get -X/-X until end of turn.

    — Toxic Deluge. X here comes entirely from the announced additional-
    cost life payment (RULE 601.2b), not a mana ``{X}`` — `RulesEngine.
    cast_spell`/`GameEngine._pay_additional_cast_cost` already thread a
    caller-supplied ``x`` through ``additional_cost={"pay_life": "x"}``
    regardless of whether the printed mana cost itself has a variable
    symbol. `RulesEngine._substitute_x` was extended this batch to also
    rewrite a `pump` effect's own ``power``/``toughness`` fields (not just
    ``amount``/``count``), including a new ``"-x"`` sentinel for an
    X-scaled *debuff* whose X isn't itself negative.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("pump", {"power": "-x", "toughness": "-x", "selector": "all_creatures"})],
            additional_cost={"pay_life": "x"},
        )
    ]


register("Toxic Deluge", _toxic_deluge)
