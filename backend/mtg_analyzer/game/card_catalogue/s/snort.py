from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "draw 5 cards" and "5 damage".
_SNORT_AMOUNT = 5


def _snort() -> list[AbilitySpec]:
    """Each player may discard their hand and draw five cards. Then Snort deals 5 damage to each opponent who discarded their hand this way.
    Flashback {4}{R}

    — PLAY-ALL (Revival Trance). Flashback is a keyword. Players choose in APNAP order (RULE 101.4).
    Accepting players discard together, then draw in that order. Damage follows every draw instruction.
    """
    return [AbilitySpec("spell_effect", [EffectSpec("snort", {})])]


register("Snort", _snort)
