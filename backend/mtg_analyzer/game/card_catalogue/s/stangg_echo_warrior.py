from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _stangg_echo_warrior() -> list[AbilitySpec]:
    """Whenever Stangg attacks, create Stangg Twin, a legendary 3/4 red and
    green Human Warrior creature token. It enters tapped and attacking. For
    each Aura and Equipment attached to Stangg, create a token that's a copy
    of it attached to Stangg Twin. Sacrifice all tokens created this way at
    the beginning of the next end step.

    -- Stangg, Echo Warrior. Hand-authored rather than parsed: (1)
    `normalize` folds the token name "Stangg Twin" -> "~ Twin" (it contains
    the card's own given name), which no `create_token` handler can read;
    (2) the attachment copies use generic `copy_permanent` and `attach`
    operands: the copy reads each attachment on the source and the attach
    node links those copies to the first token this resolution made. The
    delayed "sacrifice all tokens
    created this way" is `create_delayed_trigger`'s existing
    ``capture="created_objects"`` (Kiki-Jiki's template), which grabs the
    whole `created_objects` list -- Stangg Twin plus every attachment copy.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "token_name": "Stangg Twin",
                    "legendary": True,
                    "power": 3,
                    "toughness": 4,
                    "colors": ["R", "G"],
                    "subtypes": ["Human", "Warrior"],
                    "tapped": True,
                    "attacking": True,
                }),
                EffectSpec("seq", {"effects": [
                    {"type": "copy_permanent", "params": {
                        "target_kind": None, "referent": "attachments_each",
                    }},
                    {"type": "attach", "params": {
                        "mover": "created_after_first", "target_kind": "first_created",
                    }},
                ]}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "any",
                    "capture": "created_objects",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                    "description": "Stangg: erzeugte Tokens opfern",
                }),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Stangg, Echo Warrior", _stangg_echo_warrior)
