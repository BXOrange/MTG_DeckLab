from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: The generic mana the defending player may pay to keep Shrouded Serpent blockable.
SERPENT_TAX = "{4}"


def _shrouded_serpent() -> list[AbilitySpec]:
    "Whenever this creature attacks, defending player may pay {4}. If that player doesn't, this creature can't be blocked this turn."
    return [
        AbilitySpec(
            "triggered",
            # RULE 118.3 / 508.1: the *defending* player is asked (``payer="defending_player"``);
            # declining runs the else branch, which marks the attacker unblockable for the
            # turn (RULE 509.1b: blockers are declared after this trigger resolves).
            # ``target_kind=None`` makes `unblockable` act on its own source.
            [EffectSpec("pay_cost_then", {
                "cost": SERPENT_TAX,
                "payer": "defending_player",
                "else_effects": [{"type": "unblockable", "params": {"target_kind": None}}],
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="whenever ~ attacks, defending player may pay {4}. if that player doesn't, ~ can't be blocked this turn.",
        ),
    ]


register("Shrouded Serpent", _shrouded_serpent)
