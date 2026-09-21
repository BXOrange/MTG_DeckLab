from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gandalf_the_white() -> list[AbilitySpec]:
    """Gandalf the White (Legendary Creature — Avatar Wizard, {3}{W}{W})

    "Flash
    You may cast legendary spells and artifact spells as though they had
    flash.
    If a legendary permanent or an artifact entering or leaving the
    battlefield causes a triggered ability of a permanent you control to
    trigger, that ability triggers an additional time."

    Flash is already parser-claimable. The standing flash-permission
    static reuses `flash_permission`'s new ``type_filter`` (MEC-40,
    ``noncreature_only``/``creature_only``'s sibling for a closed
    "legendary"/"artifact" word list). The trigger-doubling clause is
    Elesh Norn's own ``cause_filter`` widened to *two* event types
    ("entering **or** leaving") plus the new ``cause_type_filter``
    (unlike Elesh Norn's own unscoped "**a** permanent", this one is
    narrowed to legendary permanents/artifacts specifically).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("flash_permission", {"type_filter": ["legendary", "artifact"]})],
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec(
                    "trigger_doubler",
                    {
                        "cause": {
                            "event": ["ENTERS_BATTLEFIELD", "LEAVES_BATTLEFIELD"],
                            "condition": {
                                "subject": "group", "controller": "any", "other": False,
                                "filter": {"any_of": [{"legendary": True}, {"card_type": "artifact"}]},
                            },
                        },
                    },
                )
            ],
        ),
    ]


register("Gandalf the White", _gandalf_the_white)
