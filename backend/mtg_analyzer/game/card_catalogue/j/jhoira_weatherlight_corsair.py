from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jhoira_weatherlight_corsair() -> list[AbilitySpec]:
    """Whenever Jhoira enters or attacks, target opponent reveals cards from the top of their library until they reveal a
    historic permanent card. You put that card onto the battlefield under your control and lose life equal to that permanent's
    mana value. That player puts the rest of the revealed cards on the bottom of their library in a random order. (Artifacts,
    legendaries, and Sagas are historic.)

    — PLAY-ALL (Multiverse Reforged). Two triggers (enters, attacks) over `reveal_opponent_library_steal`; "historic permanent
    card" is the `card_query` ``type`` OR-list Artifact / Legendary / Saga (an instant or sorcery is never a permanent card,
    and none is legendary or an artifact).
    """
    def _steal() -> list[EffectSpec]:
        return [EffectSpec("reveal_opponent_library_steal", {"criteria": {"type": ["Artifact", "Legendary", "Saga"]}})]

    return [
        AbilitySpec("triggered", _steal(), trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}}),
        AbilitySpec("triggered", _steal(), trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}}),
    ]


register("Jhoira, Weatherlight Corsair", _jhoira_weatherlight_corsair)
