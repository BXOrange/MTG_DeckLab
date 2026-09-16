from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _beseech_the_mirror() -> list[AbilitySpec]:
    """Bargain
    Search your library for a card, exile it face down, then shuffle. If
    this spell was bargained, you may cast the exiled card without paying
    its mana cost if that spell's mana value is 4 or less. Put the exiled
    card into your hand if it wasn't cast this way.

    — Beseech the Mirror. **Bargain** is the optional additional cost
    "sacrifice an artifact, enchantment, or token as you cast this spell",
    now genuinely payable (`GameEngine.cast_spell(..., bargained=True)`,
    charged alongside every other additional cost) and recorded on
    `GameObject.bargained`.

    "If this spell was bargained, …" is then the existing
    `EffectSpec.condition` gate with a new ``"bargained"`` key — the exact
    shape Kicker's own ``"kicked"`` gate already had, reading a flag instead
    of a counter, so `ConditionalEffect` needed one branch rather than a new
    mechanism.

    The exile round trip is now genuinely modeled rather than collapsed to
    "tutor to hand, then cheat something into play": the search's
    ``"exile_face_down"`` destination sets `GameObject.face_down_in_exile`
    (RULE 701.20a — hidden from everyone but its owner), and
    `CastExiledFaceDownEffect` then hands out Rebound's own free-cast window
    (`RulesEngine.grant_free_cast_window_from_exile`) so the card is cast
    from exile through the ordinary action loop, with its full targeting and
    modal choices. The "put the exiled card into your hand if it wasn't cast
    this way" half is a `DelayedTrigger` at the next end step, and applies
    immediately instead when the card was never eligible to be cast (the
    spell wasn't bargained, or the card costs more than {4}).

    Note the two halves have *different* conditions, which is why this isn't
    a `ConditionalEffect` around a single cast: only the cast is gated on
    ``bargained``, while the return-to-hand always happens.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": "",
                    "destination": "exile_face_down",
                    "count": 1,
                }),
                EffectSpec(
                    "cast_exiled_face_down",
                    {"max_mana_value": 4, "require_bargained": True},
                ),
            ],
        ),
    ]


register("Beseech the Mirror", _beseech_the_mirror)
