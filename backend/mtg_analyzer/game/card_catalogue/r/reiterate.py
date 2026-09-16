from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _reiterate() -> list[AbilitySpec]:
    """Buyback {3}
    Copy target instant or sorcery spell. You may choose new targets for the
    copy.

    — Reiterate. Needed nothing new at all: Buyback (RULE 702.27) has been a
    real, payable additional cost since the keyword catalogue landed
    (`GameEngine._buyback_cost`/`GameObject.buyback_paid`, with
    `RulesEngine.resolve_top_of_stack` returning the card to hand instead of
    the graveyard), and `CopySpellEffect` was already built — its own
    docstring names Reiterate. It was simply never registered, so the
    fail-closed coverage gate left the card `UNMODELED` on the strength of
    the unparsed body. Registering it is the whole fix.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"]})],
        ),
    ]


register("Reiterate", _reiterate)
