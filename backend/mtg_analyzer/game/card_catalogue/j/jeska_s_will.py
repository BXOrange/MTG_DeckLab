from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jeskas_will() -> list[AbilitySpec]:
    """Choose one. If you control a commander as you cast this spell, you
    may choose both instead.
    • Add {R} for each card in target opponent's hand.
    • Exile the top three cards of your library. You may play them this
    turn.

    — Imodane deck batch. Mode 1 needed a genuinely new `AddManaEffect`
    shape (``target_kind``/``amount_from_target_hand_size`` — every prior
    use of that effect was untargeted); mode 2 is `ImpulsiveDrawEffect`
    unchanged (``count=3, same_turn_only=True`` — Ragavan, Nimble
    Pilferer's own shorter "this turn" window rather than Light Up the
    Stage's "until your next turn"). **Documented simplification**:
    ``or_both`` is offered unconditionally rather than gated on "if you
    control a commander" — this app's decks are Commander decks by
    construction, so the gate is true in every real game this engine
    plays; a genuinely commander-less game would let this spell over-
    offer the combined mode.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "or_both": True,
                "options": [
                    [EffectSpec("add_mana", {
                        "color": "R", "target_kind": "opponent", "amount_from_target_hand_size": True,
                    })],
                    [EffectSpec("impulsive_draw", {"count": 3, "same_turn_only": True})],
                ],
                "descriptions": [
                    "Füge {R} für jede Karte auf der Hand eines Zielgegners hinzu.",
                    "Exiliere die obersten drei Karten deiner Bibliothek. Du "
                    "kannst sie in diesem Zug ausspielen.",
                ],
            },
        ),
    ]


register("Jeska's Will", _jeskas_will)
