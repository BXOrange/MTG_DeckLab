from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "cost {2} more to cast" -- the printed generic surcharge.
_SURCHARGE = 2


def _aven_interrupter() -> list[AbilitySpec]:
    """Flash
    Flying
    When this creature enters, exile target spell. It becomes plotted. (Its owner may cast it as a sorcery on a later
    turn without paying its mana cost.)
    Spells your opponents cast from graveyards or from exile cost {2} more to cast.

    Flash and Flying come from the keyword catalogue. The ETB is `exile_target_spell_and_plot` (RULE 702.170, new
    plotted designation). The tax is the `cost_reduction` static's ``increase`` form scoped to
    ``opponents_spells`` with the new ``from_graveyard_or_exile`` zone test (RULE 601.2f).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_target_spell_and_plot", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec("static", [EffectSpec("cost_reduction", {
            "affects": "opponents_spells", "generic": _SURCHARGE, "increase": True, "from_graveyard_or_exile": True,
        })]),
    ]


register("Aven Interrupter", _aven_interrupter)
