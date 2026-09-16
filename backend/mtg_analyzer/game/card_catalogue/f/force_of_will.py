from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# --- cEDH lists batch: RULE 118.9 "pitch" alternative-cost family -----------
#
# Force of Will/Negation/Vigor and Daze all print "You may <cost> rather
# than pay this spell's mana cost." — RULE 118.9, an alternative *casting*
# cost the engine doesn't model yet (see `_flare_of_duplication`'s own
# precedent for this same drop). Each card below is hand-authored for its
# *resolution effect only*, fully castable at its real printed mana cost
# (all four have one) — a strict subset of the real card, not a fake one.
# **Documented simplification, all four**: the free/discounted alternative
# cost is dropped; tracked as a real open primitive (RULE 118.9) in
# BACKLOG.md rather than silently rebuilt per card.


def _force_of_will() -> list[AbilitySpec]:
    """You may pay 1 life and exile a blue card from your hand rather than
    pay this spell's mana cost.
    Counter target spell.

    RULE 118.9's own alternative cost (MEC-15, previously dropped — see
    `Done_Backend.md`'s original cEDH batch entry for why it was deferred)
    now ships as a second `spell_effect` spec carrying only `alt_cost` and
    no effects of its own — `effect_binder.attach_to_object` scans every
    spec for it regardless of which one carries the "real" effects, the
    same idiom `additional_cost`/`free_cast_condition` already use. No
    condition: this alt cost is always available, unlike Force of
    Negation/Vigor's "if it's not your turn" gate below. Still also fully
    castable at its printed {3}{U}{U}.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter", {})],
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"pay_life": 1, "exile_hand_card_color": "U"},
        ),
    ]


register("Force of Will", _force_of_will)
