from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import EffectSpec
from .._shared.licid import _licid
from ...card_registry.core import register


def _leeching_licid() -> list:
    """{B}, {T}: This creature loses this ability and becomes an Aura
    enchantment with enchant creature. Attach it to target creature. You
    may pay {B} to end this effect.
    At the beginning of the upkeep of enchanted creature's controller, this
    creature deals 1 damage to that player.

    — MEC-47 Tempest Licid cycle (pass 3, the triggered-grant Licids):
    shares `card_catalogue/_shared/licid.py`'s `_licid` factory; the granted
    clause is a triggered ability keyed to the *enchanted permanent's*
    controller's own upkeep (``phase_relation="attached_permanent"``).
    """
    return _licid(
        "Leeching Licid", "{B}", "{B}",
        [EffectSpec("damage", {"amount": 1, "recipient_subject": "attached_permanent_controller"})],
        "At the beginning of the upkeep of enchanted creature's controller, this "
        "creature deals 1 damage to that player.",
        granted_kind="triggered",
        trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                 "phase_relation": "attached_permanent"},
    )


register("Leeching Licid", _leeching_licid)
