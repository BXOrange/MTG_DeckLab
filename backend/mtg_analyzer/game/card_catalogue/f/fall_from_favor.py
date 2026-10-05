from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fall_from_favor() -> list[AbilitySpec]:
    """Enchant creature
    When this Aura enters, tap enchanted creature and you become the monarch.
    Enchanted creature doesn't untap during its controller's untap step unless that player is the
    monarch.

    — Keen Engineering deck batch. Enchant creature is the keyword; the ETB is the parser's own claim.
    The static is `no_untap` over the attached permanent gated by ``active_if: not
    controlled_by_monarch(attached)`` — the new condition asks about the *enchanted creature's
    controller*, not the Aura's.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"target_kind": "attached_permanent", "untap": False}),
             EffectSpec("become_monarch", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec("static", [EffectSpec("no_untap", {
            "affects": "attached_permanent",
            "active_if": {"kind": "not", "condition": {"kind": "controlled_by_monarch", "of": "attached"}},
        })]),
    ]


register("Fall from Favor", _fall_from_favor)
