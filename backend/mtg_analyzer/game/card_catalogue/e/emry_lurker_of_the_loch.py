from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _emry_lurker_of_the_loch() -> list[AbilitySpec]:
    """Affinity for artifacts (This spell costs {1} less to cast for each
    artifact you control.)
    When Emry enters, mill four cards.
    {T}: Choose target artifact card in your graveyard. You may cast that card
    this turn. (You still pay its costs. Timing rules still apply.)

    — PLAY-ALL Step 2 (Counter Intelligence). Affinity is the keyword fold-in
    and the mill the parser's own claim, reproduced. "You may cast that card
    this turn" is MEC-24's per-card `grant_flashback_to_target` (Snapcaster
    Mage's marker, with ``as_permission=True`` for normal casting) aimed at
    ``graveyard_artifact``: it marks exactly the chosen card, survives Emry
    leaving, and pays normal costs under normal timing rules. This permission
    does not impose flashback's exile replacement; a countered spell goes to
    the graveyard and needs a fresh permission to be cast again.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("mill", {"count": 4})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_flashback_to_target", {"target_kind": "graveyard_artifact", "as_permission": True})],
            cost={"text": "{T}"},
        ),
    ]


register("Emry, Lurker of the Loch", _emry_lurker_of_the_loch)
