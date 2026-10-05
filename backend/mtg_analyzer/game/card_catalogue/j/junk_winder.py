from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _junk_winder() -> list[AbilitySpec]:
    """Affinity for tokens (This spell costs {1} less to cast for each token you control.)
    Whenever a token you control enters, tap target nonland permanent an opponent controls. It doesn't untap
    during its controller's next untap step.

    — Family Matters deck batch. Affinity is the keyword fold-in. The trigger is the parser's group
    token-entry head with the claimed tap-and-skip-next-untap body (`tap` then `skip_next_untap` on the same
    target), widened to a nonland permanent an opponent controls.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"target_kind": "nonland_permanent_you_dont_control", "untap": False}),
             EffectSpec("skip_next_untap", {"previous_subject": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": False, "filter": {"token": True}}},
        ),
    ]


register("Junk Winder", _junk_winder)
