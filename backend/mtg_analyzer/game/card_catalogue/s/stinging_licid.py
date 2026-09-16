from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import EffectSpec
from .._shared.licid import _licid
from ...card_registry.core import register


def _stinging_licid() -> list:
    """{1}{U}, {T}: This creature loses this ability and becomes an Aura
    enchantment with enchant creature. Attach it to target creature. You
    may pay {U} to end this effect.
    Whenever enchanted creature becomes tapped, this creature deals 2
    damage to that creature's controller.

    — MEC-47 Tempest Licid cycle (pass 3, the triggered-grant Licids):
    shares `card_catalogue/_shared/licid.py`'s `_licid` factory; the granted
    clause triggers off the *enchanted permanent* becoming tapped.
    """
    return _licid(
        "Stinging Licid", "{1}{U}", "{U}",
        [EffectSpec("damage", {"amount": 2, "recipient_subject": "trigger_subject_controller"})],
        "Whenever enchanted creature becomes tapped, this creature deals 2 damage "
        "to that creature's controller.",
        granted_kind="triggered",
        trigger={"event": EventType.TAPPED, "condition": {"subject": "attached_permanent"}},
    )


register("Stinging Licid", _stinging_licid)
