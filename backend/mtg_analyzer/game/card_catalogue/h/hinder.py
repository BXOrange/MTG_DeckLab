from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hinder() -> list[AbilitySpec]:
    """Counter target spell. If that spell is countered this way, put that card on your choice of the top or bottom of its owner's
    library instead of into that player's graveyard.

    — PAR-161. `counter` with ``library_choice``: the caster (not the spell's owner) answers a RULE 401.4 `library_position` choice, and the
    answer performs the counter with the library as the landing zone (RULE 614.1 replaces the graveyard). A spell that can't be countered
    never asks and stays on the stack (RULE 701.5b); a copy ceases to exist.
    """
    return [AbilitySpec("spell_effect", [EffectSpec("counter", {"library_choice": True})])]


register("Hinder", _hinder)
