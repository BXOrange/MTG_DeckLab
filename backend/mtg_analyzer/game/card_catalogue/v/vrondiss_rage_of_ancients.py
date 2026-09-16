from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vrondiss_rage_of_ancients() -> list[AbilitySpec]:
    """Enrage — Whenever Vrondiss is dealt damage, you may create a 5/4
    red and green Dragon Spirit creature token with "When this token
    deals damage, sacrifice it."
    Whenever you roll one or more dice, you may have Vrondiss deal 1
    damage to itself.

    Simplified: the created token's own "sacrifice it after it deals
    damage" downside isn't modeled (no quoted-ability-grant support for a
    created token yet — every other quoted-grant primitive in this engine
    targets an *existing* permanent, not a token being created in the same
    breath), so the token created here is strictly a 5/4 vanilla.

    The dice trigger is real now (MEC-75 — `RulesEngine.roll_die` /
    `EventType.DICE_ROLLED`): "whenever you roll one or more dice, you may
    have Vrondiss deal 1 damage to itself" is a `DICE_ROLLED` triggered
    ability, so a d20 rolled by any other permanent this player controls
    (Barbarian Class, a die-rolling Equipment) both fires it and, via the
    self-damage, re-arms the Enrage trigger above.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Dragon Spirit", "power": 5, "toughness": 4,
                "colors": ["R", "G"], "subtypes": ["Dragon", "Spirit"],
            })],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            optional=True,
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "self"})],
            trigger={"event": "DICE_ROLLED", "condition": {"subject": "you"}},
            optional=True,
        ),
    ]


register("Vrondiss, Rage of Ancients", _vrondiss_rage_of_ancients)
