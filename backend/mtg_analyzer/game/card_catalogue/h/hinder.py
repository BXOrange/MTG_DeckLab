from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hinder() -> list[AbilitySpec]:
    """Counter target spell. If that spell is countered this way, put that card on your choice of the top or bottom
    of its owner's library instead of into that player's graveyard.

    — PAR-161. `counter` with ``library_choice``: the spell leaves the stack for neither zone list, and the
    *countering* player (Hinder's controller, not the spell's owner) answers a `library_position` choice (RULE 401.4).
    Not countered, and so not moved, when it can't be countered (RULE 101.2).
    """
    return [AbilitySpec("spell_effect", [EffectSpec("counter", {"library_choice": True})])]


register("Hinder", _hinder)
