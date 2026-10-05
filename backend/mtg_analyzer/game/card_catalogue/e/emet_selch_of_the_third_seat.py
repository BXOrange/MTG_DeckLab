from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _emet_selch_of_the_third_seat() -> list[AbilitySpec]:
    """Spells you cast from your graveyard cost {2} less to cast.
    Whenever one or more opponents lose life, you may cast target instant or
    sorcery card from your graveyard. If that spell would be put into your
    graveyard, exile it instead. Do this only once each turn.

    — PLAY-ALL Step 2 (yshtola). The discount is `cost_reduction` with the new
    ``from_graveyard`` param (the card is still in the graveyard while its cost is
    computed). The trigger is a `LIFE_LOST` head (subject ``player``, scope
    ``not_you``) with ``limit`` (once each turn) over MEC-24's per-card
    `grant_flashback_to_target` (Snapcaster's marker, optional, at the card's own
    mana cost): flashback is exactly "cast from the graveyard, exile instead of
    the graveyard". **Documented simplification:** the permission lasts for the
    turn instead of being used at once during the trigger's resolution — a
    superset of the printed timing (the card may be cast later this turn, at the
    normal timing for it). The {2} discount applies to it.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 2, "from_graveyard": True})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_flashback_to_target", {"target_kind": "graveyard_instant_or_sorcery"})],
            trigger={
                "event": EventType.LIFE_LOST,
                "condition": {"subject": "player", "scope": "not_you"},
                "limit": True,
            },
        ),
    ]


register("Emet-Selch of the Third Seat", _emet_selch_of_the_third_seat)
