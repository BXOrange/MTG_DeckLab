from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _venser_fervent_forger() -> list[AbilitySpec]:
    """Flash
    When Venser enters, choose one —
    • Copy target instant or sorcery spell an opponent controls twice. You may choose new targets for the copies.
    • Create two tokens that are copies of target permanent an opponent controls. They gain haste. At the beginning of the next
      end step, sacrifice them.

    — PLAY-ALL (Multiverse Reforged). Flash is the keyword's. Mode 1 is `copy_spell` over ``spell_you_dont_control`` with
    ``count`` 2; both copies finish their optional target choices before the batch enters the stack.
    Mode 2 is `copy_permanent` (``count`` 2, ``haste``) plus the Reflection of Kiki-Jiki delayed end-step sacrifice over the
    tokens it created (``capture="created_objects"``).
    """
    return [
        AbilitySpec(
            "triggered", [],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            modes={"choose": 1, "options": [
                [EffectSpec("copy_spell", {
                    "target_kind": "spell_you_dont_control", "card_types": ["instant", "sorcery"], "count": 2,
                })],
                [
                    EffectSpec("copy_permanent", {
                        "target_kind": "permanent_you_dont_control", "count": 2, "haste": True,
                    }),
                    EffectSpec("create_delayed_trigger", {
                        "step": "end", "scope": "any", "capture": "created_objects",
                        "effects": [{"type": "sacrifice_specific", "params": {}}],
                    }),
                ],
            ], "descriptions": [
                "Copy target instant or sorcery spell an opponent controls twice.",
                "Create two tokens that are copies of target permanent an opponent controls.",
            ]},
        ),
    ]


register("Venser, Fervent Forger", _venser_fervent_forger)
