from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "a number between 0 and 10".
_MAX_NUMBER = 10


def _expel_the_interlopers() -> list[AbilitySpec]:
    """Choose a number between 0 and 10. Destroy all creatures with power greater than or equal to the chosen number.

    — PLAY-ALL (Abzan Armor). `choose_number_then`: a resolution-time number choice (`RulesEngine._request_number_choice`) whose
    answer replaces the ``"x"`` in the body, a `destroy` over every creature (``min_power``) of any controller.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("choose_number_then", {
            "min": 0, "max": _MAX_NUMBER,
            "then": [{"type": "destroy", "params": {"group": {
                "zone": "battlefield", "of": "any", "filter": {"card_type": "creature", "min_power": "x"},
            }}}],
        })]),
    ]


register("Expel the Interlopers", _expel_the_interlopers)
