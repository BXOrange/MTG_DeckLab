from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _grinding_station() -> list[AbilitySpec]:
    """{T}, Sacrifice an artifact: Target player mills three cards.
    Whenever an artifact enters, you may untap this artifact.

    The untap names ``target_kind="source"`` rather than the bare ``None``
    that means the same thing, because this is a RULE 603.1 ``"group"``
    trigger: `effect_binder._retarget_implicit_subject_effects` rewrites a
    bare ``None`` there into "whichever object fired the trigger" (right for
    Raiyuu's "untap **it**", wrong here — RULE 109.2's "this artifact" is
    Grinding Station itself). Untapping the artifact that just entered is a
    silent no-op, which is exactly how this went unnoticed.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("mill", {"count": 3, "target_kind": "player"})],
            cost={"text": "{T}, Sacrifice an artifact"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"target_kind": "source", "untap": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "group", "type": "artifact"}},
            optional=True,
        ),
    ]


register("Grinding Station", _grinding_station)
