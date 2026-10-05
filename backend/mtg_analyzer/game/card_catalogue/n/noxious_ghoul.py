from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _noxious_ghoul() -> list[AbilitySpec]:
    """Whenever this creature or another Zombie enters, all non-Zombie creatures get -1/-1 until end of turn.

    — PLAY-ALL Step 2 (Wretched Ranks). One group enter trigger (any controller's Zombie, the Ghoul included — it
    is a Zombie itself) over a group `pump` -1/-1 of every non-Zombie creature (``without_subtype``).
    """
    return [AbilitySpec(
        "triggered",
        [EffectSpec("pump", {"power": -1, "toughness": -1, "selector": {
            "zone": "battlefield", "of": "any", "filter": {"card_type": "creature", "without_subtype": "zombie"}}})],
        trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
            "subject": "group", "controller": "any", "other": False, "subtypes": ["zombie"]}},
    )]


register("Noxious Ghoul", _noxious_ghoul)
