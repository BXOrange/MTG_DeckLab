from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mass_polymorph() -> list[AbilitySpec]:
    """Exile all creatures you control, then reveal cards from the top of your library until you reveal that many creature
    cards. Put all creature cards revealed this way onto the battlefield, then shuffle the rest of the revealed cards into
    your library.

    — PLAY-ALL (Multiverse Reforged). One `exile_creatures_reveal_that_many` effect: it exiles the controller's creatures
    (tokens included), counts them once, and runs `RulesEngine.reveal_until_matching` for that many creature cards, the rest
    shuffled back (RULE 701.20).
    """
    return [AbilitySpec("spell_effect", [EffectSpec("exile_creatures_reveal_that_many", {})])]


register("Mass Polymorph", _mass_polymorph)
