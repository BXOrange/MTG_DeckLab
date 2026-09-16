from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tainted_pact() -> list[AbilitySpec]:
    """Exile the top card of your library. You may put that card into
    your hand unless it has the same name as another card exiled this
    way. Repeat this process until you put a card into your hand or you
    exile two cards with the same name, whichever comes first.

    — MEC-12 (sixth pass). `ExileUntilDuplicateNameEffect`/`RulesEngine.
    exile_until_duplicate_name` — a new, genuinely general RULE 701.19-
    adjacent loop shape (see its own docstring for why it's not an
    instance of `dig_until`), confirmed a singleton template cache-wide
    but built as a real primitive anyway since the loop has no card-
    specific data in it. A real interactive choice each time a fresh
    (non-duplicate) name comes up with cards still left in the library —
    take it, or keep digging (the real reason this card is played: paired
    with Thassa's Oracle in a singleton deck, deliberately declining every
    hit mills the whole library on purpose).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile_until_duplicate_name", {})],
        ),
    ]


register("Tainted Pact", _tainted_pact)
