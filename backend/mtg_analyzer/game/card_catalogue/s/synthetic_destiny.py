from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _synthetic_destiny() -> list[AbilitySpec]:
    """Exile all creatures you control. At the beginning of the next end step, reveal cards from the top of your library
    until you reveal that many creature cards, put all creature cards revealed this way onto the battlefield, then shuffle the
    rest of the revealed cards into your library.

    — PLAY-ALL (Multiverse Reforged). Mass Polymorph's `exile_creatures_reveal_that_many` with ``delayed``: the count is read as
    the creatures are exiled and baked into a RULE 603.7 delayed trigger for the next end step.
    """
    return [AbilitySpec("spell_effect", [EffectSpec("exile_creatures_reveal_that_many", {"delayed": True})])]


register("Synthetic Destiny", _synthetic_destiny)
