from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    # RULE 603.3d: choose the opponent as the trigger is put on the stack.
    effects = [
        EffectSpec("choose_objects", {"player_selector": "target", "target_kind": "opponent",
            "what": "permanent", "card_types_any": ["creature", "planeswalker"], "action": "sacrifice"}),
        EffectSpec("discard", {"count": 1, "player": {"of": "target"}}),
        EffectSpec("lose_life", {"amount": 3, "player": {"of": "target"}}),
        EffectSpec("draw", {"count": 1}), EffectSpec("gain_life", {"amount": 3}),
    ]
    return [AbilitySpec("triggered", effects,
        trigger={"event": event, "condition": {"subject": "self"}})
        for event in ("ENTERS_BATTLEFIELD", "ATTACKS")]


register('Archon of Cruelty', _card)
