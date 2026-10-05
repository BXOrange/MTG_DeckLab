from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lier_disciple_of_the_drowned() -> list[AbilitySpec]:
    """Spells can't be countered.
    Each instant and sorcery card in your graveyard has flashback. The flashback cost is
    equal to that card's mana cost.

    — Jeskai Striker deck batch. The first line is `grant_cant_be_countered` with the new
    ``all_spells`` scope (`RulesEngine._is_cant_be_countered`: every spell, either player's).
    The second is the standing sibling of Backdraft Hellkite's turn-scoped grant:
    `graveyard_cast_permission` limited to instants/sorceries (``instant_sorcery_only``),
    unlimited per turn, paid at the card's own mana cost, and exiled instead of going back
    to the graveyard (RULE 702.34a — a spell cast with flashback is exiled as it leaves the stack).
    """
    return [
        AbilitySpec("static", [EffectSpec("grant_cant_be_countered", {"scope": "all_spells"})]),
        AbilitySpec("static", [EffectSpec("graveyard_cast_permission", {
            "permanent_only": False, "once_per_turn": False, "instant_sorcery_only": True,
            "exile_if_would_be_put_into_graveyard": True,
        })]),
    ]


register("Lier, Disciple of the Drowned", _lier_disciple_of_the_drowned)
